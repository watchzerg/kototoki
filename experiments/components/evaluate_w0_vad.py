"""Score terminal VAD/W0-only extensions using immutable existing audit helpers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.analysis.development_selection import axes, dominates
from experiments.components import evaluate as generic
from experiments.components import evaluate_vad as pilot
from experiments.components import run_vad as runner
from experiments.components.finalize_manifest import checked
from experiments.components.run import ROOT, LOCAL, digest, read, write_new
from experiments.components.separate import read_pcm

REVISION = "terminal-w0-only-vad-extension-evaluation-v1"
AXES = ("CER", "deletion_rate", "insertion_rate", "negative_complete_fraction",
        "negative_measurable_coverage", "negative_success_0.5_lower",
        "negative_success_2.0_lower", "negative_success_5.0_lower")


def assemble(name: str, manifest_path: Path) -> dict[str, Any]:
    runner.validate_name(name)
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to((ROOT / ".local").resolve()) or manifest_path.exists():
        raise ValueError("W0 VAD extension manifest requires a new private .local identity")
    plan_path = LOCAL / name / "plan.json"
    plan, plan_identity = checked(plan_path)
    if plan.get("id") != name or plan.get("frozen") is not True:
        raise ValueError("A matching frozen W0 VAD extension plan is required")
    clips = plan["clips"]
    tasks = {(task["clip"], task["stage"]): task for task in plan["tasks"]}
    expected = {(clip["id"], stage) for clip in clips for stage in ("vad", "w0")}
    if (not clips or len({clip["id"] for clip in clips}) != len(clips)
            or len(tasks) != len(plan["tasks"]) or set(tasks) != expected):
        raise ValueError("W0 VAD extension requires exactly VAD/W0 tasks for every unique clip")
    progress = {}
    for task in plan["tasks"]:
        path = LOCAL / name / "progress" / (task["id"] + ".json")
        if not path.is_file():
            raise ValueError("W0 VAD extension batch is not terminal; no partial scoring")
        record = read(path)
        if record.get("status") not in pilot.TERMINAL:
            raise ValueError("W0 VAD extension has nonterminal tasks")
        runner.verify_progress(task, record, plan_identity["sha256"])
        progress[task["id"]] = record
    runner.verify_sources(plan)
    historical, historical_identity = checked(ROOT / ".local/round2/progress.json")
    routes = {route: {"id": route, "configuration_id": route, "runs": []}
              for route in ("w0-baseline", "w0-vad", "w1-baseline", "x0-baseline")}
    receipts = []
    for clip in clips:
        runner.verify_clip(clip)
        _, identity = read_pcm(Path(clip["audio"]))
        for route in ("w0", "w1", "x0"):
            routes[f"{route}-baseline"]["runs"].append(pilot.baseline(route, clip, historical["tasks"]))
        vad_task, task = tasks[(clip["id"], "vad")], tasks[(clip["id"], "w0")]
        vad_record, record = progress[vad_task["id"]], progress[task["id"]]
        slot, result, _ = pilot._slot(task, record, clip)
        vad, vad_sha = None, None
        if vad_record["status"] == "completed":
            runner.verify_harness(vad_task, clip, plan)
            vad = read(vad_task["output"])
            vad_sha = digest(vad_task["output"])
            pilot.w0_contract(vad, identity, clip["offset"])
        if record["status"] == "completed":
            if vad is None:
                raise ValueError("Completed W0 VAD has no completed VAD dependency")
            runner.verify_harness(task, clip, plan)
            eligible = pilot.verify_w0(result, vad, identity, clip, vad_sha)
            slot.update(status="completed" if eligible else "execution_unverified", execution_verified=eligible)
        routes["w0-vad"]["runs"].append(slot)
        walls = {}
        for stage, stage_task in (("vad", vad_task), ("w0", task)):
            harness_path = ROOT / ".local/results" / stage_task["id"] / "manifest.json"
            walls[stage] = read(harness_path).get("wall_seconds") if harness_path.is_file() else None
        receipts.append({"clip_id": clip["id"], "vad_status": vad_record["status"], "w0_status": record["status"],
            "vad_manifest": {"path": vad_task["output"], "sha256": vad_sha},
            "chunks": len(vad["chunks"]) if vad else None,
            "retained_samples": sum(chunk["end_sample_exclusive"] - chunk["start_sample"] for chunk in vad["chunks"]) if vad else None,
            "original_samples": identity["samples"], "stage_harness_wall_seconds": walls,
            "end_to_end_harness_wall_seconds": sum(walls.values()) if all(value is not None for value in walls.values()) else None})
    sources = dict(plan["source_sha256"])
    for path in (Path(__file__), Path(pilot.__file__), Path(generic.__file__)):
        sources[str(path.resolve())] = digest(path)
    manifest = {"schema_version": 1, "manifest_id": name, "frozen": True, "strict_hashes": True,
        "clips": clips, "configurations": list(routes.values()), "source_sha256": sources,
        "assembly": {"revision": REVISION, "plan": plan_identity, "historical_progress": historical_identity,
            "scope": "Exposed component development extension; repeated pilot windows remain the same corpus units",
            "audit_helpers": {"path": str(Path(pilot.__file__).resolve()), "sha256": digest(Path(pilot.__file__))},
            "receipts": receipts, "cost_scope": "Sum shared VAD and W0 cold harness processes; baseline cached files remain historical observations"}}
    write_new(manifest_path, manifest)
    return manifest


def decision_diagnostics(report: dict[str, Any]) -> dict[str, Any]:
    """Apply the existing eight-axis definition descriptively, without promotion."""
    scopes = {"pooled": report["pooled"], **report["films"]}
    result = {"revision": REVISION, "axes": list(AXES), "axis_direction": "Smaller is favorable on every listed axis",
              "scope": "Descriptive eight-axis check; no automatic selection or production approval", "scopes": {}}
    for name, scope in scopes.items():
        routes = {route["route_id"]: route for route in scope["routes"]}
        baseline, vad = routes["w0-baseline"], routes["w0-vad"]
        pair = next(pair for pair in scope["comparisons"] if pair["left"] == "w0-baseline" and pair["right"] == "w0-vad")
        baseline_axes, vad_axes = axes(baseline), axes(vad)
        result["scopes"][name] = {"baseline": list(baseline_axes), "vad": list(vad_axes),
            "vad_minus_baseline": [new - old for old, new in zip(baseline_axes, vad_axes)],
            "vad_dominates_baseline": dominates(vad, baseline),
            "baseline_dominates_vad": dominates(baseline, vad),
            "success_bounds": {key: {"baseline": baseline["summary"]["timing"]["success"][key],
                                     "vad": vad["summary"]["timing"]["success"][key]}
                               for key in ("0.5", "2.0", "5.0")},
            "common_valid_count": pair["common_valid_count"], "paired_scene_bootstrap": pair["paired_scene_bootstrap"]}
    return result


def build(name: str, manifest_path: Path, output: Path) -> dict[str, Any]:
    output = output.resolve()
    allowed = (ROOT / ".local").resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("W0 VAD extension requires a new private analysis snapshot")
    manifest = assemble(name, manifest_path)
    report = generic.build(manifest_path, output)
    write_new(output / "vad-evidence.json", manifest["assembly"])
    write_new(output / "decision-diagnostics.json", decision_diagnostics(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.name, args.manifest, args.output)
    print(json.dumps({"revision": REVISION, "output": str(args.output.resolve()),
        "table_rows": value["pooled"]["table_rows"]}, ensure_ascii=False))
