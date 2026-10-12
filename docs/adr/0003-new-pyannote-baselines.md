# ADR-0003：W0／X0 统一采用新 Pyannote VAD

状态：已接受；基线定义已更新，CLI省略参数时的旧默认尚未迁移  
日期：2026-10-05  
范围：用户在两部完整电影对照后明确确认的最新基线；替代ADR-0001／0002中旧VAD与默认分段选择。

## 决定

- **W0**：faster-whisper，无降噪、无人声分离，新Pyannote VAD，MMS日语CTC。WhisperX的切分合并、独立无时间戳解码和特征处理等已核验逻辑仍是必要组成，由自有适配层承接。
- **X0**：Qwen-ASR，无降噪、无人声分离，新Pyannote VAD，同一MMS日语CTC；吸收适用于Qwen的WhisperX流程思想，保留Qwen原生processor、特征和独立纯文字解码。

“新Pyannote”明确指本轮`pyannote.audio 4.0.7`与`pyannote/segmentation-3.0`，权重revision
`e66f3d3b9eb0873085418a7b813d3b369bf160bb`，不是旧PyanNet配方或完整diarization。
现有整片证据采用CUDA FP32；通用设备原则仍为ASR／CTC GPU-only、VAD可CPU或GPU，换设备须独立记录。
不新增权重、精度、翻译、降噪或人声分离能力。

两条路线均先检测语音，再按原音频源跨度组织最多30秒的识别窗口，保留整数采样坐标、块内间隙和完整识别文字，
以对应同源窗口进行MMS对齐。新模型采用原生powerset语音检测及已实现的源跨度切分合并；
不能把旧PyanNet的迟滞／min-cut配方直接宣称为新模型的逐项等价实现。
W0保留已验证的Whisper特征、提示和解码契约；X0不复制Whisper专属Mel、token或CT2参数。

旧W0 Pyannote、X0无VAD fixed30及cut-merge保留历史／对照身份，不能再把省略策略参数的旧命令称为最新基线。

## 依据与取舍

决策依据是用户明确采纳。[两片整片对照](../research/2026-10-05-fullfilm-segmentation-comparison.md)
提供当前证据：W0新Pyannote的文字与时间指标优于cut-merge；X0配对排除失败后文字几乎持平，
选择新Pyannote主要由本轮零ASR触顶及运行成本支持。X0时间质量未显示普遍优势，极短窗MMS失败仍存在。
本轮未比较fixed30整片表现；用户选择不等于已经证明新Pyannote优于所有历史候选或满足严格字幕时间目标。

## 实现与文档边界

本次按用户要求更新文档，不修改Python实现、CLI默认参数、依赖或历史产物。
当前W0／X0已有显式外部VAD manifest入口及新Pyannote适配器；整片实验已新跑八组ASR／MMS并独立审计。
新基线执行需按[测试指南](../guides/baseline-testing.md)显式选择新Pyannote输入，核对模型、设备、源窗口与运行身份。
原W0 CLI省略VAD参数仍走旧配方，原X0 CLI省略分段参数仍走fixed30；这些是待迁移的代码默认，不是当前选型定义。
正式后端迁移、默认参数切换和极短窗改良须另行实现并回归，不能用本文替代实现验收。

历史报告的数值、配方和当时建议不回写；仅增加后续采纳指引。权威组件定义见
[当前基线](../architecture/stt-candidate-pipelines.md)，操作入口继续复用两套canonical demo。
