"""Offline CUDA Pyannote speech crops, retaining each original source sample offset."""
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
import time
from typing import Any
import wave

if __package__:
    from .separate import read_pcm, sha256, source_origin_sample, validate_output
else:
    from separate import read_pcm, sha256, source_origin_sample, validate_output

RATE = 16000
MAX_SAMPLES = 30 * RATE
PADDING_SAMPLES = RATE // 5


def padded_chunks(native: list[dict[str, Any]], samples: int) -> list[dict[str, Any]]:
    """Keep native cuts; constrain added context and deduplicate samples at gap midpoints."""
    if samples < 1:
        raise ValueError("Input must contain at least one sample")
    cores: list[tuple[int, int, int]] = []
    previous_time = 0.0
    previous_sample = 0
    for native_index, interval in enumerate(native):
        start, end = interval["start"], interval["end"]
        if not all(math.isfinite(value) for value in (start, end)) or end <= start:
            raise ValueError("Native VAD intervals must be finite and nonempty")
        if start < previous_time - 1e-6:
            raise ValueError("Native VAD intervals must be ordered and nonoverlapping")
        previous_time = end
        # Cover rounded endpoints; a shared boundary sample belongs to the earlier crop.
        begin = min(samples, max(previous_sample, 0, math.floor(start * RATE)))
        finish = min(samples, max(0, math.ceil(end * RATE)))
        previous_sample = max(previous_sample, finish)
        while finish > begin:
            stop = min(finish, begin + MAX_SAMPLES)
            cores.append((begin, stop, native_index))
            begin = stop
    result: list[dict[str, Any]] = []
    for index, (start, end, native_index) in enumerate(cores):
        lower = 0 if index == 0 else (cores[index - 1][1] + start) // 2
        upper = samples if index + 1 == len(cores) else (end + cores[index + 1][0]) // 2
        begin, finish = max(lower, start - PADDING_SAMPLES), min(upper, end + PADDING_SAMPLES)
        # Preserve the core speech range, trimming only added context to enforce 30 seconds.
        excess = max(0, finish - begin - MAX_SAMPLES)
        cut_left = min(start - begin, (excess + 1) // 2)
        begin += cut_left
        excess -= cut_left
        cut_right = min(finish - end, excess)
        finish -= cut_right
        excess -= cut_right
        begin += excess
        if not begin <= start < end <= finish or finish - begin > MAX_SAMPLES:
            raise RuntimeError("Cannot retain native speech within the crop duration limit")
        result.append({"start_sample": begin, "end_sample_exclusive": finish,
                       "speech_start_sample": start, "speech_end_sample_exclusive": end,
                       "padding_before_samples": start - begin, "padding_after_samples": finish - end,
                       "native_chunk_index": native_index})
    return result


def write_crop(path: Path, pcm: bytes, start: int, end: int) -> dict[str, Any]:
    if not 0 <= start < end <= len(pcm) // 2:
        raise ValueError("Crop must be a nonempty subset of the input PCM")
    cropped = pcm[start * 2:end * 2]
    with path.open("xb") as stream, wave.open(stream, "wb") as output:
        output.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        output.writeframes(cropped)
    return {"path": str(path.resolve()), "file_sha256": sha256(path),
            "pcm_sha256": hashlib.sha256(cropped).hexdigest(), "samples": end - start,
            "sample_rate": RATE, "channels": 1, "representation": "PCM16"}


def run(audio: Path, out: Path, offset: float = 0, device_index: int = 0) -> dict[str, Any]:
    started = time.perf_counter()
    origin = source_origin_sample(offset)
    if device_index < 0:
        raise ValueError("CUDA device index must be nonnegative")
    out = validate_output(out, Path(__file__).resolve().parents[2] / ".local")
    pcm, input_identity = read_pcm(audio)
    # All optional model/cache operations are restricted to local assets and the workspace.
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[name] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    cache = Path(__file__).resolve().parents[2] / ".local" / "cache" / "component-vad"
    os.environ["HF_HOME"] = str(cache)
    os.environ["TORCH_HOME"] = str(cache / "torch")
    import torch
    import whisperx
    from whisperx.vads.pyannote import Pyannote
    from whisperx.vads.vad import Vad

    if importlib.metadata.version("whisperx") != "3.8.6":
        raise RuntimeError("This frozen experiment requires the existing WhisperX 3.8.6 environment")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; VAD CPU fallback is disabled")
    device = torch.device("cuda", device_index)
    torch.cuda.set_device(device)
    torch.manual_seed(0)
    torch.backends.cudnn.benchmark = False
    torch.cuda.reset_peak_memory_stats(device)
    checkpoint = Path(whisperx.__file__).parent / "assets" / "pytorch_model.bin"
    checkpoint_hash = sha256(checkpoint)
    load_started = time.perf_counter()
    vad = Pyannote(device=device, model_fp=str(checkpoint), vad_onset=0.5, vad_offset=0.363)
    # Pyannote's pipeline has no public accessor for the inference module; this is evidence only.
    module = vad.vad_pipeline._segmentation.model
    if any(parameter.device != device for parameter in module.parameters()):
        raise RuntimeError("The packaged Pyannote model is not on the requested CUDA device")
    evidence: dict[str, Any] = {"count": 0, "input_devices": [], "output_devices": []}

    def observe(mod: Any, args: Any, output: Any) -> None:
        if args[0].device != device or output.device != device:
            raise RuntimeError("A VAD forward ran outside the requested CUDA device")
        evidence["count"] += 1
        for key, value in (("input_devices", str(args[0].device)), ("output_devices", str(output.device))):
            if value not in evidence[key]:
                evidence[key].append(value)

    hook = module.register_forward_hook(observe)
    torch.cuda.synchronize(device)
    load_s = time.perf_counter() - load_started
    infer_started = time.perf_counter()
    try:
        with torch.inference_mode():
            waveform = torch.frombuffer(bytearray(pcm), dtype=torch.int16).float()[None] / 32768
            scores = vad({"waveform": waveform, "sample_rate": RATE})
            native = vad.merge_chunks(scores, chunk_size=30, onset=0.5, offset=0.363)
            native = [{"start": float(chunk["start"]), "end": float(chunk["end"]),
                       "segments": [[float(start), float(end)] for start, end in chunk["segments"]]}
                      for chunk in native]
        torch.cuda.synchronize(device)
    finally:
        hook.remove()
    infer_s = time.perf_counter() - infer_started
    if evidence["count"] < 1:
        raise RuntimeError("No CUDA VAD forward was observed")
    crops = padded_chunks(native, input_identity["samples"])
    if sha256(audio) != input_identity["file_sha256"] or sha256(checkpoint) != checkpoint_hash:
        raise RuntimeError("Audio or model checkpoint changed during VAD processing")
    out.mkdir(parents=True, exist_ok=False)
    for index, crop in enumerate(crops):
        crop["audio"] = write_crop(out / f"chunk-{index:04}.wav", pcm,
                                   crop["start_sample"], crop["end_sample_exclusive"])
        crop["source_start_sample"] = origin + crop["start_sample"]
        crop["source_end_sample_exclusive"] = origin + crop["end_sample_exclusive"]
        crop["source_offset_s"] = crop["source_start_sample"] / RATE
    source = Path(inspect.getfile(Pyannote))
    merge_source = Path(inspect.getfile(Vad))
    manifest = {
        "schema_version": 1, "component": "pyannote-vad-speech-crops", "status": "ok",
        "input": input_identity, "source_origin_s": offset, "source_origin_sample": origin,
        "chunks": crops, "native_chunks": native, "empty_speech": not bool(crops),
        "config": {"onset": 0.5, "offset": 0.363, "chunk_size_s": 30,
                   "binarize_min_duration_on_s": 0, "binarize_min_duration_off_s": 0,
                   "native_padding_s": 0, "requested_crop_context_s": 0.2,
                   "context_policy": "clip at input edge/gap midpoint; trim context only to keep 30s",
                   "oversize_core_policy": "split a native core exceeding 30s at 480000 samples",
                   "endpoint_rounding": "floor onset, ceil offset; shared sample assigned to earlier crop",
                   "concatenated_audio": False, "masking": False, "seed": 0},
        "model": {"source": "WhisperX packaged Pyannote checkpoint", "path": str(checkpoint),
                  "file_sha256": checkpoint_hash},
        "device": {"requested": str(device), "actual": str(next(module.parameters()).device),
                   "precision": str(next(module.parameters()).dtype),
                   "gpu_name": torch.cuda.get_device_name(device), "forward_evidence": evidence,
                   "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
                   "peak_reserved_bytes": torch.cuda.max_memory_reserved(device)},
        "implementation": {"adapter_sha256": sha256(Path(__file__)),
                           "pyannote_wrapper": {"path": str(source), "sha256": sha256(source)},
                           "native_merge": {"path": str(merge_source), "sha256": sha256(merge_source)}},
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "torch_cuda": torch.version.cuda,
                    "packages": {name: importlib.metadata.version(name)
                                 for name in ("whisperx", "pyannote.audio", "torch")}},
        "timing": {"load_s": load_s, "inference_s": infer_s,
                   "total_wall_s": time.perf_counter() - started},
    }
    with (out / "manifest.json").open("x", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2, allow_nan=False)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--offset", type=float, default=0)
    parser.add_argument("--device-index", type=int, default=0)
    args = parser.parse_args()
    result = run(args.audio, args.out, args.offset, args.device_index)
    print(json.dumps({"status": result["status"], "chunks": len(result["chunks"]),
                      "manifest": str(args.out.resolve() / "manifest.json")}))


if __name__ == "__main__":
    main()
