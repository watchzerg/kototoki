# 研究索引

状态：current（研究轮次的登记页与规则入口）

## 规则

规则的权威是 [ADR-0031](../docs/adr/0031-research-layout-and-lightweight-records.md)，这里只列执行要点：

- **一轮一目录（R1）**：研究的计划、代码、结论放在 `research/<YYYY-MM>-<slug>/`，立项时在下面的[轮次登记](#轮次登记)加一行。产品验收记录放 [acceptance/](acceptance/)，一次一篇。
- **必填项（R2）**：README 按 [TEMPLATE.md](TEMPLATE.md) 填写；正文约 150 行以内。
- **不写进记录（R3）**：文件或样本的哈希（git commit SHA 除外）、本机绝对路径、逐窗或逐条明细与大段日志、字幕或转写原文（短例外）、执行台账与接跑步骤。
- **冻结靠 git（R4）**：结题把状态写成 `concluded`／`stopped`；修错、修链接、精简随时可以做。原始材料从归档 tag `archive/2026-11-18-pre-research-restructure` 或 git 历史取。代码不对文档做 sha256 自检。
- **依赖方向（R5）**：产品永不导入 `research/`；研究可以导入产品。研究数据经仓库根 `data.toml`（逻辑名 → 相对数据根的路径）与环境变量 `KOTOTOKI_DATA` 定位，第一个需要数据的新轮次建立该文件。跨轮复用的工具第二个使用者出现时才在本目录下建 `_lib/`。
- **规则移植（R6）**：研究结论进产品后，产品实现是唯一权威，后续研究直接调用产品实现；需要钉住的取值在 `tests/core` 里以字面量钉。
- 采纳的结论写成 ADR（[记录新决定](../docs/adr/INDEX.md#记录新决定)）；现行规则看 [CURRENT.md](../docs/adr/CURRENT.md)，不从轮次记录推断。

## 研究方法约束

- 翻译只有一条基线 **Q3**，新测试以它为对照；引用 Q2、Q1、Q0、F1、H0 时写明（[CURRENT·翻译基线 Q3](../docs/adr/CURRENT.md#翻译基线-q3)）。新的翻译对比、裁判与统计口径按[翻译评估方法](../docs/agents/translation-evaluation.md)。
- 不自动选用"翻译多次再挑选"类方法（[ADR-0008](../docs/adr/0008-no-multi-translation-selection.md)）。
- 已结题的研究线不重开，重开只由用户明确要求；专名一致性研究线不提议新轮次（[CURRENT·专名](../docs/adr/CURRENT.md#专名)）。
- 确认集一经开封不再用于确认：v3、v4、v5 的确认集已开封，新的确认用全新隔离的集合。
- 翻译流程第二轮（v2）已停止，作业不恢复，只取 v1／v2 的教训作先验（[flow-v1-v4](2026-10-translation-flow-v1-v4/README.md#教训)）。
- 轮次分两步：先在交互会话里和用户讨论方向，把计划写进轮次目录（问题、各臂的对照与终点、门、GPU 与裁判预算、停止条件、不做的事、待裁定），并附一段可粘贴到新 session 的执行提示词（写明 GPU 与裁判授权、预算、无人值守规则、提交方式）；执行者在新 session 里无人值守跑完，需要用户拍板的事集中写进待裁定，不中途询问。计划就是执行者的全部上下文，门、预算与不做的事必须写死。
- 门只设给必须无人值守判定的臂。便宜的臂（约 1–2 次 GPU 运行）只报数（带 S／D／I 与代价），不写死通过阈值，进不进由用户看数字裁定；安全网与守卫类改动按"零误报＋拦住已知翻车"判，不按平均 CER 降幅（用户 2026-11-10 对 v14 的裁定）。
- 判定规则在看结果前冻结：主终点、非劣界、按作品分层的窗口 bootstrap、对照与候选同期同包重判；同 seed 输出不可复现，配对比较要带 A/A 噪声底（口径见[翻译评估方法](../docs/agents/translation-evaluation.md)）。

## 遗留路径

`kototoki/` 有些注释写着"复制自 `experiments/…`"：这些路径指归档 tag `archive/2026-11-18-pre-research-restructure`，本次不改产品代码，下次因其他原因改到这些文件时顺手更新（[ADR-0031](../docs/adr/0031-research-layout-and-lightweight-records.md)）。

## 按主题的现状

| 主题 | 现状 | 轮次 | 权威 |
| --- | --- | --- | --- |
| STT 基线与组件 | W0、X0 两条基线已采纳；分离、额外 VAD 放弃，MMS 日语 CTC 为共用对齐器 | [stt-landscape](2026-10-stt-landscape/README.md)、[stt-demo-w0-x0](2026-10-stt-demo-w0-x0/README.md)、[components-and-ctc](2026-10-components-and-ctc/README.md)、[x0-whisperx-flow](2026-10-x0-whisperx-flow/README.md) | [ADR-0003](../docs/adr/0003-new-pyannote-baselines.md) |
| VAD 与分段 | 两路统一用新 Pyannote，比较已结束 | [vad-comparison](2026-10-vad-comparison/README.md) | [ADR-0003](../docs/adr/0003-new-pyannote-baselines.md) |
| ASR 模型候选 | 换 ASR 模型这条线由用户裁定停止，重开前提是出现新的、许可清楚的日语 ASR 模型 | [asr-candidates](2026-10-asr-candidates/README.md) | [CURRENT·STT](../docs/adr/CURRENT.md#stt-基线与产品-stt) |
| cue 规则 | 引入 ASR token 边界的方案调研后不实现 | [cue-token-boundary](2026-10-cue-token-boundary/README.md) | [技术设计](../docs/specs/bilingual-subtitle-pipeline.md) |
| 两路 ASR 交叉合并 | Whisper 交叉打分作可选引擎 `cross` 进产品，默认仍 w0 | [cross-asr-judge](2026-10-cross-asr-judge/README.md) | [ADR-0012](../docs/adr/0012-cross-asr-judge.md) |
| ASR 稳健性 | v14、v15 已结题，只有整窗复读守卫进产品，后扩展为三条规则 | [asr-robustness-v14-v15](2026-11-asr-robustness-v14-v15/README.md) | [ADR-0023](../docs/adr/0023-asr-repeat-guard.md)、[ADR-0030](../docs/adr/0030-asr-window-plausibility-guard.md) |
| 专名一致性 | 研究线已结题，重开只由用户明确要求；产品只建表并注入 | [name-consistency](2026-10-name-consistency/README.md)、[strata-v12-v13](2026-11-strata-v12-v13/README.md) | [ADR-0014](../docs/adr/0014-name-consistency-in-product.md)、[ADR-0022](../docs/adr/0022-product-names-on-strata.md) |
| 翻译模型与量化（H0） | 历史选型；H0 已不是基线 | [translation-model-selection](2026-10-translation-model-selection/README.md) | [ADR-0005](../docs/adr/0005-apex-i-compact-translation-baseline.md) |
| 翻译流程（H0 线 v1–v8） | 已结题；切包规则沿用到现行基线，"翻译多次再挑选"已放弃，语序重排线已关闭 | [flow-v1-v4](2026-10-translation-flow-v1-v4/README.md)、[quality-v5](2026-10-quality-v5/README.md)、[batching-v6-v8](2026-10-batching-v6-v8/README.md) | [ADR-0010](../docs/adr/0010-dp10-cut-translation-flow-baseline.md)、[ADR-0008](../docs/adr/0008-no-multi-translation-selection.md) |
| 通用模型翻译（Q 线 v9–v13） | 已结题，现行唯一基线是 Q3 | [q-line-v9-v11](2026-10-q-line-v9-v11/README.md)、[strata-v12-v13](2026-11-strata-v12-v13/README.md) | [ADR-0021](../docs/adr/0021-q3-strata-names-baseline.md) |

## 轮次登记

状态取值：`active`、`concluded`（已结题）、`stopped`（中止）。一句话只写去向，数字看各轮 README。

| 目录 | 时间 | 状态 | 一句话 |
| --- | --- | --- | --- |
| [2026-10-stt-landscape](2026-10-stt-landscape/README.md) | 2026-10-03 – 10-04 | concluded | 来源调研与环境、资产核验，无推理；形成后端契约与资产版本等设计先验 |
| [2026-10-stt-demo-w0-x0](2026-10-stt-demo-w0-x0/README.md) | 2026-10-03 – 10-05 | concluded | 多路线实测与框架等价实验，无配置达严格时间目标；采纳 W0、X0 两条基线 |
| [2026-10-components-and-ctc](2026-10-components-and-ctc/README.md) | 2026-10-04 – 10-05 | concluded | 分离与 VAD 叠加放弃，MMS 日语 CTC 成为共用对齐器 |
| [2026-10-vad-comparison](2026-10-vad-comparison/README.md) | 2026-10-05 | concluded | 新 VAD 未晋级，整片对照后两路统一用新 Pyannote |
| [2026-10-asr-candidates](2026-10-asr-candidates/README.md) | 2026-10-05（附 11-18 测量） | concluded | Cohere、Nemotron、Granite 未超过 W0／X0；`no_speech_prob` 规则不进产品 |
| [2026-10-x0-whisperx-flow](2026-10-x0-whisperx-flow/README.md) | 2026-10-05 | concluded | X0 吸收 WhisperX 切点无无回归赢家，后改用新 Pyannote |
| [2026-10-translation-model-selection](2026-10-translation-model-selection/README.md) | 2026-10-05 – 10-08 | concluded | 五候选与四量化后采纳 Hy-MT2 30B APEX-I-Compact（H0） |
| [2026-10-translation-flow-v1-v4](2026-10-translation-flow-v1-v4/README.md) | 2026-10-07 – 10-11 | concluded（v2 stopped） | 没有配方全面通过确认；`b10-joint` 按工程理由采纳，多样本挑选放弃 |
| [2026-10-cue-token-boundary](2026-10-cue-token-boundary/README.md) | 2026-10-15 | concluded | token 边界映射收益极小，不实现 |
| [2026-10-quality-v5](2026-10-quality-v5/README.md) | 2026-10-16 | concluded | 错误约 76% 来自 ASR；两侧无可采纳改动，多样本挑选放弃 |
| [2026-10-batching-v6-v8](2026-10-batching-v6-v8/README.md) | 2026-10-16 – 10-18 | concluded | 分批与语序重排无可复现收益；`dp10-cut` 按离线模拟与用户裁定采纳 |
| [2026-10-cross-asr-judge](2026-10-cross-asr-judge/README.md) | 2026-10-19 | concluded | 交叉打分裁判进产品作可选引擎 `cross` |
| [2026-10-name-consistency](2026-10-name-consistency/README.md) | 2026-10-19 | concluded | 专名 1–6 轮，研究线结题并进产品 `names` 阶段 |
| [2026-10-q-line-v9-v11](2026-10-q-line-v9-v11/README.md) | 2026-10-21 – 10-23 | concluded | 通用模型直接翻译产生 Q0，加 high 专名注入产生 Q1 |
| [2026-11-strata-v12-v13](2026-11-strata-v12-v13/README.md) | 2026-11-08 – 11-09 | concluded | Strata Flash-Next 翻译产生 Q2，再加 Strata 建表产生 Q3 |
| [2026-11-asr-robustness-v14-v15](2026-11-asr-robustness-v14-v15/README.md) | 2026-11-09 – 11-11 | concluded | 只有整窗复读守卫进产品 |

## 验收记录

产品验收一次一篇，在 [acceptance/](acceptance/) 下。

| 记录 | 对象 | 结论 |
| --- | --- | --- |
| [2026-10-14](acceptance/2026-10-14-bilingual-pipeline-fullfilm.md) | 两部整片 × w0／x0 | 通过（显存阈值临时下调） |
| [2026-10-15](acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md) | 最终验收 | 失败路径通过；soxr 重采样拖累 CER |
| [2026-10-16](acceptance/2026-10-16-bilingual-pipeline-swr-regression.md) | 改回 swr 重采样 | 通过，w0 与基线逐条一致 |
| [2026-10-19](acceptance/2026-10-19-cross-asr-acceptance.md) | `cross` 引擎 | 差 0.05 pp 未达线，用户仍采纳 |
| [2026-10-19](acceptance/2026-10-19-cross-coresidency-probe.md) | Whisper 与 Qwen 同进程共驻 | 通过 |
| [2026-10-19](acceptance/2026-10-19-ffmpeg-9.0-upgrade.md) | ffmpeg 9.0 升级 | 通过，派生 PCM 逐字节一致 |
| [2026-10-20](acceptance/2026-10-20-name-consistency-product.md) | 产品专名一致性 | 通过（替换后由 ADR-0019 移出） |
| [2026-11-12](acceptance/2026-11-12-product-fullflow-acceptance.md) | 产品全流程 | 通过 |
