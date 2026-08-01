#!/usr/bin/env python3
"""Safely import old scout state and the latest workbook; never copy videos."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


DATA_ROOT = Path(
    os.environ.get("DOUYIN_SCOUT_HOME", Path.home() / ".douyin-benchmark-scout")
).expanduser()


def read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest(root: Path, pattern: str) -> Path | None:
    files = [path for path in root.rglob(pattern) if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime) if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="旧的 benchmark-scout 缓存目录")
    parser.add_argument("--destination", type=Path, default=DATA_ROOT)
    parser.add_argument("--copy-transcripts", action="store_true", help="同时复制旧口播稿；永远不复制视频")
    parser.add_argument("--apply", action="store_true", help="确认后实际复制；省略时仅预览")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    destination = args.destination.expanduser().resolve()
    source_state = read_json(source / "state.json", {})
    workbook = latest(source, "*.xlsx")
    transcripts = [path for path in source.rglob("*.txt") if path.is_file()] if args.copy_transcripts else []
    if not source.is_dir():
        raise RuntimeError(f"旧数据目录不存在：{source}")
    if not source_state and not workbook and not transcripts:
        raise RuntimeError("没有发现可迁移的状态、Excel 或口播稿。请确认 --source 指向旧缓存根目录。")

    print("迁移预览（只复制，不删除旧数据）：")
    print(f"- 去重状态：{'找到' if source_state else '未找到'}")
    print(f"- 最新 Excel：{workbook or '未找到'}")
    print(f"- 口播稿：{len(transcripts)} 个")
    print("- 原视频：0 个（安全策略禁止迁移视频）")
    print(f"- 新位置：{destination}")
    if not args.apply:
        print("未做任何更改。确认路径后加 --apply。")
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    target_state_path = destination / "cache" / "state.json"
    target_state = read_json(target_state_path, {})
    merged = {
        "schema_version": 2,
        "keyword_cursor": int(target_state.get("keyword_cursor", source_state.get("keyword_cursor", 0)) or 0),
        "seen_aweme_ids": sorted(set(map(str, source_state.get("seen_aweme_ids", []))) | set(map(str, target_state.get("seen_aweme_ids", [])))),
        "processed_aweme_ids": sorted(set(map(str, source_state.get("processed_aweme_ids", []))) | set(map(str, target_state.get("processed_aweme_ids", [])))),
        "last_run_at": target_state.get("last_run_at") or source_state.get("last_run_at"),
        "last_run_dir": target_state.get("last_run_dir"),
        "legacy_source": str(source),
    }
    write_json(target_state_path, merged)

    if workbook:
        workbook_target = destination / "竞品选题分析.xlsx"
        shutil.copy2(workbook, workbook_target)
        config_path = destination / "config.json"
        config = read_json(config_path, {})
        if config:
            config.setdefault("paths", {})["workbook_template"] = str(workbook_target)
            write_json(config_path, config)
        print(f"已复制 Excel：{workbook_target}")

    for path in transcripts:
        relative = path.relative_to(source)
        target = destination / "legacy-transcripts" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    print(f"迁移完成：已合并 {len(merged['seen_aweme_ids'])} 条已见、{len(merged['processed_aweme_ids'])} 条已处理记录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
