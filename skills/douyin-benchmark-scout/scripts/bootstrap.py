#!/usr/bin/env python3
"""Install the upstream crawler and local runtime only after explicit --apply."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


UPSTREAM = "https://github.com/NanmiCoder/MediaCrawler.git"
# 2026-07-30 的已验证上游版本。固定提交，避免今天能用、明天上游改动后失效。
PINNED_REVISION = "1779dde9725f6b7ef42e29022c0054b3e678f1af"
EXTRA_PACKAGES = ["openpyxl==3.1.5", "openai-whisper==20240930", "playwright==1.61.0"]


def run(command, cwd=None):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / "MediaCrawler")
    parser.add_argument("--apply", action="store_true", help="实际联网安装；省略时只显示计划")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    plan = [
        f"克隆上游 MediaCrawler 到 {root}（固定兼容版本 {PINNED_REVISION[:12]}）",
        "使用 uv sync；没有 uv 时创建 .venv 并安装 requirements.txt",
        "在同一虚拟环境安装 openpyxl、openai-whisper、playwright",
        "安装 Playwright Chromium，并运行 doctor.py 复检",
    ]
    print("\n".join(f"{i}. {text}" for i, text in enumerate(plan, 1)))
    if not args.apply:
        print("未做任何更改。确认合规和网络权限后加 --apply。")
        return 0
    if not shutil.which("git"):
        raise RuntimeError("缺少 git。请先安装 Git。")
    if not shutil.which("node"):
        raise RuntimeError("缺少 Node.js 16+；MediaCrawler 的抖音能力需要它。")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("缺少 FFmpeg。请先安装，再重新运行安装向导。")
    if root.exists() and not (root / "main.py").is_file():
        raise RuntimeError(f"目标目录已存在但不是 MediaCrawler：{root}")
    if not root.exists():
        run(["git", "clone", "--no-checkout", "--filter=blob:none", UPSTREAM, root])
        run(["git", "-C", root, "fetch", "--depth", "1", "origin", PINNED_REVISION])
        run(["git", "-C", root, "checkout", "--detach", PINNED_REVISION])
    uv = shutil.which("uv")
    if uv:
        run([uv, "sync"], root)
        python = root / (".venv/Scripts/python.exe" if platform.system() == "Windows" else ".venv/bin/python")
        run([uv, "pip", "install", "--python", python, *EXTRA_PACKAGES], root)
    else:
        python = root / (".venv/Scripts/python.exe" if platform.system() == "Windows" else ".venv/bin/python")
        if not python.is_file():
            run([sys.executable, "-m", "venv", root / ".venv"])
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        run([python, "-m", "pip", "install", "-r", root / "requirements.txt"])
        run([python, "-m", "pip", "install", *EXTRA_PACKAGES])
    run([python, "-m", "playwright", "install", "chromium"])
    print("安装完成。首次正式采集会打开浏览器，请由用户本人扫码登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
