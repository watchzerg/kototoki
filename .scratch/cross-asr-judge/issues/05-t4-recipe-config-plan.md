# T4 配方、配置、计划、产物名

Status: done
Type: task
依赖：无

## 内容

`recipes.CROSS`、`config.ENGINES` 增加 cross、`plan.ASR_RECIPES`／`model_files`、`artifacts` 新文件名常量；编排器为 cross 传两路模型路径。

## 文件所有权

`kototoki/recipes.py`、`config.py`、`plan.py`、`artifacts.py`、`job.py`（仅 asr jobs 的 models 映射）及对应 `tests/core/test_*.py`

## 完成标准

配方 hash 钉子测试；cross 需要两路模型文件；身份含两路 SHA；现有 w0／x0 的 hash 与身份不变。

## Comments

### 2026-10-19 T4 实现

- `recipes.CROSS`（id `cross-w0-x0-whisper-judge-v1`，嵌套 W0／X0，含 `judge` 全部字段）；按协调者更正，`start_sequence` 改为描述 `tokenizer.sot_sequence`（CT2 自接 `<|notimestamps|>`），新增 `score_error: "keep w0, warn, count"`。钉住的 hash：CROSS `da3b7241dcd5ec6561a2c7e02bc0e9420cb2ae7165d42c02c54f481659e8a00d`（更正前的 `92ca2d79…` 已作废）；W0 `127397b5…`、X0 `5d1bec25…` 不变，测试同时钉住。
- `config.ENGINES = ("w0", "x0", "cross")`；`Config.models` 与 `plan.worker_models` 本就带齐 `w0`、`w0_mel_assets`、`x0`，`job.py` 无需修改。
- `plan.ASR_RECIPES["cross"]`；`model_files("asr", engine="cross")` = w0 文件（含 mel 资产）∪ x0 文件。
- `artifacts.ASR_W0／ASR_X0／ASR_JUDGE` 常量：不进 `STAGE_ARTIFACTS`，不进 `LOCAL_TIME_ARTIFACTS`（该集合只约束经 `write_artifact` 写出的阶段产物须带 `offset_s`；若 T5 用 `write_artifact` 写审计产物则不做该检查）。代码里没有按固定清单清理阶段产物的逻辑，无需改。
- `schema.py` 无引擎枚举，未改。
- 仍按 w0/x0 分支、不归 T4 的位置：`kototoki/workers/asr.py`（`if engine == "x0"` / 否则 w0，需第三支路；模块文档字符串也需更新）。其余位置（job、align、translate）只透传 engine 字符串。
