# 03 时间轴边界情况缺 full 测试

Status: needs-triage
Type: task
Blocked by: —

## 来源

[2026-10-19 审计报告](../2026-10-19-report.md) §1 A-4（报告时判断：推测（按 ffmpeg 语义应能对齐））。报告基于 commit 12e4ff6 与当时的真实运行；本票据建于 2026-11-18，现状没有重新核实。

## 问题

时间轴只测了起始延迟与中途间隙；负延迟、MP4 AAC 编辑列表、Opus pre-skip、PTS 倒退／回绕都没测。

## 证据（报告时）

`tests/full/test_media_ffmpeg.py`。

## 报告建议

合成 3–4 个 full 测试。

## 分诊

先对照当前代码确认问题是否还在，再决定修、只补文档，还是 wontfix。

## Comments
