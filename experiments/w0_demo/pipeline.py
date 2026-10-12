"""Backend-independent orchestration for the reusable W0 demo."""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Protocol

from kototoki_eval.schema import validate_transcript
from . import RECIPE
from .alignment import sample_window


class Vad(Protocol):
    metadata: dict[str, Any]
    def segment(self, audio: Any) -> list[dict[str, Any]]: ...


class Asr(Protocol):
    metadata: dict[str, Any]
    def transcribe(self, audio: Any, chunks: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]: ...
    def close(self) -> None: ...


class Aligner(Protocol):
    metadata: dict[str, Any]
    def align(self, audio: Any, segments: list[dict], offset: float = 0) -> dict: ...
    def close(self) -> None: ...


def validate_chunks(chunks: list[dict], duration: float) -> None:
    previous = 0.0
    for chunk in chunks:
        start, end = chunk["start"], chunk["end"]
        exact = sample_window(chunk, round(duration * 16000))
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in (start, end)) or not previous <= start < end <= duration
                or (exact[1] - exact[0] if exact is not None else
                    int(end * 16000) - int(start * 16000)) > 480000):
            raise ValueError("VAD chunks must be ordered, nonoverlapping source windows of at most 30 seconds")
        previous = end


def run_pipeline(audio: Any, vad: Vad, asr_factory: Callable[[], Asr],
                 aligner_factory: Callable[[], Aligner], *, offset: float = 0) -> dict:
    """Process one prepared input; factories allow sequential GPU residency."""
    if isinstance(offset, bool) or not math.isfinite(offset) or offset < 0 or len(audio) == 0:
        raise ValueError("Nonempty audio and a finite nonnegative source offset are required")
    stages: dict[str, float] = {}
    started = mark = time.perf_counter()
    try:
        chunks = vad.segment(audio)
        validate_chunks(chunks, len(audio) / 16000)
        stages["vad_s"] = time.perf_counter() - mark
        metadata = {"vad": dict(vad.metadata)}
    finally:
        close_vad = getattr(vad, "close", None)
        if close_vad:
            close_vad()
    original, traces = [], []
    aligned = {"text": "", "units": [], "records": [], "derived_segments": []}
    if chunks:
        mark = time.perf_counter()
        asr = asr_factory()
        stages["asr_load_s"] = time.perf_counter() - mark
        try:
            mark = time.perf_counter()
            original, traces = asr.transcribe(audio, chunks)
            stages["asr_inference_s"] = time.perf_counter() - mark
            metadata["asr"] = dict(asr.metadata)
        finally:
            asr.close()
        mark = time.perf_counter()
        aligner = aligner_factory()
        stages["alignment_load_s"] = time.perf_counter() - mark
        try:
            mark = time.perf_counter()
            aligned = aligner.align(audio, original, offset)
            stages["alignment_inference_s"] = time.perf_counter() - mark
            metadata["alignment"] = dict(aligner.metadata)
        finally:
            aligner.close()
    text = "".join(s["text"] for s in original)
    if aligned["text"] != text:
        raise ValueError("Alignment must preserve the complete ASR text")
    result = {"schema_version": 1, "recipe": RECIPE, "route": "W0", "status": "ok",
              "text": text, "units": aligned["units"], "cues": [],
              "original_segments": original, "chunks": chunks, "asr_traces": traces,
              "alignment_records": aligned["records"],
              "derived_segments": aligned["derived_segments"],
              "effective_parameters": metadata, "offset_s": offset,
              "source_start_seconds": offset, "duration_seconds": len(audio) / 16000,
              "source_end_seconds": offset + len(audio) / 16000,
              "stages": stages, "cached_inference": False, "offline_requested": True}
    validate_transcript(result)
    covered = [0] * len(text)
    for unit in result["units"]:
        for index in range(unit["char_start"], unit["char_end"]):
            covered[index] += 1
        if unit["status"] == "ok" and not (
                isinstance(unit.get("start"), (int, float)) and isinstance(unit.get("end"), (int, float))
                and math.isfinite(unit["start"]) and math.isfinite(unit["end"])
                and offset <= unit["start"] <= unit["end"] <= offset + len(audio) / 16000 + .001):
            raise ValueError("Timed units must remain inside the source input")
    if any(count != 1 for count in covered):
        raise ValueError("Alignment units must account for every original character exactly once")
    stages["total_pipeline_s"] = time.perf_counter() - started
    return result
