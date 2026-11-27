# 失败收敛

[跨模块流程](../collaborations.md)的子页：转写、建表与翻译中的失败如何在模块之间收敛到窗口、cue、文件或批次一级（原技术设计 §6 中的跨模块部分）。用户看到的结果（文件级隔离、无语音、质量门、续跑）见[中日双语字幕批量生产流水线](../../behaviors/bilingual-subtitle-pipeline.md#边界与错误情况)；锁冲突与 Strata 被拒绝的批次级收敛见[阶段链与调度](stage-chain-and-scheduling.md#gpu-内部顺序与并发)。

## 窗口级：ASR 失败窗口

w0／x0／cross 同一表示：x0 生成触顶、w0 整窗守卫置空（复读折叠后仍命中、语速 > 20 字/秒、整窗是已知幻听句；[ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)），都只把该窗 `text` 置空、原因与原文记入 `failed_windows`，不进对齐、cue 与翻译，不让整部影片失败（[STT worker](../modules/stt-workers.md)、[产物契约](../modules/artifact-contract/worker-protocol.md)）。

## 调用级：Strata 基础设施失败与批次终态

ADR-0029「基础设施失败」：OOM、服务崩溃／断开、传输错误、Strata 起不来属基础设施失败，同一调用内重启 Strata，最多 2 次；生成触顶、结构校验失败、超出 context、一条都没收下是该次尝试失败，两次都失败即节点终态，进入拆分；`StrataRefused` 不重试；被拒绝或整批启动失败累计达额度后，本批其余需要模型的影片直接失败（额度见 [Strata session](../modules/strata-session.md)）。

## cue 级：按条解决

产品规则，配方另名 `q3-translate-v1`，ADR-0029：回复结构合法即按条收下，缺失、空串、含空行的 cue 按最大连续段再问；两次都失败的节点对半拆，单条仍失败该 cue 不出中文，双语字幕里只有日文一行；未翻译清单写 `report.json` 并在汇总给出未翻译数。可靠性重试、按条追问与拆分都不是"翻译多次再挑选"（ADR-0008）。见[翻译子系统](../modules/translation-subsystem.md)。

## 文件级：专名建表失败

ADR-0028「建表失败」：超预算或 5 次回复格式都不合格写空表（模型回空表不算失败，ADR-0028）（`build.status` 为 `too_long`／`failed`），记 WARNING，影片照常翻译与发布；Strata 起不来、OOM、HTTP 或传输失败是该影片 `names` 阶段的文件级失败（[专名一致性](../modules/name-consistency.md)）。
