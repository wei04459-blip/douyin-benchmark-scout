#!/usr/bin/env python3
"""在已登录 Chrome 页面内补抓创作者中心返回但直连失败的视频。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path


DEFAULT_OUTPUT = Path.home() / ".douyin-benchmark-scout" / "own-account"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def start_browser_job(chrome, work: dict, *, probe: bool) -> None:
    urls = json.dumps(work.get("_media_urls") or [], ensure_ascii=False)
    work_id = str(work["aweme_id"])
    download_name = f"douyin_{work_id}.mp4"
    js = f"""
(() => {{
  window.__codexDouyinBrowserDownload = {{state: 'running'}};
  const urls = {urls};
  (async () => {{
    const attempts = [];
    for (const url of urls) {{
      try {{
        const response = await fetch(url, {{credentials: 'include'}});
        attempts.push({{host: new URL(url).host, status: response.status,
          type: response.headers.get('content-type') || ''}});
        if (!response.ok) continue;
        if ({str(probe).lower()}) {{
          window.__codexDouyinBrowserDownload = {{state: 'done', probe: true, attempts}};
          return;
        }}
        const blob = await response.blob();
        if (blob.size < 100000) continue;
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = {json.dumps(download_name)};
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 120000);
        window.__codexDouyinBrowserDownload = {{state: 'done', probe: false,
          size: blob.size, attempts}};
        return;
      }} catch (error) {{
        attempts.push({{host: (() => {{ try {{ return new URL(url).host; }} catch {{ return 'unknown'; }} }})(),
          error: String(error)}});
      }}
    }}
    window.__codexDouyinBrowserDownload = {{state: 'error', attempts}};
  }})();
  return JSON.stringify({{started: true, candidates: urls.length}});
}})()
"""
    result = chrome._js(js, timeout=20)
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))


def poll_browser_job(chrome, timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = chrome._js(
            "JSON.stringify(window.__codexDouyinBrowserDownload || {state:'missing'})",
            timeout=20,
        )
        if isinstance(result, dict) and result.get("state") in {"done", "error"}:
            return result
        time.sleep(1)
    raise TimeoutError("等待 Chrome 下载任务超时。")


def wait_for_download(work_id: str, downloads: Path, timeout: int = 180) -> Path:
    target = downloads / f"douyin_{work_id}.mp4"
    partial = downloads / f"douyin_{work_id}.mp4.crdownload"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if target.is_file() and target.stat().st_size > 100000 and not partial.exists():
            return target
        time.sleep(1)
    raise TimeoutError(f"浏览器下载文件未出现：{target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("aweme_id")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    parser.add_argument(
        "--adapter-dir",
        type=Path,
        default=Path(os.environ.get("DOUYIN_BROWSER_ADAPTER_DIR", "")),
        help="包含 douyin_creator_content.py 与 chrome_ctrl.py 的本地适配器目录",
    )
    args = parser.parse_args()

    adapter_dir = args.adapter_dir.expanduser()
    if not (adapter_dir / "douyin_creator_content.py").is_file() or not (adapter_dir / "chrome_ctrl.py").is_file():
        raise RuntimeError("浏览器桥接是可选能力；请用 --adapter-dir 指向兼容的本地适配器，登录信息不会被导出。")
    content = load_module("douyin_creator_content", adapter_dir / "douyin_creator_content.py")
    chrome = load_module("chrome_ctrl", adapter_dir / "chrome_ctrl.py")
    works = content.fetch_works(pages=10, count=12, timeout=60)
    work = next((row for row in works if row["aweme_id"] == str(args.aweme_id)), None)
    if work is None:
        raise RuntimeError(f"找不到作品：{args.aweme_id}")
    start_browser_job(chrome, work, probe=args.probe)
    result = poll_browser_job(chrome)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if result.get("state") != "done":
        return 1
    if args.probe:
        return 0
    downloaded = wait_for_download(str(args.aweme_id), args.downloads.expanduser())
    destination = args.output_root / str(args.aweme_id) / "原视频.mp4"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(downloaded), destination)
    print(destination, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
