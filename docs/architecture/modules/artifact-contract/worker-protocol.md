---
covers:
  - kototoki/workers/protocol.py
---
# 产物契约子页：worker --jobs 协议与退出码

`产物契约` 的子页：编排器与 GPU worker 之间的 `--jobs` 协议、进度事件、退出码、启动判定（读侧）与失败窗口表示。改 `kototoki/workers/protocol.py` 或核对 worker 退出码与重启判定时读本页。上级：[产物契约](../artifact-contract.md)。

## 行为规格

**worker 协议**（`kototoki/workers/protocol.py`）：

- `--jobs <path>` 指向 `{"stage", "recipe_hash", "config", "files": [{"id", "work_dir", "inputs": {name: path}}]}`，键集合严格、id 唯一（`parse_jobs`／`read_jobs`／`write_jobs`）。
- `run_worker` 读 jobs、调用一次 `start(jobs)` 加载模型，成功后向 stdout 打 `started` 事件，再由 `run_jobs` 逐文件处理；结果由 worker 写进各自工作目录。
- stdout 打 UTF-8 JSON 进度行：`started`（模型加载完成、处理首个文件前）与 `done`／`failed`／`fatal`／`startup_failed`，只含事件、id、异常类型、计数与 `startup_failed` 的 `message`，不含窗口文字。
- 退出码：0 全部完成；1 有文件失败（该文件写 `failure.json`，继续下一文件）；2 启动失败（`startup_failed`，不重启）或 `FatalWorkerError`（`fatal`：CUDA 粘性错误等，当前文件写 `failure.json` 后立即退出，编排器从下一文件重启）；未发出 `started` 与任何文件事件前的异常退出同样视为启动失败、不重启。

**失败窗口**（w0／x0／cross 共用）：

- `fail_window(asr, chunk_index, reason)` 把 `original_segments[i].text` 移入 `failed_windows`（`chunk_index`、`reason`、`text`）并置空；`retained_text` 是保留文本，后续对齐、cue 与翻译只用它。
- `validate_failed_windows` 要求列表存在、索引唯一有效且对应窗口已置空。
- `reason` 的现有取值：解码／生成抛错的 `RuntimeError: …`、x0 触顶的 `token_limit_reached: generated <n> tokens`、w0 整窗守卫置空的 `guard:repeat-strict`、`guard:speech-rate`、`guard:hallucination-phrase`（[ADR-0030](../../../adr/0030-asr-window-plausibility-guard.md)；此时 `text` 是该窗被置空前的完整原文）。

**整窗守卫记录**（w0 与 cross 的 `asr.json`、cross 的 `asr-w0.json`）：

- 被守卫改动或跳过的窗口在 `asr_traces[i]` 里多一个键 `guard`，内容是生效规则或跳过记录：复读 `{rule, action, period, copies, removed_raw_chars}`，语速 `{rule, action, chars, duration_s}`，幻听句 `{rule, action, phrase_index}`，无法规范化跳过 `{rule: "normalize", action: "skip", reason: "normalize_failed"}`。
- `action` 为 `collapse`（只有复读，`original_segments[i].text` 已是折叠后的文字）、`blank`（该窗同时出现在 `failed_windows`）或 `skip`（保留原文不置空）；没有命中或跳过的窗口没有这个键。
- 记录只有规则名与计数，不含文字。字段含义见 [STT ASR](../stt-asr/window-guard.md#w0-整窗守卫)。


## 实现设计

### 协议读侧

同一模块，编排使用。纯函数 `classify_launch(ids, exit_code, events) -> LaunchOutcome` 解释一次 worker 启动，`LaunchOutcome` 含 `failed`、`crashed`、`fatal`、`startup_failed`、`remaining` 与 `error_types`（报了 `failed`／`fatal` 的 id → worker 的 `error_type`）；`progress_event(event)` 判定事件是否转发成进度行并给出 `done` 的数值计数。事件名只在本模块出现。

规则：

- 退出码 0／1 只有在每个待跑 id 都有事件时才算正常结束（退出码 1 也是 Python 未捕获异常的退出码）。
- 否则有 `startup_failed` 即启动失败，`startup_failed` 保留 `error_type` 及事件 `message` 首行摘要（截断到 200 字符；为空时仅保留 `error_type`）；既无 `started` 又无已报告的待跑文件事件（加载模型期间原生崩溃），同样按启动失败处理（`exited with code <n>`），剩余全部失败、不重启。
- 否则有 `fatal` 即该 id 为崩溃文件，从其后重启；再否则最后一个有事件的 id 之后的那个 id（有 `started` 而无文件事件时为首个 id）是崩溃文件，从其后重启。
- 编排的 `run_gpu_stage` 只循环与记失败，不用字面量解释协议。

## 代码与验证入口

- 代码：`kototoki/workers/protocol.py`。
- `tests/core/test_protocol.py`：`run_worker` 先发 `started` 再逐文件处理、单文件失败隔离与 `fatal` 退出码 2；`classify_launch` 的部分失败与 `error_type` 传递、`startup_failed` 保留 `message` 首行摘要、`progress_event`、`fatal`、启动期无 `started` 崩溃（不重启）与 `started` 后崩溃归咎；`failed_windows` 清空窗口文字并记录。
- 测试精简（2026-11-22）后不再有测试覆盖：
  - 协议：jobs 解析、畸形 jobs 与不一致记录的 `validate` 与退出码 1 缺事件。
