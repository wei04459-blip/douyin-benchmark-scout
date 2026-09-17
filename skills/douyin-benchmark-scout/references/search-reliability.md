# 搜索可靠性

新版搜索观察、逐词状态与恢复方式见 [新版执行契约](new-workflow.md)。Computer Use 优先；Kimi 不再是必要条件。

旧搜索日志的 success/failed 仅代表旧采集器状态，不自动解释为明确零结果。检查旧批次时另存诊断，保留原日志。旧 run.py collect 只有显式 --legacy-collector 才启用；其批次熔断和页面兜底不等同于新版的独立观察队列。
