---
covers:
  - kototoki/job.py
  - kototoki/workers/protocol.py
---
# 运行日志与进程原语子页：worker 子进程

`运行日志、进程原语与 worker 子进程` 的子页：GPU worker 子进程的命令、环境、进度事件与崩溃重启。

## worker 子进程

**命令与 jobs**（`job._launch`、`job.worker_command`）：命令 `sys.executable -m kototoki.workers.<stage> --jobs <work root>/jobs-<stage>.json`，`cwd` 为仓库根。

- jobs 按 [STT worker](../stt-workers.md) 的约定：`recipe_hash` 为 `plan.recipe_hash(stage, engine=…)`，`config` 为 `{"engine", "models": plan.worker_models(config), "model_cache"}`，`inputs` 按 `plan.STAGE_INPUTS`（vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）；worker 用 `plan` 的身份函数写入身份，编排用同一函数核对。
- 子进程环境（`child_env`）：当前环境加 `PYTHONUTF8=1`、`HF_HUB_OFFLINE`／`TRANSFORMERS_OFFLINE`／`HF_DATASETS_OFFLINE`／`HF_HUB_DISABLE_TELEMETRY=1`、`PYANNOTE_METRICS_ENABLED=0`、`HF_HOME`＝`TORCH_HOME`＝`<work_dir>/cache/`，以及关进度条的 `QUIET_ENV`。
- stdout 逐行读进度 JSON，stderr 追加到 `<work root>/run-<时间戳>-<stage>.stderr.log`；stdout 上无法按 UTF-8 JSON 解析或不是 JSON 对象的非空行（缺结尾换行时补换行）加 `[stdout] ` 前缀转发到同一 stderr 日志（不静默丢弃，前缀使其不触发告警计数）。进度事件进运行日志的方式：
  - 哪些事件转发、附带哪些计数由 `protocol.progress_event` 判定，`job` 不含事件名字面量。
  - `done`：INFO `[stage] done <相对路径>`，事件里除 `event`、`id` 之外的数值字段按事件自身的字段名以 `key=value` 追加，例 `[align] done S1/ep01.mkv: windows=195 failed_alignment_windows=1 text_only_units=417`（不建映射表）。
  - `started`／`failed`／`fatal`／`startup_failed` 不单独记行：`started` 只标加载完成，失败由 `run_gpu_stage` 把原因交给 `ctx.fail`、只记一行 ERROR `[stage] FAILED <相对路径>: <类型>`（无 traceback）。
  - 启动失败先记一行 ERROR `[stage] worker startup failed: <原因>`，随后逐文件的 FAILED 行不带 traceback（`WorkerCrashed: <stage> worker startup failed: <原因>`）。
  - 退出码不是 0 或 1 时固定记 WARNING `[stage] worker exited with code <n>, see <stderr 文件名>`，与告警计数行互不替代：裸 traceback 与原生崩溃不按本格式、不计数，靠这一行指向。
- 同一类失败在多个文件的 FAILED 行里只在第一次带 traceback（batch-run-fixes 06.3）。类别 = 阶段 + 异常类型 + 抛出位置（最内层帧的文件与行号，`job._failure_kind`）；`PlanError` 包着缓存异常时按被包的异常算（如模型核对失败）。每个文件各抛一个新异常对象（如发布时同一处 `OSError`）也只带一次；同类型但抛出位置不同的算新的一类。

**崩溃与重启**（`job.run_gpu_stage`，按文件计）：每次启动 worker 后，`run_gpu_stage` 把待跑 id、退出码与进度事件交给 `protocol.classify_launch(ids, exit_code, events) -> LaunchOutcome`（规则见[产物契约](../artifact-contract/worker-protocol.md)），自己只做循环与 `ctx.fail`：

- 报告 `failed` 的文件记该阶段失败（`failure.json` 已由 worker 写出），失败类型取 `LaunchOutcome.error_types`；`fatal` 的崩溃文件同理。
- 正常结束的判定见协议规则，其余按产物核对。
- 启动失败、`fatal` 与其他异常退出的判定与重启规则以[协议规则](../artifact-contract/worker-protocol.md)为准：`run_gpu_stage` 按 `LaunchOutcome` 记失败，并写 `failure.json`（`WorkerCrashed`）。
- `_launch` 读 worker stdout 期间抛异常（Ctrl+C、写日志失败）时，先 kill 并 wait 仍在运行的 worker，再向上抛；之后 `run` 的 `finally` 才释放 GPU 锁。

## 代码与验证入口

- 代码：worker 启动在 `kototoki/job.py`（`worker_command`、`_launch`、`run_gpu_stage`）；`kototoki/workers/protocol.py`（`classify_launch`）。
- 测试（core，`mise run test`）：
  - `tests/core/test_protocol.py`：`run_worker` 先发 `started` 再逐文件处理、单文件失败隔离、`fatal` 以退出码 2 停止；`classify_launch` 的部分失败（不重启）、`fatal`（从下一文件重启）、无 `started` 启动崩溃（不重启）与 `started` 后／已处理文件后崩溃归咎；`failed_windows` 清空窗口文字并记录。
  - `tests/core/test_job.py` 的 `LockTests`（GPU 锁冲突时保留 CPU 阶段产物）与 `IsolationTests`（单文件崩溃隔离并按文件重启 worker、启动期崩溃整批失败且不重启、非 JSON stdout 转发到 stderr 日志）。
  - 测试精简（2026-11-22）后不再有测试覆盖（协议与编排侧）：
    - 协议：`jobs` 文件往返与畸形输入、全部完成退出 0 且每文件一行 UTF-8、启动失败退出码 2、`run_worker` 只加载一次、`classify_launch` 的 `startup_failed`、退出码 1 缺事件、全部已报告后崩溃无嫌疑、无待处理 id 的事件被忽略、`fail_window` 与 `validate` 的拒绝。
    - 编排侧：`startup_failed` 事件不重启、退出码 1 缺事件按崩溃重启、读 worker 输出时中断回收 worker、各类锁冲突与残留锁、空锁破除、锁内 pid 记录。
- 未验证：worker 退出码 2（CUDA 粘性错误）与按文件重启的真实路径。
