#!/usr/bin/env python3
"""Build a source-grounded first-pass analysis from every full transcript and page capture."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import run as scout


TIME_LINE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def title_without_tags(title: str) -> str:
    value = re.sub(r"#[^\s#]+", "", clean(title))
    return clean(value).strip("，。！？、# ")


def route(title: str, transcript: str) -> tuple[str, str]:
    haystack = (title + " " + transcript[:1200]).lower()
    if any(word in haystack for word in ("教程", "保姆级", "零基础", "手把手", "学会", "使用方法", "怎么用")):
        return "AI教程/工具实操", "教程实操"
    if any(word in haystack for word in ("焦虑", "害怕", "淘汰", "失业", "裁员", "恐慌")):
        return "AI焦虑/职业变化", "情绪共鸣"
    if any(word in haystack for word in ("搞钱", "赚钱", "变现", "副业", "收入", "生意")):
        return "AI搞钱/变现", "项目或观点拆解"
    if any(word in haystack for word in ("创业", "一人公司", "产品", "商业", "老板")):
        return "AI创业/一人公司", "创业认知"
    if any(word in haystack for word in ("工作流", "自动化", "提效", "sop", "agent", "智能体")):
        return "AI工作流/效率", "方法论"
    if any(word in haystack for word in ("认知", "普通人", "时代", "趋势", "未来", "机会")):
        return "AI认知/趋势", "认知观点"
    return "AI干货/应用", "知识分享"


def chapter_structure(page_text: str) -> str:
    lines = [line.strip() for line in str(page_text or "").splitlines() if line.strip()]
    headings = []
    for index, line in enumerate(lines[:-1]):
        if TIME_LINE.match(line):
            candidate = lines[index + 1]
            if not TIME_LINE.match(candidate) and len(candidate) <= 40:
                headings.append(candidate)
    headings = list(dict.fromkeys(headings))[:7]
    if headings:
        return " → ".join(headings)
    return "抛出问题或结果 → 解释核心观点 → 给出步骤/案例 → 总结并引导行动"


def emotion(title: str) -> str:
    if re.search(r"焦虑|害怕|淘汰|失业|裁员|别慌|危机", title):
        return "危机感与焦虑共鸣，随后用解释或方法缓解"
    if re.search(r"赚钱|搞钱|收入|风口|机会|红利", title):
        return "收益期待、机会感与行动冲动"
    if re.search(r"零基础|小白|保姆级|学会|教程|免费", title):
        return "降低门槛，制造“我也能学会”的确定感"
    if re.search(r"真相|认知|不要|远离|真正|到底", title):
        return "反常识和认知纠偏，激发好奇与讨论"
    return "好奇、实用期待与轻度紧迫感"


def compact_summary(page_text: str, transcript: str) -> str:
    page = clean(str(page_text or "").replace("章节要点", ""))
    if page:
        return page[:420]
    body = clean(transcript)
    return body[:420]


def viral_reason(item: dict, title: str) -> str:
    level = str(item.get("breakout_level") or "")
    ratio = float(item.get("like_fan_ratio") or 0)
    signals = []
    if level.startswith("S"):
        signals.append(f"低粉高爆，赞粉比约 {ratio:.1f} 倍")
    elif level.startswith("A"):
        signals.append(f"中小账号明显破圈，赞粉比约 {ratio:.0%}")
    else:
        signals.append("互动量有可观察样本价值")
    if re.search(r"零基础|小白|保姆级|一条视频|分钟|学会", title):
        signals.append("承诺具体且学习门槛低")
    if re.search(r"赚钱|搞钱|收入|风口|机会", title):
        signals.append("直接命中收益与机会需求")
    if re.search(r"焦虑|害怕|淘汰|失业|裁员", title):
        signals.append("命中 AI 焦虑并形成情绪张力")
    if re.search(r"真正|到底|别再|远离|不要|真相", title):
        signals.append("反常识措辞制造认知冲突")
    return "；".join(signals[:3])


def migration(track: str, title: str) -> str:
    core = title_without_tags(title)[:80]
    if track.startswith("AI教程"):
        return f"保留“普通人跟做”的低门槛结构，用用户已验证的工具或工作流复刻：{core}"
    if track.startswith("AI焦虑"):
        return f"从非技术大学生视角回应同类焦虑，不装专家；先讲真实担忧，再给一个已实践动作：{core}"
    if track.startswith("AI搞钱"):
        return f"保留收益问题，但明确尚在验证，不编造收入；改成项目筛选或踩坑记录：{core}"
    if track.startswith("AI创业"):
        return f"结合一人公司与社群运营的真实进度，讲一次具体尝试而非成功学：{core}"
    if track.startswith("AI工作流"):
        return f"换成已跑通的晨报、飞书推送或写作工作流，展示输入、过程和结果：{core}"
    return f"用“普通人比别人早行动一步”的身份重讲，加入亲测证据与下一步动作：{core}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_dir = args.run.expanduser().resolve()
    manifest = scout.read_json(run_dir / "待分析数据.json", {}) or {}
    items = manifest.get("items", [])
    result = {"schema_version": 1, "items": {}}
    missing = []
    for item in items:
        aweme_id = str(item.get("aweme_id") or "")
        transcript_path = Path(item.get("transcript_path") or "")
        if not transcript_path.is_file():
            missing.append(aweme_id)
            continue
        transcript = transcript_path.read_text(encoding="utf-8", errors="ignore")
        title = clean(item.get("title") or item.get("desc"))
        track, content_type = route(title, transcript)
        hashtags = list(dict.fromkeys(re.findall(r"#[^\s#]+", title)))
        source_keywords = item.get("source_keywords") or []
        topics = " ".join(hashtags[:8]) or "、".join(map(str, source_keywords))
        hook = clean(transcript)[:220] or title[:220]
        summary = compact_summary(item.get("page_chapter_summary") or "", transcript)
        result["items"][aweme_id] = {
            "track": track,
            "topics": topics or track,
            "type": content_type,
            "topic_summary": title_without_tags(title)[:180] or title[:180],
            "hook": hook,
            "structure": chapter_structure(item.get("page_chapter_summary") or ""),
            "emotion": emotion(title),
            "summary": summary,
            "viral": viral_reason(item, title),
            "migration": migration(track, title),
        }
    if missing:
        raise RuntimeError("以下视频尚未完成转录：" + ", ".join(missing))
    output = (args.output or run_dir / "AI拆解_机器初稿.json").expanduser().resolve()
    scout.write_json(output, result)
    print(f"已生成待审核的机器初稿，不能直接完成研究：{output}（{len(result['items'])} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
