#!/usr/bin/env python3
"""Chinese first-run wizard for people who do not use the terminal."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
DATA_ROOT = Path(os.environ.get("DOUYIN_SCOUT_HOME", Path.home() / ".douyin-benchmark-scout")).expanduser()
CONFIG = Path(os.environ.get("DOUYIN_SCOUT_CONFIG", DATA_ROOT / "config.json")).expanduser()


def run(script: str, *args: str) -> int:
    return subprocess.run([sys.executable, str(HERE / script), *args], check=False).returncode


def ensure_python() -> bool:
    if sys.version_info >= (3, 10):
        return True
    print(f"当前 Python 是 {platform.python_version()}，需要 3.10 或更高版本。")
    print("请安装新版 Python 后重新双击启动；本次没有修改任何数据。")
    return False


def init_config() -> dict:
    if not CONFIG.is_file():
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text((SKILL / "assets" / "example-config.json").read_text(encoding="utf-8"), encoding="utf-8")
        print(f"已创建个人配置：{CONFIG}")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def first_setup() -> int:
    print("\n首次设置分三步：确认使用边界 → 环境体检 → 生成个人配置。")
    print("MediaCrawler 的上游许可证限制商业用途；平台规则和内容权利仍需遵守。")
    answer = input("你确认仅在许可证和平台规则允许的范围内使用吗？输入‘确认’继续：").strip()
    if answer != "确认":
        print("已停止，没有安装或抓取任何内容。")
        return 2
    config = init_config()
    config["compliance_acknowledged"] = True
    config["resource_mode"] = "low"
    config.setdefault("transcription", {}).update({"model": "base", "threads": 1})
    save_config(config)
    result = run("doctor.py")
    if result:
        print("\n环境还不完整。上面的叉号就是需要补齐的项目。")
        print("可回到菜单选择“查看安装计划”；安装完成后再体检，不会重复抓取。")
    return result


def collect_once() -> int:
    config = init_config()
    if not config.get("compliance_acknowledged"):
        print("请先完成“首次设置”，确认许可证和平台边界。")
        return 2
    if run("doctor.py"):
        print("环境体检未通过，已停止；没有开始抓取。")
        return 2
    raw = input("输入本轮关键词，用中文逗号或英文逗号分隔（直接回车使用轮换词库）：").strip()
    per_word = input("每个词至少保留几条？直接回车默认 1：").strip() or "1"
    keywords = raw.replace("，", ",")
    command = ["collect", "--per-keyword", per_word]
    if keywords:
        command.extend(["--keywords", keywords])
        count = len([item for item in keywords.split(",") if item.strip()])
        command.extend(["--download-limit", str(max(count * int(per_word), count))])
    print("\n即将以单并发、Whisper base、1 个线程运行。首次搜索会打开浏览器，请本人扫码登录。")
    if input("输入‘开始’继续：").strip() != "开始":
        print("已取消。")
        return 0
    return run("run.py", *command)


def latest_result() -> int:
    workbooks = sorted((DATA_ROOT / "cache" / "runs").rglob("竞品选题分析_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True) if (DATA_ROOT / "cache" / "runs").exists() else []
    if not workbooks:
        print("还没有最终 Excel。若已有口播拆解，请在 Codex 中说：继续完成上次批次。")
        return 1
    print(f"最新 Excel：{workbooks[0]}")
    print(f"对应运行目录：{workbooks[0].parent}")
    return 0


def migrate() -> int:
    source = input("把旧 benchmark-scout 缓存目录拖到这里，然后回车：").strip().strip('"')
    if not source:
        print("未提供路径，已取消。")
        return 0
    if run("migrate_legacy.py", "--source", source):
        return 2
    if input("确认上面的迁移预览？输入‘迁移’继续：").strip() != "迁移":
        print("已取消，旧数据未变。")
        return 0
    return run("migrate_legacy.py", "--source", source, "--copy-transcripts", "--apply")


def menu() -> int:
    actions = {
        "1": ("首次设置（推荐第一次选）", first_setup),
        "2": ("环境体检", lambda: run("doctor.py")),
        "3": ("查看安装计划（不会自动安装）", lambda: run("bootstrap.py")),
        "4": ("低占用跑一轮", collect_once),
        "5": ("查看进度与下一批关键词", lambda: run("run.py", "status")),
        "6": ("找到最新 Excel", latest_result),
        "7": ("迁移旧数据", migrate),
    }
    print("\n抖音竞品选题侦察 · 新手入口")
    for key, (label, _) in actions.items():
        print(f"{key}. {label}")
    choice = input("请选择数字：").strip()
    if choice not in actions:
        print("没有这个选项，本次未做任何更改。")
        return 2
    return actions[choice][1]()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="自动化验收：只创建配置并输出状态")
    args = parser.parse_args()
    if not ensure_python():
        return 2
    if args.check:
        config = init_config()
        assert config["transcription"]["threads"] == 1
        assert config["transcription"]["model"] == "base"
        print("FIRST_RUN_CHECK_OK")
        return 0
    try:
        return menu()
    except (KeyboardInterrupt, EOFError):
        print("\n已安全退出。")
        return 130
    except Exception as exc:
        print(f"\n没有完成：{exc}")
        print("已保留断点。可在 Codex 中说‘继续上次失败的抖音竞品批次’。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
