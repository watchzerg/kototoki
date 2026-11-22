---
covers:
  - kototoki/procs.py
  - kototoki/workers/protocol.py
  - kototoki/job.py
---
# 运行日志与进程原语子页：进程原语与 worker 子进程

`运行日志与进程原语` 的子页：进程存活与身份、子进程随编排器退出、O_EXCL 锁文件，以及 GPU worker 子进程的命令、环境、进度事件与崩溃重启。

## 进程原语

- **进程身份**：`pid_alive(pid)`（`os.kill(pid, 0)`；`PermissionError` 即别的用户的进程，视为存在；非整数或非正 pid 视为不存在）；`process_created(pid)` 取进程启动时间（`/proc/<pid>/stat` 第 22 个字段，开机以来的 clock tick；不可得时为 None）；`process_matches(pid, created)` 要求进程存活，且记录了启动时间时仍是同一进程（防 pid 复用）。
- **子进程随编排器退出**（[ADR-0034](../../../adr/0034-ubuntu-only-platform.md#子进程与长任务)）：`contained(command)` 在命令前加 `setpriv --pdeathsig KILL --`。创建子进程的线程一退出（含编排器被 SIGKILL），内核就向子进程发 SIGKILL；调用方因此在同一线程里等子进程结束。不用 `preexec_fn`（提取线程池在，多线程下不安全）。GPU worker 与 Strata CLI 另传 `start_new_session=True`，Ctrl+C 只到编排器、由它回收；ffmpeg 留在前台进程组，Ctrl+C 让它立即退出。Strata 服务是 CLI 再 fork 出的，不继承 PDEATHSIG，靠 `--stop` 收尾。
- **锁文件**（`ProcessLock(path, kind, info)`）：
  - `acquire` 用 O_EXCL 创建锁文件，写入 `pid`、`pid_created`、调用方的 `info`、`owner: "kototoki"`、`created_at_utc` 与 `replaced_stale_lock`。
  - 已有锁文件时：持有者存活（`process_matches`）即抛 `LockError`，从不抢占存活的持有者；没有 `pid_created` 的外部锁只按 pid 判断。
  - 残留锁（死 pid，或空的／无法解析的／pid 不是整数的锁文件）默认抛 `LockError`，消息提示 `KOTOTOKI_BREAK_STALE_LOCK=1`；`acquire(break_stale=True)` 时删除残留锁再创建，旧内容记入 `replaced_stale_lock`。
  - 并发创建撞上即抛 `LockError`。
  - `update(**fields)` 只在持有且锁文件仍属本进程时原子改写；`release()` 只删 pid 与创建时间都与本进程相同的锁。
  - 编排经 `update` 往 GPU 锁写附加字段：worker 运行期间 `worker_pid`／`worker_stage`（`Popen.pid`，`setpriv` exec 后即 worker 本身）；Strata 运行期间 `server_pid`（由共享 `strata.Session` 的 `on_server_pid` 回调提供：ready 后写入、停止后清空；pid 取自 `strata launch --status`，缺失时不记）。

## worker 子进程

**命令与 jobs**（`job._launch`、`job.worker_command`）：命令 `sys.executable -m kototoki.workers.<stage> --jobs <work root>/jobs-<stage>.json`，`cwd` 为仓库根。

- jobs 按 [STT worker](../stt-workers.md) 的约定：`recipe_hash` 为 `plan.recipe_hash(stage, engine=…)`，`config` 为 `{"engine", "models": plan.worker_models(config), "model_cache"}`，`inputs` 按 `plan.STAGE_INPUTS`（vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）；worker 用 `plan` 的身份函数写入身份，编排用同一函数核对。
- 子进程环境（`child_env`）：当前环境加 `PYTHONUTF8=1`、`HF_HUB_OFFLINE`／`TRANSFORMERS_OFFLINE`／`HF_DATASETS_OFFLINE`／`HF_HUB_DISABLE_TELEMETRY=1`、`PYANNOTE_METRICS_ENABLED=0`、`HF_HOME`＝`TORCH_HOME`＝`<work_dir>/cache/`，以及关进度条的 `QUIET_ENV`。
- stdout 逐行读进度 JSON，stderr 追加到 `<work root>/run-<时间戳>-<stage>.stderr.log`。进度事件进运行日志的方式：
  - `done`：INFO `[stage] done <相对路径>`，事件里除 `event`、`id` 之外的数值字段按事件自身的字段名以 `key=value` 追加，例 `[align] done S1/ep01.mkv: windows=195 failed_alignment_windows=1 text_only_units=417`（不建映射表）。
  - `failed`／`fatal`／`startup_failed` 不单独记行：`run_gpu_stage` 把事件的 `error_type` 交给 `ctx.fail`，失败只记一行 ERROR `[stage] FAILED <相对路径>: <类型>`（无 traceback，`failure.json` 已由 worker 写出）。
  - 启动失败先记一行 ERROR `[stage] worker startup failed: <类型>`，随后逐文件的 FAILED 行不带 traceback（`WorkerCrashed: <stage> worker startup failed: <类型>`）。
  - 退出码不是 0 或 1 时固定记 WARNING `[stage] worker exited with code <n>, see <stderr 文件名>`，与告警计数行互不替代：裸 traceback 与原生崩溃不按本格式、不计数，靠这一行指向。
- 同一类失败在多个文件的 FAILED 行里只在第一次带 traceback（batch-run-fixes 06.3）。类别 = 阶段 + 异常类型 + 抛出位置（最内层帧的文件与行号，`job._failure_kind`）；`PlanError` 包着缓存异常时按被包的异常算（如模型核对失败）。每个文件各抛一个新异常对象（如发布时同一处 `OSError`）也只带一次；同类型但抛出位置不同的算新的一类。

**崩溃与重启**（`job.run_gpu_stage`，按文件计）：每次启动 worker 后，`run_gpu_stage` 把待跑 id、退出码与进度事件交给 `protocol.classify_launch(ids, exit_code, events) -> LaunchOutcome`（规则见[产物契约](../artifact-contract.md)），自己只做循环与 `ctx.fail`：

- 报告 `failed` 的文件记该阶段失败（`failure.json` 已由 worker 写出）。
- 退出码 0／1 且每个待跑 id 都有事件：正常结束，其余按产物核对。有待跑 id 没有事件时不算正常结束（退出码 1 也是 Python 未捕获异常的退出码），按下面的崩溃规则处理。
- 有 `startup_failed` 事件（模型加载失败，与文件无关）：本阶段剩余文件全部失败，不重启。
- 有 `fatal` 事件：该文件失败，从下一文件重启 worker。
- 其他异常退出：最后一个有事件的文件之后的第一个文件即正在处理的文件，编排写 `failure.json`（`WorkerCrashed`）并从其后文件重启。
- `_launch` 读 worker stdout 期间抛异常（Ctrl+C、写日志失败）时，先 kill 并 wait 仍在运行的 worker，再向上抛；之后 `run` 的 `finally` 才释放 GPU 锁。

## 代码与验证入口

- 代码：`kototoki/procs.py`（`pid_alive`、`process_created`、`process_matches`、`contained`、`ProcessLock`、`LockError`）；worker 启动在 `kototoki/job.py`（`worker_command`、`_launch`、`run_gpu_stage`）；`kototoki/workers/protocol.py`（`classify_launch`）。
- 测试（core，`just test`）：
  - `tests/core/test_protocol.py`：`classify_launch`（正常、部分失败、`fatal`、`startup_failed`、无事件崩溃、退出码 1 但缺事件）。
  - `tests/core/test_procs.py`：锁内容、空锁文件与不可解析、无 `pid_created` 的外部锁、死 pid 与破锁、非整数 pid、并发创建、`update` 只改自己的锁、`release` 只删自己的锁；`/proc` 启动时间（含带空格与括号的 comm）与 pid 复用判定、`contained` 的命令前缀。
  - 同文件的 `LockTests`（锁冲突退出码、残留锁、空的／无法解析的锁、锁内 pid 记录）、`ScanTests`（早期失败时释放工作根锁）、`IsolationTests`（崩溃文件隔离、按文件重启、`_launch` 异常时回收 worker）。
- 测试（full，`just test-full`）：`tests/full/test_procs_children.py` 起真的父进程按产品方式启动子进程，强杀父进程后子进程随之结束，且子进程不在父进程的进程组里。
- 未验证：worker 退出码 2（CUDA 粘性错误）与按文件重启的真实路径。
- 未验证（Linux）：整批运行中强杀编排器后 GPU worker 释放显存的真实路径（Windows 时期的[最终验收](../../../research/acceptance/bilingual-pipeline-final-acceptance-2026-10-15.md)只作历史）。
