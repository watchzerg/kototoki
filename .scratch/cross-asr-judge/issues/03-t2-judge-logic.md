# T2 裁判纯逻辑 `kototoki/judge.py`

Status: done
Type: task
依赖：无

## 内容

从 `experiments/quality_v5` 搬运规范化、字符对齐、分歧区间、原文偏移映射、假设构造、判定与合并，封装为窗口级 `judge_window`；基础层，不导入 torch 与 experiments。

## 文件所有权

`kototoki/judge.py`、`tests/core/test_judge.py`

## 完成标准

离线测试覆盖相同窗口、单／多区间、映射失败回退、空结果守卫、margin 边界、批上限；与研究脚本在合成样例上结果一致。

## Comments

### 2026-10-19 实现完成（T2 agent）

- 新增 `kototoki/judge.py`（基础层，只依赖标准库）与 `tests/core/test_judge.py`（28 条）；`unittest discover -s tests/core` 445 条全绿，`compileall` 通过。
- 公开接口：`Normalized`／`normalize`（逐字复制 `kototoki_eval.schema`）、`Interval`、`align_ops`、`disagreement_intervals`、`compose`、`hypotheses`、`decide`、`merge`、`WindowJudgement`、`judge_window`、`summarize`。
- 与研究脚本对照：`align_ops`／`disagreement_intervals`／`compose`（全部 picks 组合）／raw 假设在 10 个合成样例上与 `asr_pair_oracle`、`asr_pair_cross_score` 逐项一致（研究模块只在测试内导入）。
- 与研究的差异：单窗原文不做 `join_raw`（hyp_w 即 w0 窗口原文）；无翻转时 text 取 w0 原文（normalized 回退形式下也保留标点）；原文无法规范化时守卫 `normalize_failed`、取 w0、不打分；守卫触发时 `switched` 记最终结果（False），`d` 仍保留。
- 留给 T5：`summarize` 另含 `normalized_form` 计数；scorer 返回条数不符时抛 ValueError。
