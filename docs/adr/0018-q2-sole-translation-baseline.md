# ADR-0018：翻译只保留一条基线 Q2

状态：已接受（2026-11-08，用户决定）。替代 [ADR-0015](0015-two-translation-baselines.md) 第 1 点（两条基线并存）、第 4 点中"对照写明 H0 还是 Q2"一句、第 5 点中"产品继续用 H0"作为基线安排的含义；[ADR-0017](0017-q2-strata-default-launch-baseline.md) 第 2 点"新的 Q 线测试"扩展为"新的翻译测试"。第 3 点中"产品当前的翻译实现"一项自 2026-11-08 起由 [ADR-0019](0019-product-translation-q2.md) 替代：产品已切到 Q2。第 1 点自 2026-11-09 起由 [ADR-0021](0021-q3-strata-names-baseline.md) 替代：唯一基线改为 Q3；第 2、4 点的规则改为针对 Q3。  
范围：研究与测试用哪条翻译基线。不改产品 `kototoki/`，不决定产品何时、如何切到 Q2，不开封确认集。

## 决定

1. 翻译只保留**一条基线：Q2**。身份、服务与运行顺序不变，以 [ADR-0017](0017-q2-strata-default-launch-baseline.md) 为准。
2. 以后所有新的翻译测试都以 Q2 为对照。引用 Q1、Q0、F1 或 H0 作对照时须写明，并说明理由。
3. **H0 不再是基线。** 它的身份（[ADR-0005](0005-apex-i-compact-translation-baseline.md)、[ADR-0010](0010-dp10-cut-translation-flow-baseline.md)、[ADR-0015](0015-two-translation-baselines.md) 第 2 点）保留，但只有两种用途：
   - 产品当前的翻译实现：在产品切到 Q 线之前，`python -m kototoki` 仍跑 `dp10-cut-degrade-v1`，发布时仍做专名替换；
   - 历史研究轮次里的对照身份。
4. 以下规则不变，现在只针对 Q2：
   - 切包仍与 `dp10-cut` 逐字一致，`check-batches` 照常可用；
   - 数字只在同一裁判 profile、同一数据集、同一 seed 块之间比较；
   - 配方变了就出新配方与新 hash，名称后缀递增（Q3…）须用户裁定。
5. [ADR-0008](0008-no-multi-translation-selection.md) 继续适用。v3、v4、v5 的确认集已开封，新的确认仍须用全新隔离的集合。

## 依据

- 用户决定不再维持两条基线。Q 线在 v9–v12 中已对 H0 显著占优：v10 的 Q0 在 dev 两类和产品 ASR 源上都好于 H0；之后 Q1、F1 又依次在 Q 线内部改进。证据见 [ADR-0015](0015-two-translation-baselines.md)、[ADR-0017](0017-q2-strata-default-launch-baseline.md) 与[调研索引](../../research/INDEX.md)。
- 只保留一个对照可以省掉"每次都跑两臂"的 GPU 与裁判成本。

## 约束与未关闭项

- **产品与基线暂时不一致**：产品仍跑 H0，基线已是 Q2。产品切换另写 ADR，需要解决 [ADR-0017](0017-q2-strata-default-launch-baseline.md) 列出的几项：
  - 外部 OpenAI 兼容服务后端；
  - 不用 grammar 时的失败路径；
  - Q 链没有替换阶段，而 H0 链有；
  - Strata 与 llama-server 不得同时驻留。
- Q2 启动配置未跑过翻译、首用前建议先 smoke、给新 SRT 生成 Q2 配方没有通用入口：这三项见 [ADR-0017](0017-q2-strata-default-launch-baseline.md)，本决定不改变。
