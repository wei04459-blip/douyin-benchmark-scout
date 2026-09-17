#!/usr/bin/env python3
"""Reusable local ASR worker with content-bound segment checkpoints; never reviews content."""
import argparse
import contextlib
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from verify_evidence import check_media, ffmpeg_path, digest, probe_duration, transcript_problem
from research_batch import save


class TranscriptionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Transcriber:
    def __init__(self, model_path, loader=None):
        self.model_path = Path(model_path).resolve()
        if not self.model_path.is_file():
            raise TranscriptionError('model_missing', '模型未在本地安装；不隐式联网下载')
        self.model_sha = digest(self.model_path)
        self.loader, self.model = loader, None
        try:
            from importlib.metadata import version
            engine_version = version('openai-whisper')
        except Exception:
            engine_version = 'unavailable'
        self.parameters = {'engine': 'openai-whisper', 'engine_version': engine_version,
                           'language': 'zh', 'threads': 1, 'temperature': 0,
                           'condition_on_previous_text': False, 'checkpoint_version': 1}

    def load(self):
        if self.model is None:
            if self.loader:
                self.model = self.loader(str(self.model_path))
            else:
                import torch, whisper
                torch.set_num_threads(1)
                self.model = whisper.load_model(str(self.model_path), device='cpu')
            print(json.dumps({'event':'asr_model_loaded','pid':__import__('os').getpid(),
                              'model_sha256':self.model_sha}),file=sys.stderr,flush=True)
        return self.model

    def chunks(self, audio, duration, media_sha, cache, chunk_seconds=120):
        identity = {'media_sha256': media_sha, 'model_sha256': self.model_sha,
                    'parameters': self.parameters, 'chunk_seconds': chunk_seconds}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        folder = Path(cache)/fingerprint
        result = []
        for number in range(math.ceil(duration/chunk_seconds)):
            start, end = number*chunk_seconds, min((number+1)*chunk_seconds, duration)
            path = folder/(str(number).zfill(4)+'.json')
            row = None
            if path.is_file():
                try:
                    cached = json.loads(path.read_text())
                    if (cached.get('input_sha256') == fingerprint and cached.get('status') == 'ok'
                        and cached.get('start') == start and cached.get('end') == end
                        and not transcript_problem(cached.get('text', ''), cached, duration)):
                        row = cached
                except (ValueError, TypeError, OSError):
                    pass
            if row is None:
                row = {'input_sha256': fingerprint, 'start': start, 'end': end, 'number': number}
                try:
                    raw = self.load().transcribe(audio[int(start*16000):int(end*16000)],
                        language='zh', fp16=False, temperature=0,
                        condition_on_previous_text=False, verbose=None)
                    segments = [{**s, 'start': float(s['start'])+start,
                                 'end': float(s['end'])+start} for s in raw.get('segments', [])]
                    row.update(text=raw.get('text', ''), segments=segments)
                    problem = transcript_problem(row['text'], row, duration)
                    if any(s['start'] < start or s['end'] > end+1 for s in segments):
                        problem = '分段超出本片段范围'
                    row['status'] = 'empty_or_invalid' if problem else 'ok'
                    if problem: row['error'] = problem
                except Exception as exc:
                    row.update(status='failed', text='', segments=[], error=type(exc).__name__)
                save(path, row)
            result.append(row)
        return identity, result

    def transcribe(self, video, output, cache=None, chunk_seconds=120):
        import numpy as np
        video, output = Path(video).resolve(), Path(output).resolve()
        if output.exists():
            raise ValueError('输出目录已存在，请使用新的转录版本')
        if not 10 <= chunk_seconds <= 300:
            raise ValueError('片段长度需为10至300秒')
        error, sha = check_media(video, ffmpeg_path())
        if error: raise TranscriptionError('media_invalid', error)
        duration = probe_duration(video, ffmpeg_path())
        if duration is None or not 0 < duration <= 1800:
            raise ValueError('无法确定时长或超过单条30分钟上限')
        raw = subprocess.run([ffmpeg_path(), '-nostdin', '-v', 'error', '-i', str(video),
              '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-'],
              capture_output=True, check=True, timeout=300).stdout
        audio = np.frombuffer(raw, np.int16).astype(np.float32)/32768.0
        audio_duration = len(audio)/16000
        if abs(audio_duration-duration) > max(2, duration*.03):
            raise TranscriptionError('transcript_incomplete', '音轨时长与视频明显不符，需要核对画面与音频')
        identity, chunks = self.chunks(audio, audio_duration, sha, cache or output.parent/'片段缓存', chunk_seconds)
        if digest(video) != sha:
            raise TranscriptionError('media_invalid', '转录期间媒体变化，拒绝绑定')
        segments = [s for c in chunks if c['status']=='ok' for s in c['segments']]
        text = ''.join(c.get('text', '') for c in chunks if c['status']=='ok')
        incomplete = [c['number'] for c in chunks if c['status']!='ok']
        flags = []
        if len(text.strip()) < duration*1.5: flags.append('文本相对时长稀疏，检查音乐、画面主导或漏识别')
        if incomplete: flags.append('存在空白或失败片段，需要重试或核对画面；未确认完整转录')
        end = max((s['end'] for s in segments), default=0)
        if duration-end > max(3, duration*.05): flags.append('语音结尾距片尾较远，需要核对无声画面或遗漏')
        result = {**identity, 'text': text, 'segments': segments, 'chunks': chunks,
                  'incomplete_chunks': incomplete, 'quality_flags': flags,
                  'model_path': str(self.model_path), 'audio_duration_seconds': audio_duration,
                  'media_duration_seconds': duration, 'transcript_end_seconds': end,
                  'status': 'machine_partial_unreviewed' if incomplete else 'machine_draft_unreviewed'}
        output.mkdir(parents=True)
        save(output/'transcript.json', result)
        with (output/'transcript.txt').open('w', encoding='utf-8') as handle:
            handle.write(text); handle.flush(); __import__('os').fsync(handle.fileno())
        return {'transcript': str(output/'transcript.txt'), 'characters': len(text),
                'status': result['status'], 'incomplete_chunks': incomplete}


def transcribe(video, model_path, output):
    return Transcriber(model_path).transcribe(video, output)


def worker(model_path):
    engine = None
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if engine is None: engine = Transcriber(model_path)
                result = engine.transcribe(request['video'], request['output'], request.get('cache'), request.get('chunk_seconds',120))
            response = {'request_id': request['request_id'], 'ok': True, 'result': result}
        except Exception as exc:
            response = {'request_id': request.get('request_id'), 'ok': False,
                        'code': getattr(exc, 'code', 'transcription_failed'), 'message': str(exc)[:500]}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path);p.add_argument('--model-path',required=True,type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--cache',type=Path);p.add_argument('--worker',action='store_true')
    a=p.parse_args()
    if a.worker: worker(a.model_path)
    else:
        if not a.video or not a.output:p.error('需要 --video 和 --output')
        r=Transcriber(a.model_path).transcribe(a.video,a.output,a.cache)
        print(json.dumps(r,ensure_ascii=False))
        sys.exit(2 if r['incomplete_chunks'] else 0)
