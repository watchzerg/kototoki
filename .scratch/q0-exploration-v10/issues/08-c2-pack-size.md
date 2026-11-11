# 08 C2 输出包放大

Status: resolved
Type: GPU
Stage: C
Blocked by: 07

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-21-q0-exploration-v10.md）。

## 执行记录

## Answer

未做：§4.3 C1 的门"wrong-referent 任一类 CI90 下界 >0 → 记'随邻文增长'，C2 跳过"被 `qwen-scene` 的电影 wrong-referent +0.026［+0.001, +0.051］触发。配方 `qwen-p15`（`gap_pack` 目标与上限 15、min 8、可见上限 40；dev 434 包对 Q0 621 包，−30% 请求）已写好未运行。重开条件写 §8：门只是勉强越线且 wide50 未见同向，若用户认为该门过严，可按原设计先 1 seed（C 预算尚余 GPU 6、裁判 $62）。
