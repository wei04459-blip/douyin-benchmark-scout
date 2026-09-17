---
name: douyin-benchmark-scout
description: Batch collect relevant public Douyin viral competitor videos, verify follower and interaction metrics, classify low-follower breakouts, prepare media and text, and deliver initial content analysis in sortable Excel. Use for 抖音爆款竞品收集、对标视频分析、赞粉比分级和历史假完成排查.
---

# 抖音爆款竞品收集与初步分析

替用户省去逐个搜索、查粉丝、抄数据、保存视频和初读整理的劳动。交付可持续积累的竞品库，帮助用户决定哪些选题、结构和账号值得继续研究。批量收集加初步分析是默认任务；不能改成少量精读、工具验证或先写选题。

## 默认执行

先读 [批量执行流程](references/new-workflow.md)、[原30列工作簿](references/workbook-contract.md) 和 [赞粉比分级](references/classification-rules.md)。统一入口 `scripts/start.py`，以用户当前输出目录为批次。默认推进50条合格视频与配置中的所有关键词；用户具体要求优先，不暗改时间和门槛。恢复任务先运行 `next`，根据待办继续；`resume` 负责可执行的机械步骤和有限重试，代理接续相关性选择、全文初读与视觉检查。

持续完成搜索、相关性筛选、公开指标补齐、分级、材料准备和逐条初步分析。先盘点已有下载项目与可复用材料，再选浏览器通道。Computer Use 与 Kimi 都可用，选当前实际可用的一条，不重复折腾浏览器。使用独立研究页。

搜索成功、收录、指标核实、视频下载、文本准备和初步分析分别记录。每页新增先保存，范围完成取本词最新尝试。达到本词目标或明确验证结果已尽才结束；停滞、超时、重试耗尽都保留为未完成。Computer Use 通过 `search_checkpoint.py` 接入同一台账。公开粉丝未拿到就留空，不猜赞粉比。200空响应、页面没加载、转录文件存在均不能证明成功。

初读要求全文阅读与关键画面核对，重点检查影响判断的专名、数字和引用。画面承载主要内容时明确记录画面文字，不冒充口播。内容结构从实际材料提取；不靠标题填满表，也不把收入故事或单条互动当成因果证明。

队列失败不阻塞其他作品。正常重试有上限，原失败保留；入选后不删除失败项来制造完成。平台验证码出现时停止受限通道，用户解除后接续。除必要澄清或真实障碍，连续推进到可交付。

同批转录复用模型进程，逐片段保存。空白或失败片段阻止材料通过，其他片段可继续复用；已有完整视频不重复下载。具体状态、恢复边界与旧批兼容见 [接续和验收机制](references/recovery-contract.md)。

## 交付与条件分支

恢复30列主表、S/A重点账号、真实材料状态及可追溯依据。Excel导出后重开并查看所有表，完成回执绑定本次数据、分析与文件。仅修改skill或少数样本通过不能称全流程可用。

- 目标纠偏或参考旧表：读 [收集目标](references/collection-purpose.md)。
- 本机浏览器/下载故障：读 [已实测路径](references/search-and-session.md)。已有开源项目优先；无需新建一套下载器。
- 单个本地视频导入：`scripts/prepare_video.py`；它只是材料入口，不替代批量收集。
- 审计旧假完成：读 [材料契约](references/evidence-contract.md)，用 verify_evidence.py，只读旧表，不回写为已审核。
- 用户明确要深拆或逐句研究：使用 research_batch.py / export_reviewed.mjs 的精读路线，按 [分析字段](references/analysis-schema.md) 扩展；默认初读无需全片逐字OCR。
- 旧 MediaCrawler 兼容：run.py collect --legacy-collector，使用前读 [依赖与隐私](references/privacy-compliance.md)。旧下载上限不限制新批量规模。
