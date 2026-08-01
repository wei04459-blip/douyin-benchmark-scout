#!/usr/bin/env python3
"""抓指定视频详情，并只保存判断低粉高爆所需的公开账号量级数据。"""

from __future__ import annotations

import json
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
config.ENABLE_GET_MEIDAS = False

import main as crawler_main
from store import douyin as douyin_store
from tools.app_runner import run
from tools.user_hash import anonymize_user_id, mask_nickname


OUTPUT_PATH = Path(
    os.environ.get("CREATOR_METRICS_PATH", "/tmp/douyin_creator_metrics.json")
)
captured: dict[str, dict] = {}
original_update = douyin_store.update_douyin_aweme


def first_number(*values):
    for value in values:
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


async def capture_aweme(aweme_item):
    author = aweme_item.get("author") or {}
    aweme_id = str(aweme_item.get("aweme_id") or "")
    captured[aweme_id] = {
        "aweme_id": aweme_id,
        "creator_hash": anonymize_user_id(author.get("uid")),
        "nickname": mask_nickname(author.get("nickname")),
        "follower_count": first_number(
            author.get("follower_count"),
            author.get("mplatform_followers_count"),
        ),
        "total_favorited": first_number(author.get("total_favorited")),
        "aweme_count": first_number(author.get("aweme_count")),
    }
    await original_update(aweme_item)


douyin_store.update_douyin_aweme = capture_aweme


async def enriched_main():
    await crawler_main.main()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(list(captured.values()), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"CREATOR_METRICS\t{OUTPUT_PATH}")


run(enriched_main, crawler_main.async_cleanup, cleanup_timeout_seconds=15.0)
