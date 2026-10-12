"""Freeze unchanged CUDA CTC on complete cached original-coordinate W0+VAD results."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.components.run import digest, read, write_new, replace
from experiments.components.run_vad import (
    ROOT, LOCAL, validate_name, verify_sources, verify_clip, verify_progress, verify_harness,
)
from experiments.components.w0_vad import validate_vad
from experiments.components.word_envelope_ctc import envelope, mapping_hash, verify_bridge
from experiments.components.run_word_envelope import verify_result

SOURCE_NAME = "comp-vad-dev-v1"
CTC_NAME = "comp-w0-ctc-envelope-dev-v1"


def validate_cached_asr(saved: dict, vad: dict, identity: dict, clip: dict, vad_hash: str) -> None:
    """Validate the VAD candidate, including its original waveform and native decode options."""
    contract = validate_vad(vad, identity, clip["offset"])
    experimental = saved.get("experimental_vad", {})
    params = saved.get("effective_parameters", {})
    expected = {"language": "ja", "task": "transcribe", "beam_size": 5, "word_timestamps": True,
                "vad_filter": False, "chunk_length": 30, "condition_on_previous_text": False,
                "clip_timestamps": contract["clip_timestamps"]}
    segments = saved.get("original_segments")
    if (saved.get("status", "ok") != "ok" or saved.get("route") != "W0-pyannote-vad-clips"
            or saved.get("cached_inference") is not False or saved.get("offline_requested") is not True
            or saved.get("offset_s") != clip["offset"]
            or any(saved.get("input", {}).get(key) != identity[key] for key in
                   ("file_sha256", "pcm_sha256", "samples", "sample_rate", "channels", "duration_s"))
            or experimental.get("file_sha256") != vad_hash
            or any(experimental.get(key) != value for key, value in contract.items())
            or experimental.get("audio_transform") != "original complete PCM; clips use original feature/time coordinates"
            or any(params.get("transcribe", {}).get(key) != value for key, value in expected.items())
            or "temperature" in params.get("transcribe", {})
            or params.get("temperature") != "unchanged native fallback defaults"
            or not isinstance(segments, list) or not isinstance(saved.get("text"), str)
            or saved.get("native", {}).get("segments") != segments):
        raise ValueError("Cached W0+VAD input, source coordinates, complete segments or native configuration differs")
    # Reject invalid word/search coordinates before any plan or derived input is written.
    envelope(segments, identity["duration_s"])
    if "".join(segment["text"] for segment in segments) != saved["text"]:
        raise ValueError("Cached W0+VAD omitted complete ASR text")
    device = saved.get("devices", {}).get("asr", {})
    if contract["empty_speech"]:
        if segments or saved["text"] or device.get("inference_executed") is not False:
            raise ValueError("Empty VAD falsely claims ASR execution or text")
        return
    if (device.get("device") != "cuda" or device.get("compute_type") != "float16"
            or device.get("device_index") not in (0, [0]) or device.get("inference_requested") is not True
            or params.get("info", {}).get("transcription_options", {}).get("temperatures") != [0, .2, .4, .6, .8, 1]
            or saved.get("environment", {}).get("packages", {}).get("faster-whisper") != "1.2.1"):
        raise ValueError("Cached W0+VAD lacks frozen CUDA/native fallback evidence")


def source_cache(clip: dict, parent: dict, parent_path: Path) -> tuple[dict, dict]:
    """Audit both completed upstream tasks without rerunning either inference stage."""
    identity = verify_clip(clip)
    parent_hash = digest(parent_path)
    matching = [task for task in parent["tasks"] if task["clip"] == clip["id"]]
    tasks = {task["stage"]: task for task in matching}
    if len(matching) != 2 or set(tasks) != {"vad", "w0"} or tasks["w0"]["depends_on"] != [tasks["vad"]["id"]]:
        raise ValueError("Cached stack requires exactly the matching completed VAD and W0 chain")
    sources = {}
    for stage in ("vad", "w0"):
        task = tasks[stage]
        progress_path = parent_path.parent / "progress" / (task["id"] + ".json")
        progress = read(progress_path)
        verify_progress(task, progress, parent_hash)
        if progress["status"] != "completed" or progress.get("returncode") != 0:
            raise ValueError("Every cached VAD and ASR stage must be independently complete")
        harness_path = verify_harness(task, clip, parent)
        result = read(task["output"])
        implementation = result.get("implementation", {})
        adapter = Path(task["command"][1]).resolve()
        if implementation.get("adapter_sha256" if stage == "vad" else "sha256") != parent["source_sha256"][str(adapter)]:
            raise ValueError("Cached inference result differs from its frozen executed adapter")
        sources[stage] = {"id": task["id"], "path": task["output"], "sha256": digest(task["output"]),
            "progress_path": str(progress_path), "progress_sha256": digest(progress_path),
            "harness_path": str(harness_path), "harness_sha256": digest(harness_path),
            "harness_wall_s": read(harness_path)["wall_seconds"]}
    vad, saved = read(sources["vad"]["path"]), read(sources["w0"]["path"])
    vad_model = vad.get("model", {})
    if (parent["model_sha256"].get(vad_model.get("path")) != vad_model.get("file_sha256")
            or not vad_model.get("file_sha256") or saved.get("model_identity", {}).get("vad") != vad_model):
        raise ValueError("Cached VAD checkpoint differs from the frozen model registry")
    if Path(saved["experimental_vad"]["manifest"]).resolve() != Path(sources["vad"]["path"]).resolve():
        raise ValueError("Cached ASR consumed another VAD manifest")
    validate_cached_asr(saved, vad, identity, clip, sources["vad"]["sha256"])
    if not saved["experimental_vad"]["empty_speech"]:
        model = saved["model_identity"]["asr"]
        acquisition = model.get("acquisition", {})
        if Path(model["path"]).resolve() != ROOT / ".local/models/faster-whisper-large-v3" or acquisition.get("complete") is not True:
            raise ValueError("Cached VAD-ASR model identity is incomplete")
        files = acquisition.get("files", [])
        if not {"model.bin", "config.json", "tokenizer.json", "vocabulary.json"}.issubset({Path(f["path"]).name for f in files}):
            raise ValueError("Cached VAD-ASR checkpoint/tokenizer identities are incomplete")
        for asset in files:
            if parent["model_sha256"].get(str((ROOT / asset["path"]).resolve())) != asset["sha256"]:
                raise ValueError("Cached VAD-ASR checkpoint differs from the frozen registry")
    source = {**sources["w0"], "vad": sources["vad"], "cached_asr_complete": True,
              "cached_asr_text_sha256": hashlib.sha256(saved["text"].encode()).hexdigest(),
              "costs": {"cached_asr_harness_wall_s": sources["w0"]["harness_wall_s"],
                        "cached_vad_harness_wall_s": sources["vad"]["harness_wall_s"],
                        "new_asr_inference": False, "new_vad_inference": False, "new_ctc_inference": True}}
    return saved, source


def build_bridge(saved: dict, source: dict) -> dict:
    repaired, mapping = envelope(saved["original_segments"], saved["input"]["duration_s"])
    return {"schema_version": 1, "status": "ok", "text": saved["text"], "input": deepcopy(saved["input"]),
            "offset_s": saved["offset_s"], "source_start_seconds": saved["offset_s"],
            "duration_seconds": saved["input"]["duration_s"], "original_segments": repaired,
            "original_asr": {"source_result": source["path"], "source_result_sha256": source["sha256"],
                             "text": saved["text"], "original_segments": deepcopy(saved["original_segments"])},
            "upstream_vad": deepcopy(source["vad"]), "cached_inference": True, "new_asr_inference": False,
            "window_repair": {"method": "parent-and-own-native-word-envelope-v1", "mapping": mapping,
                "mapping_sha256": mapping_hash(mapping), "changed_segments": sum(row["changed"] for row in mapping),
                "source_sha256": digest(ROOT / "experiments/components/word_envelope_ctc.py"),
                "bridge_source_sha256": digest(Path(__file__)), "reference_text_used": False,
                "ctc_scores_used": False, "padding_s": 0, "concatenated_audio": False},
            "stage_cache": {"vad": "complete cached CUDA VAD", "asr": "complete cached W0+VAD",
                            "alignment": "not_yet_executed"}}


def prepare(name: str) -> dict:
    validate_name(name)
    destination = LOCAL / name
    if destination.exists():
        raise FileExistsError("Use a new stacked experiment identity")
    parent_path, template_path = LOCAL / SOURCE_NAME / "plan.json", LOCAL / CTC_NAME / "plan.json"
    parent, template = read(parent_path), read(template_path)
    verify_sources(parent, models=True)
    verify_sources(template, models=True)
    if len(parent["clips"]) != 12 or parent["clips"] != template["clips"] or len(template["tasks"]) != 12:
        raise ValueError("VAD cache and unchanged CTC template must use the same complete twelve-clip registry")
    plan = deepcopy(template)
    plan.update(id=name, tasks=[], source_plan={"path": str(parent_path), "sha256": digest(parent_path)},
                ctc_template_plan={"path": str(template_path), "sha256": digest(template_path)},
                component="cached original-coordinate W0+VAD plus unchanged normalized standard Japanese CUDA CTC",
                scope="user-requested bounded twelve-clip stack; no ASR/VAD rerun or parameter sweep",
                selection_policy="subtitle offset priority; preserve separate recognition/coverage guardrails",
                cost_policy="cached VAD wall + cached VAD-ASR wall + new CTC wall; only CTC newly executed",
                comparison_routes=["w0-baseline", "w1-baseline", "x0-baseline", "w0-ctc", "w0-vad", "w0-vad-ctc"])
    plan.pop("base_ctc_plan", None)
    plan["source_sha256"].update(parent["source_sha256"])
    plan["source_sha256"][str(Path(__file__).resolve())] = digest(Path(__file__))
    products = []
    for original_task in template["tasks"]:
        clip = next(c for c in parent["clips"] if c["id"] == original_task["clip"])
        saved, source = source_cache(clip, parent, parent_path)
        bridge = build_bridge(saved, source)
        verify_bridge(bridge, saved, clip["offset"])
        task = deepcopy(original_task)
        task.update(id=f"{name}-{clip['id']}-ctc", source_asr=source)
        task["output"] = str(ROOT / ".local/results" / task["id"] / "result.json")
        if Path(task["output"]).parent.exists():
            raise FileExistsError("Existing CTC artifacts cannot be reused under a new identity")
        bridge_path = destination / "bridges" / (clip["id"] + ".json")
        replace(task["command"], "--output", task["output"])
        replace(task["command"], "--asr-result", bridge_path)
        task["bridge"] = {"path": str(bridge_path), "sha256": None,
            "bounds_mapping_sha256": bridge["window_repair"]["mapping_sha256"],
            "changed_segments": bridge["window_repair"]["changed_segments"]}
        plan["tasks"].append(task)
        products.append((task, bridge))
    # All twelve source contracts pass before writing any derived input or frozen plan.
    for task, bridge in products:
        write_new(Path(task["bridge"]["path"]), bridge)
        task["bridge"]["sha256"] = digest(task["bridge"]["path"])
    write_new(destination / "plan.json", plan)
    return plan


def verify_upstream(task: dict, clip: dict, plan: dict) -> dict:
    for key in ("source_plan", "ctc_template_plan"):
        if digest(plan[key]["path"]) != plan[key]["sha256"]:
            raise ValueError("Frozen stack source or unchanged CTC template plan changed")
    parent_path = Path(plan["source_plan"]["path"])
    saved, source = source_cache(clip, read(parent_path), parent_path)
    if source != task["source_asr"]:
        raise ValueError("Frozen cached VAD/ASR artifacts, execution evidence or costs changed")
    return saved


def verify_input(task: dict, clip: dict, plan: dict) -> dict:
    saved = verify_upstream(task, clip, plan)
    if digest(task["bridge"]["path"]) != task["bridge"]["sha256"]:
        raise ValueError("Frozen VAD-ASR-to-CTC bridge changed")
    bridge = read(task["bridge"]["path"])
    verify_bridge(bridge, saved, clip["offset"])
    if (bridge != build_bridge(saved, task["source_asr"])
            or bridge["window_repair"]["mapping_sha256"] != task["bridge"]["bounds_mapping_sha256"]):
        raise ValueError("Stack bridge lost its complete cached ASR, VAD or deterministic search mapping")
    return bridge


def run(name: str) -> None:
    validate_name(name)
    plan_path = LOCAL / name / "plan.json"
    plan, plan_hash = read(plan_path), digest(plan_path)
    if plan.get("id") != name or plan.get("frozen") is not True or len(plan["tasks"]) != 12:
        raise ValueError("A matching frozen twelve-slot stack plan is required")
    verify_sources(plan, models=True)
    for task in plan["tasks"]:
        clip = next(c for c in plan["clips"] if c["id"] == task["clip"])
        bridge = verify_input(task, clip, plan)
        progress_path = LOCAL / name / "progress" / (task["id"] + ".json")
        if progress_path.exists():
            prior = read(progress_path)
            verify_progress(task, prior, plan_hash)
            if prior["status"] == "completed":
                verify_harness(task, clip, plan)
                verify_result(task, clip, bridge)
            continue
        command = [sys.executable, str(ROOT / "experiments/run_experiment.py"), "--id", task["id"],
                   "--audio", task["audio"], "--reference", clip["source_srt"],
                   "--reference-sha256", clip["source_srt_sha256"], "--timeout", "3600", "--", *task["command"]]
        harness = ROOT / ".local/results" / task["id"] / "manifest.json"
        record = {"plan_sha256": plan_hash, "task_command": task["command"], "command": command,
                  "source_asr": task["source_asr"], "bridge": task["bridge"], "cached_asr_complete": True,
                  "cached_vad_complete": True, "new_asr_inference": False, "new_vad_inference": False,
                  "new_ctc_inference": None, "artifact_sha256": {task["bridge"]["path"]: task["bridge"]["sha256"]}}
        if harness.parent.exists():
            try:
                verify_harness(task, clip, plan)
                evidence = verify_result(task, clip, bridge)
            except (OSError, ValueError, KeyError) as error:
                raise RuntimeError("Interrupted stack artifacts retained; use a new attempt identity") from error
            record.update(status="completed", returncode=0, recovered_completed_harness=True)
        else:
            print(json.dumps({"starting": task["id"]}), flush=True)
            done = subprocess.run(command, cwd=ROOT, check=False)
            record.update(status="failed", returncode=done.returncode)
            if done.returncode == 0:
                try:
                    verify_harness(task, clip, plan)
                    evidence = verify_result(task, clip, bridge)
                    record["status"] = "completed"
                except (OSError, ValueError, KeyError) as error:
                    record["failure_reason"] = str(error)
        if harness.is_file():
            record["harness_sha256"] = digest(harness)
            record["new_ctc_harness_wall_s"] = read(harness).get("wall_seconds")
        if Path(task["output"]).is_file():
            record["output_sha256"] = digest(task["output"])
            record["artifact_sha256"][task["output"]] = record["output_sha256"]
        verify_input(task, clip, plan)
        if record["status"] == "completed":
            record["new_ctc_inference"] = evidence["executed"]
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
