# X0 pipeline

## 定位与阅读

负责 X0 基线：用根项目轻量环境的父进程，依次在已配置的隔离环境中启动 plan、asr、align 三个子进程，完成分段计划 → Qwen3-ASR 逐窗纯文字识别 → 共享 MMS 对齐，并汇总进程成本。不运行 VAD（只导入外部 manifest）、不复制 MMS 实现。双语字幕流水线的产品实现复制了本页的 Qwen ASR 边界，作为 ASR worker 的 x0 适配器，触顶改为窗口级失败，见 [STT worker](stt-workers.md)；本页仍描述研究期代码。

上级总览见[架构总览](../INDEX.md)。行为契约以 [X0 契约](../../specs/x0-reusable-demo.md) 为准，使用方法见 [X0 demo README](../../../experiments/x0_demo/README.md)，组件定义见[当前 STT 基准线](../stt-candidate-pipelines.md)。

## 当前行为规格

- 入口：`python -m experiments.x0_demo.run`（或 `just x0-demo`）`--audio --out [--offset] [--segmentation fixed30|cut-merge|vad] [--vad-manifest]`。`--segmentation vad` 与 `--vad-manifest` 必须同时给出；默认 `fixed30`。`--out` 须为 `.local/x0-demo/` 下的新目录；Qwen 与 MMS 解释器路径须存在。
- 配方（`experiments/x0_demo/__init__.py::RECIPES`）：`x0-demo-fixed30-v1`（每 480000 样本分块，保留尾段）、`x0-demo-cut-merge-v1`（无 VAD 低能量切点＋贪心合并）、`x0-demo-vad-source-windows-v1`（当前基线，配合 `vad_id=pyannote-current`）。fixed30／cut-merge 校验全样本守恒；vad 配方允许删除窗口外样本并记 `retained_samples`／`removed_samples`。
- 流程：父进程冻结源码（`source/`、`source-manifest.json`）与 manifest 原字节，写 `request.json`，持 `.local/gpu.lock` 依次执行三个子阶段，每阶段前后重验源码哈希。空 VAD 窗口表跳过 Qwen／MMS 模型加载并记 `skipped_no_speech`。
- 输出：`plan.json`、`asr.json`、`alignment.json`、最终 `result.json`、`transcript.txt`、`process-costs.json` 及各阶段 stdout／stderr 日志；临时目录 `tmp/` 在成功或失败后删除，失败保留已完成阶段与 `failure.json`。
- 状态与退出码：任一 MMS 窗口失败时 `status=partial` 并列出失败窗口，CLI 退出码 2；生成达到 4096 token 上限或子阶段失败为非零退出，不运行后续推理。
- 不变量与 W0 相同：完整全文、每字符恰好一个 unit、有时间 unit 在源范围内、通过 `validate_transcript`。

## 实现设计

- `run.py::orchestrate` 是父进程：校验参数、冻结证据、调用 `execute_stage` 启动子进程并记录 `wall_s`、`pid`、退出码；中断时终止子进程并以 `InterruptedStage` 保留其成本。`offline_environment` 把 HF／Torch 缓存与 TMP 指向运行目录。
- `stages.py` 是子进程入口（`plan`、`asr`、`align`）：`plan_stage` 读取音频身份并生成窗口；`asr_stage` 在 `qwen-hf-final` 环境运行 `QwenAsr`；`align_stage` 在 `whisper-latest` 环境运行 `MmsAligner`。`load_plan` 每阶段重新核对 plan、request、源码与输入身份。
- `chunks.py`：`fixed_chunks`、`cut_merge_chunks`、`merge_short_chunks`、`validate_chunks`，整数样本为权威坐标。`cut_merge_chunks` 的 docstring 说明它不同于 `x0_flow` 的 trailing-5s energy 策略与 WhisperX 的 VAD 逻辑。
- `vad.py::import_vad_plan` 调用 W0 的 `read_vad_manifest`，优先使用 manifest 的整数边界，否则按秒×16000 向下取整并裁到源范围。
- `asr.py::QwenAsr` 从历史 `x0_flow/asr.py` 提升而来：CUDA BF16、SDPA、`do_sample=False`、`max_new_tokens=4096`、batch 1、各窗独立、无前文、使用 Qwen 原生 processor，并记录已安装 transformers 中 Qwen3-ASR 实现文件的 SHA256。
- `pipeline.py::build_result` 汇总结果并做完整文字与 unit 覆盖校验；`storage.py` 提供私有输出路径、源码冻结与运行身份。

## 接口与依赖

- 依赖 [W0 pipeline](w0-pipeline.md) 的 `read_audio`、`setup_runtime`、`gpu_lock`、`read_vad_manifest`，以及 [MMS 对齐](mms-alignment.md) 的 `MmsAligner`（显式传整数样本窗口）。
- 依赖历史回归参照包 `experiments.qwen.run_qwen` 的 `ASR_ID`、`ASR_REVISION`、`ASR_SHA256`、`checkpoint_identity`、`check_gpu`；修改该包会改变 X0 的资产身份核验。
- 依赖 `kototoki_eval.schema.validate_transcript`；manifest 来自[外部 VAD 阶段](vad-stage.md)。
- 两套 Python 环境的 Transformers 版本不同，这是使用子进程的原因（见 [Windows 与 NVIDIA](../../development/windows-nvidia.md#portable-commands-and-processes)）。

## 代码与验证入口

- 源码：`experiments/x0_demo/run.py`、`stages.py`、`chunks.py`、`vad.py`、`asr.py`、`pipeline.py`、`storage.py`。
- 测试（离线，`just experiments-test` 中 `discover -s experiments/x0_demo -t .`）：`test_demo.py`（`ChunkTests` 样本守恒、cut-merge 合并与尾段；`ResultTests` 完整文字、`text_only`、偏移、cap；`RunnerTests` 假子阶段下的失败保留、拒绝覆盖与进程成本）、`test_vad.py::VadTests`（身份／offset 拒绝、窗口排序与上限、整数边界、manifest 篡改、空检测）。根环境缺 NumPy 时数组测试跳过，README 给出在 `whisper-latest` 中补测的命令。
- 真实推理验证：[X0 验证记录](../../testing/2026-10-05-x0-demo-validation.md)（fixed30／cut-merge）与[整片报告](../../research/2026-10-05-fullfilm-segmentation-comparison.md)（新 Pyannote）。
- 已知差异：CLI 默认 `--segmentation fixed30`，而 [ADR-0003](../../adr/0003-new-pyannote-baselines.md) 采纳的当前基线须显式 `--segmentation vad --vad-manifest`；ADR 与 README 已把它列为待迁移的代码默认。
- 未验证：完整 Windows 取消与 OOM 恢复（README 明示）；整片 worker 的"失败后继续"只属于 `fullfilm_comparison`，canonical X0 生成触顶仍非零退出。

## 变更与决策来源

[ADR-0002](../../adr/0002-x0-demo-flow.md)、[ADR-0003](../../adr/0003-new-pyannote-baselines.md)；[X0 契约](../../specs/x0-reusable-demo.md)。
