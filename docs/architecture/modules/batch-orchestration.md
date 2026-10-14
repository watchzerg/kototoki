# 批次编排

状态：current（票据 06 交付，2026-10-14）；GPU worker（票据 03／07）、翻译子系统与合并（票据 05／09）尚未实现，编排按[目标架构](../bilingual-pipeline-architecture.md)的接口调用它们，只经伪 worker 与伪翻译模块离线验证。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §3、§4、§6、§7.1，[目标架构](../bilingual-pipeline-architecture.md)"编排"行）的唯一入口与全部流程知识：扫描输入、调度 CPU 与 GPU 阶段、CPU 阶段产物的身份与写入、GPU 阶段产物的期望身份、续跑与失败隔离、两把锁、Job Object、子进程环境、三份 SRT 一起发布与运行日志。不负责：产物身份与覆盖规则本身（[产物契约](artifact-contract.md)）、音轨与 WAV（[配置、配方与媒体提取](config-and-media.md)）、cue 切分（[日文 cue](japanese-cues.md)）、推理（票据 03／07）、翻译与合并的内部（票据 05／09）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**入口**：`python -m kototoki [kototoki.toml]`（默认 `./kototoki.toml`）读配置，`check_output_dir` 拒绝输出目录位于仓库内（`.local/` 除外）或位于输入目录内（含相同），再调用 `job.run(config) -> Summary`。退出码：0 全部成功；1 有文件失败（其余照常发布）；2 配置或输出目录不可用；3 输出目录锁冲突（`OutputLocked`）；4 GPU 锁冲突（`GpuLocked`，已完成的 CPU 产物保留，可续跑）。被用户改动而拒绝覆盖、仍在写入的文件只告警，不改变退出码。

**流程**（阶段 × 整批）：

1. 取 `<output_dir>/.work/lock`（`ProcessLock`）；把编排器进程放进 KILL_ON_JOB_CLOSE Job Object，此后的 ffmpeg、worker 与 llama-server 自动加入，编排器以任何方式退出时随之结束。
2. 扫描：递归列出扩展名（大小写不敏感）匹配的文件，按相对路径排序；两次采样（间隔 `stable_check_s`）大小不变才处理，否则本次跳过；登记 `.work/<id>`；`publish_blockers` 判定最终文件被用户改动且 `force = false` 的文件告警跳过，不 probe、不进 GPU 阶段。
3. probe／extract：线程池（`extract_workers`）对每个文件跑 ffprobe（每次都跑，得到视频身份）；`probe.json` 身份匹配且 `audio-16k.wav` 在时跳过 extract，否则 extract 后写 `probe.json`（probe payload 加 `extract` 记录，含 PCM SHA256）。
4. vad → asr → align：每个阶段开始前对每个文件从 vad 起重算期望身份（`next_stage`），需要本阶段的文件组成一批，交给一个 worker 子进程；没有文件需要 GPU 时不取 GPU 锁。
5. ja-cues（进程内）：`cues.build_cues(align, [cues] 规则)`，写 `ja.srt` 后写 `ja-cues.json`。
6. translate（进程内）：整批一个 `translate.Session`；`ja.srt` 零条目的文件不请求模型；单文件异常记该文件失败并继续。
7. 发布：三份文本写到 `.work/<id>/publish/`，再次 `publish_blockers` 放行 → `record_published` → 逐个移动到最终位置（`replace_with_retry`，带 `PermissionError` 重试）→ 删除该文件的 `failure.json`。

**期望身份**（`next_stage`，也是续跑与跳过的唯一判据）：

| 产物 | 身份 |
| --- | --- |
| `probe.json` | `video_identity`（相对路径、大小、`mtime_ns`、ffprobe 指纹）＋ `MEDIA` 配方 hash ＋ `audio_language` |
| `vad.json` | 上游 `audio_16k`（PCM SHA256）＋ `VAD` 配方 hash |
| `asr.json` | 上游 `audio_16k`、`vad`（文件 SHA256）＋ `W0`／`X0` 配方 hash |
| `align.json` | 上游 `audio_16k`、`asr` ＋ `MMS` 配方 hash |
| `ja-cues.json` | 上游 `align` ＋ `CUES` 配方 hash ＋ `[cues]` 规则 |
| 翻译 | `ja.srt` SHA256 ＋ `translate.RECIPE_HASH` ＋ seed |

身份暂不含模型文件 SHA256（期望值尚无归属，见"未验证"）。`published.json` 的 `sources` 记录上表全部身份与 `no_speech`（另记 `translate_fallback_cues`，不参与比较）；`sources` 与当前期望相同且三份最终文件 SHA 等于记录时该文件为"已是最新"，不再翻译与发布。

**GPU worker 调度**：命令 `sys.executable -m kototoki.workers.<stage> --jobs <.work/jobs-<stage>.json>`，`cwd` 为仓库根；jobs 的 `inputs` 为 vad `{wav}`、asr `{wav, vad}`、align `{wav, asr}`，`config` 为 `{"config_path": <配置文件>, "identities": {<id>: <该文件本阶段期望身份>}}`，worker 用给定身份写产物（`write_artifact`），不自行计算身份。子进程环境在当前环境上加 `PYTHONUTF8=1`、`HF_HUB_OFFLINE`／`TRANSFORMERS_OFFLINE`／`HF_DATASETS_OFFLINE`／`HF_HUB_DISABLE_TELEMETRY=1`、`PYANNOTE_METRICS_ENABLED=0`、`HF_HOME`＝`TORCH_HOME`＝`<output_dir>/.work/cache/`；stdout 逐行读进度 JSON 写入运行日志，stderr 追加到 `.work/run-<时间戳>-<stage>.stderr.log`。

**崩溃与重启**（按文件计）：

- 退出码 0／1：报告 `failed` 的文件记该阶段失败（`failure.json` 已由 worker 写出），其余按产物核对。
- 有 `startup_failed` 事件（模型加载失败，与文件无关）：本阶段剩余文件全部失败，不重启。
- 有 `fatal` 事件：该文件失败，从下一文件重启 worker。
- 其他异常退出：最后一个有事件的文件之后的第一个文件即正在处理的文件，编排写 `failure.json`（`WorkerCrashed`）并从其后文件重启。
- worker 结束后产物缺失或身份不符的文件记失败（`ArtifactMissing`）。失败文件退出后续阶段，批次继续。

**无语音**：`vad.json` 的 `chunks` 为空列表时跳过 asr／align／ja-cues／翻译，直接发布三份零条目 SRT。

**锁**：GPU 锁是 `config.gpu_lock`（仓库内 `.local/gpu.lock`），第一个需要 GPU 的阶段前获取，持有到翻译结束；锁文件记录编排器 pid 与创建时间，worker 运行期间记 `worker_pid`／`worker_stage`（`Popen.pid`；用 venv 的 `python.exe` 启动时这是启动器进程，真正的 worker 是它的子进程），翻译期间记 `server_pid`（由 `Session` 的 `on_server_pid` 回调提供）。持有者存活即拒绝，残留锁默认拒绝，`KOTOTOKI_BREAK_STALE_LOCK=1` 时移除残留锁（对输出目录锁同样适用）；从不抢占存活的持有者。

**`failure.json` 清理**：该文件本次成功发布后删除；重跑时不看 `failure.json`，只按产物身份决定从哪个阶段继续，新的失败覆盖旧记录。

**日志**：控制台与 `.work/run-<UTC 时间戳>.log` 只写阶段起止、逐文件状态（相对路径）、计数与耗时，不写转写与译文。

## 接口与依赖

导入 `artifacts`、`config`、`recipes`、`srt`、`workers.protocol`、`media`、`cues`；翻译子系统与合并在用到时以 `importlib` 导入 `kototoki.translate`（`RECIPE_HASH`、`Session(config, on_server_pid=...)` 上下文管理器、`translate_document(document, run_dir, session, config)` 返回带 `translations`（cue id → 译文）与 `fallback_count` 的结果）与 `kototoki.merge`（`merge(ja_document, translations) -> srt_text`），二者由票据 05／09 实现。不导入任何推理模块与 `experiments.*`：`import kototoki.job`／`kototoki.__main__` 之后 `sys.modules` 中没有 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec`。不做任何时间换算。

## 代码与验证入口

- 代码：`kototoki/__main__.py`（`main`、`check_output_dir`）、`kototoki/job.py`（`run`、`Summary`、`next_stage`、`run_gpu_stage`、`ProcessLock`、`contain_children`）。锁、进程身份与 Job Object 复制自 `experiments/translation_v3/procs.py`（未导入）。
- 测试（core，`just test`）：`tests/test_job.py` 以伪 worker 脚本 `tests/fake_worker.py`、伪翻译与合并模块、打桩的 `media.probe`／`extract` 与 `cues.build_cues` 覆盖扫描与镜像、大小采样稳定性、发布前置判定与 `force`、阶段顺序、崩溃文件隔离与按文件重启、失败隔离、中断后续跑、输出目录锁与 GPU 锁冲突退出码、无语音路径、一起发布、子进程环境、禁止导入清单与输出目录位置检查。
- 未验证：真实 worker、llama-server 与 ffmpeg 下的整批运行（票据 08）；Job Object 在编排器被强杀时结束子进程（只在 Windows 上由系统保证，未自动测试）；产物身份中的模型文件 SHA256（期望值归属待定，票据 03 起接入）；`kototoki.translate`／`kototoki.merge` 的真实接口与本页假设一致（票据 05）。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/06-batch-orchestration.md`；规格 §3、§4、§6、§7.1 与 §1.2 第三轮裁定表；[目标架构](../bilingual-pipeline-architecture.md)。
