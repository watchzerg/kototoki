# 第九轮探索（v9）：通用模型 Qwen3.8-27B 在同一接缝下直接翻译

权威方案：[研究文档](../../docs/research/2026-10-21-general-model-translation-v9.md)（§3 问题、§4 已定设计、§5 判定纪律／预算／停止条件）。本文只记执行层面的约定，不重复方案。

## 范围

- 三个臂：对照 `dp10-cut`（Hy-MT2，`ee72ce66…`，本轮新生成）、`qwen-narrow`（同包、前 1＋后 1 邻文）、`qwen-wide`（同包、前 20＋后 5 邻文，只在渲染阶段放开）。
- 不做：自由文本回填、重排、专名表注入、提示搜索（smoke 后不改提示）、其他量化／模型／思考模式、多样本挑选、确认集、改 `kototoki/`。
- 预算：GPU dev run ≤10（smoke 折 1）；裁判标价 ≤$100；配额耗尽（退出码 75）转离线或停下。
- 用户已授权按 tracker 顺序无人值守执行本计划内 GPU 作业与裁判；启动 llama-server 前用 `Get-Process` 核实无其他 GPU 作业、遵守 `.local/gpu.lock`。

## 实现落点

- `experiments/translation_v3`：`Recipe.model`、`prompt="qwen-joint"`、`Recipe.wide_context`（渲染期邻文覆盖）；Qwen 请求与 server 接入在 `qwen.py`；内置 `qwen-narrow`、`qwen-wide`。
- `experiments/scene_batching_v6`：`--round v9`（根 `.local/general-model-translation-v9/`），`v9.py`（生成派发、全集裁判、分项配对比较、批次核对、代价）。
- 产物根目录 `.local/general-model-translation-v9/`；`.local/translation-evaluation/hy30-flow-v4/` 只读。

## 票据

01 离线实现 → 02 smoke（GPU）→ 03 L1 门（GPU＋裁判）→ 04 L2 三 seed 筛选（GPU＋裁判）→ 05 结题。
