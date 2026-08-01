#!/usr/bin/env python3
"""用独立 Chrome 配置运行 MediaCrawler，不改日常浏览器的远程调试设置。"""

import os
import sys
from pathlib import Path

crawler_root = Path(os.environ.get("MEDIACRAWLER_ROOT", Path.home() / "MediaCrawler")).expanduser()
if not (crawler_root / "main.py").is_file():
    raise RuntimeError(f"MediaCrawler not found: {crawler_root}")
sys.path.insert(0, str(crawler_root))

import config

config.CDP_CONNECT_EXISTING = False
config.AUTO_CLOSE_BROWSER = True
config.ENABLE_GET_MEIDAS = os.environ.get("MEDIACRAWLER_DOWNLOAD") == "1"

from main import async_cleanup, main
from tools.app_runner import run

run(main, async_cleanup, cleanup_timeout_seconds=15.0)
