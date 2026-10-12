"""Local W0 Pyannote scores and the frozen WhisperX 3.8.6 cut/merge policy.

Source: whisperx/vads/pyannote.py and vads/vad.py at v3.8.6 (BSD-2),
and pyannote.audio 4.0.7 VoiceActivityDetection (MIT). Retained notices are
in THIRD_PARTY_NOTICES.txt. The measured asset is the bundled 5-second,
non-powerset PyanNet, SHA256
0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea;
it is not segmentation-3.0. Provision this checkpoint separately.

No downloads, WhisperX imports, model loads, or optional imports occur at
module import. Only mono float32 16 kHz arrays are accepted. Cut/merge uses
the exact independent replica and Pyannote Annotation/Segment semantics.
This is a serial demo boundary,
not a general diarization or streaming API.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import math
from pathlib import Path
from typing import Any

from .alignment import sample_window

SAMPLE_RATE = 16000
MAX_CHUNK_SECONDS = 30.0


def validate_audio(audio: Any) -> None:
    """Reject conversions that would silently alter the measured PCM contract."""
    import numpy as np

    if not isinstance(audio, np.ndarray) or audio.ndim != 1 or audio.dtype != np.float32:
        raise ValueError("Expected a mono numpy float32 waveform at 16 kHz")
    if not np.isfinite(audio).all():
        raise ValueError("Audio must contain only finite samples")


def validate_chunks(chunks: list[dict[str, Any]], samples: int) -> list[dict[str, Any]]:
    """Validate raw source windows without rounding or changing their bounds."""
    result = copy.deepcopy(chunks)
    duration = samples / SAMPLE_RATE
    previous_end = 0.0
    for index, chunk in enumerate(result):
        try:
            start, end = float(chunk["start"]), float(chunk["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Chunk {index} requires numeric start/end") from exc
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= duration:
            raise ValueError(f"Chunk {index} falls outside the source waveform")
        if start < previous_end:
            raise ValueError(f"Chunk {index} overlaps or precedes the previous chunk")
        exact = sample_window(chunk, samples)
        count = exact[1] - exact[0] if exact is not None else int(end * SAMPLE_RATE) - int(start * SAMPLE_RATE)
        if not 0 < count <= int(MAX_CHUNK_SECONDS * SAMPLE_RATE):
            raise ValueError(f"Chunk {index} must crop 1..480000 source samples")
        previous_end = end
        spans = chunk.get("segments", [])
        span_end = start
        for span in spans:
            if not isinstance(span, (list, tuple)) or len(span) != 2:
                raise ValueError(f"Chunk {index} has an invalid constituent segment")
            left, right = map(float, span)
            if not math.isfinite(left) or not math.isfinite(right) or not start <= left < right <= end:
                raise ValueError(f"Chunk {index} has an out-of-bounds constituent segment")
            if left < span_end:
                raise ValueError(f"Chunk {index} has overlapping constituent segments")
            span_end = right
        chunk.update(start=start, end=end, segments=spans)
    return result


def merge_scores(scores: Any, chunk_size: float = 30, onset: float = .5,
                 offset: float = .363) -> list[dict]:
    """Reproduce strict thresholds, midpoint timestamps, latter-half min-cut."""
    import numpy as np
    from pyannote.core import Annotation, Segment

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


class FrozenVad:
    """Replay frozen raw windows; this is not evidence of fresh neural VAD."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = copy.deepcopy(chunks)
        self.metadata = {"kind": "frozen-vad", "fresh_inference": False,
                         "chunk_count": len(chunks)}

    def segment(self, audio: Any) -> list[dict[str, Any]]:
        validate_audio(audio)
        return validate_chunks(self._chunks, len(audio))

    def close(self) -> None:
        pass


class PyannoteVad:
    """Reuse the separately provisioned PyanNet with CUDA-only default Inference.

    Model.from_pretrained receives the local checkpoint, as in the measured
    WhisperX loader. Pyannote retains its training-window, 0.1-duration step,
    tail padding, Hamming aggregation, and crop behavior. Speaker scores are
    reduced before aggregation; pipeline binarization is deliberately absent.
    """

    def __init__(self, checkpoint: Path) -> None:
        self.checkpoint = Path(checkpoint).resolve()
        if not self.checkpoint.is_file():
            raise FileNotFoundError(f"Provision a local Pyannote checkpoint: {self.checkpoint}")
        self._inference: Any = None
        self._closed = False
        self.metadata: dict[str, Any] = {
            "kind": "pyannote", "checkpoint": str(self.checkpoint),
            "device_requested": "cuda:0", "onset": .5, "offset": .363,
            "chunk_size": 30, "min_duration_on": 0, "min_duration_off": 0,
            "fresh_inference": True, "loaded": False,
        }
        self._load()

    def _load(self) -> None:
        with self.checkpoint.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != "0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea":
            raise ValueError("VAD checkpoint differs from the measured W0 asset; provision the pinned checkpoint")
        import numpy as np
        import torch
        from pyannote.audio import Inference, Model

        if not torch.cuda.is_available():
            raise RuntimeError("Pyannote VAD requires a working CUDA GPU; CPU fallback is disabled")
        model = Model.from_pretrained(str(self.checkpoint), token=None)
        if model is None:
            raise RuntimeError("Pyannote could not load the provisioned local checkpoint")
        model.eval()
        inference = Inference(model, device=torch.device("cuda:0"),
                              pre_aggregation_hook=lambda scores: np.max(scores, axis=-1, keepdims=True))
        if inference.model.device.type != "cuda":
            raise RuntimeError("Pyannote loaded on a non-CUDA device")
        self._inference = inference
        self.metadata.update(loaded=True, checkpoint_sha256=checksum,
                             device=str(inference.model.device),
                             dtype=str(next(inference.model.parameters()).dtype),
                             window_duration=inference.duration, window_step=inference.step,
                             batch_size=inference.batch_size,
                             pyannote_audio=importlib.metadata.version("pyannote.audio"),
                             torch=importlib.metadata.version("torch"))

    def segment(self, audio: Any) -> list[dict[str, Any]]:
        if self._closed:
            raise RuntimeError("Pyannote VAD is closed")
        validate_audio(audio)
        if not len(audio):
            return []
        if self._inference is None:
            self._load()
        import torch

        scores = self._inference({"waveform": torch.from_numpy(audio).unsqueeze(0),
                                  "sample_rate": SAMPLE_RATE})
        self.metadata.update(scores_sha256=hashlib.sha256(scores.data.tobytes()).hexdigest(),
                             scores_shape=list(scores.data.shape),
                             scores_window={"start": scores.sliding_window.start,
                                            "duration": scores.sliding_window.duration,
                                            "step": scores.sliding_window.step})
        chunks = merge_scores(scores)
        return validate_chunks(chunks, len(audio))

    def close(self) -> None:
        self._inference = None
        self._closed = True
        if self.metadata["loaded"]:
            import gc
            import torch

            gc.collect()
            torch.cuda.empty_cache()
