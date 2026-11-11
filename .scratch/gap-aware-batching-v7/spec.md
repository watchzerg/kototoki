# 第七轮探索（v7）：按静默拼包、停顿标记与两级结构

权威方案：[研究文档](../../docs/research/2026-10-16-gap-aware-batching-v7.md)（§3 问题、§4 已定设计、§5 判定纪律与停止条件）。本文只记执行层面的约定，不重复方案。

## 范围

- 三个变体，不追加：`dp6`（§4.1–4.3）、`mark5`（§4.4）、`dp6-grp`（§4.5）。对照固定 `b10-joint`（`2ba68054…`）。
- 不换模型、量化、采样、裁判（`claude-opus-5-5-mqm-v1`）；joint 提示正文不改；唯一提示改动是 mark5 的停顿行；不做多候选／再挑选（ADR-0008）；不改 `kototoki/`；每批可见 cue ≤ 12。
- GPU：最多 18 个 dev run（3 变体 × 主 seed 20261011–13 + 重复 seed 20261021–23）。

## 实现落点

- 切法与标记：`experiments/translation_v3`，新增 `Recipe.gap_pack`（`gap-pack-v1`）与 `Recipe.pause_marks`（`pause-mark-v1`），默认值不进 `spec()`，已有 hash 不变（`scene_batching_v6/test_v7.py` 固定 b10-joint、c0、t03、mbr8c、tctx10、gsnap5）。
- 驱动与统计：扩展 `experiments/scene_batching_v6/`（不改名，v6 的复现命令保持有效），`--round v7` 切到根目录 `.local/gap-aware-batching-v7/`；`sim7.py` 离线模拟，`v7.py` 全集比较。
- 配方文件：`.local/gap-aware-batching-v7/recipes/{dp6,mark5,dp6-grp}.json`。

## 评测

- 全集裁判：每个 seed 的对照副本 `b10-joint-ctl` 在全集上判一次，三个变体共用（全集时包组成与 run 无关，所有臂相同）。
- 主终点：全集 accuracy Δ（剧集、电影分开，50:50 总览），CI90 由 v4 的作品分层 5 条窗口 bootstrap 给出；wrong-referent、mistranslation、negation-number-condition 分开；critical、major+；交付失败；成本（请求数、输出 token、墙钟、显存峰值、批大小与可见 cue 分布）。
- 非劣：每类 CI90 上界 < +0.05；critical 点估计 ≤ +0.002／条。显著变差：某类 CI90 下界 > 0（该变体停止）。
- 复现：主 seed 筛选后，无论结果如何（除非已显著变差而停止），都用重复 seed 独立配对一次。Q4 采纳要求两次都非劣。
