#!/usr/bin/env python3
"""Read-only evidence validation. Never updates run state or deletes source media."""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ('track', 'type', 'topic_summary', 'hook', 'structure', 'emotion', 'summary', 'viral', 'migration')
GROUNDED_FIELDS = ('hook', 'structure', 'emotion', 'summary', 'viral', 'migration')


def transcript_problem(text, metadata, duration=None):
    """Validate a text artifact, including new chunk completeness metadata."""
    if not isinstance(text, str) or not text.strip(): return '转录正文为空'
    if not isinstance(metadata, dict): return '转录元数据格式错误'
    if metadata.get('incomplete_chunks') or metadata.get('status') == 'machine_partial_unreviewed':
        return '转录仍有未完成片段'
    if 'chunks' in metadata and (not isinstance(metadata['chunks'], list) or not metadata['chunks'] or any(not isinstance(c, dict) or c.get('status') != 'ok' for c in metadata['chunks'])):
        return '转录片段尚未全部验收'
    segments = metadata.get('segments')
    if not isinstance(segments, list) or not segments: return '转录缺少分段'
    for s in segments:
        if not isinstance(s, dict):return '转录分段格式错误'
        start, end = s.get('start'), s.get('end')
        if (not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end))
            or not 0 <= start < end or (duration and end > duration+1)):
            return '转录分段时间无效'
        if not isinstance(s.get('text'), str) or not s['text'].strip():return '转录分段正文为空'
    if normalized(text) != normalized(''.join(s['text'] for s in segments)):
        return '正文与分段内容不一致'
    return None


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def normalized(text):
    return re.sub(r'\s+', '', str(text or ''))


def file_path(value, base):
    if not isinstance(value, str) or not value.strip():
        return None
    p = Path(value).expanduser()
    return p if p.is_absolute() else base / p


def read_object(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('JSON 根节点必须为对象')
    return data


def ffmpeg_path():
    candidates = [os.environ.get('FFMPEG_PATH'), shutil.which('ffmpeg'), str(Path.home()/'.local/bin/ffmpeg')]
    return next((x for x in candidates if x and Path(x).is_file()), None)


def check_media(path, ffmpeg):
    # Decode both streams to the end; fail if FFmpeg reports a damaged packet.
    if not ffmpeg:
        return '缺少 FFmpeg，无法验证媒体', None
    try:
        before = digest(path)
        result = subprocess.run(
            [ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-threads', '1', '-i', str(path),
             '-map', '0:v:0', '-map', '0:a:0', '-threads', '1', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode or result.stderr.strip():
            return '媒体无法完整解码：' + result.stderr.strip()[:300], None
        if digest(path) != before:
            return '媒体在验证期间改变', None
        return None, before
    except (OSError, subprocess.TimeoutExpired) as e:
        return '媒体检查失败：' + str(e), None



def probe_duration(path, ffmpeg):
    """Read container duration; full decoding remains a separate required check."""
    if not ffmpeg:
        return None
    try:
        r = subprocess.run([ffmpeg, '-nostdin', '-hide_banner', '-i', str(path)],
                           capture_output=True, text=True, timeout=30)
        m = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', r.stderr)
        return sum(float(x)*factor for x, factor in zip(m.groups(), (3600, 60, 1))) if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def duration_error(expected, actual):
    if not isinstance(expected, (int, float)) or isinstance(expected, bool) or not math.isfinite(expected) or expected <= 0:
        return '来源时长无效'
    if actual is None or abs(expected-actual) > max(2, expected*.02):
        return '来源时长与本地视频不一致，需核对是否下载完整或作品错配'
    return None


def audit(manifest_path, analysis_path=None, decode=True):
    manifest_path = Path(manifest_path).resolve()
    report = {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'manifest': str(manifest_path), 'ready': False, 'errors': [], 'items': []}
    try:
        manifest = read_object(manifest_path)
        items = manifest.get('items')
        if not isinstance(items, list) or not items:
            raise ValueError('批次为空或 items 无效')
        payload = read_object(Path(analysis_path)) if analysis_path else {}
        analyses = payload.get('items', payload)
        if not isinstance(analyses, dict):
            raise ValueError('分析 items 无效')
    except (OSError, ValueError) as e:
        report['errors'].append(str(e))
        return report
    ids = set()
    ffmpeg = ffmpeg_path()
    for item in items:
        result = {'id': '', 'ready': False, 'errors': [], 'warnings': []}
        report['items'].append(result)
        errors = result['errors']
        if not isinstance(item, dict):
            errors.append('条目不是对象')
            continue
        aid = str(item.get('aweme_id') or '')
        result['id'] = aid
        if not re.fullmatch(r'\d+', aid) or aid in ids:
            errors.append('作品 ID 缺失、无效或重复')
        ids.add(aid)
        video = file_path(item.get('video_path'), manifest_path.parent)
        transcript = file_path(item.get('transcript_path'), manifest_path.parent)
        text = ''
        if not video or not video.is_file():
            errors.append('缺少原视频，无法追溯核验；不能推断历史下载失败')
        elif not decode:
            errors.append('本次未解码媒体，仅做诊断，不能通过完成验收')
        else:
            error, sha = check_media(video, ffmpeg)
            if error:
                errors.append(error)
            else:
                result['media_sha256'] = sha
                result['media_decode'] = 'full_audio_video'
                if 'source_duration_seconds' in item:
                    result['media_duration_seconds'] = probe_duration(video, ffmpeg)
                    mismatch = duration_error(item['source_duration_seconds'], result['media_duration_seconds'])
                    if mismatch:
                        errors.append(mismatch)
                    if not item.get('source_duration_evidence'):
                        errors.append('来源时长缺少页面或接口观察记录')
                else:
                    result['warnings'].append('缺少独立来源时长，完整解码不证明取得了整条原作')
        if not transcript or not transcript.is_file():
            errors.append('缺少转录文件')
        else:
            try:
                text = transcript.read_text(encoding='utf-8').strip()
                result['transcript_sha256'] = digest(transcript)
                result['transcript_characters'] = len(normalized(text))
                if not text:
                    errors.append('转录为空')
                elif re.fullmatch(r'(字幕\s*(by|：|:).*|感谢观看[。！!]?|谢谢观看[。！!]?)', text, re.I):
                    errors.append('转录仅含署名或片尾，缺少实质口播；需视觉证据分支')
                elif len(normalized(text)) < 40:
                    result['warnings'].append('口播较短，需要审核者确认内容完整，不能按字数直接判断失败')
            except (OSError, UnicodeError) as e:
                errors.append('转录无法读取：' + str(e))
        analysis = analyses.get(aid)
        if not isinstance(analysis, dict):
            errors.append('缺少分析')
        else:
            missing = [x for x in FIELDS if not isinstance(analysis.get(x), str) or not analysis[x].strip()]
            if missing:
                errors.append('分析字段缺失或类型无效：' + ', '.join(missing))
            review = analysis.get('evidence_review')
            if not isinstance(review, dict):
                errors.append('缺少针对原材料的 evidence_review；旧分析不自动升级')
            else:
                for key in ('reviewer', 'reviewed_at', 'quality_notes'):
                    if not isinstance(review.get(key), str) or not review[key].strip():
                        errors.append('审核记录缺少 ' + key)
                for key in ('transcript_checked', 'identity_checked', 'full_content_checked', 'claims_checked'):
                    if review.get(key) is not True:
                        errors.append('尚未审核：' + key)
                for key in ('media_sha256', 'transcript_sha256'):
                    if not result.get(key) or review.get(key) != result[key]:
                        errors.append('审核材料指纹不匹配：' + key)
                refs = review.get('references')
                if not isinstance(refs, list):
                    refs = []
                covered = set()
                for ref in refs:
                    if not isinstance(ref, dict):
                        errors.append('引用格式无效')
                        continue
                    field, quote = ref.get('field'), ref.get('quote')
                    start, end = ref.get('start'), ref.get('end')
                    valid_time = (all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (start, end))
                                  and 0 <= start < end)
                    if (field not in GROUNDED_FIELDS or not isinstance(quote, str) or len(normalized(quote)) < 4
                            or normalized(quote) not in normalized(text) or not valid_time):
                        errors.append('引用缺少有效原文或时间位置：' + str(field))
                        continue
                    # Require exact segment provenance for every citation.
                    try:
                        segments = read_object(transcript.with_suffix('.json')).get('segments', [])
                        matches = [s for s in segments if isinstance(s, dict) and
                                   isinstance(s.get('start'), (float, int)) and isinstance(s.get('end'), (float, int)) and
                                   s['start'] >= start - .25 and s['end'] <= end + .25]
                        window = ''.join(normalized(s.get('text')) for s in matches)
                        if normalized(quote) not in window:
                            raise ValueError('原文不在指定时间段')
                    except (OSError, ValueError, TypeError, AttributeError):
                        errors.append('引用时间无法与转录分段对应：' + str(field))
                        continue
                    covered.add(field)
                if set(GROUNDED_FIELDS) - covered:
                    errors.append('缺少可定位证据：' + ', '.join(sorted(set(GROUNDED_FIELDS) - covered)))
        result['ready'] = not errors
    report['summary'] = {'total': len(report['items']), 'ready': sum(x['ready'] for x in report['items'])}
    report['ready'] = not report['errors'] and all(x['ready'] for x in report['items'])
    return report


def require_ready(manifest, analysis):
    report = audit(manifest, analysis)
    if not report['ready']:
        reasons = report['errors'] + [x['id'] + ': ' + '; '.join(x['errors']) for x in report['items'] if x['errors']]
        raise RuntimeError('材料验收未通过，不出正式表、不提交完成状态：\n' + '\n'.join(reasons))
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True, type=Path)
    p.add_argument('--analysis', type=Path)
    p.add_argument('--output', required=True, type=Path, help='独立诊断 JSON，不得指向输入文件')
    p.add_argument('--skip-media', action='store_true', help='仅诊断，永远不通过完成验收')
    args = p.parse_args()
    # Keep diagnostics separate from all batch inputs and state.
    output = args.output.resolve()
    if output.exists() or output == args.manifest.resolve() or (args.analysis and output == args.analysis.resolve()):
        p.error('输出必须是不存在的新文件，避免覆盖已有资料')
    report = audit(args.manifest, args.analysis, not args.skip_media)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({'ready': report['ready'], 'summary': report.get('summary'), 'output': str(output)}, ensure_ascii=False))
    return 0 if report['ready'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
