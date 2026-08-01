#!/usr/bin/env python3
"""通过已登录 Chrome 的页面内 fetch + 分块桥接补抓视频，不导出 Cookie。"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import sys
import time
from pathlib import Path


DEFAULT_OUTPUT = Path.home() / ".douyin-benchmark-scout" / "own-account"
CHUNK_CHARS = 524288  # 必须是 4 的倍数，便于逐块 base64 解码。


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def start_fetch(chrome, work: dict) -> None:
    urls = json.dumps(work.get("_media_urls") or [], ensure_ascii=False)
    js = f"""
(() => {{
  window.__codexDouyinBridge = {{state: 'running'}};
  const urls = {urls};
  (async () => {{
    const attempts = [];
    for (const url of urls) {{
      try {{
        const response = await fetch(url, {{credentials: 'include'}});
        attempts.push({{host: new URL(url).host, status: response.status,
          type: response.headers.get('content-type') || ''}});
        if (!response.ok) continue;
        const blob = await response.blob();
        if (blob.size < 100000) continue;
        const reader = new FileReader();
        const data = await new Promise((resolve, reject) => {{
          reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
          reader.onerror = () => reject(reader.error || new Error('FileReader failed'));
          reader.readAsDataURL(blob);
        }});
        window.__codexDouyinBridge = {{state: 'done', data, size: blob.size,
          length: data.length, attempts}};
        return;
      }} catch (error) {{
        attempts.push({{host: (() => {{ try {{ return new URL(url).host; }} catch {{ return 'unknown'; }} }})(),
          error: String(error)}});
      }}
    }}
    window.__codexDouyinBridge = {{state: 'error', attempts}};
  }})();
  return JSON.stringify({{started: true, candidates: urls.length}});
}})()
"""
    result = chrome._js(js, timeout=20)
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))


def wait_ready(chrome, timeout: int = 240) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = chrome._js(
            "JSON.stringify((() => { const j=window.__codexDouyinBridge||{state:'missing'}; "
            "return {state:j.state,size:j.size||0,length:j.length||0,attempts:j.attempts||[]}; })())",
            timeout=20,
        )
        if isinstance(result, dict) and result.get("state") in {"done", "error"}:
            return result
        time.sleep(1)
    raise TimeoutError("等待 Chrome 读取视频超时。")


def copy_chunks(chrome, target: Path, length: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".mp4.part")
    with partial.open("wb") as output:
        for offset in range(0, length, CHUNK_CHARS):
            end = min(length, offset + CHUNK_CHARS)
            result = chrome._js(
                f"JSON.stringify({{chunk:window.__codexDouyinBridge.data.slice({offset},{end})}})",
                timeout=30,
            )
            chunk = result.get("chunk") if isinstance(result, dict) else None
            if not isinstance(chunk, str):
                raise RuntimeError(f"视频分块读取失败：{offset}-{end}")
            output.write(base64.b64decode(chunk))
            if offset == 0 or end == length or (offset // CHUNK_CHARS) % 20 == 0:
                print(f"    本地写入 {end * 100 // length}%", flush=True)
    if partial.stat().st_size < 100000:
        raise RuntimeError("桥接后的视频文件过小。")
    partial.replace(target)
    chrome._js("window.__codexDouyinBridge={state:'cleared'}; 'ok'", timeout=20)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("aweme_id", nargs="+")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
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
    work_by_id = {row["aweme_id"]: row for row in works}
    failures = []
    for index, work_id in enumerate(args.aweme_id, 1):
        print(f"补抓 {index}/{len(args.aweme_id)}：{work_id}", flush=True)
        work = work_by_id.get(str(work_id))
        if work is None:
            failures.append({"aweme_id": work_id, "error": "找不到作品"})
            continue
        target = args.output_root / str(work_id) / "原视频.mp4"
        if target.is_file() and target.stat().st_size > 100000:
            print("    已存在，跳过。", flush=True)
            continue
        try:
            start_fetch(chrome, work)
            ready = wait_ready(chrome)
            print(json.dumps({key: ready.get(key) for key in ("state", "size", "attempts")}, ensure_ascii=False), flush=True)
            if ready.get("state") != "done":
                raise RuntimeError(str(ready.get("attempts")))
            copy_chunks(chrome, target, int(ready["length"]))
            print(f"    已保存：{target}", flush=True)
        except Exception as exc:
            failures.append({"aweme_id": work_id, "error": str(exc)})
            print(f"    失败：{exc}", flush=True)
    if failures:
        print(json.dumps({"failures": failures}, ensure_ascii=False), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
