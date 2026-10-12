# X0 吸收 WhisperX 策略的源码核查

状态：源码核查完成；质量与成本结论以同轮隔离实验为准  
最后更新：2026-10-05  
范围：本机官方 Qwen3-ASR native Transformers 路径、现有 W0 可复用模块及 MMS 日语对齐；不升级环境、不切换默认后端。

## 核查结论

后续实现入口为[X0 demo](../../experiments/x0_demo/README.md)。用户随后澄清采用门槛，
由[ADR-0002](../adr/0002-x0-demo-flow.md)记录无VAD流程设计的采用；本文保留原核查范围与历史实验建议。

2026-10-05 再后续采用由[ADR-0003](../adr/0003-new-pyannote-baselines.md)记录：X0 基线改为新 Pyannote＋Qwen-ASR＋MMS，仅吸收兼容 Qwen 的流程，保留原生 processor／特征及独立纯文字解码。canonical demo 的 CLI 默认仍为 fixed30、迁移待实现和验证。以下“当前”调用链均指本次源码核查时点；旧 VAD 实验与无 VAD 设计保留其历史身份。

值得做小实验的是**切点策略**：固定30秒可能切断对白，低活动／低能量位置可能提供更完整的上下文。源码只能证明这个变量尚未在当前 X0 中使用，不能证明它会改善日语识别或 MMS 时间。先比较保留全部音频的断点，再单独比较 VAD 过滤及合并；两个动作不能混称“加 VAD”。

WhisperX 的逐块独立识别、先文字后外部对齐，在 X0 已有对应行为。Whisper 的提示 token、无时间戳 token、CT2 参数和固定30秒特征补齐不应移植到 Qwen。MMS 的归一化、jpn adapter、标准 CTC、全文／text_only 保留、原时间映射已是两路线共用能力，也不能再作为 WhisperX 移植的新增质量收益。[现有基准定义](../architecture/stt-candidate-pipelines.md)、[W0 契约](../specs/w0-reusable-demo.md)

## 本机实际调用链及身份差异

已读 [docs 索引](../INDEX.md)、[选型原则](../development/inference-selection.md)、[W0 README](../../experiments/w0_demo/README.md)、契约、[验证记录](../testing/2026-10-05-w0-demo-validation.md)、[ASR 框架审计](2026-10-04-whisper-framework-asr-audit.md)、[VAD／MMS 边界审计](2026-10-04-whisper-framework-vad-alignment-audit.md)及 Qwen 执行记录，再核查以下实际源码。

1. [`experiments/qwen/run_cross.py`](../../experiments/qwen/run_cross.py)运行 Qwen `run_qwen.py --window-seconds 30 --asr-only`，导出窗口文字，再将同一音频和桥接结果交给旧 `whisper/run.py --route W1 --ctc-normalize --ctc-forced-align`。ASR／CTC 为顺序离线子进程，Qwen 原生 FA 不加载。
2. **这个历史入口的默认 CTC 仍是 Jonatas 日语模型，不是 MMS。** 因此 `route=X0` 标签或旧目录名本身不能证明它已实现文档当前 Qwen＋MMS 基准。当前 MMS 的历史 X0 成绩主要来自 [`experiments/japanese_ctc/run.py`](../../experiments/japanese_ctc/run.py)追加对齐；新的同轮比较须明确固定 MMS 实现。不能直接跑未修改 `run_cross.py`，然后把结果写成当前 MMS X0。
3. [`run_qwen.py`](../../experiments/qwen/run_qwen.py)按整数样本构建连续、不重叠窗口；最后一片保留实际长度。每片只把该 PCM 传入 `apply_transcription_request(audio=data, language="ja")`，无上下文 prompt、无前窗文字。`generate(max_new_tokens=4096, do_sample=False)`，BF16、SDPA、batch1、CUDA；每窗分别解析原始输出为 transcription。模型在多窗间复用，输入请求与生成状态重新建立。
4. [`export_ctc_input.py`](../../experiments/qwen/export_ctc_input.py)校验连续音频分区、窗口／整体 PCM hash、源偏移、完整文字与 CUDA 证据。ASR 输入窗口边界只是后续 CTC 搜索范围，不是声学时间戳。VAD 非连续窗口不能直接绕过其完整分区检查；已有 [`components/qwen_vad.py`](../../experiments/components/qwen_vad.py)另有非连续窗口及原坐标契约，可供适配时参照。
5. 现有 [`w0_demo/alignment.py`](../../experiments/w0_demo/alignment.py)的 `MmsAligner.align(audio, segments, offset)`与识别模型无关，可直接消费 Qwen 的完整文字及原音频窗口。应复用该边界，而不是再复制 loader／归一化／CTC／字符映射。它固定 jpn adapter/head、FP32 CUDA、标准 forced_align 和显式 TF32 作用域，保留失败及 OOV 字符；没有调用 Whisper ASR。

本次只读核查到的本机环境是 `.local/envs/qwen-hf-final`，Transformers 5.18.0；ASR 为 `Qwen/Qwen3-ASR-1.7B-hf`，revision `bcd2b5b7f32b480ab5790554cfa8347f246a14f3`。安装源码 SHA256 本次重新读取：

| 文件 | SHA256 |
| --- | --- |
| `processing_qwen3_asr.py` | `5ff7ace057ae959fb0cd551775cbbfdad8c003eb731bf0f1f39bfc6452ce86fa` |
| `feature_extraction_qwen3_asr.py` | `95d23cca9645546b9f6a97885eace5c02a95f5048bf3616e03f00041fd993a74` |
| `modeling_qwen3_asr.py` | `62b77cd1eee32d002f0b5c36a2a507df4b093a8891d5890173737d2e08fe8401` |

前两项与[既有 Qwen 固定 tag 核验](2026-10-04-qwen-execution.md)一致。本次不是环境升级或权重重下载。模型的 `generation_config.json`写 max_new_tokens=512，但本机 runner 明确覆盖为4096，应按有效参数记账。模型特征配置嵌在 `processor_config.json`中，而非独立 `preprocessor_config.json`。

## 可移植、已有等价、不适用

| WhisperX 行为／动机 | Qwen／X0 事实 | 处置 |
| --- | --- | --- |
| 在低活动位置切长段，减少句中截断 | 固定30秒切点尚未看声音 | 有可隔离变量；先试保留全部音频的切点 |
| VAD 迟滞筛选、长段 min-cut、按原时间跨度合并 | X0 无 VAD；W0 `vad.py`已有已验证实现 | 技术可复用，过滤质量不能继承 W0 或论文结论 |
| 每块独立解码，不串联前文 | 当前 X0 每块重新请求，无 prompt／前文 | 已具备，无需新增迁移实验 |
| 不让 Whisper 同时生成文字和时间 token，另做强制对齐 | Qwen 当前输出 transcription，MMS 独立对齐 | 流程已等价；不添加 Whisper `without_timestamps` token |
| Whisper EOT token 过滤、语言／任务 token、suppress token、CT2 beam 参数 | Qwen 使用自己的 chat template／语言 prefill／tokenizer／greedy generation | 模型专属，不移植 |
| Whisper 波形补到30秒、冻结 Mel 资产、固定特征张量 | Qwen 按自己的 processor 提取及补齐，attention mask 和音频 token 长度参与模型输入 | 保留 Qwen 原契约 |
| 外部 CTC 归一化、日语词表、失败文字保留与源时间 | 当前 MMS 共享边界已经实现 | 共用模块；比较时固定，不记作新增移植收益 |
| batch 推理提升吞吐 | Qwen 官方 API 支持 batch，当前 X0 batch1 | 后续独立成本实验；本轮不与切点混测 |
| 原生 WhisperX 句级 cue／NLTK／插值 | 当前目标是原文与字符时间／text_only，显示层另行处理 | 无需复制整套句切／输出流水线 |

WhisperX v3.8.6 的 `merge_chunks`输出的是原坐标 `start/end`及内部 constituents。ASR 取连续 `audio[start:end]`，**保留被合并段之间的内部静音**；并非把多个 speech PCM 紧密拼接。这一区分适用于复用 [`w0_demo/vad.py`](../../experiments/w0_demo/vad.py)时的音频身份与时间映射。[上游 merge 源码](https://raw.githubusercontent.com/m-bain/whisperX/v3.8.6/whisperx/vads/vad.py)、[ASR 源码](https://raw.githubusercontent.com/m-bain/whisperX/v3.8.6/whisperx/asr.py)

## Qwen 特征与切窗：两个容易混淆的事实

本机 `Qwen3ASRFeatureExtractor`同样使用128通道 Mel、16 kHz、hop160、FFT400和 log-Mel动态范围压缩。这不意味着可直接替换为 WhisperX 特征：Qwen helper 默认 `padding=True/truncation=False`、`n_window=50`、attention mask；短于8000样本先补零，Mel 轴补至100帧倍数，真实音频长度参与音频 token 展开。`chunk_length=30`用于 `padding="max_length"`的默认长度，本机推荐 helper 不调用固定最大长度裁切。当前30秒**是项目显式策略，不是由该 HF helper 自动 VAD 或强制切窗**。[固定 Transformers feature 源码](https://raw.githubusercontent.com/huggingface/transformers/v5.18.0/src/transformers/models/qwen3_asr/feature_extraction_qwen3_asr.py)、[processor 源码](https://raw.githubusercontent.com/huggingface/transformers/v5.18.0/src/transformers/models/qwen3_asr/processing_qwen3_asr.py)

官方旧 `qwen-asr` wrapper 另有 `split_audio_into_chunks`：在目标切点附近±5秒搜索100 ms 的低绝对幅值窗口，再选择局部最低幅值样本，保留原音频连续切片。其调用存在于同 commit 的 `qwen3_asr.py`，**本机 native HF helper 没有调用它**。这提供了无需新增神经 VAD 的最小对照思路，但不是已经启用的 X0 优化，也不是专门来自 WhisperX。[固定 Qwen utils 源码](https://raw.githubusercontent.com/QwenLM/Qwen3-ASR/c17a131fe028b2e428b6e80a33d30bb4fa57b8df/qwen_asr/inference/utils.py)、[对应 wrapper 调用](https://raw.githubusercontent.com/QwenLM/Qwen3-ASR/c17a131fe028b2e428b6e80a33d30bb4fa57b8df/qwen_asr/inference/qwen3_asr.py)

该旧 helper 不能照搬：搜索可越过名义 max_chunk_sec，短尾片还会补至0.5秒，不能据其注释声称返回 PCM 拼接与原文件逐样本完全一致。隔离原型应存原坐标边界，检查无缺样、无重叠，补零只由 Qwen processor 负责；若沿用 W0 的30秒窗口契约，将候选搜索限制在上限之前。低能量对持续音乐／低声对白是否可靠必须实测。

Qwen parsed 输出也已有 repetition 修正：本机 processor 内 `_detect_and_fix_repetitions(threshold=20)`处理极长重复字符／模式，原始 decoder 字符串仍由 runner 保存。它并非普通跨片重复消除器，不能拿它当作已经解决边界重复；真实重复对白和歌声也不能按“看起来重复”直接删除。[固定 processor 源码](https://raw.githubusercontent.com/huggingface/transformers/v5.18.0/src/transformers/models/qwen3_asr/processing_qwen3_asr.py)

## 反证与最小实验边界

[既有组件增量实验](2026-10-04-component-augmentation-results.md)已经试过旧 X0＋Pyannote 带上下文 VAD，四个300秒窗口：CER 18.98%→19.13%，删除127→141，半秒确定成功90→90，两片共同可测 P95 都变差，因此停止该分支。其 CTC 是旧 Jonatas，窗口策略也不能与本轮 MMS／W0 原 merge 混同；它是过滤策略的风险证据，不是“任何 VAD 对 Qwen 均无效”的证明。

建议以同一小样本、同一 Qwen 和 MMS 开始：

1. 固定30秒全音频基准。先核对原 Qwen 固定窗文字／有效参数与现有缓存身份；换为共享 MMS 边界的工程收益与切窗质量收益分开。
2. 仅改变切点、保留全部音频。可先用低能量候选，或者复用一次冻结 Pyannote scores 提供低活动候选；有无新神经检测成本必须明示。连续、不重叠、原样本总覆盖100%，不增加 overlap／去重／prompt／batch 等变量。
3. VAD 过滤后按 W0 原 merge 合并。复用 W0 detector 与后处理，保留块内静音和源坐标，使用同一个 Qwen Adapter／MMS runner。相对第2项增加的过滤、边界和块数变化均须记录，不声称纯“删除静音”的因果效应。

每项记录全文 CER、S/D/I、边界重复、timed／text_only 原文字数、完整参考分母的时间成功及严重偏移；成本包括分段／VAD、Qwen、MMS、加载和完整进程墙钟。不得用更短输出或只统计成功对齐字符制造改善；新过滤分支即使没有检测到对白，也要记缺失及跳过，而非移出分母。输入优先 II／III 原版日文参考，对白优先；真实歌声保留不是 VAD 误报，字幕未标歌声造成的插入不能未经听辨当作幻觉。[评估规范](../testing/stt-evaluation.md)、[选型原则](../development/inference-selection.md)

当前源码不足以要求重跑 Whisper token／Mel 移植、Qwen 原生 FA、精度、batch 或整片。小样本若无明确收益或出现漏字／覆盖回归，停止扩展；若出现收益，再冻结配置扩大到独立场景。MMS 搜索窗改变后时间可能改善也可能恶化，CTC 对齐器无法补回 ASR 漏字或 VAD 删去的音频。

## 来源、版本与限制

上述上游链接均于 **2026-10-05**访问；固定源码版本为 WhisperX v3.8.6、Transformers v5.18.0、Qwen wrapper commit `c17a131fe028b2e428b6e80a33d30bb4fa57b8df`。固定源码用于解释本机已锁定实现，不是建议升级或装入旧 wrapper。

- [WhisperX 论文 v2](https://arxiv.org/abs/2303.00747v2)，2023-07-11：论文在 Whisper 长音频系统中验证 VAD Cut & Merge 及批量策略；其效果和速度不能直接外推为本机 Qwen＋MMS 结果。
- [WhisperX v3.8.6 min-cut／迟滞源码](https://raw.githubusercontent.com/m-bain/whisperX/v3.8.6/whisperx/vads/pyannote.py)：核查神经分数到活动段的后处理，模型身份和本机等价性另见 W0 验证。
- [官方 Qwen native HF 模型卡](https://huggingface.co/Qwen/Qwen3-ASR-1.7B-hf)：推荐 `apply_transcription_request`、forced language、parsed 输出和 batch API。本机实际能力仍由固定源码／配置决定。
- [Qwen 官方项目](https://github.com/QwenLM/Qwen3-ASR)：官方列出对白、歌声及带 BGM 歌曲能力，不能据此宣称本机日语电影／歌声质量已通过验证。

本文区分本机源码事实、既有实测和待检验推断；不提供新 GPU 质量成绩。W0 两窗已验证的是行为保留，不是 Qwen 同窗改善。固定 TorchAudio 2.8 forced_align 的维护和 MMS 许可边界沿用[既有 MMS 来源报告](2026-10-04-japanese-ctc-source-verification.md)，本轮不升级或改换。新的隔离实验结果应由同轮报告单独承载；后续 X0 基线定义以 ADR-0003 为准，本文核查记录不能证明其 canonical 迁移已完成。
