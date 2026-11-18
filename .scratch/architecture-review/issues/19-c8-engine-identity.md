# 19 翻译身份不含引擎版本

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 C-8（报告时判断：已核实（低））。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

换 llama.cpp 构建后续跑，会在同一部片里混入两种构建的批次；`sessions[]` 可以追溯。

## 证据（报告时）

翻译身份与 `sessions[]`。

## 报告建议

报告未给具体改法。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。 报告针对 llama-server 时期的翻译；产品翻译与建表已改在 Strata 上（ADR-0019、ADR-0022），先确认这一条是否仍适用，不适用就 wontfix。需要核实 Strata 的身份常量是否已进翻译身份。

## Comments
