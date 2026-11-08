# 决定索引

本页回答两个问题：**现在什么决定有效**，以及**它是怎么演变过来的**。

2026-11-08 经用户授权做过一次合并精简：每个主题只保留一篇现行 ADR，正文只写仍有效的决定。被并掉的编号（0001、0002、0004、0006、0009、0011、0013、0016）只留两行跳转页，原文见 Git 历史（提交 f139e17 及之前）。历史摇摆只在本页的[演进链](#演进链)里体现。

- 找"当前怎么做"：看 [当前有效决定](#当前有效决定)。表里每一行给出现行规则，以及权威 ADR 的哪一条。
- 找"为什么变成这样"：看 [演进链](#演进链)，再按链接读当时的 ADR。
- 要做或要记录一个新决定：按 [记录新决定](#记录新决定) 的步骤，在同一次提交里改完。
- 研究轮次的过程与裁定时间线在[调研索引·决定与探索时间线](../research/INDEX.md#决定与探索时间线)。本页只收采纳的决定。

## 当前有效决定

更新于 2026-11-08（合并精简后；同日 ADR-0018 改为唯一基线 Q2）。

| 主题 | 现行规则 | 权威出处 |
| --- | --- | --- |
| STT 基线 | **W0**：faster-whisper＋新 Pyannote VAD＋MMS `jpn` CTC。须用自有适配层移植 WhisperX 的切分合并与独立解码。**X0**：Qwen-ASR＋同一 VAD＋MMS。新 Pyannote＝`pyannote.audio 4.0.7`＋`pyannote/segmentation-3.0`（rev `e66f3d3b…`）。旧 PyanNet W0、fixed30、cut-merge 只作历史身份 | [0003](0003-new-pyannote-baselines.md) |
| 设备 | ASR 与强制对齐只跑 GPU，不回退 CPU；VAD 可用 CPU 或 GPU（产品固定 `cuda:0`） | [0003](0003-new-pyannote-baselines.md)、[0007](0007-bilingual-subtitle-pipeline-architecture.md) |
| 产品 STT 引擎 | `[stt] engine` = `w0`（默认）｜`x0`｜`cross`（`cross-w0-x0-whisper-judge-v1`，Whisper 交叉打分，d > −1.0 取 x0）。改默认须新 ADR，并在全新隔离素材上确认 | [0012](0012-cross-asr-judge.md) |
| 产品架构 | GPU 阶段按"阶段 × 整批"推进，每阶段一个子进程。阶段链为 `vad` → `asr` → `align`（MMS）→ `cues` → **`names`** → `translate` → publish。单一 CUDA 12.8 Python 3.13 环境，翻译用独立进程的官方 llama.cpp。`kototoki.toml` 驱动，无 CLI。每片一个工作目录，按身份与配方 hash 续跑 | [0007](0007-bilingual-subtitle-pipeline-architecture.md)；names 阶段见 [0014](0014-name-consistency-in-product.md) |
| 翻译基线（唯一） | **Q2** 是唯一翻译基线，新的翻译测试都以 Q2 为对照；引用 Q1、Q0、F1、H0 时须写明并说明理由。H0 不再是基线，只作产品当前翻译实现与历史对照的身份。新增后缀命名须用户裁定 | [0018](0018-q2-sole-translation-baseline.md)；H0／Q0 身份见 [0015](0015-two-translation-baselines.md) |
| 产品当前翻译（H0）：模型与采样 | Hy-MT2 30B-A3B APEX-I-Compact（rev `312cce86…`）。采样 `official30b-cached-v1`：temperature 0.7、无 top_k、`n_predict` 4096，context 8192，超长拒绝不截断 | [0005](0005-apex-i-compact-translation-baseline.md)（含研究侧与产品的引擎版本） |
| 产品当前翻译（H0）：流程 | `dp10-cut`（`ee72ce66…`）：每包 ≤10 条目标、可见 ≤12 条；DP 拼包，分级切点偏向停顿，不跨 ≥20 s 的停顿。邻文规则：前一条停顿 <5 s 才带、后一条 <1 s 才带。提示 `joint-understanding-v1` | [0010](0010-dp10-cut-translation-flow-baseline.md) |
| 产品当前翻译（H0）：配方 | `dp10-cut-degrade-v1`（`086754ca…`），失败按 10→5→1 降级，单条仍失败时保留日文 | [0010](0010-dp10-cut-translation-flow-baseline.md) |
| **翻译基线 Q2：身份** | Q1 的配方规则不变：`qwen-wide`，加产品 `names` 建表中 `confidence: high` 的专名注入，不做事后替换。模型换为 Strata 0.2.12 上的 `qwen3.8-flash-next-iq3_s`，服务用不加参数的 `strata launch`（DFlash2）。配方带 `strata_launch: "default"`，不用 grammar。每个输入一个实例。质量证据来自 v12 F1；Q2 的启动配置本身未跑过翻译 | [0017](0017-q2-strata-default-launch-baseline.md)（含 Q1 规则）；Q0 身份见 [0015](0015-two-translation-baselines.md) |
| 方法禁区 | 不自动选用"翻译多次再挑选"（MBR、best-of-N、多次投票及更省的变体）：不提议、不列候选、不在无人值守时执行。两次可靠性重试与 10→5→1 降级不算在内。边界情况先问 | [0008](0008-no-multi-translation-selection.md) |
| 专名一致性 | 研究线已结题，不开新轮次，最佳配置冻结（no-think、提示 v5、规则一＋孤立单字）。已原样移植进产品 `names` 阶段：用 Qwen3.8-27B 建表，发布时替换，默认开启，表可手改 | [0014](0014-name-consistency-in-product.md) |

### 未关闭项

合并时已把各 ADR 的过时措辞改为现行事实。仍然成立的未关闭项：

- **引擎并存**：H0 研究侧仍用 compat loader b11429，产品用官方 llama.cpp（现行 b11669，以[技术选型](../development/technology-stack.md)为准）。研究侧是否同步升级，未裁定（[0005](0005-apex-i-compact-translation-baseline.md)）。
- **W0／X0 demo 的 CLI 旧默认**：省略参数时仍落到旧 PyanNet／fixed30，须显式选择新 Pyannote（[0003](0003-new-pyannote-baselines.md)）。
- **未裁定或未验证**：
  - 产品与基线暂不一致：基线已是 Q2，产品仍跑 H0；产品何时、如何切到 Q2 未裁定，切换需要外部服务后端、不用 grammar 时的失败路径，并处理 Q 链没有替换阶段（[0018](0018-q2-sole-translation-baseline.md)）；
  - Q2 启动配置的 smoke 尚未运行；
  - 给新 SRT 生成 Q1／Q2 配方还没有通用入口（[0017](0017-q2-strata-default-launch-baseline.md)）；
  - [0014](0014-name-consistency-in-product.md) 验收第 4 条（用户抽查 `changes`）未做；
  - `cross` 尚未在新素材上确认（[0012](0012-cross-asr-judge.md)）。

## 演进链

每条链按时间排列，箭头表示"被替代或被扩展"。日期是采纳日。标"（已合并）"的编号只剩跳转页，当时的全文见 Git 历史（提交 f139e17 及之前）。

- **STT 基线**：
  1. [0001](0001-two-stt-baselines.md)（已合并）（10-04）：W0 用旧 Pyannote，X0 不用 VAD、固定 30 s 分片；10-05 放宽 VAD 设备限制。
  2. → [0002](0002-x0-demo-flow.md)（已合并）（10-05）：X0 demo 与 cut-merge。
  3. → [0003](0003-new-pyannote-baselines.md)（10-05）：两路统一改用新 Pyannote。
  4. → [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13／14）：进产品，VAD 固定 `cuda:0`。
  5. → [0012](0012-cross-asr-judge.md)（10-19）：增加可选引擎 `cross`，默认仍 w0。
- **翻译模型与采样（H0）**：
  1. [0004](0004-hy-mt2-translation-baseline.md)（已合并）（10-06）：Q3_K_M，greedy，上下文 4096。
  2. → [0005](0005-apex-i-compact-translation-baseline.md)（10-07）：APEX-I-Compact；10-08 改为 `official30b-cached-v1`。
  3. → [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-14）：产品引擎换成官方 llama.cpp。
  4. → [0015](0015-two-translation-baselines.md)（10-21）：命名为 H0。
  5. → [0018](0018-q2-sole-translation-baseline.md)（11-08）：不再是基线，只作产品当前实现与历史对照。
- **翻译流程（切包与提示）**：
  1. [0005](0005-apex-i-compact-translation-baseline.md) 的 C0（每包 5 条目标，前后各 1 条邻文）。
  2. → [0006](0006-b10-joint-translation-flow-baseline.md)（已合并）（10-11）：`b10-joint`，即 10 条目标＋joint 提示。
  3. → [0009](0009-dp6-grp-translation-flow-baseline.md)（已合并）（10-17）：`dp6-grp`。
  4. → [0010](0010-dp10-cut-translation-flow-baseline.md)（10-17 同日）：`dp10-cut`，提示不变。
- **产品翻译配方**：
  1. [0007](0007-bilingual-subtitle-pipeline-architecture.md)（10-13）：`b10-joint-degrade-v1`。
  2. → [0011](0011-dp10-cut-product-recipe.md)（已合并）（10-18）：`dp10-cut-degrade-v1`。
- **方法禁区**：[0008](0008-no-multi-translation-selection.md)（10-16），放弃 v4 `mbr8c` 与 v5 `mbr8s`。0012、0014–0017 都确认它仍适用。
- **专名一致性**：
  1. [0013](0013-name-consistency-closed.md)（已合并）（10-19）：结题，冻结配置，不进产品。
  2. → [0014](0014-name-consistency-in-product.md)（10-19 同日）：替代第 3 条，进产品 `names` 阶段。
  3. → 该阶段产出的表在 [0016](0016-q1-translation-baseline.md)（已合并） 起用于 Q 线注入。
- **Q 线基线**：
  1. [0015](0015-two-translation-baselines.md)（10-21）：**Q0**＝Qwen3.8-27B＋`qwen-wide`（`719237b9…`），来自 v9。
  2. → [0016](0016-q1-translation-baseline.md)（已合并）（11-08）：**Q1**＝Q0＋只注入 high 条目的专名表，来自 v11。
  3. → [0017](0017-q2-strata-default-launch-baseline.md)（11-08 同日）：**Q2**＝Q1 规则＋Strata Flash-Next，不加参数启动、DFlash2。v12 的 F1 是同一规则下 MTP 启动的候选。
  4. → [0018](0018-q2-sole-translation-baseline.md)（11-08 同日）：Q2 成为唯一翻译基线，H0 退出基线。

## 全部 ADR

| 编号 | 主题 | 状态 |
| --- | --- | --- |
| [0003](0003-new-pyannote-baselines.md) | STT 基线 W0／X0（新 Pyannote） | 有效（并入 0001、0002） |
| [0005](0005-apex-i-compact-translation-baseline.md) | H0 翻译模型、采样与引擎 | 有效（并入 0004） |
| [0007](0007-bilingual-subtitle-pipeline-architecture.md) | 双语字幕流水线架构 | 有效 |
| [0008](0008-no-multi-translation-selection.md) | 不自动选用"翻译多次再挑选" | 有效 |
| [0010](0010-dp10-cut-translation-flow-baseline.md) | H0 翻译流程与产品配方（`dp10-cut`／`dp10-cut-degrade-v1`） | 有效（并入 0006、0009、0011） |
| [0012](0012-cross-asr-judge.md) | 产品 STT 可选引擎 `cross` | 有效 |
| [0014](0014-name-consistency-in-product.md) | 专名一致性（研究线结题＋进产品） | 有效（并入 0013） |
| [0015](0015-two-translation-baselines.md) | 翻译两条基线：H0 与 Q 线 | 部分有效：两条基线安排由 0018 替代，H0／Q0 身份与测试规则仍有效 |
| [0017](0017-q2-strata-default-launch-baseline.md) | Q 线基线 Q2（含 Q1 规则） | 有效（并入 0016） |
| [0018](0018-q2-sole-translation-baseline.md) | 唯一翻译基线 Q2 | 有效 |

跳转页：0001、0002 → 0003；0004 → 0005；0006、0009、0011 → 0010；0013 → 0014；0016 → 0017。新 ADR 编号从 0019 起。

## 记录新决定

用户采纳一个决定（换基线、裁定研究结论、改产品行为）后，在**同一次提交**里完成下面几步：

1. **新增 ADR**：`docs/adr/NNNN-<slug>.md`，编号顺延。写清状态、日期，以及替代了哪篇 ADR 的哪一点；写清身份（配方、hash、入口）、证据，以及未验证的部分。
2. **处理旧 ADR**：默认只在被替代的 ADR 状态行末尾追加"某点自某日起由 ADR-NNNN 替代"，正文不动。只有用户授权合并精简时，才把旧篇改成跳转页、把有效条款并入新篇。
3. **改本页**：
   - 在"当前有效决定"里改对应行和"更新于"日期；
   - 在"演进链"的对应链末尾追加一环；
   - 在"全部 ADR"里加一行，并更新被替代那篇的状态；
   - 新发现的不一致或未关闭项写进"未关闭项"。
4. **同步摘要入口**：
   - 基线变化时，改 [AGENTS.md](../../AGENTS.md)"冻结证据与基线身份"中的基线句；
   - 术语有变化时，改 [GLOSSARY.md](../../GLOSSARY.md)；
   - 来自研究轮次的决定，在[调研索引时间线](../research/INDEX.md#决定与探索时间线)加一行，并在该轮文档的待裁定项下注明裁定结果；
   - 涉及代码时，按[随交付同步](../agents/documentation.md#随交付同步)更新模块页与 README。

不在本页记录的：研究过程、实验数据、未采纳的候选。这些放在 `docs/research/`。
