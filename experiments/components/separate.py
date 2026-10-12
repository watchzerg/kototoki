"""Offline single-model HTDemucs vocal separation with unchanged source coordinates."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import time
from typing import Any
import wave


SAMPLE_RATE = 16000
MODEL_RATE = 44100
MODEL_SIGNATURE = "955717e8"
MODEL_REVISION = "cbc8a9b1a87023b7fd74e7b3412e6321c0eab003"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_origin_sample(offset: float) -> int:
    """Require an exact input-sample origin rather than silently round the timeline."""
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("Source offset must be finite and nonnegative")
    sample = offset * SAMPLE_RATE
    if abs(sample - round(sample)) > 1e-6:
        raise ValueError("Source offset must be aligned to a 16000 Hz sample")
    return round(sample)


def resampled_length(samples: int, old_rate: int, new_rate: int) -> int:
    """Length for julius.resample_frac(..., full=True)."""
    if samples < 1 or old_rate < 1 or new_rate < 1:
        raise ValueError("Sample count and sample rates must be positive")
    return (samples * new_rate + old_rate - 1) // old_rate


def trim_count(actual: int, expected: int) -> int:
    """Only discard the endpoint rounding sample; never pad or shift the start."""
    if expected < 1 or actual not in (expected, expected + 1):
        raise ValueError(f"Unexpected round-trip length: {actual}; expected {expected} or {expected + 1}")
    return actual - expected


def validate_output(out: Path, local_root: Path) -> Path:
    resolved = out.resolve()
    root = local_root.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Output must be a new subdirectory under the workspace .local directory")
    if resolved.exists():
        raise FileExistsError(f"Refusing to overwrite output: {resolved}")
    return resolved


def read_pcm(path: Path) -> tuple[bytes, dict[str, Any]]:
    identity_before = sha256(path)
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth(), audio.getcomptype()) != (
            1, SAMPLE_RATE, 2, "NONE"
        ):
            raise ValueError("Input must be mono 16000 Hz PCM16 WAV")
        frames = audio.getnframes()
        pcm = audio.readframes(frames)
    if frames < 1 or len(pcm) != frames * 2:
        raise ValueError("Input audio is empty or truncated")
    if sha256(path) != identity_before:
        raise RuntimeError("Input changed during reading")
    return pcm, {"path": str(path.resolve()), "file_sha256": identity_before,
                 "pcm_sha256": hashlib.sha256(pcm).hexdigest(), "sample_rate": SAMPLE_RATE,
                 "channels": 1, "samples": frames, "duration_s": frames / SAMPLE_RATE,
                 "representation": "float32 PCM16 / 32768"}


def source_identity(target: Any) -> dict[str, str]:
    path = Path(inspect.getsourcefile(target) or inspect.getfile(target))
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def separate(audio: Path, repo: Path, out: Path, offset: float, device_name: str) -> dict[str, Any]:
    started = time.perf_counter()
    origin = source_origin_sample(offset)
    if re.fullmatch(r"cuda(?::[0-9]+)?", device_name) is None:
        raise ValueError("Inference device must be cuda or cuda:<index>; CPU fallback is disabled")
    local_root = Path(__file__).resolve().parents[2] / ".local"
    out = validate_output(out, local_root)
    pcm, input_identity = read_pcm(audio)
    repo = repo.resolve()
    assets = [repo / "htdemucs.yaml", repo / f"{MODEL_SIGNATURE}.safetensors",
              repo / f"{MODEL_SIGNATURE}.json"]
    for path in assets:
        if not path.is_file():
            raise FileNotFoundError(f"Provision required local HTDemucs asset separately: {path}")
    asset_identity = [{"path": str(path), "file_sha256": sha256(path)} for path in assets]
    # These settings prevent incidental caches/network access by optional imports.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import julius
    import numpy as np
    import torch
    import yaml
    from demucs.apply import apply_model
    from demucs.hf import load_safetensors_model

    if importlib.metadata.version("demucs") != "4.1.0":
        raise RuntimeError("This frozen experiment requires Demucs 4.1.0 in its isolated environment")
    bag = yaml.safe_load(assets[0].read_text(encoding="utf-8"))
    if bag != {"models": [MODEL_SIGNATURE]}:
        raise ValueError("This experiment requires the unchanged single-model htdemucs YAML")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; run in the provisioned GPU environment")
    device = torch.device(device_name)
    torch.cuda.set_device(device)
    device = torch.device("cuda", torch.cuda.current_device())
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    torch.cuda.manual_seed_all(0)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.use_deterministic_algorithms(True)
    torch.cuda.reset_peak_memory_stats(device)
    model_started = time.perf_counter()
    model = load_safetensors_model(assets[1]).eval().to(device)
    if model.samplerate != MODEL_RATE or model.audio_channels != 2 or "vocals" not in model.sources:
        raise ValueError("Loaded checkpoint is not the expected 44100 Hz stereo vocal separator")
    if any(parameter.device != device for parameter in model.parameters()):
        raise RuntimeError("Model parameters are not all on the requested CUDA device")
    torch.cuda.synchronize(device)
    model_load_s = time.perf_counter() - model_started
    forward_evidence: dict[str, Any] = {"count": 0, "input_devices": [], "output_devices": []}

    def check_forward(module: Any, args: Any, result: Any) -> None:
        observed_input, observed_output = str(args[0].device), str(result.device)
        if args[0].device != device or result.device != device:
            raise RuntimeError("A separator forward pass ran outside the requested CUDA device")
        forward_evidence["count"] += 1
        for key, value in (("input_devices", observed_input), ("output_devices", observed_output)):
            if value not in forward_evidence[key]:
                forward_evidence[key].append(value)

    hook = model.register_forward_hook(check_forward)
    processing_started = time.perf_counter()
    try:
        with torch.inference_mode():
            # A writable copy keeps torch.frombuffer independent of the immutable input bytes.
            mono = torch.frombuffer(bytearray(pcm), dtype=torch.int16).to(torch.float32) / 32768
            input_peak = float(mono.abs().max())
            input_rms = float(mono.square().mean().sqrt())
            high_rate = julius.resample_frac(mono[None], SAMPLE_RATE, MODEL_RATE, full=True)
            if high_rate.shape[-1] != resampled_length(len(mono), SAMPLE_RATE, MODEL_RATE):
                raise RuntimeError("Unexpected input resampling length")
            stereo = high_rate.expand(2, -1)
            ref = stereo.mean(0)
            mean, std = ref.mean(), ref.std() + 1e-8
            prediction = apply_model(model, ((stereo - mean) / std)[None], device=device,
                                     shifts=0, split=True, overlap=0.25, transition_power=1,
                                     num_workers=0, progress=False)
            if forward_evidence["count"] < 1:
                raise RuntimeError("No CUDA model forward was observed")
            if tuple(prediction.shape) != (1, len(model.sources), 2, high_rate.shape[-1]):
                raise RuntimeError("Separator changed the intermediate audio length or channel layout")
            vocals = (prediction[0, model.sources.index("vocals")] * std + mean).mean(0)[None]
            restored = julius.resample_frac(vocals.cpu(), MODEL_RATE, SAMPLE_RATE, full=True)[0]
            tail_trim = trim_count(restored.shape[-1], input_identity["samples"])
            restored = restored[:input_identity["samples"]]
            if not bool(torch.isfinite(restored).all()):
                raise RuntimeError("Separator output contains nonfinite samples")
            output_peak = float(restored.abs().max())
            output_rms = float(restored.square().mean().sqrt())
            upper = 32767 / 32768
            clipped_samples = int(((restored < -1) | (restored > upper)).sum())
            # Do not peak-normalize: preserve recovered amplitude and clamp only at PCM16 bounds.
            quantized = torch.round(restored.clamp(-1, upper) * 32768).to(torch.int16)
            output_pcm = quantized.numpy().astype("<i2", copy=False).tobytes()
            torch.cuda.synchronize(device)
    finally:
        hook.remove()
    processing_s = time.perf_counter() - processing_started
    if sha256(audio) != input_identity["file_sha256"]:
        raise RuntimeError("Source audio changed during processing")
    for entry in asset_identity:
        if sha256(Path(entry["path"])) != entry["file_sha256"]:
            raise RuntimeError("Model assets changed during processing")
    # Reserve a unique result directory; failed or completed runs are never overwritten.
    out.mkdir(parents=True, exist_ok=False)
    wav_path = out / "vocals.wav"
    with wav_path.open("xb") as stream, wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(output_pcm)
    manifest = {
        "schema_version": 1, "component": "demucs-vocals", "status": "ok",
        "input": input_identity,
        "output": {"path": str(wav_path), "file_sha256": sha256(wav_path),
                   "pcm_sha256": hashlib.sha256(output_pcm).hexdigest(), "samples": len(output_pcm) // 2,
                   "sample_rate": SAMPLE_RATE, "channels": 1, "representation": "PCM16"},
        "timeline": {"source_origin_s": offset, "source_origin_sample": origin,
                     "source_end_sample_exclusive": origin + input_identity["samples"],
                     "mapping": "source sample = source_origin_sample + output sample",
                     "start_shift_samples": 0, "tail_trim_samples": tail_trim,
                     "acoustic_delay_verified": False},
        "model": {"name": "htdemucs", "signature": MODEL_SIGNATURE, "single_model": True,
                  "repo_id": "adefossez/HTDemucs", "provisioning_revision": MODEL_REVISION,
                  "assets": asset_identity, "sources": list(model.sources),
                  "model_sample_rate": MODEL_RATE, "segment_s": float(model.segment)},
        "config": {"loader": "demucs.hf.load_safetensors_model(local_path)", "offline": True,
                   "shifts": 0, "split": True, "overlap": 0.25, "transition_power": 1,
                   "num_workers": 0, "seed": 0, "deterministic_algorithms": True,
                   "tf32": False, "resampler": "julius.resample_frac(full=True)",
                   "stereo_conversion": "duplicate mono input", "mono_conversion": "mean vocal channels",
                   "input_normalization": "(stereo - mono.mean()) / (mono.std() + 1e-8)",
                   "output_amplitude": "restore std and mean; no peak normalization; PCM16 clamp"},
        "amplitude": {"input_peak": input_peak, "input_rms": input_rms,
                      "normalization_mean": float(mean), "normalization_std": float(std),
                      "output_peak_before_clamp": output_peak, "output_rms_before_clamp": output_rms,
                      "pcm16_clipped_samples": clipped_samples},
        "device": {"requested": device_name, "actual": str(device),
                   "gpu_name": torch.cuda.get_device_name(device), "precision": "float32",
                   "forward_evidence": forward_evidence,
                   "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                   "peak_reserved_bytes": torch.cuda.max_memory_reserved(device)},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "torch_cuda": torch.version.cuda,
                    "packages": {name: importlib.metadata.version(name) for name in
                                 ("demucs", "torch", "julius", "numpy", "safetensors", "PyYAML")}},
        "implementation": {"adapter": {"path": str(Path(__file__).resolve()),
                                       "sha256": sha256(Path(__file__))},
                           "loader": source_identity(load_safetensors_model),
                           "apply_model": source_identity(apply_model),
                           "model_class": source_identity(type(model)),
                           "resampler": source_identity(julius.resample_frac)},
        "timing": {"model_load_s": model_load_s, "processing_s": processing_s,
                   "total_wall_s": time.perf_counter() - started},
    }
    with (out / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--offset", type=float, default=0)
    parser.add_argument("--device", default="cuda:0")
    args = parser.parse_args()
    manifest = separate(args.audio, args.repo, args.out, args.offset, args.device)
    print(json.dumps({"status": manifest["status"], "manifest": str(args.out.resolve() / "manifest.json")}))


if __name__ == "__main__":
    main()
