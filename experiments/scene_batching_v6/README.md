# 第六轮探索：场景感知分批（scene_batching_v6）

实现[v6 研究文档](../../docs/research/2026-10-16-scene-aware-batching-v6.md)的 Q1 离线分析与 Q2 干预实验（已结题，结论见文档 §7）。对照 `b10-joint`，裁判 `claude-opus-5-5-mqm-v1` 不变。

切法本身在 `translation_v3`：`Recipe.gap_split`（`gap-split-v1`，见 [translation_v3 README](../translation_v3/README.md)）。本包只导入 v3／v4 代码，不修改冻结产物；v4 根目录 `.local/translation-evaluation/hy30-flow-v4/` 的集合、参考与 run 只读。

## 命令

仓库根目录运行 `uv run --locked --offline python -X utf8 -m experiments.scene_batching_v6 <命令>`，产物根目录 `.local/scene-batching-v6/`。

| 命令 | 作用 | 资源 |
| --- | --- | --- |
| `status` | 只读：各 run 生成状态、裁判包进度、子集、配额阻塞、GPU 锁 | 离线 |
| `q1` | Q1：少数派／多数派／干净批次对比、批边界自然实验、位置检查 → `q1/q1.json` | 离线，约 30 秒 |
| `generate --recipe R --seed S` | 在 v4 dev 的 seed 场景块上生成（v3 可续跑生成，`.local/gpu.lock`） | **GPU**，约 4.5 分钟 |
| `copy-control --seed S` | 复制 v4 b10-joint run 的 `run.json`＋`scenes/` 为 `b10-joint-ctl__sS__dev` | 离线 |
| `subset --variant R --seed S` | 受影响 cue（批次的目标或邻文与对照不同）与所在 5 条窗口；统计未受影响 cue 译文是否逐字相同 | 离线 |
| `judge --variant R --seed S` | 只判子集窗口：候选与对照副本用相同包组成各判一次；退出码 75 = 配额阻塞 | **Claude 配额** |
| `compare --variant R --seeds S… [--label L]` | 受影响 cue 配对差（作品等权、剧集／电影分开、窗口 bootstrap）、分类别、critical／major+、全集护栏、对照重判噪声、成本 → `summaries/` | 离线 |

两次独立实现的合并估计：`q2.pooled(variant, [[主 seed…], [重复 seed…]])`。

## 验证

`uv run --locked --offline python -m unittest experiments.scene_batching_v6.test_v6`（离线 14 项：间隔分类、对比统计、已有配方 hash 不变、gap_split 校验与切批规则、随机场景不变量、受影响 cue 判定）。真实数据上的端到端运行记录在研究文档 §7、§9。
