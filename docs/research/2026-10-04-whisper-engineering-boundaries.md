# Whisper 后续实现的工程边界

> 2026-10-05 后续开发入口：本文保留旧 W0／W1 的工程交接。当前 W0 的实现、加固和模型边界调整应复用并更新 [W0 demo](../../experiments/w0_demo/README.md)，以其契约和回归为起点，避免重新采用旧流程的运行时 hook。

状态：探索性工程交接；已实现 demo 与证据支持的约束，尚无正式后端采用决定  
最后更新：2026-10-04  
范围：本轮 W0、W1 原生/组件及规范化标准 CTC 分支；仅消费开发证据与验证范围说明，不读取保留测试结果，不判定冠军或达标资格。

本文回答“如果后续实现保留这些路线，哪些行为必须明确”。质量排名及资格判定由独立的
[开发报告](2026-10-04-dev-comparison.md)、[固定验证报告](2026-10-04-validation-results.md)
和已冻结的[筛选规则](../testing/evaluation-config-v1.md)维护。验证范围为完整分母
151、章03/14/23；这里说明实现边界，不替代该报告的质量与资格结论。
详细安装与诊断过程见[Whisper 执行记录](2026-10-04-whisper-execution.md)。

## 固定配置与模型身份

两种模型的本地资产获取、许可与完整性证据由[资产记录](2026-10-04-model-assets.md)维护。
当前对应 manifest 为 `.local/manifests/model-faster-whisper-large-v3.json` 和
`.local/manifests/model-wav2vec2-large-xlsr-53-japanese.json`。模型只在获取阶段下载。

| 项目 | 本轮实际冻结身份 |
| --- | --- |
| ASR checkpoint | `Systran/faster-whisper-large-v3`，revision `edaa852ec7e145841d8ffdb056a99866b5f0a478`，MIT |
| 日语 CTC checkpoint | `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`，revision `cf031e020336460d15a417eba710bbc5bb43be9a`，Apache-2.0 |
| W0 环境 | CPython 3.12.15；faster-whisper 1.2.1；CTranslate2 4.8.2；完整解见 [requirements-w0.lock](../../experiments/whisper/requirements-w0.lock) |
| W1 环境 | CPython 3.13.16；WhisperX 3.8.6；faster-whisper 1.2.1；CTranslate2 4.8.2；Torch/torchaudio 2.8.0+cu128；torchvision 0.23.0+cu128；Transformers 4.57.6；pyannote-audio 4.0.7；完整解见 [requirements-whisperx.lock](../../experiments/whisper/requirements-whisperx.lock) |

W1 稳定包限制 Torch/torchaudio `~=2.8.0`，所以采用该兼容解；4.57.6 是本轮已验证的
Transformers 4.x 基线，不声称它是全项目最新版本，也未证明 5.x 一定不兼容。
环境与权重 revision 在比较途中没有升级。独立环境避免与使用另一 Torch/Transformers
版本的 Qwen 流程互相改变依赖。

| 配置 | ASR 与前处理 | 时间来源与明确参数 |
| --- | --- | --- |
| W0 原生对照 | CUDA:0 float16，日语 transcribe，beam5；普通 faster-whisper；VAD off；context on；温度 fallback `[0,.2,.4,.6,.8,1]` | 原生 word timestamps；stable 默认 chunk30 s；早期首次参数记录未显式 chunk，后续显式传30，差异保留在原 manifest |
| W0 无前文 fallback | 同模型/精度/beam；VAD off；`condition_on_previous_text=false`；保留 fallback；chunk30 s | 原生 word timestamps；配置 ID `fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback` |
| W1-native 原生对照 | WhisperX 原生 Pyannote VAD，onset/offset0.500/0.363，CUDA float32；ASR CUDA float16，beam5，batch1，chunk30 s | 日语 CTC CUDA float32；padding0；nearest；原 API chars/words/cues |
| W1 复用 W0 组件 | 保存 W0 无前文 original segments；不再执行 ASR/VAD；只使用预测窗口，padding0 | 同原生 CTC；配置 ID `wx386-jactc-cuda-fp32-nearest-pad0-reuse-w0-ctx-off` |
| W1-native 规范化标准 CTC | 原生 ASR/VAD不变；每个预测窗口按 checkpoint 官方 feature extractor 规范化；同一个 CTC 模型/forward | 显式 `--ctc-normalize --ctc-forced-align`；标准 CTC 非 blank token 跨度；配置 ID `wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda` |

W0 的温度 fallback 不可直接套用到 W1-native：WhisperX 的 batch generator 实际向 CT2
传入 beam、patience、length/repetition penalty、suppress 与 no-repeat 参数，并非普通
faster-whisper 的多温度重试流程。结果中的 `asr_options` 是完整配置对象，
`generator_effective_keys` 才明确列出该稳定实现实际使用的键。后续参数接口必须报告
实际生效范围，不能因为对象存在某字段就宣称它参与了解码。

## 原生 Windows、设备与运行组件

已测主机为 Windows 11 build26200、RTX5080、驱动616.92。证据是实际模型调用，
不是仅有 `nvidia-smi` 或 `torch.cuda.is_available()`。W0 的 CT2 实例报告 CUDA 与
float16；W1 分别检查 CT2 ASR、Pyannote 参数/forward 输入和 CTC 参数/forward 输入。
标准 CTC decoder 另记录输入/输出均为 CUDA:0，它是新增解码算法，不是新增神经模型。
CPU 合成测试可以运行该 decoder，但正常 demo 入口始终请求 CUDA，没有失败后切换设备。

可核对的开发入口与证据：

- `.local/results/w1native-smoke-cuda-r1/result.json`：60 s，ASR CUDA float16、VAD4次/CTC1次 CUDA float32。
- `.local/results/w1native-ch01-cuda-r1/result.json`：239.551 s，VAD16次、CTC6次 CUDA forward。
- `.local/results/w1native-ch07-ctc-normalize-forced-r1/result.json`：同 CTC emissions 上9次新 decoder CUDA 输出，无 decoder failure。
- `.local/results/w0-ch07-cuda-no-context-r1/result.json`：CT2 device CUDA、device_index0、compute_type float16。
- 各同名 `manifest.json`：命令、平台、独立子进程、GPU采样、字幕身份及源码快照。

上述证据只覆盖所测主机、精度和模型。不能扩展为所有 Windows、所有 driver、int8、其他
GPU或所有算子都已验证。音频读取、标准化、时间映射与原版 trellis/结果处理仍有 CPU 工作。
普通 faster-whisper 的可选 Silero VAD 在稳定源码中使用 CPUExecutionProvider；本轮 W0
固定 VAD off。需要该原生前处理时必须单列其设备，不能安装 ORT GPU 包后就声称它已在 GPU。

CT2 所用运行组件来自已完成的官方 PyTorch CUDA12.8 Windows wheel，保存在
`.local/tools/whisper-runtime-provisional`；目录历史名称不等于当前验证状态。
`acquisition.json` 当前为 verified，11个文件逐项 SHA256 与完成 wheel 一致：cuBLAS、
cuBLASLt、cuDart，以及 cuDNN9 的主库/adv/cnn/ops/graph/heuristic/两种 engines。
cuDNN 有版本资源的文件记录9.10.2.21；部分资源为 null，不能凭同目录补造版本。
cuBLAS/cuDart 的 Windows 文件版本原值与 SHA 保存在 manifest，不把该资源字符串误译为
另一组 CUDA release。早期结果内 provisional 快照保留，后续通过同 hash 追认获取完整性。

目前只改变进程内 DLL 搜索路径，没有以运行成功证明系统 CUDA Toolkit 是必需依赖。
正式打包应采用可追溯 runtime 来源、检查实际加载路径/版本、完整依赖和可再分发许可，
不长期依赖临时提取目录或系统 PATH 中的同名 DLL。现有机器其他软件的分散 DLL 没有
用作基线；不应把这份本机观察推广为其所有安装包都不完整。

开发五章的全设备采样最大范围：W0 原生6,450–7,687MiB、无前文6,098–7,540MiB；
W1原生与规范化完整流程最大约6,938MiB。采样约每秒一次，包含桌面基线，不能叫准确
进程峰值或最低 VRAM 要求。组件阶段约4.4GiB的采样值不包含已退出上游ASR，不能冒充
组合端到端峰值。每章为新进程且探索中可并行 CPU/网络准备；启动耗时、阶段和模型驻留
策略必须与稳态吞吐分开。详细速度与显存表只以开发报告的固定范围为准。

## 已定位的 CTC 时间机制

原版 WhisperX `backtrack` 把 blank stay Point 附给当前 token，`merge_repeats` 把它们
合入字符跨度，平均 score 也包含 blank 概率。CPU反例中 token A 仅一个 emission frame，
仍返回2.02 s、高score0.9997的跨度；真实 ch07/cue-0258 最后字有709个 blank stay frame。
因此原版 char score 高不证明声学时间正确，调 nearest/linear 的 word/sentence 插值不能
修复已经生成的 raw char 跨度。

`--ctc-nonblank-only` 仅是诊断：同一原生路径中截取 token transition 一个真实 frame，
标明 `ctc_transition_frame_interval`，不称字符发声时长。它解释部分长尾，但 ch01 仍有
低 token emission probability 的多秒错误放置。不得将该单帧办法作为生产字持续时间。

checkpoint `do_normalize=true`，原版 WhisperX 直接 forward 原 waveform。独立的
[ctc_audio.py](../../experiments/whisper/ctc_audio.py) 调用冻结官方 Wav2Vec2FeatureExtractor，
按窗口 float32 `(x-mean)/sqrt(var+1e-7)`；少于400 samples的原生右零padding不计入统计，
由有效 attention length 恢复padding零。模型仍沿用原版不传 attention_mask，避免把
attention-mask变化混成归一化因素。CPU测试与官方 extractor逐元素完全一致，实际forward
检查原 slice hash，记录归一化后float32 hash、sample范围、长度、设备和源码身份。

[ctc_forced.py](../../experiments/whisper/ctc_forced.py) 继续使用同次 emission与完整目标文本，
调用 TorchAudio2.8 `forced_align` / `merge_tokens` 的标准 CTC 路径：允许 token self-loop，
排除 blank，并对重复 token要求分隔。输出是模型支持的非blank token帧跨度，
`time_semantics=ctc_nonblank_token_span`；仍不能仅凭 SRT 得分称为人工声学持续时间。
沿用原版搜索窗口 `duration/emission_frame_count` 到秒的比例和3位小数，没有凭参考
边界选路径、添加最短时长、整体offset拟合或事后截断长字。

开发 ch07 归一化仅把最大起点差7.752降到0.539 s，末端最大差仍13.979 s；再用标准 CTC
后末端最大0.562 s。ch01组合仍有16.345 s的条件P95。五章组合的可测覆盖116→109/195，
完整分母<500ms确定成功32→96/195。这些是显示参考观察及机制对照，不是推荐或达标判定。

词表外 wildcard 在当前 WhisperX3.8.6 使用附加的 max-nonblank emission列和正 target ID，
不是旧接口的 -1。它可约束路径，但不能证明具体字符的声学匹配。新分支保留该路径锚点，
拒绝其词法时间，原文仍存在；decoder失败、目标不一致或缺少证据同样 text-only。
七个开发跨度因此由可测变无词法时间，属于诚实覆盖下降。不能删字提高分数，不能用
待测ASR补真值，也不能把这些无时间内容从最终展示中悄悄丢弃。

原生 aligned chars/words/cues保存在 `native`，原评测单位保存在 `native_evaluation`；
新分支根级units使用派生字符跨度，原cues/words没有偷偷重写。后续 writer 应显式选择
时间策略，分别报告字幕覆盖与未渲染文字；sidecar保留全文不等于SRT已显示全部内容。
统一显示规则见[显示契约](../testing/demo-display-contract.md)。

## 升级与生成稳定性边界

TorchAudio2.8 `forced_align` 已deprecated，官方说明2.9移除。这里固定版本是为复现实验，
不是长久依赖决定。后续需选择受维护、Windows CUDA已测的decoder，并以同 emissions、
重复token/OOV、真实输入故障与时间映射回归验证等价性；不能静默升级或临时回退CPU。
当前 `decoder_source_sha256` 指向deprecation wrapper；真正 `_alignment.py`、wrapper及
native .pyd 身份在 `.local/analysis/whisper/torchaudio-decoder-source-identity.json` 补齐，
开发r7 source registry已绑定这份补充。正式配置应直接保存完整调用链/扩展身份。

已观察并保留的生成风险不作为新的任意CER门槛：W0原生context流程 ch01有四字单位跨
12段重复，ch17有双字单位34次重复，压缩率分别6.5/23.526；尚未听辨时不把所有重复
直接宣称为声学幻觉。无前文fallback开发五章没有同类超压缩观测，但没有覆盖所有输入。
无前文且固定temperature0则在ch05生成单字符连续444次、compression55.625，属于明确
generation_loop_unresolved，不应作为稳定工程配置采用。fallback仍标记过度重复，但单一
temperature耗尽尝试后返回失败候选；高avg_logprob不能消除循环。原始结果、文字、
分数与失败证据全部保留，不继续沿这条方向无界调参。

## 后续实现应保留的小边界

| 边界 | 当前证据与后续要求 |
| --- | --- |
| 获取 / 推理 | 本地模型、固定revision和runtime单独获取/校验；推理设置offline/local-only、关闭pyannote/HF遥测，先检查NLTK资源。未做系统网络封锁，不宣称已有完全断网证明 |
| 音频 / 坐标 | 目前只接受预备16kHz/mono/PCM16 WAV，保存文件与PCMhash；offset恢复源秒。产品引入任意格式、resample/VAD/chunk需单独记录映射与取消/故障，不覆盖D:\movie源 |
| ASR / aligner | 两阶段实际设备独立证明。ASR对象释放后加载CTC；组件严格核对保存PCM与offset，Qwen桥接另核对文字和上游设备。缓存ASR不计新ASR推理或新端到端性能 |
| 原文 / 时间 / 显示 | 原连续文字及半开char offset保留，合句/拆句不影响文字；无证据时间为null，失败留全分母。formatter不可根据显示需求暗改模型时间或丢弃困难内容 |
| 运行清单 / 恢复 | 新输出ID、不可覆盖；冻结命令、模型、环境、源码与输入身份。现有helper若异常先保留失败记录；正式恢复必须校验配置/阶段完成身份，不能只检查文件存在 |
| 性能 / 生命周期 | GPU队列串行；分别记load、ASR、FA与copy成本；正确处理Windows取消、OOM、进程退出、GPU释放和批次中断。需测长音频边界连续性、常驻复用、重复性能和进程内存，短章成功不替代这些检查 |
| 验证 / 采用 | 当前16项Whisper CPU测试在冻结环境全部执行；轻量root环境明确跳过11项后端依赖测试。跳过不是成功推理证据。后续新decoder、attention mask、精度、batch、VAD或去噪各是新配置，保持开发/验证/保留边界与规则冻结 |

这些要求只描述可复现的模型边界，不提前形成UI、流式框架或通用平台。当前实验性
pass-through wrapper/pre-hook可回答有限机制问题；正式代码应有显式输入转换、decoder
接口和异常生命周期，避免进程级函数替换污染并发会话。还需要实际加载DLL路径证明、
hash变更检测、离线网络约束、隐私日志审查和长音频测试。字幕声学资格仍需独立听辨/
标注；无法执行该工作时明确保留限制，不能用当前候选输出生成“真值”。

## 复现与一手来源

以下为原章07开发配置的重新推理入口，需要已获取资产且GPU队列空闲；新目录不能存在。
本文编写没有执行GPU。完整旧参数以 `.local/results/<run-id>/manifest.json` 的command和
source快照为准；统一harness会冻结源码、保护字幕hash并记录采样。

```powershell
.local/envs/whisper-w0-py312/Scripts/python.exe experiments/whisper/run.py --route W0 --audio .local/audio/chapter-07.wav --offset 1438.427 --model .local/models/faster-whisper-large-v3 --no-condition-previous --chunk 30 --output .local/results/engineering-w0-ch07-recheck/result.json --dll-dir .local/tools/whisper-runtime-provisional
.local/envs/whisper-latest/Scripts/python.exe experiments/whisper/run.py --route W1-native --audio .local/audio/chapter-07.wav --offset 1438.427 --model .local/models/faster-whisper-large-v3 --align-model .local/models/wav2vec2-large-xlsr-53-japanese --ctc-normalize --ctc-forced-align --output .local/results/engineering-w1-ch07-recheck/result.json --dll-dir .local/tools/whisper-runtime-provisional
.local/envs/whisper-latest/Scripts/python.exe -m unittest discover -s experiments/whisper -p 'test_*.py' -v
```

一手来源均为本轮2026-10-04已核查资料，本文未追加新网络调研：

- [faster-whisper1.2.1](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)、[GPU要求](https://github.com/SYSTRAN/faster-whisper#gpu)、[稳定transcribe源码](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)。
- [WhisperX3.8.6依赖约束](https://github.com/m-bain/whisperX/blob/v3.8.6/pyproject.toml)、[ASR源码](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/asr.py)、[alignment源码](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py)。
- [CT2 large-v3模型](https://huggingface.co/Systran/faster-whisper-large-v3/tree/edaa852ec7e145841d8ffdb056a99866b5f0a478)、[日语CTC checkpoint](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/tree/cf031e020336460d15a417eba710bbc5bb43be9a)、[归一化配置](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/resolve/cf031e020336460d15a417eba710bbc5bb43be9a/preprocessor_config.json)。
- [官方PyTorch CUDA12.8 wheel源](https://download.pytorch.org/whl/cu128)、[forced_align2.8接口及弃用范围](https://docs.pytorch.org/audio/2.8.0/generated/torchaudio.functional.forced_align.html)、[merge_tokens2.8语义](https://docs.pytorch.org/audio/2.8.0/generated/torchaudio.functional.merge_tokens.html)。
