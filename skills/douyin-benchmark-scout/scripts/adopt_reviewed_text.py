#!/usr/bin/env python3
"""Adopt a human-reviewed text version without rewriting ASR attempt history."""
import argparse
from pathlib import Path
from material_queue import locked,read,save,verify_prepared
from verify_evidence import digest

def adopt(root,aid,text):
 meta=text.with_suffix('.json');t=read(meta)
 if t.get('source_type') not in ('visual','speech_corrected','mixed') or not t.get('review_method') or not t.get('segments') or not text.read_text().strip():raise ValueError('需要注明来源、核对方式和分段的审核文本')
 with locked(root):
  q=read(root/'材料队列.json');j=next(j for j in q['jobs'] if j['source'].get('aweme_id')==aid);m=j['artifacts'];video=Path(m['video_path'])
  if digest(video)!=m['media_sha256'] or t['media_sha256']!=m['media_sha256']:raise ValueError('文本和本条原视频不对应')
  if any(not 0<=s['start']<s['end']<=m['media_duration_seconds']+1 for s in t['segments']):raise ValueError('分段超出视频时长')
  evidence=[Path(p) for p in t.get('evidence_files',[])]
  if not evidence or any(not p.is_file() for p in evidence):raise ValueError('缺少用于核对的画面或来源')
  j.setdefault('text_adoptions',[]).append({'previous_status':j['status'],'previous_error':j.get('error'),'transcript_path':str(text),'source_type':t['source_type'],'review_method':t['review_method']})
  m.update(transcript_path=str(text.resolve()),transcript_sha256=digest(text),transcript_metadata_sha256=digest(meta),source_type=t['source_type'])
  if not verify_prepared(j):raise ValueError('文本接入验收失败')
  j['status']='pending_review';j.pop('error',None);j.pop('next_action',None);j.pop('partial_transcript_path',None);save(root/'材料队列.json',q)
 return j
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--id',required=True);p.add_argument('--text',type=Path,required=True);a=p.parse_args();j=adopt(a.root.resolve(),a.id,a.text.resolve());print(j['job_id']+' 已接入审核文本；研究分析仍需单独验收')
