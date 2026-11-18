# 13 worker stdout 的非 JSON 行被静默丢弃

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 B-8（报告时判断：已核实（低））。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

`_read_events` 丢掉非 JSON 行；如果与事件行粘连会丢事件（下次运行按身份自动纠正）。

## 证据（报告时）

`_read_events`。

## 报告建议

把这些行转写进该阶段的 stderr 日志。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
