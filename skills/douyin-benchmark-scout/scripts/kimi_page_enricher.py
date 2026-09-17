#!/usr/bin/env python3
"""Enrich Douyin search rows from the visible public video page via Kimi WebBridge."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen

import run as scout


ENDPOINT = "http://127.0.0.1:10086/command"
SESSION = "douyin-competitor-20260804"
TIME_RE = re.compile(r"^(?:刚刚|\d+(?:秒|分钟|小时|天|周|月|年)前)(?:·.*)?$")
AUTHOR_RE = re.compile(
    r"\n([^\n]{1,60})\n\s*粉丝\s*([0-9.万亿wW]+)\s*获赞\s*([0-9.万亿wW]+)"
)


def call(action: str, args: dict, timeout: int = 50) -> dict:
    body = json.dumps(
        {"action": action, "args": args, "session": SESSION},
        ensure_ascii=False,
    ).encode("utf-8")
    req = Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as response:
        envelope = json.loads(response.read().decode("utf-8"))
    if not envelope.get("ok"):
        raise RuntimeError(str((envelope.get("error") or {}).get("message") or envelope))
    return envelope.get("data") or {}


def count_number(text: str) -> int | None:
    value = str(text or "").strip().lower().replace(",", "")
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([万亿w]?)", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit in {"万", "w"}:
        number *= 10_000
    elif unit == "亿":
        number *= 100_000_000
    return int(round(number))


def mask_name(name: str) -> str:
    name = str(name or "").strip()
    if not name:
        return ""
    if len(name) == 1:
        return name + "*"
    return name[0] + "***" + name[-1]


def parse_comments(section: str, limit: int = 10) -> list[dict]:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    comments: list[dict] = []
    for index, line in enumerate(lines):
        if not TIME_RE.match(line):
            continue
        marker = None
        for cursor in range(index - 1, max(-1, index - 12), -1):
            if lines[cursor] == "...":
                marker = cursor
                break
        if marker is None or marker == 0:
            continue
        username = lines[marker - 1]
        content_lines = lines[marker + 1 : index]
        content = "\n".join(
            part for part in content_lines if part not in {"分享", "回复"}
        ).strip()
        if not content or content in {"加载中", "展开回复"}:
            continue
        like_count = None
        for candidate in lines[index + 1 : index + 4]:
            if re.fullmatch(r"\d+(?:\.\d+)?(?:万)?", candidate):
                like_count = count_number(candidate)
                break
        comments.append(
            {
                "commenter": mask_name(username),
                "content": content,
                "time_location": line,
                "like_count": like_count,
            }
        )
        if len(comments) >= limit:
            break
    return comments


def parse_page(text: str, item: dict, profile_path: str) -> dict:
    nickname = str(item.get("nickname") or "").strip()
    author_matches = list(AUTHOR_RE.finditer(text))
    author_match = next(
        (match for match in author_matches if match.group(1).strip() == nickname),
        author_matches[0] if author_matches else None,
    )
    follower_count = count_number(author_match.group(2)) if author_match else None
    total_favorited = count_number(author_match.group(3)) if author_match else None

    comment_start = text.find("全部评论")
    comment_end = author_match.start() if author_match else -1
    comment_section = ""
    if comment_start >= 0:
        if comment_end <= comment_start:
            comment_end = text.find("\n下载客户端", comment_start)
        if comment_end < 0:
            comment_end = min(len(text), comment_start + 8000)
        comment_section = text[comment_start + len("全部评论") : comment_end].strip()

    before_comments = text[:comment_start] if comment_start >= 0 else text
    chapter_start = before_comments.find("章节要点")
    chapter_text = ""
    if chapter_start >= 0:
        chapter_text = before_comments[chapter_start:].strip()
        title = str(item.get("title") or "").strip()
        if title:
            title_at = chapter_text.rfind(title)
            if title_at > 0:
                chapter_text = chapter_text[:title_at].strip()
        chapter_text = chapter_text[:12_000]

    published = None
    match = re.search(r"发布时间：([^\n]+)", text)
    if match:
        published = match.group(1).strip()

    return {
        "aweme_id": str(item.get("aweme_id") or ""),
        "nickname": nickname,
        "follower_count": follower_count,
        "creator_total_favorited": total_favorited,
        "published_text": published,
        "profile_path": profile_path,
        "visible_comments": parse_comments(comment_section),
        "comments_raw_text": comment_section[:12_000],
        "page_chapter_summary": chapter_text,
        "page_ok": bool(text and (comment_start >= 0 or author_match)),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    run_dir = args.run.expanduser().resolve()
    config = scout.load_config(args.config)
    state = scout.load_state()
    rows = scout.load_rows(run_dir / "search", "search_contents_*.json")
    items = scout.filter_search_rows(
        rows,
        config,
        set(map(str, state.get("processed_aweme_ids", []))),
    )
    if args.limit:
        items = items[: args.limit]

    output = run_dir / "页面公开数据.json"
    existing = scout.read_json(output, []) or []
    done = {str(row.get("aweme_id")): row for row in existing if row.get("aweme_id")}
    print(f"页面补数：共 {len(items)} 条，已完成 {len(done)} 条", flush=True)

    code = r'''(()=>{
      const text=document.body?.innerText||"";
      const nick=__NICKNAME__;
      const links=[...document.querySelectorAll('a[href*="/user/"]')];
      const hit=links.find(a=>(a.innerText||a.textContent||"").trim()===nick && !new URL(a.href).pathname.endsWith('/user/self'));
      return JSON.stringify({text,profile_path:hit?new URL(hit.href).pathname:""});
    })()'''

    for index, item in enumerate(items, 1):
        aweme_id = str(item.get("aweme_id") or "")
        if aweme_id in done and done[aweme_id].get("page_ok"):
            continue
        print(f"[页面补数 {index}/{len(items)}] {aweme_id}", flush=True)
        error = None
        record = None
        try:
            call(
                "navigate",
                {"url": f"https://www.douyin.com/video/{aweme_id}", "newTab": False},
                50,
            )
            time.sleep(3)
            page_code = code.replace(
                "__NICKNAME__", json.dumps(str(item.get("nickname") or ""), ensure_ascii=False)
            )
            result = call("evaluate", {"code": page_code}, 40)
            value = result.get("value")
            payload = json.loads(value) if isinstance(value, str) else {}
            record = parse_page(
                str(payload.get("text") or ""),
                item,
                str(payload.get("profile_path") or ""),
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        if record is None:
            record = {
                "aweme_id": aweme_id,
                "nickname": str(item.get("nickname") or ""),
                "page_ok": False,
                "error": error,
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        done[aweme_id] = record
        scout.write_json(output, list(done.values()))
        time.sleep(1)

    ok_count = sum(1 for row in done.values() if row.get("page_ok"))
    fan_count = sum(1 for row in done.values() if row.get("follower_count"))
    comment_count = sum(len(row.get("visible_comments") or []) for row in done.values())
    print(f"页面补数完成：页面 {ok_count}，粉丝数 {fan_count}，可见评论 {comment_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
