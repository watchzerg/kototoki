# 中日双语字幕批量生产流水线

状态：implemented（只含用户可见行为；跨模块流程已移到[跨模块流程][collab]，配置参考、环境与历史记录已拆出，见文末"拆出的内容"）  
日期：2026-10-13  
范围：第一个正式产品形态，命令行工具，输入一批日语视频或音频，在源文件旁输出中日双语 SRT。不含 UI、流式、打包、非日语输入。本文写用户可见行为；阶段链、调度、产物交接与失败收敛见[跨模块流程][collab]，各模块的完整行为以[架构总览][arch]中的模块页为准，依赖方向与接缝见[模块边界][mb]，取舍见 [ADR-0007][adr7]。

| 子页 | 何时读 |
| --- | --- |
| [固定配方](bilingual-subtitle-pipeline/fixed-recipes.md) | 查各阶段写死、不做配置项的模型与配方 |

子页与本页说法冲突时以本页为准。

## 场景与前提

### 目标与边界

- 输入：`input_dir` 下（递归）的本地视频或音频文件（扩展名见[配置参考][cfg]，视频还是音频由 ffprobe 判定）。音频默认视为日语对白。
- 输出（每个输入）：写在源文件所在目录的 `<stem>.ja-zh.srt`（ADR-0007「发布」）；`ja.srt`、译文等中间产物留在工作目录（[产物交接][handoff]）。源文件旁已有 `<stem>.ja-zh.srt` 即跳过该文件。
- 入口 `python -m kototoki [kototoki.toml]` 只读一份配置文件，没有其他命令行参数；影响模型行为的解码／采样／提示常量是配方常量，留在代码里，不进配置文件（[配置参考][cfg]）。
- 产品不变量继续生效：本地运行、ASR／CTC／翻译只跑 GPU 不回退 CPU、保留日语原文、音频与转写不进 Git 与日志。

### 固定配方（写死，不做配置项）

各阶段的模型、精度与配方 id 写死在代码里，不做配置项；逐阶段的选择与依据见子页[固定配方](bilingual-subtitle-pipeline/fixed-recipes.md)。

### 已裁定

设计阶段（2026-10-13／14）的裁定表原文见历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）；现行规则以[现行决定](../adr/CURRENT.md)、[决定索引](../adr/INDEX.md)与各 ADR（ADR-0007 起）为准。

### 配置文件 `kototoki.toml`

见[配置参考][cfg]。

### 未来方向

未裁定事项与未来方向见[待裁定事项](../pending-decisions.md)与 Beads 票据 `kototoki-671`（说话人信息）；本节原文见历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。

## 操作与可观察结果

### 运行一批

每个输入依次经过阶段链；CPU 阶段先跑完整批，GPU 阶段按"阶段 × 整批"推进，因此首个结果要等整批 STT 结束。阶段顺序、调度与进程见[阶段链与调度][chain]。

最终产物只有写在源文件旁的双语字幕（`<input_dir>/S1/ep01.mkv` → `<input_dir>/S1/ep01.ja-zh.srt`），其余全在工作目录（ADR-0007「工作目录」）。`[paths] work_dir` 下有共用的 `cache/` 与每个目标目录一个工作根 `<work_dir>/<input_dir 末段名>-<绝对路径 sha12>/`（下称 `<work root>`）；每个输入的工作目录 `<work root>/<id>/`，`<id>` 是相对路径（含扩展名）SHA256 的前 12 位。目标目录改名或移动后对应不上旧工作根，从头重跑。工作目录布局见[产物交接][handoff]，路径、身份与原子写的权威正文是[产物契约][art]。

- 所有产物保留，不自动删除。
- 工作目录之外只写源文件旁的双语字幕；控制台只输出进度、计数与耗时；专名表条目是转写内容，日志只记计数。

### 内嵌日文字幕

[ADR-0024](../adr/0024-embedded-japanese-subtitles.md)：`[input] use_embedded_subtitles`（默认 `true`）开着且文件有可用的日文文本字幕轨时，该文件不经 extract、vad、asr、align、ja-cues，改为抽轨＋清洗后直接进 names、translate、merge（路径图见[阶段链与调度][chain-stages]）。

选轨、抽取与清洗规则（配方 `recipes.EMBEDDED`，id `embedded-ja-subtitle-v1`）见[配置、配方与媒体提取][media]；是否采用与回退见[批次编排][orch]。不做：外挂字幕文件、位图字幕 OCR、按内容判断语言、假名注音处理、按 ASS 样式过滤卡拉 OK 行与屏幕字。

### 发布

merge 阶段写一份副本到工作目录 `publish/`，再原子写到源文件旁（临时文件在目标目录内，工作目录与输入可在不同卷），成功后写 `published.json`。扫描时源文件旁已有 `<stem>.ja-zh.srt`（只看文件名）即跳过该文件；要重做就删掉这份字幕，中间产物按身份续跑。主名相同的两个输入争用同一字幕路径时，相对路径排序靠后的那个在扫描阶段失败。

### 切分规则

日文 cue 的键与默认值见[配置参考][cfg]；规则顺序、无时间字符的回填（`time_source`）、毫秒取整见[日文 cue][cues]。cue 为什么是翻译输入见[产物交接][handoff-cue]。双语合并把中文内的换行替换为空格，保证 `ja-zh.srt` 每条恰好两行（未翻译的 cue 只有日文一行；[双语合并][merge]）。

### 专名表可人工校对

跳过只比 `identity`，改 `entries` 不触发重建；手改后须删掉该片的 `*.ja-zh.srt` 再运行才会重译，哪些改动会触发重译见[专名一致性][names]。

### 续跑

重跑同一命令即可，已完成的产物按身份跳过；翻译按批次增量落盘，中断后从未完成的批次继续。未翻译的 cue 对该身份是终态；要重试须改 `[translate] seed`（另起 run 目录、整片重译）；要重做已发布的文件须先删掉其 `.ja-zh.srt`（ADR-0007「发布」）。

## 边界与错误情况

各项的跨模块处理（重试、拆分、收敛到哪一级失败）见[失败收敛][fail]。

- **文件级隔离**：一个文件在某阶段失败，写 `failure.json`，该文件退出后续阶段，批次继续；最终汇总打印失败清单，退出码非零。
- **内嵌字幕不可用**（ADR-0024）：抽取失败或清洗后零条目，记一行 WARNING，该文件回到 STT 链，不写 `failure.json`，结果不缓存。
- **无语音**：VAD 结果为空时跳过 ASR／对齐／翻译，直接发布零条目 `ja-zh.srt` 并告警。
- **抽取质量门**（batch-run-fixes 04）：视频输入解码时长超过参照时长 1.5 倍判 extract 失败；VAD 语音时长不足参照时长 1% 判 vad 失败。两者都写 `failure.json`。
- **个别窗口转写失败**：生成触顶或被整窗守卫判为不可信的窗口不出字幕，不让整部影片失败（[失败收敛][fail]）。
- **未翻译的 cue**：多次请求与拆分后仍没有译文的 cue 不出中文，双语字幕里只有日文一行；未翻译清单写 `report.json` 并在汇总给出未翻译数（[失败收敛][fail]）。
- **专名建表失败**：超预算或回复格式始终不合格时写空表并记 WARNING，影片照常翻译与发布；Strata 起不来、OOM、HTTP 或传输失败是该影片 `names` 阶段的文件级失败（[失败收敛][fail]）。
- **Strata 不可用**：Strata 被拒绝（`StrataRefused`），或整批启动失败累计 3 次后，本批其余需要模型的影片在 names 与 translate 两个阶段都直接失败（[阶段链与调度][chain-gpu]）。
- **并发与 GPU 冲突**：同一 `input_dir` 已有编排器在运行时退出码 3；撞 GPU 锁时整批以退出码 4 结束、不写逐文件 `failure.json`，已完成的产物保留，可续跑（[阶段链与调度][chain-gpu]）。

## 相关模块

- [跨模块流程][collab]：[阶段链与调度][chain]、[产物交接][handoff]、[失败收敛][fail]。
- [批次编排][orch]：唯一入口，扫描、调度、续跑、锁与发布。
- [阶段计划][plan]：阶段链、各阶段期望身份与下一个要跑的阶段。
- [产物契约][art]：工作目录、产物身份、原子写与 worker 协议。
- [配置、配方与媒体提取][media]、[配置参考][cfg]：配置键、音轨与 WAV、内嵌字幕抽取与清洗。
- [STT worker][stt]、[STT ASR](../architecture/modules/stt-asr.md)：VAD、转写与强制对齐。
- [日文 cue][cues]：把字符时间切成日文字幕条目。
- [Strata 服务与共享 session](../architecture/modules/strata-session.md)、[专名一致性][names]、[翻译子系统][tr]、[双语合并][merge]：建表、翻译与中日两行合并。
- [运行日志与进程][run]：运行日志、锁文件与子进程。

### 拆出的内容

2026-11-11 文档架构整理（票据 09）把下列内容移出本文（章节号指当时的编号版本）：

| 原章节 | 去向 |
| --- | --- |
| 状态行修订历史、§1.2、§8、§9、§11、§12、§13 | 历史记录原文（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`） |
| §2 的单片成本列、§2.2 重采样经过、§3.2 对比表、§3.4 时间线 | 历史记录原文（同上，"原第 2 至 6 节中移出的原文"一节）；理由见 [ADR-0007][adr7] |
| §2 各阶段细则、§2.1、§2.2 时长校验与下混 | [配置、配方与媒体提取][media]、各模块页 |
| §4、§6 的逐模块细则 | [产物契约][art]、[阶段计划][plan]、[批次编排][orch]、[翻译子系统][tr]、[专名一致性][names] |
| §5.2 规则表 | [配置参考][cfg]、[日文 cue][cues] |
| §7.1 的动态库与导入细节 | [STT worker][stt]、[批次编排][orch] |
| §7.2–§7.4 | [技术选型](../development/technology-stack.md)、[依赖布局与资产清单](../development/dependencies.md)；原文在历史记录（同上） |
| §10 | [配置参考][cfg] |

2026-11-22 按行为规格骨架重排（`kototoki-d8m`），编号章节的去向：

| 原章节 | 去向 |
| --- | --- |
| §1、§1.2、§10、§11 | 本页"场景与前提" |
| §1.1 | 子页[固定配方](bilingual-subtitle-pipeline/fixed-recipes.md) |
| §2、§2.1、§2.2、§3、§7 | [阶段链与调度][chain] |
| §4 布局与身份、§5.1 | [产物交接][handoff]；§4 的发布、保留、专名表校对与日志规则在本页"操作与可观察结果" |
| §5.2 | 本页"切分规则" |
| §6 | 本页"边界与错误情况"与"续跑"；ASR 失败窗口、Strata 基础设施失败、按条解决与建表失败的处理在[失败收敛][fail] |

[arch]: ../architecture/INDEX.md
[mb]: ../architecture/module-boundaries.md
[collab]: ../architecture/collaborations.md
[chain]: ../architecture/collaborations/stage-chain-and-scheduling.md
[chain-stages]: ../architecture/collaborations/stage-chain-and-scheduling.md#阶段分解
[chain-gpu]: ../architecture/collaborations/stage-chain-and-scheduling.md#gpu-内部顺序与并发
[handoff]: ../architecture/collaborations/artifact-handoff.md
[handoff-cue]: ../architecture/collaborations/artifact-handoff.md#翻译输入为什么是-jasrt
[fail]: ../architecture/collaborations/failure-convergence.md
[adr7]: ../adr/0007-bilingual-subtitle-pipeline-architecture.md
[cfg]: ../architecture/modules/config-and-media/reference.md
[media]: ../architecture/modules/config-and-media.md
[stt]: ../architecture/modules/stt-workers.md
[cues]: ../architecture/modules/japanese-cues.md
[names]: ../architecture/modules/name-consistency.md
[tr]: ../architecture/modules/translation-subsystem.md
[merge]: ../architecture/modules/translation-subsystem/bilingual-merge.md
[orch]: ../architecture/modules/batch-orchestration.md
[plan]: ../architecture/modules/stage-plan.md
[art]: ../architecture/modules/artifact-contract/layout-and-identity.md
[run]: ../architecture/modules/run-logging-and-processes.md
