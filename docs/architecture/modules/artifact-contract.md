# 产物契约

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线（[行为规格](../../behaviors/bilingual-subtitle-pipeline.md)）各阶段共用的三件事：工作目录布局与最终字幕路径、产物身份与跳过／替换、原子写；编排器与 GPU worker 之间的 `--jobs` 协议；SRT 读写。

不负责：各阶段的推理与 payload 字段（[STT worker](stt-workers.md)、[STT ASR](stt-asr.md)、[日文 cue](japanese-cues.md)、[专名一致性](name-consistency.md)）；每阶段期望身份的组成（[阶段计划](stage-plan.md)）；批次编排与锁（[批次编排](batch-orchestration.md)）；翻译 run 目录内部格式（[翻译子系统](translation-subsystem.md)）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

### 子页

| 子页 | 何时读 |
| --- | --- |
| [工作目录布局与产物身份](artifact-contract/layout-and-identity.md) | 改 `kototoki/artifacts.py`：工作目录与最终字幕路径、产物文件名、身份与 `is_current`、失败与发布记录、cross 审计／专名／内嵌产物、原子写 |
| [worker `--jobs` 协议与退出码](artifact-contract/worker-protocol.md) | 改 `kototoki/workers/protocol.py`：jobs 文件、进度事件、退出码、`classify_launch` 的崩溃判定、失败窗口与整窗守卫记录 |
| [SRT 解析与渲染](artifact-contract/srt.md) | 改 `kototoki/srt.py`：严格解析、毫秒取整、字幕文字规则、`write_srt` |

## 当前行为规格

本页没有自有行为规格，三块内容各在一个子页：布局与身份见[工作目录布局与产物身份](artifact-contract/layout-and-identity.md)，worker 协议见[worker `--jobs` 协议与退出码](artifact-contract/worker-protocol.md)，SRT 见[SRT 解析与渲染](artifact-contract/srt.md)。

## 实现设计

本页没有自有实现设计，原子写见[工作目录布局与产物身份](artifact-contract/layout-and-identity.md#原子写)，协议读侧见[worker `--jobs` 协议与退出码](artifact-contract/worker-protocol.md#协议读侧)。

## 接口与依赖

只依赖标准库；不导入研究代码、torch 或任何推理包，编排器可直接导入。本模块只提供身份的组成规则（`video_identity`、`derived_identity`）与匹配（`is_current`、`canonical`）；每个阶段的期望身份由谁的 SHA、哪个配方 hash、哪些模型文件组成，归[阶段计划](stage-plan.md)，worker 壳与编排都向它取。CUDA 粘性错误的识别与包装为 `FatalWorkerError` 归 worker 壳（[STT worker](stt-workers.md)）。`<work root>/lock`、GPU 锁与 worker 子进程重启归编排器。

## 代码与验证入口

- 代码与测试分别见三个子页的「代码与验证入口」：`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`。
- worker 协议、身份跳过与发布已由真实 worker 在[两部整片验收](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)中使用。

## 变更与决策来源

- ADR：
  - [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0028](../../adr/0028-names-accept-empty-table.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)；
  - [ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/（`issues/00-foundation.md`）、.scratch/cross-asr-judge/、.scratch/name-consistency-product/；Beads `kototoki-e8t`（2026-10-19 审计 B-1、B-13）
- 计划：`archive/2026-11-18-pre-research-restructure:docs/plans/architecture-cleanup.md`
- 验收：[两部整片验收](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)、[cross 产品路径验收](../../research/acceptance/cross-asr-acceptance-2026-10-19.md)
- 历史：技术设计历史（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）
- 来源代码：`archive/2026-11-18-pre-research-restructure:experiments/translation_flow/srt.py`、`archive/2026-11-18-pre-research-restructure:experiments/translation_v3/common.py`（原子写）、`archive/2026-11-18-pre-research-restructure:experiments/translation_v3/server.py`（`verify_model`）
