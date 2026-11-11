# 02 翻译子系统经 logger 发进度

Status: resolved
Type: task
Blocked by: 01

## 范围

规格见 [spec.md](../spec.md) §3.2、§3.3、§3.6。logger 名 `kototoki.translate`（`logging.getLogger(__name__)` 即可，模块都在 `kototoki.translate.*` 下）；不配置 handler、不开文件、不 print。

- `kototoki/translate/server.py`：`wait_for_free_vram` 等待超过 30 s 时 `warning`（当前读数与阈值）；`ManagedServer.__enter__` 启动后 `info`（冷加载秒数、启动前空闲显存、pid）；加载期退出／超时抛 `InfraFailure` 前 `error`。
- `kototoki/translate/generate.py`：每批次完成一行 `info`：`[translate] batch <i>/<n>: <cues> cue(s), <tokens> tok, <tok/s>, cache <n>`（字段取自现有 `row`／`attempt` 记录，不新增统计；取不到的字段省略，不编造）；session 开始／结束 `info`（`index`、`pending_at_start`、`batches_written`、`wall_seconds`）；基础设施失败与重启 `warning`（`kind`、第几次／`MAX_RESTARTS`）；放弃时 `error`；意外异常 `error` 带 `exc_info`。
- `kototoki/translate/degrade.py`：进入降级（拆子批次）`warning`（`batch_id`、层级）；单条回退保留日文 `warning`（`batch_id`、回退条数）。
- 审计并保证：所有 `StepFailed`／`TranslateError`／`InfraFailure` 的 `str()` 不含 cue 文字、提示词、grammar 或模型响应正文；若现有消息含响应正文，改为只含长度／类型／`batch_id`，并在票据评论记录改了哪处。

## 完成标准

- `just test` 全绿；`tests/core/test_translate.py`、`test_translate_degrade.py` 用 `self.assertLogs("kototoki.translate", ...)` 断言：正常流程每批一行、重启有 `WARNING`、降级与回退有 `WARNING`；一条用例断言全部日志文本不含文档里的任何 cue 文字（用测试文档里的日文字符串做反向子串断言）。
- 不改 `run.json`、`batches.jsonl`、`report.json` 内容与配方 hash（`test_translate_recipes.py` 钉子不动）。

## 文件所有权

`kototoki/translate/{server,generate,degrade}.py`、`tests/core/test_translate.py`、`tests/core/test_translate_server.py`、`tests/core/test_translate_degrade.py`（只加用例）。**不改 `kototoki/job.py`**（03 正在改它）。

## Comments

- 2026-10-18 实现完成（Opus 5.5，worktree `.claude/worktrees/rl-02`，未提交）：
  - 实现：`server.py`、`generate.py`、`degrade.py` 各加 `log = logging.getLogger(__name__)`，只发事件，不配置 handler、不开文件、不 print；`server_command` 未动；`degrade.py` 仍不导入 `generate`。
    - `server.py`：`wait_for_free_vram` 等待超过 `FREE_VRAM_WARN_SECONDS = 30` 秒时记一次 `WARNING [translate] waiting for free GPU memory: <读数> < <阈值> MiB after <秒> s`；`ManagedServer.__enter__` 健康检查通过后 `INFO [translate] llama-server pid <pid> loaded in <秒> s (free VRAM before start <MiB> MiB)`；加载期退出／超时在抛 `InfraFailure` 前以同一消息记 `ERROR`。
    - `generate.py`：session 开始 `INFO [translate] session <index> start (<server_session>): <pending_at_start> of <n> batch(es) pending`；每批写入 `batches.jsonl` 后 `INFO [translate] batch <i>/<n>: <cues> cue(s), <output_tokens> tok, <predicted_per_second> tok/s, cache <cache_n>`（取该行请求的末次尝试；降级批次取原批次请求，并追加 `degraded (<节点数> request(s), <回退数> fallback)`；`tok/s` 只取 llama-server `timings.predicted_per_second`，取不到即省略，伪客户端没有该字段故测试里不出现）；session 结束（finally）`INFO [translate] session <index> end: <batches_written> batch(es) written in <wall_seconds> s`；基础设施失败后重启 `WARNING [translate] server restart <n>/2: <kind>: <异常首行，≤200 字符>`；用尽 `ERROR [translate] giving up after 2 server restart(s): <kind>: <首行>`；意外异常 `ERROR [translate] unexpected <类型> during translation; stopping the server` 带 `exc_info`（编排器的 `ctx.fail` 也带 traceback，同一异常会在运行日志里出现两次 traceback）。
    - `degrade.py`：节点终态失败要拆分时 `WARNING [translate] batch <batch_id> failed (<error_kind>) at level <level>; splitting into <k> sub-batch(es)`；批次有回退时 `WARNING [translate] batch <batch_id>: <n> cue(s) kept in Japanese (fallback)`。续跑复用已记录节点时这些告警会再次发出。
  - 审计（`str()` 不含 cue 文字、提示词、grammar、模型响应正文）：改了两处，均在 `generate.run_step`：
    1. `HTTPError` 分支原为 `HTTP <code>: <response.raw 正文 + HTTPError 文本>[:500]`，改为 `HTTP <code> (<kind>): response body <长度> char(s)`；分类（oom／context／server_error）仍按完整正文判定，正文留在 `transport/session-NN/<序号>/response.raw`。
    2. 响应 JSON 带 `error` 时原为 `server error: <error 的 JSON>`，改为 `server error (<kind>): <error 的类型名> of <长度> char(s)`。
    其余核对无需改动：tokenize／completion transport 消息只含 `URLError` 文本；`context_budget`、`cache_n`、token 数不符、`limit`、`empty generated text` 为固定文本或数字；`validation: <exc>` 的 `exc` 来自 `adapters`／`recipes` 的固定消息或 `json.JSONDecodeError`（只含行列位置）——例外是 `Duplicate JSON key: <key>` 与 `Blank line inside translation of <key>` 带键名，键受 grammar 约束只能是 cue ID，不是正文；`InfraFailure` 只含显存读数、退出码、run 目录路径、超时秒数；`TranslateError` 只含路径、计数、kind 与上述消息。
    影响：这两条消息同时是 `run.json` 的 `sessions[].infra_failure.error`／`server_start_failures[].error`、`batches.jsonl`／`degrade.jsonl` 里 attempt 的 `error` 与 `report.json` 的 `fallback[].error` 的取值，只在 HTTP 错误或 server error 路径上文本变短；字段与 schema 不变，配方 hash 不变（`test_translate_recipes.py` 未动且通过）。
  - 测试（只加用例）：`test_translate.py` +5（正常流程每批一行且全为 INFO、session start／end 行；OOM 重启 WARNING 与用尽后 ERROR；意外异常 ERROR 带 `exc_info`；覆盖降级＋回退＋重启的整段日志不含任何 cue 文字及 `台詞`／`ですね`／`译` 片段；HTTP 错误消息不含 `response.raw` 里的日文正文且分类仍为 `context`）；`test_translate_degrade.py` +1（拆分两级与回退共三条 WARNING、降级批次的进度行）；`test_translate_server.py` +2（等显存超过 30 s 只记一条 WARNING；短等待不记日志）。
  - 自动检查：`python -m unittest discover -s tests/core -t .` 363 个测试全部通过（01 之后 355 + 本票 8）；`python -m compileall -q kototoki` 通过。未运行 `just test`／`just check`（worktree 无 `.venv`，按委派说明用主 checkout 的解释器）。
  - 未验证：`ManagedServer.__enter__` 的 INFO／ERROR 行没有离线用例（需要真实进程），只经代码审阅与编译检查；真实 llama-server 下 `predicted_per_second` 是否存在、批次行在整片上的实际观感需一次 GPU 运行核对（重任务，另问）。未经 `job.run` 的调用（如 `scripts/smoke` 的 translate_product）没有 handler 时，WARNING 以上会经 logging 的 lastResort 打到 stderr。
