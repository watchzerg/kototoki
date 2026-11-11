# 03 worker 壳日志与第三方噪声

Status: resolved
Type: task
Blocked by: 01

## 范围

规格见 [spec.md](../spec.md) §3.2、§3.7。

- `kototoki/workers/gpu.py::main`：解析参数后 `logging.basicConfig(stream=sys.stderr, level=INFO, format=<与 01 相同的格式>)`，`asctime` UTC、`elapsed` 自进程启动；`warnings.captureWarnings(True)`。stdout 仍只有协议 JSON 行，不得有任何 logging 输出。
- 壳记录（logger `kototoki.workers.<stage>`）：`start` 内模型核对与加载耗时 `info`；每文件 `info`（id、窗口数、失败窗口数、推理秒数，字段取自 `compute` 已返回的 `fields`／`stages`，不新增统计）；失败窗口逐条 `warning`（`chunk_index`、`reason`，**不记 `text`**）；`FatalWorkerError` 与单文件异常在 `protocol.run_jobs` 捕获处 `error` 带 `exc_info`（协议模块只依赖标准库，可直接用 logger；stdout 协议行不变）。
- `kototoki/job.py::child_env`：加 `TQDM_DISABLE=1`、`HF_HUB_DISABLE_PROGRESS_BARS=1`、`TRANSFORMERS_VERBOSITY=warning`（只改这一个函数及其测试）。
- 推理模块 `vad.py`、`asr_whisper.py`、`asr_qwen.py`、`align.py` 不加日志、不 print。

## 完成标准

- `just test` 全绿；`tests/core/test_stt_workers.py`（或协议测试）加用例：伪 `start`／`process` 下 stderr 有 INFO 行与失败窗口 WARNING 行且不含窗口文字，stdout 只有 JSON 行；`child_env` 含三个新变量。
- 真实 GPU 运行核对 stderr 文件无进度条属重任务，本票不跑，在评论里标为"未验证"。

## 文件所有权

`kototoki/workers/{gpu,protocol,vad,asr,align}.py`、`kototoki/job.py` 的 `child_env`（及 `OFFLINE_ENV` 常量附近）与 `tests/core/test_job.py` 中对应断言、`tests/core/test_stt_workers.py`。**不改 `kototoki/translate/*`**（02 正在改它）。

## Comments

- 2026-10-18 实现完成（Opus 5.5，worktree `.claude/worktrees/rl-03`，未提交）：
  - 共用格式：新增基础层模块 `kototoki/logs.py`（只依赖标准库），从 `job.py` 移入 `LOG_FORMAT`、`LOG_DATEFMT` 与 `_RunFormatter`（改名 `RunFormatter(started)`，行为不变）；`job.py` 改为从 `kototoki.logs` 导入，`_STDERR_PROBLEM` 与 `_run_logging` 留在 `job.py`。worker 不导入 `job`。
  - `workers/gpu.main`：解析参数后在 root 上挂一个写 `sys.stderr` 的 `StreamHandler`（`RunFormatter(started=main 开始时刻)`），`kototoki` logger 设 INFO（第三方按 root 默认只有 WARNING 及以上），`logging.captureWarnings(True)`。stdout 仍只有协议 JSON 行。
  - 壳日志（logger `kototoki.workers.<stage>`）：`start` 里 `[<stage>] verified N model file(s)`（asr 为 `[asr] engine <e>: verified N model file(s)`）与 `[<stage>] model loaded in X.Xs`；每文件 INFO：vad `[vad] <id>: N window(s), inference X.Xs`，asr `[asr] <id>: N window(s), M failed, inference X.Xs`，align `[align] <id>: N window(s), M failed alignment, K text-only unit(s), inference X.Xs`（字段取自已有 `fields`／`inference_s`，未新增统计）；asr 失败窗口逐条 WARNING `[asr] <id>: window <chunk_index> failed: <reason>`，align 对齐失败窗口逐条 WARNING `[align] <id>: window <segment_index> alignment failed: <failure>`，均不记窗口文字（核对过 `asr_whisper`／`asr_qwen`／`align` 的 reason 只含异常类型与消息或 token 计数）。
  - `protocol.py`（仍只依赖标准库）：`run_jobs` 的 `FatalWorkerError` 与单文件异常分别 `error("[<stage>] FATAL|FAILED <id>: <异常类型>", exc_info=...)`；`run_worker` 启动失败 `error("startup failed: <异常类型>", exc_info=...)`。
  - `job.py`：`OFFLINE_ENV` 旁新增 `QUIET_ENV`（`TQDM_DISABLE=1`、`HF_HUB_DISABLE_PROGRESS_BARS=1`、`TRANSFORMERS_VERBOSITY=warning`），`child_env` 合入。推理模块、`kototoki/translate/*`、文档未动。
- 自动检查：`python -m unittest discover -s tests/core -t .` 358 个测试全部通过（原 355 + 3：`test_child_environment_silences_progress_bars`；`WorkerLogTest` 两个真实子进程用例——伪 `start` 跑 asr 壳时 stderr 每条日志行符合格式、含失败窗口 WARNING（chunk_index＋reason）与每文件 INFO、单文件异常的 ERROR＋traceback、不含失败窗口文字，stdout 只有 done／failed 两行 JSON；`python -m kototoki.workers.vad` 配方不符时 stderr 首行为 `ERROR    startup failed: ValueError` 并带 traceback，stdout 只有 `startup_failed`）。`test_protocol.py` 的单文件失败、fatal 与启动失败用例改为 `assertLogs` 断言 ERROR 记录带 `exc_info`。进程内跑壳的测试挂 `NullHandler`，测试输出无日志噪声。`compileall -q kototoki` 通过；`job.py` 导入守门与壳导入不加载 torch 的测试仍通过。
- 未验证：真实 GPU 运行下 stderr 无进度条：未验证（重任务，本票不跑）。另注意：`exc_info` 的异常消息含文件路径（如 `FileNotFoundError`），不含转写；架构文档（基础层清单需加 `logs`、stt-workers 模块页的日志说明）留给票据 04。
