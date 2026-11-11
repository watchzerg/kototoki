# 02 配方块、新 id、重钉 hash；workers/asr.py 接入 w0 与 cross

Status: resolved
Type: task
Blocked by: 01

范围与终点见计划 §4 票据 02（docs/plans/asr-repeat-guard.md）。

## 执行记录

- 2026-11-11：配方块、新 id、重钉 hash 已在 01 完成。本票：`workers/asr.py` 加 `apply_guard`，w0 引擎在 `compute()` 的 `transcribe` 之后调用，cross 在写 `asr-w0.json` 之前对 w0 那一路调用；x0 引擎与 cross 的 x0 那一路不调用。进度行与每文件 INFO 行加 `guarded_windows`／`guarded N`；折叠记一行 WARNING（窗口号、周期、份数、删去字符数），置空走既有的失败窗口 WARNING。
- 测试（`tests/core/test_stt_workers.py`）：折叠改文字并写 trace、置空进 `failed_windows`、已失败窗口不过守卫、x0 不受影响、cross 的裁判拿到守卫后的 w0 文字且 x0 那一路不过守卫、日志无文字。
- `just check`、`just test`（627 项）、`just test-full`（14 项）通过。
- 研究期 `experiments/asr_robustness_v14/test_offline.py::Identity::test_w0_recipe_hash_is_pinned` 钉着旧 hash，现在失败（不在门禁内、不可改），写计划 §8。

## Answer

完成。trace 形状：`asr_traces[i].guard = {rule, action, period, copies, removed_raw_chars}`；置空原因 `guard:repeat-strict`。
