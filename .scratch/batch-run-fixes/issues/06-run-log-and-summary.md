# 06 运行日志与汇总修正

Status: needs-triage
Type: task
Blocked by: —

5 个互不依赖的小问题，可以一起讨论、分开提交。

## 6.1 汇总里的回退条数漏算

- 现象：`[summary] ... 0 fallback cue(s)`，实际有一个文件 2 条 cue 保留了日文（翻译阶段日志 `done ... 2 fallback`）。
- 原因：`ctx.summary.fallback_cues += fallback` 在 `publish()` 移动成功之后（`job.py` 约 661 行）。移动失败（见 01）就不计。
- 候选方向：翻译完成时累加，与发布结果解耦；或汇总分别给"已发布文件的回退"和"全部回退"。

## 6.2 运行日志耗时前缀用墙钟

- 现象：2026-11-15 01:14:16Z 系统时钟被 NTP 校正 +8 h（System 事件 Kernel-General ID 1，`Time Delta 28799736 ms`）。运行日志前缀 `[NNN.Ns]` 从 4630.6s 跳到 33434.5s，看起来像卡了 8 小时，监视脚本误报停滞。
- 原因：`job.py` 约 118 行 `RunFormatter(time.time())`，前缀耗时 = 当前墙钟 − 起始墙钟。各阶段 `end` 行用的是 `perf_counter`，不受影响。
- 候选方向：前缀改用 `time.monotonic()`；绝对时间戳仍用 UTC 墙钟。

## 6.3 失败时每个文件都打完整报错堆栈

- 现象：本批运行日志有 232 段 Traceback，其中 publish 的 228 段内容相同。
- 原因：`_Context.fail`（`job.py` 约 380–392 行）只对**同一个异常对象**去重（`self.traced`），每个文件抛出的是新的 `OSError`。
- 候选方向：按"阶段 + 异常类型 + 消息模板"去重，只给第一次打堆栈，之后一行带过；summary 里给出每类计数。

## 6.4 "没有标 jpn 的音轨"告警太多

- 现象：`No non-commentary audio stream tagged 'jpn'; using the first audio stream` 在 213/228 个文件上出现（这批源基本都不打语言标签）。
- 原因：`media.py` 约 193 行，只要没匹配到就告警，不区分是否只有一条音轨。
- 候选方向：只有一条音轨时降为 INFO 或不报；多条音轨需要猜时才告警。

## 6.5 控制台输出重定向后中文乱码

- 现象：用 pwsh `*> file` 重定向的控制台副本里中文是乱码；产品自己的 `run-*.log`（UTF-8）正常。不设 `PYTHONUTF8=1` 时，此前还出现过 cp1252 下打印崩溃（见 smoke runner 的旧修复）。
- 原因：控制台 handler 的编码取决于调用方环境。
- 候选方向：入口处 `sys.stdout/stderr.reconfigure(encoding="utf-8", errors="replace")`，或文档要求设置 `PYTHONUTF8`；需确认 Windows 控制台直接显示时不变坏。

## 证据

- 运行日志 `.local/work/jav_best_copy-15fff3e12253/run-20261114T235704Z.log`（6.1 的 summary 行、6.2 的跳变点、6.3 的堆栈、6.4 的告警）。
- 台账"第 3 次运行新发现的主程序问题"、§C3。

## Comments
