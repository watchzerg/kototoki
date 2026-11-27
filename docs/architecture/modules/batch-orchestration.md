---
covers:
  - kototoki/__main__.py
  - kototoki/job.py
---
# 批次编排

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线（[阶段链与调度](../collaborations/stage-chain-and-scheduling.md)、[产物交接](../collaborations/artifact-handoff.md)、[失败收敛](../collaborations/failure-convergence.md)）的唯一入口与全部流程知识：扫描输入（视频与音频）、调度 CPU 与 GPU 阶段、CPU 阶段产物的写入、续跑与失败隔离、两把锁的取放时机、专名表的写出、双语字幕发布到源文件旁与运行日志的挂接。

不负责：

- 阶段链、各阶段的期望身份与"下一个要跑的阶段"（[阶段计划](stage-plan.md)，编排只负责问）
- 身份的组成与匹配规则（[产物契约](artifact-contract/layout-and-identity.md)）
- 音轨与 WAV（[配置、配方与媒体提取](config-and-media.md)）
- cue 切分（[日文 cue](japanese-cues.md)）
- 推理（[STT worker](stt-workers.md)）
- 建表与翻译的内部（[专名一致性](name-consistency.md)、[翻译子系统](translation-subsystem.md)）
- 日志格式、进程原语与 worker 启动（[运行日志与进程原语](run-logging-and-processes.md)）。

上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

### 子页

| 子页 | 何时读 |
| --- | --- |
| [主流程](batch-orchestration/flow.md) | 改入口、退出码、扫描、各阶段顺序、发布或收尾不变量时 |
| [内嵌字幕与计划](batch-orchestration/embedded-and-plan.md) | 改内嵌日文字幕路径，或续跑、跳过与身份核对的编排侧行为时 |
| [运行时规则](batch-orchestration/runtime-rules.md) | 改 GPU worker 调度与崩溃处理、锁的取放时机、无语音与近乎无声、`failure.json` 清理时 |

## 当前行为规格

行为规格按主题写在各子页，见上方子页表。

## 实现设计

实现设计随各子页的行为规格一并描述，跨子页共用的依赖见下节。

## 接口与依赖

导入基础层的 `artifacts`、`config`、`srt`、`logs`、`procs`（`ProcessLock`、`LockError`、`contained`）、`workers.protocol`（jobs 读写、`classify_launch` 及其 `error_types`、`progress_event`；`job` 不含 worker 事件名字面量），以及 `media`、`cues`、`embedded`、[阶段计划](stage-plan.md)的 `plan` 与 `workers.gpu`（只用 `verify_models`，导入时不加载推理库），不导入 worker 壳。

以普通导入使用四个子系统（都不导入 `plan`、`job`，不加载 torch，测试以属性 patch 替换，如 `mock.patch("kototoki.translate.translate_document")`）：

- `kototoki.strata`：共享 session，`Session(config, on_server_pid=...)` 上下文管理器。
- `kototoki.names`：`build_document(work_dir, document, session | None, seed, *, relative=None)` 返回带 `payload`／`status`／`attempts`／`seconds` 的结果（`relative` 仅用于日志）；names 身份由阶段计划算。
- `kototoki.translate`：`translate_document(plan, session | None, *, relative)` 返回带 `translations`（cue id → 译文，不出中文为 `None`）与 `untranslated_count` 的结果；`TranslatePlan` 由阶段计划经 `translate.plan` 取得。
- `kototoki.merge`：`merge(ja_document, translations) -> srt_text`。

不导入任何推理模块与研究代码：`import kototoki.job`／`kototoki.__main__` 之后 `sys.modules` 中没有 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`。不做任何时间换算。

## 代码与验证入口

代码与验证入口集中在[主流程](batch-orchestration/flow.md#代码与验证入口)。

## 变更与决策来源

- [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0028](../../adr/0028-names-accept-empty-table.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- 归档 tag 中的计划 `archive/2026-11-18-pre-research-restructure:docs/plans/` 下 product-names-on-strata（§7 共用 session 的真实运行）、architecture-cleanup；技术设计历史记录 docs/research/2026-11-11-bilingual-pipeline-spec-history.md
- 验收：[两部整片](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)、[最终验收](../../research/acceptance/bilingual-pipeline-final-acceptance-2026-10-15.md)、[专名一致性进产品](../../research/acceptance/name-consistency-product-2026-10-20.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/issues/（06、14、15）；.scratch/runtime-logging/、.scratch/runtime-logging-gaps/；Beads `kototoki-e8t.1`（2026-10-19 审计小修）；.scratch/name-consistency-product/issues/06-orchestration.md；.scratch/q2-product-switch/；.scratch/q3-product-switch/；.scratch/architecture-cleanup/
