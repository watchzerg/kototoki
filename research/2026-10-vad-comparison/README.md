# VAD 比较：W0／X0 的 VAD 候选、新 Pyannote 与整片分段

## 状态
concluded：十组合比较未晋级任何新 VAD；随后用户在整片对照后采用新 Pyannote（ADR-0003）。

## 时间
2026-10-05。

## 问题
W0 的 Pyannote 检测与后处理、X0 的固定 30 秒切分有改进空间：换一个 VAD 是否稳定改善文字与时间；新 Pyannote（segmentation-3.0）在 GPU 上是否改变结果；与无 VAD 的 cut-merge 比整片表现如何。

## 策略
- 调研：先核对成熟与新兴 VAD（Silero、FSMN、FireRed、OmniVAD、TEN 等）的版本、许可与 Windows 路径，再选 Silero、FSMN、FireRed、Pyannote-current 做实测。
- 十组合：原 W0（旧 PyanNet）／原 X0（无 VAD fixed30）与四个新 VAD 配方（保留各自原生检测默认值，再按共同的"≤30 秒源跨度合并、保留窗口内静音"组窗）。
- GPU 补测：新 Pyannote 从 CPU 改 CUDA 重跑十二窗，对比结果一致性与耗时。
- 整片：两部完整电影，W0／X0 各比较新 Pyannote 与 cut-merge（低能量切点、保留全部样本），八条链路。

## 环境与版本
- RTX 5080、Windows 11、驱动 616.92。VAD 隔离环境 Python 3.12，Torch／TorchAudio 2.11.0（CPU 补测为 +cpu，GPU 为 +cu128）。
- pyannote.audio 4.0.7＋pyannote/segmentation-3.0（e66f3d3b）；silero-vad 6.2.3；FunASR 1.4.16＋funasr/fsmn-vad（df20e6b3）；fireredvad 0.0.2（FireRedTeam/FireRedVAD @ 7990aacc，仍标 Beta）。
- ASR／对齐沿用 W0（faster-whisper 1.2.1／CT2 4.8.2／large-v3）、X0（Qwen3-ASR-1.7B-hf @ bcd2b5b7，BF16，≤4096 新 token）、MMS `jpn` CUDA FP32；ASR／对齐环境未升级。
- 新 Pyannote 参数：onset／offset 0.5、`min_duration_on/off` 0，检测窗 10 秒、步长 1 秒、batch 32；窗口策略 `source-span-merge-v1`。

## 测试
- 十组合：Heaven's Feel II／III 各 6 个 300 秒窗口，共 60 分钟、590 条参考、6544 字符，窗口此前已使用，不是盲测。同一个新 VAD 每窗真实检测一次，W0／X0 共用其整数样本窗口。
- 整片：两部电影共 239.2 分钟、2064 条参考、22134 字符；无采样、无降噪、无人声分离。文字指标为整片全局 CER（含失败；另给配对剔除失败区间的版本），时间指标同 W0／X0 评测。
- 成本为"VAD 进程墙钟＋demo 进程墙钟"的重构串行成本，含加载。

## 结果
十二窗十组合（部分行）：

| 组合 | CER | 半秒成功／590 | 重构成本（分钟） |
| --- | ---: | ---: | ---: |
| W0 原方案（旧 PyanNet） | 14.98% | 342 | 13.19 |
| W0＋Pyannote-current | 14.91% | 353 | 17.13 |
| W0＋Silero | 19.73% | 321 | 13.33 |
| W0＋FSMN／FireRed | 15.39%／15.34% | 351／354 | 15.88／13.00 |
| X0 原方案（无 VAD） | 16.90% | 343 | 18.72 |
| X0＋Pyannote-current | 25.67%（含 1 窗触顶失败） | 307 | 25.43 |

- 120 个槽位全部尝试，119 个完成；X0＋Pyannote-current 在一个窗口的首个 chunk 触及 4096 token 上限，其余部分保留在完整分母中。Silero 增加漏字；FSMN／FireRed 提高部分覆盖但严重时间偏移更多；X0＋FSMN 16.05%、＋FireRed 16.32% 为小幅样本内改善。
- GPU 补测：新 Pyannote 在 GPU 上检测、识别、对齐结果不变；每次启动新进程时 GPU 更慢，同一 VAD 实例复用时单窗约快 13 倍。
- 整片（含失败）：W0 新 Pyannote 15.25% 对 cut-merge 20.70%，两片方向一致、覆盖与长尾也更好；X0 新 Pyannote 16.68% 对 17.34%（cut-merge 有 6 个分段触顶 4096 token），配对剔除失败后 17.06% 对 17.03%，无总体文字优势。Pyannote 向 ASR 提供 159.7 分钟音频，过滤约 79.5 分钟。四路线可测时间覆盖仅 61%–63%，全部未达严格时间目标；极短窗口（约 50–85 ms）的 MMS 帧数不足失败仍存在（文字保留为 `text_only`）。

## 结论与去向
- 十二窗阶段当时不晋级新 VAD；整片阶段 W0 倾向新 Pyannote，X0 因稳定性与耗时倾向新 Pyannote（无 fixed30 整片对照，不能据此声称优于 fixed30）。
- 用户采纳新 Pyannote＋MMS 作为 W0／X0 基线：[ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md)；基线整体定义见 [W0／X0 demo 轮次](../2026-10-stt-demo-w0-x0/README.md)。VAD 阶段在产品中的实现见 [ADR-0007](../../docs/adr/0007-bilingual-subtitle-pipeline-architecture.md)。
- 后续 ASR 候选比较在固定了该 VAD／窗口／对齐后进行：[ASR 候选](../2026-10-asr-candidates/README.md)。

## 教训
- VAD 过滤与 ASR／对齐失败是两件事：被过滤的音频仍在评分分母里，不能当作"已处理"。
- 换 VAD 同时改变保留范围、块数与上下文，不是单变量消融；对白检测是主目标，保留歌声不扣分。
- 新进程冷启动成本掩盖 GPU 收益：评估吞吐必须区分是否复用模型。
- Pyannote 切分合并是显式流程（迟滞阈值、长段切分、源跨度合并），"装上 Pyannote"不等于复现 WhisperX 的行为。

## 原始材料
前缀 `archive/2026-11-18-pre-research-restructure:`：
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-05-vad-baseline-comparison.md`、`2026-10-05-pyannote-gpu-comparison.md`、`2026-10-05-fullfilm-segmentation-comparison.md`
- 来源调研：`archive/2026-11-18-pre-research-restructure:docs/research/2026-10-05-vad-landscape.md`、`2026-10-05-established-vad-sources.md`、`2026-10-05-emerging-vad-sources.md`、`2026-10-05-vad-stable-versions.md`
- `archive/2026-11-18-pre-research-restructure:docs/plans/vad-baseline-comparison.md`、`pyannote-gpu-comparison.md`、`fullfilm-segmentation-comparison.md`；`archive/2026-11-18-pre-research-restructure:docs/context/2026-10-05-vad-comparison-execution.md`；代码 `archive/2026-11-18-pre-research-restructure:experiments/vad_comparison/`、`archive/2026-11-18-pre-research-restructure:experiments/fullfilm_comparison/`
