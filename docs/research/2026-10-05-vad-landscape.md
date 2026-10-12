# VAD 选型与 W0／X0 分片改进调研

状态：探索性研究；保留当时候选排序与改进建议，后续采用另见 ADR-0003  
最后更新：2026-10-05  
范围：原生 Windows／RTX 5080、本地日语电影转写；只读上游研究，无模型安装或新推理。

2026-10-05 后续采用：用户已明确两条基线均使用新 Pyannote＋MMS，见[ADR-0003](../adr/0003-new-pyannote-baselines.md)及[当前架构](../architecture/stt-candidate-pipelines.md)。W0 继续要求 faster-whisper 与 WhisperX 切分合并、独立无时间戳解码和特征处理；X0 仅采用兼容 Qwen 的流程并保留原生特征。均无降噪和人声分离。canonical demo 的旧 W0／fixed30 X0 执行默认仍待迁移。本文研究时的排序与身份保留，不能替代后续采用决定。

## 研究时的结论与边界

W0 的 Pyannote 检测与后处理、X0 的固定 30 秒切分都有研究空间，但不能将“换一个 VAD”视为必然改善。
建议优先比较 **现有 Pyannote、Silero、FireRedVAD 离线版**；分别代表已有行为基准、成熟轻量生态、新的多语言事件检测路线。
对 X0，先研究 **保留全部音频、在长度上限附近借助低能量或 VAD 得分选择断点**，再研究删除非语音段。
这是验证优先级，不是已经证明的质量排名。用户在本轮明确放宽 VAD 设备条件：
CPU／GPU 均可，质量、稳定性、集成成本和端到端性能决定选择；ASR／CTC 继续使用 GPU。
因此 OmniVAD 的 CPU 部署可与官方 FireRed 实现比较，TEN 也不因缺少 GPU 路径被排除。
用户同时明确：对白检测为主要目标，检测并保留歌声是次要加分，保留歌声本身不扣分。

本研究开始时的基准线依据[ADR-0001](../adr/0001-two-stt-baselines.md)，以下为历史身份，后续定义已由 ADR-0003 更新：

- W0：faster-whisper＋移植 WhisperX 的切分合并、独立无时间戳解码和特征处理＋Pyannote VAD＋MMS 日语 CTC。
- X0：Qwen-ASR＋MMS 日语 CTC，无 VAD、固定 30 秒分片。
- 均无降噪、无人声分离；本研究不修改默认配置、不升级环境，也不把历史实验成绩转移给新组合。

详细来源核查分为[成熟方案](2026-10-05-established-vad-sources.md)和[FireRed／Omni／TEN](2026-10-05-emerging-vad-sources.md)。
本文综合这些核查和仓库历史证据；各来源访问日期均为 2026-10-05。网页 main 与发布包可能不一致，实验前须冻结实际版本及权重 revision。

## 先分清四个问题

| 层次 | 回答的问题 | 对本项目的作用 |
| --- | --- | --- |
| 声学 VAD | 每帧或短时窗有没有语音／人声？ | 提供得分或活动区间；不能单独决定识别块长度。 |
| 分段后处理 | 怎样处理短暂停顿、弱语音、长段与前后留白？ | 阈值、迟滞、最短时长、padding、min-cut、合并共同影响保留内容。 |
| ASR 分片 | 给识别器哪些完整音频窗口？ | 可以完全不删音频，只移动断点；也可以跳过非语音或拼接语音，两者风险不同。 |
| 话轮结束检测 | 这个人是不是说完一句／一轮话？ | 依赖声学韵律或语义；主要服务实时对话，不是逐帧 VAD 的直接替代。 |

WhisperX 的价值已经包含后处理与分片，不应在换检测网络时一起丢弃。
W0 迁移先保证旧行为等价，之后另立实验修改算法。[本地 VAD 审计](2026-10-04-whisper-framework-vad-alignment-audit.md)
记录了迟滞、长段低分切分、源跨度合并和时间坐标契约。

“固定 30 秒”是本项目 X0 的实验／基准策略，不是所有 Qwen 使用方式的硬限制。
[官方 Qwen3-ASR SDK 源码](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/utils.py)
包含长音频切块及在目标边界附近寻找低能量位置的逻辑；其当前 ASR 与原生 ForcedAligner 的分块常量不同。
X0 使用 MMS，不应把原生 Qwen aligner 的长度常量套到 MMS 上，也不应据此直接把 X0 改成长块。

## 候选全景与工程定位

“主流”在这里表示持续维护、被实际语音工具集成或有成熟研究／部署生态，不是统一市场占有率排名。
“现代、优雅”主要看职责清晰、可返回帧得分、后处理可配置、离线可复现及部署成本，不以模型更新年份或参数量单独决定。

| 方案 | 背景与特点 | 对 Kototoki 的判断 |
| --- | --- | --- |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Silero 团队／snakers4 与社区；轻量神经 VAD，PyTorch／ONNX，广泛用于语音应用。 | 优先候选；官方 CPU ONNX 路径可直接纳入研究，不必为 GPU 专门适配。 |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) | Hervé Bredin 等研究者与 pyannote 团队；语音分段、重叠语音和 diarization 生态。 | 保留既有 checkpoint 作为基准。框架新版本、segmentation 新模型和 Community-1 diarization 管线不是同一件事。 |
| [FireRedVAD](https://github.com/FireRedTeam/FireRedVAD) | 小红书 FireRedTeam；DFSMN，离线／流式／多标签 AED 三类模型；约 0.6M 参数。 | 最值得加入的新候选，尤其离线版本；不能把作者榜单视为日语电影已胜出。 |
| [OmniVAD-Kit](https://github.com/lifeiteng/OmniVAD-Kit) | FeiTeng Li／社区维护的跨平台工具包；使用 FireRedVAD 模型，提供多语言绑定和原生／浏览器部署。 | FireRed 的实用部署候选，不是另一套独立声学模型；需验证转换数值、后处理和 Windows 实际表现。 |
| [TEN VAD](https://github.com/ten-framework/ten-vad) | TEN／Agora 生态；轻量低延迟，适合实时交互与端侧。 | 可纳入候选；离线电影不以极低延迟为首要目标，附加许可条件仍需考虑。 |
| [FunASR FSMN-VAD](https://github.com/modelscope/FunASR) | 阿里／ModelScope、FunASR 维护者；工业语音工具链中的轻量 FSMN 检测，流式／离线分段。 | 成熟备选；中文模型身份与英文模型须区分，日语质量需要实测，工具包多语言 ASR 支持不能直接转移给 VAD。 |
| [NeMo MarbleNet／Frame VAD](https://huggingface.co/nvidia/Frame_VAD_Multilingual_MarbleNet_v2.0) | NVIDIA；卷积式帧级检测、GPU 训练与推理生态。 | 有 GPU 研究价值，但官方模型卡 Linux 支持与语言范围不直接覆盖原生 Windows 日语目标，集成成本较高。 |
| [SpeechBrain VAD](https://huggingface.co/speechbrain/vad-crdnn-libriparty) | SpeechBrain 学术社区；CRDNN、训练 recipe 和可组合后处理。 | 研究／微调备选；LibriParty 模型不是日语电影专用，多一套框架的收益尚无证据。 |
| [WebRTC VAD](https://github.com/wiseman/py-webrtcvad) | WebRTC 传统算法，Python wrapper 为独立社区项目；固定短帧、侵略性等级、CPU 路线。 | 经典轻量对照；不会因 CPU 被排除，但没有日语复杂电影优于首选神经模型的证据。 |
| [Brouhaha](https://github.com/marianne-m/brouhaha-vad) | Lavechin、Métais 等的 2023 多任务研究；同时估计 VAD、SNR 与混响 C50。 | 更适合分析声学条件；不是本轮最小替换方案。未核实持续模型发布节奏。 |
| [Picovoice Cobra](https://github.com/Picovoice/cobra) | Picovoice 的端侧 VAD SDK，需 AccessKey。 | 不进入首轮；现有接口与分发方式不比无需账户的开放模型路线更贴合本项目。 |

另外，[sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 和
[DakeQQ 的 ONNX VAD 项目](https://github.com/DakeQQ/Voice-Activity-Detection-VAD-ONNX)
是部署／转换层，不应与其承载的 Silero、TEN、FireRed、MarbleNet 重复计为独立模型。
框架支持 CUDA 不证明每个 VAD 实际运行在 GPU；应记录实际 execution provider 和设备，避免错误归因性能。

[Smart Turn](https://github.com/pipecat-ai/smart-turn) 和
[LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/)
代表较新的话轮结束检测方向，官方均有日语支持说明，但预测的是发言是否结束。
它们与轻量 VAD 配合，不是为离线电影提供逐帧语音覆盖的直接替换；本项目当前没有必要因此引入语义模型或实时服务。

## 两个特别容易误读的细节

版本与更新节奏需同时看软件和权重。核验到 Silero 6.2.3（2026-09-23）、pyannote.audio 4.0.7（2026-06-30）、
FunASR 1.4.16（2026-09-18）、NeMo Speech 3.0.0（2026-08-07）、SpeechBrain 1.1.1（2026-08-27）；
这些工具持续维护，不意味着其 VAD 权重同步重训。
FireRedVAD 独立仓库于 2026-03-03 公开，PyPI 0.0.2 于 03-09 发布，当前 main 最近提交为 05-06；
OmniVAD-Kit PyPI 0.2.13 于 06-30 发布，main 最近提交为 09-23；两者 PyPI 标注 Beta，未发现正式 GitHub Release 序列。
TEN 的 v1.0／v1.0-ONNX 发布于 2025-07-11，当前 main 最近提交为 2026-02-02。
具体多次发布日期、资产 revision 和来源见两份详细核查。这些是可观察历史，不是维护者承诺每月更新。

GPU 路径也应单独看：Silero 官方普通 ONNX loader 强制 CPU，GPU 实验应采用经验证的 CUDA JIT 或明确 provider 的实现；
[OmniVAD 原生实现](https://github.com/lifeiteng/OmniVAD-Kit/blob/main/native/src/omnivad.cpp)明确设置 `use_vulkan_compute=false`，
不能从底层 ncnn 有 Vulkan 能力推导现成工具已使用 GPU。这些是部署事实，按用户新要求不构成排除条件。
TEN 的 [LICENSE](https://github.com/ten-framework/ten-vad/blob/main/LICENSE)在 Apache-2.0 基础上包含额外 Agora 竞争限制，
不能仅按仓库徽章当作无附加条件的 Apache-2.0。

### FireRed 合并说话与歌声符合用户偏好

[技术报告 §4.1](https://arxiv.org/html/2603.10420v1#S4.SS1) 将普通 VAD 的正类定义为 **speech ∪ singing**。
另一个 AED／mVAD 模型才分别输出 speech、singing、music 的概率，且标签可以同时存在。
因此普通 FireRed VAD 会保留歌声，这符合用户在本轮明确的偏好：重点是说话，唱歌检测是锦上添花，
不因为保留歌声而扣分。没有必要仅为区分歌声新增 AED；AED 可作为分析对白与音乐重叠的可选研究工具。
也不能因为检测到 music 就删掉同时存在的对白。事件分类不改造波形，因此不等于降噪或人声分离。

### 新项目自称 SOTA 与另一家的测评可以同时不矛盾

| 作者自测 | 公开结果摘要 | 能说明什么 |
| --- | --- | --- |
| [FireRed 的 FLEURS-VAD-102](https://github.com/FireRedTeam/FireRedVAD#evaluation) | FireRed F1 97.57%，Silero 95.95%；表内还有 TEN／FunASR／WebRTC。 | 支持 FireRed 是强候选；这是跨语言朗读数据衍生评测，不能推导电影／动画质量。 |
| [Silero 的多领域验证](https://github.com/snakers4/silero-vad/wiki/Quality-Metrics) | Multi-Domain AUC：Silero v6 0.97，FireRed 离线 0.94，FireRed 流式与 TEN 各 0.93。 | 在另一数据与方法下排名反转；并非同一次公平复验。 |

两组的语料、标签、版本、阈值和指标不同，均为模型作者提供的证据，不能合并成总榜。
FLEURS-VAD-102 的 README 在本次读取时仍称标注集即将开源；本轮未取得可复跑的该标注集。
需要区分漏检与误报：降低误报可能增加漏字；总 F1 高不能保证轻声和短促回应不被裁掉。

## 日语相关性

VAD 通常不生成词或字，也通常不要求设置日语 tokenizer；但“无需语言参数”不等于“所有语言和声音条件效果一致”。
训练语料的语言／口音覆盖、声音强度、说话方式及正类定义均会影响结果。
[Silero](https://github.com/snakers4/silero-vad) 声称覆盖超过 6000 种语言；
[FireRed](https://github.com/FireRedTeam/FireRedVAD) 给出 102 语言综合评测。
本次没有找到能将所有首选候选放在同一日语电影／动画集上的独立、可复现比较。

以下是针对本项目提出的测试场景，不是已证明某款模型必然失败的结论：

- 轻声、耳语、尾音渐弱、无声化或低能量音节附近的起止边界。
- 很短的「はい」「うん」「えっ」及喘息式台词，检验最短语音长度门槛。
- 动画高音、尖叫、哭泣、低沉声、远处对白、多人重叠。
- 配乐、爆炸与对白共存；片尾歌曲、吟唱和纯器乐。
- 句中停顿与跨 30 秒边界的连续发言。

其中高音角色与类人声乐器不是纯粹推测：
[Silero v6 发布说明](https://github.com/snakers4/silero-vad/releases/tag/v6.0)
明确保留了这两类已知问题。其余场景应通过独立声学标注及下游识别结果验证，不以语言名称替代测试。

## W0 的改进路径

当前实现入口是 [W0 可复用 demo](../../experiments/w0_demo/README.md)，已完成移植及[两窗独立回归](../testing/2026-10-05-w0-demo-validation.md)。
后续 session 实现本文实验时，复用并更新该 demo 的 `vad.py`／Adapter，保持 ASR、MMS 与 runner 共用；不重建另一套流水线。

1. 以已冻结的 `w0-pyannote-mms-v1` 为参照，核对原 checkpoint、阈值、min-cut、merge、特征和解码参数；扩大样本或改变行为时另建身份。
2. 在同一检测网络上研究后处理：边界留白、迟滞、短停顿合并、最大块长及长段切点。不要一次改变全部开关。
3. 再换成 Silero 或 FireRed 得分，保持共同的分片政策；各模型分数未必同标定，不能机械复制 0.5 阈值。
4. 将默认参数的即用比较与经过等量调参预算的比较分开。必要时按相近语音召回／保留时长比较。

“共同后处理”需处理不同帧步长、时间参考点、流式状态和 padding，而不是只把返回区间换个格式。
保留原始 scores 和原始采样坐标，有助于区分模型差异与分片差异。
不能为换 VAD 同时重新启用 faster-whisper 原生过滤、静音拼接或另一解码路径，然后将全部收益归因于检测器。

## X0 的改进路径

后续已建立[X0 demo](../../experiments/x0_demo/README.md)：默认fixed30，正式支持保留全部音频的独立cut-merge配方；
后续测试按[标准基线测试指南](../guides/baseline-testing.md)执行。用户在该次流程采用时明确不移植VAD；再后续的新 Pyannote 采用见 ADR-0003，不改变历史 cut-merge 身份。
下表保留当时的研究分支；两种VAD方案仍是独立研究建议，不是X0 demo现有组件或必须执行的下一步。
历史三臂数据见[X0流程研究](2026-10-05-x0-whisperx-flow.md)，新cut-merge不继承历史energy分数。

原建议比较如下三个独立变体；均保留 X0 原样作为参照：

| 变体 | 做法 | 主要要回答的问题 |
| --- | --- | --- |
| 只改善断点 | 在预定长度上限之前的有限范围内寻找低能量位置，所有音频连续覆盖。 | 无新模型也能减少切在词中的情况吗？配乐场景中低能量是否失效？ |
| VAD 辅助断点 | 使用语音得分寻找较安全切点，不因低得分删除任何片段。 | 语音检测是否比纯能量更懂对白边界？额外成本有无回报？ |
| VAD 过滤＋合并 | 跳过高置信非语音；保留语音前后上下文，按源跨度组成有界识别块。 | 节省无对白识别和减少幻觉能否抵消漏字、上下文损失及复杂度？ |

第一轮可保持不超过 30 秒以隔离切点因素；找不到合适切点就保留有界强制切分。
这不是要求所有 VAD 都必须运行 30 秒，也不是断言 Qwen 只能处理 30 秒。
后续若研究重叠窗口，需要独立验证去重与 MMS 时间对应，不能先简单重复拼接转写。

保持全部音频的策略仍可能改变 ASR 输出，不保证质量不降；它的优势是避免由 VAD 漏检直接删除源音频。
MMS 使用与实际 ASR 块对应的原音频搜索窗口。若将不连续语音拼成一块，必须保留逐段映射，
不能只加一个起点偏移恢复原片时间；本轮优先保留连续原音频窗口以控制复杂度。

## 本地已有反例与后续验证

[历史 W0＋VAD＋CTC 追加](2026-10-04-w0-vad-ctc-follow-up.md)中，旧 W0＋CTC 与旧 W0＋VAD＋CTC 相比：
严格半秒成功 306→302／590，漏字 274→322；部分时间长尾改善但没有整体成功增益。
这不是当前新 W0 的成绩，也不能证明 Pyannote 网络本身是漏字原因；检测、窗口变化和识别上下文都可能贡献。
旧 X0 的 VAD 筛查也未显示稳定收益，见[组件结果](2026-10-04-component-augmentation-results.md)。

该旧 X0 四窗比较中 CER 18.98%→19.13%，漏字 127→141，半秒成功均为 90／193。
旧 W0 的诊断将 111 个新增漏字按原 word 时间分为裁剪外 47、跨边界 6、裁剪内 58，支持同时检查裁剪与识别上下文，
但原 word 时间本身并非人工真值。旧组件实验已有 200 ms 上下文扩展，“加一点 padding”不是从未尝试的万能解法。

日语专项方向还有 [ReazonSpeech 的 CTC 分片实现](https://github.com/reazon-research/ReazonSpeech/blob/master/pkg/espnet-asr/src/ctc.py)：
其 ESPnet 路线利用自身 CTC blank 连续区间辅助选切点，区别于一个独立的“Reazon VAD”模型。
将类似思想用于 MMS 是更后面的研究假设；blank 也会出现在语音内部，不能等同静音，更不能直接据此删除音频。

下轮应冻结模型／后处理／分片三个身份，并使用同一音频、ASR、MMS 和评价规则：

- 声学层：漏掉的语音时长、误保留的非语音时长、语音起止误差、短促台词召回；需要人工声学小样本，不能将 SRT 显示边界直接当 VAD 真值。
- 转写层：日语 CER，并拆开漏字、多字、替换，尤其统计切点附近错误；对白与有可靠参考的歌词分别报告，避免把字幕未收录的真实歌词误计为 VAD 假阳性或 ASR 幻觉。
- 对齐层：完整参考分母的内容／有效时间覆盖、严格时间成功和严重偏移，不能只报各自幸存子集 P99。
- 工程层：原生 Windows 实际设备执行、整条链墙钟、CPU／内存与显存成本、短块数量、加载成本及离线复现；ASR／CTC 仍需真 GPU 证据。
- 调参只用开发集；现有两片窗口已经多轮使用，不能重新命名为盲测。后续独立素材应单独冻结。

以上是后续试验建议，未执行。VAD 的 CPU／GPU 例外以[选型原则](../development/inference-selection.md)为权威，
AGENTS 只保留简短例外以避免全局 GPU-only 误用；README、架构和 ADR 已同步设备边界，组件组合与分片策略不变。
VAD 声学评价以对白召回为首要、歌声召回为次要；歌声保留不计非人声误报。此偏好未定义数值权重，
不回写历史冻结分数；后续实验应在运行前声明标签及参考覆盖范围。
