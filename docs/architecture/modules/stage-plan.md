# 阶段计划

状态：current（2026-11-11 加内嵌日文字幕路径，ADR-0024；票据 14 交付，2026-10-15；票据 15 把翻译身份与 `needs_model` 转交翻译子系统，2026-10-15；专名票据 05 在 cues 与 translate 之间加 names 阶段，2026-10-19）。此前阶段链、worker 输入名、模型键表与各阶段身份散在 `job`、三个 worker 壳与伪 worker 六处，收进 `kototoki/plan.py` 后身份字段、键名与取值逐字节不变（四个整片工作目录的 vad／asr／align／translate 身份重算全等，新旧 `next_stage` 对拍一致）。2026-11-11 起按 [ADR-0025](../../adr/0025-product-package-boundaries.md) 所属计划 [`architecture-cleanup`](../../plans/architecture-cleanup.md) 先行写入本页接口（引擎组成表 `ENGINE_PARTS`、`ja.srt` 新鲜度的统一判定，`MEDIA` 补进声道布局与音轨选择规则后 `probe.json` 一次性失效），代码随该计划的票据 03、06 落地，结果见计划 §7。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3、§4，[模块边界](../module-boundaries.md#产品包的责任边界)）中"一个文件接下来该跑哪个阶段"的唯一判据：阶段链、各阶段的产物与输入名、模型文件清单与固定 SHA256、各阶段的期望身份，以及从产物身份推出的"下一个要跑的阶段"与发布状态。编排（[批次编排](batch-orchestration.md)）与三个 worker 壳（[STT worker](stt-workers.md)）都从这里取身份：壳把它写进产物，编排用它核对产物是否当前。不负责：身份的组成规则与匹配本身（[产物契约](artifact-contract.md)的 `derived_identity`／`is_current`）、配方常量与 `recipe_hash` 的取值（[配置、配方与媒体提取](config-and-media.md)）、翻译阶段的 run 目录与身份（[翻译子系统](translation-subsystem.md)的 `translate.plan`；身份含注入行的 `names_sha256`）、比对产物内容、写文件、加载模型。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**阶段链**（规格 §3）：

```
probe/extract ─► vad ─► asr ─► align ─► cues ─► names ─► translate ─► publish
                  vad.json 无语音时直接 ──────────────────────────────► publish
probe ─► 内嵌日文字幕（CPU，编排写 ja.srt 与 ja-embedded.json）─► names ─► translate ─► publish
```

**内嵌日文字幕路径**（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）：`Target.embedded` 不为 None（值是 `ja-embedded.json` 的身份，编排在 CPU 阶段已确认当前）时，`next_stage` 从 names 起核对，不看 `vad.json`／`asr.json`／`align.json`／`ja-cues.json`，也不调用 `ModelSha`（不核对任何 GPU 阶段的模型）；此时 `Target.pcm_sha256` 为 None。是否采用字幕轨由编排判定；`ja-embedded.json` 是否当前由本模块判定（身份匹配，且记下的 `ja_srt_sha256` 等于工作目录里 `ja.srt` 的 SHA256，与 cues 检查共用同一个辅助函数），编排在 CPU 阶段调用它决定要不要重新抽取。期望身份 `embedded_identity(probe, stream_index)`：上游为输入文件身份（`probe.json` 的身份）的 `object_hash`、`EMBEDDED` 配方 hash、配置键 `stream_index`。这条路径下 `identities` 以 `ja_embedded`（常量 `EMBEDDED_KEY`）代替 vad／asr／align／ja_cues，`sources` 为 `probe`、`ja_embedded`、`names`、`translate` 加 `no_speech`（恒为 false：零条目的字幕轨不会被采用）。names 与 translate 的身份照旧只认 `ja.srt` 的 SHA256。

需要核对身份的阶段按链上顺序为 `STAGES = (vad, asr, align, cues, names, translate)`，其中 `GPU_STAGES = (vad, asr, align)`（由 worker 子进程跑；names 与 translate 由编排在进程内跑，见[批次编排](batch-orchestration.md)）；names 恒在链上（建表必开，[ADR-0019](../../adr/0019-product-translation-q2.md)）；`publish`（无语音）是计划的终态，不是阶段。阶段表：`STAGE_OUTPUT`（阶段 → 工作目录内产物文件名，names 为 `name-table.json`）、`STAGE_INPUTS`（GPU 阶段 → worker jobs 的输入名与文件：vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）、`IDENTITY_KEY`（阶段 → 身份键，即 `published.json`〔审计记录〕的 `sources` 键，`cues` 阶段为 `ja_cues`，names 为 `names`）。

**期望身份**（字段、键名与取值不变：现有产物目录续跑必须全部命中）：

| 产物 | 身份（`plan` 的函数） |
| --- | --- |
| `probe.json` | `probe_identity`：`video_identity`（相对路径、大小、`mtime_ns`、ffprobe 指纹）＋ `MEDIA` 配方 hash ＋ `audio_language`。`MEDIA` 含下混、未标注布局时的声道数映射与音轨选择规则（含语言别名表），这些规则一变 `probe.json` 即不当前、重抽音频；PCM 不变时 vad 及下游身份不变（[配置、配方与媒体提取](config-and-media.md)） |
| `vad.json`／`asr.json`／`align.json` | `vad_identity`／`asr_identity`／`align_identity`：上游 PCM 与上游产物 SHA256、配方 hash（`recipe_hash(stage, engine=…)`，只有 asr 需要引擎）、模型文件 SHA256；worker 壳写进产物的是同一个函数的结果 |
| `ja-cues.json` | `cues_identity`：上游 `align.json` ＋ `CUES` 配方 hash ＋ `[cues]` 规则。是否当前另要求 payload 记下的 `ja_srt_sha256` 等于工作目录里 `ja.srt` 的 SHA256（`ja.srt` 缺失、被手改或被内嵌路径改写即不当前、cues 重跑）；这一步与 `ja-embedded.json` 的同类检查共用一个辅助函数 |
| `name-table.json` | `names_identity(ja_srt_sha256, config)`：`{ja_srt_sha256, recipe_hash, seed}`（与翻译身份同形），`recipe_hash` 为延迟导入的 `kototoki.names.recipes.BUILD_RECIPE_HASH`（模型名与 Strata 身份在建表配方里，不进身份），`seed` 为 `[names] seed`；表不当前即需要建表，没有"是否需要模型"的内部状态 |
| 翻译 | `translate_plan`：读 `ja.srt` 与 `name-table.json`（核对到翻译阶段时表必已当前），调用翻译子系统 `translate.plan(work_dir, ja.srt, name_table, config)`（核对到该阶段时才导入），身份 `{ja_srt_sha256, recipe_hash, seed, names_sha256}`、run 目录与 `needs_model` 都由它给出，计划把整个 `TranslatePlan` 带在 `Plan.translate` 上。表中会被注入的条目一改，`names_sha256` 变、翻译身份变、重新翻译并发布；`names` 阶段自己的身份不变（表仍当前，不重建） |

**引擎组成**：`ENGINE_PARTS`（`w0 → ("w0",)`、`x0 → ("x0",)`、`cross → ("w0", "x0")`）是"一个 ASR 引擎由哪些模型组成"的唯一出处：`model_files`、worker 壳 `workers/asr.start`（加载哪些适配器）与复读守卫的判定（这一路是不是 w0）都读它，不各自写分支。`tests/core/test_plan.py` 钉住这张表、它与 `ASR_RECIPES`、`config.ENGINES` 同键（`config` 在基础层，不反向导入 `plan`，靠测试保持一致），以及 `model_files` 按表中次序给出清单。

**模型文件清单**：`worker_models(config)` 给出 jobs `config.models` 的路径表（`Config.models` 的同名键：`vad`、`w0`、`w0_mel_assets`、`x0`、`align`）；`model_files(stage, models, engine=…)` 给出 GPU 阶段加载前要核对的 `{名称: (路径, 期望 SHA256)}`：segmentation-3.0 `pytorch_model.bin`；faster-whisper-large-v3 的 `config.json`／`model.bin`／`preprocessor_config.json`／`tokenizer.json`／`vocabulary.json` 与 `w0-assets/mel_filters.npz`；qwen3-asr-1.7b-hf 的 `model.safetensors` 与全部 `.json`／`.jinja`（共 7 个）；mms-1b-all 的 adapter、`model.safetensors` 与 5 个配置／词表文件。期望值取自 W0／X0 基线运行记录，核对结果即身份的 `models` 字段。模型文件的 SHA256 本模块不算，由调用方经 `ModelSha` 回调（阶段名 → `{模型文件名: SHA256}`）提供：编排用 `workers/gpu.verify_models` 加 size+mtime 缓存，每次运行每阶段最多一次。

**w0 配方与复读守卫**（[ADR-0023](../../adr/0023-asr-repeat-guard.md)）：`recipes.W0` 自 2026-11-11 起带 `guard` 块（id `w0-faster-whisper-large-v3-guard-v2`），`recipe_hash("asr", engine="w0")` 与嵌套它的 `cross` 的 hash 随之改变；身份的组成规则不变，旧工作目录的 `asr.json` 不再当前，asr 及其下游按既有规则重算。

**cross 引擎的 asr 身份**（[ADR-0012](../../adr/0012-cross-asr-judge.md)）：`ASR_RECIPES` 有 `w0`、`x0`、`cross`（→ `recipes.CROSS`）三项，`recipe_hash("asr", engine="cross")` 与 `asr_identity("cross", …)` 可用，其它值抛错。`cross` 的 `asr.json` 身份：上游 PCM SHA256 ＋ `vad.json` SHA256 ＋ `recipe_hash(CROSS)` ＋ 两路模型文件 SHA256，即 w0 模型（`config.json`／`model.bin`／`preprocessor_config.json`／`tokenizer.json`／`vocabulary.json`）、mel 资产 `mel_filters.npz` 与 x0 模型（7 个文件），共 13 个；`model_files("asr", models, engine="cross")` 按 `ENGINE_PARTS["cross"]` 返回 w0 与 x0 两套清单的并集。`CROSS` 配方字典嵌入 `W0`、`X0` 与裁判参数，一个 hash 覆盖全部，任一子配方变化即身份变化（字段见[配置与配方](config-and-media.md)）。worker 另写的 `asr-w0.json`／`asr-x0.json` 用单引擎身份（`asr_identity("w0"|"x0", …)`，只含该路模型文件）、`asr-judge.json` 用 cross 身份，三者是审计产物，不进 `STAGE_OUTPUT`，不参与 `is_current`（见[产物契约](artifact-contract.md)）。身份字段与键名不变，其它阶段的身份函数与阶段链不变。

**计划**：`Target(work_dir, probe, pcm_sha256, embedded=None)` 是一个文件在 CPU 阶段之后已知的常量（`embedded` 见上"内嵌日文字幕路径"）。`Plan` 是不可变值：`stage`（第一个需要运行的阶段，或终态 `publish`：无语音，直接发布零条目字幕；是否已发布不归本模块，编排在扫描时按源文件旁的 `.ja-zh.srt` 是否存在判定，ADR-0020，所以没有 `done`）、`identities`（`probe` 与从 vad 起到 `stage` 为止各阶段的期望身份，键同 `sources`；`names` 在表当前时已含其中）、`no_speech`、`translate`（核对到翻译阶段后才有的 `TranslatePlan`，否则 `None`），以及发布记录用的 `sources`（无语音时只含 `probe`、`vad`；否则为 `probe`、`vad`、`asr`、`align`、`ja_cues`、`names`、`translate`，加 `no_speech`）。

- `next_stage(target, config, models)`：从 vad 起逐阶段调用 `artifacts.is_current`，第一个不当前的阶段即结果（`cues` 阶段同时要求 `ja.srt` 的 SHA256 等于 `ja-cues.json` 记下的 `ja_srt_sha256`）；`vad.json` 的 `chunks` 为空即无语音，结果为 `publish`；全部当前时结果为 `translate`（翻译阶段总要经过，run 已完成时只读回译文）。不读 `published.json`。每文件每次运行调用一次。
- `advance(previous, …)`：`previous.stage` 跑完之后从该阶段继续同一核对，不从头重算、不改写入参；其产物不当前时返回的 `stage` 不变（调用方据此记失败）；对已到终态的计划报错。对同一目录连续调用结果相同。
- 核对途中出错（如读不了上游产物）抛 `PlanError`，带正在核对的阶段，编排记为该阶段失败；损坏的产物不是错误，只是"不当前"。

## 接口与依赖

依赖 `artifacts`、`recipes`、`srt`、`config`（基础层）；不依赖 torch、ffmpeg 与网络；只在核对翻译阶段时延迟导入翻译子系统（`translate.plan`），只在核对 names 阶段时延迟导入 `kototoki.names.recipes`（只取 `BUILD_RECIPE_HASH`，见[专名一致性](name-consistency.md)），worker 壳不会触发这两条边。调用方：编排（`next_stage`／`advance`、`recipe_hash`、`STAGE_INPUTS`、`worker_models`、`model_files` 写 jobs 文件与核对模型）、三个 worker 壳（身份函数、`recipe_hash` 校验 jobs、`model_files` 核对模型）、伪 worker `tests/fake_worker.py`（与真 worker 一样经本模块取身份）。接口变宽或身份字段变化须先改本页与[模块边界](../module-boundaries.md#产品包的责任边界)，并核对现有工作目录的续跑不受影响。

## 代码与验证入口

- 代码：`kototoki/plan.py`（`Target`、`Plan`、`next_stage`、`advance`、`PlanError`、`ModelSha`、`ENGINE_PARTS`、各阶段身份函数、`embedded_identity` 与内嵌记录是否当前的判定 `embedded_current(work_dir, identity)`、`ja.srt` 新鲜度辅助函数 `_current_with_ja_srt`（cues 检查与 `embedded_current` 共用）、`EMBEDDED_KEY`、`names_identity`、`translate_plan`、`STAGES`／`GPU_STAGES`／`STAGE_INPUTS`／`STAGE_OUTPUT`／`IDENTITY_KEY`、`worker_models`、`model_files`、`recipe_hash`、模型文件 SHA256 常量）。
- 测试（core，`just test`）：`tests/core/test_plan.py` 直接测计划模块：阶段链逐级推进、cues 阶段同时要求 `ja-cues.json` 与 SHA256 相符的 `ja.srt`（手改 `ja.srt` 后 cues 重建）、`MEDIA` hash 变而 PCM 不变时 vad、asr、align、cues 仍当前、无语音直达 `publish`、`advance` 停在未写出产物的阶段、连续调用结果相同且不改写入参、`PlanError` 标明阶段、损坏产物视为不当前；翻译阶段以属性 patch 替换 `kototoki.translate.plan`（只需返回 `identity` 与 `needs_model`），names 阶段用伪建表 hash；names 组另测身份随配方 hash 与 seed 变化、链为 cues → names → translate、`ja.srt`／seed 变化或表缺失停在 names、手改注入条目改变翻译身份并重新翻译与发布、从 names 继续推进、无语音路径没有 names 键（具体用例以 `test_plan.py` 当前内容为准，ADR-0019 后随之改写）；内嵌字幕组（`EmbeddedChainTests`）测身份随输入文件、配方与流索引变化、计划从 names 起且不调用 `ModelSha`、`sources` 的键、目录里遗留的 STT 产物不影响这条路径。`tests/core/test_job.py` 核对一次整批运行中每文件 `next_stage` 恰一次、每个跑过的阶段 `advance` 恰一次；`tests/core/test_stt_workers.py` 核对壳写出的身份与本模块的期望身份逐字段相等。
- 真实运行：票据 14 交付时对四个整片工作目录重算身份全等（见状态行）。
- 未验证：没有单独的真实运行；行为由编排与 worker 的整片验收间接覆盖。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/14-stage-plan-module.md`（2026-10-15 架构评审候选 1：把散在六处的阶段链与身份收进一个模块）、`15-translate-run-key.md`（翻译 run 键、身份与 `needs_model` 归翻译子系统，本模块只转问）；规格 §1.2、§4、§13。

2026-10-19 `cross` 引擎交付，依据 [ADR-0012](../../adr/0012-cross-asr-judge.md) 与[产品路径验收](../../research/acceptance/2026-10-19-cross-asr-acceptance.md)，票据 `.scratch/cross-asr-judge/`；增量说明已吸收进本页（asr 身份）并删除。

2026-10-19／20 专名一致性进产品（[ADR-0014](../../adr/0014-name-consistency-in-product.md)）：票据 `.scratch/name-consistency-product/issues/05-config-assets-plan.md` 加 names 阶段与两个身份，06 接入编排并同步本页。

2026-11-08 产品翻译切到 Q2（[ADR-0019](../../adr/0019-product-translation-q2.md)）：删除 `[names] enabled` 与 `names_apply` 身份，translate 身份加 `names_sha256`，`translate_plan` 读 `name-table.json` 交给翻译子系统；发布状态判定比较期望键与记录键的并集。

2026-11-09 产品建表切到 Strata（[ADR-0022](../../adr/0022-product-names-on-strata.md)）：`names_identity` 形状不变，`BUILD_RECIPE_HASH` 换为新配方 `q3-names-v1` 的值，旧 `name-table.json` 全部失效、重建。

2026-11-11 内嵌日文字幕（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）：`Target` 加 `embedded`、`pcm_sha256` 可为 None，加 `embedded_identity` 与 `EMBEDDED_KEY`，`next_stage` 对这类文件从 names 起；STT 路径的身份字段、键名与取值不变。

2026-11-11 产品包架构整理（计划 [`docs/plans/architecture-cleanup.md`](../../plans/architecture-cleanup.md) §3 决定 2 与票据 03、06；[ADR-0025](../../adr/0025-product-package-boundaries.md)）：加 `ENGINE_PARTS`；cues 检查从"`ja.srt` 存在"改为比对 `ja-cues.json` 记下的 `ja_srt_sha256`，"内嵌记录是否当前"从编排挪进本模块并与之共用辅助函数（旧 `ja-cues.json` 没有该字段，自然重建一次，不写兼容分支）；`MEDIA` hash 变一次。
