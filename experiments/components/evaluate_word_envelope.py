"""Score a separate terminal native-word envelope CTC attempt privately."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.analysis.build_round2 import display_summary, input_identity
from experiments.components import evaluate as generic
from experiments.components import evaluate_raw_w0_ctc as raw_score
from experiments.components import evaluate_vad as audit
from experiments.components import run_word_envelope as runner
from experiments.components.finalize_manifest import checked
from experiments.components.run import ROOT, LOCAL, digest, read, write_new

REVISION = "terminal-native-word-envelope-ctc-evaluation-v1"


def validate_output_identity(result: dict[str, Any], saved: dict[str, Any], bridge: dict[str, Any], task: dict[str, Any]) -> None:
    if (result.get("text") != saved["text"] or bridge["text"] != saved["text"]
            or result.get("original_segments") != bridge["original_segments"]
            or result.get("native", {}).get("reused_asr_file") != task["bridge"]["path"]):
        raise ValueError("Envelope CTC altered complete original ASR text or frozen repaired search bounds")


def assemble(name: str, manifest_path: Path) -> dict[str, Any]:
    runner.validate_name(name)
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to((ROOT / ".local").resolve()) or manifest_path.exists():
        raise ValueError("Envelope scoring requires a new private manifest")
    plan, plan_id = checked(LOCAL / name / "plan.json")
    clips = plan["clips"]
    tasks = {task["clip"]: task for task in plan["tasks"]}
    if (plan.get("id") != name or plan.get("frozen") is not True or len(clips) != 12
            or len(tasks) != len(plan["tasks"]) or set(tasks) != {clip["id"] for clip in clips}
            or any(task.get("stage") != "ctc" or not task.get("bridge") for task in tasks.values())):
        raise ValueError("Matching frozen twelve-clip envelope CTC registry required")
    progress = {}
    for task in plan["tasks"]:
        path = LOCAL / name / "progress" / (task["id"] + ".json")
        if not path.exists():
            raise ValueError("Envelope CTC batch is not terminal; no partial scoring")
        record = read(path)
        if record.get("status") not in {"completed", "failed"}:
            raise ValueError("Envelope CTC batch has nonterminal tasks")
        runner.verify_progress(task, record, plan_id["sha256"])
        progress[task["id"]] = record
    runner.verify_sources(plan)
    original, original_id = checked(plan["source_plan"]["path"], plan["source_plan"]["sha256"])
    base, base_id = checked(plan["base_ctc_plan"]["path"], plan["base_ctc_plan"]["sha256"])
    if clips != base["clips"]:
        raise ValueError("Envelope attempt changed the original raw development registry")
    routes = {route: {"id": route, "configuration_id": route if route != "w0-ctc" else "w0-ctc-native-word-envelope", "runs": []}
              for route in ("w0-baseline", "w0-ctc", "w1-baseline", "x0-baseline")}
    receipts = []
    for clip in clips:
        runner.verify_clip(clip)
        task, record = tasks[clip["id"]], progress[tasks[clip["id"]]["id"]]
        saved = runner.verify_upstream(task, clip, plan)
        bridge = runner.verify_input(task, clip, plan)
        for route in ("w0", "w1", "x0"):
            routes[f"{route}-baseline"]["runs"].append(audit.baseline(route, clip, original["tasks"]))
        slot, result, harness = audit._slot(task, record, clip)
        facts = raw_score.phase_diagnostics(result) if result and isinstance(result.get("text"), str) else {}
        if result and isinstance(result.get("text"), str):
            input_identity(result, harness, clip)
            validate_output_identity(result, saved, bridge, task)
            facts["partial_alignment_display"] = display_summary(result, clip)
        if record["status"] == "completed":
            runner.verify_harness(task, clip, plan)
            runner.verify_result(task, clip, bridge)
            slot.update(status="completed", execution_verified=True)
        else:
            raw_score.preserve_slot(slot, saved, clip, manifest_path)
        routes["w0-ctc"]["runs"].append(slot)
        cached_wall, new_wall = task["source_asr"]["costs"]["cached_asr_harness_wall_s"], record.get("new_ctc_harness_wall_s")
        receipts.append({"clip_id": clip["id"], "status": slot["status"], "process_returncode": record.get("returncode"),
            "failure_reason": record.get("failure_reason"), "source_asr": task["source_asr"], "bridge": task["bridge"],
            "window_repair": bridge["window_repair"], "phase_diagnostics": facts,
            "result": {"path": task["output"], "sha256": record.get("output_sha256")},
            "new_ctc_harness_wall_seconds": new_wall, "cached_raw_asr_harness_wall_seconds": cached_wall,
            "cached_plus_new_wall_seconds": cached_wall + new_wall if new_wall is not None else None,
            "new_asr_inference": False, "full_text_identity_preserved": True,
            "failure_timing_policy": "Whole failed window excluded from primary timing; exact cached text retained"})
    sources = dict(plan["source_sha256"])
    dependencies = (Path(__file__), Path(raw_score.__file__), Path(generic.__file__), Path(audit.__file__),
                    ROOT / "experiments/components/finalize_manifest.py",
                    ROOT / "experiments/analysis/build_round2.py", ROOT / "experiments/analysis/development_selection.py",
                    ROOT / "experiments/components/run.py")
    for path in dependencies:
        sources[str(path.resolve())] = digest(path)
    manifest = {"schema_version": 1, "manifest_id": name, "frozen": True, "strict_hashes": True,
        "clips": clips, "configurations": list(routes.values()), "source_sha256": sources,
        "assembly": {"revision": REVISION, "plan": plan_id, "original_raw_registry": original_id,
            "retained_direct_ctc_attempt": base_id, "receipts": receipts,
            "scope": "Same exposed development registry; deterministic native-word envelope bridge; no VAD or denoising",
            "cost_scope": "Historical cached raw ASR plus new CTC; not fresh end-to-end inference"}}
    write_new(manifest_path, manifest)
    return manifest


def build(name: str, manifest_path: Path, output: Path) -> dict[str, Any]:
    allowed, output = (ROOT / ".local").resolve(), output.resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("Envelope scoring requires a new private snapshot")
    manifest = assemble(name, manifest_path)
    report = generic.build(manifest_path, output)
    generic.write_new(output / "ctc-evidence.json", manifest["assembly"])
    diagnostic = raw_score.diagnostics(report)
    diagnostic["revision"] = REVISION
    generic.write_new(output / "decision-diagnostics.json", diagnostic)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.name, args.manifest, args.output)
    print(json.dumps({"revision": REVISION, "output": str(args.output.resolve()), "table_rows": value["pooled"]["table_rows"]}))
