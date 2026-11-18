# 10 worker 加载模型时原生崩溃被当成文件问题

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 B-4（报告时判断：推演）。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

worker 加载模型时原生崩溃（未经 Python 捕获）不发任何事件，被当成第一个文件的问题，逐文件重启并逐文件记 `WorkerCrashed`。

## 证据（报告时）

`run_gpu_stage` 的 `culprit_at=0`；`run_worker` 启动成功后不发事件。

## 报告建议

`start()` 成功后发 `started` 事件，没收到就按启动失败处理，约 5 行，外加假 worker 的对应动作。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
