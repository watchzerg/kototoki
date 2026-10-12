"""Separate sensitivity analysis of one post-lock adapter guard repair."""

import argparse
import copy
from pathlib import Path

from kototoki_eval import evaluate

from .aggregate import aggregate_manifest
from .build_development import ROOT, digest, gpu_verified, proof, read, write
from .build_validation import upstream_evidence


def build(output: Path) -> None:
    output = output.resolve()
    allowed = (ROOT / ".local/analysis/heldout").resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError("Recovery output must be a new private held-out analysis directory")
    baseline = ROOT / ".local/analysis/heldout/cpu-v2-r1"
    original_registry = read(baseline / "source-registry.json")
    manifest = read(baseline / "main-manifest.json")
    original_id, recovery_id = "h1-q1-ch20-r1", "h2-q1-ch20-nonlexical-r1"
    old_path = ROOT / ".local/results" / original_id / "result.json"
    new_path = ROOT / ".local/results" / recovery_id / "result.json"
    harness_path = new_path.parent / "manifest.json"
    captured = next(run for run in original_registry["runs"] if run["run_id"] == original_id)
    expected = next(item["sha256"] for item in captured["artifacts"] if Path(item["path"]).name == "result.json")
    if digest(old_path) != expected:
        raise ValueError("Original failed result changed after capture")
    old, new, harness = read(old_path), read(new_path), read(harness_path)
    equality = {key: old[key] == new[key] for key in ("text", "units", "native", "cues")}
    if not all(equality.values()):
        raise ValueError("Guard-only recovery changed prediction content or intervals")
    if not gpu_verified(new, harness):
        raise ValueError("Fresh recovery FA execution is not verified")
    source_verified, upstream, source_files = upstream_evidence(new)
    if not source_verified:
        raise ValueError("Saved source ASR is not independently verified")
    scene = next(scene for scene in manifest["scenes"] if scene["id"] == "chapter-20")
    reference_path = Path(scene["reference_path"])
    if (digest(reference_path) != scene["reference_sha256"]
            or harness["audio_sha256"] != new["manifest"]["input_sha256"]
            or new["manifest"]["input_sha256"] != old["manifest"]["input_sha256"]):
        raise ValueError("Recovery reference or audio identity differs")
    output.mkdir(parents=True, exist_ok=False)
    source_paths = [baseline / "source-registry.json", baseline / "main-manifest.json", baseline / "main-report.json",
                    old_path, new_path, harness_path, reference_path, *source_files, Path(__file__)]
    write(output / "source-registry.json", {"schema_version": 1, "scope": "post-lock guard repair sensitivity; not new blind ranking",
        "original_run_id": original_id, "fresh_fa_run_id": recovery_id, "ASR_reused": True,
        "original_and_recovery_equal": equality,
        "files": [{"path": str(path), "sha256": digest(path)} for path in source_paths]})
    fa = new["manifest"]
    scoring = {**new, "source_start_seconds": fa["source_offset_s"], "duration_seconds": fa["asr_manifest"]["input"]["duration_s"]}
    score_path = output / "chapter-20-ref2-eval2.json"
    write(score_path, evaluate(read(reference_path), scoring))
    route = copy.deepcopy(next(route for route in manifest["routes"] if route["id"] == "Q1-no-vad"))
    route["id"] = "Q1-no-vad-nonlexical-guard-sensitivity"
    route["configuration_id"] += "-postlock-nonlexical-guard"
    route["model_metadata"] = {"scope": "15 original cached FA results plus 1 fresh repaired FA; same saved ASR"}
    record = next(run for run in route["runs"] if run["scene_id"] == "chapter-20")
    record.update(run_id=recovery_id, status="completed", execution_verified=True,
                  evaluation_path=str(score_path), evaluation_sha256=digest(score_path))
    record.pop("failure_reason", None)
    updated = {**manifest, "manifest_id": "heldout-q1-nonlexical-guard-postlock-sensitivity", "routes": [route],
               "evaluation_config": {**manifest["evaluation_config"], "status": "post-lock sensitivity; not blind or reselected"}}
    write(output / "main-manifest.json", updated)
    report = aggregate_manifest(updated, base=output, bootstrap=False)
    if report["routes"][0]["summary"]["timing"]["denominator"] != 620:
        raise ValueError("Recovery sensitivity lost the full denominator")
    report.update(scope="post-lock recovery sensitivity only", original_and_recovery_equal=equality,
                  source_reuse="15 original cached FA results + 1 fresh repaired FA; ASR unchanged",
                  adoption="not_performed", blind_heldout_comparison="original cpu-v2-r1 remains authoritative")
    write(output / "main-report.json", report)
    write(output / "execution-evidence.json", {"schema_version": 1, "recovery": proof(new, harness), "upstream": upstream})
    print(report["table_rows"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)
