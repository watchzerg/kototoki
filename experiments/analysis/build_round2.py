"""Reevaluate five fixed configurations on two films without tuning or blind claims."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

from kototoki_eval import evaluate
from kototoki_eval.scoring import RULE_VERSION, THRESHOLDS
from kototoki_eval.schema import normalize, validate_transcript

from .aggregate import _numeric_summary, aggregate_manifest
from .build_development import ROOT, digest, gpu_verified, is_crisp, read, write
from .build_heldout import qwen_asr_phase_complete, qwen_decode_observations
from .build_validation import harness_complete, pipeline_complete, upstream_evidence
from experiments.display.replay import RULES as DISPLAY_RULES, replay

POLICY_REVISION = "round2-fixed-overlap-edge-uncertainty-v1"
POLICY = {
    "revision": POLICY_REVISION,
    "scope": "exploratory fixed-configuration comparison; no tuning, blind or held-out claim",
    "text": "Complete candidate text against all overlapping original SRT cues; no candidate cropping or deduplication",
    "edge_timing": "Crossing reference cues retain the denominator, are unresolved at all thresholds, and cannot be certain successes",
    "edge_text": "Conditional edit-distance sensitivity under deletion of at most all crossing-reference characters; not an acoustic accuracy guarantee",
    "interior": "Supplementary timing-only subset excludes predefined crossing cues; primary denominator remains intact",
    "bootstrap": "Pooled fixed windows only when at least ten; per-film six-window bootstrap disabled",
    "display": "Same existing minimal-display-v1 writer; report rendered/unrendered character counts and structural durations separately from timing",
}
STAGES = {
    "w0": "W0-no-context", "w1": "W1-normalized-forced", "q0": "Q0-window30",
    "q1": "Q1-no-vad", "x0": "X0-Q0-window30-normalized-forced",
}
CONFIGS = {
    "w0": "fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback",
    "w1": "wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda",
    "q0": "hf518-qwen17-fa06-cuda-bf16-sdpa-greedy-window30",
    "q1": "crisp0841-qwen17-fa06-f16-vulkan0-vad-off-fa-replay",
    "x0": "qwen17-hf518-window30-reused-officialnorm-torchaudio28-forced-cuda",
}
TERMINAL = {"completed", "failed", "blocked", "timeout", "harness_error", "missing"}


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def identity_json(path: Path, expected: str | None = None) -> dict[str, Any]:
    if expected and digest(path) != expected.lower():
        raise ValueError(f"Round2 artifact SHA256 mismatch: {path}")
    value = read(path)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def verify_frozen_sources(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Use immutable policy snapshots while retaining strict executable identity."""
    checks = []
    for name, expected in plan.get("source_sha256", {}).items():
        current = resolve(name)
        relative = current.relative_to(ROOT.resolve())
        snapshot = ROOT / ".local/round2/source" / relative
        snapshot_sha = digest(snapshot)
        if snapshot_sha != expected:
            raise ValueError("Frozen round2 source snapshot identity changed")
        current_sha = digest(current) if current.is_file() else None
        policy_document = relative.suffix.lower() == ".md"
        if not policy_document and current_sha != expected:
            raise ValueError("Frozen round2 executable/configuration identity changed")
        checks.append({"path": str(relative), "snapshot_path": str(snapshot),
                       "expected_frozen_sha256": expected, "snapshot_sha256": snapshot_sha,
                       "current_sha256": current_sha, "kind": "policy_document" if policy_document else "executable_or_configuration",
                       "status": "unchanged" if current_sha == expected else "current_document_updated" if current_sha else "current_document_missing",
                       "verification": "immutable_snapshot_matches; working prose may reflect later execution status" if policy_document else "current_and_snapshot_both_match"})
    return checks


def verify_source_assets(plan: dict[str, Any]) -> list[dict[str, str]]:
    """Rehash original media and subtitle files at final analysis time."""
    checks = []
    for name, expected in plan.get("source_asset_sha256", {}).items():
        path = resolve(name)
        actual = digest(path)
        if actual != expected:
            raise ValueError("Frozen round2 original source asset identity changed")
        checks.append({"path": str(path), "sha256": actual, "status": "matches_frozen_original"})
    return checks


def edge_ids(clip: dict[str, Any], reference: dict[str, Any]) -> set[str]:
    start, end = float(clip["offset"]), float(clip["offset"]) + float(clip["duration"])
    # Compute from frozen original display coordinates; never inspect candidates.
    return {span["id"] for span in reference["spans"] if span["start"] < start or span["end"] > end}


def uncertain_edge_score(score: dict[str, Any], crossing: set[str]) -> dict[str, Any]:
    result = copy.deepcopy(score)
    for row in result["spans"]:
        if row["id"] in crossing and row["status"] != "empty_reference":
            row.update(status="matching_ambiguity", boundary_complete=False,
                       unresolved_possible_thresholds=list(THRESHOLDS), unresolved_may_be_complete=True,
                       round2_uncertainty="reference_display_cue_crosses_input_edge")
            for key in ("error", "start_error", "end_error", "error_interval"):
                row.pop(key, None)
    result["unadjusted_core_timing"] = result["timing"]
    result["timing"] = _numeric_summary([{"text": result["text"], "spans": result["spans"],
        "execution_status": "completed", "execution_verified": False}])["timing"]
    return result


def edge_sensitivity(text_counts: dict[str, Any], crossing_characters: int) -> dict[str, Any]:
    reference = text_counts["reference_characters"]
    distance = sum(text_counts[key] for key in ("S", "D", "I"))
    k = min(crossing_characters, reference)
    return {"crossing_reference_characters": k, "reference_characters": reference,
            "edit_distance": distance, "edit_distance_lower": max(0, distance - k),
            "edit_distance_upper": distance + k,
            "conditional_CER_lower": max(0, distance - k) / reference if reference else None,
            "conditional_CER_upper": (distance + k) / (reference - k) if reference > k else None,
            "assumption": "Only up to K characters belonging to crossing reference cues may be absent from cropped audio; unreviewed speech/subtitle differences remain outside this envelope",
            "interpretation": "Sensitivity envelope, not corrected CER or a confidence interval; S/D/I attribution has no matching bound"}


def normalize_clip(clip: dict[str, Any]) -> dict[str, Any]:
    # Corpus uses explicit source coordinates; aliases permit legacy generic manifests.
    value = dict(clip)
    value["id"] = value.get("id", value.get("clip_id"))
    value["film"] = value.get("film", value.get("film_id"))
    value["offset"] = value.get("offset", value.get("source_start_seconds", value.get("source_start")))
    value["duration"] = value.get("duration", value.get("duration_seconds"))
    value["audio"] = value.get("audio", value.get("audio_path", value.get("wav")))
    value["audio_sha256"] = value.get("audio_sha256", value.get("wav_sha256"))
    value["reference"] = value.get("reference", value.get("reference_path"))
    if not all(value.get(key) is not None for key in ("id", "film", "offset", "duration", "audio", "audio_sha256", "reference", "reference_sha256")):
        raise ValueError("Corpus clip lacks frozen audio/reference identity or source mapping")
    return value


def artifact(entry: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    if not entry or not entry.get("id"):
        return None, None, []
    result_path = resolve(entry.get("output", f".local/results/{entry['id']}/result.json"))
    harness_path = resolve(entry.get("harness_manifest", result_path.parent / "manifest.json"))
    result = identity_json(result_path, entry.get("output_sha256")) if result_path.is_file() else None
    harness = identity_json(harness_path, entry.get("harness_manifest_sha256")) if harness_path.is_file() else None
    identities = [{"path": str(path), "sha256": digest(path)} for path in (result_path, harness_path) if path.is_file()]
    if entry.get("status") == "completed" and (result is None or harness is None):
        raise ValueError("Completed progress entry lacks result/harness")
    if entry.get("status") == "completed" and (not entry.get("output_sha256") or not entry.get("harness_manifest_sha256")):
        raise ValueError("Completed progress entry lacks persisted artifact hashes")
    return result, harness, identities


def input_identity(result: dict[str, Any], harness: dict[str, Any], clip: dict[str, Any]) -> None:
    if harness.get("audio_sha256") != clip["audio_sha256"] or not harness.get("reference_unchanged"):
        raise ValueError("Round2 harness input/reference integrity differs")
    info = result.get("input", {})
    manifest = result.get("manifest", {})
    actual = result.get("input_sha256", info.get("file_sha256", info.get("sha256", manifest.get("input_sha256", manifest.get("input", {}).get("sha256")))))
    if actual != clip["audio_sha256"]:
        raise ValueError("Round2 backend audio identity differs")
    offset = result.get("source_start_seconds", manifest.get("source_offset_s", manifest.get("config", {}).get("source_offset_s")))
    duration = result.get("duration_seconds", info.get("duration_s", info.get("duration", manifest.get("input", {}).get("duration_s", manifest.get("asr_manifest", {}).get("input", {}).get("duration_s")))))
    if not isinstance(offset, (int, float)) or not math.isclose(offset, clip["offset"], abs_tol=1e-7):
        raise ValueError("Round2 source offset differs")
    if not isinstance(duration, (int, float)) or not math.isclose(duration, clip["duration"], abs_tol=1e-7):
        raise ValueError("Round2 source duration differs")


def complete_asr(result: dict[str, Any] | None, harness: dict[str, Any] | None, clip: dict[str, Any], stage: str) -> bool:
    if not result or not harness:
        return False
    if stage == "q0":
        return qwen_asr_phase_complete(result, harness, expected_audio_sha256=clip["audio_sha256"],
                                      expected_offset=clip["offset"], expected_duration=clip["duration"])
    if stage == "q1asr":
        manifest = result.get("manifest", {})
        return bool(harness_complete(harness) and manifest.get("status") == "ok"
                    and manifest.get("route") == "crisp-qwen-f16-cli-asr-only"
                    and manifest.get("input", {}).get("sha256") == clip["audio_sha256"])
    return False


def display_summary(document: dict[str, Any], clip: dict[str, Any]) -> dict[str, Any]:
    _, sidecar = replay(document, source_start=clip["offset"], source_end=clip["offset"] + clip["duration"])
    summaries = {}
    for key in ("unified", "native", "native_writer"):
        facts = sidecar["diagnostics"][key]
        durations = facts["duration_seconds"]
        summaries[key] = {field: facts[field] for field in ("cue_count", "overlap_count_in_original_order", "nonmonotonic_start_count", "over_7_seconds_count", "over_42_characters_count")}
        summaries[key].update(invalid_cue_count=len(facts["invalid_cue_indices"]), under_0_5_seconds_count=sum(value < .5 for value in durations))
    return {"rules": DISPLAY_RULES, "coverage": sidecar["coverage"], "diagnostics": summaries,
            "scope": "Structural fixed-writer replay only; no listening or readability qualification"}


def derive_run(stage: str, clip: dict[str, Any], progress: dict[str, Any], reference: dict[str, Any],
               output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = progress.get(f"{clip['id']}-{stage}", {})
    result, harness, identities = artifact(entry)
    upstream, upstream_harness, upstream_files = None, None, []
    if stage in {"q1", "x0"}:
        upstream, upstream_harness, upstream_files = artifact(progress.get(f"{clip['id']}-{'q1asr' if stage == 'q1' else 'q0'}"))
    complete = bool(result and harness and pipeline_complete(result, harness))
    ctc_failure = any(item.get("failure") for item in (result or {}).get("experimental_alignment", {}).get("records", []))
    complete = complete and not ctc_failure
    if result and harness:
        if harness.get("audio_sha256") != clip["audio_sha256"] or not harness.get("reference_unchanged"):
            raise ValueError("Failed or complete invocation has changed source identity")
        if complete:
            input_identity(result, harness, clip)
        validate_transcript(result)
    verified, integrity_failure = False, None
    if complete:
        try:
            source_ok, _, _ = upstream_evidence(result)
            verified = gpu_verified(result, harness) and source_ok
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            integrity_failure = type(error).__name__
    retained_source = None
    if not complete:
        if stage == "w1" and ctc_failure and result and harness and harness_complete(harness):
            input_identity(result, harness, clip)
            retained_source = result
        elif stage == "q0" and complete_asr(result, harness, clip, "q0"):
            retained_source = result
        elif stage in {"x0", "q1"} and complete_asr(upstream, upstream_harness, clip, "q0" if stage == "x0" else "q1asr"):
            input_identity(upstream, upstream_harness, clip)
            retained_source = upstream
    scoring = result or {"schema_version": 1, "text": "", "units": [], "cues": []}
    status = "completed" if complete and verified else "execution_unverified" if complete else "invocation_failed" if harness else "missing"
    if retained_source is not None:
        # Keep complete native prediction text; never invent alignment times from input windows.
        scoring = {"schema_version": 1, "text": retained_source["text"], "units": [], "cues": []}
        status = "alignment_failed"
    run_id = entry.get("id", f"not-observed-{clip['id']}-{stage}")
    score = uncertain_edge_score(evaluate(reference, scoring), edge_ids(clip, reference))
    score_path = output / "scores" / f"{clip['id']}-{stage}.json"
    write(score_path, score)
    record = {"scene_id": clip["id"], "run_id": run_id, "status": status, "execution_verified": verified,
              "evaluation_path": str(score_path), "evaluation_sha256": digest(score_path)}
    if status not in {"completed", "execution_unverified"}:
        record["failure_reason"] = "complete_upstream_asr_preserved_dependent_alignment_failed" if retained_source is not None else "scheduled_invocation_unavailable_or_failed"
    source = upstream if stage == "x0" else result if stage == "q0" else None
    observations = qwen_decode_observations(source) if source else []
    manifest = (result or {}).get("manifest", {})
    evidence = {"run_id": run_id, "execution_status": status, "actual_gpu_verified": verified,
                "harness_status": (harness or {}).get("status"), "returncode": (harness or {}).get("returncode"),
                "harness_wall_seconds": (harness or {}).get("wall_seconds"), "artifacts": identities,
                "upstream_artifacts": upstream_files, "upstream_complete_text_retained": retained_source is not None,
                "upstream_integrity_failure": integrity_failure, "qwen_decode_observations": observations,
                "generation_cap_windows": sum(bool(item["token_limit_reached"]) for item in observations),
                "crisp_alignment_failure_count": len(manifest.get("failures", [])),
                "experimental_ctc_failure_count": sum(bool(item.get("failure")) for item in (result or {}).get("experimental_alignment", {}).get("records", [])),
                "source_sha256": (harness or {}).get("source_sha256", {}),
                "display": display_summary(scoring, clip),
                "scope": "Actual execution proof is separate from descriptive scores; no acoustic truth or eligibility from process exit alone"}
    return record, evidence


def aggregate_groups(manifest: dict[str, Any], clips: list[dict[str, Any]], references: dict[str, dict[str, Any]], *, base: Path) -> dict[str, Any]:
    reports = {"pooled": aggregate_manifest(manifest, base=base, bootstrap=True), "films": {}}
    for film in dict.fromkeys(clip["film"] for clip in clips):
        subset = copy.deepcopy(manifest)
        ids = {clip["id"] for clip in clips if clip["film"] == film}
        subset["scenes"] = [scene for scene in subset["scenes"] if scene["id"] in ids]
        for route in subset["routes"]:
            route["runs"] = [run for run in route["runs"] if run["scene_id"] in ids]
        reports["films"][film] = aggregate_manifest(subset, base=base, bootstrap=False)
    scopes = [(reports["pooled"], clips)] + [(reports["films"][film], [clip for clip in clips if clip["film"] == film]) for film in reports["films"]]
    for report, selected in scopes:
        crossing = {clip["id"]: edge_ids(clip, references[clip["id"]]) for clip in selected}
        k = sum(len(normalize(span["text"]).text) for clip in selected for span in references[clip["id"]]["spans"] if span["id"] in crossing[clip["id"]])
        for route in report["routes"]:
            route["edge_text_sensitivity"] = edge_sensitivity(route["summary"]["text"], k)
            interior = copy.deepcopy(route["scene_records"])
            for record in interior:
                record["spans"] = [row for row in record["spans"] if row["id"] not in crossing[record["scene_id"]]]
            timing = _numeric_summary(interior)["timing"]
            timing.pop("recognized_character_coverage", None)
            timing.pop("exact_character_coverage", None)
            route["interior_timing_only"] = timing
        report["edge_reference"] = {"crossing_cue_count": sum(len(ids) for ids in crossing.values()),
                                    "crossing_normalized_characters": k, "cue_ids_by_scene": {key: sorted(ids) for key, ids in crossing.items()},
                                    "no_certain_edge_successes": True}
        report["policy"] = POLICY
        report["limitations"].append("Crossing-cue text may be outside cropped audio; full-overlap CER and conditional edge sensitivity are descriptive. Display containment does not establish acoustic containment.")
    return reports


def build(corpus_path: Path, plan_path: Path, progress_path: Path, output: Path, *, batch_complete: bool = False) -> None:
    if not batch_complete:
        raise ValueError("Round2 final analysis requires parent-confirmed complete batch")
    allowed = (ROOT / ".local/analysis/round2").resolve()
    output = output.resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("Round2 analysis requires a new private snapshot directory")
    corpus, plan, progress_document = (identity_json(path) for path in (corpus_path, plan_path, progress_path))
    if progress_document.get("plan_sha256") != digest(plan_path):
        raise ValueError("Progress references a different frozen runner plan")
    clips = [normalize_clip(clip) for clip in corpus["clips"]]
    if len(clips) != 12 or len({clip["id"] for clip in clips}) != 12 or sorted([sum(item["film"] == film for item in clips) for film in {clip["film"] for clip in clips}]) != [6, 6]:
        raise ValueError("Round2 requires twelve fixed windows, six per film")
    if plan.get("corpus_sha256") and plan["corpus_sha256"] != digest(corpus_path):
        raise ValueError("Runner plan corpus freeze differs")
    if plan.get("clips") != corpus["clips"]:
        raise ValueError("Runner clip registry differs from corpus")
    planned = {(task["clip"], task["stage"]): task for task in plan["tasks"]}
    for clip in clips:
        for stage, configuration in STAGES.items():
            task = planned.get((clip["id"], stage))
            if task is None or task.get("configuration") != configuration:
                raise ValueError("Runner fixed configuration set differs")
    for item in plan.get("files", []):
        if digest(resolve(item["path"])) != item["sha256"]:
            raise ValueError("Frozen round2 implementation/configuration identity changed")
    frozen_source_checks = verify_frozen_sources(plan)
    for path, expected in plan.get("input_sha256", {}).items():
        if digest(resolve(path)) != expected:
            raise ValueError("Frozen round2 input identity changed")
    source_asset_checks = verify_source_assets(plan)
    progress = progress_document["tasks"]
    if any(entry.get("status") not in TERMINAL for entry in progress.values()):
        raise ValueError("Round2 batch still has nonterminal tasks")
    references, scenes = {}, []
    for clip in clips:
        if digest(resolve(clip["audio"])) != clip["audio_sha256"]:
            raise ValueError("Round2 frozen clip audio changed")
        path = resolve(clip["reference"])
        references[clip["id"]] = identity_json(path, clip["reference_sha256"])
        scenes.append({"id": clip["id"], "reference_path": str(path), "reference_sha256": clip["reference_sha256"]})
    output.mkdir(parents=True, exist_ok=False)
    routes, evidence = [], {}
    for stage, route_id in STAGES.items():
        runs = []
        for clip in clips:
            record, facts = derive_run(stage, clip, progress, references[clip["id"]], output)
            runs.append(record)
            evidence[f"{clip['id']}-{stage}"] = facts
        routes.append({"id": route_id, "configuration_id": CONFIGS[stage], "runs": runs})
    manifest = {"schema_version": 1, "manifest_id": POLICY_REVISION, "frozen": True, "reference_kind": "srt_display",
                "evaluation_config": {"status": "exploratory_fixed_configurations", "rule_version": RULE_VERSION, **POLICY},
                "scenes": scenes, "routes": routes}
    write(output / "main-manifest.json", manifest)
    reports = aggregate_groups(manifest, clips, references, base=output)
    write(output / "report.json", reports)
    write(output / "execution-evidence.json", {"schema_version": 1, "runs": evidence})
    write(output / "source-registry.json", {"policy": POLICY, "files": [{"path": str(path), "sha256": digest(path)} for path in (corpus_path, plan_path, progress_path)],
        "frozen_source_checks": frozen_source_checks, "original_source_asset_checks": source_asset_checks,
        "analysis_source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (Path(__file__), ROOT / "experiments/analysis/aggregate.py", *sorted((ROOT / "kototoki_eval").glob("*.py")))}})
    print(json.dumps({"output": str(output), "table_rows": reports["pooled"]["table_rows"], "policy": POLICY_REVISION}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-complete", action="store_true")
    args = parser.parse_args()
    build(args.corpus, args.plan, args.progress, args.output, batch_complete=args.batch_complete)
