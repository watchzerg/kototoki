"""SRT 解析与写出：复制自 `experiments/translation_flow/srt.py`，改为允许零条目。

读取容忍 UTF-8 BOM，写出一律 UTF-8 无 BOM、LF。秒到毫秒的取整沿用
`experiments/display/replay.py` 的 `floor(x*1000+0.5)`（不用 Python `round`
的银行家舍入），见规格 §5.2。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Any

from kototoki.artifacts import atomic_write_text

_TIME = re.compile(
    r"^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})[ \t]+-->[ \t]+"
    r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$"
)


@dataclass(frozen=True)
class SourceCue:
    id: str
    ordinal: int
    index: int
    index_text: str
    time_line: str
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SourceDocument:
    source_sha256: str
    cues: tuple[SourceCue, ...]
    encoding: str
    source_path: str | None = None


def milliseconds(seconds: float) -> int:
    """秒 → 整数毫秒，半毫秒一律进位。"""
    return math.floor(seconds * 1000 + 0.5)


def srt_time(ms: int) -> str:
    if type(ms) is not int or ms < 0:
        raise ValueError("SRT time must be a nonnegative integer millisecond")
    hours, remainder = divmod(ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, fraction = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}"


def _milliseconds(parts: tuple[str, ...]) -> int:
    hours, minutes, seconds, millis = map(int, parts)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _check_text(text: Any, what: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{what}: empty subtitle text")
    text = _normalize_newlines(text)
    if any(not line.strip() for line in text.split("\n")):
        raise ValueError(f"{what}: blank text line would break SRT")
    return text


def parse_srt(text: str, *, source_sha256: str | None = None, encoding: str = "utf-8") -> SourceDocument:
    """严格解析，保留原编号、时间行与文字；空白输入得到零条目文档。

    传入的 SHA 是 `read_srt` 读到的原始字节摘要；只给字符串时以其 UTF-8 字节为准。
    空 cue、重复编号、格式错误的时间行与非正时长均报错；重叠与乱序保留不报错。
    """
    digest = source_sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("source_sha256 must be a lowercase SHA256 hex digest")
    content = _normalize_newlines(text.removeprefix("﻿")).strip("\n")
    if not content.strip():
        return SourceDocument(digest, (), encoding)
    blocks = re.split(r"\n[ \t]*\n(?:[ \t]*\n)*", content)
    cues = []
    seen = set()
    for ordinal, block in enumerate(blocks, 1):
        lines = block.split("\n")
        if len(lines) < 3 or not re.fullmatch(r"[0-9]+", lines[0]):
            raise ValueError(f"Cue {ordinal}: expected an index, time line, and nonempty text")
        index = int(lines[0])
        if index < 1 or index in seen:
            raise ValueError(f"Cue {ordinal}: invalid or duplicate SRT index {index}")
        match = _TIME.fullmatch(lines[1])
        if match is None:
            raise ValueError(f"Cue {ordinal}: invalid SRT time line")
        start = _milliseconds(match.groups()[:4])
        end = _milliseconds(match.groups()[4:])
        if end <= start:
            raise ValueError(f"Cue {ordinal}: end time must be after start time")
        body = "\n".join(lines[2:])
        if not body.strip() or any(not line.strip() for line in lines[2:]):
            raise ValueError(f"Cue {ordinal}: empty subtitle text or text line")
        seen.add(index)
        cues.append(SourceCue(
            # 提示里用的短别名；完整身份是 (source_sha256, cue.id)。
            id=f"{digest[:8]}-cue-{index}", ordinal=ordinal, index=index,
            index_text=lines[0], time_line=lines[1], start_ms=start, end_ms=end,
            text=body,
        ))
    return SourceDocument(digest, tuple(cues), encoding)


def read_srt(path: Path | str, *, encoding: str = "utf-8-sig") -> SourceDocument:
    """按给定编码读取，不猜编码；摘要取原始字节。"""
    source = Path(path).resolve()
    raw = source.read_bytes()
    parsed = parse_srt(raw.decode(encoding), source_sha256=hashlib.sha256(raw).hexdigest(), encoding=encoding)
    return SourceDocument(parsed.source_sha256, parsed.cues, encoding, str(source))


def format_srt(entries: Sequence[tuple[float, float, str]]) -> str:
    """把 (start_s, end_s, text) 序列写成 SRT 文本，编号从 1 起；零条目得到空串。"""
    blocks = []
    for number, (start_s, end_s, text) in enumerate(entries, 1):
        start, end = milliseconds(start_s), milliseconds(end_s)
        if start < 0 or end <= start:
            raise ValueError(f"Cue {number}: rounded end time must be after a nonnegative start")
        blocks.append(f"{number}\n{srt_time(start)} --> {srt_time(end)}\n{_check_text(text, f'Cue {number}')}")
    return "\n\n".join(blocks) + "\n" if blocks else ""


def validate_translations(document: SourceDocument, translations: Mapping[str, str]) -> dict[str, Any]:
    """按 ID 精确核对覆盖；缺失或空译文不会继承原文。"""
    expected = {cue.id for cue in document.cues}
    actual = set(translations)
    invalid = []
    for cue_id in sorted(expected & actual):
        text = translations[cue_id]
        if not isinstance(text, str) or not text.strip():
            invalid.append({"id": cue_id, "reason": "empty_or_nonstring_text"})
        elif any(not line.strip() for line in _normalize_newlines(text).split("\n")):
            invalid.append({"id": cue_id, "reason": "blank_text_line_would_break_srt"})
    missing = [cue.id for cue in document.cues if cue.id not in actual]
    unexpected = sorted(actual - expected, key=str)
    complete = not missing and not unexpected and not invalid
    return {
        "status": "complete" if complete else "partial",
        "source_sha256": document.source_sha256,
        "expected_count": len(expected),
        "valid_count": len(expected & actual) - len(invalid),
        "missing_ids": missing, "unexpected_ids": unexpected, "invalid": invalid,
    }


class IncompleteTranslationError(ValueError):
    """携带部分交付的核对报告，不伪造完整 SRT。"""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("SRT export requires a complete exact ID mapping; inspect .report")


def render_srt(document: SourceDocument, translations: Mapping[str, str]) -> str:
    """沿用原编号与时间行替换文字；零条目文档得到空串。"""
    report = validate_translations(document, translations)
    if report["status"] != "complete":
        raise IncompleteTranslationError(report)
    blocks = [f"{cue.index_text}\n{cue.time_line}\n{_normalize_newlines(translations[cue.id])}"
              for cue in document.cues]
    return "\n\n".join(blocks) + "\n" if blocks else ""


def write_srt(text: str, path: Path | str, *, source: SourceDocument | None = None) -> None:
    """原子写出 UTF-8 无 BOM；拒绝覆盖 `source` 本身。是否允许覆盖其他现有文件由调用方按发布规则判定。"""
    output = Path(path).resolve()
    if source is not None and source.source_path and output == Path(source.source_path).resolve():
        raise ValueError("Output must not replace the source SRT")
    atomic_write_text(output, text)
