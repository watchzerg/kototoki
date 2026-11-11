# 第八轮探索（v8）：同一句话小组内语序重排

权威方案：[研究文档](../../docs/research/2026-10-18-group-reorder-v8.md)（§3 问题、§4 已定设计、§5 判定纪律与停止条件）。本文只记执行层面的约定，不重复方案。

## 范围

- 唯一变体 `grp1`（§4.3）：`dp10-cut` 的切包与邻文＋包内 R2+ 划组（<1.0 s，§4.1）＋`joint-understanding-v2` 与一行 `groups` 注入（§4.2）。对照 `dp10-cut`（`ee72ce66…`），本轮新生成。
- 不换模型、量化、采样、裁判（`claude-opus-5-5-mqm-v1`）、切包、邻文、grammar；不做多候选／再挑选（ADR-0008）；不改 `kototoki/`；每批可见 cue ≤ 12。
- GPU：最多 12 个 dev run（对照＋候选 × 主 seed 20261011–13 ＋ 重复 seed 20261021–23），另有 02 小样（10 个包）。

## 实现落点

- 配方与提示：`experiments/translation_v3`，`Recipe.groups`（`{"gap": 1.0}`，版本 `group-reorder-v1`）、`JOINT2_INSTRUCTION`（`joint-understanding-v2`）、内置 `grp1`（hash `5aaf3e77…`）。默认值不进 `spec()`；`test_recipes.GroupReorderTest` 固定 17 个旧内置配方的 hash。
- 划组：`translation_v3/batching.py::sentence_groups`（唯一实现），`reorder_groups/stats.py` 调用它。
- 终点工具：`experiments/reorder_groups/checks.py`（重排率、显示校验）、`coverage.py`（注入覆盖与 token 增量）。
- 驱动：沿用 `experiments/scene_batching_v6/`，需加 `--round v8`（根目录 `.local/group-reorder-v8/`），见 02。
- 产物根目录 `.local/group-reorder-v8/`；`.local/translation-evaluation/hy30-flow-v4/` 的集合与参考只读。

## 评测

- Q1（03）：生成完成后先算重排率（主阈值 0.2）与 30 组人工抽查；重排率接近严格对严格的噪声底（≥0.2 约 2–6%，见 01）即否定，不裁判。
- Q2（04）：全集裁判，候选与对照同期各判一次；另报"多 cue 组内 cue"与"单条组 cue"子集。非劣界 0.05，剧集、电影分开。
- Q3（04）：`checks.py` 在候选与对照上各报一次读速与占比偏差。
- 复现（05）：重复 seed 独立配对；Q4（06）看 §3 采纳条件是否两次都成立。
