# Douyin Benchmark Scout

一个可安装的 Codex Skill，用于多关键词抖音竞品采集、公开指标补充、本地 Whisper 转录、低粉高爆分级、口播拆解、Excel 归档和选题迁移。

实际 Skill 位于 `skills/douyin-benchmark-scout/`。

## 安装

将该目录复制到 Codex Skills 目录：

```bash
cp -R skills/douyin-benchmark-scout ~/.codex/skills/
```

在 Codex 中调用 `$douyin-benchmark-scout`，第一次运行先执行：

```bash
python ~/.codex/skills/douyin-benchmark-scout/scripts/doctor.py
python ~/.codex/skills/douyin-benchmark-scout/scripts/bootstrap.py
```

`bootstrap.py` 默认只展示计划；确认联网安装后才使用 `--apply`。

## 安全边界

仓库不包含 Cookie、登录状态、浏览器 Profile、真实竞品视频、真实口播稿、真实工作簿或个人知识库内容。运行数据默认保存在 `~/.douyin-benchmark-scout/`。

MediaCrawler 是独立的上游依赖，不在本仓库中再分发。其当前许可证为 Non-Commercial Learning License，并限制商业用途。使用前请阅读 [MediaCrawler 仓库及许可证](https://github.com/NanmiCoder/MediaCrawler)。本仓库的存在不改变上游许可证、平台规则或第三方内容权利。

## 主要能力

- 多关键词硬配额与断点续跑
- 搜索接口假空识别、重试、页面兜底和熔断
- 视频与作者公开指标合并
- 低资源 Whisper 本地转录
- S/A/B/C 低粉高爆分级
- AI 钩子、结构、情绪、事实边界与迁移分析
- 30 列主表和重点关注账号表
- 完整性检查通过后才清理原视频

