# 当前三候选的组件增强来源核查

> 2026-10-05 当前入口说明：本文“三候选”及缺失组件建议均指当轮旧配置。当前已采用W0／X0两条基线，新测试从[统一指南](../guides/baseline-testing.md)进入两套标准demo；本页来源核查不定义当前缺失组件。

状态：调研完成；以下排序是实验建议，新增组件效果由独立实测报告决定  
最后更新：2026-10-04  
范围：W1／W0／X0、本地日语电影音频、原生 Windows／RTX 5080；只核查上游、组件边界与可复用资产。

本次按[推理选择原则](../development/inference-selection.md)、[当前候选](../architecture/stt-candidate-pipelines.md)及[评测方法](../testing/stt-evaluation.md)开展。本文没有运行 GPU、安装依赖或下载大权重；版本/API 核查不代表真实推理通过。全部外部来源访问日期均为 **2026-10-04**。

## 建议的单组件顺序

1. **W1 前增加一个 GPU 人声分离器**，先测 Demucs 4.1.0 的单模型 `htdemucs` vocals。现有 W1 已有 GPU Pyannote、ASR、日语 CTC；新增分离器直接针对 BGM／效果声，保留 W1 完整流程。优先性是依据电影音频用途的推断，并非上游已证明日语字幕提升。只有开发样本的时间成功、识别／覆盖护栏一起支持时，才扩大或继续叠加。
2. **W0 或 X0 增加独立 GPU VAD**。优先复用已经验证的 WhisperX Pyannote 权重与执行环境，避免新增资产；它们分别缺独立 VAD，但原 ASR 的无语音判断仍存在。保留原 ASR 解码设置及下游时间机制。语音段切分／合并需要明确源时间映射，不用参考字幕边界指导切窗。先检验弱语音删除与跨窗短句，不能只比较静音幻觉。
3. **固定 W0 的 PCM 与识别文字，增加现有日语 CTC**，属于缺失阶段实验；已有同类探索证据，应先查[历史 W0＋CTC](2026-10-04-w0-ctc-exploration.md)，避免重复执行同一配置。对 W1／X0 再加同一个 CTC 不形成新能力。
4. **宽带降噪或其它分离器**作为有失败机制支持的替代前处理对照。不能从歌曲分离分数推导电影对白改善，也不能先将降噪与人声分离同时叠加。Qwen FA 替换仅适用于明确需要对齐器比较的独立诊断；当前已有 Q0 历史结果，优先级低于缺失组件。

每次比较固定版本、音频身份、评分规则与选择门槛；记录新计算与缓存阶段。两片主参考分别报告 CER、S/D/I、完整分母时间成功上下界、覆盖和失败；条件 P95/P99 不代替完整性。已经接触的样本不能重新称为未见保留集。源素材只读，派生音频与结果写入 `.local/`。

## 分离与降噪：稳定版本及实际边界

| 组件 | 核查结果 | 选型含义 |
| --- | --- | --- |
| Demucs | [PyPI 4.1.0](https://pypi.org/project/demucs/4.1.0/) 于 2026-07-11 发布；作者 [v4.1.0](https://github.com/adefossez/demucs/tree/v4.1.0) commit `6a604bb002d12c4fbabb303ba64db40b5c5743f0`。 | 当前稳定默认应为 4.1.0；旧 Meta repo 已归档，作者 repo 是官方维护入口，但作者明确说明开发投入有限。 |
| HTDemucs | [作者 HF checkpoint](https://huggingface.co/adefossez/HTDemucs/tree/cbc8a9b1a87023b7fd74e7b3412e6321c0eab003) revision `cbc8a9b1a87023b7fd74e7b3412e6321c0eab003`，单模型 `955717e8`；safetensors 为 84,025,440 bytes，LFS SHA256 `d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd`。 | 本项目／Subtitle Edit 既有清单没有该分离器，需要单独 provision。官方 HF 文件为权重、JSON sidecar 与 bag YAML；不把同名旧 `.th` 自动当成同一文件。 |
| `htdemucs_ft` | [作者说明](https://github.com/adefossez/demucs/tree/v4.1.0)将其描述为可能略好、约四倍耗时的 fine-tuned 版本。 | 这是四模型 bag；初探单 `htdemucs` 可降低试验成本。若开发证据支持且资源允许，再另设质量优先对照。 |
| audio-separator | [PyPI 0.47.0](https://pypi.org/project/audio-separator/0.47.0/) 于 2026-08-27 发布；[官方项目](https://github.com/nomadkaraoke/python-audio-separator)集成 UVR／RoFormer／Demucs 等，含 PyTorch CUDA 和 ONNX 路径。 | 可作为后续分离候选，但它是集成框架；默认模型、模型发布者、版本与实际 provider 必须独立核查。其依赖含 `onnx-weekly`，不适合无说明地并入已锁后端环境。 |
| DeepFilterNet | [稳定 0.5.6](https://github.com/Rikorose/DeepFilterNet/releases/tag/v0.5.6)；[官方说明](https://github.com/Rikorose/DeepFilterNet)支持 Windows 和 Python PyTorch GPU。48 kHz 输入、STFT／lookahead 延迟须补偿。 | 噪声抑制与人声伴奏分离职责不同。Rust CLI 本身不能当作 GPU 路径；现有 Python 3.12／3.13 不应直接假定可安装。 |

Demucs 4.1.0 [推理依赖](https://github.com/adefossez/demucs/blob/v4.1.0/pyproject.toml)要求 Python ≥3.10、Torch ≥2.1，采用 `sphn`，常规推理不要求旧版 TorchAudio。`sphn` 0.1.12 的 [PyPI 文件](https://pypi.org/project/sphn/0.1.12/#files)有 Windows cp312／cp313 wheel。这使复用现有 CUDA PyTorch 环境成为可行试验方向，仍需实测 RTX 5080 模型 forward。官方 [Windows 指南](https://github.com/adefossez/demucs/blob/v4.1.0/docs/windows.md)保留旧 Python／TorchAudio 限制，已与新打包不一致；不据旧文字降级冻结环境。

[stable 本地权重 helper](https://github.com/adefossez/demucs/blob/v4.1.0/demucs/hf.py) 的 `load_safetensors_model(path)`可直接载入 provision 后文件，再用 [apply_model](https://github.com/adefossez/demucs/blob/v4.1.0/demucs/apply.py)显式 CUDA 推理。`get_model` 默认会尝试 HF、失败后旧远程仓库；正常离线推理不能依赖其自动联网。`--two-stems vocals`是输出选择，内部仍执行完整分离，不能宣称只计算一个 stem。

44.1 kHz／stereo 是 HTDemucs 原生表示。若冻结 16 kHz mono PCM 先复制声道并重采样，再分离和回到 16 kHz mono，可保持与现有候选的输入身份关系，但已丢失空间线索／高频；该链的结果不能代表原始 stereo 输入的分离上限。若后续直接使用已分离 FLAC 的 stereo 表示，要另设配对输入基准。输出样本数、重采样和任何 padding／裁剪应登记，不能通过参考字幕估计并补偿时间偏移。

DeepFilterNet 0.5.6 对 [DeepFilterLib 文件](https://pypi.org/project/DeepFilterLib/0.5.6/#files)的 Windows wheels 截至 cp311，没有 cp312／cp313；因此它需要单独兼容性评估，不能仅凭 Python package 存在判断当前环境无成本可用。Demucs 代码仓库许可为 MIT；HF HTDemucs 卡未独立列出 license 元数据，应保留模型发布者与原始许可出处，不自造权重许可结论。

## WhisperX 是否允许组合其它对齐器

[WhisperX 3.8.6 稳定源码](https://github.com/m-bain/whisperX/tree/v3.8.6) commit `3ccc17b8de34f305300f8a3fd3c9f76ba820c0d0` 的 [ASR loader](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/asr.py)公开 `vad_model`、`vad_method`；自定义 VAD 有优先级，原生支持 Pyannote／Silero。这属于可替换边界，但本轮 W1 已有 GPU Pyannote，继续保留即可。

[alignment.py](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py)的 `load_align_model` 对 HF 路径明确调用 `Wav2Vec2ForCTC`／`Wav2Vec2Processor`，不是通用 aligner 插槽。`--align_model`不能直接接收 Qwen FA 或 Canary GGUF。可以保存 WhisperX 原生 ASR segments，独立调用外部 aligner 并桥接文本／窗口／源坐标，但这是新增适配器和另一个实验配置，不能冒称 WhisperX 官方原生支持。

### Qwen3-ForcedAligner 与 CTC 的区别

[官方 Qwen FA HF 卡](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf/tree/c07281df297b9905d24a508279258cccf987a064) revision `c07281df297b9905d24a508279258cccf987a064` 明确支持日语；它可独立接受文字与音频，因此可为其它 ASR 结果服务。[官方 API](https://github.com/QwenLM/Qwen3-ASR#forcedaligner-usage)提供独立 `align`调用。

[Transformers 5.18.0 稳定 processor](https://github.com/huggingface/transformers/blob/v5.18.0/src/transformers/models/qwen3_asr/processing_qwen3_asr.py)将 `<timestamp>`位置的分类 argmax 乘以默认 80 ms，并执行时间修正；[模型类](https://github.com/huggingface/transformers/blob/v5.18.0/src/transformers/models/qwen3_asr/modeling_qwen3_asr.py)采用 TokenClassification。这是非自回归时间分类对齐器，不能当成另一个 CTC head，也不能将其输出交给现有 `torchaudio.forced_align`。

Qwen HF 卡仍有“从 Transformers 源码安装”的旧 setup 文字；项目已有稳定 5.18.0 的同 API 实测，不必按旧文字升级 development build。已有 Q0／FA 结果只证明其现有配置的表现，不能自动推导 WhisperX 文字＋Qwen FA 的表现。W1／X0 目前已有 CTC，叠加 FA 不等于增加缺失阶段。

### Canary CTC 的日语边界

[cstr Canary CTC 卡](https://huggingface.co/cstr/canary-ctc-aligner-GGUF/tree/2b22dc9aff585bc8368a5228173c8afe22c155b7) revision `2b22dc9aff585bc8368a5228173c8afe22c155b7`称其来自 Canary-1B-v2 `.nemo`内辅助 CTC，25 种欧洲语言；[NVIDIA 原模型](https://huggingface.co/nvidia/canary-1b-v2)的语言清单同样不含日语。它能接受其它 ASR transcript，是接口独立性，不是语言无关能力。现有本机 Q8 GGUF 可复用这一资产事实，不能据此纳入日语质量候选；不运行无日语支持的正式排名。

### `wav2vec2aligner-japanese` 的身份

在当前上下文中，该称呼可解析到 Subtitle Edit 的 `wav2vec2 aligner (Japanese)`／`wav2vec2-aligner-ja`，而不是另一份新训练模型：[官方下载定义](https://github.com/SubtitleEdit/subtitleedit/blob/c7c4a43730524c368e14a3dbf07b0c5684f73c61/src/ui/Features/Video/SpeechToText/Engines/ForcedAlignerOption.cs)指向 `cstr/wav2vec2-large-xlsr-53-japanese-GGUF` 的 Q4_K。

[发布者模型卡](https://huggingface.co/cstr/wav2vec2-large-xlsr-53-japanese-GGUF/tree/16c3b21fe7858426806f4bf795578497e0b5dad2)明确是原 checkpoint 格式转换／量化，无新训练；[原模型](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/tree/cf031e020336460d15a417eba710bbc5bb43be9a)正是 W1／X0 当前使用的模型。改用 GGUF/Crisp 会同时改变数值表示、runtime 和对齐实现，应视为另一个后端实验；它不能作为“加一个尚缺日语 CTC”来解释 W1／X0 的潜在收益。

## VAD 的 GPU 证据要求

[Silero 最新稳定 v6.2.3](https://github.com/snakers4/silero-vad/releases/tag/v6.2.3)于 2026-09-23 发布，commit `5cd7945676eb32225748052e2e6a0580e4686a08`。[官方 loader](https://github.com/snakers4/silero-vad/blob/v6.2.3/src/silero_vad/model.py)的 ONNX 默认强制 CPU；JIT 初始化也默认 CPU。自行显式移到 CUDA并验证 forward 是另一条路径，不得把安装 GPU ORT 包称为已完成 GPU VAD。

[WhisperX stable Silero adapter](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/vads/silero.py)通过未指定 tag 的 `torch.hub`加载，未显式 `.to(cuda)`；[faster-whisper 1.2.1 VAD](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/vad.py)固定 CPUExecutionProvider。因此本轮 GPU-only 前处理不能直接打开这些默认开关后宣称满足约束。项目已有 Pyannote GPU 路径可优先复用；新增 Silero 必须固定版本、本地资产与设备，并记录弱语音遗漏、模型 reset、padding 和实际窗口。

本文所有组件建议尚未构成产品后端采用决定。来源核查本身不验证 RTX 5080 的真实 forward、峰值显存、处理成本、对白保留、音频时间偏移或三候选的实际增益；后续已经执行的分离、VAD 与 CTC 实验见[组件增量实测](2026-10-04-component-augmentation-results.md)，未执行组件仍只属于接口及选型分析。
