# 04 编排共用 session：整批只启动一次、中断 stop、GPU 锁 pid

Status: resolved
Type: task
Blocked by: 03

范围、终点与门见计划 §4 第 4 张票据（docs/plans/product-names-on-strata.md）。

- `job` 持有共享 session，跨 names 与 translate；names 全部 current 时从 translate 启动；都不需要时不启动。
- 更新 `test_job.py`、`test_job_ffmpeg.py` 的伪模块与顺序断言。

## 执行记录

- 2026-11-09 `job.py`：`_strata_module()`（importlib）；`_run` 在 names 之前建 `strata.Session(config, on_server_pid=写 GPU 锁)` 作上下文管理器包住 `names_batch` 与 `translate_batch`，退出（正常、出错、Ctrl+C）即 `--stop`，之后才 `gpu_lock.release()`；两个 batch 函数改为接收 `session`：names 对有 cue 的文件传 session、零条目传 None；translate 对 `needs_model` 的文件传 session、其余传 None；取锁规则不变（names 有 cue 才取，translate 有 `needs_model` 才取，已取则沿用）；两处 `gpu_lock.update(server_pid=None)` 删除（Session 停止时经回调清空；未取锁时 `update` 本就是空操作）。模块说明同步。
- `kototoki.translate` 不再导出 `Session`。
- 测试：`test_job.py` 的伪 `kototoki.translate.Session`、伪 `names.Session` 换成伪 `kototoki.strata` 模块（`Session` 构造不启动、首次 `ensure_started` 记 `session_enter` 并回调 pid、`stop` 记 `session_exit`；`StrataRefused`），伪 `build_document`／`translate_document` 像真实模块一样只在需要模型时调 `ensure_started()`；顺序断言改为 `session_enter → names:* → translate:* → session_exit → merge`；新增：整批恰一个 session、names 启动翻译后停、`StrataRefused` 让 names（新片）与 translate（表当前只翻译）两阶段都失败且不启动、翻译中 Ctrl+C 仍 stop 并释放两把锁；`test_job_ffmpeg.py` 顺序断言同步。
- 自动检查：`just test` 609 过；`tests.full.test_job_ffmpeg` 3 过；`just check` 过；`docs-check` 44 条均为已有。模块页（批次编排第 7–9 步、锁、测试清单）在票据 01 已按此写好，无需再改。

## Answer

完成。编排持有一个共享 Strata session 跨 names 与 translate，整批只启动一次、退出即停、pid 进 GPU 锁；两阶段都不需要模型时不启动。
