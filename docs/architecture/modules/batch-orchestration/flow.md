---
covers:
  - kototoki/__main__.py
  - kototoki/job.py
---
# 批次编排子页：主流程

`批次编排` 的子页：入口与退出码，以及 probe／extract、计划、各 GPU 与进程内阶段到发布的完整流程。

**入口**：`python -m kototoki [kototoki.toml]`（默认 `./kototoki.toml`）读配置，再做两项检查，然后调用 `job.run(config) -> Summary`：

- `check_input_dir`：`input_dir` 必须是已存在的目录（否则扫描到 0 个文件也以退出码 0 结束）；双语字幕写在源文件旁，因此也拒绝位于仓库内（`.local/` 除外）的输入目录。
- `check_work_dir`：拒绝工作目录位于仓库内（`.local/` 除外）或位于输入目录内（含相同）。

退出码：

- 0 全部成功；1 有文件失败（其余照常发布）；2 配置、输入目录或工作目录不可用；3 同一目标目录已有编排器在运行（`WorkLocked`，`EXIT_WORK_LOCKED`）。
- 4 GPU 锁冲突（`GpuLocked`）：任何阶段——vad、asr、align、names、translate——需要 GPU 锁而撞上都以此结束整批，不写逐文件 `failure.json`；已完成的 CPU 产物保留，可续跑；同批的零条目文件也等到下一次运行再发布。
- 源文件旁已有字幕而跳过、仍在写入的文件不改变退出码，后者只告警。

**流程**（阶段 × 整批）：

1. 取工作根 `<work_dir>/<input_dir 末段名>-<sha12>/lock`（`procs.ProcessLock`，锁信息含 `input_dir`；`artifacts.work_root`），写 `input.json`（失败时释放工作根锁再抛出）。此后的 ffmpeg、worker 与 Strata CLI 子进程都经 `procs.contained` 启动，编排器以任何方式退出都随之结束；Strata 服务本身由 `strata launch` 在后台启动，不受此约束，靠 `Session` 退出时的 `--stop` 收尾。
2. 扫描：递归列出扩展名（大小写不敏感，`[input] extensions`）匹配的文件，按相对路径排序；两次采样（间隔 `stable_check_s`）大小不变才处理，否则本次跳过。
   - 源文件旁已有 `<主名>.ja-zh.srt`（`final_srt_path`，只看文件名，不论来源）的文件记入 `Summary.existing` 并跳过，不登记工作目录、不 probe、不进任何阶段，也不动残留的 `failure.json`。
   - 否则登记 `<work root>/<id>`；`register_work_dir` 抛异常（`index.json` 损坏、短 id 碰撞）只记该文件 `scan` 失败，没有工作目录因而不写 `failure.json`，整批继续。
   - 同目录主名相同、扩展名不同的文件（如 `ep01.mkv` 与 `ep01.mp3`）争用同一份字幕路径，按相对路径顺序后出现的那个记 `scan` 失败（`FinalPathCollision`，写 `failure.json`）；路径比较区分大小写。
3. probe／extract：线程池（`extract_workers`）对每个文件跑 ffprobe（每次都跑，得到输入文件身份）。
   - `[input] use_embedded_subtitles` 开着且 `media.select_subtitle` 选出可用的日文文本字幕轨时先走"内嵌日文字幕"（见下）；采用后该文件不提取音频。
   - 否则（或字幕轨不可用时）`probe.json` 身份匹配且 `audio-16k.wav` 在时跳过 extract；不然先删除工作目录里上次强杀留下的 `.*.partial*` 与 `.*.tmp`（`clean_leftovers`），再 extract 并写 `probe.json`（probe payload 加 `extract` 记录，含 PCM SHA256）。
   - 每个成功的文件先把 `Probe.warnings` 与 `Extract.warnings`（跳过 extract 时取 `probe.json` 记下的）逐条记为 WARNING，再记补偿告警（`compensation_warnings`：`net_padding_s` 绝对值或 swr 报告的丢弃样本折算超过 `COMPENSATION_WARN_S = 0.1` s 时各一行，跳过 extract 时同样由 `probe.json` 算出），最后记 `done`。
   - Ctrl+C（任何 `BaseException`）时 `shutdown(cancel_futures=True)`：排队中的文件不再提取；正在跑的 ffmpeg 在前台进程组里同样收到 Ctrl+C 而退出，等它们结束后沿 `finally` 释放两把锁。
4. 计划：CPU 阶段之后对每个文件调用一次 `plan.next_stage`，从 vad 起（采用内嵌字幕的文件从 names 起）逐阶段核对产物身份，得到第一个需要运行的阶段（`vad`／`asr`／`align`／`cues`／`names`／`translate`）或终态 `publish`（无语音）；没有 `done` 状态——是否已发布由扫描按源文件旁的字幕判定。
5. vad → asr → align：计划落在本阶段的文件组成一批，交给一个 worker 子进程；没有文件需要 GPU 时不取 GPU 锁。worker 结束后对每个文件 `plan.advance`：产物缺失或身份不符即记该阶段失败（`ArtifactMissing`），否则推进到下一个需要运行的阶段。
6. ja-cues（进程内，`build_ja_cues`）：`cues.build_cues(align, [cues] 规则)`，写 `ja.srt` 后写 `ja-cues.json`（payload 另记 `ja.srt` 的 SHA256 `ja_srt_sha256`，供阶段计划核对 `ja.srt` 的新鲜度），随后 `plan.advance`；三件套日志行见[日文 cue](../japanese-cues.md#当前行为规格)。
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

## 代码与验证入口

- 代码：
  - `kototoki/__main__.py`（`main`、`check_input_dir`、`check_work_dir`）。
  - `kototoki/job.py`（`run`、`_run`（按序调用各 `_*_stage`）、`Summary`、`model_sha_lookup`、`compensation_warnings`、`clean_leftovers`、`probe_and_extract`、`use_embedded_subtitle`、`speech_gate`、`advance_or_fail`、`build_ja_cues`、`cues_batch`、`names_batch`、`translate_batch`、`publish`、`FinalPathCollision`、`NotPublished`）。
  - `kototoki/logs.py`、`kototoki/procs.py`、`kototoki/workers/protocol.py` 与 worker 启动见[运行日志与进程原语](../run-logging-and-processes.md)。
- 测试（core，`mise run test`）：
  - `tests/core/test_job.py` 以伪 worker 脚本 `tests/fake_worker.py`（经 `plan` 取身份）、属性 patch 的专名、翻译与 Strata 函数（`merge` 用真的）、打桩的 `media.probe`／`extract` 与 `cues.build_cues` 覆盖主路径：
    - `ScanTests`：扫描过滤与排序、字幕发布在源文件旁、同目录同名主干的后一文件失败、大小采样决定稳定性、源文件旁已有字幕则跳过。
    - `StageTests`／`IsolationTests`／`ResumeTests`：整批按阶段顺序再翻译、发布；崩溃文件隔离且 worker 为后续文件重启；无语音发布空字幕并跳过后续阶段；中断后续跑只补缺失阶段；字幕被删后不取 GPU 锁而重新发布。
    - `LockTests`：GPU 锁冲突时保留 CPU 阶段产物。`InvariantTests`：转写、译文与专名文字不进日志与 stderr 文件；禁止导入清单；输入与工作目录检查。
  - 同文件的 `NamesTests`（换表身份后在同一 session 上重译）、`EmbeddedSubtitleTests`（开关关掉走 STT、不可用字幕轨带 WARNING 回退）；它们的细节分别见[专名一致性](../name-consistency.md#代码与验证入口)与[内嵌字幕](../config-and-media/embedded-subtitles.md#代码与验证入口)。
  - 测试精简（2026-11-22）后不再有测试覆盖：
    - 扫描与发布：`register_work_dir` 异常与早失败释放工作根锁、`stable_files` 单元、续跑后全部跳过、发布期出现字幕不覆盖、发布不跨目录移动、发布失败不写审计记录、`published.json` 内容、工作根按输入目录键控。
    - 阶段与失败：子进程环境、`fatal`／启动失败／退出码 1 缺事件的重启规则、读 worker 输出时中断回收 worker、无人处理的文件在发布失败、模型核对按阶段缓存、extract 失败与期间中断、临时文件清理、翻译失败隔离、`next_stage`／`advance` 调用次数、`media` hash 变而 PCM 不变时下游仍当前。
    - 锁：工作根锁冲突、names／translate 阶段 GPU 锁冲突为进程级、残留锁与空锁的破除、锁内 pid 记录、用法与配置错误退出码 2。
    - Strata 与翻译：共享 session 只启动一次并在翻译后停止、`StrataRefused`、中断时停止并释放锁、零 cue 文档不取锁与 session、建表失败与坏表的处理；内嵌字幕：跳过 extract 与 GPU 阶段、纯内嵌批次只为 Strata 取锁、续跑复用、两条路径互不复用 `ja.srt`；`RunLogTests` 全部删除（见[运行日志与进程原语](../run-logging-and-processes.md#代码与验证入口)）。
- 未验证：被中断时 Strata 停止与显存核实的真实路径；names 阶段 x0 输出、其他作品与失败路径的真实运行；路径碰撞只经离线测试；中断取消提取、临时文件清理、空锁破除、补偿告警现无自动测试；内嵌字幕路径只用合成片段测过 SubRip 一种。
