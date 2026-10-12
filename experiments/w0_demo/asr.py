"""Reusable CUDA FP16 W0 ASR preserving the measured WhisperX 3.8.6 path.

The log-Mel and generation flow derives from WhisperX 3.8.6 (BSD-2) and
OpenAI Whisper (MIT); see THIRD_PARTY_NOTICES.txt. Original independent
replica: experiments/framework_equivalence/adapter.py. The caller supplies
local faster-whisper large-v3 assets and an independently provisioned
OpenAI/WhisperX mel_filters.npz containing the exact float32 mel_128 matrix.
No WhisperX runtime, network acquisition, language detection, translation,
temperature fallback, previous-text conditioning, or native timing is used.
The measured equivalence scope is faster-whisper 1.2.1 / CT2 4.8.2,
Japanese, beam 5, batch 1, 128 Mel, <=30-second crops. Other assets or
versions require independent verification. Imports are stdlib-only until use.
"""
from __future__ import annotations

import gc
import hashlib
import importlib.metadata
from pathlib import Path
from typing import Any

from .vad import SAMPLE_RATE, validate_audio, validate_chunks
from .alignment import sample_window


def features(audio: Any, filters: Any) -> Any:
    """Right-pad waveform before centered float32 Torch STFT; never pad Mel."""
    import torch

    validate_audio(audio)
    if not 0 < len(audio) <= 480000:
        raise ValueError("Expected nonempty mono PCM at 16 kHz, no longer than 30s")
    waveform = torch.from_numpy(audio)
    if len(audio) < 480000:
        waveform = torch.nn.functional.pad(waveform, (0, 480000 - len(audio)))
    window = torch.hann_window(400).to(waveform.device)
    spectrum = torch.stft(waveform, 400, 160, window=window, return_complex=True)
    magnitudes = spectrum[..., :-1].abs() ** 2
    log_spec = torch.clamp(filters @ magnitudes, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).numpy()


def generate(model: Any, mel: Any, options: dict[str, Any]) -> dict[str, Any]:
    """Use the base faster-whisper prompt/encoder and the exact CT2 whitelist."""
    import numpy as np
    from faster_whisper.tokenizer import Tokenizer

    tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                          task="transcribe", language="ja")
    previous = []
    if options["initial_prompt"] is not None:
        previous = tokenizer.encode(" " + options["initial_prompt"].strip())
    prompt = model.get_prompt(tokenizer, previous, without_timestamps=options["without_timestamps"],
                              prefix=options["prefix"], hotwords=options["hotwords"])
    encoder = model.encode(mel[np.newaxis])
    kwargs = {name: options[name] for name in (
        "beam_size", "patience", "length_penalty", "suppress_blank", "suppress_tokens",
        "no_repeat_ngram_size", "repetition_penalty")}
    kwargs.update(max_length=model.max_length, return_scores=True)
    result = model.model.generate(encoder, [prompt], **kwargs)[0]
    tokens = result.sequences_ids[0]
    length = len(tokens)
    return {"tokens": list(tokens), "text": tokenizer.tokenizer.decode_batch(
        [[token for token in tokens if token < tokenizer.eot]])[0],
        "avg_logprob": result.scores[0] * length ** options["length_penalty"] / (length + 1),
        "prompt": list(prompt), "kwargs": kwargs}


class WhisperAsr:
    """Local model residency, independent Japanese chunks, and token traces."""

    def __init__(self, model_path: Path, mel_path: Path) -> None:
        self.model_path, self.mel_path = Path(model_path).resolve(), Path(mel_path).resolve()
        if not self.model_path.is_dir():
            raise FileNotFoundError(f"Provision a local faster-whisper model directory: {self.model_path}")
        if not self.mel_path.is_file():
            raise FileNotFoundError(f"Provision local mel_filters.npz: {self.mel_path}")
        self._model: Any = None
        self._filters: Any = None
        self._closed = False
        self.options: dict[str, Any] = {
            "beam_size": 5, "patience": 1, "length_penalty": 1,
            "suppress_blank": True, "suppress_tokens": [-1],
            "no_repeat_ngram_size": 0, "repetition_penalty": 1,
            "initial_prompt": None, "without_timestamps": True,
            "prefix": None, "hotwords": None,
        }
        self.metadata: dict[str, Any] = {
            "kind": "faster-whisper-direct", "model_path": str(self.model_path),
            "mel_path": str(self.mel_path), "device_requested": "cuda:0",
            "compute_type_requested": "float16", "language": "ja",
            "task": "transcribe", "batch_size": 1, "loaded": False,
            "options": self.options.copy(), "condition_on_previous_text": False,
        }
        self._load()

    def _load(self) -> None:
        with self.mel_path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != "7450ae70723a5ef9d341e3cee628c7cb0177f36ce42c44b7ed2bf3325f0f6d4c":
            raise ValueError("Mel asset differs from the measured W0 filterbank; provision the pinned mel_filters.npz")
        import numpy as np
        import torch
        from faster_whisper import WhisperModel

        with np.load(self.mel_path, allow_pickle=False) as archive:
            bank = archive["mel_128"].copy()
        if bank.shape != (128, 201) or bank.dtype != np.float32 or not np.isfinite(bank).all():
            raise ValueError("mel_128 must be a finite float32 matrix with shape (128, 201)")
        filters = torch.from_numpy(bank)
        model = WhisperModel(str(self.model_path), device="cuda", device_index=0,
                             compute_type="float16", local_files_only=True, cpu_threads=4)
        if model.model.device != "cuda" or model.model.compute_type != "float16":
            raise RuntimeError("ASR requires actual CUDA float16 execution; CPU fallback is disabled")
        if model.feature_extractor.mel_filters.shape[0] != 128:
            raise ValueError("The measured W0 ASR requires a 128-Mel model")
        self._model, self._filters = model, filters
        self.metadata.update(loaded=True, device=model.model.device,
                             compute_type=model.model.compute_type, mel_sha256=checksum,
                             faster_whisper=importlib.metadata.version("faster-whisper"),
                             ctranslate2=importlib.metadata.version("ctranslate2"),
                             torch=importlib.metadata.version("torch"))

    def transcribe(self, audio: Any, chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self._closed:
            raise RuntimeError("Whisper ASR is closed")
        validate_audio(audio)
        windows = validate_chunks(chunks, len(audio))
        sample_bounds = [sample_window(chunk, len(audio)) for chunk in windows]
        if any(bounds is not None and bounds[1] - bounds[0] > 480000 for bounds in sample_bounds):
            raise ValueError("ASR source sample windows must be at most 480000 samples")
        if not windows:
            return [], []
        if self._model is None:
            self._load()
        segments, traces = [], []
        for chunk, exact in zip(windows, sample_bounds):
            start_sample, end_sample = (exact if exact is not None else
                                       (int(chunk["start"] * SAMPLE_RATE), int(chunk["end"] * SAMPLE_RATE)))
            mel = features(audio[start_sample:end_sample], self._filters)
            result = generate(self._model, mel, self.options)
            segments.append({"text": result["text"], "start": round(chunk["start"], 3),
                             "end": round(chunk["end"], 3), "avg_logprob": result["avg_logprob"]})
            if exact is not None:
                segments[-1].update(start=chunk["start"], end=chunk["end"],
                                    start_sample=start_sample, end_sample=end_sample)
            traces.append({"tokens": result["tokens"], "prompt": result["prompt"],
                           "kwargs": result["kwargs"],
                           "feature_sha256": hashlib.sha256(mel.tobytes()).hexdigest(),
                           "start_sample": start_sample, "end_sample": end_sample})
        return segments, traces

    def close(self) -> None:
        """Release CT2 residency and owned feature tensors; close is idempotent."""
        model, self._model = self._model, None
        self._filters = None
        self._closed = True
        if model is not None:
            model.model.unload_model()
            del model
            gc.collect()
