"""Aggregate a frozen scene registry; never discover only successful outputs."""

import copy
import hashlib
import itertools
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from kototoki_eval import evaluate, micro_summary
from kototoki_eval.scoring import REFERENCE_KINDS, RULE_VERSION, THRESHOLDS, distribution, quantile
from kototoki_eval.schema import normalize

ANALYSIS_VERSION = "frozen-scene-registry-v1"
BOOTSTRAP_SEED = 20261004
BOOTSTRAP_REPLICATES = 2000
RUN_STATUSES = {"completed", "invocation_failed", "alignment_failed", "execution_unverified", "missing"}


def _read_identity(path: Path, expected: str | None, *, required: bool) -> tuple[dict[str, Any], str]:
    data = path.read_bytes()
    identity = hashlib.sha256(data).hexdigest()
    if required and not expected:
        raise ValueError(f"Frozen identity missing for {path}")
    if expected and identity != expected.lower():
        raise ValueError(f"Frozen SHA256 mismatch for {path}")
    return json.loads(data.decode("utf-8-sig")), identity


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _empty_result(reference: dict[str, Any], execution_status: str) -> dict[str, Any]:
    result = evaluate(reference, {"schema_version": 1, "text": "", "units": [], "cues": []})
    if execution_status == "alignment_failed":
        raise ValueError("Alignment failure requires preserved text counts or transcript")
    return result


def _validate_result(reference: dict[str, Any], result: dict[str, Any]) -> None:
    if result.get("schema_version") != 1 or result.get("rule_version") != RULE_VERSION:
        raise ValueError("Evaluation schema/rule identity does not match this analysis round")
    if result.get("reference_kind") != reference["reference_kind"]:
        raise ValueError("Never mix SRT display and human acoustic evaluations")
    expected_chars = len(normalize("".join(span["text"] for span in reference["spans"])).text)
    if result["text"]["reference_characters"] != expected_chars:
        raise ValueError("Result text denominator differs from frozen reference")
    expected_ids = [span["id"] for span in reference["spans"]]
    if [span["id"] for span in result["spans"]] != expected_ids:
        raise ValueError("Result reference spans differ from frozen full scene")
    for field in ("reference_characters", "candidate_characters", "S", "D", "I", "silence_hallucination_characters"):
        value = result["text"][field]
        if not isinstance(value, int) or value < 0:
            raise ValueError("Text counts must be nonnegative integers")
    counts = result["text"]
    if (counts["S"] + counts["D"] > counts["reference_characters"]
            or counts["reference_characters"] - counts["D"] + counts["I"] != counts["candidate_characters"]):
        raise ValueError("Inconsistent full-text edit accounting")
    metadata = result.get("reference_metadata", {})
    if (metadata.get("corpus_revision") and reference.get("corpus_revision")
            and metadata["corpus_revision"] != reference["corpus_revision"]):
        raise ValueError("Evaluation references another corpus revision")
    for row in result["spans"]:
        if row["status"] == "measurable":
            values = [row[key] for key in ("start_error", "end_error", "error")]
            bounds = row["error_interval"]
            if (not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values + bounds)
                    or not 0 <= bounds[0] <= row["error"] <= bounds[1]
                    or not math.isclose(row["error"], max(abs(row["start_error"]), abs(row["end_error"])))):
                raise ValueError("Malformed measurable timing evidence")


def _scene_record(scene_id: str, run: dict[str, Any], reference: dict[str, Any],
                  result: dict[str, Any], artifacts: list[dict[str, str]]) -> dict[str, Any]:
    status = run["status"]
    _validate_result(reference, result)
    rows = []
    for row in result["spans"]:
        # Preserve only IDs, counts and numeric scoring evidence, never raw text,
        # candidate character maps or paths embedded by an untrusted backend.
        item = {key: value for key, value in row.items() if key in {
            "id", "status", "characters", "recognized_characters", "exact_characters",
            "boundary_complete", "start_error", "end_error", "error", "error_interval",
            "unresolved_possible_thresholds", "unresolved_may_be_complete"}}
        if item["status"] != "empty_reference" and status in {"invocation_failed", "missing", "alignment_failed"}:
            item["status"] = {"invocation_failed": "invocation_failure",
                              "missing": "missing_run", "alignment_failed": "alignment_failure"}[status]
            for key in ("start_error", "end_error", "error", "error_interval", "unresolved_possible_thresholds"):
                item.pop(key, None)
            if status in {"invocation_failed", "missing"}:
                item.update(recognized_characters=0, exact_characters=0, boundary_complete=False)
        rows.append(item)
    partial_text = copy.deepcopy(result["text"]) if status in {"invocation_failed", "missing"} else None
    if status in {"invocation_failed", "missing"}:
        # A failed invocation never substitutes partial output for the scheduled
        # complete run. Preserve partial counts separately for diagnosis.
        result = _empty_result(reference, status)
    return {"scene_id": scene_id, "run_id": run["run_id"], "execution_status": status,
            "execution_verified": run.get("execution_verified", False) and status == "completed",
            "failure_reason": run.get("failure_reason"), "artifacts": artifacts,
            "text": copy.deepcopy(result["text"]), "partial_output_text_counts": partial_text, "spans": rows,
            "reference_kind": reference["reference_kind"], "rule_version": result["rule_version"],
            "reference_scope": {key: reference[key] for key in (
                "corpus_revision", "scope", "acoustic_ground_truth", "reference_sha256",
                "boundary_warning", "scene_warning", "boundary_policy") if key in reference}}


def _numeric_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    text = micro_summary(records)
    rows = [row for record in records for row in record["spans"]]
    eligible = [row for row in rows if row["status"] != "empty_reference"]
    measured = [row for row in eligible if row["status"] == "measurable"]
    n = len(eligible)
    timing: dict[str, Any] = {
        "denominator": n, "measurable_count": len(measured),
        "measurable_coverage": len(measured) / n if n else None,
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "boundary_complete_count": sum(row.get("boundary_complete", False) for row in eligible),
        "recognized_character_coverage": sum(row.get("recognized_characters", 0) for row in eligible) / text["reference_characters"]
        if text["reference_characters"] else None,
        "exact_character_coverage": sum(row.get("exact_characters", 0) for row in eligible) / text["reference_characters"]
        if text["reference_characters"] else None,
        "start_signed_median": statistics.median(row["start_error"] for row in measured) if measured else None,
        "end_signed_median": statistics.median(row["end_error"] for row in measured) if measured else None,
        "start_absolute": distribution([abs(row["start_error"]) for row in measured]),
        "end_absolute": distribution([abs(row["end_error"]) for row in measured]),
        "error": distribution([row["error"] for row in measured]),
        "joint_completeness_timing": distribution([row["error"] if row["status"] == "measurable" else math.inf
                                                   for row in eligible]),
        "over_threshold_counts": {str(t): sum(row["error"] > t for row in measured) for t in THRESHOLDS},
        "success": {},
    }
    timing["joint_completeness_timing"]["nonfinite_count"] = n - len(measured)
    for threshold in THRESHOLDS:
        success = sum(row["error_interval"][1] < threshold for row in measured)
        uncertain = sum(row["error_interval"][0] < threshold <= row["error_interval"][1] for row in measured)
        uncertain += sum(row["status"] == "matching_ambiguity" and threshold in row.get("unresolved_possible_thresholds", [])
                         for row in eligible)
        timing["success"][str(threshold)] = {
            "success_count": success, "unresolved_count": uncertain,
            "lower": success / n if n else None, "upper": (success + uncertain) / n if n else None}
    return {"text": text, "timing": timing,
            "execution_status_counts": dict(Counter(record["execution_status"] for record in records)),
            "invocation_failure_count": sum(record["execution_status"] == "invocation_failed" for record in records),
            "missing_run_count": sum(record["execution_status"] == "missing" for record in records),
            "alignment_failure_count": sum(record["execution_status"] == "alignment_failed" for record in records),
            "execution_unverified_count": sum(not record["execution_verified"] for record in records),
            "all_execution_verified": bool(records) and all(record["execution_verified"] for record in records)}


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None or not math.isfinite(left) or not math.isfinite(right):
        return None
    return left - right


def _pair_summary(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rows = {(record["scene_id"], row["id"]): row for record in left["scene_records"] for row in record["spans"]}
    right_rows = {(record["scene_id"], row["id"]): row for record in right["scene_records"] for row in record["spans"]}
    common = sorted(key for key in left_rows if left_rows[key]["status"] == "measurable"
                    and right_rows[key]["status"] == "measurable")
    differences = [left_rows[key]["error"] - right_rows[key]["error"] for key in common]
    left_common = [left_rows[key]["error"] for key in common]
    right_common = [right_rows[key]["error"] for key in common]
    scene_pairs = []
    for lscene, rscene in zip(left["scene_records"], right["scene_records"]):
        if lscene["scene_id"] != rscene["scene_id"]:
            raise ValueError("Pair scene registry differs")
        lsum, rsum = _numeric_summary([lscene]), _numeric_summary([rscene])
        scene_pairs.append({"scene_id": lscene["scene_id"],
                            "left_execution": lscene["execution_status"], "right_execution": rscene["execution_status"],
                            "CER_difference_left_minus_right": _difference(lsum["text"]["CER"], rsum["text"]["CER"]),
                            "measurable_coverage_difference": _difference(lsum["timing"]["measurable_coverage"], rsum["timing"]["measurable_coverage"]),
                            "joint_p95_difference": _difference(lsum["timing"]["joint_completeness_timing"]["p95"], rsum["timing"]["joint_completeness_timing"]["p95"]),
                            "common_valid_count": sum(key[0] == lscene["scene_id"] for key in common)})
    return {"left": left["route_id"], "right": right["route_id"],
            "direction": "left-minus-right; smaller error/CER is favorable to left, larger coverage favorable to left",
            "common_valid_count": len(common), "full_denominator": left["summary"]["timing"]["denominator"],
            "left_full_coverage": left["summary"]["timing"]["measurable_coverage"],
            "right_full_coverage": right["summary"]["timing"]["measurable_coverage"],
            "common_valid_left_error": distribution(left_common), "common_valid_right_error": distribution(right_common),
            "paired_error_difference": distribution(differences),
            "common_p95_difference": _difference(quantile(left_common, .95), quantile(right_common, .95)),
            "paired_spans": [{"scene_id": scene, "span_id": span,
                              "error_difference": left_rows[(scene, span)]["error"] - right_rows[(scene, span)]["error"],
                              "start_error_difference": left_rows[(scene, span)]["start_error"] - right_rows[(scene, span)]["start_error"],
                              "end_error_difference": left_rows[(scene, span)]["end_error"] - right_rows[(scene, span)]["end_error"]}
                             for scene, span in common], "per_scene": scene_pairs}


def _bootstrap(left: dict[str, Any], right: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    scenes = len(left["scene_records"])
    if not enabled or scenes < 10:
        return {"status": "not_run", "reason": "not_requested" if not enabled else "fewer_than_10_fixed_scenes",
                "scene_count": scenes}
    rng = random.Random(BOOTSTRAP_SEED)
    values: dict[str, list[float]] = {"CER": [], "coverage": [], "joint_p95": [], "success_0.5": []}
    nonfinite = Counter()
    for _ in range(BOOTSTRAP_REPLICATES):
        indices = [rng.randrange(scenes) for _ in range(scenes)]
        lsum = _numeric_summary([left["scene_records"][i] for i in indices])
        rsum = _numeric_summary([right["scene_records"][i] for i in indices])
        pairs = {"CER": (lsum["text"]["CER"], rsum["text"]["CER"]),
                 "coverage": (lsum["timing"]["measurable_coverage"], rsum["timing"]["measurable_coverage"]),
                 "joint_p95": (lsum["timing"]["joint_completeness_timing"]["p95"], rsum["timing"]["joint_completeness_timing"]["p95"]),
                 "success_0.5": (lsum["timing"]["success"]["0.5"]["lower"], rsum["timing"]["success"]["0.5"]["lower"])}
        for metric, (lv, rv) in pairs.items():
            difference = _difference(lv, rv)
            if difference is None:
                nonfinite[metric] += 1
            else:
                values[metric].append(difference)
    return {"status": "descriptive_only", "unit": "paired_fixed_scene", "scene_count": scenes,
            "seed": BOOTSTRAP_SEED, "replicates": BOOTSTRAP_REPLICATES,
            "metrics": {key: {"finite_replicates": len(value), "nonfinite_replicates": nonfinite[key],
                              "nonfinite_fraction": nonfinite[key] / BOOTSTRAP_REPLICATES,
                              "finite_conditional_percentile_interval_95": [quantile(value, .025), quantile(value, .975)]
                              if value else None} for key, value in values.items()},
            "limitation": "Scenes from one film may remain dependent. Finite-only intervals are conditional and do not establish independent tails or generalization."}


def aggregate_manifest(manifest: dict[str, Any], *, base: Path, bootstrap: bool = False) -> dict[str, Any]:
    """Consume only a declared frozen registry; all absent routes/scenes stay visible."""
    if manifest.get("schema_version") != 1 or manifest.get("frozen") is not True or not manifest.get("manifest_id"):
        raise ValueError("Analysis requires schema_version=1, frozen=true and manifest_id")
    if manifest.get("reference_kind") not in REFERENCE_KINDS:
        raise ValueError("Manifest must declare one reference kind")
    strict = manifest.get("strict_hashes", True)
    scenes: dict[str, tuple[dict[str, Any], dict[str, str]]] = {}
    for entry in manifest["scenes"]:
        scene_id = entry["id"]
        if scene_id in scenes:
            raise ValueError("Duplicate scene IDs")
        path = _resolve(base, entry["reference_path"])
        reference, digest = _read_identity(path, entry.get("reference_sha256"), required=strict)
        if reference["reference_kind"] != manifest["reference_kind"]:
            raise ValueError("Reference kind differs from frozen registry")
        scenes[scene_id] = (reference, {"path": str(path), "sha256": digest})
    routes = []
    route_ids = set()
    for route in manifest["routes"]:
        if route["id"] in route_ids or not route.get("configuration_id"):
            raise ValueError("Routes require unique IDs and frozen configuration_id")
        route_ids.add(route["id"])
        runs = {}
        for run in route["runs"]:
            if run["scene_id"] not in scenes or run["scene_id"] in runs or run["status"] not in RUN_STATUSES:
                raise ValueError("Invalid/duplicate run scene or execution status")
            runs[run["scene_id"]] = run
        records = []
        for scene_id, (reference, identity) in scenes.items():
            run = copy.deepcopy(runs.get(scene_id, {"scene_id": scene_id, "run_id": "not-scheduled",
                                                   "status": "missing", "failure_reason": "missing_frozen_run_slot"}))
            artifacts = [{"role": "reference", **identity}]
            result = None
            if run.get("evaluation_path"):
                path = _resolve(base, run["evaluation_path"])
                if path.is_file():
                    result, digest = _read_identity(path, run.get("evaluation_sha256"), required=strict)
                    artifacts.append({"role": "evaluation", "path": str(path), "sha256": digest})
            if result is None and run.get("transcript_path"):
                path = _resolve(base, run["transcript_path"])
                if path.is_file():
                    transcript, digest = _read_identity(path, run.get("transcript_sha256"), required=strict)
                    artifacts.append({"role": "transcript", "path": str(path), "sha256": digest})
                    result = evaluate(reference, transcript)
            if result is None:
                if run["status"] == "alignment_failed":
                    raise ValueError("Alignment failure cannot discard existing recognized text; provide transcript/counts")
                if run["status"] in {"completed", "execution_unverified"}:
                    run.update(status="missing", failure_reason="declared_output_artifact_missing")
                result = _empty_result(reference, run["status"])
            records.append(_scene_record(scene_id, run, reference, result, artifacts))
        routes.append({"route_id": route["id"], "configuration_id": route["configuration_id"],
                       "model_metadata": route.get("model_metadata", {}), "scene_records": records,
                       "summary": _numeric_summary(records)})
    pairs = []
    for left, right in itertools.combinations(routes, 2):
        comparison = _pair_summary(left, right)
        comparison["paired_scene_bootstrap"] = _bootstrap(left, right, enabled=bootstrap)
        pairs.append(comparison)
    table = [{"route_id": route["route_id"], "configuration_id": route["configuration_id"],
              "reference_characters": route["summary"]["text"]["reference_characters"],
              "S": route["summary"]["text"]["S"], "D": route["summary"]["text"]["D"], "I": route["summary"]["text"]["I"],
              "CER": route["summary"]["text"]["CER"], "timing_N": route["summary"]["timing"]["denominator"],
              "measurable_n": route["summary"]["timing"]["measurable_count"],
              "measurable_coverage": route["summary"]["timing"]["measurable_coverage"],
              "conditional_p95_seconds": route["summary"]["timing"]["error"]["p95"],
              "conditional_p99_seconds": route["summary"]["timing"]["error"]["p99"],
              "success_0.5_lower": route["summary"]["timing"]["success"]["0.5"]["lower"],
              "success_0.5_upper": route["summary"]["timing"]["success"]["0.5"]["upper"],
              "invocation_failures": route["summary"]["invocation_failure_count"],
              "missing_runs": route["summary"]["missing_run_count"],
              "execution_unverified": route["summary"]["execution_unverified_count"],
              "all_execution_verified": route["summary"]["all_execution_verified"]} for route in routes]
    return {"schema_version": 1, "analysis_version": ANALYSIS_VERSION, "rule_version": RULE_VERSION,
            "manifest_id": manifest["manifest_id"], "reference_kind": manifest["reference_kind"],
            "evaluation_config": manifest.get("evaluation_config", {"status": "exploratory"}),
            "ranking": "not_performed", "promotion": "not_performed",
            "scene_count": len(scenes), "routes": routes, "comparisons": pairs, "table_rows": table,
            "frozen_hashes_required": strict,
            "limitations": ["Descriptive comparison does not approve a route or freeze selection criteria",
                            "Execution/GPU eligibility is separate from output scoring",
                            "Fixed-scene scores do not replace full-film continuity checks",
                            "One-film scene dependence and unreviewed SRT boundaries limit statistical interpretation",
                            "Imported evaluations bind file SHA256, corpus revision, span IDs and character denominator; identical-length reference rewrites require provenance review or reevaluation from transcripts"]}
