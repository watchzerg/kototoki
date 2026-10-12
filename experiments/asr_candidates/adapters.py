"""Offline native Transformers boundaries, without import-time model loading."""
from __future__ import annotations

import gc
import hashlib
import importlib.metadata
import inspect
from pathlib import Path
import re
import time
from typing import Any

from experiments.x0_demo.chunks import RATE, validate_chunks
from experiments.x0_demo.storage import sha256

MODEL_IDS = {
    "cohere": "CohereLabs/cohere-transcribe-03-2026",
    "granite": "ibm-granite/granite-speech-4.1-2b",
    "nemotron": "nvidia/nemotron-3.5-asr-streaming-0.6b",
}
DEFAULT_CAPS = {"cohere": 1000, "granite": 1024, "nemotron": None}
GRANITE_PROMPT = "<|audio|>transcribe the speech with proper punctuation and capitalization."


def validate_job(job: dict) -> None:
    candidate = job.get("candidate_id")
    if candidate not in MODEL_IDS or job.get("model_id") != MODEL_IDS[candidate]:
        raise ValueError("Candidate identity must match the requested official base checkpoint")
    if job.get("route") != candidate or job.get("schema_version") != 1:
        raise ValueError("Candidate stage requires schema_version=1 and route=candidate_id")
    if not re.fullmatch(r"[a-f0-9]{40}", job.get("model_revision", "")):
        raise ValueError("Candidate model_revision must be a frozen full checkpoint SHA")
    if job.get("dtype", "bfloat16") not in {"bfloat16", "float16", "float32"}:
        raise ValueError("Unsupported native model dtype")
    cap = job.get("max_new_tokens", DEFAULT_CAPS[candidate])
    if candidate == "nemotron":
        if cap is not None:
            raise ValueError("Nemotron uses native encoder exhaustion, without an arbitrary text-token cap")
    elif isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
        raise ValueError("Autoregressive candidates require a positive max_new_tokens")


def generated_suffix(sequence: list[int], prompt: list[int], start_token: int | None) -> list[int]:
    """Verify rather than guess the prefix inserted by native generation."""
    prefixes = [prompt]
    if prompt and start_token is not None and prompt[0] != start_token:
        prefixes.insert(0, [start_token, *prompt])
    for prefix in prefixes:
        if sequence[:len(prefix)] == prefix:
            return sequence[len(prefix):]
    raise ValueError("Native output does not preserve the supplied decoder prompt")


def rnnt_completion(tokens: list[int], durations: list[int], frames: int, blank: int) -> dict:
    if len(tokens) != len(durations) or not durations or durations[0] != 0:
        raise ValueError("RNNT output must preserve decoder-start duration and all emission steps")
    if frames <= 0 or any(d not in (0, 1) for d in durations):
        raise ValueError("Invalid native RNNT frame accounting")
    consumed = sum(durations)
    return {"encoder_valid_frames": frames, "encoder_consumed_frames": consumed,
            "encoder_exhausted": consumed >= frames,
            "forced_frame_advances": sum(d == 1 and t != blank for t, d in zip(tokens[1:], durations[1:])),
            "generation_steps_including_blanks": len(tokens) - 1}


def gpu_evidence(model: Any, inputs: dict, torch: Any) -> dict:
    model_evidence = model_device_evidence(model, torch)
    tensors = {name: value for name, value in inputs.items() if isinstance(value, torch.Tensor)}
    if not tensors or any(t.device != torch.device("cuda:0") for t in tensors.values()):
        raise RuntimeError("Every native model input tensor must reside on cuda:0")
    for name, value in tensors.items():
        if value.is_floating_point() and not torch.isfinite(value).all():
            raise ValueError(f"Native processor produced non-finite features: {name}")
    return {**model_evidence,
            "input_devices": {n: str(t.device) for n, t in tensors.items()},
            "native_input_shapes": {n: list(t.shape) for n, t in tensors.items()},
            "input_dtypes": {n: str(t.dtype) for n, t in tensors.items()}}


def model_device_evidence(model: Any, torch: Any) -> dict:
    parameters = sorted({str(p.device) for p in model.parameters()})
    buffers = sorted({str(b.device) for b in model.buffers()})
    if not parameters or any(torch.device(d) != torch.device("cuda:0") for d in parameters + buffers):
        raise RuntimeError(f"Model parameters/buffers must reside entirely on cuda:0: {parameters}, {buffers}")
    return {"parameter_devices": parameters, "buffer_devices": buffers}


def checkpoint_files(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): sha256(p) for p in sorted(path.rglob("*"))
            if p.is_file() and ".cache" not in p.relative_to(path).parts}


def plain_value(value: Any) -> Any:
    if hasattr(value, "detach"):
        return value.detach().cpu().tolist()
    if isinstance(value, dict):
        return {key: plain_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain_value(item) for item in value]
    return value


def implementation_identity(model: Any, processor: Any) -> dict:
    paths = {Path(inspect.getfile(type(model))), Path(inspect.getfile(type(processor)))}
    for component in (getattr(processor, "feature_extractor", None), getattr(processor, "audio_processor", None)):
        if component is not None:
            paths.add(Path(inspect.getfile(type(component))))
    distribution = importlib.metadata.distribution("transformers")
    root = Path(distribution.locate_file("transformers"))
    # Freeze generation machinery as well as model-specific feature extraction.
    paths.update(root.glob("generation/*.py"))
    for folder in ("cohere_asr", "granite_speech", "nemotron3_5_asr", "nemotron_asr_streaming", "parakeet"):
        paths.update((root / "models" / folder).glob("*.py"))
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(paths) if p.is_relative_to(root)}


class NativeAsr:
    def __init__(self, job: dict):
        validate_job(job)
        import torch
        from transformers import AutoModelForRNNT, AutoModelForSpeechSeq2Seq, AutoProcessor

        if not torch.cuda.is_available():
            raise RuntimeError("Candidate ASR requires CUDA; CPU fallback is prohibited")
        self.candidate = job["candidate_id"]
        self.cap = job.get("max_new_tokens", DEFAULT_CAPS[self.candidate])
        self.dtype = getattr(torch, job.get("dtype", "bfloat16"))
        path = Path(job["asr_model"]).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Provision candidate checkpoint separately: {path}")
        identity = checkpoint_files(path)
        if job.get("model_files_sha256") is not None and identity != job["model_files_sha256"]:
            raise ValueError("Provisioned model files differ from frozen acquisition manifest")
        self.processor = AutoProcessor.from_pretrained(path, local_files_only=True, trust_remote_code=False)
        factory = AutoModelForRNNT if self.candidate == "nemotron" else AutoModelForSpeechSeq2Seq
        self.model = factory.from_pretrained(path, local_files_only=True, trust_remote_code=False,
            dtype=self.dtype, device_map={"": "cuda:0"}, attn_implementation="sdpa").eval()
        devices = model_device_evidence(self.model, torch)
        feature = getattr(self.processor, "feature_extractor", getattr(self.processor, "audio_processor", None))
        if feature is None or feature.sampling_rate != RATE:
            raise ValueError("Candidate native processor must require the frozen 16kHz source")
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        self.metadata = {"candidate_id": self.candidate, "model": job["model_id"],
            "revision": job["model_revision"], "path": str(path), "model_files_sha256": identity,
            "language": "ja-JP" if self.candidate == "nemotron" else "ja",
            "language_conditioning": "native explicit locale" if self.candidate != "granite" else "source-language transcription; official English prompt",
            "dtype": str(self.dtype), "attention": "sdpa", "device_map": {"": "cuda:0"},
            "max_new_tokens": self.cap, "do_sample": False, "num_beams": 1, "batch_size": 1,
            "independent_chunks": True, "previous_text_conditioning": False, "padding_to_30s": False,
            "preprocessing": "native processor; exact frozen mono16kHz float32 source crop",
            "generation_config": self.model.generation_config.to_dict(),
            "model_config": self.model.config.to_dict(),
            "installed_implementation_sha256": implementation_identity(self.model, self.processor),
            "granite_prompt": GRANITE_PROMPT if self.candidate == "granite" else None, **devices,
            "hotwords": None, "translation": False, "native_streaming": False}

    def transcribe(self, audio: Any, chunks: list[dict], progress=None, *, retain_all: bool = True) -> tuple[list[dict], list[dict]]:
        import numpy as np
        import torch

        validate_chunks(chunks, len(audio), retain_all=retain_all)
        segments, traces = [], []
        for index, chunk in enumerate(chunks):
            data = audio[chunk["start_sample"]:chunk["end_sample"]]
            if data.ndim != 1 or data.dtype != np.float32 or not np.isfinite(data).all() or not 0 < len(data) <= 30 * RATE:
                raise ValueError("Candidate input must be a finite float32 mono source window of at most 30 seconds")
            mark = time.perf_counter()
            if self.candidate == "granite":
                prompt = self.processor.tokenizer.apply_chat_template(
                    [{"role": "user", "content": GRANITE_PROMPT}], tokenize=False, add_generation_prompt=True)
                inputs = self.processor(prompt, torch.from_numpy(data.copy()).unsqueeze(0), device="cuda:0", return_tensors="pt")
            else:
                inputs = self.processor(audio=data.copy(), sampling_rate=RATE,
                    language="ja-JP" if self.candidate == "nemotron" else "ja", return_tensors="pt")
            chunk_map = inputs.pop("audio_chunk_index", None)
            inputs = inputs.to("cuda:0", self.dtype)
            evidence = gpu_evidence(self.model, inputs, torch)
            if inputs["input_features"].shape[0] != 1:
                raise ValueError("Native processor split the frozen source window into multiple requests")
            if self.candidate == "cohere":
                prompt_tokens = inputs["decoder_input_ids"][0].tolist()
                limit = self.model.config.max_position_embeddings
                if len(prompt_tokens) + self.cap + 1 > limit:
                    raise ValueError("Cohere token budget exceeds the native decoder position capacity")
            elif self.candidate == "granite":
                prompt_tokens = inputs["input_ids"][0].tolist()
            else:
                prompt_tokens = []
            torch.cuda.synchronize()
            preprocess_s = time.perf_counter() - mark
            mark = time.perf_counter()
            options = {"do_sample": False, "num_beams": 1, "return_dict_in_generate": True}
            if self.cap is not None:
                options["max_new_tokens"] = self.cap
            with torch.inference_mode():
                output = self.model.generate(**inputs, **options)
            torch.cuda.synchronize()
            inference_s = time.perf_counter() - mark
            sequence = output.sequences
            if sequence.device != torch.device("cuda:0") or sequence.ndim != 2 or sequence.shape[0] != 1:
                raise RuntimeError("Native generate must produce one CUDA token sequence")
            ids = sequence[0].detach().cpu().tolist()
            completion = {}
            if self.candidate == "nemotron":
                if output.durations is None:
                    raise ValueError("Native RNNT output lacks encoder-exhaustion evidence")
                mask = inputs.get("attention_mask")
                length = mask.sum(-1) if mask is not None else torch.tensor([inputs["input_features"].shape[1]], device="cuda:0")
                frames = self.model.encoder._get_subsampling_output_length(length).item()
                durations = output.durations[0].detach().cpu().tolist()
                completion = rnnt_completion(ids, durations, frames, self.model.config.blank_token_id)
                completion["native_durations"] = durations
                generated = ids[1:]
                capped = not completion["encoder_exhausted"]
            else:
                start = self.model.generation_config.decoder_start_token_id if self.candidate == "cohere" else None
                generated = generated_suffix(ids, prompt_tokens, start)
                capped = len(generated) >= self.cap
            decoder = self.processor.tokenizer if self.candidate == "granite" else self.processor
            text = decoder.decode(generated, skip_special_tokens=True)
            raw = decoder.decode(generated, skip_special_tokens=False)
            segment = {**chunk, "text": text}
            trace = {"chunk_index": index, "start_sample": chunk["start_sample"], "end_sample": chunk["end_sample"],
                "pcm_float32_sha256": hashlib.sha256(data.tobytes()).hexdigest(), "token_ids": generated,
                "native_sequence_token_ids": ids, "decoder_prompt_token_ids": prompt_tokens,
                "native_audio_chunk_index": plain_value(chunk_map), "generated_tokens": len(generated),
                "token_limit_reached": capped, "raw_asr": raw, "requested_language": self.metadata["language"],
                "asr_input_evidence": {**evidence, "output_device": str(sequence.device)},
                "preprocess_s": preprocess_s, "inference_s": inference_s, **completion}
            segments.append(segment)
            traces.append(trace)
            if progress:
                progress(segments, traces, self.metadata)
            if capped:
                raise ValueError(f"{self.candidate} native generation incomplete; partial output retained")
            del inputs, output, sequence
        return segments, traces

    def close(self) -> None:
        import torch
        self.model = self.processor = None
        gc.collect()
        torch.cuda.empty_cache()
