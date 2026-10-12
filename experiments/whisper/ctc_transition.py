"""Explicit transition-frame diagnostic for pinned WhisperX 3.8.6.

The native path/result stays unchanged. Derived intervals describe the frame at
which the trellis advances to a token; they are not spoken character durations.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import math
from typing import Any, Iterator


class TransitionRecorder:
    def __init__(self, segments: list[dict[str, Any]], dictionary: dict[str, int], duration: float):
        self.segments = segments
        self.dictionary = dictionary
        self.records: list[dict[str, Any]] = []
        self.eligible: list[tuple[int, list[int]]] = []
        for index, segment in enumerate(segments):
            text = segment["text"]
            leading = len(text) - len(text.lstrip())
            trailing = len(text) - len(text.rstrip())
            positions = [i for i, char in enumerate(text)
                         if leading <= i < len(text) - trailing
                         and (char.lower() in dictionary or char.lower() not in (" ", "|"))]
            if positions and segment["start"] < duration:
                self.eligible.append((index, positions))

    def observe(self, trellis: Any, emission: Any, tokens: list[int], blank_id: int, path: Any) -> None:
        call_index = len(self.records)
        if call_index >= len(self.eligible):
            raise ValueError("Unexpected WhisperX backtrack count; diagnostic mapping is unsupported")
        segment_index, positions = self.eligible[call_index]
        if len(positions) != len(tokens):
            raise ValueError("WhisperX token/character count mismatch; no derived timestamps inferred")
        record: dict[str, Any] = {"segment_index": segment_index, "frame_count": int(trellis.size(0) - 1),
                                  "blank_id": blank_id, "emission_sha256": hashlib.sha256(emission.numpy().tobytes()).hexdigest(),
                                  "emission_shape": list(emission.shape), "path_failed": path is None,
                                  "tokens": []}
        if path is not None:
            groups: dict[int, list[Any]] = {}
            previous_token = -1
            previous_frame = -1
            for point in path:
                if point.token_index < previous_token or point.time_index <= previous_frame:
                    raise ValueError("Unexpected non-monotonic native path; no derived timestamps inferred")
                previous_token, previous_frame = point.token_index, point.time_index
                groups.setdefault(point.token_index, []).append(point)
            for token_index, raw_pos in enumerate(positions):
                points = groups.get(token_index, [])
                # In this pinned recurrence a token group starts with its change
                # emission; every remaining point is a blank stay. Native
                # backtrack is called unchanged and the full path is retained.
                first = points[0] if points else None
                record["tokens"].append({"token_index": token_index, "original_position": raw_pos,
                                          "token_id": int(tokens[token_index]),
                                          "evidence_kind": "vocabulary_token" if self.segments[segment_index]["text"][raw_pos].lower() in self.dictionary else "wildcard",
                                          "transition_frame": int(first.time_index) if first is not None else None,
                                          "token_probability": float(first.score) if first is not None else None,
                                          "blank_stay_frames": max(0, len(points) - 1),
                                          "native_start_frame": int(points[0].time_index) if points else None,
                                          "native_end_frame": int(points[-1].time_index + 1) if points else None})
        self.records.append(record)

    def derived_segments(self) -> list[dict[str, Any]]:
        by_index = {record["segment_index"]: record for record in self.records}
        output = []
        for index, segment in enumerate(self.segments):
            record = by_index.get(index)
            evidence = {token["original_position"]: token for token in record["tokens"]} if record else {}
            chars = []
            for position, char in enumerate(segment["text"]):
                token = evidence.get(position)
                frame = token.get("transition_frame") if token else None
                ratio = (segment["end"] - segment["start"]) / record["frame_count"] if record and record["frame_count"] > 0 else None
                valid = (frame is not None and ratio is not None and math.isfinite(ratio) and ratio > 0
                         and 0 <= frame < record["frame_count"])
                chars.append({"char": char, "start": round(segment["start"] + frame * ratio, 3) if valid else None,
                              "end": round(segment["start"] + (frame + 1) * ratio, 3) if valid else None,
                              "score": token.get("token_probability") if token else None,
                              "evidence_kind": token.get("evidence_kind") if token else "missing",
                              "time_semantics": "ctc_transition_frame_interval"})
            output.append({"text": segment["text"], "start": segment["start"], "end": segment["end"], "chars": chars})
        return output


@contextmanager
def capture_transitions(module: Any, segments: list[dict[str, Any]], dictionary: dict[str, int],
                        duration: float, *, enabled: bool) -> Iterator[TransitionRecorder | None]:
    if not enabled:
        yield None
        return
    recorder = TransitionRecorder(segments, dictionary, duration)
    original = module.backtrack

    def wrapper(trellis: Any, emission: Any, tokens: list[int], blank_id: int = 0) -> Any:
        path = original(trellis, emission, tokens, blank_id)
        recorder.observe(trellis, emission, tokens, blank_id, path)
        return path

    module.backtrack = wrapper
    try:
        yield recorder
    finally:
        module.backtrack = original
