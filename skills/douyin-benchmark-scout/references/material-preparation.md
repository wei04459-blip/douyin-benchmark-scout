# 单条材料入口

批量收集默认使用 new-workflow.md 的 start.py。本文仅用于单条导入与恢复。

# 材料准备与恢复

现有安装先查 `~/Douyin_TikTok_Download_API`，不要只盘点 MediaCrawler 或先安装新下载器。此项目包含自己的运行环境与配置，adapter 通过它的客户端读取公开作品；不提取、打印或搬运浏览器凭证，也不修改用户的既有项目。若配置或上游兼容性失效，报告实际返回，不能推断必然是 Cookie 过期。

## 一个入口

```sh
python scripts/doctor.py
python scripts/prepare_video.py --root <本批材料目录> --url <完整抖音作品链接>
python scripts/prepare_video.py --root <本批材料目录> --video <本地视频>
python scripts/prepare_video.py --root <同一目录> --status
python scripts/prepare_video.py --root <同一目录> --retry-failed
```

无参数启动会让用户拖入本地视频或粘贴完整作品链接。代理执行时从既有任务取参数，不让用户重复填写。短分享链接应先在正常页面中取得完整作品 ID，不根据标题猜 ID。

默认寻找已安装 Whisper，优先 medium，其次 small。模型选择需结合当前素材的准确性与资源条件，不能用速度冒充质量。`--model` 和 `--python` 可指定已安装模型和环境。转录始终是 machine_draft_unreviewed，必须阅读全文、核对字幕或关键帧后才能接入正式分析。

需要来源时长、身份信息或自定义安装路径时：

```sh
python scripts/material_queue.py --root <目录> add --source <来源.json>
python scripts/material_queue.py --root <目录> prepare --python <ASR运行环境> --model <模型.pt>
```

来源 JSON 支持 `local_video` 或 `url`；已有公开媒体地址可提供 `video_download_url` 加 `source_duration_seconds`。可选 `aweme_id`、`title`、`identity_evidence`、`source_duration_evidence`。自定义安装目录用 `downloader_project` 和 `downloader_python`。本地视频没有来源身份及时长时仍可准备机器初稿，但不能通过正式研究验收。

## 状态与断点

- queued / preparing：待处理或处理中；进程中断后可恢复。
- failed：保存原因与本次日志；暂时性错误可由接续入口有限重试，其他问题修复后使用 retry-failed。普通尝试累计最多3次，不因失败删项。
- access_restricted：停止受限网络通道。核实访问恢复后，用材料队列或start.py的 `--access-restored` 接续原任务，不新建重复任务。
- pending_review：完整媒体与非空、带分段的机器转录已绑定指纹，仍需内容审核。此状态绝不是研究完成。

每次尝试一个独立版本。已准备材料重跑先验证媒体、TXT 与 JSON 指纹；没有变化便跳过。有变化则退回失败，不静默复用。转录重试可复用已校验媒体，不重复下载。队列有进程锁，失败项不阻塞其他独立条目。

下载器单次解析上限 30 秒，不重试空响应。HTTP 401/403/429 记录访问限制；HTTP 200 空正文记录 empty_response。元数据必须有匹配作品 ID、来源时长和 HTTPS 媒体地址。接着使用现有 acquire 做字节、全片解码和时长检查。

## 接回正式研究

材料队列是准备层，不替代 batch.json。代理确认来源与筛选条件后 select 入研究批次，完成文本校对后 adopt，再做分析、verify、export 和 commit。队列不调用 commit、不改全局 processed、不把历史回归样本算入新样本配额。

实际状态必须分别汇报：本地准备能否运行、线上解析是否真实成功、内容是否审核、Excel 是否验收。doctor 的“已安装”不能当作线上测试通过。
