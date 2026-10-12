# ADR-0001：未来采用 W0／X0 两条 STT 基准线

状态：部分被[ADR-0003](0003-new-pyannote-baselines.md)替代；以下保留原决定及当时实现状态  
日期：2026-10-04  
范围：本地 GPU 日语转写的后续开发与评估；不改变历史实验身份。

## 背景

此前保留历史W0、W1、X0三条候选，后续分别完成MMS对齐补充实测和Whisper框架等价研究。
用户在阅读研究后明确要求将未来基准线改为两条，并更新文档。

## 原决定（2026-10-04）

采纳用户指定的两条组合，完整组件定义以[当前基准线](../architecture/stt-candidate-pipelines.md)为权威：

- **W0**：faster-whisper，无降噪、无人声分离，使用Pyannote VAD和MMS CTC；必须移植WhisperX的切分合并、独立无时间戳解码和特征处理等已核验逻辑。
- **X0**：Qwen-ASR，无降噪、无人声分离、无VAD，固定30秒分片，使用MMS CTC。

用户随后明确补充了W0的移植要求：自有适配层须保留这些行为，不能只组合三个模型或直接调用标准API就视为完成W0。
这是对同一基准线的实现要求补充，不是已经完成移植的声明；具体范围由当前基准线文档维护。

两条均保留日语原文、本地GPU推理，不上传音频。MMS使用已核验的日语`jpn` adapter。
2026-10-05 用户补充：GPU 要求继续适用于 ASR 和 CTC；VAD 选型允许 CPU 或 GPU，
不以 GPU 支持作为资格条件。此补充只放宽 VAD 设备约束，不更换上述组件或分片策略。
WhisperX不再作为未来独立基准线；历史W1继续作为研究证据和回归参照。
此次不新增模型权重／精度选择，不将现有隔离原型直接认定为正式后端。

## 理由与备选

决策依据首先是用户明确选择。[Whisper框架研究](../research/2026-10-04-whisper-framework-architecture.md)
支持在faster-whisper上以明确适配层保留关键行为；[MMS补充实测](../research/2026-10-04-japanese-ctc-results.md)
支持其作为两条路线的对齐方向，同时保留时间长尾和覆盖限制。
继续保留三条未来基准线、沿用Jonatas对齐或为X0增加VAD均不属于本次采用的配置。
其他模型及流程可以另立实验，不自动改变基准线。

## 后果与验证边界

W0／X0名称继续使用，但与旧同名路线的组件已不同；历史manifest、route值、目录和分数不改写。
新运行须另建身份并固定完整配置，不得将旧W0的单模型资源／成绩归给新W0，或将旧X0的Jonatas成绩归给MMS。
W0需要落实保行为适配和独立Pyannote／MMS流程；X0需要保留30秒音频窗口与对齐文字的关联。
完整迁移、端到端性能和质量仍需验证。此次变更只更新文档，不执行推理、不升级环境、不切换默认后端。

## 原demo实现进展（新Pyannote采纳前）

本节保留当时的实现与验证范围；当前组件、整片证据和CLI迁移状态以[ADR-0003](0003-new-pyannote-baselines.md)为准。

两条基线的当前执行和比较统一从[标准基线测试指南](../guides/baseline-testing.md)开始。
已建立[X0 demo](../../experiments/x0_demo/README.md)，默认fixed30及独立cut-merge配方均完成[两窗GPU验证](../testing/2026-10-05-x0-demo-validation.md)。
流程采用范围见[ADR-0002](0002-x0-demo-flow.md)，不改写本决定的默认基线。

已建立 [W0 可复用 demo](../../experiments/w0_demo/README.md)，独立 Pyannote／ASR／MMS 的[两窗端到端回归](../testing/2026-10-05-w0-demo-validation.md)通过。
后续实现本决定、替换 W0 VAD 或优化其识别／对齐时，应复用并更新该 demo，按其契约新建 recipe 和运行身份。
这项进展补充上述决定，不改写当日执行范围；正式后端迁移、十二窗／整片和无 WhisperX 安装的新环境仍未验收。
