#!/usr/bin/env python3
"""Cross-platform environment audit for Douyin Benchmark Scout."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def memory_gb() -> float | None:
    try:
        if platform.system() == "Darwin":
            value = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, stderr=subprocess.DEVNULL)
            return int(value.strip()) / 1024**3
        if platform.system() == "Linux":
            line = next(x for x in Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemTotal:"))
            return int(line.split()[1]) / 1024**2
    except Exception:
        return None
    return None


def find_chrome() -> str | None:
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
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return next((str(path) for path in candidates if path.is_file()), None)


def module_available(python: str, module: str) -> bool:
    code = f"import importlib.util,sys;sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
    try:
        return subprocess.run([python, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    except Exception:
        return False


def find_module_runtime(candidates: list[Path], modules: tuple[str, ...]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file() and all(module_available(str(candidate), module) for module in modules):
            return candidate
    return None


def command_version(command: str, args: list[str]) -> tuple[str | None, tuple[int, ...]]:
    found = shutil.which(command)
    if not found:
        return None, ()
    try:
        output = subprocess.check_output([found, *args], text=True, stderr=subprocess.STDOUT, timeout=20).strip()
    except Exception:
        return found, ()
    match = __import__("re").search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", output)
    version = tuple(int(part or 0) for part in match.groups(default="0")) if match else ()
    return f"{found} ({output.splitlines()[0]})", version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="警告也返回非零状态")
    args = parser.parse_args()
    root = Path(os.environ.get("MEDIACRAWLER_ROOT", Path.home() / "MediaCrawler")).expanduser()
    crawler_python = Path(os.environ.get("MEDIACRAWLER_PYTHON", ""))
    if not crawler_python.is_file():
        candidates = [root / ".venv/bin/python", root / ".venv/Scripts/python.exe"]
        crawler_python = next((path for path in candidates if path.is_file()), Path(sys.executable))
    runtime_candidates = list(dict.fromkeys([
        crawler_python,
        Path(sys.executable),
        Path.home() / ".local/bin/python3.11",
        Path("/usr/bin/python3"),
    ]))
    workbook_python = find_module_runtime(runtime_candidates, ("openpyxl",))
    transcription_python = find_module_runtime(runtime_candidates, ("whisper", "torch"))
    browser_python = find_module_runtime(runtime_candidates, ("playwright",))
    total, used, free = shutil.disk_usage(Path.home())
    mem = memory_gb()
    results = []

    def add(name, status, detail, impact=""):
        results.append({"name": name, "status": status, "detail": detail, "impact": impact})

    add("操作系统", "pass", f"{platform.system()} {platform.release()} / {platform.machine()}")
    try:
        runtime_version = subprocess.check_output(
            [str(crawler_python), "-c", "import platform;print(platform.python_version())"],
            text=True,
            timeout=20,
        ).strip()
        runtime_tuple = tuple(map(int, runtime_version.split(".")[:2]))
    except Exception:
        runtime_version, runtime_tuple = platform.python_version(), sys.version_info[:2]
    add("Python运行环境", "pass" if runtime_tuple >= (3, 10) else "fail", f"{runtime_version} ({crawler_python})", "需要 Python 3.10+")
    add("系统Python", "pass" if sys.version_info >= (3, 10) else "warn", platform.python_version(), "系统Python可较旧，但正式流程应使用MediaCrawler虚拟环境")
    add("内存", "pass" if mem is None or mem >= 8 else "warn", f"{mem:.1f} GB" if mem else "无法自动读取", "低于8GB建议 base 模型、单任务运行")
    add("磁盘空间", "pass" if free >= 8 * 1024**3 else "fail", f"可用 {free / 1024**3:.1f} GB", "模型、视频和转录至少预留8GB")
    for command, required, impact in [
        ("git", True, "安装 MediaCrawler 和版本管理"),
        ("ffmpeg", True, "视频解码与 Whisper 转录"),
        ("ffprobe", False, "可选：更快读取视频时长；缺少时自动用 FFmpeg 校验"),
        ("libreoffice", False, "可选，用于无 Excel 环境的视觉预览"),
    ]:
        found = shutil.which(command)
        if command == "ffprobe" and not found:
            ffmpeg = shutil.which("ffmpeg")
            sibling = Path(ffmpeg).with_name("ffprobe") if ffmpeg else None
            found = str(sibling) if sibling and sibling.is_file() else None
        add(command, "pass" if found else ("fail" if required else "warn"), found or "未找到", impact)
    node_detail, node_version = command_version("node", ["--version"])
    add("node", "pass" if node_version >= (16,) else "fail", node_detail or "未找到", "MediaCrawler 的抖音采集依赖 Node.js 16+")
    chrome = find_chrome()
    add("Chrome/Chromium", "pass" if chrome else "fail", chrome or "未找到", "可见搜索和登录态兜底")
    add("MediaCrawler", "pass" if (root / "main.py").is_file() else "fail", str(root), "抖音搜索、详情和下载")
    in_project_venv = crawler_python.is_file() and (root / ".venv") in crawler_python.parents
    add("MediaCrawler虚拟环境", "pass" if in_project_venv else "warn", str(crawler_python), "建议使用项目独立虚拟环境")
    add("Excel运行环境", "pass" if workbook_python else "fail", str(workbook_python or "未找到 openpyxl"), "生成和校验 Excel")
    add("页面兜底环境", "pass" if browser_python else "fail", str(browser_python or "未找到 playwright"), "页面搜索兜底")
    add("本地转录环境", "pass" if transcription_python else "fail", str(transcription_python or "未在同一个 Python 中找到 whisper + torch"), "本地中文转录；两者必须位于同一环境")
    profile = root / "browser_data/cdp_dy_user_data_dir"
    add("独立浏览器资料目录", "pass" if profile.exists() else "warn", str(profile), "首次运行会创建并要求扫码登录；不得提交到GitHub")
    accel = "CPU"
    if transcription_python:
        probe = "import torch;print('CUDA' if torch.cuda.is_available() else ('MPS' if getattr(torch.backends,'mps',None) and torch.backends.mps.is_available() else 'CPU'))"
        try:
            accel = subprocess.check_output([str(transcription_python), "-c", probe], text=True, timeout=30).strip()
        except Exception:
            pass
    add("转录加速", "pass", accel, "默认低占用：CPU/MPS/CUDA均限制单任务")
    # 读不到内存时也选低占用；宁可慢一点，不让新手电脑无故发热。
    recommendation = "low" if mem is None or mem < 16 else "balanced"
    report = {
        "schema_version": 1,
        "ready": not any(row["status"] == "fail" for row in results),
        "recommended_resource_mode": recommendation,
        "recommended_whisper_model": "base" if recommendation == "low" else "small",
        "checks": results,
        "install_hints": {
            "macOS": "安装 Python 3.10+、Git、Node.js 16+、Google Chrome 和 FFmpeg，再运行 bootstrap.py --apply",
            "Windows": "安装 Python 3.10+、Git、Node.js 16+、Google Chrome 和 FFmpeg，再运行 bootstrap.py --apply",
            "Linux": "用系统包管理器安装 Python 3.10+、git、Node.js 16+、Chrome/Chromium、ffmpeg，再运行 bootstrap.py --apply",
        },
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        icons = {"pass": "✓", "warn": "!", "fail": "✗"}
        for row in results:
            print(f"{icons[row['status']]} {row['name']}：{row['detail']}")
        print(f"建议运行模式：{recommendation}；Whisper：{report['recommended_whisper_model']}")
        failed = [row["name"] for row in results if row["status"] == "fail"]
        if failed:
            print("\n还不能正式运行，缺少：" + "、".join(failed))
            print(report["install_hints"].get(platform.system(), "请按各工具官网说明安装后重新体检。"))
        else:
            print("\n环境已具备正式运行条件。首次采集时请本人扫码登录。")
    if not report["ready"] or (args.strict and any(row["status"] == "warn" for row in results)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
