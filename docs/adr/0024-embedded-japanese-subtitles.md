# ADR-0024：有内嵌日文文本字幕轨的文件跳过 STT

状态：已接受（2026-11-11，用户裁定：按方案默认开启、ASS 进第一版、听障说明原样保留、外挂字幕不做）、**已实现（2026-11-11）**：`kototoki/embedded.py`（清洗）、`kototoki/media.py`（选轨与抽取）、`kototoki/plan.py`（身份与计划起点）、`kototoki/job.py`（接入 CPU 阶段）；配方 `recipes.EMBEDDED`，id `embedded-ja-subtitle-v1`。验证见"依据"与"未验证"。不替代任何 ADR：[ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md) 的阶段链对没有可用字幕轨的文件不变，本 ADR 给有字幕轨的文件另加一条不经 STT 的路径；[ADR-0020](0020-media-inputs-work-dir-and-side-by-side-publish.md) 的输入、工作目录与发布规则不变；[ADR-0019](0019-product-translation-q2.md)、[ADR-0022](0022-product-names-on-strata.md) 的翻译与建表不变。2026-11-12 补漏：第 2 点的"不是 `forced`"在实现上也认标题里的 "forced"（不分大小写；真实片源 Black Panther 的两条 jpn 轨 disposition 都为 0、forced 只写在标题 `ja--forced--` 里，v1 选中了只有 224 条的部分字幕），配方 id 升为 `embedded-ja-subtitle-v2`，见[产品全流程验收](../../research/acceptance/2026-11-12-product-fullflow-acceptance.md)。  
范围：产品包 `kototoki/`。不改 W0／X0／`cross`、cue 规则、翻译与建表配方，不改研究侧。

## 决定

1. **路径。** `[input] use_embedded_subtitles`（默认 `true`）开着，且输入文件有可用的日文文本字幕轨时，该文件的阶段链为 probe → 抽轨与清洗（CPU，写 `ja.srt` 与 `ja-embedded.json`）→ `names` → `translate` → publish。不提取音频，不经 `vad`／`asr`／`align`／`cues`；整批都是这类文件时 GPU 只用于 Strata。其余文件照旧走 STT。
2. **可用的字幕轨。** 语言标签与 `[input] audio_language` 归一后相同（`jpn`／`ja`／`jp`）、编码在白名单（`subrip`、`ass`、`ssa`、`mov_text`、`webvtt`）、不是 `forced`。多条可用时取 `default` 的，再取流索引最小的，并告警。位图字幕（PGS、VobSub、DVB）视为没有。只看流的元数据，不看内容。
3. **抽取与清洗。** `ffmpeg -map 0:<index> -c:s srt -f srt` 统一转成 SRT，不自写 ASS 解析器。清洗：去掉 `<i>`／`<b>`／`<u>`／`<s>`／`<font>` 标签与 `{\...}` 覆盖块，字面的 `\h`、`\N` 换成空格；一条多行并成一行；丢掉清洗后为空、是 ASS 绘图指令、时长非正的条目，以及起止与文字都相同的重复条目；按（起、止）稳定排序，从 1 重新编号。不改写时间，不过滤听障字幕的音效说明（如"（ドアの音）"），它们照常翻译。
4. **回退。** ffmpeg 抽取失败，或清洗后零条目：记一行 WARNING，该文件回到 STT 链，不判失败。
5. **身份与续跑。** `ja-embedded.json` 的身份 = 输入文件身份（`probe.json` 的身份）＋ `EMBEDDED` 配方 hash ＋字幕流索引，payload 记流信息、清洗计数与 `ja.srt` 的 SHA256；身份匹配且 `ja.srt` 的 SHA256 相符即跳过抽取。`published.json` 的 `sources` 在这条路径下为 `probe`、`ja_embedded`、`names`、`translate`。下游身份只认 `ja.srt` 的 SHA256，`names` 与 `translate` 不知道日文从哪条路径来。
6. **两条路径互不串用 `ja.srt`。** 写字幕轨的 `ja.srt` 时删掉 `ja-cues.json`（否则以后改走 STT 会把字幕轨的 `ja.srt` 当成 cue 阶段的输出）；cue 阶段改写 `ja.srt` 后 `ja-embedded.json` 记下的 SHA256 不再相符，下次走内嵌路径时重新抽取。已发布的文件按 ADR-0020 仍然整个跳过，不会因为本 ADR 重做。
7. **不做的事。** 同目录外挂字幕（`.ja.srt` 等）不读；位图字幕不做 OCR；不检测字幕内容是不是日文、不识别没有语言标签的日文轨；不处理假名注音；不按 ASS 样式过滤 OP／ED 卡拉 OK 行与屏幕字。

## 依据

- 质量上限：[v5](../../research/2026-10-quality-v5/README.md) 估计译文质量损失里 STT 侧上限约 76%，翻译侧约 1%；有人工日文字幕的文件直接绕开 STT 的全部错误源。[技术设计](../specs/bilingual-subtitle-pipeline.md) §11 原登记为"1.1 版最值得做的功能"。
- 清洗规则按 ffmpeg n9.0.2 的实际输出定（2026-11-11 用合成 mkv／mp4 实测）：ASS 轨转出后样式变成嵌套 `<font>`、对齐留成 `{\an8}`、`\h` 原样留下、`\N` 变换行、绘图指令漏成文字、空事件留成只有标签的条目；SubRip 与 mov_text 轨基本原样。
- 时间轴：容器起点不为 0（合成 +2 s）时，转出的字幕时间与派生 WAV 一样以 ffmpeg 的输入零点为准（字幕 0.5 s 仍是 0.5 s，WAV 不补 2 s），两条路径的时间基准一致。
- 测试：core 覆盖清洗、选轨、计划（从 names 起、不核对 GPU 模型）、编排（不提取音频、不起 worker、回退、续跑、两条路径来回切换）；full 用真实 ffmpeg 合成带 SubRip、ASS、mov_text 字幕轨的片段走完整批次编排。

## 影响

- 默认行为改变：有日文文本字幕轨的文件不再做 STT。字幕轨时间轴偏移或质量差时，把 `[input] use_embedded_subtitles` 设为 `false` 强制走 STT（已发布的文件须先删掉其 `.ja-zh.srt`）。
- 人工字幕的条目比 cue 阶段的产出长，且可能时间重叠；翻译与合并照常处理（`srt.parse_srt` 允许重叠），`ja-zh.srt` 仍是每条两行。
- 大文件抽字幕轨要读完整个容器（数十秒量级），仍远快于 STT；抽取失败不缓存，每次运行重试。

## 未验证

- 没有用真实片源（流媒体片源、字幕组 ASS）跑过；ASS 的卡拉 OK 与屏幕字噪声有多大未知，噪声大时的备选是把 `ass`／`ssa` 从白名单拿掉（改配方即可）。
- 没有跑过真实模型验证（Strata 上的建表与翻译对人工字幕输入的表现）；需要用户批准后跑一部整片。
- 字幕轨标了 `jpn` 但内容不是日文时会被照常翻译；假名注音会留在文字里。
- 播放器对起点不为 0 的容器如何对齐外挂字幕未核实（与 STT 路径同一基准，行为一致）。
