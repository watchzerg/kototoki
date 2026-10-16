# 中日双语字幕批量生产流水线：技术设计

状态：implemented（2026-10-14，票据 00–09 交付，两部整片验收见[验收记录](../research/acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)；2026-10-15 最终验收后票据 10–15 完成，票据 13 裁定不实现，见 §13）。设计收口于 2026-10-13，2026-10-14 按三轮评审修订并改为 CUDA 12 统一环境（§13）；取舍记录在 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)。当前行为以[架构总览](../architecture/INDEX.md)中的产品模块页为准，本文保留设计依据与裁定  
日期：2026-10-13  
范围：第一个正式产品形态，命令行工具，输入一批日语视频，输出日文 SRT、中文 SRT 与中日双语 SRT。不含 UI、流式、打包、非日语输入。

## 1. 目标与边界

- 输入：若干本地视频文件（或目录）。音频默认视为日语对白。
- 输出（每个视频）：`<stem>.ja.srt`、`<stem>.zh.srt`、`<stem>.ja-zh.srt`。
- 第一版没有命令行参数：入口 `python -m kototoki [kototoki.toml]` 只读一份配置文件（§10），输入目录、输出目录、模型目录、各组件需要关注的参数都在里面。质量基线直接复用已采纳的配方；影响模型行为的解码／采样／提示常量不进配置文件，作为配方常量留在代码里（§10.2）。
- 产品不变量继续生效：本地运行、ASR／CTC／翻译只跑 GPU 不回退 CPU、保留日语原文、音频与转写不进 Git 与日志。

### 1.1 固定配方（写死，不做配置项）

| 阶段 | 固定选择 | 依据 |
| --- | --- | --- |
| 音频分离 | ① ffmpeg 流复制（`-c:a copy`）保留原始编码，不转码；② 模型输入直接从视频容器按绝对流索引解码（不是从 ① 的裸码流），带时间戳对齐（WAV 的 sample 0 即视频 0 秒，`offset_s` 恒为 0）、按声道布局下混单声道、重采样 16 kHz、PCM16 WAV | 用户要求无损保留原格式；两套 demo 与整片证据的输入身份是 16 kHz 单声道 PCM16；裸码流容器丢时间戳，见 §2.2 |
| VAD 与分窗 | Pyannote `segmentation-3.0`（revision `e66f3d3b…`），powerset 原生检测，onset／offset 0.5，`source-span-merge-v1`：≤30 s、整数样本坐标、保留块内间隙 | [ADR-0003](../adr/0003-new-pyannote-baselines.md) |
| ASR `w0`（默认） | faster-whisper large-v3（CT2 FP16），固定日语，beam 5，batch 1，逐窗独立、无前文、无时间戳 token，移植的 Whisper 特征链 | [W0 契约](w0-reusable-demo.md) |
| ASR `x0` | Qwen3-ASR-1.7B-hf，CUDA BF16、SDPA、greedy、`max_new_tokens` 4096，原生 processor | [X0 契约](x0-reusable-demo.md) |
| 强制对齐 | MMS-1b-all `jpn` adapter，CUDA FP32，窗口归一化，字符级 CTC 对齐，`text_only` 记账 | [MMS 对齐](../architecture/modules/mms-alignment.md) |
| 日文字幕切分 | 从字符 units 组 cue，规则数值来自配置文件（§5.2 给出初值） | [显示契约](../testing/demo-display-contract.md)为起点 |
| 翻译 | Hy-MT2 30B-A3B APEX-I-Compact，`official30b-cached-v1` 采样，流程 `b10-joint`（每批 10 条，前后各 1 条只读邻文，即 1-10-1） | [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md)、[ADR-0006](../adr/0006-b10-joint-translation-flow-baseline.md) |
| 双语合并 | 同一 cue 编号与时间，两行：中文在上、日文在下 | 用户裁定 |

### 1.2 已裁定（2026-10-13）

| 事项 | 结论 |
| --- | --- |
| 默认 STT 引擎 | `w0`；两片合并 CER 15.25% 对 x0 16.68%，推理快约 2.5 倍，无生成触顶 |
| 批次粒度 | 第一版不提供 `--batch-size`，整批按阶段推进 |
| 无时间字符 | 产品端插值＋整窗回退，在 cue 文件里记账；内部方案另行细聊 |
| 音频产物 | 原始编码流复制保留；派生的 16 kHz WAV 也保留，不删除 |
| 输出位置 | `--out <dir>` 顶层放最终 SRT，工作目录在 `<dir>/.work/`；不写到视频旁边 |
| 双语行序 | 中文在上、日文在下，无选项 |
| cue 切分数值 | 由实现方给出初值并放配置文件，后续按真实输出调整 |
| Python 环境的 CUDA 版本 | **整体 CUDA 12.8**（2026-10-14 替代原方案 A）：torch 2.11.0+cu128 与 CTranslate2 共用 torch 的 CUDA 12 运行时（CT2 自带的 cuDNN 调度器例外，见 §7.2），不再有侧车与无 torch worker；llama-server 为独立进程，保留官方 CUDA 13.4 构建 |
| Python 版本 | 3.13（3.15 无 CT2／torchaudio／torchcodec wheel，不可用；3.14 边角依赖未核） |
| 环境管理 | 单一根项目：根 `pyproject.toml` 即产品，uv 管理，Torch 走显式 cu128 索引（实现方选择，见 §7.2） |
| 入口形态 | 第一版不做 CLI，入口只读配置文件；输入／输出／模型目录与组件参数全部在配置文件里 |
| cue 切分初值 | 接受 §5.2 的初值作为起点 |
| 流复制容器 | 按编码选最合适的容器，其余退回 `.mka`（映射见 §2.1，实现方选择） |
| 回归测试 | 本期只讨论工程架构，升级后的回归与容差推迟到实现之后 |
| 翻译批内对应 | 本期 1+10+1 中间 10 条与中文一一对应；批内语序自由调整属未来方向（§11） |
| 配置文件边界 | 按 §10.2：路径、并发、显示规则、seed 进配置；解码／采样／提示常量留在代码 |
| 翻译失败降级 | 批次终态失败自动 10→5→1 拆批重试；单条仍失败则保留日文并写入报告，整片照常交付 |
| cue 结束延长 | `lead_out_s` 初值 0.3 s，向后延长不越过下一条起点 |
| 输出目录 | 镜像输入目录的子目录层级 |
| 里程碑 | 由实现方拆分并建票（§12） |
| 下混 | 单声道直通；双声道沿用 0.5/0.5；5.1 以上用 ffmpeg 标准矩阵含中置 |
| 重采样器 | ffmpeg 默认 swr（`aresample=16000`，2026-10-15 用户裁定由 soxr 28 bit 改回，票据 10）；派生 WAV 与基线 `hf-ii-full.wav` 逐字节一致 |
| 翻译引擎 | 官方 llama.cpp b11583 win-cuda-13.4 替代 ADR-0005 的 b11429 兼容引擎条款 |
| 产品翻译配方 | `b10-joint-degrade-v1` |

第三轮评审（2026-10-14，独立评审）采纳的裁定：

| 事项 | 结论 |
| --- | --- |
| 时间轴零点 | 派生 WAV 用 `async=1:first_pts=0` 补齐起始静音，sample 0 即视频 0 秒；`offset_s` 恒为 0，音轨 `start_time` 只进 `probe.json` 作诊断，不再贯穿链路（§2.2） |
| 产物坐标系 | 各阶段 JSON 一律本地秒（与 WAV 一致）＋顶层 `offset_s`；cue 时间只在 ja-cues 阶段加一次 offset（§4） |
| 5.1 下混 | 每种声道布局的 `pan` 表达式写死为配方常量，含归一化系数，禁止削波（§2.2） |
| 时长校验 | 对照视频流时长：解码短于视频超过 1 s 判失败，长于视频只告警；ffmpeg verbose 日志入工作目录（§2.2） |
| 翻译 run 目录 | 按 `translate/srt-<sha12>/<配方名>__s<seed>/` 分键，键由翻译子系统 `translate.plan` 唯一给出，`published.json` 指向当前使用的那份（§4，票据 15） |
| 发布与覆盖 | 对照 `published.json` 的 SHA256：三份最终文件未被改动即替换，任一被改动且非 `force` 才拒绝，并在扫描阶段提前判定（§4） |
| 输出目录锁 | 启动即取 `<output_dir>/.work/lock`，GPU 锁在 GPU 阶段前取（§3.3） |
| worker 重启 | 按文件计：崩溃时正在处理的文件记该阶段失败，从下一文件重启；不再"整阶段只重启一次"（§3.1） |
| x0 触顶窗口 | 该窗 `text` 置空、截断文字记入 `failed_windows`，不进对齐与翻译（§6） |
| 票据 03 门禁 | ASR 文字必须逐字符一致；unit 时间允许 ±20 ms（1 帧），超出另开票但不阻塞 05／06（§12） |
| `break_stale_lock` | 不进配置文件，改为环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1` 一次性生效（§10） |
| VAD 设备 | 第一版固定 `cuda:0`，不设配置键；CPU 仍列未来方向（§10） |
| 产品测试位置 | `tests/`，由票据 00 建目录并把 `kototoki/` 接进 `just check`／`just test`（§12） |
| 翻译配方归属 | 只住在 `kototoki/translate/recipes.py`（05 建、09 改）；`kototoki/recipes.py` 只放 STT／cue／媒体常量（§7.3） |

## 2. 阶段分解

每个视频经过 8 个阶段；每阶段只读上一阶段的文件产物，写自己的产物，互不导入对方的运行时状态。

```
probe ──► extract ──► vad ──► asr ──► align ──► ja-cues ──► translate ──► merge
 CPU       CPU       GPU*    GPU     GPU        CPU          GPU          CPU
```

| 阶段 | 做什么 | 输入 → 产物 | 设备 | 单片成本（2 h 电影，来自整片证据） |
| --- | --- | --- | --- | --- |
| probe | ffprobe 读取全部流：音轨按 `language=jpn` 且非 `disposition.comment` 优先，再按 `disposition.default`，多条匹配告警并记录；没有匹配选第一条音轨并告警；记录绝对流索引、编码、声道布局、`start_time`、时长，以及字幕流清单（只记录，第一版不使用） | 视频 → `probe.json` | CPU | <1 s |
| extract | ① ffmpeg `-c:a copy` 把选中音轨原样写出，容器按 §2.1 选；② 从视频容器按绝对流索引解码该音轨，`aresample=async=1:first_pts=0` 保留时间轴（起始静音补齐、间隙补零，sample 0 即视频 0 秒），按 §2.2 下混，重采样 16 kHz，PCM16 WAV；ffmpeg verbose 日志写入工作目录；校验解码时长对视频流时长（§2.2）；记录 PCM SHA256、样本数、`offset_s = 0` | 视频 → `audio.<ext>`、`audio-16k.wav`、`extract.log` | CPU | ① 秒级 ② 约 10–30 s |
| vad | Pyannote 检测 → 源跨度合并 → manifest | `audio-16k.wav` → `vad.json` | GPU（VAD 允许 CPU） | 加载 28 s，推理 20 s |
| asr | 逐窗识别，纯文字 | `audio-16k.wav`+`vad.json` → `asr.json` | GPU | w0：加载 7 s，推理 150–170 s；x0：加载 19 s，推理 365–395 s |
| align | 逐窗 CTC 对齐，字符时间 | `audio-16k.wav`+`asr.json` → `align.json`（现有 `result.json` 结构） | GPU | 加载 17 s，推理 53–56 s |
| ja-cues | 字符 units → 日文 cue，含无时间字符的时间回填 | `align.json` → `ja.srt`+`ja-cues.json` | CPU | <1 s |
| translate | b10-joint 整片翻译，续跑语义沿用 v3 | `ja.srt` → `zh.srt`+翻译 run 目录 | GPU（独占） | 1993 条约 270 s，387 条约 66 s；另加模型加载 |
| merge | 按 cue 编号合并 | `ja.srt`+`zh.srt` → `ja-zh.srt` | CPU | <1 s |

### 2.1 流复制的容器映射

| 音轨编码（ffprobe `codec_name`） | 容器后缀 |
| --- | --- |
| flac | `.flac` |
| aac、alac | `.m4a` |
| ac3 | `.ac3` |
| eac3 | `.eac3` |
| dts | `.dts` |
| opus | `.opus` |
| vorbis | `.ogg` |
| mp3 | `.mp3` |
| pcm_s16le、pcm_s24le、pcm_s32le、pcm_f32le（小端 PCM） | `.wav`（超过 4 GB 时用 RF64，ffmpeg `-rf64 auto`） |
| 大端 PCM、pcm_bluray、pcm_dvd、aac_latm、truehd 及其它未列出编码 | `.mka`（Matroska 音频，容纳任何编码并保留时间戳） |

### 2.2 时间轴与下混

- **为什么 ② 不从 ① 派生**：`.ac3`／`.eac3`／`.dts`／`.mp3`／ADTS AAC 等裸码流容器没有时间戳，流复制后丢掉音轨相对视频的起始延迟与中途间隙（广播 `.ts` 常见），AAC 的编码器预延迟处理也不同。② 直接从视频容器解码，`async=1:first_pts=0` 补齐起始静音，让 WAV 的 sample 0 对齐视频 0 秒。
- **零点与 `offset_s`**（2026-10-14 第三轮修订）：补齐静音后 WAV 已经是视频坐标，因此 `offset_s` 恒为 0，各阶段不再把音轨 `start_time` 加到时间上（否则同一延迟会在 `map_records` 里算两次）。ffmpeg 默认把输入的 `format.start_time` 平移到 0，广播 `.ts` 的音轨 `start_time` 是绝对值，直接当偏移会整体后移一秒多；而音频先于视频的负延迟又无法用非负 offset 表达。`start_time`（音轨与容器）只进 `probe.json` 作诊断。现有 W0 链路的 `offset_s` 参数保留，产品固定传 0；票据 02 的"延迟音轨"合成测试必须断言最终 cue 时间等于视频时间。
- **丢样与时长校验**：`async=1` 是硬补偿（插静音／丢样本），时间戳回绕或 PTS 断裂时会静默丢音频，因此解码用 `-loglevel verbose` 并把日志写入 `extract.log`，记录补偿量（票据 02 实测：swr 在 verbose 下报告 `adding N audio samples of silence`，但只报出一部分，合成 2 s 间隙只报约 0.63 s，因此另按 ffmpeg 结束统计的输入样本数记净补偿 `net_padding_s`，见[配置、配方与媒体提取](../architecture/modules/config-and-media.md)）。校验对象是**视频流时长**而不是 `format.duration`（TS 内 VBR 音频的容器时长是估算值）：解码短于视频超过 1 s 视为截断失败，长于视频只告警。视频流时长的来源按优先级取 `stream.duration`、精确的 `DURATION` 标签、mkvmerge 统计标签 `DURATION-<lang>`、`format.duration`；标签来源与 `format.duration` 相差超过容差时取较小者并告警（票据 11：ffmpeg `-c copy` 剪辑会保留原片的 `DURATION-eng`，曾把合法片段误判为截断）。
- **下混按声道布局**：每种布局的 `pan` 表达式在 `recipes.py` 写死并进配方 hash。单声道直通；双声道沿用基线证据的 `pan=mono|c0=0.5*c0+0.5*c1`；5.1 及以上用 ffmpeg 标准系数（前左右 1、中置 0.707、环绕 0.707、丢 LFE）并除以系数和归一化，禁止削波，不能只取左右前；`-ac 1` 的隐式矩阵不用，因为它的系数与归一化不在配方里。合成 5.1 测试断言满幅输入不削波。日本广播双单声道（主／副音声）无法自动识别，第一版按双声道处理并记为已知限制。
- **重采样器**：降采样用 ffmpeg 默认 swr（`aresample=16000`），与 `async=1:first_pts=0` 的时间轴补偿同为 swr。2026-10-14 曾裁定改 soxr 28 bit，2026-10-15 最终验收发现 soxr 版派生 WAV 使 Pyannote 少保留约 9–10% 语音、产品 CER 比 2026-10-05 基线高 0.5–3.5 个百分点，而产品 VAD 在 swr 版 WAV 上与基线窗口完全相等，用户裁定改回（票据 10）。保留 2026-10-14 的频谱对比供参考：在 HF II 整片对比中，6 kHz 以下两者差异比信号低约 79 dB，差别集中在 7.8–8 kHz（swr 残留 −8.3 dB，soxr −44.9 dB，即 swr 边缘的折叠残留），削波无差别（各 1–2 个样本）；默认 swr 时派生 WAV 与基线 `hf-ii-full.wav` 的 PCM SHA256 一致（票据 02 与票据 10 均核对为 `ee4e2da3…`）。频谱上更干净没有换来识别率：Pyannote 对 soxr 版音频更保守，这是改回的直接原因。

"无损"的边界：① 是严格无损（字节级流复制），只作归档；② 是推理输入，下混与重采样必然改变样本。

VAD 的"GPU*"：按选型原则 VAD 可 CPU 可 GPU；整片证据用 CUDA FP32。默认 GPU（成本只有 50 s／片），CPU 作为将来需要让出显存时的选项，第一版不做。

## 3. 调度模型：CPU 流水线 + GPU 分阶段批处理

### 3.1 结论

- **CPU 阶段（probe、extract、ja-cues、merge）与 GPU 阶段分开**。extract 用一个小进程池（默认 `min(4, cpu_count)`）先跑完整批，GPU 阶段再开始：worker 启动时拿到的是固定的 `batch.json`，整批 extract 只需 1–2 分钟，不做流式投喂。
- **GPU 阶段按"阶段 × 整批"推进，而不是"文件 × 全流程"**：加载 VAD → 跑完本批全部文件 → 卸载；加载 ASR → 跑完本批 → 卸载；加载 MMS → …；最后启动 llama-server → 翻译本批全部 SRT → 关闭。第一版没有批次切分参数。
- 每个 GPU 阶段在**独立子进程**中执行（一个阶段一个子进程，而不是一个文件一个子进程）：进程退出即彻底释放显存与 CUDA 上下文，崩溃不拖垮编排器，OOM 的影响范围只有一个阶段。worker 逐文件增量写结果；worker 进程异常退出时，编排器按增量结果判定"正在处理的文件"，把它记为该阶段失败，再为其后的文件重启 worker；重启次数按文件计，而不是整阶段只重启一次，避免一个文件的 OOM 把其后所有文件连带标失败。worker 遇到单文件异常（非 CUDA 粘性错误）记失败并继续下一文件，退出码 1；检测到 CUDA 粘性错误（后续文件必然失败）时退出码 2 让编排器重启。编排器本身不加载任何模型，也不 import torch（有测试保证，范围见 §7.1）。

### 3.2 为什么这样选

| 考虑 | 分阶段批处理（采用） | 逐文件全流程 |
| --- | --- | --- |
| 显存 | 任一时刻只有一个模型驻留；翻译峰值 15.7–15.8 GB 已接近 16 GB 整卡，无法与任何 STT 模型共存 | 需要 VAD+ASR+MMS 共驻（估计 10–12 GB，未验证），翻译仍必须单独一段 |
| 模型加载开销 | 每阶段每批一次：Pyannote 28 s、MMS 17 s、whisper 7 s、Qwen 19 s、llama-server 约 1 min | 每文件重复一次，20 部电影多付约 20–40 分钟 |
| 首个结果出现时间 | 整批 STT 结束后才有第一份 `ja.srt`，整批翻译结束后才有第一份双语 SRT | 第一部电影约 10 分钟后完成 |
| 失败隔离 | 一个文件失败只跳过它，阶段继续 | 同样可做 |

批量生产场景下吞吐与显存安全优先，接受首个结果延迟。需要更早看到结果时，用户可以自行分几次调用。

### 3.3 GPU 内部顺序与并发

- GPU 阶段严格串行，由 `.local/gpu.lock`（沿用现有互斥语义：不抢占、不杀进程、死锁需显式 `KOTOTOKI_BREAK_STALE_LOCK=1`，一次性生效）保护。GPU 锁在第一个有文件要跑的 GPU 阶段前获取，持有到翻译结束；翻译阶段只在有文件需要模型（`needs_model`：非零条目且 run 未完成）时才取锁、建 session，全部 run 已完成或零条目时整批不占 GPU（票据 15）。
- 同一 `output_dir` 同时只允许一个编排器：启动即取 `<output_dir>/.work/lock`（同 `ProcessLock` 语义），否则两个编排器会在 GPU 锁之前并发写同一 `.work/index.json` 与工作目录。
- 启动 llama-server 前用 `nvidia-smi` 轮询空闲显存：上一 worker 退出后 WDDM 释放显存有延迟，直接启动可能分配失败并白白消耗重启额度；空闲量低于阈值超时则按基础设施失败处理，错误信息写明当时的空闲量。
- 不在 GPU 阶段内做多文件并发：W0 契约是 batch 1、逐窗独立；并发只会争抢算力与显存，没有吞吐收益。
- 翻译阶段：llama-server 单槽、`cache_prompt`，沿用 v3 `generate.py` 的批次与续跑语义，一次 session 顺序翻完本批所有需要模型的 SRT（每个 SRT 是一个 scene）；不需要模型的文件（零条目、run 已完成）只读回译文；锁或 session 建不起来只让需要模型的文件失败，server 一直起不来时本批其余需要模型的文件直接失败（票据 15；见[翻译子系统](../architecture/modules/translation-subsystem.md)）。

### 3.4 时间线示意（4 部电影、w0）

```
CPU:  ex1 ex2 ex3 ex4 | ............ | cue1-4 | ............ | merge1-4
GPU:      [VAD 1 2 3 4][ASR 1  2  3  4 ][MMS 1 2 3 4]  [translate 1 2 3 4]
```

单片 GPU 成本约 50+165+73+300 ≈ 10 分钟（w0），4 部约 40 分钟；整批 extract 约 1–2 分钟，先于 GPU 阶段完成。

## 4. 产物：中间产物与最终产物

输出目录镜像输入目录的子目录层级（`<input_dir>/S1/ep01.mkv` → `<output_dir>/S1/ep01.ja.srt`）。每个输入视频有一个工作目录 `<output_dir>/.work/<id>/`，`<id>` 是相对路径（含扩展名）SHA256 的前 12 位，避免同名不同扩展名碰撞与 Windows 路径长度上限；`.work/index.json` 维护 `<id>` ↔ 相对路径。下面以单层为例。

```
<out>/
  <stem>.ja.srt          最终
  <stem>.zh.srt          最终
  <stem>.ja-zh.srt       最终
  .work/lock             编排器独占本输出目录（ProcessLock）
  .work/index.json       <id> ↔ 相对路径
  .work/cache/           HF_HOME／TORCH_HOME，整个输出目录共用一份
  .work/translate-sessions/  llama-server 运行日志（每次运行一个时间戳目录，按 session 分子目录，整批影片共用）
  .work/<id>/
    probe.json           音轨选择与 ffprobe 快照（含 start_time 诊断）
    audio.<ext>          原始编码音轨（流复制），保留
    audio-16k.wav        模型输入（2 h ≈ 230 MB），保留
    extract.log          ffmpeg verbose 日志（补偿统计）
    vad.json             身份：PCM SHA256 + VAD 配方 hash
    asr.json             最贵的 STT 阶段；每窗文字与 trace、failed_windows，不含音频
    align.json           权威 STT 证据：全文、units、text_only、对齐记录
    ja-cues.json         cue ↔ unit 映射、时间回填记账、未渲染文字记账
    translate/srt-<sha12>/<配方名>__s<seed>/   v3 风格 run，按 ja.srt 的 SHA256 分键、再按配方与 seed 分目录：run.json、batches.jsonl、scene.json、transport；可续跑
    published.json       三份最终 SRT 的 SHA256 与来源产物身份（含当前使用的 translate run 目录，相对工作目录）
    failure.json         任一阶段失败时写，记录阶段、异常与已完成产物
```

规则：

- **每个产物带输入身份与配方 hash**；阶段开始前若产物存在且身份匹配，直接跳过；身份不匹配时**原地原子替换**（旧产物不另存，这是"所有产物保留"的唯一例外，`translate/` 目录除外，见下）。这同时提供崩溃后续跑与"改了翻译配方只重跑翻译"。身份的组成规则集中在 `kototoki/artifacts.py`（票据 00），各阶段的期望身份与阶段链由 `kototoki/plan.py` 给出（票据 14）：视频身份 = 相对路径＋大小＋修改时间＋ffprobe 指纹（只取流的 `index`／`codec_name`／`channels`／`channel_layout`／`sample_rate`／`start_time`／`duration` 与容器 `duration`，不含 `filename` 与 `tags`，不对整个视频算哈希）；派生产物身份 = 上游产物 SHA256＋配方 hash＋模型文件 SHA256＋影响输出的配置键（cue 规则、seed）；绝对路径不参与身份。模型文件 SHA256 沿用 v3 `verify_model` 的 size+mtime 缓存（`.work/cache/model-verification.json`），每次运行最多算一次，不逐文件重算。
- **坐标系**：`vad.json`、`asr.json`、`align.json` 里的窗口、段、对齐记录一律是 WAV 本地秒／整数样本（与现有 `result.json` 相同：只有 `units.start/end` 含 offset），顶层带 `offset_s`（产品恒为 0）；ja-cues 阶段产出的 cue 时间是最终 SRT 时间。票据 00 的产物契约逐文件写明字段坐标，票据 04 带非零 offset 的测试证明只加一次。
- 所有产物保留，不自动删除。翻译 run 目录按 `ja.srt` 的 SHA256 前 12 位分键（与 v3 `deliveries/` 同形），因为 v3 `run_generation` 在 `run.json` 的 `sources`／`scene_ids` 不一致时直接拒绝；改 cue 规则后产生新的 `ja.srt` 就用新目录，旧目录保留。
- 三份最终 SRT 在 merge 阶段**一起**发布（先写到工作目录再原子移动），并在 `.work/<id>/published.json` 记录三者的 SHA256 与来源产物身份；跳过规则看这份记录，不只看文件是否存在，避免改 cue 规则后日文与中文版本不一致。**覆盖规则**：发布前对照 `published.json` 记录的 SHA256，三份现有文件都未被改动（或不存在）即直接替换；`published.json` 在判定放行后、移动文件前写入，并把此刻最终位置上已有文件的 SHA 记为 `previous_sha256`，等于 `sha256` 或 `previous_sha256` 都算未改动，保证写记录后、移动完成前崩溃（可连续多次）时残留的旧文件不被误判为用户改动；任一被用户改动且 `force = false` 则拒绝，并在扫描阶段（进 GPU 阶段之前）就判定、告警并跳过该文件，不白算；`force = true` 时无条件覆盖。Windows 下文件被播放器占用会 `PermissionError`，带重试。
- 工作目录之外不写任何转写内容；控制台只输出进度、计数与耗时。

## 5. 日文 cue：STT 与翻译的交界

### 5.1 翻译输入为什么是 `ja.srt`

b10-joint 是 `jpn.srt → chn.srt` 的流程：逐条翻译日文 cue，前后邻条只作上下文，每条中文直接继承那条日文的编号与时间，双语合并只是拼接。若改为翻译 30 s ASR 窗口的整段日文，得到的是一整段中文，必须再切成若干块贴回各句日语的时间范围；中日语序不同、翻译会并句拆句，这个回映射没有可靠的自动方法，也没有任何已验证的基线。因此翻译输入固定为 `ja.srt`，**cue 切分质量同时决定日文字幕可读性与翻译上下文**。

### 5.2 切分规则初值（配置文件 `kototoki.toml`，待按真实输出调整）

| 键 | 初值 | 说明 |
| --- | --- | --- |
| `max_chars` | 24 | 单条 cue 的日文字符数上限（按 Unicode 码点计，不含空白）。日本商业字幕常用每行 13–16 字、最多两行；双语显示时日文只占一行，取 24 作为单行可读上限 |
| `max_duration_s` | 6.0 | 单条 cue 显示时长上限 |
| `min_duration_s` | 0.8 | 低于此值且后方有间隙时向后延长，不与下一条重叠 |
| `max_gap_s` | 1.0 | 相邻词汇字符之间的正间隔超过此值且该间隔不整个落在同一个 VAD 子段内时断开（票据 12：CTC 发射点稀疏，拖长音会在词内留下超过阈值的假间隙，只有跨非语音区的间隔才算句界）。原初值 0.4 在 CTC 字间间隔处把词切碎，2026-10-14 按票据 04 离线观感改为 1.0（用户采纳） |
| `sentence_endings` | `。！？!?` | 遇到即断开 |
| `soft_breaks` | `、，,` | 超过 `max_chars` 时优先在这些字符后断 |
| `lead_out_s` | 0.3 | 每条 cue 结束时间向后延长的秒数（CTC 给的是发声结束，整片证据中比参考字幕结束中位早约 0.34 s），不越过下一条起点 |

规则顺序：先按句末标点与间隔断成"句"，句超限时在软断点处切，仍超限时按字符数硬切。无时间字符的回填：窗内零散 `text_only` 字符按相邻有时间字符线性插值（`time_source=interpolated`）；窗首或窗尾只有单侧邻居时，向窗口边界方向按同样的每字符时长外推，不越过窗口边界；整窗对齐失败时整窗文字按该窗的 VAD 子段（manifest `segments`）分配并对每字符时长设上限（`time_source=fallback`，沿用 `kototoki_eval.schema` 的取值，不新造 `coarse`）。`align.json` 保留原始 `text_only` 记账，回填只发生在 ja-cues 阶段并记录每个 unit 的来源。SRT 毫秒取整沿用 `replay.py` 的 `floor(x*1000+0.5)`，不用 Python `round`。中文译文允许换行（v3 只禁空行），双语合并时把中文内的换行替换为空格，保证 `ja-zh.srt` 每条恰好两行。

## 6. 失败、部分结果与续跑

- 文件级隔离：一个文件在某阶段失败，写 `failure.json`，该文件退出后续阶段，批次继续；最终汇总打印失败清单，退出码非零。
- 无语音：VAD 结果为空时跳过 ASR／对齐／翻译，直接发布三份零条目 SRT 并告警（现有 SRT 解析器对空文件抛错，产品侧绕过它）。
- x0 生成触顶（4096 token）：只把该窗口记为失败窗口，不让整部影片失败。表示方式由 worker 协议（票据 00）统一规定，w0／x0 相同：`asr.json` 中该窗的 `text` 置空，截断文字与原因记入 `failed_windows`（供诊断，不进对齐、cue 与翻译），"每个字符恰好一个 unit"的不变量按保留文本计算；窗口失败数进入汇总。现有 `x0_demo/pipeline.py::validate_asr` 拒绝 `token_limit_reached` 的行为不移植。
- 阶段级终态与基础设施失败区分（沿用 v3）：OOM、服务器崩溃、传输错误是基础设施失败，同一 run 内重启 llama-server 重做，最多 2 次；每次重启是 v3 意义上的新 session（`sessions[]` 新增一项、`cache_state` 重置、首个请求重做 `cache_n == 0` 校验、`resumed=true`）。生成超限、grammar 失败是批次终态，进入下面的降级。
- 翻译降级（产品规则，区别于 v3 实验的"不缩批"）：10 条批次终态失败 → 拆成两个 5 条批次（各自仍取前后各 1 条只读邻文，seed 不变）→ 仍失败的 5 条批次拆成单条 → 单条仍失败时该 cue 的中文位置保留日文原文。子批次 ID 为 `父ID.a`／`父ID.b`，场景文件记录降级树；降级清单写 `translate/report.json` 并在控制台汇总。降级改变了 v3 配方 `b10-joint` 中"不缩批"的身份字段，产品配方命名为 `b10-joint-degrade-v1`，另算 hash；提示、grammar、采样与请求字节不变并有测试固定。
- 续跑：重跑同一命令即可；已完成的产物按身份跳过。翻译按批次增量落盘（v3 原本按整个场景落盘，产品改为每批次追加写），中断后从未完成的批次继续。回退为日文的 cue 对该配方 hash 与 seed 是终态，重跑同一命令不会再试；要重试须改 `[translate] seed`（另起 run 目录，整片重译）；`force` 只管最终文件的覆盖，不触发重译。

## 7. 进程、环境与依赖

### 7.1 进程模型

```
python -m kototoki kototoki.toml  (编排器：唯一持有 .local/gpu.lock；不 import torch)
 ├─ ThreadPool → ffmpeg/ffprobe 子进程（CPU 队列）
 ├─ python -m kototoki.workers.vad    --jobs batch.json   (子进程，加载一次，循环文件)
 ├─ python -m kototoki.workers.asr    --jobs batch.json   (引擎取 jobs 的 config.engine：w0|x0)
 ├─ python -m kototoki.workers.align  --jobs batch.json
 ├─ llama-server + 进程内 HTTP 客户端循环翻译（一个 server session 服务整批）
 └─ 进程内 ja-cues / merge
```

- worker 之间只通过 `.work/<id>/` 下的 JSON 交接，每阶段重验输入身份（继承 X0 的做法）。编排器与 worker 用同一解释器（`sys.executable`）。
- 锁：只有编排器获取 `.local/gpu.lock`（仓库内固定路径，不随配置文件移动），worker、翻译模块都不再获取；v3 的 `GpuLock`／W0 的 `gpu_lock` 不移植，只保留 `ProcessLock` 给编排器。锁文件记录编排器、当前 worker 与 llama-server 的 pid。
- 所有 worker 与 llama-server 放进 KILL_ON_JOB_CLOSE Job Object：编排器被强杀时子进程随之退出，不留占显存的孤儿。
- 编排器为 worker 子进程设置离线环境（`HF_HUB_OFFLINE=1`、`HF_HOME`／`TORCH_HOME` 指向 `<output_dir>/.work/cache/`（整个输出目录共用，不是每文件一份）、`PYANNOTE_METRICS_ENABLED=0` 等，沿用 `setup_runtime` 的变量但**不再加私有 DLL 目录**），保持本地运行不变量。子进程环境统一 `PYTHONUTF8=1`，进度 JSON 与日志文件显式 UTF-8（本机根环境默认 cp1252，`scripts/check_docs.py` 在无 mise 的 shell 下即因此崩溃）。
- DLL 解析顺序：ASR worker 必须先 `import torch` 再导入 `ctranslate2`／`faster_whisper`，cublas／cudart 与 cuDNN 子库由此来自 torch 目录；CT2 在导入时按全路径加载自带的 `cudnn64_9.dll`（9.10 调度器），与 torch 的 9.19 调度器同进程并存，2026-10-14 用户接受（01 smoke #3：W0 冻结窗口 token 与特征逐一一致）。有导入顺序测试。VAD worker 不需要 FFmpeg PATH：01 smoke #2 实测 pyannote＋torchcodec 对内存波形推理全程不加载任何 FFmpeg DLL。
- "编排器不 import torch"的测试断言 `import kototoki.job` 与 `kototoki.__main__` 之后 `sys.modules` 中没有 `torch`、`ctranslate2`、`faster_whisper`、`transformers`、`pyannote`、`torchaudio`、`torchcodec` 与任何 `experiments.*`。

### 7.2 环境：一个统一的 CUDA 12.8 环境

现状三个隔离环境版本互斥（见[环境清单](../research/2026-10-04-runtime-inventory.md)）：

| 环境 | Python | Torch | 关键包 | 用途 |
| --- | --- | --- | --- | --- |
| `whisper-latest` | 3.13 | 2.8.0+cu128 | CT2 4.8.2、torchaudio 2.8、transformers 4.57.6 | W0 ASR、MMS |
| `qwen-hf-final` | 3.13 | 2.14.1+cu130 | transformers 5.18 | X0 ASR |
| `vad-pyannote-gpu-v1` | 3.12 | 2.11.0+cu128 | pyannote.audio 4.0.7 | VAD |

分裂的根因是 WhisperX 要求 transformers 4.x 与 Torch 2.8。产品不再依赖 WhisperX，统一为**一个 CUDA 12.8 环境**（2026-10-14 决定，替代此前的 CUDA 13＋CT2 侧车方案）：

| 组件 | 目标版本 | 来源与依据 |
| --- | --- | --- |
| Python | 3.13 | uv 托管 |
| torch | 2.11.0+cu128 | PyTorch cu128 索引（含 sm_120）；cu128 索引止于 2.11.0。本机 `vad-pyannote-gpu-v1` 已在跑 |
| torchaudio | 2.11.0+cu128 | 同上；`forced_align`／`merge_tokens` 保留（2026-10-14 在本机 `vad-pyannote-gpu-v1` 的 torchaudio 2.11.0+cu128 上只读核实存在；CUDA 路径等价性由 01 smoke #1 验证） |
| torchcodec | 0.17.0 | PyPI（cu128 索引没有 0.17.0）；本机 `vad-pyannote-gpu-v1` 已与 torch 2.11.0+cu128 同装并运行 |
| transformers | 5.19.0 | PyPI；覆盖 Qwen3-ASR 与 MMS wav2vec2；要求 torch ≥2.5 |
| pyannote.audio | 4.0.7 | PyPI；本机已在 torch 2.11 上运行 |
| faster-whisper／CTranslate2 | 1.2.1／4.8.3 | PyPI；CT2 wheel 按 CUDA 12.8＋cuDNN 9.10 构建，不需要侧车。01 smoke #3（2026-10-14，干净 PATH、先 import torch）实测：cudart／cuBLAS 与 cuDNN 子库来自 torch（cuDNN 9.19.0），CT2 wheel 自带的 `cudnn64_9.dll`（9.10.2.21 调度器）由其 `__init__` 按全路径加载，两份调度器并存；W0 冻结窗口解码的 token 与特征 SHA 与 torch 2.8＋CT2 4.8.2 的记录逐一一致，用户接受这一组合。CT2 在 sm_120 上依赖 PTX JIT（`CUDA_DISABLE_PTX_JIT=1` 时解码失败；wheel 只嵌入 sm_86 PTX、无 sm_120 SASS，2026-10-14 扫描 `ctranslate2.dll` 确认）：冷启动首窗解码 27 s，二次启动 5 s |
| llama.cpp | b11583 官方 `win-cuda-13.4` 二进制 | 独立进程，与 Python 进程无 DLL 交集；13.4 构建原生含 sm_120 内核，12.4 构建需 PTX JIT，故不降级 |
| CUDA toolkit | 不需要本地安装 | 所有组件用 wheel／二进制自带运行时；驱动 617.42 同时满足 12.x 与 13.x |

**选版规则**（用户 2026-10-14 明确）：CUDA 12 与 Python 3.13 是固定锚点；被它们限制的组件随之锁定（torch／torchaudio／torchcodec 取 cu128 索引上的最新版本，CTranslate2 取 CUDA 12 wheel 的最新版本）；不受影响的组件一律取最新稳定版（transformers、pyannote.audio、faster-whisper、numpy、llama.cpp 官方构建）。上表各行均按此规则选定，实施时以 `uv lock` 当日的最新稳定版为准并记录。

**为什么从 CUDA 13 退到 CUDA 12**：CT2 是 w0 的推理内核且只有 CUDA 12 wheel；cuDNN 9 的 DLL 文件名在 CUDA 12 与 13 构建间相同，同进程只能加载一份，原方案 A 因此要求 w0 worker 不 import torch 并用 NumPy 重写特征，复杂且无先例。整体 CUDA 12 后 w0 worker 与 VAD、对齐、x0 worker 一样正常 import torch，特征链保持现有 torch 实现，等价性风险最小。代价是 torch 停在 2.11.0 而非 2.14.1；用户 2026-10-14 接受。CT2 wheel 在 sm_120 上是 PTX JIT（只含 sm_86 PTX；01 smoke #3 冷启动 27 s、二次 5 s）。2026-10-14 复议过 cu12／cu13 混用并维持本决定；事实、重新评估的触发条件与届时的可靠形态记录在 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md) 依据段，不在此重复。

**llama.cpp 改用官方 b11583 构建**：上游 2026-07-13 合并 `hy_v3` 架构；本机 APEX-I-Compact GGUF 的路由偏置张量已是上游命名 `blk.N.exp_probs_b`（2026-10-13 本地读取确认），旧补丁针对的 `.bias` 命名问题不存在。这替代了 [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md) 中"继续使用 b11429 兼容 loader、不以 stock 引擎替代"的条款（用户 2026-10-14 确认），由 ADR-0007 记录。票据 01 的 smoke 要对比兼容引擎与 stock 引擎的 `/tokenize` 输出与固定 seed 的短生成，并在一个真实 b10 批次上测量显存峰值（现有 15.7–15.8 GB 是兼容引擎的数字）。`ManagedServer` 要求的 `identity.json` 与驻留日志解析按 stock 构建适配。

**依赖管理**：根 `pyproject.toml` 改为产品项目 `kototoki`，运行时依赖写入 `dependencies`，`[[tool.uv.index]]` 声明 `pytorch-cu128`（`explicit = true`），`[tool.uv.sources]` 把 torch／torchaudio／torchcodec 指向该索引，`tool.uv.environments` 限 win32，`uv.lock` 锁定；测试工具放 dependency group。后果：根环境从此有 Torch，`experiments/` 中原本因缺 NumPy／Torch 跳过的离线测试会实际运行。三个历史环境保留供复现，不删除。

**升级即新身份**：Torch／CT2／llama.cpp 版本变化会轻微改变数值，必须在冻结输入上与现有基线成绩回归后才算接上基线（本期不做，见 §11）。

**后续可选实验（不在第一版）**：用 HF transformers 的 Whisper 实现（纯 PyTorch）替换 CT2，解除 CUDA 12 锁定、跟上最新 torch。代价是速度约慢 1.5–3 倍、文字与现 W0 有细微差异，需要独立的等价性验证。另一条路是保留 CT2、只给 ASR worker 一个独立的 cu12 侧车 venv，让其余 worker 跟最新 torch；触发条件见 ADR-0007。

### 7.3 代码布局

各模块的接口以模块页为准，依赖方向、接缝裁定与责任边界以[模块边界](../architecture/module-boundaries.md#产品包的责任边界)为准（原目标架构页于票据 08 并入后删除）。下表是实现时（票据 00–09）的文件与来源对照，**冻结于 2026-10-14，不再随后续票据维护**；当前文件布局以[架构总览的模块地图](../architecture/INDEX.md#模块地图)为准。票据 14 新增 `kototoki/plan.py`（阶段链与期望身份从 `job.py` 与三个 worker 壳迁出，见[阶段计划](../architecture/modules/stage-plan.md)），票据 15 把 `translate/data.py` 并入 `batching.py`。

新建产品包 `kototoki/`，从 `experiments/` 复制并精简已验证的实现（历史目录保持冻结，产品包不导入它们）：

| 产品模块 | 来源 |
| --- | --- |
| `kototoki/__main__.py`、`job.py`（批次、阶段推进、续跑、锁） | 新写；锁与 Job Object 取自 `translation_v3/procs.py` |
| `config.py`（读 `kototoki.toml`，§10）、`recipes.py`（VAD／ASR／MMS／cue／媒体的配方常量与 hash，**不含翻译配方**） | 新写，`tomllib` 读取；配方常量取自各 demo 的 `RECIPE`／`recipes.py` |
| `artifacts.py`（产物路径、身份、匹配跳过、原子写与 Windows 重试、`failure.json`、`published.json`）、`workers/protocol.py`（`--jobs` 格式、增量结果、`failed_windows`、退出码） | 新写；原子写取自 `translation_v3/common.py` |
| `media.py`（ffprobe／ffmpeg 流复制与派生 WAV） | 新写；下混与重采样参数取自 `experiments/corpus/prepare_round2.py`（2026-10-14 曾改 soxr 28 bit，2026-10-15 改回默认 swr，票据 10） |
| `vad.py` | `w0_demo/vad_candidates.py` 的 `CurrentPyannoteVad` + `chunk_intervals` |
| `asr_whisper.py` | `w0_demo/asr.py`（torch 特征链不变，去掉私有 DLL 目录逻辑，显式 torch 先于 ctranslate2 导入） |
| `asr_qwen.py` | `x0_demo/asr.py` + `experiments/qwen/run_qwen.py` 的资产身份常量、`checkpoint_identity`、`check_gpu`（复制，不导入历史包） |
| `align.py` | `w0_demo/alignment.py`（继续用 torchaudio `forced_align`，放宽 2.8.0 版本断言） |
| `cues.py` | `display/replay.py` 的组 cue 规则 + 软断点 + 时间回填 |
| `translate/`（含 `translate/recipes.py`，翻译配方与 `b10-joint-degrade-v1` 的唯一归属） | `translation_v3` 的 `recipes`、`batching`、`generate`（改为传入已建 session、按批次落盘）、`server`、`procs`、`common`（路径改配置）、`data`（`Scene`／`Cue`），`translation_demo` 的 `adapters`、`client`、`run`（`explicit_oom`、资产清单），`translation_demo_runtime` 的驻留解析；去掉 `mbr` 导入与裁判／统计命令；保留一条测试钉住 v3 `b10-joint` 的原 hash `2ba68054…`，证明移植没有改身份 |
| `srt.py`、`merge.py` | `translation_flow/srt.py`（允许零条目） + 新写合并 |
| `schema.py` | `kototoki_eval/schema.py` 的 `validate_transcript` |

产品测试放 `tests/`（workflow.md 规定的 core 层，`just test` 发现），不与模块同目录；票据 00 创建 `tests/__init__.py` 并把 `kototoki/` 接进 `just check`。现有 `kototoki_eval/` 保持评分用途不动。

### 7.4 上游版本核实（2026-10-13）

由子 agent 对官方发布页、PyPI、PyTorch wheel 索引、NVIDIA redist 核实，访问日期 2026-10-13；标 UNVERIFIED 的项未实测。本表是 CUDA 13 方案时期的核实记录，原样保留；CUDA 12.8 环境的选版以 §7.2 为准。

| 组件 | 最新稳定 | Windows 构建（核实时按 CUDA 13 查） | Python | 备注 |
| --- | --- | --- | --- | --- |
| CUDA Toolkit | 13.4 Update 1（redist 13.4.1／13.4.2） | R615 驱动；本机 617.42 满足 | — | cuBLAS 随 toolkit；13.1 起不再捆绑驱动 |
| cuDNN | 9.27.0 | 有 cuda13 Windows 包；pip `nvidia-cudnn-cu13` 有 win_amd64 wheel | — | 支持 CUDA 13.4.1 |
| torch | 2.14.1（2026-09-30） | 索引有 cu126／cu130／cu132；cu130 用 CUDA 13.0 构建，含 sm_120；PyPI 上的 Windows wheel 是 CPU 版 | cp312–cp314、cp314t；3.15 仅索引且 `torch.compile` 不可用 | cu128 停在 2.11.0；cu132 标为 experimental |
| torchaudio | 2.11.0（2026-03-23），无更新 | cu130 索引有 2.11.0+cu130 | cp310–cp314 | `forced_align` 保留（CPU／CUDA，batch 1）；与 torch 2.14.1 配对 UNVERIFIED |
| torchcodec | 0.17.0 | cu130 wheel | cp311–cp314 | pyannote 4.x 的音频 I/O 依赖，需要 FFmpeg 共享 DLL |
| CTranslate2 | 4.8.3（2026-10-13） | **仅 CUDA 12.8 + cuDNN 9.10**；CUDA 13 issue #1933 开放；wheel 是否含 sm_120 kernel UNVERIFIED | cp39–cp314、cp314t | 源码构建需绕过 `FindCUDA` 的 arch 解析（手加 `compute_120,sm_120`）；对 CUDA 13 头文件能否编译 UNVERIFIED |
| faster-whisper | 1.2.1（2025-10-31） | 跟随 CT2 | — | 要求 `ctranslate2>=4,<5` |
| transformers | 5.19.0（2026-10-06） | — | ≥3.10 | `qwen3_asr` 自 5.13 原生支持（`AutoModelForMultimodalLM`）；`Wav2Vec2ForCTC` 的 `load_adapter` 仍在 |
| pyannote.audio | 4.0.7（2026-06-30） | — | ≥3.10 | `torch>=2.8`、`torchaudio>=2.8`、`torchcodec>=0.7`；4.x 改用 torchcodec I/O、`token=`、`revision=`；直接加载 `segmentation-3.0` UNVERIFIED（仓库门控） |
| llama.cpp | b11583（2026-10-13） | 官方 `llama-b11583-bin-win-cuda-13.4-x64.zip` + `cudart-…-cuda-13.4` | — | PR #25395（2026-07-13）合并 `hy_v3`；源码构建 sm_120 用 `CMAKE_CUDA_ARCHITECTURES=120a-real` |
| Python | 3.15.0（2026-10-09） | — | — | 3.15 不可用（CT2／torchaudio／torchcodec 无 wheel）；3.14 核心栈齐全但 av／tokenizers／safetensors 未核；3.13 保守 |
| ffmpeg | 本机 git-20261001 full build | — | — | 只用默认 swr 重采样，不要求 libsoxr |

## 8. 仍开放的问题

无。2026-10-14 评审新增的四项已裁定（§1.2）；实施中出现的新问题记入对应票据。

## 9. 验收（草案）

- 离线单元测试：ffprobe 音轨选择与容器映射、派生 WAV 参数、产物身份与跳过逻辑、cue 切分与时间回填、SRT 解析／写出／合并、批次推进与失败隔离（伪 worker）。
- 环境 smoke（票据 01，脚本入库到 `scripts/smoke/`，并接到 `just test-full`；每项各自在独立子进程运行，避免 PyAV 与 torchcodec 的 FFmpeg DLL 在一个进程里相遇）：① torchaudio 2.11.0 配 torch 2.11.0+cu128 的 `forced_align`（合成序列＋一个真实冻结窗口）；② pyannote 4.0.7＋torchcodec 0.17 在产品环境导入并对内存波形推理，列出进程实际加载的 FFmpeg DLL（若没有任何 `avcodec*` 被加载，则 VAD worker 不需要 FFmpeg PATH，§7.1 的那条随之删除）；③ **在不含 `whisper-runtime-provisional` 的干净 PATH 下**，同一进程先 import torch（cu128）再用 CT2 解码一窗，打印实际加载的 cudnn／cublas／cudart 模块路径，除 CT2 wheel 自带的 `cudnn64_9.dll` 外均来自 torch 目录，并记录 cuDNN 版本与是否 PTX JIT；④ 官方 llama.cpp 加载 APEX GGUF，与兼容引擎比对 `/tokenize` 与固定 seed 短生成，再发**同一 session 的第二个 `cache_prompt` 请求**并断言 `timings.cache_n`、`tokens_evaluated`、`stop_type`／`stopped_limit`／`truncated` 的含义与 v3 `run_step` 的假设一致，保存一份 stock 引擎加载日志供 `residency_evidence` 回归，测一个 b10 批次的显存峰值。
- GPU smoke：1 个 5 分钟片段走完 8 阶段，产物齐全、SRT 合法、双语对齐。
- 回归：II／III 上新环境与现有基线的 CER／时间指标对比（本期不做，§11）。
- 整片：2 部电影批量运行一次，记录各阶段墙钟、显存峰值与失败清单。

## 10. 配置文件 `kototoki.toml`（草案）

### 10.1 结构

```toml
[paths]
input_dir   = "D:/movie/inbox"          # 递归扫描视频
output_dir  = "D:/movie/subs"           # 最终 SRT 与 .work/
models_root = ".local/models"           # 下面各模型路径相对于它
ffmpeg      = "D:/bin/ffmpeg.exe"
ffprobe     = "D:/bin/ffprobe.exe"
llama_server = ".local/tools/llama.cpp/b11583-cuda13.4/llama-server.exe"

[input]
video_extensions = [".mkv", ".mp4", ".m2ts", ".ts", ".mov", ".avi"]
audio_language   = "jpn"                # 优先选此语言标签的音轨（jpn／ja／jp 视为同一语言），没有则第一条并告警

[run]
extract_workers = 4                     # ffmpeg 并发数
force = false                           # true 时允许覆盖已被改动的最终 SRT（带重试）
stable_check_s = 10                     # 两次采样大小不变才视为写入完成（不用 mtime，拷贝工具常保留源 mtime）

[stt]
engine = "w0"                           # w0 | x0

[vad]
model  = "vad-comparison/pyannote-segmentation-3.0/pytorch_model.bin"   # 设备固定 cuda:0，第一版无配置键

[asr.w0]
model      = "faster-whisper-large-v3"
mel_assets = "w0-assets"

[asr.x0]
model = "qwen3-asr-1.7b-hf"

[align]
model = "mms-1b-all"

[cues]
max_chars = 24
max_duration_s = 6.0
min_duration_s = 0.8
max_gap_s = 1.0
sentence_endings = "。！？!?"
soft_breaks = "、，,"
lead_out_s = 0.3                        # 发声结束后向后延长，不越过下一条起点

[translate]
model = "translation/hy-mt2-30b-a3b-apex-i-compact/Hy-MT2-30B-A3B-APEX-I-Compact.gguf"
port  = 8080
seed  = 20261008
```

用户写出的相对路径以配置文件所在目录解析；用户省略的键用上述默认值，其中相对路径默认值以仓库根目录解析（配置文件放仓库外时默认模型目录与 llama-server 仍可用）。未知键报错而不是忽略。GPU 锁路径固定为仓库内 `.local/gpu.lock`，不可配置；破除死锁用环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1`，只对本次运行生效，不放配置文件（配置里的开关是粘性的，每次都会自动破锁）。

### 10.2 暴露与冻结的边界

| 放配置文件（用户关注、不改变模型行为） | 留在代码 `recipes.py`／`translate/recipes.py`（改动即新配方 hash） |
| --- | --- |
| 所有路径、模型目录、二进制位置（GPU 锁路径除外） | VAD onset／offset、30 s 窗口与合并策略、设备 `cuda:0`、下混矩阵与重采样参数 |
| 并发数、端口、文件稳定性采样间隔 | w0：beam 5、FP16、日语、无前文、无时间戳；x0：BF16、greedy、4096 |
| 输入扩展名、音轨语言偏好 | MMS FP32、归一化、字符映射 |
| cue 显示规则（§5.2） | 翻译采样 `official30b-cached-v1`、b10-joint 批次与提示、grammar、context 8192 |
| 翻译 seed | 翻译请求重试次数、失败分类、降级策略 |
| `force` | 产物 schema 版本 |

每个产物记录生效的配置快照与配方 hash；只改配置文件里的项不会使已有 STT 产物失效（cue 规则例外：改了只重跑 ja-cues 及之后）。

## 11. 未来方向（本期不做，只登记）

- **翻译批内语序自由**：如 1+5+1、中间 5 条允许并句拆句与重排，需要新的中文→时间回映射方案与评估，是独立研究。2026-10-16 讨论（[v6 结题](../research/2026-10-16-scene-aware-batching-v6.md)后）补充的方向：
  - 区分两个量。**包的大小**决定模型理解上下文的范围，应保持 10 条左右（v3：b5 不如 b10，"≤5 条、碰标点就切"无收益；v6：按 ≥5 s 静默切包收益很小且不复现）。**内容可挪动的范围**是另一回事，应按"同一句话"划分，而不是按包。
  - "同一句话"小组：相邻几行停顿很短（量级约 1 s，门槛待定）、连起来是一句完整的话，多数是 2～3 行。语序只允许在小组内调整；**停顿是硬边界**，内容不能跨停顿挪动，否则字幕会出现在无人说话的时刻。参考分布：相邻 cue 间隔中位数约 0.6 s、p90 约 4.3 s（v6 §2.1）。
  - 其他软件的做法（[Subtitle Edit](../research/2026-10-05-translation-subtitleedit.md)、[VideoLingo](../research/2026-10-05-translation-videolingo.md)、[pyVideoTrans](../research/2026-10-05-translation-pyvideotrans.md)）：主流是把被拆碎的句子合并成整句翻译，再按标点、长度比例或让模型切回原时间段；Subtitle Edit 的合并门槛是相邻间隔 <1 s；公认难点是切回时行数、编号错位，都要加结构校验。
  - 现有裁判（`claude-opus-5-5-mqm-v1`）已允许相邻 cue 之间合理挪动内容，不计 cue-attribution 与漏译，所以评估面可直接比较"严格一一对应"与"小组内重排"。
  - 实现形状可以是：包仍为 1+10+1，包内按短停顿与句末标点标出小组并在提示里告知模型，grammar 仍按 cue ID 输出，只是允许同组内的 ID 互相挪内容；回映射因此不需要新的时间对齐，只需校验组内总长度与显示时长。此项由另一会话讨论推进。
- **跨文件术语一致**：同一剧集多集之间的人名、专名统一。v3 的 `terms` 配方未采纳，产品暂无跨文件记忆。
- **用 HF transformers Whisper 替换 CTranslate2**，解除 CUDA 12 锁定（§7.2）。
- **重复／幻觉守卫**：W0 移植的 WhisperX 路径没有温度回退与压缩比检查，长重复输出目前只能靠 VAD 过滤减少；后续可加 n-gram 重复检测并标记。
- **利用视频内嵌日文字幕**：probe 已记录字幕流；检测到可用的日文字幕轨时跳过 STT 直接翻译，是 1.1 版最值得做的功能。
- **双单声道（主／副音声）识别**、**粗回退按 VAD 子段分配时间**。
- **VAD 跑 CPU** 以让出显存；**升级后的回归与容差**；**单阶段子命令与 CLI**。

## 12. 实施里程碑

票据在 `.scratch/bilingual-subtitle-pipeline/issues/`（本地 tracker，不进 Git），编号与下表一致；依赖关系写在票据的 `Blocked by`。每张票交付时按[随交付同步](../agents/documentation.md#随交付同步)更新对应模块页，不把全部文档推到 08。下表只列设计时规划的票据 00–09；最终验收后的票据 10–15（重采样改回 swr、`DURATION` 标签优先级、间隔断句跨子段、cue 词边界调研、阶段计划模块、翻译 run 键）在 §13 记录裁定，细节在各模块页"变更与决策来源"。

| 票据 | 里程碑 | 内容 | 完成标准 | Blocked by |
| --- | --- | --- | --- | --- |
| 00 | M0 共享基础 | `artifacts.py`（产物路径与短 id、身份与模型哈希缓存、坐标约定、匹配跳过与原地替换、原子写、`failure.json`、`published.json` 与覆盖规则）、`workers/protocol.py`（`--jobs`、增量结果、`failed_windows`、退出码 0／1／2）、`srt.py`（允许零条目、`floor(x*1000+0.5)` 取整）；建 `tests/__init__.py`，`just check` 纳入 `kototoki/` | 离线测试；文档：模块边界加"产物契约"归属 | — |
| 01 | M1 环境 | 根项目改产品项目、统一 CUDA 12.8 环境（torch 2.11.0+cu128）、官方 llama.cpp b11583；`tool.uv.environments` 限 win32；历史 `experiments` 测试在新环境的处理策略；`just test-full` 从此加载模型，随本票更新 AGENTS.md 重任务清单与 workflow.md 的 `test-full`／`gate-full` 描述；ADR-0005 加被 ADR-0007 部分替代的反向链接；`translation-baseline` recipe 与 translation-runtime 模块页的兼容引擎说明改为历史 | §9 的四项环境 smoke 全部通过并入库 `scripts/smoke/`、接 `just test-full`；`technology-stack.md`／`toolchain.md`／`workflow.md` 更新 | — |
| 02 | M2 配置与媒体 | `config.py`＋`kototoki.toml`、`recipes.py`（不含翻译配方）、`media.py`（probe 全字段与音轨选择含语言标签归一化、流复制与容器映射、从容器解码派生 WAV 与 verbose 日志、按布局 `pan` 常量下混、对视频流的时长校验、`offset_s = 0`） | 离线测试含合成的延迟音轨（断言 cue 时间等于视频时间）、中途间隙、5.1 满幅不削波、单声道；真实视频三份产物；派生 WAV 与现有 `hf-ii-full.wav` 对照（默认 swr 时 PCM SHA256 应一致） | 00 |
| 03 | M2 STT 三阶段 | `vad.py`、`asr_whisper.py`（torch 先于 ctranslate2 导入＋测试）、`align.py` 三个 worker；VAD worker 不加 FFmpeg PATH（01 smoke #2）；对齐字典只取 id < 模型 `vocab_size`（transformers 5.x 的 MMS 分词器多出 `|`＝2268，01 smoke #1） | 冻结窗口三阶段结果与现有同窗结果对照：窗口整数边界一致，ASR 文字逐字符一致（不一致即不通过），units 覆盖全文且时间差 ≤20 ms（超出另开票分析，不阻塞 05／06）；模块页 | 01, 02 |
| 04 | M2 日文 cue | `cues.py`：回填（插值、边缘外推、整窗按 VAD 子段 `fallback`）、三级切分、`lead_out_s`、`min_duration_s`、空／纯标点／♪ 处理，`ja.srt`＋`ja-cues.json` | 离线测试含非零 offset 只加一次；用现有 `result.json` 离线产出 `ja.srt` 人工看 5 分钟 | 00 |
| 05 | M3 翻译移植 | `translate/`（含 `translate/recipes.py`、v3 b10-joint hash 钉子测试）：session 传入、按批次落盘与续跑、基础设施失败同 run 重启 server 并记新 session、不取锁、配置化路径、run 目录按 `srt-<sha12>` 分键、启动前空闲显存检查、stock 引擎 `identity.json`；`merge.py`（中文换行替换为空格） | 伪客户端测试（正常、续跑、OOM 重启、缓存校验、空场景、`ja.srt` 变化换目录）；一部电影产出 `zh.srt`／`ja-zh.srt` | 01, 02, 04 |
| 06 | M4 批次编排 | `__main__.py`、`job.py`：扫描镜像、大小采样稳定性检查、发布前置判定、extract 先于 GPU、输出目录锁、worker 子进程与按文件重启、Job Object、唯一 GPU 锁与环境变量破锁、三份 SRT 一起发布、无语音路径、`PYTHONUTF8`、共用 `.work/cache/`、不含 torch 等推理包的测试；随本票把架构总览"只写 `.local/`"不变量改为产品例外并把入口加入 AGENTS.md 重任务清单 | 伪 worker 离线测试（含输出目录锁冲突、崩溃文件隔离）；中断后重跑能续 | 00, 02 |
| 07 | M5 x0 引擎 | `asr_qwen.py` worker；触顶窗口按 §6 置空并记 `failed_windows`；观察标点密度 | 同窗对照同 03 | 03 |
| 08 | M5 整片与文档 | 2 部电影整批运行（w0 与 x0 各一次）；架构总览、模块边界、README、AGENTS 触发表、GLOSSARY 收口（各票已随交付更新的部分只核对）；规格改 implemented | 验收记录入 `docs/research/acceptance/` 并登记索引 | 03–07, 09 |
| 09 | M3 翻译降级 | 10→5→1 拆批、子批次 ID 与降级树、单条回退与其终态语义、`report.json`、`translate/recipes.py` 中的 `b10-joint-degrade-v1` 与请求字节不变测试 | 伪客户端三级降级测试；一部电影真实运行记录降级次数 | 05 |

## 13. 评审修订记录

2026-10-14：主 agent 自审与独立 Opus 评审合并，修订：w0 worker 无 torch（cuDNN 同名冲突）；派生 WAV 从容器解码并贯通 `offset_s`；按声道布局下混；产物契约与 worker 协议独立成票 00；锁唯一归编排器；翻译 session 与按批次续跑；降级另立配方名；三份 SRT 一起发布；工作目录短 id；extract 先于 GPU；无语音与 x0 触顶的产品行为；stock llama.cpp 替代 ADR-0005 引擎条款待确认。

2026-10-14（续）：用户裁定 Python 环境整体退到 CUDA 12.8（torch 2.11.0+cu128），取消 CT2 侧车与无 torch worker；下混、默认 swr、stock 引擎、`b10-joint-degrade-v1` 按推荐采纳；llama-server 保留 CUDA 13.4 构建。

2026-10-14（第三轮，独立评审，用户全部采纳）：`offset_s` 恒为 0、零点由 `first_pts=0` 补齐（原方案双重计时且参考零点错）；产物坐标系写明；5.1 `pan` 常量与不削波；时长校验对视频流、verbose 日志入工作目录；翻译 run 目录按 `ja.srt` SHA 分键；发布覆盖规则按 `published.json` SHA 判定；输出目录锁；worker 按文件重启；x0 触顶窗口置空；票据 03 门禁加时间容差；`recipes.py` 归属拆分、05 依赖 02；产品测试放 `tests/` 并由 00 接线；AGENTS／workflow／ADR-0005 反向链接随 01／06 交付；`break_stale_lock` 改环境变量；删 `[vad] device`；语言标签归一化；小端 PCM 才映射 `.wav`；毫秒取整、`fallback` 命名、边缘插值、双语换行；DLL 共存证据修正与干净 PATH smoke、stock 引擎响应字段断言、smoke 各自子进程；启动 llama-server 前查空闲显存；清理 CUDA 13 时代残留文字。`forced_align` 在本机 torchaudio 2.11.0+cu128 只读核实存在。

2026-10-14（票据 01 实施）：四项环境 smoke 完成；torchcodec 改取 PyPI；VAD worker 不需要 FFmpeg PATH（§7.1 删除该条）；CT2 自带 cuDNN 调度器与 torch 子库并存经用户接受，§7.1／§7.2／§9 表述随之修正；MMS 分词器多出 `|` 记入票据 03。

2026-10-14（票据 02 实施）：用户裁定重采样由默认 swr 改为 soxr 28 bit（§1.2、§2.2；ADR-0007 中"重采样保持默认 swr"一句为当时裁定，不改写）；swr 在 verbose 下只报告部分补偿，`extract` 另记净补偿（§2.2）。

2026-10-14（票据 04 实施）：`max_gap_s` 初值 0.4 → 1.0（前 5 分钟观感：0.4 时 ≤2 字条目 374 条，1.0 时 123 条）；整窗 `fallback` 每字符时长上限 `FALLBACK_MAX_CHAR_S = 0.25` s 归入 cue 配方 hash（票据 02 收编）；`rules` 为与 `[cues]` 表同形的映射；`max_chars` 计入附着标点、非词汇串分配、cue 时间只取词汇字符、零时长补 1 ms 等实现细节经用户确认，见[日文 cue](../architecture/modules/japanese-cues.md)。

2026-10-14（票据 03 实施）：§7.1 两处与目标架构对齐——ASR 引擎由 jobs 的 `config.engine` 选择（不另设 `--engine` 参数），离线环境由编排器为 worker 子进程设置；冻结窗口门禁三阶段结果与现有同窗结果全等（窗口、文字、token、unit 时间），见 [STT worker](../architecture/modules/stt-workers.md)。

2026-10-14（票据 05 实施）：翻译 run 目录在 `srt-<sha12>/` 下再按 `<配方名>__s<seed>/` 分目录（与 v3 run_id 同形），否则改 seed 重试会被 run.json 不一致拒绝；llama-server 由整批共用，运行日志放 `.work/translate-sessions/`（§4）。见[翻译子系统与双语合并](../architecture/modules/translation-subsystem.md)。

2026-10-14（票据 09 实施）：降级的单条子批次命名为 `父ID.a.1`…（§6 只规定了两半的 `父ID.a`／`父ID.b`）；奇数条批次前半多 1 条，只有 1 条的批次失败即回退；降级中各节点结果追加写 `degrade.jsonl`，续跑不重做已有结果的节点；`report.json` 放在 `<配方名>__s<seed>/` run 目录内（每个配方与 seed 各一份）。用户裁定删去 §6 的“`force = true` 重跑整个翻译阶段”：`force` 只管最终文件覆盖，回退的 cue 只经改 seed 重试（最小设计，不为罕见的回退另加重译开关）。

2026-10-15（最终验收）：soxr 28 bit 的派生 WAV 使 Pyannote 少保留约 9–10% 语音，产品 CER 比 2026-10-05 基线高 0.5–3.5 个百分点（删除增多）；见[最终验收](../research/acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)。随后用户裁定三项并建票：重采样改回默认 swr（票据 10，§1.2、§2.2，`MEDIA` 配方 hash 变化、已有 `.work` 整条链重跑）；`DURATION-<lang>` 误判修复（票据 11，§2.2 时长来源优先级）；间隔断句只在跨 VAD 子段时成立（票据 12，§5.2，`CUES` 配方 hash 变化；样本中 1969 s 处的两字落在 VAD 漏检的拖长音上，新规则未能合并）。

2026-10-15（票据 13 调研）：把 ASR token 边界带进 cue 切分的方案经四部整片离线统计只减 12 条 ≤2 字条目且引入 >6 s 条目，不能修复票据 12 的样本（Whisper 日文 token 接近单字）；用户裁定不实现，根因归 VAD 召回。见[cue token 边界调研](../research/2026-10-15-cue-token-boundary-study.md)。

2026-10-15（票据 14 实施）：阶段链、worker 输入名、模型文件清单与各阶段期望身份从 `job.py`、三个 worker 壳与伪 worker 收进新模块 `kototoki/plan.py`（§4 身份归属随改）；身份字段、键名与取值逐字节不变，现有工作目录续跑不受影响。review 修订：`engine` 改为可选关键字、`advance` 对终态报错、编排侧改名 `advance_or_fail`。见[阶段计划](../architecture/modules/stage-plan.md)。

2026-10-15（票据 15 实施）：翻译 run 目录键、翻译身份与"是否需要模型"归翻译子系统 `translate.plan`（§1.2 已记）；`translate/data.py` 并入 `batching.py`。review 修订：GPU 锁的翻译阶段获取移进 `translate_batch` 并只在有文件 `needs_model` 时发生，session 失败只影响需要模型的文件，`TranslatePlan` 类型化（§3.3 随改）。配方内容变了而名字未变时 `plan` 拒绝并提示删目录，不自动另开目录（零迁移，与 v3 一致）。
