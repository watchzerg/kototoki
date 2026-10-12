"""Source-only SRT identity, complete batch coverage, and strict delivery.

No inference, reference subtitles, or quality judgments belong in this module.
Times remain source display anchors; diagnostics do not assert acoustic truth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Literal


_TIME = re.compile(
    r"^(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})[ \t]+-->[ \t]+"
    r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})$"
)
_END = re.compile(r"[。！？!?…\.][\"'」』）)\]】]*\s*(?:</[^>]+>\s*)*$")


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


@dataclass(frozen=True)
class Batch:
    id: str
    source_sha256: str
    targets: tuple[SourceCue, ...]
    before: tuple[SourceCue, ...]
    after: tuple[SourceCue, ...]

    @property
    def target_ids(self) -> tuple[str, ...]:
        return tuple(cue.id for cue in self.targets)

    @property
    def readonly_ids(self) -> tuple[str, ...]:
        return tuple(cue.id for cue in self.before + self.after)

    def to_window(self) -> dict[str, Any]:
        """Produce only the existing adapter's permitted model-input fields."""
        return {
            "id": self.id,
            "source_language": "ja",
            "target_language": "zh-Hans",
            "context": [
                {"id": cue.id, "text": cue.text}
                for cue in self.before + self.targets + self.after
            ],
            "translate_ids": list(self.target_ids),
        }


def _milliseconds(parts: tuple[str, ...]) -> int:
    hours, minutes, seconds, millis = map(int, parts)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_srt(
    text: str, *, source_sha256: str | None = None, encoding: str = "utf-8"
) -> SourceDocument:
    """Parse strictly, retaining original index, time line, tags and text.

    A supplied SHA is the exact source-byte digest from ``read_srt``. For a
    string-only input, provenance is its UTF-8 bytes. Newline normalization
    affects logical text only, never the source digest. Empty cues, duplicate
    integer indices, malformed timestamps, and nonpositive durations fail.
    Overlaps and nonchronological ordering are retained as diagnostics.
    """
    digest = source_sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("source_sha256 must be a lowercase SHA256 hex digest")
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    content = normalized.strip("\n")
    if not content.strip():
        raise ValueError("SRT contains no cues")
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
            # Compact prompt alias; full identity is (source_sha256, cue.id).
            id=f"{digest[:8]}-cue-{index}", ordinal=ordinal, index=index,
            index_text=lines[0], time_line=lines[1], start_ms=start, end_ms=end,
            text=body,
        ))
    return SourceDocument(digest, tuple(cues), encoding)


def read_srt(path: Path | str, *, encoding: str = "utf-8-sig") -> SourceDocument:
    """Read a source without guessing encoding or altering its bytes."""
    source = Path(path).resolve()
    raw = source.read_bytes()
    parsed = parse_srt(raw.decode(encoding), source_sha256=hashlib.sha256(raw).hexdigest(), encoding=encoding)
    return SourceDocument(parsed.source_sha256, parsed.cues, encoding, str(source))


def plan_batches(
    document: SourceDocument, *, target_size: int = 5, context_size: int = 1,
    policy: Literal["fixed", "natural"] = "fixed", gap_ms: int = 1000,
) -> tuple[Batch, ...]:
    """Cover each target once, with source-only adjacent read-only context.

    Natural packing chooses the latest punctuation or positive time-gap
    boundary within the target cap. These are source-text heuristics, not
    detected speakers/scenes or a token-budget guarantee.
    """
    if type(target_size) is not int or target_size < 1:
        raise ValueError("target_size must be a positive integer")
    if type(context_size) is not int or context_size < 0:
        raise ValueError("context_size must be a nonnegative integer")
    if policy not in {"fixed", "natural"}:
        raise ValueError("policy must be fixed or natural")
    if type(gap_ms) is not int or gap_ms < 0:
        raise ValueError("gap_ms must be a nonnegative integer")
    cues = document.cues
    batches = []
    start = 0
    while start < len(cues):
        stop = min(start + target_size, len(cues))
        if policy == "natural" and stop < len(cues):
            for boundary in range(stop, start, -1):
                previous, following = cues[boundary - 1], cues[boundary]
                gap = following.start_ms - previous.end_ms
                if _END.search(previous.text) or (gap > 0 and gap >= gap_ms):
                    stop = boundary
                    break
        batches.append(Batch(
            id=f"flow-{document.source_sha256}-{len(batches) + 1:04d}",
            source_sha256=document.source_sha256,
            targets=cues[start:stop],
            before=cues[max(0, start - context_size):start],
            after=cues[stop:stop + context_size],
        ))
        start = stop
    return tuple(batches)


def validate_translations(document: SourceDocument, translations: Mapping[str, str]) -> dict[str, Any]:
    """Report exact ID coverage; absent/empty results never inherit source text."""
    expected = {cue.id for cue in document.cues}
    actual = set(translations)
    invalid = []
    for cue_id in sorted(expected & actual):
        text = translations[cue_id]
        if not isinstance(text, str) or not text.strip():
            invalid.append({"id": cue_id, "reason": "empty_or_nonstring_text"})
        elif any(not line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
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
    """Carry partial-delivery evidence without manufacturing a success SRT."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("SRT export requires a complete exact ID mapping; inspect .report")


def render_srt(document: SourceDocument, translations: Mapping[str, str]) -> str:
    report = validate_translations(document, translations)
    if report["status"] != "complete":
        raise IncompleteTranslationError(report)
    blocks = []
    for cue in document.cues:
        text = translations[cue.id].replace("\r\n", "\n").replace("\r", "\n")
        blocks.append(f"{cue.index_text}\n{cue.time_line}\n{text}")
    return "\n\n".join(blocks) + "\n"


def write_srt(document: SourceDocument, translations: Mapping[str, str], path: Path | str) -> None:
    """Write a complete new UTF-8 output; refuse source and existing outputs."""
    rendered = render_srt(document, translations)
    output = Path(path).resolve()
    if document.source_path and output == Path(document.source_path).resolve():
        raise ValueError("Output must not replace the source SRT")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)


def source_provenance(document: SourceDocument) -> dict[str, Any]:
    """Serializable source mapping suitable for a local run sidecar."""
    return {
        "source_sha256": document.source_sha256,
        "source_path": document.source_path, "encoding": document.encoding,
        "timing_origin": "source_srt_display_cue",
        "text_offsets": "Unicode code points; half-open original logical text",
        "cues": [
            {"id": cue.id, "ordinal": cue.ordinal, "index": cue.index,
             "index_text": cue.index_text, "time_line": cue.time_line,
             "start_ms": cue.start_ms, "end_ms": cue.end_ms,
             "source_span": [0, len(cue.text)]}
            for cue in document.cues
        ],
    }


def diagnostics(document: SourceDocument, translations: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Raw order/overlap and code-point display metrics, without pass thresholds.

    Counts include spaces and markup code points, exclude newline characters,
    and do not pretend to measure rendered glyph width or visible graphemes.
    """
    if translations is not None:
        report = validate_translations(document, translations)
        if report["status"] != "complete":
            raise IncompleteTranslationError(report)
    rows = []
    for cue in document.cues:
        text = cue.text if translations is None else translations[cue.id]
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lengths = [len(line) for line in lines]
        count = sum(lengths)
        rows.append({"id": cue.id, "duration_ms": cue.end_ms - cue.start_ms,
                     "codepoint_count": count, "line_count": len(lines),
                     "line_codepoint_lengths": lengths,
                     "codepoints_per_second": count * 1000 / (cue.end_ms - cue.start_ms)})
    overlaps = []
    active: list[SourceCue] = []
    for cue in sorted(document.cues, key=lambda cue: (cue.start_ms, cue.ordinal)):
        active = [other for other in active if other.end_ms > cue.start_ms]
        for other in active:
            overlaps.append({"ids": [other.id, cue.id],
                             "overlap_ms": min(other.end_ms, cue.end_ms) - cue.start_ms})
        active.append(cue)
    order = []
    for previous, following in zip(document.cues, document.cues[1:]):
        if following.start_ms < previous.start_ms:
            order.append({"ids": [previous.id, following.id], "reason": "start_time_decreases"})
        if following.index <= previous.index:
            order.append({"ids": [previous.id, following.id], "reason": "index_decreases"})
    return {"source_sha256": document.source_sha256, "cues": rows,
            "overlaps": overlaps, "order_issues": order,
            "counting": "Unicode code points including spaces/markup; excluding line breaks",
            "thresholds": None, "timing_origin": "source_srt_display_cue"}
