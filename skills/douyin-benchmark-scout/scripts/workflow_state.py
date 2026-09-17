"""Shared attempt semantics and process-safe ledger transactions (stdlib only)."""
import contextlib
import functools
import hashlib
import socket
import subprocess
import threading
import urllib.error
from pathlib import Path

_locks = threading.local()
SEARCH_DEFAULTS = {'target_per_keyword': 40, 'max_scrolls': 12,
                   'stall_rounds': 3, 'max_seconds': 180,
                   'max_attempts_per_keyword': 3, 'wait_seconds': 3,
                   'require_scope_completion': True}


@contextlib.contextmanager
def ledger_lock(root):
    import fcntl
    root = Path(root).resolve()
    # Keep locks outside a not-yet-created batch, so initialize stays exclusive.
    root.parent.mkdir(parents=True, exist_ok=True)
    key = str(root)
    held = getattr(_locks, 'held', {})
    if key in held:
        yield
        return
    lock = root.parent / ('.scout-' + hashlib.sha256(key.encode()).hexdigest()[:16] + '.lock')
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        held[key] = handle
        _locks.held = held
        try:
            yield
        finally:
            held.pop(key)
            fcntl.flock(handle, fcntl.LOCK_UN)


def transaction(fn):
    @functools.wraps(fn)
    def wrapped(root, *args, **kwargs):
        with ledger_lock(root):
            return fn(root, *args, **kwargs)
    return wrapped


def latest_search(batch, keyword):
    return next((o for o in reversed(batch.get('searches', []))
                 if o.get('keyword') == keyword), None)


def search_state(batch, keyword):
    observations = [o for o in batch.get('searches', []) if o.get('keyword') == keyword]
    last = observations[-1] if observations else {}
    status = last.get('status', 'not_attempted')
    if last and last.get('query') != keyword:
        status = 'exact_query_pending'
    runs = {o.get('attempt_id') or ('legacy-' + str(n)) for n, o in enumerate(observations)}
    outcomes = {o.get('attempt_id') or ('legacy-' + str(n)):o.get('status') for n,o in enumerate(observations)}
    budgeted_runs = sum(v != 'access_restricted' for v in outcomes.values())
    reason = last.get('progress', {}).get('stop_reason', '')
    complete = status in ('results_observed', 'confirmed_empty')
    if batch.get('search_policy', {}).get('require_scope_completion') and status == 'results_observed':
        complete = reason in ('target_reached', 'content_exhausted')
    ids = {c.get('aweme_id') for o in observations for c in o.get('cards', []) if c.get('aweme_id')}
    limit = batch.get('search_policy', {}).get('max_attempts_per_keyword', 3)
    return {'keyword': keyword, 'status': status, 'attempts': len(runs),
            'observations': len(observations), 'observed_cards': len(ids) or
            max((len(o.get('cards', [])) for o in observations), default=0),
            'scope_complete': complete, 'stop_reason': reason,
            'retry_exhausted': not complete and budgeted_runs >= limit,
            'access_restricted': status == 'access_restricted'}


def pending_keywords(batch):
    return [k for k in batch['keywords'] if not search_state(batch, k)['scope_complete']]


class CaptureBudget:
    def __init__(self, policy, clock):
        self.policy = {**SEARCH_DEFAULTS, **policy}
        self.clock, self.started = clock, clock()
        self.last_count, self.stalls, self.rounds = 0, 0, 0

    def observe(self, count, explicit_end=False):
        self.stalls = 0 if count > self.last_count else self.stalls + 1
        self.last_count = max(count, self.last_count)
        self.rounds += 1
        reason = ''
        if count >= self.policy['target_per_keyword']: reason = 'target_reached'
        elif explicit_end: reason = 'content_exhausted'
        elif self.clock() - self.started >= self.policy['max_seconds']: reason = 'time_budget'
        elif self.stalls >= self.policy['stall_rounds']: reason = 'stalled'
        elif self.rounds > self.policy['max_scrolls']: reason = 'scroll_budget'
        return {'stop_reason': reason, 'observed_count': count,
                'target_count': self.policy['target_per_keyword'],
                'scrolls': self.rounds - 1, 'no_growth_rounds': self.stalls,
                'elapsed_seconds': round(self.clock() - self.started, 2)}


def failure(exc, stage):
    code = getattr(exc, 'code', None)
    if isinstance(exc, urllib.error.HTTPError):
        code = 'access_restricted' if exc.code in (401, 403, 429) else 'source_expired' if exc.code in (404, 410) else 'network_failed'
    elif isinstance(exc, (TimeoutError, socket.timeout, subprocess.TimeoutExpired)):
        code = 'timeout'
    elif isinstance(exc, urllib.error.URLError): code = 'network_failed'
    elif isinstance(exc, FileNotFoundError): code = 'environment_missing'
    code = code if isinstance(code, str) else 'processing_failed'
    category = ('access' if code == 'access_restricted' else
                'environment' if code in ('downloader_unavailable', 'local_file_missing', 'model_missing', 'project_not_installed', 'environment_missing') else
                'source' if code in ('source_expired', 'identity_mismatch', 'unsupported_url', 'duration_missing') else
                'material' if code in ('media_invalid', 'duration_mismatch', 'transcript_invalid', 'transcript_incomplete', 'artifact_changed') else
                'transient' if code in ('network_failed', 'timeout', 'transcription_failed', 'worker_failed', 'empty_response') or code.startswith('http_5') else 'upstream')
    action = {'access': '核对登录或验证码恢复后接续同一任务',
              'environment': '修复本地路径或运行环境后重试',
              'source': '重新核实同一作品的来源', 'material': '核查原视频、缺失片段或画面文字',
              'transient': '退避后仅重试失败步骤', 'upstream': '检查返回结构，保留原失败'}[category]
    return {'code': code, 'stage': stage, 'category': category,
            'retryable': category == 'transient', 'next_action': action,
            'message': str(exc)[:600]}
