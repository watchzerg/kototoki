---
covers:
  - kototoki/procs.py
---
# 运行日志与进程原语子页：进程原语

`运行日志、进程原语与 worker 子进程` 的子页：进程存活与身份、子进程随编排器退出、O_EXCL 锁文件。上级：[运行日志、进程原语与 worker 子进程](../run-logging-and-processes.md)。

## 进程原语

- **进程身份**：`pid_alive(pid)`（`os.kill(pid, 0)`；`PermissionError` 即别的用户的进程，视为存在；非整数或非正 pid 视为不存在）；`process_created(pid)` 取进程启动时间（`/proc/<pid>/stat` 第 22 个字段，开机以来的 clock tick；不可得时为 None）；`process_matches(pid, created)` 要求进程存活，且记录了启动时间时仍是同一进程（防 pid 复用）。
- **子进程随编排器退出**（[ADR-0034](../../../adr/0034-ubuntu-only-platform.md#子进程与长任务)）：`contained(command)` 在命令前加 `setpriv --pdeathsig KILL --`。创建子进程的线程一退出（含编排器被 SIGKILL），内核就向子进程发 SIGKILL；调用方因此在同一线程里等子进程结束。不用 `preexec_fn`（提取线程池在，多线程下不安全）。GPU worker 与 Strata CLI 另传 `start_new_session=True`，Ctrl+C 只到编排器、由它回收；ffmpeg 留在前台进程组，Ctrl+C 让它立即退出。Strata 服务是 CLI 再 fork 出的，不继承 PDEATHSIG，靠 `--stop` 收尾。
- **锁文件**（`ProcessLock(path, kind, info)`）：
  - `acquire` 用 O_EXCL 创建锁文件，写入 `pid`、`pid_created`、调用方的 `info`、`owner: "kototoki"`、`created_at_utc` 与 `replaced_stale_lock`。
  - 已有锁文件时：持有者存活（`process_matches`）即抛 `LockError`，从不抢占存活的持有者；没有 `pid_created` 的外部锁只按 pid 判断。
  - 残留锁（死 pid，或空的／无法解析的／pid 不是整数的锁文件）默认抛 `LockError`，消息提示 `KOTOTOKI_BREAK_STALE_LOCK=1`；`acquire(break_stale=True)` 时删除残留锁再创建，旧内容记入 `replaced_stale_lock`。
  - 并发创建撞上即抛 `LockError`。
  - `update(**fields)` 只在持有且锁文件仍属本进程时原子改写；`release()` 只删 pid 与创建时间都与本进程相同的锁。
  - 编排经 `update` 往 GPU 锁写附加字段：worker 运行期间 `worker_pid`／`worker_stage`（`Popen.pid`，`setpriv` exec 后即 worker 本身）；Strata 运行期间 `server_pid`（由共享 `strata.Session` 的 `on_server_pid` 回调提供：ready 后写入、停止后清空；pid 取自 `strata launch --status`，缺失时不记）。

## 代码与验证入口

- 代码：`kototoki/procs.py`（`pid_alive`、`process_created`、`process_matches`、`contained`、`ProcessLock`、`LockError`）。
- 测试（core，`mise run test`）：
  - `tests/core/test_procs.py`：存活持有者永不被抢占；死持有者的残留锁默认拒绝、`break_stale` 才替换并记录旧锁；`release` 只删自己的锁；`process_created`／`process_matches` 以启动时间识别 pid 复用。
  - 测试精简（2026-11-22）后不再有测试覆盖（进程原语部分）：
    - 进程原语：锁内容、空锁与不可解析的锁、无 `pid_created` 的外部锁按 pid 判断、非整数 pid、并发创建报锁错误、`update` 只改自己的锁、含空格与括号的 comm 解析、无效 pid 无身份、`contained` 的 `setpriv` 前缀。
- 未验证（Linux）：整批运行中强杀编排器后 GPU worker 释放显存的真实路径（Windows 时期的[最终验收](../../../research/acceptance/bilingual-pipeline-final-acceptance-2026-10-15.md)只作历史）。
