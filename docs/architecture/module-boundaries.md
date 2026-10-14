# 模块边界

本文规定职责归属、依赖方向与状态所有权。模块页说明自己如何遵守；实际偏差在模块页就地注明，不在此改写规则。

## 职责归属

| 规则 | 唯一归属 | 消费方 |
| --- | --- | --- |
| VAD 候选加载、原生检测、`source-span-merge-v1` 窗口切分合并（`chunk_intervals`、`CHUNK_POLICY`） | [外部 VAD 阶段](modules/vad-stage.md)（代码位于 `w0_demo/vad_candidates.py`） | 只经 manifest 文件被 W0／X0 消费 |
| VAD manifest 校验（`read_vad_manifest`） | [W0 pipeline](modules/w0-pipeline.md) 的 `experiments/w0_demo/run.py` | X0 的 `x0_demo/vad.py::import_vad_plan` 直接调用，不复制 |
| 音频读取与输入身份（`read_audio`：mono／16 kHz／PCM16，WAV／PCM SHA256） | `experiments/w0_demo/run.py` | X0 子阶段、外部 VAD 阶段 |
| Whisper 特征、无时间戳独立解码 | [W0 pipeline](modules/w0-pipeline.md) | — |
| fixed30／cut-merge 分段、Qwen 原生特征与解码、子进程编排 | [X0 pipeline](modules/x0-pipeline.md) | — |
| CTC 强制对齐、整数样本窗口校验（`sample_window`）、字符→unit 映射与 `text_only` | [MMS 对齐](modules/mms-alignment.md) | W0、X0 |
| 转写 JSON 结构契约（`validate_transcript`）与评分 | [STT 评分与显示重放](modules/stt-evaluation.md) | W0、X0 写出前调用；评分 CLI 读取 |
| 字幕显示切分（`minimal-display-v1`） | [STT 评分与显示重放](modules/stt-evaluation.md) 的 `display/replay.py` | demo 不复制 WhisperX cue 逻辑 |
| 模型下载与资产 SHA256 固定 | [语料与模型资产准备](modules/corpus-and-assets.md) | 推理入口只读本地文件 |
| llama-server 命令行、驻留证据解析、资产清单与 OOM 识别 | [逐窗翻译运行时](modules/translation-runtime.md) | 完整 SRT 流程导入 `residency_evidence`、`validate_residency`、`load_assets`、`explicit_oom` 等 |
| Hy30 原生提示模板与 ID JSON grammar（`translation_demo.adapters`） | [逐窗翻译运行时](modules/translation-runtime.md) | 完整 SRT 流程 |
| 产物契约：`.work/<id>` 布局与短 id、产物文件名、视频／派生身份、模型哈希缓存、坐标约定、匹配跳过与原地替换、原子写、`failure.json`、`published.json` 与覆盖规则；worker `--jobs` 协议、退出码与 `failed_windows`；产品 SRT 读写与毫秒取整 | [产物契约](modules/artifact-contract.md)（`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`） | 产品流水线各阶段与编排器（票据 02–09） |
| 产品配置读取与路径解析（`kototoki.toml`、GPU 锁路径、破锁环境变量）；STT／cue／媒体配方常量、下混 `pan` 常量与 `recipe_hash`（翻译配方除外）；音轨选择、流复制容器映射、派生 WAV 与时间轴零点（`offset_s` 恒为 0）、对视频流的时长校验 | [配置、配方与媒体提取](modules/config-and-media.md)（`kototoki/config.py`、`kototoki/recipes.py`、`kototoki/media.py`） | 编排器（票据 06）、STT worker（票据 03／07）、翻译子系统读配置（票据 05） |
| 产品日文 cue：无时间字符回填（插值、外推、整窗 `fallback`）、三级切分、lead-out 与最短时长、cue 时间加一次 `offset_s` | [日文 cue](modules/japanese-cues.md)（`kototoki/cues.py`） | 编排器（票据 06）写 `ja-cues.json`／`ja.srt` |
| 产品 STT 推理：Pyannote 检测与 `source-span-merge-v1` 分窗、w0 特征链与 CT2 解码（torch 先于 ctranslate2 导入）、x0 Qwen 原生 processor 与 4096 触顶转失败窗口、MMS 强制对齐与字典按模型类数过滤；`vad.json`／`asr.json`／`align.json` 的身份、payload 与窗口级失败记账；CUDA 粘性错误判定（退出码 2）；`validate_transcript`、窗口与 units 校验（`kototoki/schema.py`） | [STT worker](modules/stt-workers.md)（`kototoki/vad.py`、`asr_whisper.py`、`asr_qwen.py`、`align.py`、`schema.py`、`kototoki/workers/{vad,asr,align,gpu}.py`） | 编排器（票据 06）以子进程启动 worker、导入壳的 `identity` 判定跳过；日文 cue 读 `align.json` |
| 产品批次编排：扫描与稳定性、阶段调度与期望身份、worker 重启、`<output_dir>/.work/lock` 与 `.local/gpu.lock`、Job Object、子进程环境、发布与 `failure.json` 清理、运行日志 | [批次编排](modules/batch-orchestration.md)（`kototoki/__main__.py`、`kototoki/job.py`） | 用户经 `python -m kototoki` 调用 |
| 流程配方身份（`Recipe.recipe_hash`）、批次、整片交付 | [完整 SRT 翻译流程](modules/translation-srt-flow.md) | — |
| 产品翻译：配方与 `RECIPE_HASH`（`kototoki/translate/recipes.py`，翻译配方的唯一归属）、llama-server session 生命周期与空闲显存轮询、`b10-joint` 请求、按批次落盘与续跑、基础设施失败重启、产品配方 `b10-joint-degrade-v1` 的三级降级与回退报告；中日两行合并 | [翻译子系统与双语合并](modules/translation-subsystem.md)（`kototoki/translate/`、`kototoki/merge.py`） | 编排器（票据 06）持有 `Session`、调用 `translate_document` 与 `merge`，从 `TranslateResult` 读回退计数 |

## 依赖方向

- 允许：X0 → W0（`read_audio`、`setup_runtime`、`gpu_lock`、`read_vad_manifest`、`MmsAligner`）；外部 VAD 阶段 → W0（`gpu_lock`、`read_audio`、`vad_candidates`）；W0／X0 → `kototoki_eval.schema`。
- 允许：完整 SRT 流程 → 逐窗翻译运行时（`translation_demo.adapters`、`client`、`run`、`translation_demo_runtime` 的纯函数）。
- 现存的当前→历史依赖（只读导入，不得扩大）：X0 → `experiments.qwen.run_qwen`（Qwen 资产身份常量与 `checkpoint_identity`、`check_gpu`）；完整 SRT 流程 → `experiments.translation_flow.srt`（SRT 读写与覆盖校验），其测试另导入冻结的 `translation_flow.v2_prepare`／`v2_recipes` 做 C0 等价核对；W0 测试导入 `experiments.framework_equivalence` 作数值参照，运行时不导入。
- 产品包 `kototoki/`（分层图见[架构总览](INDEX.md#依赖与装配)）：依赖只向下，编排 `job` → 媒体、cue、合并、翻译子系统 → 基础层（`config`、`recipes`、`artifacts`、`srt`、`workers/protocol`、`schema`）。四条硬规则：
  - **编排层不导入任何推理模块。** `job` 只以 `sys.executable -m kototoki.workers.<stage> --jobs <path>` 启动阶段 worker，与它们的全部通信是 jobs 文件、工作目录里的产物和退出码；`tests/test_job.py` 的禁止导入测试（`torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`、任何 `experiments.*`）守门。编排可导入 worker 壳（`workers.vad`／`asr`／`align`／`gpu`）的身份与模型核对函数，壳导入时不加载推理库。
  - **推理模块互不导入。** `vad`、`asr_*`、`align` 只依赖基础层，各自在独立进程里加载模型；阶段之间只经产物文件交接。三壳共用的入口、读 WAV、模型核对与 CUDA 守卫在 `workers/gpu.py`，只被 worker 壳与编排导入，不属基础层。
  - **基础层不依赖 torch、ffmpeg、网络与上层。** 它是所有离线测试的根基，编排器可以直接导入。
  - **产品包不导入 `experiments.*`。** 历史实现只复制不引用；`kototoki_eval/` 继续承担评分，产品侧的 `validate_transcript` 复制在 `kototoki/schema.py`。
- 禁止：`kototoki/job.py`、`kototoki/__main__.py` 导入 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`；`kototoki/` 任何模块导入 `experiments.*`（历史实现只复制）。
- 禁止：`kototoki_eval` 导入任何推理或 `experiments` 代码；推理入口导入 `experiments/provision`；当前模块写入或修改历史实验包（`translation_flow/v2_*`、`translation_judge/`、`translation_eval/` 等冻结证据）。
- 文件契约代替导入：W0／X0 不导入外部 VAD 阶段的入口，只读其 manifest；评分 CLI 只读 `result.json`；各入口只读语料准备产出的 WAV 与参考 JSON。

## 状态与契约

- 每个运行目录由创建它的入口独占：`.local/w0-demo/`、`.local/x0-demo/`、`.local/vad-comparison/`、翻译 `--output-dir` 及 v3 根目录（默认 `.local/translation-evaluation/hy30-flow-v3/`）。目录已存在即拒绝；结果、全文和缓存只写在该目录内。
- VAD manifest 是窗口的唯一权威：runner 将其原字节复制为 `vad-manifest.json` 并记录 SHA256，运行中来源变化即失败。manifest 中的 `stages` 是外部进程成本的快照，不计入 W0／X0 自身 `stages` 或 `wall_s`；回放 manifest 不是新的 VAD 推理（`fresh_inference=false`／`precomputed_external_manifest`）。
- 输入身份以内容为准（`file_sha256`、`pcm_sha256`、采样率、声道、样本数、时长、`offset_s`），路径可以不同。
- 运行身份（recipe 名、v3 `recipe_hash`、模型 SHA256、冻结源码哈希）是派生结果可比的前提；同名配方内容不同时拒绝续跑。
- X0 子进程之间只通过运行目录中的 JSON 交接（`request.json` → `plan.json` → `asr.json` → `alignment.json`），每阶段重验源码与输入哈希。

## 并发与生命周期

- `.local/gpu.lock` 是所有 GPU 作业共用的互斥文件，存在两种实现：`experiments/w0_demo/run.py::gpu_lock`（O_EXCL 创建，写 `pid`＋`recipe`，退出时删除；W0、X0 父进程、CUDA 设备的外部 VAD 阶段使用）与 `experiments/translation_v3/procs.py::ProcessLock`／`server.py::GpuLock`（写 `pid`＋`pid_created`＋`run_id`；存活持有者在时退出码 3，死锁只在 `--break-stale-lock` 时替换）。两者都不抢占、不杀进程。
- 逐窗翻译运行时（`translation_demo_runtime.py`）不获取 `.local/gpu.lock`，只检查端口是否被占用；与其他 GPU 作业的互斥由操作者保证。
- 模型生命周期按阶段串行：W0 通过工厂在 VAD 关闭后加载 ASR，ASR `close()` 后再加载 MMS；X0 每阶段一个独立子进程，进程退出即释放；父进程持锁直到全部子进程退出。
- 取消：X0 父进程在中断时 `terminate`→10 秒后 `kill` 当前子进程，记录被中断阶段成本并清理 `tmp/`；v3 把 llama-server 放入 KILL_ON_JOB_CLOSE Job Object，Python 被强杀时服务器随之退出。发出取消不等于 GPU 已释放；完整 Windows 取消／OOM 恢复仍未验证（见 [X0 pipeline](modules/x0-pipeline.md#代码与验证入口)）。

## 产品包的责任边界

双语字幕流水线（`kototoki/`）按"谁有权做这个决定"划分，每项只有一个归属：

- **时间轴**只在三处出现：媒体定零点，推理模块输出 WAV 本地坐标，日文 cue 加一次 offset。编排、翻译、合并不得出现任何时间换算。
- **跳过与替换**由产物契约的 `is_current` 判定，编排只负责问；推理模块永远不决定"要不要跑"。
- **失败分三级，各归一层**：窗口级（`failed_windows`，推理模块填、协议校验，不进对齐、cue 与翻译）；文件级（退出码 1，协议记账，编排继续下一文件）；进程级（退出码 2，编排从下一文件重启 worker）。翻译子系统内部的基础设施失败自己消化到重启两次为止，再往上抛即为该文件的文件级失败；批次终态失败在子系统内降级到单条，单条仍失败保留日文。
- **发布**只有编排能做，且必须走 `publish_blockers` → `record_published` → 移动三份文件的固定顺序；判定在扫描阶段完成，被用户改动且非 `force` 的文件不进 GPU 阶段。
- **锁**全归编排：`<output_dir>/.work/lock` 与 `.local/gpu.lock` 都在编排器手里；翻译子系统的 server 不取锁。
- **身份**：各阶段 `recipe_hash` 归 `recipes.py`，翻译配方 hash 归 `translate/recipes.py`，模型 SHA256 经产物契约的缓存；没有模块把绝对路径写进身份。
- **子进程环境**归编排：`PYTHONUTF8=1`、离线变量、共用 `HF_HOME`／`TORCH_HOME=<output_dir>/.work/cache/` 由编排传入，worker 不自行设置 PATH 或 DLL 目录。
- **日志**只有编排写运行日志，内容限进度与计数；推理模块只返回数据，不打印，转写与译文不进日志。

接缝：有两个适配器的位置才是真接缝，只有一个适配器时保持具体实现、不抽象。真接缝有三处：ASR 引擎（`asr_whisper`／`asr_qwen` 写出同一种 `asr.json`，由 `config.engine` 选择）、编排器 ↔ 阶段 worker（真实子进程／测试用伪 worker 脚本，接口是 jobs 文件＋增量结果＋退出码）、翻译 ↔ llama-server（HTTP 客户端／伪客户端，只在 `translate/` 内部）。媒体 ↔ ffmpeg、VAD 与对齐后端、配置来源、SRT 写出器都只有一个实现，不做后端协议类或抽象层；换模型时改配方常量与实现，不改接口。在只有一个适配器的位置新建接缝须先在本节写明第二个使用者。内部接缝只供各自模块的测试使用、不属对外接口：`translate.client` 可换伪客户端，`protocol.run_worker` 的 `start` 回调可换伪处理函数，`artifacts.replace_with_retry` 的 `replace` 可注入。

测试穿过与调用方相同的接缝：`cues`、`merge`、`srt`、`artifacts`、`protocol`、`config` 直接按接口离线测；媒体测命令行构造与合成媒体；推理模块用冻结窗口门禁（重任务）；翻译子系统用伪客户端走完整流程；编排用伪 worker 脚本。需要越过接口去戳实现时，先怀疑模块形状。编排是最深的模块（一个入口承载全部流程知识），worker 壳的 `__main__` 只做入口，流程知识在协议模块。
