# ASR 候选：开放模型调研、整片对比与长录音素材

## 状态
concluded：三个新候选在两部整片上均未超过 W0／X0，基线不变；另附国会长录音参考实测与 2026-11 的静音概率测量。

## 时间
2026-10-05（模型调研、素材选择、整片与长录音实测）；附：2026-11-18（`no_speech_prob` 测量）。

## 问题
除 Whisper 与 Qwen 外，是否有开放权重的日语 ASR 模型在本机（RTX 5080、原生 Windows）上，于相同 VAD／窗口／MMS 对齐下优于 W0／X0；长录音（数小时）场景下两条基线表现如何；Whisper 的 `no_speech_prob` 能否拦住整窗幻听。

## 策略
- 调研候选：Cohere Transcribe、IBM Granite Speech 4.1、NVIDIA Nemotron 3.5 ASR、Parakeet 日语、ReazonSpeech NeMo v2、Fun-ASR-Nano、SenseVoiceSmall、日语蒸馏 Whisper、Meta Omnilingual、VibeVoice-ASR，按"Windows＋GPU 路径、日语支持、许可"分批。
- 整片对比：第一批三个（Cohere、Granite、Nemotron）与 W0、X0 在同一新 Pyannote 窗口、同一 MMS 对齐、同一计分下比较，各自使用原生音频处理与解码。
- 素材：从公开日语长录音来源挑选评测补充，选 YODAS2 国会讨论一段，跑 W0／X0 各一次完整推理（用户明确字幕准确度未知，只作参考）。
- 静音概率：对 230 个批处理工作目录的全部窗口逐窗取 Whisper `no_speech_prob`，与 `avg_logprob`、字速、能量对照，检验整窗丢弃规则。

## 环境与版本
- RTX 5080、驱动 616.92。新候选环境 Python 3.12，Torch／Torchaudio 2.11.0+cu128、Transformers 5.18.0（Granite 需要配对 Torchaudio，故独立环境，未改 W0／X0 环境）。
- 候选与固定 revision：CohereLabs/cohere-transcribe-03-2026 @ b1eacc26（BF16、SDPA、greedy、≤1000 新 token）；ibm-granite/granite-speech-4.1-2b 基础版 @ de575db6（≤1024 新 token）；nvidia/nemotron-3.5-asr-streaming-0.6b @ ea30d66d（原生 greedy RNNT、`ja-JP`）。三者均 CUDA。
- 对照：W0 faster-whisper 1.2.1／CT2 4.8.2／large-v3；X0 Qwen3-ASR-1.7B-hf（bcd2b5b7）；新 Pyannote segmentation-3.0（e66f3d3b）；MMS `jpn` CUDA FP32。
- 数据集 YODAS2（`espnet/yodas2`）固定 revision c9674490；评分用 RapidFuzz 3.14.6 精确 Levenshtein。

## 测试
- 整片：Heaven's Feel II／III 两部全片共 239.2 分钟、2064 条参考、22134 字符；新 Pyannote 产生 402 个源窗口（保留 159.7 分钟），五个模型共用同一整数窗口。全局精确编辑距离，失败窗口不剔除分母；时间覆盖同前。
- 长录音素材：YODAS2 日语 `ja000`（上传者字幕）子集中的一段国会讨论，约 3 小时、1371 条字幕、35409 个规范化字符；字幕准确度未知，CER 表示"与字幕的字符差异"，时间只比较字幕显示边界；另设去除明确现场注记的敏感性参考。选样依据：YODAS2 日语两子集共 32899 条记录、总时长约 5200 小时，`ja000` 为上传者字幕、`ja100` 为自动字幕；只读元数据与部分字幕就可筛选，不需下载全量。
- 静音概率：230 个文件、60392 个非空窗口，来自两类材料：批处理产出的无参考字幕工作目录（幻听多）与 HF II／III（有参考，用来查误杀）。

## 结果
| 路线 | 两片 CER | 流程分钟 | ASR 失败／402 | 可测覆盖 |
| --- | ---: | ---: | ---: | ---: |
| W0 | 15.25% | 11.0 | 0 | 63.0% |
| X0 | 16.68% | 19.2 | 0 | 61.2% |
| Cohere Transcribe 2B | 22.84% | 9.4 | 1 | 54.5% |
| Nemotron 3.5 ASR 0.6B | 26.79% | 9.2 | 0 | 39.7% |
| Granite Speech 4.1 2B | 31.09% | 57.2 | 31 | 44.8% |

- Cohere 唯一失败为生成 1000 token 未出现 EOS；Granite 的 31 次失败均触及 1024 token，失败尝试占其 ASR 时间 60%；Nemotron 无整窗触顶但删除多（D=3535）。三者半秒确定成功与可测覆盖均未改善。
- 国会长录音（379 个窗口，MMS 失败 0）：W0 与字幕差异 12.53%（ASR 推理 498 s、含 VAD 路线成本 664 s），X0 14.95%（1321 s、1525 s）；`text_only` 字符 608 对 1261；W0 在固定 37 个 ≤300 秒区间上的可测覆盖 73.5%、半秒确定成功 38.2%、两秒 63.0%；X0 的同规则时间评分未完成（评分进程耗时超过 18 分钟而主动结束）。
- `no_speech_prob`／`avg_logprob` 规则拦不住结尾套话类幻听（Whisper 对它们很有把握，窗口越长静音概率越低），主要拦下的是「ああああ」类真实叫声，还会误杀歌词。

## 结论与去向
- 放弃：三个新候选作为替代 ASR；保留现有基线，优先 W0。其中 Cohere 可留作速度对照，Granite 不再继续，Nemotron 的流式能力未测。
- 基线与产品 STT 引擎的现行定义见 [ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md) 与 [ADR-0012](../../docs/adr/0012-cross-asr-judge.md)（可选 cross 引擎：x0 转写＋Whisper 交叉打分裁判，另见 CURRENT.md 的 STT 一节）。
- `no_speech_prob` 规则不进产品，改用整窗幻听句匹配：[ADR-0030](../../docs/adr/0030-asr-window-plausibility-guard.md)。
- 基线前序见 [W0／X0 demo 轮次](../2026-10-stt-demo-w0-x0/README.md) 与 [VAD 比较](../2026-10-vad-comparison/README.md)。

## 教训
- 长度累积的短句语料不能代替连续长录音：整片分段、漏识别、重复、长时间稳定性需要连续录音（来源类别：上传者字幕、LibriVox 有声书加青空文库原文、播客加作者稿、国会录像加会议录，可信度各异，字幕与原文都不是声学真值）。
- 流式能力需要独立评估，离线成绩不能当流式验收；日语能力要按 checkpoint 核对（如 Granite 的 plus／nar 变体不含日语）。
- 生成触顶、重复与 MMS 极短窗失败要保留在完整分母里；触顶的部分文字只作诊断，不冒充转写。
- 单个国会讨论只能作参考；CER 低的一方不能据此宣称真实准确率更高。

## 原始材料
前缀 `archive/2026-11-18-pre-research-restructure:`：
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-05-asr-model-landscape.md`、`2026-10-05-asr-candidates-fullfilm.md`、`2026-10-05-japanese-longform-asr-sources.md`、`2026-10-05-yodas2-japanese-selection.md`、`2026-10-05-parliament-baselines.md`
- `archive/2026-11-18-pre-research-restructure:docs/plans/asr-candidates-fullfilm.md`、`archive/2026-11-18-pre-research-restructure:docs/testing/yodas2-parliament-reference.md`
- 代码与说明：`archive/2026-11-18-pre-research-restructure:experiments/asr_candidates/`、`archive/2026-11-18-pre-research-restructure:experiments/fullfilm_comparison/`、`archive/2026-11-18-pre-research-restructure:experiments/asr_nospeech/README.md`
