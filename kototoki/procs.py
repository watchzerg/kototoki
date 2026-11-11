"""进程原语：进程存活与身份（pid＋创建时间）、Job Object、O_EXCL 锁文件（基础层，只用标准库与 ctypes）。

与流水线无关；批次编排（`kototoki.job`）用它持有工作根锁与 `.local/gpu.lock`，并把编排器放进 KILL_ON_JOB_CLOSE
Job Object。复制自 `experiments/translation_v3/procs.py`（不导入）。锁文件内容的时间戳与原子改写取自同在基础层的
`kototoki.artifacts`。

模块页：docs/architecture/modules/run-logging-and-processes.md。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import ctypes
import json
import os
from pathlib import Path
import sys
from typing import Any

from kototoki import artifacts

_QUERY = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
_STILL_ACTIVE = 259


class LockError(RuntimeError):
    pass


def _kernel() -> Any:
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    return kernel


def pid_alive(pid: Any) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    from ctypes import wintypes
    kernel = _kernel()
    handle = kernel.OpenProcess(_QUERY, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5  # access denied => 进程存在
    try:
        code = wintypes.DWORD()
        return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == _STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def process_created(pid: Any) -> int | None:
    """进程创建时间（Windows FILETIME 整数）；不可得时为 None。"""
    if sys.platform != "win32" or type(pid) is not int or pid <= 0:
        return None
    from ctypes import wintypes
    kernel = _kernel()
    handle = kernel.OpenProcess(_QUERY, False, pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def process_matches(pid: Any, created: Any) -> bool:
    """进程存活，且记录了创建时间时仍是同一进程（防 pid 复用）。"""
    if not pid_alive(pid):
        return False
    if created is None:
        return True
    current = process_created(pid)
    return current is None or current == created


_job_handle: Any = None


def contain_children() -> None:
    """把编排器进程放进 KILL_ON_JOB_CLOSE Job Object；之后启动的 ffmpeg、worker 与 Strata CLI 自动加入（Strata 服务本身在后台，靠 `--stop` 收尾）。

    句柄只由本进程持有、从不显式关闭：编排器以任何方式退出时系统关闭句柄，子进程随之结束，
    不留占显存的孤儿。每个进程只做一次；非 Windows 平台不做。
    """
    global _job_handle
    if _job_handle is not None or sys.platform != "win32":
        return
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    if not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    _job_handle = handle


Alive = Callable[[Any, Any], bool]


class ProcessLock:
    """O_EXCL 锁文件，以 pid + 创建时间标识持有者；从不抢占存活的持有者。"""

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
