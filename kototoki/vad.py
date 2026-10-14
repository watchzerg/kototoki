"""VAD：Pyannote segmentation-3.0 原生语音检测＋`source-span-merge-v1` 分窗（配方 `recipes.VAD`）。

复制自 `experiments/w0_demo/vad_candidates.py` 的 `CurrentPyannoteVad` 与 `chunk_intervals`，
只保留 pyannote 一条路径。输入是内存波形（mono float32 16 kHz），输出是 WAV 本地坐标的窗口：
秒与成对整数样本 `start_sample/end_sample`，以及组成窗口的子段 `segments`。设备固定 `cuda:0`，
不回退 CPU。导入本模块不加载 torch 与 pyannote，构造 `PyannoteVad` 时才加载。
"""

from __future__ import annotations

import importlib.metadata
import math
from numbers import Real
from pathlib import Path
from typing import Any

from kototoki.recipes import VAD

SAMPLE_RATE = 16000
MAX_CHUNK_SAMPLES = VAD["chunk_policy"]["max_chunk_samples"]
DEVICE = VAD["device"]


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Speech interval bounds must be finite numbers")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Speech interval bounds must be finite numbers")
    return result


def _seconds(sample: int, samples: int) -> float:
    """Preserve exact integer crops for consumers still using int(seconds*sr)."""
    value = sample / SAMPLE_RATE
    if sample != samples and int(value * SAMPLE_RATE) < sample:
        value = math.nextafter(value, math.inf)
    return value


def chunk_intervals(intervals: list[Any], samples: int) -> tuple[list[dict], dict]:
    """原生语音区间（秒）→ ≤30 s 源窗口；保留并集，不压缩时间。

    区间起点向下、终点向上取整为样本并裁到源范围（Pyannote 末帧补齐会越界，计数），
    排序取并集，超过 480000 样本的区间硬切，再按源跨度贪心合并完整区间。
    非法、反向或非有限区间直接报错。
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 0:
        raise ValueError("Source sample count must be a nonnegative integer")
    raw, converted = [], []
    clipped = dropped = 0
    for interval in intervals:
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError("Each speech interval must contain start and end")
        left, right = map(_number, interval)
        if left >= right:
            raise ValueError("Speech interval start must precede end")
        start, end = math.floor(left * SAMPLE_RATE), math.ceil(right * SAMPLE_RATE)
        bounded = max(0, start), min(samples, end)
        if bounded != (start, end):
            clipped += 1
        raw.append({"start": left, "end": right})
        if bounded[0] >= bounded[1]:
            dropped += 1
        else:
            converted.append(bounded)
    union: list[tuple[int, int]] = []
    for start, end in sorted(converted):
        if union and start <= union[-1][1]:
            union[-1] = union[-1][0], max(end, union[-1][1])
        else:
            union.append((start, end))
    pieces: list[tuple[int, int]] = []
    split_count = 0
    for start, end in union:
        while end - start > MAX_CHUNK_SAMPLES:
            pieces.append((start, start + MAX_CHUNK_SAMPLES))
            start += MAX_CHUNK_SAMPLES
            split_count += 1
        pieces.append((start, end))
    groups: list[list[tuple[int, int]]] = []
    for piece in pieces:
        if groups and piece[1] - groups[-1][0][0] <= MAX_CHUNK_SAMPLES:
            groups[-1].append(piece)
        else:
            groups.append([piece])
    chunks = [{"start": _seconds(group[0][0], samples),
               "end": _seconds(group[-1][1], samples),
               "start_sample": group[0][0], "end_sample": group[-1][1],
               "segments": [[_seconds(start, samples), _seconds(end, samples)]
                            for start, end in group]}
              for group in groups]
    speech_samples = sum(end - start for start, end in union)
    chunk_samples = sum(chunk["end_sample"] - chunk["start_sample"] for chunk in chunks)
    metadata = {
        "raw_intervals": raw,
        "speech_intervals": [{"start_sample": start, "end_sample": end,
                              "start": _seconds(start, samples), "end": _seconds(end, samples)}
                             for start, end in union],
        "accounting": {"input_samples": samples, "raw_interval_count": len(raw),
                       "speech_interval_count": len(union), "chunk_count": len(chunks),
                       "clipped_interval_count": clipped, "dropped_interval_count": dropped,
                       "hard_split_count": split_count, "speech_samples": speech_samples,
                       "chunk_samples": chunk_samples,
                       "internal_silence_samples": chunk_samples - speech_samples,
                       "skipped_source_samples": samples - chunk_samples},
    }
    return chunks, metadata


def validate_audio(audio: Any) -> None:
    import numpy as np

    if not isinstance(audio, np.ndarray) or audio.ndim != 1 or audio.dtype != np.float32:
        raise ValueError("Expected a mono numpy float32 waveform at 16 kHz")
    if not np.isfinite(audio).all():
        raise ValueError("Audio must contain only finite samples")


class PyannoteVad:
    """本地 segmentation-3.0 powerset checkpoint，pyannote.audio 4.0.7 `VoiceActivityDetection`。"""

    def __init__(self, checkpoint: Path) -> None:
        import torch
        from pyannote.audio import Model
        from pyannote.audio.pipelines import VoiceActivityDetection

        distribution, expected = VAD["package"]
        actual = importlib.metadata.version(distribution)
        if actual != expected:
            raise RuntimeError(f"VAD requires {distribution}=={expected}; found {actual}")
        checkpoint = Path(checkpoint)
        if not checkpoint.is_file():
            raise FileNotFoundError(f"Provision the gated segmentation-3.0 checkpoint: {checkpoint}")
        if not torch.cuda.is_available():
            raise RuntimeError("VAD requires CUDA; CPU fallback is disabled")
        model = Model.from_pretrained(str(checkpoint), token=None)
        if model is None:
            raise RuntimeError("Pyannote could not load the local segmentation-3.0 checkpoint")
        if not model.specifications.powerset:
            raise ValueError("VAD requires segmentation-3.0 powerset; do not substitute old PyanNet")
        engine = VoiceActivityDetection(segmentation=model, device=torch.device(DEVICE))
        engine.instantiate(dict(VAD["instantiate"]))
        parameter = next(model.parameters())
        if str(parameter.device) != DEVICE:
            raise RuntimeError(f"VAD loaded on {parameter.device}, requested {DEVICE}; automatic fallback is forbidden")
        inference = engine._segmentation
        self._engine = engine
        self.metadata: dict[str, Any] = {
            "device": str(parameter.device), "dtype": str(parameter.dtype),
            "window_duration": inference.duration, "window_step": inference.step,
            "batch_size": inference.batch_size,
            "package_versions": {name: importlib.metadata.version(name)
                                 for name in ("torch", "pyannote.audio", "numpy")},
        }

    def segment(self, audio: Any) -> tuple[list[dict], dict]:
        """一个文件的波形 → (窗口, 记账)；空波形或无语音返回空窗口表。"""
        import torch

        validate_audio(audio)
        if not len(audio):
            return chunk_intervals([], 0)
        annotation = self._engine({"waveform": torch.from_numpy(audio).unsqueeze(0),
                                   "sample_rate": SAMPLE_RATE, "uri": "kototoki-vad"})
        intervals = [[segment.start, segment.end] for segment in annotation.get_timeline().support()]
        return chunk_intervals(intervals, len(audio))
