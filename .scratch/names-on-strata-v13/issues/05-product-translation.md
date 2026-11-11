# 05 产品 ASR 源翻译 T1／T0 各 3 seed＋配对判

Status: resolved
Type: GPU
Stage: E
Blocked by: 03

范围、终点与门见研究文档 §4.5（docs/research/2026-11-08-names-on-strata-v13.md）。

## 执行记录

- 2026-11-09 `v13-product`（`logs/product.log`，T0 HF-II s55 一个包两次失败、退出码 1，6 cue 未交付）→ `product13 plan`（判 1051、相同 677）→ `product13 judge`（`logs/judge-product.log`，$6.33）→ `product13 gate`（`E/gate.json`）。

## Answer

**全体明显变好**（Δ −0.095 [−0.159, −0.031]，light −0.267），人名、不一致率都过；门按字面因对照 T0 的 6 cue 交付失败不过，候选为 0（§8 第 9 项）。

以下为旧答案：

S1 v2 同样不过门，未跑：票据 02 可行性门不过，按研究文档 §4.2／§5"B 不过就停"，阶段 E 不执行。GPU 0、裁判 $0。
