# 02 场景感知切法实现与受影响子集

Status: resolved
Type: task
Blocked by: 01

## 范围

- `translation_v3.recipes.Recipe` 加切法字段（默认值不进 `spec()`），`batching.build_batches` 按该字段切批；测试证明 v3／v4／v5 已有配方 hash 不变（含 b10-joint `2ba68054…`）、默认切法逐批不变。
- `experiments/scene_batching_v6/`：受影响子集构造（与对照切法相比，目标集或邻文发生变化的批覆盖的 cue → 所在 5 条 tile 窗口）、生成与裁判驱动（读 v4 集合与参考，写本轮根目录）、对照副本 run（只复制译文，供同包重判）、配对比较、status。
- 阈值、弹性范围、邻文规则按 01 结果与 §2.1 间隔分布选定，理由写在执行记录。

## 完成标准

离线测试全部通过（新测试＋v3、v4 全套）；对 dev 主 seed 计算每个变体的受影响批／cue 数、每批可见 cue 数上限不超过对照（12）。

## 文件所有权

`experiments/translation_v3/{recipes,batching,test_*}.py`（只加字段）、`experiments/scene_batching_v6/`。

## 执行记录

- 2026-10-16 先实现并模拟了"顺序弹性"切法（从上一切点起在 [min, max] 内找最大间隔），网格 min∈{6,8}、max∈{10,12}、cut∈{3,5,10} s、硬边界∈{无,20 s}。问题：一个切点挪动后，后面所有批次都跟着平移，受影响 cue 占 55–90%，配对比较会被与间隔无关的重新分组稀释；有硬边界时请求数增加 4–17%，与 Q3 的"墙钟不增"冲突。
- 改为"网格吸附"（`gap-split-v1`，`batching.gap_cuts`）：保留 b10 的切点网格（10、20…），每个网格点在 ±snap 条内挪到最大的 ≥cut_gap 静默处（平局取离网格点近的、再取靠前的），任何批不超过 max 条；邻文只在与它之间的静默 < context_gap 时才取，可见条数超过 max_visible 时先丢后邻文、再丢前邻文。批次数与 b10 完全相同（墙钟不增），只有靠近间隔的批会变。模拟（dev／confirm）：
  | 切法 | 批数／b10 | 跨 ≥5 s 批占比 | 跨 ≥10 s | 跨 ≥20 s | 邻文跨 ≥5 s | 受影响 cue |
  | --- | --- | --- | --- | --- | --- | --- |
  | b10-joint | 1.000 | 0.437／0.457 | 0.274／0.260 | 0.135／0.099 | 0.082／0.099 | — |
  | 吸附 snap2 cut5 | 1.000 | 0.370／0.372 | 0.200／0.183 | 0.078／0.062 | 0 | 0.475／0.486 |
  | 吸附 snap3 cut5 | 1.000 | 0.350／0.362 | 0.186／0.178 | 0.076／0.058 | 0 | 0.539／0.539（尾批可达 13 条，超上限） |
  | 顺序 min8 max12 cut5 | 0.995／1.018 | 0.367／0.352 | 0.192／0.178 | 0.082／0.057 | 0 | 0.753／0.705 |
  | 顺序 min6 max12 cut5 硬 20 | 1.083／1.097 | 0.277／0.300 | 0.115／0.115 | 0 | 0 | 0.849／0.790 |
- 选定唯一主变体 **`gsnap5`**：snap 2、max 12、cut_gap 5 s、context_gap 5 s、max_visible 12（recipe_hash `f58afa33…`，`.local/scene-batching-v6/recipes/gsnap5.json`）。理由：5 s 约为相邻间隔 p90（4.3 s）之上，Q1 的 wrong-referent 效应在 5 s 与 10 s 同样大，5 s 修掉更多跨越；snap 2 保证所有批 ≤12 条、可见 ≤12 条（不增大显存上限），批数不变；跨间隔的邻文全部去掉。与顺序切法相比，修掉的跨越相当，受影响 cue 少三分之一。不做硬边界：会增加请求数，而 Q1 在 20 s 上没有可估的效应。
- dev 主 seed 下受影响 cue：20261011 951／1844（51.6%），20261012 707／1663（42.5%），20261013 905／1890（47.9%）；批数 189／172／193，与 b10-joint 相同。
- 代码：`translation_v3/recipes.py` 加 `gap_split` 字段（默认 None，在 `V4_DEFAULTS` 中，不进 `spec()`；非空时 `versions.gap_split = gap-split-v1`）；`translation_v3/batching.py` 加 `silence`、`gap_cuts`、`_neighbours`。`experiments/scene_batching_v6/q2.py`（生成、对照副本、子集、裁判、比较）、`status.py`、`__main__.py`。
- 测试：`python -m unittest experiments.scene_batching_v6.test_v6`（14 项，含 b10-joint／c0／t03／mbr8c／tctx10 的已记录 hash 不变、gap_split 进 hash、校验、无合格间隔时与 b10 逐批相同、吸附与邻文规则、300 个随机场景上批数相同／≤12 条／可见 ≤12、受影响 cue 判定）；v3 全套 55 项、v4 19 项、quality_v5 全套通过。

## Answer

实现完成。主变体 `gsnap5`：b10 网格切点在 ±2 条内吸附到最大的 ≥5 s 静默，跨 ≥5 s 静默的只读邻文去掉；批数与 b10 相同，单批 ≤12 条、可见 ≤12 条。dev 上跨 ≥10 s 间隔的批从 27% 降到 20%，邻文跨间隔从 8% 降到 0，受影响 cue 约 48%。已有配方 hash 不变已由测试证明。
