# 第六轮探索（v6）：场景感知分批

研究文档（唯一进 Git 的进度与结论记录）：[docs/research/2026-10-16-scene-aware-batching-v6.md](../../docs/research/2026-10-16-scene-aware-batching-v6.md)。本 spec 只做执行层面的拆解，问题、边界与判定纪律以研究文档 §1–§5 为准，不在此重复。

## 目标

回答研究文档 §3 的 Q1、Q2、Q3，每个答案带区间，剧集与电影分开。成功 = 三个问题都有答案，不是找到显著配方；满足 §5 任一停止条件即结题。

## 固定项

- 对照 `b10-joint`（recipe_hash `2ba68054…`）；模型、量化、采样、提示、裁判（`claude-opus-5-5-mqm-v1`）都不变。
- 唯一变化：批次在哪里切、邻文取不取。
- 不做多候选／多次翻译再挑选（ADR-0008）；不改 `kototoki/`；不做根环境 `uv sync|add|lock`。
- `translation_v3` 只加默认值不进 `spec()` 的字段，用测试证明已有配方 hash 不变；新脚本放 `experiments/scene_batching_v6/`，附离线测试。

## 数据

- 集合、参考与 b10-joint／c0 run：`.local/translation-evaluation/hy30-flow-v4/`（只读）。
- 本轮产物：`.local/scene-batching-v6/`（新 run、裁判结果、分析 JSON）。

## 票据

| 编号 | 内容 | 资源 |
| --- | --- | --- |
| 01 | Q1 离线分析：受影响 cue 的错误类别分布、批边界自然实验 | 离线 |
| 02 | 场景感知切法实现＋受影响子集构造＋离线测试（hash 不变） | 离线 |
| 03 | Q2 筛选：dev 主 seed 生成、受影响子集裁判（候选＋对照同包重判）、配对比较 | GPU＋Claude 配额 |
| 04 | Q2 复现：dev 重复 seed（仅当 03 方向成立） | GPU＋Claude 配额 |
| 05 | Q3 判断与结题 | 离线 |

## 预算

- 生成 run 以个位数为目标：每个变体在 dev 上 3 个 run（每个 seed 只覆盖它的场景块，约 14–16 场景），复现再 3 个。
- 裁判只判受影响子集所在窗口（候选＋对照各一次）。
