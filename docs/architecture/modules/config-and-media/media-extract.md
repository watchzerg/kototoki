---
covers:
  - kototoki/media.py
---
# 配置与媒体子页：probe 与 extract

`配置与媒体` 的子页：ffprobe 探测、音轨选择、参照时长、ffmpeg 解码提取 WAV 与解码日志。

**probe**（`kototoki/media.py`，`probe(path, config) -> Probe`）：ffprobe `-show_streams -show_format` 全部流；原始 JSON 保留在 `Probe.ffprobe`（供 `artifacts.video_identity` 取指纹，视频与音频同用），`Probe.payload()` 是 `probe.json` 的内容。

- 音轨选择：语言标签归一化后（`jpn`／`ja`／`jp` 大小写不敏感视为 `jpn`，按 `recipes.LANGUAGE_ALIASES`，配置值同样归一化）等于 `input.audio_language` 且非 `disposition.comment` 的音轨优先，其中 `disposition.default` 优先、否则取第一条；多条匹配告警；无匹配取第一条音轨并告警，唯一的音轨没有语言标签或标为 `und` 时不告警（没得选；batch-run-fixes 06.4，只改告警，选轨规则与配方不变）；没有音轨报 `MediaError`。
- 记录：所选与全部音轨的绝对流索引、编码、声道数与布局、采样率、语言、default／comment、`start_time` 与时长（只作诊断，不进时间轴）、`measured_sample_rate` 与 `corrected_sample_rate`（见下条）；容器 `start_time`；字幕流清单（索引、编码、语言、default、forced，供内嵌日文字幕选轨）；告警列表。
- 采样率标错（`media.sample_rate_check`，规则 `MEDIA["sample_rate_correction"]`）：AAC-LC 且有 `nb_frames` 与流 `duration` 时实测 `nb_frames × 1024 ÷ duration`；声明 48000 而实测在 44100 的 ±1% 内（或反之）时 `corrected_sample_rate` 取真实值，所选音轨命中记告警。只认这一对（共用 SFB 表，改标签无损）。
- `has_video`：除封面图（`attached_pic`）外没有视频流即为音频输入（`Probe.has_video = False`）。
- 参照时长：视频输入取第一条非封面视频流，音频输入取所选音轨。取其 `duration`；没有时先取精确的 Matroska 标签 `DURATION`（大小写不敏感），再取 mkvmerge 统计标签 `DURATION-<lang>`；都没有时退回容器时长并告警；时长全无报 `MediaError`。
- 流时长与 `format.duration` 相差超过 `MEDIA["duration_tolerance_s"]` 时取较小者并写入 `Probe.warnings`，`duration_source` 记实际来源。`probe.json` 的字段是 `has_video`、`duration_s`、`duration_source`。

**extract**（`extract(path, work_dir, probe, config) -> Extract`）：视频与音频输入相同，只运行一条 ffmpeg 解码命令，写同目录临时文件后原子替换 `audio-16k.wav`；不流复制原始音轨（ADR-0007「输入范围」）。构造命令时校验下混布局，不支持的布局在运行 ffmpeg 前抛 `MediaError`。

1. **从输入容器**按所选音轨的绝对索引解码，`-af aresample=async=1:first_pts=0,<PAN>,aresample=16000`（采样率标错时最前面加 `asetrate=<真实>,asetpts=PTS*<真实>/<声明>`，后者把时间戳拉回容器时间）（ffmpeg 默认 swr）、`pcm_s16le`、`-fflags +bitexact -flags:a +bitexact`、`-loglevel level+verbose`（每行带级别标签；不进 `MEDIA` hash）；命令行与精简后的 stderr 写入 `extract.log`。起始延迟补静音、中途间隙补零，WAV 的 sample 0 即输入 0 秒，`Extract.offset_s` 恒为 0。
2. 时长校验对参照时长 `Extract.duration_s`：视频输入解码短于参照超过 1 s 抛 `MediaError` 且不留下 `audio-16k.wav`（日志保留）；音频输入短于参照只告警（时长可能是估算值，ADR-0007「输入范围」）；长于参照超过 1 s 告警，视频输入超过 1.5 倍（`MAX_OVERLONG_RATIO`，不进 `MEDIA`）抛 `MediaError`。
3. `Extract` 记录 PCM 数据块 SHA256、样本数、解码时长、所用 `pan`、告警与补偿统计 `compensation`：swr 报告的补入／丢弃样本数之和（输入采样率，含起始补齐，不完整，仅作参考）与净补偿秒数 `net_padding_s`（派生时长 − ffmpeg 结束统计的输入时长，已纠正时按纠正后的采样率，以它为准）。超过 0.1 s 时的 WARNING 由编排写（`job.compensation_warnings`）。

**解码日志**（batch-run-fixes 03）：`extract` 流式读 stderr，不整段进内存，经 `digest_decode_log` 写精简的 `extract.log`：info、无上下文、`in#`／`out#` 行原样写；error（含 fatal）、warning 行与 swr 补偿行各留前后 100 条（样本数全数累加）；其余 verbose 行只计数；末尾附消息类型计数表。`Extract.diagnostics`（进 `probe.json`，只作诊断）含各级别条数 `levels`、所选音轨的 `decode_errors` 与前 20 类 error／warning `messages`；有 error 行时 `Extract.warnings` 加一条（不判失败）。

子进程一律参数列表、`stdin=DEVNULL`（ffmpeg 另加 `-nostdin`）、UTF-8 解码。

## 代码与验证入口

- 代码：`kototoki/media.py`。
- 测试（core，`just test`）：
  - `tests/core/test_media.py`：日文语言别名归一化；音轨选择（语言优先于默认标记、多匹配取默认并告警、无匹配取首条并告警）；时长取流时长优先、标签与容器矛盾取小并告警、纯音频输入取所选音轨时长；声道布局与声道数回退；采样率标错两个方向都纠正；字幕轨选择（位图、forced、其他语言不可用，多匹配取默认再取最小索引并告警）；视频远长于参考时长则失败。
  - 测试精简（2026-11-22）后不再有测试覆盖：commentary 排除、单条无标签音轨静默采用、无音轨失败、`Extract` 记录字段与不含 `audio_copy`、容器时长兜底与封面图、mp3 封面、采样率检测的适用条件与纠正滤镜次序、不支持布局在 ffmpeg 前失败、字幕与 `derive` 命令行构造、`probe` 命令、ffmpeg 版本解析、解码日志精简与计数（保留首尾各 100 行、类型汇总、长度上限、回车进度）、补偿解析与时长校验的其余分支。
- 测试（full，`just test-full`）：
  - `tests/full/test_media_ffmpeg.py`：用 ffmpeg 合成媒体：音轨延迟 0.5 s 时补静音使样本 0 对齐视频 0；5.1 满幅下混不削波。默认路径的 ffmpeg／ffprobe 缺失时失败而不跳过。
  - 测试精简（2026-11-22）后不再有测试覆盖：中途 2 s 间隙的补入告警、单声道与立体声、音频长于／短于视频、FLAC 与大小端 PCM 只留 WAV 与日志、多音轨选择、解码日志（干净与损坏的 AAC）、路径含空格与非 ASCII。
- 未验证：
  - 采样率纠正无合成测试，只离线验证过 10 个真实音轨（票据 02）；纠正后识别质量未验证；无 `nb_frames` 的容器检测不到。
  - 广播 `.ts`（音轨绝对 `start_time`、PTS 回绕、音频先于视频的负延迟）只按 ffmpeg 默认零点推理，没有真实样本；`6.1`／`7.1` 常量无真实样本。
  - cue 时间等于视频时间只在 WAV 样本层断言，cue 侧只由[日文 cue](../japanese-cues.md)的离线测试断言 offset 只加一次；整片验收没有与视频画面对时。
- 已知限制：日本广播双单声道（主／副音声）按双声道处理；`pan` 保证下混本身不削波，但其后 48→16 kHz 降采样对满幅方波会过冲到 −32768（合成测试因此用 16 kHz 源验证下混系数）。
