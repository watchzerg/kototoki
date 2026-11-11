# 翻译评估方法（现行）

状态：current

本页说明新的翻译对比用什么方法评估：v3 起的研究轮次（截至 v15）实际使用的 Claude 裁判、统计口径和对照规则。
Codex 时代的冻结流程见 [自动评估流程](subtitle-translation-evaluation.md) 和 [翻译评估入口](../testing/translation-model-evaluation.md)，只作历史参考。

所有分数都只能叫“自动裁判结果”，没有经过人工核验。

## 现行裁判 profile

v12、v13 两轮把两个 profile 并列写成“评测设施，不改 profile”；v15 只用了第二个。

| profile | 用于 | 定义 |
| --- | --- | --- |
| `claude-opus-5-5-mqm-v1` | dev 集（干净的字幕组日文） | `experiments/translation_v3/judge.py` |
| `v5-asr-pairwise-v1` | 产品 ASR 源（HF II／III 产品 w0 `ja.srt`） | `experiments/quality_v5/asr_source.py` |

**共用执行面**：`judge.CliBackend` 用 `claude -p --safe-mode --model claude-opus-5-5 --effort high --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence --output-format json --system-prompt … --json-schema …` 在空临时目录中运行，提示经 stdin 传入。如果 CLI 拒绝空的 `--setting-sources`，改用 `project`，并记录这一回退。

**模型身份**：`modelUsage` 中每个有输出的模型都必须是 `claude-opus-5-5`，否则该包记为错误、不重试（`check_model_usage`）。退出码 75 表示配额用尽或未登录，重跑同一命令即可续跑。

**`claude-opus-5-5-mqm-v1` 的盲评方式**：每包 4 个窗口，全部来自同一个 run，候选只用不透明哈希标识。包组成用固定种子 `v3-judge-packing-20261010` 按 split 洗牌，与 run 无关。

**MQM 标注规则**：只标错误，不打总分，严重度 minor 1／major 5／critical 10。
- accuracy 类：mistranslation、omission、addition、wrong-referent、negation-number-condition、cue-attribution。
- fluency 类：grammar、unnatural、register、terminology-inconsistency。

**裁判看到的输入**：每个评分 cue 的日文、参考中文、参考置信度和可接受歧义。

**提示与 schema 的哈希**：提示为 `prompt-v2`，profile 版本 `2026-10-10.2`。系统提示、user 前缀和 schema 的 sha256 都写进 `PROFILE`／`PROFILE_HASH`，每包结果记录 `profile_hash` 和 `prompt_sha256`。

**`v5-asr-pairwise-v1` 的成对盲评方式**：每包 8 个条目。每个条目给出参考日文（前后各 2 条作语境）和盲序的 A、B 两份中文。裁判分别列出两份的错误（权重与 MQM 相同），再给出 A／B／tie 偏好。估计报告记录 `system_prompt_sha256`。

**校准**（v5 票据 02）：同一译文两份，32 条全部判平；参考源 seed 对 seed 共 64 条，偏好 14% 对 17%；原样重判 40 条，胜负一致 90%。

**备用执行面**：`judge --backend export|ingest` 由子 agent 读导出的包、写回 JSON，结果标为 `surface: export-ingest`。`compare` 拒绝混用不同执行面的结果。

## 入口命令

从仓库根目录运行。会消耗 Claude 配额的命令先问用户；生成译文的命令占 GPU，同样先问。

- **dev 集 MQM 盲评**：
  - v3／v4 的根目录用 `python -m experiments.translation_v3 judge --run RUN`、`python -m experiments.translation_v4 judge --run RUN`。
  - v9–v13 用 `python -m experiments.scene_batching_v6 --round vNN judge-run --recipe R --seed S`。
- **dev 集统计**：
  - v9–v10 用 `compare9`。
  - v11 起用 `compare11`：送裁判前先 `copy-identical`，两臂逐字相同的包直接复制判分，相同的 cue 按 Δ＝0 计入。
- **产品 ASR 源成对评审**：
  - v10／v11／v12／v13 分别用 `--round` 下的 `product`／`product12`／`product13`，子命令 `plan|judge|estimate`，底层是 `experiments/scene_batching_v6/asr10.py`。
  - v15 用 `python -m experiments.asr_robustness_v15 impact-plan|impact-judge|impact-report`。

**新轮次需要新入口**：`scene_batching_v6` 的 `--round` 只接受 `v6`–`v13`，每一轮绑定自己的根目录。新一轮要么新增 round，要么像 v15 那样建新包，复用 `asr10` 或 v9 的函数。

## 统计口径

**dev 集**：
- 主终点是每条评分 cue 的 accuracy 惩罚，候选减对照，Δ 越低越好。
- 汇总顺序：作品内按 cue 平均，类别内作品等权，剧集和电影分开报告。
- 区间用 v4 的窗口 bootstrap：作品内分层，按 5 条一组的窗口重抽，报 CI90（`experiments/scene_batching_v6/v9.py` 调用 v4 统计）。
- 不能交付的 cue 记 10 分，同时计入 major+ 和 critical。
- 次要指标：各类别、fluency、major+、critical、人名相关错误、交付失败、墙钟。

**产品 ASR 源**：
- 每个 CER 桶（exact／light／heavy）算 Δ＝候选惩罚 − 对照惩罚的均值，用条目 bootstrap 报 CI90。
- 同时报偏好、人名错误差，以及整片不一致率。

## 对照与确认集规则

- **对照必须是 Q3**：新测试以 Q3 为对照；引用 Q2、Q1、Q0、F1 或 H0 作对照时要写明，并说明理由（[ADR-0021](../adr/0021-q3-strata-names-baseline.md) 第 1 点）。
- **对照同期重判**：dev 对照必须与候选同期、同一包组成重判。v10 记录的重判漂移为 −0.012～−0.018，与候选效应同量级。产品 ASR 源的 x、y 两侧在同一个 packet 内比较，不需要同期重判。
- **三个 seed 起才谈质量**：作品是聚类单位。dev 主 seed 为 20261011–13，产品 ASR 源用 20261054–56（v12 起）。
- **筛选与确认分开**：确认在冻结前不读的全新确认集上做单侧检验，并做 Holm 校正。
  - v3、v4、v5 的确认集都已开封，新的确认必须用全新隔离的集合（[ADR-0018](../adr/0018-q2-sole-translation-baseline.md) 第 5 点）。
  - 电影确认材料已被 v4 的 confirm 用尽，v5 只建了剧集确认集。
- **不选“多次翻译再挑选”的方法**：不自动选用多样本／多 seed＋MBR、best-of-N 等方法（[ADR-0008](../adr/0008-no-multi-translation-selection.md)）。

## 不可混用的分数

- **只在同条件下比较**：数字只在同一裁判 profile、同一数据集、同一 seed 块之间比较（[ADR-0018](../adr/0018-q2-sole-translation-baseline.md) 第 4 点，现在针对 Q3）。
- **MQM 与成对偏好不混算**：`claude-opus-5-5-mqm-v1` 的 MQM 分数不与 `v5-asr-pairwise-v1` 的成对结果混算（[v5 §3](../research/2026-10-16-quality-exploration-v5.md)）。需要新量尺时，新建带版本的 profile，先做盲重复噪声校准。
- **不跨执行面比较**：同一对比较只用一种执行面的结果。
- **Codex 时代的分数不可比**：`gpt-6.1-sol` 和 `sol-high-auto-v1` 的分数与 Claude 裁判分数不可比；换裁判后 C0 和所有候选都要重判（[v3 计划](../plans/hy-mt2-translation-flow-exploration-v3.md) §1、[v1/v2 教训](../research/2026-10-10-hy30-flow-v1-v2-lessons.md)）。
- **改量尺就出新 profile**：裁判提示、模型、effort 或 schema 一变就是新的 profile 版本，旧分数不跨版本比较（[v3 计划](../plans/hy-mt2-translation-flow-exploration-v3.md) §4.2 说明了 `…-mqm-v2` 的触发条件）。

## 冻结的 Codex 时代流程

`sol-high-auto-v1` 的流程以 `gpt-6.1-sol / high / codex-cli` 为裁判身份，由 `experiments/translation_judge/`、`experiments/translation_eval/` 执行，见 [自动评估流程](subtitle-translation-evaluation.md) 和 [翻译评估入口](../testing/translation-model-evaluation.md)。

这条链带 sha256 自检，只读不改，也不用于新的对比。

[Claude 裁判迁移方案](../plans/claude-judge-profile.md)（`claude-opus-5-5-auto-v1`）已被 v3 的 MQM profile 取代，只保留为迁移分析。

## 来源

- [v3 计划](../plans/hy-mt2-translation-flow-exploration-v3.md) §4、§5
- [`translation_v3`](../../experiments/translation_v3/README.md)
- [`translation_v4`](../../experiments/translation_v4/README.md)
- [`quality_v5`](../../experiments/quality_v5/README.md)
- [`scene_batching_v6`](../../experiments/scene_batching_v6/README.md)
- [`asr_robustness_v15`](../../experiments/asr_robustness_v15/README.md)
- 各轮报告：[v5](../research/2026-10-16-quality-exploration-v5.md) §3、[v9](../research/2026-10-21-general-model-translation-v9.md)、[v10](../research/2026-10-21-q0-exploration-v10.md)、[v11](../research/2026-10-22-q0-product-route-v11.md)、[v12](../research/2026-11-08-strata-flash-next-v12.md) §2.3、[v13](../research/2026-11-08-names-on-strata-v13.md) §2.3、[v15](../research/2026-11-10-asr-robustness-v15.md)
- [ADR-0008](../adr/0008-no-multi-translation-selection.md)、[ADR-0018](../adr/0018-q2-sole-translation-baseline.md)、[ADR-0021](../adr/0021-q3-strata-names-baseline.md)
- [迁移方案（已取代）](../plans/claude-judge-profile.md)
