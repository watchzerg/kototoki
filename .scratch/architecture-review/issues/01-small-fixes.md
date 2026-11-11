# 01 纯工程小修集合（审计报告 §3 第 1 项）

Status: resolved
Type: task
Blocked by: —

来源：[2026-10-19 架构与流程评估](../2026-10-19-report.md) §1 的 B-1、B-2、A-3、B-3、B-6、B-9、B-10、B-13、B-14／C-5、C-6，均为"已核实"的纯工程项，各改几行并可写离线测试。约束：最小充分设计、不加配置项、测试不加载模型（`just test`／`just test-full` 离线）、不动冻结的 `server_command`。

## 范围

| 项 | 改动 | 位置 |
| --- | --- | --- |
| B-1 | 扫描阶段按最终 SRT 路径（`artifacts.final_srt_paths`，Windows 下忽略大小写）去重：同目录主名相同、扩展名不同的后一个文件记 `scan` 阶段失败（`FinalPathCollision`，写 `failure.json`），不进后续阶段 | `kototoki/job.py::_run` |
| B-2 | `paths.input_dir` 不是目录时抛 `ConfigError`，退出码 2 | `kototoki/__main__.py::check_input_dir`，与 `check_output_dir` 并列 |
| A-3 | 编排按 `probe.json` 的 `extract.compensation` 判定：`net_padding_s` 绝对值或 `swr_reported_discarded_samples` 折算秒数超过 0.1 s 时各记一行 WARNING（续跑跳过 extract 时照样出现）；媒体模块只返回数据 | `kototoki/job.py::compensation_warnings`、`probe_and_extract` |
| B-3 | extract 线程池遇 `BaseException`（Ctrl+C）时 `shutdown(cancel_futures=True)` 再抛出，排队文件不再逐个提取完 | `kototoki/job.py::_run` |
| B-6 | 提取前删除该工作目录里的 `.*.partial*` 与 `.*.tmp` 残留（输出目录锁保证无并发） | `kototoki/job.py::probe_and_extract` |
| B-9 | `ProcessLock.acquire`：空的或无法解析的锁文件与死 pid 同等对待——默认拒绝并提示 `KOTOTOKI_BREAK_STALE_LOCK=1`，`break_stale` 时替换 | `kototoki/job.py::ProcessLock` |
| B-10 | `register_work_dir` 抛异常记为该文件 `scan` 失败（无工作目录，不写 `failure.json`），整批继续；`contain_children` 移进 `try`，失败时释放输出目录锁 | `kototoki/job.py::_run`、`run` |
| B-13 | 文件判定为 `done`（已是最新）或被拦下（扫描期与发布期）时删除残留的 `failure.json` | `kototoki/job.py::_run`、`publish` |
| B-14 | 翻译 session 的 llama-server stderr 改为 `DEVNULL`（与 `--log-file` 的 `server.log` 逐字节相同，不再另存 `stderr.log`）；`loader_logs` 只读 `server.log`、`stdout.log`；session 目录名改 UTC 时间戳带 `Z` 后缀（`<UTC戳>-<pid>`） | `kototoki/translate/server.py`、`generate.py::Session` |
| C-6 | `engine-final.json` 新增 `server_stop`：`terminated`（`terminate()` 后 15 s 内退出，此时 `server_exit_code` 是 Windows 的固定值 1，不是故障）、`killed`、`exited`（进程已自行退出）、`None`（未启动） | `kototoki/translate/server.py::ManagedServer.__exit__` |

不做：配置项、兼容旧 session 目录名、改 `server_command`、B-4／B-5／B-7／B-8／C-1 及任何配方变更。

## 完成标准

- 每项有离线测试：core（`tests/core/test_job.py` 伪 worker／伪媒体、`test_translate_server.py`、`test_translate.py`）；full（`tests/full/test_media_ffmpeg.py` 合成 2 s 间隙的补偿告警顺带断言）。
- `just test`、`just test-full`、`just check` 全绿；`just docs-check` 的既有失败（冻结文档外链）不算回归，本次改动页面无新错误。
- 文档随交付同步：批次编排、产物契约、配置与媒体、翻译子系统模块页受影响的句子；规格 §4 的 session 目录名。
- 不提交 Git。

## 文件所有权

单 agent 实施：`kototoki/job.py`、`kototoki/__main__.py`、`kototoki/translate/server.py`、`kototoki/translate/generate.py`、`tests/core/test_job.py`、`tests/core/test_translate_server.py`、`tests/core/test_translate.py`、`tests/full/test_media_ffmpeg.py`、上述文档页。

## Comments

- 2026-10-19 实现完成（Fable 5.1，未提交 Git）：
  - 实现：
    - B-1 `job._run` 扫描时以 `os.path.normcase(finals["ja"])` 为键去重，后出现的文件 `ctx.fail(video, "scan", FinalPathCollision(...))`（新异常类，消息指出先占用者），写 `failure.json`、不 probe。
    - B-2 `__main__.check_input_dir`：`input_dir` 不是目录即 `ConfigError`，`main` 在 `check_output_dir` 之前调用，退出码 2；`config.load` 不动（不看文件系统）。
    - A-3 `job.compensation_warnings(compensation, sample_rate)` 与常量 `COMPENSATION_WARN_S = 0.1`：`net_padding_s` 绝对值超阈值一行（padded／dropped），`swr_reported_discarded_samples / 输入采样率` 超阈值另一行；`probe_and_extract` 在 extract 后与跳过 extract 时（从 `probe.json` 的 `extract.compensation`）都并入返回的告警，由现有机制记 WARNING。媒体模块未改。
    - B-3 线程池 `with` 内 `try/except BaseException: pool.shutdown(wait=True, cancel_futures=True); raise`。
    - B-6 `job.clean_leftovers(work_dir)`：删除 `.*.partial*`、`.*.tmp`；只在真的要 extract 之前调用。
    - B-9 `ProcessLock.acquire`：无 pid（空文件、非 JSON、非 dict、pid 非整数）与死 pid 同一路径——默认 `LockError("Stale ... with no owner pid (empty or unparseable); set KOTOTOKI_BREAK_STALE_LOCK=1 ...")`，`break_stale` 时 unlink 并记入 `replaced_stale_lock`。
    - B-10 `register_work_dir` 包在 `try` 里：异常记 `summary.failed[rel] = "scan"` 并 `logger.error(..., exc_info=error)`，没有工作目录故不写 `failure.json`；`run` 里 `contain_children()` 移进 `try`，失败时 `finally` 释放输出目录锁。
    - B-13 三处 `unlink(missing_ok=True)`：计划判定 `done`、扫描期拦下、发布期拦下。
    - B-14 `ManagedServer.__enter__` 的 Popen 改 `stderr=subprocess.DEVNULL`，不再开 `stderr.log`；`loader_logs` 只读 `server.log`、`stdout.log`；`Session.runtime_root` 的时间戳改 `time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())`。`server_command` 未动。
    - C-6 `ManagedServer.__exit__` 在 `engine-final.json` 新增 `server_stop`（`terminated`／`killed`／`exited`／`None`），`server_exit_code` 原值保留。
  - 自动检查：`just test` 385 个测试通过（原 368＋新增 17：`test_job.py` 10——同主名碰撞、`register_work_dir` 异常隔离、Job Object 失败释放锁、`done`／扫描期／发布期拦下删 `failure.json`、extract 期间 `KeyboardInterrupt` 只跑完正在提取的文件、提取前清理残留、空锁与非 JSON 锁按残留处理并可破除、`input_dir` 缺失退出码 2、`compensation_warnings` 单元与续跑日志；`test_translate_server.py` 6——`server_stop` 四种值、`loader_logs` 忽略残留 `stderr.log`、Popen 的 stderr 为 DEVNULL 且目录无 `stderr.log`；`test_translate.py` 1——session 目录名）；`just test-full` 12 个通过（`test_media_ffmpeg` 的 2 s 间隙另断言一行补入告警）；`just check` 通过；`just docs-check` 仍只报既有的冻结文档外链，本次改动的五个页面无新错误；导入守门测试仍通过。
  - 文档：批次编排（入口、扫描、extract、锁、`failure.json` 清理、日志级别、代码与测试入口、未验证、来源）、产物契约（`failure.json` 清理归属与 `final_srt_paths` 碰撞说明）、配置与媒体（`input_dir` 检查归属、补偿告警归编排、临时文件清理）、翻译子系统（session 目录名、stderr 去重、`server_stop`、测试入口、来源）、规格 §4 目录名。
  - 未验证：全部只经离线测试，没有真实运行——真实 llama-server 下 `server.log` 是否在 DEVNULL 之后仍完整（审计以 `-lv 4` 加载日志逐字节相同为据）、`terminate()` 真实退出码为 1 的标注、真实 Ctrl+C 下线程池取消的体感、Windows 真实文件占用下清理残留 `.partial` 的 `PermissionError`（未处理：会让该文件 extract 失败而不是整批中止）。B-3 测试用 0.3 s 伪 probe 延迟保证 b、c 仍在队列，机器极端卡顿时可能偶发。
