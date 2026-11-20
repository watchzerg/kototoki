"""进程原语：进程存活与身份（pid＋启动时间）、子进程随编排器退出、O_EXCL 锁文件（基础层，只用标准库）。

与流水线无关；批次编排（`kototoki.job`）用它持有工作根锁与 `.local/gpu.lock`，并用 `contained` 启动 ffmpeg、
GPU worker 与 Strata CLI。锁文件内容的时间戳与原子改写取自同在基础层的 `kototoki.artifacts`。

模块页：docs/architecture/modules/run-logging-and-processes.md。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
import os
from pathlib import Path
from typing import Any

from kototoki import artifacts


class LockError(RuntimeError):
    pass


def pid_alive(pid: Any) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # 别的用户的进程：存在
        return True
    return True


def process_created(pid: Any) -> int | None:
    """进程启动时间：`/proc/<pid>/stat` 第 22 个字段（开机以来的 clock tick）；不可得时为 None。"""
    if type(pid) is not int or pid <= 0:
        return None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except OSError:
        return None
    # 第 2 个字段 comm 带括号且可含空格与括号，从最后一个 ")" 之后数：其后第 1 个字段是第 3 个（state）。
    return int(stat[stat.rindex(")") + 2:].split()[19])


def process_matches(pid: Any, created: Any) -> bool:
    """进程存活，且记录了启动时间时仍是同一进程（防 pid 复用）。"""
    if not pid_alive(pid):
        return False
    if created is None:
        return True
    current = process_created(pid)
    return current is None or current == created


def contained(command: Sequence[str]) -> list[str]:
    """子进程命令：经 `setpriv --pdeathsig KILL` 启动，创建它的线程一退出（编排器以任何方式结束，含被 SIGKILL），
    内核就向它发 SIGKILL，不留占显存的孤儿（ADR-0034「子进程与长任务」）。

    GPU worker 与 Strata CLI 另传 `start_new_session=True`：它们在自己的进程组里，终端的 Ctrl+C 只到编排器，由它
    回收。ffmpeg／ffprobe 留在前台进程组：Ctrl+C 让它们立即退出，提取线程池不必等整部影片解码完。
    PDEATHSIG 看的是创建子进程的**线程**：调用方须在同一线程里等子进程结束（`Popen.wait`／`subprocess.run`）。
    `setpriv` 来自 util-linux，`exec` 后 pid 不变；PDEATHSIG 不传给子进程再 fork 出的进程（Strata 服务因此不受影响，
    仍靠 `strata launch --stop` 收尾）。
    """
    return ["setpriv", "--pdeathsig", "KILL", "--", *command]


Alive = Callable[[Any, Any], bool]


class ProcessLock:
    """O_EXCL 锁文件，以 pid + 启动时间标识持有者；从不抢占存活的持有者。"""

    def __init__(self, path: Path, kind: str, info: Mapping[str, Any] | None = None, *,
                 alive: Alive = process_matches):
        self.path, self.kind, self.alive = Path(path), kind, alive
        self.pid = os.getpid()
        self.created = process_created(self.pid)
        self.info = dict(info or {})
        self.stale: dict[str, Any] | None = None
        self.held = False

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {"unparseable": True}
        return data if isinstance(data, dict) else {"unparseable": True}

    def acquire(self, *, break_stale: bool = False) -> None:
        current = self.read()
        if current is not None:
            # 空的或无法解析的锁文件（持有者刚创建就被杀）没有 pid，与死 pid 同等对待：默认拒绝，`break_stale` 时替换。
            owner = current.get("pid") if type(current.get("pid")) is int else None
            if owner is not None and self.alive(owner, current.get("pid_created")):
                raise LockError(f"{self.kind} {self.path} held by live pid {owner}; not starting. Do not kill it.")
            if not break_stale:
                origin = f"from dead pid {owner}" if owner is not None else "with no owner pid (empty or unparseable)"
                raise LockError(f"Stale {self.kind} {self.path} {origin}; "
                                f"set KOTOTOKI_BREAK_STALE_LOCK=1 for one run to remove it")
            self.stale = current
            self.path.unlink()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LockError(f"{self.kind} {self.path} was taken concurrently") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": self.pid, "pid_created": self.created, **self.info, "owner": "kototoki",
                       "created_at_utc": artifacts.utc_now(), "replaced_stale_lock": self.stale}, stream)
        self.held = True

    def update(self, **fields: Any) -> None:
        if self.held:
            current = self.read() or {}
            if current.get("pid") == self.pid:
                artifacts.atomic_write_json(self.path, current | fields)

    def release(self) -> None:
        if not self.held:
            return
        current = self.read()
        if current and current.get("pid") == self.pid and current.get("pid_created") == self.created:
            self.path.unlink()
        self.held = False
