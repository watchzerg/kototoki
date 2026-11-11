# ADR-0010：H0 翻译流程与产品配方（dp10-cut）

状态：已接受。合并整理于 2026-11-08（并入 ADR-0006、ADR-0009、ADR-0010、ADR-0011 的有效条款；历次变更见[决定索引·演进链](INDEX.md#演进链)，原文见 Git 历史）。自 2026-11-08 起 H0 不再是基线（[ADR-0018](0018-q2-sole-translation-baseline.md)），本篇只作产品当前翻译实现与历史对照的身份；切包仍是 Q2 的切包。第 6、7 点（产品配方与产品 run 目录）自 2026-11-08 起由 [ADR-0019](0019-product-translation-q2.md) 替代：产品改跑 `q2-degrade-v1`。第 9 点中"重新发布"不成立：按 [ADR-0020](0020-media-inputs-work-dir-and-side-by-side-publish.md) 第 4 点，源文件旁已有字幕即跳过，身份过期只在没有已发布字幕时触发重译（2026-11-11 标注，用户委托 agent 裁定）。  
范围：H0 线完整 SRT 流程的切包、邻文、提示与交付规则，研究侧配方 `dp10-cut` 与产品配方 `dp10-cut-degrade-v1`。模型、采样、引擎见 [ADR-0005](0005-apex-i-compact-translation-baseline.md)。

## 决定

1. 提示：`joint-understanding-v1`，即只把"每个值独立理解"改为"先共同理解全部可见台词及跨条目的条件、否定、指代和语气，再分别表达各源 ID 的信息"。grammar 为 ID JSON（无界空白），token-ids 传输，保护 64 tokens，每请求最多 2 次相同尝试，超出 context 记为失败而不截断。采样等其余固定项见 ADR-0005。
2. 拼包：每个场景（整片 SRT 是一个场景）用动态规划取总惩罚最低的切法，任意两条之间都可切。每包代价 = (条数 − 10)² ＋ 包内每个 ≥2 s 停顿按秒数计 1 分；<6 条的包加 1000 分；超过 10 条或包内有 ≥20 s 停顿不可行。
3. 分级切点：在 <0.5 s 的停顿处切加 6 分，<1 s 加 3 分，<2 s 加 1 分，≥2 s 不加；缺时间戳按无停顿（加 6 分）。每批待译 ≤10 条、可见 ≤12 条。
4. 只读邻文：前一条在停顿 <5 s 时可见，后一条只在停顿 <1 s 时可见；可见总数不超过 12 条。停顿取自 `ja.srt` 自身时间轴，只比较长短。
5. 研究侧配方：`experiments/translation_v3` 内置 `dp10-cut`（字段 `gap_pack` 加 `cut_penalty`，版本 `gap-pack-v2`），recipe_hash `ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70`，由 `test_recipes.AdoptedBaselineTest` 固定。入口 `just translation-srt --srt <ja.srt> --seed <S> --out <chn.srt>`，即 `python -m experiments.translation_v3 translate-srt --recipe dp10-cut`；占用 GPU，不覆盖已有输出，校验覆盖率，保留原 cue 编号和时间。
6. 产品配方：`kototoki/translate/recipes.py` 的 `DP10_CUT_DEGRADE_V1`（`PRODUCT`），hash `086754ca751365c21840742511bf39eaa621b8fc2f5a630372f22661fc86158e`。字段与 `dp10-cut` 相同，只把 `fixed.overflow` 换成 `degrade-10-5-1-keep-source`：批次终态失败按 10→5→1 拆批（前后两半、单条，邻文规则同原批次），单条仍失败则保留日文原文。同文件 `DP10_CUT` 的 hash 必须等于 6 里 `dp10-cut` 的 hash。
7. 产品 run 目录：`translate/srt-<sha12>/dp10-cut-degrade-v1__s<seed>/`。入口 `python -m kototoki`，翻译阶段自动使用该配方。产品 `build_batches` 与 v3 `dp10-cut` 在同一 SRT 上切包、邻文、提示与请求逐字节相同。
8. 对照身份（保留并钉住 hash，不是基线）：`b10-joint`（每批 10 条目标按源顺序、前后各 1 条邻文）`2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a`；`dp6-grp`（`gap-pack-v1`）`ae473cdce915b16379a838cec15fc53e444d24686cd36c706e5f9d379ba2061e`；`b10-joint-degrade-v1` `994c0d03ac4c91fec437285b66f597c19ff28f09c2ecad5b0e9541437ca795fe`（旧产品 run 目录的身份）。`c0` 为 v3 内置的更早配方。
9. 不做旧结果迁移与兼容开关：配方 hash 变化即该影片 translate 阶段身份过期，整批运行时重译并重新发布。

## 依据

- `dp10-cut` 由用户阅读[上限 10 条的切法模拟](../research/2026-10-17-dynamic-cut-batching-simulation.md)后裁定；**没有 GPU 质量证据**，质量按"切点偏向停顿"推定，现有样本测不出不同门槛的差别。
- `b10-joint` 来自 [v3 报告](../research/2026-10-10-hy30-flow-v3-report.md)：筛选集 Δ −0.093 promising，确认集未通过（Δ −0.012，剧集劣于非劣界），是用户的工程选择。`dp6-grp` 见 [v7 研究](../research/2026-10-16-gap-aware-batching-v7.md)：与 `b10-joint` 无可分辨差异。
- 离线切包相对 `b10-joint`：请求数增加约 20–35%，跨 ≥10 s 停顿的批从约 50% 降到约 20%，切点在 ≥1 s 停顿处的比例升到 92–97%，没有批跨 ≥20 s 停顿。
- 产品整片真实运行（2026-10-18）：HF III 147 批、HF II 149 批，请求全部一次接受，降级与回退为 0，`zh.srt`／`ja-zh.srt` 全部发布。

## 约束与未关闭项

- 产品时间轴上 <6 条的包占 9–24%（来自被 ≥20 s 停顿夹出的短段）。
- 2026-10-18 HF II 运行第 96 批起生成速度由约 175 tok/s 跌到约 4 tok/s，疑为显存触顶回落系统内存，与配方无关但未验证。
- 质量验证须以 `b10-joint-degrade-v1` 旧 run 目录或 `dp6-grp` 为对照，确认须用全新隔离的集合。
- 多次翻译再挑选的方法不予采用，见 [ADR-0008](0008-no-multi-translation-selection.md)。
