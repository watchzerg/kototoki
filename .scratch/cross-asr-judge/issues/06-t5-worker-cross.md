# T5 worker cross 路径

Status: done
Type: task
依赖：03、04、05

## 内容

`kototoki/workers/asr.py`：start 按 engine 加载一或两个适配器；compute 的 cross 分支逐文件 ①②③ 写 `asr-w0.json`、`asr-x0.json`、`asr-judge.json`、`asr.json`；日志行只记计数。

## 文件所有权

`kototoki/workers/asr.py`、`tests/core/test_stt_workers.py`、`tests/fake_worker.py`

## 完成标准

伪适配器离线测试：产物齐全、x0 失败窗口取 w0、w0 失败窗口记失败、`asr.json` 通过 `validate_transcript` 并能被 align 阶段消费。

## Comments

### 2026-10-19 实现完成（T5 agent）

- `kototoki/workers/asr.py`：抽出 `transcript_document`（w0／x0／cross 共用的 `asr.json` 组装，段先复制再 `fail_window`）与 `log_failures`；新增 `compute_cross` 与 `clean_x0`；`start` 的 cross 分支先加载 `WhisperAsr` 再加载 `QwenAsr`，分别记加载耗时，并按 `plan.model_files(engine="w0"/"x0")` 拆出两路模型 SHA。w0／x0 单引擎路径行为不变。
- 逐文件：① 写 `asr-w0.json`（身份 = 单独 w0 身份）② 写 `asr-x0.json`（身份 = 单独 x0 身份）③ 逐窗裁判，写 `asr-judge.json`（cross 身份）后由 `file_processor` 写 `asr.json`（cross 身份）。三个审计产物写前各调一次 `check()`（可注入，默认 `gpu.check_cuda`），保持"写前确认 CUDA"；`asr.json` 最后写，中途失败不会留下新的 `asr.json`。
- 窗口决定：`w0_failed`（仍失败、不替代）、`x0_failed`（取 w0、计数）、`score_error`（`RuntimeError`／`ValueError`，取 w0、WARNING 只记序号与异常、计数）、`identical`、`judged`（含守卫 `empty_result`／`normalize_failed`）。x0 原文先 `clean_x0`（`join_raw` 规则）再进 `judge_window`；`asr-judge.json` 的 `x0_text` 记未清理原文。
- 汇总：`summarize()` 只统计进入裁判的窗口，`windows` 改为全部窗口数，另加 `w0_failed`／`x0_failed`／`score_error`／`score_s`；写进 `asr-judge.json` 的 `summary` 与 `asr.json` 的 `metadata.judge`。
- 测试：`tests/core/test_stt_workers.py` 新增 `CrossAsrWorkerTest`（6 条）、`CrossStartupTest`（1 条）、align 消费 cross 结果（1 条）；core 453 条、full 12 条全绿，`compileall` 通过。`tests/fake_worker.py` 本来就按 `jobs.config["engine"]` 算身份，未改动；也未加 tests/full 的 cross 用例。
- 与设计文档的差异，需要 T7 吸收：x0 空白清理是本票按派单加的，`judge.py` 文档写的是"不改写空白"，`CROSS` 配方里没有这条规则，配方 hash 也就不覆盖它（T0 探针同样没做清理）；日志行比 changes 文档 §2.3 多了 `x0_failed`、`score_error` 与 w0／x0 耗时；stt-workers 页显存表仍写"共驻（估）约 11.5 GB／未实测"，没跟上 T0 实测的 10688 MiB。

- 2026-10-19 主 agent 审查：代码通过；x0 空白清理规则已补进 `recipes.CROSS["judge"]["x0_text_cleaning"]`，CROSS hash 重钉为 ab9f4532…，changes 文档 §2.2 同步。日志行与显存表的文档差异留给 T7。
