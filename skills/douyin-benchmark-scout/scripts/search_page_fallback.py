#!/usr/bin/env python3
"""当 MediaCrawler 搜索接口假空时，复用抖音真实搜索页的请求结果。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import shutil
import time
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from playwright.async_api import async_playwright


SEARCH_ENDPOINT = "/aweme/v1/web/general/search/single/"
WEBBRIDGE_ENDPOINT = "http://127.0.0.1:10086/command"
WEBBRIDGE_SESSION = "douyin-competitor-20260804"


def discover_chrome() -> str | None:
    configured = os.environ.get("CHROME_PATH")
    if configured and Path(configured).is_file():
        return configured
    candidates = []
    if platform.system() == "Darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    elif platform.system() == "Windows":
        for root in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if root:
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                return found
    found = next((str(path) for path in candidates if path.is_file()), None)
    return found


def first_url(value: dict) -> str:
    urls = value.get("url_list", []) if isinstance(value, dict) else []
    return str(urls[-1]) if urls else ""


def mask_nickname(value: str) -> str:
    value = str(value or "")
    if len(value) <= 2:
        return value[:1] + "*" if value else ""
    return value[:1] + "***" + value[-1:]


def convert_aweme(aweme: dict, keyword: str) -> dict:
    author = aweme.get("author") or {}
    statistics = aweme.get("statistics") or {}
    video = aweme.get("video") or {}
    cover = video.get("raw_cover") or video.get("origin_cover") or {}
    play = (
        video.get("play_addr_h264")
        or video.get("play_addr_256")
        or video.get("play_addr")
        or {}
    )
    uid = str(author.get("uid") or "")
    aweme_id = str(aweme.get("aweme_id") or "")
    return {
        "aweme_id": aweme_id,
        "aweme_type": str(aweme.get("aweme_type") or "0"),
        "title": str(aweme.get("desc") or ""),
        "desc": str(aweme.get("desc") or ""),
        "create_time": aweme.get("create_time"),
        "creator_hash": hashlib.sha256(uid.encode()).hexdigest()[:16] if uid else "",
        "nickname": mask_nickname(author.get("nickname")),
        "liked_count": str(statistics.get("digg_count") or 0),
        "collected_count": str(statistics.get("collect_count") or 0),
        "comment_count": str(statistics.get("comment_count") or 0),
        "share_count": str(statistics.get("share_count") or 0),
        "last_modify_ts": int(time.time() * 1000),
        "aweme_url": f"https://www.douyin.com/video/{aweme_id}",
        "cover_url": first_url(cover),
        "video_download_url": first_url(play),
        "music_download_url": first_url((aweme.get("music") or {}).get("play_url") or {}),
        "note_download_url": "",
        "source_keyword": keyword,
        "matched_query": keyword,
        "search_channel": "page_ui_fallback",
    }


def webbridge_call(action: str, args: dict, timeout: int = 45) -> dict:
    body = json.dumps(
        {"action": action, "args": args, "session": WEBBRIDGE_SESSION},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        WEBBRIDGE_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        envelope = json.loads(response.read().decode("utf-8"))
    if not envelope.get("ok"):
        raise RuntimeError(str((envelope.get("error") or {}).get("message") or envelope))
    return envelope.get("data") or {}


def convert_webbridge_item(item: dict, keyword: str) -> dict:
    uid = str(item.get("uid") or item.get("sec_uid") or "")
    aweme_id = str(item.get("id") or "")
    return {
        "aweme_id": aweme_id,
        "aweme_type": str(item.get("aweme_type") or "0"),
        "title": str(item.get("title") or ""),
        "desc": str(item.get("title") or ""),
        "create_time": item.get("create_time"),
        "creator_hash": hashlib.sha256(uid.encode()).hexdigest()[:16] if uid else "",
        "nickname": str(item.get("nickname") or ""),
        "liked_count": str(item.get("liked") or 0),
        "collected_count": str(item.get("collected") or 0),
        "comment_count": str(item.get("comments") or 0),
        "share_count": str(item.get("shares") or 0),
        "last_modify_ts": int(time.time() * 1000),
        "aweme_url": f"https://www.douyin.com/video/{aweme_id}",
        "cover_url": str(item.get("cover_url") or ""),
        "video_download_url": str(item.get("play_url") or ""),
        "music_download_url": "",
        "note_download_url": "",
        "source_keyword": keyword,
        "matched_query": keyword,
        "search_channel": "kimi_webbridge",
    }


async def collect_with_webbridge(keyword: str, limit: int) -> list[dict]:
    tabs = await asyncio.to_thread(webbridge_call, "list_tabs", {}, 20)
    has_tabs = bool(tabs.get("tabs"))
    url = f"https://www.douyin.com/search/{quote(keyword)}?type=general"
    navigate_args = {"url": url, "newTab": not has_tabs}
    if not has_tabs:
        navigate_args["group_title"] = "抖音竞品抓取"
    await asyncio.to_thread(webbridge_call, "navigate", navigate_args, 45)

    await asyncio.sleep(5)
    for _ in range(5):
        await asyncio.to_thread(
            webbridge_call,
            "evaluate",
            {"code": "window.scrollTo(0,document.body.scrollHeight); true"},
            20,
        )
        await asyncio.sleep(1.8)

    urls_result = await asyncio.to_thread(
        webbridge_call,
        "evaluate",
        {
            "code": r'''JSON.stringify([...new Set(performance.getEntriesByType("resource")
              .map(e=>e.name).filter(x=>x.includes("/aweme/v1/web/general/search/single/")))])'''
        },
        30,
    )
    raw_urls = urls_result.get("value")
    urls = json.loads(raw_urls) if isinstance(raw_urls, str) else []
    by_id: dict[str, dict] = {}
    for endpoint_url in urls:
        js = f'''(async()=>{{
      const u={json.dumps(endpoint_url)};
      const byId={{}};
      try{{
        const j=await (await fetch(u,{{credentials:"include"}})).json();
        for(const item of (j.data||[])){{
          const a=item.aweme_info||item.aweme_mix_info?.mix_items?.[0];
          if(!a?.aweme_id) continue;
          const author=a.author||{{}};
          const stats=a.statistics||{{}};
          const video=a.video||{{}};
          const play=video.play_addr_h264||video.play_addr_256||video.play_addr||{{}};
          const cover=video.raw_cover||video.origin_cover||{{}};
          byId[a.aweme_id]={{
            id:String(a.aweme_id),aweme_type:String(a.aweme_type||0),title:String(a.desc||""),
            create_time:a.create_time,duration_ms:video.duration||0,nickname:String(author.nickname||""),
            uid:String(author.uid||""),sec_uid:String(author.sec_uid||""),
            liked:stats.digg_count||0,comments:stats.comment_count||0,
            collected:stats.collect_count||0,shares:stats.share_count||0,
            play_url:(play.url_list||[]).slice(-1)[0]||"",
            cover_url:(cover.url_list||[]).slice(-1)[0]||""
          }};
        }}
      }}catch(_e){{}}
      return JSON.stringify({{items:Object.values(byId)}});
    }})()'''
        result = await asyncio.to_thread(
            webbridge_call, "evaluate", {"code": js}, 45
        )
        value = result.get("value")
        payload = json.loads(value) if isinstance(value, str) else {}
        for item in payload.get("items") or []:
            if item.get("id"):
                by_id[str(item["id"])] = item
        if len(by_id) >= limit:
            break

    converted = [
        convert_webbridge_item(item, keyword)
        for item in by_id.values()
        if item.get("id")
    ]
    return converted[:limit]

    js = r'''(async()=>{
      const urls=[...new Set(performance.getEntriesByType("resource")
        .map(e=>e.name).filter(x=>x.includes("/aweme/v1/web/general/search/single/")))];
      const byId={};
      for(const u of urls){
        try{
          const j=await (await fetch(u,{credentials:"include"})).json();
          for(const item of (j.data||[])){
            const a=item.aweme_info||item.aweme_mix_info?.mix_items?.[0];
            if(!a?.aweme_id) continue;
            const author=a.author||{};
            const stats=a.statistics||{};
            const video=a.video||{};
            const play=video.play_addr_h264||video.play_addr_256||video.play_addr||{};
            const cover=video.raw_cover||video.origin_cover||{};
            byId[a.aweme_id]={
              id:String(a.aweme_id),aweme_type:String(a.aweme_type||0),title:String(a.desc||""),
              create_time:a.create_time,duration_ms:video.duration||0,nickname:String(author.nickname||""),
              uid:String(author.uid||""),sec_uid:String(author.sec_uid||""),
              liked:stats.digg_count||0,comments:stats.comment_count||0,
              collected:stats.collect_count||0,shares:stats.share_count||0,
              play_url:(play.url_list||[]).slice(-1)[0]||"",
              cover_url:(cover.url_list||[]).slice(-1)[0]||""
            };
          }
        }catch(_e){}
      }
      return JSON.stringify({items:Object.values(byId)});
    })()'''
    result = await asyncio.to_thread(webbridge_call, "evaluate", {"code": js}, 60)
    value = result.get("value")
    payload = json.loads(value) if isinstance(value, str) else {}
    converted = [
        convert_webbridge_item(item, keyword)
        for item in payload.get("items") or []
        if item.get("id")
    ]
    return converted[:limit]


async def collect(keyword: str, output: Path, limit: int, chrome_path: str | None, profile_path: Path) -> int:
    try:
        webbridge_rows = await collect_with_webbridge(keyword, limit)
    except Exception as exc:
        print(
            "Kimi WebBridge 搜索失败；保留当前已登录标签页，不再启动或关闭其他浏览器："
            f"{type(exc).__name__}: {exc}"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("[]\n", encoding="utf-8")
        return 2
    if webbridge_rows:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(webbridge_rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Kimi WebBridge：{keyword} 返回 {len(webbridge_rows)} 条")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("[]\n", encoding="utf-8")
    print(f"Kimi WebBridge：{keyword} 返回 0 条；保留当前标签页，不启动旧浏览器")
    return 2

    payloads: list[dict] = []
    response_tasks: list[asyncio.Task] = []
    search_response_urls: list[str] = []

    async def capture(response) -> None:
        if "search" in response.url:
            search_response_urls.append(response.url)
        if SEARCH_ENDPOINT not in response.url:
            return
        try:
            payload = await response.json()
        except Exception:
            return
        if isinstance(payload, dict):
            payloads.append(payload)

    async with async_playwright() as playwright:
        launch_options = dict(
            headless=False,
            viewport={"width": 1440, "height": 960},
            args=["--disable-blink-features=AutomationControlled"],
        )
        if chrome_path:
            launch_options["executable_path"] = chrome_path
        context = await playwright.chromium.launch_persistent_context(
            str(profile_path),
            **launch_options,
        )
        page = context.pages[0] if context.pages else await context.new_page()
        page.on("response", lambda response: response_tasks.append(asyncio.create_task(capture(response))))
        await page.goto(
            f"https://www.douyin.com/search/{quote(keyword)}?type=general",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(8_000)
        for _ in range(2):
            await page.mouse.wheel(0, 1800)
            await page.wait_for_timeout(2_000)
        if response_tasks:
            await asyncio.gather(*response_tasks, return_exceptions=True)
        anchor_count = await page.locator('a[href*="/video/"]').count()
        page_title = await page.title()
        await context.close()

    rows: dict[str, dict] = {}
    for payload in payloads:
        for item in payload.get("data") or []:
            aweme = item.get("aweme_info")
            if not aweme:
                mix_items = (item.get("aweme_mix_info") or {}).get("mix_items") or []
                aweme = mix_items[0] if mix_items else None
            if not isinstance(aweme, dict):
                continue
            row = convert_aweme(aweme, keyword)
            if row["aweme_id"]:
                rows[row["aweme_id"]] = row
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(list(rows.values()), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"页面搜索兜底：{keyword} 返回 {len(rows)} 条")
    if not rows:
        print(f"  页面标题：{page_title}；视频链接：{anchor_count}；搜索请求：{len(search_response_urls)}")
        interesting = [
            url for url in search_response_urls
            if "aweme/v1" in url or "/api/" in url or "search/single" in url
        ]
        for url in (interesting or search_response_urls)[:20]:
            print(f"  {urlsplit(url).path}")
    return 0 if rows else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--chrome-path", default=discover_chrome())
    parser.add_argument(
        "--profile-path",
        type=Path,
        default=Path.home() / ".douyin-benchmark-scout" / "browser-profile",
    )
    args = parser.parse_args()
    return asyncio.run(collect(args.keyword, args.output, args.limit, args.chrome_path, args.profile_path.expanduser()))


if __name__ == "__main__":
    raise SystemExit(main())
