---
covers:
  - kototoki/workers/asr.py
---
# STT ASR：w0／x0 引擎、cross 裁判与整窗守卫

状态：current；权威决定：[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责 asr 阶段的内容：两个推理适配器（w0 = faster-whisper large-v3，x0 = Qwen3-ASR-1.7B-hf）、可选的 `cross` 引擎（同一进程两路转写＋Whisper 教师强制打分裁判）、w0 的整窗守卫，以及 ASR 壳 `workers/asr.py` 如何组合它们写出 `asr.json`。

worker 壳的共用规则（jobs、模型核对、身份、写产物、失败分级、日志配置）、VAD 与对齐见 [STT worker](stt-workers.md)。现行引擎取值、`cross` 配方与守卫规则的完整定义见[现行决定](../../adr/CURRENT.md)（"产品 STT 引擎""ASR 整窗守卫"两节）；配方常量见[配置、配方与媒体提取](config-and-media.md)。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

### 子页

| 子页 | 何时读 |
| --- | --- |
| [w0／x0 适配器](stt-asr/engines.md) | 改 `asr_whisper.py`、`asr_qwen.py`，或核对两个引擎的解码参数、CUDA 库加载顺序、单窗失败与触顶处理 |
| [整窗守卫](stt-asr/window-guard.md) | 改 `guard.py` 或壳内 `apply_guard`，或核对复读／语速／幻听句三条规则、`guard` trace 与日志 |
| [cross 引擎与裁判](stt-asr/cross-judge.md) | 改 `judge.py`、`WhisperAsr.score`、cross 的加载与逐文件流程，或核对审计产物字段 |

## 当前行为规格

**引擎与模型键**：`config.engine` 取 `cross`（默认，ADR-0035）、`w0` 或 `x0`。加载哪些适配器、读哪些模型键按 `plan.ENGINE_PARTS`：w0 只读 `w0`，x0 只读 `x0`，cross 两者都读；`recipe_hash` 分别为 `recipes.W0`、`X0`、`CROSS` 的 hash。`W0` 含 `guard` 块（ADR-0030），`CROSS` 嵌套 `W0` 与 `X0`。

**`asr.json`**（三种引擎同构）：`schema_version`、`engine`、`offset_s`、`input`、`chunks`（照抄 `vad.json`）、`original_segments`（与窗口一一对应：`text`、秒与整数样本、`avg_logprob`）、`asr_traces`、`failed_windows`、保留文本 `text`、`metadata`、`stages`。

- `asr_traces` 是引擎自有的诊断：w0 为 tokens、prompt、解码参数、特征 SHA256，被整窗守卫改动的窗口另有 `guard`。
- x0 为 tokens、`generated_tokens`、`token_limit_reached`、原始输出、检测语言、输入设备与形状证据、PCM SHA256 与逐窗耗时。
- 解码抛 `RuntimeError` 的失败窗口 trace 为 `null`。

各引擎的行为规格见上表子页。

## 实现设计

壳内一个辅助函数 `workers.asr.transcribe` 承担"转写 → 计时 → 守卫 → 记失败 → 组文档"，单引擎的 `compute` 与 `cross` 的两路都用它；守卫是否生效只在这一处按"这一路是不是 w0"（`plan.ENGINE_PARTS` 的部件名）决定。

`cross` 不新增推理模块，壳 `workers/asr.py` 同时持有 `WhisperAsr` 与 `QwenAsr`，两路的模型身份按 `plan.model_files(..., engine=part)` 拆分。

## 接口与依赖

各适配器与守卫的函数接口见对应子页；以下依赖规则对三个子页共用。

- `judge` 属基础层，只依赖标准库，不导入 torch、研究代码与任何推理模块；打分函数由壳传入。
- `kototoki.guard` 属基础层，只导入 `recipes` 与 `judge.normalize`。`guard.REPEAT`、`guard.SPEECH_RATE`、`guard.PHRASES` 是三条规则的规则名与参数（取自 `recipes.W0["guard"]` 的三个子块）。

## 代码与验证入口

- 代码：`kototoki/workers/asr.py`（壳，`transcribe`、`apply_guard`、`compute`、cross 编排）；适配器见[w0／x0 适配器](stt-asr/engines.md#代码与验证入口)，守卫见[整窗守卫](stt-asr/window-guard.md#代码与验证入口)，裁判见[cross 引擎与裁判](stt-asr/cross-judge.md#代码与验证入口)。共用壳 `kototoki/workers/gpu.py` 见 [STT worker](stt-workers.md)。
- 真实模型验证：`just smoke ct2_after_torch`（CT2 的 CUDA 库来源）；其余路径由小批量 `just subtitles` 覆盖（[STT worker](stt-workers.md#代码与验证入口)）。
- 未验证：显存紧张的机器上 `cross` 共驻能否放下（没有回退路径）、w0 失败窗口以 x0 替代（不做）、数值确定性、译文层收益与新材料确认；x0 触顶的真实路径。

## 变更与决策来源

- [ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- 研究：[交叉打分](../../research/2026-10-cross-asr-judge.md)、[v15](../../research/2026-11-asr-robustness-v14-v15.md)；`no_speech_prob` 测量（归档 experiments/asr_nospeech/，票据 batch-run-fixes 09）
- 验收：[cross 共驻探针](../../research/acceptance/cross-coresidency-probe-2026-10-19.md)、[cross 产品路径验收](../../research/acceptance/cross-asr-acceptance-2026-10-19.md)、[两部整片验收](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)、[最终验收](../../research/acceptance/bilingual-pipeline-final-acceptance-2026-10-15.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/（`issues/03-stt-workers.md`、`issues/07-x0-engine.md`）、.scratch/cross-asr-judge/、.scratch/asr-repeat-guard/、.scratch/batch-run-fixes/（`issues/09-short-window-asr-overflow.md`）、.scratch/runtime-logging-gaps/
- 归档 tag `archive/2026-11-18-pre-research-restructure` 中：计划 docs/plans/asr-repeat-guard.md、docs/plans/architecture-cleanup.md；模块页拆出的历史记录 docs/research/acceptance/2026-11-11-module-page-history-stt-plan-artifacts.md；来源代码 experiments/ 下的 w0_demo/asr.py、x0_demo/asr.py、qwen/run_qwen.py、asr_robustness_v15/repeat.py、quality_v5
