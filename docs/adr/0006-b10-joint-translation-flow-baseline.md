# ADR-0006：字幕翻译流程基线改为 b10-joint

状态：已被部分替代；2026-10-17 起完整 SRT 流程的批次部分由 [ADR-0009：dp6-grp 基线](0009-dp6-grp-translation-flow-baseline.md)替代，joint 提示仍有效。下文保留 2026-10-11 的采纳理由，"当前基线"均指当时状态。  
日期：2026-10-11。  
部分替代：[ADR-0005](0005-apex-i-compact-translation-baseline.md) 中关于完整 SRT 流程的批次与提示部分。ADR-0005 的模型、引擎、采样（`official30b-cached-v1`）、context 和运行时参数**全部保持不变**。

## 决定

用户在阅读 [v3 报告](../research/2026-10-10-hy30-flow-v3-report.md)后，明确决定把 `jpn.srt → chn.srt` 的流程基线从 C0（每批 5 条、前后各 1 条只读邻文、原 JSON 提示）改为 **b10-joint**：

- 每批 10 条目标字幕；前后各 1 条只读邻文。
- 提示只替换 C0 中“每个值独立理解”的那一句，改为“先共同理解全部可见台词及跨条目的条件、否定、指代和语气，再分别表达各源 ID 的信息”（`joint-understanding-v1`）。
- 其余与 C0 相同：Hy30 原生模板、ID JSON grammar（无界空白）、token-ids 传输、官方采样 temperature 0.7、`n_predict` 4096、`cache_prompt`、总 context 8192、保护 64 tokens、每请求最多 2 次相同尝试，超出 context 记为失败而不截断。

## 身份与入口

- 配方：`experiments/translation_v3` 内置配方 `b10-joint`，recipe_hash `2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a`。该 hash 与 v3 筛选和确认 run 的身份一致，由 `test_recipes.AdoptedBaselineTest` 固定。
- 完整 SRT 入口：`just translation-srt --srt <ja.srt> --seed <S> --out <chn.srt>`，即 `python -m experiments.translation_v3 translate-srt --recipe b10-joint`。该入口会占用 GPU，并加载完整模型。
  - 交付 run 写在 `--root` 下的 `deliveries/`，默认是 v3 产物目录。
  - 不覆盖已有输出；会完整校验覆盖率，并保留原 cue 编号和时间。
- 对 v3 之后的流程实验，`b10-joint` 是新的对照。C0 保留为 v3 内置的历史配方 `c0`。
- 逐窗 demo（`just translation-baseline`，输入为窗口 JSONL）以及 `translation_flow` 的历史 `prepare` 入口不受影响，它们的配方身份保持不变。

## 证据与已知代价（如实记录）

- **筛选集**（96 窗 × 3 seed，Claude Opus 5.5 MQM 裁判）：Δ −0.093，区间 [−0.124, −0.054]，判为 promising；screen-b 单独比较也判为 promising。
- **独立确认集**（48 窗 × 3 seed）：Δ −0.012，区间 [−0.053, 0.033]，**未通过确认**。其中剧集 +0.072，区间 [+0.003, +0.139]，劣于非劣界；电影 −0.097。
- **两集合并**（120 个代表窗）：Δ −0.061，区间 [−0.089, −0.027]，剧集和电影都为负。但它是从 19 个配方中按筛选成绩选出来的，存在赢家诅咒，合并数字会偏乐观。
- critical 在两个集合上都不增加；确认集上 fluency 更好（0.058，对 C0 0.090）。
- 墙钟约 −4% 到 −7%，请求数减半，显存峰值与 C0 相同（15835 MiB）。整片交付（1993 条电影、387 条剧集）完整，没有触顶。

因此，这次采纳是**用户根据质量期望、交付稳定性和速度作出的工程选择**，不是“质量显著优于 C0”的结论。已知风险是在剧集的新窗口上可能略差，后续回归要单独关注剧集。

## 后续

- v3 的确认集已经开封，不能再作为未见集使用。之后再做确认，需要新建并隔离新的确认集。
- 后续探索见 [v4 计划](../plans/hy-mt2-translation-flow-exploration-v4.md)。v4 以 b10-joint 为对照。
- 历史报告、台账和 v3 产物都不改写。
