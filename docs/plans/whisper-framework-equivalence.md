# Whisper 流程等价性与架构依据

> 2026-10-05 后续开发入口：本计划保留当时的研究与隔离原型范围。独立 Pyannote／ASR／MMS 已在 [W0 demo](../../experiments/w0_demo/README.md) 建立；继续移植、替换 VAD 或优化流程时复用并更新该入口。新增两窗端到端证据见 [验证记录](../testing/2026-10-05-w0-demo-validation.md)，正式迁移仍需另行验收。

状态：已完成；只做研究及隔离原型，不迁移正式架构  
最后更新：2026-10-04  
范围：原生 Windows／RTX 5080，本地日语；固定 Pyannote VAD 与 MMS jpn，对比 faster-whisper 自研流程及 WhisperX。

## 决策问题

判断 WhisperX 除 VAD／对齐集成之外，是否具有本项目需要、有效且难以独立维护的识别或分段能力。
旧 W0／W1 使用不同的识别、分段及搜索窗，不能当成本任务的公平对照。
研究建议不代表采用后端；不改模型、环境、默认配置或历史实验产物。

## 执行顺序

1. 核实本机安装版本、资产、历史命令和源码；分别追踪标准 `transcribe`、原生 `BatchedInferencePipeline`、WhisperX 自定义生成路径。
2. 审计 VAD 原始概率到切分／合并窗口、音频特征、解码实际参数及 MMS 输入输出契约；参数声明与实际执行分开。
3. 在独立 `experiments/framework_equivalence/` 和忽略的 `.local/framework-equivalence/` 中做最小必要对照：先冻结两片各 window-01 的 Pyannote 输出，再比较同块 ASR。GPU 串行，不上传音频。
4. 区分未修改的标准 API 与保行为适配层。若适配层与 WhisperX 的音频、完整文字、分段和搜索窗口严格相同，复用现有 MMS 证据并明确未重复对齐；如有差异，查明来源后按需对齐，不以删字改善指标。
5. 汇总实际能力、维护成本、反证与迁移门槛；更新研究入口及受影响说明。

## 验证边界

- 固定 large-v3、CUDA FP16、日语 `transcribe`、beam5、batch1，使用已配置离线环境；不升级或下载。
- 冻结输入／模型／源码身份，保存 raw VAD scores、精确窗口和源坐标；原文件只读，新增产物不得覆盖。
- 比较特征、token、全文、分段、裁剪坐标和对齐搜索窗。原生 API 差异不得误记为适配层差异。
- 不预先要求重新跑旧排行榜。内容或时间不同而需要计分时，保留完整分母、漏字、重复、覆盖和严重偏移。
- 新 ASR 成本与缓存对齐成本分开；严格相同的对齐输入支持有条件的流程等价推论，不冒充新的 MMS GPU 实测。
- 小样本不能保证全片、批量大于1、其他模型或跨版本等价。后续正式替换需要更广的回归门槛。

相关背景：[当前候选](../architecture/stt-candidate-pipelines.md)、[日语 CTC 实测](../research/2026-10-04-japanese-ctc-results.md)、[验证边界](../testing/validation.md)。

## 完成记录

源码审计和独立实验证据已归入[架构建议](../research/2026-10-04-whisper-framework-architecture.md)。
同两窗17块的适配层与WhisperX在特征、token、文字和边界上全部相同；标准API只有7块文字相同，
原生batch两窗全文均不同。独立cut/merge的两份真实score及44项边界对照全部一致。
新结果也与所测两窗旧W1及MMS上游输入一致，因此没有重复MMS推理或扩大质量排行榜。
推荐长期以faster-whisper＋保行为适配层为基础，完整迁移、旧原生cue兼容和独立MMS仍有明确门槛。
未修改正式架构、环境和默认后端。详细成本、源码冻结身份及限制见[实验记录](../research/2026-10-04-whisper-framework-experiment.md)。
