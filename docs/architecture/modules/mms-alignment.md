# MMS 对齐

## 定位与阅读

负责 W0 与 X0 共用的 CTC 强制对齐：给定完整 ASR 文字与同源音频窗口，用 `facebook/mms-1b-all` 日语 `jpn` adapter 在 CUDA FP32 上求帧概率，经 TorchAudio 2.8 `forced_align` 得到字符级时间，并把结果映射为覆盖全文的 `units`。不负责窗口生成、文字识别、字幕显示切分；时间语义是 CTC nonblank token span，不等于声学真实时长。

上级总览见[架构总览](../INDEX.md)；契约条款见 [W0 契约](../../specs/w0-reusable-demo.md#可替换边界)与 [X0 契约](../../specs/x0-reusable-demo.md#mms-和输出)；术语背景见[当前 STT 基准线](../stt-candidate-pipelines.md#历史配置中的-ctc强制对齐vad-和降噪)。

## 当前行为规格

- 构造 `MmsAligner(model_path)`：CUDA 不可用即失败；要求 `torchaudio` 2.8.0、本地 `adapter.jpn.safetensors`；加载后逐元素核对 `lm_head` 与 adapter 一致，要求词表 2268、blank ID 0、特征提取器归一化且右侧零填充；参数须全部为 CUDA FP32。不下载（`local_files_only=True`）。
- `align(audio, segments, offset)`：音频须为一维有限 float32 NumPy 数组，offset 有限非负。每个 segment 带 `text`；有成对整数 `start_sample/end_sample` 时由 `sample_window` 严格校验（整数、范围、与秒坐标在 1e-9 内一致）后按整数裁剪，否则按秒坐标 `clamp_window`。
- 单窗口推理或解码抛 `RuntimeError`／`ValueError` 时，该窗口记录 `failure`、tokens 为空并继续，不转 CPU 重试；该窗口字符成为 `text_only`。
- 字符映射（`character_targets`）保留原文位置：只跳过首尾空白及词表外空格／`|`，其余 OOV 字符用通配符参与对齐；缺少词表或时间证据的字符保留为 `text_only`。输出全文与输入全文一致，时间加上源 offset。
- 数值作用域 `mms_numeric_policy`：前向与 log_softmax 期间 matmul TF32 关、cuDNN TF32 开，退出时恢复调用者设置，保留调用者的 deterministic 要求。docstring 说明原因："Pyannote disables TF32 globally and does not restore it. MMS must not inherit that preceding-stage setting."
- `close()` 释放模型并清空 CUDA 缓存，供后续阶段使用。

## 实现设计

- `MmsAligner.align` 逐窗调用 `_align_segment`（`normalize_window` 做窗口均值／方差归一化 → 模型前向 → CUDA log_softmax → CPU 侧通配符与哈希 → CUDA `forced_align`），再由 `map_records` 汇总 units、records 与 `derived_segments`。
- 字符过滤与通配符构造按模块 docstring 保持 WhisperX 3.8.6 行为，上游许可见 `experiments/w0_demo/THIRD_PARTY_NOTICES.txt`；不实现 WhisperX 的 trellis、句切、插值或 cue。
- 整数样本窗口接口是为 X0 增加的：X0 用它保留任意尾段的全部样本；旧 PyanNet W0 不传整数字段时保持原秒坐标裁剪。

## 接口与依赖

- 调用方：[W0 pipeline](w0-pipeline.md)（`run_pipeline` 经工厂创建）、[X0 pipeline](x0-pipeline.md)（`align_stage` 子进程）。修改本模块须同时检查两条契约与两套测试。
- 运行环境：`.local/envs/whisper-latest`（Torch／TorchAudio 2.8、transformers）；模型路径默认 `.local/models/mms-1b-all`，由[语料与模型资产准备](corpus-and-assets.md)的 `provision/japanese_ctc.py` 获取。
- 输出 units 须满足 `kototoki_eval.schema.validate_transcript`（见 [STT 评分与显示重放](stt-evaluation.md)）。

## 代码与验证入口

- 源码：`experiments/w0_demo/alignment.py` 的 `MmsAligner`、`mms_numeric_policy`、`character_targets`、`sample_window`、`clamp_window`、`normalize_window`、`map_records`、`TIME_SEMANTICS`。
- 测试：`experiments/w0_demo/test_alignment.py`（`TargetTests`、`NumericPolicyTests`、`MappingTests`、`SampleWindowTests`、`NormalizationTests`、`PublicContractTests`），用假 Torch／假对齐器离线运行；X0 的 `test_demo.py`／`test_vad.py` 覆盖整数窗口传递。
- 已知限制：TorchAudio 2.8 的 `forced_align` 已弃用、2.9 移除（见[当前 STT 基准线](../stt-candidate-pipelines.md#历史配置的资源与工程代价)）；极短窗口 MMS 失败在整片证据中仍存在。代码位于 `w0_demo` 包内但被两条路线共享，包名不反映归属。
- 已知差异：无。

## 变更与决策来源

[日语 CTC 补充实测](../../research/2026-10-04-japanese-ctc-results.md)、[MMS 来源核验](../../research/2026-10-04-japanese-ctc-source-verification.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)。
