"""Evaluate current demo runs against a complete frozen VAD study registry."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from kototoki_eval.schema import normalize, validate_transcript
from kototoki_eval.__main__ import json_safe
from experiments.components import evaluate as components
from experiments.analysis.build_heldout import repeated_unit_observation

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ROUTE_IDS = tuple(f"{family}-{vad}" for family in ("w0", "x0")
                           for vad in ("original", "pyannote-current", "silero", "fsmn", "firered"))
TERMINAL_STATUSES = {"completed", "partial", "alignment_failed", "invocation_failed",
                     "execution_unverified", "missing", "blocked", "failed", "timeout"}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return document


def seconds(value: Any) -> float | None:
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0):
        return None
    return float(value)


def costs(run: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """Distinguish measured process costs from a reconstructed serial sum."""
    process = seconds(run.get("process_wall_s"))
    vad = seconds(run.get("vad_process_wall_s", 0))
    return {"fresh_demo_process_wall_s": process, "shared_vad_process_wall_s": vad,
            "reconstructed_serial_wall_s": process + vad if process is not None and vad is not None else None,
            "reported_stages_s": {key: float(value) for key, value in (result or {}).get("stages", {}).items()
                                  if seconds(value) is not None},
            "process_costs": [{key: row.get(key) for key in ("stage", "wall_s", "exit_code")}
                              for row in (result or {}).get("process_costs", [])],
            "gpu_sampling": {key: run.get("process", {}).get(key) for key in (
                "sampled_gpu_total_used_peak_mib", "gpu_sample_count", "memory_scope")},
            "scope": "Demo process wall is measured; adding reused VAD preprocessing is reconstructed serial cost, not a separately measured live end-to-end run. Internal load/inference timers exclude process startup."}


def execution_proof(document: dict[str, Any]) -> dict[str, Any]:
    """Inspect persisted execution observations without certifying acoustic truth."""
    chunks = document.get("chunks", [])
    traces = document.get("asr_traces", [])
    parameters = document.get("effective_parameters", {})
    def cuda(value: Any) -> bool:
        return isinstance(value, str) and (value == "cuda" or value.startswith("cuda:"))
    qwen = any("asr_input_evidence" in row for row in traces)
    asr_ok = len(traces) == len(chunks) and bool(traces)
    if qwen:
        for trace in traces:
            evidence = trace.get("asr_input_evidence", {})
            observed = evidence.get("parameter_devices", []) + list(evidence.get("input_devices", {}).values())
            asr_ok = asr_ok and bool(observed) and all(cuda(value) for value in observed)
            asr_ok = asr_ok and cuda(evidence.get("output_device"))
    else:
        asr_ok = asr_ok and cuda(parameters.get("asr", {}).get("device"))
    records = document.get("alignment_records", [])
    measured = [row for row in records if "decoder_input_device" in row]
    alignment_ok = bool(measured) and cuda(parameters.get("alignment", {}).get("model"))
    for row in measured:
        alignment_ok = alignment_ok and all(cuda(value) for value in (
            row.get("model_output_device"), row.get("decoder_input_device"),
            row.get("decoder_output_device"), row.get("normalization", {}).get("actual_input_device")))
    failures = sum(bool(row.get("failure")) for row in records)
    caps = sum(row.get("token_limit_reached") is True for row in traces)
    cap_clear = not qwen or all(row.get("token_limit_reached") is False for row in traces)
    full_text = document.get("text") == "".join(row["text"] for row in document.get("original_segments", []))
    fresh = document.get("cached_inference") is False
    offline = document.get("offline_requested") is True
    empty_vad = not chunks and not document.get("text") and not traces and not records
    return {"asr_gpu_observed": bool(asr_ok), "alignment_gpu_observed": bool(alignment_ok),
            "asr_gpu_evidence_kind": "parameter_input_output_tensors" if qwen else "loaded_CTranslate2_device_metadata",
            "alignment_failure_count": failures, "token_cap_chunk_count": caps,
            "token_cap_clear": cap_clear,
            "complete_asr_text_preserved": full_text, "fresh_asr_alignment": fresh,
            "offline_requested": offline, "empty_vad_inference_skipped": empty_vad,
            "execution_observations_pass": bool((empty_vad or asr_ok and alignment_ok)
                                                and fresh and offline and full_text and not failures and cap_clear)}


def chunk_diagnostics(document: dict[str, Any]) -> dict[str, Any]:
    chunks = document.get("chunks", [])
    retained = sum((row["end_sample"] - row["start_sample"]) / 16000
                   if "start_sample" in row and "end_sample" in row else row["end"] - row["start"]
                   for row in chunks)
    vad = document.get("effective_parameters", {}).get("vad", {})
    vad = vad.get("origin_metadata", vad)
    if not vad:
        vad = document.get("vad_provenance", {}).get("metadata", {})
    raw = vad.get("raw_speech_duration_s", vad.get("speech_duration_s"))
    accounting = vad.get("accounting", {})
    raw_duration = sum(row["end_seconds"] - row["start_seconds"] for row in vad.get("raw_intervals", []))
    speech = seconds(accounting.get("speech_samples"))
    if speech is not None:
        raw = speech / 16000
    units = document.get("units", [])
    statuses = Counter(unit.get("status", "ok") for unit in units)
    character_statuses: Counter[str] = Counter()
    for unit in units:
        character_statuses[unit.get("status", "ok")] += unit["char_end"] - unit["char_start"]
    boundaries = []
    segments = document.get("original_segments", [])
    for index, (left, right) in enumerate(zip(segments, segments[1:])):
        before, after = normalize(left["text"]).text, normalize(right["text"]).text
        overlap = next((length for length in range(min(len(before), len(after)), 1, -1)
                        if before[-length:] == after[:length]), 0)
        if overlap:
            boundaries.append({"left_chunk_index": index, "right_chunk_index": index + 1,
                               "normalized_overlap_characters": overlap})
    return {"chunk_count": len(chunks), "source_window_retained_duration_s": retained,
            "raw_speech_duration_s": seconds(raw), "unit_status_counts": dict(statuses),
            "native_raw_interval_duration_sum_s": raw_duration if "raw_intervals" in vad else None,
            "vad_sample_accounting": accounting,
            "character_unit_status_counts": dict(character_statuses),
            "normalized_literal_repetition": repeated_unit_observation(normalize(document["text"]).text),
            "chunk_boundary_literal_repetition": boundaries,
            "scope": "Retained window duration includes merged internal gaps. Literal repetitions can be genuine speech; they are not automatic error labels. Song retention is not a false-positive penalty."}


def summary_row(route: dict[str, Any], scope: str) -> dict[str, Any]:
    summary = route["summary"]
    text, timing = summary["text"], summary["timing"]
    return {"scope": scope, "route_id": route["route_id"], "configuration_id": route["configuration_id"],
            **{key: text[key] for key in ("reference_characters", "candidate_characters", "S", "D", "I", "CER")},
            "timing_denominator": timing["denominator"], "measurable_count": timing["measurable_count"],
            "strict_half_second": timing["success"]["0.5"],
            "conditional_P95_s": timing["error"]["p95"], "conditional_max_s": timing["error"]["max"],
            "over_2_s": timing["over_threshold_counts"]["2.0"], "over_5_s": timing["over_threshold_counts"]["5.0"],
            "joint_completeness_timing_P95_s": timing["joint_completeness_timing"]["p95"],
            "status_counts": timing["status_counts"], "execution_status_counts": summary["execution_status_counts"]}


def source_consistency(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose mixed inference snapshots while retaining every score."""
    def executable_sources(row: dict[str, Any]) -> dict[str, dict[str, str]]:
        return {field: {name: value for name, value in (row.get(field) or {}).items()
                        if not Path(name.replace("\\", "/")).name.startswith("test_")}
                for field in ("source_sha256", "shared_source_sha256")}
    observed = [(row, executable_sources(row)) for row in runs if row.get("source_sha256")]
    baseline = observed[0][1] if observed else None
    mismatches = [{"clip_id": row["clip_id"], "run_id": row["run_id"]}
                  for row, sources in observed if sources != baseline]
    unique = {json.dumps(sources, sort_keys=True, separators=(",", ":")) for _, sources in observed}
    return {"status": "not_observed" if not observed else "heterogeneous" if mismatches else "consistent_in_observed_runs",
            "observed_run_count": len(observed), "source_evidence_missing_run_count": len(runs) - len(observed),
            "unique_inference_source_identity_count": len(unique),
            "all_registry_runs_observed": len(observed) == len(runs),
            "different_from_first_observed": mismatches,
            "scope": "Per-route persisted source_sha256 and shared_source_sha256; test_*.py entries excluded. A mismatch is reported and does not discard or rewrite scores."}


def evaluate_study(study_path: Path, output: Path, *, bootstrap: bool = True) -> dict[str, Any]:
    """Freeze source/input identities and score every declared terminal slot."""
    study_path, output = study_path.resolve(), output.resolve()
    if study_path.is_dir():
        study_path /= "study.json"
    private = (ROOT / ".local").resolve()
    if not study_path.is_relative_to(private) or not output.is_relative_to(private) or output == private or output.exists():
        raise ValueError("Study and new analysis output must be private .local paths")
    study = read(study_path)
    if study.get("schema_version") != 1 or not study.get("study_id") or study.get("terminal") is not True:
        raise ValueError("Study requires schema_version=1, study_id and terminal=true")
    plan_path = resolve(study.get("source_plan_path", ".local/round2/plan.json"))
    if not study.get("source_plan_sha256") or digest(plan_path) != study["source_plan_sha256"]:
        raise ValueError("Study source plan SHA256 differs")
    plan = read(plan_path)
    if study.get("clips") != plan["clips"]:
        raise ValueError("Study must retain the exact complete frozen source-plan clip registry")
    routes = study.get("routes", [])
    if not routes or len({route["id"] for route in routes}) != len(routes):
        raise ValueError("Study requires unique route IDs")
    expected_routes = study.get("expected_route_ids", list(EXPECTED_ROUTE_IDS))
    if [route["id"] for route in routes] != expected_routes:
        raise ValueError("Study routes differ from frozen expected route IDs")
    clip_ids = {clip["id"] for clip in study["clips"]}
    checks: dict[str, str] = {}
    for clip in study["clips"]:
        for field in ("audio", "reference", "source_audio", "source_srt"):
            if field not in clip:
                continue
            path = resolve(clip[field])
            actual = checks.setdefault(str(path), digest(path)) if str(path) not in checks else checks[str(path)]
            if not clip.get(field + "_sha256") or actual != clip[field + "_sha256"]:
                raise ValueError(f"Frozen {field} SHA256 differs: {clip['id']}")
    configurations, diagnostics = [], []
    result_checks: dict[str, str] = {}
    for route in routes:
        if not route.get("configuration_id"):
            raise ValueError("Each route requires configuration_id")
        declared = route.get("runs", [])
        if len({run["clip_id"] for run in declared}) != len(declared) or any(run["clip_id"] not in clip_ids for run in declared):
            raise ValueError("Duplicate or unknown run clip IDs")
        mapped = []
        by_clip = {run["clip_id"]: run for run in declared}
        for clip in study["clips"]:
            run = by_clip.get(clip["id"], {"clip_id": clip["id"], "run_id": "not-scheduled", "status": "missing"})
            status = run.get("status")
            if status not in TERMINAL_STATUSES:
                raise ValueError("All declared run slots must be terminal")
            if "execution_verified" in run and not isinstance(run["execution_verified"], bool):
                raise ValueError("execution_verified must be boolean")
            copied = copy.deepcopy(run)
            document, identity = None, None
            if run.get("result_path"):
                path = resolve(run["result_path"])
                copied["result_path"] = str(path)
                if path.is_file():
                    if not run.get("result_sha256") or digest(path) != run["result_sha256"]:
                        raise ValueError("Result SHA256 differs or is missing")
                    result_checks[str(path)] = run["result_sha256"]
                    document = read(path)
                    validate_transcript(document)
                    identity = {"path": str(path), "sha256": run["result_sha256"]}
            if status in {"partial", "alignment_failed"} and document is None:
                raise ValueError("Partial/alignment failure requires complete preserved ASR result")
            vad_identity = None
            if run.get("vad_manifest_path"):
                vad_path = resolve(run["vad_manifest_path"])
                vad_hash = digest(vad_path)
                if not run.get("vad_manifest_sha256") or vad_hash != run["vad_manifest_sha256"]:
                    raise ValueError("VAD manifest SHA256 differs or is missing")
                result_checks[str(vad_path)] = vad_hash
                vad_manifest = read(vad_path)
                if (vad_manifest.get("input", {}).get("file_sha256") != clip["audio_sha256"]
                        or vad_manifest.get("offset_s") != clip["offset"]):
                    raise ValueError("VAD manifest input identity differs")
                vad_identity = {"path": str(vad_path), "sha256": vad_hash, "metadata": vad_manifest.get("metadata"),
                                "stages": vad_manifest.get("stages"), "source_sha256": vad_manifest.get("source_sha256")}
                if document is not None:
                    provenance = document.get("vad_manifest_source", document.get("vad_provenance", {}))
                    if provenance.get("sha256") != vad_hash:
                        raise ValueError("Demo result does not bind declared VAD manifest")
            proof = execution_proof(document) if document else None
            if status == "partial" or document and document.get("status") == "partial":
                copied["status"], copied["execution_verified"] = "execution_unverified", False
            elif status in {"failed", "blocked", "timeout"}:
                copied["status"], copied["execution_verified"] = "invocation_failed", False
            elif status in {"completed", "execution_unverified"}:
                copied["execution_verified"] = bool(proof and proof["execution_observations_pass"]
                                                     and run.get("execution_verified", True))
            else:
                copied["execution_verified"] = False
            mapped.append(copied)
            diagnostics.append({"route_id": route["id"], "clip_id": run["clip_id"], "run_id": run.get("run_id"),
                                "declared_status": status, "analysis_status": copied["status"],
                                "execution_proof": proof, "result": identity,
                                "vad_manifest": vad_identity, "failure_path": run.get("failure_path"),
                                "failure_reason": run.get("failure_reason", run.get("reason")),
                                "result_status": document.get("status") if document else None,
                                "stage_execution": document.get("stage_execution") if document else None,
                                "costs": costs(run, document),
                                "transcription": chunk_diagnostics(document) if document else None,
                                "parameters": document.get("effective_parameters") if document else None,
                                "runtime_identity": document.get("runtime_identity") if document else None,
                                "source_sha256": document.get("source_sha256") if document else None,
                                "shared_source_sha256": document.get("shared_source_sha256") if document else None,
                                "asset_sha256": document.get("asset_sha256") if document else None,
                                "model_files_sha256": document.get("model_files_sha256") if document else None})
        configurations.append({"id": route["id"], "configuration_id": route["configuration_id"],
                               "model_metadata": route.get("model_metadata", {}), "runs": mapped})
    clips = [{**clip, **{field: str(resolve(clip[field])) for field in ("audio", "reference")}}
             for clip in study["clips"]]
    source_paths = [Path(__file__), ROOT / "experiments/components/evaluate.py",
                    ROOT / "experiments/analysis/aggregate.py", ROOT / "experiments/analysis/build_round2.py",
                    ROOT / "experiments/analysis/build_heldout.py", ROOT / "experiments/display/replay.py",
                    *sorted((ROOT / "kototoki_eval").glob("*.py"))]
    source_before = {str(path): digest(path) for path in source_paths}
    study_sha = digest(study_path)
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "component-manifest.json"
    components.write_new(manifest_path, {"schema_version": 1, "manifest_id": study["study_id"], "frozen": True,
                                        "strict_hashes": True, "clips": clips, "configurations": configurations})
    report = components.build(manifest_path, output / "scoring", bootstrap=bootstrap)
    rows = [summary_row(route, "pooled") for route in report["pooled"]["routes"]]
    rows.extend(summary_row(route, film) for film, group in report["films"].items() for route in group["routes"])
    total_costs, source_rows = [], []
    for route in routes:
        selected = [row for row in diagnostics if row["route_id"] == route["id"]]
        source_rows.append({"route_id": route["id"], **source_consistency(selected)})
        values = [row["costs"]["reconstructed_serial_wall_s"] for row in selected]
        complete = len(selected) == len(clips) and all(value is not None for value in values)
        total_costs.append({"route_id": route["id"], "declared_run_count": len(selected),
                            "complete_registry_cost_available": complete,
                            "reconstructed_serial_wall_s": sum(values) if complete else None,
                            "observed_process_wall_s_sum": sum(row["costs"]["fresh_demo_process_wall_s"] or 0 for row in selected),
                            "partial_run_count": sum(row["declared_status"] == "partial" or row["result_status"] == "partial"
                                                     or bool(row["execution_proof"] and row["execution_proof"]["alignment_failure_count"])
                                                     for row in selected)})
    for path, expected in {**checks, **result_checks, **source_before, str(study_path): study_sha,
                           str(plan_path): study["source_plan_sha256"]}.items():
        if digest(Path(path)) != expected:
            raise ValueError("Frozen evidence or evaluator source changed during scoring")
    final = {"schema_version": 1, "study_id": study["study_id"], "study_sha256": study_sha,
             "source_plan_sha256": study["source_plan_sha256"], "summary_rows": rows,
             "cost_rows": total_costs, "runtime_source_consistency": source_rows, "report": report,
             "limitations": ["These are previously exposed fixed movie windows, not new blind or held-out samples.",
                              "Blocked routes retain full-denominator failure-accounting placeholders; their CER/S/D/I are not measured quality and must be displayed as untested.",
                              "SRT text and display boundaries are reference proxies, not independently labelled acoustic truth.",
                              "Speech/dialogue is primary; retained singing is not penalized as a VAD false positive.",
                              "CER insertions and literal repetition observations are not automatic hallucination or song error counts.",
                              "Partial segment alignment retains complete text and valid remaining timing; execution remains incomplete.",
                              "Shared VAD cost plus fresh demo process cost is a reconstructed serial total."]}
    components.write_new(output / "report.json", final)
    components.write_new(output / "diagnostics.json", {"schema_version": 1, "runs": diagnostics})
    components.write_new(output / "identity.json", {"schema_version": 1, "study": {"path": str(study_path), "sha256": study_sha},
                         "input_sha256": checks, "result_sha256": result_checks, "evaluator_source_sha256": source_before})
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description="Score all terminal current-demo VAD comparison slots")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-bootstrap", action="store_true")
    args = parser.parse_args()
    report = evaluate_study(args.study, args.out, bootstrap=not args.no_bootstrap)
    print(json.dumps(json_safe({"study_id": report["study_id"], "output": str(args.out.resolve()),
                               "summary_rows": report["summary_rows"]}), ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
