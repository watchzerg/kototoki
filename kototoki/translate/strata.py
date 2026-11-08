"""Strata 服务：由产品自动启停的翻译后端（ADR-0019）。只有这一个实现，不抽象后端协议。

一次 `StrataServer` 即一个 session：

- 进入：`strata launch --status` 必须没有任何正在服务的 launch（不抢占别人的 Strata，也不替别人停）；空闲显存
  达到 `MIN_FREE_MIB`（names 的 llama-server 已停、显存已释放）；可用内存达到 `MIN_AVAILABLE_RAM_GIB`（等满
  `RAM_WAIT_S` 仍不够只记 WARNING 照常启动）；执行 `strata launch --no-tui --model iq3_s`；轮询到唯一一个
  ready 的 launch 后按 ADR-0017 的接入检查核对身份（版本、端口 8080 本机、run config 的模型／`--max-context 131072`、
  本次启动在服务日志里写下的起草方式为 DFlash2、`/v1/models`、`/v1/status` 原生上下文 131072），不符即停掉并拒绝
  （`StrataRefused`）。

起草方式不从 run config 的参数判断：Strata 总会给引擎传 `--mtp <权重目录>`，DFlash2 由宿主另行加上，研究侧
`probe` 按参数判断会把默认启动认成 MTP（2026-11-08 首次 smoke 实测）。产品改读本次启动写进
`launch-<name>.server.log` 的 `[strata] drafting:` 一行（启动前记下日志长度，只看之后新写的部分）。

专家区：Qwen3.8-Flash-Next IQ3_S 要把 46.84 GiB 专家常驻内存；内存不够时引擎退到 mmap、从 SSD 读专家，答案不变但
读提示与生成都慢约 5 倍（2026-11-08 整片实测）。因此启动前先等可用内存，ready 后从本次启动写进
`<name>.engine.log` 的新内容判断专家区在内存还是退到 mmap，记进 `strata.json`；退到 mmap 只记 WARNING、不拒绝。
- 退出：只停自己启动的 launch：`strata launch --stop`，再核实 `--status` 为空、空闲显存回到 `MIN_FREE_MIB`；
  核实失败只记 ERROR 与 `strata-final.json`，不抛出（退出路径上不能盖住原异常）。

不加参数的 `strata launch` 只能在终端里走交互向导；子进程里（或带 `--no-tui`）必须点名 `--preset` 或 `--model`，
否则以退出码 2 拒绝。`--model iq3_s` 就是默认选择本身：2026-11-08 本机 `strata launch --plan` 与
`strata launch --no-tui --model iq3_s --plan` 的计划逐行相同，只差前者多一行"未点名模型，按本机选了 IQ3_S"的提示
（ADR-0019）。服务的进程不由本模块持有：`launch` 返回后它在后台运行，`--stop` 才卸载。

运行证据写在 session 目录：`strata.json`（接入时观察到的身份）、`resources.json`（`/v1/status` 采样的整机显存与内存
峰值、服务日志的事件计数）、`strata-final.json`（停止与显存释放的核实结果）。
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

from kototoki.artifacts import atomic_write_json, utc_now
from kototoki.llama_server import InfraFailure, nvidia_smi, wait_for_free_vram

from . import recipes as R

PORT = 8080
HOST = "127.0.0.1"
LAUNCH_ARGS = ("launch", "--no-tui", "--model", R.STRATA_RESOLVED["model"])
STOP_ARGS = ("launch", "--stop")
STATUS_ARGS = ("launch", "--status", "--output", "json")
# Strata 运行时几乎占满整卡（调优实测显存 15.6 GB）；names 的 llama-server 停掉后桌面只占 0.6–1.2 GB。
MIN_FREE_MIB = 14000
# 专家区 46.84 GiB＋分配专家区之前引擎已占的约 4.8 GiB（CPU 上的图片读取器等）＋余量。2026-11-08 实测：启动前可用
# 50.4 GiB，到分配专家区时只剩 45.6 GiB，仍差 1.26 GiB 退到 mmap；2026-11-07 调优时可用 53.6 GiB 放得下。
MIN_AVAILABLE_RAM_GIB = 52.0
RAM_WAIT_S = 180.0
MMAP_MARKERS = ("not enough RAM for the expert arena", "experts via mmap")
LAUNCH_TIMEOUT_S = 900.0   # 加载约 73 s（调优记录）；首次还可能编译／预热
READY_TIMEOUT_S = 300.0
STOP_TIMEOUT_S = 180.0
POLL_S = 2.0
SAMPLE_SECONDS = 5.0
# 服务日志中按会话计数的事件（只计数，不复制日志）：推理循环自救、logits 非有限、单 token 重复截停。
LOG_EVENTS = {"reasoning_recoveries": "repeated reasoning detected", "nonfinite_logits": "logits became non-finite",
              "repeat_stops": "times in a row: ended as"}

log = logging.getLogger(__name__)


class StrataRefused(RuntimeError):
    """Strata 不能用于本次翻译（已有别的 launch 在服务、身份与 ADR-0017 不符）；重启无济于事，不重试。"""


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
    want = R.STRATA_RESOLVED["context"]
    version = cli("--version").strip()
    if f"strata {R.STRATA_VERSION} " not in version + " " or f"build {R.STRATA_ENGINE_BUILD}" not in version:
        raise StrataRefused(f"Strata version differs from {R.STRATA_VERSION} / build {R.STRATA_ENGINE_BUILD}: "
                            f"{version!r}")
    if launch.get("port") != PORT or launch.get("host") != HOST:
        raise StrataRefused(f"Strata launch must serve {HOST}:{PORT}, got {launch.get('host')!r}:{launch.get('port')!r}")
    config = json.loads(Path(launch["config"]).read_text(encoding="utf-8-sig")) if launch.get("config") else {}
    args = [str(a) for a in config.get("args") or []]
    drafting, drafting_line = drafting_from_log(log_text)
    if config.get("model_name") != R.MODEL or _arg(args, "--max-context") != str(want) or drafting != "dflash2":
        raise StrataRefused(f"Strata run config differs from ADR-0017: model {config.get('model_name')!r}, "
                            f"--max-context {_arg(args, '--max-context')!r}, drafting {drafting!r}")
    base = f"http://{HOST}:{PORT}"
    models = [m.get("id") for m in get(base + "/v1/models").get("data", [])]
    if R.MODEL not in models:
        raise StrataRefused(f"/v1/models does not serve {R.MODEL}: {models!r}")
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
    """本次启动的引擎日志 → 专家区所在："mmap"（退到从文件读）、"ram"（有引擎日志且没有退化记录）、None（没有日志）。"""
    if not engine_text.strip():
        return None
    return "mmap" if any(marker in engine_text for marker in MMAP_MARKERS) else "ram"


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
        self.identity: dict[str, Any] = {"candidate": R.MODEL}
        self.launched = False
        self.sampler: ResourceSampler | None = None
        self.log_path: Path | None = None
        self.log_offset = 0

    def _wait_free(self, timeout: float) -> int:
        return wait_for_free_vram(MIN_FREE_MIB, timeout, stage="translate", query=self.free_vram, sleep=self.sleep,
                                  clock=self.clock)

    def _wait_ram(self) -> float | None:
        """等可用内存达到 `MIN_AVAILABLE_RAM_GIB`（建表进程的内存可能还在释放）；等满仍不够记 WARNING 照常启动。"""
        deadline = self.clock() + RAM_WAIT_S
        while True:
            free = self.available_ram()
            if free is None or free >= MIN_AVAILABLE_RAM_GIB:
                return free
            if self.clock() >= deadline:
                log.warning("[translate] only %.1f GiB RAM available after %.0f s (want %.0f GiB): Strata may read its "
                            "experts from the SSD and translate several times slower; close other programs",
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
        self.identity["available_ram_gib_before_start"] = self._wait_ram()
        self.launched = True
        try:
            sizes = log_sizes(self.log_dir)
            engine_sizes = log_sizes(self.engine_log_dir, "*.engine.log")
            try:
                self.cli(*LAUNCH_ARGS, timeout=LAUNCH_TIMEOUT_S)
            except subprocess.CalledProcessError as exc:
                # Strata 的 stderr 是它自己的说明文字（不含字幕内容），截尾写进消息便于诊断。
                tail = " ".join((exc.stderr or "").split())[-300:]
                raise InfraFailure(f"strata launch exited with {exc.returncode}" + (f": {tail}" if tail else "")) from exc
            except (OSError, subprocess.SubprocessError) as exc:
                raise InfraFailure(f"strata launch failed: {type(exc).__name__}: {exc}") from exc
            launch = self._wait_ready()
            self.log_path = self.log_dir / f"launch-{launch.get('name')}.server.log"
            self.log_offset = sizes.get(self.log_path.name, 0)
            observed = probe(launch, cli=self.cli, get=self.get, log_text=read_from(self.log_path, self.log_offset))
            engine_log = self.engine_log_dir / f"{launch.get('name')}.engine.log"
            observed["expert_arena"] = expert_arena(read_from(engine_log, engine_sizes.get(engine_log.name, 0)))
            if observed["expert_arena"] == "mmap":
                log.warning("[translate] Strata did not fit its experts in RAM and reads them from the SSD "
                            "(see %s); translation will be several times slower. Free RAM and run again", engine_log)
            self.identity.update(strata=observed, cold_load_seconds=self.clock() - started)
            atomic_write_json(self.runtime_dir / "strata.json", dict(observed, attached_at_utc=utc_now()))
            self.sampler = ResourceSampler(self.url, self.get)
            self.sampler.start()
            log.info("[translate] Strata ready in %.1f s (%s, %s, experts in %s)", self.identity["cold_load_seconds"],
                     observed["launch"].get("name"), observed["drafting"], observed["expert_arena"])
            if type(launch.get("pid")) is int:
                self.on_pid(launch["pid"])
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _wait_ready(self) -> dict[str, Any]:
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
                raise InfraFailure(f"Strata did not become ready within {READY_TIMEOUT_S:.0f} s (last status {last!r})")
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
            log.info("[translate] Strata stopped; %s MiB GPU memory free", final["free_vram_mib"])
        else:
            log.error("[translate] Strata stop not confirmed (stop %s, status empty %s, free %s MiB); "
                      "check `strata launch --status` and nvidia-smi", final["stop"], final["status_empty"],
                      final["free_vram_mib"])
        self.on_pid(None)
