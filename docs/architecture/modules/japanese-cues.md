# 日文 cue

状态：current（票据 04 交付，2026-10-14）；编排器调用与 `ja-cues.json`／`ja.srt` 落盘见[批次编排](batch-orchestration.md)（票据 06）。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md) §5、[模块边界](../module-boundaries.md#产品包的责任边界)）中 STT 与翻译的交界：把 `align.json` 的字符级时间回填后切成日文字幕条目，产出 `ja-cues.json` 的 payload 与 `ja.srt` 文本。不负责：文件读写、身份与跳过判定（[产物契约](artifact-contract.md)，由编排器经 `write_artifact`／`srt.write_srt` 写出）、cue 规则的配置加载与默认值（票据 02 `config`）、翻译与合并（票据 05）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**入口**：`build_cues(align, rules) -> (payload, srt_text)`（`kototoki/cues.py`），纯函数，不读写文件、不打印。

- `align`：已解析的 `align.json` 内容（现有 `result.json` 结构）。用到 `text`、`offset_s`、`units`（每个字符恰好一个 unit，`char_start/char_end` 连续，`status` 为 `ok`／`text_only`）、`original_segments`（ASR 窗口文字与本地边界，与 `chunks` 一一对应）、`chunks[].segments`（VAD 子段，本地秒；整窗回退与间隔断句都用它）。不满足"一字符一 unit"或窗口文字拼不出全文时报 `ValueError`。
- `rules`：键集合恰为 `max_chars`、`max_duration_s`、`min_duration_s`、`max_gap_s`、`sentence_endings`、`soft_breaks`、`lead_out_s` 的映射（与配置文件 `[cues]` 表同形，初值见规格 §5.2），多键少键报错。

**坐标**：`units[].start/end` 已含 `offset_s`，原样使用；窗口边界（外推夹取用）与 VAD 子段（回退用）是本地秒，用到时加一次 `offset_s`。这是时间轴上唯一加 offset 的地方；cue 时间即最终 SRT 时间。

**回填**（先于切分，逐窗口）：

- 窗内有时间字符之间的 `text_only` 串按前一字符的 `end` 到后一字符的 `start` 等分（`time_source=interpolated`）。
- 窗首／窗尾只有单侧邻居的串，按该窗平均每字符时长（首个到末个有时间字符的跨度 ÷ 字符数）向窗口边界外推，夹取在窗口边界内（`interpolated`）。
- 整窗无时间：按 VAD 子段时长比例（最大余数法）分配字符数，子段内从起点依次排列，每字符时长 = min(子段时长 ÷ 字符数, `FALLBACK_MAX_CHAR_S`=0.25 s)（`time_source=fallback`，沿用 `kototoki_eval.schema` 取值）；没有子段时用窗口边界。
- `align.json` 不改；回填只体现在返回的 payload 里。

**切分**：标点、空白与符号（Unicode 类别 P／S／Z／C，含 ♪）是非词汇字符，不参与 cue 时间与切点。

1. 相邻词汇字符之间的非词汇串含 `sentence_endings` 字符，或两词汇字符的间隔（前字结束到后字开始）> `max_gap_s` 且不整个落在同一个 VAD 子段内，即断句。子段首尾相接或跨窗口都算不在同一子段；没有子段的窗口以窗口边界代替。票据 12：CTC 每字只给一个短发射点，拖长音会在词内留下假间隙，只有跨非语音区的间隔才算句界。
2. 句子超出 `max_chars`（非空白码点数，含附着的标点）或 `max_duration_s` 时，取最后一个使前段不超限的软断点（非词汇串含 `soft_breaks` 字符）切开，余下部分递归处理。
3. 没有可用软断点则硬切：按字符数与时长所需的段数均分字符，前段同时受 `max_duration_s` 约束，至少一个词汇字符。单个字符本身超时长时不再切。

非词汇串在第一个空白或开括号（类别 Ps／Pi）处分开：前半附着前一条 cue，后半附着后一条；全文首尾的串附着首末 cue。cue 文本的空白折叠为单个空格并去掉首尾空白。

**时间修饰**：cue 起止取其首个词汇字符的 `start` 与末个词汇字符的 `end`；先加 `lead_out_s`，再把不足 `min_duration_s` 的延长到该值，两步都不越过下一条起点，也不缩短原时长。毫秒取整用 `srt.milliseconds`；取整后时长为零时补 1 ms（只在下一条同毫秒起始时可能与其重叠 1 ms）。

**输出**：

- 没有任何词汇字符（空输入、纯标点、纯 ♪）时零条目，`srt_text == ""`；不产出空 cue 或纯标点 cue。
- `payload`（`ja-cues.json` 的内容，身份由编排器包装）：`cues[]`（`index`、`start_ms`、`end_ms`、`text`、`char_start/char_end`、`unit_start/unit_end`（一字符一 unit，与字符范围相同）、`time_sources` 计数、`backfilled_units`）；全文 `time_sources` 计数；`backfilled_units`（回填 unit 的连续区间与来源）；`fallback_windows`（整窗回退的窗口序号）；`unrendered_chars`（不在任何 cue 内的字符数，有 cue 时为 0）。

## 接口与依赖

只依赖标准库与 `kototoki.srt`（`format_srt`、`milliseconds`）；属基础层之上的纯函数模块，编排器直接调用（[模块边界](../module-boundaries.md#依赖方向)）。cue 规则的取值与默认由配置模块提供；`FALLBACK_MAX_CHAR_S` 是会改变输出的代码常量，须进 cue 配方 hash；已由票据 02 纳入 `recipes.CUES["fallback_max_char_s"]`（进 cue 配方 hash），本模块的常量是使用处，`tests/test_recipes.py` 钉住两者相等。

## 代码与验证入口

- 代码：`kototoki/cues.py`（`build_cues`、`is_lexical`、`FALLBACK_MAX_CHAR_S`）。
- 测试（core，`just test`）：`tests/test_cues.py`——插值、边缘外推与夹取、整窗 `fallback`、三级切分与时长切分、lead-out 不重叠、min-duration、间隔断句（跨子段切、同一子段内不切、子段相接与跨窗口照切）、空输入、全 `text_only` 窗、纯标点、♪ 附着、非零 `offset_s` 只加一次、SRT 可被 `parse_srt` 解析且与 payload 一致、规则键校验。
- 离线观感（2026-10-14，规格 §5.2 原初值，`.local/fullfilm-comparison/fullfilm-v1/runs/w0-pyannote-current-hf-ii-full/align/alignment.json`，前 5 分钟）：1627 条，无重叠、无超 6 s；`max_gap_s=0.4` 在 CTC 字间间隔处把词切碎（"先｜輩…"、"なん｜だ?"），≤2 字的条目 374 条；同一输入 `max_gap_s=1.0` 时降到 123 条。用户据此把初值改为 1.0（规格 §5.2）。记录见票据 04 Comments。
- x0 标点密度离线对照（2026-10-14，票据 07；现有同窗 X0／W0 研究期 `result.json`，hf-ii／hf-iii 各 6 个冻结窗口中两引擎都有结果的 11 个，同一组 101 个 VAD 窗口，默认 `[cues]`）：x0 每 100 个词汇字符有 7.7 个句末标点、2.5 个逗号，w0 为 2.3 与 0.6；cue 数 626 对 591，平均每条 9.9 对 9.8 字、p90 均为 18、触及 24 字上限 4 对 3 条，平均时长 1.84 s 对 1.99 s；以句末标点收尾的 cue 占 69% 对 20%，w0 其余多在时间间隔或硬切处断开。结论：x0 的标点主要改变断点位置（更多落在句末），不改变条目长度，现有初值无需按引擎区分。
- 票据 12 离线重算（2026-10-15，整片验收 `align.json`，初值 `[cues]`）：跨 VAD 子段才断句后，cue 数 w0／II 1056→1048、w0／III 1188→1181、x0／II 1154→1150、x0／III 1263→1257，≤2 字条目 113→110、124→118、115→114、95→90，重叠与 >6 s 条目数不变。建票样本（HF II w0 约 1969 s 的两字词）仍为两条：两字都落在 VAD 子段之外（Pyannote 漏检了约 2.4 s 的拖长音），本规则无法判定；词边界方案由票据 13 调研，结论见下一条。
- 票据 13 词边界调研（2026-10-15，只读，未实现）：用两个模型目录的 `tokenizer.json` 把 `asr.json` 的 `asr_traces[].tokens` 按字节还原并对回窗口文字，四部整片 772 个窗口全部逐字全等（w0 取小于 eot 的 id；x0 去特殊 token 后 `strip()`），跨多字节字符的 token 并组即可得到稳定的 token→字符映射。但 Whisper 对日文的 token 接近单字（平均 1.28 字／组，`先輩` 是两个 token），建票样本不会合并；"同一 token 内不按间隔断句"在四部整片只减 12 条 ≤2 字条目（432→420），同 token 内的 1–14 s 间隔都跨过非语音区，合并反而新增两条 >6 s cue。建议不实现，建票样本的根因是 VAD 漏检拖长音。数据表见票据 13 Comments。
- 未验证：x0 标点密度下的观感（只有统计，未人工看）；整片双语观感（[两部整片验收](../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)只核对了条目数、时间一致与每条两行，未人工看）。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/04-japanese-cues.md`；规格 §4、§5.2、§1.2 第三轮裁定表。非词汇字符判定参考 `experiments/display/replay.py`（只读，未导入），并把符号类别（♪）纳入。

目标架构页（`docs/architecture/bilingual-pipeline-architecture.md`，2026-10-14 设计稿）已于票据 08 收口时删除：分层图与不变量并入[架构总览](../INDEX.md)，依赖方向、责任边界与接缝并入[模块边界](../module-boundaries.md)；本模块的接口以本页"接口与依赖"节为准。
