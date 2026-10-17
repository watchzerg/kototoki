# ADR-0009：字幕翻译流程基线改为 dp6-grp

状态：已接受。  
日期：2026-10-17。  
替代：[ADR-0006](0006-b10-joint-translation-flow-baseline.md) 中关于完整 SRT 流程批次的部分。ADR-0006 的 joint 提示，以及 [ADR-0005](0005-apex-i-compact-translation-baseline.md) 的模型、引擎、采样（`official30b-cached-v1`）、context 和运行时参数**全部保持不变**。  
范围：只改研究侧的完整 SRT 流程基线（`translation_v3`、`just translation-srt`、后续探索的对照）。产品包 `kototoki/` 的翻译配方 `b10-joint-degrade-v1` **不在本决定内**，仍按源顺序每批 10 条。

## 决定

用户在阅读 [v7 研究文档](../research/2026-10-16-gap-aware-batching-v7.md) §7.7 后，明确决定把 `jpn.srt → chn.srt` 的流程基线从 b10-joint 改为 **dp6-grp**：

- 小组：相邻停顿 <1 s 的连续字幕组成一个小组，小组不拆；超过 12 条的小组等分成 ⌈n/10⌉ 份。
- 拼包：每个场景（整片 SRT 是一个场景）用动态规划取总惩罚最低的切法，切点只落在小组边界。每包代价 = (条数 − 10)² ＋ 包内每个 ≥2 s 停顿按秒数计 1 分；<6 条的包加 1000 分；包内有 ≥10 s 停顿或超过 12 条不可行。
- 只读邻文：前一条在停顿 <5 s 时可见，后一条只在停顿 <1 s 时可见；可见总数不超过 12 条。
- 提示、grammar、采样与其余固定项与 b10-joint 相同（`joint-understanding-v1`、ID JSON grammar、temperature 0.7、`n_predict` 4096、`cache_prompt`、context 8192）。

## 身份与入口

- 配方：`experiments/translation_v3` 内置配方 `dp6-grp`（字段 `gap_pack`，版本 `gap-pack-v1`），recipe_hash `ae473cdce915b16379a838cec15fc53e444d24686cd36c706e5f9d379ba2061e`。它与 v7 的 6 个 dev run 身份相同，由 `test_recipes.AdoptedBaselineTest` 固定。
- 完整 SRT 入口：`just translation-srt --srt <ja.srt> --seed <S> --out <chn.srt>`，即 `python -m experiments.translation_v3 translate-srt --recipe dp6-grp`。要求 SRT 带时间戳（SRT 总是带）。
- 之后的流程实验以 `dp6-grp` 为对照。`b10-joint` 保留为内置配方，hash 不变，可作历史对照。

## 证据与已知代价（如实记录）

v7 在 dev 集（5397 条，剧集与电影分开）上与 b10-joint 同包组成、同期全集裁判（`claude-opus-5-5-mqm-v1`），Δ 为每条 accuracy 惩罚差，区间 CI90：

| | 剧集 | 电影 | 总 |
| --- | --- | --- | --- |
| 主 seed 20261011–13 | −0.002［−0.036, +0.031］ | +0.029［−0.017, +0.075］ | +0.014［−0.015, +0.042］ |
| 重复 seed 20261021–23 | −0.017［−0.053, +0.018］ | −0.022［−0.067, +0.022］ | −0.020［−0.048, +0.009］ |
| 两次合并 | −0.009［−0.038, +0.019］ | +0.003［−0.035, +0.041］ | −0.003［−0.027, +0.021］ |

- 结论是**与 b10-joint 无可分辨差异**，不是更好。按 v7 预先定的 Q4 规则它**不满足**"两次都非劣"：主 seed 电影上界 +0.075 越过非劣界 0.05。用户知道这一点，仍按两次合并接近 0、且逻辑上合理（包不跨 ≥10 s 停顿、切点落在句子之间、可与语序工作共用边界）作出采纳。
- 相对 dp6（不按小组直接拼）非劣：总 −0.004［−0.027, +0.018］。
- critical：主 seed +0.0007［−0.0008, +0.0021］，重复 −0.0015［−0.0030, 0.0000］。交付失败 0／6。
- 成本：dev 上请求 +24%（685 对 554），平均每包 7.9 条，可见 cue 均值 8.4（b10-joint 11.6），墙钟与 b10-joint 持平（795／792 s 对 808／809 s），显存峰值 15.8 GiB 不变。
- **产品时间轴上代价更大**：在自家 VAD／ASR 生成的 HF II／III 整片 `ja.srt` 上离线模拟，请求为 b10 的 1.48 倍，<6 条的包占 34.9%（dev 为 20.6%），因为产品的 ≥10 s 停顿约为研究集的两倍。v7 的质量结论来自字幕组时间轴的 dev 集，没有在产品时间轴上评分。
- 没有运行确认集。

## 后续

- `just translation-srt` 用在产品时间轴的 SRT 上时，小包比例偏高；门槛是否按产品时间轴重定，见 v7 §8 第 3 项。
- 是否同步到产品 `b10-joint-degrade-v1` 另行裁定（v7 §8 第 4 项）；同步需要产品侧配方、降级规则与回归。
- 历史报告、台账与 v3–v7 产物不改写；v3–v7 的结论都是以 b10-joint 为对照得出的。
