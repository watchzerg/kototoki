# W0 冻结文字与 normalized standard CTC 的锁定后探索

状态：固定开发五章及验证三章已经完成新 FA 推理和独立 CPU 评分。属于原筛选锁定后
新增的单个配置，不能放回原盲测排行榜。没有调整评分、原筛选门槛、参考文字、ASR
文字或预测窗口；不根据这些结果宣称胜出或严格达标。

动机是既有 W1 normalized 验证结果相对 W0 多 104 个删除字符。E2 保留 W0
no-context 已保存文字与原始 segment，换用同一个日语 CTC checkpoint、官方逐段
归一化和 standard forced token spans，检验内容保留与时间精度能否同时获得。
这次同时采用已选定的归一化和解码提取流程，不是将两者分别隔离的因果消融。

配置为 `fw121-ct2482-ctx-off-officialnorm-torchaudio28-forced-cuda`：原 ASR 使用
faster-whisper 1.2.1、CTranslate2 4.8.2、large-v3 CUDA float16、ja/transcribe、
beam 5、word timestamps、VAD off、condition_on_previous_text=false、温度回退。
ASR checkpoint 为 `Systran/faster-whisper-large-v3`，revision
`edaa852ec7e145841d8ffdb056a99866b5f0a478`。开发/验证对齐比较组的 ASR 是缓存，
不能记为新推理；另一次新端到端入口证据在下文单独记录。

新 FA 使用 WhisperX 3.8.6、Torch/TorchAudio 2.8.0+cu128、Transformers 4.57.6，
`jonatasgrosman/wav2vec2-large-xlsr-53-japanese` revision
`cf031e020336460d15a417eba710bbc5bb43be9a`、CUDA float32、padding 0、nearest、
`ctc_normalize=true`、`ctc_forced_align=true`。standard CTC 输出是 nonblank token
跨度，不是已证实的完整声学发音时长；TorchAudio 此接口在 2.8 弃用、2.9 删除，
依赖边界仍需保留。没有新增神经模型、精度调整、降噪或参数搜索。

实验注册与比较证据位于 Git 忽略的 `.local/`：

- `.local/manifests/w0-standard-ctc-exploration-v1.json`：在附加开发推理前注册，
  明确不是原盲测或新的独立测试集。
- `.local/manifests/w0-standard-ctc-validation-v1.json`：固定验证 chapter-03/14/23、
  WAV/缓存 ASR SHA256、offset 和 duration 后执行新 FA。
- `.local/analysis/w0-standard-ctc/dev-r1/`：主 agent 原开发快照，保持不变。
- `.local/analysis/w0-standard-ctc/dev-r3/`：独立重算，四路线完整数字表与 dev-r1
  逐项一致，report SHA256 `d87e947fab45bafb8ac130766548a547e734cd0bb0fce7fd98cb02403b2fe168`。
- `.local/analysis/w0-standard-ctc/validation-r1/`：三个验证章节独立新评分，report
  SHA256 `7aedbb20c25e84da1bb301ea8f8828ae91ca60b95e35a0e2870386391e74cc29`。
  manifest、全部分章 score、execution-evidence 和当时 builder 源码副本一并保存。

CPU 入口调用未改动的 `evaluate`、`aggregate_manifest` 和 `upstream_evidence`，
核验全部参考 SHA256、WAV、完整 PCM 身份、offset/duration、模型 revision、原运行
harness/adapter/helper 源码身份与实际 CUDA 记录。E2 全文及 original_segments 必须
与注册的缓存 ASR 严格相等；任何变化立即拒绝。历史 W0 的适配器 SHA 与其当时
harness 绑定，明确记录它和当前最终适配器不同，不把历史实验改写为当前源码推理。
E2 的实际新 FA source/helper 与冻结的当前版本一致。

开发五章为 chapter-01/02/05/07/17，R=1902、完整时间分母 N=195：

| 路线 | S / D / I | CER | 可测 n/N | <500 ms 确定成功 / 不确定性上界 | 条件 E-P95 / P99 |
| --- | --- | --- | --- | --- | --- |
| W0 no-context | 262 / 71 / 224 | 29.28% | 123/195 | 89 / 114 | 1.348 / 6.268 s |
| W0 文字 + 原生 CTC | 同 W0 | 29.28% | 126/195 | 86 / 104 | 1.379 / 6.514 s |
| W1 normalized | 205 / 137 / 88 | 22.61% | 109/195 | 96 / 122 | 3.080 / 6.895 s |
| E2：W0 文字 + normalized standard CTC | 同 W0 | 29.28% | 120/195 | 99 / 122 | 1.172 / 6.657 s |

E2 相对 W0 的确定 <500 ms 成功数增加 10，但可测减少 3，P99 没有改善。相对
同文字的原生 CTC，确定成功数增加 13、可测减少 6。共同可测 120 项中原生 CTC/E2
P95 为 1.370/1.172 s，P99 为 6.514/6.657 s。开发数据支持继续固定配置查看验证，
并不支持淘汰较好的 ASR 文字来源或据条件 P95 单独排名。

验证三章为 chapter-03/14/23，R=1669、完整时间分母 N=151：

| 路线 | S / D / I | CER | 可测 n/N | <500 ms 确定成功 / 不确定性上界 | 条件 E-P95 / P99 |
| --- | --- | --- | --- | --- | --- |
| W0 no-context | 168 / 186 / 85 | 26.30% | 84/151 | 37 / 52 | 2.068 / 5.694 s |
| W0 文字 + 原生 CTC | 同 W0 | 26.30% | 89/151 | 45 / 58 | 4.282 / 47.683 s |
| W1 normalized | 169 / 290 / 50 | 30.50% | 78/151 | 56 / 63 | 2.224 / 10.140 s |
| E2：W0 文字 + normalized standard CTC | 同 W0 | 26.30% | 82/151 | 48 / 62 | 2.641 / 47.482 s |

E2 没有增加或修正文字：其 104 个删除优势来自 W0 缓存 ASR，不是 aligner 提升
识别能力。相对 W1 normalized，确定成功减少 8，可测增加 4，且可测集合仍包含约
47 秒的困难跨度；这不是相同样本逐项退化的证明。
相对同文字原生 CTC，仅增加 3 个确定成功，可测减少 7。与 W0 的共同可测 78 项中
E-P95 为 2.108/2.641 s，不能只用各自不同可测子集的分位数宣称全面改善。

[独立新端到端与尾部审核](../../.local/audit/w0ctc-fresh-and-tail-r1/report.md)进一步
定位 chapter-03/cue-0095：同一参考跨度的候选文字跨两个短 ASR 区域，分别为
602.796–605.456 s 和 652.116–655.856 s，中间相隔 46.660 s。13 个匹配参考字符中
12 个位于前区域，最后一个位于后区域；CTC 区间都留在各自预测区域内，没有证据
表明一个字符的 blank stay 被拉长约 47 秒，也不存在单个 50 秒 ASR 搜索窗口。
相同 W0 文字在原评分中为 `coarse_time`，因边界切入多字 word unit 而不进入条件
分位数；细粒度 CTC 让这个跨时间文字对应问题进入可测集合。因此 W0 P99 5.694 s
与 E2 P99 47.482 s 不能解释为同一总体或同一跨度从前者退化到后者。仍需保留完整
分母及该困难项，不能按参考窗口限制 CTC、删除此项或宣称 CTC 造成这条长尾。
后区域的 no_speech_prob 和低 token 概率只能支持输出/匹配机制诊断，未经人工
听辨不能认定它是音乐、数字静音或真实幻觉。

验证分章进一步显示收益不一致：

| 章节 | N | W0 可测 / <500 ms | 原生 CTC 可测 / <500 ms | W1 normalized 可测 / <500 ms | E2 可测 / <500 ms | E2 条件 P95 / P99 |
| --- | --- | --- | --- | --- | --- | --- |
| chapter-03 | 54 | 30 / 14 | 32 / 16 | 35 / 28 | 32 / 21 | 5.769 / 47.482 s |
| chapter-14 | 49 | 28 / 19 | 29 / 27 | 31 / 26 | 28 / 25 | 0.553 / 0.557 s |
| chapter-23 | 48 | 26 / 4 | 28 / 2 | 12 / 2 | 22 / 2 | 2.655 / 3.680 s |

chapter-23 的 W0 删除 113、W1 normalized 删除 234；E2 保留 W0 的 113，但不能
修复它。E2 验证完整失败分类为 82 可测、31 匹配歧义、26 内容不完整、6 内容缺失、
5 text-only、1 文字不匹配，合计 151。不可测项没有从分母删去；联合完整性/时间
P95 为无穷，不能把条件 P95 称作完整字幕服务的尾部保证。

这些是相对 scoring-v2 SRT 显示参考的差异，非人工声学真值。章间相关、样本很少，
没有 bootstrap 胜率、模型真值标签、说话人/数字错误归因或字幕主观可读性结论。
没有改原规则以使 E2 通过；后续同片更多章节只能作为已观察语料的探索性扩展。

每次 E2 的实际 FA、归一化输入和 standard decoder 输入/输出均有 CUDA 证据，
缓存 ASR 的原设备证据和输出 SHA 通过 `upstream_evidence` 单独关联。普通 CTC
及 E2 的阶段时间只计新 FA，不能与缓存 ASR 历史耗时相加冒充新端到端测速。
独立 CPU 审核现已核验 `e2-w0ctc-fresh-ch07-r1` 的新 ASR、新 FA：完整文字、所有
units/cues、ASR segments、搜索窗口、派生字符结果和全部 emission SHA 与缓存
E2 比较结果完全一致；音频文件/PCM/offset、6 个执行源码副本及两个阶段输出哈希
均吻合。ASR CUDA float16，59 次 CTC forward、归一化输入及新 decoder 输出为
CUDA:0，解码失败为 0；FA 仅复用同次产生的 ASR，两个阶段都是新推理。
这次外层墙钟 38.935 s、wrapper 范围 38.492 s 是探索性入口证据，不能代替后续
安静窗口的正式性能报告，也不与缓存 FA 时间混合。审核材料见上述私有报告及
同目录 `fresh-comparison.json`。

主 agent 已按有界停止规则终止 E2 扩展：验证相对 W0 仅多 11 个确定 <500 ms 成功，
同时少 2 个可测跨度；相对已有原生 CTC 仅多 3 个确定成功、少 7 个可测，残余的
跨区域文字对应失败仍未解决。收益不构成全面优势；不同可测集合的 P99 不是此次
停止的因果退化依据。不进行 16 个已观察章节的额外 E2 推理，也不安排 E2 整片
测试。已完成的新端到端入口验证和尾部复核只用于结束取证，不继续调参。
W0 no-context 内容角色与 W1 normalized 时间角色的整片运行现已由主 agent 完成，
正式整片质量、连续性及性能结论以随后汇总报告为准；本文不编造其指标，也不据
这八章探索宣布两条路线通过严格字幕目标。

可复现入口采用独占输出目录：

```powershell
uv run --locked --offline python .local/analysis/w0-standard-ctc/build_comparison.py `
  --phase validation --output .local/analysis/w0-standard-ctc/validation-replay-r2
uv run --locked --offline python .local/analysis/w0-standard-ctc/build_comparison.py `
  --phase dev --output .local/analysis/w0-standard-ctc/dev-replay-r4
```

首次独立 dev-r2 因历史适配器版本检查过严而中止，保留空目录，没有 GPU 执行或
模型失败；修正证据绑定方式后采用新 dev-r3 目录，未覆盖任何已有快照。项目实现
若保留此方向，应保持 ASR/FA 组件边界、缓存 provenance、原全文和失败记账，并
将 standard CTC 的固定版本维护成本和未解决的大偏移作为明确工程风险。
