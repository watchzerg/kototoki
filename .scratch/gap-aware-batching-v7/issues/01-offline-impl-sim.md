# 01 离线实现与模拟

Status: resolved
Type: task

## 目标

实现三个变体的切法与标记（`translation_v3`），证明已有配方 hash 不变；在 dev（字幕组时间轴）与产品 `ja.srt`（自家 VAD／ASR 时间轴）上离线复算包大小分布（研究文档 §4.6）。不占 GPU。

## 执行记录

- 2026-10-16 claimed。
- `Recipe.gap_pack`（`gap-pack-v1`）：键 `min, max, soft_gap, hard_gap, soft_weight, small_penalty, group_gap, group_max, context_both_below, context_before_below, max_visible`；目标包大小取 `batch_count`（10）。`batching.gap_pack_cuts` 对每个场景做动态规划：每包代价 (大小−10)² ＋（<min 时）small_penalty ＋ soft_weight × 包内每个 ≥soft_gap 的间隔秒数；包内有 ≥hard_gap 间隔或超过 max 条不可行。`group_gap` 非空时切点只能落在 `gap_groups` 边界（<1 s 连续 cue 为一组，>12 条的组等分成 ⌈n/10⌉ 份）。邻文：前句在其停顿 <5 s 时可见，后句只在 <1 s 时可见，可见 >12 时先去后句再去前句。缺时间戳按无间隔处理。
- `Recipe.pause_marks`（`pause-mark-v1`）：`{"min_gap": 5.0}`；`Batch.pauses` 记录可见列表里每个 ≥5 s 静默的位置与秒数（含邻文与正文之间），`recipes.mark_pauses` 在只读上下文 JSON 列表的对应位置插入 `{"pause": "此处约N秒无台词"}`（N 四舍五入为整秒）；待译 JSON 与 ID grammar 不变；scene 文件的 batch 记录只在有标记时多一个 `pauses` 键。键名、模板文字与版本号进 hash。
- 驱动：扩展 `experiments/scene_batching_v6/`（`--round v7`、`sim7.py`、`v7.py`），不改名，v6 复现命令不变。`q2._batch_map` 把 `pauses` 计入批次键（v6 旧数据无此键，结果不变）。
- 配方：`.local/gap-aware-batching-v7/recipes/{dp6,mark5,dp6-grp}.json`。
- 测试：`uv run --locked --offline python -m unittest experiments.scene_batching_v6.test_v7`（13 项）、`test_v6`（14 项）、v3 全套 55 项、v4 全套，全部通过。
- 模拟：`P simulate` → `.local/gap-aware-batching-v7/sim/sim.json`。

## 实现细节的取值与理由

| 细节 | 取值 | 理由 |
| --- | --- | --- |
| 软边界惩罚 | 1 分／秒（`soft_weight` 1.0） | 扫描 0–20：1.0 在 dev 上精确复现研究文档 §2.2 讨论行（请求 1.17×、平均 8.3 句、<8 句 24%、跨 ≥5 s 22%、跨 ≥10 s 0%），满足 §4.2 目标（跨 ≥10 s 为 0、跨 ≥5 s 约 20%、平均 ≥8）。更大权重使跨 ≥5 s 只再降 2–4 个百分点，平均包却掉到 8 以下 |
| 小包惩罚 | 1000（`small_penalty`） | 远大于任何可行替代方案的代价，<6 句的包只在被硬边界或场景首尾夹出的短段里出现（随机场景测试验证） |
| 标记文字 | `{"pause": "此处约N秒无台词"}` | 只陈述时间事实，不写"换场景"之类推断；用 `pause` 键而非 `id`/`text`，不像台词，也不进待译 JSON；grammar 只含目标 ID，标记不可能被输出，所以 grammar 不需要改 |
| 并列最优 | 先找到者（最后一包最短） | 确定性；与结果无实质关系 |

## Answer

三个变体已实现并有离线测试；已有配方（b10-joint、c0、t03、mbr8c、tctx10、gsnap5）hash 不变。recipe_hash：dp6 `0ba0a7c9fc23…`、mark5 `745c45eead35…`、dp6-grp `ae473cdce915…`（全文见 `sim.json`）。

| 方案 | 集合 | 请求／b10 | 平均每包 | <6 句 | <8 句 | =12 句 | 跨 ≥5 s | 跨 ≥10 s | 受影响 cue |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b10-joint | dev | 1.00 | 9.74 | 2.5% | 4.3% | 0% | 43.7% | 27.4% | — |
| dp6 | dev | 1.17 | 8.33 | 16.2% | 23.8% | 5.9% | 22.4% | 0% | 97.8% |
| mark5 | dev | 1.00 | 9.74 | 2.5% | 4.3% | 0% | 43.7% | 27.4% | 49.7%（带标记的批 48.9%，共 502 个标记） |
| dp6-grp | dev | 1.24 | 7.88 | 20.6% | 36.5% | 9.8% | 20.1% | 0% | 99.6% |
| b10-joint | 产品 | 1.00 | 9.99 | 0% | 0% | 0% | 74.1% | 50.4% | — |
| dp6 | 产品 | 1.47 | 6.80 | **34.3%** | 45.2% | 4.7% | 37.0% | 0% | 100% |
| mark5 | 产品 | 1.00 | 9.99 | 0% | 0% | 0% | 74.1% | 50.4% | 78.4% |
| dp6-grp | 产品 | 1.48 | 6.74 | **34.9%** | 46.2% | 6.1% | 36.6% | 0% | 100% |

- dev 剧集／电影分开：dp6 请求 1.15×／1.20×，<6 句 13%／21%；dp6-grp 1.22×／1.26×。
- 间隔分布：dev 中位数 0.61 s、p90 4.3 s、≥5 s 8.6%、≥10 s 4.5%；产品 1.36 s、p90 9.4 s、≥5 s 17.8%、≥10 s 9.5%，与研究文档 §2.3 一致。
- **产品时间轴上 dp6／dp6-grp 的 <6 句包约 34–35%，远超 §4.6 的 10% 线**：产品的 ≥10 s 硬边界约是 dev 的两倍，把台词切成大量短段。按 §4.6 写入研究文档 §8（门槛是否按产品时间轴重定），本轮不改门槛。
- dp6-grp 相对 dp6 多 5.6% 请求（§4.5 预期 7–12%）。§2.2 讨论行"只在小组边界切"的 1.12×、跨 ≥10 s 11% 显然没有执行硬边界；按 §4.5"门槛同 4.1–4.3"执行硬边界后跨 ≥10 s 为 0，请求 1.24×。
- 可见 cue 上限 12 在三个变体上都成立；dp6 可见均值 9.0（b10 11.6），dp6-grp 8.4。
