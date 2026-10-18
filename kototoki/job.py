"""批次编排：扫描、CPU 阶段、GPU 阶段子进程、ja-cues、翻译、一起发布（规格 §3、§4、§6、§7.1）。

对外只有 `run(config) -> Summary`。流程按"阶段 × 整批"推进::

    扫描（大小采样稳定性、镜像、短 id、发布前置判定）
    → probe/extract（线程池，整批完成）
    → vad → asr → align（各一个子进程 worker，`--jobs` 文件 + 退出码）
    → ja-cues（进程内）→ translate（进程内，整批一个 session；翻译子系统的计划说要模型时才取 GPU 锁、建 session）
    → 三份 SRT 一起发布

阶段链、期望身份与"下一个要跑的阶段"归阶段计划模块 `kototoki.plan`：CPU 阶段之后每文件算一次 `next_stage`，
某阶段跑完再 `advance` 继续核对；产物存在且身份匹配即跳过，因此中断后重跑同一命令即续跑。GPU 阶段产物
（`vad.json`、`asr.json`、`align.json`）由 worker 写出；CPU 阶段产物（`probe.json`、`ja-cues.json`）由本模块
写出。模型文件 SHA256 的核对（size+mtime 缓存，每次运行每阶段最多一次）在本模块经 `workers/gpu.verify_models`
完成。本模块不做任何时间换算，不导入任何推理模块（有测试守门）。

锁：启动即取 `<output_dir>/.work/lock`；第一个需要 GPU 的阶段前取 `.local/gpu.lock`，持有到翻译结束，
锁文件记录编排器、当前 worker 与 llama-server 的 pid。破除死锁只认 `KOTOTOKI_BREAK_STALE_LOCK=1`。
锁、Job Object 与进程身份取自 `experiments/translation_v3/procs.py`（复制，不导入）。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
import concurrent.futures
import contextlib
import ctypes
from dataclasses import asdict, dataclass, field
import importlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any, TextIO

from kototoki import artifacts, cues, media, plan, srt
from kototoki.config import REPO_ROOT, Config
from kototoki.logs import RunFormatter
from kototoki.plan import GPU_STAGES, JA_SRT, ModelSha, Plan, PlanError

if TYPE_CHECKING:  # 翻译子系统运行时才以 importlib 导入
    from kototoki.translate import TranslatePlan
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs, write_jobs

EXIT_OK = 0
EXIT_FAILED = 1           # 有文件在某阶段失败；其余文件照常发布
EXIT_CONFIG = 2           # 配置文件或输出目录不可用（__main__）
EXIT_OUTPUT_LOCKED = 3    # 同一输出目录已有编排器在运行
EXIT_GPU_LOCKED = 4       # `.local/gpu.lock` 被其他作业持有或残留

PUBLISH_DIR = "publish"    # 三份最终 SRT 的暂存目录（工作目录内），写完后一起移动到最终位置

# worker 子进程的离线环境（沿用 experiments setup_runtime 的变量，不加私有 DLL 目录）。
OFFLINE_ENV = {"PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
               "HF_HUB_DISABLE_TELEMETRY": "1", "PYANNOTE_METRICS_ENABLED": "0"}
# worker stderr 只留日志行：关掉 tqdm／HF 下载进度条，transformers 只报 warning 及以上。
QUIET_ENV = {"TQDM_DISABLE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1", "TRANSFORMERS_VERBOSITY": "warning"}


class OutputLocked(RuntimeError):
    """同一输出目录已有编排器（或残留锁）。"""


class GpuLocked(RuntimeError):
    """`.local/gpu.lock` 被其他作业持有或残留。"""


class WorkerCrashed(RuntimeError):
    """worker 在处理该文件时异常退出（未写出结果也未报告失败）。"""


class ArtifactMissing(RuntimeError):
    """worker 正常结束但该文件的产物缺失或身份不符。"""


class FinalPathCollision(RuntimeError):
    """同目录另一个视频（主名相同、扩展名不同）已占用同一组最终 SRT 路径。"""


# 提取补偿（`probe.json` 的 `extract.compensation`）超过这么多秒时记 WARNING：净补入／丢弃与 swr 报告的丢弃样本。
COMPENSATION_WARN_S = 0.1


# --- 进程身份、Job Object 与文件锁（取自 translation_v3/procs.py） --------------------------------

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
    """把编排器进程放进 KILL_ON_JOB_CLOSE Job Object；之后启动的 ffmpeg、worker 与 llama-server 自动加入。

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


# --- 运行日志 -----------------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# worker stderr 里按 `kototoki.logs.LOG_FORMAT` 写出的告警／错误行；tqdm、裸 traceback 等其他行不计。
_STDERR_PROBLEM = re.compile(rb"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z \[ *[0-9.]+s\] (?:WARNING|ERROR|CRITICAL) ",
                             re.MULTILINE)


@contextlib.contextmanager
def _run_logging(path: Path, console: TextIO | None = None) -> Iterator[None]:
    """`run` 期间把日志写到控制台与 `.work/run-<时间戳>.log`（内容相同，INFO 及以上）；退出时摘下并关闭 handler。

    handler 挂在 root logger 上，第三方库的告警也进同一文件；`kototoki` logger 临时放到 INFO。
    只有进度、计数与耗时，不写转写与译文。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = RunFormatter(time.time())
    root, ours = logging.getLogger(), logging.getLogger("kototoki")
    level = ours.level
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        handlers = [logging.StreamHandler(stream),
                    logging.StreamHandler(console if console is not None else sys.stdout)]
        for handler in handlers:
            handler.setLevel(logging.INFO)
            handler.setFormatter(formatter)
            root.addHandler(handler)
        ours.setLevel(logging.INFO)
        try:
            yield
        finally:
            ours.setLevel(level)
            for handler in handlers:
                root.removeHandler(handler)
                handler.close()


def _count_stderr_problems(data: bytes) -> int:
    """worker stderr 片段里级别为 WARNING／ERROR（及 CRITICAL）的日志行数。"""
    return len(_STDERR_PROBLEM.findall(data))


# --- 文件状态与汇总 ------------------------------------------------------------------------------

@dataclass
class VideoFile:
    relative: str                 # 输入目录内相对路径（正斜杠）
    path: Path
    work_dir: Path
    finals: dict[str, Path]
    probe: media.Probe | None = None
    probe_identity: dict[str, Any] | None = None
    pcm_sha256: str | None = None
    plan: Plan | None = None      # CPU 阶段之后由阶段计划模块给出，某阶段跑完后推进
    failed: str | None = None     # 本次运行中失败的阶段

    def target(self) -> plan.Target:
        assert self.probe_identity is not None and self.pcm_sha256 is not None
        return plan.Target(self.work_dir, self.finals, self.probe_identity, self.pcm_sha256)

    @property
    def no_speech(self) -> bool:
        return self.plan is not None and self.plan.no_speech

    @property
    def translate_plan(self) -> TranslatePlan:
        """核对到翻译阶段之后才存在（`plan.stage` 为 translate／publish／done 且有 cue）。"""
        assert self.plan is not None and self.plan.translate is not None
        return self.plan.translate


@dataclass
class Summary:
    total: int = 0                                         # 扫描到的视频数
    published: list[str] = field(default_factory=list)     # 本次发布
    up_to_date: list[str] = field(default_factory=list)    # 已发布且身份匹配，跳过
    blocked: list[str] = field(default_factory=list)       # 最终文件被用户改动且 force=false，跳过
    unstable: list[str] = field(default_factory=list)      # 大小仍在变化（写入中），跳过
    no_speech: list[str] = field(default_factory=list)     # VAD 为空，发布零条目 SRT
    failed: dict[str, str] = field(default_factory=dict)   # 相对路径 → 失败阶段
    fallback_cues: int = 0                                 # 译文回退为日文的 cue 数

    @property
    def exit_code(self) -> int:
        return EXIT_FAILED if self.failed else EXIT_OK


# --- 扫描 ---------------------------------------------------------------------------------------

def scan(input_dir: Path, extensions: Iterable[str]) -> list[tuple[str, Path]]:
    """递归列出扩展名匹配的文件，按相对路径排序。"""
    wanted = {ext.lower() for ext in extensions}
    found = [(path.relative_to(input_dir).as_posix(), path) for path in input_dir.rglob("*")
             if path.suffix.lower() in wanted and path.is_file()]
    return sorted(found)


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def stable_files(files: list[tuple[str, Path]], interval_s: float,
                 sleep: Callable[[float], None]) -> tuple[list[tuple[str, Path]], list[str]]:
    """两次采样（间隔 `interval_s`）大小不变才视为写入完成；不看 mtime（拷贝工具常保留源 mtime）。"""
    first = {rel: _size(path) for rel, path in files}
    if files and interval_s > 0:
        sleep(interval_s)
    stable, unstable = [], []
    for rel, path in files:
        size = _size(path)
        (stable if size is not None and size == first[rel] else unstable).append((rel, path))
    return stable, [rel for rel, _ in unstable]


# --- 翻译与合并的延迟导入、模型核对 ----------------------------------------------------------------

def _translate_module() -> Any:
    return importlib.import_module("kototoki.translate")


def _merge_module() -> Any:
    return importlib.import_module("kototoki.merge")


def model_sha_lookup(config: Config) -> ModelSha:
    """按阶段核对 worker 用到的模型文件 SHA256（size+mtime 缓存与 worker 共用），每次运行每阶段最多一次。"""
    models = plan.worker_models(config)
    cache_path = artifacts.model_cache_path(config.paths.output_dir)
    done: dict[str, Mapping[str, str]] = {}

    def lookup(stage: str) -> Mapping[str, str]:
        if stage not in done:
            done[stage] = gpu.verify_models(plan.model_files(stage, models, engine=config.engine), cache_path)
        return done[stage]
    return lookup


# --- CPU 阶段：probe／extract -------------------------------------------------------------------

def compensation_warnings(compensation: Mapping[str, Any], sample_rate: int | None) -> list[str]:
    """`extract.compensation` 里净补偿（补入为正、丢弃为负）或 swr 报告的丢弃样本折算超过 `COMPENSATION_WARN_S` 时的告警。"""
    warnings = []
    net = compensation.get("net_padding_s")
    if isinstance(net, (int, float)) and abs(net) > COMPENSATION_WARN_S:
        warnings.append(f"Resampler {'padded' if net > 0 else 'dropped'} {abs(net):.3f} s net to keep the timeline")
    dropped = compensation.get("swr_reported_discarded_samples")
    if isinstance(dropped, int) and sample_rate and dropped / sample_rate > COMPENSATION_WARN_S:
        warnings.append(f"Resampler discarded {dropped} input samples ({dropped / sample_rate:.3f} s)")
    return warnings


def clean_leftovers(work_dir: Path) -> None:
    """删除上次被强杀留下的临时文件：ffmpeg 的 `.*.partial*` 与原子写的 `.*.tmp`（输出目录锁保证无并发）。"""
    for pattern in (".*.partial*", ".*.tmp"):
        for path in Path(work_dir).glob(pattern):
            path.unlink(missing_ok=True)


def probe_and_extract(config: Config, video: VideoFile) -> tuple[str, ...]:
    """ffprobe 每次都跑（<1 s）以得到视频身份；`probe.json` 当前且 WAV 在时跳过 extract。

    `probe.json` 在 extract 完成后写出，内容为 probe payload 加 `extract` 记录（PCM SHA256 等）。
    返回 probe 与 extract 的告警（跳过 extract 时取 `probe.json` 里记下的）以及补偿告警，由调用方写进运行日志。
    """
    video.probe = media.probe(video.path, config)
    video.probe_identity = plan.probe_identity(config, video.relative, video.probe.ffprobe)
    path = video.work_dir / artifacts.PROBE
    if artifacts.is_current(path, video.probe_identity) and (video.work_dir / artifacts.AUDIO_16K).is_file():
        record = artifacts.read_json(path)["extract"]
        video.pcm_sha256 = record["pcm_sha256"]
        return (video.probe.warnings + tuple(record["warnings"])
                + tuple(compensation_warnings(record["compensation"], video.probe.audio.sample_rate)))
    clean_leftovers(video.work_dir)
    result = media.extract(video.path, video.work_dir, video.probe, config)
    artifacts.write_artifact(path, video.probe_identity, {**video.probe.payload(), "extract": result.payload()})
    video.pcm_sha256 = result.pcm_sha256
    return (video.probe.warnings + result.warnings
            + tuple(compensation_warnings(result.compensation, video.probe.audio.sample_rate)))


# --- GPU 阶段：worker 子进程 ---------------------------------------------------------------------

def worker_command(stage: str, jobs_path: Path) -> list[str]:
    return [sys.executable, "-m", f"kototoki.workers.{stage}", "--jobs", str(jobs_path)]


def child_env(config: Config) -> dict[str, str]:
    cache = artifacts.work_root(config.paths.output_dir) / artifacts.CACHE_DIR
    return {**os.environ, **OFFLINE_ENV, **QUIET_ENV, "HF_HOME": str(cache), "TORCH_HOME": str(cache)}


@dataclass
class _Context:
    config: Config
    summary: Summary
    stamp: str
    worker_command: Callable[[str, Path], list[str]]
    gpu_lock: ProcessLock
    sleep: Callable[[float], None]
    models: ModelSha
    files: list[VideoFile] = field(default_factory=list)

    def fail(self, video: VideoFile, stage: str, error: BaseException | None = None) -> None:
        """记该文件该阶段失败；`error` 为 None 时 failure.json 已由 worker 写出。"""
        if error is not None:
            artifacts.write_failure(video.work_dir, stage, error)
        video.failed = stage
        self.summary.failed[video.relative] = stage
        logger.error(f"[{stage}] FAILED {video.relative}" + (f": {type(error).__name__}" if error else ""),
                     exc_info=error)

    def ensure_gpu_lock(self) -> None:
        if self.gpu_lock.held:
            return
        try:
            self.gpu_lock.acquire(break_stale=self.config.break_stale_lock)
        except LockError as error:
            raise GpuLocked(str(error)) from error
        logger.info(f"GPU lock acquired: {self.gpu_lock.path}")


def _launch(ctx: _Context, stage: str, batch: list[VideoFile]) -> tuple[int, list[dict[str, Any]]]:
    """启动一次 worker 跑 `batch`；返回退出码与进度事件（stdout 的 JSON 行）。"""
    config = ctx.config
    root = artifacts.work_root(config.paths.output_dir)
    jobs_path = root / f"jobs-{stage}.json"
    write_jobs(jobs_path, Jobs(
        stage=stage, recipe_hash=plan.recipe_hash(stage, engine=config.engine),
        config={"engine": config.engine, "models": plan.worker_models(config),
                "model_cache": str(artifacts.model_cache_path(config.paths.output_dir))},
        files=tuple(FileJob(v.work_dir.name, v.work_dir,
                            {name: v.work_dir / file for name, file in plan.STAGE_INPUTS[stage]}) for v in batch)))
    by_id = {v.work_dir.name: v for v in batch}
    stderr_path = root / f"run-{ctx.stamp}-{stage}.stderr.log"
    with stderr_path.open("ab") as stderr:
        offset = stderr.tell()
        process = subprocess.Popen(ctx.worker_command(stage, jobs_path), stdout=subprocess.PIPE, stderr=stderr,
                                   stdin=subprocess.DEVNULL, env=child_env(config), cwd=REPO_ROOT)
        ctx.gpu_lock.update(worker_pid=process.pid, worker_stage=stage)
        assert process.stdout is not None
        with process.stdout:
            events = _read_events(ctx, stage, process.stdout, by_id)
        code = process.wait()
    ctx.gpu_lock.update(worker_pid=None, worker_stage=None)
    with stderr_path.open("rb") as stream:
        stream.seek(offset)
        problems = _count_stderr_problems(stream.read())
    if problems:
        logger.warning(f"[{stage}] {problems} warning/error line(s), see {stderr_path.name}")
    return code, events


def _read_events(ctx: _Context, stage: str, stdout: Iterable[bytes],
                 by_id: Mapping[str, VideoFile]) -> list[dict[str, Any]]:
    events = []
    for raw in stdout:
        try:
            event = json.loads(raw.decode("utf-8"))
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)
        video = by_id.get(event.get("id"))
        label = video.relative if video else ""
        logger.info(f"[{stage}] {event.get('event')} {label}".rstrip())
    return events


def run_gpu_stage(ctx: _Context, stage: str, batch: list[VideoFile]) -> None:
    """跑完 `batch`；worker 异常退出时按增量结果找出正在处理的文件，记失败，为其后文件重启 worker。"""
    started = time.perf_counter()
    logger.info(f"[{stage}] start: {len(batch)} file(s)")
    pending = list(batch)
    while pending:
        code, events = _launch(ctx, stage, pending)
        reported = {event.get("id"): event.get("event") for event in events}
        position = {v.work_dir.name: i for i, v in enumerate(pending)}
        for video in pending:
            if reported.get(video.work_dir.name) == "failed":
                ctx.fail(video, stage)
        if code in (0, 1):
            break
        startup = next((e for e in events if e.get("event") == "startup_failed"), None)
        if startup is not None:
            # 模型加载失败与文件无关：本阶段剩余文件全部失败，不逐个重启。
            error = WorkerCrashed(f"{stage} worker startup failed: {startup.get('error_type')}")
            for video in pending:
                ctx.fail(video, stage, error)
            pending = []
            break
        handled = [position[i] for i in reported if i in position]
        culprit_at = (max(handled) + 1) if handled else 0
        fatal = next((e.get("id") for e in events if e.get("event") == "fatal"), None)
        if fatal in position:
            ctx.fail(pending[position[fatal]], stage)
            culprit_at = position[fatal]
        elif culprit_at < len(pending):
            ctx.fail(pending[culprit_at], stage, WorkerCrashed(f"{stage} worker exited with code {code}"))
        pending = pending[culprit_at + 1:]
        if pending:
            logger.info(f"[{stage}] restarting worker for {len(pending)} remaining file(s)")
    done = sum(advance_or_fail(ctx, video, stage) for video in batch if not video.failed)
    logger.info(f"[{stage}] end: {done} done, {len(batch) - done} failed, {time.perf_counter() - started:.1f}s")


def advance_or_fail(ctx: _Context, video: VideoFile, stage: str) -> bool:
    """`stage` 刚跑完：从它起继续核对；产物缺失或身份不符即记该阶段失败。返回是否推进成功。"""
    assert video.plan is not None and video.plan.stage == stage
    try:
        video.plan = plan.advance(video.plan, video.target(), ctx.config, ctx.models)
    except PlanError as error:
        ctx.fail(video, error.stage, error)
        return False
    if video.plan.stage == stage:
        ctx.fail(video, stage, ArtifactMissing(f"{plan.STAGE_OUTPUT[stage]} missing or not current after worker"))
        return False
    return True


# --- ja-cues、翻译与发布 -------------------------------------------------------------------------

def build_ja_cues(config: Config, video: VideoFile) -> None:
    align = artifacts.read_json(video.work_dir / artifacts.ALIGN)
    payload, text = cues.build_cues(align, asdict(config.cues))
    srt.write_srt(text, video.work_dir / JA_SRT)
    assert video.plan is not None
    artifacts.write_artifact(video.work_dir / artifacts.JA_CUES, video.plan.identities["ja_cues"], payload)


def translate_batch(ctx: _Context, batch: list[VideoFile]) -> dict[str, tuple[dict[str, str], int, str]]:
    """按各文件的 `TranslatePlan` 翻译；返回 相对路径 → (译文, 回退条数, run 目录相对工作目录)。

    只有某个文件 `needs_model` 时才取 GPU 锁、建 session（零条目或 run 已完成的文件不需要模型，直接读回译文）；
    session 建不起来只让需要模型的文件失败。
    """
    results: dict[str, tuple[dict[str, str], int, str]] = {}
    if not batch:
        return results
    started = time.perf_counter()
    logger.info(f"[translate] start: {len(batch)} file(s)")
    translate = _translate_module()
    needed = [video for video in batch if video.translate_plan.needs_model]
    session: Any = contextlib.nullcontext()
    if needed:
        try:
            ctx.ensure_gpu_lock()
            session = translate.Session(ctx.config, on_server_pid=lambda pid: ctx.gpu_lock.update(server_pid=pid))
        except Exception as error:
            for video in needed:
                ctx.fail(video, "translate", error)
    with session:
        for video in batch:
            if video.failed:
                continue
            tplan = video.translate_plan
            try:
                result = translate.translate_document(tplan, session if tplan.needs_model else None)
            except Exception as error:
                ctx.fail(video, "translate", error)
                continue
            results[video.relative] = (dict(result.translations), int(result.fallback_count), tplan.relative)
            logger.info(f"[translate] done {video.relative}: {len(tplan.document.cues)} cue(s), "
                        f"{result.fallback_count} fallback")
    ctx.gpu_lock.update(server_pid=None)
    logger.info(f"[translate] end: {time.perf_counter() - started:.1f}s")
    return results


def publish(ctx: _Context, video: VideoFile, texts: Mapping[str, str], translate_dir: str, fallback: int) -> bool:
    """三份 SRT 先写到工作目录暂存，`publish_blockers` 放行 → `record_published` → 移动；成功后删 failure.json。"""
    staging = video.work_dir / PUBLISH_DIR
    staged = {kind: staging / path.name for kind, path in video.finals.items()}
    for kind, path in staged.items():
        srt.write_srt(texts[kind], path)
    blockers = artifacts.publish_blockers(video.finals, video.work_dir, force=ctx.config.run.force)
    if blockers:
        ctx.summary.blocked.append(video.relative)
        (video.work_dir / artifacts.FAILURE).unlink(missing_ok=True)
        logger.warning(f"[publish] {video.relative}: final file(s) changed by user, not overwritten "
                       f"({', '.join(blockers)}); set [run] force = true to overwrite")
        return False
    assert video.plan is not None
    sources = video.plan.sources | {"translate_fallback_cues": fallback}
    artifacts.record_published(video.work_dir, video.finals, {k: artifacts.sha256_file(p) for k, p in staged.items()},
                               sources, translate_dir)
    for kind, path in staged.items():
        video.finals[kind].parent.mkdir(parents=True, exist_ok=True)
        artifacts.replace_with_retry(path, video.finals[kind])
    (video.work_dir / artifacts.FAILURE).unlink(missing_ok=True)
    ctx.summary.published.append(video.relative)
    ctx.summary.fallback_cues += fallback
    logger.info(f"[publish] {video.relative}" + (" (no speech)" if video.no_speech else ""))
    return True


# --- 入口 ---------------------------------------------------------------------------------------

def run(config: Config, *, worker_command: Callable[[str, Path], list[str]] = worker_command,
        sleep: Callable[[float], None] = time.sleep, console: TextIO | None = None) -> Summary:
    """跑完一批；输出目录锁冲突抛 `OutputLocked`，GPU 锁冲突抛 `GpuLocked`（已完成的 CPU 产物保留，可续跑）。"""
    output_dir = config.paths.output_dir
    root = artifacts.work_root(output_dir)
    out_lock = ProcessLock(root / artifacts.LOCK, "output directory lock", {"config": str(config.source)})
    try:
        out_lock.acquire(break_stale=config.break_stale_lock)
    except LockError as error:
        raise OutputLocked(str(error)) from error
    try:
        contain_children()
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        gpu_lock = ProcessLock(config.gpu_lock, "GPU lock", {"output_dir": str(output_dir)})
        ctx = _Context(config, Summary(), stamp, worker_command, gpu_lock, sleep, model_sha_lookup(config))
        with _run_logging(root / f"run-{stamp}.log", console):
            try:
                _run(ctx)
            finally:
                gpu_lock.release()
    finally:
        out_lock.release()
    return ctx.summary


def _run(ctx: _Context) -> None:
    config, summary = ctx.config, ctx.summary
    output_dir = config.paths.output_dir

    found = scan(config.paths.input_dir, config.input.video_extensions)
    summary.total = len(found)
    stable, summary.unstable = stable_files(found, config.run.stable_check_s, ctx.sleep)
    for rel in summary.unstable:
        logger.warning(f"[scan] {rel}: size still changing, skipped this run")
    claimed: dict[str, str] = {}  # 最终 ja.srt 路径（按平台大小写规则）→ 先占用它的相对路径
    for rel, path in stable:
        try:
            work_dir = artifacts.register_work_dir(output_dir, rel)
        except Exception as error:  # index.json 损坏、短 id 碰撞等：没有工作目录可写 failure.json，只记日志
            summary.failed[rel] = "scan"
            logger.error(f"[scan] FAILED {rel}: {type(error).__name__}", exc_info=error)
            continue
        video = VideoFile(rel, path, work_dir, artifacts.final_srt_paths(output_dir, rel))
        key = os.path.normcase(str(video.finals["ja"]))
        if key in claimed:
            ctx.fail(video, "scan", FinalPathCollision(
                f"final SRT paths of {rel!r} are already taken by {claimed[key]!r} (same stem in the same directory)"))
            continue
        claimed[key] = rel
        blockers = artifacts.publish_blockers(video.finals, video.work_dir, force=config.run.force)
        if blockers:
            summary.blocked.append(rel)
            (video.work_dir / artifacts.FAILURE).unlink(missing_ok=True)
            logger.warning(f"[scan] {rel}: final file(s) changed by user ({', '.join(blockers)}), skipped; "
                           f"set [run] force = true to overwrite")
            continue
        ctx.files.append(video)
    logger.info(f"[scan] {summary.total} video(s): {len(ctx.files)} to check, {len(summary.blocked)} blocked, "
                f"{len(summary.unstable)} unstable")

    started = time.perf_counter()
    logger.info(f"[extract] start: {len(ctx.files)} file(s)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.run.extract_workers) as pool:
        try:
            futures = {pool.submit(probe_and_extract, config, video): video for video in ctx.files}
            for future in concurrent.futures.as_completed(futures):
                video = futures[future]
                if future.exception() is not None:
                    ctx.fail(video, "extract", future.exception())
                    continue
                for warning in future.result():
                    logger.warning(f"[extract] {video.relative}: {warning}")
                logger.info(f"[extract] done {video.relative}")
        except BaseException:  # Ctrl+C：排队中的文件不再提取，只等正在跑的 ffmpeg 结束
            pool.shutdown(wait=True, cancel_futures=True)
            raise
    logger.info(f"[extract] end: {sum(1 for v in ctx.files if not v.failed)} ok, {time.perf_counter() - started:.1f}s")

    def live() -> list[VideoFile]:
        return [video for video in ctx.files if not video.failed]

    for video in live():  # 每文件一次：从 vad 起核对到第一个需要运行的阶段
        try:
            video.plan = plan.next_stage(video.target(), config, ctx.models)
        except PlanError as error:
            ctx.fail(video, error.stage, error)
            continue
        if video.plan.stage == "done":
            summary.up_to_date.append(video.relative)
            (video.work_dir / artifacts.FAILURE).unlink(missing_ok=True)
            logger.info(f"[scan] up to date: {video.relative}")

    def planned(stage: str) -> list[VideoFile]:
        return [video for video in live() if video.plan is not None and video.plan.stage == stage]

    for stage in GPU_STAGES:
        batch = planned(stage)
        if batch:
            ctx.ensure_gpu_lock()
            run_gpu_stage(ctx, stage, batch)

    for video in planned("cues"):
        try:
            build_ja_cues(config, video)
        except Exception as error:
            ctx.fail(video, "cues", error)
            continue
        advance_or_fail(ctx, video, "cues")

    translated = translate_batch(ctx, planned("translate"))
    ctx.gpu_lock.release()

    for video in live():
        try:
            stage = video.plan.stage if video.plan is not None else None
            if stage == "publish":
                if publish(ctx, video, {kind: "" for kind in artifacts.FINAL_SUFFIXES}, "", 0):
                    summary.no_speech.append(video.relative)
            elif stage == "translate" and video.relative in translated:
                translations, fallback, translate_dir = translated[video.relative]
                document = video.plan.translate.document
                texts = {"ja": (video.work_dir / JA_SRT).read_text(encoding="utf-8"),
                         "zh": srt.render_srt(document, translations),
                         "ja-zh": _merge_module().merge(document, translations) if document.cues else ""}
                publish(ctx, video, texts, translate_dir, fallback)
        except Exception as error:
            ctx.fail(video, "publish", error)

    logger.info(f"[summary] {summary.total} video(s): {len(summary.published)} published "
                f"({len(summary.no_speech)} no speech), {len(summary.up_to_date)} up to date, "
                f"{len(summary.failed)} failed, {len(summary.blocked)} blocked, {len(summary.unstable)} unstable, "
                f"{summary.fallback_cues} fallback cue(s)")
    for rel, stage in summary.failed.items():
        logger.info(f"[summary] failed at {stage}: {rel}")
