# 批量收集与初步分析

## 标准任务

替用户完成多词搜索、去重、指标核实、分级、保存材料与初步内容判断。默认计划50条合格视频，覆盖配置中的所有关键词；用户的数量与范围优先。下载并发或单次上限不是整轮条数。

统一入口是 `scripts/start.py`，状态写入用户输出目录。命令由 Codex 执行，不让用户手动抄链接或整理材料。以下 `<批次>` 等为占位路径。

```sh
python scripts/start.py init --root <批次>
python scripts/start.py status --root <批次>
python scripts/start.py next --root <批次>
python scripts/start.py resume --root <批次>
```

配置取 `~/.douyin-benchmark-scout/config.json`，不存在时先参考 `assets/example-config.json`。初始化冻结关键词、30天窗口、互动阈值与分级规则；不为凑数扩大范围。上一批收录ID自动排除，首次迁移可把已核实历史ID加入 batch.json.excluded_aweme_ids。旧状态里的 processed 不能证明旧材料或内容分析已成功。

## 发现与筛选

代理选择当前可用的独立研究页，不打扰用户标签。Computer Use 是代理工具；Kimi 是可选搜索适配器，不是模型调用的必经层。本机已有实测路径见 [搜索与会话](search-and-session.md)。有已观察的 Kimi 研究会话时：

```sh
python scripts/start.py search --root <批次> --session <研究会话>
python scripts/start.py enrich --root <批次>
```

Computer Use 每页保存一份 `{"observation":{...},"items":[...]}`，使用 `python scripts/search_checkpoint.py --root <批次> --file <观察.json>`。观察含 keyword、query、observed_at、channel、page_url、evidence_text、page_loaded、query_confirmed、cards。卡片必须来自真实页面；作品ID要有页面链接或同页响应对应证据。items 的作品ID、title、keyword 必须与卡片吻合，其他公开字段参考 `collect_visible_search.py`，未知字段留空。脚本先合并作品，再保存观察，自动计算累计数量、停滞及范围，不手填成功状态。

新批每词目标默认40个去重作品，最多12次滚动、180秒、连续3次无新增或3次正常尝试。看到首屏不算完成。达到目标、结果区明确结束、加载停滞、时间/滚动上限分别记停止原因。整页出现“没有更多”不能证明属于搜索结果；明确结束需 end_scope=search_results、end_evidence 和对应原文。范围结束但未够50条合格视频，继续报告缺口，不降低筛选门槛。具体接续规则见 [接续和验收机制](recovery-contract.md)。

搜索每词保留尝试和实际查询，区分：已见结果、明确零结果、检索失败、未能核实、访问限制。只有明确空结果文案且原词页面已加载才能判零；200空响应、标题列表没匹配上、正文未更新都不是零结果。普通本机故障记录后继续其他独立词；平台验证出现则停止受限通道，等用户处理，不换通道绕过。

补指标调用已安装的 Douyin_TikTok_Download_API，与作品作者 uid 对上后才接受公开粉丝和总获赞。保存观察时点。缺失值留空，不能填0或推断低粉。

初筛使用“点赞≥1万，或收藏≥5000，或评论≥200”，随后检查AI应用相关性。排除理由保留在竞品库，不拿搜索命中数当有效视频数。赞粉分级按 [分级规则](classification-rules.md)。将作品ID列表写为 `{"ids":["作品ID"]}`：

```sh
python scripts/start.py select --root <批次> --file <入选列表.json>
```

固定入选后允许追加，不允许为了通过验收移除失败视频。相关性仍应在全文初读复查，发现误匹配如实保留原因，不伪造50条通过。

## 材料与初读

```sh
python scripts/start.py prepare --root <批次>
python scripts/start.py prepare --root <批次> --retry-failed
```

队列按作品ID去重，单并发，锁定避免双重启动。已准备且指纹不变的材料跳过；失败继续其他条。`resume` 对暂时性错误退避重试，每项跨调用最多3次正常尝试；内容缺失、环境或来源问题先查原因，修复后才用 `--retry-failed`。中断尝试留痕并接续已验证材料，访问验证恢复用 `--access-restored`，二者不占普通失败次数。受限期间只继续本地材料。

同批使用一个本地转录进程，模型按冻结的 transcription_policy.model_path 或 model 读取，不隐式下载。默认以120秒分片，按视频、模型和参数指纹缓存；成功片段复用，失败或空白片段保留问题。中断后从已完成片段接续。机器转录完成不等于内容准确，仍须初读。

下载选择来源明确的音画完整MP4版本。不能把分离音轨的DASH画面流当成完整视频。校验传输字节、全片解码和来源时长后才记下载成功。来源过期重新取得该作品来源，不能编造媒体地址。

先全文阅读语音稿，再查看开头、转折、演示结果等关键画面。重点核对影响判断的专名、数字与引用；初步分析不要求每条逐字听校或全帧OCR。机器稿保留未审核状态，不因模型运行结束自动升级为准确口播稿。转录为空、内容明显缺失或音乐被幻听成语音时，查画面或尝试正常的本地转录修复；不能用标题补正文。主要信息在画面的作品可用核实的画面文字，标明它不是口播稿。

用已加载且带 Pillow 的工作区 Python 生成关键画面候选：`python scripts/prepare_visuals.py --root <批次>`。它只提取六个时间位置，不会自动声明已看。代理必须查看，若转折或文字卡片不在这些位置，继续针对性取帧。旧画面绑定的视频变化时停止复用并重建新版本。

每条初步分析包含：方向、类型、选题概括、开头、内容结构、情绪、摘要与事实边界、传播假设、用户可尝试的借鉴。按真实内容写，不要求每条都套同一四段式。至少给开头、结构、摘要保存对应时间范围的原文依据；保存完整阅读与关键画面核对记录，并绑定视频和文本指纹。收入、产品效果和行业判断标为作者主张，传播解释不写成已证明因果。

需要补画面文字或修正明显遗漏时，将新文本保存为独立TXT及同名JSON。JSON注明 source_type（visual、mixed 或 speech_corrected）、review_method、media_sha256、带时间的 segments 和实际看过的 evidence_files。队列运行完后接入，保留原转录与失败记录：

```sh
python scripts/adopt_reviewed_text.py --root <批次/材料准备> --id <作品ID> --text <核实文本.txt>
```

接入文本只代表材料已准备，仍需完成初读。每条分析还必须有实际查看的 visual_evidence 文件路径及 visual_sha256，复用旧批次时也要补齐画面依据。

分析JSON结构是 `{"items":{"作品ID":{...}}}`，字段和校验见 `collection.FIELDS`、`collection.item_problems`。审核数据用 evidence_review.full_content_checked、quality_notes、media_sha256、transcript_sha256、references；引用项含 field、start、end、quote。

```sh
python scripts/start.py review --root <批次> --file <初步分析.json>
python scripts/start.py verify --root <批次>
```

默认交付深度为初步分析。仅当用户要仿写、拍摄拆解、逐句研究时，才使用 [材料契约](evidence-contract.md) 和 research_batch.py / export_reviewed.mjs 的精读模式，不让精读要求拖住整个竞品库。

## 出表和恢复

按当前 Spreadsheets skill 加载 Artifact Tool 环境并运行操作标记，然后：

```sh
python scripts/start.py export --root <批次> --output <新工作簿.xlsx> --node <Node> --python <Python> --modules <node_modules> --require-complete
```

恢复原30列主表和S/A重点账号表，附材料状态、依据、搜索覆盖、全部候选与规则。搜索覆盖同时显示页面状态、范围是否完成、停止原因和尝试次数。部分进度也可以出表（不加 require-complete），包括尚无入选作品时；未经核实的分析保持空白，缺项明确显示。部分表不表示全流程完成。

导出前重验材料；保存后重开检查表头、作品ID、数字、比率和内容。代理查看所有表的预览后，确认 `导出回执.json` 的 visual_reviewed=true，再执行：

```sh
python scripts/start.py commit --root <批次> --file <新工作簿.xlsx>
```

只有验收无缺项且输入/输出指纹与回执一致，才生成完成回执。输入指纹覆盖全部候选、入选、规则、检索与分析；未入选候选变化也使回执失效。被标记不相关或不再达到门槛的入选项不能通过。原始材料、失败原因和旧Excel均保留。交付报告分别说明候选、入选、指标、下载、文本、初步分析完成数；不把部分成功说成整轮成功。
