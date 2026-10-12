"""Fresh frozen Qwen ASR on CUDA VAD intervals, with an original-audio CTC bridge."""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Callable

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.components.separate import read_pcm, sha256, source_origin_sample
from experiments.qwen.run_qwen import (
    ASR_ID, ASR_REVISION, ASR_SHA256, checkpoint_identity, check_gpu, evaluation_schema,
)

RATE = 16000
ASR_CONFIG_SHA256 = "117ac8e63e2af7cae3665e5a632d6eb03f5f384915519ceb6403c15ec6533f63"
MAX_NEW_TOKENS = 4096
LOCAL = Path(__file__).resolve().parents[2] / ".local"


def validate_vad(manifest: dict[str, Any], identity: dict[str, Any], pcm: bytes,
                 offset: float) -> list[dict[str, Any]]:
    """Bind original PCM and exact sample intervals; this ASR has no frame rounding."""
    origin = source_origin_sample(offset)
    if (manifest.get("schema_version") != 1 or manifest.get("status") != "ok"
            or manifest.get("component") != "pyannote-vad-speech-crops"):
        raise ValueError("A successful standalone Pyannote VAD manifest is required")
    for key in ("file_sha256", "pcm_sha256", "samples", "sample_rate", "channels"):
        if manifest.get("input", {}).get(key) != identity.get(key):
            raise ValueError(f"VAD input identity differs from original ASR input: {key}")
    if (identity.get("sample_rate") != RATE or identity.get("channels") != 1
            or identity.get("samples") != len(pcm) // 2 or len(pcm) % 2
            or hashlib.sha256(pcm).hexdigest() != identity.get("pcm_sha256")):
        raise ValueError("Original PCM16 identity is inconsistent")
    if manifest.get("source_origin_s") != offset or manifest.get("source_origin_sample") != origin:
        raise ValueError("VAD source origin differs from ASR source origin")
    device = manifest.get("device", {})
    actual = str(device.get("actual", ""))
    evidence = device.get("forward_evidence", {})
    if (not actual.startswith("cuda:") or type(evidence.get("count")) is not int
            or evidence["count"] < 1 or evidence.get("input_devices") != [actual]
            or evidence.get("output_devices") != [actual]):
        raise ValueError("VAD manifest lacks actual CUDA input/output forward evidence")
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or manifest.get("empty_speech") is not (not chunks):
        raise ValueError("VAD empty-speech status and chunk list are inconsistent")
    result = []
    previous_end = 0
    for index, chunk in enumerate(chunks):
        begin, end = chunk.get("start_sample"), chunk.get("end_sample_exclusive")
        if (type(begin) is not int or type(end) is not int
                or not 0 <= previous_end <= begin < end <= identity["samples"]
                or end - begin > 30 * RATE):
            raise ValueError("VAD chunks must be ordered nonoverlapping sample intervals of at most 30 seconds")
        if (chunk.get("source_start_sample") != origin + begin
                or chunk.get("source_end_sample_exclusive") != origin + end
                or chunk.get("source_offset_s") != (origin + begin) / RATE):
            raise ValueError("VAD chunk source sample mapping is inconsistent")
        crop = chunk.get("audio", {})
        if (crop.get("pcm_sha256") != hashlib.sha256(pcm[2 * begin:2 * end]).hexdigest()
                or crop.get("samples") != end - begin or crop.get("sample_rate") != RATE
                or crop.get("channels") != 1 or crop.get("representation") != "PCM16"):
            raise ValueError("VAD crop PCM identity differs from the original sample slice")
        result.append({"vad_chunk_index": index, "start_sample": begin, "end_sample": end,
                       "source_start_sample": origin + begin, "source_end_sample_exclusive": origin + end,
                       "offset": (origin + begin) / RATE, "crop_pcm16_sha256": crop["pcm_sha256"]})
        previous_end = end
    return result


def transcribe_windows(audio: Any, intervals: list[dict[str, Any]],
                       infer: Callable[[Any], dict[str, Any]],
                       completed: Callable[[list[dict[str, Any]]], None] | None = None
                       ) -> list[dict[str, Any]]:
    """Reuse the supplied inference boundary and slice the original waveform exactly once."""
    windows = []
    for interval in intervals:
        data = audio[interval["start_sample"]:interval["end_sample"]]
        outcome = infer(data)
        if not isinstance(outcome.get("text"), str):
            raise ValueError("ASR must return a complete transcription string")
        windows.append({**interval, **outcome,
                        "pcm_sha256": hashlib.sha256(data.tobytes()).hexdigest()})
        if completed is not None:
            completed(windows)
    return windows


def cuda_evidence(evidence: dict[str, Any]) -> None:
    parameters, inputs = evidence.get("parameter_devices", []), evidence.get("input_devices", {})
    if (not parameters or not inputs or any(not str(d).startswith("cuda:") for d in parameters)
            or any(not str(d).startswith("cuda:") for d in inputs.values())
            or not str(evidence.get("output_device", "")).startswith("cuda:")):
        raise ValueError("ASR lacks complete CUDA parameter/input/output evidence")


def ctc_bridge(source: dict[str, Any], source_path: Path, audio_path: Path,
               pcm: bytes, identity: dict[str, Any], vad: dict[str, Any], offset: float) -> dict[str, Any]:
    """Explicit noncontiguous bridge; the old continuous-window exporter stays unchanged."""
    import numpy as np
    intervals = validate_vad(vad, identity, pcm, offset)
    if source.get("backend") != "official-qwen-native-hf-vad" or source.get("status") != "ok":
        raise ValueError("A completed fresh VAD Qwen ASR result is required")
    model = source.get("models", {}).get("asr", {})
    hashes = source.get("checkpoint_file_sha256", {}).get("asr", {})
    if (model.get("id") != ASR_ID or model.get("revision") != ASR_REVISION
            or hashes.get("model.safetensors") != ASR_SHA256 or hashes.get("config.json") != ASR_CONFIG_SHA256):
        raise ValueError("ASR checkpoint differs from the frozen X0 identity")
    expected = {"language": "ja", "dtype": "bfloat16", "attention": "sdpa",
                "max_new_tokens": MAX_NEW_TOKENS, "do_sample": False, "batch_size": 1,
                "offset": offset, "asr_only": True, "offline": True, "alignment_only": None}
    if (any(source.get("config", {}).get(key) != value for key, value in expected.items())
            or source.get("cache_reused") is not False or source.get("source_start_seconds") != offset):
        raise ValueError("ASR settings or source origin differ from this frozen ablation")
    if source.get("input", {}).get("sha256") != sha256(audio_path) or identity["file_sha256"] != sha256(audio_path):
        raise ValueError("Original audio file identity changed")
    waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    float_hash = hashlib.sha256(waveform.tobytes()).hexdigest()
    if (source["input"].get("pcm_sha256") != float_hash
            or source["input"].get("samples") != identity["samples"]):
        raise ValueError("Qwen full-input decoded float32 identity differs")
    windows = source.get("windows", [])
    if len(windows) != len(intervals):
        raise ValueError("ASR window count differs from the complete VAD interval list")
    segments = []
    for window, interval in zip(windows, intervals):
        for key in ("start_sample", "end_sample", "offset", "source_start_sample", "source_end_sample_exclusive"):
            if window.get(key) != interval[key]:
                raise ValueError(f"ASR window differs from exact VAD coordinates: {key}")
        if window.get("token_limit_reached") is not False:
            raise ValueError("Generation cap reached; preserve raw text but do not promote or align this run")
        begin, end = interval["start_sample"], interval["end_sample"]
        if window.get("pcm_sha256") != hashlib.sha256(waveform[begin:end].tobytes()).hexdigest():
            raise ValueError("Window float32 input hash differs from original audio")
        cuda_evidence(window.get("asr_input_evidence", {}))
        segments.append({"start": begin / RATE, "end": end / RATE, "text": window["text"]})
    if "".join(segment["text"] for segment in segments) != source.get("text"):
        raise ValueError("Bridge would change or omit full ASR text")
    return {"schema_version": 1, "status": "ok", "text": source["text"], "offset_s": offset,
            "source_start_seconds": offset, "duration_seconds": identity["duration_s"],
            "original_segments": segments,
            "input": {**identity, "representation": "PCM16", "float32_pcm_sha256": float_hash,
                      "pcm_hash_representation": "serialized signed little-endian PCM16 bytes; W1 consumer contract",
                      "decoded_float32_exactly_equal": True},
            "provenance": {"operation": "fresh-qwen-vad-to-whisperx-ctc-bridge-v1",
                           "source_result": str(source_path.resolve()), "source_result_sha256": sha256(source_path),
                           "source_adapter_sha256": source["adapter_sha256"], "exporter_sha256": sha256(Path(__file__)),
                           "checkpoint": model, "checkpoint_file_sha256": hashes,
                           "asr_config": source["config"], "loaded_generation_config": source["generation_config"],
                           "window_asr_cuda_evidence": [w["asr_input_evidence"] for w in windows],
                           "window_pcm_sha256": [w["pcm_sha256"] for w in windows],
                           "vad": source["experimental_vad"],
                           "timing_semantics": "Noncontiguous original input sample-window bounds; not acoustic alignments",
                           "reference_text_used": False, "source_fa_times_used": False,
                           "cache_classification": "fresh_asr_from_external_vad",
                           "new_asr_inference": bool(windows), "new_alignment_inference": False},
            "cached_inference": False, "stage_cache": {"asr": "fresh_previous_stage", "alignment": "not_yet_executed"}}


def write_json(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def execute(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    pcm, identity = read_pcm(args.audio)
    vad_hash = sha256(args.vad_manifest)
    vad = json.loads(args.vad_manifest.read_text(encoding="utf-8"))
    intervals = validate_vad(vad, identity, pcm, args.offset)
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[name] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.setdefault("HF_HOME", str(LOCAL / "cache/qwen-hf"))
    import numpy as np
    import torch
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    if importlib.metadata.version("transformers") != "5.18.0":
        raise RuntimeError("Use the frozen Qwen Transformers 5.18.0 environment")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; CPU ASR fallback is prohibited")
    torch.cuda.set_device(0)
    torch.cuda.reset_peak_memory_stats()
    mark = time.perf_counter()
    checkpoint = checkpoint_identity(args.asr_model, ASR_SHA256)
    if checkpoint.get("config.json") != ASR_CONFIG_SHA256:
        raise ValueError("ASR config differs from the frozen X0 checkpoint")
    identity_s = time.perf_counter() - mark
    distribution = importlib.metadata.distribution("transformers")
    implementations = {name: sha256(Path(distribution.locate_file(f"transformers/models/qwen3_asr/{name}")))
                       for name in ("processing_qwen3_asr.py", "feature_extraction_qwen3_asr.py", "modeling_qwen3_asr.py")}
    waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
    raw: dict[str, Any] = {**evaluation_schema("", [], args.offset), "status": "running",
        "backend": "official-qwen-native-hf-vad", "adapter_sha256": sha256(Path(__file__)),
        "base_adapter_sha256": sha256(Path(__file__).parents[1] / "qwen/run_qwen.py"),
        "input": {"path": str(args.audio.resolve()), "sha256": identity["file_sha256"],
                  "pcm_sha256": hashlib.sha256(waveform.tobytes()).hexdigest(),
                  "sample_rate": RATE, "channels": 1, "samples": identity["samples"], "duration": identity["duration_s"]},
        "source_start_seconds": args.offset, "duration_seconds": identity["duration_s"],
        "models": {"asr": {"id": ASR_ID, "revision": ASR_REVISION, "path": str(args.asr_model.resolve())}},
        "checkpoint_file_sha256": {"asr": checkpoint},
        "config": {"language": "ja", "dtype": "bfloat16", "attention": "sdpa", "max_new_tokens": MAX_NEW_TOKENS,
                   "do_sample": False, "batch_size": 1, "offset": args.offset, "asr_only": True,
                   "alignment_only": None, "offline": True, "sequential_residency": True,
                   "vad": "external CUDA Pyannote sample intervals", "window_seconds": None, "prompt": None},
        "windows": [], "generation_config": None, "cache_reused": False,
        "experimental_vad": {"manifest": str(args.vad_manifest.resolve()), "file_sha256": vad_hash,
                             "config": vad["config"], "device": vad["device"], "model": vad["model"],
                             "empty_speech": not bool(intervals), "sample_mapping_exact": True,
                             "original_audio_samples": identity["samples"],
                             "asr_audio_samples": sum(w["end_sample"] - w["start_sample"] for w in intervals),
                             "concatenated_audio": False, "reference_text_used": False},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "torch_cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
                        "packages": {name: importlib.metadata.version(name) for name in
                                     ("torch", "transformers", "accelerate", "numpy")}, "devices": {"vad": vad["device"]}},
        "upstream_implementation": {"transformers_tag": "v5.18.0", "commit": "a906d3c4b65095f2308b6a6a193e934d03b8eb5d",
                                    "installed_file_sha256": implementations},
        "phase_costs": {"external_vad_timing": vad["timing"], "vad_not_included_in_asr_process_total": True},
        "timings": {"identity_verification_seconds": identity_s},
        "stage_execution": {"asr": "not_executed_empty_vad", "aligner": "not_requested_asr_only"}}

    def preserve(windows: list[dict[str, Any]]) -> None:
        text = "".join(w["text"] for w in windows)
        raw.update(evaluation_schema(text, [], args.offset))
        raw["windows"] = windows
        write_json(args.output, raw)

    preserve([])
    if intervals:
        mark = time.perf_counter()
        processor = AutoProcessor.from_pretrained(args.asr_model, local_files_only=True)
        model = AutoModelForMultimodalLM.from_pretrained(args.asr_model, dtype=torch.bfloat16,
            attn_implementation="sdpa", device_map={"": "cuda:0"}, local_files_only=True).eval()
        torch.cuda.synchronize()
        raw["timings"]["asr_load_seconds"] = time.perf_counter() - mark
        raw["generation_config"] = model.generation_config.to_dict()

        def infer(data: Any) -> dict[str, Any]:
            mark = time.perf_counter()
            inputs = processor.apply_transcription_request(audio=data, language="ja",
                processor_kwargs={"audio_kwargs": {"sampling_rate": RATE}}).to("cuda:0", torch.bfloat16)
            evidence = check_gpu(model, inputs, torch)
            torch.cuda.synchronize()
            preprocess_s = time.perf_counter() - mark
            mark = time.perf_counter()
            with torch.inference_mode():
                output = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False)
            torch.cuda.synchronize()
            inference_s = time.perf_counter() - mark
            if output.device.type != "cuda":
                raise RuntimeError("ASR output token IDs were not produced on CUDA")
            evidence["output_device"] = str(output.device)
            generated = output[:, inputs["input_ids"].shape[1]:]
            parsed = processor.decode(generated, return_format="parsed")[0]
            result = {"asr_input_evidence": evidence, "asr_preprocess_seconds": preprocess_s,
                      "asr_inference_seconds": inference_s,
                      "generated_tokens": generated.shape[1], "token_limit_reached": generated.shape[1] >= MAX_NEW_TOKENS,
                      "raw_asr": processor.decode(generated)[0], "text": parsed["transcription"],
                      "detected_language": parsed["language"], "alignment_status": "not_requested_asr_only"}
            raw["environment"]["devices"]["asr"] = evidence
            return result

        try:
            transcribe_windows(waveform, intervals, infer, preserve)
        finally:
            raw["timings"]["asr_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            raw["timings"]["asr_peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
            del model, processor
            gc.collect()
            torch.cuda.empty_cache()
        raw["stage_execution"]["asr"] = "executed"
    if sha256(args.audio) != identity["file_sha256"] or sha256(args.vad_manifest) != vad_hash:
        raise RuntimeError("Original audio or VAD manifest changed during ASR")
    if checkpoint_identity(args.asr_model, ASR_SHA256) != checkpoint:
        raise RuntimeError("ASR checkpoint identity changed during ASR")
    raw["timings"]["total_seconds"] = time.perf_counter() - started
    raw["status"] = "ok"
    raw["engineering_comparison_eligible"] = bool(intervals) and not any(w["token_limit_reached"] for w in raw["windows"])
    write_json(args.output, raw)
    bridge = ctc_bridge(raw, args.output, args.audio, pcm, identity, vad, args.offset)
    with args.bridge_output.open("x", encoding="utf-8") as stream:
        json.dump(bridge, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return raw


def output_paths(raw: Path, bridge: Path, audio: Path, manifest: Path) -> tuple[Path, Path]:
    raw, bridge = raw.resolve(), bridge.resolve()
    if raw == bridge or raw in {audio.resolve(), manifest.resolve()} or bridge in {audio.resolve(), manifest.resolve()}:
        raise ValueError("Raw and bridge outputs must be distinct from each other and source assets")
    for path in (raw, bridge):
        if not path.is_relative_to(LOCAL.resolve()) or path == LOCAL.resolve() or path.suffix.lower() != ".json":
            raise ValueError("Outputs must be new JSON files under workspace .local")
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    return raw, bridge


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--vad-manifest", type=Path, required=True)
    parser.add_argument("--asr-model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bridge-output", type=Path, required=True)
    parser.add_argument("--offset", type=float, default=0)
    args = parser.parse_args()
    args.output, args.bridge_output = output_paths(args.output, args.bridge_output, args.audio, args.vad_manifest)
    for path in (args.output, args.bridge_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"schema_version": 1, "status": "starting"}, stream)
    try:
        result = execute(args)
    except Exception as error:
        partial = json.loads(args.output.read_text(encoding="utf-8"))
        partial.update({"status": "failed", "failure_type": type(error).__name__, "error": str(error),
                        "engineering_comparison_eligible": False})
        write_json(args.output, partial)
        raise
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "bridge": str(args.bridge_output), "windows": len(result["windows"])}))


if __name__ == "__main__":
    main()
