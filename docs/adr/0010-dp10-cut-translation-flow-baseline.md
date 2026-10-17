# ADR-0010：字幕翻译流程基线改为 dp10-cut

状态：已接受。  
日期：2026-10-17。  
替代：[ADR-0009](0009-dp6-grp-translation-flow-baseline.md)（dp6-grp 的批次规则）。[ADR-0006](0006-b10-joint-translation-flow-baseline.md) 的 joint 提示，以及 [ADR-0005](0005-apex-i-compact-translation-baseline.md) 的模型、引擎、采样（`official30b-cached-v1`）、context 和运行时参数**全部保持不变**。  
范围：只改研究侧的完整 SRT 流程基线（`translation_v3`、`just translation-srt`、后续探索的对照）。产品包 `kototoki/` 的翻译配方 `b10-joint-degrade-v1` **不在本决定内**。

## 决定

用户在阅读[上限 10 条的切法模拟](../research/2026-10-17-dynamic-cut-batching-simulation.md)后决定：每批待翻译不超过 10 条、可见不超过 12 条；在这个上限下，按"分级切点 + ≥20 s 硬切"打包。因为现有样本测不出不同门槛之间的差别，取值按逻辑合理推定，不再做 GPU 筛选。

- 拼包：每个场景（整片 SRT 是一个场景）用动态规划取总惩罚最低的切法，任意两条之间都可以切。每包代价 = (条数 − 10)² ＋ 包内每个 ≥2 s 停顿按秒数计 1 分；<6 条的包加 1000 分；超过 10 条或包内有 ≥20 s 停顿不可行。
- 分级切点：在 <0.5 s 的停顿处切加 6 分，<1 s 加 3 分，<2 s 加 1 分，≥2 s 不加；缺时间戳按无停顿（加 6 分）。效果是切点在可行范围内自动挪到最长的停顿上。
- 只读邻文：与 dp6-grp 相同，前一条在停顿 <5 s 时可见，后一条只在停顿 <1 s 时可见；可见总数不超过 12 条。
- 提示、grammar、采样与其余固定项与 b10-joint 相同。

## 身份与入口

- 配方：`experiments/translation_v3` 内置配方 `dp10-cut`（字段 `gap_pack`，加 `cut_penalty`，版本 `gap-pack-v2`），recipe_hash `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`，由 `test_recipes.AdoptedBaselineTest` 固定。
- 完整 SRT 入口：`just translation-srt --srt <ja.srt> --seed <S> --out <chn.srt>`，即 `python -m experiments.translation_v3 translate-srt --recipe dp10-cut`。
- `dp6-grp`、`b10-joint` 保留为内置配方，hash 不变（`gap-pack-v1` 的行为未改），可作对照。

## 证据与已知代价（如实记录）

- **没有质量证据**：没有 GPU 生成，也没有裁判。v7 已知 dp6-grp 与 b10-joint 无可分辨差异；dp10-cut 的质量按"介于两者之间、切点偏向停顿"推定。用现有 v7 裁判数据按停顿长度分组，测不出任何门槛效应（模拟文档 §4）。
- 离线切包（正式 `build_batches`）：

  | | dev 请求 | dev 平均 | 产品请求 | 产品平均 | 跨 ≥10 s 的包 dev／产品 | 切点在 ≥1 s 停顿 dev／产品 |
  | --- | --- | --- | --- | --- | --- | --- |
  | b10-joint | 554 | 9.74 | 232 | 9.99 | 27% / 50% | 30% / 64% |
  | dp6-grp | 685 | 7.88 | 344 | 6.74 | 0 / 0 | 92% / 100% |
  | dp10-cut | 621 | 8.69 | 296 | 7.83 | 14% / 22% | 68% / 95% |

- 相对 dp6-grp 放弃了"包内绝不跨 ≥10 s 停顿"：14%（dev）／22%（产品）的包跨 10–20 s 的停顿；没有包跨 ≥20 s。
- 产品时间轴上 <6 条的包仍有 15%（dev 4%），来自被 ≥20 s 停顿夹出的短段。

## 后续

- 若之后要验证，以 dp6-grp 或 b10-joint 为对照在 dev 上同包筛选；确认须用全新隔离的集合。
- 是否同步到产品 `b10-joint-degrade-v1` 另行裁定。
- 历史报告、台账与 v3–v7 产物不改写。
