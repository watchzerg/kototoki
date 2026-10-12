"""Offline, GPU-only Whisper experiment adapter; acquisition is separate."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import dataclasses
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import wave
from typing import Any


def plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if hasattr(value, "_asdict"):
        return plain(value._asdict())
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, "item"):
        return plain(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def read_audio(path: Path) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    if not path.is_file():
        raise FileNotFoundError(f"Audio not found: {path}")
    with wave.open(str(path), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, 16000, 2):
            raise ValueError("Prepared audio must be mono 16000 Hz PCM16 WAV")
        pcm = source.readframes(source.getnframes())
    if not pcm:
        raise ValueError("Empty audio")
    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return audio, {"path": str(path.resolve()), "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "pcm_sha256": hashlib.sha256(pcm).hexdigest(), "sample_rate": 16000,
                   "channels": 1, "samples": len(audio), "duration_s": len(audio) / 16000,
                   "representation": "float32 PCM16 / 32768", "silent": bool(np.max(np.abs(audio)) == 0)}


def evaluation(original: list[dict[str, Any]], timed: list[dict[str, Any]], offset: float,
               character: bool = False) -> dict[str, Any]:
    """Map native units monotonically into complete original text, preserving failures."""
    text = "".join(s["text"] for s in original)
    units: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    cursor = 0
    for segment in timed:
        label = segment["text"]
        pos = text.find(label, cursor)
        if pos < 0:
            # Alignment may change sentence whitespace. Keep original text and mark unmapped.
            continue
        cursor = pos + len(label)
        if (segment.get("start") is not None and segment.get("end") is not None
                and segment["start"] >= 0 and segment["end"] >= segment["start"]):
            cues.append({"text": label, "start": segment["start"] + offset, "end": segment["end"] + offset})
        native_units = segment.get("chars" if character else "words") or []
        local_cursor = 0
        for native in native_units:
            unit_text = native.get("char" if character else "word", "")
            if not unit_text:
                continue
            unit_pos = label.find(unit_text, local_cursor)
            if unit_pos < 0:
                continue
            local_cursor = unit_pos + len(unit_text)
            start, end = native.get("start"), native.get("end")
            valid = start is not None and end is not None and start >= 0 and end >= start
            units.append({"char_start": pos + unit_pos, "char_end": pos + local_cursor,
                          "start": start + offset if valid else None, "end": end + offset if valid else None,
                          "granularity": "character" if character else "word",
                          "time_source": "api" if character else "native", "status": "ok" if valid else "text_only"})
    covered = [False] * len(text)
    for unit in units:
        for index in range(unit["char_start"], unit["char_end"]):
            covered[index] = True
    begin = None
    for index in range(len(text) + 1):
        missing = index < len(text) and not covered[index]
        if missing and begin is None:
            begin = index
        if not missing and begin is not None:
            units.append({"char_start": begin, "char_end": index, "start": None, "end": None,
                          "granularity": "segment", "time_source": "fallback", "status": "text_only"})
            begin = None
    units.sort(key=lambda unit: unit["char_start"])
    return {"schema_version": 1, "text": text, "units": units, "cues": cues}


def local_model(path: str | None, files: tuple[str, ...]) -> str:
    if not path or not Path(path).is_dir():
        raise ValueError(f"A provisioned local model directory is required: {path}")
    for name in files:
        if not (Path(path) / name).is_file():
            raise FileNotFoundError(f"Missing offline model asset: {Path(path) / name}")
    return str(Path(path).resolve())


def model_identity(path: str) -> dict[str, Any]:
    directory = Path(path)
    acquisition = directory / "acquisition.json"
    if not acquisition.exists():
        acquisition = directory.parent.parent / "manifests" / f"model-{directory.name}.json"
    return {"path": path, "acquisition": json.loads(acquisition.read_text(encoding="utf-8")) if acquisition.exists() else None,
            "files": [{"name": f.name, "bytes": f.stat().st_size} for f in directory.iterdir() if f.is_file()]}


def ct2_device(model: Any) -> dict[str, Any]:
    inner = model.model
    evidence = {"device": inner.device, "device_index": plain(inner.device_index), "compute_type": inner.compute_type}
    if evidence["device"] != "cuda":
        raise RuntimeError(f"CPU fallback prohibited: {evidence}")
    return evidence


def execute(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    vad_overrides = {key: value for key, value in (("vad_onset", args.vad_onset), ("vad_offset", args.vad_offset))
                     if value is not None}
    if vad_overrides and args.route != "W1-native":
        raise ValueError("VAD onset/offset overrides apply only to W1-native")
    if any(not 0 < value < 1 for value in vad_overrides.values()):
        raise ValueError("VAD onset and offset must be between 0 and 1")
    if (args.ctc_nonblank_only or args.ctc_forced_align) and args.route == "W0":
        raise ValueError("CTC extraction experiments apply only to W1/W1-native")
    if args.ctc_nonblank_only and args.ctc_forced_align:
        raise ValueError("Choose transition-frame diagnostic or standard CTC token spans")
    if args.ctc_normalize and args.route == "W0":
        raise ValueError("CTC normalization applies only to W1/W1-native")
    if args.ctc_normalize and args.ctc_nonblank_only:
        raise ValueError("This bounded round keeps normalization and transition-frame diagnostics separate")
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[name] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HOME"] = str(Path(args.cache).resolve())
    os.environ["TORCH_HOME"] = str(Path(args.cache).resolve() / "torch")
    os.environ["NLTK_DATA"] = str(Path(args.nltk_data).resolve())
    dll_handles = []
    runtimes = []
    for dll_dir in args.dll_dir:
        resolved = str(Path(dll_dir).resolve())
        if not Path(resolved).is_dir():
            raise FileNotFoundError(f"DLL directory not found: {resolved}")
        os.environ["PATH"] = resolved + os.pathsep + os.environ.get("PATH", "")
        if os.name == "nt":
            dll_handles.append(os.add_dll_directory(resolved))
        runtime_manifest = Path(resolved) / "acquisition.json"
        runtimes.append({"directory": resolved, "acquisition": json.loads(runtime_manifest.read_text(encoding="utf-8-sig"))
                         if runtime_manifest.exists() else None})
    audio, identity = read_audio(Path(args.audio))
    stages = {"audio_load_s": time.perf_counter() - started}
    devices: dict[str, Any] = {}
    effective: dict[str, Any] = {}
    models: dict[str, Any] = {}
    import ctranslate2
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("No CTranslate2 CUDA device; CPU fallback prohibited")
    if args.route != "W1":
        model_path = local_model(args.model, ("model.bin", "config.json", "tokenizer.json", "vocabulary.json"))
        models["asr"] = model_identity(model_path)
        mark = time.perf_counter()
        if args.route == "W0":
            from faster_whisper import WhisperModel
            asr = WhisperModel(model_path, device="cuda", device_index=args.device_index,
                               compute_type=args.compute_type, local_files_only=True)
            stages["asr_load_s"] = time.perf_counter() - mark
            devices["asr"] = ct2_device(asr)
            mark = time.perf_counter()
            kwargs: dict[str, Any] = {"language": "ja", "task": "transcribe", "beam_size": args.beam,
                                     "word_timestamps": True, "vad_filter": args.vad, "chunk_length": args.chunk}
            if args.condition_previous is not None:
                kwargs["condition_on_previous_text"] = args.condition_previous
            if args.temperature_zero:
                kwargs["temperature"] = 0.0
            segments, info = asr.transcribe(audio, **kwargs)
            original = [plain(segment) for segment in segments]
            if args.vad:
                from faster_whisper.vad import get_vad_model
                devices["vad"] = {"providers": get_vad_model().session.get_providers(),
                                  "native_builtin_preprocessing": True}
            native = {"segments": original, "info": plain(info)}
            effective = {"transcribe": kwargs, "info": plain(info)}
        else:
            import torch
            import whisperx
            if not torch.cuda.is_available():
                raise RuntimeError("PyTorch CUDA unavailable; VAD/FA CPU fallback prohibited")
            asr = whisperx.load_model(model_path, "cuda", device_index=args.device_index,
                                     compute_type=args.compute_type, language="ja", task="transcribe",
                                     asr_options={"beam_size": args.beam}, vad_method="pyannote",
                                     vad_options=vad_overrides or None, local_files_only=True)
            stages["asr_load_s"] = time.perf_counter() - mark
            devices["asr"] = ct2_device(asr.model)
            devices["vad"] = {"requested_device": f"cuda:{args.device_index}", "forward_observation": []}
            vad_asset = Path(whisperx.__file__).parent / "assets" / "pytorch_model.bin"
            models["vad"] = {"source": "WhisperX packaged checkpoint", "path": str(vad_asset),
                             "sha256": hashlib.sha256(vad_asset.read_bytes()).hexdigest()}
            vad_pipeline = asr.vad_model.vad_pipeline
            vad_module = vad_pipeline._segmentation.model
            if next(vad_module.parameters()).device.type != "cuda":
                raise RuntimeError("Pyannote VAD model is not on CUDA")
            def record_vad(module: Any, inputs: Any) -> None:
                if inputs[0].device.type != "cuda":
                    raise RuntimeError("VAD forward input is not on CUDA")
                devices["vad"]["forward_observation"].append({"model": str(next(module.parameters()).device),
                                                            "dtype": str(next(module.parameters()).dtype),
                                                            "input": str(inputs[0].device), "input_dtype": str(inputs[0].dtype)})
            hook = vad_module.register_forward_pre_hook(record_vad)
            effective = {"asr_options": plain(asr.options), "vad": plain(asr._vad_params),
                         "vad_overrides": vad_overrides,
                         "generator_effective_keys": ["beam_size", "patience", "length_penalty", "suppress_blank",
                                                     "suppress_tokens", "no_repeat_ngram_size", "repetition_penalty"],
                         "batch_size": args.batch, "chunk_size": args.chunk}
            mark = time.perf_counter()
            native = asr.transcribe(audio, batch_size=args.batch, chunk_size=args.chunk, verbose=False)
            hook.remove()
            original = plain(native["segments"])
        stages["asr_s"] = time.perf_counter() - mark
        del asr
    else:
        saved = json.loads(Path(args.asr_result).read_text(encoding="utf-8"))
        if saved["input"]["pcm_sha256"] != identity["pcm_sha256"]:
            raise ValueError("Saved ASR PCM identity differs from alignment input")
        if saved.get("offset_s") != args.offset:
            raise ValueError("Saved ASR source offset differs from alignment input")
        original = saved["original_segments"]
        native = {"reused_asr_file": str(Path(args.asr_result).resolve()), "segments": original}
        effective["asr_reused"] = True
    timed = original
    experimental = None
    normalization = None
    if args.route != "W0":
        import torch
        import whisperx
        import nltk
        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch CUDA unavailable; aligner CPU fallback prohibited")
        nltk.data.find("tokenizers/punkt_tab/english/")
        torch.cuda.empty_cache()
        align_path = local_model(args.align_model, ("config.json", "vocab.json", "preprocessor_config.json"))
        models["aligner"] = model_identity(align_path)
        mark = time.perf_counter()
        device = f"cuda:{args.device_index}"
        aligner, metadata = whisperx.load_align_model("ja", device, model_name=align_path, model_cache_only=True)
        stages["align_load_s"] = time.perf_counter() - mark
        devices["aligner"] = {"model": str(next(aligner.parameters()).device),
                              "dtype": str(next(aligner.parameters()).dtype), "forward_observation": []}
        if next(aligner.parameters()).device.type != "cuda":
            raise RuntimeError("Aligner model is not on CUDA")
        def record_align(module: Any, inputs: Any) -> None:
            if inputs[0].device.type != "cuda":
                raise RuntimeError("Aligner forward input is not on CUDA")
            devices["aligner"]["forward_observation"].append(str(inputs[0].device))
        hook = aligner.register_forward_pre_hook(record_align)
        search = [{**s, "start": max(0, s["start"] - args.padding),
                   "end": min(identity["duration_s"], s["end"] + args.padding)} for s in original]
        normalization_context = nullcontext(None)
        if args.ctc_normalize:
            if importlib.metadata.version("whisperx") != "3.8.6" or metadata["type"] != "huggingface":
                raise ValueError("Normalization probe is pinned to WhisperX 3.8.6 HuggingFace alignment")
            from transformers import Wav2Vec2FeatureExtractor
            from ctc_audio import SegmentNormalizer, normalize_segments
            extractor = Wav2Vec2FeatureExtractor.from_pretrained(align_path, local_files_only=True)
            normalizer = SegmentNormalizer(audio, search, metadata["dictionary"], extractor)
            normalization_context = normalize_segments(aligner, normalizer)
            stages["align_normalization_prepare_s"] = normalizer.preparation_seconds
        mark = time.perf_counter()
        context = nullcontext(None)
        if args.ctc_nonblank_only:
            if importlib.metadata.version("whisperx") != "3.8.6":
                raise ValueError("Transition-frame diagnostic is pinned to WhisperX 3.8.6")
            import whisperx.alignment as alignment_module
            from ctc_transition import capture_transitions
            context = capture_transitions(alignment_module, search, metadata["dictionary"], identity["duration_s"], enabled=True)
        if args.ctc_forced_align:
            if importlib.metadata.version("whisperx") != "3.8.6" or importlib.metadata.version("torchaudio").split("+")[0] != "2.8.0":
                raise ValueError("Standard CTC experiment requires pinned WhisperX 3.8.6 and TorchAudio 2.8.0")
            import whisperx.alignment as alignment_module
            from ctc_forced import capture_forced
            context = capture_forced(alignment_module, search, metadata["dictionary"], identity["duration_s"], device=device)
        with normalization_context as norm_recorder:
            with context as recorder:
                aligned = whisperx.align(search, aligner, metadata, audio, device, interpolate_method=args.interpolate,
                                         return_char_alignments=True)
        torch.cuda.synchronize()
        stages["align_s"] = time.perf_counter() - mark
        hook.remove()
        native["aligned"] = plain(aligned)
        native["align_search_segments"] = search
        effective.update({"padding": args.padding, "interpolate_method": args.interpolate,
                          "char_time_provenance": "API-returned; unknown-character wildcard and missing-time provenance not exposed"})
        timed = plain(aligned["segments"])
        if norm_recorder is not None:
            import inspect
            helper_path = Path(__file__).with_name("ctc_audio.py")
            extractor_source = Path(inspect.getfile(type(extractor)))
            normalization = {"algorithm": "official-wav2vec2-feature-extractor-segment-normalization-v1",
                             "native_character_extraction_unchanged": True, "asr_input_unchanged": True,
                             "formula": "(float32 waveform - valid-sample mean) / sqrt(valid-sample variance + 1e-7)",
                             "padding_policy": "exclude native <400 right-zero padding from statistics; restore padding zeros",
                             "model_attention_mask": "unchanged: not passed by native WhisperX",
                             "hash_representation": "little-endian float32 input_values bytes, including padding; source PCM16 identity is unchanged",
                             "feature_extractor_config": plain(extractor.to_dict()),
                             "feature_extractor_source_sha256": hashlib.sha256(extractor_source.read_bytes()).hexdigest(),
                             "helper_sha256": hashlib.sha256(helper_path.read_bytes()).hexdigest(),
                             "records": norm_recorder.records}
            stages["align_normalization_hook_s_included_in_align_s"] = norm_recorder.hook_seconds
            effective["ctc_normalize"] = True
        if recorder is not None:
            helper_path = Path(__file__).with_name("ctc_forced.py" if args.ctc_forced_align else "ctc_transition.py")
            upstream_path = Path(alignment_module.__file__)
            semantics = "ctc_nonblank_token_span" if args.ctc_forced_align else "ctc_transition_frame_interval"
            experimental = {"algorithm": "torchaudio-2.8-standard-ctc-nonblank-token-spans-v1" if args.ctc_forced_align else "whisperx-3.8.6-backtrack-token-transition-frame-v1",
                            "time_semantics": semantics,
                            "experimental_not_acoustic_duration": True,
                            "same_emissions_text_and_windows": True,
                            "native_words_and_cues_unchanged": True,
                            "frame_to_seconds": "same upstream mapping: original search-region duration / emission-frame count",
                            "time_source": "api", "rounded_seconds_decimals": 3,
                            "missing_evidence_policy": "Preserve original text as text_only; do not invent intervals",
                            "source_sha256": hashlib.sha256(upstream_path.read_bytes()).hexdigest(),
                            "helper_sha256": hashlib.sha256(helper_path.read_bytes()).hexdigest(),
                            "records": recorder.records, "derived_character_segments": recorder.derived_segments()}
            if args.ctc_forced_align:
                import inspect
                from torchaudio.functional import forced_align
                decoder_path = Path(inspect.getfile(forced_align))
                experimental.update({"decoder_source_sha256": hashlib.sha256(decoder_path.read_bytes()).hexdigest(),
                                     "native_capture_helper_sha256": hashlib.sha256(Path(__file__).with_name("ctc_transition.py").read_bytes()).hexdigest(),
                                     "new_neural_model": False, "decoder_requested_device": device,
                                     "topology": "standard CTC blank-expanded path with token self-loops; merge nonblank consecutive labels",
                                     "missing_evidence_policy": "Preserve all original text; OOV wildcard and decoder failures have no lexical timestamps",
                                     "maintenance_limit": "TorchAudio forced_align deprecated in 2.8 and removed in 2.9; this is an experimental pinned decoder"})
        del aligner
        torch.cuda.empty_cache()
    result = evaluation(original, timed, args.offset, character=args.route != "W0")
    if experimental is not None:
        native_evaluation = {**result, "source_start_seconds": args.offset, "duration_seconds": identity["duration_s"]}
        derived = evaluation(original, experimental["derived_character_segments"], args.offset, character=True)
        result = {**native_evaluation, "units": derived["units"], "native_evaluation": native_evaluation,
                  "experimental_alignment": experimental}
        for unit in result["units"]:
            unit["time_semantics"] = experimental["time_semantics"]
            unit["experimental_not_acoustic_duration"] = True
    stages["total_s"] = time.perf_counter() - started
    if normalization is not None:
        result["experimental_preprocessing"] = normalization
    result.update({"route": args.route, "input": identity, "offset_s": args.offset,
                   "source_start_seconds": args.offset, "duration_seconds": identity["duration_s"],
                   "original_segments": original, "native": native, "effective_parameters": effective,
                   "model_identity": models, "devices": devices, "stages": stages,
                   "runtime_identity": runtimes,
                   "environment": {"python": sys.version, "platform": platform.platform(),
                                   "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}},
                   "offline_requested": True, "cached_inference": False})
    result["implementation"] = {"path": str(Path(__file__).resolve()),
                                "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return plain(result)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--route", choices=("W0", "W1-native", "W1"), required=True)
    value.add_argument("--audio", required=True)
    value.add_argument("--output", required=True)
    value.add_argument("--model")
    value.add_argument("--align-model")
    value.add_argument("--asr-result")
    value.add_argument("--offset", type=float, default=0.0)
    value.add_argument("--device-index", type=int, default=0)
    value.add_argument("--compute-type", choices=("float16", "int8_float16"), default="float16")
    value.add_argument("--beam", type=int, default=5)
    value.add_argument("--vad", action="store_true")
    value.add_argument("--vad-onset", type=float, default=None, help="W1-native only; stable default 0.500")
    value.add_argument("--vad-offset", type=float, default=None, help="W1-native only; stable default 0.363")
    value.add_argument("--condition-previous", action=argparse.BooleanOptionalAction, default=None)
    value.add_argument("--temperature-zero", action="store_true")
    value.add_argument("--batch", type=int, default=1)
    value.add_argument("--chunk", type=int, choices=(15, 30), default=30)
    value.add_argument("--padding", type=float, default=0.0)
    value.add_argument("--interpolate", choices=("nearest", "linear", "ignore"), default="nearest")
    value.add_argument("--ctc-nonblank-only", action="store_true", help="Explicit diagnostic token-transition frame intervals, not acoustic character durations")
    value.add_argument("--ctc-normalize", action="store_true", help="Explicit normalization-only FA probe using the checkpoint's official feature extractor")
    value.add_argument("--ctc-forced-align", action="store_true", help="Experimental standard CTC nonblank token spans from the same emissions; pinned TorchAudio 2.8 CUDA decoder")
    value.add_argument("--cache", default=".local/cache/whisper-runtime")
    value.add_argument("--nltk-data", default=".local/cache/whisper-nltk")
    value.add_argument("--dll-dir", action="append", default=[])
    return value


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args()
    output = Path(args.output).resolve()
    allowed = Path(__file__).resolve().parents[2] / ".local"
    if not output.is_relative_to(allowed):
        print(f"Private experiment output must be inside {allowed}", file=sys.stderr)
        return 2
    if output.exists():
        print(f"Run output already exists; choose a new run identity: {output}", file=sys.stderr)
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = execute(args)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps({"status": "ok", "output": str(output.resolve()), "stages": result["stages"]}))
        return 0
    except Exception as error:
        output.write_text(json.dumps({"status": "failed", "route": args.route,
                                      "error_type": type(error).__name__, "error": str(error)}, indent=2), encoding="utf-8")
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
