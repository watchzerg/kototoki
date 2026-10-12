"""Freeze and run unchanged CTC on complete cached raw-audio W0 transcription."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.components.run import digest, read, write_new
from experiments.components.run_vad import (
    validate_name, verify_clip, verify_harness, verify_progress, verify_sources,
)
from experiments.qwen.run_cross import validate_ctc_evidence

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local/components"
SOURCE_NAME = "comp-vad-dev-v1"


def validate_cached_asr(result: dict[str, Any], clip: dict[str, Any]) -> None:
    """Require a complete original transcript and the exact frozen W0 configuration."""
    if (result.get("status", "ok") != "ok" or result.get("route") != "W0"
            or result.get("cached_inference") is not False or result.get("offset_s") != clip["offset"]
            or result.get("input", {}).get("file_sha256") != clip["audio_sha256"]
            or result.get("input", {}).get("pcm_sha256") != clip["pcm_sha256"]):
        raise ValueError("Cached W0 ASR status, route, input or source origin is invalid")
    expected = {"language": "ja", "task": "transcribe", "beam_size": 5, "word_timestamps": True,
                "vad_filter": False, "chunk_length": 30, "condition_on_previous_text": False}
    effective = result.get("effective_parameters", {})
    transcribe = effective.get("transcribe", {})
    if (any(transcribe.get(key) != value for key, value in expected.items())
            or "temperature" in transcribe or "clip_timestamps" in transcribe
            or "experimental_vad" in result):
        raise ValueError("Cached ASR does not retain the unchanged raw W0 configuration")
    asr = result.get("devices", {}).get("asr", {})
    if (asr.get("device") != "cuda" or asr.get("compute_type") != "float16"
            or asr.get("device_index") not in (0, [0])):
        raise ValueError("Cached W0 CUDA configuration/execution evidence is absent")
    options = effective.get("info", {}).get("transcription_options", {})
    if options.get("temperatures") != [0, 0.2, 0.4, 0.6, 0.8, 1]:
        raise ValueError("Cached W0 changed the native temperature fallback schedule")
    segments = result.get("original_segments")
    if (not isinstance(segments, list) or not isinstance(result.get("text"), str)
            or any(not isinstance(segment.get("text"), str) for segment in segments)
            or "".join(segment["text"] for segment in segments) != result["text"]
            or result.get("native", {}).get("segments") != segments):
        raise ValueError("Cached result does not preserve its entire original ASR text")
    for segment in segments:
        start, end = segment.get("start"), segment.get("end")
        if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end):
            raise ValueError("Cached ASR lacks valid native local segment bounds")


def source_asr(task: dict[str, Any], clip: dict[str, Any], progress_path: Path,
               model_hashes: dict[str, str]) -> dict[str, Any]:
    """Audit the historical command and immutable executed source snapshots independently."""
    if (task.get("status") != "completed" or task.get("configuration") != "W0-no-context"
            or task.get("returncode") != 0 or digest(task["output"]) != task.get("output_sha256")):
        raise ValueError("Original round-two W0 slot is not independently complete")
    harness_path = Path(task["harness_manifest"])
    if digest(harness_path) != task.get("harness_manifest_sha256"):
        raise ValueError("Historical ASR harness changed")
    harness = read(harness_path)
    if (harness.get("id") != task["id"] or harness.get("status") != "completed"
            or harness.get("returncode") != 0 or harness.get("command") != task["command"]
            or harness.get("audio_sha256") != clip["audio_sha256"]
            or harness.get("reference_unchanged") is not True
            or harness.get("reference_sha256_before") != clip["source_srt_sha256"]
            or harness.get("reference_sha256_after") != clip["source_srt_sha256"]):
        raise ValueError("Historical ASR harness lacks matching input/command/reference evidence")
    source_hashes = harness.get("source_sha256", {})
    snapshot_hashes = {}
    run_source = str(Path("experiments/whisper/run.py"))
    if run_source not in source_hashes:
        raise ValueError("Historical W0 executed adapter source is missing")
    for relative, expected in source_hashes.items():
        snapshot = (harness_path.parent / "source" / relative).resolve()
        if not snapshot.is_relative_to(harness_path.parent.resolve() / "source") or digest(snapshot) != expected:
            raise ValueError("Historical ASR source snapshot changed")
        snapshot_hashes[str(snapshot)] = expected
    result = read(task["output"])
    if result.get("implementation", {}).get("sha256") != source_hashes[run_source]:
        raise ValueError("Historical ASR result differs from the executed frozen adapter")
    validate_cached_asr(result, clip)
    model = result.get("model_identity", {}).get("asr", {})
    acquisition = model.get("acquisition", {})
    if (Path(model.get("path", "")).resolve() != ROOT / ".local/models/faster-whisper-large-v3"
            or acquisition.get("complete") is not True):
        raise ValueError("Historical raw W0 checkpoint acquisition evidence is absent")
    declared = {}
    for asset in acquisition.get("files", []):
        path = (ROOT / asset["path"]).resolve()
        if model_hashes.get(str(path)) != asset.get("sha256"):
            raise ValueError("Historical W0 model differs from current frozen model asset identity")
        declared[path.name] = asset["sha256"]
    if not {"model.bin", "config.json", "tokenizer.json", "vocabulary.json"}.issubset(declared):
        raise ValueError("Historical W0 lacks complete checkpoint/tokenizer identities")
    return {"path": task["output"], "sha256": digest(task["output"]),
            "progress_path": str(progress_path), "progress_sha256": digest(progress_path),
            "harness_path": str(harness_path), "harness_sha256": digest(harness_path),
            "historical_executed_source_sha256": source_hashes,
            "historical_source_files": snapshot_hashes,
            "cached_asr_complete": True, "cached_asr_text_sha256": hashlib.sha256(result["text"].encode()).hexdigest(),
            "costs": {"cached_asr_harness_wall_s": read(harness_path)["wall_seconds"],
                      "new_asr_inference": False, "new_ctc_inference": True}}


def prepare(name: str) -> dict[str, Any]:
    validate_name(name)
    if (LOCAL / name).exists():
        raise FileExistsError("Choose a new CTC experiment identity")
    registry_path = LOCAL / SOURCE_NAME / "plan.json"
    identity_registry = read(registry_path)
    verify_sources(identity_registry, models=True)
    if len(identity_registry["clips"]) != 12:
        raise ValueError("This CTC step uses exactly the twelve original two-film development clips")
    source_path = ROOT / ".local/round2/progress.json"
    source_registry = read(source_path)["tasks"]
    sources = dict(identity_registry["source_sha256"])
    sources[str(Path(__file__).resolve())] = digest(Path(__file__))
    tasks = []
    for clip in identity_registry["clips"]:
        verify_clip(clip)
        original = source_registry[f"{clip['id']}-w0"]
        upstream = source_asr(original, clip, source_path, identity_registry["model_sha256"])
        task_id = f"{name}-{clip['id']}-ctc"
        output = ROOT / ".local/results" / task_id / "result.json"
        if output.parent.exists():
            raise FileExistsError("Preexisting CTC attempts cannot be reused")
        command = [str(ROOT / ".local/envs/whisper-latest/Scripts/python.exe"),
                   str(ROOT / "experiments/whisper/run.py"), "--route", "W1", "--audio", clip["audio"],
                   "--asr-result", upstream["path"], "--offset", str(clip["offset"]),
                   "--align-model", str(ROOT / ".local/models/wav2vec2-large-xlsr-53-japanese"),
                   "--ctc-normalize", "--ctc-forced-align", "--dll-dir",
                   str(ROOT / ".local/tools/whisper-runtime-provisional"), "--output", str(output)]
        tasks.append({"id": task_id, "clip": clip["id"], "stage": "ctc", "audio": clip["audio"],
                      "input_sha256": clip["audio_sha256"], "input_pcm_sha256": clip["pcm_sha256"],
                      "command": command, "output": str(output), "additional_outputs": [],
                      "source_asr": upstream})
    models = {path: digest(path) for path in identity_registry["model_sha256"]}
    plan = {"schema_version": 1, "id": name, "frozen": True, "clips": identity_registry["clips"], "tasks": tasks,
            "source_plan": {"path": str(source_path), "sha256": digest(source_path)},
            "source_sha256": sources, "model_sha256": models,
            "identity_registry": {"path": str(registry_path), "sha256": digest(registry_path), "use": "clips/models/current executable identities only; VAD results are not ASR sources"},
            "input_registry": identity_registry["input_registry"], "baseline_model_registry": identity_registry["baseline_model_registry"],
            "component": "unchanged normalized standard CUDA Japanese CTC on cached complete raw W0 text",
            "scope": "independent twelve-window two-film raw W0 CTC-only ablation; no VAD/denoising/ASR rerun/parameter sweep",
            "cost_policy": "new CTC harness wall only; end-to-end cost is cached raw W0 + new CTC; cached stages are not new GPU qualification",
            "failure_policy": "retain complete cached ASR pointer for alignment_failed accounting; all twelve slots remain in denominator"}
    write_new(LOCAL / name / "plan.json", plan)
    return plan


def verify_upstream(task: dict[str, Any], clip: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    parent = plan["source_plan"]
    if digest(parent["path"]) != parent["sha256"]:
        raise ValueError("Source raw W0 registry changed")
    identity_registry = plan.get("identity_registry")
    if identity_registry and digest(identity_registry["path"]) != identity_registry["sha256"]:
        raise ValueError("Frozen clip/model/current-source registry changed")
    for path_key, hash_key in (("path", "sha256"), ("progress_path", "progress_sha256"),
                              ("harness_path", "harness_sha256")):
        if digest(task["source_asr"][path_key]) != task["source_asr"][hash_key]:
            raise ValueError("Frozen complete ASR or its execution evidence changed")
    for path, expected in task["source_asr"].get("historical_source_files", {}).items():
        if digest(path) != expected:
            raise ValueError("Historical W0 executed source snapshot changed")
    result = read(task["source_asr"]["path"])
    validate_cached_asr(result, clip)
    return result


def verify_ctc(task: dict[str, Any], clip: dict[str, Any], saved: dict[str, Any]) -> None:
    result = read(task["output"])
    if (result.get("status", "ok") != "ok" or result.get("route") != "W1"
            or result.get("input", {}).get("file_sha256") != clip["audio_sha256"]
            or result.get("input", {}).get("pcm_sha256") != clip["pcm_sha256"]
            or result.get("offset_s") != clip["offset"] or result.get("text") != saved["text"]
            or result.get("original_segments") != saved["original_segments"]
            or result.get("native", {}).get("reused_asr_file") != task["source_asr"]["path"]
            or result.get("effective_parameters", {}).get("asr_reused") is not True):
        raise ValueError("CTC changed the cached complete ASR text, origin or input identity")
    validate_ctc_evidence(result)


def run(name: str) -> None:
    validate_name(name)
    plan_path = LOCAL / name / "plan.json"
    plan, plan_hash = read(plan_path), digest(plan_path)
    if plan.get("id") != name or plan.get("frozen") is not True or len(plan["tasks"]) != 12:
        raise ValueError("A frozen twelve-slot CTC plan with the matching identity is required")
    verify_sources(plan, models=True)
    for task in plan["tasks"]:
        clip = next(clip for clip in plan["clips"] if clip["id"] == task["clip"])
        verify_clip(clip)
        saved = verify_upstream(task, clip, plan)
        progress_path = LOCAL / name / "progress" / f"{task['id']}.json"
        if progress_path.exists():
            prior = read(progress_path)
            verify_progress(task, prior, plan_hash)
            if prior["status"] == "completed":
                verify_harness(task, clip, plan)
                verify_ctc(task, clip, saved)
            continue
        command = [sys.executable, str(ROOT / "experiments/run_experiment.py"), "--id", task["id"],
                   "--audio", task["audio"], "--reference", clip["source_srt"],
                   "--reference-sha256", clip["source_srt_sha256"], "--timeout", "3600", "--", *task["command"]]
        harness = ROOT / ".local/results" / task["id"] / "manifest.json"
        record = {"plan_sha256": plan_hash, "task_command": task["command"], "command": command,
                  "source_asr": task["source_asr"], "cached_asr_complete": True,
                  "new_asr_inference": False, "new_ctc_inference": None, "artifact_sha256": {}}
        if harness.parent.exists():
            try:
                verify_harness(task, clip, plan)
                verify_ctc(task, clip, saved)
            except (OSError, ValueError, KeyError) as error:
                raise RuntimeError("Interrupted evidence is retained; choose a new CTC attempt identity") from error
            record.update(status="completed", returncode=0, recovered_completed_harness=True)
        else:
            print(json.dumps({"starting": task["id"]}), flush=True)
            done = subprocess.run(command, cwd=ROOT, check=False)
            record.update(status="failed", returncode=done.returncode)
            if done.returncode == 0:
                try:
                    verify_harness(task, clip, plan)
                    verify_ctc(task, clip, saved)
                    record["status"] = "completed"
                except (OSError, ValueError, KeyError) as error:
                    record["failure_reason"] = str(error)
        if harness.is_file():
            record["harness_sha256"] = digest(harness)
            record["new_ctc_harness_wall_s"] = read(harness).get("wall_seconds")
        if Path(task["output"]).is_file():
            record["output_sha256"] = digest(task["output"])
            record["artifact_sha256"][task["output"]] = record["output_sha256"]
        verify_upstream(task, clip, plan)
        record["new_ctc_inference"] = (validate_ctc_evidence(read(task["output"]))["executed"]
                                      if record["status"] == "completed" else None)
        record["evaluation_status"] = "completed" if record["status"] == "completed" else "alignment_failed"
        write_new(progress_path, record)
        print(json.dumps({"finished": task["id"], "status": record["status"]}), flush=True)
    verify_sources(plan, models=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    prepare(args.name) if args.action == "prepare" else run(args.name)


if __name__ == "__main__":
    main()
