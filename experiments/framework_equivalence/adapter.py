"""Isolated faster-whisper adapter matching the measured WhisperX 3.8.6 path.

The Torch log-Mel formula derives from WhisperX/OpenAI Whisper (BSD-2/MIT).
Copyright (c) 2024 Max Bain; see THIRD_PARTY_NOTICES.txt for retained notice.
This module neither imports WhisperX nor loads its installed feature assets.
The caller supplies a separately frozen, attributed Mel filterbank.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import torch
from faster_whisper.tokenizer import Tokenizer


def features(audio: np.ndarray, filters: torch.Tensor) -> np.ndarray:
    """Preserve right waveform padding before centered STFT and float32 math."""
    if audio.ndim != 1 or not 0 < len(audio) <= 480000:
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


def generate(model: Any, mel: np.ndarray, options: dict[str, Any]) -> dict[str, Any]:
    """Use the base FW encoder/prompt and the measured direct CT2 call contract."""
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
    return {"tokens": tokens, "text": tokenizer.tokenizer.decode_batch(
        [[token for token in tokens if token < tokenizer.eot]])[0],
        "avg_logprob": result.scores[0] * length ** options["length_penalty"] / (length + 1),
        "prompt": prompt, "generate_kwargs": kwargs}
