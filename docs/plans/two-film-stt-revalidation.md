# 两片主参考的固定候选复核

> 2026-10-05 后续开发入口：本文保留五条旧配置的十二窗复核。当前W0／X0使用[标准基线测试指南](../guides/baseline-testing.md)中的demo并新建运行身份；两套demo的已测范围分别见其验证记录，不能继承本文十二窗成绩。

状态：已完成；下文保留评分前冻结方案，结果见[两片复核报告](../research/2026-10-04-two-film-revalidation.md)  
最后更新：2026-10-04  
范围：按更新后的 II/III 主参考，检验首轮两条建议是否仍成立。

执行结果：12窗共590条、6544字符，84阶段全部完成；仍优先 W1 时间研究与 W0 工程入口，X0 保留为接近的研究对照。原始素材哈希未变，未调整候选参数。原始执行前方案另存 `.local/round2/preexecution-plan.md`。

## 变更与范围

用户要求重新比较[首轮结论](../research/2026-10-04-stt-demo-conclusions.md)中的候选。
[素材规范](../testing/fatestay-reference.md)改变了主参考与输入方式，没有新增数值门槛。
本轮保留五条既有配置、模型和依赖版本，只改变冻结输入，避免把升级收益混入语料影响。
沿用[第一轮规则](../testing/evaluation-config-v1.md)的文字规范化、完整分母、Pareto 轴及角色排序；
不重新调参，不宣称沿用的研究目标已经成为产品验收标准。

| 路线 | 固定配置 |
| --- | --- |
| W0 | faster-whisper large-v3，FP16、beam5、无前文、无 VAD、原生温度 fallback、词时间 |
| W1 | WhisperX large-v3 原生 Pyannote VAD/ASR，checkpoint 归一化和 TorchAudio 2.8 CUDA 标准 CTC |
| Q0 | 官方 Qwen ASR 1.7B＋FA 0.6B，BF16、SDPA、greedy、30 秒窗、4096 token |
| Q1 | Crisp 0.8.41，Qwen/FA f16、Vulkan0、无 VAD、原生能量门与分窗，显式 FA |
| X0 | 同轮 Q0 完整 ASR 文字及其输入窗，交给归一化标准 CTC；如生成失败则保留失败与文字 |

模型 revision 和后端环境见[固定清单](../research/2026-10-04-runtime-inventory.md)。本轮不下载或替换权重。
2026-10-04 重新访问了 [faster-whisper 1.2.1](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)、
[WhisperX 3.8.6](https://github.com/m-bain/whisperX/releases/tag/v3.8.6)、
[Qwen HF 模型卡](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf)及
[Crisp 0.8.41](https://github.com/CrispStrobe/CrispASR/releases/tag/v0.8.41)。
这是原冻结配置的复核，不据此宣称所有组件仍为全局最新版。

## 输入冻结与证据边界

在查看新候选输出前，按每部影片总时长的 5%、20%、35%、50%、65%、80% 位置开始，
各取 300 秒，共 12 窗、60 分钟。起点按 PCM 样本取整；最终精确区间以私有 manifest 为准。
区间不由字幕边界决定，不随候选成绩改变。两片分别评价后按参考字符数合并 CER，
按参考跨度数合并时间成功率；I/Black Panther 不进入主排名。

现有 FLAC 只读解码为 16 kHz mono PCM16，再按样本裁剪，不重新提取 MKV。
保存源音频、源 SRT、PCM、区间、代码与配置身份；评估前后检查当前 SRT SHA256。
私有输入和结果位于 `.local/round2/`、`.local/results/r2-*/`，不改历史实验。

所有与窗口相交的参考文字及原始边界保留。跨窗口边缘的字幕单列不确定性，
不能把音频外的文字记作已确认模型漏识别，也不能按候选时间裁掉插入。
主表保留完整输出，并给出固定边缘敏感性及受影响字符数。
原始 SRT 的时间差不等于声学发声误差，独立人工声学标注仍未完成。

II 与历史影片的身份需用实际 PCM 进一步核验；已有整片结果意味着该片不能算未见测试。
III 也有媒体核验中的三段 W0 抽查。此轮是无调参的分散窗口复核，不是随机抽样、
全片评价或新的独立保留集；不把 12 个窗口或重复推理当作 12 部独立影片。

## 验证与结论规则

GPU 任务串行；ASR、VAD 和对齐分别核对实际执行设备及离线配置。Q1/X0 组件复用明确登记，
不能把只计 FA 的耗时当作端到端速度。运行失败和生成触顶保留在完整分母，保存已识别文字。

逐片及合并报告 CER、S/D/I、覆盖率、失败类别、success(0.5/2/5) 上下界，
条件 P95/P99 和联合完整性时间指标。共同可测子集只作辅助解释。
成组 bootstrap 仅在合并 12 窗上报告，并注明两片相关性与非随机抽样限制；
每片只有六窗，不制造逐片置信区间。

先验证评测器、语料时间映射、参考哈希保护和失败记账，再执行真实推理。
如新结果改变短名单，应据新证据修订建议；若差异受匹配/参考不确定性影响，保留不确定结论。
新晋级路线需要补充整片/稳定性证据，不能借用旧入围路线的运行成功替代验证。
