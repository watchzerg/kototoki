"""Managed llama-server lifecycle with the frozen C0 command line, GPU lock and model check.

The command line reproduces ``experiments/translation_demo_runtime.py`` for the
adopted baseline (APEX, compat engine, 99 layers, ctx 8192, single slot, f16 KV,
threads 8/8, batch 256/ubatch 128, flash on, fit off, prompt cache RAM 8192).
Residency parsing/validation is imported from that module unchanged. The server
is placed in a KILL_ON_JOB_CLOSE Job Object so a hard-killed Python takes it down.
"""

from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.request import ProxyHandler, build_opener

from .common import (CANDIDATE, ENGINE, ENGINE_IDENTITY, EXPECTED_MODEL_SHA256, GPU_LOCK, REPO,
                     atomic_write_json, read_json, sha256_file, utc_now)
from .procs import KillOnCloseJob, LockError, ProcessLock, pid_alive, process_created, process_matches  # noqa: F401
from .recipes import CONTEXT_SIZE

LAYERS = 99
THREADS = 8
THREADS_BATCH = 8
LOAD_TIMEOUT_SECONDS = 180


class GpuLock(ProcessLock):
    """`.local/gpu.lock` with owner pid + creation time, run id, and (once started) server pid + creation time."""

    kind = "GPU lock"

    def __init__(self, run_id: str, path: Path = GPU_LOCK, **kwargs: Any):
        super().__init__(path, {"run_id": run_id}, **kwargs)
        self.run_id = run_id

    def stale_message(self, data: dict[str, Any]) -> str:
        return (f"Stale GPU lock from dead pid {data.get('pid')} (run {data.get('run_id')}, created "
                f"{data.get('created_at_utc')}); verify no GPU job or orphan llama-server runs, then rerun with --break-stale-lock")


# --- model asset ------------------------------------------------------------------------

def resolve_model() -> tuple[Path, dict[str, Any], list[Path]]:
    from experiments.translation_demo.run import asset_manifest_paths, load_assets, select_asset
    paths = asset_manifest_paths(None, REPO)
    asset = select_asset(load_assets(paths), CANDIDATE)
    if asset["sha256"] != EXPECTED_MODEL_SHA256:
        raise ValueError("Asset manifest SHA256 differs from the adopted APEX identity")
    return Path(asset["directory"]) / asset["file"], asset, paths


def verify_model(path: Path, expected: str, cache_path: Path, *, hasher: Callable[[Path], str] = sha256_file) -> dict[str, Any]:
    """Full SHA256 before load; reuse a recorded result while size+mtime are unchanged."""
    stat = path.stat()
    key = {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    cache = read_json(cache_path) if cache_path.is_file() else {}
    entry = cache.get(key["path"])
    if entry and entry.get("size") == key["size"] and entry.get("mtime_ns") == key["mtime_ns"] and entry.get("sha256") == expected:
        return {**key, "sha256": expected, "method": "cached-size-mtime", "verified_at_utc": entry["verified_at_utc"]}
    started = time.perf_counter()
    digest = hasher(path)
    if digest != expected:
        raise ValueError(f"Model SHA256 mismatch: {digest} != {expected}")
    record = {**key, "sha256": digest, "verified_at_utc": utc_now(), "seconds": time.perf_counter() - started}
    cache[key["path"]] = record
    atomic_write_json(cache_path, cache)
    return {**record, "method": "computed"}


# --- server -----------------------------------------------------------------------------

def server_command(engine: Path, model: Path, port: int, log_file: Path) -> list[str]:
    return [str(engine), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
            "-c", str(CONTEXT_SIZE), "-np", "1", "-ngl", str(LAYERS), "-b", "256", "-ub", "128",
            "-t", str(THREADS), "-tb", str(THREADS_BATCH), "-ctk", "f16", "-ctv", "f16", "--cache-ram", "8192",
            "-fa", "on", "--fit", "off", "--no-webui", "--log-file", str(log_file), "-lv", "4"]


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


class ManagedServer:
    """Fresh server per generation session; always terminated on exit."""

    def __init__(self, runtime_dir: Path, *, port: int = 8080, root: Path, engine: Path = ENGINE,
                 engine_identity: Path = ENGINE_IDENTITY):
        self.runtime_dir, self.port, self.root = runtime_dir, port, root
        self.engine, self.engine_identity = engine, engine_identity
        self.url = f"http://127.0.0.1:{port}"
        self.process: subprocess.Popen | None = None
        self.job: KillOnCloseJob | None = None
        self.identity: dict[str, Any] = {}
        self._samples: list[int] = []
        self._stop = threading.Event()

    def _sample_gpu(self) -> None:
        while not self._stop.wait(2.0):
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                        capture_output=True, text=True, timeout=10,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode == 0 and result.stdout.strip():
                    self._samples.append(int(result.stdout.split()[0]))
            except Exception:
                pass

    def __enter__(self) -> "ManagedServer":
        from experiments.translation_demo_runtime import loader_logs, residency_evidence, validate_residency
        if not self.engine.is_file() or not self.engine_identity.is_file():
            raise FileNotFoundError(f"Compat engine or identity missing: {self.engine}")
        if not port_free(self.port):
            raise RuntimeError(f"Port {self.port} is occupied; do not share another model server")
        model, asset, manifests = resolve_model()
        verification = verify_model(model, asset["sha256"], self.root / "cache/model-verification.json")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        command = server_command(self.engine, model, self.port, self.runtime_dir / "server.log")
        self.identity = {
            "candidate": CANDIDATE, "model_path": str(model), "asset": asset, "model_verification": verification,
            "asset_manifests": [{"path": str(p), "sha256": sha256_file(p)} for p in manifests],
            "engine": str(self.engine), "engine_sha256": sha256_file(self.engine),
            "engine_identity": read_json(self.engine_identity),
            "engine_identity_sha256": sha256_file(self.engine_identity),
            "command": command, "started_at_utc": utc_now()}
        opener = build_opener(ProxyHandler({}))
        load_start = time.perf_counter()
        self.job = KillOnCloseJob()
        with (self.runtime_dir / "stdout.log").open("wb") as out, (self.runtime_dir / "stderr.log").open("wb") as err:
            self.process = subprocess.Popen(command, stdout=out, stderr=err,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.identity.update(server_pid=self.process.pid, server_created=process_created(self.process.pid))
        try:
            self.identity["kill_on_job_close"] = self.job.assign(self.process)
        except OSError:
            self.__exit__(None, None, None)
            raise
        threading.Thread(target=self._sample_gpu, daemon=True).start()
        try:
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError(f"llama-server exited {self.process.returncode}; see {self.runtime_dir}")
                if time.perf_counter() - load_start > LOAD_TIMEOUT_SECONDS:
                    raise TimeoutError("Model load exceeded 180 seconds")
                try:
                    with opener.open(self.url + "/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.5)
            self.identity["cold_load_seconds"] = time.perf_counter() - load_start
            with opener.open(self.url + "/props", timeout=10) as response:
                props = json.loads(response.read())
            self.identity["props"] = props
            residency = residency_evidence(loader_logs(self.runtime_dir))
            self.identity["residency"] = residency
            validate_residency(residency, LAYERS, False)
            atomic_write_json(self.runtime_dir / "engine.json", self.identity)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if getattr(self, "job", None) is not None:
            self.job.close()
        self.identity.update(stopped_at_utc=utc_now(),
                             server_exit_code=process.poll() if process else None,
                             peak_device_memory_mib=max(self._samples, default=None))
        if self.runtime_dir.exists():
            atomic_write_json(self.runtime_dir / "engine-final.json", self.identity)
