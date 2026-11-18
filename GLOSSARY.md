# Kototoki

Kototoki 是在原生 Windows 与 RTX 5080 上用本地 AI 模型转写音频、保留原语言的自托管 STT 工具，当前处于研究与 demo 阶段；另含独立的字幕翻译实验。本术语表收录这些基线、组件与实验流程的项目特有叫法。

## Language

只收录本项目特有的概念，不收录通用编程概念。一个概念有多个叫法时选定一个，其余列入 `_Avoid_`。定义只说它是什么，一两句。术语自然成簇时用子标题分组。

条目格式：

```md
**术语**：
一两句定义。
_Avoid_: 同义词一, 同义词二
```

### 基线身份

每个身份只给一句定义；配方 id、hash、模型与启动方式的完整定义在[现行决定](docs/adr/CURRENT.md)，沿革在[决定索引](docs/adr/INDEX.md#演进链)。

**W0**：
STT 基线之一：faster-whisper＋新 Pyannote segmentation-3.0＋MMS CTC 对齐，由自有适配层移植 WhisperX 的切分合并、无时间戳解码与特征处理（[ADR-0003](docs/adr/0003-new-pyannote-baselines.md)）。

**X0**：
STT 基线之一：Qwen-ASR＋同一新 Pyannote＋同一 MMS，只吸收与 Qwen 兼容的 WhisperX 做法，保留 Qwen 原生解码与特征；fixed30 与不带 VAD 的 cut-merge 是单独标识的对照（[ADR-0003](docs/adr/0003-new-pyannote-baselines.md)）。
_Avoid_: Q0（那是翻译身份）

**H0**：
专用翻译模型线的历史对照身份（2026-11-08 起不再是基线）：Hy-MT2 30B-A3B APEX-I-Compact＋采样 `official30b-cached-v1`＋完整 SRT 流程配方 `dp10-cut`（[ADR-0021](docs/adr/0021-q3-strata-names-baseline.md)）。
_Avoid_: Hy 基线、旧基线、Translation baseline（2026-10-21 前的旧称）

**Q0**：
通用模型线的第一个翻译身份（历史）：Qwen3.8-27B＋`translation_v3` 配方 `qwen-wide`，切包与 H0 相同、只读邻文更宽（[ADR-0021](docs/adr/0021-q3-strata-names-baseline.md)）。
_Avoid_: qwen-wide（指基线时）、通用模型基线、X0（那是 Qwen-ASR 的 STT 基线）

**Q1**：
Q0 加上只注入 `confidence: high` 条目的专名表、注入后不替换的翻译身份（历史；[ADR-0021](docs/adr/0021-q3-strata-names-baseline.md)）。
_Avoid_: N\*（指基线时）、q0-names-high（指基线时）、Q0＋注入

**Q2**：
前任翻译基线：Q1 的配方规则不变，模型换为 Strata 上的 Qwen3.8-Flash-Next、不加参数启动；产品翻译配方 `q2-degrade-v1` 即 Q2 规则加降级（[ADR-0021](docs/adr/0021-q3-strata-names-baseline.md)、[ADR-0029](docs/adr/0029-translate-per-cue-resolution.md)）。
_Avoid_: F1（指基线时；F1 是 v12 的 MTP／32K 启动）、Flash-Next 基线

**Q3**：
唯一的翻译基线（2026-11-09 起）：Q2 的翻译规则不变，注入的专名表改由同一 Strata 实例上的 Flash-Next 建（[ADR-0021](docs/adr/0021-q3-strata-names-baseline.md)；完整定义见[现行决定](docs/adr/CURRENT.md#翻译基线-q3)）。
_Avoid_: S1（指基线时；S1 是 v13 的候选臂）、names-strata-v4（指基线时）、Strata 建表基线

### 双语字幕流水线

**双语字幕流水线**：
产品包 `kototoki/`，入口 `python -m kototoki [kototoki.toml]`：一批日语视频或音频按阶段整批推进（probe／extract → vad → asr → align → ja-cues → names → translate → 发布），每个输入在源文件旁产出 `<stem>.ja-zh.srt`。
_Avoid_: 产品后端, 正式后端

**STT 引擎（w0／x0／cross）**：
配置键 `stt.engine` 的取值，`w0`／`x0` 分别按 W0／X0 的配方在产品统一 CUDA 12.8 环境中运行；环境升级即新身份，与基线成绩的回归本期未做，不直接继承 W0／X0 的分数。`cross`（[ADR-0003](docs/adr/0003-new-pyannote-baselines.md)，已接受 2026-10-19；两部合计 CER −0.95 pp，低于预设 1.0 pp 验收线，用户裁定仍采用）是可选取值，默认仍为 `w0`：同一 asr worker 内 w0 与 x0 各转写一遍，再由 Whisper 对两路分歧区间做交叉打分（阈值 −1.0）合并成同构的 `asr.json`，配方 `cross-w0-x0-whisper-judge-v1`，不是新的 W0／X0 基线。

**日文 cue**：
翻译与字幕的最小单元：由 `align.json` 字符时间回填后按句末、软断点、字数与时长切出的一条日文字幕（`ja-cues.json`／`ja.srt`），中文译文与之一一对应。采用内嵌日文字幕的文件（ADR-0024）不经切分，`ja.srt` 里清洗后的每条字幕即一条日文 cue。

**整窗 fallback**：
日文 cue 回填时，一个窗口没有任何字符时间，按 VAD 子段比例给字符排时间（`time_source=fallback`）；只属时间回填，与翻译的未翻译 cue 无关。

**产品翻译配方 `dp10-cut-degrade-v1`**：
`kototoki/translate/recipes.py` 的产品翻译配方（2026-10-18 起，ADR-0021「历史流程与产品配方」）：切包、邻文、提示、grammar、采样与请求字节与 v3 `dp10-cut` 完全相同，只把批次终态失败的处理（`overflow`）改为拆批降级（两半→单条）、单条仍失败保留日文，因此另算 `recipe_hash`。2026-10-14..18 的产品配方 `b10-joint-degrade-v1` 与 `b10-joint` 同此关系，保留作旧 run 目录的身份对照。
_Avoid_: dp10-cut、b10-joint（指产品配方时）

**未翻译 cue**：
按条追问到单条仍没有合格译文的 cue（ADR-0029）：译文为 `None`，双语字幕里只有日文一行；对该配方 hash 与 seed 是终态，重跑不再尝试，只有改 seed 才重译；数量记入 `translate/report.json` 与 `published.json`（`translate_untranslated_cues`）。2026-11-17 之前的配方 `q2-degrade-v1` 把这类 cue 的中文位置填成日文原文，称"回退 cue"。
_Avoid_: 回退 cue（指现行产品时）

**阶段计划**：
双语字幕流水线中对一个文件从 vad 起逐阶段核对产物身份、给出"下一个要跑的阶段"（或终态 `publish`／`done`）与各阶段期望身份的模块（`kototoki/plan.py`）；编排只负责问，worker 壳从它取写进产物的身份。
_Avoid_: 计划器, 调度计划

**产物身份**：
写在每个中间产物里的身份（上游 SHA256、配方 hash、模型 SHA256、相关配置），续跑时与期望身份相同即跳过、不同即原地替换；不含绝对路径。翻译阶段没有单一产物文件，其身份（`ja.srt` SHA256、配方 hash、seed、注入行 SHA256）与 run 目录键由翻译子系统的 `translate.plan` 给出。

**发布**：
双语字幕 `<stem>.ja-zh.srt` 先写入工作目录暂存、记入 `published.json`（审计记录）再原子移到源文件旁。源文件旁已有同名字幕（不论来源）即跳过该文件，没有覆盖开关，要重做须先删掉它。

**专名表（name table）**：
`names` 阶段为每部影片的 `ja.srt` 建的专名清单（`name-table.json`，schema `name-table-v2`）：若干实体，各带种类（person／class／org／place／other）、规范中文译名、写法、`zh_variants` 与 evidence；`build.status` 为 `ok`／`failed`／`too_long`，后两者是空表。表在工作目录里，可人工校对；产品只把其中 `confidence: high` 的写法作为**注入行**交给翻译（[ADR-0029](docs/adr/0029-translate-per-cue-resolution.md)），改到注入行后删掉该片的 `*.ja-zh.srt` 再运行即重译该片。条目是转写内容，不进日志（`kototoki/names/table.py`，[ADR-0028](docs/adr/0028-names-accept-empty-table.md)）。
_Avoid_: 术语表, glossary（`terms` 配方与 `glossary-v1` 模型目录是历史命名）

**实体（entity）**：
专名表的一个条目所指的对象：一个人物、职阶、组织或地点，以 `entity_ja`（模型认出的正确日文全称）标识，对应一个规范中文译名 `zh`；同一实体在日文转写里可以有多个写法。

**写法（form）**：
实体在 `ja.srt` 里实际出现的一个日文写法（含 ASR 误写）及它对应的中文 `{ja, zh}`，如 シンジ → 真嗣、碇 → 碇；同一实体的各写法按日文去重，`entity_ja` 本身也是其中之一。不是翻译配方里的"提示变体"，也与 `zh_variants`（模型列出的译文里可能出现的别的中文写法）不同。

**注入行**：
专名表里 `confidence: high` 实体的每个写法展开成的一行 `{ja → zh}`（按 `ja` 去重，跳过空写法）；某个包只注入日文写法出现在该包可见台词里的行，表头 `qwen-name-table-v1`（Q1／Q2 规则，`kototoki/translate/recipes.py::name_rows`）。注入行的 SHA256 是产品翻译身份的一部分。

**锚定 cue**：
（研究线与 2026-11-08 前的产品替换，ADR-0028「表的使用与校对」起产品不再替换）替换时，日文里出现某个实体最长 `form.ja` 的 cue 就由该写法锚定（短写法不再重复处理同一 cue），该 cue 的译文以这个写法的 `zh` 为替换目标；替换只发生在锚定 cue 内（研究实现见 [专名一致性轮次](research/2026-10-name-consistency/README.md)）。

**落点**：
在锚定 cue 的译文里找到的、应被换成目标中文的那一段：先找同实体其他写法的中文与过特异性检验的 `zh_variants`（变体层），找不到再用跨 cue 统计（统计层）；统计层落点按规则一扩展到整个名字。落点重叠、紧邻复合名连接符或不在词边界上时不替换，记为 `unresolved`。

W0／X0 demo 的 CLI 旧默认（旧 PyanNet／fixed30）**不是**已采纳的基线，见 [ADR-0003](docs/adr/0003-new-pyannote-baselines.md)。
