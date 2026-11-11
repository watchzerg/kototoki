# 批次编排

状态：current（2026-11-11 加内嵌日文字幕路径，[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)，只用伪媒体与 ffmpeg 合成片段测过；票据 06 交付，2026-10-14；票据 14 把阶段链与期望身份拆到[阶段计划](stage-plan.md)，票据 15 把翻译阶段的取锁改为按需，2026-10-15）；GPU worker 按 [STT worker](stt-workers.md)（票据 03、07）的 jobs 约定调用，翻译与合并见[翻译子系统与合并](translation-subsystem.md)（票据 05、09），专名建表见[专名一致性](name-consistency.md)（2026-10-20 专名票据 06 接入）；2026-11-08 起翻译走 Strata、没有发布时替换（[ADR-0019](../../adr/0019-product-translation-q2.md)）；2026-11-09 起 names 建表也走 Strata，两阶段共用一个由编排持有的 Strata session，产品不再起 llama-server（[ADR-0022](../../adr/0022-product-names-on-strata.md)）。离线由伪 worker、伪专名与伪翻译模块测试；真实 worker、ffmpeg 与 llama-server 下的两部整片 × w0／x0 整批运行，以及翻译失败后重跑时 STT 产物按身份全部跳过的续跑，已在[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)中通过；names 阶段已有真实运行（专名票据 07、08，含当时的发布时替换，已删除）；Q2 的 Strata 自动启停编排已于 2026-11-08 整片运行；共用 session 的真实运行结果记在 ADR-0022 所指计划的 §7。2026-11-11 起按 [ADR-0025](../../adr/0025-product-package-boundaries.md) 与计划 [`architecture-cleanup`](../../plans/architecture-cleanup.md) 先行改写本页接口（GPU 锁冲突一律进程级、worker 协议读侧收进 `protocol.classify_launch`、进程原语移到 `kototoki/procs.py`、四个子系统改为普通导入、`ja.srt` 新鲜度归阶段计划），代码随该计划的票据 02–09 落地，实现结果见计划 §7。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3、§4、§6、§7.1，[模块边界](../module-boundaries.md#产品包的责任边界)）的唯一入口与全部流程知识：扫描输入（视频与音频）、调度 CPU 与 GPU 阶段、CPU 阶段产物的写入、续跑与失败隔离、两把锁、Job Object、子进程环境、专名表的写出、双语字幕发布到源文件旁与运行日志。不负责：阶段链、各阶段的期望身份与"下一个要跑的阶段"（[阶段计划](stage-plan.md)，编排只负责问）、身份的组成规则、匹配规则本身（[产物契约](artifact-contract.md)）、音轨与 WAV（[配置、配方与媒体提取](config-and-media.md)）、cue 切分（[日文 cue](japanese-cues.md)）、推理（[STT worker](stt-workers.md)）、建表的内部（[专名一致性](name-consistency.md)）、翻译与合并的内部（[翻译子系统](translation-subsystem.md)）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**入口**：`python -m kototoki [kototoki.toml]`（默认 `./kototoki.toml`）读配置，`check_input_dir` 要求 `input_dir` 是已存在的目录（否则扫描到 0 个文件也会以退出码 0 结束，无人值守时像成功；双语字幕写在源文件旁，因此也拒绝位于仓库内（`.local/` 除外）的输入目录），`check_work_dir` 拒绝工作目录位于仓库内（`.local/` 除外）或位于输入目录内（含相同），再调用 `job.run(config) -> Summary`。退出码：0 全部成功；1 有文件失败（其余照常发布）；2 配置、输入目录或工作目录不可用；3 同一目标目录已有编排器在运行（`WorkLocked`，`EXIT_WORK_LOCKED`）；4 GPU 锁冲突（`GpuLocked`：任何阶段——vad、asr、align、names、translate——需要 GPU 锁而撞上都以此结束整批，不写逐文件 `failure.json`；已完成的 CPU 产物保留，可续跑；同批的零条目文件也等到下一次运行再发布，[ADR-0025](../../adr/0025-product-package-boundaries.md)）。源文件旁已有字幕而跳过、仍在写入的文件不改变退出码，后者只告警，不改变退出码。

**流程**（阶段 × 整批）：

1. 取工作根 `<work_dir>/<input_dir 末段名>-<sha12>/lock`（基础层 `procs.ProcessLock`，锁信息含 `input_dir`；`artifacts.work_root`，见[产物契约](artifact-contract.md)），并写 `input.json`；把编排器进程放进 KILL_ON_JOB_CLOSE Job Object，此后的 ffmpeg、worker 与 Strata CLI 子进程自动加入（Strata 服务本身由 `strata launch --no-tui --model iq3_s` 在后台启动，不在 Job Object 内，靠 `Session` 退出时的 `--stop` 收尾），编排器以任何方式退出时随之结束（Job Object 建不起来时释放工作根锁再抛出）。
2. 扫描：递归列出扩展名（大小写不敏感，`[input] extensions`，视频与音频）匹配的文件，按相对路径排序；两次采样（间隔 `stable_check_s`）大小不变才处理，否则本次跳过；源文件旁已有 `<主名>.ja-zh.srt`（`final_srt_path`，只看文件名，不论来源）的文件记入 `Summary.existing` 并跳过，不登记工作目录、不 probe、不进任何阶段，也不动残留的 `failure.json`；否则登记 `<work root>/<id>`（`register_work_dir` 抛异常——`index.json` 损坏、短 id 碰撞——只记该文件 `scan` 失败，没有工作目录因而不写 `failure.json`，整批继续）；同目录主名相同、扩展名不同的文件（如 `ep01.mkv` 与 `ep01.mp3`）会争用同一份字幕路径，按相对路径顺序后出现的那个记 `scan` 失败（`FinalPathCollision`，写 `failure.json`），Windows 下路径比较忽略大小写。
3. probe／extract：线程池（`extract_workers`）对每个文件跑 ffprobe（每次都跑，得到输入文件身份）；`[input] use_embedded_subtitles` 开着且 `media.select_subtitle` 选出可用的日文文本字幕轨时先走"内嵌日文字幕"（见下，[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)），采用后该文件不提取音频；否则（或字幕轨不可用时）`probe.json` 身份匹配且 `audio-16k.wav` 在时跳过 extract，否则先删除工作目录里上次强杀留下的 `.*.partial*`（ffmpeg 临时输出）与 `.*.tmp`（原子写临时文件），再 extract（音频输入不流复制）并写 `probe.json`（probe payload 加 `extract` 记录，含 PCM SHA256；音频输入的 `audio_copy` 为 null）。每个成功的文件先把 `Probe.warnings` 与 `Extract.warnings`（跳过 extract 时取 `probe.json` 记下的 `extract.warnings`）逐条记为 WARNING，再按 `extract.compensation` 记补偿告警（`compensation_warnings`：`net_padding_s` 绝对值或 swr 报告的丢弃样本折算超过 `COMPENSATION_WARN_S = 0.1` s 时各一行，跳过 extract 时同样由 `probe.json` 算出），最后记 `done`。Ctrl+C（任何 `BaseException`）时 `shutdown(cancel_futures=True)`：排队中的文件不再提取，只等正在跑的 ffmpeg 结束，然后沿 `finally` 释放两把锁。
4. 计划：CPU 阶段之后对每个文件调用一次 `plan.next_stage`，从 vad 起（采用内嵌字幕的文件从 names 起，不进第 5、6 步）逐阶段核对产物身份，得到第一个需要运行的阶段（`vad`／`asr`／`align`／`cues`／`names`／`translate`）或终态（`publish`：无语音）；没有 `done` 状态——是否已发布由扫描按源文件旁的字幕判定。
5. vad → asr → align：计划落在本阶段的文件组成一批，交给一个 worker 子进程；没有文件需要 GPU 时不取 GPU 锁。worker 结束后对每个文件 `plan.advance`，从刚跑完的阶段继续核对：产物缺失或身份不符即记该阶段失败（`ArtifactMissing`），否则计划推进到下一个需要运行的阶段。
6. ja-cues（进程内，`build_ja_cues`）：`cues.build_cues(align, [cues] 规则)`，写 `ja.srt` 后写 `ja-cues.json`（payload 另记写出的 `ja.srt` 的 SHA256 `ja_srt_sha256`，供阶段计划核对 `ja.srt` 的新鲜度），随后 `plan.advance`。
7. 共享 Strata session：进入 names 之前编排建一个 `strata.Session(config, on_server_pid=写 GPU 锁)`（上下文管理器，包住 names 与 translate 两个阶段：正常结束、出错或被中断都 `strata launch --stop` 并核实显存释放），传给下面两步；Strata 在第一次真正请求模型时才启动（可能在 names，也可能在 translate），两阶段之间不停，启动失败整批累计 3 次即不可用；两阶段都不需要模型时整批不启动。
8. names（进程内，恒在链上，`names_batch`）：读每个文件的 `ja.srt`；只有某个文件有 cue 时才取 GPU 锁，有 cue 的文件把共享 session 传给 `names.build_document`（零条目文件传 `None`）；随后由编排 `write_artifact(name-table.json, plan.identities["names"], payload)`，`build.status` 不是 `ok`（`too_long`／`failed`，空表）记 WARNING、影片照常往下走；读 `ja.srt` 出错记该文件 `names` 阶段失败；撞 GPU 锁（`GpuLocked`）不捕获，与 GPU 阶段一样向上抛、整批退出码 4（共享 session 此时尚未启动 Strata，`with` 块正常退出）；建表抛异常（`NamesError` 等：传输失败、HTTP 错误、OOM、Strata 不可用）只让该文件失败；随后 `plan.advance`。
9. translate（进程内）：每文件的 `TranslatePlan` 已在计划里（`plan.translate`，由 `name-table.json` 的注入行与 `ja.srt` 算出）；只有任一文件 `needs_model` 时才取 GPU 锁（names 已取时沿用），把同一个共享 session 传给 `translate_document(plan, session)`（names 阶段没有启动 Strata 时在这里第一次启动），对不需要模型的文件传 `None`（零条目、或 run 已完成而只是源文件旁的字幕被删）；撞 GPU 锁同 names，向上抛、整批退出码 4；Strata 被拒绝（已有别的 launch、身份不符、专家区退到 mmap）时共享 session 置为不可用（可能已在 names 阶段置位），其余需要模型的文件直接失败；单文件异常记该文件失败并继续。
10. 发布：`ja-zh.srt` 文本（翻译结果与 `ja.srt` 按 cue 合并，没有专名替换；零 cue 为空文本）先查源文件旁是否已出现同名字幕（运行期间由用户或别的工具写入）：有则不覆盖，记入 `existing` 并告警；否则写到 `<work root>/<id>/publish/` → `record_published`（审计）→ 原子移动到源文件旁（`replace_with_retry`，带 `PermissionError` 重试）→ 删除该文件的 `failure.json`。`ja.srt` 留在工作目录，不发布 `zh.srt`。发布日志行在有回退 cue 时追加 `, N fallback cue(s)`。收尾不变量：每个未失败的文件此时必须已在 `published`、`existing` 或 `no_speech` 里，否则记该文件 `publish` 阶段失败（防止某个计划阶段没被任何执行器处理时既不发布也不失败、整批却以 0 退出）。

**内嵌日文字幕**（`job.use_embedded_subtitle`，在 probe／extract 的线程池里；[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)，选轨、抽取与清洗规则见[配置、配方与媒体提取](config-and-media.md)）：

- 跳过：由[阶段计划](stage-plan.md)判定内嵌记录是否当前（身份等于 `plan.embedded_identity(probe 身份, 流索引)`，且记下的 `ja_srt_sha256` 等于工作目录里 `ja.srt` 的 SHA256，与 cues 检查共用同一个辅助函数），当前即不再抽取。
- 否则 `media.extract_subtitle` → `embedded.clean`；先删上次强杀留下的临时文件，再写 `ja.srt`，最后写 `ja-embedded.json`（流信息、清洗计数、`ja.srt` 的 SHA256）。不删 `ja-cues.json`：它也记着 cue 阶段写出的 `ja.srt` 的 SHA256，字幕轨改写 `ja.srt` 后它不再当前，以后改走 STT 时 cues 阶段自然重建；反过来，cue 阶段改写 `ja.srt` 后内嵌记录的 SHA256 不再相符，下次走内嵌路径时重新抽取。
- `probe.json` 不当前时写出，`extract` 为 null（没有提取音频）；以后该文件改走 STT 时照常提取并改写。
- 采用后 `VideoFile.embedded` 记该身份，计划从 names 起；日志行为 `[extract] done <相对路径>: embedded subtitle stream N (<codec>), M cue(s), skipping speech recognition`，只把选轨告警（多条可用）记为 WARNING，音轨告警与该文件无关、不记。发布行加 ` (embedded subtitles)`，`Summary.embedded` 列出这些文件，汇总行给出个数。
- 不可用（ffmpeg 抽取失败即 `MediaError`，或清洗后零条目）：不写任何内嵌产物，记 WARNING `[extract] <相对路径>: Embedded subtitle stream N is unusable (<原因>); falling back to speech recognition`，该文件照常提取音频走 STT；不算失败、不缓存，下次运行再试。
- 字幕文字不进日志（只有流索引、编码与条数）。整批都是这类文件时没有 GPU worker，GPU 锁到 names 需要模型时才取。

**计划与身份**：续跑与跳过的唯一判据是[阶段计划](stage-plan.md)给出的 `Plan`（`stage`、各阶段期望身份、`no_speech`、`TranslatePlan`）；编排对每文件调用一次 `next_stage`，每跑完一个阶段调用一次 `advance`，不自己拼身份。模型文件 SHA256 由编排的 `model_sha_lookup` 经 `gpu.verify_models`（`plan.model_files` 给出期望值，size+mtime 缓存与 worker 共用 `<work_dir>/cache/model-verification.json`）按阶段每次运行最多核对一次（失败结果同样缓存，模型 SHA 不符时不会为每个文件重算一次）；模型缺失或不符时需要该阶段核对的文件记失败。`published.json`（审计记录）的 `sources` 即 `Plan.sources`（全部身份与 `no_speech`，含 `names`，另记 `translate_fallback_cues`），不参与任何判定。用户手改 `name-table.json` 的 `entries`：改到会被注入的条目（`high` 的实体或其写法）即改变翻译身份的 `names_sha256`，但已发布的字幕不会自动重做——须先删掉该 `.ja-zh.srt`，再运行才重译（需要 Strata）；只改 medium／low 条目不触发任何重做。

**GPU worker 调度**：命令 `sys.executable -m kototoki.workers.<stage> --jobs <work root>/jobs-<stage>.json`，`cwd` 为仓库根；jobs 按 [STT worker](stt-workers.md) 的约定：`recipe_hash` 为 `plan.recipe_hash(stage, engine=…)`，`config` 为 `{"engine", "models": plan.worker_models(config), "model_cache"}`，`inputs` 按 `plan.STAGE_INPUTS`（vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）；worker 用 `plan` 的身份函数写入身份，编排用同一函数核对。子进程环境在当前环境上加 `PYTHONUTF8=1`、`HF_HUB_OFFLINE`／`TRANSFORMERS_OFFLINE`／`HF_DATASETS_OFFLINE`／`HF_HUB_DISABLE_TELEMETRY=1`、`PYANNOTE_METRICS_ENABLED=0`、`HF_HOME`＝`TORCH_HOME`＝`<work_dir>/cache/`，以及关进度条的 `QUIET_ENV`（见[运行日志](#运行日志)）；stdout 逐行读进度 JSON 写入运行日志，stderr 追加到 `<work root>/run-<时间戳>-<stage>.stderr.log`。

**崩溃与重启**（按文件计）：每次启动 worker 后，`run_gpu_stage` 把待跑 id、退出码与进度事件交给协议的纯函数 `protocol.classify_launch(ids, exit_code, events) -> LaunchOutcome`（规则见[产物契约](artifact-contract.md)），自己只做循环与 `ctx.fail`：

- 报告 `failed` 的文件记该阶段失败（`failure.json` 已由 worker 写出）。
- 退出码 0／1 且每个待跑 id 都有事件：正常结束，其余按产物核对。退出码 1 也是 Python 未捕获异常的退出码，所以有待跑 id 没有事件时不算正常结束，按下面的崩溃规则处理。
- 有 `startup_failed` 事件（模型加载失败，与文件无关，退出码 2）：本阶段剩余文件全部失败，不重启。
- 有 `fatal` 事件（退出码 2）：该文件失败，从下一文件重启 worker。
- 其他异常退出：最后一个有事件的文件之后的第一个文件即正在处理的文件，编排写 `failure.json`（`WorkerCrashed`）并从其后文件重启。
- worker 结束后 `plan.advance` 仍停在本阶段的文件（产物缺失或身份不符）记失败（`ArtifactMissing`）。失败文件退出后续阶段，批次继续。
- `_launch` 读 worker stdout 期间抛异常（Ctrl+C、写日志失败）时，先 kill 并 wait 仍在运行的 worker，再向上抛；之后 `run` 的 `finally` 才释放 GPU 锁。

**无语音**：`vad.json` 的 `chunks` 为空列表时跳过 asr／align／ja-cues／names／翻译，直接发布零条目 `ja-zh.srt`。

**锁**：GPU 锁是 `config.gpu_lock`（仓库内 `.local/gpu.lock`），第一个需要 GPU 的阶段前获取，持有到翻译结束，names 阶段只在有文件的 `ja.srt` 有 cue 时才取，翻译阶段只在有文件 `needs_model` 时才取（全部 run 已完成或零条目时整批不占 GPU）；锁文件记录编排器 pid 与创建时间，worker 运行期间记 `worker_pid`／`worker_stage`（`Popen.pid`；用 venv 的 `python.exe` 启动时这是启动器进程，真正的 worker 是它的子进程），Strata 运行期间记其 `server_pid`（由共享 `strata.Session` 的 `on_server_pid` 回调提供：ready 后写入、停止后清空；pid 取自 `strata launch --status`，缺失时不记）。持有者存活即拒绝，残留锁（死 pid，或空的／无法解析的锁文件——持有者刚创建锁就被杀）默认拒绝，`KOTOTOKI_BREAK_STALE_LOCK=1` 时移除残留锁（对工作根锁同样适用）；从不抢占存活的持有者。GPU 锁取不到时不论发生在哪个阶段都抛 `GpuLocked`、整批退出码 4（见入口），不把它记成文件级失败。锁与进程身份的原语在基础层 `kototoki/procs.py`。

**`failure.json` 清理**：该文件本次成功发布后、以及发布期发现源文件旁已有同名字幕而按已存在跳过时删除；重跑时不看 `failure.json`，只按产物身份决定从哪个阶段继续，新的失败覆盖旧记录。

### 运行日志

本节是产品运行日志的权威；模块边界只规定目的地与格式归编排（[责任边界](../module-boundaries.md#产品包的责任边界)）。

- **框架**：标准库 `logging`。[技术选型](../../development/technology-stack.md)"需要时"清单里的 `structlog` 于 2026-10-18 评估后未采用：读者只有人和 `grep`，transformers、pyannote 等第三方库的告警本就走标准库 logging，一个 root handler 即可收进同一文件，无需桥接，也不新增依赖。
- **挂接**：`job.run` 取到工作根锁后，在 `_run_logging` 上下文内给 root logger 挂两个 INFO 级 `StreamHandler`：`<work root>/run-<UTC戳>.log`（UTF-8、`\n` 行尾）与控制台（默认 `sys.stdout`），共用一个 `kototoki.logs.RunFormatter`；`kototoki` logger 临时设为 INFO。root 级别不动（默认 WARNING），所以第三方库只有 WARNING 及以上进日志，消息前加 `[<logger 名首段>]`（如 `[transformers]`），`kototoki.*` 不加。`run` 退出（含异常）时恢复级别、摘下并关闭 handler。其他产品模块只经 `logging.getLogger(__name__)` 发事件（`kototoki.job`、`kototoki.translate.*`、`kototoki.strata`（Strata 启停、等显存与内存、接入检查、停止核实，前缀 `[strata]`）、`kototoki.names.table`（不合格的建表尝试，前缀 `[names]`）；`kototoki.names` 包顶层不发日志，建表结果行由编排写；worker 壳在子进程里，见 [STT worker](stt-workers.md)），不配置 handler、不开文件。
- **级别**：INFO 为进度、计数与耗时（每阶段 start／逐文件 done／end、worker 的 stdout 进度事件、建表每部一行（条目数、丢弃数、prompt／completion token、秒数）、翻译每批一行、发布行的回退 cue 数、结尾汇总（含回退 cue 数））；WARNING 为流程继续但应看一眼的事（大小仍在变化、发布期发现字幕已出现而不覆盖、媒体告警（`[extract] <相对路径>: <告警>`，如无 `jpn` 音轨时取第一条、时长来源不符、解码偏长、重采样净补偿或丢弃样本超过 0.1 s；媒体模块不发日志，由编排在主线程逐条记，续跑跳过 extract 时照样出现）、worker stderr 有告警、建表终态失败写空表（`[names] done <相对路径>: build failed (<原因>), empty table`）、等显存超过 30 s、Strata 重启／降级拆批／回退保留日文）；ERROR 另含 Strata 被拒绝与停止未核实；ERROR 为文件级与进程级失败；DEBUG 不用。
- **行格式**（`kototoki/logs.py` 的 `LOG_FORMAT`／`LOG_DATEFMT`）：UTC 墙钟、自本次 `run` 起的相对秒、定宽级别、消息；消息沿用 `[stage]` 前缀与 start／done／end／FAILED 词汇。例：

  ```
  2026-10-18 12:06:21Z [    10.0s] INFO     [scan] 2 file(s): 2 to process, 0 with subtitles, 0 unstable
  2026-10-18 12:41:07Z [  2096.0s] WARNING  [asr] 3 warning/error line(s), see run-20261018T120611Z-asr.stderr.log
  2026-10-18 13:05:02Z [  3531.0s] ERROR    [translate] FAILED S1/ep01.mkv: TranslateError
  ```

  文件级失败的 ERROR 行只带异常类型，traceback（`exc_info`）紧随其后，控制台与文件相同；失败由 worker 报告（`failure.json` 已由 worker 写出）时没有 traceback。
- **文件**：`<work root>/run-<UTC戳>.log` 与控制台逐行相同。`<work root>/run-<戳>-<stage>.stderr.log` 在每次启动该阶段 worker 时追加其 stderr（壳按同一格式写的日志、第三方告警与裸 traceback）；worker 退出后编排只读本次启动追加的部分，统计按本格式写出、级别为 WARNING／ERROR／CRITICAL 的行，非零时在运行日志记一行 WARNING（上例第二行），非本格式的行不计。Strata session 的证据（接入身份、资源峰值、停止核实）另在 `<work root>/strata-sessions/`（[翻译子系统](translation-subsystem.md)"Strata 生命周期"）。
- **内容**：
  1. 转写、cue 与窗口文字、译文、专名表条目与 `work_guess`、提示词、grammar、模型响应正文不进任何日志；失败窗口只记序号与 reason。
  2. 失败行只记异常类型，traceback 随后（只含源码行；异常消息可能含文件路径，不含转写）；异常消息不做通用截断，只有翻译的 server 重启与放弃两行把异常首行截到 200 字符。翻译子系统的"意外异常"行不带 traceback，由编排的 FAILED 行带。
  3. 文件名用输入目录内相对路径，只有锁与日志文件的指向写绝对路径。
  4. 一事一行、每阶段三件套、结尾汇总；`end` 行带墙钟，翻译批次行带输出 token 数、tok/s 与 cache（取不到的字段省略）。
  5. 告警是级别不是措辞：消息里不写 `WARNING`。
- **子进程噪声**：`child_env` 在离线变量之外合入 `QUIET_ENV`（`TQDM_DISABLE=1`、`HF_HUB_DISABLE_PROGRESS_BARS=1`、`TRANSFORMERS_VERBOSITY=warning`），让 worker stderr 只留日志行；这组变量归编排。
- **启动早期错误**：用法与配置错误、工作根锁与 GPU 锁冲突由 `__main__` 打印到 stderr（控制台流设 `errors="backslashreplace"`），以退出码区分，不写成日志行。
- **真实运行核对**（2026-10-18，3.5 h 整片 w0，记录见 `.scratch/runtime-logging/spec.md` Comments）：运行日志与控制台逐行相同且全部符合行格式；asr／align worker stderr 为空，vad 只剩 pyannote 的 TF32 `ReproducibilityWarning`（本格式）与 torch 自挂 handler 的一行 `W… triton not found`（非本格式、不计数），无进度条；llama-server 的 `timings` 带 `predicted_per_second`，批次行均出现 tok/s 与 cache；日志与 stderr 不含 cue 文字或译文。该次核对发现的两处缺口已于 2026-10-19 补上：媒体告警改由编排写成 WARNING 行（此前只在 `probe.json`），extract 补齐 `start`／逐文件 `done`／`end` 三件套；补后未再做真实运行。

## 接口与依赖

导入基础层的 `artifacts`、`config`、`srt`、`logs`、`procs`（`ProcessLock`、`LockError`、`contain_children` 等进程原语）、`workers.protocol`（jobs 读写与 `classify_launch`），以及 `media`、`cues`、`embedded`、[阶段计划](stage-plan.md)的 `plan` 与 `workers.gpu`（只用 `verify_models`，导入时不加载推理库），不导入 worker 壳。以普通导入使用：`kototoki.strata`（共享 session，`Session(config, on_server_pid=...)` 上下文管理器，Strata 生命周期）、`kototoki.names`（`build_document(work_dir, document, session | None, seed)` 返回带 `payload`／`status`／`attempts`／`seconds` 的结果；names 身份由阶段计划算）、`kototoki.translate`（`translate_document(plan, session | None)` 返回带 `translations`（cue id → 译文）与 `fallback_count` 的结果；`TranslatePlan` 由阶段计划经 `translate.plan` 取得）与 `kototoki.merge`（`merge(ja_document, translations) -> srt_text`）；这四个模块不导入 `plan`、`job`，不加载 torch，测试以属性 patch（如 `mock.patch("kototoki.translate.translate_document")`）替换。不导入任何推理模块与 `experiments.*`：`import kototoki.job`／`kototoki.__main__` 之后 `sys.modules` 中没有 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`。不做任何时间换算。

## 代码与验证入口

- 代码：`kototoki/__main__.py`（`main`、`check_input_dir`、`check_work_dir`）、`kototoki/logs.py`（`LOG_FORMAT`、`RunFormatter`）、`kototoki/job.py`（`run`、`_run_logging`、`QUIET_ENV`、`Summary`、`model_sha_lookup`、`compensation_warnings`、`clean_leftovers`、`probe_and_extract`、`use_embedded_subtitle`、`run_gpu_stage`、`advance_or_fail`、`build_ja_cues`、`names_batch`、`translate_batch`、`publish`、`FinalPathCollision`）、`kototoki/procs.py`（`pid_alive`、`process_created`、`process_matches`、`contain_children`、`ProcessLock`、`LockError`；锁、进程身份与 Job Object 复制自 `experiments/translation_v3/procs.py`，未导入；`job` 从它导入，`mock.patch("kototoki.job.contain_children")` 仍有效）、`kototoki/workers/protocol.py`（`classify_launch`）。
- 测试（core，`just test`）：`tests/core/test_procs.py` 直接测进程原语（空锁文件、不可解析、无 `pid_created` 的外部锁、过期锁与破锁环境变量、release 只删自己的锁）；`tests/core/test_protocol.py` 直接测 `classify_launch`（正常、部分失败、`fatal`、`startup_failed`、无事件崩溃、退出码 1 但缺事件）；`tests/core/test_job.py` 以伪 worker 脚本 `tests/fake_worker.py`、属性 patch 的专名、翻译与 Strata 函数（`merge` 用真的；伪翻译不重写注入规则，表身份取整张表的不透明 hash）、打桩的 `media.probe`／`extract` 与 `cues.build_cues` 覆盖扫描（视频与音频、源文件旁字幕已存在即跳过）、同目录同主名的字幕路径碰撞、`register_work_dir` 异常只让该文件失败、Job Object 失败释放工作根锁、大小采样稳定性、发布期同名字幕已出现不覆盖、删除残留 `failure.json`、阶段顺序、崩溃文件隔离与按文件重启、失败隔离、extract 期间中断取消排队文件、提取前清理 `.*.partial*`／`.*.tmp`、中断后续跑、工作根锁与 GPU 锁冲突退出码（含首个需要 GPU 的阶段是 names 的批次：退出码 4、无 `failure.json`）、`_launch` 异常时子进程被回收、收尾不变量、空的／无法解析的锁按残留处理、无语音路径、发布到源文件旁、子进程环境、禁止导入清单、输入目录存在性与工作目录位置检查、翻译阶段只在有文件需要模型时取锁、共享 Strata session 整批只启动一次（可从 names 或 translate 起）、两阶段都不需要模型时不启动、出错或中断时 stop、`StrataRefused` 让两个阶段都失败，以及一次整批运行中每文件 `plan.next_stage` 恰一次、每个跑过的阶段（含 names）`plan.advance` 恰一次；`NamesTests` 覆盖 names 阶段（见[专名一致性](name-consistency.md#代码与验证入口)）；伪 worker 与真 worker 一样从 WAV 算 PCM SHA256 并经 `plan` 取身份。`RunLogTests` 覆盖运行日志：文件与控制台逐行相同且符合格式、告警与失败的级别、extract 三件套、媒体告警逐条 WARNING（含续跑跳过 extract）、补偿告警的阈值与续跑、失败行后的 traceback、handler 与级别复原、第三方前缀与级别过滤、worker stderr 的告警计数。计划模块自身的测试见[阶段计划](stage-plan.md)。
- 测试（full，`just test-full`）：`tests/full/test_job_ffmpeg.py` 沿用 `JobCase` 的接缝（`FAKE_MEDIA = False`），媒体阶段用 ffmpeg 合成的 3 s 视频走真实 `media.probe`／`extract`，GPU 阶段仍是伪 worker、cue、专名与翻译仍是假实现：检查派生 WAV 规格、三个 GPU 阶段各启动一次、共享 Strata session 在 names 阶段启动、翻译后退出、`name-table.json` 落盘、双语字幕发布到源文件旁及 `published.json`（`sources` 含 `names`）；音轨标 `eng` 的合成视频照常发布，且控制台恰有一行选轨回退的 WARNING。`tests/full/test_media_ffmpeg.py` 的合成 2 s 间隙另断言 `compensation_warnings` 给出一行补入告警。不经 `python -m kototoki` 子进程、不起 Strata（打桩的 `strata.Session`）。
- 内嵌日文字幕（ADR-0024）的测试：core 为 `tests/core/test_job.py` 的 `EmbeddedSubtitleTests`（打桩 `media.extract_subtitle`：采用后不提取音频、不起 worker、`sources` 的键与日志行、字幕文字不进日志；整批都是这类文件时 GPU 锁到 names 才取；开关关掉走 STT；抽取失败与零条目回退并告警；续跑按身份跳过抽轨、`ja.srt` 被改写后重新抽取；两条路径来回切换不串用 `ja.srt`）；full 为 `tests/full/test_job_ffmpeg.py` 的三个内嵌字幕用例（真实 ffmpeg，SubRip／ASS／mov_text）。未做真实片源与真实模型的运行。
- 真实运行：[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)（Heaven's Feel II／III 各以 w0、x0 整批运行，12 份 SRT 齐全；首轮翻译因空闲显存低于启动阈值失败，重跑时 STT 按产物身份全部跳过、只做翻译与发布）。
- 真实失败路径：[最终验收](../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)——asr 阶段强杀编排器后 worker 随 Job Object 退出、残留锁默认拒绝（退出码 3）、`KOTOTOKI_BREAK_STALE_LOCK=1` 后从 vad 产物续跑；无语音视频、损坏文件隔离、子目录镜像、当时的"用户改动最终文件的拒绝与 `force` 覆盖"（ADR-0020 已删除该机制）、重跑逐字节一致均通过。
- 真实运行（共用 Strata session，2026-11-09，ADR-0022 所指计划的 §7）：HF-II 整片 W0 一次通过，墙钟 1014.8 s；Strata 在 names 阶段启动一次（78.1 s，`ram`）、翻译沿用、整批结束后 `--stop`（status 为空、空闲显存 15059 MiB）再放 GPU 锁；建表 2 次尝试 ok，翻译 149 包回退 0，发布 `ja-zh.srt` 1099 条。
- 未验证：被中断时的停止与显存核实的真实路径；names 阶段的 x0 输出、其他作品与失败路径的真实运行；worker 退出码 2（CUDA 粘性错误）与按文件重启的真实路径；2026-10-19 的小修集合（最终路径碰撞、中断取消提取、临时文件清理、空锁破除、补偿告警等）只经离线测试，未做真实运行。

## 变更与决策来源

2026-11-11 内嵌日文字幕（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）：probe／extract 阶段加 `use_embedded_subtitle` 分支，`Summary` 加 `embedded`，汇总行加 `N from embedded subtitles`。

票据 `.scratch/bilingual-subtitle-pipeline/issues/06-batch-orchestration.md`、`14-stage-plan-module.md`（阶段链与身份拆出，见[阶段计划](stage-plan.md)）、`15-translate-run-key.md`（翻译阶段按 `needs_model` 取锁、session 失败只影响需要模型的文件）；规格 §3、§4、§6、§7.1 与 §1.2 第三轮裁定表。

2026-10-18 运行日志改为标准库 logging：票据 `.scratch/runtime-logging/issues/01-orchestrator-logging.md`（编排）、`02-translate-progress.md`（翻译进度）、`03-worker-logging.md`（worker 壳与 `QUIET_ENV`），设计见同目录 `spec.md`。

2026-10-18 吸收增量说明《依赖入项目与测试分层调整》（`docs/changes/local-dependencies-and-test-layers.md`，已删除）：`JobCase` 加 `FAKE_MEDIA` 接缝，新增 full 层端到端测试 `tests/full/test_job_ffmpeg.py`。

2026-10-19 架构审计小修集合：票据 `.scratch/architecture-review/issues/01-small-fixes.md`（报告 `.scratch/architecture-review/2026-10-19-report.md` 的 B-1、B-2、A-3、B-3、B-6、B-9、B-10、B-13）。

2026-10-20 专名一致性进产品（[ADR-0014](../../adr/0014-name-consistency-in-product.md)）：票据 `.scratch/name-consistency-product/issues/06-orchestration.md` 加 names 阶段（流程第 7 步）、发布时替换与审计文件、GPU 锁的 names `server_pid`、日志与汇总的替换处数。

2026-11-08 产品翻译切到 Q2（[ADR-0019](../../adr/0019-product-translation-q2.md)）：删除发布时专名替换（`apply_names`、`names-apply.json`、`Summary.name_replacements`、日志里的替换处数），发布行改记回退 cue 数；翻译 session 管理 Strata 而非 llama-server；`[names] enabled` 删除，names 恒在链上。

2026-11-09 产品建表切到 Strata（[ADR-0022](../../adr/0022-product-names-on-strata.md)）：names 的 llama-server session 删除，编排持有一个共享的 `strata.Session`（`kototoki/strata.py`）包住 names 与 translate 两个阶段，整批只启动一次 Strata；流程第 7–9 步、GPU 锁的 `server_pid` 与日志来源按此改写。

2026-11-11 产品包架构整理（[ADR-0025](../../adr/0025-product-package-boundaries.md)，计划 [`docs/plans/architecture-cleanup.md`](../../plans/architecture-cleanup.md)，tracker `.scratch/architecture-cleanup/`）：GPU 锁冲突在 names 与 translate 也改为进程级（此前本页同时写着退出码 4 与"取锁出错只让需要模型的文件失败"两种说法）；worker 退出的分类收进 `protocol.classify_launch`；`_launch` 异常时回收 worker；收尾不变量；`model_sha_lookup` 缓存失败；进程原语移到 `kototoki/procs.py`；四个子系统改为普通导入；内嵌路径不再删 `ja-cues.json`，`ja.srt` 新鲜度归阶段计划；依赖清单补上 `embedded`、`logs`。
