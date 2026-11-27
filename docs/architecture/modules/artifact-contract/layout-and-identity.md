---
covers:
  - kototoki/artifacts.py
---
# 产物契约子页：工作目录布局与产物身份

`产物契约` 的子页：工作目录布局与最终字幕路径、产物身份与跳过／替换、失败与发布记录、各类审计与专名／内嵌产物、原子写。改 `kototoki/artifacts.py` 或核对某个产物文件的位置与身份时读本页。上级：[产物契约](../artifact-contract.md)。

## 行为规格

**布局**（`kototoki/artifacts.py`，ADR-0007「工作目录」）：

- 最终产物只有写在源文件旁的双语字幕：`S1/ep01.mkv` → `<input_dir>/S1/ep01.ja-zh.srt`（`final_srt_path`，后缀常量 `FINAL_SUFFIX`）。`final_srt_path` 只用主名，同目录主名相同、扩展名不同的输入会映射到同一份字幕路径，由编排在扫描阶段检测并让后者失败。
- 工作目录在 `[paths] work_dir` 下：`cache/` 放 `HF_HOME`／`TORCH_HOME` 与 `model-verification.json`（`cache_dir`，各目标目录共用）。
- 每个目标目录一个工作根 `<work_dir>/<input_dir 末段名>-<绝对路径 sha12>/`（`input_key`／`work_root`；摘要取 resolve 后的路径原文，根目录 `/` 的末段名记为 `root`），内含 `lock`、`input.json`（`record_input`，目标目录绝对路径，只供人查）、`index.json`。
- 每个输入的工作目录是 `<work root>/<id>/`，`<id>` 是输入目录内相对路径（含扩展名，统一正斜杠）UTF-8 的 SHA256 前 12 位（`work_id`；`:`、`\` 是文件名字符，按字面计入）。
- `register_work_dir(root, relative)` 在 `index.json` 登记 id ↔ 相对路径，同一 id 已登记为另一路径时报错（短 id 碰撞）；它读改写 `index.json`，由编排器在扫描阶段串行调用。
- 相对路径不得是绝对路径、为空或含 `..`。
- 产物文件名是模块常量（`PROBE`、`AUDIO_16K`、`VAD`、`ASR`、`ALIGN`、`JA_CUES`、`JA_EMBEDDED`、`NAME_TABLE`、`PUBLISHED`、`FAILURE` 等）；`STAGE_ARTIFACTS` 是阶段产物清单。翻译 run 目录的键归翻译子系统（`translate.plan`），本模块不拼它。

**坐标约定**：`vad.json`、`asr.json`、`align.json` 的窗口、段、对齐记录为 WAV 本地秒／整数样本，顶层必须有有限数值 `offset_s`（产品恒为 0，`write_artifact` 对这三个文件名强制检查）。`align.json` 的 `units[].start/end` 也是 WAV 本地秒、不含 offset；offset 在哪一步加见[日文 cue](../japanese-cues.md)；`ja-cues.json` 与 SRT 的 cue 时间即最终 SRT 时间。

**身份**：JSON 产物顶层为 `{"identity": ..., **payload}`。

- 输入文件身份（`video_identity`，视频与音频同用）= 相对路径＋大小＋`mtime_ns`＋ffprobe 指纹；指纹只取流的 `index`／`codec_name`／`channels`／`channel_layout`／`sample_rate`／`start_time`／`duration` 与容器 `duration`，`filename` 与 `tags` 不参与。
- 派生身份（`derived_identity`）= 上游 SHA256（按名）＋配方 hash＋模型文件 SHA256（按名）＋影响输出的配置键；上游、配方、模型三处只接受 64 位小写十六进制摘要，因此绝对路径进不了这三处。
- `is_current(path, expected)`：文件存在、可解析、`identity` 与期望（经 JSON 规范化）完全相同才为真；损坏或不匹配即为假，调用方重算后用 `write_artifact` 原地原子替换。
- 模型文件 SHA256（`verify_model`）：首次完整计算并与期望比对，写入 `<work_dir>/cache/model-verification.json`（键为解析后的路径，记录 size 与 `mtime_ns`）；之后 size+mtime 不变即复用，不重算；不匹配报错且不入缓存。

**失败与发布**：

- `write_failure(work_dir, stage, error)` 写 `failure.json`：阶段、异常类型与消息、当时已存在的阶段产物（`completed`，按 `STAGE_ARTIFACTS`），不含音频与转写内容。`failure.json` 的清理归编排器（[批次编排](../batch-orchestration.md)）：成功发布后删除，运行期间源文件旁才出现字幕而放弃发布时也删除；扫描时源文件旁已有字幕的文件不进任何阶段，它工作目录里以前留下的 `failure.json` 不清理。
- `record_published(work_dir, final_path, sha256, sources, translate_dir)` 在双语字幕写到源文件旁**之后**写 `published.json`：最终路径、`ja-zh` 的 SHA256、来源产物身份、当前翻译 run 目录（`translate/srt-<sha12>/<配方名>__s<seed>__n<表sha12>`，相对工作目录）。只作审计，不参与判定。
- 是否需要发布只看源文件旁的 `<主名>.ja-zh.srt` 是否存在（只看文件名，编排在扫描阶段判定，ADR-0007「发布」）；要重做就删掉该字幕。


**cross 审计产物**（[ADR-0003](../../../adr/0003-new-pyannote-baselines.md)）：

- `engine = "cross"` 时 asr 阶段在 `<work root>/<id>/` 额外写三个审计文件，名称是模块常量 `ASR_W0`、`ASR_X0`、`ASR_JUDGE`：`asr-w0.json`、`asr-x0.json`（各自完整的 `asr.json` 结构，身份按单引擎计算）与 `asr-judge.json`（逐窗裁判记录与汇总，身份同 cross 的 `asr.json`；字段见 [STT ASR](../stt-asr/cross-judge.md#cross-引擎)）。
- 三者都带 `offset_s`（照抄 `vad.json`），经 `write_artifact` 原子写出。
- 它们**不是阶段产物**：不在 `STAGE_ARTIFACTS` 与 `STAGE_OUTPUT`，不参与 `is_current`，没有它们或它们过期都不影响 `asr.json` 是否当前，也不影响下游。保留它们是为了零 GPU 复算与离线评分。

**专名产物**：`NAME_TABLE = "name-table.json"` 是 names 阶段的阶段产物（在 `STAGE_ARTIFACTS`，参与 `is_current`，由编排经 `write_artifact` 写出，payload 为 `name-table-v2` 表与 `meta`／`build`）。身份由[阶段计划](../stage-plan.md)给出，以 `names` 键进 `published.json` 的 `sources`；表含转写内容，只写在工作目录（[专名一致性](../name-consistency.md)）。

**内嵌日文字幕记录**（[ADR-0024](../../../adr/0024-embedded-japanese-subtitles.md)）：

- `JA_EMBEDDED = "ja-embedded.json"` 在 `STAGE_ARTIFACTS`，由编排在 CPU 阶段经 `write_artifact` 写出，只有采用内嵌字幕的文件才有。
- 身份由[阶段计划](../stage-plan.md)的 `embedded_identity` 给出，以 `ja_embedded` 键进 `published.json` 的 `sources`。
- payload：`stream`（所用字幕流的索引、编码、语言、default、forced）、清洗计数（`source_cues`、`cues`、`dropped_*`）、`ja_srt_sha256`。
- 这类文件的 `probe.json` 里 `extract` 为 null（没有提取音频），工作目录里没有 `audio-16k.wav`、`vad.json`、`asr.json`、`align.json`、`ja-cues.json`。

**`ja_srt_sha256`**：`ja-cues.json` 与 `ja-embedded.json` 的 payload 都记写出的 `ja.srt` 的 SHA256；当前性判定见[阶段计划](../stage-plan.md)。

## 实现设计

### 原子写

`atomic_write_text`／`atomic_write_json` 写同目录临时文件、fsync 后 `os.replace`（临时文件名带 pid 与线程 id）；失败时删除临时文件，目标保持原样。文本一律 UTF-8 无 BOM、LF。

## 代码与验证入口

- 代码：`kototoki/artifacts.py`。
- `tests/core/test_artifacts.py`：`work_id` 为含扩展名相对路径的 SHA12、最终字幕路径在源文件旁并镜像子目录、不同输入目录得到不同工作根；视频身份忽略位置而随大小、mtime 与 probe 变化；`is_current` 匹配与失效；失败记录列出已有阶段产物；模型哈希缓存命中则不重算；原子写失败时目标不变且无临时文件。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - 产物：`register` 写索引与幂等、越界路径与短 id 碰撞的拒绝、`input_key` 的构成、`record_input`、`derived_identity` 要求摘要、原地替换、损坏或外来产物不当前、`offset_s` 强制、交叉审计产物在阶段链外、内嵌与 names 产物在失败记录里、模型哈希的 size／mtime 重算与期望值核对、`published.json` 仅审计内容与摘要必填、UTF-8 无 BOM 与 LF。
