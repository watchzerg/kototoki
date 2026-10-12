"""Character provenance and the backend-neutral JSON contract."""

import math
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Normalized:
    text: str
    raw_spans: tuple[tuple[int, int], ...]


def normalize(text: str) -> Normalized:
    """NFKC, remove Unicode punctuation/whitespace, retain source offsets.

    Combining marks and halfwidth Japanese voicing marks share a source cluster.
    Reject uncommon cross-cluster compositions rather than misrepresent offsets.
    """
    clusters: list[tuple[str, int, int]] = []
    for index, char in enumerate(text):
        if clusters and (unicodedata.combining(char) or char in "\uff9e\uff9f"):
            prior, start, _ = clusters[-1]
            clusters[-1] = (prior + char, start, index + 1)
        else:
            clusters.append((char, index, index + 1))
    parts = [(unicodedata.normalize("NFKC", value), start, end)
             for value, start, end in clusters]
    if "".join(value for value, _, _ in parts) != unicodedata.normalize("NFKC", text):
        raise ValueError("Unsupported cross-cluster NFKC composition; review source mapping")
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    for value, start, end in parts:
        for char in value:
            if char.isspace() or unicodedata.category(char).startswith("P"):
                continue
            chars.append(char)
            offsets.append((start, end))
    return Normalized("".join(chars), tuple(offsets))


def finite_time(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_transcript(document: dict[str, Any]) -> None:
    if document.get("schema_version") != 1 or not isinstance(document.get("text"), str):
        raise ValueError("Transcript requires schema_version=1 and complete text")
    for key in ("source_start_seconds", "source_end_seconds", "duration_seconds"):
        if key in document and (not finite_time(document[key]) or document[key] < 0):
            raise ValueError("Source coordinate bounds must be finite nonnegative seconds")
    if document.get("source_end_seconds", math.inf) < document.get("source_start_seconds", 0):
        raise ValueError("Source end precedes source start")
    for unit in document.get("units", []):
        a, b = unit.get("char_start"), unit.get("char_end")
        if (not isinstance(a, int) or not isinstance(b, int)
                or not 0 <= a < b <= len(document["text"])):
            raise ValueError("Unit character ranges must address complete original text")
        if unit.get("granularity") not in {"word", "character", "segment"}:
            raise ValueError("Unit granularity must be word, character, or segment")
        if unit.get("time_source", "native") not in {"native", "api", "fallback", "interpolated"}:
            raise ValueError("Unknown time provenance")
        if unit.get("status", "ok") not in {"ok", "failed", "text_only"}:
            raise ValueError("Unknown unit status")


def from_segments(segments: list[dict[str, Any]], *, time_source: str = "api") -> dict[str, Any]:
    """Adapt segment dictionaries while preserving complete text and missing words.

    Words must contain exact text located monotonically in their segment. A failed
    exact lookup is left coarse; it is never forced onto a guessed character span.
    """
    text = ""
    units: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    issues: list[str] = []
    for segment in segments:
        value = segment.get("text", "")
        base = len(text)
        text += value
        cues.append({"text": value, "start": segment.get("start"), "end": segment.get("end")})
        if value:
            units.append({"char_start": base, "char_end": len(text),
                          "start": segment.get("start"), "end": segment.get("end"),
                          "granularity": "segment", "time_source": time_source,
                          "status": segment.get("status", "ok")})
        cursor = 0
        for word in segment.get("words", []) or []:
            word_text = word.get("word", word.get("text", ""))
            if not word_text:
                continue
            local = value.find(word_text, cursor)
            if local < 0:
                issues.append("word_text_not_found")
                continue
            units.append({"char_start": base + local, "char_end": base + local + len(word_text),
                          "start": word.get("start"), "end": word.get("end"),
                          "granularity": "word", "time_source": time_source,
                          "status": word.get("status", "ok")})
            cursor = local + len(word_text)
    return {"schema_version": 1, "text": text, "units": units, "cues": cues,
            "adapter_issues": issues}


def map_time(time: float, pieces: list[dict[str, Any]], *, boundary: str) -> float:
    """Restore source seconds through explicit piecewise sample mappings.

    Each piece maps [processed_start_sample, processed_end_sample] to
    source_start_sample with separate processed/source rates. Boundary side
    disambiguates VAD concatenation joins. Negative padding must be represented
    by explicit pieces; times outside real source support are rejected.
    """
    if boundary not in {"start", "end"} or not finite_time(time):
        raise ValueError("Invalid boundary/time")
    previous_processed_end = previous_source_end = None
    for piece in pieces:
        values = [piece[key] for key in ("processed_rate", "source_rate", "processed_start_sample",
                                         "processed_end_sample", "source_start_sample")]
        if not all(finite_time(v) for v in values):
            raise ValueError("Sample mapping fields must be finite numbers")
        pr, sr, lo, hi, source = values
        if pr <= 0 or sr <= 0 or not 0 <= lo < hi or source < 0:
            raise ValueError("Sample mapping requires positive rates and nonnegative positive support")
        processed_start, processed_end = lo / pr, hi / pr
        source_start, source_end = source / sr, source / sr + (hi - lo) / pr
        if ((previous_processed_end is not None and processed_start < previous_processed_end)
                or (previous_source_end is not None and source_start < previous_source_end)):
            raise ValueError("Sample mapping pieces must be ordered without overlapping support")
        previous_processed_end, previous_source_end = processed_end, source_end
    matches = []
    for piece in pieces:
        pr, sr = piece["processed_rate"], piece["source_rate"]
        if pr <= 0 or sr <= 0:
            raise ValueError("Sample rates must be positive")
        sample = time * pr
        lo, hi = piece["processed_start_sample"], piece["processed_end_sample"]
        if lo <= sample <= hi:
            matches.append((piece, sample))
    if not matches:
        raise ValueError("Time lies outside mapped source audio (possibly padding)")
    piece, sample = matches[-1] if boundary == "start" else matches[0]
    return (piece["source_start_sample"] / piece["source_rate"]
            + (sample - piece["processed_start_sample"]) / piece["processed_rate"])
