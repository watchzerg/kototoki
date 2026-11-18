# 02 ASR 窗内长静音保留，疑有漏转

Status: needs-triage
Type: research
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 A-2（报告时判断：推测）。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

窗内静音保留（`internal_silence: retained`、`additional_padding_samples=0`）。ATKD-089 上窗内静音中位 12.2 s、最长 27.9 s，256/388 窗超过 10 s；14 个窗语音 ≥10 s 却不到 1 字/s，疑有漏转。

## 证据（报告时）

`recipes.py` 的 CHUNK_POLICY、`vad.py` 的 `chunk_intervals`。

## 报告建议

属 ADR-0003 基线配方，改动须出新配方版本做对比验证。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
