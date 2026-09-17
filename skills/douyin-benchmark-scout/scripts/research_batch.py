#!/usr/bin/env python3
"""Browser-independent evidence ledger. Computer Use observations are imported, never simulated."""
import argparse
import copy
import json
import re
import os
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote
from verify_evidence import digest, check_media, ffmpeg_path, probe_duration, duration_error, audit, transcript_problem
from workflow_state import transaction, search_state


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def initialize(root, keywords, question):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    batch = {'schema_version': 2, 'created_at': now(), 'question': question,
             'keywords': list(dict.fromkeys(keywords)), 'searches': [], 'items': [],
             'research_status': 'in_progress', 'export_status': 'not_exported'}
    save(root/'batch.json', batch)
    return batch


def valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'\d{10,25}', value))


def classify_observation(o):
    """No results is unknown unless the exact loaded page explicitly says empty."""
    required = ('keyword', 'query', 'observed_at', 'channel', 'page_url', 'evidence_text')
    if any(not isinstance(o.get(k), str) or not o[k].strip() for k in required):
        raise ValueError('搜索观察缺少关键词、查询、时间、通道、页面或原文证据')
    if o.get('restriction'):
        return 'access_restricted'
    if o.get('error'):
        return 'retrieval_failed'
    if o.get('page_loaded') is not True or o.get('query_confirmed') is not True:
        return 'retrieval_unverified'
    # An exact-query empty conclusion cannot be borrowed from a synonym search.
    cards = o.get('cards', [])
    if not isinstance(cards, list):
        raise ValueError('cards 必须为列表')
    for c in cards:
        if not isinstance(c, dict) or not c.get('title') or c['title'] not in o['evidence_text']:
            raise ValueError('卡片标题缺少原始观察支持')
        aid = c.get('aweme_id')
        if aid is not None and (not valid_id(aid) or aid not in o['evidence_text']):
            raise ValueError('作品 ID 尚未从页面核实；未知时留空')
    if cards:
        return 'results_observed'
    marker = o.get('empty_marker')
    if o['query'] == o['keyword'] and isinstance(marker, str) and marker.strip() and marker in o['evidence_text']:
        return 'confirmed_empty'
    return 'retrieval_unverified'


@transaction
def record_search(root, observation):
    root = Path(root)
    b = read(root/'batch.json')
    o = copy.deepcopy(observation)
    if o.get('keyword') not in b['keywords']:
        raise ValueError('关键词不属于本轮研究范围')
    o['status'] = classify_observation(o)
    # Store every attempt; no later retry erases a channel failure.
    o['recorded_at'] = now()
    o['observation_id'] = len(b['searches']) + 1
    b['searches'].append(o)
    b['export_status'] = 'stale' if b.get('workbook') else 'not_exported'
    b['research_status'] = 'in_progress'
    save(root/'batch.json', b)
    return o


def search_summary(b):
    return [search_state(b, keyword) for keyword in b['keywords']]


def select_item(root, item):
    root = Path(root)
    b = read(root/'batch.json')
    i = copy.deepcopy(item)
    aid = i.get('aweme_id')
    if not valid_id(aid) or aid not in str(i.get('url', '')):
        raise ValueError('需要对应作品 ID 的公开链接')
    if not i.get('selection_reason') or not i.get('identity_evidence'):
        raise ValueError('入选需要研究理由和身份观察；不根据文件名判断')
    if any(x['aweme_id'] == aid for x in b['items']):
        raise ValueError('作品已入选，不能覆盖原有材料')
    i['research_status'] = 'pending_materials'
    b['items'].append(i)
    b['export_status'] = 'stale' if b.get('workbook') else 'not_exported'
    b['research_status'] = 'in_progress'
    save(root/'batch.json', b)
    return i


def acquire(url, target, source_duration=None, opener=urllib.request.urlopen):
    """Fresh download is promoted only after transfer, decoding and duration checks."""
    target = Path(target)
    if target.exists() or target.with_suffix('.part').exists():
        raise ValueError('目标已存在，使用新的材料版本目录')
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('需要已取得的公开 HTTPS 媒体链接')
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix('.part')
    start = time.monotonic()
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.douyin.com/'})
    try:
        with opener(req, timeout=30) as response, partial.open('xb') as out:
            content_type = response.headers.get('Content-Type', '').lower()
            if content_type and not any(t in content_type for t in ('video/', 'octet-stream')):
                raise ValueError('下载返回的内容类型不是视频')
            expected = response.headers.get('Content-Length')
            received = 0
            while True:
                block = response.read(1024*1024)
                if not block:
                    break
                received += len(block)
                if received > 250*1024*1024 or time.monotonic()-start > 180:
                    raise ValueError('下载超过本轮容量或时间上限')
                out.write(block)
            if not received or (expected is not None and int(expected) != received):
                raise ValueError('下载字节数与服务器声明不一致')
            out.flush()
            os.fsync(out.fileno())
        error, sha = check_media(partial, ffmpeg_path())
        if error:
            raise ValueError(error)
        duration = probe_duration(partial, ffmpeg_path())
        if source_duration is not None:
            error = duration_error(source_duration, duration)
            if error:
                raise ValueError(error)
        partial.rename(target)
        return {'video_path': str(target.resolve()), 'media_sha256': sha,
                'media_duration_seconds': duration, 'download_bytes': received,
                'downloaded_at': now(), 'media_decode': 'full_audio_video',
                'source_host': parsed.hostname}
    finally:
        partial.unlink(missing_ok=True)


def adopt_materials(root, aid, video, transcript):
    """Bind current media to its ASR provenance; preserve unreviewed status."""
    root = Path(root)
    b = read(root/'batch.json')
    i = next(x for x in b['items'] if x['aweme_id'] == aid)
    video, transcript = Path(video).resolve(), Path(transcript).resolve()
    error, sha = check_media(video, ffmpeg_path())
    if error:
        raise ValueError(error)
    duration = probe_duration(video, ffmpeg_path())
    if i.get('source_duration_seconds') is not None:
        error = duration_error(i['source_duration_seconds'], duration)
        if error:
            raise ValueError(error)
    t = read(transcript.with_suffix('.json'))
    if t.get('media_sha256') != sha:
        raise ValueError('转录没有绑定这份视频，不能复用旧文本')
    if transcript_problem(transcript.read_text(encoding='utf-8'),t,duration):
        raise ValueError('转录为空或没有分段')
    end = max(float(x['end']) for x in t['segments'])
    i.update(video_path=str(video), transcript_path=str(transcript), media_sha256=sha,
             media_duration_seconds=duration, duration_seconds=duration, transcript_end_seconds=end,
             research_status='pending_content_review')
    i['coverage_warning'] = '转录末尾距离片尾较远，需要核对无声画面或遗漏' if duration and duration-end > max(3, duration*.05) else None
    b['export_status'] = 'stale' if b.get('workbook') else 'not_exported'
    b['research_status'] = 'in_progress'
    save(root/'batch.json', b)
    return i


def scope_errors(b):
    """Enforce user-defined batch size and keyword quotas before completion."""
    errors = []
    items = b['items']
    ids = [i.get('aweme_id') for i in items]
    if len(ids) != len(set(ids)):
        errors.append('入选作品 ID 重复，不能重复计算配额')
    target = b.get('target_count')
    if target is not None:
        if type(target) is not int or target < 1:
            errors.append('target_count 必须为正整数')
        elif len(set(ids)) != target:
            errors.append(f'入选作品数量不符：目标 {target} 条，实际 {len(set(ids))} 条')
    quota = b.get('target_per_keyword')
    if quota is not None:
        if type(quota) is not int or quota < 1:
            errors.append('target_per_keyword 必须为正整数')
        else:
            for keyword in b['keywords']:
                count = len({i.get('aweme_id') for i in items if i.get('keyword') == keyword})
                if count != quota:
                    errors.append(f'关键词 {keyword} 配额不符：目标 {quota} 条，实际 {count} 条')
            if any(i.get('keyword') not in b['keywords'] for i in items):
                errors.append('入选作品缺少本轮原关键词归属')
    excluded = set(b.get('excluded_aweme_ids', []))
    if excluded.intersection(ids):
        errors.append('新样本包含历史排除作品，不能作为未处理作品交付')
    return errors


def evaluate(root, analysis=None):
    root = Path(root)
    b = read(root/'batch.json')
    searches = search_summary(b)
    save(root/'待分析数据.json', {'schema_version': 2, 'items': b['items'], 'keywords': b['keywords']})
    report = audit(root/'待分析数据.json', analysis)
    report['searches'] = searches
    report['search_complete'] = all(x['scope_complete'] for x in searches)
    # Checking source identity/duration is required for new batches, unlike historical diagnostics.
    source_ready = all(i.get('identity_evidence') and i.get('source_duration_seconds') and i.get('source_duration_evidence') for i in b['items'])
    report['scope_errors'] = scope_errors(b)
    report['errors'].extend(report['scope_errors'])
    report['scope_complete'] = not report['scope_errors']
    report['ready'] = report['ready'] and report['search_complete'] and source_ready and report['scope_complete']
    if not source_ready:
        report['errors'].append('新批次缺少作品身份或独立来源时长证据')
    save(root/'验收报告.json', report)
    return report



def commit_export(root, analysis, workbook, receipt):
    root, analysis, workbook = Path(root), Path(analysis), Path(workbook)
    proof = read(receipt)
    expected = {'batch_sha256': digest(root/'batch.json'), 'analysis_sha256': digest(analysis),
                'workbook_sha256': digest(workbook)}
    if any(proof.get(k) != v for k,v in expected.items()) or proof.get('reopened') is not True:
        raise ValueError('导出回执不匹配，材料可能已经变化')
    b = read(root/'batch.json')
    if sorted(proof.get('ids', [])) != sorted(i['aweme_id'] for i in b['items']):
        raise ValueError('重新打开的作品列表与入选列表不一致')
    report = evaluate(root, analysis)
    if not report['ready']:
        raise ValueError('出表后材料验收未通过，不提交完成状态')
    for i in b['items']:
        i['research_status'] = 'evidence_reviewed'
    b.update(research_status='evidence_reviewed', export_status='saved_and_reopened',
             workbook=str(workbook.resolve()), workbook_sha256=expected['workbook_sha256'],
             finalized_at=now(), media_retention='retained')
    save(root/'batch.json', b)
    return b


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a=sub.add_parser('init');a.add_argument('--root',required=True,type=Path);a.add_argument('--keywords',required=True);a.add_argument('--question',required=True)
    a=sub.add_parser('search');a.add_argument('--root',required=True,type=Path);a.add_argument('--observation',required=True,type=Path)
    a=sub.add_parser('select');a.add_argument('--root',required=True,type=Path);a.add_argument('--item',required=True,type=Path)
    a=sub.add_parser('download');a.add_argument('--source',required=True,type=Path);a.add_argument('--target',required=True,type=Path)
    a=sub.add_parser('adopt');a.add_argument('--root',required=True,type=Path);a.add_argument('--id',required=True);a.add_argument('--video',required=True,type=Path);a.add_argument('--transcript',required=True,type=Path)
    a=sub.add_parser('verify');a.add_argument('--root',required=True,type=Path);a.add_argument('--analysis',type=Path)
    a=sub.add_parser('commit');a.add_argument('--root',required=True,type=Path);a.add_argument('--analysis',required=True,type=Path);a.add_argument('--workbook',required=True,type=Path);a.add_argument('--receipt',required=True,type=Path)
    a=sub.add_parser('status');a.add_argument('--root',required=True,type=Path)
    a=p.parse_args()
    if a.command=='init': r=initialize(a.root,a.keywords.split(','),a.question)
    elif a.command=='search': r=record_search(a.root,read(a.observation))
    elif a.command=='select': r=select_item(a.root,read(a.item))
    elif a.command=='download':
        source=read(a.source);r=acquire(source['video_download_url'],a.target,source.get('source_duration_seconds'));save(a.target.with_suffix('.provenance.json'),r)
    elif a.command=='adopt': r=adopt_materials(a.root,a.id,a.video,a.transcript)
    elif a.command=='commit': r=commit_export(a.root,a.analysis,a.workbook,a.receipt)
    elif a.command=='verify':
        r=evaluate(a.root,a.analysis);print(json.dumps({'ready':r['ready'],'summary':r.get('summary'),'searches':r['searches']},ensure_ascii=False));return 0 if r['ready'] else 2
    else:
        b=read(a.root/'batch.json');r={'searches':search_summary(b),'items':[{'id':x['aweme_id'],'status':x['research_status']} for x in b['items']]}
    # Do not dump signed download URLs, raw pages or transcript bodies into routine output.
    print(json.dumps({'command':a.command,'status':r.get('status') if isinstance(r,dict) else None,'saved':True},ensure_ascii=False))
    if a.command=='status': print(json.dumps(r,ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
