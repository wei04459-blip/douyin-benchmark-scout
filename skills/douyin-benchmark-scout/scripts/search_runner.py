"""Incremental, browser-independent collection runner. Readers provide real observations."""
import hashlib
import re
import time
import uuid
from pathlib import Path
from research_batch import read, save, record_search, classify_observation, now
from workflow_state import CaptureBudget, SEARCH_DEFAULTS, transaction, search_state, failure


def source_path(root, keyword):
    name = re.sub(r'[^\w\u4e00-\u9fff-]', '_', keyword)[:60]
    return Path(root)/'搜索来源'/(name+'_'+hashlib.sha256(keyword.encode()).hexdigest()[:8]+'.json')


def known_items(root, keyword):
    found = {}
    for path in sorted((Path(root)/'搜索来源').glob('*.json')):
        for item in read(path).get('items', []):
            if item.get('keyword') == keyword:
                found[item['aweme_id']] = item
    return found


@transaction
def persist(root, observation, items):
    classify_observation(observation)
    cards = {c.get('aweme_id'): c for c in observation.get('cards', [])}
    for item in items:
        card = cards.get(item.get('aweme_id'))
        if not card or card.get('title') != item.get('title') or item.get('keyword') != observation['keyword']:
            raise ValueError('来源作品必须与本次已核实卡片及关键词一致')
    merged = known_items(root, observation['keyword'])
    merged.update({i['aweme_id']: i for i in items})
    # Persist source first. A crash before the observation leaves a pending scope,
    # never a successful observation whose sources have not reached disk.
    save(source_path(root, observation['keyword']), {'items': list(merged.values()),
         'query': observation['keyword'], 'observed_at': observation['observed_at']})
    return record_search(root, observation)


def run_keyword(root, keyword, reader, policy=None, clock=time.monotonic, wait=time.sleep):
    """reader(round) returns (observation, source_items); round 0 navigates once."""
    batch = read(Path(root)/'batch.json')
    policy = {**SEARCH_DEFAULTS, **batch.get('search_policy', {}), **(policy or {})}
    state = search_state(batch, keyword)
    if state['retry_exhausted']:
        return {**state, 'stop_reason': 'attempt_budget'}
    attempt_id = uuid.uuid4().hex
    budget = CaptureBudget(policy, clock)
    known = known_items(root, keyword)
    last = None
    while True:
        try:
            observation, items = reader(budget.rounds)
            observation = {**observation, 'keyword': keyword, 'attempt_id': attempt_id}
            classify_observation(observation)
            # Failed / unverified observations are never progress or empty evidence.
            status = classify_observation(observation)
            if status not in ('results_observed', 'confirmed_empty'):
                observation['progress'] = {'stop_reason': status}
                last = persist(root, observation, [])
                break
            before=len(known)
            known.update({i['aweme_id']: i for i in items})
            end_proven = (observation.get('explicit_end') is True and
                          observation.get('end_scope') == 'search_results' and
                          bool(observation.get('end_evidence')) and
                          observation['end_evidence'] in observation.get('evidence_text',''))
            progress = budget.observe(len(known), end_proven or status == 'confirmed_empty')
            if status == 'confirmed_empty' and known:
                # A new explicit empty page must not erase earlier captured records.
                progress['stop_reason'] = 'empty_after_progress'
                observation['error']='inconsistent_empty_page'
                observation.pop('empty_marker',None)
            observation['progress'] = progress
            last = persist(root, observation, items)
            print(__import__('json').dumps({'keyword': keyword, 'new_cards': len(known)-before, **progress}, ensure_ascii=False), flush=True)
            if progress['stop_reason']:
                break
            wait(policy['wait_seconds'])
        except Exception as exc:
            info = failure(exc, 'search')
            restricted = info['category'] == 'access' or 'access_restricted' in str(exc)
            last = record_search(root, {'keyword': keyword, 'query': keyword,
                'observed_at': now(), 'channel': 'configured_browser_adapter',
                'page_url': 'https://www.douyin.com/', 'page_loaded': False,
                'query_confirmed': False, 'cards': [], 'attempt_id': attempt_id,
                'evidence_text': '本次访问受限，已保存前序进度' if restricted else '本次页面提取失败，已有作品保留',
                'restriction': '访问验证' if restricted else None,
                'error': None if restricted else info['code'], 'failure': info,
                'progress': {'stop_reason': 'access_restricted' if restricted else 'retrieval_failed',
                             'observed_count': len(known)}})
            break
    return search_state(read(Path(root)/'batch.json'), keyword)
