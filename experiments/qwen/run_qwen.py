"""Offline native Transformers Qwen ASR and forced-alignment experiment."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import time
import unicodedata


ASR_ID = "Qwen/Qwen3-ASR-1.7B-hf"
ASR_REVISION = "bcd2b5b7f32b480ab5790554cfa8347f246a14f3"
FA_ID = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
FA_REVISION = "c07281df297b9905d24a508279258cccf987a064"
ASR_SHA256 = "2db53c7d81bd9b8cbc6a074e89be2c968a0d373fb4ee68bb1b1e14f7042dfee1"
FA_SHA256 = "00568245ceca5af1991d28562a75fe1ddc9bfeb041c27fda66947ea05c47fb86"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def checkpoint_identity(path: Path, expected_sha256: str) -> dict:
    weights = path / "model.safetensors"
    actual = digest(weights)
    if actual != expected_sha256:
        raise ValueError(f"Checkpoint weight integrity mismatch: {weights}")
    return {"model.safetensors": actual, **{file.name: digest(file) for file in path.iterdir()
               if file.is_file() and file.suffix in {".json", ".jinja"}}}


def verified_checkpoints(asr_path: Path, aligner_path: Path, asr_only: bool) -> dict:
    if not asr_path.is_dir() or not asr_only and not aligner_path.is_dir():
        raise ValueError("Provision the requested local checkpoint directories before offline inference.")
    identities = {"asr": checkpoint_identity(asr_path, ASR_SHA256)}
    if not asr_only:
        identities["aligner"] = checkpoint_identity(aligner_path, FA_SHA256)
    return identities


def evaluation_schema(text: str, items: list[dict], offset: float, *, time_source: str = "api") -> dict:
    """Map cleaned aligner tokens to original text without inventing timings."""
    kept = [(i, char) for i, char in enumerate(text)
            if char == "'" or unicodedata.category(char)[0] in "LN"]
    clean_text = "".join(char for _, char in kept)
    cursor = 0
    units = []
    diagnostics = []
    covered = set()
    for index, item in enumerate(items):
        token = item["text"]
        position = clean_text.find(token, cursor)
        if position < 0:
            diagnostics.append({"native_index": index, "reason": "token_mapping_failed"})
            continue
        left, right = kept[position][0], kept[position + len(token) - 1][0] + 1
        start, end = item.get("start_time"), item.get("end_time")
        valid = (isinstance(start, (int, float)) and isinstance(end, (int, float))
                 and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end)
        units.append({"char_start": left, "char_end": right,
                      "start": start + offset if valid else None,
                      "end": end + offset if valid else None,
                      "granularity": "word", "time_source": time_source,
                      "status": "ok" if valid else "failed"})
        covered.update(range(left, right))
        cursor = position + len(token)
    for i, _ in kept:
        if i not in covered:
            units.append({"char_start": i, "char_end": i + 1, "start": None, "end": None,
                          "granularity": "character", "time_source": time_source, "status": "text_only"})
    units.sort(key=lambda unit: unit["char_start"])
    return {"schema_version": 1, "text": text, "units": units, "cues": [],
            "mapping_diagnostics": diagnostics}


def check_gpu(model, inputs, torch) -> dict:
    devices = sorted({str(param.device) for param in model.parameters()})
    tensors = {name: str(tensor.device) for name, tensor in inputs.items()
               if isinstance(tensor, torch.Tensor)}
    if not devices or any(not device.startswith("cuda") for device in devices):
        raise RuntimeError(f"Model is not entirely on CUDA: {devices}")
    if any(not device.startswith("cuda") for device in tensors.values()):
        raise RuntimeError(f"Input tensor is not on CUDA: {tensors}")
    return {"parameter_devices": devices, "input_devices": tensors,
            "dtype": str(model.dtype), "input_shapes": {name: list(tensor.shape)
                     for name, tensor in inputs.items() if isinstance(tensor, torch.Tensor)}}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--audio", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--asr-model", type=Path, required=True)
    result.add_argument("--aligner-model", type=Path, required=True)
    result.add_argument("--language", default="ja")
    result.add_argument("--dtype", choices=["bfloat16", "float16"], default="bfloat16")
    result.add_argument("--attention", choices=["sdpa", "eager"], default="sdpa")
    result.add_argument("--max-new-tokens", type=int, default=4096)
    result.add_argument("--offset", type=float, default=0.0)
    result.add_argument("--window-seconds", type=float, default=0.0)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--alignment-only", type=Path,
                      help="Diagnostic UTF-8 text input; not an independent ASR score.")
    mode.add_argument("--asr-only", action="store_true",
                      help="Run fresh ASR only; do not verify, load, or execute the aligner.")
    return result


def run(args: argparse.Namespace) -> dict:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parents[2] / ".local/cache/qwen-hf"))
    import numpy as np
    import soundfile as sf
    import torch
    from transformers import AutoModelForMultimodalLM, AutoModelForTokenClassification, AutoProcessor

    distribution = importlib.metadata.distribution("transformers")
    implementation_files = {name: digest(Path(distribution.locate_file(
        f"transformers/models/qwen3_asr/{name}"))) for name in
        ["processing_qwen3_asr.py", "feature_extraction_qwen3_asr.py", "modeling_qwen3_asr.py"]}

    started = time.perf_counter()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; CPU fallback is prohibited.")
    if not args.audio.is_file() or args.audio.suffix.lower() != ".wav":
        raise ValueError("Provide an existing local WAV file.")
    identity_started = time.perf_counter()
    identities = verified_checkpoints(args.asr_model, args.aligner_model, args.asr_only)
    identity_seconds = time.perf_counter() - identity_started
    pcm, rate = sf.read(args.audio, dtype="float32", always_2d=True)
    if rate != 16000 or pcm.shape[1] != 1:
        raise ValueError("Experiment input must be mono 16 kHz WAV; preprocess explicitly.")
    audio = pcm[:, 0]
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError("Audio must be nonempty and finite.")
    duration = len(audio) / rate
    if args.window_seconds < 0 or not math.isfinite(args.offset) or args.max_new_tokens < 1:
        raise ValueError("Invalid window, offset, or token limit.")
    if not args.window_seconds and duration > 300:
        raise ValueError("FA supports at most 300 s. Specify --window-seconds for long-input diagnostic.")
    if args.window_seconds > 300:
        raise ValueError("Each alignment window must be <= 300 s.")
    if args.alignment_only and args.window_seconds:
        raise ValueError("Alignment-only text must correspond to a single audio window.")
    dtype = getattr(torch, args.dtype)
    torch.cuda.reset_peak_memory_stats()
    windows = []
    size = round(args.window_seconds * rate) if args.window_seconds else len(audio)
    for start_sample in range(0, len(audio), size):
        end_sample = min(start_sample + size, len(audio))
        windows.append({"start_sample": start_sample, "end_sample": end_sample,
                        "offset": args.offset + start_sample / rate,
                        "pcm_sha256": hashlib.sha256(audio[start_sample:end_sample].tobytes()).hexdigest()})
    timings = {}
    devices = {}
    generation_config = None
    t = time.perf_counter()
    processor = AutoProcessor.from_pretrained(args.asr_model, local_files_only=True)
    if args.alignment_only:
        windows[0]["text"] = args.alignment_only.read_text(encoding="utf-8")
        windows[0]["asr_skipped"] = True
    else:
        model = AutoModelForMultimodalLM.from_pretrained(
            args.asr_model, dtype=dtype, attn_implementation=args.attention,
            device_map={"": "cuda:0"}, local_files_only=True).eval()
        torch.cuda.synchronize()
        timings["asr_load_seconds"] = time.perf_counter() - t
        generation_config = model.generation_config.to_dict()
        for window in windows:
            t = time.perf_counter()
            data = audio[window["start_sample"]:window["end_sample"]]
            inputs = processor.apply_transcription_request(audio=data, language=args.language,
                processor_kwargs={"audio_kwargs": {"sampling_rate": rate}}).to("cuda:0", dtype)
            devices["asr"] = check_gpu(model, inputs, torch)
            window["asr_input_evidence"] = devices["asr"]
            torch.cuda.synchronize()
            window["asr_preprocess_seconds"] = time.perf_counter() - t
            t = time.perf_counter()
            with torch.inference_mode():
                output = model.generate(**inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
            torch.cuda.synchronize()
            if output.device.type != "cuda":
                raise RuntimeError("ASR token IDs were not produced on CUDA.")
            devices["asr"]["output_device"] = str(output.device)
            window["asr_inference_seconds"] = time.perf_counter() - t
            generated = output[:, inputs["input_ids"].shape[1]:]
            window["generated_tokens"] = generated.shape[1]
            window["token_limit_reached"] = generated.shape[1] >= args.max_new_tokens
            window["raw_asr"] = processor.decode(generated)[0]
            parsed = processor.decode(generated, return_format="parsed")[0]
            window["text"] = parsed["transcription"]
            window["detected_language"] = parsed["language"]
            del inputs, output, generated
        timings["asr_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
        timings["asr_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
        del model
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    del processor
    partial_text = "".join(window["text"] for window in windows)
    partial = evaluation_schema(partial_text, [], args.offset)
    partial.update({"status": "asr_complete_alignment_not_requested" if args.asr_only else "asr_complete_alignment_pending", "windows": windows,
                    "generation_config": generation_config, "input_sha256": digest(args.audio),
                    "source_start_seconds": args.offset, "duration_seconds": duration})
    args.output.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.asr_only:
        t = time.perf_counter()
        processor = AutoProcessor.from_pretrained(args.aligner_model, local_files_only=True)
        model = AutoModelForTokenClassification.from_pretrained(
            args.aligner_model, dtype=dtype, attn_implementation=args.attention,
            device_map={"": "cuda:0"}, local_files_only=True).eval()
        torch.cuda.synchronize()
        timings["fa_load_seconds"] = time.perf_counter() - t
        for window in windows:
            window["native_alignment"] = []
            if not window["text"].strip():
                window["alignment_status"] = "empty_transcript"
                continue
            t = time.perf_counter()
            data = audio[window["start_sample"]:window["end_sample"]]
            inputs, word_lists = processor.prepare_forced_aligner_inputs(
                audio=data, transcript=window["text"], language=args.language,
                processor_kwargs={"audio_kwargs": {"sampling_rate": rate}})
            if not word_lists[0]:
                window["alignment_status"] = "no_alignable_tokens"
                del inputs
                continue
            inputs = inputs.to("cuda:0", dtype)
            devices["aligner"] = check_gpu(model, inputs, torch)
            window["fa_input_evidence"] = devices["aligner"]
            torch.cuda.synchronize()
            window["fa_preprocess_seconds"] = time.perf_counter() - t
            t = time.perf_counter()
            with torch.inference_mode():
                output = model(**inputs)
            torch.cuda.synchronize()
            if output.logits.device.type != "cuda":
                raise RuntimeError("Aligner logits were not produced on CUDA.")
            devices["aligner"]["output_device"] = str(output.logits.device)
            window["fa_inference_seconds"] = time.perf_counter() - t
            mask = inputs["input_ids"][0] == model.config.timestamp_token_id
            raw = output.logits.argmax(dim=-1)[0][mask]
            window["raw_timestamp_class_ids"] = raw.cpu().tolist()
            window["timestamp_class_ms"] = processor.timestamp_segment_time
            window["alignment_words"] = word_lists[0]
            window["native_alignment"] = processor.decode_forced_alignment(
                logits=output.logits, input_ids=inputs["input_ids"], word_lists=word_lists,
                timestamp_token_id=model.config.timestamp_token_id)[0]
            corrected = [round(item[boundary] * 1000) for item in window["native_alignment"]
                         for boundary in ("start_time", "end_time")]
            window["corrected_timestamp_count"] = sum(
                before * processor.timestamp_segment_time != after
                for before, after in zip(window["raw_timestamp_class_ids"], corrected))
            window["alignment_status"] = "ok"
            del inputs, output, raw
        torch.cuda.synchronize()
    else:
        for window in windows:
            window["native_alignment"] = []
            window["alignment_status"] = "not_requested_asr_only"
    text = "".join(window["text"] for window in windows)
    evaluation = {"schema_version": 1, "text": text, "units": [], "cues": [], "mapping_diagnostics": []}
    cursor = 0
    for window in windows:
        mapped = evaluation_schema(window["text"], window["native_alignment"], window["offset"],
                                   time_source="native" if args.asr_only else "api")
        for unit in mapped["units"]:
            unit["char_start"] += cursor
            unit["char_end"] += cursor
        evaluation["units"].extend(mapped["units"])
        evaluation["mapping_diagnostics"].extend(mapped["mapping_diagnostics"])
        cursor += len(window["text"])
    return {**evaluation, "backend": "official-qwen-native-hf", "windows": windows,
            **({"alignment_status": "not_requested_asr_only"} if args.asr_only else {}),
            "adapter_sha256": digest(Path(__file__)),
            "upstream_implementation": {"transformers_tag": "v5.18.0",
                "commit": "a906d3c4b65095f2308b6a6a193e934d03b8eb5d",
                "processing_source_sha256": "5ff7ace057ae959fb0cd551775cbbfdad8c003eb731bf0f1f39bfc6452ce86fa",
                "feature_source_sha256": "95d23cca9645546b9f6a97885eace5c02a95f5048bf3616e03f00041fd993a74",
                "installed_file_sha256": implementation_files},
            "source_start_seconds": args.offset, "duration_seconds": duration,
            "input": {"path": str(args.audio.resolve()), "sha256": digest(args.audio),
                      "pcm_sha256": hashlib.sha256(audio.tobytes()).hexdigest(),
                      "sample_rate": rate, "channels": 1, "samples": len(audio), "duration": duration},
            "models": {"asr": {"id": ASR_ID, "revision": ASR_REVISION, "path": str(args.asr_model.resolve())},
                       **({"aligner": {"id": FA_ID, "revision": FA_REVISION, "path": str(args.aligner_model.resolve())}} if not args.asr_only else {})},
            "checkpoint_file_sha256": identities,
            "config": {"language": args.language, "dtype": args.dtype, "attention": args.attention,
                       "max_new_tokens": args.max_new_tokens, "do_sample": False, "batch_size": 1,
                       "window_seconds": args.window_seconds, "offset": args.offset,
                       "sequential_residency": True, "offline": True,
                       "asr_only": args.asr_only,
                       "alignment_only": str(args.alignment_only) if args.alignment_only else None,
                       "vad": "none in documented native HF helper", "prompt": None},
            "generation_config": generation_config,
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "packages": {name: importlib.metadata.version(name) for name in
                                         ["torch", "transformers", "accelerate", "nagisa", "soundfile", "librosa"]},
                            "torch_cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
                            "devices": devices},
            "timings": {**timings, "identity_verification_seconds": identity_seconds,
                        "total_seconds": time.perf_counter() - started,
                        **({"fa_peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                            "fa_peak_reserved_bytes": torch.cuda.max_memory_reserved()} if not args.asr_only else {}),
                        "peak_allocated_bytes": max(timings.get("asr_peak_allocated_bytes", 0), torch.cuda.max_memory_allocated()),
                        "peak_reserved_bytes": max(timings.get("asr_peak_reserved_bytes", 0), torch.cuda.max_memory_reserved())},
            "stage_execution": {"asr": "skipped_alignment_only" if args.alignment_only else "executed",
                                "aligner": "not_requested_asr_only" if args.asr_only else "executed"},
            "cache_reused": False}


def main() -> None:
    args = parser().parse_args()
    output = args.output.resolve()
    if output == args.audio.resolve() or output.drive.lower() == "d:" and "movie" in [p.lower() for p in output.parts]:
        raise ValueError("Output must be outside immutable source media directories.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "status": "starting"}, handle)
    try:
        result = run(args)
    except Exception as exc:
        partial = json.loads(output.read_text(encoding="utf-8"))
        partial.update({"status": "failed", "failure_type": type(exc).__name__, "error": str(exc)})
        output.write_text(json.dumps(partial, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "status": "ok", "duration": result["input"]["duration"]}))


if __name__ == "__main__":
    main()
