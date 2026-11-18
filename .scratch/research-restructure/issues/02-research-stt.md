# 02 STT 线轮次记录

Status: resolved
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

## Answer

由子 agent（sonnet）撰写、主 agent 审阅（R2 必填标题齐全、56–92 行；无 64 位十六进制串与盘符路径；版本保留为 repo＋8 位 revision 与库版本；"原始材料"统一改为完整 tag 路径）。供 05 登记：

| 目录 | 时间 | 状态 | 一句话 |
| --- | --- | --- | --- |
| `2026-10-stt-landscape` | 2026-10-03 – 10-04 | concluded | 来源调研与环境、资产核验，无推理；产出后端时间戳契约、应用失败案例与资产版本等设计先验 |
| `2026-10-stt-demo-w0-x0` | 2026-10-03 – 10-05 | concluded | W0／W1／Q0／Q1／X0 多路线实测与框架等价实验，无配置达严格时间目标，采纳 W0、X0 两条基线（ADR-0003） |
| `2026-10-components-and-ctc` | 2026-10-04 – 10-05 | concluded | 分离与 VAD 叠加放弃，归一化标准日语 CTC 改善时间最多，MMS `jpn` 成为共用对齐器 |
| `2026-10-vad-comparison` | 2026-10-05 | concluded | 新 VAD 未晋级，整片对照后两路统一用新 Pyannote；GPU 与 CPU 结果一致 |
| `2026-10-asr-candidates` | 2026-10-05（附 2026-11-18 的 `no_speech` 测量） | concluded | Cohere、Nemotron、Granite 均未超过 W0／X0，基线不变；`no_speech_prob` 规则不进产品（ADR-0030） |
| `2026-10-x0-whisperx-flow` | 2026-10-05 | concluded | 低能量切点与旧 PyanNet 过滤无无回归赢家，吸收切点与坐标思路，后由 ADR-0003 采纳新 Pyannote |
| `2026-10-cue-token-boundary` | 2026-10-15 | concluded | token 边界映射可行但收益极小，用户裁定不实现；根因是 VAD 漏检 |

来源吸收：映射表本线全部来源均被吸收；另吸收 `docs/architecture/stt-candidate-pipelines.md` 与研究侧模块页 vad-stage、w0-pipeline、x0-pipeline、mms-alignment、stt-evaluation、corpus-and-assets（05 删除），以及 `docs/testing/` 中服务旧 demo 的契约与记录。有意不吸收：`2026-10-04-japanese-ctc-alignment-reference`（未核实的外部计划，只记一句并列入原始材料）；`docs/testing/validation.md` 等通用或翻译侧文件归 03 或丢弃（只描述 2026-10-05 前的验证边界，现行规则在 `docs/agents/testing.md`）。长执行报告只取结论表数字。
