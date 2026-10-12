"""Migrate frozen component-builder manifests through a separate audited revision.

The running plan's builder and evaluator are never edited. The original builder
output remains immutable; a new manifest adds required configuration IDs and
binds full GPU/input/upstream evidence before declaring execution verified.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

from experiments.analysis.build_development import cuda_observed, gpu_verified
from experiments.analysis.build_heldout import qwen_asr_phase_complete
from experiments.analysis.build_round2 import input_identity
from experiments.analysis.build_validation import harness_complete, upstream_evidence
from experiments.components import manifest as frozen_builder
from experiments.components.run import ROOT, LOCAL, digest, read, verify_separation, write_new
from experiments.qwen.run_cross import validate_ctc_evidence

REVISION = "component-evaluation-manifest-finalizer-v1"
TERMINAL = {"completed", "failed", "blocked", "timeout", "harness_error", "missing"}


def checked(path: str | Path, expected: str | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    path = Path(path).resolve()
    actual = digest(path)
    if expected is not None and actual != expected:
        raise ValueError(f"Finalizer artifact SHA256 mismatch: {path}")
    value = read(path)
    if not isinstance(value, dict):
        raise ValueError(f"Finalizer expected JSON object: {path}")
    return value, {"path": str(path), "sha256": actual}


def _require_entry(entry: dict[str, Any], clip: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    if not entry.get("output_sha256") or not entry.get("harness_manifest_sha256"):
        raise ValueError("Historical result and harness need persisted hashes")
    result, result_id = checked(entry["output"], entry["output_sha256"])
    harness, harness_id = checked(entry["harness_manifest"], entry["harness_manifest_sha256"])
    if not harness_complete(harness):
        raise ValueError("Historical harness is not independently complete")
    input_identity(result, harness, clip)
    return result, harness, [result_id, harness_id]


def _fresh_qwen(result: dict[str, Any], harness: dict[str, Any], clip: dict[str, Any],
                *, alignment_required: bool) -> tuple[dict[str, Any], list[dict[str, str]]]:
    pipeline = result.get("pipeline")
    if not pipeline:
        pipeline, pipeline_id = checked(result["pipeline_manifest"])
    else:
        _, pipeline_id = checked(pipeline["manifest"], pipeline["manifest_sha256"])
    identities = [pipeline_id]
    stages = {stage["stage"]: stage for stage in pipeline.get("stages", [])}
    source = stages.get("asr", {})
    if source.get("status") != "completed" or source.get("returncode") != 0 or not source.get("output_sha256"):
        raise ValueError("Fresh X0 has no independently complete persisted ASR stage")
    asr, identity = checked(source["output"], source["output_sha256"])
    identities.append(identity)
    if (not asr.get("config", {}).get("offline")
            or not qwen_asr_phase_complete(asr, harness, expected_audio_sha256=clip["audio_sha256"],
                expected_offset=clip["offset"], expected_duration=clip["duration"])
            or any(window.get("token_limit_reached") is not False for window in asr["windows"])
            or not cuda_observed(asr.get("environment", {}).get("devices", {}).get("asr", {}))):
        raise ValueError("Fresh X0 complete-window/CUDA/offline ASR evidence invalid")
    for source_identity in pipeline.get("source_files", {}).values():
        if digest(source_identity["path"]) != source_identity["sha256"]:
            raise ValueError("Fresh X0 frozen source snapshot changed")
        identities.append({"path": source_identity["path"], "sha256": source_identity["sha256"]})
    if alignment_required:
        if pipeline.get("status") != "completed" or pipeline.get("new_asr_inference") is not True:
            raise ValueError("Fresh X0 pipeline is incomplete")
        for name in ("export", "ctc"):
            stage = stages[name]
            if stage.get("status") != "completed" or stage.get("returncode") != 0:
                raise ValueError("Fresh X0 bridge/CTC stage is incomplete")
            value, identity = checked(stage["output"], stage["output_sha256"])
            identities.append(identity)
            if value["text"] != asr["text"]:
                raise ValueError("Fresh X0 bridge/CTC changed complete ASR text")
            if name == "export":
                provenance = value["provenance"]
                if (provenance["source_result_sha256"] != source["output_sha256"]
                        or provenance.get("reference_text_used") is not False
                        or provenance.get("source_fa_times_used") is not False):
                    raise ValueError("Fresh X0 bridge source/no-reference identity invalid")
        if result["text"] != asr["text"]:
            raise ValueError("Fresh X0 final result changed full ASR text")
        validate_ctc_evidence(result)
    return asr, identities


def finalize(name: str, output: Path) -> dict[str, Any]:
    if not name or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in name):
        raise ValueError("Use a lowercase simple experiment name")
    output = output.resolve()
    if not output.is_relative_to((ROOT / ".local").resolve()) or output.exists():
        raise ValueError("Finalizer requires a new private .local manifest")
    plan_path = LOCAL / name / "plan.json"
    plan, plan_id = checked(plan_path)
    progress = {}
    for task in plan["tasks"]:
        path = LOCAL / name / "progress" / (task["id"] + ".json")
        if not path.exists():
            raise ValueError("Component pilot batch is not terminal; no partial scoring")
        item, _ = checked(path)
        if item.get("status") not in TERMINAL or item.get("plan_sha256") != plan_id["sha256"]:
            raise ValueError("Component pilot batch is nonterminal or belongs to another plan")
        if item.get("output_sha256") and digest(task["output"]) != item["output_sha256"]:
            raise ValueError("Persisted component output changed")
        progress[task["id"]] = item
    for path, expected in plan["source_sha256"].items():
        if digest(path) != expected:
            raise ValueError("Running pilot frozen source identity changed")
    clips = {clip["id"]: clip for clip in plan["clips"]}
    for task in plan["tasks"]:
        if task["stage"] == "separation" and progress[task["id"]]["status"] == "completed":
            downstream = next(child for child in plan["tasks"] if child.get("depends_on") == task["id"])
            verify_separation(downstream, clips[task["clip"]], task["output"])
    staging = output.with_name(output.stem + "-builder-staging.json")
    if staging.exists():
        raise FileExistsError("Immutable builder staging already exists; choose a new final manifest identity")
    frozen_builder.build(name, staging)
    original, staging_id = checked(staging)
    final = copy.deepcopy(original)
    historical, historical_id = checked(ROOT / ".local/round2/progress.json")
    historical = historical["tasks"]
    audit = []
    for config in final["configurations"]:
        config["configuration_id"] = config["id"]
        route = config["model_metadata"]["base"]
        enhanced = config["id"].endswith("-vocals")
        for run in config["runs"]:
            clip = clips[run["clip_id"]]
            stage_clip = {**clip, "audio_sha256": run.get("input_audio_sha256", clip["audio_sha256"])}
            prior_verified = run.get("execution_verified", False)
            identities = []
            if enhanced:
                task = next(task for task in plan["tasks"] if task["clip"] == clip["id"] and task["stage"] == route)
                item = progress[task["id"]]
                result = read(task["output"]) if Path(task["output"]).exists() else None
                harness_path = ROOT / ".local/results" / task["id"] / "manifest.json"
                harness, identity = checked(harness_path, item.get("harness_sha256")) if harness_path.exists() else ({}, {})
                if identity:
                    identities.append(identity)
            else:
                result, harness, identities = _require_entry(historical[f"{clip['id']}-{route}"], clip)
            if run["status"] in {"completed", "execution_unverified"}:
                if not harness_complete(harness):
                    raise ValueError("Completed component harness not verified")
                input_identity(result, harness, stage_clip)
                if route == "x0":
                    validate_ctc_evidence(result)
                    if enhanced:
                        _, source_ids = _fresh_qwen(result, harness, stage_clip, alignment_required=True)
                    else:
                        source_ok, source_info, source_paths = upstream_evidence(result)
                        original_entry = historical[f"{clip['id']}-q0"]
                        asr, asr_harness, source_ids = _require_entry(original_entry, clip)
                        if (not source_ok or asr["text"] != result["text"]
                                or source_info.get("source_result_sha256") != original_entry["output_sha256"]
                                or Path(source_info.get("source_result", "")).resolve() != Path(original_entry["output"]).resolve()
                                or not qwen_asr_phase_complete(asr, asr_harness, expected_audio_sha256=clip["audio_sha256"],
                                    expected_offset=clip["offset"], expected_duration=clip["duration"])):
                            raise ValueError("Historical X0 original complete Q0 ASR source invalid")
                        source_ids.extend({"path": str(path), "sha256": digest(path)} for path in source_paths)
                    identities.extend(source_ids)
                else:
                    source_ok, _, source_paths = upstream_evidence(result)
                    if not gpu_verified(result, harness) or not source_ok:
                        raise ValueError("Completed Whisper ASR/VAD/CTC GPU evidence invalid")
                    if route == "w1":
                        validate_ctc_evidence(result)
                    identities.extend({"path": str(path), "sha256": digest(path)} for path in source_paths)
                run.update(status="completed", execution_verified=True)
            elif result and result.get("schema_version") != 1:
                identities.append({"path": run["result_path"], "sha256": run["result_sha256"]})
                if route == "x0" and enhanced:
                    try:
                        asr, source_ids = _fresh_qwen(result, harness, stage_clip, alignment_required=False)
                    except (KeyError, FileNotFoundError, ValueError):
                        asr = None
                    if asr is not None:
                        preserved = output.parent / "preserved-asr" / (run["run_id"] + ".json")
                        write_new(preserved, {"schema_version": 1, "text": asr["text"], "units": [], "cues": [],
                            "input_sha256": stage_clip["audio_sha256"], "source_start_seconds": clip["offset"], "duration_seconds": clip["duration"]})
                        run.update(status="alignment_failed", execution_verified=False, result_path=str(preserved), result_sha256=digest(preserved))
                        identities.extend(source_ids)
                    else:
                        run.pop("result_path", None)
                        run.pop("result_sha256", None)
                else:
                    run.pop("result_path", None)
                    run.pop("result_sha256", None)
            run.setdefault("evidence", {})["finalizer_artifacts"] = identities
            audit.append({"configuration_id": config["configuration_id"], "clip_id": clip["id"],
                "builder_execution_verified": prior_verified, "final_execution_verified": run.get("execution_verified", False),
                "final_status": run["status"], "artifacts": identities})
    final["finalization"] = {"revision": REVISION,
        "reason": "Frozen builder omitted evaluator-required configuration_id and used incomplete upstream GPU qualification; independent source-chain audit preserves original artifacts",
        "failure_handling": "Status/error-only failed artifacts remain diagnostic evidence; only independently complete ASR may be preserved for alignment failure",
        "plan": plan_id, "builder_staging": staging_id, "historical_progress": historical_id,
        "finalizer_source": {"path": str(Path(__file__).resolve()), "sha256": digest(Path(__file__))}, "run_audit": audit}
    final["source_sha256"][str(Path(__file__).resolve())] = digest(Path(__file__))
    write_new(output, final)
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = finalize(args.name, args.output)
    print({"revision": REVISION, "configurations": len(value["configurations"]), "output": str(args.output.resolve())})
