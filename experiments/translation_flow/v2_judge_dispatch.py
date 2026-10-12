"""Windows owned CLI jobs and one shared custody reservation, without fallback.

Only processes created here are ever terminated. Every root starts suspended,
joins a kill-on-close job, then resumes; descendants cannot break away. Guard
release requires all owned callbacks and native processes to have drained.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

from experiments.translation_judge.integrity import canonical_bytes, strict_parse
from experiments.translation_judge.runner import event_evidence

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_GUARD: CustodyGuard | None = None


class _Security(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]


class _Startup(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR), ("desktop", wintypes.LPWSTR),
               ("title", wintypes.LPWSTR), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
               ("x_size", wintypes.DWORD), ("y_size", wintypes.DWORD), ("x_chars", wintypes.DWORD),
               ("y_chars", wintypes.DWORD), ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
               ("show", wintypes.WORD), ("reserved_bytes", wintypes.WORD),
               ("reserved_pointer", ctypes.POINTER(ctypes.c_byte)),
               ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]


class _StartupEx(ctypes.Structure):
    _fields_ = [("startup", _Startup), ("attributes", ctypes.c_void_p)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
               ("pid", wintypes.DWORD), ("tid", wintypes.DWORD)]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong), ("flags", wintypes.DWORD),
               ("minimum_working_set", ctypes.c_size_t), ("maximum_working_set", ctypes.c_size_t),
               ("active_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
               ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]


class _Io(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ("reads", "writes", "others", "read_bytes", "write_bytes", "other_bytes")]


class _Limits(ctypes.Structure):
    _fields_ = [("basic", _BasicLimits), ("io", _Io), ("process_memory", ctypes.c_size_t),
               ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in ("user", "kernel", "period_user", "period_kernel")] + [
        (name, wintypes.DWORD) for name in ("page_faults", "total", "active", "terminated")]


def _kernel():
    if os.name != "nt":
        raise ValueError("Native Windows dispatch required; no portable fallback")
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "ResumeThread": ([wintypes.HANDLE], wintypes.DWORD),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Security),
                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        "InitializeProcThreadAttributeList": ([ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
        "UpdateProcThreadAttribute": ([ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
        "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
        "CreateProcessW": ([wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL,
                            wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(_Startup), ctypes.POINTER(_ProcessInfo)], wintypes.BOOL),
    }
    for name, (args, restype) in signatures.items():
        getattr(k, name).argtypes, getattr(k, name).restype = args, restype
    return k


def _check(value) -> None:
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())


class _NativeJob:
    def __init__(self):
        self.k = _kernel()
        self.lock = threading.RLock()
        self.handle = self.k.CreateJobObjectW(None, None)
        _check(self.handle)
        self.info = _ProcessInfo()
        self.assigned = False
        self.stop_launch = False
        self.drained = False
        limits = _Limits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway permission.
        try:
            _check(self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self.k.CloseHandle(self.handle)
            raise

    def active(self) -> int:
        if self.handle is None and self.drained:
            return 0
        data = _Accounting()
        _check(self.k.QueryInformationJobObject(self.handle, 1, ctypes.byref(data), ctypes.sizeof(data), None))
        return int(data.active)

    def launch(self, args: list[str], cwd: Path, streams: list[int], env: dict[str, str]) -> None:
        with self.lock:
            if self.stop_launch:
                raise OSError("Custody reservation is closing; suspended launch refused")
            size = ctypes.c_size_t()
            self.k.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            if not size.value:
                raise ctypes.WinError(ctypes.get_last_error())
            attributes = ctypes.create_string_buffer(size.value)
            _check(self.k.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)))
            try:
                handles = (wintypes.HANDLE * 3)(*streams)
                _check(self.k.UpdateProcThreadAttribute(attributes, 0, 0x00020002,
                                                        ctypes.byref(handles), ctypes.sizeof(handles), None, None))
                startup = _StartupEx()
                startup.startup.cb = ctypes.sizeof(startup)
                startup.startup.flags = 0x100 | 1  # USESTDHANDLES | USESHOWWINDOW.
                startup.startup.show = 0
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = streams
                startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
                command = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
                environment = ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(env.items(), key=lambda v: v[0].lower())) + "\0\0")
                flags = 0x00000004 | 0x08000000 | 0x00000400 | 0x00080000
                # SUSPENDED | NO_WINDOW | UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT.
                _check(self.k.CreateProcessW(args[0], command, None, None, True, flags, environment, str(cwd),
                                             ctypes.cast(ctypes.byref(startup), ctypes.POINTER(_Startup)), ctypes.byref(self.info)))
                self._assign()
                if self.k.ResumeThread(self.info.thread) == 0xffffffff:
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.k.DeleteProcThreadAttributeList(attributes)

    def _assign(self) -> None:
        _check(self.k.AssignProcessToJobObject(self.handle, self.info.process))
        self.assigned = True

    def wait_root(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            status = self.k.WaitForSingleObject(self.info.process, max(1, min(100, int(remaining * 1000))))
            if status == 0:
                return True
            if status != 258:
                raise ctypes.WinError(ctypes.get_last_error())

    def drain(self) -> None:
        """Retain job and enclosing lock indefinitely if drain cannot be proven."""
        last_notice = 0.0
        while True:
            try:
                with self.lock:
                    self.stop_launch = True
                    if self.drained:
                        return
                    if not self.info.process:
                        if self.active() == 0:
                            self.drained = True
                            return
                    elif not self.assigned:
                        # Still suspended: assignment failed before any root code ran.
                        status = self.k.WaitForSingleObject(self.info.process, 0)
                        if status == 258:
                            _check(self.k.TerminateProcess(self.info.process, 1))
                        _check(self.k.WaitForSingleObject(self.info.process, 1000) == 0)
                        self.drained = True
                        return
                    elif self.active() == 0:
                        _check(self.k.WaitForSingleObject(self.info.process, 1000) == 0)
                        self.drained = True
                        return
                    _check(self.k.TerminateJobObject(self.handle, 1))
                time.sleep(0.01)
            except BaseException as exc:
                if time.monotonic() - last_notice > 10:
                    try:
                        print(f"Owned native drain unproven; custody lock retained: {type(exc).__name__}", file=sys.stderr, flush=True)
                    except BaseException:
                        pass
                    last_notice = time.monotonic()
                try:
                    time.sleep(0.05)
                except BaseException:
                    pass

    def close(self) -> None:
        with self.lock:
            if not self.drained:
                raise ValueError("Native handles cannot close before positive owned drain proof")
            if self.handle is None:
                return
            errors = []
            for handle in (self.info.thread, self.info.process, self.handle):
                if handle:
                    if not self.k.CloseHandle(handle):
                        errors.append(ctypes.WinError(ctypes.get_last_error()))
            self.info.thread = self.info.process = self.handle = None
            if errors:
                raise errors[0]


def _receipt(path: Path, expected_sha256: str) -> dict[str, Any]:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Core terminal receipt bytes changed")
    value = strict_parse(data.decode("utf-8-sig"))
    if (not isinstance(value, dict) or value.get("schema") != "hy30-judge-core-terminal-receipt-v1"
            or value.get("owner") != "evaluation_custodian" or value.get("core_pipeline_terminal") is not True
            or value.get("native_children_drained") is not True or value.get("owned_cli_batches") != []):
        raise ValueError("Core pipeline is not terminal/drained or another owned CLI batch remains")
    return value


class CustodyGuard:
    """Exclusive shared six-slot lease, held through every native callback drain.

    All core and sidecar owners must honor this same lock path. The terminal
    receipt is custody attestation, not a scan of unrelated Codex GUI processes.
    """
    def __init__(self, root: Path, workers: int, terminal_receipt: Path, terminal_sha256: str,
                 *, owner: str = "evaluation_custodian"):
        if type(workers) is not int or not 1 <= workers <= 6 or owner != "evaluation_custodian":
            raise ValueError("Only custody owner may reserve 1..6 shared CLI slots")
        if os.name != "nt":
            raise ValueError("Custody native dispatch requires Windows")
        self.root, self.workers = root.resolve(), workers
        self.terminal_receipt, self.terminal_sha256 = terminal_receipt.resolve(), terminal_sha256
        self.owner = owner
        self.token = uuid.uuid4().hex
        self.condition = threading.Condition()
        self.slots = threading.BoundedSemaphore(workers)
        self.jobs: set[_NativeJob] = set()
        self.active_callbacks = 0
        self.entered = self.closing = False
        self.implementation_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.stream = None
        self.owner_record = self.root / ".judge-dispatch-receipts" / (self.token + ".json")

    def _record(self, state: str) -> None:
        value = {"schema": "hy30-native-judge-custody-v1", "owner": self.owner, "pid": os.getpid(),
                 "token": self.token, "workers_reserved": self.workers, "shared_limit": 6,
                 "global_lock": str(self.root / ".judge-global-six.lock"), "state": state,
                 "terminal_receipt": str(self.terminal_receipt), "terminal_sha256": self.terminal_sha256,
                 "active_callbacks": self.active_callbacks, "owned_job_objects": len(self.jobs),
                 "at": datetime.now(timezone.utc).isoformat(), "module_sha256": self.implementation_sha256,
                 "measurement": "receipt-time snapshot; the shared native lock is the authoritative live lease"}
        self.owner_record.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.owner_record.with_suffix(".pending")
        temporary.write_bytes(canonical_bytes(value))
        temporary.replace(self.owner_record)

    def __enter__(self):
        global _ACTIVE_GUARD
        import msvcrt
        with _ACTIVE_LOCK:
            if _ACTIVE_GUARD is not None or self.entered or self.closing:
                raise ValueError("Another custody CLI lease is already active in this process")
            self.root.mkdir(parents=True, exist_ok=True)
            self.stream = (self.root / ".judge-global-six.lock").open("a+b")
            if os.fstat(self.stream.fileno()).st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            try:
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                self.stream.close()
                self.stream = None
                raise ValueError("Shared global six-slot reservation is held by another custody pipeline") from exc
            try:
                _receipt(self.terminal_receipt, self.terminal_sha256)
                self._record("held")
            except BaseException:
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                self.stream.close()
                self.stream = None
                raise
            self.entered = True
            _ACTIVE_GUARD = self
        return self

    def __exit__(self, *exception):
        global _ACTIVE_GUARD
        import msvcrt
        with self.condition:
            self.closing = True
            owned = list(self.jobs)
        for job in owned:
            job.drain()
        # Do not let interruption/metadata failure release the lock with callbacks alive.
        while True:
            try:
                with self.condition:
                    if self.active_callbacks == 0 and not self.jobs:
                        break
                    self.condition.wait(0.05)
            except BaseException:
                continue
        with _ACTIVE_LOCK:
            try:
                self._record("drained_released")
            finally:
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                self.stream.close()
                self.stream = None
                self.entered = False
                _ACTIVE_GUARD = None

    def execute(self, args: list[str], prompt: str, cwd: Path, attempt: Path, timeout: float) -> dict[str, Any]:
        with self.condition:
            if not self.entered or self.closing:
                raise ValueError("Native CLI dispatch requires an active custody reservation")
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != self.implementation_sha256:
                raise ValueError("Native dispatch implementation changed during custody lease")
            _receipt(self.terminal_receipt, self.terminal_sha256)
            if not self.slots.acquire(blocking=False):
                raise ValueError("Native callback count exceeds reserved global slots")
            self.active_callbacks += 1
        try:
            return self._execute(args, prompt, cwd, attempt, timeout)
        finally:
            with self.condition:
                self.active_callbacks -= 1
                self.slots.release()
                self.condition.notify_all()

    def _execute(self, args, prompt, cwd, attempt, timeout):
        started = time.perf_counter()
        k = _kernel()
        attempt = Path(attempt).resolve()
        handles: list[int] = []
        native = None
        result: dict[str, Any] = {"returncode": None, "transport_status": "spawn_failed"}
        result.update(native_dispatch_sha256=self.implementation_sha256,
                      custody_receipt=str(self.owner_record), custody_token=self.token,
                      custody_workers_reserved=self.workers)
        removed = []
        try:
            if (not isinstance(args, list) or not args or any(not isinstance(a, str) or "\0" in a for a in args)
                    or not isinstance(prompt, str) or type(timeout) not in {float, int} or not math.isfinite(timeout) or timeout <= 0):
                raise ValueError("Invalid native argv, prompt or timeout")
            executable = shutil.which(args[0]) or args[0]
            if Path(executable).suffix.lower() in {".cmd", ".bat", ".ps1"}:
                raise ValueError("Native suspended dispatch requires an executable .exe, not a shell shim")
            args = [str(Path(executable).resolve()), *args[1:]]
            env = os.environ.copy()
            for key in list(env):
                if key.startswith("CODEX_") and key != "CODEX_HOME":
                    removed.append(key)
                    del env[key]
            # Disk-backed stdin/stdout/stderr avoid pipe deadlocks and retain exact bytes.
            paths = [attempt / "stdin.bin", attempt / "stdout.jsonl", attempt / "stderr.txt"]
            for index, path in enumerate(paths):
                with path.open("xb") as stream:
                    stream.write(prompt.encode("utf-8") if index == 0 else b"")
            security = _Security(ctypes.sizeof(_Security), None, True)
            for index, path in enumerate(paths):
                handle = k.CreateFileW(str(path), 0x80000000 if index == 0 else 0x40000000,
                                       1 | 2, ctypes.byref(security), 3, 0x80, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(handle)
            native = _NativeJob()
            with self.condition:
                if self.closing:
                    raise OSError("Custody reservation began closing before native launch")
                self.jobs.add(native)
            native.launch(args, Path(cwd).resolve(), handles, env)
            result.update(native_root_pid=int(native.info.pid), containment="suspended-assign-resume-kill-on-close-job")
            completed = native.wait_root(timeout)
            if completed:
                code = wintypes.DWORD()
                _check(k.GetExitCodeProcess(native.info.process, ctypes.byref(code)))
                result.update(transport_status="completed", returncode=int(code.value))
            else:
                result["transport_status"] = "timeout"
        except (OSError, ValueError) as exc:
            result.update(transport_error=str(exc))
        finally:
            if native is not None:
                native.drain()
                if native.info.pid:
                    result["native_root_pid"] = int(native.info.pid)
                result["native_active_processes_after_drain"] = native.active()
                result["native_drain_proven"] = True
                try:
                    native.close()
                finally:
                    with self.condition:
                        self.jobs.discard(native)
                        self.condition.notify_all()
            for handle in handles:
                _check(k.CloseHandle(handle))
        stdout_path, stderr_path = attempt / "stdout.jsonl", attempt / "stderr.txt"
        if not stdout_path.exists():
            stdout_path.write_bytes(b"")
        if not stderr_path.exists():
            stderr_path.write_bytes(b"")
        if result.get("transport_error"):
            with stderr_path.open("ab") as stream:
                stream.write((result["transport_error"] + "\n").encode("utf-8"))
        stdout = stdout_path.read_bytes()
        result.update(elapsed_seconds=time.perf_counter() - started,
                      removed_session_environment_names=sorted(removed),
                      **event_evidence(stdout.decode("utf-8", errors="replace")))
        return result


def execute(args: list[str], prompt: str, cwd: Path, attempt: Path, timeout: float) -> dict[str, Any]:
    """Callback compatible with the custom driver, only under the active guard."""
    with _ACTIVE_LOCK:
        guard = _ACTIVE_GUARD
    if guard is None:
        raise ValueError("No active sole-custodian global lease")
    return guard.execute(args, prompt, cwd, attempt, timeout)
