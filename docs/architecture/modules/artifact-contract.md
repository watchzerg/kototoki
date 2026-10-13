# 产物契约

状态：current（票据 00 交付，2026-10-14）；产品流水线其余阶段尚未实现，本页只描述已存在的共享基础。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)）各阶段共用的三件事：输出目录与工作目录布局、产物身份与跳过／替换、原子写；编排器与 GPU worker 之间的 `--jobs` 协议；SRT 读写。不负责：各阶段的推理与 payload 字段（票据 02–07）、批次编排与锁（票据 06）、翻译 run 目录内部格式（票据 05）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**布局**（`kototoki/artifacts.py`）：最终 SRT 镜像输入目录层级，`S1/ep01.mkv` → `<out>/S1/ep01.{ja,zh,ja-zh}.srt`（`final_srt_paths`）。每个视频的工作目录是 `<out>/.work/<id>/`，`<id>` 是输入目录内相对路径（含扩展名，统一正斜杠）UTF-8 的 SHA256 前 12 位（`work_id`）；`register_work_dir` 在 `.work/index.json` 登记 id ↔ 相对路径，同一 id 已登记为另一路径时报错（短 id 碰撞）。相对路径不得是绝对路径、含 `..` 或任何段含 `:`（盘符、NTFS 备用数据流）；`register_work_dir` 读改写 `index.json`，由编排器在扫描阶段串行调用。产物文件名是模块常量（`PROBE`、`AUDIO_16K`、`VAD`、`ASR`、`ALIGN`、`JA_CUES`、`PUBLISHED`、`FAILURE` 等）；翻译 run 目录为 `translate/srt-<ja.srt sha12>/`（`translate_run_dir`）。

**坐标约定**：`vad.json`、`asr.json`、`align.json` 的窗口、段、对齐记录为 WAV 本地秒／整数样本，顶层必须有有限数值 `offset_s`（产品恒为 0，`write_artifact` 对这三个文件名强制检查）；只有 `align.json` 的 `units[].start/end` 含 offset；`ja-cues.json` 与 SRT 的 cue 时间是最终 SRT 时间。

**身份**：JSON 产物顶层为 `{"identity": ..., **payload}`。

- 视频身份（`video_identity`）= 相对路径＋大小＋`mtime_ns`＋ffprobe 指纹；指纹只取流的 `index`／`codec_name`／`channels`／`channel_layout`／`sample_rate`／`start_time`／`duration` 与容器 `duration`，`filename` 与 `tags` 不参与。
- 派生身份（`derived_identity`）= 上游 SHA256（按名）＋配方 hash＋模型文件 SHA256（按名）＋影响输出的配置键；上游、配方、模型三处只接受 64 位小写十六进制摘要，因此绝对路径进不了这三处。
- `is_current(path, expected)`：文件存在、可解析、`identity` 与期望（经 JSON 规范化）完全相同才为真；损坏或不匹配即为假，调用方重算后用 `write_artifact` 原地原子替换。
- 模型文件 SHA256（`verify_model`）：首次完整计算并与期望比对，写入 `.work/cache/model-verification.json`（键为解析后的路径，记录 size 与 `mtime_ns`）；之后 size+mtime 不变即复用，不重算；不匹配报错且不入缓存。

**失败与发布**：

- `write_failure(work_dir, stage, error)` 写 `failure.json`：阶段、异常类型与消息、当时已存在的阶段产物，不含音频与转写内容。
- `record_published(work_dir, final_paths, sha256, sources, translate_dir)` 在 `publish_blockers` 放行后、移动三份最终 SRT **之前**写 `published.json`（三份 SHA256、来源产物身份、当前 `translate/srt-<sha12>` 目录），并把此刻最终位置上已有文件的 SHA 记为 `previous_sha256`。
- `publish_blockers(final_paths, work_dir, force=...)`：现有最终文件不存在、或 SHA256 等于当前或上一份记录，视为未改动；否则（含没有记录时已存在的文件）视为用户改动并列为阻止项。`force=True` 时恒为空。编排器在扫描阶段调用它（票据 06）。记录磁盘上的旧 SHA 是为了"写记录后、移动完成前崩溃"（包括连续多次）时，最终位置上残留的旧文件不被误判为用户改动；规格 §4 只要求对照记录的 SHA，`previous_sha256` 是实现为此补充的字段。

**原子写**：`atomic_write_text`／`atomic_write_json` 写同目录临时文件、fsync 后 `os.replace`（临时文件名带 pid 与线程 id）；Windows `PermissionError`（播放器或扫描器占用）重试 20 次、间隔递增至 0.5 s；失败时删除临时文件，目标保持原样。文本一律 UTF-8 无 BOM、LF。

**worker 协议**（`kototoki/workers/protocol.py`）：`--jobs <path>` 指向 `{"stage", "recipe_hash", "config", "files": [{"id", "work_dir", "inputs": {name: path}}]}`，键集合严格、id 唯一（`parse_jobs`／`read_jobs`／`write_jobs`）。`run_worker` 读 jobs、调用一次 `start(jobs)` 加载模型并得到逐文件处理函数；`run_jobs` 逐文件处理，结果由 worker 写进各自工作目录，每个文件结束在 stdout 打一行 UTF-8 JSON（`done`／`failed`／`fatal`／`startup_failed`，只含 id、状态与计数）。退出码：0 全部完成；1 有文件失败（该文件写 `failure.json`，继续下一文件）；2 启动失败或 `FatalWorkerError`（CUDA 粘性错误等，当前文件写 `failure.json` 后立即退出，编排器从下一文件重启）。

**失败窗口**（w0／x0 共用）：`fail_window(asr, chunk_index, reason)` 把 `original_segments[i].text` 移入 `failed_windows`（`chunk_index`、`reason`、截断文字）并置空；`retained_text` 是保留文本，后续对齐、cue 与翻译只用它；`validate_failed_windows` 要求列表存在、索引唯一有效且对应窗口已置空。

**SRT**（`kototoki/srt.py`）：解析与渲染复制自 `experiments/translation_flow/srt.py`，严格性不变（重复编号、坏时间行、非正时长、空文字行报错），但空白输入解析为零条目、零条目渲染为空串。`format_srt([(start_s, end_s, text), ...])` 从 1 编号写出；秒到毫秒用 `floor(x*1000+0.5)`（`milliseconds`），不用 `round`；取整后时长非正即报错。`write_srt` 原子写出、拒绝覆盖源文件；是否允许覆盖最终文件由 `publish_blockers` 判定。

## 接口与依赖

只依赖标准库；不导入 `experiments`、torch 或任何推理包，编排器可直接导入。worker 中 CUDA 粘性错误的识别与包装为 `FatalWorkerError` 由各 worker 负责（票据 03／07）。`.work/lock`、GPU 锁与 worker 子进程重启归编排器（票据 06）。

## 代码与验证入口

- 代码：`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`。
- 测试（core，`just test`）：`tests/test_artifacts.py`（短 id 与碰撞、身份匹配／失效与原地替换、`offset_s` 强制、模型哈希缓存命中／失效、覆盖规则四种组合与崩溃窗口、原子写重试与临时文件清理）、`tests/test_protocol.py`（jobs 解析、退出码 0／1／2、失败隔离、`failed_windows`）、`tests/test_srt.py`（空 SRT、取整边界、严格解析、UTF-8 无 BOM）。
- 未验证：`failure.json` 在该文件后续重跑成功后何时清理尚无规则（归编排器，票据 06）；真实 Windows 文件占用下的重试行为只用注入的 `replace` 模拟；worker 协议尚无真实 worker 使用者（票据 03 起）。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/00-foundation.md`；规格 §4、§6、§7.1、§1.2 第三轮裁定表。原子写取自 `experiments/translation_v3/common.py`，模型哈希缓存取自 `experiments/translation_v3/server.py::verify_model`。
