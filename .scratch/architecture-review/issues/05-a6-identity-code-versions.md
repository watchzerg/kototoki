# 05 阶段身份不含代码逻辑与依赖版本

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 A-6（报告时判断：已核实（配置项覆盖完整））。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

`cues.py`、`srt.py`、`align.map_records` 的逻辑、ffmpeg 二进制、faster-whisper／ctranslate2／transformers 版本都不在阶段身份里；改逻辑或升依赖而没改配方 id 时，旧产物会被静默复用。

## 证据（报告时）

`plan.py`、`recipes.py`。

## 报告建议

把相关源码 hash 并入配方 hash，规模小。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
