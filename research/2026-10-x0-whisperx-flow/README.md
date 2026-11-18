# X0 吸收 WhisperX 流程：切点策略与 VAD 过滤的两窗隔离验证

## 状态
concluded：源码核查与两窗三臂验证完成；当时未得到满足预登记无回归条件的组合，随后用户以流程设计合理性采纳 X0 流程适配（现并入 ADR-0003，原 ADR-0002）。

## 时间
2026-10-05。

## 问题
WhisperX 的哪些流程逻辑适用于 Qwen-ASR 的 X0：低能量切点、Pyannote 过滤与合并、逐块独立识别、先文字后对齐；它们能否在不升级环境的前提下改善 X0 的文字与时间。

## 策略
- 源码核查：确认 X0 已有的行为（逐块独立纯文字识别、共用 MMS 对齐）与不适用的 Whisper 专属部分（语言／时间 token、EOT 过滤、CT2 beam、补齐到 30 秒的固定 Mel）。
- 三臂比较，同一 Qwen、同一 MMS，仅改切片策略：`fixed30`（连续 30 秒窗，基准）、`energy`（每块上限前 5 秒内按 100 ms 网格取前 100 ms RMS 最小的切点，保留全部音频）、`pyannote`（旧 PyanNet 过滤＋合并，块内保留静音）。

## 环境与版本
- RTX 5080（16303 MiB）、驱动 616.92、Windows 11。
- Qwen：Qwen3-ASR-1.7B-hf（bcd2b5b7），Python 3.13、Torch 2.14.1+cu130、Transformers 5.18.0，BF16、SDPA、greedy、batch 1、≤4096 新 token。
- 对齐与 VAD：facebook/mms-1b-all `jpn` adapter（3d33597e），Torch／TorchAudio 2.8.0+cu128、Transformers 4.57.6、pyannote.audio 4.0.7；MMS CUDA FP32，复用 W0 的 `MmsAligner`。
- 三阶段（规划／ASR／对齐）顺序运行，模型不同时驻留；Qwen PyTorch 峰值 allocated 约 4.05 GiB。

## 测试
- 数据：Heaven's Feel II／III 各一个 300 秒窗口（window-01），共 112 条参考、1197 个规范化字符；此前多次使用，不是独立保留集，不计算 bootstrap。
- 基准适配等价性：新 `fixed30` 两窗的分段、全文与全部字符单元与历史 X0＋MMS 结果严格相等，故后续差异归于切片策略。
- 指标：连续全文 CER（S／D／I）、完整分母半秒成功、可测覆盖、条件／共同可测 P95、严重偏移；字面重复候选只作诊断，不去重。完整进程成本为三个子进程墙钟之和。

## 结果
| 策略 | 两片 CER | S／D／I | 半秒成功／112 | 可测／112 | 条件 P95／最大（s） |
| --- | ---: | --- | ---: | ---: | --- |
| fixed30 | 15.37% | 111／50／23 | 64 | 73 | 0.572／3.847 |
| energy | 15.04% | 107／48／25 | 70 | 77 | 0.536／0.737 |
| pyannote | 14.45% | 98／55／20 | 63 | 74 | 0.739／1.964 |

- `energy`：半秒成功 64→70、漏字 50→48，但插字 23→25（III 多 3 个插入）；一个 3.8 s 的个案偏移降为 0.25 s 且仍可测。未验证速度收益（墙钟差主要来自首次加载）。
- `pyannote`：CER 最低主要来自替换减少，但漏字多 5、半秒成功少 1；额外约 15 s 检测与 22 s 加载，少送约 75–80 s 音频却没有明显减少 Qwen 处理时间（III 完整链 100.7→130.1 s）。
- 三臂完整分母的联合 P95 均为非有限值，均未达严格时间目标；未覆盖已知约 31 s 极值所在窗口。

## 结论与去向
- 值得吸收的是"在更合适位置切片、保持原音频坐标、共用对齐接口"的思路，而非整套 WhisperX；Whisper 的 token、特征补齐、CT2 参数不适用于 Qwen。
- 用户随后澄清：合理流程设计的采纳不以有限样本显著涨分为前提；据此建立 X0 demo 并采纳无 VAD 的流程适配，随后整片对照后改采新 Pyannote＋MMS：[ADR-0003](../../docs/adr/0003-new-pyannote-baselines.md)（原 ADR-0002 已并入）。旧 PyanNet 臂的分数不转移给新 Pyannote。
- 整体基线与评测方法见 [W0／X0 demo 轮次](../2026-10-stt-demo-w0-x0/README.md)；VAD 候选整片比较见 [VAD 比较](../2026-10-vad-comparison/README.md)。

## 教训
- 两窗、112 条参考只能给方向，不做统计结论；总体 CER 更低不等于更好，要同时看漏字、成功数与成本。
- 切片策略有速度收益之前要先拆开加载成本；单次顺序运行不足以作性能排名。
- 以某个多变量策略（过滤、块数、上下文同时变化）为对象时，不要据此推断"单纯删静音"的因果。

## 原始材料
前缀 `archive/2026-11-18-pre-research-restructure:`：
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-05-x0-whisperx-flow.md`、`2026-10-05-x0-whisperx-source-audit.md`
- `archive/2026-11-18-pre-research-restructure:docs/plans/x0-whisperx-flow.md`；代码 `archive/2026-11-18-pre-research-restructure:experiments/x0_flow/`、`archive/2026-11-18-pre-research-restructure:experiments/x0_flow_evaluate.py`
