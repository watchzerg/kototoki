# 04 Q 线、ASR 稳健性、专名、交叉合并与验收记录

Status: ready-for-agent
Type: task
Blocked by: 01

## 范围

做法与完成标准同 [02](02-research-stt.md)，目录为：

- `research/2026-10-cross-asr-judge/`：oracle、CTC 裁判、交叉打分、声学裁判调研 → ADR-0012。先看 `.scratch/cross-asr-judge/` 是否还有未完成票据，若有，在 `## Answer` 里报告，不替它结题。
- `research/2026-10-name-consistency/`：专名 1–6 轮 → ADR-0013、0014。
- `research/2026-10-q-line-v9-v11/`：v9 Q0、v10 广度探索、v11 Q1 → ADR-0015、0016。
- `research/2026-11-strata-v12-v13/`：v12 Q2（含 Strata 使用笔记）、v13 Q3 → ADR-0017、0018、0021、0022。
- `research/2026-11-asr-robustness-v14-v15/` → ADR-0023（v15 的待裁定项若仍有效，写进 `docs/pending-decisions.md` 的链接里由 05 处理，本票据只标出）。
- `research/acceptance/`：`docs/research/acceptance/` 中产品验收记录逐篇精简（一篇一文件，保留日期、对象、版本、测了什么、结果、结论；模板同 R2，标题可按验收调整）。`2026-11-11-module-page-history-*` 三篇不迁。

## 额外注意

- 现行翻译评估方法（`docs/agents/translation-evaluation.md`）引用 `experiments/scene_batching_v6/asr10.py`、`v9.py` 等脚本作为口径来源：在 v12–v13 README 中把这些口径（裁判身份、统计方法、人名错误口径）写成文字，05 再把方法文档改为引用文字而不是脚本路径。
