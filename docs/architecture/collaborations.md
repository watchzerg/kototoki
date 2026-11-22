# 跨模块流程

状态：current

本页列出产品包 `kototoki/` 中涉及三个以上模块的流程，每个流程一页放 `collaborations/`；流程页只写顺序、等待点与失败收敛，各模块内部规则以[模块页](INDEX.md#模块地图)为准，用户可见行为见[中日双语字幕批量生产流水线](../behaviors/bilingual-subtitle-pipeline.md)。

| 流程 | 参与模块 | 何时读 |
| --- | --- | --- |
| [阶段链与调度](collaborations/stage-chain-and-scheduling.md) | [批次编排](modules/batch-orchestration.md)、[阶段计划](modules/stage-plan.md)、[配置、配方与媒体提取](modules/config-and-media.md)、[STT worker](modules/stt-workers.md)、[日文 cue](modules/japanese-cues.md)、[Strata 服务与共享 session](modules/strata-session.md)、[专名一致性](modules/name-consistency.md)、[翻译子系统](modules/translation-subsystem.md)、[运行日志与进程](modules/run-logging-and-processes.md) | 改阶段顺序、CPU／GPU 调度、GPU 锁与 Strata session 的取放、进程模型 |
| [产物交接](collaborations/artifact-handoff.md) | [产物契约](modules/artifact-contract.md)、[阶段计划](modules/stage-plan.md)、[批次编排](modules/batch-orchestration.md)、[日文 cue](modules/japanese-cues.md)、[翻译子系统](modules/translation-subsystem.md) | 改工作目录布局、阶段之间交接的文件、cue 作为翻译输入 |
| [失败收敛](collaborations/failure-convergence.md) | [STT worker](modules/stt-workers.md)、[STT ASR](modules/stt-asr.md)、[产物契约](modules/artifact-contract.md)、[Strata 服务与共享 session](modules/strata-session.md)、[专名一致性](modules/name-consistency.md)、[翻译子系统](modules/translation-subsystem.md)、[批次编排](modules/batch-orchestration.md) | 改失败窗口、Strata 基础设施失败、按条解决或建表失败的处理 |
