# 调研索引

状态：current（路由页：只写一句话和链接，结论与数字在报告正文里）

## 规则

- 本目录保存技术比较、实验、验证证据及其限制，按记录时点阅读，永不改写、不归档。
- 结论被采纳后更新当前正文或新增 ADR，证据保留原样；现行规则看[现行决定](../adr/CURRENT.md)，不从报告里推断。
- 新报告必须登记：在对应[子索引](#子索引)加一条（主题、结论、适用条件与未覆盖项），研究轮次另在[轮次登记](#轮次登记)加一行。每个文件只在一个子索引里登记一次，未登记的文件视为不存在。
- 验收记录放 `acceptance/`，文件名带日期，在[验收记录子索引](topics/acceptance-records.md)登记。
- 用户的裁定与轮次结论按日追加到[时间线](timeline.md)；它是日志，不在默认阅读路径上。
- 计划、票据与执行提示词在 `.scratch/<slug>/`，不放本目录；轮次报告只写结果与结论。
- 大报告与附录不整读：先 grep 标题，再按节读取。
- 从相邻项目迁入的调研是改写后的正文，不是对方任务状态、权限或资产的副本；各篇自带来源与限制。指向 `../../../subtitle-edit-fix/` 的链接需要那个相邻检出，原始实验产物留在那边、没有导入；外部结论的日期是原调查日期，迁入时没有重新核实。

## 按主题的现状

| 主题 | 现状 | 子索引 | 权威 |
| --- | --- | --- | --- |
| STT 基线与组件 | W0、X0 两条基线已采纳，组件选型调研结束 | [STT 组件、基线与 ASR 候选](topics/stt-components-and-baselines.md) | [ADR-0003](../adr/0003-new-pyannote-baselines.md) |
| ASR 模型候选 | 换 ASR 模型这条线已由用户裁定停止，重开前提是出现新的、许可清楚的日语 ASR 模型 | 同上 | [时间线](timeline.md) 2026-10-18 |
| VAD 与分段 | 两路统一用新 Pyannote，比较已结束 | [VAD、对齐与 cue 规则](topics/vad-alignment-and-cues.md) | [ADR-0003](../adr/0003-new-pyannote-baselines.md) |
| 强制对齐 | MMS 日语 CTC 为两条基线共用的对齐器 | 同上 | [ADR-0003](../adr/0003-new-pyannote-baselines.md) |
| cue 规则 | 引入 ASR token 边界的方案调研后不实现 | 同上 | [技术设计](../specs/bilingual-subtitle-pipeline.md) |
| 两路 ASR 交叉合并 | Whisper 交叉打分作为可选引擎 `cross` 进产品，默认仍是 w0 | [ASR 交叉合并、稳健性与专名一致性](topics/asr-robustness-and-names.md) | [ADR-0012](../adr/0012-cross-asr-judge.md) |
| ASR 稳健性 | v14、v15 已结题，只有整窗复读守卫进产品 | 同上 | [ADR-0023](../adr/0023-asr-repeat-guard.md) |
| 专名一致性 | 研究线已结题，重开只由用户明确要求；产品只建表并注入 | 同上 | [ADR-0014](../adr/0014-name-consistency-in-product.md)、[ADR-0022](../adr/0022-product-names-on-strata.md) |
| 翻译方法、模型与量化 | 历史选型（H0 的模型与量化）；H0 已不是基线 | [翻译方法、模型与量化](topics/translation-models.md) | [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md) |
| 翻译流程（H0 线） | v1–v8 已结题；切包规则沿用到现行基线，"翻译多次再挑选"已放弃，语序重排线已关闭 | [翻译流程 v1–v8](topics/translation-flow-v1-v8.md) | [ADR-0010](../adr/0010-dp10-cut-translation-flow-baseline.md)、[ADR-0008](../adr/0008-no-multi-translation-selection.md) |
| 通用模型翻译（Q 线） | v9–v13 已结题，现行唯一基线是 Q3 | [Q 线 v9–v13](topics/q-line-v9-v13.md) | [ADR-0021](../adr/0021-q3-strata-names-baseline.md) |
| 产品验收 | 各次产品改动的验收记录，冻结 | [验收记录](topics/acceptance-records.md) | 各记录所属 ADR |

## 轮次登记

状态取值：`concluded`（已结题）、`stopped`（中止并冻结）。结论只写去向，数字看报告。

| 轮次 | 日期 | 所属线 | 状态 | 一句话 | 报告 |
| --- | --- | --- | --- | --- | --- |
| v1 | 2026-10-07 | 翻译流程（H0） | concluded | 固定模型下的低成本流程方向筛选，没有替换基线 | [报告](2026-10-07-hy30-flow-optimization-results.md) |
| v2 | 2026-10-08 | 翻译流程（H0） | stopped | 第二轮探索中止并冻结，作业不恢复，只取教训作先验 | [教训](2026-10-10-hy30-flow-v1-v2-lessons.md)、[台账](../context/2026-10-08-hy30-flow-exploration-v2.md)（只按节读） |
| v3 | 2026-10-10 | 翻译流程（H0） | concluded | 改用 Claude MQM 裁判重新起跑，没有配方通过确认 | [报告](2026-10-10-hy30-flow-v3-report.md) |
| v4 | 2026-10-11 | 翻译流程（H0） | concluded | 唯一通过确认的是多样本挑选配方，后被用户放弃 | [报告](2026-10-11-hy30-flow-v4-report.md) |
| v5 | 2026-10-16 | 字幕质量 | concluded | 定位错误来源并试了 ASR 与翻译两侧，产品 STT 保持 w0，多样本挑选被放弃 | [报告](2026-10-16-quality-exploration-v5.md) |
| v6 | 2026-10-16 | 翻译流程（H0） | concluded | 场景感知分批的收益没有复现，不改默认 | [报告](2026-10-16-scene-aware-batching-v6.md) |
| v7 | 2026-10-16 | 翻译流程（H0） | concluded | 按静默拼包与停顿标记都没有改善，用户随后按逻辑采纳新切包 | [报告](2026-10-16-gap-aware-batching-v7.md) |
| v8 | 2026-10-18 | 翻译流程（H0） | concluded | 同一句话小组内语序重排没有发生，这条线关闭 | [报告](2026-10-18-group-reorder-v8.md) |
| 交叉合并 | 2026-10-19 | STT | concluded | 两路 ASR 合并的上限与三种裁判测算，交叉打分进产品作可选引擎 | [子索引](topics/asr-robustness-and-names.md) |
| 专名 1–6 轮 | 2026-10-19 | 专名一致性 | concluded | 建表加生成后替换的六轮离线验证，研究线结题 | [子索引](topics/asr-robustness-and-names.md) |
| v9 | 2026-10-21 | Q 线 | concluded | 通用模型在同一接缝下直接翻译，产生 Q0 | [报告](2026-10-21-general-model-translation-v9.md) |
| v10 | 2026-10-21 | Q 线 | concluded | 以 Q0 为对照的广度探索，只留下专名表注入一个候选成分 | [报告](2026-10-21-q0-exploration-v10.md) |
| v11 | 2026-10-22 | Q 线 | concluded | Q0 产品路线的成分验证，产生 Q1 | [报告](2026-10-22-q0-product-route-v11.md) |
| v12 | 2026-11-08 | Q 线 | concluded | Strata 上的 Flash-Next 对照 Q1，产生 Q2 | [报告](2026-11-08-strata-flash-next-v12.md) |
| v13 | 2026-11-08 | Q 线／专名 | concluded | 专名建表换到 Strata，用户采纳后产生 Q3 | [报告](2026-11-08-names-on-strata-v13.md) |
| v14 | 2026-11-09 | ASR 稳健性 | concluded | 模型不变的守卫、补窗与日文后校正三臂都没过门 | [报告](2026-11-09-asr-robustness-v14.md) |
| v15 | 2026-11-10 | ASR 稳健性 | concluded | 守卫安全网、补窗实跑与表内专名替换，只有复读守卫进产品 | [报告](2026-11-10-asr-robustness-v15.md) |

## 子索引

- [STT 组件、基线与 ASR 候选](topics/stt-components-and-baselines.md)
- [VAD、对齐与 cue 规则](topics/vad-alignment-and-cues.md)
- [翻译方法、模型与量化](topics/translation-models.md)（含四量化报告的附录清单）
- [翻译流程 v1–v8（H0 线）](topics/translation-flow-v1-v8.md)
- [Q 线 v9–v13](topics/q-line-v9-v13.md)
- [ASR 交叉合并、稳健性与专名一致性](topics/asr-robustness-and-names.md)
- [验收记录](topics/acceptance-records.md)
- [时间线](timeline.md)：逐日的裁定与轮次结论

## 决定与探索时间线

时间线原文已移到 [timeline.md](timeline.md)；本节只为旧链接保留锚点。

## 翻译后审校与人名／专名一致性（2026-10-19，已结题：ADR-0013）

条目已移到[子索引](topics/asr-robustness-and-names.md#翻译后审校与人名专名一致性2026-10-19已结题adr-0013)；本节只为旧链接保留锚点。
