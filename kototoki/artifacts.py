"""产物契约：工作目录、产物文件名、身份、匹配跳过、原子写、`failure.json` 与 `published.json`。

布局（规格 §4）::

    <output_dir>/<rel_dir>/<stem>.{ja,zh,ja-zh}.srt   最终 SRT，镜像输入目录层级
    <output_dir>/.work/lock                            编排器独占本输出目录
    <output_dir>/.work/index.json                      <id> ↔ 相对路径
    <output_dir>/.work/cache/                          HF_HOME／TORCH_HOME 与 model-verification.json
    <output_dir>/.work/<id>/                           单个视频的工作目录，文件名见下方常量

坐标约定（逐产物）：

- `probe.json`：ffprobe 快照，时间字段保持 ffprobe 原值；音轨 `start_time` 只作诊断。
- `vad.json`／`asr.json`／`align.json`：窗口、段、对齐记录一律是 WAV 本地秒与整数样本
  （16 kHz，sample 0 即视频 0 秒），顶层必须带 `offset_s`（产品恒为 0）。
  唯一例外是 `align.json` 的 `units[].start/end` 已含 `offset_s`（与现有 `result.json` 一致）。
- `ja-cues.json` 及三份 SRT：cue 时间是最终 SRT 时间（视频时间轴）。

JSON 产物的顶层固定为 `{"identity": {...}, ...payload}`。身份只由内容摘要、配方 hash 与
影响输出的配置键组成，绝对路径不参与；身份匹配即跳过，不匹配时原地原子替换
（翻译 run 目录由翻译子系统按 `ja.srt` 的 SHA 分键另建，不替换）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
from typing import Any

WORK_DIR = ".work"
INDEX = "index.json"
LOCK = "lock"
CACHE_DIR = "cache"
MODEL_VERIFICATION = "model-verification.json"

PROBE = "probe.json"
AUDIO_COPY_STEM = "audio"  # 流复制音轨为 audio.<ext>，扩展名由容器映射决定（票据 02）
AUDIO_16K = "audio-16k.wav"
EXTRACT_LOG = "extract.log"
VAD = "vad.json"
ASR = "asr.json"
ALIGN = "align.json"
JA_CUES = "ja-cues.json"
PUBLISHED = "published.json"
FAILURE = "failure.json"
# cross 引擎的审计产物（两路原始结果与裁决记录）：不在 STAGE_ARTIFACTS，不参与 `is_current` 与阶段计划，
# 也不进 LOCAL_TIME_ARTIFACTS（该集合只约束经 `write_artifact` 写出、且被编排读偏移的阶段产物）。
ASR_W0 = "asr-w0.json"
ASR_X0 = "asr-x0.json"
ASR_JUDGE = "asr-judge.json"

# failure.json 记录"已完成产物"时按此顺序检查是否存在。
STAGE_ARTIFACTS = (PROBE, AUDIO_16K, VAD, ASR, ALIGN, JA_CUES, PUBLISHED)
# 顶层必须带 offset_s 的本地坐标产物。
LOCAL_TIME_ARTIFACTS = frozenset({VAD, ASR, ALIGN})

FINAL_SUFFIXES = {"ja": ".ja.srt", "zh": ".zh.srt", "ja-zh": ".ja-zh.srt"}

WORK_ID_LENGTH = 12
_SHA256 = re.compile(r"[0-9a-f]{64}")
# 视频身份里的 ffprobe 指纹只取这些字段；filename 与 tags 会随改名或重新封装变化，不参与。
PROBE_STREAM_KEYS = ("index", "codec_name", "channels", "channel_layout", "sample_rate", "start_time", "duration")


# --- 哈希与原子写 -------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def object_hash(value: Any) -> str:
    return sha256_bytes(canonical(value).encode("utf-8"))


REPLACE_ATTEMPTS = 20


def replace_with_retry(source: Path, target: Path, *, replace: Callable[[Any, Any], None] = os.replace,
                       sleep: Callable[[float], None] = time.sleep) -> None:
    """os.replace；Windows 上目标被播放器或扫描器短暂占用（PermissionError）时重试。"""
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            replace(source, target)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            sleep(min(0.5, 0.1 * (attempt + 1)))


def atomic_write_text(path: Path, text: str) -> None:
    """写同目录临时文件并 fsync，再原子替换目标；UTF-8 无 BOM、LF；失败时删除临时文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        replace_with_retry(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# --- 路径与工作目录 -----------------------------------------------------------------------

def _relative(relative: str | PurePosixPath) -> PurePosixPath:
    """输入目录内的相对路径，统一为正斜杠形式。"""
    path = PurePosixPath(str(relative).replace("\\", "/"))
    # 任何段含 ":" 都拒绝：盘符、驱动器相对路径与 NTFS 备用数据流。
    if path.is_absolute() or not path.parts or ".." in path.parts or any(":" in part for part in path.parts):
        raise ValueError(f"Expected a path relative to the input directory: {relative!r}")
    return path


def work_id(relative: str | PurePosixPath) -> str:
    """相对路径（含扩展名）UTF-8 的 SHA256 前 12 位。"""
    return sha256_bytes(_relative(relative).as_posix().encode("utf-8"))[:WORK_ID_LENGTH]


def work_root(output_dir: Path) -> Path:
    return Path(output_dir) / WORK_DIR


def model_cache_path(output_dir: Path) -> Path:
    return work_root(output_dir) / CACHE_DIR / MODEL_VERIFICATION


def register_work_dir(output_dir: Path, relative: str | PurePosixPath) -> Path:
    """返回并创建 `.work/<id>/`，在 `.work/index.json` 登记 id ↔ 相对路径；短 id 碰撞时报错。

    读改写 `index.json`，须由编排器在扫描阶段串行调用。
    """
    rel = _relative(relative).as_posix()
    identifier = work_id(rel)
    index_path = work_root(output_dir) / INDEX
    index = read_json(index_path) if index_path.is_file() else {}
    registered = index.get(identifier)
    if registered is not None and registered != rel:
        raise ValueError(f"Work id {identifier} collides: {registered!r} and {rel!r}")
    if registered is None:
        index[identifier] = rel
        atomic_write_json(index_path, dict(sorted(index.items())))
    directory = work_root(output_dir) / identifier
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def final_srt_paths(output_dir: Path, relative: str | PurePosixPath) -> dict[str, Path]:
    """三份最终 SRT 的路径，镜像输入目录层级：`S1/ep01.mkv` → `<out>/S1/ep01.ja.srt` 等。"""
    rel = _relative(relative)
    base = Path(output_dir).joinpath(*rel.parent.parts)
    return {kind: base / f"{rel.stem}{suffix}" for kind, suffix in FINAL_SUFFIXES.items()}


# --- 身份 ---------------------------------------------------------------------------------

def _sha256(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{what}: expected a lowercase SHA256 hex digest")
    return value


def probe_fingerprint(probe: Mapping[str, Any]) -> dict[str, Any]:
    """ffprobe `-show_streams -show_format` JSON 中参与身份的字段。"""
    streams = [{key: stream[key] for key in PROBE_STREAM_KEYS if key in stream} for stream in probe.get("streams", [])]
    return {"streams": streams, "format_duration": probe.get("format", {}).get("duration")}


def video_identity(input_dir: Path, relative: str | PurePosixPath, probe: Mapping[str, Any]) -> dict[str, Any]:
    """视频身份 = 相对路径＋大小＋修改时间＋ffprobe 指纹；不对整个视频算哈希。"""
    rel = _relative(relative)
    stat = Path(input_dir).joinpath(*rel.parts).stat()
    return {"relative_path": rel.as_posix(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "ffprobe": probe_fingerprint(probe)}


def derived_identity(*, upstream: Mapping[str, str], recipe_hash: str, models: Mapping[str, str] | None = None,
                     config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """派生产物身份 = 上游产物 SHA256＋配方 hash＋模型文件 SHA256＋影响输出的配置键（cue 规则、seed）。"""
    if not upstream:
        raise ValueError("A derived artifact needs at least one upstream SHA256")
    return {
        "upstream": {name: _sha256(value, f"upstream {name}") for name, value in sorted(upstream.items())},
        "recipe_hash": _sha256(recipe_hash, "recipe_hash"),
        "models": {name: _sha256(value, f"model {name}") for name, value in sorted((models or {}).items())},
        "config": dict(config or {}),
    }


def verify_model(path: Path, expected: str, cache_path: Path, *,
                 hasher: Callable[[Path], str] = sha256_file) -> dict[str, Any]:
    """加载前核对模型文件完整 SHA256；size+mtime 未变时复用缓存记录，不重算（取自 v3 `verify_model`）。"""
    path = Path(path)
    stat = path.stat()
    key = {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    cache = read_json(cache_path) if Path(cache_path).is_file() else {}
    entry = cache.get(key["path"])
    if entry and entry.get("size") == key["size"] and entry.get("mtime_ns") == key["mtime_ns"] \
            and entry.get("sha256") == expected:
        return {**key, "sha256": expected, "method": "cached-size-mtime", "verified_at_utc": entry["verified_at_utc"]}
    started = time.perf_counter()
    digest = hasher(path)
    if digest != expected:
        raise ValueError(f"Model SHA256 mismatch for {path.name}: {digest} != {expected}")
    record = {**key, "sha256": digest, "verified_at_utc": utc_now(), "seconds": time.perf_counter() - started}
    cache[key["path"]] = record
    atomic_write_json(cache_path, cache)
    return {**record, "method": "computed"}


# --- JSON 产物 ----------------------------------------------------------------------------

def write_artifact(path: Path, identity: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    """原子写出 `{"identity": ..., **payload}`；已存在的同名产物被原地替换。"""
    path = Path(path)
    if "identity" in payload:
        raise ValueError("Payload must not carry its own identity key")
    if path.name in LOCAL_TIME_ARTIFACTS:
        offset = payload.get("offset_s")
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset):
            raise ValueError(f"{path.name} must record a finite top-level offset_s")
    atomic_write_json(path, {"identity": dict(identity), **payload})


def is_current(path: Path, expected_identity: Mapping[str, Any]) -> bool:
    """产物存在、可解析且身份与期望完全相同时返回 True（调用方据此跳过该阶段）。"""
    try:
        artifact = read_json(path)
    except (OSError, ValueError):
        return False
    return isinstance(artifact, dict) and artifact.get("identity") == json.loads(canonical(expected_identity))


def write_failure(work_dir: Path, stage: str, error: BaseException) -> None:
    """写 `failure.json`：失败阶段、异常类型与消息、已存在的阶段产物；不含音频与转写内容。"""
    work_dir = Path(work_dir)
    atomic_write_json(work_dir / FAILURE, {
        "stage": stage, "error_type": type(error).__name__, "message": str(error),
        "completed": [name for name in STAGE_ARTIFACTS if (work_dir / name).exists()],
        "failed_at_utc": utc_now(),
    })


# --- 发布记录与覆盖规则 -----------------------------------------------------------------------

def read_published(work_dir: Path) -> dict[str, Any] | None:
    path = Path(work_dir) / PUBLISHED
    return read_json(path) if path.is_file() else None


def record_published(work_dir: Path, final_paths: Mapping[str, Path], sha256: Mapping[str, str],
                     sources: Mapping[str, Any], translate_dir: str) -> None:
    """在 `publish_blockers` 放行之后、移动三份最终 SRT **之前**写 `published.json`。

    此刻最终位置上已有文件的 SHA 记为 `previous_sha256`：若写记录后、移动完成前崩溃（可连续多次），
    最终位置上残留的旧文件仍被认作未改动，不会误拒。
    """
    if set(sha256) != set(FINAL_SUFFIXES) or set(final_paths) != set(FINAL_SUFFIXES):
        raise ValueError(f"published.json needs exactly the files and SHA256 of {sorted(FINAL_SUFFIXES)}")
    atomic_write_json(Path(work_dir) / PUBLISHED, {
        "sha256": {kind: _sha256(sha256[kind], kind) for kind in FINAL_SUFFIXES},
        "previous_sha256": {kind: sha256_file(path) for kind, path in final_paths.items() if Path(path).exists()},
        "sources": dict(sources), "translate_dir": translate_dir, "published_at_utc": utc_now(),
    })


def publish_blockers(final_paths: Mapping[str, Path], work_dir: Path, *, force: bool) -> list[str]:
    """返回阻止发布的最终文件种类；空列表即可替换。

    现有最终文件不存在，或其 SHA256 等于 `published.json` 的记录，视为未被改动；
    任一存在且对不上记录（含没有记录）即视为用户改动，`force=False` 时阻止发布。
    """
    if force:
        return []
    record = read_published(work_dir) or {}
    blockers = []
    for kind, path in final_paths.items():
        if not Path(path).exists():
            continue
        known = {(record.get(field) or {}).get(kind) for field in ("sha256", "previous_sha256")}
        if sha256_file(path) not in known:
            blockers.append(kind)
    return blockers
