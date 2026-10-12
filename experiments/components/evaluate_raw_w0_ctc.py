"""Score terminal cached raw W0 + CTC runs without hiding alignment failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from experiments.analysis.build_round2 import display_summary, input_identity
from experiments.analysis.development_selection import axes, dominates
from experiments.components import align_raw_w0 as runner
from experiments.components import evaluate as generic
from experiments.components import evaluate_vad as audit
from experiments.components.finalize_manifest import checked
from experiments.components.run import ROOT, LOCAL, digest, read, write_new

REVISION = "terminal-raw-w0-standard-ctc-evaluation-v1"
AXIS_NAMES = ("CER", "deletion_rate", "insertion_rate", "negative_complete_fraction", "negative_measurable_coverage",
              "negative_success_0.5_lower", "negative_success_2.0_lower", "negative_success_5.0_lower")


def phase_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    aligner = result.get("devices", {}).get("aligner", {})
    forwards = aligner.get("forward_observation", [])
    records = result.get("experimental_alignment", {}).get("records", [])
    preprocessing = result.get("experimental_preprocessing", {}).get("records", [])
    failed = [record for record in records if record.get("failure")]
    successful = [record for record in records if record.get("failure") is None]
    return {"full_original_characters": len(result.get("text", "")), "retained_unit_count": len(result.get("units", [])),
        "unit_status_counts": {status: sum(unit.get("status", "ok") == status for unit in result.get("units", []))
                               for status in ("ok", "failed", "text_only")},
        "decoder_record_count": len(records), "decoder_failure_count": len(failed),
        "decoder_failures": [{"segment_index": record.get("segment_index"), "failure": record.get("failure")} for record in failed],
        "model_device_cuda": str(aligner.get("model", "")).startswith("cuda:"), "forward_count": len(forwards),
        "all_forward_devices_cuda": bool(forwards) and all(str(device).startswith("cuda:") for device in forwards),
        "all_normalization_devices_cuda": bool(preprocessing) and all(str(record.get("actual_input_device", "")).startswith("cuda:") for record in preprocessing),
        "all_successful_decoder_devices_cuda": bool(successful) and all(
            str(record.get("decoder_input_device", "")).startswith("cuda:") and str(record.get("decoder_output_device", "")).startswith("cuda:")
            for record in successful)}


def preserve_slot(slot: dict[str, Any], saved: dict[str, Any], clip: dict[str, Any], manifest_path: Path) -> None:
    target = manifest_path.parent / "preserved-asr" / (slot["run_id"] + ".json")
    write_new(target, {"schema_version": 1, "text": saved["text"], "units": [], "cues": [],
        "input_sha256": clip["audio_sha256"], "source_start_seconds": clip["offset"], "duration_seconds": clip["duration"]})
    slot.update(status="alignment_failed", execution_verified=False, result_path=str(target), result_sha256=digest(target),
                failure_reason="complete_cached_raw_w0_text_retained_after_dependent_alignment_failure")


def assemble(name: str, manifest_path: Path) -> dict[str, Any]:
    runner.validate_name(name)
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to((ROOT / ".local").resolve()) or manifest_path.exists():
        raise ValueError("Raw W0 CTC scoring requires a new private manifest")
    plan, plan_id = checked(LOCAL / name / "plan.json")
    if plan.get("id") != name or plan.get("frozen") is not True:
        raise ValueError("Matching frozen raw W0 CTC plan required")
    clips = plan["clips"]
    tasks = {task["clip"]: task for task in plan["tasks"]}
    if (not clips or len(tasks) != len(plan["tasks"]) or set(tasks) != {clip["id"] for clip in clips}
            or any(task.get("stage") != "ctc" for task in tasks.values())):
        raise ValueError("Exactly one declared CTC task per complete clip registry is required")
    progress = {}
    for task in plan["tasks"]:
        path = LOCAL / name / "progress" / (task["id"] + ".json")
        if not path.exists():
            raise ValueError("Raw W0 CTC batch is not terminal; no partial scoring")
        record = read(path)
        if record.get("status") not in {"completed", "failed"}:
            raise ValueError("Raw W0 CTC batch has nonterminal tasks")
        runner.verify_progress(task, record, plan_id["sha256"])
        progress[task["id"]] = record
    runner.verify_sources(plan)
    original, original_id = checked(plan["source_plan"]["path"], plan["source_plan"]["sha256"])
    routes = {name: {"id": name, "configuration_id": name, "runs": []}
              for name in ("w0-baseline", "w0-ctc", "w1-baseline", "x0-baseline")}
    receipts = []
    for clip in clips:
        runner.verify_clip(clip)
        task = tasks[clip["id"]]
        record = progress[task["id"]]
        saved = runner.verify_upstream(task, clip, plan)
        if hashlib.sha256(saved["text"].encode()).hexdigest() != task["source_asr"]["cached_asr_text_sha256"]:
            raise ValueError("Cached complete raw W0 text identity changed")
        for route in ("w0", "w1", "x0"):
            routes[f"{route}-baseline"]["runs"].append(audit.baseline(route, clip, original["tasks"]))
        slot, result, harness = audit._slot(task, record, clip)
        facts = phase_diagnostics(result) if result and isinstance(result.get("text"), str) else {}
        if result and isinstance(result.get("text"), str):
            input_identity(result, harness, clip)
            if (result["text"] != saved["text"] or result.get("original_segments") != saved["original_segments"]
                    or result.get("native", {}).get("reused_asr_file") != task["source_asr"]["path"]):
                raise ValueError("Raw W0 CTC altered full ASR text, segments or cache identity")
            facts["partial_alignment_display"] = display_summary(result, clip)
        if record["status"] == "completed":
            runner.verify_harness(task, clip, plan)
            runner.verify_ctc(task, clip, saved)
            slot.update(status="completed", execution_verified=True)
        else:
            preserve_slot(slot, saved, clip, manifest_path)
        routes["w0-ctc"]["runs"].append(slot)
        walls = task["source_asr"]["costs"]
        new_wall = record.get("new_ctc_harness_wall_s")
        receipts.append({"clip_id": clip["id"], "status": slot["status"], "process_returncode": record.get("returncode"),
            "failure_reason": record.get("failure_reason"), "source_asr": task["source_asr"],
            "result": {"path": task["output"], "sha256": record.get("output_sha256")}, "phase_diagnostics": facts,
            "new_ctc_harness_wall_seconds": new_wall, "cached_raw_asr_harness_wall_seconds": walls["cached_asr_harness_wall_s"],
            "cached_plus_new_wall_seconds": walls["cached_asr_harness_wall_s"] + new_wall if new_wall is not None else None,
            "new_asr_inference": False, "full_text_identity_preserved": True,
            "failure_timing_policy": "Primary whole-window failure excludes all timing; original partial units stay immutable and have separate display diagnostics"})
    sources = dict(plan["source_sha256"])
    sources[str(Path(__file__).resolve())] = digest(Path(__file__))
    manifest = {"schema_version": 1, "manifest_id": name, "frozen": True, "strict_hashes": True,
        "clips": clips, "configurations": list(routes.values()), "source_sha256": sources,
        "assembly": {"revision": REVISION, "plan": plan_id, "original_raw_registry": original_id, "receipts": receipts,
            "scope": "Exposed complete development registry; no VAD or denoising; original failure outcomes retained",
            "cost_scope": "Cached historical raw ASR plus new CTC; not a fresh complete end-to-end run"}}
    write_new(manifest_path, manifest)
    return manifest


def diagnostics(report: dict[str, Any]) -> dict[str, Any]:
    result = {"revision": REVISION, "axes": list(AXIS_NAMES), "scopes": {}}
    for name, scope in {"pooled": report["pooled"], **report["films"]}.items():
        routes = {route["route_id"]: route for route in scope["routes"]}
        candidate = routes["w0-ctc"]
        result["scopes"][name] = {"candidate_axes": list(axes(candidate)), "against": {}}
        for baseline in ("w0-baseline", "w1-baseline", "x0-baseline"):
            other = routes[baseline]
            pair = next(pair for pair in scope["comparisons"] if {pair["left"], pair["right"]} == {baseline, "w0-ctc"})
            result["scopes"][name]["against"][baseline] = {"baseline_axes": list(axes(other)),
                "candidate_dominates": dominates(candidate, other), "baseline_dominates": dominates(other, candidate),
                "success_bounds_candidate": candidate["summary"]["timing"]["success"],
                "success_bounds_baseline": other["summary"]["timing"]["success"], "paired_comparison": pair}
    return result


def build(name: str, manifest_path: Path, output: Path) -> dict[str, Any]:
    allowed, output = (ROOT / ".local").resolve(), output.resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("Raw W0 CTC scoring requires a new private snapshot")
    manifest = assemble(name, manifest_path)
    report = generic.build(manifest_path, output)
    generic.write_new(output / "ctc-evidence.json", manifest["assembly"])
    generic.write_new(output / "decision-diagnostics.json", diagnostics(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.name, args.manifest, args.output)
    print(json.dumps({"revision": REVISION, "output": str(args.output.resolve()), "table_rows": value["pooled"]["table_rows"]}))
