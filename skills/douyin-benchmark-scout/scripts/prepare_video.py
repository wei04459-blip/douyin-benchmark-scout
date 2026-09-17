#!/usr/bin/env python3
"""One entrypoint for local/public video preparation and visible recovery."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from doctor import inspect
from material_queue import enqueue, prepare, read

LABELS={'queued':'待处理','preparing':'处理中或上次中断','failed':'失败，已保留断点',
        'access_restricted':'访问受限，需恢复来源','pending_review':'材料已准备，待内容审核'}

def report(root):
    path=root/'材料队列.json'
    if not path.exists():print('此目录还没有材料队列');return
    q=read(path)
    for j in q['jobs']:
        print(j['job_id']+'  '+LABELS.get(j['status'],j['status']))
        if j.get('error'):print('  原因：'+j['error']['code']+'；'+j['error']['message'])
        if j.get('artifacts',{}).get('transcript_path'):print('  转录：'+j['artifacts']['transcript_path'])
    print('尚未代表竞品研究完成。内容核对后，由 Codex 接入正式分析与 Excel 验收。')

def main():
    p=argparse.ArgumentParser(description='抖音竞品材料准备：失败可恢复，不依赖浏览器逐步点击')
    p.add_argument('--root',type=Path)
    g=p.add_mutually_exclusive_group();g.add_argument('--video',type=Path);g.add_argument('--url')
    p.add_argument('--model',type=Path);p.add_argument('--python');p.add_argument('--status',action='store_true')
    p.add_argument('--retry-failed',action='store_true');p.add_argument('--check',action='store_true')
    a=p.parse_args()
    if a.check:
        print(json.dumps(inspect(),ensure_ascii=False,indent=2));return 0
    root=(a.root or Path.home()/'.douyin-benchmark-scout/materials'/datetime.now().strftime('%Y%m%d_%H%M%S')).resolve()
    if a.status:report(root);return 0
    if not a.video and not a.url and not (root/'材料队列.json').exists():
        raw=input('拖入本地视频，或粘贴完整抖音作品链接：').strip().strip('\"').strip("'")
        if not raw:return 2
        if raw.startswith('https://'):a.url=raw
        else:a.video=Path(raw)
    if a.video:enqueue(root,{'local_video':str(a.video)})
    if a.url:enqueue(root,{'url':a.url})
    env=inspect();runtime=a.python or env['transcription_python']
    model=a.model or (Path(env['installed_models'][0]) if env['installed_models'] else None)
    if not runtime or not model:
        print('缺少本地转录运行环境或模型，队列已保存。');return 2
    result=prepare(root,runtime,model,a.retry_failed)
    report(root)
    return 0 if all(j['status']=='pending_review' for j in result['jobs']) else 2

if __name__=='__main__':
    try:sys.exit(main())
    except (KeyboardInterrupt,EOFError):print('已停止；下次指定同一目录可继续。');sys.exit(130)
