---
covers:
  - kototoki/translate/__init__.py
  - kototoki/merge.py
---
# 翻译子系统与双语合并

状态：current；权威决定：[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0021](../../adr/0021-q3-strata-names-baseline.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[ADR-0008](../../adr/0008-no-multi-translation-selection.md)

## 定位与阅读

负责双语字幕流水线中 `ja.srt → 译文` 与 `ja.srt + 译文 → ja-zh.srt` 两步：`dp10-cut` 切包与 Q2 请求、专名注入、按批次落盘与续跑、基础设施失败的重启、按条收下与追问、未翻译报告，以及中日两行合并。配方的完整定义见[决定定义：产品翻译](../../adr/CURRENT.md#产品翻译)；跨模块契约见[GPU 内部顺序与并发](../collaborations/stage-chain-and-scheduling.md#gpu-内部顺序与并发)、[产物交接](../collaborations/artifact-handoff.md)、[失败收敛](../collaborations/failure-convergence.md)。

不负责：

- Strata 的启停、身份核对、共享 session 与本机客户端（[Strata 服务与共享 session](strata-session.md)）；
- GPU 锁、子进程随编排器退出、`ja-zh.srt` 的写出与发布（[批次编排](batch-orchestration.md)；`zh.srt` 不发布，ADR-0007「发布」）；
- 专名表的建表（[专名一致性](name-consistency.md)）；工作目录本身的位置（[产物契约](artifact-contract.md)）；任何时间换算。

上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。本模块是 Q2 的产品移植，研究侧同名规则（归档 tag 中的 experiments/translation_v3/ 与 translation-srt-flow 模块页）已删除，本模块是唯一权威。

### 子页

| 子页 | 何时读 |
| --- | --- |
| [请求、失败分类与按条解决](translation-subsystem/requests-and-resolution.md) | 改切包、邻文、提示、专名注入、请求体与校验，或核对失败种类的处理与追问／拆分规则 |
| [session、run 目录与日志](translation-subsystem/run-directory.md) | 改批次落盘、续跑、`run.json`／`batches.jsonl` 等 run 目录内容、session 记录或翻译日志 |

## 当前行为规格

**对编排器的接口**（`kototoki.translate`）：

- `plan(work_dir, document, name_table, config) -> TranslatePlan`：只读、不写文件。`document` 是 `srt.read_srt` 读出的 `ja.srt`，`name_table` 是该影片 `name-table.json` 的内容（[阶段计划](stage-plan.md)的 `translate_plan` 读出传入）。返回：
  - `run_dir`：`<work_dir>/translate/srt-<sha12>/q3-translate-v1__s<seed>__n<names_sha12>/`；`relative` 是相对工作目录的 posix 串，即发布记录的 `translate_dir`；
  - `identity`：`{ja_srt_sha256, recipe_hash, seed, names_sha256}`，阶段计划的 translate 身份由此取得；
  - `needs_model`：零条目文档或 `run.json` 已记 `complete` 时为 False，编排器据此决定是否取 GPU 锁、启动 Strata；
  - `document` 与 `names`（注入行）。
  - `run.json` 已存在但配方 hash／seed／注入行／来源不符时抛 `ValueError`，消息提示删除该目录即可重译。
- `translate_document(plan, session, *, relative) -> TranslateResult`：`session` 是编排传入的共享 `kototoki.strata.Session`，`relative` 是输入目录内相对路径（只进日志）；`needs_model` 为 False 时可为 `None`，只读回已完成的 run（记为完成而批次文件缺失即抛 `TranslateError`，不启动 Strata）。返回：
  - `translations`：cue id → 译文，精确覆盖全部 cue；不出中文的 cue 值为 `None`（见[请求子页](translation-subsystem/requests-and-resolution.md)的"按条解决"）；
  - `untranslated_count`：不出中文的 cue 数，编排器写进 `published.json` 的 `translate_untranslated_cues`、发布日志行与控制台汇总（汇总在翻译完成时计，发布失败的文件也算）；
  - `report`：即 `report.json` 的内容。
  - 基础设施失败用尽重启、Strata 被拒绝或已不可用时抛 `TranslateError`（编排器记为该文件翻译失败）。
- `RECIPE_HASH`：配方 `q3-translate-v1` 的 hash，进翻译身份，由 `tests/core/test_translate_recipes.py` 钉住。注入行的内容不进配方 hash，进身份的 `names_sha256`。

各规则的细节见上表子页。

**合并**（`kototoki.merge.merge(ja_document, zh_translations) -> srt_text`）：纯函数；沿用日文 cue 的编号与时间行，每条两行，中文在上、日文在下；中文与日文内的换行都替换为空格；译文为 `None` 的条目只有日文一行。译文须精确覆盖全部 cue（`None` 算覆盖，只在本层处理；缺失、多余、空串、含空行抛 `IncompleteTranslationError`）；零条目文档得到空串。

## 实现设计

移植来源与取舍（研究代码已删除，产品实现是唯一权威）：

- `recipes.py`：来自 `archive/2026-11-18-pre-research-restructure:experiments/translation_v3/{qwen,strata}.py`、`names11.product_tables` 与 v9 `wide-context-v1`。Q2 规则写成常量（提示、注入、请求体、校验、配方 hash），与研究侧逐字节对照由测试钉住。产品自有的按条判定与追问使它另算 hash（`q3-translate-v1`）。Strata 身份常量从 `kototoki.strata` 取。
- `batching.py`：来自 `translation_v3/batching.py` 与 `data.py`。gap-pack-v2 切包只留 `group_gap=None` 分支；`Scene`／`Cue`（带秒）由 `ja.srt` 构造；`source_key` 是 `srt-<sha12>` 的唯一出处。
- `resolve.py`：产品自有。节点规则、按条解决与 `report.json`；不导入 `generate`，由其传入请求与日志写入函数。
- `generate.py`：来自 `translation_v3/strata.py::run_step` 与 `generate.py`。`run_step` 去掉思考分支、改为按条判定（零收下计 `unresolved`）；共享 `Session` 取代研究侧"执行者先启动服务"；按批次追加落盘；同调用内重启 Strata；按 session 记 `cache_state`。

## 接口与依赖

- 依赖：标准库、`kototoki.artifacts`、`kototoki.config`（只读 `translate.seed`）、`kototoki.srt`、中间层 `kototoki.strata`（`Session`、`StrataRefused`、身份常量）与 `kototoki.local_client`（`InfraFailure`、`explicit_oom`）。共享 `Session` 经 `ensure_started()`、`stop()`、`label`、`client()`、`unavailable` 使用（[Strata 服务与共享 session](strata-session.md#接口与依赖)）。
- 不导入 `names`（只读它写出的表内容，由 `plan` 传入）与研究代码。
- 编排器只导入包顶层的 `translate_document` 与 `kototoki.merge`；[阶段计划](stage-plan.md)延迟导入包顶层的 `plan` 取 `TranslatePlan`；包顶层还导出 `RECIPE_HASH`、`TranslateError`、`TranslateResult`。`recipes`、`batching`、`resolve`、`generate` 是内部实现。
- 外部依赖：Strata 本机 8080 服务（安装与模型由用户维护，见[依赖布局](../../development/dependencies.md)）。

## 代码与验证入口

- 代码：`kototoki/translate/__init__.py`（`plan`、`translate_document` 与导出）、`kototoki/merge.py`；其余模块见[请求子页](translation-subsystem/requests-and-resolution.md#代码与验证入口)与[运行目录子页](translation-subsystem/run-directory.md#代码与验证入口)。Strata 与客户端见 [Strata 服务与共享 session](strata-session.md#代码与验证入口)。
- 测试（core，`just test`）：`tests/core/test_merge.py`：中上日下、换行替换为空格、`None` 只输出日文一行、零条目得空串、缺失／多余／空串抛错。其余测试见子页。
- 真实模型验证（占 GPU，须用户批准）：`just smoke translate_product`（`scripts/smoke/translate_product.py`）。运行记录：Q2 首用 smoke 与整片（含 mmap 诊断）（`archive/2026-11-18-pre-research-restructure:docs/research/acceptance/2026-11-11-module-page-history-translation-names.md`）；与建表共用 session 的整片见 `archive/2026-11-18-pre-research-restructure:docs/plans/product-names-on-strata.md` §7。
- 未验证：追问与拆分只经伪客户端，追问窗口下的译文质量无裁判证据；Strata 的请求不复现（同 seed 跨启动约半数 cue 不同，ADR-0021「未验证与已知限制」），重跑不保证同一译文；产品配方在产品里的质量没有独立裁判证据（沿用 ADR-0021「依据」的 v12 F1 证据）。

## 变更与决策来源

- [ADR-0021](../../adr/0021-q3-strata-names-baseline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0008](../../adr/0008-no-multi-translation-selection.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- 归档 tag 中的 .scratch/bilingual-subtitle-pipeline/issues/（05、09、15、16）、.scratch/name-consistency-product/issues/02-shared-llama-server.md、.scratch/q2-product-switch/、.scratch/q3-product-switch/、.scratch/architecture-cleanup/、.scratch/runtime-logging-gaps/、.scratch/batch-run-fixes/issues/08-short-cue-translation.md；Beads `kototoki-e8t.1`（2026-10-19 审计小修）
- 归档 tag `archive/2026-11-18-pre-research-restructure` 中：计划 docs/plans/product-names-on-strata.md、docs/plans/architecture-cleanup.md；技术设计历史原文 docs/research/2026-11-11-bilingual-pipeline-spec-history.md；模块页拆出的历史记录 docs/research/acceptance/2026-11-11-module-page-history-translation-names.md
