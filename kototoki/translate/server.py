"""受管 llama-server：冻结命令行、模型与引擎身份核对、启动前空闲显存轮询、驻留证据校验。

复制自 `experiments/translation_v3/server.py`（`ManagedServer`、`server_command`、`port_free`），
去掉 `GpuLock`（GPU 锁归编排器）与资产清单文件读取（模型路径来自配置，身份核对改用下方冻结常量）；
驻留解析 `residency_evidence`／`validate_residency`／`loader_logs` 复制自 `experiments/translation_demo_runtime.py`，
01 smoke #4 已在 stock b11583 加载日志上验证原解析不需改动；`explicit_oom` 复制自 `translation_demo/run.py`。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.request import ProxyHandler, build_opener

from kototoki.artifacts import atomic_write_json, read_json, sha256_file, utc_now, verify_model

from .procs import list_llama_servers
from .recipes import CONTEXT_SIZE

# APEX-I-Compact 冻结资产身份（`translation_demo/run.py` 的 HY30_ASSET_IDENTITIES 对应行）。
CANDIDATE = "hy-mt2-30b-a3b-apex-i-compact"
MODEL_ASSET = {"repo": "alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF", "revision": "312cce865e03a0718e36cfd1077e6307957aef72",
               "file": "Hy-MT2-30B-A3B-APEX-I-Compact.gguf", "size": 15035838080,
               "sha256": "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a"}
LAYERS = 99
THREADS = 8
THREADS_BATCH = 8
LOAD_TIMEOUT_SECONDS = 180
# 启动前等待的空闲显存（MiB）与超时。01 smoke #4：stock 会话峰值 15653 MiB，桌面基线约 1200 MiB，
# 即 llama-server 自身约 14450 MiB；本机空闲时 free 约 14560 MiB。阈值取 14300：上一 worker 释放完毕即可达到。
MIN_FREE_MIB = 14300
FREE_VRAM_TIMEOUT_SECONDS = 120.0
FREE_VRAM_POLL_SECONDS = 2.0

_OOM = re.compile(r"out of memory|cuda_error_out_of_memory|cudaerrormemoryallocation|vk_error_out_of_device_memory|std::bad_alloc",
                  re.IGNORECASE)


class InfraFailure(RuntimeError):
    """可通过重启 server 重试的基础设施失败（加载期退出／超时、显存不足）。"""


def explicit_oom(message: str) -> bool:
    return bool(_OOM.search(message))


def nvidia_smi(query: str) -> int | None:
    try:
        result = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = result.stdout.split()[0] if result.returncode == 0 and result.stdout.strip() else ""
    return int(first) if first.isdigit() else None


def wait_for_free_vram(min_mib: int = MIN_FREE_MIB, timeout: float = FREE_VRAM_TIMEOUT_SECONDS, *,
                       query: Callable[[], int | None] = lambda: nvidia_smi("memory.free"),
                       sleep: Callable[[float], None] = time.sleep,
                       clock: Callable[[], float] = time.monotonic) -> int:
    """轮询 `nvidia-smi memory.free` 直到不低于阈值；超时抛 `InfraFailure` 并写明最后一次读数。"""
    deadline = clock() + timeout
    while True:
        free = query()
        if free is not None and free >= min_mib:
            return free
        if clock() >= deadline:
            seen = "unknown (nvidia-smi failed)" if free is None else f"{free} MiB"
            raise InfraFailure(f"Free GPU memory {seen} stayed below {min_mib} MiB for {timeout:.0f} s; "
                               "another process may hold the GPU")
        sleep(FREE_VRAM_POLL_SECONDS)


# --- 驻留证据（stock 引擎加载日志） ------------------------------------------------------------

def residency_evidence(log: str) -> dict[str, Any]:
    """从加载日志提取显式的层与 buffer 放置；不把 mmap 当作 CPU 驻留。"""
    offloads = re.findall(r'offloaded (\d+)/(\d+) layers to GPU', log)
    buffers = re.findall(r'load_tensors:\s+(\S+) model buffer size\s*=\s*([\d.]+) MiB', log)
    gpu_buffers = {device: float(size) for device, size in buffers
                   if re.fullmatch(r'(?:CUDA\d+|Vulkan\d+|SYCL\d+|Metal)', device)}
    cpu_buffers = {device: float(size) for device, size in buffers if device.startswith('CPU')}
    loaded, total = map(int, offloads[-1]) if offloads else (None, None)
    return {'gpu_layers_offloaded': loaded, 'model_layers_total': total,
            'layers_not_offloaded': total - loaded if total is not None else None,
            'partial_layer_offload': loaded < total if total is not None else None,
            'gpu_model_buffers_mib': gpu_buffers, 'cpu_model_buffers_mib': cpu_buffers,
            'evidence_source': 'loader-log',
            'buffer_measurement_scope': 'loader allocations/mappings; not process working set or physical CPU residency'}


def validate_residency(evidence: dict[str, Any], requested_layers: int) -> None:
    """缺少 GPU 证据或出现部分层留在 CPU 时拒绝（产品不允许 CPU 回退）。"""
    loaded, total = evidence['gpu_layers_offloaded'], evidence['model_layers_total']
    if loaded is None or total is None or not 0 < loaded <= total:
        raise RuntimeError('Loader did not prove positive GPU layer offload; inspect runtime logs')
    if not any(size > 0 for size in evidence['gpu_model_buffers_mib'].values()):
        raise RuntimeError('Loader did not prove a GPU model buffer; inspect runtime logs')
    if loaded < total:
        raise RuntimeError('Partial GPU offload is not allowed')
    if loaded != min(requested_layers, total):
        raise RuntimeError('Actual GPU layers differ from explicit request; no silent placement fallback is allowed')


def loader_logs(runtime: Path) -> str:
    return '\n'.join(path.read_text(encoding='utf-8', errors='replace')
                     for name in ('server.log', 'stderr.log', 'stdout.log')
                     if (path := runtime / name).exists())


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


def check_model(model: Path, cache_path: Path) -> dict[str, Any]:
    if model.name != MODEL_ASSET["file"]:
        raise ValueError(f"Translation model must be {MODEL_ASSET['file']}, got {model.name}")
    if model.stat().st_size != MODEL_ASSET["size"]:
        raise ValueError(f"Translation model size differs from the frozen asset: {model}")
    return verify_model(model, MODEL_ASSET["sha256"], cache_path)


class ManagedServer:
    """一次 server session：进入时等显存、启动并核对驻留；退出时总是终止进程并记峰值显存。"""

    def __init__(self, runtime_dir: Path, *, engine: Path, model: Path, port: int, model_cache: Path):
        self.runtime_dir, self.engine, self.model, self.port = runtime_dir, engine, model, port
        self.model_cache = model_cache
        self.engine_identity = engine.with_name("identity.json")
        self.url = f"http://127.0.0.1:{port}"
        self.process: subprocess.Popen | None = None
        self.identity: dict[str, Any] = {}
        self._samples: list[int] = []
        self._stop = threading.Event()

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    def _sample_gpu(self) -> None:
        while not self._stop.wait(2.0):
            if (used := nvidia_smi("memory.used")) is not None:
                self._samples.append(used)

    def __enter__(self) -> "ManagedServer":
        if not self.engine.is_file() or not self.engine_identity.is_file():
            raise FileNotFoundError(f"llama-server or its identity.json missing: {self.engine}")
        if not port_free(self.port):
            raise RuntimeError(f"Port {self.port} is occupied (running llama-server pids: {list_llama_servers()}); "
                               "do not share another model server")
        verification = check_model(self.model, self.model_cache)
        free_mib = wait_for_free_vram()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        command = server_command(self.engine, self.model, self.port, self.runtime_dir / "server.log")
        self.identity = {
            "candidate": CANDIDATE, "model_path": str(self.model), "asset": MODEL_ASSET,
            "model_verification": verification, "engine": str(self.engine), "engine_sha256": sha256_file(self.engine),
            "engine_identity": read_json(self.engine_identity),
            "engine_identity_sha256": sha256_file(self.engine_identity),
            "command": command, "free_vram_mib_before_start": free_mib, "started_at_utc": utc_now()}
        opener = build_opener(ProxyHandler({}))
        load_start = time.perf_counter()
        with (self.runtime_dir / "stdout.log").open("wb") as out, (self.runtime_dir / "stderr.log").open("wb") as err:
            self.process = subprocess.Popen(command, stdout=out, stderr=err,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.identity["server_pid"] = self.process.pid
        threading.Thread(target=self._sample_gpu, daemon=True).start()
        try:
            while True:
                if self.process.poll() is not None:
                    oom = " (out of memory)" if explicit_oom(loader_logs(self.runtime_dir)) else ""
                    raise InfraFailure(f"llama-server exited {self.process.returncode} during load{oom}; "
                                       f"see {self.runtime_dir}")
                if time.perf_counter() - load_start > LOAD_TIMEOUT_SECONDS:
                    raise InfraFailure(f"Model load exceeded {LOAD_TIMEOUT_SECONDS} seconds")
                try:
                    with opener.open(self.url + "/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.5)
            self.identity["cold_load_seconds"] = time.perf_counter() - load_start
            with opener.open(self.url + "/props", timeout=10) as response:
                self.identity["props"] = json.loads(response.read())
            residency = residency_evidence(loader_logs(self.runtime_dir))
            self.identity["residency"] = residency
            validate_residency(residency, LAYERS)
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
        self.identity.update(stopped_at_utc=utc_now(),
                             server_exit_code=process.poll() if process else None,
                             peak_device_memory_mib=max(self._samples, default=None))
        if self.runtime_dir.exists():
            atomic_write_json(self.runtime_dir / "engine-final.json", self.identity)
