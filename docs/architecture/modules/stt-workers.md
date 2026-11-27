---
covers:
  - kototoki/vad.py
  - kototoki/align.py
  - kototoki/schema.py
  - kototoki/workers/vad.py
  - kototoki/workers/asr.py
  - kototoki/workers/align.py
  - kototoki/workers/gpu.py
---
# STT worker：worker 壳、VAD 与对齐

状态：current；权威决定：[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线（[行为规格](../../behaviors/bilingual-subtitle-pipeline.md)）的三个 GPU 阶段的 worker 壳与共用规则：从 `audio-16k.wav` 求 VAD 窗口（`vad.json`）、逐窗转写（`asr.json`）、字符级强制对齐（`align.json`）。本页写三壳共用的入口、jobs 约定、模型核对、身份、产物与失败分级，以及 VAD 与对齐两个推理模块。

ASR 的两个引擎（w0、x0）、可选的 `cross` 引擎、裁判与 w0 整窗守卫见 [STT ASR](stt-asr.md)。

不负责：决定哪些文件要跑或跳过、锁、子进程环境与按文件重启（[批次编排](batch-orchestration.md)）；身份的组成与期望值（[阶段计划](stage-plan.md)）；cue 切分与时间回填（[日文 cue](japanese-cues.md)）。

推理逻辑移植自研究期的 W0／X0 demo（研究代码与其模块页已删除，经过见[STT demo 与 W0／X0 轮次](../../research/2026-10-stt-demo-w0-x0.md)），产品实现是唯一权威。移植时保留、至今仍成立的行为：

- **分窗**（`recipes` 的 `source-span-merge-v1`）：VAD 区间起点向下、终点向上取整为样本并裁到源范围、排序取并集；超过 480000 样本的区间每 480000 样本硬切，再按源跨度贪心合并，合并后跨度不超过 30 秒；不加 padding，窗内静音保留，不拼接波形；空检测是合法结果。
- **w0 解码**：逐窗独立、不以前文 conditioning、不出时间戳 token（`condition_on_previous_text=False`、`without_timestamps=True`）。
- **MMS 对齐**：`jpn` adapter、词表 2268、blank ID 0、CUDA FP32；单窗推理失败记该窗失败并把字符留作 `text_only`，不转 CPU 重试；词表外字符用通配符参与对齐；前向期间 matmul TF32 关、cuDNN TF32 开，退出时恢复调用者设置（Pyannote 会全局关 TF32 且不恢复）。

本页其余部分只写产品侧的接口与差别。现行 STT 基线与设备规则见[现行决定](../../adr/CURRENT.md)。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**jobs 约定**（在协议的 `{"stage", "recipe_hash", "config", "files"}` 之上，协议见[产物契约](artifact-contract/worker-protocol.md)）：

- `recipe_hash` 必须等于该 worker 写进身份的配方 hash（VAD、MMS 各一个，ASR 按引擎），否则启动失败。
- `config.models`：`Config.models` 的同名键，路径字符串（`vad`、`w0`、`x0`、`align`）。
- `config.model_cache`：`<work_dir>/cache/model-verification.json`。
- ASR 另需 `config.engine`（`w0`、`x0` 或 `cross`，其它值启动失败；按引擎读哪些模型键见 [STT ASR](stt-asr.md)）。
- 每个文件的 `inputs`：VAD `wav`；ASR `wav`＋`vad`；对齐 `wav`＋`asr`。

**模型核对**：`start` 加载前用 `gpu.verify_models`（`artifacts.verify_model`，size+mtime 缓存）逐个核对 `plan.model_files` 给出的固定 SHA256；清单见[阶段计划](stage-plan.md)。核对结果即身份的 `models` 字段。推理模块自己不哈希 checkpoint。

**身份**（`plan` 的身份函数，经 `artifacts.derived_identity` 组装，`config` 字段为空——这三个阶段没有影响输出的配置键）：

| 产物 | upstream | recipe_hash |
| --- | --- | --- |
| `vad.json` | `audio-16k.wav` = PCM 数据块 SHA256 | `recipes.VAD` |
| `asr.json` | 同上＋`vad.json` 文件 SHA256 | 按引擎：`recipes.W0`／`X0`／`CROSS`（见 [STT ASR](stt-asr.md)） |
| `align.json` | 同上＋`asr.json` 文件 SHA256 | `recipes.MMS` |

ASR 与对齐壳读上游产物时重验其 `identity.upstream["audio-16k.wav"]` 等于本次读到的 PCM SHA256，不等即该文件失败。

**产物**（坐标一律 WAV 本地，`offset_s` 从 `recipes.MEDIA` 起逐级照抄，恒为 0）：

- `vad.json`：`schema_version`、`offset_s`、`input`（PCM SHA256、样本数、采样率、时长）、`chunks`（秒、成对整数 `start_sample/end_sample`、子段 `segments`）、`raw_intervals`、`speech_intervals`、`accounting`、`metadata`（设备、dtype、pyannote 窗口参数、包版本）、`stages`（`load_s` 为该 worker 进程的加载耗时，`inference_s` 为本文件）。窗口写出前经 `schema.validate_windows`。
- `asr.json`：三种引擎同构，字段见 [STT ASR](stt-asr.md#当前行为规格)。
- `align.json`：W0 `result.json` 的结构——`schema_version`、`engine`、`status`、`text`、`units`、`cues`（空）、`original_segments`、`chunks`、`failed_windows`（照抄 `asr.json`）、`alignment_records`、`derived_segments`、`offset_s`、`source_start_seconds`／`duration_seconds`／`source_end_seconds`、`input`、`metadata`、`stages`；不含 `asr_traces`。
- `align.json` 的 `units[].start/end` 为 WAV 本地秒（[offset](japanese-cues.md)）。写出前要求对齐全文等于 ASR 保留文本，并通过 `schema.validate_transcript` 与 `schema.validate_units`（每字符恰好一个 unit；有时间的 unit 落在源范围内）。

**VAD**（`vad.PyannoteVad`）：

- 要求 pyannote.audio 4.0.7 与 powerset checkpoint，`VoiceActivityDetection` 以 `min_duration_on/off = 0` 实例化。
- 设备固定 `cuda:0`，CUDA 不可用或实际设备不同即失败，不回退 CPU。
- 输入是内存波形 dict，不经 torchcodec 解码文件，不加 FFmpeg PATH；空波形或无语音返回空窗口表。
- `chunk_intervals` 只接受秒区间，规则同 `source-span-merge-v1`（`recipes.VAD["chunk_policy"]`）。

**对齐**（`align.MmsAligner`）：

- 与研究期实现的差别：TorchAudio 要求放宽为 ≥2.10，实际版本记入 `metadata.package_versions`。
- 字典只取 id < `model.config.vocab_size` 的词表项（`align.model_dictionary`）：分词器多出的 added token `|`（id 2268）被丢弃并记入 `metadata.dropped_tokenizer_entries`，通配符列号仍为 2268。
- `map_records(segments, records)` 与 `MmsAligner.align(audio, segments)` 不收 offset，units 输出 WAV 本地秒。
- 窗口一律是整数样本（`align.sample_window` 校验整数边界且秒与样本一致，不符即该文件失败）。
- 单窗 `RuntimeError`／`ValueError` 记入该窗 `failure`，字符成为 `text_only`，不转 CPU 重试。
- `asr.json` 中被置空的失败窗口没有可对齐字符（`skip_reason = no_eligible_characters`）。

**失败分级**：

- 窗口级：ASR 见 [STT ASR](stt-asr.md)，对齐见上。
- 单文件异常（读 WAV、身份不符、校验失败等）由协议写 `failure.json`、退出码 1，继续下一文件。
- `gpu.file_processor` 在 `compute` 抛异常后、以及写产物之前各调用一次 `torch.cuda.synchronize()`；失败即判定为 CUDA 粘性错误，抛 `FatalWorkerError`（不写产物，退出码 2，由编排从下一文件重启）。因此推理模块按窗口吞掉的粘性错误也不会写出"全窗失败"的产物。

## 实现设计

**分两层**：

- 推理模块（`kototoki/vad.py`、`asr_whisper.py`、`asr_qwen.py`、`align.py`）只做"加载一次、按窗口推理"：输入输出是内存对象与 WAV 本地坐标，只依赖基础层、互不导入，不读写产物、不判断跳过、不打印。
- worker 壳（`kototoki/workers/{vad,asr,align}.py`）负责读输入、重验上游身份、组装 payload 与 `failed_windows` 记账，经 `protocol.run_worker` 运行，`__main__` 两行。

**共用部分在 `kototoki/workers/gpu.py`**：命令行入口 `main`、读 WAV `read_wav`（mono 16 kHz PCM16，返回 float32 波形与 PCM SHA256）、读上游产物并重验 `read_input_artifact`、`require_recipe`、`verify_models`、CUDA 守卫 `check_cuda` 与写产物 `file_processor`。

- 每个壳的 `Compute` 对一个文件返回若干 `(path, identity, payload)` 与进度行附加字段。
- `gpu.file_processor` 查一次 CUDA 后按顺序全部写出，阶段产物（如 `asr.json`）排在最后，所以中途失败时没有新的阶段产物。
- 采样率等常量（`SAMPLE_RATE`、`MAX_WINDOW_SAMPLES`）只在 `recipes.py` 定义，其余模块导入。
- 壳模块导入时不加载 torch 等推理库，推理模块在 `start` 里才导入。

**身份归属**：壳自身不持有身份、模型文件清单与配方 hash，这些归[阶段计划](stage-plan.md)。壳写进产物的身份与编排核对用的是同一个函数（`plan.vad_identity`／`asr_identity`／`align_identity`）；`start` 用 `plan.recipe_hash(stage, engine=…)` 校验 jobs，用 `plan.model_files(stage, models, engine=…)` 取要核对的模型文件。

## 接口与依赖

推理模块依赖 `recipes` 与 `schema`（基础层）及 torch、pyannote.audio、faster-whisper／CTranslate2、transformers／torchaudio；四者互不导入。

`schema` 属基础层，只依赖标准库与 `recipes`（`SAMPLE_RATE`、`MAX_WINDOW_SAMPLES`）：`validate_transcript` 复制自 `archive/2026-11-18-pre-research-restructure:kototoki_eval/schema.py`（评分包已删除，产品实现是唯一权威），另有 `validate_windows`、`validate_units`。

壳依赖 `artifacts`、`plan`、`recipes`、`schema`、`workers/protocol`、`workers/gpu`；ASR 壳另依赖 `guard`、`judge`（[STT ASR](stt-asr.md)）。`plan` 只在算翻译身份时才导入翻译子系统，壳不会触发。

子进程环境（`PYTHONUTF8=1`、`HF_HUB_OFFLINE` 等离线变量、`HF_HOME`／`TORCH_HOME = <work_dir>/cache/`，以及关掉 tqdm 与 HF 进度条的 `QUIET_ENV`）由编排传入，worker 不自行设置（[模块边界：产品包的责任边界](../module-boundaries.md#产品包的责任边界)）。

**日志**（由 `gpu.main` 配置）：

- root 上一个写 stderr 的 handler（`kototoki.logs.RunFormatter`，与运行日志同格式），`kototoki` logger 为 INFO；第三方只有 WARNING 及以上；`logging.captureWarnings(True)` 把 Python warnings 收进同一流；`gpu.quiet_known_warnings` 只过滤 `KNOWN_HARMLESS_WARNINGS` 列出的已知无害告警（当前一条：pyannote 在 GPU 上关掉 TF32 时的 `ReproducibilityWarning`，按 `UserWarning` 与消息开头匹配），免得 vad 每次运行都在运行日志里留一行告警计数，其他告警照常。
- 三个壳的 logger 固定命名为 `kototoki.workers.<stage>`：以 `python -m kototoki.workers.<stage>` 运行时 `__name__` 是 `__main__`，不在 INFO 级的 `kototoki` 之下，每文件 INFO 行会被丢弃。
- 壳记模型核对与加载耗时、每文件窗口数／失败数／推理秒数；每个失败窗口一行 WARNING（只记序号与 reason，不记文字）。
- `protocol` 对单文件失败、`FatalWorkerError` 与启动失败记 ERROR（异常类型＋traceback）；启动失败行为 `[<stage>] startup failed: <类型>`，读 jobs 失败、还不知道阶段时为 `[worker] startup failed: <类型>`。
- stderr 侧文件里的相对秒自 worker 进程启动起算，不是自本次 `run` 起。
- 推理模块不发日志；stdout 只留协议 JSON 行，`done` 行的数值字段由编排抄进运行日志。stderr 的存放与告警计数见[运行日志](run-logging-and-processes/run-log.md#运行日志)。

## 代码与验证入口

- 代码：`kototoki/vad.py`、`kototoki/align.py`、`kototoki/schema.py`、`kototoki/workers/{vad,asr,align,gpu}.py`（`kototoki/workers/protocol.py` 归[产物契约](artifact-contract.md)；ASR 推理模块、`kototoki/guard.py` 与 `kototoki/judge.py` 归 [STT ASR](stt-asr.md)）。
- `tests/core/test_vad.py`：`chunk_intervals` 的并集（重叠与乱序）、超长硬切、贪心合并不超上限。
- `tests/core/test_align.py`：`character_targets` 重复字保位置、未知字用通配；`map_records` 每个字恰好一个 unit、失败或无效记录退为只有文字；`MmsAligner.align` 逐窗循环按样本边界出记录且 units 为 WAV 本地秒；`normalize_window` 短窗右补零到最小长度。
- `tests/core/test_schema.py`：`validate_transcript` 拒绝错误 schema 版本或缺文字；`validate_windows` 接受精确窗口与空列表、拒绝重叠乱序与超 480000 样本；`validate_units` 的精确覆盖、只有文字的 unit、缺漏、重复覆盖与时间越界。
- `tests/core/test_stt_workers.py`（伪推理对象）：
  - vad 壳写出的身份等于 `plan.vad_identity`，坐标与 `stages` 如实；asr 壳身份链到 vad 且逐窗文字、`failed_windows` 正确；失败窗口置空并记录；复读窗口被折叠并写 trace 与 WARNING（日志不含文字）；vad 对应另一份音频则整文件失败。
  - align 壳的链产出能被 `cues.build_cues` 消费；对齐改文字则整文件失败。
  - CUDA 守卫：坏 CUDA 出错或成功均退出码 2 且不写产物；`gpu.verify_models` 核对并缓存 sha256；`gpu.read_wav` 归一化 PCM16 为 float32 并算 PCM sha256。
  - 壳导入不加载推理库。
  - ASR 与 `cross` 的用例见 [STT ASR](stt-asr/cross-judge.md#代码与验证入口)。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - vad：`chunk_intervals` 的取整、越界裁剪与计数、窗口外区间丢弃、内部静音记账、非法区间与样本数、输出过窗口 schema；`validate_audio` 的形状与 dtype。
  - align：torchaudio 最小版本、模型字典过滤（含 transformers 5 的分隔符）、小写展开报错、数值作用域的设置与恢复、`sample_window` 的各种拒绝；`map_records` 的 `offset` 与缺记录保留文字。
  - schema：多数拒绝分支、1 ms 容差、采样率常量只在 recipes 定义。
  - 壳：身份不自有、非法窗口使文件失败、配方与引擎启动校验、`main` 读 jobs、日志去向与启动失败的 traceback、模型文件清单、`gpu.file_processor` 的一次 CUDA 检查、logger 名、TF32 告警过滤；整链 `align.json`、`ja-cues.json`、`ja.srt` 的字节 sha256 钉子已删除。
- 真实模型路径由小批量 `mise run subtitles` 验证；对照研究期冻结窗口的门禁已随 ADR-0034 删除，不再与 W0／X0 demo 逐 token 比对。
- 未验证：真实的 CUDA 粘性错误与窗口级 OOM 只用伪对象验证了分级逻辑；多文件 jobs 只有离线测试；TF32 告警过滤后真实 vad 运行不再有告警计数行，尚未经真实运行核对。

## 变更与决策来源

- [ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/（`issues/03-stt-workers.md`、`issues/07-x0-engine.md`、`issues/14-stage-plan-module.md`）、.scratch/cross-asr-judge/、.scratch/runtime-logging-gaps/
- 计划：`archive/2026-11-18-pre-research-restructure:docs/plans/architecture-cleanup.md`、`archive/2026-11-18-pre-research-restructure:docs/plans/asr-repeat-guard.md`
- 验收：[两部整片验收](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)、[最终验收](../../research/acceptance/bilingual-pipeline-final-acceptance-2026-10-15.md)、[swr 回归](../../research/acceptance/bilingual-pipeline-swr-regression-2026-10-16.md)
- 历史记录：模块页拆出的历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/acceptance/2026-11-11-module-page-history-stt-plan-artifacts.md`）、技术设计历史（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）
- 来源代码：`archive/2026-11-18-pre-research-restructure:experiments/w0_demo/vad_candidates.py`、`archive/2026-11-18-pre-research-restructure:experiments/w0_demo/alignment.py`、`archive/2026-11-18-pre-research-restructure:experiments/w0_demo/pipeline.py`（units 不变量）、`archive/2026-11-18-pre-research-restructure:kototoki_eval/schema.py`
