# 04 替换纯函数：`kototoki/names/apply.py`

Status: done
Type: task
Blocked by: 01

## 背景

移植 `experiments/name_consistency/apply_table.py` 的默认路径（规则一＋孤立单字），以及它从 `experiments/quality_v5/consistency.py` 用到的片段。产品里译文是 `cue id → 文本`（`srt.render_srt` 的输入），不再操作 SRT 原文位置。设计见增量说明 §3.1、§3.3。

## 范围

- `kototoki/names/apply.py`：
  - 复制 `consistency.py` 的 `EDGE_STOP`、`zh_grams`、`edit_distance`、`variant_in`、`analyze_term`、`TermResult`（只这几项，注明来源；不复制 `extract_terms`、评估与 I/O）。
  - 复制 `apply_table.py` 的常量（`MIN_SUPPORT`…`BOUNDARY_EXTRA`、`BOUNDARY_CHARS`、`NAME_CHARS`、`COMPOUND_JOINER`、`COUNTERS`）、`find_spans`、`Match`、`entity_forms`、`assign_forms`、`shape_problem`、`isolated_in`、`support`、`usable_variants`、`StatLayer`、`extend_spans`、`Unit`、`locate`、`to_replace`、`in_compound`、`overlapping`、`bad_boundary`、`unit_boundary`、`is_near_name`、`apply_pass`。删除 `name_check`、`pool_by_target`、`bigram_isolation`、`iterate`／`residual`、`weak_name_check`、`min_confidence` 参数及其分支；删除 `parse_srt`／`read_srt`／`render_srt`／`run_*`／`main`／`measure`。
  - `apply(table, document, translations) -> ApplyResult(translations, changes, unresolved, summary)`：`ja_cues` 取 `document.cues` 的文本，`zh_cues` 取 `translations[cue.id]`；译文等于该 cue 日文原文的（翻译回退）不参与锚定与统计、不替换；`changes`／`unresolved` 里用 cue 编号与 id；`summary` 字段同研究期 `summary.json`（去掉 `passes`）。表 `schema != name-table-v2` 或 `entries` 缺失抛 `ValueError`；空表直接原样返回。
  - `apply_table` 顶层 docstring 改写为产品口径，列出已删除的开关并指向 ADR-0013。

## 完成标准

- `tests/core/test_names_apply.py`：移植 `experiments/name_consistency/test_apply_table.py` 中默认路径的用例（锚定、两层落点、规则一边界、孤立单字、`partial_canonical`／`already_canonical`／`overlap`／`compound`／`boundary`、扩展与修饰词、不幂等说明不需要）；删除针对已删开关的用例。新增：回退 cue 跳过；空表原样；schema 错误抛错。移植的用例以研究期测试的期望值为准，不改期望。**整片等价校验在 08**（对产品表用研究脚本重跑、输出逐字节相同）：小样本触发不了统计层，不在本票伪造等价钉子。
- `just test` 全绿；不导入 `experiments.*`。

## 文件所有权

`kototoki/names/apply.py`、`tests/core/test_names_apply.py`。

## Comments

