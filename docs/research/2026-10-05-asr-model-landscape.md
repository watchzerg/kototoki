# 面向日语本地转写的 ASR 模型候选调研

状态：来源调研完成；候选建议，未采纳新模型、未安装或运行新推理  
最后更新：2026-10-05  
范围：原生 Windows、RTX 5080、GPU ASR、日语电影／动漫对白；兼顾多语言与未来流式需求。所有外部来源访问日期均为 2026-10-05。

## 结论及与当前基线的关系

ASR 远不止 Whisper 和 Qwen。它们是本项目已有实测和运行入口的两个家族，但当前开放权重候选还包括 NVIDIA、Cohere、IBM Granite、ReazonSpeech、SenseVoice／Fun-ASR、Meta Omnilingual 等。没有统一、跨语言和场景都成立的“主流前二”排名。

按[当前基线](../architecture/stt-candidate-pipelines.md)，W0／X0 已共享新 Pyannote、源跨度分窗、独立转写及 MMS 对齐；识别模型、模型原生特征和解码仍不同。因此可以将下一轮重点放到 ASR，固定其他组件后比较。但同一分窗不代表能共用 Whisper 特征、token、解码参数，模型替换仍需要各自的小适配器。

对本项目，建议首先增加 **Cohere Transcribe 2B、Granite Speech 4.1 2B、Nemotron 3.5 ASR 0.6B** 三个独立家族；随后比较 **Parakeet 日语 0.6B／ReazonSpeech NeMo v2**。已有 anime 微调资产可并行作为家族内低成本实验。SenseVoiceSmall／Fun-ASR-Nano 是值得保留的第二批候选。这个顺序是语言、工程路径与预期研究收益的综合判断，尚无本机质量结果支持优胜排序。

## 候选一览

“GPU 路径”表示官方接口／构建有证据；“本机未验证”表示没有本次 Windows＋5080 运行结果。参数量不是完整推理显存，许可证只按所列官方权重身份记录。

| 建议 | 精确 checkpoint／版本 | 日语及其他语言 | 权重许可 | GPU／Windows 证据与取舍 |
| --- | --- | --- | --- | --- |
| 第一批 | [`CohereLabs/cohere-transcribe-03-2026`](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)，2B | 日语在内 14 语言 | Apache-2.0；下载需接受共享联系信息的门控 | 原生 Transformers、BF16；官方有日语示例；Windows＋5080 未验证。适合纯文字 ASR 后接现有 MMS |
| 第一批 | [`ibm-granite/granite-speech-4.1-2b`](https://huggingface.co/ibm-granite/granite-speech-4.1-2b)，2026-04-29 | 英、法、德、西、葡、日 | Apache-2.0 | 官方 Transformers BF16 CUDA 路径、16 kHz 单声道；本机未验证；日语研究应选基础版 |
| 第一批 | [`nvidia/nemotron-3.5-asr-streaming-0.6b`](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)，v1 | 19 个可直接转写 locale 含 `ja-JP`，另 13 个广泛支持、8 个需适配 | OpenMDW-1.1 | 原生 Transformers；NeMo 卡的 OS 列表为 Linux／L4T，另有官方 C++ Windows CUDA／Vulkan 路线；本机未验证 |
| 第一／二批 | [`nvidia/parakeet-tdt_ctc-0.6b-ja`](https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja)，约 0.6B | 专用日语，带标点 | CC-BY-4.0 | 官方 NeMo、Hybrid TDT＋CTC；Windows checkpoint 运行需验证，不套用英语／欧洲语言 v3 的结论 |
| 第二批 | [`reazon-research/reazonspeech-nemo-v2`](https://huggingface.co/reazon-research/reazonspeech-nemo-v2)，619M | 专用日语，官方称支持数小时长音频 | Apache-2.0 | NeMo FastConformer RNN-T；有本地接口，Windows GPU 未验证；是新的 ASR 试验，不等于此前 Reazon CTC 对齐试验 |
| 第二批 | [`FunAudioLLM/Fun-ASR-Nano-2512`](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512)，800M | 中、英、日；31 语言属于另一个 MLT checkpoint | Apache-2.0 | 官方 FunASR `cuda:0` 路径；另有官方 Windows Blackwell CUDA／Vulkan runtime；本机未验证 |
| 第二批 | [`FunAudioLLM/SenseVoiceSmall`](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) | 普通话、粤语、英、日、韩 | FunASR 模型协议，不能用源码 MIT 代替权重条款 | 非自回归；官方 CUDA 接口和 Windows CUDA／Vulkan runtime；短音频直接接口与当前分窗较契合 |
| 家族内控制 | [`kotoba-tech/kotoba-whisper-v2.0`](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0)，日语蒸馏 Whisper | 日语 | Apache-2.0 | 官方 Transformers CUDA；属于 Whisper 家族。蒸馏主要吸引力是速度，不应因名字新就视为 large-v3 质量升级 |
| 观察 | Meta `omniASR_LLM_3B_v2`／`omniASR_CTC_7B_v2`，见[官方模型表](https://github.com/facebookresearch/omnilingual-asr) | 1600+ 语言；日语注册与条件参数需在实验准备时绑定源码 | Apache-2.0 | fairseq2 官方明确无原生 Windows 支持；不适合作为本项目第一批原生 Windows 试验 |
| 独立流程研究 | [`microsoft/VibeVoice-ASR`](https://huggingface.co/microsoft/VibeVoice-ASR)，约 9B | 官方称 50+ 语言 | MIT | 长音频、说话人和时间信息联合输出；BF16 权重及长上下文显存压力较高，本机未验证 |

## 第一批为什么值得试

**Cohere Transcribe** 是训练自独立 Conformer encoder／Transformer decoder 的专用 ASR，支持日语且官方直接提供 `language="ja"` 示例。官方推荐原生 Transformers 离线接口，要求 `transformers>=5.4.0`，测试使用 `torch==2.10.0`。它不提供自动语言识别、原生时间戳或说话人信息，静音可能幻觉；这些特征使其与现有 Pyannote＋MMS 职责边界较匹配。先固定日语和分窗，关闭隐式 CPU offload，记录实际 GPU 设备及失败。模型卡的版本字符串 `03-2026` 和论文引用短 revision 不替代下载时固定完整权重 SHA。[官方模型卡](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026)、[官方文档](https://docs.cohere.com/docs/transcribe)。

**Granite Speech 4.1 2B** 明确包含日语，支持名字／术语关键词偏置，适合测试动漫专名、口语和背景音场景。它沿用 4.0 的总参数规模，名称变化反映实际模型规模，不能把旧 `granite-4.0-1b-speech` 的“1B”与新“2B”解释为完整模型翻倍。优先基础版、原生 BF16；热词另立变体，避免用人工知道的参考答案给某个候选独占优势。[官方模型卡](https://huggingface.co/ibm-granite/granite-speech-4.1-2b)。

Granite 同家族的 **4.1 `plus` 和 `nar` 都只列英、法、德、西、葡五种语言，没有日语**。`plus` 的说话人／词级时间能力和 `nar` 的吞吐不能直接继承到基础版或日语。`nar` 官方还要求 FlashAttention 2、`transformers>=5.5.3`、`torch>=2.9.1`，并不是在本项目现有 Windows 环境换个权重就能公平比较。[plus 模型卡](https://huggingface.co/ibm-granite/granite-speech-4.1-2b-plus)、[NAR 模型卡](https://huggingface.co/ibm-granite/granite-speech-4.1-2b-nar)。

**Nemotron 3.5** 的重要性在于 NVIDIA 当前已有明确的日语支持及独立的原生 Transformers 推理路径。官方要求 `transformers>=5.13.0`；要显式选择 `ja-JP`，不能沿用默认 `en-US`。Streaming checkpoint 可以先评估按既定短窗输出纯文字的离线路径；缓存、连续流式延迟是另一个实验维度。其 40 locale 口径包括需适配语言，不能笼统宣称 40 语言开箱即用。[官方模型卡](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)。

NVIDIA 官方 [`NeMo-Speech.cpp`](https://github.com/NVIDIA/NeMo-Speech.cpp) 已列 Nemotron 支持及 Windows PowerShell、CUDA／Vulkan 构建说明。这提供了非 Python 的后续路线，但 `main` 文档能力与已发布 tag／二进制必须分别核验。先用原生 checkpoint 做质量比较，再研究转换及 GPU runtime，避免同时改变模型、精度和分段机制。

## 日语专用模型与现有动漫资产

**Parakeet 日语 0.6B** 是 Hybrid FastConformer TDT-CTC，以超过 35,000 小时 ReazonSpeech v2 日语语料训练；默认 TDT、可切 CTC。官方 CER 表包含 JSUT、Common Voice、TEDxJP，并不是动漫电影测试。值得与 Qwen／Whisper 形成架构不同的对照，也可独立比较 TDT 与 CTC 解码；本轮仍保持 MMS，不因为 ASR 模型带 CTC 就顺便替换对齐器。[官方模型卡](https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja)。

**ReazonSpeech NeMo v2** 为 619M RNN-T，日语专用且有长音频官方接口；与 Parakeet 共享 ReazonSpeech 数据来源，但模型与解码不同。两者都值得尝试，不过相似语料不构成完全独立的训练域证据。小型 [`reazonspeech-k2-v2`](https://huggingface.co/reazon-research/reazonspeech-k2-v2) 为 159.34M Zipformer RNN-T、约 30 秒输入，偏部署效率；质量优先时先测 NeMo v2，再考虑 k2／ONNX 路线。此前项目验证 Reazon CTC 时间对齐不等于验证这两个 ASR 模型。[NeMo 模型卡](https://huggingface.co/reazon-research/reazonspeech-nemo-v2)、[官方接口](https://github.com/reazon-research/ReazonSpeech/tree/master/pkg/nemo-asr)。

**Kotoba** 的 `v2.2` 主要在 `v2.0` 之上集成说话人和标点后处理，不能据小版本数字认定更强识别权重。当前固定分窗＋MMS 下更适合比较 v2.0 的 ASR 核心；整套 v2.2 pipeline 会额外引入分段／说话人模型，成为另一条流程。[v2.0](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0)、[v2.2](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.2)、[官方仓库](https://github.com/kotoba-tech/kotoba-whisper)。

本机已有 [`quantumcookie/anime-whisper-ct2-int8`](https://huggingface.co/quantumcookie/anime-whisper-ct2-int8/tree/7e132355e4f7f15640efe9bdebe13ee55fafe02e) 和 [`cstr/qwen3-asr-1.7b-ja-anime-GGUF`](https://huggingface.co/cstr/qwen3-asr-1.7b-ja-anime-GGUF/tree/1906c1f812b598d5e9dae091c79656d73b41ec28)，身份核验见[本机资产报告](2026-10-04-subtitle-edit-model-reuse.md)。这是领域微调＋转换／量化的组合，不是两个新模型家族，也不是纯精度对照。已有文件能降低获取成本，仍需核实兼容 GPU 引擎、上游微调来源及许可证；不能继承基础模型本机成绩。原偏好标签 `1.7b-amine-q8_0` 仅“最可能”对应 Qwen `ja-anime`，保留其歧义。

## 第二批与部署路线

**Fun-ASR-Nano-2512** 官方表明确中、英、日；另一个 [`FunAudioLLM/Fun-ASR-MLT-Nano-2512`](https://huggingface.co/FunAudioLLM/Fun-ASR-MLT-Nano-2512) 才是 31 语言变体。两者同为 800M，不能从整个产品系列宣传把所有功能移到同一权重。日语电影优先普通 Nano，显式语言与 ITN，输入原音频；歌词及 rap 能力是兴趣点，官方中英文／行业表不证明日语电影收益。更大的闭源 Fun-ASR 7.7B 不能作为本地可下载权重候选。[Nano 模型卡](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512)。

**SenseVoiceSmall** 是非自回归 ASR，包含情感／事件标签，日语必须以 Small 实际五语言口径评估，不能使用 SenseVoice 家族 Large 的 50+ 语言宣传。按现有 30 秒分窗直接推理、去掉非转写标签，保留原始输出供审计；长音频官方自动 VAD 组合不要偷偷替换现有新 Pyannote。权重采用 FunASR 模型协议，源码为 MIT；官方许可说明允许按协议商用，仍有归属和模型命名要求。[官方模型卡](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)、[维护者许可与接口说明](https://github.com/QwenAudio/SenseVoice/blob/main/README.md)。

FunASR 当前官方 runtime **`runtime-llamacpp-v0.2.6`** 提供 Windows Vulkan、CUDA、Blackwell CUDA 包，覆盖 SenseVoiceSmall／Fun-ASR-Nano 的 GGUF 路线。这是比“PyTorch 理论可运行”更具体的 Windows GPU 发布证据，但没有本机测过，也不等于所有 tensor／全部 ASR 都已 GPU 执行。配置时强制 ASR GPU、记录实际 backend，禁用静默 CPU fallback；量化与 FP16 另立身份。[官方 README](https://github.com/modelscope/FunASR/blob/main/README.md?plain=1)、[runtime 发布](https://github.com/modelscope/FunASR/releases/tag/runtime-llamacpp-v0.2.6)。

## 保留观察及非日语候选

**Meta Omnilingual ASR** 已有 2025-12 的 v2 CTC／LLM／Unlimited 家族，支持 1600+ 语言。官方 A100、BF16、batch=1、30 秒表中，LLM 7B 约 17 GiB、LLM 3B 约 10 GiB；这些不是 RTX 5080 测量。`7B` 不应因权重算术接近 16 GB 就宣称可稳跑。本项目若要研究，应先验证最大可行 CTC 或 3B LLM，而不是默认最小模型。[官方模型表](https://github.com/facebookresearch/omnilingual-asr)。

更直接的限制是依赖 **fairseq2 官方明确不支持原生 Windows，建议 WSL2**。Omnilingual README 的跨平台文字及 libsndfile 提示不足以覆盖该底层限制。遵守当前原生 Windows 目标，先保持观察；WSL／第三方移植属于另行明确的环境实验。[fairseq2 官方安装说明](https://github.com/facebookresearch/fairseq2#installing-on-windows)。

**VibeVoice-ASR** 关注长音频、多说话人和时间信息；官方标准 checkpoint 约 9B，不能泛称“7B 可装进 5080”。按 9B×2 字节估算，BF16 仅权重已约 18 GB，激活及缓存还会增加；这个估算只说明 16 GB 单卡全量驻留存在明显门槛。量化、`VibeVoice-ASR-HF` 等变体需要独立核验。本项目可作为未来联合流程观察项，先做资源资格，不与固定30秒纯文字＋MMS的单变量试验混排。[官方模型卡](https://huggingface.co/microsoft/VibeVoice-ASR)、[官方仓库](https://github.com/microsoft/VibeVoice)。

| 模型 | 为什么当前日语试验优先级低 |
| --- | --- |
| [`nvidia/parakeet-tdt-0.6b-v3`](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | 25 种欧洲语言，不含日语；应关注专用 `-ja` 或 Nemotron |
| [`nvidia/canary-1b-v2`](https://huggingface.co/nvidia/canary-1b-v2)／[`canary-qwen-2.5b`](https://huggingface.co/nvidia/canary-qwen-2.5b) | 前者25种欧洲语言，后者英语专用；Canary-Qwen 与 Qwen3-ASR 是不同权重和训练任务。均 CC-BY-4.0 |
| [`ibm-granite/granite-speech-5.0-470m-turboctc-nc`](https://huggingface.co/ibm-granite/granite-speech-5.0-470m-turboctc-nc) | 2026-08-25 的更新款为英语；此 `-nc` 权重 CC-BY-NC-SA-4.0。更新发布日期不代表替代日语4.1基础版 |
| [`FireRedTeam/FireRedASR2-AED`](https://huggingface.co/FireRedTeam/FireRedASR2-AED)／[`FireRedASR2-LLM`](https://huggingface.co/FireRedTeam/FireRedASR2-LLM) | 官方 ASR 支持中文方言、英语、混语，未列日语；VAD／LID 的100+语言不能转移给ASR。源码 Apache-2.0，具体权重许可需按下载卡再核对。[官方范围](https://github.com/FireRedTeam/FireRedASR2S) |
| [`bosonai/higgs-audio-v3-stt`](https://huggingface.co/bosonai/higgs-audio-v3-stt) | 官方英语 checkpoint；组合 Whisper encoder 与 Qwen LLM 不自动获得两者原有所有语言 |

## 公平试验及结论边界

1. **先资格、后质量**：冻结实际 stable runtime、完整 checkpoint revision、预处理、语言、生成上限、精度和 GPU 证据。先确认原生 Windows 能加载并完整 GPU 推理，无 CPU fallback，再进入同音频比较。上表不是已冻结下载清单。
2. **固定非 ASR 组件**：新 Pyannote manifest、源窗口、整数坐标、原音频及同一 MMS 保持一致；模型使用原生特征与独立纯文字模式。各模型 token 上限不能机械照搬，明确触顶与重复生成失败。
3. **优先质量足量模型**：基础 checkpoint FP16／BF16 优先；模型、CTC 按阶段驻留，实测峰值。量化、不同 runtime、hotword、原生长音频／流式另立身份，不把综合变更归因于 ASR 权重。
4. **既有口径覆盖同一失败分母**：按[评测方法](../testing/stt-evaluation.md)及[素材规范](../testing/fatestay-reference.md)比较 II／III 原版日文字幕主参考。保留漏字、幻觉、专名、重复、静音、覆盖、MMS失败、时间长尾和端到端成本；不只报告成功片段 CER。
5. **原生时间另立研究**：Parakeet／Nemotron／VibeVoice 自带时间信息的能力可以后测，但本轮先用共同 MMS；ASR 更低 CER 不自动意味着字幕时间更好，错误文字仍可能被强制对齐。

Open ASR 的英语 WER、厂商 FLEURS／Common Voice 日语指标、A100／H100／H200 的 RTFx、batch=128 吞吐，以及“全球语言平均最好”等指标都只能帮助挑候选。语言、规范化、背景音、说话方式、字幕参考一致性及批量规模不同，不能据此推导 Kototoki 日语电影的排名或5080速度。此调研没有运行新音频推理，没有建立新的质量、显存、延迟或跨模型优势事实。
