"""Process identity (pid + creation time), Windows Job Objects and file locks (stdlib/ctypes only)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from .common import atomic_write_json, utc_now

_QUERY = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
_STILL_ACTIVE = 259


class LockError(RuntimeError):
    pass


def _kernel():
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
    kernel = _kernel()
    handle = kernel.OpenProcess(_QUERY, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5  # access denied => the process exists
    try:
        code = wintypes.DWORD()
        return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == _STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)


def process_created(pid: Any) -> int | None:
    """Process creation time as a FILETIME integer (Windows), or None if unavailable."""
    if sys.platform != "win32" or type(pid) is not int or pid <= 0:
        return None
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
    """Alive and, when a creation time was recorded, the same process (handles PID reuse)."""
    if not pid_alive(pid):
        return False
    if created is None:
        return True
    current = process_created(pid)
    return current is None or current == created


def list_llama_servers() -> list[int]:
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("llama-server") and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


# --- Job Object -------------------------------------------------------------------------

class _BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                     "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class KillOnCloseJob:
    """Windows Job Object with KILL_ON_JOB_CLOSE: if this Python process dies, assigned children die too."""

    def __init__(self) -> None:
        self.handle = None
        if sys.platform != "win32":
            return
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel = kernel
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            kernel.CloseHandle(handle)
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        self.handle = handle

    def assign(self, process: subprocess.Popen) -> bool:
        if self.handle is None:
            return False
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        return True

    def close(self) -> None:
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


# --- file lock with pid + creation time ---------------------------------------------------

Alive = Callable[[Any, Any], bool]


class ProcessLock:
    """O_EXCL lock file naming its owner by pid + creation time; never preempts a live owner."""

    kind = "lock"

    def __init__(self, path: Path, info: dict[str, Any] | None = None, *, alive: Alive = process_matches,
                 pid: int | None = None, created: int | None = None):
        self.path, self.alive = Path(path), alive
        self.pid = os.getpid() if pid is None else pid
        self.created = process_created(self.pid) if created is None and pid is None else created
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

    def owner_alive(self, data: dict[str, Any]) -> bool:
        return self.alive(data.get("pid"), data.get("pid_created"))

    def stale_message(self, data: dict[str, Any]) -> str:
        return f"Stale {self.kind} from dead pid {data.get('pid')}"

    def acquire(self, *, break_stale: bool = False) -> None:
        current = self.read()
        if current is not None:
            if current.get("unparseable") or type(current.get("pid")) is not int:
                raise LockError(f"{self.path} exists but is not a v3 lock; inspect it and its owner manually")
            if self.owner_alive(current):
                raise LockError(f"{self.kind} {self.path} held by live pid {current['pid']} "
                                f"({ {k: v for k, v in current.items() if k in ('run_id', 'created_at_utc')} }); "
                                "not starting. Do not kill it.")
            if not break_stale:
                raise LockError(self.stale_message(current))
            self.stale = current
            self.path.unlink()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LockError(f"{self.kind} was taken concurrently") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(self._payload(), stream)
        self.held = True

    def _payload(self) -> dict[str, Any]:
        return {"pid": self.pid, "pid_created": self.created, **self.info, "owner": "experiments.translation_v3",
                "created_at_utc": utc_now(), "replaced_stale_lock": self.stale}

    def update(self, **fields: Any) -> None:
        if self.held:
            current = self.read() or {}
            if current.get("pid") == self.pid:
                atomic_write_json(self.path, current | fields)

    def release(self) -> None:
        if not self.held:
            return
        current = self.read()
        if current and current.get("pid") == self.pid and current.get("pid_created") == self.created:
            self.path.unlink()
        self.held = False

    def __enter__(self) -> "ProcessLock":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()
