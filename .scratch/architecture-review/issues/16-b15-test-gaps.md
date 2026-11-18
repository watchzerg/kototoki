# 16 编排鲁棒性的测试缺口

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 B-15（报告时判断：已核实）。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

报告时 B-1/2/3/4/6/8/9 都没有离线测试；"发布只移动了部分文件"只在 artifacts 层测过；假 worker 不走 `gpu.main`，不产生真实格式的 stderr；Job Object 在测试里被 mock，只在 2026-10-15 验收时手动验证过。

## 证据（报告时）

`tests/core`、`tests/full`、`tests/fake_worker.py`。

## 报告建议

报告未给具体改法。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。 票据 01（小修集合）已为其中多项补了测试，分诊时先逐项核对还缺哪些。

## Comments
