"""Score a declared component ablation registry without changing frozen evaluators.

All paths in the manifest are relative to its directory unless absolute. Clips
use the round-two corpus schema. Each configuration declares run slots by
``clip_id`` with a standard complete transcript ``result_path`` and SHA256.
Statuses follow the existing analysis contract. Missing slots remain in every
denominator; only independently complete ASR output may be alignment_failed.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from kototoki_eval import evaluate
from kototoki_eval.__main__ import json_safe
from kototoki_eval.scoring import RULE_VERSION
from kototoki_eval.schema import normalize, validate_transcript

from experiments.analysis.aggregate import RUN_STATUSES, _numeric_summary, aggregate_manifest
from experiments.analysis.build_round2 import (
    POLICY, display_summary, edge_ids, edge_sensitivity, input_identity,
    normalize_clip, uncertain_edge_score,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_REVISION = "component-ablation-complete-text-edge-uncertainty-v1"
ABLATION_POLICY = {
    **POLICY, "revision": POLICY_REVISION,
    "scope": "exploratory component ablations on a declared complete registry; no blind or held-out claim",
    "bootstrap": "Paired fixed-window bootstrap in each reported scope only with at least ten windows",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def read_identity(path: Path, expected: str | None, *, strict: bool) -> tuple[dict[str, Any], dict[str, str]]:
    if strict and not expected:
        raise ValueError(f"Frozen SHA256 required: {path}")
    actual = digest(path)
    if expected and actual != expected.lower():
        raise ValueError(f"Artifact SHA256 mismatch: {path}")
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return document, {"path": str(path), "sha256": actual}


def write_new(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(json_safe(document), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _verify_file(base: Path, path: str, expected: str | None, *, strict: bool) -> dict[str, str]:
    target = resolve(base, path)
    if strict and not expected:
        raise ValueError(f"Frozen input/source SHA256 required: {target}")
    actual = digest(target)
    if expected and actual != expected.lower():
        raise ValueError(f"Input/source SHA256 mismatch: {target}")
    return {"path": str(target), "sha256": actual}


def _reports(analysis: dict[str, Any], clips: list[dict[str, Any]], references: dict[str, dict[str, Any]],
             *, base: Path, bootstrap: bool) -> dict[str, Any]:
    scopes = {"pooled": clips}
    scopes.update({film: [clip for clip in clips if clip["film"] == film]
                   for film in dict.fromkeys(clip["film"] for clip in clips)})
    reports: dict[str, Any] = {"films": {}}
    for scope, selected in scopes.items():
        subset = copy.deepcopy(analysis)
        ids = {clip["id"] for clip in selected}
        subset["scenes"] = [scene for scene in subset["scenes"] if scene["id"] in ids]
        for route in subset["routes"]:
            route["runs"] = [run for run in route["runs"] if run["scene_id"] in ids]
        report = aggregate_manifest(subset, base=base, bootstrap=bootstrap)
        crossing = {clip["id"]: edge_ids(clip, references[clip["id"]]) for clip in selected}
        k = sum(len(normalize(span["text"]).text) for clip in selected
                for span in references[clip["id"]]["spans"] if span["id"] in crossing[clip["id"]])
        for route in report["routes"]:
            route["edge_text_sensitivity"] = edge_sensitivity(route["summary"]["text"], k)
            interior = copy.deepcopy(route["scene_records"])
            for record in interior:
                record["spans"] = [row for row in record["spans"] if row["id"] not in crossing[record["scene_id"]]]
            timing = _numeric_summary(interior)["timing"]
            timing.pop("recognized_character_coverage", None)
            timing.pop("exact_character_coverage", None)
            route["interior_timing_only"] = timing
        report["edge_reference"] = {"crossing_cue_count": sum(len(value) for value in crossing.values()),
            "crossing_normalized_characters": k, "cue_ids_by_scene": {key: sorted(value) for key, value in crossing.items()},
            "no_certain_edge_successes": True}
        report["policy"] = ABLATION_POLICY
        report["limitations"].append("Component selection used these windows; results do not constitute independent confirmation. Crossing-cue CER sensitivity does not correct unreviewed acoustic/subtitle differences.")
        if scope == "pooled":
            reports["pooled"] = report
        else:
            reports["films"][scope] = report
    return reports


def build(manifest_path: Path, output: Path, *, bootstrap: bool = True) -> dict[str, Any]:
    """Write a new private snapshot; never discover successful runs from folders."""
    manifest_path, output = manifest_path.resolve(), output.resolve()
    allowed = (ROOT / ".local").resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("Component analysis requires a new private .local snapshot directory")
    manifest, manifest_identity = read_identity(manifest_path, None, strict=False)
    if manifest.get("schema_version") != 1 or manifest.get("frozen") is not True or not manifest.get("manifest_id"):
        raise ValueError("Manifest requires schema_version=1, frozen=true and manifest_id")
    strict = manifest.get("strict_hashes", True)
    if not isinstance(strict, bool):
        raise ValueError("strict_hashes must be boolean")
    base = manifest_path.parent
    clips = [normalize_clip(clip) for clip in manifest["clips"]]
    if not clips or len({clip["id"] for clip in clips}) != len(clips):
        raise ValueError("Clips must form a nonempty registry with unique IDs")
    references, scenes, input_checks = {}, [], []
    for clip in clips:
        if (not isinstance(clip["offset"], (int, float)) or isinstance(clip["offset"], bool)
                or not isinstance(clip["duration"], (int, float)) or isinstance(clip["duration"], bool)
                or not math.isfinite(clip["offset"]) or not math.isfinite(clip["duration"])
                or clip["offset"] < 0 or clip["duration"] <= 0):
            raise ValueError("Clips require finite source offset and positive duration")
        input_checks.append({"clip_id": clip["id"], "role": "source_audio",
            **_verify_file(base, clip["audio"], clip["audio_sha256"], strict=strict)})
        reference_path = resolve(base, clip["reference"])
        reference, identity = read_identity(reference_path, clip["reference_sha256"], strict=strict)
        references[clip["id"]] = reference
        scenes.append({"id": clip["id"], "reference_path": str(reference_path), "reference_sha256": identity["sha256"]})
    kinds = {reference["reference_kind"] for reference in references.values()}
    if len(kinds) != 1:
        raise ValueError("Reference kinds must not be mixed")
    source_checks = [{**_verify_file(base, path, expected, strict=strict)}
                     for path, expected in manifest.get("source_sha256", {}).items()]
    # Validate the complete registry before creating any output files.
    configurations = manifest["configurations"]
    if not configurations or len({item["id"] for item in configurations}) != len(configurations):
        raise ValueError("Configurations require nonempty unique IDs")
    for config in configurations:
        if not config.get("configuration_id"):
            raise ValueError("Each configuration requires configuration_id")
        runs = config.get("runs", [])
        if len({run["clip_id"] for run in runs}) != len(runs):
            raise ValueError("Duplicate run clip IDs")
        if any(run["clip_id"] not in references or run.get("status") not in RUN_STATUSES for run in runs):
            raise ValueError("Unknown run clip or unsupported execution status")
    output.mkdir(parents=True, exist_ok=False)
    routes, evidence = [], {}
    for config_index, config in enumerate(configurations):
        declared = {run["clip_id"]: run for run in config.get("runs", [])}
        records = []
        for clip_index, clip in enumerate(clips):
            run = copy.deepcopy(declared.get(clip["id"], {"status": "missing", "run_id": "not-scheduled",
                "failure_reason": "missing_frozen_run_slot"}))
            if not isinstance(run.get("execution_verified", False), bool):
                raise ValueError("execution_verified must be boolean")
            status = run["status"]
            identities = []
            document = None
            if run.get("result_path"):
                path = resolve(base, run["result_path"])
                if path.is_file():
                    document, identity = read_identity(path, run.get("result_sha256"), strict=strict)
                    identities.append({"role": "result", **identity})
                    validate_transcript(document)
                    input_path = run.get("input_audio_path", clip["audio"])
                    input_sha = run.get("input_audio_sha256", clip["audio_sha256"])
                    identities.append({"role": "inference_input", **_verify_file(base, input_path, input_sha, strict=strict)})
                    if status in {"completed", "execution_unverified", "alignment_failed"}:
                        stage_clip = {**clip, "audio_sha256": input_sha}
                        input_identity(document, {"audio_sha256": input_sha, "reference_unchanged": True}, stage_clip)
            if document is None:
                if status == "alignment_failed":
                    raise ValueError("Alignment failure requires independently complete ASR text in result_path")
                if status in {"completed", "execution_unverified"}:
                    status = "missing"
                    run["failure_reason"] = "declared_output_artifact_missing"
            elif status == "completed" and not run.get("execution_verified", False):
                status = "execution_unverified"
            scoring = document or {"schema_version": 1, "text": "", "units": [], "cues": []}
            if status == "alignment_failed":
                scoring = {**scoring, "units": [], "cues": []}
            score = uncertain_edge_score(evaluate(references[clip["id"]], scoring), edge_ids(clip, references[clip["id"]]))
            score_path = output / "scores" / f"config-{config_index:03d}-clip-{clip_index:03d}.json"
            write_new(score_path, score)
            records.append({"scene_id": clip["id"], "run_id": run.get("run_id", f"{config['id']}-{clip['id']}"),
                "status": status, "execution_verified": run.get("execution_verified", False) and status == "completed",
                "failure_reason": run.get("failure_reason"), "evaluation_path": str(score_path), "evaluation_sha256": digest(score_path)})
            evidence[f"{config_index}:{clip_index}"] = {"configuration_id": config["configuration_id"],
                "clip_id": clip["id"], "status": status, "execution_verified_declared": run.get("execution_verified", False),
                "artifacts": identities, "display": display_summary(scoring, clip),
                "display_scope": "Partial failed-run output is diagnostic only; primary scores retain failure accounting"}
        routes.append({"id": config["id"], "configuration_id": config["configuration_id"],
            "model_metadata": config.get("model_metadata", {}), "runs": records})
    analysis = {"schema_version": 1, "manifest_id": manifest["manifest_id"], "frozen": True,
        "strict_hashes": strict, "reference_kind": kinds.pop(), "scenes": scenes, "routes": routes,
        "evaluation_config": {"status": "exploratory_component_ablation", "rule_version": RULE_VERSION, **ABLATION_POLICY}}
    write_new(output / "analysis-manifest.json", analysis)
    report = _reports(analysis, clips, references, base=output, bootstrap=bootstrap)
    write_new(output / "report.json", report)
    write_new(output / "execution-evidence.json", {"schema_version": 1, "runs": evidence,
        "scope": "Declared execution eligibility is not independently certified by this CPU evaluator"})
    code_paths = [Path(__file__), ROOT / "experiments/analysis/aggregate.py", ROOT / "experiments/analysis/build_round2.py",
        ROOT / "experiments/display/replay.py", *sorted((ROOT / "kototoki_eval").glob("*.py"))]
    write_new(output / "source-registry.json", {"schema_version": 1, "manifest": manifest_identity,
        "input_checks": input_checks, "frozen_source_checks": source_checks,
        "analysis_source_sha256": {str(path): digest(path) for path in code_paths}, "policy": ABLATION_POLICY})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate complete component ablation registries privately")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-bootstrap", action="store_true")
    args = parser.parse_args()
    report = build(args.manifest, args.output, bootstrap=not args.no_bootstrap)
    print(json.dumps({"output": str(args.output.resolve()), "table_rows": report["pooled"]["table_rows"],
        "policy": POLICY_REVISION}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
