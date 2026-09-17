#!/usr/bin/env python3
"""Capability check; installed is not the same as verified online access."""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

def inspect():
    home=Path.home()
    candidates=[Path(sys.executable),home/'.local/bin/python3.11',Path('/usr/bin/python3')]
    transcription=None
    for p in candidates:
        if not p.is_file():continue
        try:
            r=subprocess.run([str(p),'-c','import importlib.util;print(bool(importlib.util.find_spec("whisper") and importlib.util.find_spec("torch")))'],capture_output=True,text=True,timeout=10)
            if r.stdout.strip()=='True':transcription=str(p);break
        except (OSError,subprocess.TimeoutExpired):pass
    ffmpeg=shutil.which('ffmpeg') or str(home/'.local/bin/ffmpeg')
    models=[str(home/'.cache/whisper'/name) for name in ['medium.pt','small.pt','base.pt','tiny.pt'] if (home/'.cache/whisper'/name).is_file()]
    project=home/'Douyin_TikTok_Download_API'
    return {'local_material_preparation_ready':Path(ffmpeg).is_file() and bool(transcription and models),
        'transcription_python':transcription,'ffmpeg':ffmpeg,'installed_models':models,
        'installed_downloader':(project/'crawlers/douyin/web/web_crawler.py').is_file(),
        'downloader_python':str(project/'.venv311/bin/python') if (project/'.venv311/bin/python').is_file() else None,
        'online_download_status':'not_probed','search_status':'not_probed',
        'research_completion':'requires_content_review_and_workbook_verification'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--json',action='store_true');p.add_argument('--strict',action='store_true');a=p.parse_args()
    r=inspect()
    if a.json:print(json.dumps(r,ensure_ascii=False,indent=2))
    else:
        print('本地视频准备：'+('可运行' if r['local_material_preparation_ready'] else '缺少运行环境'))
        print('已有开源下载器：'+('已安装' if r['installed_downloader'] else '未发现'))
        print('在线下载及搜索：尚未实测，安装状态不能证明可用')
        print('研究完成：仍需内容审核与工作簿验收')
    return 0 if r['local_material_preparation_ready'] and not a.strict else 2
if __name__=='__main__':sys.exit(main())
