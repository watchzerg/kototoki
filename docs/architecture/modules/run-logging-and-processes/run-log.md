---
covers:
  - kototoki/logs.py
  - kototoki/job.py
---
# 运行日志与进程原语子页：运行日志

`运行日志与进程原语` 的子页：产品运行日志的目的地、挂接、行格式、级别与内容规则。

## 运行日志

- **框架**：标准库 `logging`，不用 `structlog`：读者只有人和 `grep`，一个 root handler 就能把第三方告警收进同一文件。
- **挂接**：`job.run` 取到工作根锁后，在 `_run_logging` 上下文内给 root logger 挂两个 INFO 级 `StreamHandler`：`<work root>/run-<UTC戳>.log`（UTF-8、`\n` 行尾）与控制台（默认 `sys.stdout`），共用一个 `kototoki.logs.RunFormatter`；`kototoki` logger 临时设为 INFO，并开 `logging.captureWarnings(True)`（第三方 `warnings.warn` 以 `[py]` 前缀进日志）。root 级别不动（默认 WARNING），所以第三方库只有 WARNING 及以上进日志。`run` 退出（含异常）时恢复级别与 `captureWarnings` 状态、摘下并关闭 handler。
- **发事件的一方**：其他产品模块只经 `logging.getLogger(__name__)` 发事件，不配置 handler、不开文件：
  - `kototoki.job`；`kototoki.translate.*`；
  - `kototoki.strata`（Strata 启停、等显存与内存、接入检查、停止核实，前缀 `[strata]`）；
  - `kototoki.names.table`（不合格的建表尝试，前缀 `[names]`）；`kototoki.names` 包顶层只发 `count_tokens` 不可用与停 Strata 前的两条 WARNING，建表结果行由编排写；
  - worker 壳在子进程里，由 `workers/gpu.main` 用同一 `RunFormatter` 写 stderr（[STT worker](../stt-workers.md)）。
- **级别**：
  - INFO：进度、计数与耗时——每阶段 start／逐文件 done／end、worker 的 stdout 进度事件、建表每部一行（条目数、丢弃数、prompt／completion token、秒数）、翻译每批一行、发布行的未翻译 cue 数、结尾汇总（含未翻译 cue 数：翻译完成即累加，与发布成败无关）。
  - WARNING：流程继续但应看一眼的事——大小仍在变化、发布期发现字幕已出现而不覆盖、媒体告警（`[extract] <相对路径>: <告警>`；媒体模块不发日志，由编排在主线程逐条记，续跑跳过 extract 时照样出现）、worker stderr 有告警、建表终态失败写空表（`[names] done <相对路径>: build failed (<原因>), empty table`）、等显存超过 30 s、Strata 重启／追问与拆分／未翻译。
  - ERROR：文件级与进程级失败，另含 Strata 不可用（被拒绝或启动额度用尽，整批一次）与停止未核实。DEBUG 不用。
- **行格式**（`kototoki/logs.py` 的 `LOG_FORMAT`／`LOG_DATEFMT`）：UTC 墙钟、自本次 `run` 起的相对秒（单调时钟，格式化时取：系统时钟被校正时不跳变；时间戳仍是墙钟，会随校正跳）、定宽级别、消息；非 `kototoki` logger 的消息前加 `[<logger 名首段>]`（如 `[transformers]`）。消息沿用 `[stage]` 前缀与 start／done／end／FAILED 词汇。例：

  ```
  2026-10-18 12:06:21Z [    10.0s] INFO     [scan] 2 file(s): 2 to process, 0 with subtitles, 0 unstable, 0 failed
  2026-10-18 12:41:07Z [  2096.0s] WARNING  [asr] 3 warning/error line(s), see run-20261018T120611Z-asr.stderr.log
  2026-10-18 13:05:02Z [  3531.0s] ERROR    [translate] FAILED S1/ep01.mkv: TranslateError
  ```

  文件级失败的 ERROR 行带异常类型，traceback（`exc_info`）紧随其后，控制台与文件相同；不带 traceback 的 FAILED 行（同类失败已记过、Strata 不可用之后、worker 崩溃或启动失败）改为 `<类型>: <异常消息首行>`（截到 200 字符），例 `[publish] FAILED S1/ep02.mkv: OSError: [WinError 17] …`。失败由 worker 报告（`failure.json` 已由 worker 写出）时类型取自事件的 `error_type`，没有 traceback 也没有消息。
- **文件**：
  - `<work root>/run-<UTC戳>.log` 与控制台逐行相同，是权威副本。控制台流的编码取决于调用方，产品不改（batch-run-fixes 06.5）。
  - `<work root>/run-<戳>-<stage>.stderr.log` 在每次启动该阶段 worker 时追加其 stderr（壳按同一格式写的日志、第三方告警与裸 traceback）；worker 退出后只读本次追加的部分，统计按本格式写出、级别为 WARNING／ERROR／CRITICAL 的行，非零时在运行日志记一行 WARNING（上例第二行），非本格式的行不计：裸 traceback、tqdm 残行与 torch 的 `W1109 20:31:52…` 这类 glog 行都不计。
  - Strata session 的证据（接入身份、资源峰值、停止核实）另在 `<work root>/strata-sessions/`（[翻译子系统](../translation-subsystem.md)）。
- **内容**：
  1. 转写、cue 与窗口文字、译文、专名表条目与 `work_guess`、提示词、grammar、模型响应正文不进任何日志；失败窗口只记序号与 reason。
  2. 带 traceback 的失败行只记异常类型，traceback 随后：源码行加末行的 `<类型>: <异常消息>`（消息可能含文件路径，不含转写；校验消息是固定文本，如 `Duplicate JSON key` 不带键名）；异常消息不做通用截断。把异常首行嵌进一行日志的地方都截到 200 字符：
     - 不带 traceback 的 FAILED 行（`job._Context.fail`）
     - 翻译的批次尝试失败行、Strata 重启行、放弃行与 `Strata refused` 行（`kototoki/translate/generate.py`）
     - `[strata] start failed` 与 `unavailable` 行（`kototoki/strata.py`）
     - names 的尝试失败行（`kototoki/names/table.py`）与 `count_tokens` 不可用行（`kototoki/names/__init__.py`，`build.prompt_check` 仍记 300 字符）。。
     - 翻译子系统的"意外异常"行不带 traceback，由编排的 FAILED 行带。
  3. 文件名用输入目录内相对路径，只有锁与日志文件的指向、`[run] start` 行的配置文件与输入目录写绝对路径。
  4. 一事一行、每阶段三件套、结尾汇总：各阶段（extract、vad、asr、align、cues、names、translate）的 end 行统一为 `[x] end: N done, M failed, T.Ts`，发布行为 `[publish] done <相对路径>…`；`[scan]` 汇总行的 to process、with subtitles、unstable、failed 相加等于总数。秒数写 `12.3s`（无空格），MiB、GiB、tok 带空格。翻译批次行带输出 token 数、tok/s 与 cache（取不到的字段省略）。
  5. 告警是级别不是措辞：消息里不写 `WARNING`。
- **运行的首尾**（`job.run`）：
  - 进入日志上下文后第一行是 INFO `[run] start: config=<配置文件> input=<输入目录> engine=<engine> ffmpeg=<版本>`（ffmpeg 取不到为 `unavailable`；不记模型 SHA 与 commit）。
  - 锁：工作根锁在日志挂接之前取得，破了残留锁时随后补记；GPU 锁取得时记 INFO `[lock] GPU acquired: <路径>`。任一把锁破除了残留锁（`KOTOTOKI_BREAK_STALE_LOCK=1`）时记 WARNING `[lock] replaced stale <work directory lock|GPU lock> (pid <n>[, worker_stage <s>][, server_pid <n>])`，旧锁没有整数 pid 时写 `(no owner pid)`；证据另在新锁文件的 `replaced_stale_lock` 里，锁释放即删。
  - 任何逃出流程的异常（Ctrl+C、`GpuLocked`、Strata 启停异常、未预期的 `OSError` 等 `BaseException`）在日志上下文内记 ERROR `[run] ABORTED: <异常类型>`，`KeyboardInterrupt` 不带 traceback，其余带；随后原样抛出，退出码不变。
  - `[summary]` 的两类行（总计行与逐个 `failed at <stage>` 行）在任何退出路径都写，中断时写已知的计数。
- **编排的计划与复用行**：extract 复用已有派生 WAV（`probe.json` 当前、跳过提取）时 done 行追加 ` (reused)`；计划之后一行 INFO `[plan] N file(s) resume at: vad 3, names 2, translate 7, publish 1`，按阶段链顺序只列非零项（`publish` 是无语音直接发布），没有文件时为 `none`。为什么重跑（产物缺失、不可读或哪个身份字段不符）不记。
- **编排的翻译结果行**：每文件 `[translate] done <相对路径>[ (resumed)]: N cue(s), U untranslated, T.Ts`；`(resumed)` 表示全部批次早已完成、本次只读回译文未用模型；未翻译数大于 0 时为 WARNING。翻译子系统自己的行见[翻译子系统](../translation-subsystem.md)。
- **子进程噪声**：`job.child_env` 在离线变量之外合入 `job.QUIET_ENV`（`TQDM_DISABLE=1`、`HF_HUB_DISABLE_PROGRESS_BARS=1`、`TRANSFORMERS_VERBOSITY=warning`），让 worker stderr 只留日志行；这组变量归编排。
- **启动早期错误**：用法与配置错误、工作根锁冲突由 `__main__` 打印到 stderr（控制台流设 `errors="backslashreplace"`），以退出码区分，不写成日志行。GPU 锁冲突不属此类：它在 scan、extract 之后才可能发生，运行日志以 `[run] ABORTED: GpuLocked` 与 `[summary]` 收尾，`__main__` 另把原因打印到 stderr，退出码仍是 4。

## 代码与验证入口

- 代码：`kototoki/logs.py`（`LOG_FORMAT`、`LOG_DATEFMT`、`RunFormatter`）；挂接在 `kototoki/job.py`（`_run_logging`、`QUIET_ENV`、`child_env`）。
- 测试（core，`mise run test`）：`tests/core/test_job.py` 的 `InvariantTests` 断言转写、译文与专名文字不进运行日志与 worker stderr 日志。
- 测试精简（2026-11-22）后不再有测试覆盖运行日志本身：
  - 日志格式的单元测试与 `RunLogTests` 全部删除：行格式与墙钟跳变下的相对秒、文件与控制台逐行相同、`[run]`／`[lock]`／`[plan]`／`[summary]` 各行、ABORTED 收尾（含 `KeyboardInterrupt` 无 traceback）、extract 与 cues 三件套及计数。
  - 级别与 traceback 规则：告警与失败的级别、worker 报告的失败一行 ERROR、同一缓存异常或同类失败只有一份 traceback、Strata 不可用后的失败不带 traceback、非 0／1 退出码的 stderr 指针行、破残留锁与 `warnings.warn` 进日志、第三方 logger 前缀、worker stderr 告警计数、handler 复原。
  - 各阶段 done 行的字段：worker `done` 的数值字段、翻译耗时与 `(resumed)`、names 的重试次数、媒体与补偿告警（含续跑跳过 extract）。
- 测试（full，`mise run test-full`）：没有覆盖运行日志的用例（`tests/full/test_media_ffmpeg.py` 不再断言补入告警）。
