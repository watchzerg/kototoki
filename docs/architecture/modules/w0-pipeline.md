# W0 pipeline

## 定位与阅读

负责 W0 基线在单个进程内的推理：回放 VAD 窗口 → faster-whisper 逐窗独立无时间戳解码 → 调用共享 MMS 对齐 → 写出私有 `result.json` 与全文。同时持有 X0 和外部 VAD 阶段复用的工具函数（音频读取、GPU 锁、VAD manifest 校验）。不负责生成新 Pyannote 窗口（见[外部 VAD 阶段](vad-stage.md)）、CTC 细节（见 [MMS 对齐](mms-alignment.md)）或评分。双语字幕流水线的产品实现复制了本页的 ASR 与 units 不变量，拆成独立的 VAD／ASR／对齐 worker，见 [STT worker](stt-workers.md)；本页仍描述研究期代码。

上级总览见[架构总览](../INDEX.md)。行为契约以 [W0 契约](../../specs/w0-reusable-demo.md) 为准，使用方法与修改流程见 [W0 demo README](../../../experiments/w0_demo/README.md)，组件定义见[当前 STT 基准线](../stt-candidate-pipelines.md)。本页只说明代码结构，不重复契约条款。

## 当前行为规格

- 入口：`.local/envs/whisper-latest` 解释器执行 `python -m experiments.w0_demo.run --audio --out [--offset] [--vad-manifest | --frozen-vad] ...`，没有 just recipe。输入须为 mono／16 kHz／PCM16 WAV；`--out` 须为 `.local/w0-demo/` 下的新目录。
- VAD 来源三选一：`--vad-manifest`（当前基线，身份 `w0-{vad_id}-mms-v1`，即 `w0-pyannote-current-mms-v1`）、`--frozen-vad`（回放先前 `result.json` 的窗口，校验 PCM／文件 SHA256 与 offset）、均不传时加载旧 PyanNet（`PyannoteVad`，身份 `w0-pyannote-mms-v1`，仅作历史复现）。两个参数互斥。
- 流程：`run_pipeline` 依次运行 VAD、关闭 VAD；窗口非空时用工厂创建 `WhisperAsr`，转写后关闭，再创建 `MmsAligner` 对齐后关闭。空窗口表跳过 ASR／MMS，输出空全文。
- 输出：`result.json`（全文、`units`、`chunks`、`original_segments`、`asr_traces`、`alignment_records`、`effective_parameters`、`stages`、输入／模型／源码身份）、`transcript.txt`；失败写 `failure.json` 并非零退出。顶层 `status` 恒为 `ok`，个别 MMS 窗口失败只体现在 `alignment_records[].failure` 与 `text_only` units 中。
- 不变量：ASR 全文必须与对齐全文一致；每个字符恰好被一个 unit 覆盖；有时间的 unit 必须落在源范围内；结果通过 `kototoki_eval.schema.validate_transcript`。
- 运行中 W0 源码、`kototoki_eval/schema.py` 或 manifest 发生变化即判失败。

## 实现设计

- `pipeline.py` 定义 `Vad`、`Asr`、`Aligner` 三个 Protocol 与 `run_pipeline`；ASR 与对齐器通过工厂延迟创建，保证同一时刻最多一个模型驻留 GPU。
- `vad.py`：`FrozenVad` 回放窗口（manifest 与 `--frozen-vad` 都经它），`PyannoteVad`／`merge_scores` 保留旧 PyanNet 迟滞＋min-cut 历史路径；`validate_audio`、`validate_chunks` 为共享校验。
- `asr.py::WhisperAsr`：按样本裁剪窗口，`features` 用冻结 Mel 资产与 Torch STFT 生成 128 通道 log-Mel，`generate` 直接调用 CTranslate2；固定日语、beam 5、batch 1、无前文 conditioning、无时间戳。模块 docstring 记录其等价范围为 faster-whisper 1.2.1／CT2 4.8.2，"Other assets or versions require independent verification"。
- `run.py::main` 负责离线环境（`setup_runtime` 设置 HF 离线变量与 Windows DLL 目录）、源码冻结到 `source/`、`gpu_lock`、manifest 快照（`vad-manifest.json`）及 `attach_vad_manifest` 写入外部成本。
- `prepare_assets.py` 一次性从已获取的 WhisperX 资产复制 PyanNet checkpoint 与 Mel 文件到 `.local/models/w0-assets/` 并校验 SHA256，拒绝覆盖（归入[语料与模型资产准备](corpus-and-assets.md)的职责）。

## 接口与依赖

- 对外提供（被 X0 与外部 VAD 阶段导入）：`run.py` 的 `read_audio`、`setup_runtime`、`gpu_lock`、`read_vad_manifest`、`sha256`、`write_json`；`alignment.py::MmsAligner`（见 [MMS 对齐](mms-alignment.md)）。修改这些符号须同时检查 X0 与外部 VAD 阶段。
- 依赖：`kototoki_eval.schema.validate_transcript`（见 [STT 评分与显示重放](stt-evaluation.md)）；manifest 来自[外部 VAD 阶段](vad-stage.md)。
- `gpu_lock` 的语义与另一种锁实现的关系见[模块边界：并发与生命周期](../module-boundaries.md#并发与生命周期)。

## 代码与验证入口

- 源码：`experiments/w0_demo/run.py`、`pipeline.py`、`asr.py`、`vad.py`、`__init__.py::RECIPE`；`compare.py` 为验证用的同窗对照脚本。
- 测试（离线，`just experiments-test` 中 `discover -s experiments/w0_demo -t .`）：`test_pipeline.py::PipelineTests`（坐标、完整文字、空语音、阶段生命周期）、`test_manifest.py::ManifestTests`（manifest 身份、offset、窗口与整数边界校验）、`test_asr_vad.py`（`BoundaryTests`、`NumericalTests`，数值参照导入历史 `experiments/framework_equivalence`）、`test_vad_candidates.py`、`test_alignment.py`。根环境缺 NumPy／Torch 时数组测试跳过，需在 `whisper-latest` 中补测。
- 真实推理验证：[W0 验证记录](../../testing/2026-10-05-w0-demo-validation.md)（旧 PyanNet 两窗）与[整片报告](../../research/2026-10-05-fullfilm-segmentation-comparison.md)（新 Pyannote）。
- 已知差异：CLI 不传 VAD 参数时仍加载旧 PyanNet 并写 `w0-pyannote-mms-v1`，而 [ADR-0003](../../adr/0003-new-pyannote-baselines.md) 采纳的当前基线须显式 `--vad-manifest`；ADR 与 README 已把它列为待迁移的代码默认，尚未决定修代码的时间。
- 已知限制：W0 顶层 `status` 不反映 MMS 窗口失败（X0 会标 `partial`），检查结果须逐条看 `alignment_records`，见[标准基线测试指南](../../guides/baseline-testing.md#检查与评分)。

## 变更与决策来源

[ADR-0001](../../adr/0001-two-stt-baselines.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)；[ASR 差异审计](../../research/2026-10-04-whisper-framework-asr-audit.md)；[W0 契约](../../specs/w0-reusable-demo.md)。
