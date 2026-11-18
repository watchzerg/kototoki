# 翻译评估方法（现行）

状态：current

本页说明新的翻译对比用什么方法评估：v3 起的研究轮次（截至 v15）实际使用的 Claude 裁判、统计口径和对照规则。口径的来历见 [Strata v12–v13 轮次](../../research/2026-11-strata-v12-v13/README.md#测试)与 [flow v1–v4 轮次](../../research/2026-10-translation-flow-v1-v4/README.md)；早期 Codex 裁判（`gpt-6.1-sol`、`sol-high-auto-v1`）只作历史，见[翻译模型选择轮次](../../research/2026-10-translation-model-selection/README.md#测试)。

所有分数都只能叫"自动裁判结果"，没有经过人工核验。

研究期的裁判与统计实现已随研究代码删除（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)），需要时从归档 tag `archive/2026-11-18-pre-research-restructure` 取回到新轮次目录；第二个轮次复用时再放进研究目录下的共享工具目录。下面的文字是口径的权威描述，实现须与之一致。

## 现行裁判 profile

| profile | 用于 | 方式 |
| --- | --- | --- |
| `claude-opus-5-5-mqm-v1` | dev 集（干净的字幕组日文） | MQM 盲评，只标错误 |
| `v5-asr-pairwise-v1` | 产品 ASR 源（两部电影的产品 w0 `ja.srt`） | 成对盲评，列错误并给偏好 |

**执行面**：Claude CLI 以 `--model claude-opus-5-5 --effort high`、空工具、空 MCP 与 setting、不保存 session、JSON 输出加 JSON schema，在空临时目录中运行，提示经 stdin 传入。CLI 拒绝空的 setting 来源时改用 `project` 并记录回退。

**模型身份**：返回的用量信息中每个有输出的模型都必须是 `claude-opus-5-5`，否则该包记为错误、不重试。

**`claude-opus-5-5-mqm-v1` 的盲评方式**：每包 4 个窗口，全部来自同一个 run，候选只用不透明标识。包组成用固定种子按 split 洗牌，与 run 无关。裁判看到每个评分 cue 的日文、参考中文、参考置信度和可接受歧义。

**MQM 标注规则**：只标错误，不打总分，严重度 minor 1／major 5／critical 10。

- accuracy 类：mistranslation、omission、addition、wrong-referent、negation-number-condition、cue-attribution。
- fluency 类：grammar、unnatural、register、terminology-inconsistency。

**`v5-asr-pairwise-v1` 的成对盲评方式**：每包 8 个条目。每个条目给出参考日文（前后各 2 条作语境）和盲序的 A、B 两份中文；裁判分别列出两份的错误（权重与 MQM 相同），再给出 A／B／tie 偏好。校准（v5）：同一译文两份 32 条全部判平；原样重判 40 条，胜负一致 90%。

**备用执行面**：由子 agent 读导出的包、写回 JSON（标为 `surface: export-ingest`）。它固定不了具体模型，只用于筛选，不用于确认或采纳依据；同一对比较不混用执行面。

## 统计口径

**dev 集**：

- 主终点是每条评分 cue 的 accuracy 惩罚，候选减对照，Δ 越低越好。
- 汇总顺序：作品内按 cue 平均，类别内作品等权，剧集和电影分开报告。
- 区间：按作品分层，作品内把 cue 按 5 条一组的窗口有放回重抽，10000 次，报 CI90。
- 不能交付的 cue 记 10 分，同时计入 major+ 和 critical。
- 两臂逐字相同的包不送裁判，直接复制判分，相同的 cue 按 Δ＝0 计入。
- 次要指标：各类别、fluency、major+、critical、人名相关错误、交付失败、墙钟。

**产品 ASR 源**：

- 按日文 CER 分 exact／light／heavy 三桶，每桶算 Δ＝候选惩罚 − 对照惩罚的单元均值；单元有放回重抽 4000 次报 CI90；逐字相同的单元按 Δ＝0 计入。
- 同时报偏好、人名错误差，以及整片不一致率（同一作品内专名写法的分歧比例，不是裁判输出）。

**判据**：非劣界 0.05（每类 CI90 上界 < 0.05）；"改善"只在 CI90 上界 < 0 时写；wrong-referent 的非劣要求 CI90 下界 ≤ 0。判定规则在看结果前冻结。

**人名相关错误口径**（跟着数据集走，两个口径的计数互不比较）：

- dev 集：裁判错误的证据文字命中"人名、名字、姓名、称呼、译名、名称、专名、角色名、昵称、地名、音译"之一。
- 产品 ASR 源：同一组词去掉"名称""地名"，匹配错误说明而非证据文字，另把全部 `terminology` 类错误计入。

## 对照与确认集规则

- **对照必须是 Q3**：新测试以 Q3 为对照；引用 Q2、Q1、Q0、F1 或 H0 作对照时要写明，并说明理由（[ADR-0021](../adr/0021-q3-strata-names-baseline.md) 第 1 点）。
- **对照同期重判**：dev 对照必须与候选同期、同一包组成重判；重判漂移约 −0.012～−0.018，与候选效应同量级。产品 ASR 源的两侧在同一个包内比较，不需要同期重判。
- **三个 seed 起才谈质量**：作品是聚类单位。dev 主 seed 为 20261011–13，产品 ASR 源用 20261054–56。同 seed 输出不可复现（Strata 约 49% 的 cue 不同），配对比较要带 A/A 噪声底。
- **筛选与确认分开**：确认在冻结前不读的全新确认集上做单侧检验，并做 Holm 校正。v3、v4、v5 的确认集都已开封，新的确认必须用全新隔离的集合（[ADR-0021](../adr/0021-q3-strata-names-baseline.md)「对照规则」第 5 点）；电影确认材料已被 v4 用尽。
- **不选"多次翻译再挑选"的方法**（[ADR-0008](../adr/0008-no-multi-translation-selection.md)）。

## 不可混用的分数

- **只在同条件下比较**：数字只在同一裁判 profile、同一数据集、同一 seed 块之间比较（[ADR-0021](../adr/0021-q3-strata-names-baseline.md)「对照规则」第 2–4 点，现在针对 Q3）。
- **MQM 与成对偏好不混算**；需要新量尺时，新建带版本的 profile，先做盲重复噪声校准。
- **Codex 时代的分数不可比**：换裁判后对照和所有候选都要重判。
- **profile 身份**：`claude-opus-5-5-mqm-v1` 的提示曾从 prompt-v1 改到 prompt-v2 而名字没变，比较前核对两侧结果记录的 profile 指纹相同，不同就重判；成对 profile 以名字加系统提示指纹认身份。今后提示、模型、effort 或 schema 一变，必须同时改 profile 名（如 `…-v2`）。

## 来源

- 轮次：[flow v1–v4](../../research/2026-10-translation-flow-v1-v4/README.md)、[quality v5](../../research/2026-10-quality-v5/README.md)、[Q 线 v9–v11](../../research/2026-10-q-line-v9-v11/README.md)、[Strata v12–v13](../../research/2026-11-strata-v12-v13/README.md)、[ASR 稳健性 v14–v15](../../research/2026-11-asr-robustness-v14-v15/README.md)
- [ADR-0008](../adr/0008-no-multi-translation-selection.md)、[ADR-0021](../adr/0021-q3-strata-names-baseline.md)
