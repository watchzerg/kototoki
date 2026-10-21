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

## v7（按静默拼包、停顿标记与两级结构）

[v7 研究文档](../../docs/research/2026-10-16-gap-aware-batching-v7.md)（已结题，结论见 §7.7）复用本包：所有命令加 `--round v7`（`python -m experiments.scene_batching_v6 --round v7 <命令>`），根目录改为 `.local/gap-aware-batching-v7/`。切法与标记在 `translation_v3` 的 `Recipe.gap_pack`／`pause_marks`。与 v6 的差别：

- `subset` 列出受影响 cue（批次目标、邻文或停顿标记与对照不同），但保留覆盖场景的**全部**窗口，所以 `judge` 判全集；全集时包组成与 run 无关，每个 seed 的对照副本只判一次，三个变体共用。
- `judge-control --seed S` 在全集上判对照副本；变体用 `judge --variant R --seed S --candidate-only`，不再碰对照的裁判锁。
- `compare --variant R --seeds S… [--against R2] [--label L]`（`v7.py`）：全集配对 Δ（按类别、分指标）、受影响／未受影响（译文相同的未受影响 cue 即噪声底）两部分、critical／major+、对照重判 − v4 原判、非劣判定（每类 CI90 上界 < 0.05、critical ≤ +0.002）、交付与成本（批大小与可见 cue 分布）→ `summaries/v7-R-vs-R2[-L].json`。`--against` 可换成另一个变体做直接比较。
- `pooled --variant R --seed-sets a,b,c/d,e,f [--against R2]`：两组独立 seed 的配对差取均值。
- `simulate`（`sim7.py`，离线）：dev 与产品 `ja.srt`（`.local/quality-exploration-v5/01/out-w0/`）上的间隔分布与各配方的包大小分布 → `sim/sim.json`。

## v9（通用模型在同一接缝下直接翻译）

[v9 研究文档](../../docs/research/2026-10-21-general-model-translation-v9.md)复用本包：`--round v9`，根目录 `.local/general-model-translation-v9/`，三个臂 `dp10-cut`（Hy-MT2 对照，本轮新生成，无对照副本）、`qwen-narrow`、`qwen-wide`（`v9.py`）。

| 命令 | 作用 | 资源 |
| --- | --- | --- |
| `status` | 同上 | 离线 |
| `check-batches [--seed S]` | 三个臂在整个 dev 上按配方算出的每场景目标 ID 序列必须逐字相同；给 seed 时再核对 run 文件 → `checks/` | 离线 |
| `smoke --recipe R` | Qwen 臂在主 seed 块的 5 个包（剧集 3、电影 2，各取一部作品第一个 ≥6 条的包）上生成一次，保存原始回复 → `smoke/R.json` | **GPU** |
| `generate --recipe R --seed S` | Hy 臂走 v3 compat server，Qwen 臂走 `translation_v3/qwen.py`；可续跑 | **GPU** |
| `judge-run --recipe R --seed S` | 该 run 的全集裁判（包组成只取决于 split，三个臂相同）；退出码 75 = 配额阻塞 | **Claude 配额** |
| `compare9 --variant R [--against R2] --seeds S…` | 全集配对 Δ：accuracy、各 accuracy 类别、fluency 及 grammar／unnatural／register、major+、critical（作品等权、剧集／电影分开、窗口 bootstrap），§5 的 L1 关门与 L2 非劣／改善标志，逐作品 Δ，交付与代价（墙钟、载入、token、生成 tok/s、显存峰值、重试、失败）→ `summaries/v9-R-vs-R2.json` | 离线 |

## 验证

`uv run --locked --offline python -m unittest experiments.scene_batching_v6.test_v6 experiments.scene_batching_v6.test_v7 experiments.scene_batching_v6.test_v9`（v6 离线 14 项：间隔分类、对比统计、已有配方 hash 不变、gap_split 校验与切批规则、随机场景不变量、受影响 cue 判定；v7 13 项：已有配方与 gsnap5 hash 不变、新字段进 hash 与校验、动态规划与暴力枚举一致、硬边界与小包不变量、小组拆分、邻文规则、标记位置与提示／grammar、生成链路发送标记、受影响 cue 计入标记、非劣判定、模拟计数）。真实数据上的端到端运行记录在研究文档 §7、§9。v9 7 项：cue 指标与未交付、L1 关门与 L2 标志、专名错误规则、代价字段、dev 上三臂目标 ID 相同、smoke 包选取。
