# 07 C：N*＋ASR 感知提示

Status: resolved
Type: GPU
Stage: C
Blocked by: 06

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-22-q0-product-route-v11.md）。

## 执行记录

- 2026-10-23 15:58 `q0-names-high-asr`（N\*＋ASR 提示，hash `9833598a…`）seed 54–56 由链 `logs/c-chain.sh`／`c-chain3.sh` 生成完毕，6 run 全部交付（`product failures` 0 条，墙钟 586–591 s/部）。对照 `q0-names-high`（N\*）。
- `product plan --x q0-names-high --y q0-names-high-asr`：逐字相同 **765**／1728（exact 407／light 153／heavy 205，Δ＝0），送判 963（exact 404／light 357／heavy 202）；裁判排在 06 之后（`logs/judge-chain.sh`，`logs/judge-07.log`）。
- 整片不一致率（`C/inconsistency-07.json`）：N\*＋ASR **0.017**（HF-II 0.000／0.027／0.000，HF-III 0.000／0.032／0.044）；对照 N\* 0.027、Q0＋替换 0.050。
- 16:59 裁判完成（121 包、$5.74，约 40 min，无配额中断；`asr10.judge` 的新锁让第二条裁判链对同一比较直接退出，未重复付费）。`product estimate`（`C/judge/q0-names-high-asr-vs-q0-names-high/estimate.json`，Δ＝候选−对照，相同单元按 Δ＝0 计入）：
  - **全体 Δ +0.008［−0.048, +0.065］**（n 1728，已判 963）；**exact +0.111［+0.049, +0.175］**（HF-II +0.056、HF-III +0.163）、light −0.039［−0.153, +0.073］、**heavy −0.140［−0.290, −0.003］**、light+heavy −0.084［−0.176, +0.006］。
  - 人名相关错误 77 对 79（差 CI90 ［−0.004, +0.006］）；critical 30 对 31；addition 92 对 106（exact 18→30：ASR 提示让模型在转写正确的句子上也"修"出了内容）。
  - 门（立项写定，四项全要）：全体上界 <0 ✗（+0.065）；exact 上界 ≤0.05 ✗（+0.175）；无桶下界 >0 ✗（exact 下界 +0.049）；人名错误不增加 ✓ → **未过**。
- 解读：与 v10 D 的 ASR 提示（`q0-asr` 对 Q0）同一形状——heavy 桶改善、exact 桶变差、全体不动；叠在 N\* 上没有改变这个取舍。该成分不进候选。

## Answer

**未过。** 对照 N\*（`q0-names-high`），N\*＋ASR 感知提示 3 seed：全体 Δ +0.008［−0.048, +0.065］，exact **+0.111［+0.049, +0.175］**显著变差，heavy −0.140［−0.290, −0.003］改善，人名错误 77 对 79。四项门中三项不满足；与 v10 的 ASR 提示结论相同：用 exact 换 heavy，不进候选。GPU 3（C 9／12 累计）、裁判 $5.74。
