# Douyin Benchmark Scout

给普通内容创作者用的抖音竞品研究 Skill。它会按多个关键词找样本、识别“低粉高爆”、本地转录口播、生成竞品 Excel，并在确认结果完整后删除已处理的视频、保留口播稿。

## 最省事的安装方式

把这个仓库链接发给 Codex，然后说：

> 请安装这个仓库里的 douyin-benchmark-scout Skill，并带我完成首次环境体检。全程使用低占用模式。

Codex 会把 `skills/douyin-benchmark-scout` 安装到你的 Skills 目录。安装后直接说：

> 用 $douyin-benchmark-scout 带我跑一轮抖音竞品分析。

不熟悉终端也没关系。Skill 会先解释缺什么，再征得同意安装；首次抖音登录仍由你本人扫码完成。

## 自己下载后的入口

- macOS：进入 `skills/douyin-benchmark-scout`，双击 `开始使用.command`
- Windows：进入同一目录，双击 `开始使用.bat`
- 也可以运行 `python scripts/start.py`

菜单包含首次设置、环境体检、安装计划、低占用跑一轮、查看进度、寻找最新 Excel 和迁移旧数据。

## 第一次运行会检查什么

- Python 3.10+、Git、Node.js 16+
- Chrome/Chromium、FFmpeg
- MediaCrawler 与独立虚拟环境
- Excel、Playwright、Whisper、Torch 依赖
- 内存、磁盘空间、浏览器登录资料目录

新电脑缺依赖时，`bootstrap.py` 默认只展示计划，不会擅自联网安装。新安装的 MediaCrawler 固定到已验证提交 `1779dde9725f6b7ef42e29022c0054b3e678f1af`，避免上游更新突然破坏流程。

## 默认安全设置

- 单并发搜索和下载
- Whisper `base`、1 个线程、逐条转录
- 每个关键词独立配额；假空结果会重试和熔断
- 批次未完成前不前移关键词游标
- Excel 可重新打开且 30 列对齐后才允许清理视频
- 清理后会再次更新 Excel，口播稿、分析、断点和工作簿继续保留

运行数据默认只放在 `~/.douyin-benchmark-scout/`，不会进入仓库。旧版本数据可通过菜单迁移；迁移只复制状态、Excel 和口播稿，不复制或删除视频。

## 使用边界

仓库不含 Cookie、登录状态、真实视频、真实口播稿、真实工作簿或个人知识库内容。MediaCrawler 是独立上游依赖，采用限制商业用途的 Non-Commercial Learning License。使用前必须阅读 [MediaCrawler 许可证](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE)，并遵守平台规则和第三方内容权利。本 Skill 不会绕过验证码或访问控制。
