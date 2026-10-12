"""Reusable offline MMS Japanese character CTC alignment on CUDA.

This preserves the measured MMS preprocessing and token-time semantics. It does
not implement native WhisperX trellis, sentence splitting, interpolation or cues.
Heavy dependencies are imported only when constructing or using an aligner.
Character filtering and wildcard construction preserve WhisperX 3.8.6 behavior;
see THIRD_PARTY_NOTICES.txt for upstream attribution and license notices.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import math
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SAMPLE_RATE = 16000
TIME_SEMANTICS = "ctc_nonblank_token_span"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def mms_numeric_policy(torch_module: Any = None) -> Iterator[dict]:
    """Scope the measured cached-MMS numeric defaults to forward computation.

    Pyannote disables TF32 globally and does not restore it. MMS must not inherit
    that preceding-stage setting. Restore all changed flags even after failure;
    preserve the caller's global deterministic-algorithm requirement.
    This process-global scope is intended for the serial demo pipeline only.
    """
    if torch_module is None:
        import torch as torch_module

    matmul = torch_module.backends.cuda.matmul
    previous_matmul_tf32 = matmul.allow_tf32
    try:
        matmul.allow_tf32 = False
        with torch_module.backends.cudnn.flags(
                enabled=True, benchmark=False, deterministic=False, allow_tf32=True):
            yield {
                "matmul_allow_tf32": matmul.allow_tf32,
                "cudnn_allow_tf32": torch_module.backends.cudnn.allow_tf32,
                "cudnn_enabled": torch_module.backends.cudnn.enabled,
                "cudnn_benchmark": torch_module.backends.cudnn.benchmark,
                "cudnn_deterministic": torch_module.backends.cudnn.deterministic,
                "deterministic_algorithms": torch_module.are_deterministic_algorithms_enabled(),
                "float32_matmul_precision": torch_module.get_float32_matmul_precision(),
            }
    finally:
        matmul.allow_tf32 = previous_matmul_tf32


def character_targets(text: str, dictionary: dict[str, int], wildcard_id: int) -> list[dict]:
    """Keep exact source positions; only edge whitespace and unknown space/| skip."""
    leading = len(text) - len(text.lstrip())
    stop = len(text.rstrip())
    targets = []
    for position, char in enumerate(text):
        label = char.lower()
        if not leading <= position < stop or (label not in dictionary and label in (" ", "|")):
            continue
        if len(label) != 1:
            # The historical joined lower-case target has a character-count
            # mismatch here. Never fabricate a one-to-many lexical interval.
            raise ValueError("token_character_count_mismatch: lowercase expands a character")
        known = label in dictionary
        targets.append({"original_position": position, "token_id": dictionary.get(label, wildcard_id),
                        "evidence_kind": "vocabulary_token" if known else "wildcard",
                        "lexical_interval_accepted": known})
    return targets


def clamp_window(start: float, end: float, duration: float) -> tuple[float, float]:
    if (any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in (start, end, duration)) or end < start or duration < 0):
        raise ValueError("Alignment window must have finite ordered bounds")
    return min(duration, max(0.0, start)), min(duration, max(0.0, end))


def sample_window(segment: dict, audio_samples: int) -> tuple[int, int] | None:
    """Validate optional exact source bounds without changing legacy windows."""
    if "start_sample" not in segment and "end_sample" not in segment:
        return None
    start, end = segment.get("start_sample"), segment.get("end_sample")
    if (any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end))
            or not 0 <= start < end <= audio_samples):
        raise ValueError("MMS sample bounds require integer 0 <= start_sample < end_sample <= audio length")
    for key, sample in (("start", start), ("end", end)):
        seconds = segment.get(key)
        try:
            valid = (not isinstance(seconds, bool) and isinstance(seconds, (int, float))
                     and math.isfinite(seconds)
                     and math.isclose(seconds, sample / SAMPLE_RATE, rel_tol=0, abs_tol=1e-9))
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("MMS seconds must match the corresponding exact sample bounds")
    return start, end


def normalize_window(waveform: Any, extractor: Any) -> tuple[Any, dict]:
    """Official valid-sample normalization with baseline minimum right padding."""
    import numpy as np

    if not len(waveform):
        raise ValueError("Empty alignment waveform after source-window clipping")
    processed = extractor(
        waveform, sampling_rate=SAMPLE_RATE, padding="max_length", max_length=max(400, len(waveform)),
        return_attention_mask=True, return_tensors="np")
    values = processed["input_values"][0].astype(np.float32, copy=False)
    length = int(processed["attention_mask"][0].sum())
    if length != len(waveform) or values.shape != (max(400, len(waveform)),):
        raise ValueError("Official feature extractor changed expected valid/padded sample lengths")
    raw = np.pad(waveform, (0, len(values) - len(waveform)))
    return values, {
        "valid_samples": length, "padded_samples": len(values),
        "raw_float32_sha256": hashlib.sha256(raw.astype("<f4", copy=False).tobytes()).hexdigest(),
        "normalized_float32_sha256": hashlib.sha256(values.astype("<f4", copy=False).tobytes()).hexdigest(),
        "original_mean": float(waveform.mean()), "original_variance": float(waveform.var()),
        "normalization_attention_length": length, "model_attention_mask": False,
    }


def map_records(segments: list[dict], records: list[dict], offset: float = 0) -> dict:
    """Map merged nonblank spans using source duration/frame count, round then offset.

    Frame ends are exclusive. These spans are evidence from a CTC path, not
    measured acoustic character durations. Repeated characters map by index.
    Derived segments use local time; only evaluator units use source offset.
    """
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("Source offset must be finite and nonnegative")
    by_index = {record["segment_index"]: record for record in records}
    units, derived, base = [], [], 0
    for index, segment in enumerate(segments):
        record = by_index.get(index, {})
        evidence = {token["original_position"]: token for token in record.get("tokens", [])}
        frame_count = record.get("frame_count", 0)
        start, end = record.get("window_start", segment["start"]), record.get("window_end", segment["end"])
        ratio = (end - start) / frame_count if frame_count > 0 else 0
        chars = []
        for position, char in enumerate(segment["text"]):
            token = evidence.get(position)
            valid = bool(token and not record.get("failure") and token["lexical_interval_accepted"]
                         and math.isfinite(ratio) and ratio > 0
                         and 0 <= token["start_frame"] < token["end_frame"] <= frame_count)
            begin = round(start + token["start_frame"] * ratio, 3) if valid else None
            finish = round(start + token["end_frame"] * ratio, 3) if valid else None
            chars.append({"char": char, "start": begin, "end": finish,
                          "score": token.get("token_probability") if token else None,
                          "evidence_kind": token["evidence_kind"] if token else "missing",
                          "time_semantics": TIME_SEMANTICS})
            units.append({"char_start": base + position, "char_end": base + position + 1,
                          "start": begin + offset if valid else None,
                          "end": finish + offset if valid else None,
                          "granularity": "character", "time_source": "api",
                          "status": "ok" if valid else "text_only", "time_semantics": TIME_SEMANTICS,
                          "experimental_not_acoustic_duration": True})
        derived.append({"text": segment["text"], "start": start, "end": end, "chars": chars})
        base += len(segment["text"])
    return {"text": "".join(segment["text"] for segment in segments), "units": units,
            "records": records, "derived_segments": derived}


class MmsAligner:
    """One reusable FP32 model on the currently selected CUDA device; no downloads."""

    def __init__(self, model_path: Path):
        import torch
        from safetensors import safe_open
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        self.model_path = Path(model_path).resolve()
        self.model = None
        self.processor = None
        if not torch.cuda.is_available():
            raise RuntimeError("MMS requires CUDA; CPU fallback is prohibited")
        version = importlib.metadata.version("torchaudio")
        if version.split("+")[0] != "2.8.0":
            raise ValueError("MMS baseline requires TorchAudio 2.8.0 forced_align")
        adapter = self.model_path / "adapter.jpn.safetensors"
        if not adapter.is_file():
            raise FileNotFoundError(f"Provisioned Japanese adapter required: {adapter}")
        processor = Wav2Vec2Processor.from_pretrained(
            str(self.model_path), target_lang="jpn", local_files_only=True)
        processor.tokenizer.set_target_lang("jpn")
        model = Wav2Vec2ForCTC.from_pretrained(
            str(self.model_path), target_lang=None, local_files_only=True)
        model.load_adapter("jpn", local_files_only=True)
        model = model.float()
        verification = {"path": str(adapter), "sha256": _sha256(adapter)}
        with safe_open(str(adapter), framework="pt", device="cpu") as checkpoint:
            for name in ("weight", "bias"):
                actual = getattr(model.lm_head, name).detach().cpu()
                expected = checkpoint.get_tensor(f"lm_head.{name}").to(dtype=actual.dtype)
                if not torch.equal(actual, expected):
                    raise ValueError(f"Final MMS jpn lm_head.{name} differs from local adapter")
                verification[f"head_{name}_exact_match"] = True
        vocabulary = processor.tokenizer.get_vocab()
        self.dictionary = {char.lower(): code for char, code in vocabulary.items()}
        self.blank_id = model.config.pad_token_id
        if (model.target_lang != "jpn" or processor.tokenizer.target_lang != "jpn"
                or model.config.vocab_size != len(vocabulary)
                or model.lm_head.out_features != model.config.vocab_size
                or self.blank_id != 0 or self.dictionary.get("<pad>") != self.blank_id
                or model.config.vocab_size != 2268):
            raise ValueError("MMS baseline requires jpn vocabulary 2268 and matching blank ID 0")
        extractor = processor.feature_extractor
        if (not extractor.do_normalize or extractor.sampling_rate != SAMPLE_RATE
                or extractor.padding_side != "right" or extractor.padding_value != 0):
            raise ValueError("MMS baseline requires normalized mono16k with right-zero padding")
        self.device = f"cuda:{torch.cuda.current_device()}"
        model = model.to(self.device).eval()
        if any(parameter.device.type != "cuda" or parameter.dtype != torch.float32
               for parameter in model.parameters()):
            raise RuntimeError("MMS parameters must all remain CUDA FP32")
        self.model, self.processor = model, processor
        self.metadata = {
            "language": "ja", "adapter_target_lang": "jpn", "model_path": str(self.model_path),
            "model": str(next(model.parameters()).device), "dtype": str(next(model.parameters()).dtype),
            "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
            "vocabulary_size": len(vocabulary), "blank_id": self.blank_id,
            "adapter_verification": verification, "torchaudio_version": version,
            "tokenization": "character with exact original positions and OOV wildcard",
            "model_attention_mask": False, "feature_extractor_config": extractor.to_dict(),
            "time_semantics": TIME_SEMANTICS, "rounded_seconds_decimals": 3,
            "frame_to_seconds": "clamped original search-window duration / emission frame count",
            "emission_transfer": "CUDA log_softmax -> CPU wildcard/hash -> CUDA forced_align",
            "native_whisperx_cues": False,
            "numeric_policy": {
                "scope": "model forward and log_softmax; restore caller flags on exit",
                "matmul_allow_tf32": False, "cudnn_allow_tf32": True, "cudnn_enabled": True,
                "cudnn_benchmark": False, "cudnn_deterministic": False,
                "deterministic_algorithms": "preserve caller requirement",
                "provenance": "measured Torch 2.8.0 fresh-process cached-MMS defaults",
            },
        }

    def _align_segment(self, audio: Any, start: float, end: float, text: str, record: dict) -> None:
        import torch
        from torchaudio.functional import forced_align, merge_tokens

        targets = character_targets(text, self.dictionary, len(self.dictionary))
        if not targets:
            record["skip_reason"] = "no_eligible_characters"
            return
        if "window_start_sample" in record:
            f1, f2 = record["window_start_sample"], record["window_end_sample"]
        else:
            f1, f2 = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
        waveform = audio[f1:f2]
        values, normalization = normalize_window(waveform, self.processor.feature_extractor)
        tensor = torch.from_numpy(values.copy()).unsqueeze(0).to(self.device)
        record["normalization"] = {
            **normalization,
            "source_sample_start": f1, "source_sample_end": f1 + len(waveform),
            "actual_input_device": str(tensor.device), "actual_input_dtype": str(tensor.dtype),
        }
        self.model.eval()
        with torch.inference_mode():
            with mms_numeric_policy(torch) as numeric_policy:
                record["numeric_policy"] = numeric_policy
                # Preserve the baseline: use mask only for normalization, not forward.
                logits = self.model(tensor).logits
                if tensor.device.type != "cuda" or logits.device.type != "cuda" or logits.dtype != torch.float32:
                    raise RuntimeError("MMS forward input/output must remain CUDA FP32")
                emission = logits.log_softmax(dim=-1)[0].cpu().detach()
            if emission.shape[1] != len(self.dictionary):
                raise ValueError("MMS emission vocabulary differs from loaded Japanese dictionary")
            if any(not target["lexical_interval_accepted"] for target in targets):
                mask = torch.ones(emission.shape[1], dtype=torch.bool)
                mask[self.blank_id] = False
                emission = torch.cat([emission, emission[:, mask].max(dim=1).values.unsqueeze(1)], dim=1)
            record.update(frame_count=int(emission.shape[0]), emission_shape=list(emission.shape),
                          emission_sha256=hashlib.sha256(emission.numpy().tobytes()).hexdigest(),
                          model_output_device=str(logits.device), model_output_dtype=str(logits.dtype))
            inputs = emission.unsqueeze(0).to(self.device)
            ids = [target["token_id"] for target in targets]
            labels, scores = forced_align(inputs, torch.tensor([ids], device=self.device, dtype=torch.int64),
                                          blank=self.blank_id)
            if labels.device != inputs.device or labels.device.type != "cuda" or scores.device != inputs.device:
                raise RuntimeError("Standard CTC decoder output changed CUDA device")
            record.update(decoder_input_device=str(inputs.device), decoder_output_device=str(labels.device),
                          path_sha256=hashlib.sha256(labels.detach().cpu().numpy().tobytes()).hexdigest())
            spans = merge_tokens(labels[0], scores[0].exp(), blank=self.blank_id)
            if len(spans) != len(ids) or any(span.token != expected for span, expected in zip(spans, ids)):
                raise ValueError("Collapsed CTC path differs from token targets")
            record["tokens"] = [
                {**target, "token_index": index, "start_frame": int(span.start), "end_frame": int(span.end),
                 "token_probability": float(span.score)}
                for index, (target, span) in enumerate(zip(targets, spans))]

    def align(self, audio: Any, segments: list[dict], offset: float = 0) -> dict:
        import numpy as np

        if self.model is None:
            raise RuntimeError("MMS aligner is closed")
        if not isinstance(audio, np.ndarray) or audio.ndim != 1 or audio.dtype != np.float32:
            raise ValueError("MMS audio must be a mono 16 kHz NumPy float32 array")
        if not np.isfinite(audio).all():
            raise ValueError("MMS audio contains non-finite samples")
        if not math.isfinite(offset) or offset < 0:
            raise ValueError("Source offset must be finite and nonnegative")
        records, duration = [], len(audio) / SAMPLE_RATE
        for index, segment in enumerate(segments):
            if not isinstance(segment.get("text"), str):
                raise ValueError("Each MMS segment requires original text")
            samples = sample_window(segment, len(audio))
            if samples is None:
                start, end = clamp_window(segment["start"], segment["end"], duration)
            else:
                start, end = (sample / SAMPLE_RATE for sample in samples)
            record = {"segment_index": index, "window_start": start, "window_end": end,
                      "blank_id": self.blank_id, "tokens": [], "failure": None}
            if samples is not None:
                record.update(window_start_sample=samples[0], window_end_sample=samples[1])
            records.append(record)
            try:
                self._align_segment(audio, start, end, segment["text"], record)
            except (RuntimeError, ValueError) as error:
                # Failed CUDA operations are recorded and never retried on CPU.
                record["tokens"] = []
                record["failure"] = f"{type(error).__name__}: {error}"
        return map_records(segments, records, offset)

    def close(self) -> None:
        """Release the loaded model and unused CUDA allocation for later stages."""
        import gc

        self.model = None
        self.processor = None
        gc.collect()
        if getattr(self, "device", "").startswith("cuda"):
            import torch

            if torch.cuda.is_initialized():
                torch.cuda.empty_cache()
