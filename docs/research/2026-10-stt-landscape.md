# STT 早期调研：候选模型、应用与后端契约

## 状态
concluded：纯来源调研与环境／资产准备，没有新推理；结论被后续 W0／X0 实测轮次取代，仅保留作失败案例与接口先验。

## 时间
2026-10-03 至 2026-10-04。

## 问题
在原生 Windows＋RTX 5080 上做本地日语转写前，需要弄清：有哪些模型与后端可选、既有开源应用（Subtitle Edit、VideoLingo、pyvideotrans）如何组织识别与时间戳、时间戳为什么会出错，以及首轮 demo 需要哪些模型资产与运行环境。

## 策略
- 读上游源码与官方文档，把"模型 checkpoint、运行时、量化转换、对齐器、应用 writer"拆成相互独立的选择维度。
- 对三个应用快照对比识别、窗口、对齐与字幕后处理的职责划分，提炼可复用的失败案例。
- 固定上游契约版本，记录 Whisper／faster-whisper／WhisperX／Qwen3-ASR 的时间戳来源与默认值差异。
- 盘点首轮 demo 的七组模型资产与四套运行环境，核验字节身份，并登记 Subtitle Edit 已下载的可复用权重。

## 环境与版本
- 纯阅读与 CPU 只读清点；没有加载模型、没有 GPU 推理。
- 上游契约调研固定的修订（短 SHA）：OpenAI Whisper 86098128、faster-whisper 7b99be53、WhisperX 771b4a14、Qwen3-ASR 7c6daf77。这些是证据引用，不是 Kototoki 依赖选择。
- 首轮 demo 登记的七组模型（模型 repo @ 短 revision）：Systran/faster-whisper-large-v3 @ edaa852e；Qwen/Qwen3-ASR-1.7B-hf @ bcd2b5b7；Qwen/Qwen3-ForcedAligner-0.6B-hf @ c07281df；jonatasgrosman/wav2vec2-large-xlsr-53-japanese @ cf031e02；cstr/qwen3-asr-1.7b-GGUF（f16）@ 674df5d4；cstr/qwen3-forced-aligner-0.6b-GGUF（f16）@ 1ec51106；ggml-org/whisper-vad（Silero v6.2.0）@ 9ffd54a1。七组合计约 16.8 GB。
- 首轮实际锁定的运行栈：W0 为 faster-whisper 1.2.1＋CTranslate2 4.8.2（CUDA DLL 来自 Torch 2.8.0+cu128 wheel）；WhisperX 环境为 WhisperX 3.8.6＋Torch/torchaudio 2.8.0+cu128＋Transformers 4.57.6＋pyannote-audio 4.0.7；Qwen 环境为 Torch 2.14.1+cu130＋Transformers 5.18.0＋nagisa 0.3.0；Crisp 为 CrispASR 0.8.41（Windows Vulkan 构建）。根环境 Python 3.12，GPU RTX 5080。
- 清点结果：三套 Python 环境的已安装包与各自锁文件逐项一致，无缺失、无额外包。

## 测试
- 来源与源码审阅，没有 CER 或时间指标。历史失败案例取自兄弟项目对 Subtitle Edit 5.2.0＋Crisp 0.8.32 的因果诊断，使用日语电影媒体与人工编辑的中文 ASS 参考，只支持"显示时间比较"，不是日文真值。
- 资产核验：每个权重文件的大小与 SHA256 同上游 LFS／Git blob 身份比对（具体哈希不在本记录列出）。Subtitle Edit 目录中找到并核验 14 个 STT／对齐主权重，合计约 33.2 GB，全部与发布仓库固定 revision 一致，只读复用，未复制未改写。

## 结果
| 项目 | 观察 |
| --- | --- |
| 时间戳来源 | Whisper 段落为约 20 ms 网格的解码时间戳；faster-whisper 词时间来自 CTranslate2 交叉注意力对齐，不是独立 CTC；WhisperX 用独立 CTC 轨迹；Qwen ForcedAligner 的标准输出已含 `fix_timestamp` 修正，不是原始 argmax |
| faster-whisper 两个入口 | 普通 `transcribe` 与 `BatchedInferencePipeline` 默认值不同（VAD、`without_timestamps`、前文 conditioning、温度回退、幻听静音阈值），不能把批处理当作纯性能变量 |
| WhisperX 失败形态 | 对齐失败不一定抛异常：无可对齐字符、起点越界或回溯失败会保留原段落时间并给出空词表；通配符 OOV 不等于发音已验证 |
| Qwen 窗口 | 请求时间戳会把 ASR 目标窗口从 1200 秒改为 180 秒；ASR 与 ForcedAligner 的设备与 dtype 独立配置，ForcedAligner 时间单位为 80 ms |
| 应用对比 | Subtitle Edit 各适配器不共用一套时间策略；VideoLingo 的 `align_timestamp` 只是文本到词索引匹配而非声学二次对齐；pyvideotrans 的短尾合并可造成 61 s 级显示 cue，混合结果中无词段落可能被丢弃 |
| 已知时间戳失败案例 | 显示策略把一个 35.7 s cue 的起点后移 27.7 s；Crisp 全流程在对齐异常时回退到比例分配；上游特征归一化使相同前缀 PCM 的早期识别结果依赖整体输入；SE 导入裁剪相邻 cue 40／80／20 ms |
| 修补无通用解 | 缩小窗口、改 VAD、改 writer、换对齐器、改 FA 输入文本都只有局部收益并带来新回归；置信度、温度重试次数、零时长计数都不是可靠的时间质量指标 |
| 资产复用 | 盘点到 large-v2、Whisper anime.ja（CT2 INT8 与 ggml）、Qwen 动漫 Q8 GGUF 等额外候选；同名 GGUF 在不同发布者之间字节不同，不能互换 |

## 结论与去向
- 采纳为设计先验，不作为选型结论：模型适配器要小而显式、保留后端原始响应、坐标用整数样本区间、用分段映射恢复被删静音的源时间、识别文本不因时间失败而丢弃、声学时间与显示时间分离、缓存键要含模型 revision 与全部预处理参数。
- 候选选择没有在本轮完成，由后续实测决定：见 [W0／X0 demo 与评测](2026-10-stt-demo-w0-x0.md)；组件增量见 [components-and-ctc](2026-10-components-and-ctc.md)。
- 现行基线定义见 [ADR-0003](../adr/0003-new-pyannote-baselines.md)，选型原则见 `docs/development/inference-selection.md`（现行文档）。

## 教训
- 上游库的 CUDA 能力不等于某个打包应用真的带了 GPU 依赖（调研里的某 WhisperX 独立包就带 CPU PyTorch）；faster-whisper 与 CTranslate2 文档对 CUDA／cuDNN 的建议曾不一致，要固定一个具体发布组合并实测。
- vLLM 路线当时要求 Linux/WSL，不是原生 Windows。ASR 在 GPU 不代表对齐器也在 GPU，两处设备都要记录。
- 网上小样本日语 CER 对比用的子集、runtime、量化不同，不能合成排行榜，也不能迁移到本机的动漫素材。
- 同一 checkpoint 家族的 HF 版与 GGUF 版不能假设张量等价；转换来源 revision 未公开时只冻结发布后的字节身份。

## 原始材料
归档 tag 路径（前缀 `archive/2026-11-18-pre-research-restructure:`）：
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-03-model-backend-candidates.md`、`2026-10-03-stt-application-comparison.md`、`2026-10-03-stt-backend-contracts.md`、`2026-10-03-stt-pipeline-design.md`、`2026-10-03-timestamp-failure-cases.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-03-whisper-demo-readiness.md`、`2026-10-03-qwen-crisp-demo-readiness.md`（demo 就绪度与实验臂设计）
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-04-runtime-inventory.md`、`2026-10-04-model-assets.md`、`2026-10-04-subtitle-edit-model-reuse.md`
