# 批次编排

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0020](../../adr/0020-media-inputs-work-dir-and-side-by-side-publish.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线（[技术设计](../../specs/bilingual-subtitle-pipeline.md) §3、§4、§6、§7.1）的唯一入口与全部流程知识：扫描输入（视频与音频）、调度 CPU 与 GPU 阶段、CPU 阶段产物的写入、续跑与失败隔离、两把锁的取放时机、专名表的写出、双语字幕发布到源文件旁与运行日志的挂接。

不负责：阶段链、各阶段的期望身份与"下一个要跑的阶段"（[阶段计划](stage-plan.md)，编排只负责问）；身份的组成与匹配规则（[产物契约](artifact-contract.md)）；音轨与 WAV（[配置、配方与媒体提取](config-and-media.md)）；cue 切分（[日文 cue](japanese-cues.md)）；推理（[STT worker](stt-workers.md)）；建表与翻译的内部（[专名一致性](name-consistency.md)、[翻译子系统](translation-subsystem.md)）；日志格式、进程原语与 worker 启动（[运行日志与进程原语](run-logging-and-processes.md)）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**入口**：`python -m kototoki [kototoki.toml]`（默认 `./kototoki.toml`）读配置，再做两项检查，然后调用 `job.run(config) -> Summary`：

- `check_input_dir`：`input_dir` 必须是已存在的目录（否则扫描到 0 个文件也以退出码 0 结束）；双语字幕写在源文件旁，因此也拒绝位于仓库内（`.local/` 除外）的输入目录。
- `check_work_dir`：拒绝工作目录位于仓库内（`.local/` 除外）或位于输入目录内（含相同）。

退出码：

- 0 全部成功；1 有文件失败（其余照常发布）；2 配置、输入目录或工作目录不可用；3 同一目标目录已有编排器在运行（`WorkLocked`，`EXIT_WORK_LOCKED`）。
- 4 GPU 锁冲突（`GpuLocked`）：任何阶段——vad、asr、align、names、translate——需要 GPU 锁而撞上都以此结束整批，不写逐文件 `failure.json`；已完成的 CPU 产物保留，可续跑；同批的零条目文件也等到下一次运行再发布。
- 源文件旁已有字幕而跳过、仍在写入的文件不改变退出码，后者只告警。

**流程**（阶段 × 整批）：

1. 取工作根 `<work_dir>/<input_dir 末段名>-<sha12>/lock`（`procs.ProcessLock`，锁信息含 `input_dir`；`artifacts.work_root`），把编排器进程放进 KILL_ON_JOB_CLOSE Job Object（建不起来时释放工作根锁再抛出），写 `input.json`。此后的 ffmpeg、worker 与 Strata CLI 子进程自动加入 Job Object；Strata 服务本身由 `strata launch` 在后台启动，不在 Job Object 内，靠 `Session` 退出时的 `--stop` 收尾。
2. 扫描：递归列出扩展名（大小写不敏感，`[input] extensions`）匹配的文件，按相对路径排序；两次采样（间隔 `stable_check_s`）大小不变才处理，否则本次跳过。
   - 源文件旁已有 `<主名>.ja-zh.srt`（`final_srt_path`，只看文件名，不论来源）的文件记入 `Summary.existing` 并跳过，不登记工作目录、不 probe、不进任何阶段，也不动残留的 `failure.json`。
   - 否则登记 `<work root>/<id>`；`register_work_dir` 抛异常（`index.json` 损坏、短 id 碰撞）只记该文件 `scan` 失败，没有工作目录因而不写 `failure.json`，整批继续。
   - 同目录主名相同、扩展名不同的文件（如 `ep01.mkv` 与 `ep01.mp3`）争用同一份字幕路径，按相对路径顺序后出现的那个记 `scan` 失败（`FinalPathCollision`，写 `failure.json`）；Windows 下路径比较忽略大小写。
3. probe／extract：线程池（`extract_workers`）对每个文件跑 ffprobe（每次都跑，得到输入文件身份）。
   - `[input] use_embedded_subtitles` 开着且 `media.select_subtitle` 选出可用的日文文本字幕轨时先走"内嵌日文字幕"（见下）；采用后该文件不提取音频。
   - 否则（或字幕轨不可用时）`probe.json` 身份匹配且 `audio-16k.wav` 在时跳过 extract；不然先删除工作目录里上次强杀留下的 `.*.partial*` 与 `.*.tmp`（`clean_leftovers`），再 extract 并写 `probe.json`（probe payload 加 `extract` 记录，含 PCM SHA256）。
   - 每个成功的文件先把 `Probe.warnings` 与 `Extract.warnings`（跳过 extract 时取 `probe.json` 记下的）逐条记为 WARNING，再记补偿告警（`compensation_warnings`：`net_padding_s` 绝对值或 swr 报告的丢弃样本折算超过 `COMPENSATION_WARN_S = 0.1` s 时各一行，跳过 extract 时同样由 `probe.json` 算出），最后记 `done`。
   - Ctrl+C（任何 `BaseException`）时 `shutdown(cancel_futures=True)`：排队中的文件不再提取，只等正在跑的 ffmpeg 结束，然后沿 `finally` 释放两把锁。
4. 计划：CPU 阶段之后对每个文件调用一次 `plan.next_stage`，从 vad 起（采用内嵌字幕的文件从 names 起）逐阶段核对产物身份，得到第一个需要运行的阶段（`vad`／`asr`／`align`／`cues`／`names`／`translate`）或终态 `publish`（无语音）；没有 `done` 状态——是否已发布由扫描按源文件旁的字幕判定。
5. vad → asr → align：计划落在本阶段的文件组成一批，交给一个 worker 子进程；没有文件需要 GPU 时不取 GPU 锁。worker 结束后对每个文件 `plan.advance`：产物缺失或身份不符即记该阶段失败（`ArtifactMissing`），否则推进到下一个需要运行的阶段。
6. ja-cues（进程内，`build_ja_cues`）：`cues.build_cues(align, [cues] 规则)`，写 `ja.srt` 后写 `ja-cues.json`（payload 另记 `ja.srt` 的 SHA256 `ja_srt_sha256`，供阶段计划核对 `ja.srt` 的新鲜度），随后 `plan.advance`；三件套日志行见[日文 cue](japanese-cues.md#当前行为规格)。
7. 共享 Strata session：进入 names 之前建一个 `strata.Session(config, on_server_pid=写 GPU 锁)`，包住 names 与 translate 两个阶段；正常结束、出错或被中断都 `strata launch --stop` 并核实显存释放，之后才放 GPU 锁。Strata 在第一次真正请求模型时才启动，两阶段之间不停；两阶段都不需要模型时整批不启动。启动失败整批累计 `strata.MAX_START_FAILURES`（3）次或被拒绝（`StrataRefused`）后 session 不可用，此后两阶段需要模型的文件直接失败。
8. names（进程内，恒在链上，`names_batch`）：
   - 读每个文件的 `ja.srt`，读出错记该文件 `names` 阶段失败；只有某个文件有 cue 时才取 GPU 锁。
   - 有 cue 的文件把共享 session 传给 `names.build_document`（零条目文件传 `None`），随后由编排 `write_artifact(name-table.json, plan.identities["names"], payload)`。
   - `build.status` 不是 `ok`（`too_long`／`failed`，空表）记 WARNING，影片照常往下走；建表抛异常（传输失败、HTTP 错误、OOM、Strata 不可用等）只让该文件失败；随后 `plan.advance`。
   - 撞 GPU 锁（`GpuLocked`）不捕获，向上抛、整批退出码 4（此时共享 session 尚未启动 Strata）。
9. translate（进程内，`translate_batch`）：
   - 每文件的 `TranslatePlan` 已在计划里（`plan.translate`）；只有任一文件 `needs_model` 时才取 GPU 锁（names 已取时沿用）。
   - 需要模型的文件把共享 session 传给 `translate_document(plan, session)`；不需要模型的文件（零条目、或 run 已完成而只是源文件旁的字幕被删）传 `None`。
   - 撞 GPU 锁同 names；Strata 被拒绝（已有别的 launch、身份不符、专家区退到 mmap）时共享 session 置为不可用（可能已在 names 阶段置位），其余需要模型的文件直接失败；单文件异常记该文件失败并继续。
10. 发布（`publish`）：`ja-zh.srt` 文本是翻译结果与 `ja.srt` 按 cue 合并（`merge.merge`，没有专名替换；零 cue 为空文本）。
    - 先查源文件旁是否已出现同名字幕（运行期间由用户或别的工具写入）：有则不覆盖，记入 `existing` 并告警。
    - 否则写副本到 `<work root>/<id>/publish/`（保留）→ `write_srt` 原子写到源文件旁（临时文件在目标目录内，不跨卷）→ 成功后 `record_published`（审计）→ 删除该文件的 `failure.json`。
    - `ja.srt` 留在工作目录，不发布 `zh.srt`。发布日志行在有未翻译 cue（字幕里只有日文一行）时追加 `, N untranslated cue(s)`。
    - 收尾不变量：未失败的文件此时必须已在 `published`、`existing` 或 `no_speech` 里，否则记 `publish` 失败（`NotPublished`）。

**内嵌日文字幕**（`job.use_embedded_subtitle`，在 probe／extract 的线程池里；选轨、抽取与清洗规则见[配置、配方与媒体提取](config-and-media.md)）：

- 跳过：由[阶段计划](stage-plan.md)判定内嵌记录是否当前（`plan.embedded_current`：身份等于 `plan.embedded_identity(probe 身份, 流索引)`，且记下的 `ja_srt_sha256` 等于工作目录里 `ja.srt` 的 SHA256），当前即不再抽取。
- 否则 `media.extract_subtitle` → `embedded.clean`；先删上次强杀留下的临时文件，再写 `ja.srt`，最后写 `ja-embedded.json`（流信息、清洗计数、`ja.srt` 的 SHA256）。
- 不删 `ja-cues.json`：字幕轨改写 `ja.srt` 后它不再当前，以后改走 STT 时 cues 阶段自然重建；反过来，cue 阶段改写 `ja.srt` 后内嵌记录不再相符，下次走内嵌路径时重新抽取。
- `probe.json` 不当前时写出，`extract` 为 null；以后该文件改走 STT 时照常提取并改写。
- 采用后 `VideoFile.embedded` 记该身份，计划从 names 起；日志行为 `[extract] done <相对路径>: embedded subtitle stream N (<codec>), M cue(s), skipping speech recognition`，只把选轨告警记为 WARNING，音轨告警不记。发布行加 ` (embedded subtitles)`，`Summary.embedded` 列出这些文件，汇总行给出个数。
- 不可用（抽取失败，或清洗后零条目）：不写任何内嵌产物，记 WARNING `[extract] <相对路径>: Embedded subtitle stream N is unusable (<原因>); falling back to speech recognition`，该文件照常提取音频走 STT；不算失败、不缓存，下次运行再试。
- 字幕文字不进日志。整批都是这类文件时没有 GPU worker，GPU 锁到 names 需要模型时才取。

**计划与身份**：续跑与跳过的唯一判据是[阶段计划](stage-plan.md)给出的 `Plan`（`stage`、各阶段期望身份、`no_speech`、`TranslatePlan`）；编排对每文件调用一次 `next_stage`，每跑完一个阶段调用一次 `advance`，不自己拼身份。

- 模型文件 SHA256 由 `model_sha_lookup` 经 `gpu.verify_models`（`plan.model_files` 给出期望值，size+mtime 缓存与 worker 共用）按阶段每次运行最多核对一次；失败结果同样缓存，模型缺失或不符时需要该阶段核对的文件记失败。
- `published.json`（审计记录）的 `sources` 即 `Plan.sources`（全部身份与 `no_speech`，含 `names`），另记 `translate_untranslated_cues`，不参与任何判定。
- 用户手改 `name-table.json` 的 `entries`：改到会被注入的条目（`high` 的实体或其写法）即改变翻译身份的 `names_sha256`，但已发布的字幕不会自动重做——须先删掉该 `.ja-zh.srt`，再运行才重译（需要 Strata）；只改 medium／low 条目不触发任何重做。

**GPU worker 调度、崩溃与重启**：GPU 阶段每批启动一个 worker 子进程（`run_gpu_stage`），按文件隔离崩溃并为其后文件重启；命令、jobs、子进程环境与崩溃判定见[运行日志与进程原语](run-logging-and-processes.md#worker-子进程)。失败文件退出后续阶段，批次继续。

**无语音**：`vad.json` 的 `chunks` 为空列表时跳过 asr／align／ja-cues／names／翻译，直接发布零条目 `ja-zh.srt`。

**近乎无声**（batch-run-fixes 04）：asr 前 `speech_gate` 查 `vad.json` 的 `accounting.speech_samples`，不足参照时长 1%（`MIN_SPEECH_RATIO`）记 `vad` 失败。

**锁**（原语见[运行日志与进程原语](run-logging-and-processes.md#进程原语)）：

- GPU 锁是 `config.gpu_lock`（仓库内 `.local/gpu.lock`），第一个需要 GPU 的阶段前获取，持有到翻译结束；names 阶段只在有文件的 `ja.srt` 有 cue 时才取，翻译阶段只在有文件 `needs_model` 时才取（全部 run 已完成或零条目时整批不占 GPU）。
- 锁文件记录编排器 pid 与创建时间，以及运行中的 worker 与 Strata 服务的 pid。
- 两把锁都是持有者存活即拒绝、残留锁默认拒绝，`KOTOTOKI_BREAK_STALE_LOCK=1` 时移除残留锁；GPU 锁取不到时抛 `GpuLocked`、整批退出码 4（见入口）。

**`failure.json` 清理**：该文件本次成功发布后、以及发布期发现源文件旁已有同名字幕而按已存在跳过时删除；重跑时不看 `failure.json`，只按产物身份决定从哪个阶段继续，新的失败覆盖旧记录。

### 运行日志

编排持有运行日志的目的地（`<work root>/run-<UTC戳>.log`、控制台、`run-<戳>-<stage>.stderr.log`）；挂接、行格式、级别与内容规则见[运行日志与进程原语](run-logging-and-processes.md#运行日志)。

## 接口与依赖

导入基础层的 `artifacts`、`config`、`srt`、`logs`、`procs`（`ProcessLock`、`LockError`、`contain_children`）、`workers.protocol`（jobs 读写与 `classify_launch`），以及 `media`、`cues`、`embedded`、[阶段计划](stage-plan.md)的 `plan` 与 `workers.gpu`（只用 `verify_models`，导入时不加载推理库），不导入 worker 壳。

以普通导入使用四个子系统（都不导入 `plan`、`job`，不加载 torch，测试以属性 patch 替换，如 `mock.patch("kototoki.translate.translate_document")`）：

- `kototoki.strata`：共享 session，`Session(config, on_server_pid=...)` 上下文管理器。
- `kototoki.names`：`build_document(work_dir, document, session | None, seed)` 返回带 `payload`／`status`／`attempts`／`seconds` 的结果；names 身份由阶段计划算。
- `kototoki.translate`：`translate_document(plan, session | None, *, relative)` 返回带 `translations`（cue id → 译文，不出中文为 `None`）与 `untranslated_count` 的结果；`TranslatePlan` 由阶段计划经 `translate.plan` 取得。
- `kototoki.merge`：`merge(ja_document, translations) -> srt_text`。

不导入任何推理模块与研究代码：`import kototoki.job`／`kototoki.__main__` 之后 `sys.modules` 中没有 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`。不做任何时间换算。

## 代码与验证入口

- 代码：`kototoki/__main__.py`（`main`、`check_input_dir`、`check_work_dir`）、`kototoki/job.py`（`run`、`Summary`、`model_sha_lookup`、`compensation_warnings`、`clean_leftovers`、`probe_and_extract`、`use_embedded_subtitle`、`speech_gate`、`advance_or_fail`、`build_ja_cues`、`cues_batch`、`names_batch`、`translate_batch`、`publish`、`FinalPathCollision`、`NotPublished`）。`kototoki/logs.py`、`kototoki/procs.py`、`kototoki/workers/protocol.py` 与 worker 启动见[运行日志与进程原语](run-logging-and-processes.md)。
- 测试（core，`just test`）：
  - `tests/core/test_job.py` 以伪 worker 脚本 `tests/fake_worker.py`（经 `plan` 取身份）、属性 patch 的专名、翻译与 Strata 函数（`merge` 用真的）、打桩的 `media.probe`／`extract` 与 `cues.build_cues` 覆盖：扫描与跳过、字幕路径碰撞、`register_work_dir` 异常、大小采样稳定性、发布期不覆盖同名字幕、跨卷发布、发布失败不写审计记录、残留 `failure.json`、阶段顺序、extract 期间中断、临时文件清理、续跑、两把锁的冲突退出码、收尾不变量、无语音与近乎无声、子进程环境、禁止导入清单、输入与工作目录检查、按需取锁、共享 Strata session 的启动次数与 stop、`StrataRefused`、`next_stage`／`advance` 调用次数。
  - 同文件的 `NamesTests`（见[专名一致性](name-consistency.md#代码与验证入口)）、`EmbeddedSubtitleTests`（采用后不提取音频、不起 worker、`sources` 与日志行、字幕文字不进日志、GPU 锁到 names 才取、开关关掉走 STT、抽取失败与零条目回退、续跑跳过与 `ja.srt` 被改写后重抽、两条路径来回切换）；`RunLogTests`、`IsolationTests` 的 worker 部分见[运行日志与进程原语](run-logging-and-processes.md#代码与验证入口)。
- 测试（full，`just test-full`）：`tests/full/test_job_ffmpeg.py` 沿用 `JobCase` 的接缝（`FAKE_MEDIA = False`），媒体阶段用 ffmpeg 合成的短视频走真实 `media.probe`／`extract`，GPU 阶段、cue、专名与翻译仍是假实现：检查派生 WAV 规格、三个 GPU 阶段各启动一次、共享 Strata session 在 names 阶段启动、`name-table.json` 落盘、双语字幕与 `published.json`（`sources` 含 `names`）；音轨标 `eng` 的视频照常发布、恰有一行选轨 WARNING；三个内嵌字幕用例（SubRip／ASS／mov_text）。不经 `python -m kototoki`、不起 Strata（打桩）。
- 未验证：被中断时 Strata 停止与显存核实的真实路径；names 阶段 x0 输出、其他作品与失败路径的真实运行；路径碰撞、中断取消提取、临时文件清理、空锁破除、补偿告警只经离线测试；内嵌字幕路径只用伪媒体与合成片段测过。

## 变更与决策来源

- [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0014](../../adr/0014-name-consistency-in-product.md)、[ADR-0019](../../adr/0019-product-translation-q2.md)、[ADR-0020](../../adr/0020-media-inputs-work-dir-and-side-by-side-publish.md)、[ADR-0022](../../adr/0022-product-names-on-strata.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- 归档 tag 中的计划 `archive/2026-11-18-pre-research-restructure:docs/plans/` 下 product-names-on-strata（§7 共用 session 的真实运行）、architecture-cleanup；技术设计历史记录 docs/research/2026-11-11-bilingual-pipeline-spec-history.md
- 验收：[两部整片](../../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)、[最终验收](../../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)、[专名一致性进产品](../../../research/acceptance/2026-10-20-name-consistency-product.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/issues/（06、14、15）；.scratch/runtime-logging/、.scratch/runtime-logging-gaps/；`.scratch/architecture-review/issues/01-small-fixes.md`；.scratch/name-consistency-product/issues/06-orchestration.md；.scratch/q2-product-switch/；.scratch/q3-product-switch/；.scratch/architecture-cleanup/
