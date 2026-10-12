# 四候选 VAD 的发布身份与固定接口

状态：来源核查完成；候选环境与实测结果由本轮评测报告记录，本文不作质量排名  
最后更新：2026-10-05  
范围：为当前 W0／X0 的四个新 VAD 候选固定软件、模型、接口和获取条件；所有来源访问日期为 2026-10-05。

相关：[现有 VAD 调研](2026-10-05-vad-landscape.md)、[成熟候选核查](2026-10-05-established-vad-sources.md)、[FireRed 来源核查](2026-10-05-emerging-vad-sources.md)、[选择原则](../development/inference-selection.md)。

## 本轮版本身份

以下结论重新查询 PyPI JSON、GitHub Releases API 与 Hugging Face 模型 API，未直接沿用上轮调研中的“最新”字样。软件发布、模型仓库 revision 和权重训练版本分别记录。

| 候选 | 本次核验的软件发布 | 固定模型身份 | 发布边界 |
| --- | --- | --- | --- |
| Pyannote | `pyannote.audio==4.0.7`；PyPI wheel 上传 2026-06-30 | `pyannote/segmentation-3.0`，revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb` | 当前公开命名且具有官方纯 VAD 示例的 segmentation 模型；框架最新版不代表新训练。模型卡的安装示例仍面向旧 3.0 API。 |
| Silero | `silero-vad==6.2.3`，GitHub `v6.2.3`；2026-09-23 | 该 wheel 自带 `silero_vad/data/silero_vad.jit`；固定 wheel 与本地模型文件 hash | 普通稳定发布；6.2.3 主要改变可选音频依赖，不能称为新声学权重训练。 |
| FunASR FSMN | `funasr==1.4.16`，GitHub `v1.4.16`；2026-09-18 | `funasr/fsmn-vad`，revision `df20e6b30c653645fa4ff125cacfcabd1020a669` | PyPI 标 Production/Stable；框架与 checkpoint 独立版本。 |
| FireRedVAD | `fireredvad==0.0.2`；2026-03-09 | `FireRedTeam/FireRedVAD`，revision `7990aaccc6b7aec1e527743bd30201f2c4a03b8c`，只取离线 `VAD/` | 最新非预发布 PyPI 版本，但项目分类明确为 Beta，GitHub Releases 数为 0。它是用户指定的探索性例外，不能称“已核验稳定版”。 |

软件来源：[Pyannote PyPI](https://pypi.org/pypi/pyannote.audio/json)、[Pyannote release](https://github.com/pyannote/pyannote-audio/releases/tag/4.0.7)、[Silero release](https://github.com/snakers4/silero-vad/releases/tag/v6.2.3)、[Silero PyPI](https://pypi.org/pypi/silero-vad/json)、[FunASR release](https://github.com/modelscope/FunASR/releases/tag/v1.4.16)、[FunASR PyPI](https://pypi.org/pypi/funasr/json)、[FireRed PyPI](https://pypi.org/pypi/fireredvad/json)、[FireRed Releases API](https://api.github.com/repos/FireRedTeam/FireRedVAD/releases)。

模型 revision 来源：[Pyannote API](https://huggingface.co/api/models/pyannote/segmentation-3.0)、[FSMN API](https://huggingface.co/api/models/funasr/fsmn-vad)、[FireRed API](https://huggingface.co/api/models/FireRedTeam/FireRedVAD)。这些 revision 是本轮固定快照；不能在后续比较中自动跟随 `main`。

Pyannote 的最新完整说话人区分 pipeline 为 `speaker-diarization-community-1`，本次 API revision 为 `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`。其文件树确实包含 `segmentation/pytorch_model.bin`，但模型卡提供的是完整 diarization 接口与 DER 成绩，未提供独立 VAD 配方或 VAD 改善证明。将该内部模型提取为 binary VAD 应另立探索身份，不将其整条 diarization 功能混入四候选比较。[Community-1 模型卡](https://huggingface.co/pyannote/speaker-diarization-community-1)、[模型 API](https://huggingface.co/api/models/pyannote/speaker-diarization-community-1)

## 资产获取、许可与离线加载

| 候选 | 需要获取的最小资产 | 获取条件与许可 |
| --- | --- | --- |
| Pyannote | `pytorch_model.bin`，保留模型卡／许可与下载 revision 记录 | `gated="auto"`；必须由有权账户接受 [segmentation-3.0 条件](https://huggingface.co/pyannote/segmentation-3.0)，用有权限的 HF token 获取。模型 MIT，代码 MIT。普通公开请求返回 401 不说明本机损坏。 |
| Silero | 固定 wheel 中的 JIT 文件 | 无 gate、无额外模型下载；项目与发布模型 MIT。 |
| FSMN | `model.pt`、`config.yaml`、`configuration.json`、`am.mvn` | HF API 标 ungated；模型卡 Apache-2.0，FunASR 代码 MIT。 |
| FireRed | `VAD/model.pth.tar`、`VAD/cmvn.ark` | HF API 标 ungated；模型卡及代码 Apache-2.0；不以 `Stream-VAD` 或 `AED` 替代离线 VAD。 |

许可来源：[Pyannote 模型卡](https://huggingface.co/pyannote/segmentation-3.0)、[Pyannote 代码许可](https://github.com/pyannote/pyannote-audio/blob/4.0.7/LICENSE)、[Silero 许可](https://github.com/snakers4/silero-vad/blob/v6.2.3/LICENSE)、[FSMN 模型卡](https://huggingface.co/funasr/fsmn-vad)、[FunASR 代码许可](https://github.com/modelscope/FunASR/blob/v1.4.16/LICENSE)、[FireRed 模型卡](https://huggingface.co/FireRedTeam/FireRedVAD)、[FireRed 代码许可](https://github.com/FireRedTeam/FireRedVAD/blob/c30ec49e8cc69642b0ee65362eba11b9d11c6e54/LICENSE)。

建议使用 `huggingface_hub.snapshot_download(repo_id=..., revision=..., local_dir=..., allow_patterns=...)` 单独预置资产；推理只加载本地路径。所有包安装、模型下载和缓存写入须按本仓库 Windows 沙箱规则执行。音频不上传，ASR／MMS 保持现有 GPU 环境。Pyannote 推理前设置 `PYANNOTE_METRICS_ENABLED=0`；FunASR 创建模型时设置 `disable_update=True`。这是本地离线实验设置，并非各模型质量参数。[Pyannote telemetry 文档](https://github.com/pyannote/pyannote-audio/blob/4.0.7/README.md)、[FunASR AutoModel](https://github.com/modelscope/FunASR/blob/v1.4.16/funasr/auto/auto_model.py)

用于验证下载的普通 wheel SHA256：

| wheel | SHA256 |
| --- | --- |
| `pyannote_audio-4.0.7-py3-none-any.whl` | `852ea15c4d85bc34773e618267603ffca6a521669a74d33742692cc67fc700d6` |
| `silero_vad-6.2.3-py3-none-any.whl` | `7b7f5436cfcb02fae583a05b512ea96467fd449fe54cb49a5e4f06c51a1e43b8` |
| `funasr-1.4.16-py3-none-any.whl` | `f95943f6a8111349a1b08907363b048a49e9cb9caa1e3afd8c92970d08bf450d` |
| `fireredvad-0.0.2-py3-none-any.whl` | `7aca392e5d6ab22add80f5920561928bf2cd4adc7474b6d20952257941a11cf5` |

上述 hash 来自各包前述 PyPI JSON，不替代实际模型文件 hash。

## 适配器需冻结的当前接口与默认行为

### Pyannote

`Model.from_pretrained(local_checkpoint)` 后传入 `VoiceActivityDetection(segmentation=model)`，显式 `instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})`；输入可为 `{"waveform": tensor[1,N], "sample_rate":16000}`。3.0 powerset 模型固定 onset／offset 为 0.5。4.0.7 的模型下载参数是 `token`，不是旧卡的 `use_auth_token`。其 `default_parameters` 对字符串 `segmentation-3.0.0` 的匹配和实际模型名不同，不能依赖自动默认实例化。以上分别由[4.0.7 模型 loader](https://github.com/pyannote/pyannote-audio/blob/4.0.7/src/pyannote/audio/core/model.py)、[VAD pipeline](https://github.com/pyannote/pyannote-audio/blob/4.0.7/src/pyannote/audio/pipelines/voice_activity_detection.py)和模型卡核验。

### Silero

`load_silero_vad()` 从 wheel 加载 JIT；`get_speech_timestamps(float32_mono_tensor, model, sampling_rate=16000)` 的默认阈值为 0.5、最短语音 250 ms、最短静音 100 ms、前后扩展 30 ms、最长语音无限。默认返回采样点区间；推荐保存该整数坐标，再换算秒，避免 `return_seconds=True` 默认一位小数导致的精度损失。16 kHz 网络帧为 512 采样点。普通 ONNX loader 强制 CPU；JIT 默认 CPU。即便安装 GPU extra，也不能直接宣称官方 loader 使用 CUDA。[固定 loader](https://github.com/snakers4/silero-vad/blob/v6.2.3/src/silero_vad/model.py)、[固定时间戳代码](https://github.com/snakers4/silero-vad/blob/v6.2.3/src/silero_vad/utils_vad.py)

### FSMN

`AutoModel(model=local_snapshot, hub="hf", device="cpu", disable_update=True)`，`generate(input=float32_mono_numpy, fs=16000)`，取 `result[0]["value"]` 的毫秒起止区间。16 kHz checkpoint 的前端使用 25 ms 帧长／10 ms 步长、80 Mel、5 帧 LFR；原配置为 800 ms 结束静音、150 ms 状态转移、200 ms 句首回看／100 ms 句尾前看、最长 60 秒、`speech_noise_thres=0.6`。[配置](https://huggingface.co/funasr/fsmn-vad/blob/df20e6b30c653645fa4ff125cacfcabd1020a669/config.yaml)、[输入 loader](https://github.com/modelscope/FunASR/blob/v1.4.16/funasr/utils/load_utils.py)

**当前框架默认并不等于上述 YAML 默认。** 1.4.16 的 `inference` 在未显式给出 `max_end_silence_time` 时默认启用 `dynamic_silence`，按累计块时间修改结束静音并把 `speech_noise_thres` 设置为 0.5。离线默认表为：累计 10／20／30／40／50／60 秒分别对应 2000／1000／800／600／400／200 ms，之后 100 ms；检查发生在默认 60000 ms 分块循环中。若实验显式关闭动态策略并固定 800 ms，必须称为独立固定 endpoint 配方；不能把它写成最新框架的未修改默认。[1.4.16 FSMN 推理与 schedule](https://github.com/modelscope/FunASR/blob/v1.4.16/funasr/models/fsmn_vad_streaming/model.py)

### FireRed

`FireRedVad.from_pretrained(local_VAD_dir, FireRedVadConfig(use_gpu=False))`，`detect((pcm16_numpy,16000))` 返回 `(result, probs)`；`result["timestamps"]` 是秒区间。入口 tuple 顺序是波形、采样率；内部 fbank tuple 顺序相反。直接使用 int16 PCM 数值尺度与官方文件 loader 一致，不能把归一化 float 音频原样传入。默认 5 帧平滑、阈值 0.4、最短语音／静音各 20 帧、最长语音 2000 帧、merge／extend 为 0、分块 30000 帧，每帧 10 ms。可 `do_postprocess=False` 获取原始概率；不改变本轮二分类正类定义。[VAD API](https://github.com/FireRedTeam/FireRedVAD/blob/c30ec49e8cc69642b0ee65362eba11b9d11c6e54/fireredvad/vad.py)、[输入与特征](https://github.com/FireRedTeam/FireRedVAD/blob/c30ec49e8cc69642b0ee65362eba11b9d11c6e54/fireredvad/core/audio_feat.py)

## Windows 与运行环境边界

Silero／FunASR 的包元数据声明 OS Independent 或 Windows；FireRed README 明列 Windows／Linux NVIDIA 安装路径，但示例 shell 为 bash，不能直接照抄到 PowerShell。Pyannote 4.0.7 依赖 `torch>=2.8`、`torchaudio>=2.8`、`torchcodec>=0.7`，音频文件解码可能涉及 FFmpeg；传入已解码 waveform 仍需验证 import 和 checkpoint 兼容。上述是部署资格线索，不是 RTX 5080 或本机运行通过证据。[FireRed 固定 README](https://github.com/FireRedTeam/FireRedVAD/blob/c30ec49e8cc69642b0ee65362eba11b9d11c6e54/README.md)、各包前述 PyPI 元数据。

2026-10-05 公共 PyPI 当前 `torch` 为 2.14.1、`torchaudio` 为 2.11.0，均有 Python 3.12 Windows x64 wheel。因此不能无约束地分别追最新版并假定兼容。为本轮 VAD 环境选择成对稳定 runtime 时，应固定兼容的 Torch／TorchAudio 组合并记录原因；选择较旧兼容 runtime 不改变四个 VAD 软件包的发布身份。[Torch JSON](https://pypi.org/pypi/torch/json)、[TorchAudio JSON](https://pypi.org/pypi/torchaudio/json)

本文未运行模型；实际安装版本、资产 SHA256、设备、错误以及端到端数据由实验记录补充。门控模型未取得时，该组合应明确记作获取受阻；旧 bundled Pyannote checkpoint 不能冒充 `segmentation-3.0`。
