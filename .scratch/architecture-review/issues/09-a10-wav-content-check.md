# 09 跳过 extract 时不核对 WAV 内容

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 A-10（报告时判断：已核实（低））。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

WAV 被替换后每次运行都报 `ArtifactMissing`（会报错，不是静默），要手动删文件才能恢复。

## 证据（报告时）

`probe_and_extract` 的跳过判断。

## 报告建议

报告未给具体改法。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
