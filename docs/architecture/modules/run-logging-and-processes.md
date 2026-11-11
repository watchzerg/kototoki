# 运行日志、进程原语与 worker 子进程

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责三块基础设施：产品运行日志的目的地、行格式、级别与内容规则（`kototoki/logs.py` 的格式，挂接在 `job._run_logging`）；进程原语——进程存活与身份、KILL_ON_JOB_CLOSE Job Object、O_EXCL 锁文件（`kototoki/procs.py`）；编排启动 GPU worker 子进程的命令、环境与崩溃判定（`job._launch`、`job.run_gpu_stage`、`workers/protocol.classify_launch`）。流程中何时取哪把锁、哪些文件进哪个阶段归[批次编排](batch-orchestration.md)；worker 内部归 [STT worker](stt-workers.md)；各模块具体写哪些日志行见各自模块页。模块边界只规定日志目的地与格式归编排（[责任边界](../module-boundaries.md#产品包的责任边界)），本页是这些规则的正文。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

### 运行日志

- **框架**：标准库 `logging`，不用 `structlog`：读者只有人和 `grep`，第三方库的告警本就走标准库 logging，一个 root handler 即可收进同一文件，无需桥接，也不新增依赖。
- **挂接**：`job.run` 取到工作根锁后，在 `_run_logging` 上下文内给 root logger 挂两个 INFO 级 `StreamHandler`：`<work root>/run-<UTC戳>.log`（UTF-8、`\n` 行尾）与控制台（默认 `sys.stdout`），共用一个 `kototoki.logs.RunFormatter`；`kototoki` logger 临时设为 INFO。root 级别不动（默认 WARNING），所以第三方库只有 WARNING 及以上进日志。`run` 退出（含异常）时恢复级别、摘下并关闭 handler。
- **发事件的一方**：其他产品模块只经 `logging.getLogger(__name__)` 发事件，不配置 handler、不开文件：
  - `kototoki.job`；`kototoki.translate.*`；
  - `kototoki.strata`（Strata 启停、等显存与内存、接入检查、停止核实，前缀 `[strata]`）；
  - `kototoki.names.table`（不合格的建表尝试，前缀 `[names]`）；`kototoki.names` 包顶层不发日志，建表结果行由编排写；
  - worker 壳在子进程里，由 `workers/gpu.main` 用同一 `RunFormatter` 写 stderr（[STT worker](stt-workers.md)）。
- **级别**：
  - INFO：进度、计数与耗时——每阶段 start／逐文件 done／end、worker 的 stdout 进度事件、建表每部一行（条目数、丢弃数、prompt／completion token、秒数）、翻译每批一行、发布行的回退 cue 数、结尾汇总（含回退 cue 数）。
  - WARNING：流程继续但应看一眼的事——大小仍在变化、发布期发现字幕已出现而不覆盖、媒体告警（`[extract] <相对路径>: <告警>`；媒体模块不发日志，由编排在主线程逐条记，续跑跳过 extract 时照样出现）、worker stderr 有告警、建表终态失败写空表（`[names] done <相对路径>: build failed (<原因>), empty table`）、等显存超过 30 s、Strata 重启／降级拆批／回退保留日文。
  - ERROR：文件级与进程级失败，另含 Strata 被拒绝与停止未核实。DEBUG 不用。
- **行格式**（`kototoki/logs.py` 的 `LOG_FORMAT`／`LOG_DATEFMT`）：UTC 墙钟、自本次 `run` 起的相对秒、定宽级别、消息；非 `kototoki` logger 的消息前加 `[<logger 名首段>]`（如 `[transformers]`）。消息沿用 `[stage]` 前缀与 start／done／end／FAILED 词汇。例：

  ```
  2026-10-18 12:06:21Z [    10.0s] INFO     [scan] 2 file(s): 2 to process, 0 with subtitles, 0 unstable
  2026-10-18 12:41:07Z [  2096.0s] WARNING  [asr] 3 warning/error line(s), see run-20261018T120611Z-asr.stderr.log
  2026-10-18 13:05:02Z [  3531.0s] ERROR    [translate] FAILED S1/ep01.mkv: TranslateError
  ```

  文件级失败的 ERROR 行只带异常类型，traceback（`exc_info`）紧随其后，控制台与文件相同；失败由 worker 报告（`failure.json` 已由 worker 写出）时没有 traceback。
- **文件**：`<work root>/run-<UTC戳>.log` 与控制台逐行相同。`<work root>/run-<戳>-<stage>.stderr.log` 在每次启动该阶段 worker 时追加其 stderr（壳按同一格式写的日志、第三方告警与裸 traceback）；worker 退出后编排只读本次启动追加的部分，统计按本格式写出、级别为 WARNING／ERROR／CRITICAL 的行，非零时在运行日志记一行 WARNING（上例第二行），非本格式的行不计。Strata session 的证据（接入身份、资源峰值、停止核实）另在 `<work root>/strata-sessions/`（[翻译子系统](translation-subsystem.md)）。
- **内容**：
  1. 转写、cue 与窗口文字、译文、专名表条目与 `work_guess`、提示词、grammar、模型响应正文不进任何日志；失败窗口只记序号与 reason。
  2. 失败行只记异常类型，traceback 随后（只含源码行；异常消息可能含文件路径，不含转写）；异常消息不做通用截断；只有把异常首行嵌进一行日志的地方截到 200 字符：翻译的批次尝试失败行、Strata 重启行、放弃行与 `Strata refused` 行（`kototoki/translate/generate.py`），以及 names 的尝试失败行（`kototoki/names/table.py`）。翻译子系统的"意外异常"行不带 traceback，由编排的 FAILED 行带。
  3. 文件名用输入目录内相对路径，只有锁与日志文件的指向写绝对路径。
  4. 一事一行、每阶段三件套、结尾汇总；`end` 行带墙钟，翻译批次行带输出 token 数、tok/s 与 cache（取不到的字段省略）。
  5. 告警是级别不是措辞：消息里不写 `WARNING`。
- **子进程噪声**：`job.child_env` 在离线变量之外合入 `job.QUIET_ENV`（`TQDM_DISABLE=1`、`HF_HUB_DISABLE_PROGRESS_BARS=1`、`TRANSFORMERS_VERBOSITY=warning`），让 worker stderr 只留日志行；这组变量归编排。
- **启动早期错误**：用法与配置错误、工作根锁与 GPU 锁冲突由 `__main__` 打印到 stderr（控制台流设 `errors="backslashreplace"`），以退出码区分，不写成日志行。

### 进程原语

- **进程身份**：`pid_alive(pid)`（Windows 上 `OpenProcess` 被拒绝即视为存在；非整数或非正 pid 视为不存在）；`process_created(pid)` 取进程创建时间（Windows FILETIME，不可得时为 None）；`process_matches(pid, created)` 要求进程存活，且记录了创建时间时仍是同一进程（防 pid 复用）。
- **Job Object**：`contain_children()` 把当前进程放进 KILL_ON_JOB_CLOSE Job Object，此后启动的子进程自动加入；句柄只由本进程持有、从不显式关闭，进程以任何方式退出时系统关闭句柄，子进程随之结束。每个进程只做一次；非 Windows 平台不做；建立失败抛 `OSError`。
- **锁文件**（`ProcessLock(path, kind, info)`）：
  - `acquire` 用 O_EXCL 创建锁文件，写入 `pid`、`pid_created`、调用方的 `info`、`owner: "kototoki"`、`created_at_utc` 与 `replaced_stale_lock`。
  - 已有锁文件时：持有者存活（`process_matches`）即抛 `LockError`，从不抢占存活的持有者；没有 `pid_created` 的外部锁只按 pid 判断。
  - 残留锁（死 pid，或空的／无法解析的／pid 不是整数的锁文件）默认抛 `LockError`，消息提示 `KOTOTOKI_BREAK_STALE_LOCK=1`；`acquire(break_stale=True)` 时删除残留锁再创建，旧内容记入 `replaced_stale_lock`。
  - 并发创建撞上即抛 `LockError`。
  - `update(**fields)` 只在持有且锁文件仍属本进程时原子改写；`release()` 只删 pid 与创建时间都与本进程相同的锁。
  - 编排经 `update` 往 GPU 锁写附加字段：worker 运行期间 `worker_pid`／`worker_stage`（`Popen.pid`；用 venv 的 `python.exe` 启动时这是启动器进程，真正的 worker 是它的子进程）；Strata 运行期间 `server_pid`（由共享 `strata.Session` 的 `on_server_pid` 回调提供：ready 后写入、停止后清空；pid 取自 `strata launch --status`，缺失时不记）。

### worker 子进程

**命令与 jobs**（`job._launch`、`job.worker_command`）：命令 `sys.executable -m kototoki.workers.<stage> --jobs <work root>/jobs-<stage>.json`，`cwd` 为仓库根。

- jobs 按 [STT worker](stt-workers.md) 的约定：`recipe_hash` 为 `plan.recipe_hash(stage, engine=…)`，`config` 为 `{"engine", "models": plan.worker_models(config), "model_cache"}`，`inputs` 按 `plan.STAGE_INPUTS`（vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）；worker 用 `plan` 的身份函数写入身份，编排用同一函数核对。
- 子进程环境（`child_env`）：当前环境加 `PYTHONUTF8=1`、`HF_HUB_OFFLINE`／`TRANSFORMERS_OFFLINE`／`HF_DATASETS_OFFLINE`／`HF_HUB_DISABLE_TELEMETRY=1`、`PYANNOTE_METRICS_ENABLED=0`、`HF_HOME`＝`TORCH_HOME`＝`<work_dir>/cache/`，以及关进度条的 `QUIET_ENV`。
- stdout 逐行读进度 JSON 写入运行日志，stderr 追加到 `<work root>/run-<时间戳>-<stage>.stderr.log`。

**崩溃与重启**（`job.run_gpu_stage`，按文件计）：每次启动 worker 后，`run_gpu_stage` 把待跑 id、退出码与进度事件交给 `protocol.classify_launch(ids, exit_code, events) -> LaunchOutcome`（规则见[产物契约](artifact-contract.md)），自己只做循环与 `ctx.fail`：

- 报告 `failed` 的文件记该阶段失败（`failure.json` 已由 worker 写出）。
- 退出码 0／1 且每个待跑 id 都有事件：正常结束，其余按产物核对。有待跑 id 没有事件时不算正常结束（退出码 1 也是 Python 未捕获异常的退出码），按下面的崩溃规则处理。
- 有 `startup_failed` 事件（模型加载失败，与文件无关）：本阶段剩余文件全部失败，不重启。
- 有 `fatal` 事件：该文件失败，从下一文件重启 worker。
- 其他异常退出：最后一个有事件的文件之后的第一个文件即正在处理的文件，编排写 `failure.json`（`WorkerCrashed`）并从其后文件重启。
- `_launch` 读 worker stdout 期间抛异常（Ctrl+C、写日志失败）时，先 kill 并 wait 仍在运行的 worker，再向上抛；之后 `run` 的 `finally` 才释放 GPU 锁。

## 接口与依赖

`workers/protocol` 的 jobs 读写与 `classify_launch` 是编排与 worker 之间的协议（[产物契约](artifact-contract.md)、[STT worker](stt-workers.md)）。`logs` 只依赖标准库；`procs` 只依赖标准库、`ctypes` 与基础层 `artifacts`（锁内容的时间戳与原子改写）。二者属基础层，与流水线无关。使用方：`kototoki.job`（`RunFormatter`、`ProcessLock`、`LockError`、`contain_children`）与 `kototoki.workers.gpu`（`RunFormatter`）。`procs` 复制自 `experiments/translation_v3/procs.py`，不导入；`job` 从它导入，测试以 `mock.patch("kototoki.job.contain_children")` 替换。

## 代码与验证入口

- 代码：`kototoki/logs.py`（`LOG_FORMAT`、`LOG_DATEFMT`、`RunFormatter`）、`kototoki/procs.py`（`pid_alive`、`process_created`、`process_matches`、`contain_children`、`ProcessLock`、`LockError`）；挂接与 worker 启动在 `kototoki/job.py`（`_run_logging`、`QUIET_ENV`、`child_env`、`worker_command`、`_launch`、`run_gpu_stage`）；`kototoki/workers/protocol.py`（`classify_launch`）。
- 测试（core，`just test`）：
  - `tests/core/test_protocol.py`：`classify_launch`（正常、部分失败、`fatal`、`startup_failed`、无事件崩溃、退出码 1 但缺事件）。
  - `tests/core/test_procs.py`：锁内容、空锁文件与不可解析、无 `pid_created` 的外部锁、死 pid 与破锁、非整数 pid、并发创建、`update` 只改自己的锁、`release` 只删自己的锁。
  - `tests/core/test_job.py` 的 `RunLogTests`：文件与控制台逐行相同且符合格式、告警与失败的级别、extract 三件套、媒体告警逐条 WARNING（含续跑跳过 extract）、补偿告警的阈值与续跑、失败行后的 traceback、handler 与级别复原、第三方前缀与级别过滤、worker stderr 的告警计数。
  - 同文件的 `LockTests`（锁冲突退出码、残留锁、空的／无法解析的锁、锁内 pid 记录）、`ScanTests`（Job Object 建立失败时释放工作根锁）、`IsolationTests`（崩溃文件隔离、按文件重启、`_launch` 异常时回收 worker）。
- 测试（full，`just test-full`）：`tests/full/test_media_ffmpeg.py` 的合成 2 s 间隙断言 `job.compensation_warnings` 给出一行补入告警。
- 未验证：worker 退出码 2（CUDA 粘性错误）与按文件重启的真实路径。
- 真实路径：asr 阶段强杀编排器后 worker 随 Job Object 退出、残留锁默认拒绝，见[最终验收](../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)。

## 变更与决策来源

- [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- 运行日志设计与真实运行核对：`.scratch/runtime-logging/`（`spec.md` 及票据 01–04）
- 小修集合（媒体告警、extract 三件套、空锁破除）：`.scratch/architecture-review/issues/01-small-fixes.md`
- 进程原语移入基础层：计划 [`architecture-cleanup`](../../plans/architecture-cleanup.md)，`.scratch/architecture-cleanup/`
- [技术选型](../../development/technology-stack.md)（`structlog` 未采用）
