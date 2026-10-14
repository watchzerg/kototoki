# 配置、配方与媒体提取

状态：current（票据 02 交付，2026-10-14）；编排器（票据 06）尚未接入，本页描述已存在的函数与常量。

## 定位与阅读

负责双语字幕流水线（[规格](../../specs/bilingual-subtitle-pipeline.md)、[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md)）的三件事：读取 `kototoki.toml` 得到 `Config`；STT／cue／媒体的配方常量与 `recipe_hash`；从视频选音轨、流复制原始音轨、派生模型输入 WAV。不负责：翻译配方（`kototoki/translate/recipes.py`，票据 05／09）、`probe.json` 等 JSON 产物的身份包装、写入与跳过判定（编排经[产物契约](artifact-contract.md)完成，票据 06）、VAD／ASR／对齐推理（票据 03／07）。上级：[架构总览](../INDEX.md)、[模块边界](../module-boundaries.md)、[目标架构](../bilingual-pipeline-architecture.md)。

## 当前行为规格

**配置**（`kototoki/config.py`，`load(path, environ=os.environ) -> Config`）：`tomllib` 读取规格 §10.1 的结构，返回全部路径已解析为绝对路径的冻结数据类。

- 缺省键取默认值（与规格 §10.1 相同，`kototoki.toml.example` 列出全部键）；`paths.input_dir`、`paths.output_dir` 没有默认值，必须写出。
- 未知节、未知键、类型不符（整数键给字符串、布尔键给 1 等）、`stt.engine` 不是 `w0`／`x0`、`run.extract_workers < 1` 均抛 `ConfigError`，消息给出键名；浮点键接受整数。
- 路径：用户写出的相对路径按配置文件所在目录解析，省略键的默认相对路径按仓库根解析；`[vad]`、`[asr.w0]`、`[asr.x0]`、`[align]`、`[translate]` 的模型路径为相对路径时相对于 `paths.models_root`（绝对路径原样）。
- 不可配置：GPU 锁固定为仓库内 `.local/gpu.lock`（`Config.gpu_lock`）；`Config.break_stale_lock` 只在环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1` 时为真。没有 `break_stale_lock` 与 `[vad] device` 键（写了即为未知键）。

**配方**（`kototoki/recipes.py`）：`MEDIA`、`VAD`、`W0`、`X0`、`MMS`、`CUES` 六个字典，`recipe_hash(recipe)` 是其规范 JSON 的 SHA256（`artifacts.object_hash`），供产物身份的 `recipe_hash` 字段使用。值取自已验证的 demo（来源写在各节注释）：VAD 固定设备 `cuda:0`、Pyannote revision `e66f3d3b…`、`source-span-merge-v1`；w0 beam 5、FP16、日语、无前文与时间戳 token、128 Mel 特征链；x0 BF16、SDPA、greedy、4096；MMS FP32、`jpn` adapter、字典按模型类数过滤；cue 的切分顺序、回填方式与毫秒取整（数值规则在配置 `[cues]`，作为影响输出的配置键另入身份）。

**下混常量**（`recipes.PAN`，进 `MEDIA` 因而进 hash）：单声道 `anull` 直通；双声道 `pan=mono|c0=0.5*c0+0.5*c1`（与基线证据相同）；`5.1`、`5.1(side)`、`6.1`、`7.1` 用前左右 1、中置 0.707、环绕 0.707、丢 LFE 的权重除以权重和、向下截到 6 位小数，系数和 ≤ 1，满幅同相输入不削波。表达式按声道序号引用；ffprobe 未给布局时按声道数取 `mono`／`stereo`／`5.1`／`7.1`；其它布局（如 `5.0`、`quad`）报 `MediaError`。不用 `-ac 1`。

**probe**（`kototoki/media.py`，`probe(path, config) -> Probe`）：ffprobe `-show_streams -show_format` 全部流；原始 JSON 保留在 `Probe.ffprobe`（供 `artifacts.video_identity` 取指纹），`Probe.payload()` 是 `probe.json` 的内容。

- 音轨选择：语言标签归一化后（`jpn`／`ja`／`jp` 大小写不敏感视为 `jpn`，配置值同样归一化）等于 `input.audio_language` 且非 `disposition.comment` 的音轨优先，其中 `disposition.default` 优先、否则取第一条；多条匹配告警；无匹配取第一条音轨并告警；没有音轨报 `MediaError`。
- 记录：所选与全部音轨的绝对流索引、编码、声道数与布局、采样率、语言、default／comment、`start_time` 与时长（只作诊断，不进时间轴）；容器 `start_time`；字幕流清单（索引、编码、语言、default、forced，第一版不使用）；告警列表。
- 视频流时长：第一条非封面视频流的 `duration`，没有时取 Matroska 标签 `DURATION` 或 mkvmerge 统计标签 `DURATION-<lang>`，都没有时退回容器时长并告警；没有视频流或时长全无报 `MediaError`。

**extract**（`extract(path, work_dir, probe, config) -> Extract`）：先校验下混布局，再依次运行两条 ffmpeg 命令，各写同目录临时文件（保留扩展名）后原子替换目标。

1. `extract_original`：`-map 0:<绝对索引> -c:a copy` 写出 `audio.<ext>`，容器按规格 §2.1：`flac`→`.flac`、`aac`／`alac`→`.m4a`、`ac3`、`eac3`、`dts`、`opus`、`vorbis`→`.ogg`、`mp3`，小端 PCM（`pcm_s16le`／`s24le`／`s32le`／`f32le`）→`.wav`（`-rf64 auto`），其余（大端 PCM、`pcm_bluray`、`pcm_dvd`、`aac_latm`、`truehd` 等）→`.mka`。
2. `derive_pcm16k`：**从视频容器**按同一绝对索引解码，`-af aresample=async=1:first_pts=0,<PAN>,<重采样>`、`pcm_s16le`、`-fflags +bitexact -flags:a +bitexact`，`-loglevel verbose`；`<重采样>` 是 `aresample=16000:resampler=soxr:precision=28`（时间轴补偿那一步仍是 swr，同采样率只插静音／丢样）；两条命令行与 stderr 写入 `extract.log`。起始延迟补静音、中途间隙补零，WAV 的 sample 0 即视频 0 秒，`Extract.offset_s` 恒为 0。
3. 时长校验对**视频流时长**：解码短于视频超过 1 s 抛 `MediaError` 且不留下 `audio-16k.wav`（日志保留）；长于视频超过 1 s 只记告警。
4. `Extract` 记录 PCM 数据块 SHA256、样本数、解码时长、所用 `pan`、告警与补偿统计 `compensation`：swr 在 verbose 下报告的"adding N audio samples of silence"／"discarding N audio samples"之和（输入采样率，含起始补齐），以及按 ffmpeg 结束统计的输入样本数算出的净补偿秒数 `net_padding_s`（派生时长 − 解码出的输入时长）。实测 swr 只报告一部分补偿（合成 2 s 间隙只报出约 0.63 s），因此以 `net_padding_s` 为准，swr 计数只作参考。

子进程一律参数列表、`stdin=DEVNULL`（ffmpeg 另加 `-nostdin`；ffprobe 不认 `-nostdin`）、UTF-8 解码；路径含空格与非 ASCII 已测。

## 接口与依赖

`config`、`recipes` 属基础层，只依赖标准库与 `artifacts`；`media` 依赖二者与外部 ffmpeg／ffprobe 可执行文件，不依赖 torch 与网络，编排器在线程池里直接调用。媒体模块只写 ffmpeg 自身的输出文件（`audio.<ext>`、`audio-16k.wav`、`extract.log`），不读写 JSON 产物、不判断跳过；`MediaError` 由编排记为该文件 extract 阶段失败。时间轴零点只在本模块定义，下游阶段只传 `offset_s = 0`（[目标架构：责任边界](../bilingual-pipeline-architecture.md#责任边界)）。

## 代码与验证入口

- 代码：`kototoki/config.py`、`kototoki/recipes.py`、`kototoki/media.py`、`kototoki.toml.example`。
- 测试（core，`just test`）：`tests/test_config.py`（默认值、两种相对路径基准、模型路径、未知键与已删除键、类型、环境变量破锁、示例文件覆盖全部键）、`tests/test_recipes.py`（`pan` 系数与归一化、不削波、`pan`／重采样参数进 hash、固定值、无翻译配方）、`tests/test_media.py`（语言归一化、音轨选择含 commentary／多条匹配／无匹配、视频时长来源、容器映射、命令行构造、补偿解析、时长校验）、`tests/test_media_ffmpeg.py`（用本机 ffmpeg 合成媒体：音轨延迟 0.5 s、中途 2 s 间隙、5.1 满幅、单声道、立体声、音频长于／短于视频、流复制容器、多音轨选择；临时目录含空格与非 ASCII）。合成测试需要 `D:/bin/ffmpeg.exe`、`ffprobe.exe`（配置默认值），缺失时测试失败而不是跳过。
- 真实视频（2026-10-14，ffmpeg 2026-10-01 gyan.dev full build，不进 Git）：Heaven's Feel II（mkv，FLAC 立体声）产出三份产物（112448683 样本，PCM SHA256 `c203f952…`），视频流时长取自 `DURATION-eng`；改 soxr 之前用默认 swr 跑同一条链，PCM SHA256 `ee4e2da3…` 与基线 `hf-ii-full.wav` 一致，说明零点补齐与下混未改变样本，差异只来自重采样器（对比数据见规格 §2.2）；Black Panther（mkv，12 条音轨，选中 jpn E-AC-3 `5.1(side)`）产出 `audio.eac3`、`audio-16k.wav`、`extract.log`。
- 未验证：广播 `.ts`（音轨绝对 `start_time`、PTS 回绕、音频先于视频的负延迟）只按 ffmpeg 默认零点推理，没有真实样本；`6.1`／`7.1` 常量无真实样本；cue 时间等于视频时间目前只在 WAV 样本层断言（`sample / 16000 + offset_s`），经 cue 阶段的断言待票据 04。日本广播双单声道（主／副音声）按双声道处理，是已知限制。已知限制：`pan` 保证下混本身不削波，但其后的降采样滤波（48 kHz→16 kHz，swr 与 soxr 都会）对满幅方波这类信号会过冲到 −32768（合成测试因此用 16 kHz 源单独验证下混系数）；真实素材实测（2026-10-14）：HF II 派生 WAV 1.12 亿样本中 swr 版 1 个、soxr 版 2 个样本到满幅；Black Panther（swr 版）峰值 31073、无削波。

## 变更与决策来源

票据 `.scratch/bilingual-subtitle-pipeline/issues/02-config-and-media.md`；规格 §1.2 第三轮裁定表、§2.1、§2.2、§10。下混与重采样参数取自 `experiments/corpus/prepare_round2.py`，配方常量取自 `experiments/w0_demo/`（`vad_candidates.py`、`asr.py`、`alignment.py`）、`experiments/x0_demo/asr.py`、`experiments/qwen/run_qwen.py`。
