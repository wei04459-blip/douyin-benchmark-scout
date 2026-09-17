#!/usr/bin/env python3
"""Resumable material preparation. Never grants research/review completion."""
import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from research_batch import acquire, now, read, save
from verify_evidence import check_media, digest, duration_error, ffmpeg_path, probe_duration, transcript_problem
from workflow_state import failure
from transcription_worker import TranscriptionWorker

HERE = Path(__file__).resolve().parent
UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1'


class MaterialError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parse_public_page(html, aid):
    """Only read publisher-provided data. Never execute challenge scripts."""
    if 'byted_acrawler.sign' in html or re.search(r'<title>[^<]*(验证码|验证|验证中心)', html):
        raise MaterialError('access_restricted', '公开页面返回访问校验；停止此通道')
    match = re.search(r'window\._ROUTER_DATA\s*=\s*(.*?)</script>', html, re.S)
    if not match:
        raise MaterialError('metadata_unavailable', '页面未提供可解析的作品数据')
    try:
        data = json.loads(match[1].strip().rstrip(';'))
        routes = data.get('loaderData', {})
        candidates = []
        for route in routes.values():
            if isinstance(route, dict):
                candidates.extend((route.get('videoInfoRes') or {}).get('item_list', []))
        item = next((i for i in candidates if str(i.get('aweme_id')) == aid), None)
        if not item:
            raise MaterialError('metadata_unavailable', '页面只有外壳或作品 ID 不匹配；未获得视频材料')
        video = item.get('video') or {}
        urls = (video.get('play_addr') or {}).get('url_list') or []
        duration = float(video.get('duration', 0)) / 1000
        if not urls or duration <= 0:
            raise MaterialError('metadata_incomplete', '作品缺少公开媒体地址或来源时长')
        return {'aweme_id': aid, 'title': item.get('desc', ''),
                'nickname': (item.get('author') or {}).get('nickname'),
                'source_duration_seconds': duration,
                'source_duration_evidence': '公开分享页 video.duration（毫秒）',
                'video_download_url': urls[0], 'metrics': item.get('statistics'),
                'create_time': item.get('create_time'), 'observed_at': now()}
    except (TypeError, KeyError, ValueError) as exc:
        raise MaterialError('metadata_invalid', '公开数据结构无法验证') from exc


def resolve_public(url, evidence_path):
    parsed = urlparse(url)
    match = re.fullmatch(r'/(?:share/)?video/(\d{10,25})/?', parsed.path)
    if parsed.scheme != 'https' or parsed.hostname not in {'www.douyin.com', 'www.iesdouyin.com', 'jingxuan.douyin.com'} or not match:
        raise MaterialError('unsupported_url', '需要完整公开作品链接；短分享链接请先取得完整作品链接')
    aid = match[1]
    request_url = 'https://www.iesdouyin.com/share/video/' + aid
    try:
        req = urllib.request.Request(request_url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise MaterialError('page_too_large', '公开页面超过读取上限')
    except urllib.error.HTTPError as exc:
        code = 'access_restricted' if exc.code in (401, 403, 429) else 'network_failed'
        raise MaterialError(code, '公开页面 HTTP ' + str(exc.code)) from exc
    evidence_path.write_bytes(raw)
    return parse_public_page(raw.decode('utf-8', errors='replace'), aid)


@contextlib.contextmanager
def locked(root):
    """OS lock releases on process death; stale files never block resumption."""
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.queue.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MaterialError('already_running', '该队列正在处理，不能重复启动')
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def enqueue(root, source):
    if not any(source.get(k) for k in ('local_video', 'url', 'video_download_url')):
        raise ValueError('缺少本地视频或公开作品链接')
    if source.get('local_video'):
        source = dict(source, local_video=str(Path(source['local_video']).expanduser().resolve()))
    with locked(root):
        path = root / '材料队列.json'
        queue = read(path) if path.exists() else {'schema_version': 1, 'jobs': []}
        key = json.dumps(source, sort_keys=True, ensure_ascii=False)
        for job in queue['jobs']:
            if (source.get('aweme_id') and source.get('aweme_id') == job['source'].get('aweme_id')) or json.dumps(job['source'], sort_keys=True, ensure_ascii=False) == key:
                return job
        job = {'job_id': str(len(queue['jobs']) + 1).zfill(4), 'source': source,
               'status': 'queued', 'created_at': now(), 'attempts': [], 'artifacts': {}}
        queue['jobs'].append(job)
        save(path, queue)
        return job


def verify_prepared(job, model_sha=None):
    a = job.get('artifacts', {})
    video = Path(a.get('video_path', ''))
    transcript = Path(a.get('transcript_path', ''))
    if not video.is_file() or digest(video) != a.get('media_sha256'):
        return False
    origin = job.get('source', {}).get('local_video')
    if origin and (not Path(origin).is_file() or digest(Path(origin)) != a.get('media_sha256')):
        return False
    if not transcript.is_file() or digest(transcript) != a.get('transcript_sha256'):
        return False
    metadata = transcript.with_suffix('.json')
    if not metadata.is_file() or digest(metadata) != a.get('transcript_metadata_sha256'):
        return False
    try:
        t = read(metadata)
        if model_sha and t.get('model_sha256') and t['model_sha256'] != model_sha:return False
        return (t.get('media_sha256') == a['media_sha256'] and
                transcript_problem(transcript.read_text(),t,a.get('media_duration_seconds')) is None)
    except (ValueError,TypeError,OSError):return False


def prepare(root, python, model, retry_failed=False, access_restored=False, worker_factory=None, online_restricted=False):
    factory=worker_factory or TranscriptionWorker
    with locked(root), factory(python,model,root/"转录运行日志.txt") as worker:
        path = root / '材料队列.json'
        queue = read(path)
        restricted=online_restricted or (not access_restored and any(j['status']=='access_restricted' for j in queue['jobs']))
        model_sha=digest(Path(model)) if Path(model).is_file() else None
        for job in queue['jobs']:
            if job['status'] == 'pending_review' and verify_prepared(job,model_sha):
                continue
            if job['status'] == 'pending_review':
                job['status'] = 'failed'
                job['error'] = {'code':'artifact_changed','message':'已准备材料被修改或缺失，需重新验收'}
                save(path,queue)
            if job['status'] == 'access_restricted':
                if not access_restored:
                    restricted=True
                    continue
                job.setdefault('access_recoveries',[]).append({'at':now(),'reason':'调用方已核对访问恢复'})
                job['status']='queued'
            cached = Path(job.get('artifacts',{}).get('video_path',''))
            cached_valid = cached.is_file() and digest(cached)==job.get('artifacts',{}).get('media_sha256')
            if restricted and not job['source'].get('local_video') and not cached_valid:
                continue
            if job['status']=='preparing':
                for prior in job['attempts']:
                    if not prior.get('finished_at'):prior.update(outcome='interrupted',finished_at=now())
                job['status']='queued'
                save(path,queue)
            if job['status'] == 'failed' and not retry_failed and not job.get('error',{}).get('retryable'):
                continue
            if sum(a.get('outcome') not in ('access_restricted','interrupted') for a in job['attempts']) >= 3:
                continue
            attempt = {'started_at': now(), 'number': len(job['attempts']) + 1}
            job['attempts'].append(attempt)
            job['status'] = 'preparing'
            save(path, queue)
            folder = root / job['job_id'] / ('v' + str(attempt['number']))
            stage='download'
            try:
                folder.mkdir(parents=True, exist_ok=False)
                source = dict(job['source'])
                media = folder / '原视频.mp4'
                previous = job.get('artifacts',{})
                reusable = Path(previous.get('video_path',''))
                reuse = reusable.is_file() and digest(reusable)==previous.get('media_sha256')
                if reuse and source.get('local_video'):
                    origin=Path(source['local_video'])
                    reuse=origin.is_file() and digest(origin)==previous['media_sha256']
                if reuse:
                    media=reusable
                    source=read(reusable.parent/'来源.json')
                elif source.get('local_video'):
                    original = Path(source['local_video'])
                    if not original.is_file():
                        raise MaterialError('local_file_missing', '本地视频不存在')
                    if original.stat().st_size > 250 * 1024 * 1024:
                        raise MaterialError('file_too_large', '本地视频超过 250MB 上限')
                    shutil.copy2(original, media)
                else:
                    if not source.get('video_download_url'):
                        aid = re.search(r'/video/(\d{10,25})(?:[/?#]|$)',source.get('url',''))
                        if not aid:
                            raise MaterialError('unsupported_url','需要完整作品链接，不能从相似标题推断作品 ID')
                        project = Path(source.get('downloader_project', Path.home()/'Douyin_TikTok_Download_API'))
                        runtime = Path(source.get('downloader_python', project/'.venv311/bin/python'))
                        if not runtime.is_file():
                            raise MaterialError('downloader_unavailable','已装开源下载项目的运行环境不可用')
                        result = subprocess.run([str(runtime),str(HERE/'installed_downloader.py'),
                            '--project',str(project),'--id',aid[1],'--output',str(folder/'接口来源.json')],
                            capture_output=True,text=True,timeout=40)
                        (folder/'解析结果.txt').write_text(result.stdout)
                        if result.returncode:
                            try: provider_failure=json.loads(result.stdout.strip().splitlines()[-1])
                            except (ValueError,IndexError): provider_failure={}
                            raise MaterialError(provider_failure.get('code','resolver_failed'),'已装下载项目未返回可验证作品，详见解析结果')
                        source.update(read(folder/'接口来源.json'))
                    if not source.get('source_duration_seconds'):
                        raise MaterialError('duration_missing', '下载入口缺少来源时长，不能验收完整性')
                    acquire(source['video_download_url'], media, source['source_duration_seconds'])
                error, sha = check_media(media, ffmpeg_path())
                if error:
                    raise MaterialError('media_invalid', error)
                duration = probe_duration(media, ffmpeg_path())
                if source.get('source_duration_seconds') is not None:
                    error = duration_error(source['source_duration_seconds'], duration)
                    if error:
                        raise MaterialError('duration_mismatch', error)
                save(folder / '来源.json', source)
                job['artifacts'] = {'video_path': str(media.resolve()), 'media_sha256': sha,
                                    'media_duration_seconds': duration}
                save(path, queue)
                stage='transcribe'
                job['stage']=stage
                save(path,queue)
                print(json.dumps({'job': job['job_id'], 'stage': 'transcribing', 'duration': duration}), flush=True)
                result=worker.transcribe(media,folder/'转录',root/job['job_id']/'片段缓存')
                if result.get('incomplete_chunks'):
                    job['partial_transcript_path']=result.get('transcript')
                    raise MaterialError('transcript_incomplete','部分片段为空或失败；保留已识别片段，重试或核对画面文字')
                transcript = folder / '转录/transcript.txt'
                t = read(transcript.with_suffix('.json'))
                if transcript_problem(transcript.read_text(),t,duration) or t.get('media_sha256') != sha:
                    raise MaterialError('transcript_invalid', '转录为空、无分段或视频指纹不匹配')
                job['artifacts'].update(transcript_path=str(transcript.resolve()),
                    transcript_sha256=digest(transcript), transcript_metadata_sha256=digest(transcript.with_suffix('.json')))
                job['status'] = 'pending_review'
                job['quality_flags'] = t.get('quality_flags',[])
                job['review_required'] = ['核对作品身份与来源时长', '全文初读与关键画面核对，必要处校词', '引用证据与内容分析']
                job['source_metadata'] = {k: v for k, v in source.items() if k != 'video_download_url'}
                job.pop('error', None)
                job['stage']='text_ready'
                job.pop('next_action',None)
                job.pop('partial_transcript_path',None)
                attempt['outcome'] = 'pending_review'
            except Exception as exc:
                info=failure(exc,stage)
                job['status'] = 'access_restricted' if info['category']=='access' else 'failed'
                if job['status']=='access_restricted':restricted=True
                job['error'] = info
                job['next_action']=info['next_action']
                attempt['outcome'] = job['status']
                attempt['error'] = job['error']
            attempt['finished_at'] = now()
            save(path, queue)
        return queue


def main():
    p = argparse.ArgumentParser(description='材料准备队列：可恢复，不自动标记研究完成')
    p.add_argument('--root', required=True, type=Path)
    sub = p.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add'); add.add_argument('--source', required=True, type=Path)
    run = sub.add_parser('prepare'); run.add_argument('--python', default=sys.executable)
    run.add_argument('--model', required=True, type=Path); run.add_argument('--retry-failed', action='store_true'); run.add_argument('--access-restored',action='store_true')
    sub.add_parser('status')
    a = p.parse_args(); root = a.root.resolve()
    if a.command == 'add': result = enqueue(root, read(a.source))
    elif a.command == 'prepare': result = prepare(root, a.python, a.model, a.retry_failed, a.access_restored)
    else: result = read(root / '材料队列.json')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if a.command == 'prepare' and any(j['status'] != 'pending_review' for j in result['jobs']):
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
