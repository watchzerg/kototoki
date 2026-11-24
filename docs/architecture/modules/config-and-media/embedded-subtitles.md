---
covers:
  - kototoki/embedded.py
  - kototoki/media.py
---
# 配置与媒体子页：内嵌日文字幕

`配置与媒体` 的子页：内嵌日文字幕的选轨、抽取与清洗。

**内嵌日文字幕**（配方 `recipes.EMBEDDED`，id `embedded-ja-subtitle-v1`，进 `ja-embedded.json` 的身份；开关 `[input] use_embedded_subtitles`）：

- `media.select_subtitle(subtitles, language) -> (stream | None, warnings)`：从 `Probe.subtitles` 里选可用的字幕轨。
  - 可用 = 语言标签归一后等于 `language`（编排传 `input.audio_language`）、`codec_name` 在 `EMBEDDED["codecs"]`（`ass`、`mov_text`、`ssa`、`subrip`、`webvtt`）、不是 forced（`parse_probe` 记录的 `forced`：disposition 标了 forced，或 `tags.title` 含 "forced"、不分大小写）。
  - 多条可用时取 default 的，再取流索引最小的，并返回一条告警。
  - 位图字幕（PGS、VobSub、DVB）与没有语言标签的轨不可用。
  - 只看元数据，不看内容。
- `media.extract_subtitle(video, index, ffmpeg) -> str`：`ffmpeg -map 0:<index> -c:s srt -f srt pipe:1`，返回 SRT 文本，不写文件；ffmpeg 非零退出报 `MediaError`。字幕时间与派生 WAV 一样以 ffmpeg 的输入零点为准（容器起点不为 0 时两者同样平移）。
- `embedded.clean(text) -> (srt_text, stats)`（纯函数，只依赖 `srt` 的整数毫秒入口，毫秒格式化不自写）：
  - 自己宽松分条：时间行且上一行是纯数字编号即一条的开头；文字里的空行与数字行不会断条；不用 `srt.parse_srt`。
  - 逐条去掉 `<i>`／`<b>`／`<u>`／`<s>`／`<font>` 标签与 `{\...}` 覆盖块（其它尖括号、不以反斜杠开头的花括号保留），字面的 `\h`、`\N`、`\n` 换成空格，多行并成一行、空白折叠。
  - 丢掉清洗后为空、整条是 ASS 绘图指令（`m 0 0 l …`）、时长非正的条目，以及起止与文字都与已保留条目相同的重复条目；按（起、止）稳定排序，经 `format_srt_ms` 从 1 重新编号。没有可用条目时返回空串。
  - `stats` 只有计数（`source_cues`、`cues`、`dropped_empty`、`dropped_drawing`、`dropped_invalid_time`、`dropped_duplicate`）。不改写时间，不过滤听障字幕的音效说明。
- 规则按 ffmpeg n9.0.2 的实际输出定：ASS 的样式会变成嵌套 `<font>`，对齐留成 `{\an8}`，`\h` 原样留下，绘图指令漏成文字，空事件留成只有标签的条目。
- 是否采用、回退到 STT、`ja.srt` 与 `ja-embedded.json` 的写出与跳过都在编排（[批次编排](../batch-orchestration.md)）；计划从哪一阶段起核对在[阶段计划](../stage-plan.md)。

## 代码与验证入口

- 代码：`kototoki/embedded.py`，选轨与抽取在 `kototoki/media.py`（`select_subtitle`、`extract_subtitle`）。
- 测试（core，`mise run test`）：
  - `tests/core/test_embedded.py`：ASS 标签与覆盖块去除、多行并成一行；绘图／空／重复／非正时长条目丢弃及计数；按时间排序与重新编号；清洗结果过 `srt.parse_srt`。
  - 测试精简（2026-11-22）后不再有测试覆盖：SubRip 标记与字面方括号的选择性保留、整数毫秒条目输出不变、cue 内空行与 CRLF 不分割、正文里的数字行不当条目头、无可用条目给空文本。
- 测试（full，`mise run test-full`）：
  - `tests/full/test_job_ffmpeg.py`：真实 ffmpeg 合成带 SubRip 字幕轨（容器起点 +2 s）的片段走完整批次编排，字幕替代语音识别。ASS 与 mov_text 轨不再有测试。
- 未验证：
  - 内嵌字幕：真实片源（流媒体、字幕组 ASS 特效）、假名注音、标签与内容语言不符的轨。
