#!/usr/bin/env python3
"""Merge WebBridge page enrichment with downloaded media into the standard manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

import run as scout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    run_dir = args.run.expanduser().resolve()
    config = scout.load_config(args.config)
    state = scout.load_state()
    rows = scout.load_rows(run_dir / "search", "search_contents_*.json")
    filtered = scout.filter_search_rows(
        rows,
        config,
        set(map(str, state.get("processed_aweme_ids", []))),
    )
    page_rows = scout.read_json(run_dir / "页面公开数据.json", []) or []
    page_by_id = {
        str(row.get("aweme_id")): row for row in page_rows if row.get("aweme_id")
    }
    metrics = [
        {
            "aweme_id": aweme_id,
            "follower_count": row.get("follower_count"),
            "total_favorited": row.get("creator_total_favorited"),
        }
        for aweme_id, row in page_by_id.items()
    ]
    items = scout.merge_details(filtered, [], metrics, config)
    for item in items:
        page = page_by_id.get(str(item.get("aweme_id")), {})
        item.update(
            {
                "visible_comments": page.get("visible_comments") or [],
                "comments_raw_text": page.get("comments_raw_text") or "",
                "page_chapter_summary": page.get("page_chapter_summary") or "",
                "published_text": page.get("published_text"),
                "public_profile_path": page.get("profile_path") or "",
                "page_capture_ok": bool(page.get("page_ok")),
            }
        )
    scout.attach_local_files(items, run_dir)
    manifest = scout.write_manifest(
        run_dir,
        items,
        [
            "普通人学AI", "AI认知", "AI焦虑", "AI干货",
            "AI教程", "AI工作流", "AI搞钱", "AI创业",
        ],
        config,
        mode="live-kimi-webbridge",
    )
    scout.write_json(
        run_dir / scout.RUN_CHECKPOINT,
        {
            "schema_version": 1,
            "status": "awaiting_analysis",
            "keywords": [
                "普通人学AI", "AI认知", "AI焦虑", "AI干货",
                "AI教程", "AI工作流", "AI搞钱", "AI创业",
            ],
            "created_at": scout.datetime.now(scout.SHANGHAI).isoformat(),
        },
    )
    print(f"标准待分析数据：{manifest}")
    print(f"条目：{len(items)}；粉丝已补：{sum(bool(x.get('follower_count')) for x in items)}；评论正文：{sum(len(x.get('visible_comments') or []) for x in items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
