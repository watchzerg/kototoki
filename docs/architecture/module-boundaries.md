# 模块边界

状态：current；

权威决定：[ADR-0003](../adr/0003-new-pyannote-baselines.md)、[ADR-0028](../adr/0028-names-accept-empty-table.md)、[ADR-0029](../adr/0029-translate-per-cue-resolution.md)、[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0030](../adr/0030-asr-window-plausibility-guard.md)、[ADR-0024](../adr/0024-embedded-japanese-subtitles.md)、

[ADR-0025](../adr/0025-product-package-boundaries.md)、[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)；

现行配方见 [CURRENT](../adr/CURRENT.md)

本文只规定依赖方向、唯一归属、接缝、状态与并发规则。各模块做什么见[架构总览](INDEX.md)的模块表与各模块页；模块页说明自己如何遵守，实际偏差在模块页就地注明，不在此改写规则。

## 职责归属

每条规则只有一个归属；消费方调用或读取，不复制。

产品包 `kototoki/`：

- 工作目录布局、产物文件名、身份与 `is_current`、原子写、`failure.json`、`published.json`、worker 协议（含读侧 `protocol.classify_launch`）、SRT 毫秒取整、三个 cross 审计产物的文件名与位置（不是阶段产物，不参与 `is_current`）归[产物契约](modules/artifact-contract.md)。
- 配置与路径解析、媒体配方、`recipe_hash`（翻译与建表配方除外）归[配置与媒体](modules/config-and-media.md)；`SAMPLE_RATE`、`MAX_WINDOW_SAMPLES` 只在 `kototoki/recipes.py` 定义。
- 时间轴零点只在 `media` 定义（`offset_s` 恒为 0）；内嵌字幕的判定、抽取与清洗也归该页，`embedded` 不知道工作目录与产物。是否采用、回退到 STT、写 `ja.srt` 与 `ja-embedded.json`、跳过判定归编排，`ja-embedded.json` 的身份归阶段计划。
- 日文 cue 是时间轴上唯一加 offset 的地方，归[日文 cue](modules/japanese-cues.md)。
- STT 推理、`cross` 引擎与 `kototoki/schema.py` 的校验归 [STT worker](modules/stt-workers.md)。`judge` 不导入推理模块，打分由调用方传入的 `WhisperAsr.score` 做；`guard` 只处理字符串，改写、trace 与把置空窗口记失败归 worker 壳，x0 不用守卫。
- 阶段链、`ENGINE_PARTS`（唯一出处）、模型清单与各阶段期望身份归[阶段计划](modules/stage-plan.md)；translate 身份转问翻译子系统，是否已发布由编排按字幕文件是否存在判定。
- 翻译配方与 `RECIPE_HASH`（只在 `kototoki/translate/recipes.py`）、注入规则、run 目录键、`needs_model`、按条追问与未翻译归[翻译子系统](modules/translation-subsystem.md)；双语合并归[双语合并](modules/translation-subsystem/bilingual-merge.md)。
- 建表配方与 hash（只在 `kototoki/names/recipes.py`）、建表请求额度与 `name-table.json` 的内容归[专名一致性](modules/name-consistency.md)；文件由编排写，表的用法（注入哪些行）归翻译子系统。
- 扫描、调度、锁、发布、子进程环境与运行日志归[批次编排](modules/batch-orchestration.md)；进程原语在基础层 `kototoki/procs.py`，日志行格式在 `kototoki/logs.py`。
- 本机回环客户端 `LlamaClient`、`InfraFailure`、失败分类 `classify_failure`／`response_body` 归 `kototoki/local_client.py`；llama-server 进程生命周期不在产品里，`list_llama_servers` 在 `scripts/smoke/`。
- Strata 起停、显存轮询（`nvidia_smi`、`wait_for_free_vram`）、身份核对与常量、共享 `Session` 归 `kototoki/strata.py`（[Strata session](modules/strata-session.md)）；启动额度只由 `Session` 计数，`unavailable` 只由它写。

## 依赖方向

研究与产品（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md) R5、R6）：

- 产品永不导入研究代码（Python 包 `research`）；研究可以导入产品符号，直接调用产品实现，不保留研究侧副本。
- 研究数据经仓库根 `data.toml` 与环境变量 `KOTOTOKI_DATA` 定位，代码与文档不写本机绝对路径。
- 产品符号移动或改名时，产品不为研究侧保留再导出模块；研究代码随之改导入行。

产品包 `kototoki/`（分层图见[架构总览](INDEX.md)），依赖只向下：

- 编排层：`job`、`__main__`。
- 编排之下：`media`、`cues`、`embedded`（纯函数，只依赖 `srt`）、`merge`、`plan`、`names`、翻译子系统。
- 中间层：`plan` 与 worker 壳（壳导入 `plan` 取身份与模型清单）、`strata`、`local_client`；`names` 与翻译都经 `strata` 与 `local_client`。
- 基础层：`config`、`recipes`、`artifacts`、`srt`、`workers/protocol`、`schema`、`logs`、`procs`、`judge`、`guard`。
- 推理模块 `vad`、`asr_*`、`align` 只依赖基础层，只由 worker 壳导入。

四条硬规则：

- **编排层不导入任何推理模块。** `job` 只以 `sys.executable -m kototoki.workers.<stage> --jobs <path>` 启动 worker，通信只经 jobs 文件、产物与退出码。编排不导入 worker 壳；期望身份来自 `plan`，模型核对只用 `workers/gpu.verify_models`（导入时不加载推理库）。`tests/core/test_job.py` 的 `InvariantTests.test_job_and_main_import_no_inference_stack` 守门（`torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`、`research`）。
- **推理模块互不导入。** 各自在独立进程加载模型，阶段之间只经产物文件交接。`workers/gpu.py` 只被 worker 壳与编排导入，不属基础层。
- **基础层不依赖 torch、ffmpeg、网络与上层。** 编排可直接导入。`judge`、`guard` 不导入 torch、推理模块与研究代码；`judge.normalize`、`schema.validate_transcript` 与 `guard` 的算法当初复制自已删除的研究代码（归档 tag，见 [ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)），现在产品实现是唯一权威；`guard` 只导入 `recipes` 与 `judge.normalize`。
- **产品包不导入 `research`**。`tests/core/test_boundaries.py` 以 AST 扫描 `kototoki/` 全部模块、并要求 `tests/core` 自身不导入 `research`。

中间层规则：

- `local_client` 只依赖基础层，发 HTTP，基础层不得导入它；`strata`、翻译子系统与 `names` 单向依赖它。
- `strata` 只依赖基础层与 `local_client`；不导入 `names`、翻译子系统、torch。`names` 与翻译子系统单向依赖它，研究代码也可以直接导入它。
- `names` 只依赖 `artifacts`、`srt`、`recipes`、`strata`、`local_client`；不导入 `config`、翻译子系统、torch。
- 翻译子系统不导入 `names`，只读 `name-table.json` 的内容（经 `plan` 传入）。
- 编排以普通导入使用 `strata`、`names`、`translate`、`merge`：四者不导入 `plan` 与 `job`、不加载 torch，由同一条禁止导入测试守门（含 `names`、`translate`）。
- `plan` 只在核对翻译阶段时延迟导入 `translate`，只在核对 names 阶段时延迟导入 `names.recipes`（只取 `BUILD_RECIPE_HASH`）；worker 壳导入 `plan`，但不会触发这两条边。

## 状态与契约

- 输入身份以内容为准（`file_sha256`、`pcm_sha256`、采样率、声道、样本数、时长、`offset_s`），路径可以不同。
- 运行身份（recipe 名、`recipe_hash`、模型 SHA256）是派生结果可比的前提；同名配方内容不同时拒绝续跑。

## 并发与生命周期

- `.local/gpu.lock` 是所有 GPU 作业共用的互斥文件，全部以 `O_EXCL` 创建，不抢占、不杀进程。
  - 产品的实现是 `kototoki/procs.py` 的 `ProcessLock`（记录 `pid_created` 并处理过期锁）；`scripts/smoke/` 另有写入方，统一它们不在当前范围。
- 产品 STT 阶段之间串行。例外：`cross` 引擎的 asr worker 让 Whisper（CT2）与 Qwen（torch）同进程共驻到退出，运行时不按显存回退；translate、align 不与之共驻（[ADR-0003](../adr/0003-new-pyannote-baselines.md)）。
- 产品只有一个服务进程 Strata，由共享 `strata.Session` 管理：
  - 整批一个，首次真正需要模型时才启动（names 或 translate），两阶段之间不停；没有影片需要模型时不启动。
  - 启动前 `strata launch --status` 必须为空（不抢占别人的 launch），空闲显存达到 14000 MiB、可用内存达到 50 GiB。
  - 结束、出错或编排被中断（`Session` 是上下文管理器）都执行 `strata launch --stop`，并核实 status 为空、显存回到 14000 MiB。
  - 启动失败整批累计 3 次，或 `StrataRefused`，即置 `unavailable`；额度由 names 与翻译共用。
  - 产品不启动 llama-server。产品进程被强杀时 Strata 可能留在后台，下次因 status 非空而拒绝，需手动 `strata launch --stop`。

## 产品包的责任边界

双语字幕流水线按"谁有权做这个决定"划分，每项只有一个归属：

- **时间轴**只在三处出现：媒体定零点；推理模块输出 WAV 本地坐标（`align.map_records`、`MmsAligner.align` 不收 offset）；日文 cue 给窗口边界、VAD 子段与 units 各加一次 offset。采用内嵌字幕的文件没有后两处：时间由 ffmpeg 按同一零点转出，`embedded.clean` 只排序、不改时间。编排、翻译、合并不做时间换算；翻译只读 `ja.srt` 相邻 cue 的停顿长短来切包与取邻文。
- **跳过与替换**由产物契约的 `is_current` 判定，期望身份与"下一个要跑的阶段"由阶段计划给出，编排只负责问；推理模块永远不决定要不要跑。
- **失败分三级，各归一层**，判定是 `protocol.classify_launch` 的纯函数规则，编排只循环与记账：
  - 窗口级 `failed_windows`：推理模块填、协议校验，不进对齐、cue 与翻译。
  - 文件级：worker 报 `failed` 事件、退出码 1，编排继续下一文件。
  - worker 进程级：退出码 2 带 `fatal`，该文件失败、从下一文件重启 worker；退出码 2 带 `startup_failed` 或既无 `started` 又无文件事件的异常退出（启动／加载模型原生崩溃），本阶段剩余文件全部失败、不重启；其余异常退出（或退出码 0／1 缺事件），最后一个有事件的文件之后那个（有 `started` 无文件事件时为首个）记 `WorkerCrashed`，从其后重启。
  - 批次级：任何阶段撞 `.local/gpu.lock` 都以退出码 4 结束整批，不写逐文件 `failure.json`。
- **翻译与建表的基础设施失败**：
  - 翻译子系统内部消化传输、OOM、server 错误与 Strata 起不来，最多重启 Strata 两次，受整批 3 次启动额度约束；再往上抛即该文件的文件级失败。
  - `StrataRefused`（身份不符、已有别的 launch、专家区退到 mmap）不重试，共享 `Session` 置为不可用，本批其余需要模型的影片在 names 与 translate 都直接失败。
  - 批次终态失败（两次尝试都失败）在子系统内按 10→5→1 降级，单条仍失败保留日文。
  - 建表的传输、HTTP、OOM 与意外异常停掉 Strata，是该文件 names 阶段的文件级失败（下一部需要模型的影片再启动，计入整批 3 次）。
  - 建表终态失败（5 次都不合格、超预算）只写空表、不算失败（翻译照常，不注入）。发布没有专名替换，因而没有替换失败。
- **发布**只有编排能做：`ja-zh.srt` 写一份副本到工作目录 → 原子写到源文件旁（临时文件建在目标目录内，不跨卷移动）→ `record_published`。源文件旁已有同名字幕的文件在扫描阶段即跳过，不进任何阶段。
- **锁**全归编排：`<work_dir>/<目标目录键>/lock` 与 `.local/gpu.lock`；翻译子系统、`names` 与 `strata.Session` 都不取锁。翻译按 `needs_model` 决定是否取 GPU 锁也由编排判断。
- **身份**：
  - 各阶段 `recipe_hash` 归 `recipes.py`，翻译配方 hash 归 `translate/recipes.py`，建表配方 hash 归 `names/recipes.py`，模型 SHA256 经产物契约的缓存。
  - 翻译身份 = `{ja_srt_sha256, recipe_hash, seed, names_sha256}`；`names_sha256` 是注入行的哈希：手改会被注入的条目即换身份、重译，只改 medium／low 条目不会。
  - 每个阶段期望身份的组成只在 `plan.py` 写一次，worker 壳与编排消费不复制；没有模块把绝对路径写进身份。
- **子进程环境**归编排：`PYTHONUTF8=1`、离线变量、共用 `HF_HOME`／`TORCH_HOME=<work_dir>/cache/` 由编排传入，worker 不自行设置 PATH 或 `LD_LIBRARY_PATH`。
- **日志**目的地与格式只归编排（`kototoki/logs.py` 的格式；`gpu.main` 只把 worker 日志按同一格式写到 stderr，由编排存档）。
  - 产品模块经各自 `kototoki.*` logger 发进度与告警：`job`、`translate.*`、`strata`（前缀 `[strata]`）、`names.table`（不合格的尝试）、worker 壳；`names` 包顶层只发 `count_tokens` 不可用与停 Strata 前的两条 WARNING，建表结果行由编排写。
  - 推理模块不发日志、不打印；转写、译文、提示与模型响应正文不进任何日志。细则见[批次编排](modules/batch-orchestration.md)。

### 接缝

有两个适配器的位置才是真接缝；只有一个适配器时保持具体实现、不抽象。真接缝有三处：

- ASR 引擎：`w0`、`x0`、`cross` 写出同一种 `asr.json`，由 `config.engine` 选择；`cross` 由 `asr_whisper`＋`asr_qwen`＋`judge` 组合，不是新的推理模块。
- 编排器 ↔ 阶段 worker：真实子进程或测试用伪 worker 脚本，接口是 jobs 文件＋增量结果＋退出码。
- names 与翻译 ↔ Strata HTTP 服务：`local_client.LlamaClient` 或测试用伪客户端，两阶段都经 `Session.client(trace_dir, *, timeout)` 取得。

共享 session 的调用契约：

- 编排持有 `strata.Session`，传给 `names.build_document(work_dir, document, session, seed)` 与 `translate_document(plan, session)`。
- 两阶段经 `ensure_started()` 取运行中的服务、经 `label` 与 `client()` 取 session 名与客户端，基础设施失败时 `stop()`；不碰 `ordinal`、`runtime_root`、`client_factory`。
- `plan` 调用 `translate.plan(work_dir, document, name_table, config)` 取翻译身份与 `needs_model`；编排从 `TranslateResult` 读回退计数。
- 翻译的同调用内重启与降级留在 `kototoki/translate/generate.py`，经 `stop()`／`ensure_started()` 重启；names 不做同调用内重启。

单一实现、不做后端协议或抽象层：`StrataServer`（产品只有 Strata 一个推理后端）、媒体 ↔ ffmpeg、VAD 与对齐后端、配置来源、SRT 写出器。换模型时改配方常量与实现，不改接口。在只有一个适配器的位置新建接缝，须先在本节写明第二个使用者。

内部接缝只供各自模块的测试使用、不属对外接口：`strata.Session(server_factory=..., client_factory=...)` 换伪服务与伪客户端（`client_factory` 只经 `Session.client()` 使用；伪服务与装配只有 `tests/core/strata_fakes.py` 一份）；`protocol.run_worker` 的 `start` 回调；`artifacts.replace_with_retry` 的 `replace`。

测试穿过与调用方相同的接缝：

- `cues`、`merge`、`srt`、`artifacts`、`protocol`（含 `classify_launch`）、`procs`、`judge`、`config` 直接按接口离线测。
- 需要钉住的研究来源取值在 core 里钉字面量，注释写来源（ADR 或归档 tag 路径）；没有实时对照层（[ADR-0031](../adr/0031-research-layout-and-lightweight-records.md)）。
- 媒体测选轨、时长与采样率纠正等判定，真实 ffmpeg 行为用合成媒体（full）；推理模块用冻结窗口门禁（重任务）；翻译子系统用伪客户端走完整流程；编排用伪 worker 脚本。
- 需要越过接口去戳实现时，先怀疑模块形状。编排是最深的模块；worker 壳的 `__main__` 只做入口，流程知识在协议模块。
