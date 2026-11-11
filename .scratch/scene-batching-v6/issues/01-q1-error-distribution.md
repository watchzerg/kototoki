# 01 Q1：错误是否集中在跨场景混批处

Status: resolved
Type: research
Blocked by: —

## 范围

只读 v4 的 b10-joint run 与裁判结果（dev 6 个 run、confirm 3 个 run），离线回答：少数派一侧／间隔两侧 cue 的错误是否以 wrong-referent 等跨 cue 类别为主。

设计（理由见执行记录）：

1. **类别分布**：阈值 T ∈ {5, 10, 20} s。把每条 cue 分为 minority（所在批含 ≥T 间隔，且在被间隔切开的较小一段）、majority（同批的最大段）、clean（所在批无 ≥T 间隔）。分别报 accuracy 惩罚及 wrong-referent、mistranslation、negation-number-condition、其他四类的每条惩罚；作品内先求 minority − clean 差，再作品等权、剧集／电影分开，场景重抽（作品内分层）CI90。另报 wrong-referent 占 accuracy 惩罚的份额差。
2. **批边界自然实验**（主要证据）：b10 的边界固定在 cue 0、10、20…，与内容无关。一个 ≥T 间隔落在批边界上（批没有跨越它）还是落在批内（批跨越它），近似随机。比较"紧邻间隔的 cue"（间隔前 1 条＋后 1 条）在两种情况下的惩罚与类别。两组 cue 都处在场景边界，位置特殊性相同，差异只来自是否混批。c0（b5）的 dev run 提供第二套边界（每 5 条），合并时分配方单独报。

## 完成标准

- 表：dev／confirm × 剧集／电影 × T 的 minority − clean 分类别差（CI90）；自然实验的 in-batch − at-boundary 差（CI90）与样本量。
- 一句话结论：机制成立／不成立／证据不足，以及对 02、03 投入的影响。

## 文件所有权

`experiments/scene_batching_v6/`（gaps.py、q1.py 及测试）；产物 `.local/scene-batching-v6/q1/`。

## 执行记录

- 2026-10-16 设计理由：§2.2 的"少数派 vs 干净批次"比较混有位置特殊性（少数派一侧多是场景开头／孤立短句）。b10 的批边界固定在 cue 0、10、20…，与内容无关，间隔落在边界上还是批内近似随机，所以"紧邻间隔的 cue：间隔在批内 vs 在批边界"是同为场景边缘 cue 的准随机对比，作为主要证据。边界组的 cue 总在批首／批尾，因此另做位置检查（干净批次中批首尾 vs 批内部）。c0（b5）dev run 提供第二套边界。
- 区间：作品内先求差，作品等权、剧集／电影分开、总览 50:50；作品内按场景重抽 2000 次（种子 `v6-scene-bootstrap-20261016`），CI90。每条 cue 取该配方各 run 均值（dev b10-joint 6 个 run 每条 2 次，confirm 3 次，c0 dev 1 次）。
- 命令：`.venv/Scripts/python.exe -X utf8 -c "from experiments.scene_batching_v6 import q1; q1.main()"`（约 30 秒）；产物 `.local/scene-batching-v6/q1/q1.json`。缺失窗口 0，交付失败 0。
- 离线测试：`python -m unittest experiments.scene_batching_v6.test_v6`（6 项通过）。

## Answer

**结论：机制存在但很小。** 少数派一侧的超额惩罚不是 wrong-referent 造成的，而且 dev 与 confirm 方向不一致，主要是位置／难度混杂；但准随机的批边界对比显示，批内跨过静默间隔会让间隔两侧的 cue 多出少量 wrong-referent，三个对比臂、两个阈值方向一致。按受影响 cue 占比折算，全集效应约 0.004，低于确认 MDE（0.017–0.020）。按 §5，Q1 没有显示"与干净批次无异"，继续 Q2，但只做一个主变体。

| 对比（T=10 s，Δ 每条惩罚） | 臂 | accuracy 剧集／电影 | wrong-referent 剧集／电影／总 | mistranslation 总 |
| --- | --- | --- | --- | --- |
| 少数派 − 干净 | dev b10-joint | +0.187［+0.05, +0.31］／+0.148［−0.09, +0.40］ | −0.018／+0.028／+0.005［−0.03, +0.06］ | +0.112［+0.01, +0.19］ |
| 少数派 − 干净 | confirm b10-joint | +0.110［−0.04, +0.31］／−0.067［−0.26, +0.02］ | −0.026／+0.005／−0.010［−0.05, +0.03］ | +0.030［−0.08, +0.08］ |
| 间隔在批内 − 在批边界 | dev b10-joint | −0.183／+0.531 | +0.036／+0.059／**+0.048［+0.01, +0.08］** | +0.085［−0.16, +0.28］ |
| 间隔在批内 − 在批边界 | confirm b10-joint | +0.366／+0.098 | +0.108／+0.079／**+0.094［+0.04, +0.16］** | +0.136［+0.01, +0.29］ |
| 间隔在批内 − 在批边界 | dev c0（b5） | +0.084／+0.356 | −0.022／+0.124／**+0.051［+0.01, +0.11］** | +0.125［−0.11, +0.36］ |
| 位置检查：干净批次 批首尾 − 内部 | dev／confirm b10-joint | — | 总 +0.003［−0.03, +0.04］／+0.048［+0.00, +0.08］ | — |

- T=5 s 时 wrong-referent 的批内 − 边界同样为正：dev +0.049［+0.03, +0.07］、confirm +0.038［−0.10, +0.10］、c0 +0.057［+0.01, +0.10］。T=20 s 边界组只剩 2–11 条，无法估计。
- 少数派一侧的 wrong-referent 占 accuracy 惩罚的份额**不高于**干净批次（T=10：dev 剧集 −0.13、confirm 剧集 −0.10，区间多跨 0）；超额主要在 mistranslation（及 dev 剧集的 negation-number-condition），符合"开头／孤立句更难"的混杂。
- 同批的多数派一侧 wrong-referent 反而**低于**干净批次（dev T=10 总 −0.053［−0.08, −0.03］），negation-number-condition 在三个臂都低约 0.02。
- 位置检查：批首尾 cue 的 wrong-referent 不低于内部，所以边界组较少的 wrong-referent 不能用"处在批边缘"解释。
- 局限：边界组样本小（T=10：dev 35 条、confirm 62 条、c0 73 条），区间来自少数作品，偏乐观；accuracy 总量的批内 − 边界在剧集与电影之间方向不稳定。
- 规模：T=10 时紧邻间隔的 cue 约占 8%，wrong-referent +0.05 × 8% ≈ 全集 0.004；即使把 accuracy 总量的 +0.2 全算上也只有约 0.016。

对 02、03 的影响：切法应以"别让批跨过间隔"为目标（把切点挪到间隔处），而不是缩小批次；主终点放在受影响子集，并单独报 wrong-referent。
