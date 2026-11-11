# 配置、配方与媒体提取

状态：current（票据 02 交付，2026-10-14；2026-11-11 加内嵌日文字幕的选轨、抽取与清洗，[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)）；编排器调用见[批次编排](batch-orchestration.md)（票据 06）。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)）的三件事：读取 `kototoki.toml` 得到 `Config`；STT／cue／媒体的配方常量与 `recipe_hash`；从输入（视频或音频文件）选音轨、视频的流复制原始音轨、派生模型输入 WAV；以及内嵌日文字幕的选轨、抽取与清洗（`kototoki/media.py`、`kototoki/embedded.py`，见下方"内嵌日文字幕"）。不负责：是否采用字幕轨、`ja.srt` 与 `ja-embedded.json` 的落盘与跳过判定（编排）、翻译配方（`kototoki/translate/recipes.py`，Q2 `q2-degrade-v1`）、`probe.json` 等 JSON 产物的身份包装、写入与跳过判定（编排经[产物契约](artifact-contract.md)完成，票据 06）、VAD／ASR／对齐推理（票据 03／07）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)。

## 当前行为规格

**配置**（`kototoki/config.py`，`load(path, environ=os.environ) -> Config`）：`tomllib` 读取规格 §10.1 的结构，返回全部路径已解析为绝对路径的冻结数据类。

- 缺省键取默认值（与规格 §10.1 相同，`kototoki.toml.example` 列出全部键）；`paths.input_dir` 没有默认值，必须写出；`paths.work_dir`（缓存与各目标目录的工作根）默认仓库内 `.local/work`（ADR-0020），没有 `output_dir`。`[input] extensions`（替代 `video_extensions`）默认是视频 `.mkv .mp4 .m2ts .ts .mov .avi` 加音频 `.wav .flac .mp3 .m4a .aac .ogg .opus .mka`；`[run]` 没有 `force`。`load` 只解析路径，不看文件系统；`input_dir` 必须是已存在的目录且不得位于仓库内（`.local/` 除外）、`work_dir` 不得位于 `input_dir` 内也不得位于仓库内（`.local/` 除外），由 `__main__` 的 `check_input_dir`／`check_work_dir` 检查（[批次编排](batch-orchestration.md)）。
- `[input] use_embedded_subtitles`（布尔，默认 `true`）：有可用的日文文本字幕轨时跳过 STT（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)，见下方"内嵌日文字幕"）；`false` 时一律走 STT。它不进任何产物身份：走哪条路径由产物本身体现。
- `[translate]`（[翻译子系统](translation-subsystem.md)）只有 `seed`（默认 20261008，须为小于 2**31 的正整数，Strata 不接受 0；改 seed 即另起翻译 run）。翻译模型由 Strata 自己管理、端口固定 8080，没有 `model`／`port` 键，写了按未知键报错（[ADR-0019](../../adr/0019-product-translation-q2.md)）。
- 未知节、未知键、类型不符（整数键给字符串、布尔键给 1 等）、`stt.engine` 不是 `w0`／`x0`／`cross`、`run.extract_workers < 1` 均抛 `ConfigError`，消息给出键名；浮点键接受整数。
- 路径：用户写出的相对路径按配置文件所在目录解析，省略键的默认相对路径按仓库根解析；`[vad]`、`[asr.w0]`、`[asr.x0]`、`[align]` 的模型路径为相对路径时相对于 `paths.models_root`（绝对路径原样）。
- `[names]`（专名建表，[专名一致性](name-consistency.md)）只有 `seed`（默认 20261019，进表的身份，改 seed 即重建表）。建表必开，没有 `enabled` 键；建表模型由与翻译共用的 Strata 管理、端口固定 8080，没有 `model`／`port` 键，`[paths]` 也没有 `llama_server`（[ADR-0022](../../adr/0022-product-names-on-strata.md)；写了按未知键报错）。提示、采样、schema、上下文与归一规则不是配置项，在 `kototoki/names/recipes.py` 的建表配方里。
- 不可配置：GPU 锁固定为仓库内 `.local/gpu.lock`（`Config.gpu_lock`）；`Config.break_stale_lock` 只在环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1` 时为真。没有 `break_stale_lock` 与 `[vad] device` 键（写了即为未知键）。

**配方**（`kototoki/recipes.py`）：`MEDIA`、`VAD`、`W0`、`X0`、`CROSS`、`MMS`、`CUES`、`EMBEDDED`（内嵌日文字幕，见下）八个字典，`recipe_hash(recipe)` 是其规范 JSON 的 SHA256（`artifacts.object_hash`），供产物身份的 `recipe_hash` 字段使用。值取自已验证的 demo（来源写在各节注释）：VAD 固定设备 `cuda:0`、Pyannote revision `e66f3d3b…`、`source-span-merge-v1`；w0 beam 5、FP16、日语、无前文与时间戳 token、128 Mel 特征链；x0 BF16、SDPA、greedy、4096；MMS FP32、`jpn` adapter、字典按模型类数过滤；cue 的切分顺序、回填方式、整窗回退每字符时长上限 0.25 s（与 `cues.FALLBACK_MAX_CHAR_S` 相等，有测试钉住）与毫秒取整（数值规则在配置 `[cues]`，`max_gap_s` 默认 1.0（票据 04），作为影响输出的配置键另入身份）。

**cross 引擎的配置与配方**（[ADR-0012](../../adr/0012-cross-asr-judge.md)）：`stt.engine` 接受 `w0 | x0 | cross`（`config.ENGINES`），默认仍为 `w0`，其它值抛 `ConfigError`。`cross` 需要 `[asr.w0]` 与 `[asr.x0]` 两节的模型路径（默认值已存在），不新增配置键。配方字典共七个，第七个 `CROSS`（id `cross-w0-x0-whisper-judge-v1`，当前 `recipe_hash` 以 `ab9f4532…` 开头，由 `tests/core/test_recipes.py` 钉住）嵌入 `W0` 与 `X0` 两个子配方和裁判参数 `judge`：判定阈值 `margin` −1.0、`length_weight` 0.0（无长度项）、打分批上限 `max_batch` 16、打分器与 start_sequence 约定（`tokenizer.sot_sequence` 即 `<|startoftranscript|><|ja|><|transcribe|>`，CT2 自动接 `<|notimestamps|>`，等价于产品无时间戳、无 initial prompt 的提示）、规范化与区间规则、文本形式（w0 原文，只替换分歧区间的字符，映射失败退回规范化文本）、守卫（`identical_windows`、`empty_result`、`x0_failed_window`、`w0_failed_window`、`score_error`）与 `x0_text_cleaning`（`recipes.CROSS["judge"]["x0_text_cleaning"]`：只清 x0 原文中与非 ASCII 字符相邻的空白，w0 原文不动，实现为 `workers.asr.clean_x0`）。裁判参数是配方常量而非配置项，一个 `recipe_hash(CROSS)` 覆盖全部，任一子配方或参数变化即新身份。

**下混常量**（`recipes.PAN`，进 `MEDIA` 因而进 hash）：单声道 `anull` 直通；双声道 `pan=mono|c0=0.5*c0+0.5*c1`（与基线证据相同）；`5.1`、`5.1(side)`、`6.1`、`7.1` 用前左右 1、中置 0.707、环绕 0.707、丢 LFE 的权重除以权重和、向下截到 6 位小数，系数和 ≤ 1，满幅同相输入不削波。表达式按声道序号引用；ffprobe 未给布局时按声道数取 `mono`／`stereo`／`5.1`／`7.1`；其它布局（如 `5.0`、`quad`）报 `MediaError`。不用 `-ac 1`。

**probe**（`kototoki/media.py`，`probe(path, config) -> Probe`）：ffprobe `-show_streams -show_format` 全部流；原始 JSON 保留在 `Probe.ffprobe`（供 `artifacts.video_identity`（视频与音频同用）取指纹），`Probe.payload()` 是 `probe.json` 的内容。

- 音轨选择：语言标签归一化后（`jpn`／`ja`／`jp` 大小写不敏感视为 `jpn`，配置值同样归一化）等于 `input.audio_language` 且非 `disposition.comment` 的音轨优先，其中 `disposition.default` 优先、否则取第一条；多条匹配告警；无匹配取第一条音轨并告警；没有音轨报 `MediaError`。
- 记录：所选与全部音轨的绝对流索引、编码、声道数与布局、采样率、语言、default／comment、`start_time` 与时长（只作诊断，不进时间轴）；容器 `start_time`；字幕流清单（索引、编码、语言、default、forced，供内嵌日文字幕选轨）；告警列表。
- 时长参照与 `has_video`：除封面图（`attached_pic`）外没有视频流即为音频输入（`Probe.has_video = False`，ADR-0020）。参照时长对视频输入是第一条非封面视频流，对音频输入是所选音轨；取其 `duration`，没有时先取精确的 Matroska 标签 `DURATION`（大小写不敏感），再取 mkvmerge 统计标签 `DURATION-<lang>`，都没有时退回容器时长并告警；标签来源与 `format.duration` 相差超过 `MEDIA["duration_tolerance_s"]` 时取较小者并写入 `Probe.warnings`、`duration_source` 记实际来源（票据 11 修复：ffmpeg `-c copy` 剪辑保留原片 `DURATION-eng` 时曾被误判为截断）；时长全无报 `MediaError`。`probe.json` 的字段是 `has_video`、`duration_s`、`duration_source`。

**extract**（`extract(path, work_dir, probe, config) -> Extract`）：先校验下混布局，再依次运行 ffmpeg 命令（视频两条，音频输入只有第 2 条），各写同目录临时文件（保留扩展名）后原子替换目标。

1. `extract_original`（仅 `has_video`；音频输入跳过，`Extract.audio_copy` 为 null、`extract.audio_copy` 记 null，源文件本身即原始音频，工作目录无 `audio.<ext>`）：`-map 0:<绝对索引> -c:a copy` 写出 `audio.<ext>`，容器按规格 §2.1：`flac`→`.flac`、`aac`／`alac`→`.m4a`、`ac3`、`eac3`、`dts`、`opus`、`vorbis`→`.ogg`、`mp3`，小端 PCM（`pcm_s16le`／`s24le`／`s32le`／`f32le`）→`.wav`（`-rf64 auto`），其余（大端 PCM、`pcm_bluray`、`pcm_dvd`、`aac_latm`、`truehd` 等）→`.mka`。
2. `derive_pcm16k`：**从输入容器**按同一绝对索引解码，`-af aresample=async=1:first_pts=0,<PAN>,<重采样>`、`pcm_s16le`、`-fflags +bitexact -flags:a +bitexact`，`-loglevel verbose`；`<重采样>` 是 `aresample=16000`（ffmpeg 默认 swr；2026-10-14 曾改 soxr 28 bit，2026-10-15 因 Pyannote 少保留语音改回，票据 10）；两条命令行与 stderr 写入 `extract.log`。起始延迟补静音、中途间隙补零，WAV 的 sample 0 即输入 0 秒，`Extract.offset_s` 恒为 0。
3. 时长校验对**参照时长**（视频输入的视频流、音频输入的所选音轨，字段 `Extract.duration_s`）：视频输入解码短于参照超过 1 s 抛 `MediaError` 且不留下 `audio-16k.wav`（日志保留）；音频输入短于参照只记告警、照常往下走（`check_duration(…, has_video=False)`；VBR MP3 缺 Xing 头时 ffprobe 的时长是估算值，ADR-0020）；长于参照超过 1 s 一律只记告警。
4. `Extract` 记录 PCM 数据块 SHA256、样本数、解码时长、所用 `pan`、告警与补偿统计 `compensation`：swr 在 verbose 下报告的"adding N audio samples of silence"／"discarding N audio samples"之和（输入采样率，含起始补齐），以及按 ffmpeg 结束统计的输入样本数算出的净补偿秒数 `net_padding_s`（派生时长 − 解码出的输入时长）。实测 swr 只报告一部分补偿（合成 2 s 间隙只报出约 0.63 s），因此以 `net_padding_s` 为准，swr 计数只作参考。本模块只返回这些数据；`net_padding_s` 或丢弃样本折算超过 0.1 s 时的 WARNING 由编排写进运行日志（[批次编排](batch-orchestration.md) 的 `compensation_warnings`）。

子进程一律参数列表、`stdin=DEVNULL`（ffmpeg 另加 `-nostdin`；ffprobe 不认 `-nostdin`）、UTF-8 解码；路径含空格与非 ASCII 已测。

**内嵌日文字幕**（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)；配方 `recipes.EMBEDDED`，id `embedded-ja-subtitle-v1`，进 `ja-embedded.json` 的身份；开关 `[input] use_embedded_subtitles`，默认 `true`）：

- `media.select_subtitle(subtitles, language) -> (stream | None, warnings)`：从 `Probe.subtitles` 里选可用的字幕轨。可用 = 语言标签归一后等于 `language`（编排传 `input.audio_language`）、`codec_name` 在 `EMBEDDED["codecs"]`（`ass`、`mov_text`、`ssa`、`subrip`、`webvtt`）、不是 forced。多条可用时取 default 的，再取流索引最小的，并返回一条告警。位图字幕（PGS、VobSub、DVB）与没有语言标签的轨不可用。只看元数据，不看内容。
- `media.extract_subtitle(video, index, ffmpeg) -> str`：`ffmpeg -map 0:<index> -c:s srt -f srt pipe:1`，返回 SRT 文本，不写文件；ffmpeg 非零退出报 `MediaError`。字幕时间与派生 WAV 一样以 ffmpeg 的输入零点为准（容器起点不为 0 时两者同样平移，full 测试覆盖 +2 s）。
- `embedded.clean(text) -> (srt_text, stats)`（`kototoki/embedded.py`，纯函数，只依赖 `srt.format_srt`）：自己宽松分条（时间行且上一行是纯数字编号即一条的开头；文字里的空行与数字行不会断条），不用 `srt.parse_srt`。逐条去掉 `<i>`／`<b>`／`<u>`／`<s>`／`<font>` 标签与 `{\...}` 覆盖块（其它尖括号、不以反斜杠开头的花括号保留），字面的 `\h`、`\N`、`\n` 换成空格，多行并成一行、空白折叠；丢掉清洗后为空、整条是 ASS 绘图指令（`m 0 0 l …`）、时长非正的条目，以及起止与文字都与已保留条目相同的重复条目；按（起、止）稳定排序，经 `format_srt` 从 1 重新编号。没有可用条目时返回空串。`stats` 只有计数（`source_cues`、`cues`、`dropped_empty`、`dropped_drawing`、`dropped_invalid_time`、`dropped_duplicate`）。不改写时间，不过滤听障字幕的音效说明。
- 规则按 ffmpeg n9.0.2 的实际输出定：ASS 的样式会变成嵌套 `<font>`，对齐留成 `{\an8}`，`\h` 原样留下，绘图指令漏成文字，空事件留成只有标签的条目。
- 是否采用、回退到 STT、`ja.srt` 与 `ja-embedded.json` 的写出与跳过都在编排（[批次编排](batch-orchestration.md)）；计划从哪一阶段起核对在[阶段计划](stage-plan.md)。

## 接口与依赖

`embedded` 是基础层之上的纯函数模块（与 `cues` 同级），只依赖 `srt`，由编排直接调用。`config`、`recipes` 属基础层，只依赖标准库与 `artifacts`；`media` 依赖二者与 ffmpeg／ffprobe 可执行文件（默认是项目内 `.local/tools/ffmpeg/<version>/bin/`，版本由 `assets.toml` 锁定），不依赖 torch 与网络，编排器在线程池里直接调用。媒体模块只写 ffmpeg 自身的输出文件（`audio.<ext>`、`audio-16k.wav`、`extract.log`；临时文件 `.<名>.<pid>.partial<ext>` 正常结束时自行删除，被强杀留下的残留由编排在下次提取前清理），不读写 JSON 产物、不判断跳过；`MediaError` 由编排记为该文件 extract 阶段失败；`Probe.warnings`／`Extract.warnings` 只作数据返回，本模块不发日志，由编排逐条写进运行日志（[批次编排：运行日志](batch-orchestration.md#运行日志)）。时间轴零点只在本模块定义，下游阶段只传 `offset_s = 0`（[模块边界：产品包的责任边界](../module-boundaries.md#产品包的责任边界)）。

## 代码与验证入口

- 代码：`kototoki/config.py`、`kototoki/recipes.py`、`kototoki/media.py`、`kototoki/embedded.py`、`kototoki.toml.example`。
- 内嵌日文字幕的测试：core 为 `tests/core/test_embedded.py`（标签与覆盖块、多行与空行、绘图／空／重复／非正时长条目、排序与重新编号、清洗结果过 `srt.parse_srt`）与 `tests/core/test_media.py` 的选轨、命令行与抽取失败；full 为 `tests/full/test_job_ffmpeg.py`（真实 ffmpeg 合成带 SubRip、ASS、mov_text 字幕轨的片段走完整批次编排，含容器起点 +2 s）。未验证：真实片源（流媒体片源、字幕组 ASS 的卡拉 OK 与屏幕字噪声）、假名注音、标签与内容语言不符的字幕轨。
- 测试（core，`just test`）：`tests/core/test_config.py`（默认值、两种相对路径基准、模型路径、未知键与已删除键、类型、环境变量破锁、示例文件覆盖全部键）、`tests/core/test_recipes.py`（`pan` 系数与归一化、不削波、`pan`／重采样参数进 hash、固定值、无翻译配方）、`tests/core/test_media.py`（语言归一化、音轨选择含 commentary／多条匹配／无匹配、时长来源（含音频输入）、容器映射、命令行构造、补偿解析、时长校验含音频输入偏短只告警）。
- 测试（full，`just test-full`）：`tests/full/test_media_ffmpeg.py`（用 ffmpeg 合成媒体：音轨延迟 0.5 s、中途 2 s 间隙、5.1 满幅、单声道、立体声、音频长于／短于视频、流复制容器、多音轨选择；临时目录含空格与非 ASCII）。合成测试需要配置默认路径的 `ffmpeg.exe`、`ffprobe.exe`，缺失时测试失败而不是跳过。
- 真实视频（2026-10-14，ffmpeg 2026-10-01 gyan.dev full build，不进 Git）：Heaven's Feel II（mkv，FLAC 立体声）产出三份产物（112448683 样本；默认 swr 下 PCM SHA256 `ee4e2da3…` 与基线 `hf-ii-full.wav` 一致，票据 02 与票据 10 改回后各核对一次；2026-10-14 至 10-15 的 soxr 版为 `c203f952…`，说明零点补齐与下混未改变样本，差异只来自重采样器，对比数据见规格 §2.2），视频流时长取自 `DURATION-eng`（该文件没有精确 `DURATION`）；Black Panther（mkv，12 条音轨，选中 jpn E-AC-3 `5.1(side)`）产出 `audio.eac3`、`audio-16k.wav`、`extract.log`。
- 未验证：广播 `.ts`（音轨绝对 `start_time`、PTS 回绕、音频先于视频的负延迟）只按 ffmpeg 默认零点推理，没有真实样本；`6.1`／`7.1` 常量无真实样本（5.1(side) ac3 真实片段已在[最终验收](../../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)通过）；cue 时间等于视频时间目前只在 WAV 样本层断言（`sample / 16000 + offset_s`），cue 侧只由[日文 cue](japanese-cues.md)的离线测试断言 offset 只加一次；整片验收只核对了三份 SRT 时间一致，没有与视频画面对时。日本广播双单声道（主／副音声）按双声道处理，是已知限制。已知限制：`pan` 保证下混本身不削波，但其后的降采样滤波（48 kHz→16 kHz，swr 与 soxr 都会）对满幅方波这类信号会过冲到 −32768（合成测试因此用 16 kHz 源单独验证下混系数）；真实素材实测（2026-10-14）：HF II 派生 WAV 1.12 亿样本中 swr 版 1 个、soxr 版 2 个样本到满幅；Black Panther（swr 版）峰值 31073、无削波。

## 变更与决策来源

2026-11-11 内嵌日文字幕（[ADR-0024](../../adr/0024-embedded-japanese-subtitles.md)，用户裁定：默认开启、ASS 进第一版、听障说明原样保留、外挂字幕不做）：加 `[input] use_embedded_subtitles`、`recipes.EMBEDDED`、`media.select_subtitle`／`extract_subtitle`、`kototoki/embedded.py`。

票据 `.scratch/bilingual-subtitle-pipeline/issues/02-config-and-media.md`、`10-resampler-swr.md`、`11-duration-tag.md`；规格 §1.2 第三轮裁定表、§2.1、§2.2、§10。下混与重采样参数取自 `experiments/corpus/prepare_round2.py`，配方常量取自 `experiments/w0_demo/`（`vad_candidates.py`、`asr.py`、`alignment.py`）、`experiments/x0_demo/asr.py`、`experiments/qwen/run_qwen.py`。

2026-10-18 吸收增量说明《依赖入项目与测试分层调整》（`docs/changes/local-dependencies-and-test-layers.md`，已删除）：ffmpeg 默认路径改指项目内 `.local/tools/ffmpeg/<version>/bin/`，构建与身份锁在 `assets.toml`（[依赖布局与资产清单](../../development/dependencies.md)）；`test_media_ffmpeg` 移入 full 层。

2026-10-19 `cross` 引擎交付，依据 [ADR-0012](../../adr/0012-cross-asr-judge.md) 与[产品路径验收](../../research/acceptance/2026-10-19-cross-asr-acceptance.md)，票据 `.scratch/cross-asr-judge/`；增量说明已吸收进本页（配置与配方）并删除。

2026-10-19 专名一致性进产品（[ADR-0014](../../adr/0014-name-consistency-in-product.md)）：票据 `.scratch/name-consistency-product/issues/05-config-assets-plan.md` 加 `[names]` 节，06 同步本页。
