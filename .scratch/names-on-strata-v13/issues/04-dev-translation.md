# 04 dev 翻译 T1／T0 各 3 seed＋同期判

Status: resolved
Type: GPU
Stage: D
Blocked by: 03

范围、终点与门见研究文档 §4.4（docs/research/2026-11-08-names-on-strata-v13.md）。

## 执行记录

- 2026-11-09 `v13-recipes` → `v13-dev`（日志 `logs/dev.log`）；裁判链 `judge-run` T0 → `copy-identical` → `judge-run` T1，逐 seed（`logs/judge-dev.log`），全部退出码 0；`v13-dev-gate` → `summaries/v13-dev-gate.json`，按作品见 `summaries/v11-q2-names-s1-vs-q2-names-27b-v13.json`。

## Answer

**不过非劣门**：剧集 wrong-referent Δ +0.042 [+0.021, +0.067]、accuracy 上界 0.051；电影 accuracy Δ −0.049 [−0.085, −0.014]（显著变好）。剧集的变差主要来自 W08、W11 两部的表问题。人名错误 64 对 78。裁判 $56.19。

以下为旧答案：

S1 v2 同样不过门，未跑：票据 02 可行性门不过，按研究文档 §4.2／§5"B 不过就停"，阶段 D 不执行。GPU 0、裁判 $0。
