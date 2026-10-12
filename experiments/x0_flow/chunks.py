"""Deterministic source-preserving chunk plans; no model imports."""
from __future__ import annotations

import math
from typing import Any

from experiments.w0_demo.pipeline import validate_chunks

RATE = 16000
MAX_SAMPLES = 30 * RATE
SEARCH_SAMPLES = 5 * RATE
RMS_SAMPLES = RATE // 10


def sample_seconds(sample: int) -> float:
    """Encode an integer boundary for W0's existing int(seconds * rate) crop."""
    seconds = sample / RATE
    if int(seconds * RATE) < sample:
        seconds = math.nextafter(seconds, math.inf)
    if int(seconds * RATE) != sample:
        raise ValueError("Cannot represent a source sample boundary")
    return seconds


def make_chunk(start: int, end: int) -> dict:
    return {"start": sample_seconds(start), "end": sample_seconds(end),
            "start_sample": start, "end_sample": end,
            "segments": [[sample_seconds(start), sample_seconds(end)]]}


def validate_sample_coverage(chunks: list[dict], samples: int, *, retain_all: bool) -> None:
    """Reject loss, overlap, oversized windows and mismatched seconds/samples."""
    validate_chunks(chunks, samples / RATE)
    cursor = 0
    for chunk in chunks:
        start, end = chunk["start_sample"], chunk["end_sample"]
        if (not isinstance(start, int) or not isinstance(end, int)
                or not cursor <= start < end <= samples or end - start > MAX_SAMPLES
                or int(chunk["start"] * RATE) != start or int(chunk["end"] * RATE) != end):
            raise ValueError("Chunk sample bounds disagree with source-coordinate contract")
        if retain_all and start != cursor:
            raise ValueError("Retain-all plan lost source samples")
        cursor = end
    if retain_all and cursor != samples:
        raise ValueError("Retain-all plan lost source tail")


def fixed_chunks(samples: int) -> list[dict]:
    if not isinstance(samples, int) or isinstance(samples, bool) or samples <= 0:
        raise ValueError("Positive integer sample count required")
    chunks = [make_chunk(start, min(samples, start + MAX_SAMPLES))
              for start in range(0, samples, MAX_SAMPLES)]
    validate_sample_coverage(chunks, samples, retain_all=True)
    return chunks


def energy_chunks(audio: Any) -> list[dict]:
    """Search trailing 100 ms RMS on a 100 ms grid in the last 5 s of 30 s.

    Choose the latest boundary among equal minima. Leave the final <=30 s tail
    whole. No threshold, VAD, samples removed, concatenation or audio transform.
    """
    import numpy as np
    from experiments.w0_demo.vad import validate_audio

    validate_audio(audio)
    if not len(audio):
        raise ValueError("Nonempty audio required")
    chunks, start = [], 0
    while len(audio) - start > MAX_SAMPLES:
        maximum = start + MAX_SAMPLES
        candidates = range(maximum - SEARCH_SAMPLES, maximum + 1, RMS_SAMPLES)
        scored = [(float(np.mean(np.square(audio[cut - RMS_SAMPLES:cut], dtype=np.float64))), cut)
                  for cut in candidates]
        score, end = min(scored, key=lambda pair: (pair[0], -pair[1]))
        chunk = make_chunk(start, end)
        chunk["cut_evidence"] = {"policy": "minimum_trailing_100ms_rms_latest_tie",
                                 "rms": math.sqrt(score), "search_start_sample": maximum - SEARCH_SAMPLES,
                                 "search_end_sample": maximum, "grid_samples": RMS_SAMPLES}
        chunks.append(chunk)
        start = end
    chunks.append(make_chunk(start, len(audio)))
    validate_sample_coverage(chunks, len(audio), retain_all=True)
    return chunks
