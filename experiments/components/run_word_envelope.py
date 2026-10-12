"""Preregister a deterministic native-word envelope fix as a separate CTC-only attempt."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.components.align_raw_w0 import ROOT, LOCAL, verify_upstream
from experiments.components.run import digest, read, write_new, replace
from experiments.components.run_vad import validate_name, verify_sources, verify_clip, verify_progress, verify_harness
from experiments.components.word_envelope_ctc import build_bridge, verify_bridge
from experiments.qwen.run_cross import validate_ctc_evidence

BASE_NAME = "comp-raw-w0-ctc-dev-v1"


def prepare(name: str) -> dict:
    validate_name(name)
    destination = LOCAL / name
    if destination.exists():
        raise FileExistsError("Use a new envelope-fix attempt identity")
    base_path = LOCAL / BASE_NAME / "plan.json"
    base = read(base_path)
    verify_sources(base, models=True)
    if len(base["clips"]) != 12 or len(base["tasks"]) != 12:
        raise ValueError("Fix variant must retain the complete twelve-clip raw W0 registry")
    clips = {clip["id"]: clip for clip in base["clips"]}
    plan = deepcopy(base)
    plan.update(id=name, base_ctc_plan={"path": str(base_path), "sha256": digest(base_path)}, tasks=[],
                component="unchanged normalized standard CUDA CTC; parent search bounds enclose their own unmodified native words",
                scope="separate preregistered twelve-clip input-contract fix; original failed attempt retained",
                repair_policy="all segments: envelope(parent,native own words), clamp input; reject invalid or overlapping bounds; no reference, scores or padding",
                cost_policy="cached raw W0 cost + new CTC harness; no ASR/VAD inference or changed model/decoder options")
    products = []
    for original_task in base["tasks"]:
        clip = clips[original_task["clip"]]
        verify_clip(clip)
        saved = verify_upstream(original_task, clip, base)
        bridge_path = destination / "bridges" / f"{clip['id']}.json"
        bridge = build_bridge(Path(original_task["source_asr"]["path"]), Path(clip["audio"]), clip["offset"])
        verify_bridge(bridge, saved, clip["offset"])
        task = deepcopy(original_task)
        task["id"] = f"{name}-{clip['id']}-ctc"
        task["output"] = str(ROOT / ".local/results" / task["id"] / "result.json")
        if Path(task["output"]).parent.exists():
            raise FileExistsError("Preexisting stage artifacts cannot be reused")
        replace(task["command"], "--output", task["output"])
        replace(task["command"], "--asr-result", bridge_path)
        task["bridge"] = {"path": str(bridge_path), "sha256": None,
                          "bounds_mapping_sha256": bridge["window_repair"]["mapping_sha256"],
                          "changed_segments": bridge["window_repair"]["changed_segments"]}
        products.append((task, bridge))
        plan["tasks"].append(task)
    for relative in ("experiments/components/word_envelope_ctc.py", "experiments/components/run_word_envelope.py"):
        path = ROOT / relative
        plan["source_sha256"][str(path)] = digest(path)
    # Freeze the complete mapping before starting any GPU work, after all inputs pass.
    for task, bridge in products:
        write_new(Path(task["bridge"]["path"]), bridge)
        task["bridge"]["sha256"] = digest(task["bridge"]["path"])
    write_new(destination / "plan.json", plan)
    return plan


def verify_input(task: dict, clip: dict, plan: dict) -> dict:
    if digest(plan["base_ctc_plan"]["path"]) != plan["base_ctc_plan"]["sha256"]:
        raise ValueError("Original raw CTC attempt plan changed")
    saved = verify_upstream(task, clip, plan)
    if digest(task["bridge"]["path"]) != task["bridge"]["sha256"]:
        raise ValueError("Frozen envelope bridge changed")
    bridge = read(task["bridge"]["path"])
    verify_bridge(bridge, saved, clip["offset"])
    origin = bridge["original_asr"]
    if (Path(origin["source_result"]).resolve() != Path(task["source_asr"]["path"]).resolve()
            or origin["source_result_sha256"] != task["source_asr"]["sha256"]
            or bridge["window_repair"]["source_sha256"] != plan["source_sha256"][str(ROOT / "experiments/components/word_envelope_ctc.py")]):
        raise ValueError("Bridge lost its frozen original ASR or repair implementation identity")
    if bridge["window_repair"]["mapping_sha256"] != task["bridge"]["bounds_mapping_sha256"]:
        raise ValueError("Frozen source-to-search bound mapping changed")
    return bridge


def verify_result(task: dict, clip: dict, bridge: dict) -> dict:
    result = read(task["output"])
    if (result.get("status", "ok") != "ok" or result.get("route") != "W1"
            or result.get("text") != bridge["text"] or result.get("original_segments") != bridge["original_segments"]
            or result.get("input", {}).get("pcm_sha256") != clip["pcm_sha256"]
            or result.get("input", {}).get("file_sha256") != clip["audio_sha256"]
            or result.get("offset_s") != clip["offset"]
            or result.get("native", {}).get("reused_asr_file") != task["bridge"]["path"]
            or result.get("effective_parameters", {}).get("asr_reused") is not True):
        raise ValueError("CTC changed complete text, repaired search bounds, source origin or input")
    return validate_ctc_evidence(result)


def run(name: str) -> None:
    validate_name(name)
    plan_path = LOCAL / name / "plan.json"
    plan, plan_hash = read(plan_path), digest(plan_path)
    if plan.get("id") != name or plan.get("frozen") is not True or len(plan["tasks"]) != 12:
        raise ValueError("A matching preregistered twelve-slot fix plan is required")
    verify_sources(plan, models=True)
    for task in plan["tasks"]:
        clip = next(clip for clip in plan["clips"] if clip["id"] == task["clip"])
        verify_clip(clip)
        bridge = verify_input(task, clip, plan)
        progress_path = LOCAL / name / "progress" / f"{task['id']}.json"
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
                  "new_asr_inference": False, "new_ctc_inference": None,
                  "artifact_sha256": {task["bridge"]["path"]: task["bridge"]["sha256"]}}
        if harness.parent.exists():
            try:
                verify_harness(task, clip, plan)
                evidence = verify_result(task, clip, bridge)
            except (OSError, ValueError, KeyError) as error:
                raise RuntimeError("Interrupted fix artifacts are retained; use a new attempt identity") from error
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
