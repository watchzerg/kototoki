# 阶段计划

状态：current（票据 14 交付，2026-10-15；票据 15 把翻译身份与 `needs_model` 转交翻译子系统，2026-10-15；专名票据 05 在 cues 与 translate 之间加 names 阶段，2026-10-19）。此前阶段链、worker 输入名、模型键表与各阶段身份散在 `job`、三个 worker 壳与伪 worker 六处，收进 `kototoki/plan.py` 后身份字段、键名与取值逐字节不变（四个整片工作目录的 vad／asr／align／translate 身份重算全等，新旧 `next_stage` 对拍一致）。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3、§4，[模块边界](../module-boundaries.md#产品包的责任边界)）中"一个文件接下来该跑哪个阶段"的唯一判据：阶段链、各阶段的产物与输入名、模型文件清单与固定 SHA256、各阶段的期望身份，以及从产物身份推出的"下一个要跑的阶段"与发布状态。编排（[批次编排](batch-orchestration.md)）与三个 worker 壳（[STT worker](stt-workers.md)）都从这里取身份：壳把它写进产物，编排用它核对产物是否当前。不负责：身份的组成规则与匹配本身（[产物契约](artifact-contract.md)的 `derived_identity`／`is_current`）、配方常量与 `recipe_hash` 的取值（[配置、配方与媒体提取](config-and-media.md)）、翻译阶段的 run 目录与身份（[翻译子系统](translation-subsystem.md)的 `translate.plan`）、比对产物内容、写文件、加载模型。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**阶段链**（规格 §3）：

```
probe/extract ─► vad ─► asr ─► align ─► cues ─► names ─► translate ─► publish
                  vad.json 无语音时直接 ──────────────────────────────► publish
```

需要核对身份的阶段按链上顺序为 `STAGES = (vad, asr, align, cues, names, translate)`，其中 `GPU_STAGES = (vad, asr, align)`（由 worker 子进程跑；names 与 translate 由编排在进程内跑，见[批次编排](batch-orchestration.md)）；`[names] enabled = false` 时核对直接跳过 names；`publish`／`done` 是计划的终态，不是阶段。阶段表：`STAGE_OUTPUT`（阶段 → 工作目录内产物文件名，names 为 `name-table.json`）、`STAGE_INPUTS`（GPU 阶段 → worker jobs 的输入名与文件：vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）、`IDENTITY_KEY`（阶段 → `published.json` 的 `sources` 键，`cues` 阶段为 `ja_cues`，names 为 `names`）；发布时替换的审计产物 `names-apply.json` 另有键 `names_apply`，它不是阶段。

**期望身份**（字段、键名与取值不变：现有产物目录续跑必须全部命中）：

| 产物 | 身份（`plan` 的函数） |
| --- | --- |
| `probe.json` | `probe_identity`：`video_identity`（相对路径、大小、`mtime_ns`、ffprobe 指纹）＋ `MEDIA` 配方 hash ＋ `audio_language` |
| `vad.json`／`asr.json`／`align.json` | `vad_identity`／`asr_identity`／`align_identity`：上游 PCM 与上游产物 SHA256、配方 hash（`recipe_hash(stage, engine=…)`，只有 asr 需要引擎）、模型文件 SHA256；worker 壳写进产物的是同一个函数的结果 |
| `ja-cues.json` | `cues_identity`：上游 `align.json` ＋ `CUES` 配方 hash ＋ `[cues]` 规则 |
| `name-table.json` | `names_identity(ja_srt_sha256, config)`：`{ja_srt_sha256, recipe_hash, seed}`（与翻译身份同形），`recipe_hash` 为延迟导入的 `kototoki.names.recipes.BUILD_RECIPE_HASH`（模型 SHA256 在建表配方里，不进身份），`seed` 为 `[names] seed`；表不当前即需要建表，没有"是否需要模型"的内部状态 |
| `names-apply.json` | `names_apply_identity(table_sha256)`：`derived_identity(upstream={name-table.json: 表文件 SHA256}, recipe_hash=APPLY_RECIPE_HASH)`；只在表当前时算出并进 `sources`，不参与 `is_current`。表文件 SHA256 覆盖用户手改的 `entries`，因此改表只改变本身份 |
| 翻译 | `translate_plan`：调用翻译子系统 `translate.plan(work_dir, ja.srt, config)`（核对到该阶段时才导入），身份 `{ja_srt_sha256, recipe_hash, seed}`、run 目录与 `needs_model` 都由它给出，计划把整个 `TranslatePlan` 带在 `Plan.translate` 上 |

**模型文件清单**：`worker_models(config)` 给出 jobs `config.models` 的路径表（`Config.models` 的同名键：`vad`、`w0`、`w0_mel_assets`、`x0`、`align`）；`model_files(stage, models, engine=…)` 给出 GPU 阶段加载前要核对的 `{名称: (路径, 期望 SHA256)}`：segmentation-3.0 `pytorch_model.bin`；faster-whisper-large-v3 的 `config.json`／`model.bin`／`preprocessor_config.json`／`tokenizer.json`／`vocabulary.json` 与 `w0-assets/mel_filters.npz`；qwen3-asr-1.7b-hf 的 `model.safetensors` 与全部 `.json`／`.jinja`（共 7 个）；mms-1b-all 的 adapter、`model.safetensors` 与 5 个配置／词表文件。期望值取自 W0／X0 基线运行记录，核对结果即身份的 `models` 字段。模型文件的 SHA256 本模块不算，由调用方经 `ModelSha` 回调（阶段名 → `{模型文件名: SHA256}`）提供：编排用 `workers/gpu.verify_models` 加 size+mtime 缓存，每次运行每阶段最多一次。

**cross 引擎的 asr 身份**（[ADR-0012](../../adr/0012-cross-asr-judge.md)）：`ASR_RECIPES` 有 `w0`、`x0`、`cross`（→ `recipes.CROSS`）三项，`recipe_hash("asr", engine="cross")` 与 `asr_identity("cross", …)` 可用，其它值抛错。`cross` 的 `asr.json` 身份：上游 PCM SHA256 ＋ `vad.json` SHA256 ＋ `recipe_hash(CROSS)` ＋ 两路模型文件 SHA256，即 w0 模型（`config.json`／`model.bin`／`preprocessor_config.json`／`tokenizer.json`／`vocabulary.json`）、mel 资产 `mel_filters.npz` 与 x0 模型（7 个文件），共 13 个；`model_files("asr", models, engine="cross")` 因而返回 w0 与 x0 两套清单的并集。`CROSS` 配方字典嵌入 `W0`、`X0` 与裁判参数，一个 hash 覆盖全部，任一子配方变化即身份变化（字段见[配置与配方](config-and-media.md)）。worker 另写的 `asr-w0.json`／`asr-x0.json` 用单引擎身份（`asr_identity("w0"|"x0", …)`，只含该路模型文件）、`asr-judge.json` 用 cross 身份，三者是审计产物，不进 `STAGE_OUTPUT`，不参与 `is_current`（见[产物契约](artifact-contract.md)）。身份字段与键名不变，其它阶段的身份函数与阶段链不变。

**计划**：`Target(work_dir, finals, probe, pcm_sha256)` 是一个文件在 CPU 阶段之后已知的常量。`Plan` 是不可变值：`stage`（第一个需要运行的阶段，或终态 `publish`：无语音，直接发布零条目 SRT；`done`：已发布且身份匹配、最终文件未改动）、`identities`（`probe` 与从 vad 起到 `stage` 为止各阶段的期望身份，键同 `published.json` 的 `sources`；names 启用且表当前时另含 `names_apply`）、`no_speech`、`translate`（核对到翻译阶段后才有的 `TranslatePlan`，否则 `None`），以及发布记录用的 `sources`（无语音时只含 `probe`、`vad`；否则为 `probe`、`vad`、`asr`、`align`、`ja_cues`、names 启用时的 `names`／`names_apply`、`translate`，加 `no_speech`）。

- `next_stage(target, config, models)`：从 vad 起逐阶段调用 `artifacts.is_current`，第一个不当前的阶段即结果（`cues` 阶段同时要求 `ja.srt` 在）；`vad.json` 的 `chunks` 为空即无语音，跳到发布判定；全部当前时对照 `published.json`：`sources` 与期望相同且三份最终文件 SHA 等于记录即 `done`，否则 `translate`（无语音时 `publish`）。比较时总带上 `names`／`names_apply` 两键（期望里没有也比）：从启用改为停用时记录里多出的两键同样触发重新发布。每文件每次运行调用一次。
- `advance(previous, …)`：`previous.stage` 跑完之后从该阶段继续同一核对，不从头重算、不改写入参；其产物不当前时返回的 `stage` 不变（调用方据此记失败）；对已到终态的计划报错。对同一目录连续调用结果相同。
- 核对途中出错（如读不了上游产物）抛 `PlanError`，带正在核对的阶段，编排记为该阶段失败；损坏的产物不是错误，只是"不当前"。

## 接口与依赖

依赖 `artifacts`、`recipes`、`srt`、`config`（基础层）；不依赖 torch、ffmpeg 与网络；只在核对翻译阶段时延迟导入翻译子系统（`translate.plan`），只在核对 names 阶段时延迟导入 `kototoki.names.recipes`（取 `BUILD_RECIPE_HASH`／`APPLY_RECIPE_HASH`，见[专名一致性](name-consistency.md)），worker 壳不会触发这两条边。调用方：编排（`next_stage`／`advance`、`recipe_hash`、`STAGE_INPUTS`、`worker_models`、`model_files` 写 jobs 文件与核对模型）、三个 worker 壳（身份函数、`recipe_hash` 校验 jobs、`model_files` 核对模型）、伪 worker `tests/fake_worker.py`（与真 worker 一样经本模块取身份）。接口变宽或身份字段变化须先改本页与[模块边界](../module-boundaries.md#产品包的责任边界)，并核对现有工作目录的续跑不受影响。

## 代码与验证入口

- 代码：`kototoki/plan.py`（`Target`、`Plan`、`next_stage`、`advance`、`PlanError`、`ModelSha`、各阶段身份函数、`names_identity`、`names_apply_identity`、`translate_plan`、`STAGES`／`GPU_STAGES`／`STAGE_INPUTS`／`STAGE_OUTPUT`／`IDENTITY_KEY`、`worker_models`、`model_files`、`recipe_hash`、模型文件 SHA256 常量）。
- 测试（core，`just test`）：`tests/core/test_plan.py` 直接测计划模块：阶段链逐级推进、cues 阶段同时要求 `ja-cues.json` 与 `ja.srt`、无语音直达 `publish` 再 `done`、最终文件改动或身份改变即重新发布、`advance` 停在未写出产物的阶段、连续调用结果相同且不改写入参、`PlanError` 标明阶段、损坏产物视为不当前；翻译阶段用 `sys.modules` 里的伪 `kototoki.translate` 模块（只需 `plan` 返回 `identity` 与 `needs_model`），names 阶段用伪 `kototoki.names.recipes`（两个 hash）；names 组（`[names] enabled = true`）另测身份随配方 hash 与 seed 变化、链为 cues → names → translate 且表不当前时没有 `names_apply`、`ja.srt`／seed 变化或表缺失停在 names、手改条目只改变 `names_apply` 并重新发布、从 names 继续推进、无语音路径没有两键、停用即跳过并重新发布；其余各组默认停用 names，即接入前的链与 `sources`。`tests/core/test_job.py` 核对一次整批运行中每文件 `next_stage` 恰一次、每个跑过的阶段 `advance` 恰一次；`tests/core/test_stt_workers.py` 核对壳写出的身份与本模块的期望身份逐字段相等。
- 真实运行：票据 14 交付时对四个整片工作目录重算身份全等（见状态行）。
- 未验证：没有单独的真实运行；行为由编排与 worker 的整片验收间接覆盖。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/14-stage-plan-module.md`（2026-10-15 架构评审候选 1：把散在六处的阶段链与身份收进一个模块）、`15-translate-run-key.md`（翻译 run 键、身份与 `needs_model` 归翻译子系统，本模块只转问）；规格 §1.2、§4、§13。

2026-10-19 `cross` 引擎交付，依据 [ADR-0012](../../adr/0012-cross-asr-judge.md) 与[产品路径验收](../../research/acceptance/2026-10-19-cross-asr-acceptance.md)，票据 `.scratch/cross-asr-judge/`；增量说明已吸收进本页（asr 身份）并删除。

2026-10-19／20 专名一致性进产品（[ADR-0014](../../adr/0014-name-consistency-in-product.md)）：票据 `.scratch/name-consistency-product/issues/05-config-assets-plan.md` 加 names 阶段与两个身份，06 接入编排并同步本页。
