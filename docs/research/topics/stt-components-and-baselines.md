# STT 组件、基线与 ASR 候选

状态：current（子索引；条目是登记时的摘要，结论以报告正文与[决定索引](../../adr/INDEX.md)为准）

条目格式：`[主题](文件.md)：一句话结论；适用条件或限制`。条目文字自[调研索引](../INDEX.md) 2026-11-11 拆分时原样搬来，新报告在对应小节追加一条。

## STT 组件与基线（2026-10-03 至 2026-10-04）

- [模型与后端候选](../2026-10-03-model-backend-candidates.md)：继承自相邻调研的本地 STT 候选短名单；exploratory，未采用任何后端或模型
- [Whisper 与 Qwen 后端契约](../2026-10-03-stt-backend-contracts.md)：推理、对齐、文本单元与时间行为的版本绑定观察；绑定当时版本，未验证
- [STT pipeline 设计参考](../2026-10-03-stt-pipeline-design.md)：迁入的本地转写流水线设计调研；不是已采纳架构
- [STT 应用对照](../2026-10-03-stt-application-comparison.md)：三个相邻应用快照的本地 STT 与时间路径对照；历史比较已结束，实现建议仍属探索
- [时间戳失败案例](../2026-10-03-timestamp-failure-cases.md)：相邻项目有界时间调查中观察到的失败机制与工程教训；对 Kototoki 的补救措施未验证
- [Whisper demo 就绪度](../2026-10-03-whisper-demo-readiness.md)：faster-whisper large-v3 与 WhisperX 日语对齐的源码核查；原生 GPU 执行当时未验证
- [Qwen 与 Crisp demo 就绪度](../2026-10-03-qwen-crisp-demo-readiness.md)：官方 Qwen3-ASR／ForcedAligner 与 CrispASR 在原生 Windows＋RTX 5080 上的来源评审；无本地推理
- [第一轮固定验证结果](../2026-10-04-validation-results.md)：验证章 03/14/23 的六配置完整实测并锁定保留候选；严格时间目标均未达标，不含保留测试
- [开发集对比](../2026-10-04-dev-comparison.md)：开发五章 13 种配置的验证前观察，跨家族 X0 经官方 CTC 归一化后 0.5 秒确定成功约 49%；均未达严格时间目标，不等于生产推荐
- [固定保留测试结果](../2026-10-04-heldout-results.md)：五条预锁路线在 N=620 的描述性结果，W1 确定成功率最高、W0 覆盖最高；五条均未达时间目标，缺人工声学真值
- [整片质量与连续性](../2026-10-04-fullfilm-results.md)：W0／W1 各一次完整 7,028 秒整片推理，CER 约 20% 且几乎相同；同片诊断，均未达时间目标
- [最终性能与重复性](../2026-10-04-final-performance.md)：两条路线各三次 chapter07 新推理加一次整片，文字与 timed units 的 SHA 完全一致；只证明重复稳定，不证明识别正确
- [实测结论与实施顺序](../2026-10-04-stt-demo-conclusions.md)：保留 W0 与 W1 两个方向，尚无配置达到严格时间目标；首轮成绩与单片冻结输入绑定，不替代已采纳的 W0／X0 基线
- [开发／验证／保留集字幕显示分析](../2026-10-04-display-analysis.md)：CPU 显示回放核算 SRT 覆盖与短／长 cue；声学同步和人工可读性未验证
- [数字静音预检](../2026-10-04-silence-preflight.md)：10 秒全零输入下 W0、Q0 仍产生少量文字，W1 与 Crisp 原生 VAD 输出空；单一合成输入，不代表真实静音稳健性
- [Whisper 执行准备](../2026-10-04-whisper-execution.md)：W0／W1 环境、适配器与离线合成测试的执行基线；探索中，不构成正式选型
- [Whisper 后续实现边界](../2026-10-04-whisper-engineering-boundaries.md)：W0、W1 与标准 CTC 分支的工程交接与约束；仅用开发证据，无后端采用决定
- [Qwen 执行准备](../2026-10-04-qwen-execution.md)：官方 Qwen native HF 的源码、冻结环境与 CUDA 推理核查；历史 Q0 记录，当前 X0 以 X0 demo 为准
- [Crisp 执行准备](../2026-10-04-crisp-execution.md)：CrispASR 0.8.41 在原生 Windows 的两种受控流程实测，GPU 可复现；字幕时间未达标
- [W0 与标准 CTC 的有界探索](../2026-10-04-w0-ctc-exploration.md)：保留 W0 文字、换用日语 CTC 官方归一化与 forced spans 的锁定后探索；新增单一配置，不能放回原盲测排行榜，不宣称胜出
- [两片主参考复核结果](../2026-10-04-two-film-revalidation.md)：II／III 新主参考上五条固定路线复核，保留原实验建议与分数；均未达到严格时间目标
- [模型资产获取记录](../2026-10-04-model-assets.md)：七组模型与配套文件已通过内容身份核验；只证明资产就绪，不代表推理或质量通过
- [Subtitle Edit 模型复用](../2026-10-04-subtitle-edit-model-reuse.md)：优先复用 Subtitle Edit 已下载资产的本地核验；未新增推理、不改变首轮结论
- [环境与复现清单](../2026-10-04-runtime-inventory.md)：原生 Windows 的锁定版本、模型、安装包与恢复入口只读清点；质量结论见各实验报告

## Whisper 框架与 W0／X0 流程（2026-10-04 至 2026-10-05）

- [Whisper 框架架构选择](../2026-10-04-whisper-framework-architecture.md)：推荐 faster-whisper＋保行为适配，含维护成本、反证与迁移门槛；不代表正式采用
- [Whisper 冻结 VAD 等价实验](../2026-10-04-whisper-framework-experiment.md)：两窗 17 块适配层 ASR 严格一致、46 项 VAD 后处理一致，标准 API 不等价；MMS 复用输入契约证据，未重跑
- [Whisper ASR 源码核验](../2026-10-04-whisper-framework-asr-audit.md)：三种生成路径、有效参数、特征处理及安装源码完整性；绑定所核查版本
- [Whisper VAD／MMS 边界核验](../2026-10-04-whisper-framework-vad-alignment-audit.md)：原始 VAD 分数到窗口、MMS 自研替换点及残留框架职责
- [X0／WhisperX 源码核查](../2026-10-05-x0-whisperx-source-audit.md)：可跨模型的策略、已有等价行为、Whisper 专属逻辑及旧入口 CTC 身份差异
- [X0 吸收 WhisperX 流程](../2026-10-05-x0-whisperx-flow.md)：历史两窗三臂 GPU 验证，energy 与 VAD 均有取舍；流程设计采用见 ADR-0002，新 demo 的 cut-merge 不继承 energy 分数

## ASR 候选与评测素材（2026-10-05）

- [ASR 模型全景与候选优先级](../2026-10-05-asr-model-landscape.md)：面向日语、本地 Windows／RTX 5080 的官方来源调研与验证门槛；未改变 W0／X0 基线
- [第一批 ASR 两片整片实测](../2026-10-05-asr-candidates-fullfilm.md)：五路线十次运行，Cohere／Nemotron 更快但 CER 落后，Granite 多次重复触顶；保留 W0／X0
- [日语长音频与对应文本来源](../2026-10-05-japanese-longform-asr-sources.md)：公开有声书、播客、长篇语料与会议录像的入口、长度与参考质量；来源调研，未下载或纳入正式评测
- [YODAS2 日语元数据与选样](../2026-10-05-yodas2-japanese-selection.md)：两子集 32,899 条时长实查、字幕质量陷阱与按包获取方案；后续选定国会讨论
- [国会讨论 W0／X0 整段实测](../2026-10-05-parliament-baselines.md)：YODAS2 国会讨论 10,843 秒各一次完整推理；字幕准确度未知，结果仅作参考，X0 附加时间评分中止，不混入电影排名、不据此换基线
