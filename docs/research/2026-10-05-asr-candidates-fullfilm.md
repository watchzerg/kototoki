# 第一批 ASR 候选：两部完整电影实测

状态：五条路线、十次整片运行与统一评分完成  
日期：2026-10-05  
设备：原生 Windows 11、RTX 5080 16GB  
关联：[冻结计划](../plans/asr-candidates-fullfilm.md)、[运行入口](../../experiments/asr_candidates/README.md)、[模型来源调研](2026-10-05-asr-model-landscape.md)、[当前基线](../architecture/stt-candidate-pipelines.md)。

## 结论

**这三个候选在本轮两部日语电影上均未超过当前 W0／X0。建议保留现有基线，优先使用 W0。** 两部影片的文字排名方向一致，结果不是由单片合并权重反转造成。

- **Cohere Transcribe 2B** 是本批文字最好的候选，合并 CER 22.84%，但仍比 W0 高 7.59 个百分点。重构流程耗时减少约 14.3%，代价是更多文字错误和更低的可测时间覆盖；可以保留作速度对照，当前不足以替换基线。
- **Nemotron 3.5 ASR 0.6B** 全部窗口及 MMS 均无失败，流程耗时比 W0 少约 16.7%；但 CER 26.79%，删除错误较多，时间可测覆盖也最低。流式能力不是本轮测试对象，不能把此次离线成绩当作流式验收。
- **Granite Speech 4.1 2B 基础版** 暂不建议继续作为当前电影转写主线：CER 31.09%，402 个窗口中有 31 次重复生成触顶；触顶尝试占 ASR 时间约 60.1%，流程约需 57.2 分钟。

本次只完成评估，没有修改 W0／X0 的采纳决定、模型或 CLI 默认。

## 完整输入与公平比较范围

使用约定的 Heaven’s Feel II／III 全片派生音频：分别为 7028.0426875 秒和 7325.3333125 秒，合计 **239.222933 分钟**。完整日文参考含 2064 条、22134 个规范化字符。原 FLAC、SRT 只读，复用既有 mono／16kHz PCM；运行前后核验完整输入身份。

W0／X0 本轮重新推理。新 Pyannote 在两部完整音频上执行检测和规划，至 EOF，分别产生 195／207 个源窗口；五个模型共用完全相同的整数采样边界和 MMS 日语对齐。三个新模型各跑两片，不复制成两份相同 VAD／MMS 流程；各自使用原生音频处理和解码。

**没有抽样评测，也没有截掉片头、片尾。** 整片 VAD 会过滤未检测为语音的范围；其保留窗口合计 159.701 分钟，并非全部 239.223 分钟的每个样本都送入 ASR。窗口内间隙保留，所有完整参考始终留在评分分母。300 秒区间仅用于时间统计，不参与推理切分或采样。

无降噪、人声分离、翻译、热词、前文 conditioning。模型按阶段串行驻留，持有共享 GPU 锁；ASR／MMS 均在 GPU，权重下载与离线推理分开。

## 文字质量与成本

CER 越低越好。每部片计算全局精确编辑距离，两片先加 S／D／I 计数和完整参考分母后求比值，不平均两个百分比。失败窗口不从分母剔除；触顶的部分文字只保留作诊断，不冒充完整转写。

| 路线 | II CER | III CER | 两片 CER | 两片 S／D／I | 两片流程分钟 | ASR 失败／402 |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| W0：Whisper large-v3 | 16.807% | 13.767% | **15.248%** | 1641／1126／608 | 11.00 | 0 |
| X0：Qwen3-ASR 1.7B | 18.301% | 15.141% | **16.680%** | 2085／1146／461 | 19.15 | 0 |
| Cohere Transcribe 2B | 25.072% | 20.717% | **22.838%** | 1916／2345／794 | 9.43 | 1 |
| Nemotron 3.5 ASR 0.6B | 28.411% | 25.253% | **26.791%** | 2210／3535／185 | 9.16 | 0 |
| Granite Speech 4.1 2B 基础版 | 30.906% | 31.260% | **31.088%** | 1863／4679／339 | 57.19 | 31 |

“流程分钟”为各路线两片的**重构串行成本**：ASR／MMS 子进程墙钟，加本轮共享 VAD 每片各一次，包括加载、导出和失败尝试；不包括安装、下载、短窗资格验证和评分。共享 VAD 实际只执行一次，不能把五列成本相加当作本次研究实际墙钟。它衡量本机当前实现，不是模型在所有后端上的理论速度。

| 路线 | II 流程秒 | III 流程秒 | 合计流程秒 | 合计纯 ASR 推理秒 |
| --- | ---: | ---: | ---: | ---: |
| W0 | 324.678 | 335.605 | 660.283 | 358.126 |
| X0 | 578.102 | 570.765 | 1148.867 | 827.313 |
| Cohere | 275.983 | 289.999 | 565.982 | 253.913 |
| Nemotron | 270.672 | 279.172 | 549.845 | 247.211 |
| Granite | 1495.511 | 1935.777 | 3431.288 | 3130.294 |

## 失败、设备与解码审计

五条路线都尝试全部 402 个窗口；十个影片槽均有真实 ASR 产物，登记 `terminal=true`、`all_models_tested=true`。完整执行不等于每个窗口都成功。

| 路线 | II／III ASR 失败 | II／III MMS 失败 | 说明 |
| --- | --- | --- | --- |
| W0 | 0／0 | 1／1 | 两个极短窗口 CTC 帧数不足，文字保留 |
| X0 | 0／0 | 1／0 | 同一 II 极短窗口失败，文字保留 |
| Cohere | 0／1 | 0／0 | III 一个窗口生成 1000 tokens，未出现 EOS |
| Nemotron | 0／0 | 0／0 | 全部有效 encoder frame 耗尽，零整窗触顶 |
| Granite | 12／19 | 1／1 | 31 次均达到 1024 tokens，部分存在持续重复 token |

MMS 的极短窗口分别仅约 50.6875／84.4375 毫秒，其失败不等同于 ASR 失败。`text_only` 还包括正常 OOV 等未映射文字，不能把其全部字符算作失败窗口。

Granite 失败尝试合计 1882.069 秒，占其 ASR 推理 60.12%。原生 prompt、特征形状、源裁剪与生成前缀审计未发现接口不匹配；保留失败后继续，没有重试替换成功结果或调参重跑。Cohere 唯一触顶确认缺少 EOS，其他成功窗口均正常结束。

Nemotron 原生 `max_length` 警告对应有效 encoder 帧数乘每帧最大发射数的动态容量，不是任意文字上限；402 个窗口均耗尽有效帧，未到整窗容量。III 有一次同帧连续发射 10 个非 blank token 后的原生强制帧推进，完整保留为诊断。使用原生 `processor.decode(group_tokens=False)`，没有错误套用 CTC 重复折叠。原生 RNN 出现权重非连续的性能警告，本轮成本包含该实现表现，未额外优化或测量实时流式延迟。

成功与失败 partial trace 均参与设备审计：新候选的参数、buffer、输入和输出均为 CUDA，全部源窗口有设备观察。设备证据与成功覆盖率分开报告；有触顶或对齐失败时，组合通过标记仍为 false，不将其误写成 CPU 回退。

## 时间覆盖与偏移

完整时间分母均为 2064 条参考。SRT 是显示时间，不是人工声学真值。可测覆盖降低时，剩余可测条目的条件 P95 可能变小，不能据此称为整体时间质量更好。

| 路线 | 可测覆盖 | 严格 <0.5 秒下界／上界 | 条件 P95 秒 | 最大偏移秒 | >5 秒条目 |
| --- | ---: | --- | ---: | ---: | ---: |
| W0 | 63.03% | 55.23%／61.77% | 0.753 | 22.703 | 20 |
| X0 | 61.19% | 53.29%／59.74% | 0.696 | 31.296 | 20 |
| Cohere | 54.51% | 48.50%／55.62% | 0.653 | 33.737 | 14 |
| Nemotron | 39.73% | 36.09%／40.02% | 0.552 | 18.635 | 8 |
| Granite | 44.77% | 39.44%／44.43% | 0.658 | 22.344 | 17 |

三个候选均未改善完整分母下的半秒确定成功或可测覆盖。现有基线也尚未达到严格字幕时间目标。

## 冻结配置与复现证据

W0 为 canonical faster-whisper large-v3、CUDA FP16、beam5；X0 为 canonical Qwen3-ASR-1.7B-hf、CUDA BF16、greedy、max_new_tokens4096。两者保持现有适配器与环境，完整配置见[既有整片报告](2026-10-05-fullfilm-segmentation-comparison.md)。新 Pyannote 为 segmentation-3.0；共用 MMS-1b-all／jpn、CUDA FP32。

| 新候选官方模型 ID | 固定 revision | 本轮原生设置 |
| --- | --- | --- |
| `CohereLabs/cohere-transcribe-03-2026` | `b1eacc2686a3d08ceaae5f24a88b1d519620bc09` | BF16、SDPA、greedy、batch1、ja、max_new_tokens1000 |
| `ibm-granite/granite-speech-4.1-2b` | `de575db64086f84fdc79da4932d1076e965bc546` | 基础版、BF16、SDPA、greedy、batch1、官方转写 prompt、max_new_tokens1024 |
| `nvidia/nemotron-3.5-asr-streaming-0.6b` | `ea30d66debe3740a08b573244286791d423d6b3e` | BF16、SDPA、原生 greedy RNNT、batch1、ja-JP、原生帧耗尽 |

新候选环境为 Python 3.12.15、Torch／Torchaudio 2.11.0+cu128、Transformers 5.18.0。Granite 需要 Torchaudio，故采用配对版本的独立环境，未改动 W0／X0。Cohere 初始门控由用户处理，本机凭据通过后从官方固定 revision 下载；三款权重全部校验 SHA256，之后离线推理。

私有证据保存在 Git 忽略的 `.local/`：

- `.local/fullfilm-comparison/asr-controls-v1/study.json`：新执行 W0／X0；未选择的旧 cut-merge 槽仍 pending，不纳入本轮。
- `.local/fullfilm-comparison/asr-candidates-v1/study.json`：最终五路线、十槽、导入来源、冻结源码和输入哈希。
- 同目录 `analysis-v1/`：`report.json`、`summary.md`、`diagnostics.json`、`bin-scores.json`、`identities.json`；统一评分使用 RapidFuzz 精确编辑距离。
- `.local/asr-candidates-provision/*-ready.json`、`requirements-py312.txt`：模型文件与环境身份。
- 同目录 `control-text-audit-v1.json`、`cohere-fullfilm-audit-v1.json`、`granite-fullfilm-audit-v1.json`、`nemotron-fullfilm-audit-v1.json`：独立全文计数和成本复算。
- 同目录 `final-comparison-crosscheck-v1.json`：十个单片与五个合并结果、完整参考归属、成本、GPU 诊断及源码／模型／已安装实现哈希的最终交叉核验。
- `.local/fullfilm-comparison/asr-smoke-v1-{granite,cohere,nemotron}/`：短窗 GPU 接口资格验证，仅用于工程验证，没有混入以上整片质量或成本。

17 项适配器／控制器测试和 18 项评分测试通过；另完成三模型真实 GPU 验证、完整十次运行及独立原生 RNNT／模型身份／文字计数核验。新 W0／X0 的全文和整数窗口与此前同配置整片结果一致。原音频、完整转写和 token 诊断未写入 Git。

以上结论仅覆盖这两部已接触过的电影参考，不是独立盲测，也不代表所有日语场景。未参考输出不自动归类为幻觉；模型许可和其他部署边界仍见官方来源调研。
