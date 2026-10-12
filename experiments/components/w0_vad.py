"""Bounded W0 companion using CUDA Pyannote intervals through public clip_timestamps."""
from __future__ import annotations

import argparse
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any

# Support both direct CLI and namespace-package unittest/module execution.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.components.separate import read_pcm, sha256, source_origin_sample
from experiments.whisper.run import ct2_device, evaluation, local_model, model_identity, plain

RATE = 16000
FRAME_RATE = 100


def validate_vad(manifest: dict[str, Any], identity: dict[str, Any], offset: float) -> dict[str, Any]:
    """Bind CUDA evidence and the complete timeline before giving intervals to the ASR."""
    origin = source_origin_sample(offset)
    if manifest.get("status") != "ok" or manifest.get("component") != "pyannote-vad-speech-crops":
        raise ValueError("A successful standalone Pyannote VAD manifest is required")
    vad_input = manifest.get("input", {})
    for key in ("file_sha256", "pcm_sha256", "samples", "sample_rate", "channels"):
        if vad_input.get(key) != identity.get(key):
            raise ValueError(f"VAD input identity differs from ASR input: {key}")
    if manifest.get("source_origin_s") != offset or manifest.get("source_origin_sample") != origin:
        raise ValueError("VAD source origin differs from ASR source origin")
    frozen = {"onset": 0.5, "offset": 0.363, "chunk_size_s": 30,
              "binarize_min_duration_on_s": 0, "binarize_min_duration_off_s": 0,
              "native_padding_s": 0, "requested_crop_context_s": 0.2,
              "concatenated_audio": False, "masking": False}
    if any(manifest.get("config", {}).get(key) != value for key, value in frozen.items()):
        raise ValueError("VAD manifest does not use this experiment's frozen native configuration")
    device = manifest.get("device", {})
    actual = device.get("actual", "")
    forward = device.get("forward_evidence", {})
    if (not isinstance(actual, str) or not actual.startswith("cuda:") or forward.get("count", 0) < 1
            or forward.get("input_devices") != [actual] or forward.get("output_devices") != [actual]):
        raise ValueError("VAD manifest lacks actual CUDA forward evidence")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or manifest.get("empty_speech") is not (len(chunks) == 0):
        raise ValueError("VAD empty-speech status and chunk list are inconsistent")
    timestamps: list[float] = []
    intervals: list[dict[str, Any]] = []
    previous_end = 0
    previous_frame_end = 0
    for chunk in chunks:
        start, end = chunk.get("start_sample"), chunk.get("end_sample_exclusive")
        if (type(start) is not int or type(end) is not int
                or not 0 <= previous_end <= start < end <= identity["samples"]
                or end - start > 30 * RATE):
            raise ValueError("VAD crop intervals must be ordered, nonoverlapping, and at most 30 seconds")
        if (chunk.get("source_start_sample") != origin + start
                or chunk.get("source_end_sample_exclusive") != origin + end
                or chunk.get("source_offset_s") != (origin + start) / RATE):
            raise ValueError("VAD chunk source sample mapping is inconsistent")
        start_s, end_s = start / RATE, end / RATE
        frame_start, frame_end = round(start_s * FRAME_RATE), round(end_s * FRAME_RATE)
        if not previous_frame_end <= frame_start < frame_end:
            raise ValueError("VAD interval collapses or overlaps on faster-whisper's 10 ms frame grid")
        timestamps.extend((start_s, end_s))
        intervals.append({"start_sample": start, "end_sample_exclusive": end,
                          "source_start_sample": origin + start, "source_end_sample_exclusive": origin + end,
                          "requested_start_s": start_s, "requested_end_s": end_s,
                          "effective_seek_start_frame": frame_start, "effective_seek_end_frame": frame_end,
                          "effective_seek_start_s": frame_start / FRAME_RATE,
                          "effective_seek_end_s": frame_end / FRAME_RATE})
        previous_end, previous_frame_end = end, frame_end
    return {"clip_timestamps": timestamps, "intervals": intervals,
            "sample_mapping_exact": True, "asr_seek_resolution_s": 0.01,
            "requested_audio_duration_s": sum(c["end_sample_exclusive"] - c["start_sample"]
                                               for c in chunks) / RATE,
            "effective_seek_policy": "round(timestamp * 100); final end capped by original content frames",
            "empty_speech": not bool(chunks)}


def transcribe_intervals(asr: Any, waveform: Any, clips: list[float]) -> tuple[list[dict[str, Any]], Any]:
    """Bypass the public API for empty VAD because an empty clip list means full audio."""
    if not clips:
        return [], None
    if len(clips) % 2:
        raise ValueError("Explicit start/end pairs are required; implicit full-audio tails are prohibited")
    segments, info = asr.transcribe(waveform, language="ja", task="transcribe", beam_size=5,
                                    word_timestamps=True, vad_filter=False, chunk_length=30,
                                    condition_on_previous_text=False, clip_timestamps=clips)
    return [plain(segment) for segment in segments], plain(info)


def execute(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    pcm, identity = read_pcm(Path(args.audio))
    vad_path = Path(args.vad_manifest).resolve()
    vad_hash = sha256(vad_path)
    vad = json.loads(vad_path.read_text(encoding="utf-8"))
    contract = validate_vad(vad, identity, args.offset)
    if args.device_index < 0:
        raise ValueError("CUDA device index must be nonnegative")
    stages: dict[str, float] = {"audio_and_vad_validation_s": time.perf_counter() - started}
    original: list[dict[str, Any]] = []
    info = None
    devices: dict[str, Any] = {"vad": vad["device"]}
    models: dict[str, Any] = {"vad": vad["model"]}
    runtimes: list[dict[str, Any]] = []
    upstream_source: dict[str, Any] = {"imported": False, "reason": "empty VAD bypasses ASR"}
    dll_handles = []
    if not contract["empty_speech"]:
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
            os.environ[name] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["HF_HOME"] = str(Path(args.cache).resolve())
        for directory in args.dll_dir:
            resolved = Path(directory).resolve()
            if not resolved.is_dir():
                raise FileNotFoundError(f"DLL directory not found: {resolved}")
            os.environ["PATH"] = str(resolved) + os.pathsep + os.environ.get("PATH", "")
            if os.name == "nt":
                dll_handles.append(os.add_dll_directory(str(resolved)))
            acquisition = resolved / "acquisition.json"
            runtimes.append({"directory": str(resolved), "acquisition":
                             json.loads(acquisition.read_text(encoding="utf-8-sig"))
                             if acquisition.exists() else None})
        import ctranslate2
        import numpy as np
        from faster_whisper import WhisperModel
        if importlib.metadata.version("faster-whisper") != "1.2.1":
            raise RuntimeError("This experiment requires the frozen faster-whisper 1.2.1 environment")
        if ctranslate2.get_cuda_device_count() <= args.device_index:
            raise RuntimeError("The requested CTranslate2 CUDA device is unavailable; no CPU fallback")
        native_source = Path(inspect.getfile(WhisperModel))
        upstream_source = {"imported": True, "path": str(native_source), "sha256": sha256(native_source)}
        model_path = local_model(args.model, ("model.bin", "config.json", "tokenizer.json", "vocabulary.json"))
        models["asr"] = model_identity(model_path)
        mark = time.perf_counter()
        asr = WhisperModel(model_path, device="cuda", device_index=args.device_index,
                           compute_type="float16", local_files_only=True)
        stages["asr_load_s"] = time.perf_counter() - mark
        devices["asr"] = {**ct2_device(asr), "inference_requested": True,
                          "forward_hook_available": False,
                          "evidence_scope": "CTranslate2 configured CUDA device and compute type; consumed generator"}
        if devices["asr"]["compute_type"] != "float16":
            raise RuntimeError("CTranslate2 did not retain requested float16 compute type")
        if devices["asr"]["device_index"] not in (args.device_index, [args.device_index]):
            raise RuntimeError("CTranslate2 did not retain requested CUDA device index")
        waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        mark = time.perf_counter()
        original, info = transcribe_intervals(asr, waveform, contract["clip_timestamps"])
        stages["asr_s"] = time.perf_counter() - mark
        del asr
    else:
        devices["asr"] = {"inference_requested": False, "inference_executed": False,
                          "gpu_qualified": False, "reason": "empty VAD bypasses ASR"}
        stages["asr_load_s"] = stages["asr_s"] = 0
    if sha256(Path(args.audio)) != identity["file_sha256"] or sha256(vad_path) != vad_hash:
        raise RuntimeError("Audio or VAD manifest changed during transcription")
    result = evaluation(original, original, args.offset, character=False)
    result.update({
        "route": "W0-pyannote-vad-clips", "input": identity, "offset_s": args.offset,
        "source_start_seconds": args.offset, "duration_seconds": identity["duration_s"],
        "original_segments": original, "native": {"segments": original, "info": info},
        "effective_parameters": {"transcribe": {"language": "ja", "task": "transcribe", "beam_size": 5,
            "word_timestamps": True, "vad_filter": False, "chunk_length": 30,
            "condition_on_previous_text": False, "clip_timestamps": contract["clip_timestamps"]},
            "temperature": "unchanged native fallback defaults", "info": info},
        "model_identity": models, "devices": devices, "runtime_identity": runtimes,
        "experimental_vad": {"manifest": str(vad_path), "file_sha256": vad_hash,
                             "config": vad["config"], **contract,
                             "audio_transform": "original complete PCM; clips use original feature/time coordinates"},
        "stages": {**stages, "total_s": time.perf_counter() - started},
        "phase_costs": {"external_vad_timing": vad["timing"], "vad_not_included_in_asr_process_total": True},
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}},
        "offline_requested": True, "cached_inference": False,
        "implementation": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__)),
                           "base_helpers_sha256": sha256(Path(__file__).parents[1] / "whisper" / "run.py"),
                           "faster_whisper_source": upstream_source},
    })
    return plain(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--vad-manifest", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offset", type=float, default=0)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--dll-dir", action="append", default=[])
    parser.add_argument("--cache", default=".local/cache/whisper-runtime")
    args = parser.parse_args()
    output = args.output.resolve()
    private = Path(__file__).resolve().parents[2] / ".local"
    if not output.is_relative_to(private) or output == private:
        raise ValueError("Output must be a new JSON file under the workspace .local")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    result = execute(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"output": str(output), "empty_vad": result["experimental_vad"]["empty_speech"]}))


if __name__ == "__main__":
    main()
