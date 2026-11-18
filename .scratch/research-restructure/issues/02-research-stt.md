# 02 STT 线轮次记录

Status: ready-for-agent
Type: task
Blocked by: 01

## 范围

按 [spec](../spec.md) 的"旧材料 → 新轮次映射"表写以下目录的 `README.md`（只写 README，不搬代码、不搬数据）：

- `research/2026-10-stt-landscape/`
- `research/2026-10-stt-demo-w0-x0/`
- `research/2026-10-components-and-ctc/`
- `research/2026-10-vad-comparison/`
- `research/2026-10-asr-candidates/`
- `research/2026-10-x0-whisperx-flow/`
- `research/2026-10-cue-token-boundary/`

## 做法

- 读来源时先 grep 标题、按节读取，不整读大文件。数字取报告里的结论表，不重新计算。
- 每篇按 `research/TEMPLATE.md` 填写，遵守 R3：不抄哈希、本机路径、逐窗明细、字幕原文。版本信息要保留（模型 repo＋revision 可写短 SHA 前 8 位或版本号；推理库版本；GPU）。
- 结论去向链接到现行 ADR（`../../docs/adr/NNNN-*.md`）。
- "原始材料"写归档 tag 路径，例如 `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-05-vad-baseline-comparison.md`。
- 不改 `research/INDEX.md`（由 05 汇总登记，避免并行冲突）；在本票据 `## Answer` 下列出每个目录的一行摘要（日期、状态、一句话），供 05 登记。

## 完成标准

- 每个目录一个 README，必填标题齐全，正文约 150 行以内。
- 对 `research/` 本票据目录 grep `[0-9a-f]{64}` 与 `[A-Za-z]:[\\/]` 无命中。
- 映射表中本线的每个来源都被至少一篇 README 吸收，或在 `## Answer` 里说明为何丢弃。
