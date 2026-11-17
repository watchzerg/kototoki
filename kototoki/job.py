"""批次编排：扫描、CPU 阶段、GPU 阶段子进程、ja-cues、专名建表、翻译、一起发布（规格 §3、§4、§6、§7.1）。

对外只有 `run(config) -> Summary`。流程按"阶段 × 整批"推进::

    扫描（视频与音频；大小采样稳定性、源文件旁字幕已存在即跳过、主名冲突、短 id）
    → probe/extract（线程池，整批完成；有可用的内嵌日文文本字幕轨的文件在这里抽轨写 `ja.srt`，不提取音频，
      此后直接进 names，不经 vad／asr／align／ja-cues，ADR-0024）
    → vad → asr → align（各一个子进程 worker，`--jobs` 文件 + 退出码）
    → ja-cues（进程内）
    → names 与 translate 共用一个 Strata session（`kototoki.strata.Session`，编排持有，ADR-0022）：第一次真正需要模型时
      才启动（可能在 names，也可能在 translate），两阶段之间不停，整批结束、出错或被中断都 `strata launch --stop`
    → names（进程内；有非零条目的 `ja.srt` 要建表时才取 GPU 锁，零条目文件不碰 session）
    → translate（进程内；翻译子系统的计划说要模型时才取 GPU 锁，不需要模型的文件不碰 session）
    → 双语字幕 `<主名>.ja-zh.srt` 发布到源文件旁

阶段链、期望身份与"下一个要跑的阶段"归阶段计划模块 `kototoki.plan`：CPU 阶段之后每文件算一次 `next_stage`，
某阶段跑完再 `advance` 继续核对；产物存在且身份匹配即跳过，因此中断后重跑同一命令即续跑。GPU 阶段产物
（`vad.json`、`asr.json`、`align.json`）由 worker 写出；CPU 与进程内阶段的产物（`probe.json`、`ja-embedded.json`、
`ja-cues.json`、`name-table.json`）由本模块写出。模型文件 SHA256 的核对（size+mtime 缓存，每次运行每阶段最多一次）
在本模块经 `workers/gpu.verify_models` 完成。本模块不做任何时间换算，不导入任何推理模块（有测试守门）；
`strata`、`names`、`translate`、`merge` 以普通导入使用
（都只依赖标准库层面的产品代码、不导入 `plan` 与 `job`）。

工作根 `<work_dir>/<目标目录键>/`（`artifacts.work_root`，ADR-0020）。锁：启动即取工作根下的 `lock`；第一个需要 GPU 的阶段前取 `.local/gpu.lock`，持有到翻译结束，
锁文件记录编排器、当前 worker 与 Strata 服务的 pid。破除死锁只认 `KOTOTOKI_BREAK_STALE_LOCK=1`。
锁、Job Object 与进程身份是基础层 `kototoki/procs.py` 的进程原语（复制自 `experiments/translation_v3/procs.py`，不导入）。

模块页：docs/architecture/modules/batch-orchestration.md。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
import concurrent.futures
import contextlib
from dataclasses import asdict, dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, TextIO
import warnings

from kototoki import artifacts, cues, embedded, media, merge, names, plan, recipes, srt, strata, translate
from kototoki.config import REPO_ROOT, Config
from kototoki.logs import RunFormatter
from kototoki.names import BuildResult
from kototoki.plan import GPU_STAGES, JA_SRT, ModelSha, Plan, PlanError
from kototoki.procs import LockError, ProcessLock, contain_children
from kototoki.translate import TranslatePlan
from kototoki.workers import gpu
from kototoki.workers.protocol import FileJob, Jobs, classify_launch, write_jobs

EXIT_OK = 0
EXIT_FAILED = 1           # 有文件在某阶段失败；其余文件照常发布
EXIT_CONFIG = 2           # 配置文件、输入目录或工作目录不可用（__main__）
EXIT_WORK_LOCKED = 3      # 同一目标目录已有编排器在运行
EXIT_GPU_LOCKED = 4       # `.local/gpu.lock` 被其他作业持有或残留

PUBLISH_DIR = "publish"    # 工作目录内的双语字幕副本（供人工恢复与 sha256 对照）；发布到源文件旁的那份另行原子写

# worker 子进程的离线环境（沿用 experiments setup_runtime 的变量，不加私有 DLL 目录）。
OFFLINE_ENV = {"PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
               "HF_HUB_DISABLE_TELEMETRY": "1", "PYANNOTE_METRICS_ENABLED": "0"}
# worker stderr 只留日志行：关掉 tqdm／HF 下载进度条，transformers 只报 warning 及以上。
QUIET_ENV = {"TQDM_DISABLE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1", "TRANSFORMERS_VERBOSITY": "warning"}


class WorkLocked(RuntimeError):
    """同一目标目录已有编排器（或残留锁）。"""


class GpuLocked(RuntimeError):
    """`.local/gpu.lock` 被其他作业持有或残留。"""


class WorkerCrashed(RuntimeError):
    """worker 在处理该文件时异常退出（未写出结果也未报告失败）。"""


class ArtifactMissing(RuntimeError):
    """worker 正常结束但该文件的产物缺失或身份不符。"""


class FinalPathCollision(RuntimeError):
    """同目录另一个输入文件（主名相同、扩展名不同）已占用同一份双语字幕路径。"""


class NotPublished(RuntimeError):
    """收尾时文件既未失败也未发布：它的计划阶段没有被任何执行器处理（不变量被破坏）。"""


class TooLittleSpeech(RuntimeError):
    """VAD 检出的语音不足参照时长的 `MIN_SPEECH_RATIO`：音频近乎无声或抽取坏了，不再往下识别。"""


# 提取补偿（`probe.json` 的 `extract.compensation`）超过这么多秒时记 WARNING：净补入／丢弃与 swr 报告的丢弃样本。
COMPENSATION_WARN_S = 0.1
# VAD 语音时长（`accounting.speech_samples`）不足参照时长的这个比例时记该文件 vad 阶段失败（batch-run-fixes 04）。
MIN_SPEECH_RATIO = 0.01


# --- 运行日志 -----------------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# worker stderr 里按 `kototoki.logs.LOG_FORMAT` 写出的告警／错误行；tqdm、裸 traceback 等其他行不计。
_STDERR_PROBLEM = re.compile(rb"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z \[ *[0-9.]+s\] (?:WARNING|ERROR|CRITICAL) ",
                             re.MULTILINE)


@contextlib.contextmanager
def _run_logging(path: Path, console: TextIO | None = None) -> Iterator[None]:
    """`run` 期间把日志写到控制台与 `.work/run-<时间戳>.log`（内容相同，INFO 及以上）；退出时摘下并关闭 handler。

    handler 挂在 root logger 上，第三方库的告警（含 `warnings.warn`，经 `captureWarnings`）也进同一文件；
    `kototoki` logger 临时放到 INFO。只有进度、计数与耗时，不写转写与译文。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = RunFormatter()
    root, ours = logging.getLogger(), logging.getLogger("kototoki")
    level, showwarning = ours.level, warnings.showwarning
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        handlers = [logging.StreamHandler(stream),
                    logging.StreamHandler(console if console is not None else sys.stdout)]
        for handler in handlers:
            handler.setLevel(logging.INFO)
            handler.setFormatter(formatter)
            root.addHandler(handler)
        ours.setLevel(logging.INFO)
        logging.captureWarnings(True)
        try:
            yield
        finally:
            if warnings.showwarning is not showwarning:  # 进入前已在捕获时不动
                logging.captureWarnings(False)
            ours.setLevel(level)
            for handler in handlers:
                root.removeHandler(handler)
                handler.close()


def _stale_line(lock: ProcessLock) -> str:
    """破除残留锁的告警行：旧锁的 pid，以及它记下的 worker 阶段与 Strata 服务 pid（有才写）。"""
    stale = lock.stale or {}
    owner = stale.get("pid")
    parts = [f"pid {owner}" if type(owner) is int else "no owner pid"]
    parts += [f"{key} {stale[key]}" for key in ("worker_stage", "server_pid") if stale.get(key) is not None]
    return f"[lock] replaced stale {lock.kind} ({', '.join(parts)})"


def _count_stderr_problems(data: bytes) -> int:
    """worker stderr 片段里级别为 WARNING／ERROR（及 CRITICAL）的日志行数。"""
    return len(_STDERR_PROBLEM.findall(data))


# --- 文件状态与汇总 ------------------------------------------------------------------------------

@dataclass
class VideoFile:
    """一个输入文件（视频或音频）在本次运行中的状态。"""
    relative: str                 # 输入目录内相对路径（正斜杠）
    path: Path
    work_dir: Path
    final: Path                   # 源文件旁的双语字幕
    probe: media.Probe | None = None
    probe_identity: dict[str, Any] | None = None
    pcm_sha256: str | None = None
    embedded: dict[str, Any] | None = None  # 采用内嵌日文字幕时 `ja-embedded.json` 的身份（此时不提取音频）
    embedded_note: str = ""       # 采用内嵌字幕时的日志说明（流索引、编码、条数）
    reused_wav: bool = False      # 本次运行复用了已有的派生 WAV（`probe.json` 当前，跳过 extract）
    plan: Plan | None = None      # CPU 阶段之后由阶段计划模块给出，某阶段跑完后推进
    failed: str | None = None     # 本次运行中失败的阶段

    def target(self) -> plan.Target:
        assert self.probe_identity is not None and (self.pcm_sha256 is not None or self.embedded is not None)
        return plan.Target(self.work_dir, self.probe_identity, self.pcm_sha256, self.embedded)

    @property
    def no_speech(self) -> bool:
        return self.plan is not None and self.plan.no_speech

    @property
    def translate_plan(self) -> TranslatePlan:
        """核对到翻译阶段之后才存在（`plan.stage` 为 translate）。"""
        assert self.plan is not None and self.plan.translate is not None
        return self.plan.translate


@dataclass
class Summary:
    total: int = 0                                         # 扫描到的输入文件数（视频与音频）
    published: list[str] = field(default_factory=list)     # 本次发布
    existing: list[str] = field(default_factory=list)      # 源文件旁已有双语字幕，跳过
    unstable: list[str] = field(default_factory=list)      # 大小仍在变化（写入中），跳过
    no_speech: list[str] = field(default_factory=list)     # VAD 为空，发布零条目字幕
    embedded: list[str] = field(default_factory=list)      # 本次发布中日文取自内嵌字幕轨、未经 STT 的文件
    failed: dict[str, str] = field(default_factory=dict)   # 相对路径 → 失败阶段
    untranslated_cues: int = 0                             # 本次翻译完成的文件中不出中文的 cue 数（不论是否发布）

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


# --- 模型核对 -------------------------------------------------------------------------------------

def model_sha_lookup(config: Config) -> ModelSha:
    """按阶段核对 worker 用到的模型文件 SHA256（size+mtime 缓存与 worker 共用），每次运行每阶段最多一次。

    核对失败（模型缺失或 SHA 不符）同样缓存：同阶段的其余文件直接得到同一个异常，不再逐个重新哈希。
    """
    models = plan.worker_models(config)
    cache_path = artifacts.model_cache_path(config.paths.work_dir)
    done: dict[str, Mapping[str, str]] = {}
    failed: dict[str, tuple[Exception, Any]] = {}  # 阶段 → (异常, 首次核对时的 traceback)

    def lookup(stage: str) -> Mapping[str, str]:
        if stage in failed:
            error, traceback = failed[stage]
            raise error.with_traceback(traceback)  # 复原首次的 traceback，不随每次重抛累积
        if stage not in done:
            try:
                done[stage] = gpu.verify_models(plan.model_files(stage, models, engine=config.engine), cache_path)
            except Exception as error:
                failed[stage] = (error, error.__traceback__)
                raise
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


def use_embedded_subtitle(config: Config, video: VideoFile, stream: Mapping[str, Any]) -> str | None:
    """采用内嵌日文字幕轨 `stream`（ADR-0024）：抽取、清洗，写 `ja.srt` 与 `ja-embedded.json`，置 `video.embedded`。

    返回 None 即已采用；否则是不可用的原因（ffmpeg 抽取失败、清洗后零条目），调用方回到 STT 链。
    内嵌记录是否当前由阶段计划判定（`plan.embedded_current`：身份匹配且记下的 `ja_srt_sha256` 与 `ja.srt` 相符），
    当前即跳过抽取。不删 `ja-cues.json`：它也记着 cue 阶段写出的 `ja.srt` 的 SHA256，这里改写 `ja.srt` 后它自然
    不再当前，以后改走 STT 时 cues 阶段重建。
    """
    assert video.probe is not None and video.probe_identity is not None
    work = video.work_dir
    identity = plan.embedded_identity(video.probe_identity, int(stream["index"]))
    record_path, ja_path = work / artifacts.JA_EMBEDDED, work / JA_SRT
    cue_count = artifacts.read_json(record_path)["cues"] if plan.embedded_current(work, identity) else None
    if cue_count is None:
        try:
            text, stats = embedded.clean(media.extract_subtitle(video.path, int(stream["index"]), config.paths.ffmpeg))
        except (media.MediaError, ValueError) as error:
            return f"{type(error).__name__}: {(str(error).splitlines() or [''])[0]}"
        if not text:
            return f"no usable cue among {stats['source_cues']}"
        work.mkdir(parents=True, exist_ok=True)
        clean_leftovers(work)
        srt.write_srt(text, ja_path)
        artifacts.write_artifact(record_path, identity, {"stream": dict(stream), **stats,
                                                         "ja_srt_sha256": artifacts.sha256_file(ja_path)})
        cue_count = stats["cues"]
    probe_path = work / artifacts.PROBE
    if not artifacts.is_current(probe_path, video.probe_identity):  # 没有提取音频：`extract` 为 null
        artifacts.write_artifact(probe_path, video.probe_identity, {**video.probe.payload(), "extract": None})
    video.embedded = identity
    video.embedded_note = f"embedded subtitle stream {stream['index']} ({stream['codec_name']}), {cue_count} cue(s)"
    return None


def probe_and_extract(config: Config, video: VideoFile) -> tuple[str, ...]:
    """ffprobe 每次都跑（<1 s）以得到视频身份；`probe.json` 当前且 WAV 在时跳过 extract。

    `[input] use_embedded_subtitles` 开着且有可用的日文文本字幕轨时先试 `use_embedded_subtitle`：采用后不提取音频，
    只返回选轨告警（音轨告警与该文件无关）；不可用时加一条告警，照常提取音频走 STT。
    `probe.json` 在 extract 完成后写出，内容为 probe payload 加 `extract` 记录（PCM SHA256 等）。
    返回 probe 与 extract 的告警（跳过 extract 时取 `probe.json` 里记下的）以及补偿告警，由调用方写进运行日志。
    """
    video.probe = media.probe(video.path, config)
    video.probe_identity = plan.probe_identity(config, video.relative, video.probe.ffprobe)
    fallback: tuple[str, ...] = ()
    if config.input.use_embedded_subtitles:
        stream, notes = media.select_subtitle(video.probe.subtitles, config.input.audio_language)
        if stream is not None:
            reason = use_embedded_subtitle(config, video, stream)
            if reason is None:
                return tuple(notes)
            fallback = (*notes, f"Embedded subtitle stream {stream['index']} is unusable ({reason}); "
                                "falling back to speech recognition")
    path = video.work_dir / artifacts.PROBE
    # `extract` 为 null 的 `probe.json` 是采用内嵌字幕时写的，没有 WAV 记录
    if artifacts.is_current(path, video.probe_identity) and (video.work_dir / artifacts.AUDIO_16K).is_file():
        record = artifacts.read_json(path)["extract"]
        if record is not None:
            video.pcm_sha256 = record["pcm_sha256"]
            video.reused_wav = True
            return (fallback + video.probe.warnings + tuple(record["warnings"])
                    + tuple(compensation_warnings(record["compensation"], video.probe.audio.sample_rate)))
    clean_leftovers(video.work_dir)
    result = media.extract(video.path, video.work_dir, video.probe, config)
    artifacts.write_artifact(path, video.probe_identity, {**video.probe.payload(), "extract": result.payload()})
    video.pcm_sha256 = result.pcm_sha256
    return (fallback + video.probe.warnings + result.warnings
            + tuple(compensation_warnings(result.compensation, video.probe.audio.sample_rate)))


# --- GPU 阶段：worker 子进程 ---------------------------------------------------------------------

def worker_command(stage: str, jobs_path: Path) -> list[str]:
    return [sys.executable, "-m", f"kototoki.workers.{stage}", "--jobs", str(jobs_path)]


def child_env(config: Config) -> dict[str, str]:
    cache = artifacts.cache_dir(config.paths.work_dir)
    return {**os.environ, **OFFLINE_ENV, **QUIET_ENV, "HF_HOME": str(cache), "TORCH_HOME": str(cache)}


def _failure_kind(stage: str, cause: BaseException) -> tuple[str, str, str | None, int | None]:
    """失败类别：阶段、异常类型与抛出位置（最内层帧的文件与行号）。每个文件各抛一个新异常对象时（如发布的
    `OSError`）也归为同一类；同类型但从别处抛出的仍算新的一类。没有 traceback 的异常位置为 None。"""
    tb = cause.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    where = (tb.tb_frame.f_code.co_filename, tb.tb_lineno) if tb is not None else (None, None)
    return (stage, f"{type(cause).__module__}.{type(cause).__qualname__}", *where)


@dataclass
class _Context:
    config: Config
    summary: Summary
    root: Path                    # 本目标目录的工作根
    stamp: str
    worker_command: Callable[[str, Path], list[str]]
    gpu_lock: ProcessLock
    sleep: Callable[[float], None]
    models: ModelSha
    files: list[VideoFile] = field(default_factory=list)
    traced: set[tuple[str, str, str | None, int | None]] = field(default_factory=set)  # 已带 traceback 记过的失败类别

    def fail(self, video: VideoFile, stage: str, error: BaseException | None = None, *,
             error_type: str | None = None, traceback: bool = True) -> None:
        """记该文件该阶段失败；`error` 为 None 时 failure.json 已由 worker 写出，类型取 worker 事件的 `error_type`。

        同一类失败（`_failure_kind`：阶段、异常类型、抛出位置）只在第一次带 traceback；不带 traceback 的行改为
        附上异常消息首行（截到 200 字符），原因不丢（batch-run-fixes 06.3）。
        """
        if error is not None:
            artifacts.write_failure(video.work_dir, stage, error)
            error_type = type(error).__name__
        video.failed = stage
        self.summary.failed[video.relative] = stage
        cause = error.__cause__ if isinstance(error, PlanError) and error.__cause__ is not None else error
        if cause is not None and traceback:
            kind = _failure_kind(stage, cause)
            traceback = kind not in self.traced
            self.traced.add(kind)
        line = f"[{stage}] FAILED {video.relative}" + (f": {error_type}" if error_type else "")
        if error is not None and not traceback and (message := str(error).strip()):
            line += f": {message.splitlines()[0][:200]}"
        logger.error(line, exc_info=error if traceback else None)

    def ensure_gpu_lock(self) -> None:
        if self.gpu_lock.held:
            return
        try:
            self.gpu_lock.acquire(break_stale=self.config.break_stale_lock)
        except LockError as error:
            raise GpuLocked(str(error)) from error
        logger.info(f"[lock] GPU acquired: {self.gpu_lock.path}")
        if self.gpu_lock.stale is not None:
            logger.warning(_stale_line(self.gpu_lock))


def _launch(ctx: _Context, stage: str, batch: list[VideoFile]) -> tuple[int, list[dict[str, Any]]]:
    """启动一次 worker 跑 `batch`；返回退出码与进度事件（stdout 的 JSON 行）。"""
    config, root = ctx.config, ctx.root
    jobs_path = root / f"jobs-{stage}.json"
    write_jobs(jobs_path, Jobs(
        stage=stage, recipe_hash=plan.recipe_hash(stage, engine=config.engine),
        config={"engine": config.engine, "models": plan.worker_models(config),
                "model_cache": str(artifacts.model_cache_path(config.paths.work_dir))},
        files=tuple(FileJob(v.work_dir.name, v.work_dir,
                            {name: v.work_dir / file for name, file in plan.STAGE_INPUTS[stage]}) for v in batch)))
    by_id = {v.work_dir.name: v for v in batch}
    stderr_path = root / f"run-{ctx.stamp}-{stage}.stderr.log"
    with stderr_path.open("ab") as stderr:
        offset = stderr.tell()
        process = subprocess.Popen(ctx.worker_command(stage, jobs_path), stdout=subprocess.PIPE, stderr=stderr,
                                   stdin=subprocess.DEVNULL, env=child_env(config), cwd=REPO_ROOT)
        try:
            ctx.gpu_lock.update(worker_pid=process.pid, worker_stage=stage)
            assert process.stdout is not None
            with process.stdout:
                events = _read_events(ctx, stage, process.stdout, by_id)
            code = process.wait()
        finally:
            if process.returncode is None:  # 读 stdout 时抛异常（Ctrl+C、写日志失败）：先回收 worker，再向上抛
                process.kill()
                process.wait()
    ctx.gpu_lock.update(worker_pid=None, worker_stage=None)
    with stderr_path.open("rb") as stream:
        stream.seek(offset)
        problems = _count_stderr_problems(stream.read())
    if problems:
        logger.warning(f"[{stage}] {problems} warning/error line(s), see {stderr_path.name}")
    if code not in (0, 1):  # 裸 traceback、原生崩溃不计数：退出码异常时固定给出指针
        logger.warning(f"[{stage}] worker exited with code {code}, see {stderr_path.name}")
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
        name = event.get("event")
        if name in ("failed", "fatal", "startup_failed"):  # 由 run_gpu_stage 记成带类型的 FAILED 行
            continue
        video = by_id.get(event.get("id"))
        line = f"[{stage}] {name} {video.relative if video else ''}".rstrip()
        counts = [f"{key}={value}" for key, value in event.items() if key not in ("event", "id")
                  and isinstance(value, (int, float)) and not isinstance(value, bool)]
        logger.info(line + (f": {' '.join(counts)}" if name == "done" and counts else ""))
    return events


def run_gpu_stage(ctx: _Context, stage: str, batch: list[VideoFile]) -> None:
    """跑完 `batch`；worker 异常退出时按增量结果找出正在处理的文件，记失败，为其后文件重启 worker。"""
    started = time.perf_counter()
    logger.info(f"[{stage}] start: {len(batch)} file(s)")
    by_id = {video.work_dir.name: video for video in batch}
    pending = list(batch)
    while pending:
        code, events = _launch(ctx, stage, pending)
        outcome = classify_launch([video.work_dir.name for video in pending], code, events)
        reported = {event.get("id"): str(event.get("error_type")) for event in events
                    if event.get("event") in ("failed", "fatal")}
        for identifier in outcome.failed:
            ctx.fail(by_id[identifier], stage, error_type=reported[identifier])
        if outcome.startup_failed is not None:
            # 模型加载失败与文件无关：本阶段剩余文件全部失败，不逐个重启；原因一行，逐文件行不带 traceback。
            logger.error(f"[{stage}] worker startup failed: {outcome.startup_failed}")
            error = WorkerCrashed(f"{stage} worker startup failed: {outcome.startup_failed}")
            for video in pending:
                ctx.fail(video, stage, error, traceback=False)
            break
        if outcome.crashed is not None:
            if outcome.fatal:
                ctx.fail(by_id[outcome.crashed], stage, error_type=reported[outcome.crashed])
            else:
                ctx.fail(by_id[outcome.crashed], stage, WorkerCrashed(f"{stage} worker exited with code {code}"),
                         traceback=False)
        pending = [by_id[identifier] for identifier in outcome.remaining]
        if pending:
            logger.info(f"[{stage}] restarting worker for {len(pending)} remaining file(s)")
    done = sum(advance_or_fail(ctx, video, stage) for video in batch if not video.failed)
    logger.info(f"[{stage}] end: {done} done, {len(batch) - done} failed, {time.perf_counter() - started:.1f}s")


def speech_gate(ctx: _Context, batch: list[VideoFile]) -> None:
    """计划停在 asr 的文件：`vad.json` 的语音时长不足参照时长的 `MIN_SPEECH_RATIO` 时记 vad 阶段失败。"""
    for video in batch:
        assert video.probe is not None
        accounting = artifacts.read_json(video.work_dir / artifacts.VAD)["accounting"]
        speech_s = accounting["speech_samples"] / recipes.SAMPLE_RATE
        reference_s = video.probe.duration_s
        if speech_s < reference_s * MIN_SPEECH_RATIO:
            ctx.fail(video, "vad", TooLittleSpeech(
                f"VAD found {speech_s:.1f} s of speech in {reference_s:.1f} s of input "
                f"(below {MIN_SPEECH_RATIO:.0%}); the audio is nearly silent or the extraction is broken"),
                traceback=False)


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


# --- ja-cues、专名建表、翻译与发布 ----------------------------------------------------------------

def build_ja_cues(config: Config, video: VideoFile) -> Mapping[str, Any]:
    """写 `ja.srt`，再写 `ja-cues.json`（返回其 payload）；payload 另记写出的 `ja.srt` 的 SHA256，供阶段计划核对新鲜度。"""
    align = artifacts.read_json(video.work_dir / artifacts.ALIGN)
    payload, text = cues.build_cues(align, asdict(config.cues))
    ja_path = video.work_dir / JA_SRT
    srt.write_srt(text, ja_path)
    assert video.plan is not None
    artifacts.write_artifact(video.work_dir / artifacts.JA_CUES, video.plan.identities["ja_cues"],
                             {**payload, "ja_srt_sha256": artifacts.sha256_file(ja_path)})
    return payload


def _cues_line(relative: str, payload: Mapping[str, Any]) -> str:
    """一个文件 cue 阶段的结果行：条数与回填、回退计数，不含 cue 文字。"""
    sources = payload["time_sources"]
    return (f"[cues] done {relative}: {len(payload['cues'])} cue(s), "
            f"{sources.get('interpolated', 0)} interpolated unit(s), {sources.get('fallback', 0)} fallback unit(s), "
            f"{len(payload['fallback_windows'])} fallback window(s), {payload['unrendered_chars']} unrendered char(s)")


def cues_batch(ctx: _Context, batch: list[VideoFile]) -> None:
    """进程内为 `batch` 建日文 cue；0 条 cue 的 done 行用 WARNING（有语音却渲染不出字幕），单文件异常只让该文件失败。"""
    if not batch:
        return
    started = time.perf_counter()
    logger.info(f"[cues] start: {len(batch)} file(s)")
    done = 0
    for video in batch:
        try:
            payload = build_ja_cues(ctx.config, video)
        except Exception as error:
            ctx.fail(video, "cues", error)
            continue
        (logger.info if payload["cues"] else logger.warning)(_cues_line(video.relative, payload))
        done += advance_or_fail(ctx, video, "cues")
    logger.info(f"[cues] end: {done} done, {len(batch) - done} failed, {time.perf_counter() - started:.1f}s")


def _names_line(relative: str, result: BuildResult) -> str:
    """一部影片建表结果的日志行：只有计数、token 与耗时，条目文字不进日志。"""
    if result.status != "ok":
        return f"[names] done {relative}: build failed ({result.payload['build']['reason']}), empty table"
    if result.attempts == 0:
        return f"[names] done {relative}: no cues, empty table"
    meta = result.payload["meta"]
    dropped = sum(len(meta[key]) for key in ("dropped_shape", "dropped_honorific", "dropped_ja_shape"))
    return (f"[names] done {relative}: {len(result.payload['entries'])} entries ({dropped} dropped), "
            f"{meta['prompt_tokens']} prompt tok, {meta['completion_tokens']} completion tok, {result.seconds:.1f}s"
            + (f", attempt {result.attempts}/{names.ATTEMPTS}" if result.attempts > 1 else ""))


def names_batch(ctx: _Context, batch: list[VideoFile], session: strata.Session) -> None:
    """为 `batch` 建专名表并写 `name-table.json`；建表终态失败（`too_long`／`failed`）写空表、记 WARNING，影片照常往下走。

    只有某个文件的 `ja.srt` 有 cue 时才取 GPU 锁，有 cue 的文件拿到共享 `session`（第一次请求模型时启动 Strata），零条目
    文件传 None；撞 GPU 锁（`GpuLocked`）向上抛、整批退出码 4（此时共享 session 尚未启动 Strata），建表异常只让该文件失败。
    """
    if not batch:
        return
    started = time.perf_counter()
    logger.info(f"[names] start: {len(batch)} file(s)")
    done = 0
    documents: dict[str, srt.SourceDocument] = {}
    for video in batch:
        try:
            documents[video.relative] = srt.read_srt(video.work_dir / JA_SRT)
        except Exception as error:
            ctx.fail(video, "names", error)
    if any(not video.failed and documents[video.relative].cues for video in batch):
        ctx.ensure_gpu_lock()
    for video in batch:
        if video.failed:
            continue
        assert video.plan is not None
        document = documents[video.relative]
        known = session.unavailable is not None  # 原因已由 `[strata]` ERROR 行记过：FAILED 行不再带 traceback
        try:
            result = names.build_document(video.work_dir, document, session if document.cues else None,
                                          ctx.config.names.seed)
            artifacts.write_artifact(video.work_dir / artifacts.NAME_TABLE, video.plan.identities["names"],
                                     result.payload)
        except Exception as error:
            ctx.fail(video, "names", error, traceback=not known)
            continue
        line = _names_line(video.relative, result)
        (logger.info if result.status == "ok" else logger.warning)(line)
        done += advance_or_fail(ctx, video, "names")
    logger.info(f"[names] end: {done} done, {len(batch) - done} failed, {time.perf_counter() - started:.1f}s")


def translate_batch(ctx: _Context, batch: list[VideoFile],
                    session: strata.Session) -> dict[str, tuple[dict[str, str | None], int, str]]:
    """按各文件的 `TranslatePlan` 翻译；返回 相对路径 → (译文, 未翻译条数, run 目录相对工作目录)。

    只有某个文件 `needs_model` 时才取 GPU 锁（names 已取时沿用），需要模型的文件拿到共享 `session`（names 阶段没有
    启动 Strata 时在这里第一次启动）；零条目或 run 已完成的文件不需要模型，传 None、直接读回译文。撞 GPU 锁
    （`GpuLocked`）向上抛、整批退出码 4。
    """
    results: dict[str, tuple[dict[str, str | None], int, str]] = {}
    if not batch:
        return results
    started = time.perf_counter()
    logger.info(f"[translate] start: {len(batch)} file(s)")
    if any(video.translate_plan.needs_model for video in batch):
        ctx.ensure_gpu_lock()
    for video in batch:
        if video.failed:
            continue
        tplan = video.translate_plan
        file_started = time.perf_counter()
        known = session.unavailable is not None  # 同 names_batch
        try:
            result = translate.translate_document(tplan, session if tplan.needs_model else None,
                                                  relative=video.relative)
        except Exception as error:
            ctx.fail(video, "translate", error, traceback=not known)
            continue
        results[video.relative] = (dict(result.translations), int(result.untranslated_count), tplan.relative)
        ctx.summary.untranslated_cues += int(result.untranslated_count)  # 翻译完成即计，与发布成败无关
        resumed = " (resumed)" if tplan.document.cues and not tplan.needs_model else ""  # 全部批次已完成，未用模型
        (logger.warning if result.untranslated_count else logger.info)(
            f"[translate] done {video.relative}{resumed}: {len(tplan.document.cues)} cue(s), "
            f"{result.untranslated_count} untranslated, {time.perf_counter() - file_started:.1f}s")
    logger.info(f"[translate] end: {len(results)} done, {len(batch) - len(results)} failed, "
                f"{time.perf_counter() - started:.1f}s")
    return results


def publish(ctx: _Context, video: VideoFile, text: str, translate_dir: str, untranslated: int) -> bool:
    """双语字幕写一份到工作目录 `publish/`（副本）→ 原子写到源文件旁 → `record_published`（审计）；成功后删 failure.json。

    源文件旁那份用 `write_srt` 原子写：临时文件建在目标目录内再替换，工作目录与输入不在同一卷时也不会跨卷移动。
    审计记录只在写成功之后写。运行期间源文件旁出现了同名字幕（用户或别的工具写的）时不覆盖，按"已存在"跳过（ADR-0020）。
    """
    if video.final.exists():
        ctx.summary.existing.append(video.relative)
        (video.work_dir / artifacts.FAILURE).unlink(missing_ok=True)
        logger.warning(f"[publish] {video.relative}: {video.final.name} appeared during the run, not overwritten")
        return False
    assert video.plan is not None
    srt.write_srt(text, video.work_dir / PUBLISH_DIR / video.final.name)
    srt.write_srt(text, video.final)
    artifacts.record_published(video.work_dir, video.final, artifacts.sha256_file(video.final),
                               video.plan.sources | {"translate_untranslated_cues": untranslated}, translate_dir)
    (video.work_dir / artifacts.FAILURE).unlink(missing_ok=True)
    ctx.summary.published.append(video.relative)
    if video.embedded is not None:
        ctx.summary.embedded.append(video.relative)
    logger.info(f"[publish] done {video.relative}" + (" (no speech)" if video.no_speech else "")
                + (" (embedded subtitles)" if video.embedded is not None else "")
                + (f", {untranslated} untranslated cue(s)" if untranslated else ""))
    return True


# --- 入口 ---------------------------------------------------------------------------------------

def run(config: Config, *, worker_command: Callable[[str, Path], list[str]] = worker_command,
        sleep: Callable[[float], None] = time.sleep, console: TextIO | None = None) -> Summary:
    """跑完一批；工作根锁冲突抛 `WorkLocked`，GPU 锁冲突抛 `GpuLocked`（已完成的 CPU 产物保留，可续跑）。"""
    input_dir = config.paths.input_dir
    root = artifacts.work_root(config.paths.work_dir, input_dir)
    work_lock = ProcessLock(root / artifacts.LOCK, "work directory lock",
                            {"config": str(config.source), "input_dir": str(input_dir)})
    try:
        work_lock.acquire(break_stale=config.break_stale_lock)
    except LockError as error:
        raise WorkLocked(str(error)) from error
    try:
        contain_children()
        artifacts.record_input(root, input_dir)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        gpu_lock = ProcessLock(config.gpu_lock, "GPU lock", {"input_dir": str(input_dir)})
        ctx = _Context(config, Summary(), root, stamp, worker_command, gpu_lock, sleep, model_sha_lookup(config))
        with _run_logging(root / f"run-{stamp}.log", console):
            logger.info(f"[run] start: config={config.source} input={input_dir} engine={config.engine}")
            if work_lock.stale is not None:
                logger.warning(_stale_line(work_lock))
            try:
                _run(ctx)
            except BaseException as error:  # Ctrl+C、GpuLocked、Strata 启停异常等：日志收尾后原样抛出
                logger.error(f"[run] ABORTED: {type(error).__name__}",
                             exc_info=None if isinstance(error, KeyboardInterrupt) else error)
                raise
            finally:
                _log_summary(ctx.summary)
                gpu_lock.release()
    finally:
        work_lock.release()
    return ctx.summary


def _run(ctx: _Context) -> None:
    config, summary = ctx.config, ctx.summary
    input_dir = config.paths.input_dir

    found = scan(input_dir, config.input.extensions)
    summary.total = len(found)
    stable, summary.unstable = stable_files(found, config.run.stable_check_s, ctx.sleep)
    for rel in summary.unstable:
        logger.warning(f"[scan] {rel}: size still changing, skipped this run")
    claimed: dict[str, str] = {}  # 双语字幕路径（按平台大小写规则）→ 先占用它的相对路径
    for rel, path in stable:
        final = artifacts.final_srt_path(input_dir, rel)
        if final.exists():  # 只看文件名，不论是否本项目生成（ADR-0020）
            summary.existing.append(rel)
            logger.info(f"[scan] {rel}: {final.name} exists, skipped")
            continue
        try:
            work_dir = artifacts.register_work_dir(ctx.root, rel)
        except Exception as error:  # index.json 损坏、短 id 碰撞等：没有工作目录可写 failure.json，只记日志
            summary.failed[rel] = "scan"
            logger.error(f"[scan] FAILED {rel}: {type(error).__name__}", exc_info=error)
            continue
        video = VideoFile(rel, path, work_dir, final)
        key = os.path.normcase(str(final))
        if key in claimed:
            ctx.fail(video, "scan", FinalPathCollision(
                f"subtitle path of {rel!r} is already taken by {claimed[key]!r} (same stem in the same directory)"))
            continue
        claimed[key] = rel
        ctx.files.append(video)
    logger.info(f"[scan] {summary.total} file(s): {len(ctx.files)} to process, {len(summary.existing)} with "
                f"subtitles, {len(summary.unstable)} unstable, "
                f"{sum(stage == 'scan' for stage in summary.failed.values())} failed")

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
                logger.info(f"[extract] done {video.relative}"
                            + (f": {video.embedded_note}, skipping speech recognition" if video.embedded else "")
                            + (" (reused)" if video.reused_wav else ""))
        except BaseException:  # Ctrl+C：排队中的文件不再提取，只等正在跑的 ffmpeg 结束
            pool.shutdown(wait=True, cancel_futures=True)
            raise
    ok = sum(1 for video in ctx.files if not video.failed)
    logger.info(f"[extract] end: {ok} done, {len(ctx.files) - ok} failed, {time.perf_counter() - started:.1f}s")

    def live() -> list[VideoFile]:
        return [video for video in ctx.files if not video.failed]

    for video in live():  # 每文件一次：从 vad 起核对到第一个需要运行的阶段
        try:
            video.plan = plan.next_stage(video.target(), config, ctx.models)
        except PlanError as error:
            ctx.fail(video, error.stage, error)
    logger.info(_plan_line([video.plan.stage for video in live() if video.plan is not None]))

    def planned(stage: str) -> list[VideoFile]:
        return [video for video in live() if video.plan is not None and video.plan.stage == stage]

    for stage in GPU_STAGES:
        if stage == "asr":
            speech_gate(ctx, planned(stage))
        batch = planned(stage)
        if batch:
            ctx.ensure_gpu_lock()
            run_gpu_stage(ctx, stage, batch)

    cues_batch(ctx, planned("cues"))

    # names 与 translate 共用一个 Strata session：第一次需要模型时启动，退出上下文（正常、出错、中断）即 `--stop` 并核实
    # 显存释放，之后才放 GPU 锁；两阶段都不需要模型时整批不启动。pid 经回调写进 GPU 锁（未取锁时 update 是空操作）。
    with strata.Session(config, on_server_pid=lambda pid: ctx.gpu_lock.update(server_pid=pid)) as session:
        names_batch(ctx, planned("names"), session)
        translated = translate_batch(ctx, planned("translate"), session)
    ctx.gpu_lock.release()

    for video in live():
        try:
            stage = video.plan.stage if video.plan is not None else None
            if stage == "publish":
                if publish(ctx, video, "", "", 0):
                    summary.no_speech.append(video.relative)
            elif stage == "translate" and video.relative in translated:
                translations, untranslated, translate_dir = translated[video.relative]
                document = video.plan.translate.document
                text = merge.merge(document, translations) if document.cues else ""
                publish(ctx, video, text, translate_dir, untranslated)
        except Exception as error:
            ctx.fail(video, "publish", error)

    # 收尾不变量：未失败的文件必须已发布（含无语音）或按"已存在"跳过；某个计划阶段没被任何执行器处理时记失败，
    # 不让它既不发布也不失败、整批却以 0 退出。
    for video in live():
        if video.relative not in summary.published and video.relative not in summary.existing:
            stage = video.plan.stage if video.plan is not None else None
            ctx.fail(video, "publish", NotPublished(f"planned stage {stage!r} was not handled by any executor"))


def _plan_line(stages: list[str]) -> str:
    """计划之后每个文件从哪个阶段继续：按阶段链顺序只列非零项（`publish` 即无语音或已全部完成、只差发布）。"""
    order = (*GPU_STAGES, "cues", "names", "translate", "publish")
    counts = {stage: stages.count(stage) for stage in order if stages.count(stage)}
    return f"[plan] {len(stages)} file(s) resume at: " + (", ".join(f"{stage} {n}" for stage, n in counts.items()) or "none")


def _log_summary(summary: Summary) -> None:
    """结尾汇总：任何退出路径都写（中断时是已知的计数）。"""
    logger.info(f"[summary] {summary.total} file(s): {len(summary.published)} published "
                f"({len(summary.no_speech)} no speech, {len(summary.embedded)} from embedded subtitles), "
                f"{len(summary.existing)} with subtitles, "
                f"{len(summary.failed)} failed, {len(summary.unstable)} unstable, "
                f"{summary.untranslated_cues} untranslated cue(s)")
    for rel, stage in summary.failed.items():
        logger.info(f"[summary] failed at {stage}: {rel}")
