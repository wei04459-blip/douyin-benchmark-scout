#!/usr/bin/env python3
"""竞品爆款采集总入口：搜索、过滤、补粉丝、分层、下载、转录、准备 Excel。"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


MODULE_DIR = Path(__file__).resolve().parent
SKILL_DIR = MODULE_DIR.parent
ASSETS_DIR = SKILL_DIR / "assets"
DATA_ROOT = Path(
    os.environ.get("DOUYIN_SCOUT_HOME", str(Path.home() / ".douyin-benchmark-scout"))
).expanduser().resolve()
PROJECT_ROOT = DATA_ROOT
DEFAULT_CONFIG_PATH = ASSETS_DIR / "example-config.json"
CACHE_ROOT = DATA_ROOT / "cache"
RUNS_ROOT = CACHE_ROOT / "runs"
SEARCH_CHECKPOINT_ROOT = CACHE_ROOT / "search_checkpoints"
STATE_PATH = CACHE_ROOT / "state.json"
SHANGHAI = timezone(timedelta(hours=8))
ANALYSIS_FIELDS = [
    "track",
    "topics",
    "type",
    "topic_summary",
    "hook",
    "structure",
    "emotion",
    "summary",
    "viral",
    "migration",
]


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def slug(text: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", text).strip("_")
    return cleaned[:40] or "keyword"


def first_existing(*candidates: Path) -> Path | None:
    return next((path for path in candidates if path and path.exists()), None)


def resolve_runtime_paths(config: dict) -> dict:
    paths = config.setdefault("paths", {})
    crawler_root = Path(
        os.environ.get("MEDIACRAWLER_ROOT")
        or paths.get("media_crawler_root")
        or first_existing(
            Path.cwd() / "MediaCrawler",
            Path.home() / "MediaCrawler",
            Path.home() / "Projects" / "MediaCrawler",
        )
        or Path.home() / "MediaCrawler"
    ).expanduser().resolve()
    crawler_python = first_existing(
        Path(os.environ["MEDIACRAWLER_PYTHON"]).expanduser()
        if os.environ.get("MEDIACRAWLER_PYTHON") else None,
        Path(paths["media_crawler_python"]).expanduser()
        if paths.get("media_crawler_python") else None,
        crawler_root / ".venv" / "bin" / "python",
        crawler_root / ".venv" / "Scripts" / "python.exe",
    )
    paths["media_crawler_root"] = str(crawler_root)
    paths["media_crawler_python"] = str(crawler_python or sys.executable)
    paths["workbook_python"] = str(
        Path(paths.get("workbook_python") or crawler_python or sys.executable).expanduser()
    )
    paths["workbook_template"] = str(
        Path(paths.get("workbook_template") or ASSETS_DIR / "benchmark-template.xlsx").expanduser()
    )
    paths["chrome_path"] = str(Path(paths.get("chrome_path") or "").expanduser())
    paths["browser_profile"] = str(
        Path(
            paths.get("browser_profile")
            or crawler_root / "browser_data" / "cdp_dy_user_data_dir"
        ).expanduser()
    )
    config.setdefault("transcription", {})["python"] = str(
        Path(config.get("transcription", {}).get("python") or crawler_python or sys.executable).expanduser()
    )
    return config


def load_config(path: Path | None = None) -> dict:
    config_path = (path or Path(os.environ.get("DOUYIN_SCOUT_CONFIG", DATA_ROOT / "config.json"))).expanduser()
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEFAULT_CONFIG_PATH, config_path)
        print(f"已创建用户配置：{config_path}")
    config = read_json(config_path)
    if not isinstance(config, dict):
        raise RuntimeError(f"配置文件无效：{config_path}")
    return resolve_runtime_paths(config)


def load_state() -> dict:
    return read_json(
        STATE_PATH,
        {
            "schema_version": 1,
            "keyword_cursor": 0,
            "seen_aweme_ids": [],
            "processed_aweme_ids": [],
            "last_run_at": None,
            "last_run_dir": None,
        },
    )


def save_state(state: dict) -> None:
    state["seen_aweme_ids"] = sorted(set(map(str, state.get("seen_aweme_ids", []))))
    state["processed_aweme_ids"] = sorted(
        set(map(str, state.get("processed_aweme_ids", [])))
    )
    write_json(STATE_PATH, state)


def find_json_files(root: Path, pattern: str) -> list[Path]:
    return sorted(root.rglob(pattern))


def load_rows(root: Path, pattern: str) -> list[dict]:
    rows: list[dict] = []
    for path in find_json_files(root, pattern):
        payload = read_json(path, [])
        if isinstance(payload, list):
            rows.extend(row for row in payload if isinstance(row, dict))
    return rows


def preliminary_score(item: dict) -> int:
    return (
        as_int(item.get("liked_count"))
        + as_int(item.get("collected_count"))
        + 2 * as_int(item.get("comment_count"))
        + as_int(item.get("share_count"))
    )


def classify(fans: int, likes: int, rules: dict) -> tuple[str, str]:
    if fans <= 0:
        return "待补粉丝数", "缺少公开粉丝数，暂不判定"
    ratio = likes / fans
    if (
        fans <= rules["s_max_fans"]
        and likes >= rules["s_min_likes"]
        and ratio >= rules["s_min_like_fan_ratio"]
    ):
        return "S｜低粉高爆", "低粉账号单条点赞超过粉丝基本盘"
    if (
        fans <= rules["a_max_fans"]
        and likes >= rules["a_min_likes"]
        and ratio >= rules["a_min_like_fan_ratio"]
    ):
        return "A｜重点观察", "中小账号单条数据明显突破基本盘"
    if (
        fans >= rules["big_account_fans"]
        and ratio < rules["big_account_ratio_ceiling"]
    ):
        return "C｜大号常规流量", "更可能由账号基本盘驱动"
    return "B｜常规样本", "未达到低粉高爆或重点观察阈值"


def choose_keywords(config: dict, state: dict, explicit: str | None, all_keywords: bool):
    keywords = list(config["keywords"])
    if explicit:
        chosen = [item.strip() for item in explicit.split(",") if item.strip()]
        return chosen, state.get("keyword_cursor", 0)
    if all_keywords:
        return keywords, state.get("keyword_cursor", 0)
    count = min(config["run_policy"]["keywords_per_run"], len(keywords))
    cursor = int(state.get("keyword_cursor", 0)) % len(keywords)
    chosen = [keywords[(cursor + offset) % len(keywords)] for offset in range(count)]
    return chosen, (cursor + count) % len(keywords)


def run_command(command: list[str], cwd: Path, env: dict | None = None) -> None:
    print("  运行：" + " ".join(command[:4]) + " …", flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"步骤失败，退出码 {completed.returncode}")


def media_crawler_command(
    config: dict,
    entry: Path,
    crawler_type: str,
    save_path: Path,
    *,
    keywords: str | None = None,
    specified_ids: list[str] | None = None,
    headless: bool = True,
) -> list[str]:
    command = [
        config["paths"]["media_crawler_python"],
        str(entry),
        "--platform",
        "dy",
        "--type",
        crawler_type,
        "--lt",
        "qrcode",
        "--headless",
        "yes" if headless else "no",
        "--get_comment",
        "no",
        "--save_data_option",
        "json",
        "--save_data_path",
        str(save_path),
        "--max_concurrency_num",
        "1",
    ]
    if keywords is not None:
        command.extend(
            [
                "--keywords",
                keywords,
                "--crawler_max_notes_count",
                str(config["run_policy"]["results_per_keyword"]),
            ]
        )
    if specified_ids:
        command.extend(["--specified_id", ",".join(specified_ids)])
    return command


def count_search_results(root: Path) -> int:
    return len(
        {
            str(row.get("aweme_id"))
            for row in load_rows(root, "search_contents_*.json")
            if row.get("aweme_id")
        }
    )


def search_queries_for_keyword(config: dict, keyword: str) -> list[str]:
    """Return stable fallbacks while keeping the configured keyword as the bucket."""
    search_policy = config.get("search_policy", {})
    configured = search_policy.get("keyword_fallbacks", {}).get(keyword, [])
    queries = [keyword, *configured]
    if keyword.startswith("AI") and not keyword.startswith("AI "):
        queries.append("AI " + keyword[2:])
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))


def normalize_search_keyword(root: Path, keyword: str, query: str) -> None:
    """Keep fallback matches grouped under the user's original keyword."""
    broad_fallback = (
        keyword.upper().startswith("AI")
        and "AI" not in query.upper()
        and "人工智能" not in query
    )
    ai_markers = ("ai", "人工智能", "aigc", "gpt", "豆包", "claude", "codex")
    for path in find_json_files(root, "search_contents_*.json"):
        payload = read_json(path, [])
        if not isinstance(payload, list):
            continue
        normalized = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            haystack = " ".join(
                str(row.get(field) or "") for field in ("title", "desc")
            ).lower()
            if broad_fallback and not any(marker in haystack for marker in ai_markers):
                continue
            row["matched_query"] = query
            row["source_keyword"] = keyword
            normalized.append(row)
        write_json(path, normalized)


def dedupe_search_rows(rows: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for row in rows:
        aweme_id = str(row.get("aweme_id") or "")
        if aweme_id:
            by_id[aweme_id] = row
    return list(by_id.values())


def checkpoint_path(keyword: str) -> Path:
    day = datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    return SEARCH_CHECKPOINT_ROOT / day / f"{slug(keyword)}.json"


def save_search_checkpoint(keyword: str, rows: list[dict]) -> None:
    normalized = []
    for source in dedupe_search_rows(rows):
        row = dict(source)
        row["source_keyword"] = keyword
        normalized.append(row)
    write_json(checkpoint_path(keyword), normalized)


def load_search_checkpoint(keyword: str) -> list[dict]:
    path = checkpoint_path(keyword)
    payload = read_json(path, [])
    if isinstance(payload, list) and payload:
        return dedupe_search_rows(
            [row for row in payload if isinstance(row, dict)]
        )

    # Upgrade interrupted same-day runs into reusable checkpoints. This makes
    # circuit-breaker exits resumable instead of throwing away successful words.
    day_prefix = datetime.now(SHANGHAI).strftime("%Y%m%d_")
    recovered: list[dict] = []
    for run_dir in sorted(RUNS_ROOT.glob(f"{day_prefix}*"), reverse=True):
        for row in load_rows(run_dir / "search", "search_contents_*.json"):
            if str(row.get("source_keyword") or "").strip() == keyword:
                recovered.append(row)
    recovered = dedupe_search_rows(recovered)
    if recovered:
        save_search_checkpoint(keyword, recovered)
    return recovered


def validate_analysis_complete(manifest: dict, analysis_path: Path) -> dict:
    payload = read_json(analysis_path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"AI拆解文件无效：{analysis_path}")
    analysis_by_id = payload.get("items", payload)
    if not isinstance(analysis_by_id, dict):
        raise RuntimeError(f"AI拆解文件缺少 items：{analysis_path}")
    required = [field for field in ANALYSIS_FIELDS if field != "topics"]
    for item in manifest.get("items", []):
        aweme_id = str(item.get("aweme_id") or "")
        analysis = analysis_by_id.get(aweme_id)
        if not isinstance(analysis, dict):
            raise RuntimeError(f"缺少视频 {aweme_id} 的AI拆解")
        missing = [
            field
            for field in required
            if not str(analysis.get(field) or "").strip()
        ]
        if missing:
            raise RuntimeError(
                f"视频 {aweme_id} 的AI拆解不完整：{', '.join(missing)}"
            )
    return analysis_by_id


def delete_processed_videos(
    manifest_path: Path,
    analysis_path: Path,
    workbook_path: Path,
) -> int:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise RuntimeError(f"待分析数据无效：{manifest_path}")
    validate_analysis_complete(manifest, analysis_path)
    if not workbook_path.is_file():
        raise RuntimeError("Excel 尚未成功生成，拒绝删除原视频")

    items = manifest.get("items", [])
    missing_transcripts = []
    for item in items:
        transcript_path = item.get("transcript_path")
        if not transcript_path or not Path(transcript_path).is_file():
            missing_transcripts.append(str(item.get("aweme_id") or ""))
    if missing_transcripts:
        raise RuntimeError(
            "以下视频缺少已保存口播稿，拒绝删除原视频："
            + ", ".join(missing_transcripts)
        )

    deleted = 0
    deleted_at = datetime.now(SHANGHAI).isoformat()
    for item in items:
        video_path = item.get("video_path")
        if video_path:
            path = Path(video_path)
            if path.is_file():
                path.unlink()
                deleted += 1
        item["video_path"] = None
        item["video_deleted_at"] = deleted_at
        item["video_status"] = "已完成转录与分析，原视频已删除"
    write_json(manifest_path, manifest)
    write_json(
        manifest_path.parent / "视频清理记录.json",
        {
            "deleted_at": deleted_at,
            "deleted_count": deleted,
            "kept_transcripts": len(items),
            "workbook": str(workbook_path),
        },
    )
    return deleted


def filter_search_rows(
    rows: list[dict],
    config: dict,
    seen_ids: set[str],
) -> list[dict]:
    cutoff = datetime.now(SHANGHAI) - timedelta(days=config["filter"]["days"])
    deduped: dict[str, dict] = {}
    for raw in rows:
        aweme_id = str(raw.get("aweme_id") or "")
        if not aweme_id:
            continue
        if config["run_policy"]["skip_seen_across_runs"] and aweme_id in seen_ids:
            continue
        created = datetime.fromtimestamp(as_int(raw.get("create_time")), SHANGHAI)
        if created < cutoff:
            continue
        likes = as_int(raw.get("liked_count"))
        favorites = as_int(raw.get("collected_count"))
        comments = as_int(raw.get("comment_count"))
        if not (
            likes >= config["filter"]["min_likes"]
            or favorites >= config["filter"]["min_favorites"]
            or comments >= config["filter"]["min_comments"]
        ):
            continue
        keyword = str(raw.get("source_keyword") or "").strip()
        if aweme_id not in deduped:
            item = dict(raw)
            item["source_keywords"] = [keyword] if keyword else []
            deduped[aweme_id] = item
        elif keyword and keyword not in deduped[aweme_id]["source_keywords"]:
            deduped[aweme_id]["source_keywords"].append(keyword)
    result = list(deduped.values())
    result.sort(key=preliminary_score, reverse=True)
    return result


def select_with_keyword_quota(
    rows: list[dict],
    keywords: list[str],
    limit: int,
    per_keyword: int,
    *,
    require_quota: bool = False,
) -> list[dict]:
    """Give every requested keyword its own slots before filling by global score."""
    selected: list[dict] = []
    selected_ids: set[str] = set()
    shortages: list[str] = []
    for keyword in keywords:
        matches = [
            row
            for row in rows
            if keyword in row.get("source_keywords", [])
            and str(row.get("aweme_id") or "") not in selected_ids
        ]
        take = matches[:per_keyword]
        if require_quota and len(take) < per_keyword:
            shortages.append(f"{keyword}（{len(take)}/{per_keyword}）")
        for row in take:
            selected.append(row)
            selected_ids.add(str(row.get("aweme_id") or ""))
    if shortages:
        raise RuntimeError(
            "以下关键词没有达到正式批次的独立样本配额：" + "、".join(shortages)
        )
    for row in rows:
        aweme_id = str(row.get("aweme_id") or "")
        if len(selected) >= limit:
            break
        if aweme_id not in selected_ids:
            selected.append(row)
            selected_ids.add(aweme_id)
    return selected[:limit]


def merge_details(
    candidates: list[dict],
    details: list[dict],
    metrics: list[dict],
    config: dict,
) -> list[dict]:
    detail_by_id = {str(row.get("aweme_id")): row for row in details}
    metrics_by_id = {str(row.get("aweme_id")): row for row in metrics}
    metrics_by_hash = {str(row.get("creator_hash")): row for row in metrics}
    merged: list[dict] = []
    for candidate in candidates:
        aweme_id = str(candidate.get("aweme_id"))
        item = {**candidate, **detail_by_id.get(aweme_id, {})}
        metric = metrics_by_id.get(aweme_id) or metrics_by_hash.get(
            str(item.get("creator_hash"))
        )
        metric = metric or {}
        fans = as_int(metric.get("follower_count"))
        likes = as_int(item.get("liked_count"))
        level, reason = classify(fans, likes, config["breakout_rules"])
        item.update(
            {
                "follower_count": fans or None,
                "creator_total_favorited": as_int(metric.get("total_favorited"))
                or None,
                "like_fan_ratio": (likes / fans) if fans else None,
                "interaction_fan_ratio": (
                    (
                        likes
                        + as_int(item.get("collected_count"))
                        + as_int(item.get("comment_count"))
                        + as_int(item.get("share_count"))
                    )
                    / fans
                )
                if fans
                else None,
                "breakout_level": level,
                "breakout_reason": reason,
                "preliminary_score": preliminary_score(item),
            }
        )
        merged.append(item)
    rank = {"S｜低粉高爆": 0, "A｜重点观察": 1, "B｜常规样本": 2, "C｜大号常规流量": 3, "待补粉丝数": 4}
    merged.sort(
        key=lambda row: (
            rank.get(row["breakout_level"], 9),
            -float(row.get("like_fan_ratio") or 0),
            -int(row.get("preliminary_score") or 0),
        )
    )
    return merged


def attach_local_files(items: list[dict], source_root: Path) -> None:
    for item in items:
        aweme_id = str(item["aweme_id"])
        video_candidates = list(source_root.rglob(f"videos/{aweme_id}/video.mp4"))
        transcript_candidates = list(source_root.rglob(f"{aweme_id}.txt"))
        json_candidates = list(source_root.rglob(f"{aweme_id}.json"))
        item["video_path"] = str(video_candidates[0]) if video_candidates else None
        item["transcript_path"] = (
            str(transcript_candidates[0]) if transcript_candidates else None
        )
        duration = None
        for json_path in json_candidates:
            payload = read_json(json_path)
            if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
                segments = payload["segments"]
                if segments:
                    duration = round(float(segments[-1].get("end") or 0))
                    break
        item["duration_seconds"] = duration


def download_from_search_urls(items: list[dict], run_dir: Path) -> int:
    """Use search-result play URLs when the detail endpoint is temporarily blocked."""
    downloaded = 0
    for index, item in enumerate(items, 1):
        if item.get("video_path") and Path(item["video_path"]).is_file():
            continue
        url = str(item.get("video_download_url") or "").strip()
        if not url:
            continue
        aweme_id = str(item["aweme_id"])
        target = run_dir / "media-direct" / "videos" / aweme_id / "video.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"[直链补下载 {index}/{len(items)}] {aweme_id}", flush=True)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36",
                "Referer": "https://www.douyin.com/",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                with target.open("wb") as output:
                    shutil.copyfileobj(response, output)
        except Exception as exc:
            target.unlink(missing_ok=True)
            print(f"  直链补下载失败：{exc}", flush=True)
            continue
        if target.stat().st_size < 10_000:
            target.unlink(missing_ok=True)
            continue
        item["video_path"] = str(target)
        downloaded += 1
    return downloaded


def transcribe_videos(items: list[dict], run_dir: Path, config: dict) -> None:
    transcription = config["transcription"]
    if not transcription.get("enabled"):
        return
    transcript_root = run_dir / "transcripts"
    for index, item in enumerate(items, 1):
        video_path = item.get("video_path")
        if not video_path or not Path(video_path).is_file():
            continue
        aweme_id = str(item["aweme_id"])
        output_dir = transcript_root / aweme_id
        target_txt = output_dir / f"{aweme_id}.txt"
        if target_txt.exists():
            item["transcript_path"] = str(target_txt)
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"[转录 {index}/{len(items)}] {aweme_id}", flush=True)
        command = [
            transcription.get("python") or sys.executable,
            "-m",
            "whisper",
            str(video_path),
            "--model",
            transcription["model"],
            "--language",
            transcription["language"],
            "--fp16",
            "False",
            "--device",
            transcription.get("device", "cpu"),
            "--output_dir",
            str(output_dir),
            "--output_format",
            "all",
        ]
        env = os.environ.copy()
        threads = str(transcription.get("threads", 2))
        env.update({"OMP_NUM_THREADS": threads, "MKL_NUM_THREADS": threads})
        run_command(command, PROJECT_ROOT, env)
        for generated in output_dir.glob("video.*"):
            generated.replace(output_dir / f"{aweme_id}{generated.suffix}")
        item["transcript_path"] = str(target_txt) if target_txt.exists() else None
        transcript_json = output_dir / f"{aweme_id}.json"
        payload = read_json(transcript_json)
        if isinstance(payload, dict) and payload.get("segments"):
            item["duration_seconds"] = round(
                float(payload["segments"][-1].get("end") or 0)
            )


def make_analysis_template(items: list[dict], path: Path) -> None:
    payload = {
        "schema_version": 1,
        "说明": "由AI阅读每条完整口播稿后填写；不要编造账号经历、收入或未出现的信息。",
        "items": {
            str(item["aweme_id"]): {field: "" for field in ANALYSIS_FIELDS}
            for item in items
        },
    }
    write_json(path, payload)


def write_manifest(
    run_dir: Path,
    items: list[dict],
    keywords: list[str],
    config: dict,
    *,
    mode: str,
) -> Path:
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(SHANGHAI).isoformat(),
        "mode": mode,
        "keywords": keywords,
        "rules": {
            "days": config["filter"]["days"],
            **config["breakout_rules"],
        },
        "summary": {
            "selected": len(items),
            "s_low_fan_breakout": sum(
                1 for row in items if row["breakout_level"].startswith("S")
            ),
            "a_watch": sum(
                1 for row in items if row["breakout_level"].startswith("A")
            ),
        },
        "items": items,
    }
    path = run_dir / "待分析数据.json"
    write_json(path, manifest)
    make_analysis_template(items, run_dir / "AI拆解模板.json")
    return path


def finalize_workbook(
    run_dir: Path,
    manifest_path: Path,
    analysis_path: Path,
    config: dict,
    input_workbook: Path | None,
) -> Path:
    if not analysis_path.is_file():
        raise RuntimeError(f"缺少AI拆解文件：{analysis_path}")
    input_path = input_workbook or Path(config["paths"]["workbook_template"])
    output_path = run_dir / f"竞品选题分析_{datetime.now(SHANGHAI):%Y%m%d}.xlsx"
    env = os.environ.copy()
    env.update(
        {
            "BENCHMARK_MANIFEST": str(manifest_path),
            "BENCHMARK_ANALYSIS": str(analysis_path),
            "BENCHMARK_INPUT_XLSX": str(input_path) if input_path.is_file() else "",
            "BENCHMARK_OUTPUT_XLSX": str(output_path),
            "BENCHMARK_PREVIEW_DIR": str(run_dir / "preview"),
            "BENCHMARK_DELETE_SOURCE_VIDEO": "yes"
            if config.get("cleanup", {}).get(
                "delete_video_after_analysis_and_excel", False
            )
            else "no",
        }
    )
    run_command(
        [
            config["paths"]["workbook_python"],
            str(MODULE_DIR / "build_workbook.py"),
        ],
        run_dir,
        env,
    )
    return output_path


def collect(args, config: dict) -> int:
    state = load_state()
    keywords, next_cursor = choose_keywords(
        config, state, args.keywords, args.all_keywords
    )
    run_dir = RUNS_ROOT / datetime.now(SHANGHAI).strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    crawler_root = Path(config["paths"]["media_crawler_root"])
    if not (crawler_root / "main.py").is_file():
        raise RuntimeError(
            f"未找到 MediaCrawler：{crawler_root}。先运行 doctor.py 查看安装建议。"
        )

    search_policy = config.get("search_policy", {})
    search_is_headless = search_policy.get("browser_mode") != "visible"
    max_attempts = max(1, int(search_policy.get("max_attempts_per_keyword", 1)))
    min_results = max(1, int(search_policy.get("min_results_per_keyword", 1)))
    retry_wait = max(0, int(search_policy.get("empty_retry_wait_seconds", 90)))
    search_status = []
    failed_keywords = []

    print(f"本轮关键词：{', '.join(keywords)}")
    for index, keyword in enumerate(keywords, 1):
        print(f"[搜索 {index}/{len(keywords)}] {keyword}", flush=True)
        keyword_ok = False
        attempts = []
        used_network = False
        search_queries = search_queries_for_keyword(config, keyword)
        cached_rows = load_search_checkpoint(keyword)
        if len(cached_rows) >= min_results:
            save_path = (
                run_dir
                / "search"
                / f"{index:02d}_{slug(keyword)}"
                / "checkpoint_reuse"
                / "douyin"
                / "json"
                / f"search_contents_{datetime.now(SHANGHAI):%Y-%m-%d}.json"
            )
            write_json(save_path, cached_rows)
            keyword_ok = True
            attempts.append(
                {
                    "attempt": 0,
                    "query": keyword,
                    "result_count": len(cached_rows),
                    "error": None,
                    "browser_mode": "checkpoint_reuse",
                }
            )
            print(f"  复用今日断点：{len(cached_rows)} 条，无需重复搜索", flush=True)
        for attempt in range(1, max_attempts + 1):
            if keyword_ok:
                break
            query = search_queries[min(attempt - 1, len(search_queries) - 1)]
            save_path = (
                run_dir
                / "search"
                / f"{index:02d}_{slug(keyword)}"
                / f"attempt_{attempt}_{slug(query)}"
            )
            command = media_crawler_command(
                config,
                MODULE_DIR / "mediacrawler_entry.py",
                "search",
                save_path,
                keywords=query,
                headless=search_is_headless,
            )
            used_network = True
            env = os.environ.copy()
            env["MEDIACRAWLER_DOWNLOAD"] = "0"
            env["MEDIACRAWLER_ROOT"] = str(crawler_root)
            error = None
            try:
                run_command(command, crawler_root, env)
            except RuntimeError as exc:
                error = str(exc)
            result_count = count_search_results(save_path)
            if result_count:
                normalize_search_keyword(save_path, keyword, query)
                result_count = count_search_results(save_path)
            if result_count:
                save_search_checkpoint(
                    keyword,
                    load_rows(save_path, "search_contents_*.json"),
                )
            attempts.append(
                {
                    "attempt": attempt,
                    "query": query,
                    "result_count": result_count,
                    "error": error,
                    "browser_mode": search_policy.get("browser_mode", "headless"),
                }
            )
            if error is None and result_count >= min_results:
                keyword_ok = True
                break
            if attempt < max_attempts:
                print(
                    f"  查询‘{query}’返回 {result_count} 条，{retry_wait} 秒后换写法重试；不会把空结果计为完成",
                    flush=True,
                )
                time.sleep(retry_wait)
        if not keyword_ok and search_policy.get("page_ui_fallback", False):
            save_path = (
                run_dir
                / "search"
                / f"{index:02d}_{slug(keyword)}"
                / "page_ui_fallback"
                / "douyin"
                / "json"
            )
            output_path = save_path / f"search_contents_{datetime.now(SHANGHAI):%Y-%m-%d}.json"
            command = [
                config["paths"]["media_crawler_python"],
                str(MODULE_DIR / "search_page_fallback.py"),
                "--keyword",
                keyword,
                "--output",
                str(output_path),
                "--limit",
                str(config["run_policy"]["results_per_keyword"]),
                "--profile-path",
                config["paths"]["browser_profile"],
            ]
            if config["paths"].get("chrome_path"):
                command.extend(["--chrome-path", config["paths"]["chrome_path"]])
            error = None
            try:
                run_command(command, PROJECT_ROOT)
            except RuntimeError as exc:
                error = str(exc)
            result_count = count_search_results(save_path)
            attempts.append(
                {
                    "attempt": "page_ui_fallback",
                    "query": keyword,
                    "result_count": result_count,
                    "error": error,
                    "browser_mode": "page_ui_fallback",
                }
            )
            if error is None and result_count >= min_results:
                keyword_ok = True
                save_search_checkpoint(
                    keyword,
                    load_rows(save_path, "search_contents_*.json"),
                )
        search_status.append(
            {
                "keyword": keyword,
                "status": "success" if keyword_ok else "failed",
                "attempts": attempts,
            }
        )
        write_json(run_dir / "搜索状态.json", search_status)
        if not keyword_ok:
            failed_keywords.append(keyword)
            if search_policy.get("abort_on_incomplete", True):
                for deferred_keyword in keywords[index:]:
                    search_status.append(
                        {
                            "keyword": deferred_keyword,
                            "status": "deferred_by_circuit_breaker",
                            "attempts": [],
                        }
                    )
                write_json(run_dir / "搜索状态.json", search_status)
                print(
                    "  已触发搜索熔断：停止后续关键词，避免连续空请求加重平台限制",
                    flush=True,
                )
                break
        if index < len(keywords) and used_network:
            pause = random.randint(
                config["run_policy"]["pause_seconds_min"],
                config["run_policy"]["pause_seconds_max"],
            )
            print(f"  安全间隔 {pause} 秒", flush=True)
            time.sleep(pause)

    if failed_keywords and search_policy.get("abort_on_incomplete", True):
        raise RuntimeError(
            "以下关键词连续重试后仍无有效结果，本轮未出表、未移动关键词游标："
            + ", ".join(failed_keywords)
        )

    search_rows = load_rows(run_dir / "search", "search_contents_*.json")
    seen = set(map(str, state.get("seen_aweme_ids", [])))
    processed = set(map(str, state.get("processed_aweme_ids", [])))
    filtered = filter_search_rows(search_rows, config, processed)
    download_limit = args.download_limit or config["run_policy"]["download_limit"]
    per_keyword = args.per_keyword or 0
    if per_keyword and download_limit < per_keyword * len(keywords):
        raise RuntimeError(
            "正式批次总下载数小于关键词配额总数，请提高 --download-limit。"
        )
    shortlist = select_with_keyword_quota(
        filtered,
        keywords,
        config["run_policy"]["detail_limit"],
        per_keyword,
        require_quota=bool(per_keyword),
    ) if per_keyword else filtered[: config["run_policy"]["detail_limit"]]
    if not shortlist:
        raise RuntimeError("本轮没有命中过滤条件的视频，未修改去重状态。")

    ids = [str(row["aweme_id"]) for row in shortlist]
    print(f"进入详情与粉丝校准：{len(ids)} 条", flush=True)
    detail_path = run_dir / "detail-meta"
    metrics_path = run_dir / "creator_metrics.json"
    command = media_crawler_command(
        config,
        MODULE_DIR / "enrich_creator_metrics.py",
        "detail",
        detail_path,
        specified_ids=ids,
    )
    env = os.environ.copy()
    env["CREATOR_METRICS_PATH"] = str(metrics_path)
    env["MEDIACRAWLER_ROOT"] = str(crawler_root)
    run_command(command, crawler_root, env)
    details = load_rows(detail_path, "detail_contents_*.json")
    metrics = read_json(metrics_path, [])
    merged = merge_details(shortlist, details, metrics, config)
    downloadable = [row for row in merged if row.get("video_download_url")]
    if len(downloadable) >= download_limit:
        selected = select_with_keyword_quota(
            downloadable, keywords, download_limit, per_keyword
        ) if per_keyword else downloadable[:download_limit]
    else:
        selected = select_with_keyword_quota(
            merged,
            keywords,
            download_limit,
            per_keyword,
            require_quota=bool(per_keyword),
        ) if per_keyword else merged[:download_limit]

    if not args.skip_download:
        media_path = run_dir / "media"
        command = media_crawler_command(
            config,
            MODULE_DIR / "mediacrawler_entry.py",
            "detail",
            media_path,
            specified_ids=[str(row["aweme_id"]) for row in selected],
        )
        env = os.environ.copy()
        env["MEDIACRAWLER_DOWNLOAD"] = "1"
        env["MEDIACRAWLER_ROOT"] = str(crawler_root)
        print(f"下载优先级最高的 {len(selected)} 条视频", flush=True)
        run_command(command, crawler_root, env)
        attach_local_files(selected, media_path)
        direct_count = download_from_search_urls(selected, run_dir)
        if direct_count:
            print(f"详情接口受限后，已用搜索直链补下载 {direct_count} 条", flush=True)
        missing_videos = [
            str(row["aweme_id"])
            for row in selected
            if not row.get("video_path") or not Path(row["video_path"]).is_file()
        ]
        if missing_videos:
            raise RuntimeError(
                "以下入选视频未成功下载，本轮拒绝标记完成："
                + ", ".join(missing_videos)
            )
    if not args.skip_transcribe:
        transcribe_videos(selected, run_dir, config)
        missing_transcripts = [
            str(row["aweme_id"])
            for row in selected
            if not row.get("transcript_path")
            or not Path(row["transcript_path"]).is_file()
        ]
        if missing_transcripts:
            raise RuntimeError(
                "以下入选视频未成功转录，本轮拒绝标记完成："
                + ", ".join(missing_transcripts)
            )

    manifest_path = write_manifest(
        run_dir, selected, keywords, config, mode="live"
    )
    state["keyword_cursor"] = next_cursor
    selected_ids = {str(row["aweme_id"]) for row in selected}
    state["seen_aweme_ids"] = sorted(seen | set(ids))
    # 这里只记录已见；只有分析、Excel 和安全清理完成后才算 processed。
    state["processed_aweme_ids"] = sorted(processed)
    state["last_run_at"] = datetime.now(SHANGHAI).isoformat()
    state["last_run_dir"] = str(run_dir)
    save_state(state)
    print(f"待分析数据：{manifest_path}")
    print(f"AI拆解模板：{run_dir / 'AI拆解模板.json'}")
    print("下一步：由AI阅读口播稿填完拆解模板，再运行 finalize。")
    return 0


def dry_run(args, config: dict) -> int:
    source = args.source.expanduser().resolve()
    run_dir = RUNS_ROOT / datetime.now(SHANGHAI).strftime("dry_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)
    search_rows = load_rows(source, "search_contents_*.json")
    details = load_rows(source, "detail_contents_*.json")
    metrics = read_json(source / "creator_metrics.json", [])
    if details:
        detail_ids = {str(row.get("aweme_id")) for row in details}
        search_rows = [
            row for row in search_rows if str(row.get("aweme_id")) in detail_ids
        ]
    filtered = filter_search_rows(search_rows, config, set())
    merged = merge_details(filtered, details, metrics, config)
    selected = merged[: config["run_policy"]["download_limit"]]
    attach_local_files(selected, source)
    manifest_path = write_manifest(
        run_dir,
        selected,
        sorted(
            {
                keyword
                for row in selected
                for keyword in row.get("source_keywords", [])
                if keyword
            }
        ),
        config,
        mode="dry-run",
    )
    print(f"dry-run 待分析数据：{manifest_path}")
    if args.analysis:
        output = finalize_workbook(
            run_dir,
            manifest_path,
            args.analysis.expanduser().resolve(),
            config,
            args.input_workbook.expanduser().resolve()
            if args.input_workbook
            else None,
        )
        print(f"dry-run Excel：{output}")
    return 0


def finalize(args, config: dict) -> int:
    run_dir = args.run.expanduser().resolve()
    manifest_path = run_dir / "待分析数据.json"
    analysis_path = args.analysis.expanduser().resolve()
    output = finalize_workbook(
        run_dir,
        manifest_path,
        analysis_path,
        config,
        args.input_workbook.expanduser().resolve()
        if args.input_workbook
        else None,
    )
    deleted = 0
    if config.get("cleanup", {}).get(
        "delete_video_after_analysis_and_excel", False
    ):
        deleted = delete_processed_videos(
            manifest_path,
            analysis_path,
            output,
        )
    state = load_state()
    manifest = read_json(manifest_path, {}) or {}
    finalized_ids = {
        str(item.get("aweme_id"))
        for item in manifest.get("items", [])
        if item.get("aweme_id")
    }
    state["processed_aweme_ids"] = sorted(
        set(map(str, state.get("processed_aweme_ids", []))) | finalized_ids
    )
    save_state(state)
    print(f"Excel：{output}")
    print(f"已删除完成转录和分析的原视频：{deleted} 个")
    return 0


def show_status(config: dict) -> int:
    state = load_state()
    keywords, _ = choose_keywords(config, state, None, False)
    payload = {
        "next_keywords": keywords,
        "seen_count": len(state.get("seen_aweme_ids", [])),
        "processed_count": len(state.get("processed_aweme_ids", [])),
        "last_run_at": state.get("last_run_at"),
        "last_run_dir": state.get("last_run_dir"),
        "days": config["filter"]["days"],
        "download_limit": config["run_policy"]["download_limit"],
        "breakout_rules": config["breakout_rules"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="自定义配置文件；默认 ~/.douyin-benchmark-scout/config.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="联网采集并准备待分析数据")
    collect_parser.add_argument("--keywords", help="逗号分隔；省略则轮换默认关键词")
    collect_parser.add_argument("--all-keywords", action="store_true")
    collect_parser.add_argument("--skip-download", action="store_true")
    collect_parser.add_argument("--skip-transcribe", action="store_true")
    collect_parser.add_argument("--download-limit", type=int)
    collect_parser.add_argument(
        "--per-keyword",
        type=int,
        help="正式批次每个关键词至少入选多少条；不足则整轮不标记完成",
    )

    dry_parser = subparsers.add_parser("dry-run", help="用已有缓存验证流程")
    dry_parser.add_argument("--source", type=Path, required=True)
    dry_parser.add_argument("--analysis", type=Path)
    dry_parser.add_argument("--input-workbook", type=Path)

    finalize_parser = subparsers.add_parser("finalize", help="把AI拆解写入Excel")
    finalize_parser.add_argument("--run", type=Path, required=True)
    finalize_parser.add_argument("--analysis", type=Path, required=True)
    finalize_parser.add_argument("--input-workbook", type=Path)

    subparsers.add_parser("status", help="查看下一批关键词和去重状态")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    if args.command == "collect":
        return collect(args, config)
    if args.command == "dry-run":
        return dry_run(args, config)
    if args.command == "finalize":
        return finalize(args, config)
    return show_status(config)


if __name__ == "__main__":
    raise SystemExit(main())
