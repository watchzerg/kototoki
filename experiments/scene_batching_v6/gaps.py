"""Silence gaps between cues and how batches sit relative to them (pure functions, stdlib only).

A gap is ``start[i+1] - end[i]`` between consecutive cues of a scene (None when a timestamp is
missing). A batch "crosses" a gap of at least ``threshold`` seconds when both sides are target cues of
the same batch.
"""

from __future__ import annotations

from typing import Any, Sequence

Span = tuple[int, int]


def cue_gaps(cues: Sequence[dict[str, Any]]) -> list[float | None]:
    """gaps[i] = silence between cue i and cue i+1 (len = n-1)."""
    result = []
    for left, right in zip(cues, cues[1:]):
        if left.get("end") is None or right.get("start") is None:
            result.append(None)
        else:
            result.append(right["start"] - left["end"])
    return result


def is_cut(gap: float | None, threshold: float) -> bool:
    return gap is not None and gap >= threshold


def batch_segments(span: Span, gaps: Sequence[float | None], threshold: float) -> list[Span]:
    """Split a batch [start, stop) at every gap >= threshold inside it."""
    start, stop = span
    segments, low = [], start
    for i in range(start, stop - 1):
        if is_cut(gaps[i], threshold):
            segments.append((low, i + 1))
            low = i + 1
    segments.append((low, stop))
    return segments


def classify(spans: Sequence[Span], gaps: Sequence[float | None], threshold: float) -> dict[int, str]:
    """cue index -> "clean" | "majority" | "minority".

    clean: the batch crosses no gap >= threshold. Otherwise the largest segment is the majority side
    and every other segment the minority side; when the largest size is tied, all segments are
    minority (no side dominates the batch).
    """
    result = {}
    for span in spans:
        segments = batch_segments(span, gaps, threshold)
        if len(segments) == 1:
            result.update({i: "clean" for i in range(*span)})
            continue
        sizes = [b - a for a, b in segments]
        top = max(sizes)
        unique_top = sizes.count(top) == 1
        for (a, b), size in zip(segments, sizes):
            label = "majority" if unique_top and size == top else "minority"
            result.update({i: label for i in range(a, b)})
    return result


def gap_adjacent(spans: Sequence[Span], gaps: Sequence[float | None], threshold: float) -> dict[int, str]:
    """Cues directly before/after a gap >= threshold -> "in_batch" (the gap is inside a batch) or
    "boundary" (the gap falls exactly between two batches). A cue touching two such gaps with
    different labels is left out."""
    starts = {a for a, _ in spans}
    labels: dict[int, set[str]] = {}
    for i, gap in enumerate(gaps):
        if not is_cut(gap, threshold):
            continue
        label = "boundary" if i + 1 in starts else "in_batch"
        for cue in (i, i + 1):
            labels.setdefault(cue, set()).add(label)
    return {cue: next(iter(s)) for cue, s in labels.items() if len(s) == 1}


def clean_position(spans: Sequence[Span], gaps: Sequence[float | None], threshold: float) -> dict[int, str]:
    """Cues of batches (>= 3 cues) that cross no gap >= threshold -> "edge" (first/last) or "interior"."""
    result = {}
    for start, stop in spans:
        if stop - start < 3 or len(batch_segments((start, stop), gaps, threshold)) > 1:
            continue
        for i in range(start, stop):
            result[i] = "edge" if i in (start, stop - 1) else "interior"
    return result
