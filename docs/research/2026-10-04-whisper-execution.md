# Whisper 路线执行基线

> 2026-10-05 后续开发入口：本页记录旧路线的准备与运行方式。运行或修改当前 W0 时，使用并更新 [W0 demo](../../experiments/w0_demo/README.md)；旧环境可复用，旧 ASR／CTC runner 不作为当前 W0 的默认实现。

状态：探索中；W0/WhisperX 环境、适配器与离线合成测试已准备，真实 GPU 证据由主任务统一记录  
最后更新：2026-10-04  
范围：原生 Windows 上 large-v3 的 W0、W1-native 与固定文字 W1；本记录不构成正式选型。

关联：[执行方案](../plans/local-stt-demo-selection.md)、[评测标准](../testing/subtitle-timing-benchmark.md)、[既有就绪性研究](2026-10-03-whisper-demo-readiness.md)。

## 本轮重新核对的官方基线

2026-10-04 访问 GitHub 官方 release API、官方源码及 PyPI 发布元数据，稳定版仍为
faster-whisper 1.2.1、WhisperX 3.8.6、CTranslate2 4.8.2。main/master 与稳定版不同，
本轮使用稳定包；最新 main 的未发布功能不作为实际能力。

| 项目 | 冻结身份 | 一手来源 |
| --- | --- | --- |
| faster-whisper | 1.2.1；发布 2025-10-31 | [Release](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)、[PyPI](https://pypi.org/pypi/faster-whisper/json) |
| WhisperX | 3.8.6；发布 2026-05-25；wheel SHA256 `cb6d4fcd3fb6c42305cb8b222a33a0b78f6b657e9db3b714345fe43dc0a69c1f` | [Release](https://github.com/m-bain/whisperX/releases/tag/v3.8.6)、[PyPI 元数据](https://pypi.org/pypi/whisperx/3.8.6/json) |
| CTranslate2 | 4.8.2；发布 2026-08-31 | [Release](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.8.2) |
| CT2 large-v3 | `Systran/faster-whisper-large-v3`，revision `edaa852ec7e145841d8ffdb056a99866b5f0a478` | [官方转换模型](https://huggingface.co/Systran/faster-whisper-large-v3)、[revision API](https://huggingface.co/api/models/Systran/faster-whisper-large-v3) |
| 日语 CTC | `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`，revision `cf031e020336460d15a417eba710bbc5bb43be9a` | [模型卡](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese)、[revision API](https://huggingface.co/api/models/jonatasgrosman/wav2vec2-large-xlsr-53-japanese) |

模型卡分别标注 MIT 与 Apache-2.0。模型资产由独立资源任务供给，适配器只接收本地目录；
真实运行 manifest 自动附上 `.local/manifests/model-<directory-name>.json` 的获取和哈希证据。

WhisperX 稳定包限定 torch/torchaudio `~=2.8.0`、torchvision `~=0.23.0`、HF hub `<1.0.0`，
所以本路线采用官方 CUDA 12.8 的 torch 2.8.0 系列；不是无理由继承旧 Torch。
[稳定源码](https://github.com/m-bain/whisperX/blob/v3.8.6/pyproject.toml)的 uv Windows marker
没有覆盖 `AMD64`，本实验显式使用 [PyTorch CUDA 12.8 官方索引](https://download.pytorch.org/whl/cu128)，
不依赖其自动源选择。

当前 Transformers 最新稳定版为 5.18.0；本路线拟冻结最新 4.x 稳定版 4.57.6，
因为 WhisperX 稳定实现仍使用 4.x 的 Pipeline/Wav2Vec2Processor 接口。
这是已验证导入的兼容基线选择，而非声称 4.57.6 是整个 Transformers 的最新版本，
也不构成 5.18.0 必定无法运行的证据；CTC 真实推理仍需验证。
来源：[稳定 ASR 源码](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/asr.py)、
[对齐源码](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py)、
[Transformers 元数据](https://pypi.org/pypi/transformers/json)。

## 已实现入口与有效行为

适配器：[experiments/whisper/run.py](../../experiments/whisper/run.py)。W0 独立环境为
`.local/envs/whisper-w0-py312`，Python 3.12.15；全部解析版本保存在
[requirements-w0.lock](../../experiments/whisper/requirements-w0.lock)。
W1/W1-native 独立环境 `.local/envs/whisper-latest` 使用当前可下载的 Python 3.13.16，
已安装并通过导入与 `uv pip check`，不与 Qwen 共用 Torch 或依赖解。最初的 3.13.2 临时环境只负责完成已开始的
CUDA wheel 获取，新环境复用同一 package cache，避免从头重下 3.2 GiB。
完整 104 个解析包版本见 [requirements-whisperx.lock](../../experiments/whisper/requirements-whisperx.lock)。
其中 torch 2.8.0+cu128、torchaudio 2.8.0+cu128、torchvision 0.23.0+cu128、
Transformers 4.57.6、pyannote-audio 4.0.7、torchcodec 0.7.0、HF hub 0.36.2。

```powershell
$env:UV_CACHE_DIR = '.local/cache/whisper-uv'
uv pip install --python .local/envs/whisper-latest/Scripts/python.exe -r experiments/whisper/requirements-whisperx.lock --index https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match
```

上述复现入口消费已冻结版本，另需事先用本轮对应 Python 创建 uv 环境；不负责模型获取。

```powershell
.local/envs/whisper-w0-py312/Scripts/python.exe experiments/whisper/run.py --route W0 --audio .local/audio/fatestay-dev-smoke.wav --offset 10 --model .local/models/faster-whisper-large-v3 --output .local/results/w0-dev-smoke-native.json --dll-dir .local/envs/whisper/Lib/site-packages/torch/lib
```

DLL 参数仅设置进程内搜索路径，不修改系统 PATH。上述 Torch DLL 目录须等待环境安装完成。
CT2 最新版需要 CUDA 12 cuBLAS、cuDNN 9；[faster-whisper 官方 GPU 要求](https://github.com/SYSTRAN/faster-whisper#gpu)
与部分 CT2 安装文字存在历史差异，以实际 wheel 和已加载 DLL 的成功推理为最终证据。

- W0 保留普通 faster-whisper 推荐路径：CUDA float16、large-v3、日语 transcribe、beam 5、
  原生词时间；默认 VAD 关闭、前文 conditioning 保留、温度 fallback 保留。
  实際 `TranscriptionInfo`/options 完整入结果；`--no-condition-previous`、
  `--temperature-zero` 是另标识的受控配置。`--chunk` 实际传入 `chunk_length`，默认 30 秒。
  stable Silero VAD 在 [vad.py](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/vad.py)
  中硬编码 `CPUExecutionProvider`；若明确运行 `--vad`，结果记录实际 ORT providers，
  不能把该原生前处理算作 GPU VAD。原生普通流程默认关闭 VAD，当前基线不受影响。
  ASR 仍强制 CUDA。独立新增 VAD 模型属于另一个配置，必须另行核对执行设备；
  不能只安装 ONNX GPU 包就宣称 stable provider 改变。
- W1-native 保留 stable 的 Pyannote VAD、30 秒合并窗口和默认 decoding。
  默认 batch 1 用于初次显存预检；明确记录 batch，后续性能调整另外计次。
  保存 ASR 前对齐 region 和最终字时间，先删除 ASR 对象再加载 CTC。
  默认 Pyannote VAD checkpoint 已在 WhisperX wheel 内，无需再次下载该权重。
  根据开发片段弱短呼声遗漏，另暴露 `--vad-onset` / `--vad-offset`：缺省均为 None，
  保留 0.500/0.363；仅显式指定时作为 `load_model(vad_options=...)` 传入。
  实际 `_vad_params` 和显式覆盖均记录，W0/W1 不接受该覆盖。
  0.35/0.20 是主任务下一次有界消融，不预先声称更好；需同步检查新增音乐/静音幻觉。
  stable Pyannote 返回原始 segmentation scores，实际阈值作用于 `merge_chunks` 的
  `Binarize`，不能只读取 underlying pipeline 的默认 threshold 属性。
- W1 读取保存的 W0 original segments，严格核对 PCM SHA256；搜索 padding 为
  0/0.25/0.5 秒可选参数，只基于预测区间，不用参考字幕边界。
- 两种对齐路线默认 nearest 插值；支持 linear/ignore，保留完整 chars 和未定时文字。
  stable API 不能完整辨别每个返回时间是否来自 wildcard、插值或回退，因此统一标记 API 来源，
  不声称每一个时间都来自成功 CTC 路径。
- 仅接受预备的 16 kHz 单声道 PCM16 WAV，显式转换为 float32；文件与 PCM 分别记录 SHA256。
  原文连续保存，词/字 offset 映射到原始文字；句子合并/拆分不改变文字。
  找不到映射或缺少字时间时保留 text-only，不删除困难内容。
- `--offset` 恢复源时间。native 结果仍保留片段相对秒数，统一 `units`/`cues` 为源秒数。
  原生文字、词、字、segments、实际参数、设备与加载/推理阶段时间同存 JSON。
- GPU-only：CT2 实例实际 device 检查、CTC 模型与 forward 输入 hook、Pyannote forward hook
  分别保存设备证据。未有实际 forward 的模型仅算已加载，不算执行成功。

NLTK 3.10.3 与 `punkt_tab` 已在获取阶段安装/下载到 `.local/cache/whisper-nltk`。
适配器提前检查，避免 stable 对齐函数在离线推理时自行下载。
HF/Transformers 设为 offline，CT2 和 CTC 均 local-only；离线环境参数不是网络隔离证明，
正式证据还需本地重载和实际推理。最新 pyannote-audio 默认启用使用情况遥测，
适配器在导入前设置 `PYANNOTE_METRICS_ENABLED=0` 与 `HF_HUB_DISABLE_TELEMETRY=1`；
不把关闭 HF 模型下载误认为同时关闭所有第三方遥测。设备结果也保存 CTC/VAD dtype 和
WhisperX wheel 内 VAD checkpoint 的 SHA256。
来源：[pyannote 4.0.7 metrics 源码](https://github.com/pyannote/pyannote-audio/blob/4.0.7/src/pyannote/audio/telemetry/metrics.py)，访问 2026-10-04。

## 当前验证与限制

五项无 GPU 合成测试通过：合句/拆句字映射不变、完整文字分母、重复文字单调匹配、
缺失字时间保留、无法映射的空格不丢失。命令如下：

```powershell
.local/envs/whisper-w0-py312/Scripts/python.exe -m unittest discover -s experiments/whisper -v
```

这些测试不证明 large-v3、VAD、CTC 可在本机执行。本准备任务未执行 GPU 推理，
不据此给出时间精度、识别质量、速度或显存结论。主任务统一调度的真实运行和错误诊断归入整体报告；
筛选与保留集结论归属于整体评测报告。

主任务随后执行 W1-native；本任务已只读复核两份结果 JSON 的实际设备、forward 与阶段时间，
没有仅复述另一 agent 的结论：

| 主任务运行 | 输入 | ASR | VAD forward | CTC forward | adapter 总时间 |
| --- | --- | --- | --- | --- | --- |
| `w1native-smoke-cuda-r1` | source 10–70 s，60 s | CT2 CUDA0 float16 | 4 次 CUDA float32 | 1 次 CUDA float32 | 28.171 s |
| `w1native-ch01-cuda-r1` | source 10–249.551 s，239.551 s | CT2 CUDA0 float16 | 16 次 CUDA float32 | 6 次 CUDA float32 | 20.615 s |

两次均记录实际 VAD onset 0.500 / offset 0.363。JSON 位于
`.local/results/<run-id>/result.json`，不提交私有全文。首次短片 ASR 阶段 15.820 s，
第二次长片 5.220 s，说明首次初始化/缓存状态可影响阶段用时；这些不同输入、冷启动次数和
上下文条件不能作公平速度排名，也不是无缓存三次重复性证据。主任务已发现短弱呼声遗漏，
GPU 执行通过不能当作识别完整性或时间目标通过。

已检查机器现有 Subtitle Edit 运行组件：WhisperX 包下只有 cuDNN 9.10.2.21 的
`cudnn64_9.dll`，缺少同版本 ops/cnn/adv/engines 等依赖；Crisp 包提供 cuBLAS12/cuDart12。
因此暂不以这些分散组件作为 W0 正式基线，等待官方 PyTorch wheel 的完整 DLL 集。
这属于本机只读观测，不是对所有 Subtitle Edit 包的断言。官方 NVIDIA PyPI 另提供
Windows cuBLAS 12.9.2.10（约 553 MB）与 cuDNN 9.27.0.42（约 743 MB），作为获取受阻时的
备选；目前没有追加这组重复下载。[cuBLAS 元数据](https://pypi.org/pypi/nvidia-cublas-cu12/json)、
[cuDNN 元数据](https://pypi.org/pypi/nvidia-cudnn-cu12/json)，访问 2026-10-04。

为在整个 Torch wheel 仍下载时推进实验，主任务授权临时复制已经完整关闭 ZIP member 的
11 个 CUDA DLL 到 `.local/tools/whisper-runtime-provisional`。流式解压已前进到后续
cusparse member，所有选取文件大小非零，复制前后源大小不变，源/目标 SHA256 相等。
临时 manifest 最初标明 `provisional`。官方 wheel 已下载完成（获取 33 分 23 秒），
11 个 DLL 已全部逐项 SHA256 对照一致，manifest 已更新 `verified`；
先前保存 provisional 快照的结果可通过相同哈希和最终 manifest 补齐获取证明。该入口为：

```powershell
.local/envs/whisper-w0-py312/Scripts/python.exe experiments/whisper/run.py --route W0 --audio .local/audio/fatestay-dev-smoke.wav --offset 10 --model .local/models/faster-whisper-large-v3 --output .local/results/w0-dev-smoke-native.json --dll-dir .local/tools/whisper-runtime-provisional
```

这里仅提前取得已关闭 member，不修改下载、缓存源或全局环境；本准备任务没有执行 GPU 推理。
结果 JSON 会保存当次 runtime manifest 快照与 adapter 源 SHA256，不能隐去临时获取状态。

## 开发集 CTC 尾部故障诊断

本节仅检查开发章节 01、05、07 的 `w1native-chXX-cuda-r1` 及已冻结的
`score-ref2-eval2.json`，未读取保留集结果。规则为
`nfkc-punctuation-v2-universal-complete-invariant-boundaries`，参考为 scoring-v2 原 SRT 显示时间，
并非人工声学起止。分别有 13/35/44 个可测内容跨度，条件 P95 为 11.984/7.115/4.698 秒。
从合计 92 个可测跨度选择偏差最大的 20 个作故障样本；它们不能当作随机总体或新的独立测试集。

私有逐字材料及可恢复分析在 `.local/analysis/whisper/`：
`worst20-private.json`、`all-measurable-private.json`、`summary.json`、`diagnose.py`。
summary 保存输入结果、评分、参考及实际安装 CTC 源码的 SHA256。本节不复制完整台词。

核查结果：

- 三份实际 WAV 的 PCM SHA256 与推理结果一致；源 offset 分别为 10、920.368、1438.427 秒。
  20 个样本的评测字单位起止均精确等于上游 native char 起止加该 offset。
  未发现这批样本的 adapter 时间恢复错误、输入身份混淆或单位/秒换算错误。
- 15/20 个样本的整段规范化文字完全匹配；剩余五个保留原评分，不删除。
  原生窗口包含 18/20 个 SRT 显示区间；另外两个显示起点只早于窗口 43/10 ms，
  并非 3–14 秒偏差所需的严重截断。50 ms 仅用于此几何核查，未修改评分或声学真值定义。
- 模型词表有 2,341 项，含 2,155 个汉字与 154 个假名；三章规范化候选文字 OOV 为
  1/160、1/642、7/644。最差 20 个样本的 194 个 raw chars 有八个 OOV，其中四个标点、
  两个空白、两个其他字符。因此 OOV 可能解释局部问题，但不解释普遍的多秒尾部。
- 14/20 个样本存在超过 2 秒且 score≥0.9 的单个 native 字区间；15/20 个样本同时存在
  score<0.01 的字符。高 score 不能被用作声学时间正确的证明。
- 字时间在 word/sentence nearest 插值前已经生成；改变 `--interpolate` 不改变这批用于
  主内容时间评分的 raw char 区间。当前没有依据开展插值方式的参数扫荡。

### 已确认的源码语义及具体反例

在 [WhisperX 3.8.6 alignment.py](https://github.com/m-bain/whisperX/blob/v3.8.6/whisperx/alignment.py)
中，`backtrack` 对 blank stay 也添加当前 token index 的 Point；`merge_repeats` 将同 index
的所有 Point 合为字跨度，并把 blank 概率纳入平均 score。因此返回的字跨度包含附着 blank，
score 也不是纯 token 发声置信度。这是已确认的源码时间语义；native API 的结果没有被 adapter 篡改。

CPU 合成反例直接提取实际安装的原版三个函数运行：A 仅在 frame 1 有 token emission，
frame 2–101 为 blank，B 在 frame 102；原版仍返回 A 区间 frame 1–102，跨度 2.02 秒，
score 0.9997。材料为 `.local/analysis/whisper/synthetic_blank.py` 与
`synthetic-blank-result.json`，未调用 GPU 或任何模型。这说明即使音素 emission 很窄，
源码也可以生成较长、高分的字区间。

| 开发反例 | SRT 显示区间（源秒） | 候选内容区间（源秒） | native 字证据 | 解释范围 |
| --- | --- | --- | --- | --- |
| ch07 / cue-0258 | 1580.610–1584.000 | 1580.785–1597.999 | 最后一个词表内字长 14.212 s、score 0.999；前 12 字结束于 1583.787 | 完整文字、场景内唯一该整段文字、窗口包含参考；显著长字与 blank 纳入机制一致 |
| ch01 / cue-0014 | 145.210–146.080 | 133.226–146.310 | 前两字位于 133.226–133.326，最后字长 12.984 s、score 0.998 | 既有开始位置误配，也有跨度吸收；只缩短 blank 不能保证修复早开始 |
| ch05 / cue-0144 | 1039.510–1040.150 | 1039.841–1047.265 | 一个内部字长 7.364 s、score 0.997，其余多个字 score 0 | 同 ID 的 W0 原生词时间偏差仅 0.402 s；SRT 系统性晚七秒不足以解释成对差异 |
| ch05 / cue-0169 | 1135.280–1137.910 | 1128.669–1129.149 | 整段文字完全匹配、仅标点 OOV，多字 score 0 | W0 同 ID 偏差 0.408 s；这是错误声学放置的候选案例，不能仅靠 blank 区间解释 |

真实原运行未缓存 emissions/path，所以尚不能逐项证明每个长字中的实际 blank 数量，
也无法仅靠 RMS 把区间标注为“声学静音”。原 SRT 仍有显示时机不确定性，且 cue-0014
等还可能涉及相同短呼声的语义对应；没有人工听辨，不能宣称全部差值就是真实声学偏移。
但上述唯一文字、成对 W0 对照及源码合成反例足以把下一次试验定位于 CTC 的区间抽取。

另有一个尚未验证的预处理差异：checkpoint 的
[preprocessor_config.json](https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese/resolve/cf031e020336460d15a417eba710bbc5bb43be9a/preprocessor_config.json)
要求 `do_normalize=true`；stable WhisperX 直接调用 model(raw_waveform)，未走 processor 的
零均值/单位方差处理。不能因此就断言它是当前根因。本轮先不同时修改音频归一化。

### 已有组件对照及下一项单因素诊断

只读复核 `w1-ch01-w0nocontext-ctc-r1` 与 `w0-ch01-cuda-no-context-r1`：PCM 与完整文字完全相同，
CER 都为 0.362869；W1 复用 27 个预测区间、padding 0。W0 为 18/28 可测，条件 P95 2.400 s，
完整分母内 <500 ms 成功 6/28；W1 为 20/28 可测、条件 P95 1.379 s、<500 ms 成功 11/28。
这支持细粒度预测窗口有实际价值，且不代表 CTC 普遍差；native W1 的六个宽窗口与该组件
路线同时改变了 ASR 内容和分段，二者不能被解释为仅改变窗口的因果试验。

下一项只检验 blank 附着语义：已实现显式 `--ctc-nonblank-only` 诊断。
它在单次原生 align 调用中用进程内 pass-through 包装器记录原始 backtrack，仍返回完全相同的
原生 path；不修改安装包，不重复 GPU forward，不改变音频、文字、窗口或 baseline。
每个 token group 的第一个 Point 是该原版 recurrence 的 token transition emission，
随后 Point 为 blank stay。派生区间只采用该 emission 对应的一个真实 trellis frame 区间，
沿用原版 `region_duration / emission_frame_count` 到秒的映射及三位小数。
缺少 path/Point 时原文字保留为 text-only；不人为补最短时长。

**该派生区间不是口述字符持续时间。** 元数据固定为
`time_semantics=ctc_transition_frame_interval`、`experimental_not_acoustic_duration=true`、
`time_source=api`；记录源码/helper SHA256、emission SHA256、token transition 和 blank stay 数。
原 native chars/words 保存在 `native`，原可评测单位保存在 `native_evaluation`。
根级 `units` 仅在显式 flag 下采用派生值；`cues` 和最终 writer 输入继续保留原生结果，
避免偷偷把显示效果一起修正。若显示分数变化，应另查 formatter，不能归到该 flag。

九项 GPU-free 测试通过，包括原版 path 不变、默认禁用不包装、失败保留、源 offset 与 blank
stay 合成反例。使用已冻结 WhisperX 环境，主任务按 GPU 队列执行以下单因素试验：

```powershell
.local/envs/whisper-latest/Scripts/python.exe experiments/whisper/run.py --route W1-native --audio .local/audio/chapter-07.wav --offset 1438.427 --model .local/models/faster-whisper-large-v3 --align-model .local/models/wav2vec2-large-xlsr-53-japanese --output .local/results/w1native-ch07-ctc-transition-r1/result.json --dll-dir .local/tools/whisper-runtime-provisional --ctc-nonblank-only
.local/envs/whisper-latest/Scripts/python.exe experiments/whisper/run.py --route W1-native --audio .local/audio/chapter-01.wav --offset 10 --model .local/models/faster-whisper-large-v3 --align-model .local/models/wav2vec2-large-xlsr-53-japanese --output .local/results/w1native-ch01-ctc-transition-r1/result.json --dll-dir .local/tools/whisper-runtime-provisional --ctc-nonblank-only
```

如需在已经较好的组件上检查是否引入新偏差，使用同一 flag 的 W1、同一 chapter-01 PCM、
`--asr-result .local/results/w0-ch01-cuda-no-context-r1/result.json`，选择新的结果 ID。
这里没有使用参考字幕边界做搜索范围。即使派生时间的 SRT 分数改善，也只能证明抽取语义
对显示参考有影响，不能直接宣布“更准确的 forced alignment”或生产可用字幕时长。
第二项依据以下残余证据，已实现独立归一化消融；GPU 测量由主任务排队执行。

### transition 诊断结果与归一化单因素配置

ch01/ch07 的原始 PCM、完整文字及预测搜索窗口均与 baseline 完全一致。
ch07 仍为 44/62 可测，条件 P95 从 4.698 s 到 2.745 s；20 个原来 ≥500 ms 的可测样本
移到 <500 ms，另有三个向相反方向移动，净完整分母成功数为 16→33/62。
cue-0258 最后字的原版跨度包括 709 个 blank stay frame，实际 token transition 概率只有
0.010349；该 cue 显示参考误差由 13.999 s 降到 0.193 s。这次捕获证实了真实长尾中存在
大量 blank 附着，而非仅有合成反例。

残余不是全部由 blank 解释：ch07 / cue-0222 的起点仍早 7.752 s，首/尾 transition 概率
约 2.40e-11 / 5.05e-9；cue-0237 的末端因缩为 transition frame 反而早 4.954 s。
ch01 的条件 P95 为 11.984→12.734 s；cue-0014 前端错位不变、末端更早，其首尾概率仅
0.000349 / 0.000727。该章节四个样本跨入 <500 ms，没有原本 <500 ms 的样本跨出，
但尾部分布仍明显失败。缩短到一个 transition frame 不能替代声学持续时间估计或修复错误匹配。
这些概率来自该位置的 token emission，不能与原版包含 blank 的平均 score 等同。
详细逐 cue 信息与完整私有文字只保存在 `.local/analysis/whisper/transition-audit-private.json`。

显式 `--ctc-normalize` 通过进程内 model forward pre-hook 替换 FA input_values，保留 native
CTC 路径抽取、chars、words、cues 和 ASR 输入。它直接调用冻结 Transformers 4.57.6 的官方
`Wav2Vec2FeatureExtractor`，加载 checkpoint 本地 `do_normalize=true` 配置：
float32 `(x - valid_sample_mean) / sqrt(valid_sample_var + 1e-7)`。
每个预测窗口独立归一化；native 小于 400 samples 的右侧零填充被 attention length 排除于
统计之外，并恢复为零。为了只改变归一化这一因素，模型 forward 仍沿用原版不传
`attention_mask` 的行为；feature extractor 的 mask 仅用于归一化有效长度。

该 hook 逐调用检查原始 slice（含 padding）的 float32 SHA256 与计划窗口一致，记录归一化
后 float32 SHA256、源 sample 范围、有效与填充长度、实际输入设备/dtype、原均值/方差及
feature-extractor/helper 源码 hash。原始 PCM16 身份不变；两种 hash 的表示不可混淆。
归一化准备时间单列；验证所需 GPU→CPU copy 和 replacement transfer 的成本包含在 align_s，
hook 时间另列且不可重复相加。baseline 不装该 hook；安装包未修改。
本轮拒绝同时使用 transition 与 normalization flag，防止混入第二因素。

12 项 CPU 测试通过，包括与官方 processor 的逐元素精确匹配、短窗口 padding mask、源 sample
offset、静音有限值、输入错配失败/移除 hook、ASR 数组未变及 baseline 行为不变。
复现实验采用原命令仅将 `--ctc-nonblank-only` 换为 `--ctc-normalize`，分别写入新的
`w1native-ch07-ctc-normalize-r1` / `w1native-ch01-ctc-normalize-r1` 结果目录。
当前配置是局部 FA 前处理实验，不是正式产品默认决定；不使用参考字幕窗口。

### 标准 CTC token span 扩展与 temperature=0 淘汰证据

归一化消融仍保留原版 blank 合并，因此不能同时修正字符尾部语义。新增显式
`--ctc-forced-align`，可与 `--ctc-normalize` 组合，以同一次 neural forward 的 emissions
调用冻结 TorchAudio 2.8.0 `forced_align`，再通过 `merge_tokens` 保留连续非 blank token 帧。
与单帧诊断相比，这个标准 CTC 路径支持 token self-loop，并要求重复 token 中间有 blank。
新 decoder 请求 CUDA、记录输入/输出实际设备；不加载新模型，不改 native backtrack 返回值，
native chars/words/cues 仍完整保留。所有原文字保留；wildcard OOV 不被冒充词表内字符的
声学证据，根级单位为 text-only；长度不足、路径坍缩不一致及 decoder 失败保留失败记录。
token span 表示模型 CTC 支持帧，仍不能未经听辨就宣称是真实发声持续时间。

16 项 CPU 测试通过，新增连续 token 支持帧、blank 排除、重复 token 分隔、OOV 保留、
短序列失败以及源 offset 测试。GPU 组合试验仅在主任务队列下运行 ch07/ch01，原命令加入
`--ctc-normalize --ctc-forced-align`，使用新的 `ctc-normalize-forced-r1` 结果 ID。
它是两个分别获得诊断证据的机制组合，不构成无目的参数排列。未来实现须处理
[官方 forced_align API 的 2.8 弃用/2.9 移除](https://docs.pytorch.org/audio/2.8.0/generated/torchaudio.functional.forced_align.html)
边界，并复核 [merge_tokens 的原版语义](https://docs.pytorch.org/audio/2.8.0/generated/torchaudio.functional.merge_tokens.html)；
不能直接升级环境后假定该实验 decoder 仍存在。

W0 `--no-condition-previous --temperature-zero` 已发现具体 generation loop：ch05 首段 local
0–28.68 s 的 445 个 raw chars 含一个字符连续重复 444 次，224 tokens，compression_ratio
55.625，avg_logprob -0.0733，no_speech_prob 0.4443。同 PCM 的默认 fallback 首窗口选择
最终 temperature 1.0；首两段仅 4/3 chars，全章 raw chars 为 699，而固定 0 为 1,133。
ch01/ch02/ch07 完整输出文字与 fallback 相同；ch17 另有变化，不能把整个收益/损失都归于
重分句。原版 generate_with_fallback 在 compression_ratio>2.4 时请求重试，但只有一个
temperature 时耗尽尝试后仍返回失败候选；高平均 logprob 没能阻止这个循环。
这是具体、未解决的生成失败，支持停止此方向、按 generation_loop_unresolved 分类；
不是依据新增 CER 阈值任意淘汰，也不把所有较高压缩率或合法重复呼声都判为失败。
全部私有文字/逐段 trace 保存在 `.local/analysis/whisper/w0-temperature-audit-private.json`，
原始结果及正式评分保持不变。

补充 W0 核查：默认 context 流程 ch01 的 12 个连续片段拼接成同一四字单位重复 12 次，
compression_ratio 6.5；ch17 的 17 个连续片段拼接成同一双字单位重复 34 次，ratio 23.526。
关闭 context 且保留默认 fallback 的五章没有 ≥30 次的单字连续重复，亦没有上游
compression_ratio>2.4 的返回片段。这个限定样本支持 no-context 对已观察循环有效，
不等于对所有未见输入提供无幻觉保证。

### 两章局部机制试验的独立复核

以下全都保持同章完整 ASR 文字、PCM 身份、搜索窗口和完整分母，使用同一 scoring-v2
显示参考；P95 仅在可测样本中计算，不是全分母达标率。standard CTC 显式拒绝 wildcard
作为词表内声学证据，所以 n 的下降必须计入失败而不可删除相关参考。

| 章节 / 配置 | 可测 / 完整分母 | <500 ms / 完整分母 | 条件 P95 (s) | 起点最大绝对差 (s) | 末端最大绝对差 (s) |
| --- | --- | --- | --- | --- | --- |
| ch01 / 原生 | 13/28 | 1/28 | 11.984 | 11.984 | 8.606 |
| ch01 / transition 诊断 | 13/28 | 5/28 | 12.734 | 11.984 | 12.734 |
| ch01 / 仅 normalize | 13/28 | 2/28 | 16.345 | 16.345 | 16.278 |
| ch01 / normalize + standard CTC | 12/28 | 7/28 | 16.345 | 16.345 | 6.895 |
| ch07 / 原生 | 44/62 | 16/62 | 4.698 | 7.752 | 13.999 |
| ch07 / transition 诊断 | 44/62 | 33/62 | 2.745 | 7.752 | 4.954 |
| ch07 / 仅 normalize | 44/62 | 19/62 | 3.097 | 0.539 | 13.979 |
| ch07 / normalize + standard CTC | 39/62 | 37/62 | 0.539 | 0.539 | 0.562 |

ch07 的归一化改变开始放置，原生 blank 附着尾部仍存在；standard CTC 再减少尾部偏差。
ch01 则仍有多秒放置失败，不能据一章较好就宣布全面达到时间目标。表中 reference 均是
未经声学复核的 SRT 显示时间。组合两章的所有新 decoder 记录为 CUDA:0（6/9 次），
没有 decoder failure；OOV wildcard 为 9/32 个，作为 text-only 保留。

这批 frozen result 的 `decoder_source_sha256` 实际来自 deprecation wrapper 模块
`torchaudio/_internal/module_utils.py`。另行补充
`.local/analysis/whisper/torchaudio-decoder-source-identity.json`，包含该 wrapper、真正的
`functional/_alignment.py`（SHA256 `e3a1a1b84614a88d6013ed94292bbd048405d50a59e72ba7512f09646649bacb`）
及安装 native .pyd 的 hash；此记录不改变结果、配置或源码冻结。
align_s 的冷启动开销与 GPU→CPU 验证 copy 已包含在各次结果，不以这两章的单次 stage
时间推断稳态吞吐优势。完整数据为 `.local/analysis/whisper/ctc-factor-comparison.json`。
