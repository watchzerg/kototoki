# STT worker：VAD／ASR（w0／x0）／对齐

状态：current（票据 03 交付，x0 适配器票据 07 交付，2026-10-14）；编排器接入见[批次编排](batch-orchestration.md)（票据 06）。本页描述已存在的推理模块与 worker 壳。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)）的三个 GPU 阶段：从 `audio-16k.wav` 求 VAD 窗口（`vad.json`）、逐窗转写（`asr.json`）、字符级强制对齐（`align.json`）。不负责：决定哪些文件要跑或跳过、锁、子进程环境与按文件重启（编排，票据 06）；cue 切分与时间回填（[日文 cue](japanese-cues.md)）。推理逻辑复制自研究期实现，那里的行为说明仍有效：[外部 VAD 阶段](vad-stage.md)、[W0 pipeline](w0-pipeline.md)、[X0 pipeline](x0-pipeline.md)、[MMS 对齐](mms-alignment.md)；本页只写产品侧的差别与接口。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**分两层**：推理模块（`kototoki/vad.py`、`asr_whisper.py`、`asr_qwen.py`、`align.py`）只做"加载一次、按窗口推理"，输入输出是内存对象与 WAV 本地坐标，只依赖基础层、互不导入，不读写产物、不判断跳过、不打印；worker 壳（`kototoki/workers/{vad,asr,align}.py`）负责读输入、重验上游身份、组装 payload、身份与 `failed_windows` 记账，经 `protocol.run_worker` 运行，`__main__` 两行。三壳共用的命令行入口、读 WAV、模型文件核对、CUDA 守卫与写产物在 `kototoki/workers/gpu.py`。壳模块导入时不加载 torch 等推理库（推理模块在 `start` 里才导入，有测试钉住），编排器可以直接导入壳里的 `identity`／`model_files`／`recipe_hash` 计算期望身份。

**jobs 约定**（2026-10-14 用户认可；在协议的 `{"stage", "recipe_hash", "config", "files"}` 之上）：`recipe_hash` 必须等于该 worker 写进身份的配方 hash（VAD、MMS 各一个，ASR 按引擎），否则启动失败；`config` 需要 `models`（`Config.models` 的同名键，路径字符串：`vad`、`w0`、`w0_mel_assets`、`x0`、`align`）、`model_cache`（`.work/cache/model-verification.json`），ASR 另需 `engine`（`w0` 或 `x0`，其它值启动失败；w0 只读 `w0`／`w0_mel_assets`，x0 只读 `x0`）；每个文件的 `inputs`：VAD `wav`，ASR `wav`＋`vad`，对齐 `wav`＋`asr`。

**模型核对**：`start` 加载前用 `artifacts.verify_model`（size+mtime 缓存）逐个核对固定 SHA256：segmentation-3.0 `pytorch_model.bin`；faster-whisper-large-v3 的 `config.json`／`model.bin`／`preprocessor_config.json`／`tokenizer.json`／`vocabulary.json` 与 `w0-assets/mel_filters.npz`；qwen3-asr-1.7b-hf 的 `model.safetensors` 与全部 `.json`／`.jinja`（共 7 个，`README.md` 与下载残留不参与）；mms-1b-all 的 adapter、`model.safetensors` 与 5 个配置／词表文件。期望值取自 W0／X0 基线运行记录，核对结果即身份的 `models` 字段。研究期 X0 在模型加载时自行哈希整个 checkpoint（`checkpoint_identity`），产品不移植，改由壳经产物契约的缓存核对（目标架构：模型 SHA256 经产物契约的缓存）。

**身份**（`artifacts.derived_identity`，`config` 字段为空——这三个阶段没有影响输出的配置键）：

| 产物 | upstream | recipe_hash |
| --- | --- | --- |
| `vad.json` | `audio-16k.wav` = PCM 数据块 SHA256 | `recipes.VAD` |
| `asr.json` | 同上＋`vad.json` 文件 SHA256 | `recipes.W0`（x0 时 `recipes.X0`） |
| `align.json` | 同上＋`asr.json` 文件 SHA256 | `recipes.MMS` |

ASR 与对齐壳读上游产物时重验其 `identity.upstream["audio-16k.wav"]` 等于本次读到的 PCM SHA256，不等即该文件失败。

**产物**（坐标一律 WAV 本地，`offset_s` 从 `recipes.MEDIA` 起逐级照抄，恒为 0）：

- `vad.json`：`schema_version`、`offset_s`、`input`（PCM SHA256、样本数、采样率、时长）、`chunks`（秒、成对整数 `start_sample/end_sample`、子段 `segments`）、`raw_intervals`、`speech_intervals`、`accounting`、`metadata`（设备、dtype、pyannote 窗口参数、包版本）、`stages`（`load_s` 为该 worker 进程的加载耗时，`inference_s` 为本文件）。窗口写出前经 `schema.validate_windows`。
- `asr.json`：`schema_version`、`engine`、`offset_s`、`input`、`chunks`（照抄 `vad.json`）、`original_segments`（与窗口一一对应：`text`、秒与整数样本、`avg_logprob`）、`asr_traces`（引擎自有的诊断：w0 为 tokens、prompt、解码参数、特征 SHA256，x0 为 tokens、`generated_tokens`、`token_limit_reached`、原始输出、检测语言、输入设备与形状证据、PCM SHA256 与逐窗耗时；`RuntimeError` 失败窗口为 `null`）、`failed_windows`、保留文本 `text`、`metadata`、`stages`。
- `align.json`：W0 `result.json` 的结构——`schema_version`、`engine`、`status`、`text`、`units`、`cues`（空）、`original_segments`、`chunks`、`failed_windows`、`alignment_records`、`derived_segments`、`offset_s`、`source_start_seconds`／`duration_seconds`／`source_end_seconds`、`input`、`metadata`、`stages`；不含 `asr_traces`（在 `asr.json`）。写出前要求对齐全文等于 ASR 保留文本，并通过 `schema.validate_transcript` 与 `schema.validate_units`（每字符恰好一个 unit；有时间的 unit 落在源范围内）。

**VAD**（`vad.PyannoteVad`）：要求 pyannote.audio 4.0.7 与 powerset checkpoint，`VoiceActivityDetection` 以 `min_duration_on/off = 0` 实例化，设备固定 `cuda:0`，CUDA 不可用或实际设备不同即失败；输入是内存波形 dict，不经 torchcodec 解码文件，不加 FFmpeg PATH（票据 01 smoke #2）。`chunk_intervals` 只接受秒区间，规则同 `source-span-merge-v1`。

**ASR w0**（`asr_whisper.WhisperAsr`）：模块顶层先 `import torch` 再 `import ctranslate2`、`faster_whisper`（`tests/test_asr_whisper.py` 用伪模块钉住次序），cuDNN 子库因此来自 torch，CT2 自带的 `cudnn64_9.dll` 9.10 调度器与之并存（用户已接受）；不设私有 DLL 目录与 PATH。特征链与解码参数同 W0 契约，参数取自 `recipes.W0`。窗口输入要求整数样本（`schema.validate_windows`）。单窗解码抛 `RuntimeError` 时该窗文字为空、trace 为 `null` 并作为失败窗口返回，壳用 `protocol.fail_window` 记入 `failed_windows`，继续下一窗。CT2 在 sm_120 上靠 PTX JIT：冷启动首窗约 27 s，JIT 缓存命中后加载约 3 s。

**ASR x0**（`asr_qwen.QwenAsr`）：Qwen3-ASR-1.7B-hf，参数取自 `recipes.X0`：CUDA BF16、SDPA、`device_map` 固定 `cuda:0`、原生 `AutoProcessor.apply_transcription_request`（强制日语、16 kHz、不补到 30 s）、greedy、`max_new_tokens` 4096、batch 1、逐窗独立无前文；CUDA 不可用、参数或输入张量不在 CUDA 上即失败。transformers 5.19 下用研究期 trace 的 token 解码，8 窗文字、原始输出与检测语言与 5.18 记录全等。触顶（生成 token 数达到 4096）的窗口：段内保留截断文字、trace 照常记录，并以原因 `token_limit_reached: generated <n> tokens` 作为失败窗口返回，壳经 `protocol.fail_window` 把该窗 `text` 置空、截断文字移入 `failed_windows`，不进对齐、cue 与翻译，失败数进进度行 `failed_windows`；研究期 `validate_asr` 拒绝触顶、`transcribe` 触顶即抛错的整片失败行为不移植（规格 §6）。单窗生成抛 `RuntimeError` 的处理同 w0。段结构与 w0 相同，`avg_logprob` 为 `null`。

**对齐**（`align.MmsAligner`）：与研究期实现的差别只有两处：TorchAudio 要求放宽为 ≥2.10，实际版本记入 `metadata.package_versions`；字典只取 id < `model.config.vocab_size` 的词表项（`align.model_dictionary`），transformers 5.19 的分词器多出的 added token `|`（id 2268）被丢弃并记入 `metadata.dropped_tokenizer_entries`，于是 `character_targets` 对 `|` 的处理与 transformers 4.57 时相同，通配符列号仍为 2268。`map_records(segments, records, offset)` 保留 `offset` 参数，产品传 0。单窗 `RuntimeError`／`ValueError` 记入该窗 `failure`，字符成为 `text_only`。`asr.json` 中被置空的失败窗口没有可对齐字符（`skip_reason = no_eligible_characters`）。

**失败分级**：窗口级见上；单文件异常（读 WAV、身份不符、校验失败等）由协议写 `failure.json`、退出码 1，继续下一文件；`gpu.file_processor` 在 `compute` 抛异常后、以及写产物之前各调用一次 `torch.cuda.synchronize()`，失败即判定为 CUDA 粘性错误，抛 `FatalWorkerError`（不写产物，退出码 2，由编排从下一文件重启）。因此推理模块按窗口吞掉的粘性错误也不会写出"全窗失败"的产物。

## 接口与依赖

推理模块依赖 `recipes` 与 `schema`（基础层）及 torch、pyannote.audio、faster-whisper／CTranslate2、transformers／torchaudio；四者互不导入。`schema` 属基础层，只依赖标准库：`validate_transcript` 复制自 `kototoki_eval/schema.py`（评分包保持不动），另有 `validate_windows`、`validate_units`。壳依赖 `artifacts`、`recipes`、`schema`、`workers/protocol`、`workers/gpu`。子进程环境（`PYTHONUTF8=1`、`HF_HUB_OFFLINE` 等离线变量、`HF_HOME`／`TORCH_HOME = <output_dir>/.work/cache/`）由编排传入，worker 不自行设置（[模块边界：产品包的责任边界](../module-boundaries.md#产品包的责任边界)）。pyannote 与 transformers 的告警和加载进度条写 stderr，不干扰 stdout 上的协议进度行。

## 代码与验证入口

- 代码：`kototoki/vad.py`、`kototoki/asr_whisper.py`、`kototoki/asr_qwen.py`、`kototoki/align.py`、`kototoki/schema.py`、`kototoki/workers/{vad,asr,align,gpu}.py`。
- 测试（core，`just test`）：`tests/test_vad.py`（`chunk_intervals` 取整、裁剪、并集、硬切、贪心合并、秒坐标回整）、`tests/test_align.py`（版本判定、字典过滤 `|`、`character_targets`、`map_records` 的 offset 只加在 units、`normalize_window` 伪提取器、数值作用域恢复）、`tests/test_schema.py`、`tests/test_asr_whisper.py`（导入顺序、逐窗失败）、`tests/test_asr_qwen.py`（伪 processor／模型：配方生成参数、只取 prompt 之后的 token、触顶窗口保留截断文字并返回失败、`RuntimeError` 窗口、模型不在 CUDA 即失败；经壳串到对齐与 `build_cues`：触顶窗口置空、截断文字进 `failed_windows`、不进 cue；x0 模型文件清单与配方 hash）、`tests/test_stt_workers.py`（伪推理对象串起三阶段：身份链、坐标、`failed_windows`、上游身份不符、退出码 0／1／2 与 CUDA 守卫、启动校验、产出能被 `cues.build_cues` 消费、壳导入不加载推理库）。
- 冻结窗口门禁（full，占 GPU，须用户批准）：`just test-full stt_frozen_window`（`scripts/smoke/run_all.py` 持锁并以 `python -m tests.stt_frozen_window --out <dir>` 启动，结果写 `.local/smoke/<UTC>/stt_frozen_window.json`；没有 `.local/gpu.lock` 时脚本拒绝运行；不在 `just test` 发现范围内）。2026-10-14 首次运行（接入 test-full 之前的手动版本，产物 `.local/stt-gate/20261014T070454Z/`；RTX 5080、torch 2.11.0+cu128、torchaudio 2.11.0+cu128、transformers 5.19.0、pyannote.audio 4.0.7、faster-whisper 1.2.1、CTranslate2 4.8.3；输入 `hf-ii-window-01.wav` 300 s；对照 `.local/w0-demo/pyannote-gpu-v1-w0-pyannote-current-hf-ii-window-01/`，其 VAD 来自同为 torch 2.11 的 `vad-pyannote-gpu-v1` 环境，ASR／MMS 来自 torch 2.8 的 `whisper-latest` 环境）：8 个窗口整数边界全等；8 窗文字逐字符相等且 token 序列全等（549 字）；549 个 unit 字符范围与状态全等（25 个 `text_only`），1048 个起止时间与对照（减去其 `offset_s` 351.402125）全等，最大差 0。耗时：VAD 加载 21.2 s／推理 1.4 s，ASR 加载 3.0 s／推理 6.9 s，MMS 加载 14.1 s／推理 2.8 s。
- x0 冻结窗口门禁（full，占 GPU，须用户批准）：`just test-full x0_frozen_window`（`run_all.py` 持锁并以 `python -m tests.x0_frozen_window --out <dir>` 启动），与 `stt_frozen_window` 同法同标准，ASR 取 `x0`，对照 `.local/x0-demo/pyannote-gpu-v1-x0-pyannote-current-hf-ii-window-01/`（ASR 来自 torch 2.14.1+cu130／transformers 5.18 的 `qwen-hf-final` 环境，MMS 来自 torch 2.8）；没有 `.local/gpu.lock` 时拒绝运行。2026-10-14 运行两次（`.local/smoke/20261014T082609Z/`、`20261014T082759Z/`，两次产物逐字节相同；torch 2.11.0+cu128、transformers 5.19.0）：8 窗整数边界全等；7 窗文字与 token 全等，窗口 0 的 38 个 token 中第 2 个不同（一个汉字被另一个汉字替换，字数不变），2026-10-14 用户裁定接受为环境差异（BF16 近平局在 torch 2.11+cu128 与对照的 2.14.1+cu130 之间翻转），票据 07 完成；587 个 unit 字符范围与状态全等（47 个 `text_only`），1080 个起止时间与对照全等，最大差 0；无触顶窗口。整轮约 95 s。Qwen 加载不用研究期的 `device_map`（需要产品环境没有的 accelerate），改为加载后整体 `.to("cuda:0")`。
- 质量回归：[最终验收](../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)——同一评分器下产品 CER 高于基线（w0 II 20.29% 对 16.81%，III 14.24% 对 13.77%），根因为 soxr 派生 WAV 使 VAD 少保留语音；产品 VAD 在 swr WAV 上与基线窗口完全相等，推理代码无差异。
- 整片：[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)——两部电影 × w0／x0，无窗口级失败、x0 无触顶、对齐全部成功。
- 未验证：x0 触顶的真实路径；真实的 CUDA 粘性错误与窗口级 OOM 只用伪对象验证了分级逻辑；多文件 jobs 只有离线测试。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/03-stt-workers.md`、`07-x0-engine.md`；规格 §1.2、§4、§6、§7.1、§7.3、§12；票据 01 smoke #1–#3（`.local/smoke/20261014T045328Z/`）。来源代码：`experiments/w0_demo/vad_candidates.py`（`CurrentPyannoteVad`、`chunk_intervals`）、`experiments/w0_demo/asr.py`、`experiments/x0_demo/asr.py`、`experiments/qwen/run_qwen.py`（`check_gpu`）、`experiments/w0_demo/alignment.py`、`experiments/w0_demo/pipeline.py`（units 不变量）、`kototoki_eval/schema.py`。共用的 CUDA 守卫放在新文件 `workers/gpu.py`（2026-10-14 用户裁定，不改票据 00 的 `protocol.py`）。

目标架构页（`docs/architecture/bilingual-pipeline-architecture.md`，2026-10-14 设计稿）已于票据 08 收口时删除：分层图与不变量并入[架构总览](../INDEX.md)，依赖方向、责任边界与接缝并入[模块边界](../module-boundaries.md)；本模块的接口以本页"接口与依赖"节为准。
