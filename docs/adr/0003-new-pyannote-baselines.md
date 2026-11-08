# ADR-0003：W0／X0 两条 STT 基线（新 Pyannote VAD＋MMS）

状态：已接受。合并整理于 2026-11-08（并入 ADR-0001、ADR-0002 的有效条款；历次变更见[决定索引·演进链](INDEX.md#演进链)，原文见 Git 历史）。  
范围：本地 GPU 日语转写的两条基线身份与组件；操作入口与逐项组件定义见[当前基线](../architecture/stt-candidate-pipelines.md)。

## 决定

1. **W0**：faster-whisper，无降噪、无人声分离，新 Pyannote VAD，MMS 日语 CTC 对齐。WhisperX 已核验的切分合并、独立无时间戳解码和特征处理是必要组成，须由自有适配层承接；只组合三个模型或直接调用标准 API 不算 W0。
2. **X0**：Qwen-ASR，无降噪、无人声分离，同一新 Pyannote VAD，同一 MMS 日语 CTC。只吸收适用于 Qwen 的 WhisperX 流程思想：保留 Qwen 原生 processor、特征与独立纯文字解码，不复制 Whisper 专属 Mel、token 或 CT2 参数。
3. **新 Pyannote** 指 `pyannote.audio 4.0.7` 与 `pyannote/segmentation-3.0`，权重 revision `e66f3d3b9eb0873085418a7b813d3b369bf160bb`，用原生 powerset 语音检测及源跨度切分合并；不是旧 PyanNet 配方，也不是完整 diarization。
4. **分段**：两路均先检测语音，再按原音频源跨度组织最多 30 秒的识别窗口，保留整数采样坐标、块内间隙与完整识别文字，MMS 对应同源窗口对齐。MMS 使用已核验的日语 `jpn` adapter，复用 W0 实现并带可选整数样本窗契约，不另建第二套对齐器。
5. **设备**：ASR 与 CTC 对齐只跑 GPU；VAD 可用 CPU 或 GPU，不以 GPU 支持作为资格条件。现有整片证据采用 CUDA FP32，换设备须独立记录。
6. **保留语言与本地**：保留日语原文，本地 GPU 推理，不上传音频。
7. **历史身份**：旧 PyanNet W0、X0 无 VAD fixed30、X0 `cut-merge`（低能量切点＋按源跨度有界合并，方法适配，不声称与 WhisperX 神经 VAD 后处理等价）只作历史／对照身份；省略策略参数的旧命令不得称为最新基线。历史 manifest、route 值、目录和分数不改写，新运行另建身份并固定完整配置，不得跨身份归分。
8. **复用入口**：W0 持续迭代入口为 `experiments/w0_demo/`，X0 为 `experiments/x0_demo/`；分段、模型或解码变化须更新 recipe 与验证记录。基线测试从[标准基线测试指南](../guides/baseline-testing.md)开始，契约见 [W0](../specs/w0-reusable-demo.md)、[X0](../specs/x0-reusable-demo.md)。
9. **产品**：产品包 `kototoki/` 的 STT 阶段承接这两条基线，VAD 固定 `cuda:0`，可选引擎见 [ADR-0007](0007-bilingual-subtitle-pipeline-architecture.md)、[ADR-0012](0012-cross-asr-judge.md)。

## 依据

- 用户在两部完整电影对照后明确采纳。[两片整片对照](../research/2026-10-05-fullfilm-segmentation-comparison.md)：W0 新 Pyannote 的文字与时间指标优于 cut-merge；X0 配对排除失败后文字几乎持平，选择新 Pyannote 主要由零 ASR 触顶及运行成本支持。
- [Whisper 框架研究](../research/2026-10-04-whisper-framework-architecture.md)支持在 faster-whisper 上以明确适配层保留关键行为；[MMS 补充实测](../research/2026-10-04-japanese-ctc-results.md)支持其作为对齐方向。
- X0 不要求照搬 Whisper 的特征或 VAD 切分；[X0 流程研究](../research/2026-10-05-x0-whisperx-flow.md)与 [demo 契约](../specs/x0-reusable-demo.md)定义样本守恒、30 秒边界、完整文字、实际 GPU 与错误记账验收项。

## 约束与未关闭项

- **CLI 默认值未迁移（已核对代码）**：`experiments/w0_demo/run.py` 不给 `--vad-manifest`／`--frozen-vad` 时走旧 PyanNet 检查点（`--vad-checkpoint` 默认 `w0-assets/pytorch_model.bin`）；`experiments/x0_demo/run.py` 的 `--segmentation` 默认 `fixed30`。运行最新基线须显式提供新 Pyannote 的 VAD manifest（X0 同时 `--segmentation vad`）。
- 未证明新 Pyannote 优于所有历史候选，也未证明满足严格字幕时间目标；X0 时间质量无普遍优势，极短窗 MMS 失败仍存在。
- 本轮未比较 fixed30 整片表现；对质量或性能提升的宣称须有可复现证据。
