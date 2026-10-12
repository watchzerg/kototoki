"""Preserve source offsets through the slplab model card's pykakasi reading path."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import math
from typing import Any, Callable, Mapping, Sequence
import unicodedata


@dataclass(frozen=True)
class ReadingRange:
    original_start: int
    original_end: int
    target_start: int
    target_end: int
    original: str
    reading: str


@dataclass(frozen=True)
class ReadingTarget:
    original_text: str
    target_text: str
    ranges: tuple[ReadingRange, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _lexical(char: str) -> bool:
    return unicodedata.category(char)[0] in {"L", "N"}


def _kana_form(char: str) -> str:
    normalized = unicodedata.normalize("NFKC", char)
    return "".join(chr(ord(c) - 0x60) if "\u30a1" <= c <= "\u30f6" else c for c in normalized)


@lru_cache(maxsize=1)
def _native_converter() -> Callable[[str], Sequence[Mapping[str, str]]]:
    from pykakasi import kakasi
    return kakasi().convert


def convert_to_hiragana(
    text: str,
    converter: Callable[[str], Sequence[Mapping[str, str]]] | None = None,
) -> ReadingTarget:
    """Apply the native card recipe, preserving rather than guessing lexical readings.

    pykakasi is loaded only when used. It does not provide contextual disambiguation;
    unchanged Latin letters/digits and unknown readings remain visible to the CTC
    vocabulary check. The converter must partition its exact input monotonically.
    """
    if converter is None:
        converter = _native_converter()
    kept = [(index, char) for index, char in enumerate(text) if char not in "\u3001,\u3002"]
    while kept and kept[0][1].isspace():
        kept.pop(0)
    while kept and kept[-1][1].isspace():
        kept.pop()
    cleaned = "".join(char for _, char in kept)
    if not cleaned:
        return ReadingTarget(text, "", ())
    cursor = 0
    target = ""
    ranges: list[ReadingRange] = []
    for chunk in converter(cleaned):
        original, reading = chunk.get("orig"), chunk.get("hira")
        if not isinstance(original, str) or not original or not isinstance(reading, str):
            raise ValueError("Reading converter returned malformed or empty source chunk")
        end = cursor + len(original)
        if cleaned[cursor:end] != original:
            raise ValueError("Reading converter changed or reordered its source input")
        source_start, source_end = kept[cursor][0], kept[end - 1][0] + 1
        target_start = len(target)
        target += reading
        # Direct kana identities are genuinely one-to-one. Kanji readings and
        # other expansions stay one whole original range, with no equal splits.
        direct = (len(original) == len(reading)
                  and all(_kana_form(a) == b for a, b in zip(original, reading)))
        if direct:
            for offset, (a, b) in enumerate(zip(original, reading)):
                position = kept[cursor + offset][0]
                ranges.append(ReadingRange(position, position + 1,
                                           target_start + offset, target_start + offset + 1, a, b))
        else:
            ranges.append(ReadingRange(source_start, source_end, target_start, len(target),
                                       text[source_start:source_end], reading))
        cursor = end
    if cursor != len(cleaned):
        raise ValueError("Reading converter omitted source input")
    return ReadingTarget(text, target, tuple(ranges))


def map_reading_spans(target: ReadingTarget, token_spans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Map proven kana spans to characters or whole words, never invented char times.

    Token spans use target char_start/char_end and second-valued start/end. A range
    is timed only when every lexical target position is covered by accepted finite
    nonoverlapping spans. Multi-character original ranges retain word granularity.
    """
    chars = [{"char": char, "start": None, "end": None, "score": None,
              "evidence_kind": "missing_reading_alignment",
              "time_semantics": "phonetic_ctc_nonblank_span"} for char in target.original_text]
    words: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    for source in target.ranges:
        row = asdict(source)
        required = {i for i in range(source.target_start, source.target_end)
                    if _lexical(target.target_text[i])}
        selected = []
        covered: set[int] = set()
        previous_end = -math.inf
        valid = bool(required)
        for token in token_spans:
            lo, hi = token.get("char_start"), token.get("char_end")
            if (not isinstance(lo, int) or isinstance(lo, bool)
                    or not isinstance(hi, int) or isinstance(hi, bool) or not 0 <= lo < hi <= len(target.target_text)):
                raise ValueError("Token span does not address reading target")
            if not required.intersection(range(lo, hi)):
                continue
            begin, finish = token.get("start"), token.get("end")
            timed = (all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                         for v in (begin, finish)) and 0 <= begin < finish and begin >= previous_end)
            contained = source.target_start <= lo < hi <= source.target_end
            accepted = token.get("lexical_interval_accepted", False) and timed and contained
            if not accepted or covered.intersection(range(lo, hi)):
                valid = False
            else:
                selected.append(token)
                covered.update(range(lo, hi))
                previous_end = finish
        valid = valid and required <= covered
        row["status"] = "ok" if valid else ("ignored" if not any(_lexical(c) for c in source.original) else "unaligned")
        row["granularity"] = "character" if source.original_end - source.original_start == 1 else "word"
        row["start"] = selected[0]["start"] if valid else None
        row["end"] = selected[-1]["end"] if valid else None
        scores = [t["score"] for t in selected if isinstance(t.get("score"), (int, float))
                  and not isinstance(t["score"], bool) and math.isfinite(t["score"])]
        row["score"] = min(scores) if scores and valid else None
        mapping.append(row)
        if row["granularity"] == "character":
            chars[source.original_start].update(start=row["start"], end=row["end"], score=row["score"],
                                                evidence_kind="reading_character_span" if valid else row["status"])
        else:
            words.append({"word": source.original, "start": row["start"], "end": row["end"],
                          "score": row["score"], "char_start": source.original_start,
                          "char_end": source.original_end, "status": "ok" if valid else "text_only",
                          "time_semantics": "phonetic_ctc_word_envelope"})
            for position in range(source.original_start, source.original_end):
                chars[position]["evidence_kind"] = "reading_word_span" if valid else row["status"]
    return {"text": target.original_text, "chars": chars, "words": words,
            "reading_mapping": mapping, "reading_target": target.target_text}
