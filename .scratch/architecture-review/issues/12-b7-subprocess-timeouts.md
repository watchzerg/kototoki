# 12 子进程没有超时

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 B-7（报告时判断：已核实（低））。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

`process.wait()` 与 ffprobe／ffmpeg 调用都没有超时；目前没有卡死的证据。

## 证据（报告时）

编排与媒体模块的子进程调用。

## 报告建议

先在文档里补恢复步骤（杀进程＋`KOTOTOKI_BREAK_STALE_LOCK=1`）。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
