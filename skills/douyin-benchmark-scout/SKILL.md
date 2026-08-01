---
name: douyin-benchmark-scout
description: Run an end-to-end, resumable Douyin competitor-research workflow covering multi-keyword search, false-empty recovery, public video and creator metrics, quota filtering, download, local Whisper transcription, S/A/B/C low-follower breakout classification, AI script analysis, verified Excel output, focus-account extraction, and safe source-video cleanup. Use when the user asks to 抓取抖音竞品、跑一轮多词、找低粉高爆、下载并转录对标视频、修复关键词空结果、更新竞品Excel、分析爆款口播/钩子/结构、生成可拍选题，or package/recover this workflow on another computer.
---

# 抖音竞品选题侦察

把抖音公开竞品研究当成可审计的数据流水线。搜索成功不等于任务成功；必须完成逐词配额、转录、分析、工作簿校验和安全清理。

## 对新手的交互原则

- 先替用户执行体检并翻译结果，不让用户自己猜命令或错误信息。
- 安装、扫码、合规确认和选择关键词之外，能由代理完成的步骤直接完成。
- 默认低占用，不因追求速度提高并发、Whisper 模型或线程数。
- 失败时保留断点，明确告诉用户“已完成到哪、什么没完成、继续时会不会重复”。
- 最终只把可打开的 Excel、数量摘要和需要用户判断的内容交付出来。

## 第一次运行

1. 先阅读 `references/privacy-compliance.md`。若用途与上游许可证或平台规则冲突，暂停并说明限制。
2. 新手优先运行 `python scripts/start.py`，按中文菜单完成合规确认、体检、配置和第一次低占用批次。macOS 可双击 `开始使用.command`，Windows 可双击 `开始使用.bat`。
3. 缺依赖时先运行 `python scripts/bootstrap.py` 查看安装计划。只有用户明确允许联网安装后才加 `--apply`。
4. 默认配置会复制到 `~/.douyin-benchmark-scout/config.json`；不要修改 Skill 内的示例文件来保存登录信息或私人路径。
5. 首次搜索由用户本人扫码登录。不得导出 Cookie 或浏览器资料。

## 标准流程

### 1. 明确批次

确认关键词、时间窗口、每词配额、总下载上限和输出位置。用户说“跑一轮”时使用配置中的关键词轮换；用户给出关键词时精确使用，不把宽泛根词结果混入正式批次。

运行前查看状态：

```bash
python scripts/run.py status
```

### 2. 采集、下载和转录

正式多词示例：

```bash
python scripts/run.py collect \
  --keywords "AI自媒体,AI搞钱,AI创业" \
  --per-keyword 2 \
  --download-limit 6
```

默认单并发、可见搜索、关键词间隔和低资源转录。不要擅自提高并发。默认使用 Whisper `base`、`threads: 1`，一次只处理一条。

搜索出现空结果时，完整执行 `references/search-reliability.md`。任何关键词未达配额都视为整批未完成；保留检查点并恢复，不得伪造空关键词成功状态。

### 3. 完成 AI 拆解

读取运行目录中的 `待分析数据.json`、每条 `transcripts/<作品ID>/<作品ID>.txt` 和 `AI拆解模板.json`。先处理 S，再处理 A，最后 B/C。

按 `references/analysis-schema.md` 填写全部字段。保留真实开头语句，区分视频原话、可验证事实和推断。账号定位只从用户明确提供的本地资料读取；不得把私人资料写入 Skill、配置或仓库。

### 4. 生成并验证 Excel

```bash
python scripts/run.py finalize \
  --run <运行目录> \
  --analysis <完成后的AI拆解.json> \
  --input-workbook <可选的已有工作簿.xlsx>
```

生成器会更新重复作品、严格对齐 30 列、重建 `重点关注账号`、保存后重新打开校验，并生成 HTML 预览。按 `references/workbook-contract.md` 检查主表和重点表；等级规则见 `references/classification-rules.md`。

只有 finalize 成功后才把作品写入 `processed_aweme_ids`。任何分析缺失、XLSX 无法重开或字段错位都必须阻止清理。

关键词游标也只能在 finalize 完成后推进。采集阶段把候选游标写入运行目录的 `批次状态.json`；不得提前提交。

### 5. 安全清理和交付

清理仅针对当前运行目录中已有口播稿且已经写入验证工作簿的明确视频文件。保留：

- 完整口播稿；
- AI 分析 JSON；
- 搜索状态与检查点；
- 最终 Excel 和预览；
- 清理结果。

向用户汇报每词结果数、最终视频数、S/A/B/C 数量、失败或待核验项、Excel 路径、保留口播稿数和删除视频数。

## 恢复与专项操作

- 查看断点：`python scripts/run.py status`
- 仅验证已有缓存：`python scripts/run.py dry-run --source <缓存目录>`
- 不下载：`collect --skip-download --skip-transcribe`，只可用于诊断，不能标记正式完成。
- 只重建 Excel：对已有运行目录重新执行 `finalize`。
- 页面搜索兜底：由主流程自动调用 `search_page_fallback.py`。
- 作者公开指标补充：由主流程自动调用 `enrich_creator_metrics.py`。
- 迁移旧缓存：先运行 `python scripts/migrate_legacy.py --source <旧缓存目录>` 预览；确认后加 `--copy-transcripts --apply`。只复制状态、最新 Excel 和口播稿，绝不复制或删除旧视频。

## 数据位置

默认运行数据位于 `~/.douyin-benchmark-scout/`。可用环境变量覆盖：

- `DOUYIN_SCOUT_HOME`
- `DOUYIN_SCOUT_CONFIG`
- `MEDIACRAWLER_ROOT`
- `MEDIACRAWLER_PYTHON`
- `CHROME_PATH`

绝不把 `.auth/`、浏览器 profile、Cookie、真实视频、真实口播稿、真实工作簿或本地账号资料提交 GitHub。
