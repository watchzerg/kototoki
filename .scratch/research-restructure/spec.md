# 研究与文档精简重组

Status: ready-for-agent
Type: task
立项：2026-11-18（用户批准布局与原则，执行在新 session）

## 目标

1. 采用新布局：研究按"一轮一个目录"放在仓库根 `research/`，现行文档只留 `docs/`。
2. 按用户原则精简：研究只记"用什么策略、在什么软件版本、做了什么测试、整体结论如何"；逐窗数据、样本文件哈希、字节锁、本机路径、执行台账一律不保留在主分支。
3. 把新规范写进权威文档，并由 `docs-check` 机械检查，确保以后遵守。

## 不做的事（硬约束）

- **不改产品代码**：`kototoki/` 下任何文件不动（含注释里指向 `experiments/…` 的旧路径，见"已知遗留"）。验收时 `git diff --stat <归档 tag> -- kototoki/` 必须为空。
- 不跑 GPU、不加载模型、不跑 smoke、不跑 demo。
- 不重开已结题的研究线，不改现行决定（ADR 的决定内容不变，只修链接）。
- 不在主分支保留旧代码的"兼容层"或重定向页；旧内容一律靠归档 tag 追溯。

## 已定决定

| # | 决定 | 理由 |
| --- | --- | --- |
| D1 | 动手前在当前 HEAD 打 tag `archive/2026-11-18-pre-research-restructure` 并 push。之后引用旧材料一律写成 `archive/2026-11-18-pre-research-restructure:<路径>` | 冻结靠 git，不靠"不许改的文件" |
| D2 | **删除** `experiments/` 全部代码与文档（内容先提炼进 `research/<轮次>/README.md`） | 依赖的 `.local` 数据已离机，多数写死 `D:\` 路径，已不可运行；新原则下研究可以导入产品，不再保留研究侧副本 |
| D3 | **删除** `kototoki_eval/`。产品不导入它（`kototoki/schema.py`、`kototoki/judge.py` 是复制品），删 `experiments/` 后它没有使用者 | "第二个使用者出现时再加"；需要时从 tag 取回放进 `research/_lib/` |
| D4 | **删除** `tests/equivalence/` 与 `just test-equivalence`；`gate-full` 改为 `gate-core` 加 `test-full`。core 里的 `ResearchPinTests` 等字面量钉住保留，只把注释里的来源改成归档 tag 路径 | 对照对象被删除；规则已由 core 钉住 |
| D5 | `research/_lib/` 现在不建；第一次有跨轮复用的研究工具时再建 | 不建空目录 |
| D6 | 旧文档目录 `docs/research/`、`docs/plans/`、`docs/context/`、`docs/testing/`、`docs/guides/`、`docs/archive/`，以及 `docs/agents/subtitle-translation-evaluation.md`、已 superseded 的 `docs/specs/subtitle-translation-*.md`、`docs/specs/w0-reusable-demo.md`、`docs/specs/x0-reusable-demo.md`：内容提炼进轮次 README 或现行正文后删除 | 同 D2 |
| D7 | ADR 正文允许**修链接**（旧路径改为新轮次目录或 tag 路径），决定内容与状态行不改；新增 ADR-0031 记录本规范，取代"冻结证据只读"规则 | 历史记录的价值在内容，不在字节 |
| D8 | 已结题的 `.scratch/<slug>/`：确认有价值的结论已进轮次 README、ADR 或模块页后**删除**；进行中或待执行的保留 | 计划与票据是施工日志，完工后靠 git 历史追溯 |
| D9 | `experiments/w0_demo/THIRD_PARTY_NOTICES.txt` 原样移到仓库根 `THIRD_PARTY_NOTICES.txt`（产品代码派生自 WhisperX，许可声明必须随仓库分发） | 许可义务 |

## 新布局（目标状态）

```
kototoki/                 产品包（本次不动）
research/
  INDEX.md                轮次登记（一行一轮）＋按主题的现状＋研究方法约束
  TEMPLATE.md             轮次 README 模板
  <YYYY-MM>-<slug>/
    README.md             本轮记录（必填，见下）
    *.py                  今后新轮次的代码与本轮放一起（旧轮次不带代码）
  acceptance/             产品验收记录，一次一篇，同样按模板精简
docs/                     只放现行内容：architecture、specs、adr、development、agents、operations
tests/core  tests/full    （equivalence 删除）
.scratch/<slug>/          只放进行中的计划与票据，完工后删
data.toml                 ——本次不建；第一个需要数据的新研究轮次建立，见规范 R5
```

## 新规范（ticket 01 写入权威文档；摘要）

- **R1 一轮一目录**：研究的计划、代码、结论放在 `research/<YYYY-MM>-<slug>/`；不再拆到 `docs/research`、`.scratch`、`experiments` 三处。立项时在 `research/INDEX.md` 登记一行。
- **R2 轮次 README 必填项**（`research/TEMPLATE.md`）：状态；时间；问题；策略（试了哪些方案，各一句）；环境与版本（模型名与量化、推理引擎及版本、关键依赖、GPU）；测试（数据集的类型、规模与来源类别，指标与判据）；结果（少量关键数字，表格不超过约 10 行）；结论与去向（采纳／放弃，对应 ADR 或产品变更）；教训（可选）；原始材料（tag 路径，可选）。正文不超过约 150 行。
- **R3 不写进研究记录**：文件或样本的 sha256 等哈希（git commit SHA 除外）；本机绝对路径；逐窗、逐条明细与大段日志；字幕或转写原文（短例外）；执行台账与接跑步骤。
- **R4 冻结靠 git**：结题即在 README 状态写 `concluded`／`stopped`，不再要求"字节不可改"；修错、修链接、精简随时可以做。需要原始材料从归档 tag 取。代码不得对文档做 sha256 自检。
- **R5 依赖方向**：产品永不导入 `research/`；研究可以导入产品。研究要用的数据通过仓库根 `data.toml`（逻辑名 → 相对数据根的路径）和环境变量 `KOTOTOKI_DATA` 定位，代码与文档不写本机绝对路径。跨轮复用的研究工具放 `research/_lib/`（有第二个使用者时才建）。
- **R6 规则移植**：研究结论要进产品时，产品实现是唯一权威；后续研究直接调用产品实现，不保留研究侧副本，因此不再需要 equivalence 对照。需要钉住的取值在 core 测试里以字面量钉。
- **R7 `.scratch/<slug>/`** 只放产品侧进行中的计划与票据；完工时把持久结论写进模块页或 ADR，然后删除该目录。研究轮次的计划写在轮次目录里。
- **R8 机械检查**（`scripts/check_docs.py`，ticket 06 实现）：`research/*/README.md` 含 R2 的必填标题；`research/`、`docs/`、`tests/` 下不出现 `[A-Za-z]:[\\/]` 形式的绝对路径（测试中显式标注的虚构路径可白名单）；`research/` 下不出现 64 位十六进制串；`kototoki/` 不导入 `research`（`tests/core/test_boundaries.py`）。

## 旧材料 → 新轮次映射（建议，执行时可合并或拆分，原则是"一个策略问题一轮"）

来源路径均相对仓库根；`r/` = `docs/research/`，`p/` = `docs/plans/`，`c/` = `docs/context/`，`t/` = `docs/testing/`，`e/` = `experiments/`，`s/` = `.scratch/`。执行者先 grep 补全遗漏来源。

| 新目录 `research/…` | 主要来源 |
| --- | --- |
| `2026-10-stt-landscape` | r/2026-10-03-*（候选、应用对比、后端契约、管线设计、时间戳失败案例、demo readiness）、r/2026-10-04-runtime-inventory、model-assets、subtitle-edit-model-reuse |
| `2026-10-stt-demo-w0-x0` | r/2026-10-04-whisper-*、qwen-execution、crisp-execution、dev-comparison、heldout、validation、fullfilm-results、final-performance、display-analysis、silence-preflight、stt-demo-conclusions、two-film-revalidation；p/local-stt-demo-selection、whisper-framework-equivalence、two-film-stt-revalidation；c/2026-10-04-demo-execution；t/ 下 demo 与评估器相关；e/whisper、qwen、crisp、w0_demo、x0_demo、framework_equivalence、analysis、display、performance、corpus；docs/specs/w0-、x0-reusable-demo；docs/guides/baseline-testing |
| `2026-10-components-and-ctc` | r/2026-10-04-component-augmentation-*、japanese-ctc-*、w0-ctc-exploration、w0-vad-ctc-follow-up；p/component-augmentation、japanese-ctc-supplement、w0-vad-ctc-follow-up；e/components、japanese_ctc |
| `2026-10-vad-comparison` | r/2026-10-05-*vad*、pyannote-gpu-comparison、fullfilm-segmentation-comparison；p/vad-baseline-comparison、pyannote-gpu-comparison、fullfilm-segmentation-comparison；c/2026-10-05-vad-comparison-execution；e/vad_comparison |
| `2026-10-asr-candidates` | r/2026-10-05-asr-*、japanese-longform-asr-sources、parliament-baselines、yodas2-japanese-selection；p/asr-candidates-fullfilm；e/asr_candidates、fullfilm_comparison、asr_nospeech；t/yodas2-parliament-reference |
| `2026-10-x0-whisperx-flow` | r/2026-10-05-x0-whisperx-*；p/x0-whisperx-flow；e/x0_flow |
| `2026-10-translation-model-selection` | r/2026-10-05-translation-*、*-local-translation、subtitle-translation、2026-10-06-*、2026-10-07-hy30-four-quantization-results（含附录目录）；p/translation-model-comparison、hy30-*、hy-mt2-translation-mode-optimization、claude-judge-profile；c/2026-10-06-*；e/translation_demo、translation_compat、translation_corpus、translation_judge、translation_eval、translation_four_*.py、translation_comparison_report.py；docs/specs/subtitle-translation-*；docs/guides/local-translation-model-assets；docs/agents/subtitle-translation-evaluation.md；docs/archive/ |
| `2026-10-translation-flow-v1-v4` | r/2026-10-07-hy30-flow-*、2026-10-10-*、2026-10-11-*；p/hy-mt2-translation-flow-exploration-v2..v4；c/2026-10-07..11-*；e/translation_flow、translation_v4 |
| `2026-10-quality-v5` | r/2026-10-16-quality-exploration-v5；e/quality_v5；s/quality-exploration-v5 |
| `2026-10-batching-v6-v8` | r/2026-10-16-scene-aware-batching-v6、gap-aware-batching-v7、2026-10-17-dynamic-cut-batching-simulation、2026-10-18-group-reorder-v8、reorder-group-offline-stats；e/reorder_groups；s/scene-batching-v6、gap-aware-batching-v7、group-reorder-v8 |
| `2026-10-cue-token-boundary` | r/2026-10-15-cue-token-boundary-study |
| `2026-10-cross-asr-judge` | r/2026-10-19-asr-pair-*、acoustic-judge-survey；s/cross-asr-judge（先看是否还有未完成票据） |
| `2026-10-name-consistency` | r/2026-10-19-name-consistency-*；e/name_consistency；s/name-consistency |
| `2026-10-q-line-v9-v11` | r/2026-10-21-*、2026-10-22-*；e/translation_v3（Q 线配方部分）；s/general-model-translation-v9、q0-exploration-v10、q0-product-route-v11 |
| `2026-11-strata-v12-v13` | r/2026-11-08-*；e/scene_batching_v6（v12、v13 部分）；s/strata-flash-next-v12、names-on-strata-v13 |
| `2026-11-asr-robustness-v14-v15` | r/2026-11-09-*、2026-11-10-*；e/asr_robustness_v14、asr_robustness_v15；s/asr-robustness-v14、v15 |
| `acceptance/<日期>-<主题>.md` | r/acceptance/*（module-page-history 三篇与 r/2026-11-11-bilingual-pipeline-spec-history 不迁，属 git 历史） |

跨轮信息去向：`r/timeline.md` 中用户裁定 → 对应轮次 README 的"结论与去向"或 ADR；`r/topics/*` 与 `r/INDEX.md` 的"按主题的现状" → `research/INDEX.md`；AGENTS.md 里"确认集已开封、v2 已停止"等研究方法约束 → `research/INDEX.md` 的"研究方法约束"一节（精简为规则，不带集合哈希）。

## 票据

| # | 票据 | 依赖 | 可并行 |
| --- | --- | --- | --- |
| 01 | [归档 tag 与规范落地](issues/01-archive-tag-and-rules.md) | — | — |
| 02 | [STT 线轮次记录](issues/02-research-stt.md) | 01 | 与 03、04 并行 |
| 03 | [翻译 H0 线轮次记录](issues/03-research-translation-h0.md) | 01 | 与 02、04 并行 |
| 04 | [Q 线、ASR 稳健性、专名、交叉合并与验收记录](issues/04-research-q-asr-acceptance.md) | 01 | 与 02、03 并行 |
| 05 | [现行文档改链与旧文档删除](issues/05-current-docs.md) | 02、03、04 | — |
| 06 | [代码侧清理与机械检查](issues/06-code-and-checks.md) | 05 | — |
| 07 | [.scratch 清理](issues/07-scratch-cleanup.md) | 05 | 与 06 并行 |
| 08 | [总验收](issues/08-final-verification.md) | 06、07 | — |

执行提示词：[prompt.md](prompt.md)。

## 前置条件

- 本机 `.venv`、`.local/tools` 已在 2026-11-18 备份时删除。门禁需要先 `just setup`（改环境、联网，按 AGENTS.md 先问用户）；或在新电脑上 clone 并 setup 后执行。
- `test-full` 依赖 `.local/tools/ffmpeg`，setup 后才可跑。

## 已知遗留（本次不处理）

- `kototoki/` 中 9 处注释写着"复制自 `experiments/…`"，删除后指向不存在的路径。按"不改产品代码"保留，在 `research/INDEX.md` 注明这些路径指归档 tag；下次因其他原因改到这些文件时顺手更新。
- 仓库外的 Claude memory（已备份到移动硬盘）中有基于旧规则的条目（字节保护、研究轮次两步流程），恢复 memory 后按 ADR-0031 更新。

## 进度

（执行者每完成一张票据在此追加一行：日期、票据、提交 SHA。）

## Comments
