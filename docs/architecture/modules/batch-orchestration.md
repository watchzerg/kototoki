# 批次编排

状态：current（票据 06 交付，2026-10-14）；GPU worker 按 [STT worker](stt-workers.md)（票据 03、07）的 jobs 约定调用，翻译与合并见[翻译子系统与合并](translation-subsystem.md)（票据 05、09）。离线由伪 worker 与伪翻译模块测试；真实 worker、ffmpeg 与 llama-server 下的两部整片 × w0／x0 整批运行，以及翻译失败后重跑时 STT 产物按身份全部跳过的续跑，已在[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)中通过。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3、§4、§6、§7.1，[模块边界](../module-boundaries.md#产品包的责任边界)）的唯一入口与全部流程知识：扫描输入、调度 CPU 与 GPU 阶段、CPU 阶段产物的写入、续跑与失败隔离、两把锁、Job Object、子进程环境、三份 SRT 一起发布与运行日志；以及阶段计划模块 `kototoki/plan.py`——阶段链、各阶段的产物与输入、模型文件清单、期望身份与"下一个要跑的阶段"的唯一归属（编排与 worker 壳都从它取身份）。不负责：身份的组成规则、匹配与覆盖规则本身（[产物契约](artifact-contract.md)）、音轨与 WAV（[配置、配方与媒体提取](config-and-media.md)）、cue 切分（[日文 cue](japanese-cues.md)）、推理（票据 03／07）、翻译与合并的内部（票据 05／09）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**入口**：`python -m kototoki [kototoki.toml]`（默认 `./kototoki.toml`）读配置，`check_output_dir` 拒绝输出目录位于仓库内（`.local/` 除外）或位于输入目录内（含相同），再调用 `job.run(config) -> Summary`。退出码：0 全部成功；1 有文件失败（其余照常发布）；2 配置或输出目录不可用；3 输出目录锁冲突（`OutputLocked`）；4 GPU 锁冲突（`GpuLocked`，已完成的 CPU 产物保留，可续跑）。被用户改动而拒绝覆盖、仍在写入的文件只告警，不改变退出码。

**流程**（阶段 × 整批）：

1. 取 `<output_dir>/.work/lock`（`ProcessLock`）；把编排器进程放进 KILL_ON_JOB_CLOSE Job Object，此后的 ffmpeg、worker 与 llama-server 自动加入，编排器以任何方式退出时随之结束。
2. 扫描：递归列出扩展名（大小写不敏感）匹配的文件，按相对路径排序；两次采样（间隔 `stable_check_s`）大小不变才处理，否则本次跳过；登记 `.work/<id>`；`publish_blockers` 判定最终文件被用户改动且 `force = false` 的文件告警跳过，不 probe、不进 GPU 阶段。
3. probe／extract：线程池（`extract_workers`）对每个文件跑 ffprobe（每次都跑，得到视频身份）；`probe.json` 身份匹配且 `audio-16k.wav` 在时跳过 extract，否则 extract 后写 `probe.json`（probe payload 加 `extract` 记录，含 PCM SHA256）。
4. 计划：CPU 阶段之后对每个文件调用一次 `plan.next_stage`，从 vad 起逐阶段核对产物身份，得到第一个需要运行的阶段（`vad`／`asr`／`align`／`cues`／`translate`）或终态（`publish`：无语音；`done`：已是最新）。
5. vad → asr → align：计划落在本阶段的文件组成一批，交给一个 worker 子进程；没有文件需要 GPU 时不取 GPU 锁。worker 结束后对每个文件 `plan.advance`，从刚跑完的阶段继续核对：产物缺失或身份不符即记该阶段失败（`ArtifactMissing`），否则计划推进到下一个需要运行的阶段。
6. ja-cues（进程内）：`cues.build_cues(align, [cues] 规则)`，写 `ja.srt` 后写 `ja-cues.json`，随后 `plan.advance`。
7. translate（进程内）：整批一个 `translate.Session`；`ja.srt` 零条目的文件不请求模型；单文件异常记该文件失败并继续。
8. 发布：三份文本写到 `.work/<id>/publish/`，再次 `publish_blockers` 放行 → `record_published` → 逐个移动到最终位置（`replace_with_retry`，带 `PermissionError` 重试）→ 删除该文件的 `failure.json`。

**阶段计划与期望身份**（`kototoki/plan.py`，续跑与跳过的唯一判据）：

| 产物 | 身份（`plan` 的函数） |
| --- | --- |
| `probe.json` | `probe_identity`：`video_identity`（相对路径、大小、`mtime_ns`、ffprobe 指纹）＋ `MEDIA` 配方 hash ＋ `audio_language` |
| `vad.json`／`asr.json`／`align.json` | `vad_identity`／`asr_identity`／`align_identity`：上游 PCM 与上游产物 SHA256、配方 hash（`recipe_hash(stage, engine)`）、模型文件 SHA256；worker 壳写进产物的是同一个函数的结果，见 [STT worker](stt-workers.md) |
| `ja-cues.json` | `cues_identity`：上游 `align.json` ＋ `CUES` 配方 hash ＋ `[cues]` 规则 |
| 翻译 | `translate_identity`：`ja.srt` SHA256 ＋ `translate.RECIPE_HASH` ＋ seed（翻译子系统用到时才导入） |

`Plan` 是不可变值：`stage`、`identities`（`probe` 与从 vad 起到 `stage` 为止各阶段的期望身份，键同 `published.json` 的 `sources`）、`no_speech`，以及发布记录用的 `sources`。`next_stage(target, config, models)` 从 vad 起逐阶段调用 `artifacts.is_current`，第一个不当前的阶段即结果；`vad.json` 的 `chunks` 为空即无语音，跳到发布判定；全部当前时对照 `published.json`：`sources` 与期望相同且三份最终文件 SHA 等于记录即 `done`，否则 `translate`（无语音时 `publish`）。`advance(previous, …)` 从 `previous.stage` 继续同一核对，不改写入参；对同一目录连续调用结果相同。核对途中出错抛 `PlanError`（带正在核对的阶段，编排记为该阶段失败）；损坏的产物不是错误，只是"不当前"。阶段表 `STAGE_INPUTS`／`STAGE_OUTPUT`、`worker_models`、`model_files(stage, engine, models)` 供编排写 jobs 文件、壳核对模型。

模型文件 SHA256 由编排的 `model_sha_lookup` 经 `gpu.verify_models`（`plan.model_files` 给出期望值，size+mtime 缓存与 worker 共用 `.work/cache/model-verification.json`）按阶段每次运行最多核对一次；模型缺失或不符时需要该阶段核对的文件记失败。`published.json` 的 `sources` 记录上表全部身份与 `no_speech`（另记 `translate_fallback_cues`，不参与比较）。

**GPU worker 调度**：命令 `sys.executable -m kototoki.workers.<stage> --jobs <.work/jobs-<stage>.json>`，`cwd` 为仓库根；jobs 按 [STT worker](stt-workers.md) 的约定：`recipe_hash` 为 `plan.recipe_hash(stage, engine)`，`config` 为 `{"engine", "models": plan.worker_models(config), "model_cache"}`，`inputs` 按 `plan.STAGE_INPUTS`（vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`）；worker 用 `plan` 的身份函数写入身份，编排用同一函数核对。子进程环境在当前环境上加 `PYTHONUTF8=1`、`HF_HUB_OFFLINE`／`TRANSFORMERS_OFFLINE`／`HF_DATASETS_OFFLINE`／`HF_HUB_DISABLE_TELEMETRY=1`、`PYANNOTE_METRICS_ENABLED=0`、`HF_HOME`＝`TORCH_HOME`＝`<output_dir>/.work/cache/`；stdout 逐行读进度 JSON 写入运行日志，stderr 追加到 `.work/run-<时间戳>-<stage>.stderr.log`。

**崩溃与重启**（按文件计）：

- 退出码 0／1：报告 `failed` 的文件记该阶段失败（`failure.json` 已由 worker 写出），其余按产物核对。
- 有 `startup_failed` 事件（模型加载失败，与文件无关）：本阶段剩余文件全部失败，不重启。
- 有 `fatal` 事件：该文件失败，从下一文件重启 worker。
- 其他异常退出：最后一个有事件的文件之后的第一个文件即正在处理的文件，编排写 `failure.json`（`WorkerCrashed`）并从其后文件重启。
- worker 结束后 `plan.advance` 仍停在本阶段的文件（产物缺失或身份不符）记失败（`ArtifactMissing`）。失败文件退出后续阶段，批次继续。

**无语音**：`vad.json` 的 `chunks` 为空列表时跳过 asr／align／ja-cues／翻译，直接发布三份零条目 SRT。

**锁**：GPU 锁是 `config.gpu_lock`（仓库内 `.local/gpu.lock`），第一个需要 GPU 的阶段前获取，持有到翻译结束；锁文件记录编排器 pid 与创建时间，worker 运行期间记 `worker_pid`／`worker_stage`（`Popen.pid`；用 venv 的 `python.exe` 启动时这是启动器进程，真正的 worker 是它的子进程），翻译期间记 `server_pid`（由 `Session` 的 `on_server_pid` 回调提供）。持有者存活即拒绝，残留锁默认拒绝，`KOTOTOKI_BREAK_STALE_LOCK=1` 时移除残留锁（对输出目录锁同样适用）；从不抢占存活的持有者。

**`failure.json` 清理**：该文件本次成功发布后删除；重跑时不看 `failure.json`，只按产物身份决定从哪个阶段继续，新的失败覆盖旧记录。

**日志**：控制台与 `.work/run-<UTC 时间戳>.log` 只写阶段起止、逐文件状态（相对路径）、计数与耗时，不写转写与译文。

## 接口与依赖

导入 `artifacts`、`config`、`srt`、`workers.protocol`、`media`、`cues`、`plan` 与 `workers.gpu`（只用 `verify_models`，导入时不加载推理库），不再导入 worker 壳；翻译子系统与合并在用到时以 `importlib` 导入 `kototoki.translate`（`RECIPE_HASH`、`Session(config, on_server_pid=...)` 上下文管理器、`translate_document(document, run_dir, session, config)` 返回带 `translations`（cue id → 译文）与 `fallback_count` 的结果）与 `kototoki.merge`（`merge(ja_document, translations) -> srt_text`），二者由票据 05／09 实现。不导入任何推理模块与 `experiments.*`：`import kototoki.job`／`kototoki.__main__` 之后 `sys.modules` 中没有 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`。不做任何时间换算。

## 代码与验证入口

- 代码：`kototoki/__main__.py`（`main`、`check_output_dir`）、`kototoki/job.py`（`run`、`Summary`、`model_sha_lookup`、`run_gpu_stage`、`advance`、`ProcessLock`、`contain_children`）、`kototoki/plan.py`（`Target`、`Plan`、`next_stage`、`advance`、`PlanError`、各阶段身份函数、`STAGE_INPUTS`／`STAGE_OUTPUT`、`model_files`、`recipe_hash`、`worker_models`）。锁、进程身份与 Job Object 复制自 `experiments/translation_v3/procs.py`（未导入）。
- 测试（core，`just test`）：`tests/test_job.py` 以伪 worker 脚本 `tests/fake_worker.py`、伪翻译与合并模块、打桩的 `media.probe`／`extract` 与 `cues.build_cues` 覆盖扫描与镜像、大小采样稳定性、发布前置判定与 `force`、阶段顺序、崩溃文件隔离与按文件重启、失败隔离、中断后续跑、输出目录锁与 GPU 锁冲突退出码、无语音路径、一起发布、子进程环境、禁止导入清单与输出目录位置检查，以及一次整批运行中每文件 `plan.next_stage` 恰一次、每个跑过的阶段 `plan.advance` 恰一次；伪 worker 与真 worker 一样从 WAV 算 PCM SHA256 并经 `plan` 取身份。`tests/test_plan.py` 直接测计划模块：阶段链逐级推进、cues 阶段同时要求 `ja-cues.json` 与 `ja.srt`、无语音直达 `publish` 再 `done`、最终文件改动或身份改变即重新发布、`advance` 停在未写出产物的阶段、连续调用结果相同且不改写入参、`PlanError` 标明阶段、损坏产物视为不当前。
- 真实运行：[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)（Heaven's Feel II／III 各以 w0、x0 整批运行，12 份 SRT 齐全；首轮翻译因空闲显存低于启动阈值失败，重跑时 STT 按产物身份全部跳过、只做翻译与发布）。
- 真实失败路径：[最终验收](../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)——asr 阶段强杀编排器后 worker 随 Job Object 退出、残留锁默认拒绝（退出码 3）、`KOTOTOKI_BREAK_STALE_LOCK=1` 后从 vad 产物续跑；无语音视频、损坏文件隔离、子目录镜像、用户改动最终文件的拒绝与 `force` 覆盖、重跑逐字节一致均通过。
- 未验证：worker 退出码 2（CUDA 粘性错误）与按文件重启的真实路径。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/06-batch-orchestration.md`；规格 §3、§4、§6、§7.1 与 §1.2 第三轮裁定表。阶段计划模块来自票据 `14-stage-plan-module.md`（2026-10-15 架构评审候选 1）：此前阶段链、worker 输入名、模型键表与各阶段身份散在 job、三个 worker 壳与伪 worker 六处；收进 `plan.py` 后身份字段、键名与取值逐字节不变（四个整片工作目录的 vad／asr／align／translate 身份重算全等，新旧 `next_stage` 对拍一致）。

目标架构页（`docs/architecture/bilingual-pipeline-architecture.md`，2026-10-14 设计稿）已于票据 08 收口时删除：分层图与不变量并入[架构总览](../INDEX.md)，依赖方向、责任边界与接缝并入[模块边界](../module-boundaries.md)；本模块的接口以本页"接口与依赖"节为准。
