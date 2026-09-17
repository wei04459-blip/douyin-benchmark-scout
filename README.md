# Douyin Benchmark Scout

面向内容创作者的抖音爆款竞品收集与初步分析 Skill。由 Codex 协调多关键词搜索、公开指标核实、赞粉比分级、视频保存、本地转录和内容初读，交付可筛选、可追溯的 Excel 竞品库。

默认任务是批量收集和初步分析。视频、文本、分析与失败记录持续保留，不因导出成功自动删除原视频。

## 安装与更新

把本仓库链接交给 Codex：

> 请安装或更新这个仓库中的 douyin-benchmark-scout Skill，检查本地依赖，保留我的个人配置和已有研究数据。

安装目录是仓库内的 `skills/douyin-benchmark-scout`。使用时说：

> 用 $douyin-benchmark-scout 收集一批近期AI爆款竞品，包含教学内容，核实粉丝和互动指标，按赞粉比分级并完成初步分析。

恢复任务时说：

> 继续上次的竞品收集，从尚未完成的步骤接续，并分别汇报下载、文本和分析完成数。

Codex 负责执行命令、操作独立研究页、读取材料和检查报表。登录或验证码由用户本人完成。安装 Skill 本身不会安装第三方下载器、下载模型或开始采集。

## 默认范围

- 24个AI相关关键词，包括AI变现、AI写作、办公、工作流和工具教学。
- 近30天内容；点赞至少1万，或收藏至少5000，或评论至少200，随后检查相关性。
- 整批目标50条合格视频；每词默认目标40个去重作品。词间重叠不会增加整批作品数。
- S/A/B/C沿用粉丝规模、点赞和赞粉比规则，缺少粉丝时不能进入S/A。
- 单并发材料处理、本地Whisper medium、1个线程。模型需已安装，也可在配置中选择其他本地模型。

关键词、门槛和目标可以配置。每批初始化后冻结范围；不足时报告缺口，不自动扩大范围凑数。详细规则见 [分级规则](skills/douyin-benchmark-scout/references/classification-rules.md)。

## 执行流程

搜索和保存观察 → 去重与相关性筛选 → 核实公开指标 → 分级并固定入选 → 下载和转录 → 全文初读与关键画面核对 → Excel导出、重开与验收。

Computer Use 与 Kimi WebBridge 都可接入。Kimi是可选适配器；选择当前可用的独立研究页，不要求用户切换现有工作标签。

- 每页新增先保存，再记录搜索进度；看到首屏不等于完成搜索。
- 达到目标、结果区明确结束、停滞、超时和访问受限分别记录。
- 已校验的视频和成功转录片段可以复用；中断后接续，不重做整个批次。
- 同批转录共用模型进程，默认120秒分片；空白或失败片段阻止文本通过验收。
- 暂时性错误有限重试；访问受限时停止该网络通道，本地材料可继续处理。
- 指标、视频、文本、初读分别验收；被排除或不再达标的入选项无法被标记完成。
- 全部候选和分析都绑定到完成回执，导出后输入变化会使旧回执失效。

自动化脚本不代替内容判断。Codex仍需真正阅读全文、查看关键画面，核对影响判断的专名、数字和引用。传播原因写作假设，视频作者的收入与效果主张不会自动变成事实。

## 交付内容

Excel保留30列主表和以下7张表：

1. 竞品选题分析
2. 重点关注账号
3. 材料与分析状态
4. 引用与画面依据
5. 搜索覆盖
6. 全部候选
7. 筛选规则

视频、转录、核实文字和失败原因留在批次目录。部分进度也可导出，但不表示整批完成。字段说明见 [工作簿契约](skills/douyin-benchmark-scout/references/workbook-contract.md)。

## 运行环境与入口

新版完整流程面向macOS/Linux，使用Python、FFmpeg、本地Whisper及模型。在线作品与粉丝核实可使用已安装的 `Douyin_TikTok_Download_API`；默认查找 `~/Douyin_TikTok_Download_API/.venv311/bin/python`。Excel导出使用Codex工作区提供的Node.js与 `@oai/artifact-tool`。运行前由代理检查实际路径与可用性。

Windows启动器仍保留，但新版进程锁使用POSIX接口，下载运行环境路径也需适配；本次没有验证Windows完整流程。

进入Skill目录后，可用：

```sh
python scripts/start.py check
python scripts/start.py init --root <批次目录>
python scripts/start.py status --root <批次目录>
python scripts/start.py next --root <批次目录>
python scripts/start.py resume --root <批次目录>
```

`next`给出剩余工作；`resume`推进可执行的机械步骤和有限重试，选取作品、阅读内容与视觉复核由代理接续。命令返回2通常表示仍有缺项，应查看记录，不要把它当成已完成。完整命令见 [批量执行流程](skills/douyin-benchmark-scout/references/new-workflow.md)。

个人配置默认在 `~/.douyin-benchmark-scout/config.json`。未创建个人配置时，新批使用随Skill附带的示例默认值；也可以通过 `--config` 指定配置。批次材料保存在 `--root` 指定目录；不指定新批目录时，使用当前工作目录下的 `outputs/`。最近批次指针保存在个人配置目录。

旧版MediaCrawler路径保留为兼容模式，需要显式选择。`bootstrap.py`仅用于旧版MediaCrawler安装计划，不是新版统一安装器；不加 `--apply` 不会安装。

## 验证与已知边界

```sh
python scripts/self_test.py
```

自测需要openpyxl，媒体检查需要FFmpeg。2026-09-17发布前验证77项测试通过，包括搜索覆盖、中断恢复、部分转录、重试上限、材料指纹、入选资格和首次无个人配置启动。

2026-09-13的本地验证还检查过历史批次副本、同一进程的真实短视频转录，以及完整/未完成批次的Excel导出与重开。这些检查不代表新版已经连续跑过多轮线上采集，也不能证明免登录、无验证码或转录逐字准确。

旧批未冻结新搜索范围时保留原口径；不追认旧批达到新配额。更新Skill不会重写旧报告。接续规则见 [接续和验收机制](skills/douyin-benchmark-scout/references/recovery-contract.md)。

## 数据与第三方边界

仓库只发布Skill、脚本、文档与合成测试样例。个人配置、浏览器资料、凭据、真实视频、转录和Excel不进入仓库。不要从公开示例推断任何用户的私人经历。

MediaCrawler、Douyin_TikTok_Download_API与Whisper都是独立依赖，遵循各自的上游许可；具体说明见 [NOTICE.md](NOTICE.md)。使用者需有权访问相关内容并遵守平台规则。遇到验证码或访问限制时，停止受限通道，不绕过访问控制。
