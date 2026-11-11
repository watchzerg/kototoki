# 12 D2 专名表注入

Status: resolved
Type: GPU
Stage: D
Blocked by: 10

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-21-q0-exploration-v10.md）。

## 执行记录

- 臂：`qwen-wide+rep`（Q0＋`apply_table` 默认参数＋产品表，产品等价链）、`q0-names`（Q0＋`qwen-name-table-v1` 按窗口命中注入，hash `18fcac59…`）、`q0-names+rep`。HF II／III 产品 w0 `ja.srt`，seed 20261051–53，6 个整片 run；HF-II s51、s52 各 1 条（cue 810 末尾换行）判部分交付，按未交付计。
- 替换量：`qwen-wide+rep` 6 run 合计 replaced_stat 93、replaced_variant 1、unresolved_not_found 130；`q0-names+rep` 全部 0（1189 already_canonical），输出与 `q0-names` 逐字节相同。
- 裁判：普查 1728 单元 × 2 比较（$9.09＋$8.21）。第二个比较两侧文本完全相同，事后看是可避免的开销（应在评审前先 diff）。
- 墙钟每部：q0-names 585 s，qwen-wide 561 s（+4%）。

## Answer

**门通过：注入列为候选成分（产品 ASR 源证据）；注入＋替换不叠加。** 对照 `qwen-wide+rep`（Q0＋产品替换链）。
- 不一致率（3 seed）：注入 0.0101，替换 0.0498（Q0 原始 0.0474）——不高于 ✓。
- 人名相关错误：全体 142 对 96，差的 CI90［−0.035, −0.019］/单元，上界 <0 ✓；light、heavy 桶各自也显著。
- 每单元惩罚 Δ（注入 − 替换）：全体 −0.107［−0.175, −0.041］、light −0.202［−0.343, −0.065］、heavy −0.113［−0.285, +0.059］、exact −0.044［−0.118, +0.030］；两部同向；critical 29 对 34、addition 95 对 108。
- 注入＋替换：替换器在注入输出上 0 处改动，与注入逐字相同（Δ 恒为 0）——替换在注入后无事可做，不叠加。
- 未做：dev 补做（§4.4 可选）；heavy 桶上界 +0.059 略超非劣界，干净源上的非劣未测，记 §8。
