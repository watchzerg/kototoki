# kototoki

以 Python 和本地 AI 模型为主的自托管 Speech-to-Text 项目，当前目标是本地音频转写。
本地 STT demo 及 II／III 两片主参考复核已完成；基准线已确认，W0／X0均有持续迭代的demo入口，正式后端迁移尚未完成。

当前采用两条未来基准线，均无降噪、无人声分离，保留日语原文；ASR 与 CTC 在本地 GPU 上推理，VAD 可选 CPU 或 GPU：

**后续模型或session测试当前基线，先读[W0／X0标准基线测试指南](docs/guides/baseline-testing.md)**，再使用其中链接的demo、契约与验证记录。

2026-10-05，用户在[两片239.22分钟整片对照](docs/research/2026-10-05-fullfilm-segmentation-comparison.md)后确认最新基线，
采纳记录见[ADR-0003](docs/adr/0003-new-pyannote-baselines.md)：

- **W0**：faster-whisper＋新Pyannote VAD＋MMS日语CTC；必须保留WhisperX切分合并、独立无时间戳解码和特征处理等已核验逻辑的适配。
- **X0**：Qwen-ASR＋新Pyannote VAD＋同一MMS日语CTC；吸收Qwen兼容的WhisperX流程思想，保留原生processor、特征与独立纯文字识别。

两条均无降噪、无人声分离。“新Pyannote”为已测`segmentation-3.0`，不指旧PyanNet。
新模型原生检测后的源跨度切分合并保留整数坐标与块内间隙；X0不照搬Whisper专属特征或token。
本次更新采纳定义与文档；当前CLI省略参数仍会选择旧W0或fixed30 X0，运行最新基线须按指南显式提供新Pyannote manifest。

此前[十组合采样对照](docs/research/2026-10-05-vad-baseline-comparison.md)、
[CPU／GPU补测](docs/research/2026-10-05-pyannote-gpu-comparison.md)及整片研究保留各自配方、失败与结论。
旧Pyannote、X0 fixed30及无VAD cut-merge作为历史／对照路线保留。当前基线的采纳不改写历史分数。

[第一批 ASR 候选整片实测](docs/research/2026-10-05-asr-candidates-fullfilm.md)已完成 Cohere Transcribe 2B、
Granite Speech 4.1 2B 基础版、Nemotron 3.5 ASR 0.6B 与新运行 W0／X0 的两片比较。
三个候选均未超过本轮 W0／X0 的文字成绩，未更换基线；复现入口见[候选实验](experiments/asr_candidates/README.md)。

完整定义与新旧ID边界见[当前基准线](docs/architecture/stt-candidate-pipelines.md)，最新采纳范围见[ADR-0003](docs/adr/0003-new-pyannote-baselines.md)。
WhisperX 不再作为未来独立基准线，历史 W1 保留为回归参照。
[Whisper 框架研究](docs/research/2026-10-04-whisper-framework-architecture.md)支持保行为适配方向；标准 API 不能直接视为等价替换。

**W0 后续开发复用并更新 [`experiments/w0_demo/`](experiments/w0_demo/README.md)**：已分离可替换 VAD、保行为 ASR、独立 MMS 和运行入口。
替换 VAD 或优化流程先读[契约](docs/specs/w0-reusable-demo.md)，按[验证记录](docs/testing/2026-10-05-w0-demo-validation.md)回归；旧实验保留作历史参照。

**X0 后续开发复用并更新 [`experiments/x0_demo/`](experiments/x0_demo/README.md)**：新基线显式使用新Pyannote；CLI的fixed30旧默认及保留全部音频的cut-merge仍可用于对照；
单命令连接Qwen与共用MMS，保留Qwen原生特征和逐块独立纯文字识别。先读[契约](docs/specs/x0-reusable-demo.md)，
运行与修改按[验证记录](docs/testing/2026-10-05-x0-demo-validation.md)回归。
原有流程适配原则见[ADR-0002](docs/adr/0002-x0-demo-flow.md)，VAD选择以新ADR为准；
此前[隔离研究](docs/research/2026-10-05-x0-whisperx-flow.md)及其VAD分支保留历史身份，不将旧实验结果直接归给新Pyannote基线。

历史[两片主参考复核](docs/research/2026-10-04-two-film-revalidation.md)覆盖五条旧路线、两片共60分钟、590条参考；
[组件增量](docs/research/2026-10-04-component-augmentation-results.md)、[W0＋VAD＋CTC追加](docs/research/2026-10-04-w0-vad-ctc-follow-up.md)
及[日语CTC补充](docs/research/2026-10-04-japanese-ctc-results.md)保留当时配置与结论。
这些报告的 W0／W1／X0 指历史身份，不能把旧成绩或资源消耗直接归给新基准线。
尚无路线达到严格字幕时间目标；[首轮整片与重复证据](docs/research/2026-10-04-stt-demo-conclusions.md)保留历史身份，
当前组合的整片证据见上述2026-10-05对照报告，正式后端验收仍另行进行。

项目约定见[文档索引](docs/INDEX.md)。从 `subtitle-edit-fix` 整理的既有调研见
[STT 流水线研究入口](docs/research/2026-10-03-stt-pipeline-design.md)；候选和设计建议
不代表已经实现的能力；已采纳的基准线定义以决策记录为准。

后续模型评估优先使用 **Heaven’s Feel II 和 III** 的原版内嵌日文字幕作为精确参考；
Heaven’s Feel I 的双语提取字幕可信度较低，Black Panther 的日语配音/字幕可信度最低，
两者只作补充参照，不混入主参考排名。具体路径、来源和保护规则见[评估素材](docs/testing/fatestay-reference.md)。
识别直接读取 `D:/movie/` 各影片目录已分离的日语音频（Fate 为 `.jpn.flac`，
Black Panther 为 `.jpn.eac3`），无需再次从视频提取。字幕显示时间仍不等于词级声学真值。
既有单片实验保留原冻结身份和分数；两片主参考复核使用独立冻结轮次，未重新调参。

当前的[本地 STT demo 实测与选型方案](docs/plans/local-stt-demo-selection.md)以实测时
最新官方文档为基准，对比 Whisper 和 Qwen 路线。配套[评估标准](docs/testing/subtitle-timing-benchmark.md)
分别评价文字识别、同内容时间同步和字幕显示，合理合句或拆句不直接影响主识别分数。
[第一轮数值规则](docs/testing/evaluation-config-v1.md)已在验证前冻结。执行状态和可恢复入口见
[实验运行记录](docs/context/2026-10-04-demo-execution.md)；环境准备不等于真实推理或质量达标。

最小工具链已建立：`uv sync --locked`，`just test` 执行离线评测、适配器、显示及汇总测试，
`just check` 检查 Python 语法。各后端使用独立环境，模型获取与离线推理分开。
所有模型、私有音频、完整转写及运行日志存于 Git 忽略的 `.local/`。

## 独立字幕翻译实验

[翻译模式有界筛选报告](docs/research/2026-10-07-hy30-flow-optimization-results.md)保留第一轮局部筛选结果；没有证明1-5-1最优或主要方向充分收敛。正在执行用户选择的[第二轮C档计划](docs/plans/hy-mt2-translation-flow-exploration-v2.md)：96筛选＋48独立确认、资源宽松的自适应批次探索。源样本、参考与判定规则已冻结，当前执行多seed筛选、完整96窗扩展和协议／记忆资格验证；独立确认尚未开始，探索尚未收敛，见[新台账](docs/context/2026-10-08-hy30-flow-exploration-v2.md)。原[计划](docs/plans/hy-mt2-translation-mode-optimization.md)与[历史台账](docs/context/2026-10-07-hy30-flow-exploration.md)保留冻结范围、结果和复现路径。

2026-10-08用户随后明确更新配置基线为`official30b-cached-v1`：官方30B采样（temperature0.7、top_p1、禁用top_k、重复惩罚1）、输出4096、缓存开启，总context8192。使用`just translation-baseline`；决定见[ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md)，检查见[新配置验证](docs/testing/2026-10-08-official30b-cached-baseline-validation.md)。前述报告保留当轮结论。

当前已采纳 **Hy-MT2 30B-A3B APEX-I-Compact**（`hy-mt2-30b-a3b-apex-i-compact`）作为字幕翻译基线；后续优化讨论与回归以[ADR-0005](docs/adr/0005-apex-i-compact-translation-baseline.md)为准，使用[基线 demo 命令](experiments/translation_demo/README.md)。此前 Q3_K_M 采纳决定与固定对照身份保留于[ADR-0004](docs/adr/0004-hy-mt2-translation-baseline.md)。

三家族、五个本地量化版本的 demo 和完整固定 test 已完成，见[中文比较报告](docs/research/2026-10-06-translation-model-comparison-results.md)与[运行入口](experiments/translation_demo/README.md)。
这是独立实验，未接入当前 STT 产品流程。质量比较保留映射不可评、裁决未决及证据限制；复现入口随报告提供。

此前[Hy30 Q3／Q4 对照](docs/research/2026-10-06-hy30-q3-q4-comparison-results.md)已完成：官方 Q4 部分 offload 的三轮中位耗时为 Q3 的 4.18 倍，未证明稳定的全面质量优势；用户当时确认保留 Q3 基线。报告包含样本时间范围及两小时电影耗时预算，估算与实测分开记录。

[四种 Hy30 量化的大规模实测](docs/research/2026-10-07-hy30-four-quantization-results.md)已完成旧 83 窗口、新增 1,200 个双轮复核窗口的全量评估、四轮耗时和四款正式 30 分钟稳定性测试。该轮冻结对照 Q3_K_M 每轮同窗失败，失败成本与有效速度分开报告；APEX 的小幅质量信号及 i1-Q3_K_L 的耗时波动、显存限制见报告。用户在报告交付后明确采纳 APEX-I-Compact；原报告和附录仍保留交付时的结论与旧 Q3_K_M 统计基线，新决定由 ADR-0005 记录。[复现入口](docs/research/2026-10-07-hy30-four-quantization-results-appendices/reproduction.md)与[执行记录](docs/context/2026-10-06-hy30-four-execution.md)保留命令和证据；工具见[语料与参考复核](experiments/translation_corpus/README.md)、[串行比较运行器](experiments/translation_four_quantization/README.md)。
