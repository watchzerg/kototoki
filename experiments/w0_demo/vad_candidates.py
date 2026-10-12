"""Offline VAD comparison adapters with one source-span chunk policy.

Optional dependencies and model loading are deferred until construction. Model
acquisition is a separate operation. These adapters do not replace W0's frozen
PyanNet recipe. Each backend retains its pinned native speech postprocessing;
only conversion to source samples and the final <=30s merge policy are shared.
"""
from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import math
from numbers import Real
from pathlib import Path
from typing import Any

from .vad import SAMPLE_RATE, validate_audio

MAX_CHUNK_SAMPLES = 30 * SAMPLE_RATE
PACKAGE_PINS = {
    "silero": ("silero-vad", "6.2.3"),
    "fsmn": ("funasr", "1.4.16"),
    "firered": ("fireredvad", "0.0.2"),
    "pyannote-current": ("pyannote.audio", "4.0.7"),
}
MODEL_REVISIONS = {
    "silero": "silero-vad-6.2.3-packaged-jit",
    "fsmn": "df20e6b30c653645fa4ff125cacfcabd1020a669",
    "firered": "7990aaccc6b7aec1e527743bd30201f2c4a03b8c",
    "pyannote-current": "e66f3d3b9eb0873085418a7b813d3b369bf160bb",
}
MODEL_IDS = {
    "silero": "snakers4/silero-vad",
    "fsmn": "funasr/fsmn-vad",
    "firered": "FireRedTeam/FireRedVAD (offline VAD)",
    "pyannote-current": "pyannote/segmentation-3.0",
}
CHUNK_POLICY = {
    "id": "source-span-merge-v1",
    "sample_rate": SAMPLE_RATE,
    "max_chunk_samples": MAX_CHUNK_SAMPLES,
    "max_chunk_seconds": 30,
    "interval_conversion": "floor start, ceil end, clip to source, sorted union",
    "merge": "greedy whole intervals while source span fits",
    "long_interval_split": "hard split every 480000 source samples",
    "additional_padding_samples": 0,
    "internal_silence": "retained",
    "concatenation": False,
}


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


def chunk_intervals(intervals: list[Any], samples: int, *, unit: str = "seconds") -> tuple[list[dict], dict]:
    """Convert native intervals, retain their union, and never compress time.

    Out-of-source native bounds (for example Pyannote's padded last frame) are
    clipped and counted. Invalid/reversed/nonfinite intervals fail explicitly.
    Native overlaps are unioned so every source sample is processed at most once.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 0:
        raise ValueError("Source sample count must be a nonnegative integer")
    if unit not in {"seconds", "milliseconds", "samples"}:
        raise ValueError("Interval unit must be seconds, milliseconds, or samples")
    factor = {"seconds": SAMPLE_RATE, "milliseconds": SAMPLE_RATE / 1000, "samples": 1}[unit]
    raw, converted = [], []
    clipped = dropped = 0
    for interval in intervals:
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError("Each speech interval must contain start and end")
        left, right = map(_number, interval)
        if left >= right:
            raise ValueError("Speech interval start must precede end")
        if unit == "samples" and (left != int(left) or right != int(right)):
            raise ValueError("Sample intervals require integer bounds")
        start, end = math.floor(left * factor), math.ceil(right * factor)
        bounded = max(0, start), min(samples, end)
        if bounded != (start, end):
            clipped += 1
        raw.append({"start": left, "end": right, "unit": unit,
                    "start_seconds": left * factor / SAMPLE_RATE,
                    "end_seconds": right * factor / SAMPLE_RATE})
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
        "chunk_policy": dict(CHUNK_POLICY),
        "accounting": {"input_samples": samples, "raw_interval_count": len(raw),
                       "speech_interval_count": len(union), "chunk_count": len(chunks),
                       "clipped_interval_count": clipped, "dropped_interval_count": dropped,
                       "hard_split_count": split_count, "speech_samples": speech_samples,
                       "chunk_samples": chunk_samples,
                       "internal_silence_samples": chunk_samples - speech_samples,
                       "skipped_source_samples": samples - chunk_samples},
    }
    return chunks, metadata


def _package_versions() -> dict[str, str]:
    result = {}
    for name in ("numpy", "torch", "torchaudio", "silero-vad", "funasr", "fireredvad",
                 "pyannote.audio", "pyannote.core", "kaldi-native-fbank"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return result


def _model_hashes(path: Path) -> dict[str, str]:
    files = [path] if path.is_file() else sorted(file for file in path.rglob("*") if file.is_file())
    result = {}
    for file in files:
        with file.open("rb") as stream:
            result[file.name if path.is_file() else file.relative_to(path).as_posix()] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


class _CandidateVad:
    """Shared lifecycle and audit boundary; subclasses implement native detection."""

    vad_id: str
    required_files: tuple[str, ...] = ()

    def __init__(self, model_path: Path, *, device: str = "cpu", model_revision: str | None = None) -> None:
        self.model_path = Path(model_path).resolve()
        if device not in {"cpu", "cuda", "cuda:0"}:
            raise ValueError("VAD comparison supports explicit cpu or cuda:0; no automatic fallback")
        self.device = "cuda:0" if device == "cuda" else device
        if not self.model_path.exists():
            raise FileNotFoundError(f"Provision local {self.vad_id} model assets: {self.model_path}")
        for name in self.required_files:
            if not self.model_path.is_dir() or not (self.model_path / name).is_file():
                raise FileNotFoundError(f"Provision {self.vad_id} model file: {self.model_path / name}")
        self._model: Any = None
        self._engine: Any = None
        self._closed = False
        distribution, expected = PACKAGE_PINS[self.vad_id]
        actual = importlib.metadata.version(distribution)
        if actual != expected:
            raise RuntimeError(f"{self.vad_id} comparison requires {distribution}=={expected}; found {actual}. Use its isolated pinned environment")
        self.metadata: dict[str, Any] = {
            "kind": self.vad_id, "fresh_inference": True, "loaded": False,
            "model_path": str(self.model_path), "model_id": MODEL_IDS[self.vad_id],
            "model_revision": model_revision or MODEL_REVISIONS[self.vad_id],
            "model_revision_provenance": "separately provisioned; hashes below identify local files",
            "model_files_sha256": _model_hashes(self.model_path),
            "package_versions": _package_versions(), "device_requested": self.device,
            "sample_rate": SAMPLE_RATE,
        }
        self._load()

    def _torch_device(self) -> Any:
        import torch

        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("Requested VAD CUDA device is unavailable; CPU fallback is disabled")
        return torch.device(self.device)

    def _record_device(self, model: Any) -> None:
        parameter = next(model.parameters())
        actual = str(parameter.device)
        if actual != self.device:
            raise RuntimeError(f"VAD loaded on {actual}, requested {self.device}; automatic fallback is forbidden")
        self.metadata.update(loaded=True, device=actual, dtype=str(parameter.dtype))

    def _load(self) -> None:
        raise NotImplementedError

    def _intervals(self, audio: Any) -> tuple[list[Any], str]:
        raise NotImplementedError

    def segment(self, audio: Any) -> list[dict[str, Any]]:
        if self._closed:
            raise RuntimeError("VAD is closed")
        validate_audio(audio)
        intervals, unit = self._intervals(audio) if len(audio) else ([], "seconds")
        chunks, accounting = chunk_intervals(intervals, len(audio), unit=unit)
        self.metadata.update(accounting, input_pcm_sha256=hashlib.sha256(audio.tobytes()).hexdigest())
        return chunks

    def close(self) -> None:
        if self._closed:
            return
        self._engine = self._model = None
        self._closed = True
        gc.collect()
        if self.device.startswith("cuda"):
            import torch

            torch.cuda.empty_cache()


class SileroVad(_CandidateVad):
    """Silero v6.2.3 local JIT with explicit official timestamp defaults."""

    vad_id = "silero"

    def _load(self) -> None:
        if not self.model_path.is_file():
            raise FileNotFoundError("Silero requires the local silero_vad.jit checkpoint file")
        import torch
        from silero_vad import get_speech_timestamps

        self._model = torch.jit.load(str(self.model_path), map_location=self._torch_device()).eval()
        self._engine = get_speech_timestamps
        self.options = {"threshold": .5, "sampling_rate": SAMPLE_RATE,
                        "min_speech_duration_ms": 250, "max_speech_duration_s": float("inf"),
                        "min_silence_duration_ms": 100, "speech_pad_ms": 30,
                        "return_seconds": False}
        self.metadata["native_options"] = {**self.options, "max_speech_duration_s": "infinity"}
        self._record_device(self._model)

    def _intervals(self, audio: Any) -> tuple[list[Any], str]:
        import torch

        rows = self._engine(torch.from_numpy(audio).to(self.device), self._model, **self.options)
        return [[int(row["start"]), int(row["end"])] for row in rows], "samples"


class FsmnVad(_CandidateVad):
    """FunASR 1.4.16 local FSMN, including its default dynamic endpoint policy."""

    vad_id = "fsmn"
    required_files = ("model.pt", "config.yaml", "configuration.json", "am.mvn")

    def _load(self) -> None:
        from funasr import AutoModel

        self._torch_device()
        self._engine = AutoModel(model=str(self.model_path), hub="hf", device=self.device,
                                 disable_update=True, disable_pbar=True)
        self._model = self._engine.model
        self.metadata["native_options"] = {
            "generate": {"fs": SAMPLE_RATE}, "chunk_size_ms": 60000,
            "dynamic_silence": True, "speech_noise_thres": .5,
            "silence_schedule_ms": [[10000, 2000], [20000, 1000], [30000, 800],
                                    [40000, 600], [50000, 400], [60000, 200], ["infinity", 100]],
            "schedule_update": "once per 60000ms inference chunk (FunASR 1.4.16)",
            "checkpoint_config_file": "config.yaml",
        }
        self._record_device(self._model)

    def _intervals(self, audio: Any) -> tuple[list[Any], str]:
        rows = self._engine.generate(input=audio, fs=SAMPLE_RATE)
        if not isinstance(rows, list) or len(rows) != 1 or "value" not in rows[0]:
            raise RuntimeError("FunASR VAD did not return one result with millisecond intervals")
        return rows[0]["value"], "milliseconds"


class FireRedVad(_CandidateVad):
    """FireRed 0.0.2 offline binary voice model; positive includes singing."""

    vad_id = "firered"
    required_files = ("cmvn.ark", "model.pth.tar")

    def _load(self) -> None:
        from fireredvad import FireRedVad as Engine, FireRedVadConfig

        self._torch_device()
        config = FireRedVadConfig(use_gpu=self.device.startswith("cuda"))
        self._engine = Engine.from_pretrained(str(self.model_path), config)
        self._model = self._engine.vad_model
        self.metadata.update(native_options=dict(vars(config)), release_status="Beta",
                             input_representation="PCM16 reconstructed from normalized source samples")
        self._record_device(self._model)

    def _intervals(self, audio: Any) -> tuple[list[Any], str]:
        import numpy as np

        scaled = np.rint(audio * np.float32(32768))
        if np.any(scaled < -32768) or np.any(scaled > 32767):
            raise ValueError("FireRed expects audio within the source PCM16 range")
        pcm = scaled.astype(np.int16)
        result, probabilities = self._engine.detect((pcm, SAMPLE_RATE))
        self.metadata.update(input_pcm16_sha256=hashlib.sha256(pcm.tobytes()).hexdigest(),
                             probabilities_sha256=hashlib.sha256(np.asarray(probabilities).tobytes()).hexdigest(),
                             probabilities_shape=list(np.asarray(probabilities).shape))
        if not isinstance(result, dict) or "timestamps" not in result:
            raise RuntimeError("FireRed VAD did not return timestamp intervals")
        return result["timestamps"], "seconds"


class CurrentPyannoteVad(_CandidateVad):
    """Gated MIT segmentation-3.0 local model with current powerset conversion."""

    vad_id = "pyannote-current"

    def _load(self) -> None:
        import torch
        from pyannote.audio import Model
        from pyannote.audio.pipelines import VoiceActivityDetection

        checkpoint = self.model_path / "pytorch_model.bin" if self.model_path.is_dir() else self.model_path
        if not checkpoint.is_file():
            raise FileNotFoundError(f"Provision the gated segmentation-3.0 checkpoint: {checkpoint}")
        self._model = Model.from_pretrained(str(checkpoint), token=None)
        if self._model is None:
            raise RuntimeError("Pyannote could not load the local segmentation-3.0 checkpoint")
        if not self._model.specifications.powerset:
            raise ValueError("Current Pyannote comparison requires segmentation-3.0 powerset; do not substitute old PyanNet")
        self._engine = VoiceActivityDetection(segmentation=self._model, device=self._torch_device())
        self._engine.instantiate({"min_duration_on": 0.0, "min_duration_off": 0.0})
        self.metadata.update(native_options={"onset": .5, "offset": .5, "min_duration_on": 0,
                                            "min_duration_off": 0, "powerset_conversion": True,
                                            "speaker_reduction": "max before overlap-add"},
                             access="gated checkpoint; local provisioning required")
        inference = self._engine._segmentation
        self.metadata.update(window_duration=inference.duration, window_step=inference.step,
                             batch_size=inference.batch_size)
        self._record_device(self._model)

    def _intervals(self, audio: Any) -> tuple[list[Any], str]:
        import torch

        annotation = self._engine({"waveform": torch.from_numpy(audio).unsqueeze(0),
                                   "sample_rate": SAMPLE_RATE, "uri": "local-vad-comparison"})
        return [[segment.start, segment.end] for segment in annotation.get_timeline().support()], "seconds"


def create_vad(vad_id: str, model_path: Path, *, device: str = "cpu",
               model_revision: str | None = None) -> Any:
    """Build one pinned local adapter; acquisition and ASR/CTC stay separate."""
    candidates = {"silero": SileroVad, "fsmn": FsmnVad, "firered": FireRedVad,
                  "pyannote-current": CurrentPyannoteVad}
    if vad_id not in candidates:
        raise ValueError(f"Unknown VAD candidate {vad_id!r}; choose {', '.join(candidates)}")
    return candidates[vad_id](model_path, device=device, model_revision=model_revision)
