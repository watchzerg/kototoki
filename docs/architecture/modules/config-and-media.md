# 配置、配方与媒体提取

状态：current；权威决定：[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)

## 定位与阅读

负责双语字幕流水线（[技术设计](../../specs/bilingual-subtitle-pipeline.md)）的四件事：

- 读取 `kototoki.toml` 得到 `Config`（键、默认值与校验的参考见[配置参考](config-reference.md)）；
- STT／cue／媒体／内嵌字幕的配方常量与 `recipe_hash`；
- 从输入（视频或音频文件）选音轨、派生模型输入 WAV（不流复制原始音轨，ADR-0007「输入范围」）；
- 内嵌日文字幕的选轨、抽取与清洗（`kototoki/media.py`、`kototoki/embedded.py`）。

不负责：是否采用字幕轨、`ja.srt` 与 `ja-embedded.json` 的落盘与跳过判定（[批次编排](batch-orchestration.md)）；翻译配方（`kototoki/translate/recipes.py`）与建表配方（`kototoki/names/recipes.py`）；`probe.json` 等 JSON 产物的身份包装、写入与跳过判定（编排经[产物契约](artifact-contract.md)完成）；VAD／ASR／对齐推理（[STT worker](stt-workers.md)）。现行配方身份见[现行决定](../../adr/CURRENT.md)。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**配置**（`kototoki/config.py`，`load(path, *, environ=os.environ) -> Config`）：`tomllib` 读取，缺省键取 `config.DEFAULTS`，返回全部路径已解析为绝对路径的冻结数据类。键表、默认值与逐键校验见[配置参考](config-reference.md)；本页只写读取行为。

- `paths.input_dir` 没有默认值，必须写出；其余键缺省取默认值。
- 未知节、未知键（含已删除的键）、类型不符（整数键给字符串、布尔键给 1 等）、`stt.engine` 不是 `w0`／`x0`／`cross`（`config.ENGINES`）、`run.extract_workers < 1`、`[translate]`／`[names]` 的 `seed` 不满足 0 < seed < 2**31 均抛 `ConfigError`，消息给出键名；浮点键接受整数。TOML 语法错误与文件读不到同样抛 `ConfigError`。
- 路径：用户写出的相对路径按配置文件所在目录解析，省略键的默认相对路径按仓库根解析；`[vad]`、`[asr.w0]`（含 `mel_assets`）、`[asr.x0]`、`[align]` 的模型路径为相对路径时相对于 `paths.models_root`（绝对路径原样）。
- `load` 只解析路径，不看文件系统；`input_dir` 存在性与位置、`work_dir` 位置由 `__main__` 的 `check_input_dir`／`check_work_dir` 检查（[批次编排](batch-orchestration.md)）。
- 不可配置：GPU 锁固定为仓库内 `.local/gpu.lock`（`Config.gpu_lock`）；`Config.break_stale_lock` 只在环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1` 时为真。
- `[input] use_embedded_subtitles` 不进任何产物身份：走哪条路径由产物本身体现。
- 翻译与建表只有 `seed`；模型由 Strata 管理、端口固定 8080，没有 `model`／`port` 键；建表的提示、采样、schema 与归一规则在 `kototoki/names/recipes.py`，不是配置项。

**配方**（`kototoki/recipes.py`）：`MEDIA`、`VAD`、`W0`、`X0`、`CROSS`、`MMS`、`CUES`、`EMBEDDED` 八个字典；`recipe_hash(recipe)` 是其规范 JSON 的 SHA256（`artifacts.object_hash`），供产物身份的 `recipe_hash` 字段使用。值取自已验证的 demo（来源写在各节注释）。

- VAD：固定设备 `cuda:0`、Pyannote revision `e66f3d3b…`、`source-span-merge-v1`。
- w0：beam 5、FP16、日语、无前文与时间戳 token、128 Mel 特征链，另含整窗守卫块：复读、语速、已知幻听句三个子块（[ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)）；x0：BF16、SDPA、greedy、4096。
- MMS：FP32、`jpn` adapter、字典按模型类数过滤。
- cue：切分顺序、回填方式、整窗回退每字符时长上限 0.25 s（`CUES["fallback_max_char_s"]`，`cues` 直接读它，没有第二份常量）与毫秒取整；数值规则在配置 `[cues]`，作为影响输出的配置键另入身份。
- `SAMPLE_RATE`、`MAX_WINDOW_SAMPLES` 只在 `recipes.py` 定义。

**cross 引擎的配方**：`cross` 需要 `[asr.w0]` 与 `[asr.x0]` 两节的模型路径，不新增配置键。配方 `CROSS`（id `cross-w0-x0-whisper-judge-v1`，hash 由 `tests/core/test_recipes.py` 钉住）嵌入 `W0` 与 `X0` 两个子配方和裁判参数 `judge`：

- 判定阈值 `margin` −1.0、`length_weight` 0.0（无长度项）、打分批上限 `max_batch` 16。
- 打分器与 start_sequence 约定：`tokenizer.sot_sequence` 即 `<|startoftranscript|><|ja|><|transcribe|>`，CT2 自动接 `<|notimestamps|>`，等价于产品无时间戳、无 initial prompt 的提示。
- 规范化与区间规则；文本形式：w0 原文，只替换分歧区间的字符，映射失败退回规范化文本。
- 守卫：`identical_windows`、`empty_result`、`x0_failed_window`、`w0_failed_window`、`score_error`。
- `x0_text_cleaning`：只清 x0 原文中与非 ASCII 字符相邻的空白，w0 原文不动，实现为 `judge.clean_x0`。
- 裁判参数是配方常量而非配置项，一个 `recipe_hash(CROSS)` 覆盖全部，任一子配方或参数变化即新身份。

**下混常量**（`recipes.PAN`，进 `MEDIA` 因而进 hash）：单声道 `anull` 直通；双声道 `pan=mono|c0=0.5*c0+0.5*c1`；`5.1`、`5.1(side)`、`6.1`、`7.1` 用前左右 1、中置 0.707、环绕 0.707、丢 LFE 的权重除以权重和、向下截到 6 位小数，系数和 ≤ 1，满幅同相输入不削波。ffprobe 未给布局时按声道数取 `mono`／`stereo`／`5.1`／`7.1`（`recipes.LAYOUT_BY_CHANNELS`，嵌在 `MEDIA` 里）；其它布局（如 `5.0`、`quad`）报 `MediaError`。不用 `-ac 1`。

**`MEDIA` 覆盖全部影响音频的规则**（id `media-pcm16k-v2`）：下混常量、声道布局映射、重采样、时长容差、采样率标错纠正规则（`sample_rate_correction`）与音轨选择条目（规则说明＋语言别名表 `LANGUAGE_ALIASES`；别名表定义在 `recipes.py`，`media.py` 读它，内嵌字幕选轨同用它）。

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

**内嵌日文字幕**（配方 `recipes.EMBEDDED`，id `embedded-ja-subtitle-v1`，进 `ja-embedded.json` 的身份；开关 `[input] use_embedded_subtitles`）：

- `media.select_subtitle(subtitles, language) -> (stream | None, warnings)`：从 `Probe.subtitles` 里选可用的字幕轨。可用 = 语言标签归一后等于 `language`（编排传 `input.audio_language`）、`codec_name` 在 `EMBEDDED["codecs"]`（`ass`、`mov_text`、`ssa`、`subrip`、`webvtt`）、不是 forced（`parse_probe` 记录的 `forced`：disposition 标了 forced，或 `tags.title` 含 "forced"、不分大小写）。多条可用时取 default 的，再取流索引最小的，并返回一条告警。位图字幕（PGS、VobSub、DVB）与没有语言标签的轨不可用。只看元数据，不看内容。
- `media.extract_subtitle(video, index, ffmpeg) -> str`：`ffmpeg -map 0:<index> -c:s srt -f srt pipe:1`，返回 SRT 文本，不写文件；ffmpeg 非零退出报 `MediaError`。字幕时间与派生 WAV 一样以 ffmpeg 的输入零点为准（容器起点不为 0 时两者同样平移）。
- `embedded.clean(text) -> (srt_text, stats)`（纯函数，只依赖 `srt` 的整数毫秒入口，毫秒格式化不自写）：
  - 自己宽松分条：时间行且上一行是纯数字编号即一条的开头；文字里的空行与数字行不会断条；不用 `srt.parse_srt`。
  - 逐条去掉 `<i>`／`<b>`／`<u>`／`<s>`／`<font>` 标签与 `{\...}` 覆盖块（其它尖括号、不以反斜杠开头的花括号保留），字面的 `\h`、`\N`、`\n` 换成空格，多行并成一行、空白折叠。
  - 丢掉清洗后为空、整条是 ASS 绘图指令（`m 0 0 l …`）、时长非正的条目，以及起止与文字都与已保留条目相同的重复条目；按（起、止）稳定排序，经 `format_srt_ms` 从 1 重新编号。没有可用条目时返回空串。
  - `stats` 只有计数（`source_cues`、`cues`、`dropped_empty`、`dropped_drawing`、`dropped_invalid_time`、`dropped_duplicate`）。不改写时间，不过滤听障字幕的音效说明。
- 规则按 ffmpeg n9.0.2 的实际输出定：ASS 的样式会变成嵌套 `<font>`，对齐留成 `{\an8}`，`\h` 原样留下，绘图指令漏成文字，空事件留成只有标签的条目。
- 是否采用、回退到 STT、`ja.srt` 与 `ja-embedded.json` 的写出与跳过都在编排（[批次编排](batch-orchestration.md)）；计划从哪一阶段起核对在[阶段计划](stage-plan.md)。

## 接口与依赖

`embedded` 是基础层之上的纯函数模块（与 `cues` 同级），只依赖 `srt`，由编排直接调用。`config`、`recipes` 属基础层，只依赖标准库与 `artifacts`；`media` 依赖二者与 ffmpeg／ffprobe 可执行文件（默认是项目内 `.local/tools/ffmpeg/<version>/bin/`，版本由 `assets.toml` 锁定，见[依赖布局与资产清单](../../development/dependencies.md)），不依赖 torch 与网络，编排器在线程池里直接调用。

媒体模块只写 ffmpeg 自身的输出文件（`audio-16k.wav`、`extract.log`；临时文件 `.<名>.<pid>.partial<ext>` 正常结束时自行删除，被强杀留下的残留由编排在下次提取前清理），不读写 JSON 产物、不判断跳过；`MediaError` 由编排记为该文件 extract 阶段失败；`Probe.warnings`／`Extract.warnings` 只作数据返回，本模块不发日志，由编排逐条写进运行日志（[批次编排：运行日志](batch-orchestration.md#运行日志)）。时间轴零点只在本模块定义，下游阶段只传 `offset_s = 0`（[模块边界：产品包的责任边界](../module-boundaries.md#产品包的责任边界)）。

## 代码与验证入口

- 代码：`kototoki/config.py`、`kototoki/recipes.py`、`kototoki/media.py`、`kototoki/embedded.py`、`kototoki.toml.example`。
- 测试（core，`just test`）：
  - `tests/core/test_config.py`：默认值、两种相对路径基准、模型路径、未知键与已删除键、类型、环境变量破锁、示例文件覆盖全部键。
  - `tests/core/test_recipes.py`：`pan` 系数与归一化、不削波、重采样参数、`LAYOUT_BY_CHANNELS`、音轨选择（含 `LANGUAGE_ALIASES`）与采样率纠正规则进 hash、固定值、无翻译配方；`MEDIA`、`VAD`、`W0`、`X0`、`CROSS`、`MMS`、`CUES`、`EMBEDDED` 的 hash 全部钉住。
  - `tests/core/test_media.py`：语言归一化、音轨选择各分支、时长来源（含音频输入）、命令行构造、`Extract` 记录不含 `audio_copy`、补偿解析、解码日志精简与计数、采样率标错纠正、时长校验各分支；字幕轨选择、抽取命令行与抽取失败。
  - `tests/core/test_embedded.py`：标签与覆盖块、多行与空行、绘图／空／重复／非正时长条目、排序与重新编号、清洗结果过 `srt.parse_srt`。
- 测试（full，`just test-full`）：
  - `tests/full/test_media_ffmpeg.py`：用 ffmpeg 合成媒体：音轨延迟 0.5 s、中途 2 s 间隙、5.1 满幅、单声道、立体声、音频长于／短于视频、视频里的 FLAC 与大小端 PCM 只留 WAV 与日志、多音轨选择、解码日志（干净与损坏的 AAC）；临时目录含空格与非 ASCII。默认路径的 ffmpeg／ffprobe 缺失时失败而不跳过。
  - `tests/full/test_job_ffmpeg.py`：真实 ffmpeg 合成带 SubRip、ASS、mov_text 字幕轨的片段走完整批次编排，含容器起点 +2 s。
- 未验证：
  - 内嵌字幕：真实片源（流媒体、字幕组 ASS 特效）、假名注音、标签与内容语言不符的轨。
  - 采样率纠正无合成测试，只离线验证过 10 个真实音轨（票据 02）；纠正后识别质量未验证；无 `nb_frames` 的容器检测不到。
  - 广播 `.ts`（音轨绝对 `start_time`、PTS 回绕、音频先于视频的负延迟）只按 ffmpeg 默认零点推理，没有真实样本；`6.1`／`7.1` 常量无真实样本。
  - cue 时间等于视频时间只在 WAV 样本层断言，cue 侧只由[日文 cue](japanese-cues.md)的离线测试断言 offset 只加一次；整片验收没有与视频画面对时。
- 已知限制：日本广播双单声道（主／副音声）按双声道处理；`pan` 保证下混本身不削波，但其后 48→16 kHz 降采样对满幅方波会过冲到 −32768（合成测试因此用 16 kHz 源验证下混系数）。

## 变更与决策来源

- [ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)、[ADR-0025](../../adr/0025-product-package-boundaries.md)、[现行决定](../../adr/CURRENT.md)
- [技术设计](../../specs/bilingual-subtitle-pipeline.md) §1.1、§2
- 归档 tag `archive/2026-11-18-pre-research-restructure` 中：技术设计历史记录 docs/research/2026-11-11-bilingual-pipeline-spec-history.md（§1.2 裁定表、重采样器经过）；计划 docs/plans/architecture-cleanup.md（§3 决定 2：`MEDIA` 补入布局映射与音轨选择规则）；模块页拆出的历史记录 docs/research/acceptance/2026-11-11-module-page-history-orchestration-config.md（真实视频核对与削波实测）；常量来源 experiments/corpus/prepare_round2.py（下混与重采样）、experiments/w0_demo/（vad_candidates.py、asr.py、alignment.py）、experiments/x0_demo/asr.py、experiments/qwen/run_qwen.py
- 验收：[两部整片](../../../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)、[最终验收](../../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)、[swr 回归](../../../research/acceptance/2026-10-16-bilingual-pipeline-swr-regression.md)、[cross 产品路径](../../../research/acceptance/2026-10-19-cross-asr-acceptance.md)、[ffmpeg 9.0 升级](../../../research/acceptance/2026-10-19-ffmpeg-9.0-upgrade.md)
- 票据：归档 tag 中的 .scratch/bilingual-subtitle-pipeline/issues/02-config-and-media.md、`10-resampler-swr.md`、`11-duration-tag.md`；.scratch/cross-asr-judge/；.scratch/name-consistency-product/issues/05-config-assets-plan.md；.scratch/architecture-cleanup/；.scratch/batch-run-fixes/（02：`MEDIA` v2）
