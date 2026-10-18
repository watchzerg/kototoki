# 阶段计划

状态：current（票据 14 交付，2026-10-15；票据 15 把翻译身份与 `needs_model` 转交翻译子系统，2026-10-15）。此前阶段链、worker 输入名、模型键表与各阶段身份散在 `job`、三个 worker 壳与伪 worker 六处，收进 `kototoki/plan.py` 后身份字段、键名与取值逐字节不变（四个整片工作目录的 vad／asr／align／translate 身份重算全等，新旧 `next_stage` 对拍一致）。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3、§4，[模块边界](../module-boundaries.md#产品包的责任边界)）中"一个文件接下来该跑哪个阶段"的唯一判据：阶段链、各阶段的产物与输入名、模型文件清单与固定 SHA256、各阶段的期望身份，以及从产物身份推出的"下一个要跑的阶段"与发布状态。编排（[批次编排](batch-orchestration.md)）与三个 worker 壳（[STT worker](stt-workers.md)）都从这里取身份：壳把它写进产物，编排用它核对产物是否当前。不负责：身份的组成规则与匹配本身（[产物契约](artifact-contract.md)的 `derived_identity`／`is_current`）、配方常量与 `recipe_hash` 的取值（[配置、配方与媒体提取](config-and-media.md)）、翻译阶段的 run 目录与身份（[翻译子系统](translation-subsystem.md)的 `translate.plan`）、比对产物内容、写文件、加载模型。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**阶段链**（规格 §3）：

```
probe/extract ─► vad ─► asr ─► align ─► cues ─► translate ─► publish
                  vad.json 无语音时直接 ─────────────────────► publish
```

需要核对身份的阶段按链上顺序为 `STAGES = (vad, asr, align, cues, translate)`，其中 `GPU_STAGES = (vad, asr, align)`；`publish`／`done` 是计划的终态，不是阶段。阶段表：`STAGE_OUTPUT`（阶段 → 工作目录内产物文件名）、`STAGE_INPUTS`（GPU 阶段 → worker jobs 的输入名与文件：vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）、`IDENTITY_KEY`（阶段 → `published.json` 的 `sources` 键，`cues` 阶段为 `ja_cues`）。

**期望身份**（字段、键名与取值不变：现有产物目录续跑必须全部命中）：

| 产物 | 身份（`plan` 的函数） |
| --- | --- |
| `probe.json` | `probe_identity`：`video_identity`（相对路径、大小、`mtime_ns`、ffprobe 指纹）＋ `MEDIA` 配方 hash ＋ `audio_language` |
| `vad.json`／`asr.json`／`align.json` | `vad_identity`／`asr_identity`／`align_identity`：上游 PCM 与上游产物 SHA256、配方 hash（`recipe_hash(stage, engine=…)`，只有 asr 需要引擎）、模型文件 SHA256；worker 壳写进产物的是同一个函数的结果 |
| `ja-cues.json` | `cues_identity`：上游 `align.json` ＋ `CUES` 配方 hash ＋ `[cues]` 规则 |
| 翻译 | `translate_plan`：调用翻译子系统 `translate.plan(work_dir, ja.srt, config)`（核对到该阶段时才导入），身份 `{ja_srt_sha256, recipe_hash, seed}`、run 目录与 `needs_model` 都由它给出，计划把整个 `TranslatePlan` 带在 `Plan.translate` 上 |

**模型文件清单**：`worker_models(config)` 给出 jobs `config.models` 的路径表（`Config.models` 的同名键：`vad`、`w0`、`w0_mel_assets`、`x0`、`align`）；`model_files(stage, models, engine=…)` 给出 GPU 阶段加载前要核对的 `{名称: (路径, 期望 SHA256)}`：segmentation-3.0 `pytorch_model.bin`；faster-whisper-large-v3 的 `config.json`／`model.bin`／`preprocessor_config.json`／`tokenizer.json`／`vocabulary.json` 与 `w0-assets/mel_filters.npz`；qwen3-asr-1.7b-hf 的 `model.safetensors` 与全部 `.json`／`.jinja`（共 7 个）；mms-1b-all 的 adapter、`model.safetensors` 与 5 个配置／词表文件。期望值取自 W0／X0 基线运行记录，核对结果即身份的 `models` 字段。模型文件的 SHA256 本模块不算，由调用方经 `ModelSha` 回调（阶段名 → `{模型文件名: SHA256}`）提供：编排用 `workers/gpu.verify_models` 加 size+mtime 缓存，每次运行每阶段最多一次。

**计划**：`Target(work_dir, finals, probe, pcm_sha256)` 是一个文件在 CPU 阶段之后已知的常量。`Plan` 是不可变值：`stage`（第一个需要运行的阶段，或终态 `publish`：无语音，直接发布零条目 SRT；`done`：已发布且身份匹配、最终文件未改动）、`identities`（`probe` 与从 vad 起到 `stage` 为止各阶段的期望身份，键同 `published.json` 的 `sources`）、`no_speech`、`translate`（核对到翻译阶段后才有的 `TranslatePlan`，否则 `None`），以及发布记录用的 `sources`（无语音时只含 `probe`、`vad`）。

- `next_stage(target, config, models)`：从 vad 起逐阶段调用 `artifacts.is_current`，第一个不当前的阶段即结果（`cues` 阶段同时要求 `ja.srt` 在）；`vad.json` 的 `chunks` 为空即无语音，跳到发布判定；全部当前时对照 `published.json`：`sources` 与期望相同且三份最终文件 SHA 等于记录即 `done`，否则 `translate`（无语音时 `publish`）。每文件每次运行调用一次。
- `advance(previous, …)`：`previous.stage` 跑完之后从该阶段继续同一核对，不从头重算、不改写入参；其产物不当前时返回的 `stage` 不变（调用方据此记失败）；对已到终态的计划报错。对同一目录连续调用结果相同。
- 核对途中出错（如读不了上游产物）抛 `PlanError`，带正在核对的阶段，编排记为该阶段失败；损坏的产物不是错误，只是"不当前"。

## 接口与依赖

依赖 `artifacts`、`recipes`、`srt`、`config`（基础层）；不依赖 torch、ffmpeg 与网络；只在核对翻译阶段时延迟导入翻译子系统（`translate.plan`），worker 壳不会触发这条边。调用方：编排（`next_stage`／`advance`、`recipe_hash`、`STAGE_INPUTS`、`worker_models`、`model_files` 写 jobs 文件与核对模型）、三个 worker 壳（身份函数、`recipe_hash` 校验 jobs、`model_files` 核对模型）、伪 worker `tests/fake_worker.py`（与真 worker 一样经本模块取身份）。接口变宽或身份字段变化须先改本页与[模块边界](../module-boundaries.md#产品包的责任边界)，并核对现有工作目录的续跑不受影响。

## 代码与验证入口

- 代码：`kototoki/plan.py`（`Target`、`Plan`、`next_stage`、`advance`、`PlanError`、`ModelSha`、各阶段身份函数、`translate_plan`、`STAGES`／`GPU_STAGES`／`STAGE_INPUTS`／`STAGE_OUTPUT`／`IDENTITY_KEY`、`worker_models`、`model_files`、`recipe_hash`、模型文件 SHA256 常量）。
- 测试（core，`just test`）：`tests/core/test_plan.py` 直接测计划模块：阶段链逐级推进、cues 阶段同时要求 `ja-cues.json` 与 `ja.srt`、无语音直达 `publish` 再 `done`、最终文件改动或身份改变即重新发布、`advance` 停在未写出产物的阶段、连续调用结果相同且不改写入参、`PlanError` 标明阶段、损坏产物视为不当前；翻译阶段用 `sys.modules` 里的伪 `kototoki.translate` 模块（只需 `plan` 返回 `identity` 与 `needs_model`）。`tests/core/test_job.py` 核对一次整批运行中每文件 `next_stage` 恰一次、每个跑过的阶段 `advance` 恰一次；`tests/core/test_stt_workers.py` 核对壳写出的身份与本模块的期望身份逐字段相等。
- 真实运行：票据 14 交付时对四个整片工作目录重算身份全等（见状态行）。
- 未验证：没有单独的真实运行；行为由编排与 worker 的整片验收间接覆盖。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/14-stage-plan-module.md`（2026-10-15 架构评审候选 1：把散在六处的阶段链与身份收进一个模块）、`15-translate-run-key.md`（翻译 run 键、身份与 `needs_model` 归翻译子系统，本模块只转问）；规格 §1.2、§4、§13。
