# 固定配方

[中日双语字幕批量生产流水线](../bilingual-subtitle-pipeline.md)的子页：各阶段写死、不做配置项的模型与配方（原 §1.1）。现行决定的完整定义见[现行决定](../../adr/CURRENT.md)。

## 固定配方（写死，不做配置项）

| 阶段 | 固定选择 | 依据 |
| --- | --- | --- |
| 音频分离 | 模型输入直接从输入容器按绝对流索引解码，带时间戳对齐（WAV 的 sample 0 即输入 0 秒，`offset_s` 恒为 0）、按声道布局下混单声道、重采样 16 kHz、PCM16 WAV；不流复制原始音轨（[不流复制原始音轨][no-copy]） | 两套 demo 与整片证据的输入身份是 16 kHz 单声道 PCM16；时间戳以输入容器为准，见[时间轴与下混][timeline]；[ADR-0007](../../adr/0007-bilingual-subtitle-pipeline-architecture.md) |
| VAD 与分窗 | Pyannote `segmentation-3.0`（revision `e66f3d3b…`），powerset 原生检测，onset／offset 0.5，`source-span-merge-v1`：≤30 s、整数样本坐标、保留块内间隙 | [ADR-0003](../../adr/0003-new-pyannote-baselines.md) |
| ASR `w0` | faster-whisper large-v3（CT2 FP16），固定日语，beam 5，batch 1，逐窗独立、无前文、无时间戳 token，faster-whisper 自带的特征计算（ADR-0035）；解码之后过整窗守卫（复读 `repeat-strict`、语速、已知幻听句，[失败收敛][fail]），产品配方 id `w0-faster-whisper-large-v3-fwmel-guard-v3` | [W0 契约](../../research/2026-10-stt-demo-w0-x0.md)、[ADR-0030](../../adr/0030-asr-window-plausibility-guard.md)、[ADR-0035](../../adr/0035-cross-default-native-whisper-features.md) |
| ASR `x0` | Qwen3-ASR-1.7B-hf，CUDA BF16、SDPA、greedy、`max_new_tokens` 4096，原生 processor | [X0 契约](../../research/2026-10-stt-demo-w0-x0.md) |
| ASR `cross`（默认，ADR-0035） | 同一 asr worker 内常驻 w0 与 x0：逐文件先 w0、再 x0 转写，由 Whisper 对两路的分歧区间做教师强制打分并合并（阈值 −1.0、无长度项），输出与 `w0`／`x0` 同构的 `asr.json`；阶段链不变 | [ADR-0003](../../adr/0003-new-pyannote-baselines.md)、[产品路径验收](../../research/acceptance/cross-asr-acceptance-2026-10-19.md) |
| 强制对齐 | MMS-1b-all `jpn` adapter，CUDA FP32，窗口归一化，字符级 CTC 对齐，`text_only` 记账 | [STT worker](../../architecture/modules/stt-workers.md) |
| 日文字幕切分 | 从字符 units 组 cue，规则数值来自配置文件（[切分规则](../bilingual-subtitle-pipeline.md#切分规则)） | [日文 cue](../../architecture/modules/japanese-cues.md)（起点是研究期的显示契约，见 [STT demo 轮次](../../research/2026-10-stt-demo-w0-x0.md)） |
| 翻译 | Q2 规则：Strata 上的 `qwen3.8-flash-next-iq3_s`（Strata 0.2 版本线，`strata launch --no-tui --model iq3_s`，DFlash2），chat completions、无 grammar、思考关闭、采样 0.7／0.8／20，提示 `qwen-joint-v1`；切包 `dp10-cut`（每批待译 ≤10 条），只读邻文 `wide-context-v1`；`confidence: high` 的专名注入；每个请求节点最多两次（seed、seed+1）；产品配方 `q3-translate-v1` | [ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[ADR-0021](../../adr/0021-q3-strata-names-baseline.md) |
| 专名建表（必开） | `ja-cues` 与 `translate` 之间的 GPU 阶段 `names`：在与翻译共用的 Strata 上把整份 `ja.srt` 一次送入，取回 `name-table-v2` 专名表并归一，回复格式不合格才依次换 seed、最多 5 次请求，空表直接接受（配方 `q3-names-v3`，与 Q3 的 `names-strata-v4` 只差输出上限 16384、提示预算 32256 与空表不重试）；表只经翻译注入（只注入出现在该批可见台词里的 `confidence: high` 写法），没有发布时替换 | [ADR-0028](../../adr/0028-names-accept-empty-table.md)、[ADR-0029](../../adr/0029-translate-per-cue-resolution.md)、[专名一致性](../../architecture/modules/name-consistency.md) |
| 双语合并 | 同一 cue 编号与时间，两行：中文在上、日文在下；中文就是翻译结果；未翻译的 cue 只有日文一行（ADR-0029） | 用户裁定 |

[no-copy]: ../../architecture/collaborations/stage-chain-and-scheduling.md#不流复制原始音轨
[timeline]: ../../architecture/collaborations/stage-chain-and-scheduling.md#时间轴与下混
[fail]: ../../architecture/collaborations/failure-convergence.md
