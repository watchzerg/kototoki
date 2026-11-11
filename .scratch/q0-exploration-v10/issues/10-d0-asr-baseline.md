# 10 D0 ASR 源基线

Status: resolved
Type: GPU
Stage: D
Blocked by: 09

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-21-q0-exploration-v10.md）。

## 执行记录

- 15:00–16:10 `translate-srt` 12 个整片 run（Q0 每部约 560 s、H0 约 150–180 s），全部 exit 0、全量交付；judge 计划 `D/judge/qwen-wide-vs-dp10-cut/plan.json`（exact 60、light 80、heavy 80，x＝H0、y＝Q0），28 包 $1.39。

## Answer

**产品 ASR 源上 Q0 明显好于 H0。** Δ＝每单元惩罚（Q0 − H0，`v5-asr-pairwise-v1`，minor 1／major 5／critical 10），条目 bootstrap CI90：
- exact −0.42［−0.82, −0.02］（n 60）、light −1.15［−1.73, −0.61］（80）、heavy −0.43［−0.93, +0.09］（80）、light＋heavy −0.79［−1.16, −0.43］、全体 −0.69［−0.98, −0.40］；两部同向（HF II −0.72、HF III −0.64）。偏好 Q0 36%／H0 21%／平 43%。
- 人名相关错误（terminology 或注释提到人名／称呼／音译）H0 50 对 Q0 22，差 CI90［−0.17, −0.08］每条；addition 36 对 15；critical 7 对 7。
- 整片不一致率（`apply_table measure` 口径、替换前，两部 × 三 seed 平均）：**H0 0.126、Q0 0.047**。
- 代价：整片墙钟 Q0 每部约 560 s，H0 约 165 s（3.4×）。
- 这与 dev 上"剧集显著、电影跨 0"不同：产品时间轴上 H0 的静默门控几乎关掉了邻文（每包前 0.4、后 0.05 条，票据 09），Q0 仍看前 20 后 5，在 ASR 误识与专名上受益明显。
