"""Integer source-window contracts and retain-all deterministic segmentation."""
from __future__ import annotations

import math
from typing import Any

RATE = 16000
MAX_SAMPLES = 30 * RATE
SHORT_SAMPLES = 5 * RATE
GRID_SAMPLES = RATE // 10


def make_chunk(start: int, end: int) -> dict:
    return {"start_sample": start, "end_sample": end,
            "start": start / RATE, "end": end / RATE}


def validate_chunks(chunks: list[dict], samples: int, *, retain_all: bool = True) -> None:
    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        raise ValueError("Positive integer input sample count required")
    cursor = 0
    for chunk in chunks:
        start, end = chunk.get("start_sample"), chunk.get("end_sample")
        if (any(isinstance(v, bool) or not isinstance(v, int) for v in (start, end))
                or (start != cursor if retain_all else start < cursor)
                or not 0 <= start < end <= samples or end - start > MAX_SAMPLES):
            raise ValueError("Chunks must be ordered nonoverlapping source windows <=30 seconds")
        for key, expected in (("start", start / RATE), ("end", end / RATE)):
            value = chunk.get(key)
            if (isinstance(value, bool) or not isinstance(value, (float, int))
                    or not math.isfinite(value) or value != expected):
                raise ValueError("Seconds must describe exact integer source boundaries")
        cursor = end
    if retain_all and cursor != samples:
        raise ValueError("Chunk plan lost the source tail")


def fixed_chunks(samples: int) -> list[dict]:
    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        raise ValueError("Positive integer input sample count required")
    chunks = [make_chunk(start, min(samples, start + MAX_SAMPLES))
              for start in range(0, samples, MAX_SAMPLES)]
    validate_chunks(chunks, samples)
    return chunks


def merge_short_chunks(chunks: list[dict], samples: int) -> list[dict]:
    """Greedy adjacent candidate-span merge, preserving samples and evidence."""
    validate_chunks(chunks, samples)
    merged = []
    for original in chunks:
        chunk = dict(original)
        chunk["candidate_windows"] = [{"start_sample": chunk["start_sample"],
                                       "end_sample": chunk["end_sample"],
                                       "cut_evidence": chunk.get("cut_evidence")}]
        if merged:
            previous = merged[-1]
            if chunk["end_sample"] - previous["start_sample"] <= MAX_SAMPLES:
                previous.update(end_sample=chunk["end_sample"], end=chunk["end"])
                previous["candidate_windows"].extend(chunk["candidate_windows"])
                previous["merged_adjacent_candidates"] = True
                continue
        merged.append(chunk)
    validate_chunks(merged, samples)
    return merged


def cut_merge_chunks(audio: Any) -> list[dict]:
    """Choose one low-energy boundary per 5s source region, then merge <=30s.

    Dense candidates make merging meaningful. This is a new recipe, distinct
    from x0_flow's trailing-5s energy strategy and WhisperX's VAD logic.
    No silence threshold, filtering, waveform concatenation or model loading.
    """
    import numpy as np

    if (not isinstance(audio, np.ndarray) or audio.dtype != np.float32 or audio.ndim != 1
            or not len(audio) or not np.isfinite(audio).all()):
        raise ValueError("Finite nonempty mono float32 audio required")
    boundaries = [(0, None)]
    for region_start in range(0, len(audio), SHORT_SAMPLES):
        maximum = min(region_start + SHORT_SAMPLES, len(audio))
        if maximum == len(audio):
            break
        scored = [(float(np.mean(np.square(audio[cut - GRID_SAMPLES:cut], dtype=np.float64))), cut)
                  for cut in range(region_start + GRID_SAMPLES, maximum + 1, GRID_SAMPLES)]
        score, end = min(scored, key=lambda pair: (pair[0], -pair[1]))
        evidence = {"policy": "minimum_trailing_100ms_rms_latest_tie",
            "rms": math.sqrt(score), "search_start_sample": region_start + GRID_SAMPLES,
            "search_end_sample": maximum, "grid_samples": GRID_SAMPLES}
        boundaries.append((end, evidence))
    boundaries.append((len(audio), None))
    chunks = []
    for (start, _), (end, evidence) in zip(boundaries, boundaries[1:]):
        chunk = make_chunk(start, end)
        if evidence:
            chunk["cut_evidence"] = evidence
        chunks.append(chunk)
    return merge_short_chunks(chunks, len(audio))
