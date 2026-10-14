"""编排器 ↔ GPU worker 协议：`--jobs` 文件、逐文件进度行、失败隔离、退出码与 `failed_windows`。

`--jobs <path>` 指向 UTF-8 JSON::

    {"stage": "vad", "recipe_hash": "<sha256>", "config": {...配置快照...},
     "files": [{"id": "<work id>", "work_dir": "<.work/<id>>", "inputs": {"wav": "<path>", ...}}]}

worker 加载一次模型后逐文件处理，每个文件的结果由 worker 自己写进该文件的 `work_dir`
（增量落盘），处理完一个文件即在 stdout 打一行 UTF-8 JSON 进度。单文件异常写该文件的
`failure.json` 并继续下一个；启动失败或 `FatalWorkerError`（如 CUDA 粘性错误，后续文件必然失败）
立即以退出码 2 结束，由编排器从下一文件重启。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, BinaryIO

from kototoki.artifacts import atomic_write_json, read_json, write_failure

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
            write_failure(job.work_dir, jobs.stage, error)
            emit_progress({"event": "fatal", "id": job.id, "error_type": type(error).__name__}, stream)
            return EXIT_FATAL
        except Exception as error:
            failed += 1
            write_failure(job.work_dir, jobs.stage, error)
            emit_progress({"event": "failed", "id": job.id, "error_type": type(error).__name__}, stream)
            continue
        emit_progress({**fields, "event": "done", "id": job.id}, stream)
    return EXIT_PARTIAL if failed else EXIT_OK


def run_worker(jobs_path: Path, start: Callable[[Jobs], Callable[[FileJob], Mapping[str, Any] | None]], *,
               stream: BinaryIO | None = None) -> int:
    """worker 主循环：读 jobs、`start` 加载一次模型并返回逐文件处理函数；启动阶段任何异常返回 2。"""
    try:
        jobs = read_jobs(jobs_path)
        process = start(jobs)
    except Exception as error:
        emit_progress({"event": "startup_failed", "error_type": type(error).__name__, "message": str(error)}, stream)
        return EXIT_FATAL
    return run_jobs(jobs, process, stream=stream)


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
