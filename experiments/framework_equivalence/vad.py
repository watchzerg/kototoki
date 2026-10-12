"""Independent replica of the measured min-cut and greedy merge semantics.

Algorithm: WhisperX 3.8.6 vads/pyannote.py Binarize (BSD-2), derived from
Pyannote hysteresis binarization; experimentally frozen defaults only.
Copyright (c) 2024 Max Bain; see THIRD_PARTY_NOTICES.txt for retained notice.
No padding or minimum-duration filters are active in the measured merge path.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from pyannote.core import Annotation, Segment


def merge_scores(scores: Any, chunk_size: float = 30, onset: float = .5,
                 offset: float = .363) -> list[dict]:
    """Reproduce strict thresholds, midpoint timestamps, latter-half min-cut."""
    if chunk_size <= 0:
        raise ValueError("Positive chunk_size required")
    timestamps = [scores.sliding_window[i].middle for i in range(len(scores.data))]
    if not timestamps:
        return []
    active = Annotation()
    for track, values in enumerate(scores.data.T):
        label = track if scores.labels is None else scores.labels[track]
        start = timestamps[0]
        is_active = values[0] > onset
        current_scores, current_times = [values[0]], [start]
        final_time = start
        for final_time, value in zip(timestamps[1:], values[1:]):
            if is_active:
                if final_time - start > chunk_size:
                    latter_half = len(current_scores) // 2
                    cut_index = latter_half + np.argmin(current_scores[latter_half:])
                    cut = current_times[cut_index]
                    active[Segment(start, cut), track] = label
                    start = cut
                    current_scores = current_scores[cut_index + 1:]
                    current_times = current_times[cut_index + 1:]
                elif value < offset:
                    active[Segment(start, final_time), track] = label
                    start, is_active = final_time, False
                    current_scores, current_times = [], []
                current_scores.append(value)
                current_times.append(final_time)
            elif value > onset:
                start, is_active = final_time, True
        if is_active:
            active[Segment(start, final_time), track] = label
    segments = list(active.get_timeline())
    if not segments:
        return []
    begin, end = segments[0].start, 0
    constituents, output = [], []
    for segment in segments:
        if segment.end - begin > chunk_size and end - begin > 0:
            output.append({"start": begin, "end": end, "segments": constituents})
            begin, constituents = segment.start, []
        end = segment.end
        constituents.append((segment.start, segment.end))
    output.append({"start": begin, "end": end, "segments": constituents})
    return output
