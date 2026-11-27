---
covers:
  - kototoki/logs.py
  - kototoki/job.py
---
# 运行日志与进程原语子页：运行日志

`运行日志与进程原语` 的子页：产品运行日志的目的地、挂接、行格式、级别与内容规则。

## 运行日志

- **框架**：标准库 `logging`，不用 `structlog`：读者只有人和 `grep`，一个 root handler 就能把第三方告警收进同一文件。
- **挂接**：`job.run` 取到工作根锁后立即进入 `_run_logging` 上下文（使 `input.json` 登记、运行主体、结尾汇总以及 GPU 锁与工作根锁释放都在日志兜底之内），给 root logger 挂两个 INFO 级 `StreamHandler`：`<work root>/run-<UTC戳>.log`（UTF-8、`\n` 行尾）与控制台（默认 `sys.stdout`），共用一个 `kototoki.logs.RunFormatter`；`kototoki` logger 临时设为 INFO，并开 `logging.captureWarnings(True)`（`warnings.warn` 以 `[py]` 前缀进日志），root 级别不动。
  退出（含异常）时恢复级别与 `captureWarnings` 状态、摘下并关闭 handler；若 `_run_logging` 自身打开失败，外层 `finally` 仍确保释放工作根锁。
- **发事件的一方**：其他产品模块只经 `logging.getLogger(__name__)` 发事件，不配置 handler、不开文件：
  - `kototoki.job`；`kototoki.translate.*`；`kototoki.artifacts`（既有产物读取失败记 WARNING，覆盖既有产物记 INFO）；`kototoki.srt`（覆盖既有字幕记 INFO）；
  - `kototoki.strata`（Strata 启停、等显存与内存、接入检查、停止核实，前缀 `[strata]`）；
  - `kototoki.names.table`（不合格的建表尝试，前缀 `[names]`）；`kototoki.names` 包顶层只发 `count_tokens` 不可用与停 Strata 前的两条 WARNING，建表结果行由编排写；
  - worker 壳在子进程里，由 `workers/gpu.main` 用同一 `RunFormatter` 写 stderr（[STT worker](../stt-workers.md)）。
- **级别**：
  - INFO：进度、计数与耗时——每阶段 start／逐文件 done／end、worker 启动（`pid` 与文件数）与 stdout 进度事件、清理既有残留临时文件或既有 `failure.json`（仅确实删除时记对象与原因）、覆盖既有阶段产物／字幕文件／解码日志／派生 WAV（仅确实覆盖时记对象与原因，首次新建不记）、建表每部一行、翻译每批一行、发布行、结尾汇总。
  - WARNING：流程继续但应看一眼的事——`ffmpeg=unavailable` 诊断、大小仍在变化或扫描 `stat()` 失败、既有产物无法读取或解析、发布期发现字幕已出现而不覆盖、媒体告警（含 `ffprobe` 与字幕抽取退出码 0 时的非空 `stderr`，由编排在主线程逐条记，续跑跳过 extract 时照样出现）、worker stderr 告警或非零退出（单次启动最多一条合并 `see <stderr>` 指针）、建表终态失败写空表、等显存超过 30 s、Strata 重启／停服前意外异常／续跑截断 JSONL／追问与拆分（回放不重打）／未翻译。
  - ERROR：文件级与进程级失败，另含 Strata 不可用（被拒绝或启动额度用尽，整批一次）与停止未核实。DEBUG 不用。
- **行格式**（`kototoki/logs.py` 的 `LOG_FORMAT`／`LOG_DATEFMT`）：UTC 墙钟、自本次 `run` 起的相对秒（单调时钟，格式化时取：系统时钟被校正时不跳变；时间戳仍是墙钟，会随校正跳）、定宽级别、消息；非 `kototoki` logger 的消息前加 `[<logger 名首段>]`（如 `[transformers]`）。消息沿用 `[stage]` 前缀与 start／done／end／FAILED 词汇。例：

  ```
  2026-10-18 12:06:21Z [    10.0s] INFO     [scan] 2 file(s): 2 to process, 0 with subtitles, 0 unstable, 0 failed
  2026-10-18 12:41:07Z [  2096.0s] WARNING  [asr] 3 warning/error line(s), see run-20261018T120611Z-asr.stderr.log
  2026-10-18 13:05:02Z [  3531.0s] ERROR    [translate] FAILED S1/ep01.mkv (work_id=0123456789ab): TranslateError
  ```

  文件级失败的 ERROR 行带 `(work_id=<id>)` 与异常类型，traceback 随后，控制台与文件相同；不带 traceback 的行（同类失败已记过、Strata 不可用、worker 崩溃或启动失败）改为 `logs.format_error` 单行摘要（`<类型>: <首行>`，总长截到 200 字符），例 `[publish] FAILED S1/ep02.mkv (work_id=0123456789ab): OSError: [Errno 28] No space left on device`。worker 写出的失败只记事件 `error_type`，无消息。
- **文件**：
  - `<work root>/run-<UTC戳>.log` 与控制台逐行相同，是权威副本。控制台流的编码取决于调用方，产品不改（batch-run-fixes 06.5）。
  - `<work root>/run-<戳>-<stage>.stderr.log` 在每次启动该阶段 worker 时先写一条分隔行（`--- [<stage>] launch pid=<pid> utc=<UTC> files=<n> ---`，重启时先换行），再追加其 stderr（壳按同一格式写的日志、第三方告警与裸 traceback）；worker 退出后只读本次新增部分，统计按本格式写出、级别为 WARNING／ERROR／CRITICAL 的行，并与非零退出码合并为运行日志中最多一条 `WARNING ... see <stderr>`（含退出码 1 无告警的裸崩溃，以及退出码 2 带告警的致命/启动失败）。非本格式的行（裸 traceback、tqdm 残行与 torch glog 行）不计入告警计数。
  - Strata session 的证据（接入身份、资源峰值、停止核实）另在 `<work root>/strata-sessions/`（[翻译子系统](../translation-subsystem.md)）。
- **内容**：
  1. 转写、cue 与窗口文字、译文、专名表条目与 `work_guess`、提示词、grammar、模型响应正文不进任何日志；失败窗口只记序号与 reason。
  2. 带 traceback 的失败行只记异常类型，traceback 随后：源码行加末行的 `<类型>: <异常消息>`（消息可能含文件路径，不含转写；校验消息是固定文本，如 `Duplicate JSON key` 不带键名）；异常消息不做通用截断。把异常首行嵌进一行日志的地方都截到 200 字符：
     - 不带 traceback 的 FAILED 行（`job._Context.fail`）
     - 翻译的批次尝试失败行与 Strata 重启行（`kototoki/translate/generate.py`）
     - `[strata] start failed` 与 `unavailable` 行（`kototoki/strata.py`）
     - names 的尝试失败行（`kototoki/names/table.py`）、`count_tokens` 不可用行与停 Strata 前告警（`kototoki/names/__init__.py`，`build.prompt_check` 仍记 300 字符）
     - 翻译子系统的"意外异常"行记为 WARNING（不带 traceback），唯一一条 ERROR 与 traceback 由编排的 FAILED 行带。
  3. 文件名用输入目录内相对路径，可附 `work_id` 以便与工作目录及 worker `stderr.log` 关联；只有锁与日志文件的指向、`[run] start` 行的配置文件与输入目录写绝对路径。
  4. 一事一行、每阶段三件套、结尾汇总：各阶段（extract、vad、asr、align、cues、names、translate）的 end 行统一为 `[x] end: N done, M failed, T.Ts`，发布行为 `[publish] done <相对路径>…`；`[scan]` 汇总行的 to process、with subtitles、unstable、failed 相加等于总数。秒数写 `12.3s`（无空格），MiB、GiB、tok 带空格。翻译批次行带输出 token 数、tok/s 与 cache（取不到的字段省略）。
  5. 告警是级别不是措辞：消息里不写 `WARNING`。
- **运行的首尾**（`job.run`）：
  - 进入日志上下文后第一行是 INFO `[run] start: config=<配置文件> input=<输入目录> engine=<engine> ffmpeg=<版本>`（`media.probe_ffmpeg_version` 取不到时为 `unavailable`，紧随其后记 WARNING 给出可执行路径与具体失败原因；不记模型 SHA 与 commit）。
  - 锁：工作根锁在日志挂接之前取得，破了残留锁时进入日志上下文后补记（若破锁删旧锁后创建新锁失败，由锁层记 WARNING 并在 `LockError` 中保留旧锁摘要）；GPU 锁取得时记 INFO `[lock] GPU acquired: <路径>`。任一把锁破除了残留锁（`KOTOTOKI_BREAK_STALE_LOCK=1`）时记 WARNING `[lock] replaced stale <work directory lock|GPU lock> (pid <n>[, worker_stage <s>][, server_pid <n>][, <error>])`，旧锁没有整数 pid 时写 `(no owner pid)`；证据另在新锁文件的 `replaced_stale_lock` 里，锁释放即删。
  - 任何逃出流程（含初始化、`record_input` 与收尾锁释放）的异常（Ctrl+C、`GpuLocked`、Strata 启停异常、未预期的 `OSError` 等 `BaseException`）在日志上下文内记 ERROR `[run] ABORTED: <异常类型>`，`KeyboardInterrupt` 不带 traceback，其余带；随后原样抛出，退出码不变。
  - `[summary]` 的两类行（总计行与逐个 `failed at <stage>` 行）在任何退出路径都写，中断时写已知的计数。
- **编排的计划与复用行**：extract 复用已有派生 WAV（`probe.json` 当前、跳过提取）时 done 行追加 ` (reused)`；计划之后一行 INFO `[plan] N file(s) resume at: vad 3, names 2, translate 7, publish 1`，按阶段链顺序只列非零项（`publish` 是无语音直接发布），没有文件时为 `none`。既有产物无法读取或解析时 `is_current` 记 WARNING，覆盖既有产物、字幕、解码日志或派生 WAV 时记 INFO（含对象与原因），产物缺失或仅因身份字段不符重算时不单记差异明细。
- **编排的翻译结果行**：每文件 `[translate] done <相对路径>[ (resumed)]: N cue(s), U untranslated, T.Ts`；`(resumed)` 表示全部批次早已完成、本次只读回译文未用模型；未翻译数大于 0 时为 WARNING。翻译子系统自己的行见[翻译子系统](../translation-subsystem.md)。
- **子进程噪声**：`job.child_env` 在离线变量之外合入 `job.QUIET_ENV`（`TQDM_DISABLE=1`、`HF_HUB_DISABLE_PROGRESS_BARS=1`、`TRANSFORMERS_VERBOSITY=warning`），让 worker stderr 只留日志行；这组变量归编排。
- **启动早期错误**：用法与配置错误、工作根锁冲突由 `__main__` 打印到 stderr（控制台流设 `errors="backslashreplace"`），以退出码区分，不写成日志行。GPU 锁冲突不属此类：它在 scan、extract 之后才可能发生，运行日志以 `[run] ABORTED: GpuLocked` 与 `[summary]` 收尾，`__main__` 另把原因打印到 stderr，退出码仍是 4。

## 代码与验证入口

- 代码：`kototoki/logs.py`（`LOG_FORMAT`、`LOG_DATEFMT`、`RunFormatter`、`format_error`、`path_label`、`failure_kind`、`FailureKind`）；挂接在 `kototoki/job.py`（`_run_logging`、`QUIET_ENV`、`child_env`）。
- 测试（core，`mise run test`）：
  - `tests/core/test_logs.py`：`format_error` 空消息/多行/总长截断、`path_label` 与 `failure_kind` 最内层帧提取。
  - `tests/core/test_job.py` 的 `InvariantTests` 断言转写、译文与专名文字不进运行日志与 worker stderr 日志。
  - `tests/core/test_job.py` 的 `RunLogTests` 覆盖编排统一日志出口：启动与锁释放未捕获异常落入 `run-*.log`、跨进程 `work_id`/`pid` 与 `stderr.log` 分隔行关联、未知进度事件 `id` 回退保留原 `id`、退出码 1/2 合并单条 `WARNING` 指针、`ffmpeg=unavailable` 诊断、媒体 `stderr` 告警、既有产物读错 `WARNING`、覆盖 `INFO` 审计，以及 Strata 不可用免重复 traceback。
- 仍未由离线日志测试覆盖：行格式与墙钟跳变下的相对秒、`KeyboardInterrupt` 无 traceback、同失败去重 traceback 细粒度断言、破残留锁与 `warnings.warn` 进日志、第三方 logger 前缀、handler 复原及各阶段数值字段与媒体告警。
- 测试（full，`mise run test-full`）：没有覆盖运行日志的用例（`tests/full/test_media_ffmpeg.py` 不再断言补入告警）。
