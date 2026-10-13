# 外部 VAD 阶段

## 定位与阅读

负责在独立 Python 环境中运行一个本地 VAD 候选，把原生语音区间整理为最长 30 秒的源窗口，并写出带输入身份、窗口和成本的 VAD manifest。当前 W0／X0 基线使用的候选是 `pyannote-current`（新 Pyannote，`pyannote.audio 4.0.7`＋`segmentation-3.0`）。不负责 ASR、对齐或评分；W0／X0 只读取它写出的 manifest。

上级总览见[架构总览](../INDEX.md)；组件选型见[当前 STT 基准线](../stt-candidate-pipelines.md)与 [ADR-0003](../../adr/0003-new-pyannote-baselines.md)；manifest 消费规则见 [W0 契约](../../specs/w0-reusable-demo.md#独立-vad-manifest)与 [X0 契约](../../specs/x0-reusable-demo.md#输入分段与特征)。完整运行命令见[标准基线测试指南](../../guides/baseline-testing.md#运行一次新的基线)。

## 当前行为规格

- 入口：`python -m experiments.vad_comparison.vad_stage --audio --offset --out --vad-id --model --revision [--device]`。`--offset` 必填，须有限且非负；`--out` 必须位于 `.local/vad-comparison/` 下且尚不存在。`--device` 默认 `cpu`，当前基线命令显式传 `cuda:0`；只接受 `cpu`、`cuda`、`cuda:0`，请求 CUDA 而不可用或实际加载设备不同即失败，不回退。
- 候选：`create_vad` 支持 `silero`、`fsmn`、`firered`、`pyannote-current`；每个候选校验 `PACKAGE_PINS` 中的固定包版本，版本不符时要求改用其隔离环境。`CurrentPyannoteVad` 要求本地 `segmentation-3.0` powerset checkpoint，onset／offset 0.5、`min_duration_on/off` 0。
- 窗口规则 `CHUNK_POLICY`（`source-span-merge-v1`）：区间起点向下、终点向上取整为样本并裁到源范围、排序取并集；超过 480000 样本的区间每 480000 样本硬切；再按源跨度贪心合并完整区间，合并后跨度不超过 30 秒。不加 padding，窗口内部静音保留，不拼接波形。每个窗口给出秒坐标、成对整数 `start_sample/end_sample` 与组成 `segments`。
- 输出：成功时写 `manifest.json`（`schema_version=1`、`status=ok`、`vad_id`、`recipe={vad_id}-source-span-merge-v1`、`input` 身份、`offset_s`、`chunks`、`metadata`、`source_sha256`、`stages` 含 `input_read_s`／`vad_load_s`／`vad_inference_s`／`worker_wall_s`）及 `source/` 源码副本；失败时写 `failure.json` 并重新抛出。推理期间源码变化即失败。
- 空检测是合法结果：`chunks` 为空列表。

## 实现设计

- `vad_stage.main` 设置离线环境变量（`HF_HUB_OFFLINE` 等）并把 HF／Torch 缓存指向运行目录；CUDA 设备时在 `gpu_lock` 内加载、推理并 `close()` 模型，CPU 设备不取锁。
- `_CandidateVad` 统一生命周期、设备核验、包版本与模型文件哈希记录；子类只实现 `_load` 与 `_intervals`。`segment` 校验音频后调用 `chunk_intervals`，把记账信息和输入 PCM 哈希写入 `metadata`。
- `CurrentPyannoteVad` 的 docstring 写明其为"gated MIT segmentation-3.0 local model with current powerset conversion"；代码拒绝非 powerset 模型，"do not substitute old PyanNet"。

## 接口与依赖

- 依赖 [W0 pipeline](w0-pipeline.md) 的 `experiments/w0_demo/run.py`（`read_audio`、`gpu_lock`、`sha256`、`write_json`）及 `experiments/w0_demo/vad.py::validate_audio`。
- 下游只通过文件契约消费：W0 `--vad-manifest`、X0 `--segmentation vad --vad-manifest`，由 `experiments/w0_demo/run.py::read_vad_manifest` 校验。同一输入与 offset 的 W0／X0 可共用一份 manifest。
- manifest 中的 `stages` 是外部进程成本；下游把它保存在 `precomputed_vad`／`vad_provenance.precomputed_stages`，不计入自身耗时。完整端到端成本由父比较流程累加。

## 代码与验证入口

- 源码：`experiments/vad_comparison/vad_stage.py::main`；`experiments/w0_demo/vad_candidates.py` 的 `chunk_intervals`、`CHUNK_POLICY`、`_CandidateVad`、`CurrentPyannoteVad`、`create_vad`。
- 测试：`experiments/w0_demo/test_vad_candidates.py`（`ChunkTests` 覆盖取整、并集、硬切、贪心合并；`AdapterTests` 用假后端覆盖设备、包版本、生命周期）；`experiments/vad_comparison/test_*.py` 覆盖十组合比较 runner（历史）。均为离线测试，由 `just test` 运行，根环境缺 NumPy 等依赖时相关测试跳过。
- 已知限制：`vad_stage.py` 位于历史比较包 `experiments/vad_comparison/` 内，却是当前基线的必经入口；该目录其余文件（`run.py`、`evaluate.py`、`verify.py`、`diagnose.py`）属于已完成的十组合比较。`vad_stage.py` 本身没有专门的单元测试，真实 GPU 行为见[整片报告](../../research/2026-10-05-fullfilm-segmentation-comparison.md)与 [GPU 补测](../../research/2026-10-05-pyannote-gpu-comparison.md)。
- 已知差异：无（代码与 W0／X0 README、基线测试指南描述一致）。

## 变更与决策来源

[ADR-0003](../../adr/0003-new-pyannote-baselines.md)；[VAD 比较计划](../../plans/vad-baseline-comparison.md)；[vad_comparison README](../../../experiments/vad_comparison/README.md)。
