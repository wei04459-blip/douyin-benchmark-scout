#!/usr/bin/env python3
"""Resume a WebBridge search batch without calling the blocked legacy detail API."""

from __future__ import annotations

import argparse
from pathlib import Path

import run as scout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--transcribe", action="store_true")
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
    items = scout.merge_details(filtered, [], [], config)
    scout.attach_local_files(items, run_dir)
    print(f"去重后待处理：{len(items)} 条", flush=True)

    if args.download:
        count = scout.download_from_search_urls(items, run_dir)
        print(f"本次新增下载：{count} 条", flush=True)
    if args.transcribe:
        scout.transcribe_videos(items, run_dir, config)

    scout.attach_local_files(items, run_dir)
    scout.write_json(run_dir / "媒体处理状态.json", items)
    print(f"媒体状态：{run_dir / '媒体处理状态.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
