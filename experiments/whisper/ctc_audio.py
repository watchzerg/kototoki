"""Explicit checkpoint feature-extractor normalization for pinned WhisperX."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import time
from typing import Any, Iterator


def digest(values: Any) -> str:
    return hashlib.sha256(values.astype("<f4", copy=False).tobytes()).hexdigest()


class SegmentNormalizer:
    def __init__(self, audio: Any, segments: list[dict[str, Any]], dictionary: dict[str, int], extractor: Any):
        import numpy as np
        if not extractor.do_normalize or extractor.sampling_rate != 16000:
            raise ValueError("Normalization probe requires the checkpoint's do_normalize=true at 16000 Hz")
        if extractor.padding_side != "right" or extractor.padding_value != 0.0:
            raise ValueError("Normalization probe supports only the native right-zero padding policy")
        self.records: list[dict[str, Any]] = []
        self.plans: list[tuple[dict[str, Any], Any]] = []
        self.hook_seconds = 0.0
        started = time.perf_counter()
        for index, segment in enumerate(segments):
            text = segment["text"].strip()
            if not any(char.lower() in dictionary or char.lower() not in (" ", "|") for char in text):
                continue
            if segment["start"] >= len(audio) / 16000:
                continue
            f1, f2 = int(segment["start"] * 16000), int(segment["end"] * 16000)
            waveform = audio[f1:f2]
            if not len(waveform):
                raise ValueError("Empty eligible FA segment; normalization is undefined")
            padded_length = max(400, len(waveform))
            raw = np.pad(waveform, (0, padded_length - len(waveform)))
            # Use the exact installed official feature extractor. Its attention
            # mask excludes padding from mean/variance and restores zero padding.
            processed = extractor(waveform, sampling_rate=16000, padding="max_length",
                                  max_length=padded_length, return_attention_mask=True, return_tensors="np")
            normalized = processed["input_values"][0]
            length = int(processed["attention_mask"][0].sum())
            if length != len(waveform) or normalized.shape != raw.shape:
                raise ValueError("Official feature extractor changed expected FA length")
            self.plans.append(({"segment_index": index, "source_sample_start": f1, "source_sample_end": f1 + len(waveform),
                                "valid_samples": length, "padded_samples": padded_length,
                                "raw_float32_sha256": digest(raw), "normalized_float32_sha256": digest(normalized),
                                "original_mean": float(waveform.mean()), "original_variance": float(waveform.var()),
                                "normalization_attention_length": length,
                                "model_attention_mask": "unchanged: not passed by native WhisperX"}, normalized))
        self.preparation_seconds = time.perf_counter() - started

    def pre_hook(self, module: Any, inputs: tuple[Any, ...]) -> tuple[Any, ...]:
        import torch
        started = time.perf_counter()
        call_index = len(self.records)
        if call_index >= len(self.plans) or len(inputs) != 1:
            raise ValueError("Unexpected FA forward count or arguments; normalization mapping is unsupported")
        record, normalized = self.plans[call_index]
        raw = inputs[0]
        if raw.ndim != 2 or raw.shape != (1, record["padded_samples"]):
            raise ValueError("Unexpected FA waveform shape")
        # Verify the actual upstream slice, including native zero padding. The
        # copy and synchronization cost is deliberately included in this probe.
        if digest(raw.detach().cpu().numpy()[0]) != record["raw_float32_sha256"]:
            raise ValueError("Actual FA waveform differs from planned source slice")
        replacement = torch.from_numpy(normalized.copy()).unsqueeze(0).to(device=raw.device, dtype=raw.dtype)
        self.records.append({**record, "actual_input_device": str(replacement.device), "actual_input_dtype": str(replacement.dtype)})
        self.hook_seconds += time.perf_counter() - started
        return (replacement,)


@contextmanager
def normalize_segments(model: Any, normalizer: SegmentNormalizer) -> Iterator[SegmentNormalizer]:
    hook = model.register_forward_pre_hook(normalizer.pre_hook)
    try:
        yield normalizer
        if len(normalizer.records) != len(normalizer.plans):
            raise ValueError("FA skipped planned normalization forwards; mapping is unsupported")
    finally:
        hook.remove()
