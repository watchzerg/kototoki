"""Score two fixed whole-film runs with the unchanged evaluation core."""

import argparse
import json
from pathlib import Path

from kototoki_eval import evaluate
from kototoki_eval.scoring import RULE_VERSION

from .aggregate import aggregate_manifest
from .build_development import ROOT, digest, gpu_verified, proof, read, write
from .build_validation import experimental_proof, pipeline_complete

RUNS = (("W0-no-context", "f1-w0-full-r1", "fw121-ct2482-largev3-cuda-fp16-beam5-ctx-off-vad-off-temp-fallback"),
        ("W1-normalized-forced", "f1-w1norm-full-r1", "wx386-largev3-pyannote-native-officialnorm-torchaudio28-forced-cuda"))
INPUT_SHA256 = "bf0e59b0b89dadb72271c1feaf9bbd7d684fe6070d71b7ff06278ce8a59a85d1"


def build(output: Path) -> None:
    output = output.resolve()
    allowed = (ROOT / ".local/analysis/fullfilm").resolve()
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError("Whole-film output must be a new private analysis directory")
    freeze_path = ROOT / ".local/manifests/heldout-freeze-v1.json"
    freeze = read(freeze_path)
    if freeze["rule_version"] != RULE_VERSION:
        raise ValueError("Whole-film diagnostics must use the same evaluation rule")
    for item in freeze["files"]:
        path = Path(item["path"])
        path = path if path.is_absolute() else ROOT / path
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        if (relative.startswith("kototoki_eval/") or relative == "experiments/analysis/aggregate.py") and digest(path) != item["sha256"]:
            raise ValueError("Frozen evaluation core changed")
    reference_path = ROOT / ".local/references/scoring-v2/full.json"
    reference = read(reference_path)
    if len(reference["spans"]) != 1026 or reference.get("acoustic_ground_truth") is not False:
        raise ValueError("Expected the full SRT-relative 1026-span diagnostic")
    input_path = ROOT / ".local/audio/fatestay-full.wav"
    if digest(input_path) != INPUT_SHA256:
        raise ValueError("Whole-film audio identity changed")
    loaded, entries = {}, []
    for route, run_id, config in RUNS:
        result_path, harness_path = (ROOT / ".local/results" / run_id / name for name in ("result.json", "manifest.json"))
        result, harness = read(result_path), read(harness_path)
        if not pipeline_complete(result, harness) or not gpu_verified(result, harness):
            raise ValueError("Expected completed actual-GPU whole-film runs")
        if (result["input"]["file_sha256"] != INPUT_SHA256 or harness["audio_sha256"] != INPUT_SHA256
                or result["source_start_seconds"] != 0 or result["duration_seconds"] != 112448683 / 16000
                or harness["reference_sha256_before"].lower() != reference["reference_sha256"].lower()):
            raise ValueError("Whole-film source or reference identity differs")
        if not proof(result, harness)["offline_requested"]:
            raise ValueError("Whole-film inference did not request offline execution")
        options = result["effective_parameters"]
        if route.startswith("W0"):
            transcribe = options["transcribe"]
            if transcribe["condition_on_previous_text"] or transcribe["vad_filter"] or transcribe["beam_size"] != 5:
                raise ValueError("W0 configuration changed")
        elif not result.get("experimental_alignment") or not options.get("ctc_normalize") or options["batch_size"] != 1:
            raise ValueError("W1 normalized forced configuration changed")
        loaded[run_id] = (result, harness)
        entries.append({"route_id": route, "run_id": run_id, "configuration_id": config,
                        "files": [{"path": str(path), "sha256": digest(path)} for path in (result_path, harness_path)]})
    output.mkdir(parents=True, exist_ok=False)
    write(output / "source-registry.json", {"schema_version": 1, "scope": "whole-film diagnostic; same film, no additional independent sample",
        "rule_version": RULE_VERSION, "freeze_sha256": digest(freeze_path), "runs": entries,
        "reference_path": str(reference_path), "reference_sha256": digest(reference_path), "audio_sha256": INPUT_SHA256,
        "analysis_source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in
            (*((ROOT / "kototoki_eval").glob("*.py")), Path(__file__), ROOT / "experiments/analysis/aggregate.py")}})
    routes, evidence = [], {}
    for route, run_id, config in RUNS:
        result, harness = loaded[run_id]
        score_path = output / f"{run_id}-ref2-eval2.json"
        print(json.dumps({"scoring_started": run_id, "raw_candidate_characters": len(result["text"])}), flush=True)
        score = evaluate(reference, result)
        write(score_path, score)
        print(json.dumps({"scoring_finished": run_id, "text": score["text"], "timing": score["timing"]}), flush=True)
        routes.append({"id": route, "configuration_id": config, "runs": [{"scene_id": "full-film", "run_id": run_id,
            "status": "completed", "execution_verified": True, "evaluation_path": str(score_path), "evaluation_sha256": digest(score_path)}]})
        evidence[run_id] = {**proof(result, harness), **experimental_proof(result)}
    manifest = {"schema_version": 1, "manifest_id": "whole-film-fixed-w0-w1-diagnostic", "frozen": True,
        "reference_kind": "srt_display", "evaluation_config": {"status": "whole-film diagnostic after selection; no new sample or tuning",
                                                               "rule_version": RULE_VERSION},
        "scenes": [{"id": "full-film", "reference_path": str(reference_path), "reference_sha256": digest(reference_path)}], "routes": routes}
    write(output / "main-manifest.json", manifest)
    report = aggregate_manifest(manifest, base=output, bootstrap=False)
    if any(route["summary"]["timing"]["denominator"] != 1026 for route in report["routes"]):
        raise ValueError("Whole-film full denominator lost")
    report.update(sample_scope="same film as chapters; different uninterrupted context; no additive sample count", reselection="not_performed")
    write(output / "main-report.json", report)
    write(output / "execution-evidence.json", {"schema_version": 1, "runs": evidence})
    print(json.dumps({"output": str(output), "table_rows": report["table_rows"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    build(parser.parse_args().output)
