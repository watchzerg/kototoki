# 产物契约

状态：current（票据 00 交付，2026-10-14；各阶段在票据 02–09 接入，整片验收见[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)）。2026-11-11 起按 [ADR-0025](../../adr/0025-product-package-boundaries.md) 所属计划 [`architecture-cleanup`](../../plans/architecture-cleanup.md) 先行写入本页接口（协议读侧 `classify_launch`、units 改为 WAV 本地秒、`ja-cues.json` 记 `ja_srt_sha256`、SRT 整数毫秒入口），代码随该计划的票据 02、03、08 落地，结果见计划 §7。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)）各阶段共用的三件事：工作目录布局与最终字幕路径、产物身份与跳过／替换、原子写；编排器与 GPU worker 之间的 `--jobs` 协议；SRT 读写。不负责：各阶段的推理与 payload 字段（票据 02–07）、批次编排与锁（票据 06）、翻译 run 目录内部格式（票据 05）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**布局**（`kototoki/artifacts.py`，ADR-0020）：最终产物只有写在源文件旁的双语字幕，`S1/ep01.mkv` → `<input_dir>/S1/ep01.ja-zh.srt`（`final_srt_path`，后缀常量 `FINAL_SUFFIX`）。工作目录在 `[paths] work_dir` 下：`cache/` 放 `HF_HOME`／`TORCH_HOME` 与 `model-verification.json`（`cache_dir`，各目标目录共用），每个目标目录一个工作根 `<work_dir>/<input_dir 末段名>-<绝对路径 sha12>/`（`input_key`／`work_root`；路径按平台大小写规则归一，盘符根的末段名记为 `root`），内含 `lock`、`input.json`（`record_input`，目标目录绝对路径，只供人查）、`index.json`。每个输入的工作目录是 `<work root>/<id>/`，`<id>` 是输入目录内相对路径（含扩展名，统一正斜杠）UTF-8 的 SHA256 前 12 位（`work_id`）；`register_work_dir(root, relative)` 在 `index.json` 登记 id ↔ 相对路径，同一 id 已登记为另一路径时报错（短 id 碰撞）。相对路径不得是绝对路径、含 `..` 或任何段含 `:`（盘符、NTFS 备用数据流）；`register_work_dir` 读改写 `index.json`，由编排器在扫描阶段串行调用。产物文件名是模块常量（`PROBE`、`AUDIO_16K`、`VAD`、`ASR`、`ALIGN`、`JA_CUES`、`NAME_TABLE`、`PUBLISHED`、`FAILURE` 等）；翻译 run 目录的键归翻译子系统（`translate.plan`，见[翻译子系统](translation-subsystem.md)），本模块不拼它。

**坐标约定**：`vad.json`、`asr.json`、`align.json` 的窗口、段、对齐记录为 WAV 本地秒／整数样本，顶层必须有有限数值 `offset_s`（产品恒为 0，`write_artifact` 对这三个文件名强制检查），`align.json` 的 `units[].start/end` 也是 WAV 本地秒、不含 offset（`offset_s` 字段保留）；offset 只由日文 cue 加一次，`ja-cues.json` 与 SRT 的 cue 时间是最终 SRT 时间。

**身份**：JSON 产物顶层为 `{"identity": ..., **payload}`。

- 输入文件身份（`video_identity`，视频与音频同用）= 相对路径＋大小＋`mtime_ns`＋ffprobe 指纹；指纹只取流的 `index`／`codec_name`／`channels`／`channel_layout`／`sample_rate`／`start_time`／`duration` 与容器 `duration`，`filename` 与 `tags` 不参与。
- 派生身份（`derived_identity`）= 上游 SHA256（按名）＋配方 hash＋模型文件 SHA256（按名）＋影响输出的配置键；上游、配方、模型三处只接受 64 位小写十六进制摘要，因此绝对路径进不了这三处。
- `is_current(path, expected)`：文件存在、可解析、`identity` 与期望（经 JSON 规范化）完全相同才为真；损坏或不匹配即为假，调用方重算后用 `write_artifact` 原地原子替换。
- 模型文件 SHA256（`verify_model`）：首次完整计算并与期望比对，写入 `<work_dir>/cache/model-verification.json`（键为解析后的路径，记录 size 与 `mtime_ns`）；之后 size+mtime 不变即复用，不重算；不匹配报错且不入缓存。

**失败与发布**：

- `write_failure(work_dir, stage, error)` 写 `failure.json`：阶段、异常类型与消息、当时已存在的阶段产物，不含音频与转写内容。
- `record_published(work_dir, final_path, sha256, sources, translate_dir)` 在移动双语字幕**之前**写 `published.json`（最终路径、`ja-zh` 的 SHA256、来源产物身份、当前翻译 run 目录 `translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>`，相对工作目录）。它只是审计记录，不参与任何判定。
- 是否需要发布只看源文件旁的 `<主名>.ja-zh.srt` 是否存在（只看文件名，编排在扫描阶段判定，ADR-0020）；没有 `publish_blockers`、`read_published` 与 `force`，要重做就删掉该字幕。

**原子写**：`atomic_write_text`／`atomic_write_json` 写同目录临时文件、fsync 后 `os.replace`（临时文件名带 pid 与线程 id）；Windows `PermissionError`（播放器或扫描器占用）重试 20 次、间隔递增至 0.5 s；失败时删除临时文件，目标保持原样。文本一律 UTF-8 无 BOM、LF。

**worker 协议**（`kototoki/workers/protocol.py`）：`--jobs <path>` 指向 `{"stage", "recipe_hash", "config", "files": [{"id", "work_dir", "inputs": {name: path}}]}`，键集合严格、id 唯一（`parse_jobs`／`read_jobs`／`write_jobs`）。`run_worker` 读 jobs、调用一次 `start(jobs)` 加载模型并得到逐文件处理函数；`run_jobs` 逐文件处理，结果由 worker 写进各自工作目录，每个文件结束在 stdout 打一行 UTF-8 JSON（`done`／`failed`／`fatal`／`startup_failed`，只含 id、状态与计数）。退出码：0 全部完成；1 有文件失败（该文件写 `failure.json`，继续下一文件）；2 启动失败（`startup_failed`，不重启）或 `FatalWorkerError`（`fatal`：CUDA 粘性错误等，当前文件写 `failure.json` 后立即退出，编排器从下一文件重启）。

**协议读侧**（同一模块，编排使用）：纯函数 `classify_launch(ids, exit_code, events) -> LaunchOutcome` 用本模块自己的退出码常量与事件名解释一次 worker 启动，返回 `LaunchOutcome`（冻结 dataclass）：已报 `failed` 的 id（`failed`）、崩溃文件（`crashed`，若有）、崩溃文件是否已由 worker 写出失败即报了 `fatal`（`fatal`）、启动失败的 `error_type`（`startup_failed`，若有）与剩余待跑 id（`remaining`）。规则：有 `startup_failed` 即启动失败，剩余全部失败、不重启；有 `fatal` 即该 id 为崩溃文件，从其后重启；退出码 0／1 只有在每个待跑 id 都有事件时才算正常结束（退出码 1 也是 Python 未捕获异常的退出码）；其余情况最后一个有事件的 id 之后的那个 id 是崩溃文件，从其后重启。编排的 `run_gpu_stage` 只循环与记失败，不再用字面量解释协议。

**失败窗口**（w0／x0 共用）：`fail_window(asr, chunk_index, reason)` 把 `original_segments[i].text` 移入 `failed_windows`（`chunk_index`、`reason`、截断文字）并置空；`retained_text` 是保留文本，后续对齐、cue 与翻译只用它；`validate_failed_windows` 要求列表存在、索引唯一有效且对应窗口已置空。`reason` 的现有取值：解码／生成抛错的 `RuntimeError: …`、x0 触顶的 `token_limit_reached: generated <n> tokens`、w0 复读守卫置空的 `guard:repeat-strict`（[ADR-0023](../../adr/0023-asr-repeat-guard.md)；此时 `text` 是该窗被置空前的完整原文）。

**复读守卫记录**（w0 与 cross 的 `asr.json`、cross 的 `asr-w0.json`）：被守卫改动的窗口在 `asr_traces[i]` 里多一个键 `guard = {rule, action, period, copies, removed_raw_chars}`，`action` 为 `collapse`（`original_segments[i].text` 已是折叠后的文字）或 `blank`（该窗同时出现在 `failed_windows`）；没有被改动的窗口没有这个键。记录只有规则名与计数，不含文字。字段含义见 [STT worker](stt-workers.md#当前行为规格)。

**cross 审计产物**：`engine = "cross"` 时 asr 阶段在 `<work root>/<id>/` 额外写三个审计文件，名称是 `artifacts.py` 的模块常量 `ASR_W0`、`ASR_X0`、`ASR_JUDGE`：`asr-w0.json`、`asr-x0.json`（各自完整的 `asr.json` 结构，engine 分别为 `w0`／`x0`，身份按单引擎计算）与 `asr-judge.json`（`offset_s`、每窗口两路原文、分歧区间、逐区间分数与决定，以及文件级计数汇总，身份同 cross 的 `asr.json`；字段见 [STT worker](stt-workers.md#cross-引擎)）。三者都带 `offset_s`（照抄 `vad.json`），经 `write_artifact` 原子写出。它们**不是阶段产物**：不在 `STAGE_OUTPUT`，不参与 `is_current`，没有它们或它们过期都不影响 `asr.json` 是否当前，也不影响下游；asr 阶段的产物契约只认 `asr.json`。保留它们是为了零 GPU 复算与用 `kototoki_eval` 评分。`asr.json` 本身的结构、`offset_s` 强制检查与失败窗口约定不变。

**专名产物**（[专名一致性](name-consistency.md)）：`NAME_TABLE = "name-table.json"` 是 names 阶段的阶段产物（在 `STAGE_ARTIFACTS`，参与 `is_current`，由编排经 `write_artifact` 写出，payload 为 `name-table-v2` 表与 `meta`／`build`）。身份由[阶段计划](stage-plan.md)给出，以 `names` 键进 `published.json` 的 `sources`（审计）；表含转写内容，只写在工作目录。ADR-0019 删除了发布时替换的审计产物 `NAMES_APPLY = "names-apply.json"` 与 `names_apply` 身份键：旧版本发布的记录里若有该键，`sources` 比较时视为不匹配，影片下次运行重新翻译并发布；工作目录里遗留的 `names-apply.json` 不再读取。

**内嵌日文字幕记录**（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）：`JA_EMBEDDED = "ja-embedded.json"` 在 `STAGE_ARTIFACTS`（`failure.json` 的 `completed` 会列出），由编排在 CPU 阶段经 `write_artifact` 写出，只有采用内嵌字幕的文件才有。身份由[阶段计划](stage-plan.md)的 `embedded_identity` 给出（`derived_identity`：上游为输入文件身份的 `object_hash`、`EMBEDDED` 配方 hash、配置键 `stream_index`），以 `ja_embedded` 键进 `published.json` 的 `sources`。payload：`stream`（所用字幕流的索引、编码、语言、default、forced）、清洗计数（`source_cues`、`cues`、`dropped_*`）、`ja_srt_sha256`。是否当前除身份外还要求 `ja_srt_sha256` 等于工作目录里 `ja.srt` 的 SHA256，这一步由阶段计划核对（`is_current` 只比身份），与 `ja-cues.json` 的同类检查共用一个辅助函数。

**`ja-cues.json` 的 `ja_srt_sha256`**：cue 阶段的 payload 也记写出的 `ja.srt` 的 SHA256；阶段计划据此判定 `ja.srt` 是否仍是 cue 阶段的输出。两条路径因此不靠删文件互相隔离：内嵌路径改写 `ja.srt` 后 `ja-cues.json` 不再当前，cue 阶段改写后 `ja-embedded.json` 不再当前。没有该字段的旧 `ja-cues.json` 视为不当前、重建一次。这类文件的 `probe.json` 里 `extract` 为 null（没有提取音频），工作目录里没有 `audio-16k.wav`、`vad.json`、`asr.json`、`align.json`、`ja-cues.json`。

**SRT**（`kototoki/srt.py`）：解析与渲染复制自 `experiments/translation_flow/srt.py`，严格性不变（重复编号、坏时间行、非正时长、空文字行报错），但空白输入解析为零条目、零条目渲染为空串。`format_srt([(start_s, end_s, text), ...])` 从 1 编号写出；秒到毫秒用 `floor(x*1000+0.5)`（`milliseconds`），不用 `round`；取整后时长非正即报错。另有整数毫秒入口（时间已是整数毫秒的条目直接渲染，不经秒），日文 cue 与内嵌字幕清洗都用它，毫秒格式化只有 `srt` 一处实现。`write_srt` 原子写出、拒绝覆盖源文件；是否发布由编排按源文件旁字幕是否存在判定。

## 接口与依赖

只依赖标准库；不导入 `experiments`、torch 或任何推理包，编排器可直接导入。本模块只提供身份的组成规则（`video_identity`、`derived_identity`）与匹配（`is_current`、`canonical`）；每个阶段的期望身份由谁的 SHA、哪个配方 hash、哪些模型文件组成，归[阶段计划](stage-plan.md)（`kototoki/plan.py`），worker 壳与编排都向它取。worker 中 CUDA 粘性错误的识别与包装为 `FatalWorkerError` 由各 worker 负责（票据 03／07）。`<work root>/lock`、GPU 锁与 worker 子进程重启归编排器（票据 06）。

## 代码与验证入口

- 代码：`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`。
- 测试（core，`just test`）：`tests/core/test_artifacts.py`（短 id 与碰撞、身份匹配／失效与原地替换、`offset_s` 强制、模型哈希缓存命中／失效、工作根键与最终字幕路径、`published.json` 审计记录、原子写重试与临时文件清理）、`tests/core/test_protocol.py`（jobs 解析、退出码 0／1／2、失败隔离、`failed_windows`；`classify_launch` 的正常、部分失败、`fatal`、`startup_failed`、无事件崩溃、退出码 1 但缺事件）、`tests/core/test_srt.py`（空 SRT、取整边界、严格解析、UTF-8 无 BOM）。
- `failure.json` 的清理归编排器：该文件成功发布后、判定为已有字幕而跳过时删除（[批次编排](batch-orchestration.md)，票据 06；2026-10-19 审计 B-13）。`final_srt_path` 只用主名，同目录主名相同、扩展名不同的输入（含视频与音频）会映射到同一份字幕路径，由编排在扫描阶段检测并让后者失败（审计 B-1）。
- 未验证：真实 Windows 文件占用下的重试行为只用注入的 `replace` 模拟。worker 协议、身份跳过与发布已由真实 worker 在[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)中使用。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/00-foundation.md`；规格 §4、§6、§7.1、§1.2 第三轮裁定表。原子写取自 `experiments/translation_v3/common.py`，模型哈希缓存取自 `experiments/translation_v3/server.py::verify_model`。

2026-10-19 `cross` 引擎交付，依据 [ADR-0012](../../adr/0012-cross-asr-judge.md) 与[产品路径验收](../../research/acceptance/2026-10-19-cross-asr-acceptance.md)，票据 `.scratch/cross-asr-judge/`；增量说明已吸收进本页（审计产物）并删除。

2026-10-19 专名一致性进产品（[ADR-0014](../../adr/0014-name-consistency-in-product.md)）：票据 `.scratch/name-consistency-product/issues/05-config-assets-plan.md` 加 `NAME_TABLE`／`NAMES_APPLY` 两个常量，06 同步本页。

2026-11-08 产品翻译切到 Q2（[ADR-0019](../../adr/0019-product-translation-q2.md)）：删除 `NAMES_APPLY` 常量与 `names_apply` 身份键；翻译 run 目录加 `__n<表sha12>`。

2026-11-11 w0 复读守卫交付（[ADR-0023](../../adr/0023-asr-repeat-guard.md)）：`asr_traces[].guard` 与失败原因 `guard:repeat-strict`；`asr.json` 的结构、身份组成与失败窗口约定不变，W0／CROSS 配方 hash 改变使旧 `asr.json` 不再当前。

2026-11-11 产品包架构整理（[ADR-0025](../../adr/0025-product-package-boundaries.md)，计划 [`docs/plans/architecture-cleanup.md`](../../plans/architecture-cleanup.md)）：协议读侧收进 `classify_launch`；`align.json` 的 units 改为 WAV 本地秒（产品 offset 恒为 0，字节不变）；`ja-cues.json` 加 `ja_srt_sha256`；SRT 加整数毫秒入口。
