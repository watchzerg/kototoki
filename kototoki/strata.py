"""Strata 服务与共享 session：产品唯一的推理服务，names 建表与翻译共用（ADR-0019、ADR-0022）。只有这一个实现，不抽象后端协议。

中间层（与 `local_client` 同层，不属基础层）：起停 Strata 进程（`strata` CLI）、轮询空闲显存（`nvidia_smi`、
`wait_for_free_vram`，ADR-0025 起从原 `llama_server.py` 并入本模块）、核对身份、持有整批共用的 session。
`names` 与翻译子系统都单向依赖本模块；本模块不导入它们。Strata 的身份常量（模型名、版本、引擎 build、默认启动的
解析值）也在这里，翻译配方与建表配方都从这里取值。

一次 `StrataServer` 即一个 session：

- 进入：`strata launch --status` 必须没有任何正在服务的 launch（不抢占别人的 Strata，也不替别人停）；空闲显存
  达到 `MIN_FREE_MIB`（上一个 GPU worker 已退出、显存已释放）；可用内存达到 `MIN_AVAILABLE_RAM_GIB`（等满
  `RAM_WAIT_S` 仍不够只记 WARNING 照常启动）；执行 `strata launch --no-tui --model iq3_s`；轮询到唯一一个
  ready 的 launch 后按 ADR-0017 的接入检查核对身份（版本、端口 8080 本机、run config 的模型／`--max-context 131072`、
  本次启动在服务日志里写下的起草方式为 DFlash2、`/v1/models`、`/v1/status` 原生上下文 131072），不符即停掉并拒绝
  （`StrataRefused`）。

起草方式不从 run config 的参数判断：Strata 总会给引擎传 `--mtp <权重目录>`，DFlash2 由宿主另行加上，研究侧
`probe` 按参数判断会把默认启动认成 MTP（2026-11-08 首次 smoke 实测）。产品改读本次启动写进
`launch-<name>.server.log` 的 `[strata] drafting:` 一行（启动前记下日志长度，只看之后新写的部分）。

专家区：Qwen3.8-Flash-Next IQ3_S 要把 46.84 GiB 专家常驻内存；内存不够时引擎退到 mmap、从 SSD 读专家，答案不变但
读提示与生成都慢约 5 倍（2026-11-08 整片实测）。因此启动前先等可用内存，ready 后从本次启动写进
`<name>.engine.log` 的新内容判断专家区：必须看到 `expert arena: locked`（全部专家锁进内存）且没有退到 mmap 的记录，
否则停掉 Strata 并拒绝（`StrataRefused`，本批不再重试）；结果记进 `strata.json`。
- 退出：只停自己启动的 launch：`strata launch --stop`，再核实 `--status` 为空、空闲显存回到 `MIN_FREE_MIB`；
  核实失败只记 ERROR 与 `strata-final.json`，不抛出（退出路径上不能盖住原异常）。

不加参数的 `strata launch` 只能在终端里走交互向导；子进程里（或带 `--no-tui`）必须点名 `--preset` 或 `--model`，
否则以退出码 2 拒绝。`--model iq3_s` 就是默认选择本身：2026-11-08 本机 `strata launch --plan` 与
`strata launch --no-tui --model iq3_s --plan` 的计划逐行相同，只差前者多一行"未点名模型，按本机选了 IQ3_S"的提示
（ADR-0019）。服务的进程不由本模块持有：`launch` 返回后它在后台运行，`--stop` 才卸载。

运行证据写在 session 目录：`strata.json`（接入时观察到的身份）、`resources.json`（`/v1/status` 采样的整机显存与内存
峰值、服务日志的事件计数）、`strata-final.json`（停止与显存释放的核实结果）。

共享 `Session`（编排器持有，传给 names 与翻译两个阶段）：第一次 `ensure_started()` 才启动 Strata，两阶段之间不停，
`stop()` 后再 `ensure_started()` 即新 session（新的 `session-NN` 目录）；成功的启动不限次数（翻译同调用内最多重启 2 次是
翻译自己的规则），启动失败（`InfraFailure`）整批累计 `MAX_START_FAILURES` 次或被拒绝（`StrataRefused`）即 `unavailable`，
其余需要模型的影片在两个阶段都直接失败。退出上下文时总是 `stop()`。
证据在 `<工作根>/strata-sessions/<UTC戳>-<pid>/session-NN/`。

模块页：docs/architecture/modules/strata-session.md。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from kototoki import artifacts
from kototoki.artifacts import atomic_write_json, utc_now
from kototoki.config import Config
from kototoki.local_client import InfraFailure, LlamaClient

__all__ = [
    "ARENA_LOCKED", "ENGINE_LOG_DIR", "HOST", "LAUNCH_ARGS", "LOG_DIR", "LOG_EVENTS", "MAX_START_FAILURES",
    "MIN_AVAILABLE_RAM_GIB", "MIN_FREE_MIB", "MMAP_MARKERS", "MODEL", "POLL_S", "PORT", "RAM_WAIT_S",
    "SESSIONS_DIR", "STATUS_ARGS", "STOP_ARGS", "STRATA_ENGINE_BUILD", "STRATA_LAUNCH", "STRATA_RESOLVED",
    "STRATA_VERSION", "ResourceSampler", "Session", "StrataRefused", "StrataServer", "available_ram_gib",
    "drafting_from_log", "expert_arena", "http_get", "log_events", "log_sizes", "nvidia_smi", "probe", "read_from",
    "run_cli", "running", "strata_cmd", "wait_for_free_vram",
]

# Strata 服务身份（ADR-0017"服务"一节）：产品用 `strata launch --no-tui --model iq3_s` 启动，`probe` 逐项核对。
# 翻译配方 `q3-translate-v1` 与建表配方 `q3-names-v3` 的运行时身份都取这里的值。
MODEL = "qwen3.8-flash-next-iq3_s"
STRATA_VERSION = "0.2.12"
STRATA_ENGINE_BUILD = "0.1.58"
STRATA_LAUNCH = "default"
STRATA_RESOLVED = {"command": "strata launch", "model": "iq3_s", "context": 131072, "vision": "cpu",
                   "parallel": "fit to the card", "drafting": "dflash2", "access": "local", "tune": "skip",
                   "tuned_args": {}}

PORT = 8080
HOST = "127.0.0.1"
LAUNCH_ARGS = ("launch", "--no-tui", "--model", STRATA_RESOLVED["model"])
STOP_ARGS = ("launch", "--stop")
STATUS_ARGS = ("launch", "--status", "--output", "json")
# Strata 运行时几乎占满整卡（调优实测显存 15.6 GB）；上一个 GPU worker 退出后桌面只占 0.6–1.2 GB。
MIN_FREE_MIB = 14000
# 专家区 46.84 GiB＋分配专家区之前引擎已占的约 4.8 GiB（CPU 上的图片读取器等）＋余量。2026-11-08 实测：启动前可用
# 50.4 GiB，到分配专家区时只剩 45.6 GiB，仍差 1.26 GiB 退到 mmap；2026-11-07 调优时可用 53.6 GiB 放得下。
MIN_AVAILABLE_RAM_GIB = 52.0
RAM_WAIT_S = 180.0
MMAP_MARKERS = ("not enough RAM for the expert arena", "experts via mmap")
ARENA_LOCKED = "expert arena: locked"
LAUNCH_TIMEOUT_S = 900.0   # 加载约 73 s（调优记录）；首次还可能编译／预热
READY_TIMEOUT_S = 300.0
STOP_TIMEOUT_S = 180.0
POLL_S = 2.0
SAMPLE_SECONDS = 5.0
# 服务日志中按会话计数的事件（只计数，不复制日志）：推理循环自救、logits 非有限、单 token 重复截停。
LOG_EVENTS = {"reasoning_recoveries": "repeated reasoning detected", "nonfinite_logits": "logits became non-finite",
              "repeat_stops": "times in a row: ended as"}
SESSIONS_DIR = "strata-sessions"   # 工作根下 session 证据的根（ADR-0022 前为 translate-sessions）
MAX_START_FAILURES = 3              # 整批 Strata 启动失败的上限（与翻译"3 次连续 server_start 即放弃"、names 旧规则"整批 3 次"同量）

FREE_VRAM_TIMEOUT_SECONDS = 120.0
FREE_VRAM_POLL_SECONDS = 2.0
FREE_VRAM_WARN_SECONDS = 30.0  # 等显存超过这么久记一次 warning

log = logging.getLogger(__name__)


def nvidia_smi(query: str) -> int | None:
    try:
        result = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = result.stdout.split()[0] if result.returncode == 0 and result.stdout.strip() else ""
    return int(first) if first.isdigit() else None


def wait_for_free_vram(min_mib: int, timeout: float = FREE_VRAM_TIMEOUT_SECONDS, *, stage: str = "strata",
                       query: Callable[[], int | None] = lambda: nvidia_smi("memory.free"),
                       sleep: Callable[[float], None] = time.sleep,
                       clock: Callable[[], float] = time.monotonic) -> int:
    """轮询 `nvidia-smi memory.free` 直到不低于阈值；超时抛 `InfraFailure` 并写明最后一次读数。

    产品只有 `StrataServer` 调用（`stage="strata"`）；研究侧 `experiments/translation_v3/llama_server.py` 也导入。"""
    started = clock()
    deadline = started + timeout
    warned = False
    while True:
        free = query()
        if free is not None and free >= min_mib:
            return free
        seen = "unknown (nvidia-smi failed)" if free is None else f"{free} MiB"
        if not warned and clock() - started > FREE_VRAM_WARN_SECONDS:
            warned = True
            log.warning("[%s] waiting for free GPU memory: %s < %d MiB after %.0fs", stage, seen, min_mib,
                        clock() - started)
        if clock() >= deadline:
            raise InfraFailure(f"Free GPU memory {seen} stayed below {min_mib} MiB for {timeout:.0f} s; "
                               "another process may hold the GPU")
        sleep(FREE_VRAM_POLL_SECONDS)


class StrataRefused(RuntimeError):
    """Strata 不能用于本批（已有别的 launch 在服务、身份与 ADR-0017 不符、专家区未锁进内存、启动额度用尽）；重启无济于事，不重试。"""


def strata_cmd() -> str:
    """`strata` 在 PATH 上是 PowerShell 脚本，Python 子进程要用安装目录里的 `.cmd`。"""
    path = Path(os.environ.get("LOCALAPPDATA", "")) / "Strata" / "terminal" / "current" / "bin" / "strata.cmd"
    return str(path) if path.is_file() else "strata"


def run_cli(*args: str, timeout: float = 120.0) -> str:
    return subprocess.run([strata_cmd(), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          check=True, timeout=timeout, stdin=subprocess.DEVNULL).stdout


def http_get(url: str, timeout: float = 30.0) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def running(cli: Callable[..., str]) -> list[dict[str, Any]]:
    """`strata launch --status` 里正在服务的 launch（0.2.12 在 JSON 那一行之后还会打印一行给人看的文字）。"""
    return list(json.loads(cli(*STATUS_ARGS).strip().splitlines()[0]).get("running") or [])


def _arg(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


def drafting_from_log(text: str) -> tuple[str | None, str | None]:
    """本次启动的服务日志里最后一行 `[strata] drafting: …` → (起草方式, 原行)；没有这一行为 (None, None)。"""
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("[strata] drafting:")]
    if not lines:
        return None, None
    lower = lines[-1].lower()
    return ("dflash2" if "dflash2" in lower else "mtp" if "mtp" in lower else "off" if "off" in lower else None), lines[-1]


def probe(launch: dict[str, Any], *, cli: Callable[..., str], get: Callable[[str], dict],
          log_text: str) -> dict[str, Any]:
    """按 ADR-0017 核对已 ready 的 launch，返回观察到的值（不含 API key）；不符抛 `StrataRefused`。

    改编自 `experiments/translation_v3/strata.py::probe` 的 `"default"` 分支：不检查 preset 名、不限制并发数；
    起草方式取自本次启动的服务日志 `log_text`（见模块说明）。
    """
    want = STRATA_RESOLVED["context"]
    version = cli("--version").strip()
    if f"strata {STRATA_VERSION} " not in version + " " or f"build {STRATA_ENGINE_BUILD}" not in version:
        raise StrataRefused(f"Strata version differs from {STRATA_VERSION} / build {STRATA_ENGINE_BUILD}: "
                            f"{version!r}")
    if launch.get("port") != PORT or launch.get("host") != HOST:
        raise StrataRefused(f"Strata launch must serve {HOST}:{PORT}, got {launch.get('host')!r}:{launch.get('port')!r}")
    config = json.loads(Path(launch["config"]).read_text(encoding="utf-8-sig")) if launch.get("config") else {}
    args = [str(a) for a in config.get("args") or []]
    drafting, drafting_line = drafting_from_log(log_text)
    if config.get("model_name") != MODEL or _arg(args, "--max-context") != str(want) or drafting != "dflash2":
        raise StrataRefused(f"Strata run config differs from ADR-0017: model {config.get('model_name')!r}, "
                            f"--max-context {_arg(args, '--max-context')!r}, drafting {drafting!r}")
    base = f"http://{HOST}:{PORT}"
    models = [m.get("id") for m in get(base + "/v1/models").get("data", [])]
    if MODEL not in models:
        raise StrataRefused(f"/v1/models does not serve {MODEL}: {models!r}")
    status = get(base + "/v1/status")
    if (status.get("context") or {}).get("native") != want:
        raise StrataRefused(f"/v1/status native context differs from {want}: {status.get('context')!r}")
    return {"version": version, "launch": {k: launch.get(k) for k in ("name", "profile", "state", "port", "host", "pid")},
            "config": {"model_name": config.get("model_name"), "exe": config.get("exe"), "args": args,
                       "host": config.get("host"), "log": config.get("log")},
            "kv": _arg(args, "--kv"), "kv_resident": _arg(args, "--kv-resident"), "spec": _arg(args, "--spec"),
            "drafting": drafting, "drafting_line": drafting_line, "models": models,
            "status": {k: status.get(k) for k in ("model", "engine", "context", "concurrency", "structured_output",
                                                  "vram", "machine")}}


LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Strata" / "runtime"
ENGINE_LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Strata" / "launch"


def log_sizes(log_dir: Path, pattern: str = "launch-*.server.log") -> dict[str, int]:
    """启动前各日志的长度：启动后只读新写的部分（日志跨次追加）。"""
    return {p.name: p.stat().st_size for p in log_dir.glob(pattern)} if log_dir.is_dir() else {}


def available_ram_gib() -> float | None:
    """Windows 的可用物理内存（`GlobalMemoryStatusEx.ullAvailPhys`）；取不到为 None。"""
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    status = Status()
    status.dwLength = ctypes.sizeof(Status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError):
        return None
    return round(status.ullAvailPhys / 2**30, 1)


def expert_arena(engine_text: str) -> str | None:
    """本次启动的引擎日志 → 专家区所在："mmap"（退到从文件读）、"ram"（记有 `expert arena: locked`）、None（两者都没有）。"""
    if any(marker in engine_text for marker in MMAP_MARKERS):
        return "mmap"
    return "ram" if ARENA_LOCKED in engine_text else None


def _first_line(error: BaseException | str) -> str:
    return (str(error).splitlines() or [""])[0][:200]


def read_from(path: Path, offset: int) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read().decode("utf-8", errors="replace")


def log_events(path: Path, offset: int) -> dict[str, int] | None:
    """服务日志在 `offset` 之后那部分里各事件的出现次数（没有日志为 None）。"""
    if not path.is_file():
        return None
    text = read_from(path, offset)
    return {key: text.count(pattern) for key, pattern in LOG_EVENTS.items()}


class ResourceSampler:
    """每隔几秒从 `/v1/status` 取整机显存与内存占用的峰值（是系统总量，不是服务进程自身）。"""

    def __init__(self, url: str, get: Callable[[str], dict], every: float = SAMPLE_SECONDS):
        self.url, self.get, self.every = url, get, every
        self.peak: dict[str, Any] = {"gpu_used_mib": None, "ram_used_gib": None, "samples": 0, "errors": 0}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def sample(self) -> None:
        try:
            machine = self.get(self.url + "/v1/status").get("machine") or {}
        except (URLError, ConnectionError, TimeoutError, ValueError, OSError):
            self.peak["errors"] += 1
            return
        self.peak["samples"] += 1
        for key, value in (("gpu_used_mib", (machine.get("gpu") or {}).get("used_mib")),
                           ("ram_used_gib", (machine.get("ram") or {}).get("used_gib"))):
            if isinstance(value, (int, float)) and (self.peak[key] is None or value > self.peak[key]):
                self.peak[key] = value

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            self.sample()

    def start(self) -> None:
        self.sample()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self.every + 35)


class StrataServer:
    """一个 Strata session：`__enter__` 启动并核对，`__exit__` 停止并核实显存释放。

    `cli`、`get`、`free_vram`、`available_ram`、`sleep`、`clock`、`log_dir`、`engine_log_dir` 是只供测试替换的内部接缝。`on_pid(pid)` 在服务 ready 后以
    `--status` 报告的 pid 回调（报告里没有 pid 时不回调），停止后以 None 回调，供编排器写进 GPU 锁。
    """

    def __init__(self, runtime_dir: Path, *, on_pid: Callable[[int | None], None] = lambda pid: None,
                 cli: Callable[..., str] = run_cli, get: Callable[[str], dict] = http_get,
                 free_vram: Callable[[], int | None] = lambda: nvidia_smi("memory.free"),
                 available_ram: Callable[[], float | None] = available_ram_gib,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 log_dir: Path = LOG_DIR, engine_log_dir: Path = ENGINE_LOG_DIR):
        self.runtime_dir = Path(runtime_dir)
        self.on_pid, self.cli, self.get, self.free_vram = on_pid, cli, get, free_vram
        self.sleep, self.clock, self.log_dir = sleep, clock, Path(log_dir)
        self.available_ram, self.engine_log_dir = available_ram, Path(engine_log_dir)
        self.url = f"http://{HOST}:{PORT}"
        self.identity: dict[str, Any] = {"candidate": MODEL}
        self.launched = False
        self.sampler: ResourceSampler | None = None
        self.log_path: Path | None = None
        self.log_offset = 0

    def _wait_free(self, timeout: float) -> int:
        return wait_for_free_vram(MIN_FREE_MIB, timeout, stage="strata", query=self.free_vram, sleep=self.sleep,
                                  clock=self.clock)

    def _wait_ram(self) -> float | None:
        """等可用内存达到 `MIN_AVAILABLE_RAM_GIB`（上一阶段进程的内存可能还在释放）；等满仍不够记 WARNING 照常启动。"""
        deadline = self.clock() + RAM_WAIT_S
        while True:
            free = self.available_ram()
            if free is None or free >= MIN_AVAILABLE_RAM_GIB:
                return free
            if self.clock() >= deadline:
                log.warning("[strata] only %.1f GiB RAM available after %.0fs (want %.0f GiB): Strata may read its "
                            "experts from the SSD and run several times slower; close other programs",
                            free, RAM_WAIT_S, MIN_AVAILABLE_RAM_GIB)
                return free
            self.sleep(POLL_S)

    def __enter__(self) -> "StrataServer":
        started = self.clock()
        try:
            busy = running(self.cli)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise InfraFailure(f"strata launch --status failed: {type(exc).__name__}: {exc}") from exc
        if busy:
            raise StrataRefused(f"another Strata launch is serving ({[r.get('name') for r in busy]!r}); this run does "
                                "not stop it. Stop it with `strata launch --stop` and run again")
        self.identity["free_vram_mib_before_start"] = self._wait_free(120.0)
        self.identity["available_ram_gib_before_start"] = ram = self._wait_ram()
        log.info("[strata] launching (free VRAM %d MiB, available RAM %s GiB)",
                 self.identity["free_vram_mib_before_start"], "unknown" if ram is None else f"{ram:.1f}")
        self.launched = True
        try:
            sizes = log_sizes(self.log_dir)
            engine_sizes = log_sizes(self.engine_log_dir, "*.engine.log")
            try:
                self.cli(*LAUNCH_ARGS, timeout=LAUNCH_TIMEOUT_S)
            except subprocess.CalledProcessError as exc:
                # Strata 的 stderr 是它自己的说明文字（不含字幕内容），截尾写进消息便于诊断。
                tail = " ".join((exc.stderr or "").split())[-300:]
                raise InfraFailure(f"strata launch exited with {exc.returncode}" + (f": {tail}" if tail else "")
                                   + self._see_log(sizes)) from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise InfraFailure(f"strata launch failed: {type(exc).__name__}: {exc}") from exc
            launch = self._wait_ready(sizes)
            self.log_path = self.log_dir / f"launch-{launch.get('name')}.server.log"
            self.log_offset = sizes.get(self.log_path.name, 0)
            observed = probe(launch, cli=self.cli, get=self.get, log_text=read_from(self.log_path, self.log_offset))
            engine_log = self.engine_log_dir / f"{launch.get('name')}.engine.log"
            observed["expert_arena"] = expert_arena(read_from(engine_log, engine_sizes.get(engine_log.name, 0)))
            self.identity.update(strata=observed, cold_load_seconds=self.clock() - started)
            atomic_write_json(self.runtime_dir / "strata.json", dict(observed, attached_at_utc=utc_now()))
            if observed["expert_arena"] != "ram":
                raise StrataRefused(
                    "Strata did not lock all experts in RAM (expert arena "
                    + ("fell back to mmap, reading experts from the SSD" if observed["expert_arena"] == "mmap"
                       else "not confirmed in the engine log")
                    + f"; see {engine_log}); free RAM (about {MIN_AVAILABLE_RAM_GIB:.0f} GiB available) and run again")
            self.sampler = ResourceSampler(self.url, self.get)
            self.sampler.start()
            log.info("[strata] Strata ready in %.1fs (%s, %s, experts in %s)", self.identity["cold_load_seconds"],
                     observed["launch"].get("name"), observed["drafting"], observed["expert_arena"])
            if type(launch.get("pid")) is int:
                self.on_pid(launch["pid"])
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _see_log(self, sizes: dict[str, int]) -> str:
        """`; see <路径>`：本次启动新写的服务日志（恰好一份时），否则日志目录。"""
        grown = [name for name, size in log_sizes(self.log_dir).items() if sizes.get(name) != size]
        return f"; see {self.log_dir / grown[0] if len(grown) == 1 else self.log_dir}"

    def _wait_ready(self, sizes: dict[str, int]) -> dict[str, Any]:
        deadline = self.clock() + READY_TIMEOUT_S
        last: Any = None
        while True:
            try:
                last = running(self.cli)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            if isinstance(last, list):
                if len(last) > 1:
                    raise StrataRefused(f"expected one Strata launch, got {len(last)}")
                if last and last[0].get("state") == "ready":
                    return last[0]
            if self.clock() >= deadline:
                raise InfraFailure(f"Strata did not become ready within {READY_TIMEOUT_S:.0f} s (last status {last!r})"
                                   + self._see_log(sizes))
            self.sleep(POLL_S)

    def __exit__(self, *exc: Any) -> None:
        if self.sampler is not None:
            self.sampler.stop()
            self.sampler.sample()
            atomic_write_json(self.runtime_dir / "resources.json", dict(
                self.sampler.peak, log_events=None if self.log_path is None else log_events(self.log_path,
                                                                                            self.log_offset),
                server_log=None if self.log_path is None else str(self.log_path), finished_at_utc=utc_now()))
            self.sampler = None
        if not self.launched:
            return
        self.launched = False
        log.info("[strata] stopping")
        final: dict[str, Any] = {"stop": None, "status_empty": None, "free_vram_mib": None, "released": False}
        try:
            self.cli(*STOP_ARGS, timeout=STOP_TIMEOUT_S)
            final["stop"] = "ok"
        except (OSError, subprocess.SubprocessError) as error:
            final["stop"] = f"{type(error).__name__}: {error}"[:500]
        deadline = self.clock() + STOP_TIMEOUT_S
        while True:
            try:
                final["status_empty"] = not running(self.cli)
            except (OSError, subprocess.SubprocessError, ValueError):
                final["status_empty"] = None
            if final["status_empty"] or self.clock() >= deadline:
                break
            self.sleep(POLL_S)
        try:
            final["free_vram_mib"] = self._wait_free(STOP_TIMEOUT_S)
            final["released"] = bool(final["status_empty"])
        except InfraFailure as error:
            final["error"] = str(error)
        final["stopped_at_utc"] = utc_now()
        try:
            atomic_write_json(self.runtime_dir / "strata-final.json", final)
        except OSError:
            pass
        if final["released"]:
            log.info("[strata] Strata stopped; %s MiB GPU memory free", final["free_vram_mib"])
        else:
            log.error("[strata] Strata stop not confirmed (stop %s, status empty %s, free %s MiB); "
                      "check `strata launch --status` and nvidia-smi; see %s", final["stop"], final["status_empty"],
                      final["free_vram_mib"], self.runtime_dir / "strata-final.json")
        self.on_pid(None)


class Session:
    """整批共用的 Strata 生命周期（names 建表与翻译同一个）：首次需要时才启动，`stop` 后再 `ensure_started` 即新 session。

    `on_server_pid(pid)` 在服务 ready 后以 pid、停止后以 None 回调，供编排器写进 GPU 锁。启动失败（`InfraFailure`）整批累计
    `MAX_START_FAILURES` 次，或 Strata 被拒绝（`StrataRefused`），即 `unavailable`，此后 `ensure_started` 直接抛 `StrataRefused`，
    调用方不再等待。`unavailable` 只由本类写，调用方只读。names 与翻译经 `label`（当前 session 名）与
    `client(trace_dir, timeout=…)`（对运行中的服务建客户端）使用本类，不碰 `ordinal`、`runtime_root`、`client_factory`。
    `server_factory`／`client_factory` 是只供测试的内部接缝（伪服务须有 `url`、`identity` 与上下文管理器协议；
    伪客户端替换 `LlamaClient`，只经 `client()` 生效）。
    """

    def __init__(self, config: Config, *, on_server_pid: Callable[[int | None], None] | None = None,
                 server_factory: Callable[[Path, Callable[[int | None], None]], Any] | None = None,
                 client_factory: Callable[..., Any] = LlamaClient):
        self.config = config
        self.on_server_pid = on_server_pid or (lambda pid: None)
        self.server_factory = server_factory or self._managed_server
        self.client_factory = client_factory
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())  # UTC，与运行日志 `run-<戳>.log` 同一时间基准
        self.runtime_root = (artifacts.work_root(config.paths.work_dir, config.paths.input_dir) / SESSIONS_DIR
                             / f"{stamp}-{os.getpid()}")
        self.server: Any = None
        self.ordinal = 0      # 尝试启动的次数（也是 `session-NN` 目录的序号），含失败的启动
        self.start_failures = 0
        # 被拒绝或启动额度用尽后，本批其余需要模型的影片不再等待，直接失败。
        self.unavailable: str | None = None

    @staticmethod
    def _managed_server(runtime_dir: Path, on_pid: Callable[[int | None], None]) -> StrataServer:
        return StrataServer(runtime_dir, on_pid=on_pid)

    @property
    def label(self) -> str:
        """当前 session 名 `<runtime_root.name>/session-NN`（NN 为最近一次尝试启动的序号）：翻译记进 `run.json` 的
        `server_session`，names 用作交换目录的相对路径。"""
        return f"{self.runtime_root.name}/session-{self.ordinal:02d}"

    def client(self, trace_dir: Path, *, timeout: float) -> Any:
        """对运行中的服务建本机客户端，逐请求 trace 写进调用方给的 `trace_dir`；须先 `ensure_started()`。"""
        if self.server is None:
            raise RuntimeError("Session.client() needs a running Strata; call ensure_started() first")
        return self.client_factory(self.server.url, timeout=timeout, trace_dir=trace_dir)

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def ensure_started(self) -> Any:
        """运行中的服务（没有就启动）。启动失败（`InfraFailure`）由调用方决定是否再试，整批累计 `MAX_START_FAILURES` 次即
        `unavailable`；`StrataRefused` 立即置 `unavailable`。"""
        if self.unavailable is not None:
            raise StrataRefused(f"Strata is unavailable for the rest of this batch: {self.unavailable}")
        if self.server is None:
            self.ordinal += 1
            server = self.server_factory(self.runtime_root / f"session-{self.ordinal:02d}", self.on_server_pid)
            try:
                server.__enter__()  # ready 后以 pid 回调；启动或核对失败时自行停掉并以 None 回调
            except StrataRefused as exc:
                self.unavailable = str(exc)
                log.error("[strata] unavailable for the rest of this batch: %s", _first_line(exc))
                raise
            except InfraFailure as exc:
                self.start_failures += 1
                log.warning("[strata] start failed %d/%d: %s", self.start_failures, MAX_START_FAILURES,
                            _first_line(exc))
                if self.start_failures >= MAX_START_FAILURES:
                    self.unavailable = (f"Strata failed to start {self.start_failures} times in this batch "
                                        f"(start budget exhausted): {exc}")
                    log.error("[strata] unavailable for the rest of this batch: %s", _first_line(self.unavailable))
                raise
            self.server = server
        return self.server

    def stop(self) -> None:
        server, self.server = self.server, None
        if server is not None:
            server.__exit__(None, None, None)  # 停止并核实显存释放后以 None 回调
