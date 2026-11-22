# 组件增量与日语 CTC 对齐器：降噪、VAD、CTC 候选比较

## 状态
concluded：HTDemucs 分离与 VAD 叠加被放弃；日语 CTC 对齐被证明是最有效的时间改进，MMS `jpn` 最终成为 W0／X0 共用对齐器。

## 时间
2026-10-04 至 2026-10-05（CTC 结论在 2026-10-05 汇入 W0／X0 基线采纳）。

## 问题
在已有的 W0／W1／X0 候选上，补上哪个缺失组件（人声分离、VAD、更好的日语 CTC 强制对齐器）能稳定改善字幕时间位置而不损失文字，哪个 CTC 候选最值得采用。

## 策略
- 先预登记方案再逐个加组件：存在收益才继续叠加；四窗筛查 → 十二窗复核，已曝光窗口只算开发证据。
- 组件：HTDemucs 人声分离（输入链）；Pyannote VAD（对 W0、X0）；W0 缓存文字＋原词时间包络桥接＋归一化标准 CTC；W0＋VAD＋CTC 叠加。
- 日语 CTC 补充：四个候选（Reazon 日语 wav2vec2、Jonatas XLSR-53、MMS-1b-all `jpn`、slplab 平假名 XLS-R）对固定的 W0／W1／X0 识别文字做缓存对齐，只更换对齐阶段。
- 对照：原 W0、W1、X0 与 Jonatas 对齐。

## 环境与版本
- RTX 5080，原生 Windows 11。分离：Demucs 4.1.0，官方单模型 HTDemucs，float32 CUDA；VAD：pyannote.audio 4.0.7。
- 对齐：WhisperX 3.8.6、Torch／TorchAudio 2.8.0+cu128、Transformers 4.57.6，TorchAudio 标准 `forced_align`（该接口在 2.8 弃用、2.9 移除，必须钉住 2.8）。
- CTC 候选（repo @ 短 revision，许可）：reazon-research/japanese-wav2vec2-large-rs35kh @ 2162c9ed（Apache-2.0）；jonatasgrosman/wav2vec2-large-xlsr-53-japanese @ cf031e02（Apache-2.0）；facebook/mms-1b-all＋`jpn` @ 3d33597e（CC-BY-NC-4.0）；slplab/wav2vec2-xls-r-300m-japanese-hiragana @ d3a14c42（许可未声明）。
- 上游 ASR：faster-whisper 1.2.1／CTranslate2 4.8.2／large-v3（edaa852e）；Qwen3-ASR-1.7B-hf（bcd2b5b7），BF16。

## 测试
- 数据：Heaven's Feel II／III 各 6 个 300 秒窗口（12 窗 60 分钟、590 条参考、6544 字符）；初筛为每片 window-01／04 共 4 窗（20 分钟、193 条参考、1955 字符）。窗口此前均已被研究使用，不是盲测。
- 指标：连续全文 CER（S／D／I）；时间取完整分母的半秒／两秒／五秒确定成功数、可测覆盖、条件 P95／P99；窗口成组配对 bootstrap（2000 次、固定 seed）只作描述。完整分母的联合 P95 全部不可测，所有路线仍未达严格时间目标。
- 无参考调窗：没有用字幕边界调整窗口、没有按参考选择对齐器；文字只由上游识别决定，CTC 只能改变时间，不能修复漏字。

## 结果
| 配置（12 窗，N=590） | CER | 半秒成功 | 两秒成功 | 可测 | 条件 P95／P99（s） |
| --- | ---: | ---: | ---: | ---: | ---: |
| W0 原生 | 16.41% | 241 | 363 | 377 | 1.653／4.742 |
| W0＋原词包络＋归一化 CTC | 16.41% | 306 | 368 | 372 | 0.776／2.194 |
| W0＋VAD | 16.02% | 263 | 370 | 378 | 1.353／2.418 |
| W0＋VAD＋CTC | 16.02% | 302 | 359 | 362 | 0.724／1.885 |
| W1（Jonatas CTC） | 14.98% | 320 | 348 | 360 | 0.863／6.237 |
| W1＋MMS `jpn` | 同 W1 | 342 | 368 | 371 | 0.541／1.687 |
| X0＋Jonatas／＋MMS `jpn` | 16.90% | 304／343 | 342／371 | 354／373 | 1.113／12.062 → 0.537／0.952 |
| W0＋平假名 CTC | 16.41% | 331 | 382 | 385 | 0.817／1.738 |

- HTDemucs 四窗：半秒成功略增，但 W0／W1／X0 的 CER 全部回归（如 W0 22.97%→24.86%）；共同可测子集的 P95 反而变差。
- VAD：四窗筛查时 W0＋VAD 支配 W0，十二窗复核推翻：半秒成功 241→263，但删除 274→322、完整边界 519→499；X0＋VAD 半秒成功不增。再叠 CTC 无额外整体收益（306→302）。
- CTC：W0 加 CTC 相对原 W0 半秒成功率 +11.0 个百分点（区间 +6.5～+15.7），可测略降；MMS `jpn` 对 W1／X0 半秒成功各增 22／39 条；Reazon 无填充版明显减少大偏移但 III 半秒成功下降，不替换主线。一次修复前的失败（极短窗口 CTC 帧数不足，窗口搜索范围小于父词时间）经"根据 ASR 自身时间扩大搜索窗口"修复。

## 结论与去向
- 放弃：HTDemucs 输入链、VAD 叠加 CTC 分支。保留：归一化标准日语 CTC 对齐。
- 采纳：MMS `jpn` 作为 W0／X0 共用对齐器：[ADR-0003](../adr/0003-new-pyannote-baselines.md)；定义见 [W0／X0 demo 轮次](2026-10-stt-demo-w0-x0.md)。VAD 的后续系统比较见 [VAD 比较](2026-10-vad-comparison.md)。
- 产品中的对齐阶段：[ADR-0007](../adr/0007-bilingual-subtitle-pipeline-architecture.md)。

## 教训
- 筛查阶段的"无回归"结论要在更多窗口上复核：四窗的八轴支配在十二窗被推翻。
- 条件 P95 只描述各自可测子集，必须配合共同可测子集比较；覆盖降低时尾部会自然变小。
- CTC 的 wildcard 多为标点，OOV 不等于对齐失败；极短窗口（<~100 ms）帧数不足会让 `forced_align` 拒绝，需要保留全文并记 `text_only`。
- 外部 CTC 候选必须核对 blank、tokenizer 与语言 adapter（MMS 默认语言是 `eng`），不能只看名字。
- 同一变量组合出现多处变化时，不把端到端变化归于某个内部阶段（分离同时影响识别、VAD 与对齐）。

## 原始材料
前缀 `archive/2026-11-18-pre-research-restructure:`：
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-04-component-augmentation-{results,sources}.md`、`2026-10-04-w0-ctc-exploration.md`、`2026-10-04-w0-vad-ctc-follow-up.md`
- `archive/2026-11-18-pre-research-restructure:docs/research/2026-10-04-japanese-ctc-{results,source-verification,alignment-reference}.md`（alignment-reference 是外部会话导入的候选评估计划，未经核验）
- `archive/2026-11-18-pre-research-restructure:docs/plans/component-augmentation.md`、`japanese-ctc-supplement.md`、`w0-vad-ctc-follow-up.md`；代码 `archive/2026-11-18-pre-research-restructure:experiments/components/`、`archive/2026-11-18-pre-research-restructure:experiments/japanese_ctc/`
