# 当前 STT 基准线与组件边界

状态：两条基线均已采纳新Pyannote；显式运行入口及整片证据已具备，CLI旧默认参数与正式后端迁移另行实施  
最后更新：2026-10-05

## 当前基准线

用户在两部完整电影对照后再次明确确认以下组合，采纳记录见[ADR-0003](../adr/0003-new-pyannote-baselines.md)。
它更新[ADR-0001](../adr/0001-two-stt-baselines.md)的组件选择及[ADR-0002](../adr/0002-x0-demo-flow.md)的X0无VAD约束。
实际运行先读[标准基线测试指南](../guides/baseline-testing.md)。

| 组件 | W0 | X0 |
| --- | --- | --- |
| ASR | faster-whisper，现有large-v3 CUDA FP16起点 | 官方Qwen-ASR，现有Qwen3-ASR 1.7B CUDA BF16起点 |
| 降噪／人声分离 | 无／无 | 无／无 |
| VAD | 新Pyannote：segmentation-3.0 | 同一新Pyannote |
| 分段 | 原生语音检测后按源跨度切分合并，最多30秒，保留整数坐标及块内间隙 | 同一语音窗口契约，作为Qwen兼容的流程适配 |
| 解码 | 移植WhisperX逐块独立、无前文conditioning、无时间戳token的已核验路径 | Qwen逐块独立纯文字识别，无前文conditioning |
| 特征 | 保留已移植的Whisper波形补齐、Torch STFT／log-Mel及滤波器数值契约 | 保留Qwen原生processor／特征，不照搬Whisper固定Mel或补齐 |
| CTC对齐 | MMS-1b-all日语jpn adapter，GPU | 同一MMS实现，GPU |
| 对齐输入 | 每个识别块完整文字与对应原音频搜索窗 | 同一契约 |
| 说话人分离／标注 | 不启用 | 不启用 |
| 神经模型组件数 | 3：VAD、ASR、CTC | 3：VAD、ASR、CTC |

- **W0**：基础音频处理 → 新Pyannote及源跨度切分合并 → 移植的特征处理与faster-whisper独立无时间戳解码 → MMS CTC → 输出。
- **X0**：基础音频处理 → 新Pyannote及源跨度切分合并 → Qwen原生特征与独立纯文字识别 → MMS CTC → 输出。

“新Pyannote”固定为已测`pyannote.audio 4.0.7`＋`pyannote/segmentation-3.0`，revision
`e66f3d3b9eb0873085418a7b813d3b369bf160bb`；当前整片证据使用CUDA FP32。
ASR／CTC必须GPU执行；VAD仍按选型原则允许CPU或GPU，变更设备时单列运行身份。
两条均本地转写并保留原语言，不上传音频，不翻译。解码、下混、重采样和MMS输入归一化不属于降噪。
X0不使用Qwen3-ForcedAligner。

## WhisperX逻辑的采纳边界

W0必须承接WhisperX的有效切分合并、独立无时间戳解码和特征处理；这些是基线组成，不是可选优化。
已核验行为由自有适配层维护，不需要运行整个WhisperX框架，也不能把标准`transcribe()`视为保行为等价替换。
依据见[ASR审计](../research/2026-10-04-whisper-framework-asr-audit.md)及[VAD／对齐审计](../research/2026-10-04-whisper-framework-vad-alignment-audit.md)。

当前新Pyannote分段使用模型原生powerset转换、语音检测及`source-span-merge-v1`：超长语音区间按整数480000采样点切开，
相邻区间按源跨度贪心合并至最多30秒。块内间隙保留，不拼接不连续波形；这不是旧PyanNet迟滞／长段min-cut的逐项复制。
原生检测、源窗口策略与Whisper专属特征／解码分别记录，避免更换VAD后误称整套算法完全等价。

X0吸收适用于Qwen的检测后分段组织、同源有界窗口、独立识别、完整文字与MMS桥接等流程。
其已有原生纯文字解码和特征行为继续保留；不迁入Whisper token、固定Mel、CT2解码参数或强行30秒补齐。
`fixed30`和无VAD低能量`cut-merge`保留为历史／对照策略，不再定义最新X0基线。

## 执行入口、验证与迁移状态

持续迭代继续复用[W0 demo](../../experiments/w0_demo/README.md)与[X0 demo](../../experiments/x0_demo/README.md)，
共用`experiments/w0_demo/alignment.py`；新Pyannote适配器位于`vad_candidates.py`。
两套demo均已有显式导入冻结VAD manifest的入口。新基线运行须显式选新Pyannote，按对应README核对权重、设备、源窗口与配方身份。
本次只更新文档：W0 CLI省略参数仍选旧PyanNet，X0 CLI省略参数仍为fixed30。旧代码默认不代表当前已采纳组件；
默认参数迁移及正式后端尚待实现与回归。

[整片对照](../research/2026-10-05-fullfilm-segmentation-comparison.md)已完成两片239.22分钟、四组合八条链路，
使用上述canonical ASR／MMS适配器，模型按阶段驻留，普通分段失败后继续，提供完整与配对排除失败分析。
这项继续执行策略属于整片worker；不能据此宣称canonical X0 CLI已改变触顶即停止的策略。
整片证据支持本次选择，但不证明普遍识别优势或严格时间达标；极短窗MMS失败、时间长尾及覆盖限制保留。
原demo验证见[W0](../testing/2026-10-05-w0-demo-validation.md)／[X0](../testing/2026-10-05-x0-demo-validation.md)，
契约见[W0](../specs/w0-reusable-demo.md)／[X0](../specs/x0-reusable-demo.md)。

## 新旧ID的使用边界

| ID | 历史身份 | 当前采纳身份 |
| --- | --- | --- |
| W0 | 无VAD／CTC单模型；以及后来旧Pyannote＋MMS配方，按原报告区别 | faster-whisper＋WhisperX关键逻辑适配＋新Pyannote＋MMS |
| W1 | WhisperX＋Pyannote＋Jonatas或MMS变体 | 历史证据及回归参照，不作独立未来基线 |
| X0 | fixed30无VAD＋Jonatas或MMS；无VADcut-merge对照 | Qwen-ASR＋兼容流程适配＋新Pyannote＋MMS |

历史manifest、route值、结果目录、参数与分数保持原样，引用必须标明完整组合。
新运行另建身份并固定实际配置，不仅凭W0／X0名称继承旧分数或旧recipe。以下保留早期三候选背景。

## 历史三候选及其已测组件

**以下各节描述更新前的实验配置和当时的研究判断，不是未来W0／X0定义。**
用户此前在[两片主参考复核](../research/2026-10-04-two-film-revalidation.md)后，曾将前三条路线纳入候选：

| ID | 固定候选组合 | 保留理由 |
| --- | --- | --- |
| W1 | WhisperX large-v3＋归一化标准 CUDA CTC | 两片合并 CER 14.98%，半秒确定成功 320/590；当时时间研究的优先方向。 |
| W0 | faster-whisper large-v3，不使用前文 conditioning | 流水线简单；可测覆盖 377/590，保留为工程入口及基准。 |
| X0 | 官方 Qwen3-ASR 1.7B＋归一化标准 CUDA CTC | 半秒确定成功 304/590，与 W1 的不确定区间重叠；进入当时的候选集。 |

上述历史成功率使用完整参考分母，详细计分限制以原报告为准；三条均未达到严格字幕时间目标。
Q0（官方 Qwen＋原生 FA）和 Q1（Crisp＋FA）同样保留为历史路线。
更广泛的模型偏好和可探索范围仍遵循[选型原则](../development/inference-selection.md)。

### 历史配置实际包含哪些组件

下表描述本项目已测配置，不等于框架支持能力的全集。

| 组件 | W0：faster-whisper | W1：WhisperX＋CTC | X0：Qwen＋CTC |
| --- | --- | --- | --- |
| ASR 识别 | large-v3；CTranslate2，CUDA FP16，beam 5 | 同一 large-v3 家族；WhisperX 调用 faster-whisper／CTranslate2 | 官方 Qwen3-ASR-1.7B；Transformers，CUDA BF16、SDPA、greedy |
| 神经网络降噪／人声分离 | 无 | 无 | 无 |
| 独立 VAD（语音活动检测） | 未开启 | Pyannote VAD，在 GPU 上运行 | 无；使用固定 30 秒窗口 |
| 额外强制对齐模型 | 无；使用 Whisper 自身的词级时间机制 | 有：日语 wav2vec2 CTC 模型 | 有：与 W1 相同的日语 wav2vec2 CTC 模型 |
| CTC 输入归一化 | 无此阶段 | 有，按 checkpoint 的官方 feature extractor 处理每个对齐音频窗口 | 同 W1 |
| 强制对齐解码 | 无外部 CTC 解码 | TorchAudio 2.8 标准 CUDA CTC；取 nonblank token spans | 同 W1，通过 WhisperX 对齐适配层调用 |
| Qwen3-ForcedAligner-0.6B | 无 | 无 | 无；它属于 Q0，不是 X0 必需组件 |
| 说话人分离／标注 | 无 | 未启用 | 无 |
| 神经模型组件数 | 1：ASR | 3：VAD、ASR、CTC | 2：ASR、CTC |

三条都先做解码、下混和重采样，实验输入为 16 kHz 单声道；这些基础处理不等于降噪。均保留原语言，不包含翻译或 LLM 改写。字幕分句、显示时长和文件写出属于后续输出处理，也不额外引入神经模型。

流程可概括为：

- **W0**：音频预处理 → large-v3 识别及自身时间戳 → 字幕输出处理。
- **W1**：音频预处理 → Pyannote VAD 切分语音 → large-v3 识别 → 对齐音频归一化＋日语 CTC 模型＋标准 CTC 解码 → 字幕输出处理。
- **X0**：音频预处理 → 固定 30 秒窗口的 Qwen ASR → 文本与音频窗口桥接 → 同一套归一化 CTC 对齐 → 字幕输出处理。

W1 与 W0 共用 Whisper 模型家族，但分段与解码设置不同，不能把差异全部归因于对齐器。X0 仅借用 WhisperX 的对齐基础设施，不运行 Whisper ASR 或 Pyannote VAD。

针对长期自研底座，另有[同一 Pyannote／MMS 条件下的框架研究](../research/2026-10-04-whisper-framework-architecture.md)。
旧 W0／W1 即使后接相同 MMS，仍有不同文字、分段和搜索窗口，不能作为框架本身的公平对照。
新隔离原型区分标准 faster-whisper API 与保行为适配层；随后用户确认了本页顶部的未来基准线，历史质量结果不变。

### 历史配置中的 CTC、强制对齐、VAD 和降噪

**CTC** 是 Connectionist Temporal Classification，通常译为“连接时序分类”。它是一种处理长音频帧序列与较短文字序列之间对应关系的方法。模型为每帧给出字符／token 及 blank（空白标签）的概率；合并连续重复标签并去除 blank，可以得到文字。例如示意路径 `blank、你、你、blank、好、好` 对应“你好”。

本项目把 CTC 用于 **forced alignment（强制对齐）**：先由 Whisper 或 Qwen 产生文字，再把文字和原音频交给对齐阶段，寻找按顺序匹配这些文字的音频帧位置，得到时间戳。日语声学模型具体为 `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`；模型产生帧概率，CTC 解码算法寻找对齐路径。算法本身不是另一份神经模型。

可以按职责区分：ASR 回答“说了什么”；VAD 回答“哪些时段有人说话”；强制对齐回答“给定的这些字在什么时候说”；降噪尝试减弱背景噪声。VAD 不会消除语音段里面的音乐或噪声。CTC 对齐也不能凭空补回 ASR 漏掉的词，或保证纠正识别错误。

这里的“归一化”指对齐音频窗口的均值／方差归一化，以符合 checkpoint 预处理要求；不是文字规范化，也不是降噪。非空白 token 的声学时间跨度不能直接当作适合阅读的字幕显示时长。

### 历史配置的资源与工程代价

**W0 的流水线和部署最轻**：只有一个识别模型，不额外串联 VAD 或对齐网络。但 large-v3 自身仍是大模型，“轻”是相对于另外两条完整流程而言。

**W1 的模型组件最多**，需要维护 CTranslate2、PyTorch、Pyannote 和 CTC 对齐集成。VAD 可减少后续处理的非语音范围，因此组件更多不必然代表实际最慢。当前适配器在 ASR 阶段结束后释放识别实例，再加载 CTC 模型，不能简单相加各模型显存作为峰值。

**X0 的模型数量介于二者之间，但当前工程集成也较重**：Qwen 与 WhisperX 对齐阶段使用独立环境和进程，通过文件桥接；两个环境分别固定 Transformers 5.18.0 和 4.57.6。后续仍需维护输入身份、分窗、文本和时间坐标的一致性。候选能力不需要 Qwen 原生 FA：新推理入口调用 `--asr-only`，随后运行 CTC。

W1 与 X0 共享一项维护成本：实验固定使用 TorchAudio 2.8 的 `forced_align`；该接口已在 2.8 弃用，官方文档说明 2.9 移除。正式工程化前需要替换或维护这一边界，并重新验证时间语义。

资源比较应区分流程复杂度、墙钟耗时和峰值显存。本轮 12 个独立冷启动窗口共 60 分钟音频，W0 总墙钟约 334.4 秒，W1 约 374.4 秒。**X0 的 208.2 秒只有 CTC 阶段**，复用了 Q0 的 ASR 文字，不能拿它与前两者端到端耗时排序；Q0 还计算了 X0 不使用的原生 FA，也不能把 Q0 总耗时直接加上 X0 对齐耗时当成目标流水线成本。完整比较条件和采样显存局限见原报告。

### 历史实现和来源

后续[组件增量实验](../research/2026-10-04-component-augmentation-results.md)已评估分离、
独立 GPU VAD 和 W0＋日语 CTC。W0＋CTC 修复了父 segment 未覆盖自身 word 的搜索窗口契约，
取得明确半秒时间收益，但仍有覆盖取舍；本轮没有改变上述三条候选的定义或采用新后端。
随后按用户时间优先请求完成 [W0＋VAD＋CTC 叠加](../research/2026-10-04-w0-vad-ctc-follow-up.md)，
相对 W0＋CTC 没有增加全分母时间成功，虽有长尾收益但漏字更多；暂不默认叠加。

[日语 CTC 补充实测](../research/2026-10-04-japanese-ctc-results.md)进一步固定原 ASR 文字，
独立比较 Reazon、MMS 日语 adapter 与 hiragana。十二窗支持把 **W1／X0＋MMS、
X0＋Reazon 原生 token 无填充、W0＋hiragana** 作为补充候选；W1＋Reazon 填充版仅保留取舍。
MMS 严格半秒成功改善但仍有极端偏移；Reazon 需要原生多字 token 的整体时间，不能伪造逐字边界；
hiragana 需要读音转换和原文范围回映射。模型许可分别为 Apache-2.0、CC-BY-NC-4.0、
未明确（按 Reazon／MMS／hiragana 顺序）。这些是独立实验变体，不修改上表 W0／W1／X0 定义，
也不表示已决定采用新产品后端。新增入口位于 `experiments/japanese_ctc/`，模型获取与离线对齐分开。

- [Whisper／WhisperX 实验适配器](../../experiments/whisper/run.py)、[归一化](../../experiments/whisper/ctc_audio.py)、[标准 CTC 解码](../../experiments/whisper/ctc_forced.py)：组件开关与实际设备以这些固定实现及实验 manifest 为准。
- [X0 新推理入口](../../experiments/qwen/run_cross.py)、[Qwen ASR-only 实现](../../experiments/qwen/run_qwen.py)：区分真正新 ASR 流水线与本轮质量对比中的缓存复用。
- [TorchAudio 2.8 官方强制对齐教程](https://docs.pytorch.org/audio/2.8/tutorials/ctc_forced_alignment_api_tutorial.html)：帧概率、文本 token、对齐接口及弃用说明；访问日期 2026-10-04。教程示例的 MMS 模型不等于本项目实际使用的日语 checkpoint。
- [两片主参考结果](../research/2026-10-04-two-film-revalidation.md)：固定版本、质量与成本证据。本文的组件数量是实现事实，轻重判断是据此作出的工程分析，不是新的性能实测。
