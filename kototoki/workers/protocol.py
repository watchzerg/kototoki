"""编排器 ↔ GPU worker 协议：`--jobs` 文件、逐文件进度行、失败隔离、退出码与 `failed_windows`。

`--jobs <path>` 指向 UTF-8 JSON::

    {"stage": "vad", "recipe_hash": "<sha256>", "config": {...配置快照...},
     "files": [{"id": "<work id>", "work_dir": "<.work/<id>>", "inputs": {"wav": "<path>", ...}}]}

worker 加载一次模型后先在 stdout 打一行 `started` 进度，再逐文件处理，每个文件的结果由 worker 自己写进该文件的 `work_dir`
（增量落盘），处理完一个文件即在 stdout 打一行 UTF-8 JSON 进度。单文件异常写该文件的
`failure.json` 并继续下一个；启动失败或 `FatalWorkerError`（如 CUDA 粘性错误，后续文件必然失败）
立即以退出码 2 结束，由编排器从下一文件重启（`started` 之前的异常退出也按启动失败处理、不重启）。
异常同时以 `error`（带 traceback）记到 stderr 日志。编排器读退出码与进度行只经 `classify_launch`，不自己解释字面量。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import sys
from typing import Any, BinaryIO

from kototoki.artifacts import atomic_write_json, read_json, write_failure

logger = logging.getLogger(__name__)

EXIT_OK = 0        # 全部文件完成
EXIT_PARTIAL = 1   # 部分文件失败，其余完成
EXIT_FATAL = 2     # 启动失败或 CUDA 粘性错误；未处理的文件由编排器重启 worker 继续


class FatalWorkerError(RuntimeError):
    """后续文件必然失败的错误（如 CUDA 粘性错误）；worker 内把对应异常包装成它。"""


@dataclass(frozen=True)
class FileJob:
    id: str
    work_dir: Path
    inputs: dict[str, Path]


@dataclass(frozen=True)
class Jobs:
    stage: str
    recipe_hash: str
    config: dict[str, Any]
    files: tuple[FileJob, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid jobs file: {message}")


def parse_jobs(value: Any) -> Jobs:
    _require(isinstance(value, dict), "top level must be an object")
    _require(set(value) == {"stage", "recipe_hash", "config", "files"},
             "keys must be stage, recipe_hash, config, files")
    stage, recipe_hash, config, files = value["stage"], value["recipe_hash"], value["config"], value["files"]
    _require(isinstance(stage, str) and bool(stage), "stage must be a nonempty string")
    _require(isinstance(recipe_hash, str) and bool(recipe_hash), "recipe_hash must be a nonempty string")
    _require(isinstance(config, dict), "config must be an object")
    _require(isinstance(files, list), "files must be a list")
    parsed = []
    for position, entry in enumerate(files):
        _require(isinstance(entry, dict) and set(entry) == {"id", "work_dir", "inputs"},
                 f"files[{position}] must have exactly id, work_dir, inputs")
        _require(isinstance(entry["id"], str) and bool(entry["id"]), f"files[{position}].id must be a nonempty string")
        _require(isinstance(entry["work_dir"], str) and bool(entry["work_dir"]),
                 f"files[{position}].work_dir must be a path string")
        inputs = entry["inputs"]
        _require(isinstance(inputs, dict) and all(isinstance(k, str) and isinstance(v, str) and v
                                                  for k, v in inputs.items()),
                 f"files[{position}].inputs must map names to path strings")
        parsed.append(FileJob(entry["id"], Path(entry["work_dir"]), {k: Path(v) for k, v in inputs.items()}))
    ids = [job.id for job in parsed]
    _require(len(ids) == len(set(ids)), "file ids must be unique")
    return Jobs(stage, recipe_hash, config, tuple(parsed))


def read_jobs(path: Path) -> Jobs:
    return parse_jobs(read_json(path))


def write_jobs(path: Path, jobs: Jobs) -> None:
    atomic_write_json(path, {
        "stage": jobs.stage, "recipe_hash": jobs.recipe_hash, "config": jobs.config,
        "files": [{"id": job.id, "work_dir": str(job.work_dir), "inputs": {k: str(v) for k, v in job.inputs.items()}}
                  for job in jobs.files],
    })


def emit_progress(event: Mapping[str, Any], stream: BinaryIO | None = None) -> None:
    """stdout 打一行 UTF-8 JSON，与控制台代码页无关；只放 id、状态、计数、耗时，不放转写内容。"""
    stream = stream if stream is not None else sys.stdout.buffer
    stream.write((json.dumps(dict(event), ensure_ascii=False) + "\n").encode("utf-8"))
    stream.flush()


def run_jobs(jobs: Jobs, process: Callable[[FileJob], Mapping[str, Any] | None], *,
             stream: BinaryIO | None = None) -> int:
    """逐文件调用 `process`，其返回的字段并入该文件的 `done` 进度行。"""
    failed = 0
    for job in jobs.files:
        try:
            fields = process(job) or {}
        except FatalWorkerError as error:
            logger.error("[%s] FATAL %s: %s", jobs.stage, job.id, type(error).__name__, exc_info=error)
            write_failure(job.work_dir, jobs.stage, error)
            emit_progress({"event": "fatal", "id": job.id, "error_type": type(error).__name__}, stream)
            return EXIT_FATAL
        except Exception as error:
            failed += 1
            logger.error("[%s] FAILED %s: %s", jobs.stage, job.id, type(error).__name__, exc_info=error)
            write_failure(job.work_dir, jobs.stage, error)
            emit_progress({"event": "failed", "id": job.id, "error_type": type(error).__name__}, stream)
            continue
        emit_progress({**fields, "event": "done", "id": job.id}, stream)
    return EXIT_PARTIAL if failed else EXIT_OK


def run_worker(jobs_path: Path, start: Callable[[Jobs], Callable[[FileJob], Mapping[str, Any] | None]], *,
               stream: BinaryIO | None = None) -> int:
    """worker 主循环：读 jobs、`start` 加载一次模型后发出 `started`，再逐文件处理；启动阶段任何异常返回 2。"""
    stage = "worker"  # 读 jobs 失败时还不知道阶段
    try:
        jobs = read_jobs(jobs_path)
        stage = jobs.stage
        process = start(jobs)
    except Exception as error:
        logger.error("[%s] startup failed: %s", stage, type(error).__name__, exc_info=error)
        emit_progress({"event": "startup_failed", "error_type": type(error).__name__, "message": str(error)}, stream)
        return EXIT_FATAL
    emit_progress({"event": "started"}, stream)
    return run_jobs(jobs, process, stream=stream)


# --- 读侧：编排器解释一次 worker 启动 ---------------------------------------------------------------

@dataclass(frozen=True)
class LaunchOutcome:
    """一次 worker 启动的分类结果（`classify_launch`）。"""
    failed: tuple[str, ...]        # 报告了 `failed` 的 id（`failure.json` 已由 worker 写出），按待跑顺序
    crashed: str | None            # 崩溃文件：worker 退出时正在处理的 id；正常结束或启动失败时为 None
    fatal: bool                    # 崩溃文件报告了 `fatal`（`failure.json` 已由 worker 写出）
    startup_failed: str | None     # 启动失败原因（`startup_failed` 的 `error_type` 或 `exited with code <n>`）；有它即剩余全部失败、不重启
    remaining: tuple[str, ...]     # 需要重启 worker 继续跑的 id，按待跑顺序
    error_types: Mapping[str, str] = field(default_factory=dict)  # `failed` 的 id 与 `fatal` 的崩溃文件 id → worker 报告的 `error_type`


def classify_launch(ids: Sequence[str], exit_code: int, events: Sequence[Mapping[str, Any]]) -> LaunchOutcome:
    """按本模块的退出码与事件名解释一次 worker 启动；`ids` 为本次启动的待跑 id（jobs 的顺序）。

    退出码 0／1 且每个待跑 id 都有事件：正常结束。退出码 1 也是 Python 未捕获异常的退出码，所以有 id 缺事件时
    不算正常结束，与其他异常退出同样处理：有 `startup_failed` 即启动失败；既无 `started` 又无已报告的文件事件
    （加载模型期间原生崩溃）同样按启动失败处理（`exited with code <n>`，不重启）；有 `fatal` 即该 id 为崩溃文件；
    否则最后一个有事件的 id 之后的那个 id 是崩溃文件（有 `started` 而无文件事件时归咎首个 id）。崩溃文件之后的 id 需要重启 worker。
    """
    reported = {event.get("id"): event.get("event") for event in events}
    failed = tuple(i for i in ids if reported.get(i) == "failed")
    error_types = {event.get("id"): str(event.get("error_type")) for event in events
                   if event.get("event") in ("failed", "fatal")}

    if exit_code in (EXIT_OK, EXIT_PARTIAL) and all(i in reported for i in ids):
        return LaunchOutcome(failed=failed, crashed=None, fatal=False, startup_failed=None, remaining=(),
                             error_types=error_types)
    startup = next((event for event in events if event.get("event") == "startup_failed"), None)
    if startup is not None:
        return LaunchOutcome(failed=failed, crashed=None, fatal=False, startup_failed=str(startup.get("error_type")),
                             remaining=(), error_types=error_types)
    position = {i: at for at, i in enumerate(ids)}
    started = any(event.get("event") == "started" for event in events)
    handled = [position[i] for i in reported if i in position]
    if not started and not handled:
        return LaunchOutcome(failed=failed, crashed=None, fatal=False, startup_failed=f"exited with code {exit_code}",
                             remaining=(), error_types=error_types)
    culprit_at = (max(handled) + 1) if handled else 0
    fatal = next((event.get("id") for event in events if event.get("event") == "fatal"), None)
    if fatal in position:
        culprit_at = position[fatal]
    crashed = ids[culprit_at] if culprit_at < len(ids) else None
    return LaunchOutcome(failed=failed, crashed=crashed, fatal=crashed is not None and crashed == fatal,
                         startup_failed=None, remaining=tuple(ids[culprit_at + 1:]), error_types=error_types)


def progress_event(event: Mapping[str, Any]) -> tuple[str, dict[str, int | float]] | None:
    """这个事件要不要转发成进度日志行：返回 `(事件名, 附带计数)`，不转发返回 None。

    `started` 只标加载完成，`failed`／`fatal`／`startup_failed` 由编排按 `classify_launch` 的结果记失败，都不转发。
    只有 `done` 附带计数：事件里除 `event`、`id` 之外的数值字段（不含 bool），字段名与顺序照事件原样。
    """
    name = event.get("event")
    if name in ("started", "failed", "fatal", "startup_failed"):
        return None
    counts = {key: value for key, value in event.items() if key not in ("event", "id")
              and isinstance(value, (int, float)) and not isinstance(value, bool)} if name == "done" else {}
    return name, counts


# --- ASR 失败窗口（w0／x0 共用） ------------------------------------------------------------
#
# `asr.json` 的 `original_segments[i]` 与源窗口一一对应。窗口失败（x0 生成触顶等）时该窗
# `text` 置空，截断文字与原因移入 `failed_windows`，只供诊断，不进对齐、cue 与翻译；
# 整体文字与"每个字符恰好一个 unit"按保留文本（`retained_text`）计算。

def fail_window(asr: dict[str, Any], chunk_index: int, reason: str) -> None:
    segments = asr["original_segments"]
    if type(chunk_index) is not int or not 0 <= chunk_index < len(segments):
        raise ValueError(f"No ASR window {chunk_index!r}")
    if not isinstance(reason, str) or not reason:
        raise ValueError("A failed window needs a nonempty reason")
    failed = asr.setdefault("failed_windows", [])
    if any(entry["chunk_index"] == chunk_index for entry in failed):
        raise ValueError(f"ASR window {chunk_index} is already failed")
    failed.append({"chunk_index": chunk_index, "reason": reason, "text": segments[chunk_index]["text"]})
    segments[chunk_index]["text"] = ""


def retained_text(asr: Mapping[str, Any]) -> str:
    return "".join(segment["text"] for segment in asr["original_segments"])


def validate_failed_windows(asr: Mapping[str, Any]) -> None:
    """`failed_windows` 必须存在（可为空）、索引唯一有效，对应窗口的 `text` 已置空。"""
    failed, segments = asr.get("failed_windows"), asr["original_segments"]
    if not isinstance(failed, list):
        raise ValueError("asr.json must carry a failed_windows list")
    seen = set()
    for entry in failed:
        if not isinstance(entry, dict) or set(entry) != {"chunk_index", "reason", "text"}:
            raise ValueError("failed_windows entries need exactly chunk_index, reason, text")
        index = entry["chunk_index"]
        if type(index) is not int or not 0 <= index < len(segments) or index in seen:
            raise ValueError(f"Invalid or duplicate failed window {index!r}")
        if not isinstance(entry["reason"], str) or not entry["reason"] or not isinstance(entry["text"], str):
            raise ValueError(f"Failed window {index} needs a reason and its truncated text")
        if segments[index]["text"] != "":
            raise ValueError(f"Failed window {index} must have empty retained text")
        seen.add(index)
