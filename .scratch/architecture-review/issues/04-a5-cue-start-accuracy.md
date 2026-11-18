# 04 cue 起点绝对精度从未实测

Status: needs-triage
Type: research
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 A-5（报告时判断：推测）。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

起点取 CTC 发射区段起点、无 lead-in，可能比开口晚几十 ms；MP3 约 25 ms 的解码预延迟没有处理（播放器同样不裁，所以目前与播放对齐）。

## 证据（报告时）

`cues.py`、`media.derive_command`。

## 报告建议

拿一份人工打轴 SRT 一次性比较起点偏差分布。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
