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
| 产物契约：工作目录布局（`<work_dir>/<目标目录键>/<id>` 与短 id、共用 `cache/`）、源文件旁的双语字幕路径、产物文件名、视频／派生身份、模型哈希缓存、坐标约定、匹配跳过与原地替换、原子写、`failure.json`、`published.json`（审计记录）；worker `--jobs` 协议、退出码与 `failed_windows`；产品 SRT 读写与毫秒取整；`asr-w0.json`／`asr-x0.json`／`asr-judge.json` 三个 cross 审计产物的文件名常量与位置（`<id>/`，不是阶段产物，不参与 `is_current`） | [产物契约](modules/artifact-contract.md)（`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`） | 产品流水线各阶段与编排器（票据 02–09） |
| 产品配置读取与路径解析（`kototoki.toml`、GPU 锁路径、破锁环境变量）；STT／cue／媒体配方常量、下混 `pan` 常量与 `recipe_hash`（翻译配方除外）；音轨选择、流复制容器映射、派生 WAV 与时间轴零点（`offset_s` 恒为 0）、对视频流的时长校验 | [配置、配方与媒体提取](modules/config-and-media.md)（`kototoki/config.py`、`kototoki/recipes.py`、`kototoki/media.py`） | 编排器（票据 06）、STT worker（票据 03／07）、翻译子系统读配置（票据 05） |
| 产品日文 cue：无时间字符回填（插值、外推、整窗 `fallback`）、三级切分、lead-out 与最短时长、cue 时间加一次 `offset_s` | [日文 cue](modules/japanese-cues.md)（`kototoki/cues.py`） | 编排器（票据 06）写 `ja-cues.json`／`ja.srt` |
| 产品 STT 推理：Pyannote 检测与 `source-span-merge-v1` 分窗、w0 特征链与 CT2 解码（torch 先于 ctranslate2 导入）、x0 Qwen 原生 processor 与 4096 触顶转失败窗口、MMS 强制对齐与字典按模型类数过滤；`vad.json`／`asr.json`／`align.json` 的 payload 与窗口级失败记账（身份取自阶段计划）；CUDA 粘性错误判定（退出码 2）；`validate_transcript`、窗口与 units 校验（`kototoki/schema.py`）；`cross` 引擎的 asr 阶段：同一进程常驻 w0 与 x0 两个适配器，逐文件两路转写后经裁判合并成同一种 `asr.json`，并写三个审计产物 | [STT worker](modules/stt-workers.md)（`kototoki/vad.py`、`asr_whisper.py`、`asr_qwen.py`、`align.py`、`schema.py`、`kototoki/workers/{vad,asr,align,gpu}.py`） | 编排器（票据 06）以子进程启动 worker；日文 cue 读 `align.json` |
| 产品 ASR 裁判纯逻辑（`cross` 引擎）：文本规范化（`normalize` 复制自 `kototoki_eval/schema.py`）、字符级对齐与分歧区间、区间到原文的偏移映射、假设构造、`d > m` 判定（`CROSS` 配方：m −1.0、无长度项）、窗口级 `judge_window` 与守卫（相同窗口不打分、空结果取 w0）、`asr-judge.json` 汇总计数；打分本身由 `WhisperAsr.score` 做，经调用方传入，裁判不导入推理模块 | [STT worker](modules/stt-workers.md)（`kototoki/judge.py`，基础层） | `kototoki/workers/asr.py` 的 cross 分支 |
| 产品批次编排：扫描（视频与音频）与稳定性、字幕已存在即跳过、主名冲突、阶段调度、worker 重启、`<work_dir>/<目标目录键>/lock` 与 `.local/gpu.lock`、Job Object、子进程环境、发布与 `failure.json` 清理、运行日志（行格式在基础层 `kototoki/logs.py`） | [批次编排](modules/batch-orchestration.md)（`kototoki/__main__.py`、`kototoki/job.py`、`kototoki/logs.py`） | 用户经 `python -m kototoki` 调用 |
| 产品阶段计划：阶段链与各阶段的产物／输入名、模型文件清单与固定 SHA256、各阶段期望身份（probe、vad、asr、align、ja-cues；translate 身份转问翻译子系统）、"下一个要跑的阶段"（终态只剩 `publish`，是否已发布由编排按字幕文件是否存在判定） | [阶段计划](modules/stage-plan.md)（`kototoki/plan.py`） | 编排器（`next_stage`／`advance`、jobs 文件）、worker 壳（写进产物的身份、模型核对清单）、伪 worker |
| 流程配方身份（`Recipe.recipe_hash`）、批次、整片交付 | [完整 SRT 翻译流程](modules/translation-srt-flow.md) | — |
| 产品翻译（Q2，[ADR-0019](../adr/0019-product-translation-q2.md)）：配方与 `RECIPE_HASH`（`kototoki/translate/recipes.py`，翻译配方的唯一归属）、专名注入规则（`name_rows`：只取 `confidence: high`；`names_for_window` 过滤）与注入行的 `names_sha256`、翻译 run 目录的键（`translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>`）与翻译身份、"是否需要模型"（`needs_model`：零条目或 run 已完成即否）、`dp10-cut` 切包与 `wide-context-v1` 邻文（只读 `ja.srt` 的停顿）、chat completions 请求与校验、按批次落盘与续跑、基础设施失败重启、产品配方 `q2-degrade-v1` 的 10→5→1 降级与回退报告；中日两行合并 | [翻译子系统与双语合并](modules/translation-subsystem.md)（`kototoki/translate/`、`kototoki/merge.py`） | 阶段计划模块调用 `translate.plan(work_dir, document, name_table, config)` 取身份与 `needs_model`；编排器持有共享的 `strata.Session`、按 `needs_model` 取 GPU 锁、调用 `translate_document(plan, session)` 与 `merge`，从 `TranslateResult` 读回退计数 |
| llama-server 的进程生命周期（[ADR-0014](../adr/0014-name-consistency-in-product.md) 票据 02 抽出；[ADR-0022](../adr/0022-product-names-on-strata.md) 后产品不再使用 `ServerSpec`、`ManagedServer` 与驻留校验，只留给研究侧）；产品仍用的本机回环 HTTP 客户端 `LlamaClient`（含逐请求 trace）、`InfraFailure`、`wait_for_free_vram`／`nvidia_smi`、`explicit_oom` | `kototoki/llama_server.py`（中间层，不单独建页） | 翻译子系统与专名建表（只用客户端）；`strata`（显存轮询、`InfraFailure`）；研究侧 `experiments/translation_v3/qwen.py`（含 `ManagedServer`） |
| Strata 的生命周期与共享 session（[ADR-0019](../adr/0019-product-translation-q2.md)、[ADR-0022](../adr/0022-product-names-on-strata.md)）：`StrataServer`（`strata launch --status` 须为空、空闲显存与可用内存轮询、`--no-tui --model iq3_s` 启动、接入检查、专家区检查、资源采样、`--stop` 与显存释放核实、session 证据）、`StrataRefused`、Strata 身份常量（模型名、版本、引擎 build、默认启动的解析值）、共享 `Session`（整批一个、首次需要才启动、启动失败整批累计 3 次即不可用、`unavailable`、`ensure_started`／`stop`、`on_server_pid`、`<work root>/strata-sessions/`） | `kototoki/strata.py`（中间层，不单独建页：生命周期细则见[翻译子系统](modules/translation-subsystem.md#当前行为规格)"Strata 生命周期"一节，共享 session 的编排见[批次编排](modules/batch-orchestration.md)）。研究侧 `experiments/translation_v3/strata.py`、`scene_batching_v6/v13.py` 也直接从这里导入（2026-11-09 起，原 `translate/strata.py` 再导出已删） | 编排器持有 `Session` 并传给 names 与翻译两个阶段；两阶段经 `ensure_started()` 取运行中的服务，基础设施失败时 `stop()` |
| 专名表建表（[ADR-0014](../adr/0014-name-consistency-in-product.md)；ADR-0019 起没有发布时替换；[ADR-0022](../adr/0022-product-names-on-strata.md) 起在 Strata 上按 Q3 规则建）：提示 v5 建表、归一兜底（zh 形状、称呼词黑名单、evidence<3 降级、日文写法形状）、`BUILD` 配方 `q3-names-v1` 与 hash（`names/recipes.py`）、Strata 上的 `chat`／`count_tokens` 回调与请求额度（最多 5 个请求、seed 依次 +1、`count_tokens` 不可用的退路）、`name-table.json` 的内容（文件由编排写）；建表必开；names 阶段的身份由 `plan` 算。表的用法（注入哪些行）归翻译子系统，本模块不知道 | [专名一致性](modules/name-consistency.md)（`kototoki/names/`） | 编排器持有共享的 `strata.Session`、调用 `build_document(work_dir, document, session, seed)`；`plan` 延迟导入 `names.recipes` 取 `BUILD_RECIPE_HASH`；翻译子系统读 `name-table.json` |

## 依赖方向

- 允许：X0 → W0（`read_audio`、`setup_runtime`、`gpu_lock`、`read_vad_manifest`、`MmsAligner`）；外部 VAD 阶段 → W0（`gpu_lock`、`read_audio`、`vad_candidates`）；W0／X0 → `kototoki_eval.schema`。
- 允许：完整 SRT 流程 → 逐窗翻译运行时（`translation_demo.adapters`、`client`、`run`、`translation_demo_runtime` 的纯函数）。
- 现存的当前→历史依赖（只读导入，不得扩大）：X0 → `experiments.qwen.run_qwen`（Qwen 资产身份常量与 `checkpoint_identity`、`check_gpu`）；完整 SRT 流程 → `experiments.translation_flow.srt`（SRT 读写与覆盖校验），其测试另导入冻结的 `translation_flow.v2_prepare`／`v2_recipes` 做 C0 等价核对；W0 测试导入 `experiments.framework_equivalence` 作数值参照，运行时不导入。
- 产品包 `kototoki/`（分层图见[架构总览](INDEX.md#依赖与装配)）：依赖只向下，编排 `job` → 媒体、cue、合并、阶段计划 `plan`、专名 `names`、翻译子系统、共享 session 所在的中间层 `strata` → （`names` 与翻译都经中间层 `strata` 与 `llama_server`）基础层（`config`、`recipes`、`artifacts`、`srt`、`workers/protocol`、`schema`、`logs`、`judge`；`judge` 为 `cross` 引擎新增，不导入 torch、推理模块、`experiments` 与 `kototoki_eval`）。`plan` 与 worker 壳同在中间层：壳导入 `plan` 取身份与模型清单；`plan` 只在核对翻译阶段时延迟导入翻译子系统（`translate.plan`），壳不会触发这条边。四条硬规则：
  - **编排层不导入任何推理模块。** `job` 只以 `sys.executable -m kototoki.workers.<stage> --jobs <path>` 启动阶段 worker，与它们的全部通信是 jobs 文件、工作目录里的产物和退出码；`tests/core/test_job.py` 的禁止导入测试（`torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`、任何 `experiments.*`）守门。编排不导入 worker 壳；期望身份来自 `plan`，模型核对只用 `workers/gpu.verify_models`（导入时不加载推理库）。
  - **推理模块互不导入。** `vad`、`asr_*`、`align` 只依赖基础层，各自在独立进程里加载模型；阶段之间只经产物文件交接。三壳共用的入口、读 WAV、模型核对与 CUDA 守卫在 `workers/gpu.py`，只被 worker 壳与编排导入，不属基础层。
  - **基础层不依赖 torch、ffmpeg、网络与上层。** 它是所有离线测试的根基，编排器可以直接导入。`judge` 同受此限：不导入 torch、`experiments.*`、`kototoki_eval`，`normalize` 复制过来而不引用（与 `schema.validate_transcript` 同一做法）。
  - **产品包不导入 `experiments.*`。** 历史实现只复制不引用；`kototoki_eval/` 继续承担评分，产品侧的 `validate_transcript` 复制在 `kototoki/schema.py`。
- `kototoki/llama_server.py`、`kototoki/strata.py` 与 `kototoki/names/`（[ADR-0014](../adr/0014-name-consistency-in-product.md)、[ADR-0019](../adr/0019-product-translation-q2.md)、[ADR-0022](../adr/0022-product-names-on-strata.md)）的现行规则：
  - **`llama_server` 是中间层，不属基础层**：它发 HTTP、轮询显存（研究侧还用它起进程），基础层不得导入它；`strata`、翻译子系统与 `names` 单向依赖它（只依赖基础层）；不导入 torch、`experiments.*`。产品只取它的客户端、显存轮询与 OOM 识别，不用 `ManagedServer`（只剩研究侧使用者）。
  - **`strata` 是中间层，不属基础层**：起停 Strata 进程（`strata` CLI）、核对身份、持有共享 session，只依赖基础层与 `llama_server`（`InfraFailure`、`nvidia_smi`、`wait_for_free_vram`）；不导入 `names`、翻译子系统、torch、`experiments.*`。`names` 与翻译子系统都单向依赖它；研究侧脚本也直接导入它（`translate/strata.py` 已删除）。翻译子系统不导入 `names`，只读它写出的 `name-table.json`（经 `plan` 传入内容）。
  - **`names` 只依赖基础层（`artifacts`、`config`、`srt`、`recipes`）与中间层 `strata`（`StrataRefused`）、`llama_server`（`LlamaClient`）**，不导入 torch、`experiments.*`（历史实现只复制），不导入翻译子系统。
  - **编排经 `importlib` 导入 `kototoki.strata`、`kototoki.names`**，与导入 `kototoki.translate` 同一做法，`tests/core/test_job.py` 的禁止导入测试照常守门；`plan` 核对 names 阶段时延迟导入 `names.recipes` 只取 `BUILD_RECIPE_HASH`（不需要 `names.plan`：建表没有 run 目录，表不当前即需要模型），worker 壳不会触发这条边。
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
- 产品包只有一个服务进程：Strata（几乎占满整卡），由共享的 `strata.Session` 在第一次真正需要请求模型时启动（可能在 names 建表，也可能在翻译），names 与 translate 两阶段之间不停，整批共用；启动前 `strata launch --status` 必须为空（不抢占别人的 launch），空闲显存达到 14000 MiB、可用内存达到 52 GiB；结束、出错或编排被中断（`Session` 是上下文管理器）都执行 `strata launch --stop` 并核实 status 为空、显存回到 14000 MiB；没有影片需要模型时不启动。产品不再启动 llama-server（[ADR-0022](../adr/0022-product-names-on-strata.md)）。产品进程被强杀时 Strata 可能留在后台，下次运行因 status 非空而拒绝，需手动 `strata launch --stop`。
- 逐窗翻译运行时（`translation_demo_runtime.py`）不获取 `.local/gpu.lock`，只检查端口是否被占用；与其他 GPU 作业的互斥由操作者保证。
- 模型生命周期按阶段串行：W0 通过工厂在 VAD 关闭后加载 ASR，ASR `close()` 后再加载 MMS；X0 每阶段一个独立子进程，进程退出即释放；父进程持锁直到全部子进程退出。
- 例外：`cross` 引擎的 asr 阶段在同一 worker 进程内让 Whisper（CT2）与 Qwen（torch）同时常驻，直到进程退出（整卡共驻峰值有阈值，超出回退为三段式整批转写，细节见 [STT worker](modules/stt-workers.md)）；阶段之间仍然串行，translate、align 不与之共驻；共驻峰值实测 10688 MiB（探针）／10030 MiB（产品路径验收），见 [ADR-0012](../adr/0012-cross-asr-judge.md#依据)。
- 取消：X0 父进程在中断时 `terminate`→10 秒后 `kill` 当前子进程，记录被中断阶段成本并清理 `tmp/`；v3 把 llama-server 放入 KILL_ON_JOB_CLOSE Job Object，Python 被强杀时服务器随之退出。发出取消不等于 GPU 已释放；完整 Windows 取消／OOM 恢复仍未验证（见 [X0 pipeline](modules/x0-pipeline.md#代码与验证入口)）。

## 产品包的责任边界

双语字幕流水线（`kototoki/`）按"谁有权做这个决定"划分，每项只有一个归属：

- **时间轴**只在三处出现：媒体定零点，推理模块输出 WAV 本地坐标，日文 cue 加一次 offset。编排、翻译、合并不得出现任何时间换算；翻译子系统只读 `ja.srt` 相邻 cue 之间的停顿长短来切包与取舍邻文（ADR-0011），不改写、不换算任何时间。
- **跳过与替换**由产物契约的 `is_current` 判定，期望身份与"下一个要跑的阶段"由阶段计划模块给出，编排只负责问；推理模块永远不决定"要不要跑"。
- **失败分三级，各归一层**：窗口级（`failed_windows`，推理模块填、协议校验，不进对齐、cue 与翻译）；文件级（退出码 1，协议记账，编排继续下一文件）；进程级（退出码 2，编排从下一文件重启 worker）。翻译子系统内部的基础设施失败（传输／连接断开、OOM、server 错误、Strata 起不来）自己消化到重启 Strata 两次为止（受共享 session 整批最多 3 次启动的上限约束），再往上抛即为该文件的文件级失败；`StrataRefused`（身份不符、已有别的 launch 在服务、专家区退到 mmap）不重试，共享 `Session` 置为不可用，本批其余需要模型的影片在 names 与 translate 都直接失败；批次终态失败（两次尝试都失败）在子系统内按 10→5→1 降级，单条仍失败保留日文。专名建表的传输／HTTP／OOM 失败停掉 Strata，是该文件 names 阶段的文件级失败（下一部需要模型的影片再启动，计入整批 3 次），建表终态失败（5 次都不合格、超预算）只写空表、不算失败（翻译照常，不注入）。发布没有专名替换，因而没有替换失败。
- **发布**只有编排能做：把 `ja-zh.srt` 写到工作目录暂存 → `record_published`（审计）→ 原子移动到源文件旁。源文件旁已有同名字幕的文件在扫描阶段即跳过，不进任何阶段（ADR-0020）。
- **锁**全归编排：`<work_dir>/<目标目录键>/lock` 与 `.local/gpu.lock` 都在编排器手里；翻译子系统、`names` 与共享的 `strata.Session` 都不取锁。
- **身份**：各阶段 `recipe_hash` 归 `recipes.py`，翻译配方 hash 归 `translate/recipes.py`，专名的建表配方 hash 归 `names/recipes.py`，模型 SHA256 经产物契约的缓存；翻译身份 = `{ja_srt_sha256, recipe_hash, seed, names_sha256}`，其中 `names_sha256` 是注入行的哈希，手改表中会被注入的条目即换身份、重译（只改 medium／low 条目不会）；每个阶段的期望身份由哪些上游、配方与模型组成只在 `plan.py` 写一次，worker 壳与编排消费而不复制；没有模块把绝对路径写进身份。
- **子进程环境**归编排：`PYTHONUTF8=1`、离线变量、共用 `HF_HOME`／`TORCH_HOME=<work_dir>/cache/` 由编排传入，worker 不自行设置 PATH 或 DLL 目录。
- **日志**目的地与格式只归编排（`job._run_logging`、`kototoki/logs.py` 的格式；worker 壳的 `gpu.main` 只把子进程日志按同一格式写到 stderr，由编排存档）；产品模块经各自 `kototoki.*` logger 发进度与告警（`job`、`translate.*`、`strata`（Strata 启停、等显存与内存、接入检查，前缀 `[strata]`）、`names.table`（不合格的尝试）、worker 壳；`names` 包顶层不发日志，建表结果行由编排写）；推理模块（`vad`、`asr_*`、`align`）不发日志、不打印；转写、译文、提示与模型响应正文不进任何日志（细则见[批次编排：运行日志](modules/batch-orchestration.md#运行日志)）。

接缝：有两个适配器的位置才是真接缝，只有一个适配器时保持具体实现、不抽象。真接缝有三处：ASR 引擎（`w0`、`x0`、`cross` 三个适配器写出同一种 `asr.json`，由 `config.engine` 选择；`cross` 由 `asr_whisper`＋`asr_qwen`＋`judge` 组合而成，不是新的推理模块；[ADR-0012](../adr/0012-cross-asr-judge.md)）、编排器 ↔ 阶段 worker（真实子进程／测试用伪 worker 脚本，接口是 jobs 文件＋增量结果＋退出码）、names 与翻译 ↔ Strata HTTP 服务（本机回环客户端 `LlamaClient`／测试用伪客户端）。[ADR-0019](../adr/0019-product-translation-q2.md) 起 `StrataServer`（启停与身份核对）是**单一具体实现**，不抽后端协议：产品只有 Strata 一个推理后端，Hy-MT2 后端随 H0 配方一起删除；`strata.Session(server_factory=...)` 只是测试可替换伪服务的内部接缝。Strata 的生命周期在 ADR-0019 时只有翻译一个使用者，留在 `translate/strata.py`；[ADR-0022](../adr/0022-product-names-on-strata.md) 让 names 成为第二个使用者，于是连同共享的 `Session` 一起抽到中间层 `kototoki/strata.py`（第二个使用者出现后的抽取），`translate/strata.py` 随之删除、研究侧导入改指中间层。`ManagedServer`（端口检查、引擎与模型核对、显存轮询、驻留校验）在 [ADR-0014](../adr/0014-name-consistency-in-product.md) 时因翻译与建表两个使用者抽成共享的 `kototoki/llama_server.py`（`ServerSpec`）；ADR-0022 后产品没有使用者，只剩研究侧 `experiments/translation_v3/qwen.py`，文件留在原处、不删不挪（研究侧导入不改）。翻译的同调用内重启与降级留在 `generate.py`，经共享 `Session` 的 `stop()`／`ensure_started()` 重启；names 不做同调用内重启（每部影片最多 5 个请求，传输失败即停掉 Strata 并让该影片失败）。媒体 ↔ ffmpeg、VAD 与对齐后端、配置来源、SRT 写出器都只有一个实现，不做后端协议类或抽象层；换模型时改配方常量与实现，不改接口。在只有一个适配器的位置新建接缝须先在本节写明第二个使用者。内部接缝只供各自模块的测试使用、不属对外接口：共享的 `strata.Session(server_factory=..., client_factory=...)` 可换伪服务与伪客户端（names 与翻译都经它取客户端，真实客户端是 `llama_server.LlamaClient`），`protocol.run_worker` 的 `start` 回调可换伪处理函数，`artifacts.replace_with_retry` 的 `replace` 可注入。

测试穿过与调用方相同的接缝：`cues`、`merge`、`srt`、`artifacts`、`protocol`、`config` 直接按接口离线测；媒体测命令行构造与合成媒体；推理模块用冻结窗口门禁（重任务）；翻译子系统用伪客户端走完整流程；编排用伪 worker 脚本。需要越过接口去戳实现时，先怀疑模块形状。编排是最深的模块（一个入口承载全部流程知识），worker 壳的 `__main__` 只做入口，流程知识在协议模块。
