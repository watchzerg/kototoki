---
covers:
  - kototoki/artifacts.py
  - kototoki/workers/protocol.py
  - kototoki/srt.py
---
# 产物契约

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线（[行为规格](../../behaviors/bilingual-subtitle-pipeline.md)）各阶段共用的三件事：工作目录布局与最终字幕路径、产物身份与跳过／替换、原子写；编排器与 GPU worker 之间的 `--jobs` 协议；SRT 读写。

不负责：各阶段的推理与 payload 字段（[STT worker](stt-workers.md)、[STT ASR](stt-asr.md)、[日文 cue](japanese-cues.md)、[专名一致性](name-consistency.md)）；每阶段期望身份的组成（[阶段计划](stage-plan.md)）；批次编排与锁（[批次编排](batch-orchestration.md)）；翻译 run 目录内部格式（[翻译子系统](translation-subsystem.md)）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**布局**（`kototoki/artifacts.py`，ADR-0007「工作目录」）：

- 最终产物只有写在源文件旁的双语字幕：`S1/ep01.mkv` → `<input_dir>/S1/ep01.ja-zh.srt`（`final_srt_path`，后缀常量 `FINAL_SUFFIX`）。`final_srt_path` 只用主名，同目录主名相同、扩展名不同的输入会映射到同一份字幕路径，由编排在扫描阶段检测并让后者失败。
- 工作目录在 `[paths] work_dir` 下：`cache/` 放 `HF_HOME`／`TORCH_HOME` 与 `model-verification.json`（`cache_dir`，各目标目录共用）。
- 每个目标目录一个工作根 `<work_dir>/<input_dir 末段名>-<绝对路径 sha12>/`（`input_key`／`work_root`；摘要取 resolve 后的路径原文，根目录 `/` 的末段名记为 `root`），内含 `lock`、`input.json`（`record_input`，目标目录绝对路径，只供人查）、`index.json`。
- 每个输入的工作目录是 `<work root>/<id>/`，`<id>` 是输入目录内相对路径（含扩展名，统一正斜杠）UTF-8 的 SHA256 前 12 位（`work_id`；`:`、`\` 是文件名字符，按字面计入）。
- `register_work_dir(root, relative)` 在 `index.json` 登记 id ↔ 相对路径，同一 id 已登记为另一路径时报错（短 id 碰撞）；它读改写 `index.json`，由编排器在扫描阶段串行调用。
- 相对路径不得是绝对路径、为空或含 `..`。
- 产物文件名是模块常量（`PROBE`、`AUDIO_16K`、`VAD`、`ASR`、`ALIGN`、`JA_CUES`、`JA_EMBEDDED`、`NAME_TABLE`、`PUBLISHED`、`FAILURE` 等）；`STAGE_ARTIFACTS` 是阶段产物清单。翻译 run 目录的键归翻译子系统（`translate.plan`），本模块不拼它。

**坐标约定**：`vad.json`、`asr.json`、`align.json` 的窗口、段、对齐记录为 WAV 本地秒／整数样本，顶层必须有有限数值 `offset_s`（产品恒为 0，`write_artifact` 对这三个文件名强制检查）。`align.json` 的 `units[].start/end` 也是 WAV 本地秒、不含 offset；offset 只由日文 cue 加一次，`ja-cues.json` 与 SRT 的 cue 时间是最终 SRT 时间。

**身份**：JSON 产物顶层为 `{"identity": ..., **payload}`。

- 输入文件身份（`video_identity`，视频与音频同用）= 相对路径＋大小＋`mtime_ns`＋ffprobe 指纹；指纹只取流的 `index`／`codec_name`／`channels`／`channel_layout`／`sample_rate`／`start_time`／`duration` 与容器 `duration`，`filename` 与 `tags` 不参与。
- 派生身份（`derived_identity`）= 上游 SHA256（按名）＋配方 hash＋模型文件 SHA256（按名）＋影响输出的配置键；上游、配方、模型三处只接受 64 位小写十六进制摘要，因此绝对路径进不了这三处。
- `is_current(path, expected)`：文件存在、可解析、`identity` 与期望（经 JSON 规范化）完全相同才为真；损坏或不匹配即为假，调用方重算后用 `write_artifact` 原地原子替换。
- 模型文件 SHA256（`verify_model`）：首次完整计算并与期望比对，写入 `<work_dir>/cache/model-verification.json`（键为解析后的路径，记录 size 与 `mtime_ns`）；之后 size+mtime 不变即复用，不重算；不匹配报错且不入缓存。

**失败与发布**：

- `write_failure(work_dir, stage, error)` 写 `failure.json`：阶段、异常类型与消息、当时已存在的阶段产物（`completed`，按 `STAGE_ARTIFACTS`），不含音频与转写内容。`failure.json` 的清理归编排器（[批次编排](batch-orchestration.md)）：成功发布后删除，运行期间源文件旁才出现字幕而放弃发布时也删除；扫描时源文件旁已有字幕的文件不进任何阶段，它工作目录里以前留下的 `failure.json` 不清理。
- `record_published(work_dir, final_path, sha256, sources, translate_dir)` 在双语字幕写到源文件旁**之后**写 `published.json`：最终路径、`ja-zh` 的 SHA256、来源产物身份、当前翻译 run 目录（`translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>`，相对工作目录）。只作审计，不参与判定。
- 是否需要发布只看源文件旁的 `<主名>.ja-zh.srt` 是否存在（只看文件名，编排在扫描阶段判定，ADR-0007「发布」）；要重做就删掉该字幕。

**worker 协议**（`kototoki/workers/protocol.py`）：

- `--jobs <path>` 指向 `{"stage", "recipe_hash", "config", "files": [{"id", "work_dir", "inputs": {name: path}}]}`，键集合严格、id 唯一（`parse_jobs`／`read_jobs`／`write_jobs`）。
- `run_worker` 读 jobs、调用一次 `start(jobs)` 加载模型，成功后向 stdout 打 `started` 事件，再由 `run_jobs` 逐文件处理；结果由 worker 写进各自工作目录。
- stdout 打 UTF-8 JSON 进度行：`started`（模型加载完成、处理首个文件前）与 `done`／`failed`／`fatal`／`startup_failed`，只含事件、id、异常类型、计数与 `startup_failed` 的 `message`，不含窗口文字。
- 退出码：0 全部完成；1 有文件失败（该文件写 `failure.json`，继续下一文件）；2 启动失败（`startup_failed`，不重启）或 `FatalWorkerError`（`fatal`：CUDA 粘性错误等，当前文件写 `failure.json` 后立即退出，编排器从下一文件重启）；未发出 `started` 与任何文件事件前的异常退出同样视为启动失败、不重启。

**失败窗口**（w0／x0／cross 共用）：

- `fail_window(asr, chunk_index, reason)` 把 `original_segments[i].text` 移入 `failed_windows`（`chunk_index`、`reason`、`text`）并置空；`retained_text` 是保留文本，后续对齐、cue 与翻译只用它。
- `validate_failed_windows` 要求列表存在、索引唯一有效且对应窗口已置空。
- `reason` 的现有取值：解码／生成抛错的 `RuntimeError: …`、x0 触顶的 `token_limit_reached: generated <n> tokens`、w0 整窗守卫置空的 `guard:repeat-strict`、`guard:speech-rate`、`guard:hallucination-phrase`（[ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)；此时 `text` 是该窗被置空前的完整原文）。

**整窗守卫记录**（w0 与 cross 的 `asr.json`、cross 的 `asr-w0.json`）：

- 被守卫改动的窗口在 `asr_traces[i]` 里多一个键 `guard`，内容是生效规则的记录：复读 `{rule, action, period, copies, removed_raw_chars}`，语速 `{rule, action, chars, duration_s}`，幻听句 `{rule, action, phrase_index}`。
- `action` 为 `collapse`（只有复读，`original_segments[i].text` 已是折叠后的文字）或 `blank`（该窗同时出现在 `failed_windows`）；没有被改动的窗口没有这个键。
- 记录只有规则名与计数，不含文字。字段含义见 [STT ASR](stt-asr/window-guard.md#w0-整窗守卫)。

**cross 审计产物**（[ADR-0003](../../adr/0003-new-pyannote-baselines.md)）：

- `engine = "cross"` 时 asr 阶段在 `<work root>/<id>/` 额外写三个审计文件，名称是模块常量 `ASR_W0`、`ASR_X0`、`ASR_JUDGE`：`asr-w0.json`、`asr-x0.json`（各自完整的 `asr.json` 结构，身份按单引擎计算）与 `asr-judge.json`（逐窗裁判记录与汇总，身份同 cross 的 `asr.json`；字段见 [STT ASR](stt-asr/cross-judge.md#cross-引擎)）。
- 三者都带 `offset_s`（照抄 `vad.json`），经 `write_artifact` 原子写出。
- 它们**不是阶段产物**：不在 `STAGE_ARTIFACTS` 与 `STAGE_OUTPUT`，不参与 `is_current`，没有它们或它们过期都不影响 `asr.json` 是否当前，也不影响下游。保留它们是为了零 GPU 复算与离线评分。

**专名产物**：`NAME_TABLE = "name-table.json"` 是 names 阶段的阶段产物（在 `STAGE_ARTIFACTS`，参与 `is_current`，由编排经 `write_artifact` 写出，payload 为 `name-table-v2` 表与 `meta`／`build`）。身份由[阶段计划](stage-plan.md)给出，以 `names` 键进 `published.json` 的 `sources`；表含转写内容，只写在工作目录（[专名一致性](name-consistency.md)）。

**内嵌日文字幕记录**（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）：

- `JA_EMBEDDED = "ja-embedded.json"` 在 `STAGE_ARTIFACTS`，由编排在 CPU 阶段经 `write_artifact` 写出，只有采用内嵌字幕的文件才有。
- 身份由[阶段计划](stage-plan.md)的 `embedded_identity` 给出，以 `ja_embedded` 键进 `published.json` 的 `sources`。
- payload：`stream`（所用字幕流的索引、编码、语言、default、forced）、清洗计数（`source_cues`、`cues`、`dropped_*`）、`ja_srt_sha256`。
- 这类文件的 `probe.json` 里 `extract` 为 null（没有提取音频），工作目录里没有 `audio-16k.wav`、`vad.json`、`asr.json`、`align.json`、`ja-cues.json`。

**`ja_srt_sha256`**：`ja-cues.json` 与 `ja-embedded.json` 的 payload 都记写出的 `ja.srt` 的 SHA256；阶段计划据此判定 `ja.srt` 是否仍是该路径的输出（`is_current` 只比身份）。两条路径因此不靠删文件互相隔离：一条路径改写 `ja.srt` 后另一条路径的记录不再当前。

**SRT**（`kototoki/srt.py`）：

- 解析与渲染复制自 `archive/2026-11-18-pre-research-restructure:experiments/translation_flow/srt.py`，严格性不变（重复编号、坏时间行、非正时长、空文字行报错），但空白输入解析为零条目、零条目渲染为空串。读取容忍 UTF-8 BOM。
- `format_srt_ms([(start_ms, end_ms, text), ...])` 从 1 编号写出整数毫秒条目；时长非正即报错。日文 cue 与内嵌字幕清洗都用它。
- 秒到毫秒由调用方先用 `milliseconds` 取整：`floor(x*1000+0.5)`，不用 `round`。
- 字幕文字规则唯一出处 `subtitle_text_problem`，含翻译回复解析在内共用。
- 时间行四段到整数毫秒是 `time_parts_ms`，解析与内嵌字幕清洗共用；毫秒格式化只有 `srt` 一处实现。
- `write_srt(text, path)` 原子写出；是否允许覆盖现有文件由调用方按发布规则判定。

## 实现设计

### 原子写

`atomic_write_text`／`atomic_write_json` 写同目录临时文件、fsync 后 `os.replace`（临时文件名带 pid 与线程 id）；失败时删除临时文件，目标保持原样。文本一律 UTF-8 无 BOM、LF。

### 协议读侧

同一模块，编排使用。纯函数 `classify_launch(ids, exit_code, events) -> LaunchOutcome` 解释一次 worker 启动，`LaunchOutcome` 含 `failed`、`crashed`、`fatal`、`startup_failed`、`remaining` 与 `error_types`（报了 `failed`／`fatal` 的 id → worker 的 `error_type`）；`progress_event(event)` 判定事件是否转发成进度行并给出 `done` 的数值计数。事件名只在本模块出现。

规则：

- 退出码 0／1 只有在每个待跑 id 都有事件时才算正常结束（退出码 1 也是 Python 未捕获异常的退出码）。
- 否则有 `startup_failed` 即启动失败；既无 `started` 又无已报告的待跑文件事件（加载模型期间原生崩溃），同样按启动失败处理（`exited with code <n>`），剩余全部失败、不重启。
- 否则有 `fatal` 即该 id 为崩溃文件，从其后重启；再否则最后一个有事件的 id 之后的那个 id（有 `started` 而无文件事件时为首个 id）是崩溃文件，从其后重启。
- 编排的 `run_gpu_stage` 只循环与记失败，不用字面量解释协议。

## 接口与依赖

只依赖标准库；不导入研究代码、torch 或任何推理包，编排器可直接导入。本模块只提供身份的组成规则（`video_identity`、`derived_identity`）与匹配（`is_current`、`canonical`）；每个阶段的期望身份由谁的 SHA、哪个配方 hash、哪些模型文件组成，归[阶段计划](stage-plan.md)，worker 壳与编排都向它取。CUDA 粘性错误的识别与包装为 `FatalWorkerError` 归 worker 壳（[STT worker](stt-workers.md)）。`<work root>/lock`、GPU 锁与 worker 子进程重启归编排器。

## 代码与验证入口

- 代码：`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`。
- `tests/core/test_artifacts.py`：`work_id` 为含扩展名相对路径的 SHA12、最终字幕路径在源文件旁并镜像子目录、不同输入目录得到不同工作根；视频身份忽略位置而随大小、mtime 与 probe 变化；`is_current` 匹配与失效；失败记录列出已有阶段产物；模型哈希缓存命中则不重算；原子写失败时目标不变且无临时文件。
- `tests/core/test_protocol.py`：`run_worker` 先发 `started` 再逐文件处理、单文件失败隔离与 `fatal` 退出码 2；`classify_launch` 的部分失败与 `error_type` 传递、`progress_event`、`fatal`、启动期无 `started` 崩溃（不重启）与 `started` 后崩溃归咎；`failed_windows` 清空窗口文字并记录。
- `tests/core/test_srt.py`：毫秒取整为四舍五入而非银行家舍入、编号与时间行格式、畸形输入被严格解析拒绝、渲染保留编号与时间行与多行文字、译文不完整时抛出带报告的错误。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - 产物：`register` 写索引与幂等、越界路径与短 id 碰撞的拒绝、`input_key` 的构成、`record_input`、`derived_identity` 要求摘要、原地替换、损坏或外来产物不当前、`offset_s` 强制、交叉审计产物在阶段链外、内嵌与 names 产物在失败记录里、模型哈希的 size／mtime 重算与期望值核对、`published.json` 仅审计内容与摘要必填、UTF-8 无 BOM 与 LF。
  - 协议与 SRT：jobs 解析、畸形 jobs 与不一致记录的 `validate`、`startup_failed` 与退出码 1 缺事件、空 SRT、`srt_time` 拒绝负数、非正取整时长、空行文字、CRLF 归一、SHA 校验与 BOM 容忍。
- worker 协议、身份跳过与发布已由真实 worker 在[两部整片验收](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)中使用。

## 变更与决策来源

- ADR：
  - [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0028](../../adr/0028-names-accept-empty-table.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)；
  - [ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/（`issues/00-foundation.md`）、.scratch/cross-asr-judge/、.scratch/name-consistency-product/；Beads `kototoki-e8t`（2026-10-19 审计 B-1、B-13）
- 计划：`archive/2026-11-18-pre-research-restructure:docs/plans/architecture-cleanup.md`
- 验收：[两部整片验收](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)、[cross 产品路径验收](../../research/acceptance/cross-asr-acceptance-2026-10-19.md)
- 历史：技术设计历史（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）
- 来源代码：`archive/2026-11-18-pre-research-restructure:experiments/translation_flow/srt.py`、`archive/2026-11-18-pre-research-restructure:experiments/translation_v3/common.py`（原子写）、`archive/2026-11-18-pre-research-restructure:experiments/translation_v3/server.py`（`verify_model`）
