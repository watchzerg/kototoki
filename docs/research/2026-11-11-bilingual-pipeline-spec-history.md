# 双语字幕流水线技术设计：拆分时移出的历史原文

状态：concluded（冻结记录：技术设计 2026-11-11 拆分时移出的原文，含状态行修订历史、已裁定表、环境与上游版本核实、草案验收、未来方向、里程碑与评审修订记录；原文未改）  
日期：2026-11-11  
范围：[技术设计](../specs/bilingual-subtitle-pipeline.md) 2026-11-11 拆分前（提交 a9c1da6）的原状态行、§1.2 已裁定表、§2–§6 中移出的原文节选、§7.2–§7.4 环境与上游版本核实、§8、§9、§11、§12、§13 原文；只改了相对链接以适应新位置。现行规则见技术设计、模块页与 [现行决定](../adr/CURRENT.md)。

## 原状态行

状态：implemented（2026-10-14，票据 00–09 交付，两部整片验收见[验收记录](acceptance/2026-10-14-bilingual-pipeline-fullfilm.md)；2026-10-15 最终验收后票据 10–15 完成，票据 13 裁定不实现；2026-10-18 票据 16 把产品配方换成 `dp10-cut-degrade-v1`（[ADR-0010](../adr/0010-dp10-cut-translation-flow-baseline.md)）；2026-10-20 新增专名一致性（`names` 阶段与发布时替换，[ADR-0014](../adr/0014-name-consistency-in-product.md)）；**2026-11-08 产品翻译切到 Q2、取消发布时替换（[ADR-0019](../adr/0019-product-translation-q2.md)，下文标"ADR-0019"之处为现行规则，其余 Hy-MT2／`dp10-cut-degrade-v1`／替换的描述是历史设计依据）**；ADR-0020 起输入含音频、工作目录外置、只发布双语字幕到源文件旁，见 §13）。设计收口于 2026-10-13，2026-10-14 按三轮评审修订并改为 CUDA 12 统一环境（§13）；取舍记录在 [ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)。当前行为以[架构总览](../architecture/INDEX.md)中的产品模块页为准，本文保留设计依据与裁定

### 1.2 已裁定（2026-10-13）

| 事项 | 结论 |
| --- | --- |
| 默认 STT 引擎 | `w0`；两片合并 CER 15.25% 对 x0 16.68%，推理快约 2.5 倍，无生成触顶 |
| 批次粒度 | 第一版不提供 `--batch-size`，整批按阶段推进 |
| 无时间字符 | 产品端插值＋整窗回退，在 cue 文件里记账；内部方案另行细聊 |
| 音频产物 | 原始编码流复制保留；派生的 16 kHz WAV 也保留，不删除 |
| 输出位置（ADR-0020） | 最终 `<stem>.ja-zh.srt` 写在源文件旁；工作目录在 `[paths] work_dir`（默认仓库 `.local/work/`）下按目标目录分子目录，不写进目标目录 |
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
| 产品翻译配方 | `q2-degrade-v1`（2026-11-08 起，ADR-0019；2026-10-18..11-08 为 `dp10-cut-degrade-v1`；之前为 `b10-joint-degrade-v1`） |

第三轮评审（2026-10-14，独立评审）采纳的裁定：

| 事项 | 结论 |
| --- | --- |
| 时间轴零点 | 派生 WAV 用 `async=1:first_pts=0` 补齐起始静音，sample 0 即输入 0 秒；`offset_s` 恒为 0，音轨 `start_time` 只进 `probe.json` 作诊断，不再贯穿链路（§2.2） |
| 产物坐标系 | 各阶段 JSON 一律本地秒（与 WAV 一致）＋顶层 `offset_s`；cue 时间只在 ja-cues 阶段加一次 offset（§4） |
| 5.1 下混 | 每种声道布局的 `pan` 表达式写死为配方常量，含归一化系数，禁止削波（§2.2） |
| 时长校验 | 视频输入对照第一条视频流时长：解码短于它超过 1 s 判失败；音频输入对照所选音轨时长：短于它只告警（ADR-0020）；两者长于参照都只告警，无流时长时用容器时长；ffmpeg verbose 日志入工作目录（§2.2） |
| 翻译 run 目录 | 按 `translate/srt-<sha12>/<配方名>__s<seed>/` 分键，键由翻译子系统 `translate.plan` 唯一给出，`published.json` 指向当前使用的那份（§4，票据 15） |
| 发布与跳过（ADR-0020） | 源文件旁已有 `<stem>.ja-zh.srt`（只看文件名）即在扫描阶段跳过；没有 `force`，要重做就删掉该字幕；`published.json` 只作审计记录（§4） |
| 工作根目录锁 | 启动即取 `<work root>/lock`（同一 `input_dir` 同时只一个编排器，退出码 3），GPU 锁在 GPU 阶段前取（§3.3） |
| worker 重启 | 按文件计：崩溃时正在处理的文件记该阶段失败，从下一文件重启；不再"整阶段只重启一次"（§3.1） |
| x0 触顶窗口 | 该窗 `text` 置空、截断文字记入 `failed_windows`，不进对齐与翻译（§6） |
| 票据 03 门禁 | ASR 文字必须逐字符一致；unit 时间允许 ±20 ms（1 帧），超出另开票但不阻塞 05／06（§12） |
| `break_stale_lock` | 不进配置文件，改为环境变量 `KOTOTOKI_BREAK_STALE_LOCK=1` 一次性生效（§10） |
| VAD 设备 | 第一版固定 `cuda:0`，不设配置键；CPU 仍列未来方向（§10） |
| 产品测试位置 | `tests/`，由票据 00 建目录并把 `kototoki/` 接进 `just check`／`just test`（§12）；2026-10-18 起分为 `tests/core/`（`just test`）与 `tests/full/`（`just test-full`），都不调用真实模型，真实模型验证走 `just smoke`（[开发工作流](../development/workflow.md#测试分层与资源边界)） |
| 翻译配方归属 | 只住在 `kototoki/translate/recipes.py`（05 建、09 改）；`kototoki/recipes.py` 只放 STT／cue／媒体常量（§7.3） |

## 原第 2 至 6 节中移出的原文

下面是原 §2 的阶段表（含单片成本列）、原 §2.2 的重采样器一条、原 §3.2 与原 §3.4 全文；§2–§6 其余内容仍在技术设计里或已由模块页覆盖。

### 2. 阶段分解（原阶段表）

| 阶段 | 做什么 | 输入 → 产物 | 设备 | 单片成本（2 h 电影，来自整片证据） |
| --- | --- | --- | --- | --- |
| probe | ffprobe 读取全部流：音轨按 `language=jpn` 且非 `disposition.comment` 优先，再按 `disposition.default`，多条匹配告警并记录；没有匹配选第一条音轨并告警；记录绝对流索引、编码、声道布局、`start_time`、时长，以及字幕流清单（供内嵌日文字幕选轨，见下方"内嵌日文字幕"）；`has_video`（除封面图 `attached_pic` 外没有视频流即为音频文件）、`duration_s` 与 `duration_source` | 视频／音频 → `probe.json` | CPU | <1 s |
| extract | ① （仅视频）ffmpeg `-c:a copy` 把选中音轨原样写出，容器按 §2.1 选；音频文件跳过 ①，`extract.audio_copy` 为 null；② 从输入容器按绝对流索引解码该音轨，`aresample=async=1:first_pts=0` 保留时间轴（起始静音补齐、间隙补零，sample 0 即输入 0 秒），按 §2.2 下混，重采样 16 kHz，PCM16 WAV；ffmpeg verbose 日志写入工作目录；校验解码时长对所选音轨时长（§2.2）；记录 PCM SHA256、样本数、`offset_s = 0` | 输入 → `audio.<ext>`（仅视频）、`audio-16k.wav`、`extract.log` | CPU | ① 秒级 ② 约 10–30 s |
| vad | Pyannote 检测 → 源跨度合并 → manifest | `audio-16k.wav` → `vad.json` | GPU（VAD 允许 CPU） | 加载 28 s，推理 20 s |
| asr | 逐窗识别，纯文字 | `audio-16k.wav`+`vad.json` → `asr.json`（`cross` 另写审计文件 `asr-w0.json`、`asr-x0.json`、`asr-judge.json`） | GPU | w0：加载 7 s，推理 150–170 s；x0：加载 19 s，推理 365–395 s；`cross`：两部电影 asr 阶段 1211.6 s，为 w0 阶段（323.4 s）的 3.75 倍（w0 转写 286.0 s＋x0 转写 863.7 s＋Whisper 打分 40.7 s＋加载与启动，[验收记录](acceptance/2026-10-19-cross-asr-acceptance.md)） |
| align | 逐窗 CTC 对齐，字符时间 | `audio-16k.wav`+`asr.json` → `align.json`（现有 `result.json` 结构） | GPU | 加载 17 s，推理 53–56 s |
| ja-cues | 字符 units → 日文 cue，含无时间字符的时间回填 | `align.json` → `ja.srt`+`ja-cues.json` | CPU | <1 s |
| names | 在与翻译共用的 Strata session（Qwen3.8-Flash-Next）上把整份 `ja.srt`（剥时间轴、带 cue 编号）一次送入，按 JSON schema 解析专名表并归一，不合格依次换 seed 最多 5 次请求；终态失败写空表（见 §6）；零条目不请求 | `ja.srt` → `name-table.json` | GPU（整批共用一个 Strata session，与 translate 同一个） | Strata 加载约 75–100 s（整批一次，与翻译共摊）；每部建表耗时以 ADR-0022 所指计划 §7 的实测为准 |
| translate | 产品配方 `q2-degrade-v1` 整片翻译（ADR-0019；之前为 `dp10-cut-degrade-v1`，ADR-0011），续跑语义沿用 v3；Strata 由产品自动启停（§3.3） | `ja.srt`＋`name-table.json` → `zh.srt`+翻译 run 目录 | GPU（独占） | Q2：HF-II 1099 条、149 包约 2498 s（每包约 16 s），另加 Strata 加载约 98 s（2026-11-08）；此前 H0 为 1993 条约 270 s、387 条约 66 s |
| ~~替换~~ | 已删除（ADR-0019）：不再有发布时替换、`names-apply.json` 与 `names_apply` 身份键；专名译法只经翻译注入 | — | — | — |
| merge | 按 cue 编号合并 | `ja.srt`+`zh` → `ja-zh.srt`（发布到源文件旁） | CPU | <1 s |

### 2.2 时间轴与下混（原重采样器一条）

- **重采样器**：降采样用 ffmpeg 默认 swr（`aresample=16000`），与 `async=1:first_pts=0` 的时间轴补偿同为 swr。2026-10-14 曾裁定改 soxr 28 bit，2026-10-15 最终验收发现 soxr 版派生 WAV 使 Pyannote 少保留约 9–10% 语音、产品 CER 比 2026-10-05 基线高 0.5–3.5 个百分点，而产品 VAD 在 swr 版 WAV 上与基线窗口完全相等，用户裁定改回（票据 10）。保留 2026-10-14 的频谱对比供参考：在 HF II 整片对比中，6 kHz 以下两者差异比信号低约 79 dB，差别集中在 7.8–8 kHz（swr 残留 −8.3 dB，soxr −44.9 dB，即 swr 边缘的折叠残留），削波无差别（各 1–2 个样本）；默认 swr 时派生 WAV 与基线 `hf-ii-full.wav` 的 PCM SHA256 一致（票据 02 与票据 10 均核对为 `ee4e2da3…`）。频谱上更干净没有换来识别率：Pyannote 对 soxr 版音频更保守，这是改回的直接原因。

### 3.2 为什么这样选

| 考虑 | 分阶段批处理（采用） | 逐文件全流程 |
| --- | --- | --- |
| 显存 | 任一时刻只有一个模型驻留；翻译峰值 15.7–15.8 GB 已接近 16 GB 整卡，无法与任何 STT 模型共存。**例外**：`cross` 引擎的 asr 阶段内 Whisper 与 Qwen 同进程共驻，整卡峰值实测 10688 MiB（T0 探针）／10030 MiB（产品路径验收）；探针实测峰值加 1 GB 余量仍 ≤ 13.5 GB 才共驻（已通过），否则回退为 Whisper 整批转写 → 卸载 → Qwen 整批转写 → 卸载 → Whisper 整批打分的三段式，产物与接口不变（回退未实测）。MMS 对齐与翻译不变，仍独立阶段、不与之共驻 | 需要 VAD+ASR+MMS 共驻（估计 10–12 GB，未验证），翻译仍必须单独一段 |
| 模型加载开销 | 每阶段每批一次：Pyannote 28 s、MMS 17 s、whisper 7 s、Qwen 19 s、Strata 约 75–100 s（建表与翻译共用一次） | 每文件重复一次，20 部电影多付约 20–40 分钟 |
| 首个结果出现时间 | 整批 STT 结束后才有第一份 `ja.srt`，整批翻译结束后才有第一份双语 SRT | 第一部电影约 10 分钟后完成 |
| 失败隔离 | 一个文件失败只跳过它，阶段继续 | 同样可做 |

批量生产场景下吞吐与显存安全优先，接受首个结果延迟。需要更早看到结果时，用户可以自行分几次调用。

### 3.4 时间线示意（4 部电影、w0）

```
CPU:  ex1 ex2 ex3 ex4 | ............ | cue1-4 | ............ | ............ | apply+merge1-4
GPU:      [VAD 1 2 3 4][ASR 1  2  3  4 ][MMS 1 2 3 4][names 1 2 3 4][translate 1 2 3 4]
```

单片 GPU 成本约 50+165+73+45+300 ≈ 10.5 分钟（w0），4 部约 42 分钟；整批 extract 约 1–2 分钟，先于 GPU 阶段完成。

## 7. 进程、环境与依赖

### 7.2 环境：一个统一的 CUDA 12.8 环境

现状三个隔离环境版本互斥（见[环境清单](2026-10-04-runtime-inventory.md)）：

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

**llama.cpp 改用官方 b11583 构建**（2026-11-08 起产品只有 names 建表还用 llama-server，翻译已换 Strata，ADR-0019；2026-11-09 起建表也换 Strata，产品不再用 llama-server，llama.cpp 只供研究侧，ADR-0022）：上游 2026-07-13 合并 `hy_v3` 架构；本机 APEX-I-Compact GGUF 的路由偏置张量已是上游命名 `blk.N.exp_probs_b`（2026-10-13 本地读取确认），旧补丁针对的 `.bias` 命名问题不存在。这替代了 [ADR-0005](../adr/0005-apex-i-compact-translation-baseline.md) 中"继续使用 b11429 兼容 loader、不以 stock 引擎替代"的条款（用户 2026-10-14 确认），由 ADR-0007 记录。票据 01 的 smoke 要对比兼容引擎与 stock 引擎的 `/tokenize` 输出与固定 seed 的短生成，并在一个真实 b10 批次上测量显存峰值（现有 15.7–15.8 GB 是兼容引擎的数字）。`ManagedServer` 要求的 `identity.json` 与驻留日志解析按 stock 构建适配。

**依赖管理**：根 `pyproject.toml` 改为产品项目 `kototoki`，运行时依赖写入 `dependencies`，`[[tool.uv.index]]` 声明 `pytorch-cu128`（`explicit = true`），`[tool.uv.sources]` 把 torch／torchaudio／torchcodec 指向该索引，`tool.uv.environments` 限 win32，`uv.lock` 锁定；测试工具放 dependency group。后果：根环境从此有 Torch，`experiments/` 中原本因缺 NumPy／Torch 跳过的离线测试会实际运行。三个历史环境保留供复现，不删除。

**升级即新身份**：Torch／CT2／llama.cpp 版本变化会轻微改变数值，必须在冻结输入上与现有基线成绩回归后才算接上基线（本期不做，见 §11）。

**后续可选实验（不在第一版）**：用 HF transformers 的 Whisper 实现（纯 PyTorch）替换 CT2，解除 CUDA 12 锁定、跟上最新 torch。代价是速度约慢 1.5–3 倍、文字与现 W0 有细微差异，需要独立的等价性验证。另一条路是保留 CT2、只给 ASR worker 一个独立的 cu12 侧车 venv，让其余 worker 跟最新 torch；触发条件见 ADR-0007。

### 7.3 代码布局

各模块的接口以模块页为准，依赖方向、接缝裁定与责任边界以[模块边界](../architecture/module-boundaries.md#产品包的责任边界)为准（原目标架构页于票据 08 并入后删除）。下表是实现时（票据 00–09）的文件与来源对照，**冻结于 2026-10-14，不再随后续票据维护**；当前文件布局以[架构总览的模块地图](../architecture/INDEX.md#模块地图)为准。票据 14 新增 `kototoki/plan.py`（阶段链与期望身份从 `job.py` 与三个 worker 壳迁出，见[阶段计划](../architecture/modules/stage-plan.md)），票据 15 把 `translate/data.py` 并入 `batching.py`。2026-10-20 起新增 `kototoki/names/`（专名建表）；Strata 生命周期与共享 session 在 `kototoki/strata.py`，本机回环客户端在 `kototoki/local_client.py`，进程原语在 `kototoki/procs.py`，见[专名一致性](../architecture/modules/name-consistency.md)与模块边界。

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
| `translate/`（2026-11-08 起，ADR-0019：`recipes.py` 产品配方 `q2-degrade-v1`、`batching.py`、`degrade.py`、`generate.py`；`adapters.py`、`server.py` 与 H0 配方已删除；`translate/recipes.py` 仍是翻译配方的唯一归属） | `experiments/translation_v3/{qwen,strata}.py` 的提示、请求体与 `probe`，`names11.product_tables` 的注入行，`wide-context-v1`，`translation_v3` 的 `batching`、`generate`（改为传入已建 session、按批次落盘）、`common`（路径改配置）、`data`（`Scene`／`Cue`），`translation_demo` 的 `client`、`explicit_oom`（现为 `kototoki/local_client.py`）；去掉 `mbr` 导入与裁判／统计命令。**以下为 2026-10-18 之前的来源，历史记录**：`translation_v3` 的 `recipes`、`server`、`procs`，`translation_demo` 的 `adapters`、`run`（资产清单），`translation_demo_runtime` 的驻留解析（驻留解析与 `ManagedServer` 随唯一使用者搬到研究侧 `experiments/translation_v3/llama_server.py`，ADR-0025） |
| `srt.py`、`merge.py` | `translation_flow/srt.py`（允许零条目） + 新写合并 |
| `schema.py` | `kototoki_eval/schema.py` 的 `validate_transcript` |

产品测试放 `tests/`（2026-10-18 起分为 `tests/core/` 与 `tests/full/`，分层见 workflow.md），不与模块同目录；票据 00 创建 `tests/__init__.py` 并把 `kototoki/` 接进 `just check`。现有 `kototoki_eval/` 保持评分用途不动。

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
- 环境 smoke（票据 01，脚本入库到 `scripts/smoke/`，并接到 `just test-full`，2026-10-18 起改由真实模型验证入口 `just smoke` 运行；每项各自在独立子进程运行，避免 PyAV 与 torchcodec 的 FFmpeg DLL 在一个进程里相遇）：① torchaudio 2.11.0 配 torch 2.11.0+cu128 的 `forced_align`（合成序列＋一个真实冻结窗口）；② pyannote 4.0.7＋torchcodec 0.17 在产品环境导入并对内存波形推理，列出进程实际加载的 FFmpeg DLL（若没有任何 `avcodec*` 被加载，则 VAD worker 不需要 FFmpeg PATH，§7.1 的那条随之删除）；③ **在不含 `whisper-runtime-provisional` 的干净 PATH 下**，同一进程先 import torch（cu128）再用 CT2 解码一窗，打印实际加载的 cudnn／cublas／cudart 模块路径，除 CT2 wheel 自带的 `cudnn64_9.dll` 外均来自 torch 目录，并记录 cuDNN 版本与是否 PTX JIT；④ 官方 llama.cpp 加载 APEX GGUF，与兼容引擎比对 `/tokenize` 与固定 seed 短生成，再发**同一 session 的第二个 `cache_prompt` 请求**并断言 `timings.cache_n`、`tokens_evaluated`、`stop_type`／`stopped_limit`／`truncated` 的含义与 v3 `run_step` 的假设一致，保存一份 stock 引擎加载日志供 `residency_evidence` 回归，测一个 b10 批次的显存峰值。
- GPU smoke：1 个 5 分钟片段走完 8 阶段，产物齐全、SRT 合法、双语对齐。
- 回归：II／III 上新环境与现有基线的 CER／时间指标对比（本期不做，§11）。
- 整片：2 部电影批量运行一次，记录各阶段墙钟、显存峰值与失败清单。

## 11. 未来方向（本期不做，只登记）

- **翻译批内语序自由**（**已关闭**，2026-10-18 用户裁定，见本条末项）：如 1+5+1、中间 5 条允许并句拆句与重排，需要新的中文→时间回映射方案与评估，是独立研究。2026-10-16 讨论（[v6 结题](2026-10-16-scene-aware-batching-v6.md)后）补充的方向：
  - 区分两个量。**包的大小**决定模型理解上下文的范围，应保持 10 条左右（v3：b5 不如 b10，"≤5 条、碰标点就切"无收益；v6：按 ≥5 s 静默切包收益很小且不复现）。**内容可挪动的范围**是另一回事，应按"同一句话"划分，而不是按包。
  - "同一句话"小组：相邻几行停顿很短（量级约 1 s，门槛待定）、连起来是一句完整的话，多数是 2～3 行。语序只允许在小组内调整；**停顿是硬边界**，内容不能跨停顿挪动，否则字幕会出现在无人说话的时刻。参考分布：相邻 cue 间隔中位数约 0.6 s、p90 约 4.3 s（v6 §2.1）。
  - 其他软件的做法（[Subtitle Edit](2026-10-05-translation-subtitleedit.md)、[VideoLingo](2026-10-05-translation-videolingo.md)、[pyVideoTrans](2026-10-05-translation-pyvideotrans.md)）：主流是把被拆碎的句子合并成整句翻译，再按标点、长度比例或让模型切回原时间段；Subtitle Edit 的合并门槛是相邻间隔 <1 s；公认难点是切回时行数、编号错位，都要加结构校验。
  - 现有裁判（`claude-opus-5-5-mqm-v1`）已允许相邻 cue 之间合理挪动内容，不计 cue-attribution 与漏译，所以评估面可直接比较"严格一一对应"与"小组内重排"。
  - 实现形状可以是：包仍为 1+10+1，包内按短停顿与句末标点标出小组并在提示里告知模型，grammar 仍按 cue ID 输出，只是允许同组内的 ID 互相挪内容；回映射因此不需要新的时间对齐，只需校验组内总长度与显示时长。
  - 2026-10-18 进展：划组规则经[离线统计](2026-10-18-reorder-group-offline-stats.md)定为 R2+（停顿 <1.0 s 且前一行不以 `。？！?!.` 结尾，剥右括号；产品 ASR 句末标点几乎全是半角，所以必须含半角），dev 上 78% 的 cue 落在多 cue 小组、产品 50%。研究侧[第八轮（v8）](2026-10-18-group-reorder-v8.md)验证了上一条的实现形状（包与 grammar 沿用 dp10-cut，只改提示并注入 `groups`）：**证伪**。两次小样 70 个多 cue 组里模型没有任何组内重排，两种措辞都如此，更强的措辞还引入邻文泄漏；且严格逐 ID 模式下模型已把每行译成自足中文。改输出契约的备选路线（每组输出一个字符串再程序切回）也做了预检（v8 §7.3）：模型拿到整组仍按日文行序翻译，54 组 0 例跨行重排，而 8 组把 <1 s 停顿内的不同说话人并成一句。
  - **2026-10-18 用户裁定：关闭这条线，不立项备选路线。** 翻译保持逐 cue 对应（本节表"翻译批内对应"一行即为最终形态）。重开前提是有说话人信息、能按"同一说话人的同一句话"划组。保留的设施：`translation_v3` 的 `grp1` 配方与 `batching.sentence_groups`、`experiments/reorder_groups/`。
- **跨文件术语一致**：同一剧集多集之间的人名、专名统一。v3 的 `terms` 配方未采纳，产品暂无跨文件记忆。**单片内一致已由 names 阶段覆盖**（2026-10-20，ADR-0014）：每部影片自己建表，不合并多张表、不跨文件共享。
- **用 HF transformers Whisper 替换 CTranslate2**，解除 CUDA 12 锁定（§7.2）。
- **重复／幻觉守卫**：W0 移植的 WhisperX 路径没有温度回退与压缩比检查，长重复输出目前只能靠 VAD 过滤减少；后续可加 n-gram 重复检测并标记。
- ~~利用视频内嵌日文字幕~~：已实现（2026-11-11，[ADR-0024](../adr/0024-embedded-japanese-subtitles.md)，§2"内嵌日文字幕"）。仍未做的相邻项：同目录外挂字幕、位图字幕 OCR。
- **双单声道（主／副音声）识别**、**粗回退按 VAD 子段分配时间**。
- **VAD 跑 CPU** 以让出显存；**升级后的回归与容差**；**单阶段子命令与 CLI**。

## 12. 实施里程碑

票据在 `.scratch/bilingual-subtitle-pipeline/issues/`（本地 tracker，不进 Git），编号与下表一致；依赖关系写在票据的 `Blocked by`。每张票交付时按[随交付同步](../agents/documentation.md#随交付同步)更新对应模块页，不把全部文档推到 08。下表只列设计时规划的票据 00–09；最终验收后的票据 10–16（重采样改回 swr、`DURATION` 标签优先级、间隔断句跨子段、cue 词边界调研、阶段计划模块、翻译 run 键、产品配方换 `dp10-cut-degrade-v1`）在 §13 记录裁定，细节在各模块页"变更与决策来源"。

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

2026-10-15（最终验收）：soxr 28 bit 的派生 WAV 使 Pyannote 少保留约 9–10% 语音，产品 CER 比 2026-10-05 基线高 0.5–3.5 个百分点（删除增多）；见[最终验收](acceptance/2026-10-15-bilingual-pipeline-final-acceptance.md)。随后用户裁定三项并建票：重采样改回默认 swr（票据 10，§1.2、§2.2，`MEDIA` 配方 hash 变化、已有 `.work` 整条链重跑）；`DURATION-<lang>` 误判修复（票据 11，§2.2 时长来源优先级）；间隔断句只在跨 VAD 子段时成立（票据 12，§5.2，`CUES` 配方 hash 变化；样本中 1969 s 处的两字落在 VAD 漏检的拖长音上，新规则未能合并）。

2026-10-15（票据 13 调研）：把 ASR token 边界带进 cue 切分的方案经四部整片离线统计只减 12 条 ≤2 字条目且引入 >6 s 条目，不能修复票据 12 的样本（Whisper 日文 token 接近单字）；用户裁定不实现，根因归 VAD 召回。见[cue token 边界调研](2026-10-15-cue-token-boundary-study.md)。

2026-10-15（票据 14 实施）：阶段链、worker 输入名、模型文件清单与各阶段期望身份从 `job.py`、三个 worker 壳与伪 worker 收进新模块 `kototoki/plan.py`（§4 身份归属随改）；身份字段、键名与取值逐字节不变，现有工作目录续跑不受影响。review 修订：`engine` 改为可选关键字、`advance` 对终态报错、编排侧改名 `advance_or_fail`。见[阶段计划](../architecture/modules/stage-plan.md)。

2026-10-15（票据 15 实施）：翻译 run 目录键、翻译身份与"是否需要模型"归翻译子系统 `translate.plan`（§1.2 已记）；`translate/data.py` 并入 `batching.py`。review 修订：GPU 锁的翻译阶段获取移进 `translate_batch` 并只在有文件 `needs_model` 时发生，session 失败只影响需要模型的文件，`TranslatePlan` 类型化（§3.3 随改）。配方内容变了而名字未变时 `plan` 拒绝并提示删目录，不自动另开目录（零迁移，与 v3 一致）。

2026-10-18（票据 16 实施，[ADR-0010](../adr/0010-dp10-cut-translation-flow-baseline.md)）：用户裁定把研究基线 `dp10-cut` 合并到产品，产品配方改为 `dp10-cut-degrade-v1`（§1.2 两处、§6 已改）：`Cue` 带 `ja.srt` 的起止秒，切包与邻文按 ADR-0010，降级子批次用同一条邻文规则；不迁移旧 run、不加开关，已交付影片的翻译身份过期、下次整批重译（用户接受）。`tests/test_translate.py` 的合成 SRT 每 10 条之间留 20 s 停顿，使批次机制用例仍是 10 条一批。

2026-10-19（`cross` 引擎，[ADR-0012](../adr/0012-cross-asr-judge.md)，已接受）：用户裁定在 asr 阶段内新增可选引擎 `cross`（w0 与 x0 共驻、逐文件两路转写、Whisper 交叉打分合并），默认仍为 `w0`，阶段链与下游接口不变；本文 §1.1、§2、§3.2、§4、§7.1、§10 已按交付行为改写。同日产品路径验收（[验收记录](acceptance/2026-10-19-cross-asr-acceptance.md)）：HF II／III 官方整片口径两部合计 CER 15.25% → 14.30%，降 0.95 pp，**低于预设的 1.0 pp 验收线**，用户裁定仍采用并保持默认 `w0`；asr 阶段墙钟为 w0 的 3.75 倍，整卡峰值 10030 MiB，翻译阶段照常启动。译文层收益与新材料确认未测，改默认须新 ADR。

2026-10-20（专名一致性进产品，[ADR-0014](../adr/0014-name-consistency-in-product.md)）：用户裁定把 ADR-0013 冻结的最佳已知配置（提示 v5 建表、规则一＋孤立单字替换）接入产品：新增 GPU 阶段 `names`（`ja-cues` 与 `translate` 之间）与发布时的 CPU 替换，`[names]` 配置节，`name-table.json`／`names-apply.json` 与 `published.json.sources` 的 `names`／`names_apply` 键；建表终态失败写空表照常发布，已交付影片下次整批运行建表并重新发布、不重译（§1.1、§2、§3.1、§3.3、§3.4、§4、§6、§7.1、§7.3、§10、§11 已改）。两部整片产品路径验收与等价校验见[验收记录](acceptance/2026-10-20-name-consistency-product.md)。

2026-11-08（产品翻译切到 Q2，[ADR-0019](../adr/0019-product-translation-q2.md)）：用户裁定产品翻译与基线同为 Q2：配方 `q2-degrade-v1`（Strata 上的 Qwen3.8-Flash-Next IQ3_S，chat completions、无 grammar、`wide-context-v1`、`confidence: high` 专名注入）；Strata 由产品自动启停、不与 llama-server 同时驻留；删除发布时专名替换、`names-apply.json`、`names_apply` 身份键、`[names] enabled`、`[translate] model`／`port` 与 Hy-MT2 后端；翻译身份加 `names_sha256`，手改表中会被注入的条目即重译；失败路径保留 10→5→1 降级（§1.1、§1.2、§2、§3.1、§3.3、§4、§6、§7.1、§10、§11 已改，其余章节的 Hy-MT2／替换描述是历史设计依据）。

2026-11-08（音频输入、工作目录外置、双语字幕发布到源文件旁，[ADR-0020](../adr/0020-media-inputs-work-dir-and-side-by-side-publish.md)）：用户裁定音频文件也是输入（`[input] extensions` 替代 `video_extensions`，ffprobe 判定视频／音频，音频不做流复制）；`[paths] output_dir` 删除、新增 `work_dir`，按目标目录分工作根并共用 `cache/`；只发布 `<stem>.ja-zh.srt` 到源文件旁，已存在即跳过，删除 `[run] force` 与按 `published.json` 判定覆盖（§1、§2、§3.3、§4、§6、§7.1、§10 已改，其余章节的 `.work/`、三份 SRT、`force` 描述是历史设计依据）；锁改为 `<work root>/lock`（退出码 3）。

2026-11-09（产品建表切到 Strata，[ADR-0022](../adr/0022-product-names-on-strata.md)）：用户决定产品 `names` 阶段按基线 Q3 的规则在 Strata 上建表（配方 `q3-names-v1`，请求与 seed 序列与 `names-strata-v4` 逐字节一致，最多 5 次请求），names 与 translate 共用一个由编排持有的 Strata session（`kototoki/strata.py`，整批只启动一次），产品不再起 llama-server、不加载 27B；删除 `[names] model`／`port`、`[paths] llama_server`；本文 §1.2、§3、§4、§6、§7、§10 已按此改写，`names-sessions/` 改为共用的 `strata-sessions/`。

2026-11-11（ASR 整窗复读守卫，[ADR-0023](../adr/0023-asr-repeat-guard.md)）：用户 2026-11-10 裁定 v15 的 A 进产品，2026-11-11 实现。w0 路径（含 `cross` 的 w0 那一路）在 `asr` 阶段解码之后按 `repeat-strict` 折叠复读窗、仍命中则按 `failed_windows` 置空；纯逻辑在 `kototoki/guard.py`。产品 W0 配方加 `guard` 块并换 id `w0-faster-whisper-large-v3-guard-v2`，W0、CROSS 的 `recipe_hash` 随之改变，旧工作目录的 `asr.json` 及其下游重算，不做迁移；W0 基线身份（解码、VAD、对齐）不变。本文 §1.1、§4、§6 已按交付行为改写。验收见[实现计划](../plans/asr-repeat-guard.md) §7。

2026-11-11（内嵌日文字幕，[ADR-0024](../adr/0024-embedded-japanese-subtitles.md)）：用户裁定实现 §11 登记的"利用视频内嵌日文字幕"：默认开启（`[input] use_embedded_subtitles`）、ASS 进第一版、听障说明原样保留、外挂字幕不做。有可用日文文本字幕轨的文件由 CPU 阶段抽轨并清洗成 `ja.srt`（新产物 `ja-embedded.json`，配方 `embedded-ja-subtitle-v1`），不提取音频、不经 vad／asr／align／ja-cues，从 names 起走原链；`published.json.sources` 在这条路径下为 `probe`、`ja_embedded`、`names`、`translate`；抽取失败或零条目回到 STT 链并告警。本文 §2、§4、§6、§10.1、§11 已按交付行为改写。验证只用了 ffmpeg 合成片段（core＋full 测试），真实片源与真实模型验证未做。
