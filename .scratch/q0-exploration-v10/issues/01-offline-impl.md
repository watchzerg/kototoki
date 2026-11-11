# 01 离线实现：v10 驱动、非 LLM 指标与盲读表、Qwen 整片 session、新提示字段与 hash 守护

Status: resolved
Type: 离线
Stage: A
Blocked by: —

范围、终点与门见研究文档 §4／§5（docs/research/2026-10-21-q0-exploration-v10.md）。

## 执行记录

- 2026-10-22 先做 A 所需的最小驱动（`--round v10` 复用 v9 命令、根目录 `.local/q0-exploration-v10/`），A1 的 6 个 GPU run 随即后台启动（拆分：A1 不依赖其余离线部分）；其余在 GPU 运行期间完成。
- 生成运行中改了 `recipes.py`／`generate.py`／`qwen.py`：先跑测试并核对 `qwen-wide`、`dp10-cut` hash 不变，后续 run 导入新代码行为不变。

## Answer

完成（离线）。
- `translation_v3.Recipe.qwen_options`（默认 None 不进 spec；只能配 Qwen 模型）：`system`（`qwen-joint-v2`）、`asr`（`qwen-asr-aware-v1`）、`names`（`qwen-name-table-v1`，window／all 过滤）、`brief`（`qwen-work-brief-v1`）、`context`；文本 sha256 进 `versions.model.options`。`qwen.messages(window, recipe, work_id)` 无选项时与 v1 逐字相同。思考模式（F1）与示例（B2）留到各自票据再加键。
- `translate-srt`：带 `model` 的配方走 `qwen.session_factory`，新增 `--work-id`。
- `scene_batching_v6 --round v10`、`v10.py`（`copy_control`）、`a2.py`（chrF＋bge-m3 CPU 相似度、一致率、门；盲读表）。
- hash 守护：`qwen-wide` `719237b9…`、`dp10-cut` `ee72ce66…` 不变；`test_v10` 7 项＋既有 84 项共 91 项通过。
