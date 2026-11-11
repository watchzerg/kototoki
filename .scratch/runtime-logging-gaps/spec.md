# 产品运行日志补缺

Status: in-progress
建票：2026-11-11。范围：产品包 `kototoki/` 的运行日志，外加 `scripts/smoke/run_all.py` 一处防护。
前序：[产品运行日志规划](../runtime-logging/spec.md)（已结题，冻结）。现行规则正文在[运行日志、进程原语与 worker 子进程](../../docs/architecture/modules/run-logging-and-processes.md)。

## 1. 依据

2026-11-11 对产品日志做了一次只读审计（8 路：编排、STT worker、Strata／专名、翻译、基础层静默路径、真实运行日志、测试与文档一致性、脚本与 demo）。结论：

- 格式、级别、内容规则执行良好，没有系统性冗余；问题集中在**缺失**。
- 两类缺失最重：异常退出时运行日志没有收尾；worker 的降级信息只留在 stderr 侧文件。
- 真实日志只有 2 份单文件成功运行（`.local/q3-product-fullfilm/work/input-7c924c80249b/` 的 2026-11-09 运行、`.local/logcheck-atkd089/driver.out` 的 2026-10-18 运行）。失败、中断、续跑、多文件路径的结论都来自读码。

下文各票的"现状"是审计时点的读码结果，动手前对照当前代码核实。

## 2. 目标与不做的事

目标：操作者在无人值守的多小时批次之后，只读 `run-<戳>.log` 就能回答：这次用了什么配置、每个文件走到哪、为什么失败或降级、运行是怎么结束的。

不做：

- 不引入日志框架、轮转、指标或新配置键；不新增依赖。
- 不改产物契约（`failure.json`、`run.json`、各阶段 JSON 的字段）与 worker `--jobs` 协议；worker stdout 事件只读取已有字段。
- 翻译每批一行保持不变（约 150 行／片，兼作心跳），不抽样。
- GPU 阶段不加周期心跳行。
- 不改 `experiments/` 下任何文件（含 `quality_v5/vad_sweep.py` 把 cue 文本打到控制台的问题：属冻结证据）。
- 不处理两个与日志无关的健壮性问题，只在 §6 登记：非 JSON 回复导致整片失败、`extensions` 不带点时静默扫到 0 个文件。
- 不运行任何 GPU 重任务（`python -m kototoki`、`just smoke` 等）；真实路径核对列为未验证项，由用户另行批准。

## 3. 约定

- 级别、前缀、词汇沿用现行规则：INFO 进度与计数，WARNING 流程继续但应看一眼，ERROR 文件级与进程级失败；消息以 `[stage]` 开头，用 start／done／end／FAILED。
- 内容规则不变：转写、cue、译文、专名条目、提示词、模型响应不进任何日志；新增的行只放类型名、计数、耗时、相对路径。
- 秒数统一写 `12.3s`（无空格）；MiB、GiB、tok 保持带空格。
- 每张票：先改模块页（接口形状或日志行有变化时），再改代码与测试；`just test` 通过；按[随交付同步](../../docs/agents/documentation.md#随交付同步)更新受影响文档；一票一提交。
- 测试对文档写明的日志行可以做整行断言，其余只断言关键片段。

## 4. 票据

进度记在本表；票据不另建文件，细节在下面各小节。

| # | 标题 | 依赖 | 状态 |
| --- | --- | --- | --- |
| 01 | 运行头、异常退出收尾、破锁告警 | — | resolved |
| 02 | worker 事件字段进主日志，失败行去重，崩溃指针 | — | ready-for-agent |
| 03 | 过滤 vad 的已知无害告警 | 02 | ready-for-agent |
| 04 | cues 阶段三件套 | — | ready-for-agent |
| 05 | 翻译：固定校验消息、行内文件归属、降级批次字段 | — | ready-for-agent |
| 06 | Strata 与专名：故障行与启停行 | — | ready-for-agent |
| 07 | 续跑计数行 | 01 | ready-for-agent |
| 08 | 格式统一与文档对齐 | 01–07 | ready-for-agent |
| 09 | smoke runner 的编码与子进程回收 | — | ready-for-agent |
| 10 | 补测试缺口并结题 | 01–09 | ready-for-agent |

### 01 运行头、异常退出收尾、破锁告警

现状（`kototoki/job.py` 的 `run`、`_run`、`_run_logging`、`_Context.ensure_gpu_lock`）：

- 任何逃出 `_run` 的异常（Ctrl+C、`GpuLocked`、Strata 启停异常、未预期的 `OSError`）都在 handler 摘掉之后才由解释器打印，运行日志在最后一条进度行处中断，没有原因，也没有 `[summary]`。
- `GpuLocked` 在 scan 和整个 extract 之后才可能抛出，模块页却把它归为"启动早期错误"。
- 日志第一行是 `[scan]`，没有配置文件、输入目录、engine。
- 破残留锁的证据只写在新锁文件的 `replaced_stale_lock` 里，锁释放即删除；工作根锁在日志挂接之前取得。
- 主进程没有 `logging.captureWarnings(True)`，第三方 `warnings.warn` 不进运行日志（worker 里有）。

改动：

1. 进入日志上下文后记一行 INFO：`[run] start: config=<路径> input=<路径> engine=<值>`（绝对路径；模块页的路径规则相应补一句）。不记模型 SHA 与 commit。
2. 工作根锁或 GPU 锁的 `stale` 非空时各记一行 WARNING：`[lock] replaced stale <kind> (pid <n>[, worker_stage <s>][, server_pid <n>])`。`GPU lock acquired` 行改为 `[lock] GPU acquired: <路径>`。
3. 在日志上下文内捕获 `BaseException`：记 ERROR `[run] ABORTED: <异常类型>`（`KeyboardInterrupt` 不带 traceback，其余带），再原样抛出。
4. `[summary]` 的两类行改为任何退出路径都写（中断时写已知的计数）。
5. `_run_logging` 内开 `captureWarnings(True)`，退出时还原。
6. 模块页：把 GPU 锁冲突从"启动早期错误"里拿出来，写明它以 ABORTED 行收尾、退出码不变。

验收：`RunLogTests` 新增——`_run` 中途抛异常时文件里有 ABORTED 行与 summary 行；`KeyboardInterrupt` 无 traceback；`GpuLocked` 在 extract 之后抛出时日志有收尾；破锁时有 WARNING；首行是 `[run] start`；退出后 `captureWarnings` 已还原。

### 02 worker 事件字段进主日志，失败行去重，崩溃指针

现状（`job._read_events`、`job._launch`、`job.run_gpu_stage`、`_Context.fail`，`workers/protocol.py` 的 `run_jobs`、`run_worker`）：

- `_read_events` 只写 `[stage] <event> <相对路径>`，事件里的 `windows`、`failed_windows`、`guarded_windows`、`failed_alignment_windows`、`text_only_units`、cross 的各计数以及 `error_type` 全被丢弃。2026-11-09 的真实运行里"1 个窗口对齐失败、417 个 text-only 单元"只在 stderr 文件里。
- 同一失败先以 INFO `[asr] failed <文件>` 出现，再以 ERROR `[asr] FAILED <文件>` 出现，后者不带类型；`startup_failed` 以空标签的 INFO 出现。
- "see …stderr.log" 的 WARNING 只在 stderr 里有本格式的告警行时出现；裸 traceback、原生崩溃都不计数，最需要指针时反而没有。
- worker 启动失败或模型缺失时，N 个文件各打一份相同的 traceback。

改动：

1. `done` 事件：把事件里除 `event`、`id` 之外的数值字段按 `key=value` 追加，例 `[align] done S1/ep01.mkv: windows=195 failed_alignment_windows=1 text_only_units=417`。字段名取自事件本身，不建映射表。
2. `failed`／`fatal`／`startup_failed` 事件不再由 `_read_events` 记行；`run_gpu_stage` 把事件的 `error_type` 交给 `ctx.fail`，使 worker 报告的失败行成为 `[asr] FAILED <文件>: <类型>`（无 traceback，`failure.json` 仍由 worker 写）。
3. `_launch`：退出码不是 0 或 1 时固定记 WARNING `[stage] worker exited with code <n>, see <stderr 文件名>`，与告警计数行互不替代。
4. 启动失败：先记一行 ERROR `[stage] worker startup failed: <类型>`，随后逐文件的 FAILED 行不带 `exc_info`。`PlanError` 的同一缓存异常只在第一次带 traceback。
5. `protocol.run_worker` 的 `startup failed` 行补 `[stage]` 前缀（读 jobs 失败时没有 stage，用 `[worker]`）。
6. 模块页（运行日志、STT worker、STT ASR）改写对应行，并注明 stderr 侧文件里的相对秒自 worker 进程启动起算。

验收：`RunLogTests`／`IsolationTests` 新增或修改——done 行带计数；worker 报告的失败只有一行 ERROR、带类型、无 traceback；非 0/1 退出码有指针行；启动失败 N 个文件只有一份 traceback。

### 03 过滤 vad 的已知无害告警

现状：`workers/gpu.main` 开了 `captureWarnings(True)`，pyannote 的 `ReproducibilityWarning`（TF32 被关闭）每次运行都成为一条 WARNING，主日志于是每次都有 `[vad] 1 warning/error line(s), see …`，与真正的对齐失败指针无法区分。

改动：在 `workers/gpu.main` 用 `warnings.filterwarnings("ignore", …)` 只过滤这一条，按类别与消息前缀匹配。告警的确切类别与文字从 `.local/q3-product-fullfilm/work/input-7c924c80249b/run-20261109T123048Z-vad.stderr.log` 读取（只读，不含转写）；该文件不存在时从已安装的 pyannote 源码里找。不过滤其他任何告警。

验收：单元测试——同类别同消息的 `warnings.warn` 不产生日志行，其他 `UserWarning` 仍产生。未验证项：真实 vad 运行后计数行消失。

### 04 cues 阶段三件套

现状（`job._run` 的 cues 循环、`job.build_ja_cues`）：成功时没有任何日志行，违反"每阶段三件套"；`time_sources`、`backfilled_units`、`fallback_windows`、`unrendered_chars` 只在 `ja-cues.json`。有语音但渲染出 0 条 cue 的文件会一路 INFO 发布成近乎空的字幕。

改动：

1. `[cues] start: N file(s)`；每文件 `[cues] done <相对路径>: N cue(s), <回填与回退计数>`；`[cues] end: N done, M failed, T.Ts`。计数字段取 `build_cues` 已返回的 payload，只报数，不设阈值。
2. cue 数为 0 时该文件的 done 行用 WARNING。
3. 批次编排与日文 cue 模块页补这三行。

验收：`RunLogTests` 新增——三件套存在；done 行带计数；0 cue 时为 WARNING。

### 05 翻译：固定校验消息、行内文件归属、降级批次字段

现状（`kototoki/translate/recipes.py` 的 `strict_json`，`translate/generate.py` 的 `_batch_line`、session start 行，`job.translate_batch` 的 done 行）：

- `strict_json` 抛 `ValueError(f"Duplicate JSON key: {key}")`，key 来自模型回复，经批次尝试失败行进日志——审计中唯一确认的内容违规路径；200 字符截断挡不住。
- 批次行只有 `srt-<sha12>-bNNNN`，session 编号每个文件从 1 重新开始，多集批次里无法把告警归到某一集；续跑与全新翻译的 done 行看不出区别。
- 降级批次的 `tok`、`tok/s`、`cache` 取自失败的原始请求。
- 意外异常行不带批次号；`done` 行没有耗时。

改动：

1. `strict_json` 的消息改为固定的 `Duplicate JSON key`。动手前搜索对该字符串或 `recipes.py` 的 sha256／内容断言，确认配方 hash 不覆盖它；若覆盖，停下来报告，不改。
2. session start 行加相对路径：`[translate] session N start <相对路径> (<label>): P of T batch(es) pending`。全部批次已完成、不需要模型时，由编排在 done 行标注 `(resumed)`。
3. `_batch_line`：降级批次省略 `tok`、`tok/s`、`cache`，只留 cue 数与 `degraded (…)`。
4. 意外异常行在批次已知时带批次号。
5. `[translate] done` 行追加本文件耗时；回退数大于 0 时用 WARNING。
6. 翻译子系统模块页同步。

验收：`test_translate.py`／`test_translate_degrade.py`——重复 key 的失败行不含 key 文本；session 行含相对路径；降级批次行无 tok 字段；done 行带耗时、回退时为 WARNING。

### 06 Strata 与专名：故障行与启停行

现状（`kototoki/strata.py` 的 `Session.ensure_started`、服务的 `__enter__`／`__exit__`、`_wait_ready`，`kototoki/names/__init__.py` 的 `build_document`）：

- Strata 拒绝或启动额度用尽时 `strata.py` 不记任何行；专名路径上原因只在每部片子重复的 traceback 里（翻译路径有 `Strata refused` 的 ERROR）。
- 专名遇 HTTP 或传输错误时静默 `session.stop()`，没有 WARNING。
- 启动最多有四段静默等待，真实运行里 `[names] start` 到 `ready` 之间 78 秒空白；停止最长可静默约 6 分钟。
- 就绪超时、启动失败的异常消息不带 server log 路径；`stop not confirmed` 行不指向 `strata-final.json`。
- 专名成功行看不出是第几次尝试成功的。

改动：

1. `ensure_started`：置 `unavailable` 时记一次 ERROR `[strata] unavailable for the rest of this batch: <首行，200 字符内>`；每次启动失败记 WARNING `[strata] start failed n/3: <首行>`。之后各文件的 FAILED 行照旧，但同一原因只在第一次带 traceback。
2. 启动前记 INFO `[strata] launching (free VRAM X MiB, available RAM Y GiB)`；停止开始时记 INFO `[strata] stopping`。
3. 启动失败与就绪超时的异常消息带 server log 绝对路径；`stop not confirmed` 行追加 `see <strata-final.json 路径>`。
4. 专名停 Strata 前记 WARNING `[names] stopping Strata after <HTTP 状态与类别 | 传输异常类型>`。
5. 专名 done 行在尝试次数大于 1 时追加 `, attempt n/5`。
6. `wait_for_free_vram` 的日志调用改为纯 %-参数（去掉 f-string 与参数混用），`stage` 的默认值改为 `"strata"`。
7. Strata session、专名一致性模块页同步。

验收：`test_strata.py`／`test_names_session.py`／`test_job.py`——拒绝时有一行 `[strata]` ERROR；启动失败有计数 WARNING；launching、stopping 行存在；专名停 Strata 有 WARNING；重试成功的 done 行带 attempt。

### 07 续跑计数行

现状（`job._run` 的计划循环）：`plan.next_stage` 之后不记任何行，看不出每个文件从哪个阶段续跑；空批次的阶段静默跳过；`[extract] done` 行不区分重新提取与复用。

改动：

1. 计划循环之后记一行 INFO：`[plan] N file(s) resume at: vad 3, names 2, translate 7, publish 1`（只列非零项）。
2. 复用已有派生 WAV 时 extract 的 done 行追加 `(reused)`。

不在本票：记录"为什么重跑"（产物缺失、不可读，还是哪个身份字段不符）。它需要改 `artifacts.is_current` 的返回形状，见 §5。

验收：`RunLogTests` 新增——续跑运行有 `[plan]` 行且计数正确；复用时有 `(reused)`。

### 08 格式统一与文档对齐

在 01–07 之后做，只收尾剩余的不一致：

1. 秒数按 §3 统一（`strata.py`、`translate/generate.py` 的 session end 行、专名 done 行）。
2. 各阶段 end 行统一为 `[x] end: N done, M failed, T.Ts`（extract、names、translate 现在字段不一）；`[publish]` 行加 `done`。
3. `[scan]` 汇总行的计数补上 scan 阶段失败数，使各项相加等于总数。
4. `kototoki.names` 包顶层实际发了一条 `count_tokens` WARNING，截断是 300：把截断改为 200，并在运行日志模块页与模块边界里把这条行登记为该包的唯一日志。
5. 翻译尝试失败行的 `exchange <路径>` 改为相对工作根的路径。
6. 运行日志模块页：截断清单补全；"traceback 只含源码行"改为如实描述（末行含异常消息）；写明 torch 自身的 `W…` 行不按本格式、不计数。
7. README 的日志说明补 `run-<戳>-<stage>.stderr.log` 与指针行的读法。

验收：受影响测试的断言更新；`just test` 通过；文档链接检查通过。

### 09 smoke runner 的编码与子进程回收

现状（`scripts/smoke/run_all.py` 的 `main`、`run_one`）：父进程 `print` 用控制台编码，输出重定向到 cp1252 时子进程的进度条或 CJK 行会让父进程抛 `UnicodeEncodeError`；随后 `finally` 删除 `.local/gpu.lock`，而子进程没有被回收，仍占着 GPU。Ctrl+C 同理。没有逐步的开始与结束行，汇总只在全部跑完之后打印。

改动：

1. `main` 开头 `sys.stdout.reconfigure(errors="backslashreplace")`（同 `scripts/check_docs.py` 的做法）。
2. `run_one` 用 `try/finally`：退出时子进程仍在运行则 `kill` 并 `wait`，之后才轮到删锁。
3. 每步打印开始行（序号、名称、UTC 时间）与结束行（PASS／FAIL、耗时、该步 `.log` 的路径）；汇总放进 `finally`，中途异常也打印已完成的步骤。
4. `docs/development/` 里如有"重定向 smoke 输出须加 `PYTHONUTF8=1`"的说法，改为如实描述。

验收：不运行真实 smoke。用假的步骤脚本做单元测试——stdout 为 cp1252 且子进程输出 CJK 时不崩溃；父进程异常时子进程被回收。未验证项：真实 `just smoke` 重定向运行。

### 10 补测试缺口并结题

1. 截断：400 字符的单行异常消息经翻译尝试失败行与专名尝试失败行输出后，消息部分不超过 200 字符。
2. 文件名：`RunLogTests` 用形如 `日本語 100%.mkv` 的文件走一次失败路径，断言 ERROR 行、UTF-8 文件内容与无格式化异常。
3. 内容规则：用已知的日文与中文字符串走完整条假流水线，断言它们不出现在运行日志与各阶段 stderr 日志里。
4. 结题：核对 01–09 的规则都已写入当前正文；模块页的"变更与决策来源"链接本目录；本 spec 填 §7 结果并把状态改为 `resolved`。

## 5. 待用户裁定

- **重跑原因**：是否让 `artifacts.is_current` 返回原因（`missing`／`unreadable`／不符的身份键名），并在 `[plan]` 行里汇总。收益是改配方或模型后能直接看出为什么重跑数小时；代价是改一个基础层函数的返回形状及其全部调用方。本轮不做，执行中不要顺手做。

## 6. 另行登记，不在本轮

- 非 JSON 或缺字段的 HTTP 200 回复不在重试范围内，会让整片以"意外异常"失败（翻译与专名都有）。
- `extensions` 配置项不带前导点时永远匹配不到文件，运行以"0 file(s)"和退出码 0 结束。
- `contain_children()` 失败与未捕获异常的退出码都是 1，与"部分文件失败"无法区分。
- `stable_files` 把已消失或不可读的文件报成"size still changing"。
- 媒体与内嵌字幕的若干静默决定（所选音轨、清洗丢弃数、没有合格字幕轨的原因、ffmpeg 退出码 0 时的解码错误）。

## 7. 结果

（结题时填写：每票的提交、自动检查结果、未验证项。）
