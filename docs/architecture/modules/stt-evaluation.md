# STT 评分与显示重放

## 定位与阅读

负责与推理后端无关的转写结果契约及其下游消费：`kototoki_eval` 定义转写 JSON 的结构校验（W0／X0 写出前调用），并以完整分母计算文字 CER 与参考跨度时间；`experiments/display/replay.py` 把同一份 units 按冻结的最小显示规则重放为 SRT。不负责推理、窗口切分或参考语料的生成（见[语料与模型资产准备](corpus-and-assets.md)）。

上级总览见[架构总览](../INDEX.md)。字段与评分规则的权威说明是[评测器契约](../../testing/evaluator-contract.md)，评估方法见[质量与性能评估](../../testing/stt-evaluation.md)与[时间优先评估方法](../../testing/subtitle-timing-benchmark.md)，显示规则见[显示契约](../../testing/demo-display-contract.md)；本页不重复其条款。

## 当前行为规格

- 结构契约 `kototoki_eval.schema.validate_transcript`：`schema_version=1`、完整 `text`；源坐标有限非负且终点不早于起点；每个 unit 的 `char_start/char_end` 为整数并落在全文内，`granularity` ∈ {word, character, segment}，`time_source` ∈ {native, api, fallback, interpolated}，`status` ∈ {ok, failed, text_only}。
- 评分 `kototoki_eval.evaluate(reference, transcript)`：参考须 `schema_version=1`、合法 `reference_kind`、唯一 span ID、正时长 span（可带包含点估计的不确定区间）；`synthetic_digital_silence` 参考须为空 span 与零期望字符。全文经 `normalize` 后做完整 Levenshtein 对齐（`alignment.align`），时间只使用精确的原生 unit 边界，歧义不用时间消解。`micro_summary` 合并多个固定场景。
- CLI `python -m kototoki_eval <reference> <transcript> --output <path>`：输出须在项目 `.local/` 下且不存在、不得与输入相同；完整报告写入文件，控制台只打印 `reference_kind`、文字统计与时间统计。非有限值以字符串 `"infinity"` 表示。
- 显示重放 `python -m experiments.display.replay --input --output-prefix [--source-start] [--source-end]`：规则版本 `minimal-display-v1-2026-10-04`（间隙 0.4 s、单 cue 最长 7 s、42 字符、句末标点切分、毫秒四舍五入、不修补时间）；输出 `.srt` 与 `.display.json` 须在 `.local/` 下且不存在；无时间的非词汇字符只能贴附到相邻有效 unit，不能渲染的内容记入 `unrenderable`。

## 实现设计

- `kototoki_eval` 只用标准库，模块导入不加载任何推理依赖；`schema.from_segments` 把分段式后端输出适配为 units 并保留未映射文字，`map_time` 处理裁剪／重采样后的坐标映射。
- `scoring.evaluate` 同时校验参考与候选，结果包含字符映射和逐 span 信息，属于私有产物。
- `replay.py` 在 sidecar 中记录输入与写出器源码 SHA256；`replay_frozen_sets.py`、`replay_heldout.py` 是对冻结历史集合的批量重放脚本。

## 接口与依赖

- 被 [W0 pipeline](w0-pipeline.md)、[X0 pipeline](x0-pipeline.md) 导入 `validate_transcript`；被历史 `vad_comparison`、`components` 等实验导入 `normalize`、`align`、`json_safe`。改变 `schema.py` 会改变 W0 冻结源码身份（W0 把 `kototoki_eval/schema.py` 复制进运行目录并校验哈希）。
- 不依赖 `experiments` 任何代码（见[模块边界：依赖方向](../module-boundaries.md#依赖方向)）。
- 参考 JSON 由[语料与模型资产准备](corpus-and-assets.md)的语料脚本生成。

## 代码与验证入口

- 源码：`kototoki_eval/schema.py`（`validate_transcript`、`normalize`、`from_segments`、`map_time`）、`kototoki_eval/scoring.py`（`evaluate`、`micro_summary`、`display_diagnostics`）、`kototoki_eval/alignment.py`（`align`、`Alignment`）、`kototoki_eval/__main__.py`；`experiments/display/replay.py`（`replay`、`RULES`）。
- 测试：`tests/test_evaluator.py::EvaluatorTests`（27 项：cue 切分合并不变性、NFKC、完整分母、偏移、歧义不借用时间、`text_only`／failed／interpolated、CLI 输出保护、编辑计数与独立全矩阵一致、数字静音参考等）；`experiments/display/test_replay.py::DisplayContractTests`。均为离线 core 测试，由 `just test` 运行。
- 已知限制：评分对真实模型与声学真值的有效性仍需独立验证（评测器契约状态行）；SRT 显示时间不是声学真值。
- 已知差异：无。

## 变更与决策来源

[评测器审计](../../testing/2026-10-04-evaluator-audit.md)、[评测器契约](../../testing/evaluator-contract.md)、[显示契约](../../testing/demo-display-contract.md)。
