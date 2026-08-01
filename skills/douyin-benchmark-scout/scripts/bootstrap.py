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
        f"克隆上游 MediaCrawler 到 {root}（不复制到本 Skill）",
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
    if root.exists() and not (root / "main.py").is_file():
        raise RuntimeError(f"目标目录已存在但不是 MediaCrawler：{root}")
    if not root.exists():
        run(["git", "clone", "--depth", "1", UPSTREAM, root])
    uv = shutil.which("uv")
    if uv:
        run([uv, "sync"], root)
        python = root / (".venv/Scripts/python.exe" if platform.system() == "Windows" else ".venv/bin/python")
        run([uv, "pip", "install", "--python", python, "openpyxl", "openai-whisper", "playwright"], root)
    else:
        python = root / (".venv/Scripts/python.exe" if platform.system() == "Windows" else ".venv/bin/python")
        if not python.is_file():
            run([sys.executable, "-m", "venv", root / ".venv"])
        run([python, "-m", "pip", "install", "--upgrade", "pip"])
        run([python, "-m", "pip", "install", "-r", root / "requirements.txt"])
        run([python, "-m", "pip", "install", "openpyxl", "openai-whisper", "playwright"])
    run([python, "-m", "playwright", "install", "chromium"])
    print("安装完成。首次正式采集会打开浏览器，请由用户本人扫码登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
