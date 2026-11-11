"""受管 llama-server（研究侧）：按 `ServerSpec` 组命令行、模型与引擎身份核对、启动前空闲显存轮询、驻留证据校验，
以及补上 `/tokenize`、`/completion` 的本机客户端。

2026-11-11 架构整理票据 05（ADR-0025）从产品 `kototoki/llama_server.py` 原样搬来：产品（ADR-0022 起 names 与翻译都在
Strata 上）不再使用 llama-server 的生命周期，唯一使用者是本包的 `qwen.py`（Q0／Q1 路径）。行为不变；只改了导入来源：
本机客户端、`InfraFailure`、`explicit_oom` 取自产品 `kototoki.local_client`，显存轮询 `nvidia_smi`／`wait_for_free_vram`
取自产品 `kototoki.strata`，`list_llama_servers` 用本包 `procs.py` 的同一实现（产品那份是它的复制）。

更早的来源（2026-10-19 票据 02 从翻译子系统原样抽出）：
- `ManagedServer`、`server_command`、`port_free`、`check_model`、`check_engine` 来自 `kototoki/translate/server.py`，
  其源头是 `experiments/translation_v3/server.py`（去掉 `GpuLock`，GPU 锁归调用方；资产清单改为 spec 里的冻结常量）；
  命令行的固定部分与 `-c`／`-np`／`-ngl` 之后的参数拆进 `ServerSpec.extra_args`。
- 驻留解析 `residency_evidence`／`validate_residency`／`loader_logs` 复制自 `experiments/translation_demo_runtime.py`。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.request import ProxyHandler, build_opener

from kototoki import local_client
from kototoki.artifacts import atomic_write_json, read_json, sha256_file, utc_now, verify_model
from kototoki.local_client import InfraFailure, explicit_oom
from kototoki.strata import nvidia_smi, wait_for_free_vram

from .procs import list_llama_servers

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerSpec:
    """一种模型的 server 配置：资产身份、命令行参数、启动门槛；`stage` 是日志前缀 `[<stage>]`。"""
    stage: str
    candidate: str
    model_asset: dict[str, Any]       # repo／revision／file／size／sha256
    layers: int
    context: int
    extra_args: tuple[str, ...]       # 放在 `-c`／`-np`／`-ngl` 之后、`--no-webui`／`--log-file`／`-lv` 之前
    min_free_mib: int
    load_timeout_s: int


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
    """缺少 GPU 证据或出现部分层留在 CPU 时拒绝（不允许 CPU 回退）。"""
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
    # stderr 不另存：`-lv 4` 下它与 `--log-file` 的 server.log 逐字节相同（2026-10-19 审计 B-14）。
    return '\n'.join(path.read_text(encoding='utf-8', errors='replace')
                     for name in ('server.log', 'stdout.log')
                     if (path := runtime / name).exists())


# --- server -----------------------------------------------------------------------------

def server_command(spec: ServerSpec, engine: Path, model: Path, port: int, log_file: Path) -> list[str]:
    return [str(engine), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
            "-c", str(spec.context), "-np", "1", "-ngl", str(spec.layers), *spec.extra_args,
            "--no-webui", "--log-file", str(log_file), "-lv", "4"]


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def check_model(model: Path, spec: ServerSpec, cache_path: Path) -> dict[str, Any]:
    asset = spec.model_asset
    if model.name != asset["file"]:
        raise ValueError(f"Model for {spec.candidate} must be {asset['file']}, got {model.name}")
    if model.stat().st_size != asset["size"]:
        raise ValueError(f"Model for {spec.candidate}: size differs from the frozen asset: {model}")
    return verify_model(model, asset["sha256"], cache_path)


def check_engine(engine: Path, identity: dict[str, Any], cache_path: Path) -> dict[str, str]:
    """`llama-server.exe` 与同目录全部 DLL 必须等于 `identity.json` 的 `runtime_file_sha256`（size+mtime 缓存）。"""
    expected = identity.get("runtime_file_sha256")
    if not isinstance(expected, dict) or engine.name not in expected:
        raise ValueError(f"{engine.with_name('identity.json')} does not list {engine.name} in runtime_file_sha256")
    files = [engine] + sorted(engine.parent.glob("*.dll"))
    unlisted = [path.name for path in files if path.name not in expected]
    if unlisted:
        raise ValueError(f"Engine directory has files not in identity.json: {unlisted}")
    return {path.name: verify_model(path, expected[path.name], cache_path)["sha256"] for path in files}


class ManagedServer:
    """一次 server session：进入时等显存、启动并核对驻留；退出时总是终止进程并记峰值显存。"""

    def __init__(self, runtime_dir: Path, spec: ServerSpec, *, engine: Path, model: Path, port: int,
                 model_cache: Path, on_pid: Callable[[int | None], None] = lambda pid: None):
        self.runtime_dir, self.spec, self.engine, self.model, self.port = runtime_dir, spec, engine, model, port
        self.model_cache, self.on_pid = model_cache, on_pid
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
        spec, prefix = self.spec, f"[{self.spec.stage}]"
        if not self.engine.is_file() or not self.engine_identity.is_file():
            raise FileNotFoundError(f"llama-server or its identity.json missing: {self.engine}")
        if not port_free(self.port):
            raise RuntimeError(f"Port {self.port} is occupied (running llama-server pids: {list_llama_servers()}); "
                               "do not share another model server")
        engine_identity = read_json(self.engine_identity)
        engine_files = check_engine(self.engine, engine_identity, self.model_cache)
        verification = check_model(self.model, spec, self.model_cache)
        free_mib = wait_for_free_vram(spec.min_free_mib, stage=spec.stage)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        command = server_command(spec, self.engine, self.model, self.port, self.runtime_dir / "server.log")
        self.identity = {
            "candidate": spec.candidate, "model_path": str(self.model), "asset": spec.model_asset,
            "model_verification": verification, "engine": str(self.engine), "engine_sha256": engine_files[self.engine.name],
            "engine_files_verified": len(engine_files), "engine_identity": engine_identity,
            "engine_identity_sha256": sha256_file(self.engine_identity),
            "command": command, "free_vram_mib_before_start": free_mib, "started_at_utc": utc_now()}
        opener = build_opener(ProxyHandler({}))
        load_start = time.perf_counter()
        with (self.runtime_dir / "stdout.log").open("wb") as out:
            self.process = subprocess.Popen(command, stdout=out, stderr=subprocess.DEVNULL,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.identity["server_pid"] = self.process.pid
        self.on_pid(self.process.pid)  # 加载期间 GPU 锁里就有 server pid
        threading.Thread(target=self._sample_gpu, daemon=True).start()
        try:
            while True:
                if self.process.poll() is not None:
                    oom = " (out of memory)" if explicit_oom(loader_logs(self.runtime_dir)) else ""
                    message = f"llama-server exited {self.process.returncode} during load{oom}; see {self.runtime_dir}"
                    log.error(f"{prefix} %s", message)
                    raise InfraFailure(message)
                if time.perf_counter() - load_start > spec.load_timeout_s:
                    message = f"Model load exceeded {spec.load_timeout_s} seconds"
                    log.error(f"{prefix} %s", message)
                    raise InfraFailure(message)
                try:
                    with opener.open(self.url + "/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.5)
            self.identity["cold_load_seconds"] = time.perf_counter() - load_start
            log.info(f"{prefix} llama-server pid %d loaded in %.1f s (free VRAM before start %d MiB)",
                     self.process.pid, self.identity["cold_load_seconds"], free_mib)
            with opener.open(self.url + "/props", timeout=10) as response:
                self.identity["props"] = json.loads(response.read())
            residency = residency_evidence(loader_logs(self.runtime_dir))
            self.identity["residency"] = residency
            validate_residency(residency, spec.layers)
            atomic_write_json(self.runtime_dir / "engine.json", self.identity)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        process = self.process
        stop = None
        if process is not None:
            stop = "exited"  # 进程已自行退出，`server_exit_code` 才是它自己的退出码
            if process.poll() is None:
                process.terminate()
                stop = "terminated"  # Windows 上 terminate() 让退出码固定为 1，不是故障
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    stop = "killed"
            self.on_pid(None)
        self.identity.update(stopped_at_utc=utc_now(),
                             server_exit_code=process.poll() if process else None, server_stop=stop,
                             peak_device_memory_mib=max(self._samples, default=None))
        if self.runtime_dir.exists():
            atomic_write_json(self.runtime_dir / "engine-final.json", self.identity)


# --- client ------------------------------------------------------------------------------

class LlamaClient(local_client.LlamaClient):
    """产品本机客户端加上 llama.cpp 原生的 `/tokenize` 与 `/completion`（产品只用 `chat_completion`）。

    交换目录命名不变：`/tokenize`、`/completion` 是 5 位序号，`chat_completion` 是 `chat-NN`（同一序号计数）。
    """

    def tokenize(self, prompt: str) -> list[int]:
        # 原生提示已含显式 BOS。
        response = self.request("/tokenize", {"content": prompt, "add_special": False, "parse_special": True})
        tokens = response.get("tokens")
        if (not isinstance(tokens, list) or not tokens
                or any(type(token) is not int or token < 0 for token in tokens)):
            raise ValueError("Tokenizer must return nonempty integer token IDs")
        return tokens

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.request("/completion", request)
