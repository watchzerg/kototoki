# ADR-0007：中日双语字幕流水线的产品架构、输入与发布

状态：已接受，已实现。2026-11-18 按主题合并（用户授权）：并入 ADR-0020、ADR-0027，原文见 git 历史（提交 807de3e 及之前）。  
范围：产品包 `kototoki/` 的工程架构：阶段链、环境、配置、输入范围、工作目录、产物与续跑、时间轴、锁与进程、发布。模型与配方身份不在此决定：STT 见 [ADR-0003](0003-new-pyannote-baselines.md)，翻译见 [ADR-0029](0029-translate-per-cue-resolution.md)，建表见 [ADR-0028](0028-names-accept-empty-table.md)，内嵌日文字幕见 [ADR-0024](0024-embedded-japanese-subtitles.md)，模块边界与失败级别见 [ADR-0025](0025-product-package-boundaries.md)，研究与产品的代码边界见 [ADR-0031](0031-research-layout-and-lightweight-records.md)。完整设计见[技术设计](../specs/bilingual-subtitle-pipeline.md)与[架构总览](../architecture/INDEX.md)。

## 决定

### 阶段与整批推进

GPU 阶段按"阶段 × 整批"推进，每阶段一个子进程。阶段链为 `vad` → `asr` → `align`（MMS）→ `cues` → `names` → `translate`（`kototoki/plan.py` 的 `STAGES`），publish 是终态。加载一个模型跑完整批再卸载；CPU 阶段（ffmpeg 提取、cue 切分、合并）是独立队列，可与 GPU 并行。不提供批次切分参数。翻译见 ADR-0029，建表见 ADR-0028。

### 翻译单元

翻译单元是日文 cue，不是 ASR 窗口文本。翻译输入固定为 `ja.srt`，每条中文继承日文 cue 的编号与时间，与日文一一对应。翻译失败的降级与收下规则见 ADR-0029。

### 统一 CUDA 12 环境

一个统一的 CUDA 12.8 Python 环境：Python 3.13、torch 2.11.0+cu128、torchaudio 2.11.0、torchcodec 0.17.0、transformers 5.19、pyannote.audio 4.0.7、faster-whisper 1.2.1／CTranslate2 4.8.3，由根 `pyproject.toml` 经 uv 管理（Torch 走显式 cu128 索引）。选版规则：CUDA 12 与 Python 3.13 是锚点，受其限制的组件一起锁定，其余取最新稳定版；版本以[技术选型](../development/technology-stack.md)为准。升级 Torch／CT2 会改变数值，等于新身份。

### 设备

ASR 与强制对齐只跑 GPU，不回退 CPU；VAD 固定 `cuda:0`，不设配置键，破除死锁用一次性环境变量。

### 配置文件驱动

无 CLI：入口 `python -m kototoki`，输入／工作目录、模型目录、并发、cue 显示规则、翻译 seed、`[stt] engine`、`[names]`、`[input] extensions` 等放 `kototoki.toml`；解码、采样、提示、窗口等影响模型行为的常量留在代码里作为配方常量，改动即新配方 hash。

### 输入范围

1. 音频文件也是输入。扫描 `input_dir`（递归）时扩展名清单默认为视频 `.mkv .mp4 .m2ts .ts .mov .avi` 加音频 `.wav .flac .mp3 .m4a .aac .ogg .opus .mka`（配置键 `[input] extensions`）。视频还是音频由 ffprobe 判定：除封面图（`attached_pic`）外没有视频流即为音频。
2. 音频文件走同一条阶段链，同一配方解码、下混、重采样为 `audio-16k.wav`。时长校验对所选音轨的时长（无流时长时用容器时长），解码短于它只告警、不判截断：没有画面要对齐，而 VBR MP3 缺 Xing 头时 ffprobe 的时长是按码率估的。视频输入仍是短于视频流超过 1 s 判失败。
3. 视频与音频输入的 extract 相同：只从输入容器解码派生 `audio-16k.wav`，写 `extract.log`；不流复制原始音轨，不写 `audio.<ext>`，`probe.json` 的 `extract` 记录没有 `audio_copy` 字段。

### 工作目录

`[paths] work_dir` 默认仓库内 `.local/work/`（已被 Git 排除），不得位于 `input_dir` 内，也不得位于仓库内 `.local/` 以外。每个目标目录在其下有一个子目录 `<work_dir>/<input_dir 末段名>-<绝对路径 sha12>/`，内含 `lock`、`input.json`（目标目录绝对路径）、`index.json`、每片 `<id>/`、运行日志与 server 运行证据；`cache/`（`HF_HOME`／`TORCH_HOME`、模型核对缓存）在 `<work_dir>/cache/` 由各目标目录共用。目标目录改名或移动后对应不上旧子目录，从头重跑。目标目录不放任何中间文件。

### 产物与续跑

每个视频一个工作目录，所有中间产物（16 kHz WAV、VAD／ASR／对齐 JSON、cue JSON、专名表、翻译 run）全部保留并带输入身份与配方 hash；产物匹配即跳过；身份不匹配的中间产物原地替换；翻译 run 目录按 `ja.srt` 的 SHA256 分键保留。无时间字符在 cue 阶段不插值、不整窗回退，对齐证据不改写。

### 时间轴与解码

模型输入 WAV 直接从视频容器按绝对流索引解码，用 `aresample=async=1:first_pts=0` 补齐起始静音，使 sample 0 对齐视频 0 秒；`offset_s` 恒为 0，音轨 `start_time` 只作诊断记录；各阶段产物使用本地坐标，cue 阶段只加一次 offset。下混按声道布局（单声道直通、双声道 0.5/0.5、5.1 以上标准矩阵含中置）；重采样用 ffmpeg 默认 swr（soxr 会使 Pyannote 少保留约 10% 语音、CER 高于基线）。

### 锁与进程

只有编排器持有 `.local/gpu.lock`，worker 不取锁并进入 KILL_ON_JOB_CLOSE Job Object；编排器不 import torch。编排器另持 `<work_dir>/<目标目录子目录>/lock` 防止同一目标目录并发；worker 崩溃按文件隔离重启。GPU 锁冲突的失败级别见 ADR-0025；Strata 的启停见 ADR-0029。

### 发布

最终产物只有 `<源文件所在目录>/<主名>.ja-zh.srt`；`ja.srt` 留在工作目录，不发布单独的 `zh.srt`。无语音的文件同样发布零条目的 `ja-zh.srt`。

1. 已存在即跳过：扫描时源文件旁已有 `<主名>.ja-zh.srt`（只看文件名，不论是否本项目生成）即跳过该文件，不进任何阶段；要重做就删掉这份字幕。没有 `force` 与覆盖判定。
2. `published.json` 只作审计记录（双语字幕的 SHA256、来源身份、翻译 run 目录）。
3. 主名冲突：同一目录里主名相同的两个输入（如 `ep01.mkv` 与 `ep01.mp3`）争用同一份字幕路径，按相对路径排序靠后的那个在扫描阶段报错、记为失败，其余照常。

## 依据

- 翻译峰值显存 15.7–15.8 GB 占满整卡，任何共驻方案都不可行；分阶段批处理把每个模型的加载开销摊到整批，代价是首个结果要等整批 STT 结束，用户接受。
- 以 cue 为翻译单元，因为翻译的质量证据与续跑逻辑都建立在 cue ID 一一对应之上；基于窗口文本需要未解决的中文→时间回映射。
- 统一 CUDA 12：CTranslate2 只有 CUDA 12 wheel，且其 cuDNN 9 DLL 与 CUDA 13 构建同名、同进程只能加载一份；4.8.3 Windows wheel 在 sm_120 上靠驱动 JIT。单 venv 混装 cu12／cu13 取决于 DLL 搜索顺序，不可靠。产品不依赖 WhisperX（绑死 transformers 4.x 与 Torch 2.8）；torchaudio `forced_align` 在本机 2.11.0+cu128 存在；Python 3.15 缺 CT2／torchaudio／torchcodec wheel。
- 输入与发布（用户决定，2026-11-08）：目标目录里的音频也要出字幕；中间文件不该污染目标目录；播放器按主名自动加载同目录字幕，因此只把双语字幕放到源文件旁。"已存在即跳过"比按 SHA 判定覆盖简单，且不会覆盖片源自带或用户自制的同名字幕。
- 不流复制原始音轨（用户决定，2026-11-17）：副本从一开始只作归档，模型输入直接从容器解码，没有阶段读它；它还让可出字幕的文件整片失败（232 片批次中有一片的 AAC 有 3 个坏包，复制到 m4a 时 `aac_adtstoasc` 报错使整片判失败，而解码路径能跳过坏包）；并且多读一遍源文件，USB 盘 I/O 是瓶颈（约 4 h／232 片）。先复制到 `.mka` 再从副本派生的方案会让 PCM 可能不再逐字节一致，需新 `MEDIA` 版本与验证，且无法降级，未采纳；复制失败降级为告警只修失败，用户裁定副本本身不需要。

## 约束与未关闭项

- 根环境含 Torch 等推理依赖；三个历史环境保留供复现；产品包从 `archive/2026-11-18-pre-research-restructure:experiments/` 复制并精简实现，不导入历史包，历史目录冻结。
- **重新评估 CUDA 版本的触发条件**：CT2 发布 CUDA 13 wheel；某必需组件要求 torch > 2.11；整片验收显示 ASR 阶段是墙钟瓶颈。届时形态是给 ASR worker 一个独立 cu12 侧车 venv，或改用 HF Whisper，不采用单 venv 混装。
- 未采用：逐文件全流程调度、翻译基于 ASR 窗口文本、Python 3.14／3.15、CT2 源码构建、soxr 重采样、批内语序自由、跨文件术语一致（后两者登记为未来方向）。
- "CT2 共用 torch DLL"只证明同版本可共存；不加 DLL 目录能否解析以干净 PATH 下的 smoke 为准。
- 音频输入只经离线测试与合成 ffmpeg 测试验证，未用真实音频文件跑过整条链。音频输入不因时长偏短而失败，代价是真正损坏、只解码出前半段的音频文件也会照常出字幕（只覆盖前半段），只在运行日志留 WARNING。
- 改了配方（如 cue 规则、翻译配方）后，已发布字幕不会自动重做；需删掉 `*.ja-zh.srt` 再运行（中间产物按身份续跑，只重做受影响的阶段）。
- 目标目录须可写；只读或网络盘上的目录未验证。
- 不再流复制音轨：该片重跑未复现（源盘不在线），预期 extract 成功；抽取阶段实际省下的时间未测量。

## 沿革

- 2026-10-13／14：ADR-0007 定阶段 × 整批、cue 为翻译单元、统一 CUDA 12、配置驱动、产物续跑、时间轴、锁与发布。
- 2026-11-08：ADR-0020 音频也作输入，工作目录移出目标目录，只发布 `ja-zh.srt` 到源文件旁，已存在即跳过，删 `output_dir` 与 `force`。
- 2026-11-08／09／11：翻译与建表引擎、降级配方改由 ADR-0019／0022 等接管，现行见 ADR-0029、ADR-0028。
- 2026-11-17：ADR-0027 不再流复制原始音轨，extract 只派生 `audio-16k.wav`。
- 2026-11-18：按主题合并 ADR-0020、ADR-0027 入本文；翻译与建表相关条款改指向 ADR-0029、ADR-0028。
