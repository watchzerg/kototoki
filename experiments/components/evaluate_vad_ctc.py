"""Privately compare six immutable pipelines with complete timing denominators."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from kototoki_eval.schema import finite_time
from experiments.analysis.build_round2 import display_summary, input_identity
from experiments.analysis.development_selection import dominates
from experiments.display.replay import nonlexical
from experiments.components import evaluate as generic
from experiments.components import evaluate_raw_w0_ctc as raw_score
from experiments.components import evaluate_vad as audit
from experiments.components import run_vad_ctc as runner
from experiments.components import run_word_envelope as raw_runner
from experiments.components.evaluate_word_envelope import validate_output_identity
from experiments.components.finalize_manifest import checked
from experiments.components.run import ROOT, LOCAL, digest, read, write_new

REVISION = "terminal-w0-vad-native-word-envelope-ctc-six-route-v1"
RAW_NAME = "comp-w0-ctc-envelope-dev-v1"
VAD_NAME = "comp-vad-dev-v1"


def character_evidence(result: dict[str, Any]) -> dict[str, Any]:
    """Count timing loss and observed CTC wildcards without exporting text."""
    text = result["text"]
    lexical = {index for index, char in enumerate(text) if not nonlexical(char)}
    accepted = set()
    for unit in result.get("units", []):
        if (unit.get("status", "ok") == "ok" and finite_time(unit.get("start"))
                and finite_time(unit.get("end")) and unit["start"] >= 0 and unit["end"] > unit["start"]):
            accepted.update(range(unit["char_start"], unit["char_end"]))
    records = result.get("experimental_alignment", {}).get("records", [])
    segments = result.get("original_segments", [])
    offsets, cursor = [], 0
    for segment in segments:
        offsets.append(cursor)
        cursor += len(segment["text"])
    wildcard_positions, wildcard_count = set(), 0
    for record in records:
        for token in record.get("tokens", []):
            if token.get("evidence_kind") == "wildcard":
                wildcard_count += 1
                index = record["segment_index"]
                position = token["original_position"]
                if not 0 <= index < len(segments) or not 0 <= position < len(segments[index]["text"]):
                    raise ValueError("CTC wildcard position does not address complete ASR text")
                wildcard_positions.add(offsets[index] + position)
    return {"full_unicode_characters": len(text), "raw_lexical_characters": len(lexical),
        "timed_lexical_characters": len(lexical & accepted), "unmapped_lexical_characters": len(lexical - accepted),
        "untimed_nonlexical_characters": len(set(range(len(text))) - lexical - accepted),
        "oov_observation_available": bool(result.get("experimental_alignment")),
        "wildcard_tokens": wildcard_count, "lexical_wildcard_characters": len(lexical & wildcard_positions),
        "native_path_failure_count": sum(record.get("native_path_failed") is True for record in records),
        "scope": "ASR character timing evidence only; missing recognition remains separate CER/D accounting"}


def raw_ctc_slot(clip: dict[str, Any], plan: dict[str, Any], plan_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    task = next(task for task in plan["tasks"] if task["clip"] == clip["id"])
    record = read(LOCAL / RAW_NAME / "progress" / (task["id"] + ".json"))
    raw_runner.verify_progress(task, record, plan_hash)
    if record["status"] != "completed":
        raise ValueError("The frozen raw envelope comparator must retain its twelve completed results")
    bridge = raw_runner.verify_input(task, clip, plan)
    raw_runner.verify_harness(task, clip, plan)
    raw_runner.verify_result(task, clip, bridge)
    slot, result, _ = audit._slot(task, record, clip)
    slot.update(status="completed", execution_verified=True)
    return slot, result


def time_priority_diagnostics(report: dict[str, Any]) -> dict[str, Any]:
    result = {"revision": REVISION, "scope": "Practical timing gains and content costs; no automatic promotion", "scopes": {}}
    for name, scope in {"pooled": report["pooled"], **report["films"]}.items():
        routes = {route["route_id"]: route for route in scope["routes"]}
        candidate = routes["w0-vad-ctc"]
        comparisons = {}
        for route_id, other in routes.items():
            if route_id == "w0-vad-ctc":
                continue
            pair = next(pair for pair in scope["comparisons"] if {pair["left"], pair["right"]} == {route_id, "w0-vad-ctc"})
            comparisons[route_id] = {"candidate_dominates": dominates(candidate, other),
                "baseline_dominates": dominates(other, candidate), "paired_comparison": pair,
                "content_change_candidate_minus_baseline": {key: candidate["summary"]["text"][key] - other["summary"]["text"][key]
                                                           for key in ("CER", "D", "I")},
                "success_count_change_candidate_minus_baseline": {key: candidate["summary"]["timing"]["success"][key]["success_count"]
                    - other["summary"]["timing"]["success"][key]["success_count"] for key in ("0.5", "2.0", "5.0")}}
        result["scopes"][name] = {"against": comparisons}
    return result


def assemble(name: str, manifest_path: Path) -> dict[str, Any]:
    runner.validate_name(name)
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to((ROOT / ".local").resolve()) or manifest_path.exists():
        raise ValueError("Stack comparison requires a new private manifest")
    plan, plan_id = checked(LOCAL / name / "plan.json")
    clips = plan["clips"]
    tasks = {task["clip"]: task for task in plan["tasks"]}
    if (plan.get("id") != name or plan.get("frozen") is not True or len(clips) != 12
            or len({clip["id"] for clip in clips}) != 12 or len(tasks) != len(plan["tasks"])
            or set(tasks) != {clip["id"] for clip in clips}
            or any(task.get("stage") != "ctc" or not task.get("bridge") for task in tasks.values())):
        raise ValueError("Matching frozen twelve-window stack registry required")
    progress = {}
    for task in plan["tasks"]:
        path = LOCAL / name / "progress" / (task["id"] + ".json")
        if not path.exists():
            raise ValueError("Stack batch is not terminal; no partial scoring")
        record = read(path)
        if record.get("status") not in {"completed", "failed"}:
            raise ValueError("Stack batch has nonterminal tasks")
        runner.verify_progress(task, record, plan_id["sha256"])
        if (record.get("source_asr") != task["source_asr"] or record.get("bridge") != task["bridge"]
                or record.get("cached_asr_complete") is not True or record.get("cached_vad_complete") is not True
                or record.get("new_asr_inference") is not False or record.get("new_vad_inference") is not False):
            raise ValueError("Stack progress lost its frozen cached-stage execution identity")
        progress[task["id"]] = record
    runner.verify_sources(plan)
    vad_plan, vad_id = checked(plan["source_plan"]["path"], plan["source_plan"]["sha256"])
    raw_plan, raw_id = checked(plan["ctc_template_plan"]["path"], plan["ctc_template_plan"]["sha256"])
    if vad_plan.get("id") != VAD_NAME or raw_plan.get("id") != RAW_NAME or clips != vad_plan["clips"] or clips != raw_plan["clips"]:
        raise ValueError("All six comparators must use the same original twelve-window registry")
    raw_runner.verify_sources(raw_plan)
    original, original_id = checked(raw_plan["source_plan"]["path"], raw_plan["source_plan"]["sha256"])
    route_names = ("w0-baseline", "w1-baseline", "x0-baseline", "w0-ctc", "w0-vad", "w0-vad-ctc")
    configs = {route: {"id": route, "configuration_id": "w0-ctc-native-word-envelope" if route == "w0-ctc" else route,
                       "runs": []} for route in route_names}
    receipts = []
    for clip in clips:
        task, record = tasks[clip["id"]], progress[tasks[clip["id"]]["id"]]
        bridge = runner.verify_input(task, clip, plan)
        saved = read(task["source_asr"]["path"])
        phase_characters = {}
        for route in ("w0", "w1", "x0"):
            slot = audit.baseline(route, clip, original["tasks"])
            configs[f"{route}-baseline"]["runs"].append(slot)
            phase_characters[f"{route}-baseline"] = character_evidence(read(slot["result_path"]))
        raw_slot, raw = raw_ctc_slot(clip, raw_plan, raw_id["sha256"])
        configs["w0-ctc"]["runs"].append(raw_slot)
        phase_characters["w0-ctc"] = character_evidence(raw)
        source = task["source_asr"]
        asr_executed = not saved["experimental_vad"]["empty_speech"]
        configs["w0-vad"]["runs"].append({"clip_id": clip["id"], "run_id": source["id"],
            "status": "completed" if asr_executed else "execution_unverified",
            "execution_verified": asr_executed, "result_path": source["path"], "result_sha256": source["sha256"],
            "input_audio_path": clip["audio"], "input_audio_sha256": clip["audio_sha256"],
            "evidence": {"cached_source_chain": copy.deepcopy(source), "verification": "independent completed CUDA VAD and W0 harnesses"}})
        phase_characters["w0-vad"] = character_evidence(saved)
        slot, result, harness = audit._slot(task, record, clip)
        facts = raw_score.phase_diagnostics(result) if result and isinstance(result.get("text"), str) else {}
        if result and isinstance(result.get("text"), str):
            input_identity(result, harness, clip)
            validate_output_identity(result, saved, bridge, task)
            facts["partial_alignment_display"] = display_summary(result, clip)
            phase_characters["w0-vad-ctc"] = character_evidence(result)
        if record["status"] == "completed":
            runner.verify_harness(task, clip, plan)
            evidence = runner.verify_result(task, clip, bridge)
            if record.get("new_ctc_inference") != evidence["executed"]:
                raise ValueError("Stack progress does not preserve actual CTC execution evidence")
            slot.update(status="completed", execution_verified=True)
        else:
            raw_score.preserve_slot(slot, saved, clip, manifest_path)
        configs["w0-vad-ctc"]["runs"].append(slot)
        walls = source["costs"]
        new_wall = record.get("new_ctc_harness_wall_s")
        cached_wall = walls["cached_vad_harness_wall_s"] + walls["cached_asr_harness_wall_s"]
        receipts.append({"clip_id": clip["id"], "status": slot["status"], "failure_reason": record.get("failure_reason"),
            "process_returncode": record.get("returncode"), "source_asr": source, "bridge": task["bridge"],
            "window_repair": bridge["window_repair"], "phase_diagnostics": facts, "character_evidence_by_route": phase_characters,
            "result": {"path": task["output"], "sha256": record.get("output_sha256")},
            "new_ctc_harness_wall_seconds": new_wall, "cached_vad_asr_harness_wall_seconds": cached_wall,
            "cached_plus_new_wall_seconds": cached_wall + new_wall if new_wall is not None else None,
            "full_text_identity_preserved": True, "new_asr_inference": False, "new_vad_inference": False})
    sources = {**raw_plan["source_sha256"], **plan["source_sha256"]}
    dependencies = (Path(__file__), Path(generic.__file__), Path(audit.__file__), Path(raw_score.__file__),
        ROOT / "experiments/components/evaluate_word_envelope.py", ROOT / "experiments/components/finalize_manifest.py",
        ROOT / "experiments/components/run.py", ROOT / "experiments/analysis/build_round2.py",
        ROOT / "experiments/analysis/development_selection.py", ROOT / "experiments/display/replay.py",
        ROOT / "kototoki_eval/schema.py")
    for path in dependencies:
        sources[str(path.resolve())] = digest(path)
    manifest = {"schema_version": 1, "manifest_id": name, "frozen": True, "strict_hashes": True,
        "clips": clips, "configurations": list(configs.values()), "source_sha256": sources,
        "assembly": {"revision": REVISION, "plan": plan_id, "cached_vad_asr_plan": vad_id,
            "raw_envelope_comparator_plan": raw_id, "original_registry": original_id, "receipts": receipts,
            "scope": "User-requested timing-priority stack on identical exposed development windows; strict original score policy",
            "cost_scope": "Historical cached VAD+ASR plus new CTC, not fresh end-to-end inference"}}
    write_new(manifest_path, manifest)
    return manifest


def build(name: str, manifest_path: Path, output: Path) -> dict[str, Any]:
    allowed, output = (ROOT / ".local").resolve(), output.resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("Stack scoring requires a new private snapshot")
    manifest = assemble(name, manifest_path)
    report = generic.build(manifest_path, output)
    generic.write_new(output / "stack-evidence.json", manifest["assembly"])
    generic.write_new(output / "time-priority-diagnostics.json", time_priority_diagnostics(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = build(args.name, args.manifest, args.output)
    print(json.dumps({"revision": REVISION, "output": str(args.output.resolve()), "table_rows": value["pooled"]["table_rows"]}))
