# 计划索引（冻结）

状态：current（目录冻结：不再新增文件，新计划写 `.scratch/<slug>/spec.md`，见 [issue-tracker 约定](../agents/issue-tracker.md)）

本目录的计划都是已结束的历史记录，不再修改；“状态”一列取自各计划自己的状态行，不一致处按结果文档核实。

| 计划 | 状态 | 主题 | 结果文档 |
| --- | --- | --- | --- |
| [architecture-cleanup.md](architecture-cleanup.md) | done | 产品包 `kototoki/` 架构 review 问题的整理落地。 | [本文 §7](architecture-cleanup.md)、[.scratch/architecture-cleanup/](../../.scratch/architecture-cleanup/) |
| [asr-candidates-fullfilm.md](asr-candidates-fullfilm.md) | done | Cohere、Granite、Nemotron 三个 ASR 候选的两片整片比较。 | [整片实测报告](../research/2026-10-05-asr-candidates-fullfilm.md) |
| [asr-repeat-guard.md](asr-repeat-guard.md) | done | ASR 整窗复读守卫进产品（ADR-0023 的实现）。 | [ADR-0023](../adr/0023-asr-repeat-guard.md)、[v15 研究](../research/2026-11-10-asr-robustness-v15.md)、[.scratch/asr-repeat-guard/](../../.scratch/asr-repeat-guard/) |
| [claude-judge-profile.md](claude-judge-profile.md) | superseded | Claude 裁判 profile 的迁移、校准与基线重锚定设计。 | [v3 计划](hy-mt2-translation-flow-exploration-v3.md)、[v3 报告](../research/2026-10-10-hy30-flow-v3-report.md) |
| [component-augmentation.md](component-augmentation.md) | done | 三候选的单组件增量评估。 | [组件增量实测](../research/2026-10-04-component-augmentation-results.md) |
| [fullfilm-segmentation-comparison.md](fullfilm-segmentation-comparison.md) | done | Heaven’s Feel II／III 整片上 W0／X0 的新 Pyannote 与 cut-merge 比较。 | [整片分段比较](../research/2026-10-05-fullfilm-segmentation-comparison.md)、[ADR-0003](../adr/0003-new-pyannote-baselines.md) |
| [hy-mt2-translation-flow-exploration-v2.md](hy-mt2-translation-flow-exploration-v2.md) | stopped | Hy30 字幕流程第二轮探索：扩大样本与自适应搜索。 | [v2 台账](../context/2026-10-08-hy30-flow-exploration-v2.md)、[v1/v2 教训](../research/2026-10-10-hy30-flow-v1-v2-lessons.md) |
| [hy-mt2-translation-flow-exploration-v3.md](hy-mt2-translation-flow-exploration-v3.md) | done | Hy30 字幕流程第三轮探索：Claude 裁判下重新起跑。 | [v3 报告](../research/2026-10-10-hy30-flow-v3-report.md)、[v3 台账](../context/2026-10-10-hy30-flow-exploration-v3.md) |
| [hy-mt2-translation-flow-exploration-v4.md](hy-mt2-translation-flow-exploration-v4.md) | done | Hy30 字幕流程第四轮探索：先提高量尺精度，再测采样、多候选和译文上下文。 | [v4 报告](../research/2026-10-11-hy30-flow-v4-report.md)、[v4 台账](../context/2026-10-11-hy30-flow-exploration-v4.md)、[ADR-0008](../adr/0008-no-multi-translation-selection.md) |
| [hy-mt2-translation-mode-optimization.md](hy-mt2-translation-mode-optimization.md) | done | 固定 Hy-MT2 后寻找更好的 SRT→SRT 翻译流程（第一轮）。 | [结果报告](../research/2026-10-07-hy30-flow-optimization-results.md)、[探索台账](../context/2026-10-07-hy30-flow-exploration.md) |
| [hy30-four-quantization-comparison.md](hy30-four-quantization-comparison.md) | done | Hy-MT2 30B-A3B 四种量化的大规模对比。 | [结果报告](../research/2026-10-07-hy30-four-quantization-results.md)、[接跑记录](../context/2026-10-06-hy30-four-execution.md)、[ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md) |
| [hy30-q3-q4-comparison.md](hy30-q3-q4-comparison.md) | done | Hy-MT2 30B-A3B Q3／Q4 速度与质量对照。 | [结果报告](../research/2026-10-06-hy30-q3-q4-comparison-results.md) |
| [japanese-ctc-supplement.md](japanese-ctc-supplement.md) | done | 日语 CTC 候选对齐器的补充实测。 | [CTC 实测结果](../research/2026-10-04-japanese-ctc-results.md) |
| [local-stt-demo-selection.md](local-stt-demo-selection.md) | done | 本地 STT demo 实测与选型。 | [实施结论](../research/2026-10-04-stt-demo-conclusions.md)、[运行记录](../context/2026-10-04-demo-execution.md) |
| [product-names-on-strata.md](product-names-on-strata.md) | done | 产品 `names` 阶段切到 Strata 建表（对齐基线 Q3）。 | [ADR-0022](../adr/0022-product-names-on-strata.md)、[ADR-0021](../adr/0021-q3-strata-names-baseline.md)、[.scratch/q3-product-switch/](../../.scratch/q3-product-switch/) |
| [pyannote-gpu-comparison.md](pyannote-gpu-comparison.md) | done | 新 Pyannote CPU／GPU 对照补测。 | [对照报告](../research/2026-10-05-pyannote-gpu-comparison.md) |
| [translation-model-comparison.md](translation-model-comparison.md) | done | 三个翻译模型家族、五个版本的评估。 | [结果报告](../research/2026-10-06-translation-model-comparison-results.md)、[执行记录](../context/2026-10-06-translation-comparison-execution.md) |
| [two-film-stt-revalidation.md](two-film-stt-revalidation.md) | done | 两片主参考上固定候选的复核。 | [两片复核报告](../research/2026-10-04-two-film-revalidation.md) |
| [vad-baseline-comparison.md](vad-baseline-comparison.md) | done | W0／X0 四种 VAD 的十组合对照。 | [比较报告](../research/2026-10-05-vad-baseline-comparison.md)、[执行状态](../context/2026-10-05-vad-comparison-execution.md) |
| [w0-vad-ctc-follow-up.md](w0-vad-ctc-follow-up.md) | done | W0＋VAD＋CTC 时间优先追加实验。 | [结果报告](../research/2026-10-04-w0-vad-ctc-follow-up.md) |
| [whisper-framework-equivalence.md](whisper-framework-equivalence.md) | done | Whisper 流程等价性与架构依据研究。 | [冻结 VAD 等价实验](../research/2026-10-04-whisper-framework-experiment.md)、[架构选择](../research/2026-10-04-whisper-framework-architecture.md) |
| [x0-whisperx-flow.md](x0-whisperx-flow.md) | done | X0 吸收 WhisperX 流程的最小验证。 | [X0／WhisperX 流程](../research/2026-10-05-x0-whisperx-flow.md)、[ADR-0002](../adr/0002-x0-demo-flow.md) |

- `claude-judge-profile.md` 的状态为 superseded，被 v3 计划的 MQM 裁判 profile 取代，不再续跑。
- `architecture-cleanup.md`、`asr-repeat-guard.md`、`product-names-on-strata.md` 是 2026-11-09／11 新增的三份计划，在原处冻结，不迁回 `.scratch/`。
