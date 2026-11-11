# 产品运行日志规划

Status: done
建票：2026-10-18。范围：产品包 `kototoki/`（`python -m kototoki` 与 `kototoki.workers.*`）。
`experiments/*`（冻结、print 风格）、`kototoki_eval/`、`scripts/`（CLI 的 stdout 即其输出）与 `scripts/smoke/`（已自带 tee 到 `.local/smoke/<name>.log`）不在本规划内。

## 1. 现状（2026-10-18 对照仓库核实）

全仓库没有任何 `logging`／`structlog`／`loguru` 的使用，产品日志全部是手写的：

| 位置 | 现在怎么输出 | 问题 |
| --- | --- | --- |
| 编排器 `kototoki/job.py::RunLog` | 每条同时写 stdout 与 `<output_dir>/.work/run-<UTC戳>.log`；格式 `[  elapsed s] [stage] message`；只有阶段起止、逐文件状态、计数、耗时 | 只有相对秒，没有墙钟时间；没有级别，`WARNING`／`FAILED` 是写在文字里的；只有编排能写（`ctx.log` 靠参数传递），其他模块无法发出进度 |
| 入口 `kototoki/__main__.py` | 配置错误、锁冲突 `print(..., file=sys.stderr)` | 可接受：此时输出目录可能尚不可用 |
| GPU worker（vad／asr／align 子进程） | stdout 是协议：每文件一行 JSON 进度；stderr 整体追加到 `.work/run-<戳>-<stage>.stderr.log` | stderr 里主要是 transformers 的 `Loading weights` tqdm 进度条（2 KB 乱码级重复）和 pyannote 告警；worker 自身没有任何日志（模型加载耗时、每窗失败原因只在产物里） |
| 翻译子系统 `kototoki/translate/` | 完全静默；只有编排在整部影片翻完后写一行 `done … N cue(s), M fallback` | 一部影片翻译 200–2900 s（票据 16 实测）期间控制台无任何输出；server 启动／等显存／重启／降级都只记在 `run.json`，事后才能发现（票据 16 的"第 96 批起 4 tok/s"即如此） |
| llama-server | `--log-file server.log` 且 stderr 另存 `stderr.log`，位于 `.work/translate-sessions/<戳>-<pid>/session-NN/` | 两个文件逐字节相同（各 6 MB／session）；`stdout.log` 恒为空 |
| 失败记录 | `failure.json`：阶段、异常类型、消息、已完成产物 | 没有 traceback；worker 内异常的 traceback 被协议吞掉，编排内未捕获异常的 traceback 只出现在 stderr，不进运行日志 |
| ffmpeg | `.work/<id>/extract.log`（verbose，供补偿统计解析） | 这是产物不是日志，保持不动 |

现有规则：[模块边界](../../docs/architecture/module-boundaries.md#产品包的责任边界)"**日志**只有编排写运行日志，内容限进度与计数；推理模块只返回数据，不打印，转写与译文不进日志"；[批次编排模块页](../../docs/architecture/modules/batch-orchestration.md)有一句日志说明；[技术选型](../../docs/development/technology-stack.md)把 `structlog` 列为"需要时优先"但"不要仅因清单存在而安装"；`*.log` 已全局 gitignore；测试 `tests/core/test_job.py`、`test_translate_degrade.py` 对控制台文本做子串断言（`[summary] 2 video(s): 2 published`、`1 fallback cue(s)`）。

## 2. 目标与非目标

目标：

1. 运行中能看到在干什么：翻译按批次有进度（含生成速度），server 启动、等显存、重启、降级、回退在发生时就出现在控制台与文件里。
2. 事后能定位问题：每行带墙钟时间与级别；文件级失败在日志里有异常类型，traceback 落到文件；第三方库告警集中、可读，不与进度条混在一起。
3. 不变量不破：音频、转写、译文、提示词与模型响应正文永远不进任何日志。
4. 零新依赖、零新配置键、不改产物契约与 worker 协议。

非目标：日志轮转与清理（批处理一次一文件、"所有产物保留"）；结构化 JSON 日志与采集（没有第二个消费者）；把 `experiments/*` 改成 logging；改 `failure.json`、`run.json` 的字段；统一 llama-server 日志格式。

## 3. 设计

### 3.1 框架：标准库 `logging`，不引入 structlog

- 唯一的日志读者是人和 `grep`；进程形态固定（编排进程 + 三类 worker 子进程 + llama-server），不需要结构化字段与采集器。
- transformers、pyannote、torchaudio、faster-whisper 的告警全部走标准库 `logging`；用标准库一个 root handler 就能把它们收进我们的文件，structlog 反而要多一层桥接。
- 不新增依赖，`uv.lock` 不动。`structlog` 保留在技术选型的"需要时"清单，不在此时触发。

### 3.2 发送方与接收方（模块边界的调整）

- **编排器拥有全部日志目的地**：只有 `job.run` 配置 handler、决定文件路径与控制台；其他模块不配置 handler、不开文件。
- **任何产品模块可以通过 `logging.getLogger("kototoki.<module>")` 发事件**，取代现在靠 `ctx.log` 参数传递；首批使用者：`kototoki.job`、`kototoki.translate.*`、`kototoki.media`（时长告警）、worker 壳 `kototoki.workers.*`。
- **推理模块（`vad`、`asr_*`、`align`）维持不打印**：它们只返回数据；需要记的东西（加载耗时、窗口数、失败窗口原因）由 worker 壳在拿到返回值后记录。
- 模块边界那句改为："日志目的地与格式只归编排；产品模块经各自 logger 发进度与告警；推理模块不发日志；转写、译文、提示与模型响应不进日志。"——这是一处规则改动，需用户裁定（见 §5）。

### 3.3 级别

| 级别 | 用途 | 例 |
| --- | --- | --- |
| INFO | 进度、计数、耗时；每阶段 start／逐文件 done／end 三件套；翻译每批次一行；汇总 | `[translate] batch 96/149: 8 cue(s), 412 tok, 4.1 tok/s, cache 7812` |
| WARNING | 用户应当看一眼但流程继续 | 文件被用户改动而跳过、大小仍在变化、解码长于视频、server 重启、降级到子批次、回退保留日文、等显存超过 30 s、失败窗口（只记 reason） |
| ERROR | 文件级与进程级失败 | `[asr] FAILED <rel>: WorkerCrashed`、`[translate] FAILED <rel>: TranslateError` |
| DEBUG | 暂不使用；预留给逐请求细节，出现需求再开 | — |

控制台与文件内容相同（都是 INFO 及以上），延续现在的 tee 语义，不做"文件更详细"的分叉——翻译每批一行在整片上约 150 行，批处理 CLI 可以接受；若日后嫌吵再把批次行降到 DEBUG 并让文件收 DEBUG，这是一个常量的改动。

### 3.4 格式

```
2026-10-18 12:06:21Z [  10.0s] INFO     [scan] 2 video(s): 2 to check, 0 blocked, 0 unstable
2026-10-18 13:03:14Z [3412.8s] WARNING  [translate] server restart 1/2 for <rel>: server_start (out of memory)
2026-10-18 13:05:02Z [3520.1s] ERROR    [translate] FAILED <rel>: TranslateError
```

- 墙钟取 UTC（与 `run-<UTC戳>.log`、`*_at_utc` 字段一致）＋ 自启动相对秒（保留，便于看阶段耗时）＋ 固定宽度级别。
- 消息沿用 `[stage]` 前缀、`start／done／end／FAILED` 词汇，现有测试的子串断言不受影响。
- 第三方库的记录加 logger 名（`[transformers]`），我们自己的不加，减少噪声。
- 文件 UTF-8、`\n`；控制台维持 `errors="backslashreplace"`；子进程维持 `PYTHONUTF8=1`。

### 3.5 位置（不新增目录）

| 文件 | 内容 | 变化 |
| --- | --- | --- |
| `<output_dir>/.work/run-<UTC戳>.log` | 编排进程全部 INFO+（含翻译、媒体） | 不变的路径，内容按 §3.3／3.4 |
| `<output_dir>/.work/run-<戳>-<stage>.stderr.log` | 该阶段 worker 子进程的 logging 输出与第三方告警 | 去掉进度条；worker 壳用同样格式写 stderr |
| `.work/translate-sessions/<戳>-<pid>/session-NN/server.log` | llama-server 自身日志 | 不变；`stderr.log` 的重复先不处理（见 §5） |
| `.work/<id>/extract.log`、`failure.json`、`run.json` | 产物 | 不变 |
| 控制台 | 与 `run-<戳>.log` 相同 | 不变 |

启动早期（配置错误、输出目录锁冲突）仍 `print` 到 stderr：此时日志文件无处可写，退出码已足够。

### 3.6 内容原则

1. **不进日志**：cue 与窗口文字、译文、提示词、grammar、模型响应正文、`failed_windows[].text`、音频路径以外的任何内容派生物。失败窗口只记 `chunk_index` 与 `reason`。
2. **异常只记类型与首行消息并截断**（200 字符）；traceback 以 `exc_info` 写进同一文件（Python traceback 只含源码行，不含变量值）。要审计的一处：`translate.client`／`generate.run_step` 抛出的 `StepFailed` 消息不得包含响应正文——这条今天就该成立，本任务顺带核对。
3. **文件名用输入目录内相对路径**（现状），只有锁与日志目录指向时写绝对路径。
4. **一事一行、每阶段三件套、结尾一行汇总**（现状保持）。
5. **耗时随行**：`end` 行带墙钟；翻译批次行带 token 数与 tok/s，让票据 16 那种慢化在发生时就可见。
6. **告警是级别不是措辞**：去掉消息里的 `WARNING` 字样，改用级别。

### 3.7 子进程与第三方噪声

- 编排在子进程环境加 `TQDM_DISABLE=1`、`HF_HUB_DISABLE_PROGRESS_BARS=1`、`TRANSFORMERS_VERBOSITY=warning`（子进程环境归编排，与模块边界一致）。
- worker 壳 `workers/gpu.main` 做 `logging.basicConfig(stream=sys.stderr, ...)`＋`warnings.captureWarnings(True)`，级别 INFO；记录：模型核对与加载耗时、每文件窗口数／失败窗口数、`FatalWorkerError` 与单文件异常（含 traceback）。stdout 协议行不变。
- 编排在 worker 退出后数一下该 stderr 文件里的 `WARNING`／`ERROR` 行，非零时写一行 `[asr] 3 warning(s), see run-…-asr.stderr.log`，让用户不用翻文件也知道有事。
- llama-server 不受影响：它不是 Python。

## 4. 票据拆分（批准后建 `issues/`）

| NN | 内容 | 文件所有权 | 验证 |
| --- | --- | --- | --- |
| 01 编排器接入 logging | `RunLog` 改为 `logging` 配置（文件＋控制台 handler、格式、UTC）；`ctx.log` 调用改为 logger；`WARNING`／`FAILED` 改级别；`ctx.fail` 带 `exc_info`；worker 退出后汇总 stderr 告警数 | `kototoki/job.py`、`tests/core/test_job.py` | `just test`；伪 worker 用例断言级别与文件内容；文件与控制台逐行相同 |
| 02 翻译子系统进度 | `Session`／`generate`／`degrade` 经 `kototoki.translate` logger 发：server 启动（等显存秒数、冷加载秒数）、每批次一行、重启、降级、回退、`StepFailed` 消息审计 | `kototoki/translate/{generate,degrade,server}.py`、`tests/core/test_translate*.py` | 伪客户端用例用 `assertLogs` 断言事件与"不含 cue 文字" |
| 03 worker 壳日志与噪声 | `gpu.main` 的 basicConfig＋`captureWarnings`；壳记加载耗时与计数；编排子进程环境加三个变量 | `kototoki/workers/gpu.py`、`kototoki/workers/{vad,asr,align}.py`、`kototoki/job.py::child_env`、`tests/core/test_stt_workers.py` | 离线用例；真实 stderr 文件无进度条需一次 GPU 运行核对（重任务，另问） |
| 04 文档同步 | 模块边界"日志"条；批次编排模块页新增"运行日志"节（权威）；STT worker、翻译子系统模块页各一句；规格 §4 目录注释；README 第 12 条；CODING_STANDARDS 日志一句；技术选型注明"structlog 未采用" | 上列文档 | `just docs-check` |

依赖：02、03 依赖 01（logger 名与格式先定）；04 随各票交付同步，最后收口。01 与 03 都改 `job.py`，不并行；02 可与 03 并行。

## 5. 需用户裁定

1. **框架**：标准库 `logging`（推荐，理由 §3.1）还是采用技术选型清单里的 `structlog`（要加依赖、改 lock）。
2. **模块边界改动**：接受 §3.2 的新措辞，让翻译子系统与媒体模块经 logger 发事件；推理模块继续不发。
3. **控制台粒度**：翻译每批次一行同时上控制台与文件（推荐，最简）；还是控制台只保留 session 级事件、批次行只进文件（需要 DEBUG／INFO 分叉）。
4. **llama-server 重复日志**：`server.log` 与 `stderr.log` 相同。建议本次不动（6 MB／session 代价可忽略，`server_command` 是冻结命令行且有钉子测试）；若要去重，改 `ManagedServer` 把 stderr 指向 `DEVNULL` 并让 `loader_logs` 只读 `server.log`。

## Comments

- 2026-10-18 建票：现状核实自代码、模块边界、规格 §4 与 `.local/bilingual-fullfilm-08/out-w0/.work/` 的真实运行日志；未改任何代码。
- 2026-10-18 用户裁定（§5 全部按推荐项）：标准库 `logging`；模块边界措辞按 §3.2 调整；翻译批次行同时上控制台与文件；llama-server 重复日志本次不动。实施委派 Opus 5.5（medium）：01 先做，02／03 并行（各自 worktree），04 收口。
- 2026-10-18 实施完成（01–04 全部 resolved，未提交）：01 在主仓库完成；02／03 在临时 worktree（`.claude/worktrees/rl-02`、`rl-03`，用主仓库 `.venv` 解释器跑测试）并行完成后按文件复制回主仓库，文件集合不相交；04 以合并后的代码为准同步文档。主 agent review 后的两处修正：翻译子系统"意外异常"行去掉 `exc_info`（traceback 由编排 `ctx.fail` 记一次，避免双份）、对应用例改为断言无 traceback。
  - 自动检查：`just test` 366 个用例通过（原 349＋新增 17）、`just check` 通过。`just docs-check` 失败 44 处，全部位于未改动的冻结文档（`docs/archive/`、`docs/research/2026-10-03-*`、`docs/testing/*` 的外链与已搬走的文件），在干净 HEAD 上同样失败，非本次回归；本次改动的页面与新锚点无错误。
  - 与规格的偏差（已按代码写进批次编排模块页）：失败行只带异常类型＋traceback，无通用 200 字符截断（只有翻译重启／放弃两行截断）；`kototoki/logs.py` 作为基础层新模块承载格式（worker 壳是第二个使用者）；`child_env` 的三个变量以 `QUIET_ENV` 常量承载。
  - 已知但未处理：续跑复用已记录的降级节点时会再次打出降级／回退 WARNING（历史上确实发生过，措辞"splitting"略失真）；不经 `job.run` 调用翻译（如 smoke `translate_product`）没有 handler，WARNING 以上走 Python 兜底打到 stderr。
  - 未验证：真实 GPU 运行下 worker stderr 无进度条、llama-server 是否报告 `predicted_per_second`（决定 tok/s 字段）、整片的批次行可读性。需一次 `python -m kototoki` 真实运行（重任务，另问）。
- 2026-10-18 真实 GPU 运行核对（`D:\video\ATKD-089.avi`，3 h 28 min，单条 mp3 音轨无语言标签；配置 `.local/logcheck-atkd089/kototoki.toml` 只填 input_dir＝`D:/video`（目录内只有这一部，未建硬链接）与 output_dir＝`.local/logcheck-atkd089/out`，其余默认 w0）。命令 `.venv\Scripts\python.exe -m kototoki .local\logcheck-atkd089\kototoki.toml`，控制台（stdout＋stderr）存 `.local/logcheck-atkd089/driver.out`，退出码 0，总墙钟 840.3 s。证据都在 `.local/logcheck-atkd089/out/.work/`（下称 `.work/`），核对脚本只打印统计、不打印字幕。
  - (a) 通过：`.work/run-20261018T154158Z.log` 312 行，与 `driver.out`（去掉追加的 `EXIT=0`）逐行相同；312 行全部匹配 `UTC 时间 [elapsed s] LEVEL message`，311 INFO＋1 WARNING，无 ERROR、无 traceback。注意相对秒是 `%8.1f`，实际为 `[    10.0s]`（模块页示例原写 `[  10.0s]`，已随本次改正）。
  - (b) 通过（无进度条）：`run-…-asr.stderr.log`、`run-…-align.stderr.log` 均为 0 字节；`run-…-vad.stderr.log` 10 行，无 tqdm／HF 进度条，只有：1 行本格式 WARNING（`[py]` pyannote `ReproducibilityWarning`，TF32 被关闭；`warnings` 的多行正文作续行跟在后面）＋1 行 torch 自有格式的 `W1018 … torch\utils\flop_counter.py:29] triton not found …`（torch `torch._logging` 给 `torch` logger 自挂 handler，不经 root，不套 `RunFormatter`，也不计入编排的告警计数，属可接受噪声）。编排行 `[vad] 1 warning/error line(s)` 计数正确。附带观察：worker stderr 文件是 CRLF 行尾（Windows 文本模式 stderr），运行日志是 LF，不影响 grep。
  - (c) 通过：291 个批次行全部带 `tok`、`tok/s` 与 `cache`；tok/s 172.3–199.4（中位 194.9），首批 `cache 0`，其后 181／182。llama-server 响应的 `timings` 确有 `predicted_per_second`（另有 `predicted_n`、`cache_n`、`prompt_per_second` 等），见 `.work/125a9b5e45b9/translate/srt-3f27eb444c7a/dp10-cut-degrade-v1__s20261008/transport/session-01/*/response.raw`。
  - (d) 通过：从 `ATKD-089.ja.srt`／`zh.srt` 的 4031 行文字（≥4 字符）随机取 300 行，在运行日志、三个 stderr 日志与 `driver.out` 中 0 命中；这些文件里含假名或汉字的行数均为 0。llama-server 自身日志 `.work/translate-sessions/20261018T234932-30392/session-01/server.log`（与同目录 `stderr.log` 内容相同、各 6.1 MB／55175 行，已知重复）同样 0 行含假名汉字。
  - (e) 各阶段墙钟（`end` 行）：extract 14.2 s、vad 29.9 s、asr 302.0 s、align 96.8 s、translate 386.9 s（llama-server 加载 6.6 s，session 1 写 291 批 384.9 s），publish 后 summary：1 published、0 failed、0 fallback cue；进程退出码 0，GPU 锁运行后已释放。批次行 291／312 行（93%），每行约 90 字符、单行一事，整片读起来以批次行为主但结构清楚；stage 三件套与 summary 用 `grep -v 'translate\] batch'` 即得 21 行全貌。
  - 发现（未改代码，交用户决定）：1）媒体告警不进运行日志——本片无 `jpn` 音轨、按规则"取第一条音轨并告警"，但告警只写在 `.work/125a9b5e45b9/probe.json` 的 `warnings`，运行日志与控制台没有任何 WARNING；`Probe.warnings`／`Extract.warnings`（选轨回退、时长不符、解码偏长）都属"流程继续但应看一眼"，可考虑在 extract 后逐条记 WARNING。2）extract 阶段只有 `end` 行，没有 `start` 与逐文件 `done`，与"每阶段三件套"不一致（`kototoki/job.py:692`）。3）torch 自有格式的 `W…]` 行不计入 stderr 告警计数（见 b）。
- 2026-10-19 补上真实运行发现的 1）2）（未提交，未再做真实运行）：`job.probe_and_extract` 返回 probe 与 extract 的告警（跳过 extract 时取 `probe.json` 的 `extract.warnings`），编排在 extract 线程池的主线程循环里逐条记 `[extract] <相对路径>: <告警>` WARNING，媒体模块仍只返回数据、不发日志；extract 补 `[extract] start: N file(s)` 与逐文件 `done <相对路径>`，`end` 行不变。新增用例：`tests/core/test_job.py` 的 `RunLogTests.test_extract_logs_start_done_end`、`test_media_warnings_are_logged_per_file`，`tests/full/test_job_ffmpeg.py` 的 `test_missing_jpn_track_is_logged_as_warning`（音轨标 `eng`）。`just test` 368 通过、`just check` 通过、`just test-full` 12 通过。批次编排与配置／媒体模块页已同步。3）未处理。
