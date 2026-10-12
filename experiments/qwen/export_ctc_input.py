"""Export cached Qwen ASR windows to the existing WhisperX CTC contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import wave

from run_qwen import ASR_ID, ASR_REVISION, ASR_SHA256


ASR_CONFIG_SHA256 = "117ac8e63e2af7cae3665e5a632d6eb03f5f384915519ceb6403c15ec6533f63"


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def cuda_evidence(evidence: dict) -> None:
    parameters = evidence.get("parameter_devices", [])
    inputs = evidence.get("input_devices", {})
    output = evidence.get("output_device", "")
    if (not parameters or not inputs or any(not str(x).startswith("cuda:") for x in parameters)
            or any(not str(x).startswith("cuda:") for x in inputs.values())
            or not str(output).startswith("cuda:")):
        raise ValueError("Cached ASR does not have complete CUDA parameter/input/output evidence.")


def export(source_path: Path, audio_path: Path, offset: float) -> dict:
    import numpy as np
    import soundfile as sf

    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("backend") != "official-qwen-native-hf" or source.get("status", "ok") != "ok":
        raise ValueError("A completed native Qwen result is required.")
    identity = source["models"]["asr"]
    recorded = source["checkpoint_file_sha256"]["asr"]
    if (identity["id"] != ASR_ID or identity["revision"] != ASR_REVISION
            or recorded["model.safetensors"] != ASR_SHA256
            or recorded["config.json"] != ASR_CONFIG_SHA256):
        raise ValueError("Cached ASR checkpoint/config identity differs from the frozen Q0 baseline.")
    if not math.isfinite(offset) or abs(source["source_start_seconds"] - offset) > 1e-9:
        raise ValueError("Source media offset differs from cached ASR.")
    if source["config"]["offset"] != source["source_start_seconds"]:
        raise ValueError("Cached ASR config and source offset disagree.")
    file_hash = sha256(audio_path)
    if source["input"]["sha256"] != file_hash:
        raise ValueError("WAV SHA256 differs from cached ASR input.")
    with wave.open(str(audio_path), "rb") as reader:
        if (reader.getnchannels(), reader.getframerate(), reader.getsampwidth()) != (1, 16000, 2):
            raise ValueError("W1 consumer requires mono 16 kHz PCM16 WAV.")
        samples = reader.getnframes()
        pcm16 = reader.readframes(samples)
    if not pcm16:
        raise ValueError("Empty WAV cannot be exported.")
    consumer_float32 = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
    qwen_float32, rate = sf.read(audio_path, dtype="float32", always_2d=True)
    if rate != 16000 or not np.array_equal(consumer_float32, qwen_float32[:, 0]):
        raise ValueError("Consumer PCM16 normalization does not exactly equal Qwen decoded float32 PCM.")
    float_hash = hashlib.sha256(consumer_float32.tobytes()).hexdigest()
    if source["input"]["pcm_sha256"] != float_hash or source["input"]["samples"] != samples:
        raise ValueError("Decoded float32 PCM identity differs from cached Qwen ASR.")
    cuda_evidence(source["environment"]["devices"]["asr"])
    original = []
    cursor = 0
    for index, window in enumerate(source["windows"]):
        if window.get("token_limit_reached") is not False:
            raise ValueError(f"Window {index} reached the generation cap; source is ineligible for engineering comparison.")
        begin, end = window["start_sample"], window["end_sample"]
        if (type(begin) is not int or type(end) is not int or begin != cursor
                or not begin < end <= samples):
            raise ValueError("ASR windows must preserve a continuous non-overlapping partition of the complete input.")
        if abs(window["offset"] - (offset + begin / 16000)) > 1e-9:
            raise ValueError("Window source offset differs from its original sample boundary.")
        window_hash = hashlib.sha256(consumer_float32[begin:end].tobytes()).hexdigest()
        if window_hash != window["pcm_sha256"]:
            raise ValueError("Window PCM hash differs from its recorded ASR input.")
        cuda_evidence(window["asr_input_evidence"])
        original.append({"start": begin / 16000, "end": end / 16000, "text": window["text"]})
        cursor = end
    if cursor != samples or "".join(segment["text"] for segment in original) != source["text"]:
        raise ValueError("Export would omit input samples or alter the full cached ASR text.")
    return {"schema_version": 1, "text": source["text"], "offset_s": offset,
            "source_start_seconds": offset, "duration_seconds": samples / 16000,
            "original_segments": original,
            "input": {"path": str(audio_path.resolve()), "file_sha256": file_hash,
                      "original_qwen_file_sha256": source["input"]["sha256"],
                      "pcm_sha256": hashlib.sha256(pcm16).hexdigest(),
                      "pcm_hash_representation": "serialized signed little-endian PCM16 bytes; W1 consumer contract",
                      "float32_pcm_sha256": float_hash,
                      "float32_hash_representation": "decoded float32 PCM16/32768 bytes; original Q0 contract",
                      "decoded_float32_exactly_equal": True,
                      "sample_rate": 16000, "channels": 1, "samples": samples, "duration_s": samples / 16000},
            "provenance": {"operation": "qwen-asr-to-whisperx-ctc-export-v1",
                           "source_result": str(source_path.resolve()), "source_result_sha256": sha256(source_path),
                           "source_adapter_sha256": source["adapter_sha256"],
                           "exporter_sha256": sha256(Path(__file__)),
                           "checkpoint": identity, "checkpoint_file_sha256": recorded,
                           "asr_config": source["config"], "loaded_generation_config": source["generation_config"],
                           "asr_cuda_evidence": source["environment"]["devices"]["asr"],
                           "window_asr_cuda_evidence": [w["asr_input_evidence"] for w in source["windows"]],
                           "window_pcm_sha256": [w["pcm_sha256"] for w in source["windows"]],
                           "timing_semantics": "Original ASR input-window bounds; not acoustic or forced-alignment timestamps",
                           "reference_text_used": False, "source_fa_times_used": False,
                           "cache_classification": "cached_asr_component_comparison",
                           "new_asr_inference": False, "new_alignment_inference": False},
            "cached_inference": True, "stage_cache": {"asr": "reused", "alignment": "not_yet_executed"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asr-result", required=True, type=Path)
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--offset", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if (output in {args.audio.resolve(), args.asr_result.resolve()}
            or output.drive.lower() == "d:" and "movie" in [p.lower() for p in output.parts]):
        raise ValueError("Output must not overwrite source audio/results or immutable movie assets.")
    if output.exists():
        raise FileExistsError(output)
    result = export(args.asr_result, args.audio, args.offset)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(output), "segments": len(result["original_segments"]),
                      "cache_classification": result["provenance"]["cache_classification"]}))


if __name__ == "__main__":
    main()
