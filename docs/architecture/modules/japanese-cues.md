---
covers:
  - kototoki/cues.py
---
# 日文 cue

状态：current（票据 04 交付，2026-10-14）

- 编排器调用与 `ja-cues.json`／`ja.srt` 落盘见[批次编排](batch-orchestration.md)（票据 06）。
- 2026-11-11 起按计划 `architecture-cleanup`（`archive/2026-11-18-pre-research-restructure:docs/plans/architecture-cleanup.md`）（[ADR-0025](../../adr/0025-product-package-boundaries.md)）先行写入本页接口：units 改为 WAV 本地秒、offset 只在本模块加一次、直接读 `recipes.CUES["fallback_max_char_s"]`、用 `srt` 的整数毫秒入口。
- 代码随该计划票据 03、08 落地；offset 为 0 时 `ja-cues.json` 与 `ja.srt` 字节不变，结果见计划 §7。

## 定位与阅读

负责双语字幕流水线（[日文 cue 交界](../collaborations/artifact-handoff.md#日文-cuestt-与翻译的交界)、[切分规则](../../behaviors/bilingual-subtitle-pipeline.md#切分规则)、[模块边界](../module-boundaries.md#产品包的责任边界)）中 STT 与翻译的交界：把 `align.json` 的字符级时间回填后切成日文字幕条目，产出 `ja-cues.json` 的 payload 与 `ja.srt` 文本。

不负责：文件读写、身份与跳过判定（[产物契约](artifact-contract/layout-and-identity.md)，由编排器经 `write_artifact`／`srt.write_srt` 写出）、cue 规则的配置加载与默认值（票据 02 `config`）、翻译与合并（票据 05）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**入口**：`build_cues(align, rules) -> (payload, srt_text)`（`kototoki/cues.py`），纯函数，不读写文件、不打印。

- `align`：已解析的 `align.json` 内容（现有 `result.json` 结构）。用到 `text`、`offset_s`、`units`（每个字符恰好一个 unit，`char_start/char_end` 连续，`status` 为 `ok`／`text_only`）、`original_segments`（ASR 窗口文字与本地边界，与 `chunks` 一一对应）、`chunks[].segments`（VAD 子段，本地秒；整窗回退与间隔断句都用它）。不满足"一字符一 unit"或窗口文字拼不出全文时报 `ValueError`。
- `rules`：键集合恰为 `max_chars`、`max_duration_s`、`min_duration_s`、`max_gap_s`、`sentence_endings`、`soft_breaks`、`lead_out_s` 的映射（与配置文件 `[cues]` 表同形，默认值见[配置参考](config-and-media/reference.md)），多键少键报错。

**坐标**：`units[].start/end`、窗口边界（外推夹取用）与 VAD 子段（回退用）都是 WAV 本地秒，本模块给三者各加一次 `offset_s`。这是时间轴上唯一加 offset 的地方（对齐不再给 units 加）；cue 时间即最终 SRT 时间。

**回填**（先于切分，逐窗口）：

- 窗内有时间字符之间的 `text_only` 串按前一字符的 `end` 到后一字符的 `start` 等分（`time_source=interpolated`）。
- 窗首／窗尾只有单侧邻居的串，按该窗平均每字符时长（首个到末个有时间字符的跨度 ÷ 字符数）向窗口边界外推，夹取在窗口边界内（`interpolated`）。
- 整窗无时间：按 VAD 子段时长比例（最大余数法）分配字符数，子段内从起点依次排列，每字符时长 = min(子段时长 ÷ 字符数, `recipes.CUES["fallback_max_char_s"]`=0.25 s)（`time_source=fallback`，沿用研究期评分包的取值）；没有子段时用窗口边界。
- `align.json` 不改；回填只体现在返回的 payload 里。

**切分**：标点、空白与符号（Unicode 类别 P／S／Z／C，含 ♪）是非词汇字符，不参与 cue 时间与切点。

1. 相邻词汇字符之间的非词汇串含 `sentence_endings` 字符，或两词汇字符的间隔（前字结束到后字开始）> `max_gap_s` 且不整个落在同一个 VAD 子段内，即断句。子段首尾相接或跨窗口都算不在同一子段；没有子段的窗口以窗口边界代替。票据 12：CTC 每字只给一个短发射点，拖长音会在词内留下假间隙，只有跨非语音区的间隔才算句界。
2. 句子超出 `max_chars`（非空白码点数，含附着的标点）或 `max_duration_s` 时，取最后一个使前段不超限的软断点（非词汇串含 `soft_breaks` 字符）切开，余下部分递归处理。
3. 没有可用软断点则硬切：按字符数与时长所需的段数均分字符，前段同时受 `max_duration_s` 约束，至少一个词汇字符。递归到单个词汇字符时，它本身超时长或附着标点超字数也不再切（2026-10-24 修复：此前硬切会在其后递归出空区间，产生空 cue 让 `ja.srt` 写出失败，或在全文末字越界；整批运行 25 部中 3 部触发；触发的是时长还是字数条件未取回现场数据核实）。

非词汇串在第一个空白或开括号（类别 Ps／Pi）处分开：前半附着前一条 cue，后半附着后一条；全文首尾的串附着首末 cue。cue 文本的空白折叠为单个空格并去掉首尾空白。

**时间修饰**：cue 起止取其首个词汇字符的 `start` 与末个词汇字符的 `end`；先加 `lead_out_s`，再把不足 `min_duration_s` 的延长到该值，两步都不越过下一条起点，也不缩短原时长。毫秒取整用 `srt.milliseconds`，渲染走 `srt` 的整数毫秒入口 `format_srt_ms`；取整后时长为零时补 1 ms（只在下一条同毫秒起始时可能与其重叠 1 ms）。

**输出**：

- 没有任何词汇字符（空输入、纯标点、纯 ♪）时零条目，`srt_text == ""`；不产出空 cue 或纯标点 cue。
- `payload`（`ja-cues.json` 的内容，身份由编排器包装）：
  - `cues[]`：`index`、`start_ms`、`end_ms`、`text`、`char_start/char_end`、`unit_start/unit_end`（一字符一 unit，与字符范围相同）、`time_sources` 计数、`backfilled_units`；
  - 全文 `time_sources` 计数；`backfilled_units`（回填 unit 的连续区间与来源）；`fallback_windows`（整窗回退的窗口序号）；`unrendered_chars`（不在任何 cue 内的字符数，有 cue 时为 0）。
  - 编排写出时另在 payload 里加 `ja_srt_sha256`（写出的 `ja.srt` 的 SHA256），供阶段计划判定 `ja.srt` 是否仍是本阶段的输出；本模块不算它。

## 实现设计

本模块是不读写文件、不发日志的纯函数；offset 只在此处加一次的约定见上文"坐标"。

### 运行日志

（本模块不发日志，由编排 `job.cues_batch` 按 payload 写，只报数、不设阈值）：

- `[cues] start: N file(s)`；每文件 `[cues] done <相对路径>: N cue(s), I interpolated unit(s), F fallback unit(s), W fallback window(s), U unrendered char(s)`，计数取 payload 的 `cues` 条数、全文 `time_sources` 的 `interpolated`／`fallback`、`fallback_windows` 条数与 `unrendered_chars`；
- cue 数为 0 时 done 行用 WARNING（走到 cues 阶段的文件 VAD 有语音，0 条会发布成近乎空的字幕）；
- `[cues] end: N done, M failed, T.Ts`。

## 接口与依赖

只依赖标准库、`kototoki.srt`（整数毫秒渲染入口 `format_srt_ms`、`milliseconds`）与 `kototoki.recipes`（`CUES["fallback_max_char_s"]`）；属基础层之上的纯函数模块，编排器直接调用（[模块边界](../module-boundaries.md#依赖方向)）。cue 规则的取值与默认由配置模块提供；整窗回退的每字符时长上限是会改变输出的值，只在 `recipes.CUES` 里（进 cue 配方 hash），本模块直接读，没有自己的常量。

## 代码与验证入口

- 代码：`kototoki/cues.py`（`build_cues`、`is_lexical`）；日志行在 `kototoki/job.py`（`cues_batch`、`build_ja_cues`）。
- 测试（core，`mise run test`）：
  - `tests/core/test_cues.py`：字符时间插值、整窗 `fallback` 按 VAD 子段分配；跨 VAD 子段的间隔断句、句末标点断句并留在原条、长句在最后一个放得下的软断点切开、无软断点时均衡硬切、超时长切分；lead-out 不越过下一条起点、min-duration 向前延长且不重叠；纯标点给 0 条；`offset_s` 只加一次、SRT 与 payload 一致。
  - 测试精简（2026-11-22）后不再有测试覆盖：边缘外推与夹取、回退时长上限与余数分配、纯文字窗在有时间窗之间、同一子段内与跨窗口的间隔、句末与全文末单个超限字符不再切、空输入、♪ 附着、非零 `offset_s` 整链、规则键校验、`RunLogTests` 中 cues 三件套的日志行与 0 条 cue 的 WARNING。
- 离线观感（2026-10-14，当时的 `[cues]` 初值，`.local/fullfilm-comparison/fullfilm-v1/runs/w0-pyannote-current-hf-ii-full/align/alignment.json`，前 5 分钟）：1627 条，无重叠、无超 6 s；`max_gap_s=0.4` 在 CTC 字间间隔处把词切碎（"先｜輩…"、"なん｜だ?"），≤2 字的条目 374 条；同一输入 `max_gap_s=1.0` 时降到 123 条。用户据此把初值改为 1.0（现行默认值见[配置参考](config-and-media/reference.md)）。记录见票据 04 Comments。
- x0 标点密度离线对照（2026-10-14，票据 07；现有同窗 X0／W0 研究期 `result.json`，hf-ii／hf-iii 各 6 个冻结窗口中两引擎都有结果的 11 个，同一组 101 个 VAD 窗口，默认 `[cues]`）：x0 每 100 个词汇字符有 7.7 个句末标点、2.5 个逗号，w0 为 2.3 与 0.6；cue 数 626 对 591，平均每条 9.9 对 9.8 字、p90 均为 18、触及 24 字上限 4 对 3 条，平均时长 1.84 s 对 1.99 s；以句末标点收尾的 cue 占 69% 对 20%，w0 其余多在时间间隔或硬切处断开。结论：x0 的标点主要改变断点位置（更多落在句末），不改变条目长度，现有初值无需按引擎区分。
- 票据 12 离线重算（2026-10-15，整片验收 `align.json`，初值 `[cues]`）：跨 VAD 子段才断句后，cue 数 w0／II 1056→1048、w0／III 1188→1181、x0／II 1154→1150、x0／III 1263→1257，≤2 字条目 113→110、124→118、115→114、95→90，重叠与 >6 s 条目数不变。建票样本（HF II w0 约 1969 s 的两字词）仍为两条：两字都落在 VAD 子段之外（Pyannote 漏检了约 2.4 s 的拖长音），本规则无法判定；词边界方案由票据 13 调研，结论见下一条。
- 票据 13 词边界调研（2026-10-15，只读，未实现）：
  - 用两个模型目录的 `tokenizer.json` 把 `asr.json` 的 `asr_traces[].tokens` 按字节还原并对回窗口文字，四部整片 772 个窗口全部逐字全等（w0 取小于 eot 的 id；x0 去特殊 token 后 `strip()`），跨多字节字符的 token 并组即可得到稳定的 token→字符映射。
  - 但 Whisper 对日文的 token 接近单字（平均 1.28 字／组，`先輩` 是两个 token），建票样本不会合并；"同一 token 内不按间隔断句"在四部整片只减 12 条 ≤2 字条目（432→420），同 token 内的 1–14 s 间隔都跨过非语音区，合并反而新增两条 >6 s cue。
  - 用户裁定不实现（2026-10-15），建票样本的根因是 VAD 漏检拖长音。方法、数据表与限制见[cue token 边界调研](../../research/2026-10-cue-token-boundary.md)。
- 未验证：x0 标点密度下的观感（只有统计，未人工看）；整片双语观感（[两部整片验收](../../research/acceptance/bilingual-pipeline-fullfilm-2026-10-14.md)只核对了条目数、时间一致与每条两行，未人工看）。

## 变更与决策来源

票据：

- 归档 tag 中的 .scratch/bilingual-subtitle-pipeline/issues/04-japanese-cues.md、`12-cue-gap-split-inside-word.md`、`13-cue-word-boundary.md`（调研结论见[cue token 边界调研](../../research/2026-10-cue-token-boundary.md)）。
- [产物交接](../collaborations/artifact-handoff.md)、[切分规则](../../behaviors/bilingual-subtitle-pipeline.md#切分规则)；§1.2 第三轮裁定表原文见技术设计历史记录（`archive/2026-11-18-pre-research-restructure:docs/research/2026-11-11-bilingual-pipeline-spec-history.md`）。
- 非词汇字符判定参考 `archive/2026-11-18-pre-research-restructure:experiments/display/replay.py`（只读，未导入），并把符号类别（♪）纳入。

2026-11-11 产品包架构整理（计划 `archive/2026-11-18-pre-research-restructure:docs/plans/architecture-cleanup.md` 票据 03、08，[ADR-0025](../../adr/0025-product-package-boundaries.md)）：offset 改为在本模块对 units 也加一次（此前由对齐加，与"cue 是唯一加 offset 的地方"不符）；删除 `FALLBACK_MAX_CHAR_S` 与钉相等的测试；`ja-cues.json` 由编排加 `ja_srt_sha256`；CUES hash 不变。

运行日志补缺（归档 tag 中的 .scratch/runtime-logging-gaps/ 票据 04）：`build_ja_cues` 返回载荷，编排据此记 `[cues]` 三件套。
