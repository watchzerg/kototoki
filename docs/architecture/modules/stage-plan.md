# 阶段计划

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0012](../../adr/0012-cross-asr-judge.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0020](../../adr/0020-media-inputs-work-dir-and-side-by-side-publish.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线中"一个文件接下来该跑哪个阶段"的唯一判据：阶段链、各阶段的产物与输入名、模型文件清单与固定 SHA256、各阶段的期望身份，以及从产物身份推出的"下一个要跑的阶段"与发布记录用的 `sources`。阶段分解与产物总表见[技术设计](../../specs/bilingual-subtitle-pipeline.md) §2、§4。

编排（[批次编排](batch-orchestration.md)）与三个 worker 壳（[STT worker](stt-workers.md)）都从这里取身份：壳把它写进产物，编排用它核对产物是否当前。

不负责：身份的组成规则与匹配本身（[产物契约](artifact-contract.md)的 `derived_identity`／`is_current`）；配方常量与 `recipe_hash` 的取值（[配置、配方与媒体提取](config-and-media.md)）；翻译阶段的 run 目录与身份（[翻译子系统](translation-subsystem.md)的 `translate.plan`）；比对产物内容、写文件、加载模型。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md#产品包的责任边界)。

## 当前行为规格

**阶段链**：

```
probe/extract ─► vad ─► asr ─► align ─► cues ─► names ─► translate ─► publish
                  vad.json 无语音时直接 ──────────────────────────────► publish
probe ─► 内嵌日文字幕（CPU，编排写 ja.srt 与 ja-embedded.json）─► names ─► translate ─► publish
```

- 需要核对身份的阶段按链上顺序为 `STAGES = (vad, asr, align, cues, names, translate)`，其中 `GPU_STAGES = (vad, asr, align)` 由 worker 子进程跑；names 与 translate 由编排在进程内跑。
- names 恒在链上（建表必开）；`publish`（无语音）是计划的终态，不是阶段。
- `STAGE_OUTPUT`：阶段 → 工作目录内产物文件名（names 为 `name-table.json`；translate 没有条目）。
- `STAGE_INPUTS`：GPU 阶段 → worker jobs 的输入名与文件：vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`。
- `IDENTITY_KEY`：阶段 → 身份键，即 `published.json`（审计记录）的 `sources` 键；`cues` 阶段为 `ja_cues`，names 为 `names`。

**内嵌日文字幕路径**（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）：

- `Target.embedded` 不为 None（值是 `ja-embedded.json` 的身份，编排在 CPU 阶段已确认当前）时，`next_stage` 从 names 起核对，不看 `vad.json`／`asr.json`／`align.json`／`ja-cues.json`，也不调用 `ModelSha`；此时 `Target.pcm_sha256` 为 None。
- 是否采用字幕轨由编排判定；`ja-embedded.json` 是否当前由本模块的 `embedded_current(work_dir, identity)` 判定：身份匹配，且记下的 `ja_srt_sha256` 等于工作目录里 `ja.srt` 的 SHA256。编排在 CPU 阶段调用它决定要不要重新抽取。
- 期望身份 `embedded_identity(probe, stream_index)`：上游为输入文件身份（`probe.json` 的身份）的 `object_hash`、`EMBEDDED` 配方 hash、配置键 `stream_index`。
- 这条路径下 `identities` 以 `ja_embedded`（常量 `EMBEDDED_KEY`）代替 vad／asr／align／ja_cues；`sources` 为 `probe`、`ja_embedded`、`names`、`translate` 加 `no_speech`（恒为 false）。names 与 translate 的身份照旧只认 `ja.srt` 的 SHA256。

**期望身份**（字段、键名与取值决定现有工作目录能否续跑，改动即令对应产物不当前）：

| 产物 | 身份（`plan` 的函数） |
| --- | --- |
| `probe.json` | `probe_identity`：`video_identity`（相对路径、大小、`mtime_ns`、ffprobe 指纹）＋ `MEDIA` 配方 hash ＋ 配置键 `audio_language` |
| `vad.json`／`asr.json`／`align.json` | `vad_identity`／`asr_identity`／`align_identity`：上游 PCM 与上游产物 SHA256、配方 hash（`recipe_hash(stage, engine=…)`，只有 asr 需要引擎）、模型文件 SHA256 |
| `ja-cues.json` | `cues_identity`：上游 `align.json` ＋ `CUES` 配方 hash ＋ `[cues]` 规则 |
| `name-table.json` | `names_identity(ja_srt_sha256, config)`：`{ja_srt_sha256, recipe_hash, seed}`，`recipe_hash` 为延迟导入的 `kototoki.names.recipes.BUILD_RECIPE_HASH`，`seed` 为 `[names] seed` |
| 翻译 | `translate_plan`：读 `ja.srt` 与 `name-table.json`，调用 `translate.plan(work_dir, ja.srt 文档, name_table, config)`，身份 `{ja_srt_sha256, recipe_hash, seed, names_sha256}`、run 目录与 `needs_model` 都由它给出 |

- `MEDIA` 含下混、未标注布局时的声道数映射与音轨选择规则（含语言别名表），这些规则一变 `probe.json` 即不当前、重抽音频；PCM 不变时 vad 及下游身份不变。
- `ja-cues.json` 是否当前另要求 payload 记下的 `ja_srt_sha256` 等于工作目录里 `ja.srt` 的 SHA256（`ja.srt` 缺失、被手改或被内嵌路径改写即不当前、cues 重跑）；没有该字段的 `ja-cues.json` 同样不当前。这一步与 `embedded_current` 共用辅助函数 `_current_with_ja_srt`。
- `name-table.json` 的模型名与 Strata 身份在建表配方里，不进身份；表不当前即需要建表。
- 表中会被注入的条目一改，`names_sha256` 变、翻译身份变、重新翻译；`names` 阶段自己的身份不变（表仍当前，不重建）。计划把整个 `TranslatePlan` 带在 `Plan.translate` 上。

**引擎组成**：`ENGINE_PARTS`（`w0 → ("w0",)`、`x0 → ("x0",)`、`cross → ("w0", "x0")`）是"一个 ASR 引擎由哪些模型组成"的唯一出处：`model_files`、worker 壳 `workers/asr.start`（加载哪些适配器）与复读守卫的判定（这一路是不是 w0）都读它。它与 `ASR_RECIPES`、`config.ENGINES` 同键（`config` 在基础层，不反向导入 `plan`，靠测试保持一致）。

**cross 的 asr 身份**（[ADR-0012](../../adr/0012-cross-asr-judge.md)）：

- `ASR_RECIPES` 有 `w0`、`x0`、`cross`（→ `recipes.CROSS`）三项，其它值抛错。
- `cross` 的 `asr.json` 身份：上游 PCM SHA256 ＋ `vad.json` SHA256 ＋ `recipe_hash(CROSS)` ＋ 两路模型文件 SHA256；`model_files("asr", models, engine="cross")` 按 `ENGINE_PARTS["cross"]` 返回 w0 与 x0 两套清单的并集。
- `CROSS` 嵌入 `W0`、`X0` 与裁判参数，任一子配方变化即身份变化；`W0` 含复读守卫的 `guard` 块（[ADR-0023](../../adr/0023-asr-repeat-guard.md)）。
- 审计产物 `asr-w0.json`／`asr-x0.json` 用单引擎身份（`asr_identity("w0"|"x0", …)`，只含该路模型文件），`asr-judge.json` 用 cross 身份；三者不进 `STAGE_OUTPUT`，不参与 `is_current`。

**模型文件清单**：

- `worker_models(config)` 给出 jobs `config.models` 的路径表（`Config.models` 的同名键：`vad`、`w0`、`w0_mel_assets`、`x0`、`align`）。
- `model_files(stage, models, engine=…)` 给出 GPU 阶段加载前要核对的 `{名称: (路径, 期望 SHA256)}`：segmentation-3.0 `pytorch_model.bin`；faster-whisper-large-v3 的 `config.json`／`model.bin`／`preprocessor_config.json`／`tokenizer.json`／`vocabulary.json` 与 `w0-assets/mel_filters.npz`；qwen3-asr-1.7b-hf 的 `model.safetensors` 与全部 `.json`／`.jinja`（共 7 个，`README.md` 与下载残留不参与）；mms-1b-all 的 adapter、`model.safetensors` 与 5 个配置／词表文件。
- 期望值取自 W0／X0 基线运行记录，核对结果即身份的 `models` 字段。
- 模型文件的 SHA256 本模块不算，由调用方经 `ModelSha` 回调（阶段名 → `{模型文件名: SHA256}`）提供：编排用 `workers/gpu.verify_models` 加 size+mtime 缓存，每次运行每阶段最多一次。

**计划**：`Target(work_dir, probe, pcm_sha256, embedded=None)` 是一个文件在 CPU 阶段之后已知的常量。`Plan` 是不可变值：

- `stage`：第一个需要运行的阶段，或终态 `publish`（无语音，直接发布零条目字幕）。是否已发布不归本模块，编排在扫描时按源文件旁的 `.ja-zh.srt` 是否存在判定（ADR-0020），所以没有 `done`。
- `identities`：`probe` 与从 vad 起到 `stage` 为止各阶段的期望身份，键同 `sources`。
- `no_speech`；`translate`：核对到翻译阶段后才有的 `TranslatePlan`，否则 `None`。
- `sources`（发布记录用）：无语音时只含 `probe`、`vad`；STT 路径为 `probe`、`vad`、`asr`、`align`、`ja_cues`、`names`、`translate`；都加 `no_speech`。

函数：

- `next_stage(target, config, models)`：从 vad 起逐阶段调用 `artifacts.is_current`，第一个不当前的阶段即结果；`vad.json` 的 `chunks` 为空即无语音，结果为 `publish`；全部当前时结果为 `translate`（翻译阶段总要经过，run 已完成时只读回译文）。不读 `published.json`。每文件每次运行调用一次。
- `advance(previous, …)`：`previous.stage` 跑完之后从该阶段继续同一核对，不从头重算、不改写入参；其产物不当前时返回的 `stage` 不变（调用方据此记失败）；对已到终态的计划报错。对同一目录连续调用结果相同。
- 核对途中出错（如读不了上游产物）抛 `PlanError`，带正在核对的阶段，编排记为该阶段失败；损坏的产物不是错误，只是"不当前"。

## 接口与依赖

依赖 `artifacts`、`recipes`、`srt`、`config`（基础层）；不依赖 torch、ffmpeg 与网络。只在核对翻译阶段时延迟导入翻译子系统（`translate.plan`），只在核对 names 阶段时延迟导入 `kototoki.names.recipes`（只取 `BUILD_RECIPE_HASH`，见[专名一致性](name-consistency.md)）；worker 壳不会触发这两条边。

调用方：

- 编排：`next_stage`／`advance`、`embedded_identity`／`embedded_current`、`recipe_hash`、`STAGE_INPUTS`、`worker_models`、`model_files`（写 jobs 文件与核对模型）。
- 三个 worker 壳：身份函数、`recipe_hash` 校验 jobs、`model_files` 核对模型、`ENGINE_PARTS`。
- 伪 worker `tests/fake_worker.py`：与真 worker 一样经本模块取身份。

接口变宽或身份字段变化须先改本页与[模块边界](../module-boundaries.md#产品包的责任边界)，并核对现有工作目录的续跑不受影响。

## 代码与验证入口

- 代码：`kototoki/plan.py`（`Target`、`Plan`、`next_stage`、`advance`、`PlanError`、`ModelSha`、`ENGINE_PARTS`、`ASR_RECIPES`、各阶段身份函数、`embedded_identity`、`embedded_current`、`_current_with_ja_srt`、`EMBEDDED_KEY`、`names_identity`、`translate_plan`、`STAGES`／`GPU_STAGES`／`STAGE_INPUTS`／`STAGE_OUTPUT`／`IDENTITY_KEY`、`worker_models`、`model_files`、`recipe_hash`、模型文件 SHA256 常量）。
- `tests/core/test_plan.py`：
  - 阶段链逐级推进；cues 阶段同时要求 `ja-cues.json` 与 SHA256 相符的 `ja.srt`（手改 `ja.srt` 后 cues 重建，缺 `ja_srt_sha256` 不当前）；`MEDIA` hash 变而 PCM 不变时 vad 及下游仍当前。
  - 无语音直达 `publish`；`advance` 停在未写出产物的阶段、拒绝终态；连续调用结果相同且不改写入参；`PlanError` 标明阶段；损坏产物视为不当前。
  - 翻译阶段以属性 patch 替换 `kototoki.translate.plan`，names 阶段用伪建表 hash。
  - names 组：身份随配方 hash 与 seed 变化；链为 cues → names → translate；表过期停在 names；改高置信条目改变翻译身份、只改中低置信条目不变；从 names 继续推进；无语音路径没有 names 键。
  - 内嵌字幕组（`EmbeddedChainTests`）：身份随输入文件、配方与流索引变化；计划从 names 起且不调用 `ModelSha`；内嵌记录只在身份与 `ja.srt` 都相符时当前；一条路径改写 `ja.srt` 使另一条路径的记录不当前；目录里遗留的 STT 产物不影响这条路径。
  - 引擎组（`AsrEngineTests`）：`ENGINE_PARTS` 表及其与 `ASR_RECIPES`、`config.ENGINES` 同键；`model_files` 按表中次序给出清单；cross 身份含两路模型与 cross 配方 hash；单引擎配方 hash 钉值。
- `tests/core/test_job.py` 核对一次整批运行中每文件 `next_stage` 恰一次、每个跑过的阶段 `advance` 恰一次；`tests/core/test_stt_workers.py` 核对壳写出的身份与本模块的期望身份逐字段相等。
- 未验证：没有单独的真实运行；行为由编排与 worker 的整片验收间接覆盖。

## 变更与决策来源

- [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0012](../../adr/0012-cross-asr-judge.md)、[ADR-0014](../../adr/0014-name-consistency-in-product.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0020](../../adr/0020-media-inputs-work-dir-and-side-by-side-publish.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0023](../../adr/0023-asr-repeat-guard.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- 票据：`.scratch/bilingual-subtitle-pipeline/`（`issues/14-stage-plan-module.md`、`issues/15-translate-run-key.md`）、`.scratch/cross-asr-judge/`、`.scratch/name-consistency-product/`（`issues/05-config-assets-plan.md`）
- 计划：[`docs/plans/architecture-cleanup.md`](../../plans/architecture-cleanup.md)、[`docs/plans/product-names-on-strata.md`](../../plans/product-names-on-strata.md)
- 验收：[cross 产品路径验收](../../research/acceptance/2026-10-19-cross-asr-acceptance.md)
- 历史：[技术设计历史](../../research/2026-11-11-bilingual-pipeline-spec-history.md)
