"""Replay all frozen held-out slots, retaining failed and missing-stage evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WRITER = ROOT / "experiments/display/replay.py"
METRICS = ROOT / "experiments/display/replay_frozen_sets.py"
REGISTRY = ROOT / ".local/analysis/heldout/cpu-v2-r1/source-registry.json"
FREEZE = ROOT / ".local/manifests/heldout-freeze-v1.json"

spec = importlib.util.spec_from_file_location("frozen_display_metrics", METRICS)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default="heldout-r1")
    args = parser.parse_args()
    if args.id in {"", ".", ".."} or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in args.id):
        parser.error("Simple unique display identity required")
    output = ROOT / ".local/analysis/display" / args.id
    display = ROOT / ".local/display" / args.id
    if output.exists() or display.exists():
        parser.error("Display identity already exists; choose a fresh directory")
    registry = metrics.load(REGISTRY)
    freeze = metrics.load(FREEZE)
    entries = registry["runs"]
    if len(entries) != 80 or len({(entry["group"], entry["scene_id"]) for entry in entries}) != 80:
        raise ValueError("Held-out registry is not a complete 80-slot ledger")
    if set(Counter(entry["group"] for entry in entries).values()) != {16}:
        raise ValueError("Each of five frozen groups must retain all 16 chapters")
    output.mkdir(parents=True, exist_ok=False)
    display.mkdir(parents=True, exist_ok=False)
    (output / "derived").mkdir()
    snapshot = output / "source-artifacts"
    snapshot.mkdir()
    corpus_path = ROOT / ".local/manifests/corpus-freeze.json"
    scenes = {scene["id"]: scene for scene in metrics.load(corpus_path)["scenes"] if scene["partition"] == "heldout"}
    policy = ROOT / freeze["policy"]
    identities = {str(path.relative_to(ROOT)): metrics.digest(path) for path in [REGISTRY, FREEZE, WRITER, METRICS, Path(__file__), policy, corpus_path]}
    if metrics.digest(policy) != freeze["policy_sha256"]:
        raise ValueError("Screening policy differs from held-out freeze")
    validation_freeze = metrics.load(ROOT / ".local/manifests/validation-freeze-v1.json")
    writer_expected = next(item["sha256"] for item in validation_freeze["files"] if item["path"] == "experiments/display/replay.py")
    if metrics.digest(WRITER) != writer_expected:
        raise ValueError("Writer differs from its frozen identity")
    snapshot_records: dict[str, dict] = {}

    def preserve(path: Path, expected: str) -> None:
        path = path.resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Registered artifact is outside the project")
        if metrics.digest(path) != expected:
            raise ValueError(f"Registered artifact changed: {path}")
        relative = path.relative_to(ROOT)
        destination = snapshot / relative
        if str(relative) not in snapshot_records:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with path.open("rb") as source, destination.open("xb") as target:
                shutil.copyfileobj(source, target)
            if metrics.digest(destination) != expected:
                raise ValueError("Source artifact snapshot differs")
            snapshot_records[str(relative)] = {"source_path": str(path), "snapshot_path": str(destination), "sha256": expected}

    for relative, expected in identities.items():
        preserve(ROOT / relative, expected)
    rows = []
    for entry in entries:
        scene = scenes[entry["scene_id"]]
        artifacts = {Path(item["path"]).name: item for item in entry["artifacts"]}
        for item in entry["artifacts"] + entry.get("upstream_artifacts", []):
            if item["sha256"] is not None:
                preserve(Path(item["path"]), item["sha256"])
        audio_manifest_path = ROOT / ".local/manifests" / f"corpus-audio-{entry['scene_id']}.json"
        audio = metrics.load(audio_manifest_path)
        preserve(audio_manifest_path, metrics.digest(audio_manifest_path))
        result_artifact, harness_artifact = artifacts["result.json"], artifacts["manifest.json"]
        source_status = "completed"
        derived = False
        if result_artifact["sha256"] is None:
            if entry["run_id"] != "h1-x0-ch12-r1":
                raise ValueError("Unexpected missing result outside the predeclared diagnostic slot")
            upstream_path = ROOT / ".local/results/h1-q0-ch12-r1/result.json"
            upstream = metrics.load(upstream_path)
            text = upstream["text"]
            document = {"schema_version": 1, "text": text, "units": [], "cues": [],
                        "derived_for_display_accounting_only": True, "not_actual_x0_output": True,
                        "original_pipeline_status": "missing_bridge_rejected_upstream_generation_token_cap",
                        "upstream_result_path": str(upstream_path), "upstream_result_sha256": metrics.digest(upstream_path),
                        "no_new_asr_or_alignment_inference": True, "all_timing_intentionally_absent": True}
            if text:
                document["units"] = [{"char_start": 0, "char_end": len(text), "start": None, "end": None,
                                      "granularity": "segment", "time_source": "fallback", "status": "text_only"}]
            replay_input = output / "derived" / f"{entry['run_id']}-text-only-diagnostic.json"
            metrics.write(replay_input, document)
            harness_path = upstream_path.parent / "manifest.json"
            harness = metrics.load(harness_path)
            source_status = "missing_bridge_rejected_upstream_generation_token_cap"
            derived = True
        else:
            replay_input = Path(result_artifact["path"])
            document = metrics.load(replay_input)
            harness = metrics.load(Path(harness_artifact["path"]))
            if harness["status"] != "completed" or document.get("manifest", {}).get("status") == "failed":
                source_status = "failed_original_pipeline_diagnostic_only"
                if entry["run_id"] != "h1-q1-ch20-r1":
                    raise ValueError("Unexpected failed original pipeline outside the declared diagnostic slot")
        if harness["audio_sha256"] != audio["wav_sha256"]:
            raise ValueError("Result/upstream harness input differs from frozen chapter audio")
        capped_windows = sum(bool(window.get("token_limit_reached")) for window in document.get("windows", []))
        if capped_windows and source_status == "completed":
            source_status = "execution_complete_but_generation_token_cap"
        for relative, expected in harness.get("source_sha256", {}).items():
            actual = Path(harness_artifact["path"]).parent / "source" / relative if not derived else ROOT / ".local/results/h1-q0-ch12-r1/source" / relative
            if actual.exists():
                preserve(actual, expected)
        prefix = display / entry["run_id"]
        command = [sys.executable, str(WRITER), "--input", str(replay_input), "--output-prefix", str(prefix),
                   "--source-start", str(scene["start"]), "--source-end", str(scene["end"])]
        run = subprocess.run(command, capture_output=True, text=True)
        metrics.write(output / f"{entry['run_id']}.replay.json", {"command": command, "returncode": run.returncode,
                                                              "stdout": run.stdout, "stderr": run.stderr,
                                                              "original_pipeline_status": source_status, "derived_diagnostic": derived})
        if run.returncode:
            raise RuntimeError("Display replay failed; original slot remains in its registry")
        sidecar_path, srt_path = Path(str(prefix) + ".display.json"), Path(str(prefix) + ".srt")
        sidecar = metrics.load(sidecar_path)
        actual_lexical = metrics.actual_srt_lexical(srt_path)
        if sidecar["original_text"] != document["text"] or sidecar["original_units"] != document["units"]:
            raise ValueError("Complete available text/native units were not preserved")
        if actual_lexical != sidecar["coverage"]["rendered_lexical_characters"]:
            raise ValueError("Actual SRT lexical count differs from sidecar")
        if sidecar["input_identity"]["sha256"] != metrics.digest(replay_input) or sidecar["writer_source_sha256"] != writer_expected:
            raise ValueError("Replay source/writer hash changed")
        durations = [unit["end"] - unit["start"] for unit in document["units"]
                     if isinstance(unit.get("start"), (int, float)) and isinstance(unit.get("end"), (int, float))
                     and math.isfinite(unit["start"]) and math.isfinite(unit["end"])]
        row = {**entry, "route": entry["route_id"], "original_pipeline_status": source_status,
               "generation_capped_windows": capped_windows,
               "derived_display_diagnostic": derived, "eligible_as_successful_original_pipeline": source_status == "completed",
               "replay_input_path": str(replay_input), "replay_input_sha256": metrics.digest(replay_input),
               "input_wav_sha256": audio["wav_sha256"], "srt_path": str(srt_path), "srt_sha256": metrics.digest(srt_path),
               "sidecar_path": str(sidecar_path), "sidecar_sha256": metrics.digest(sidecar_path),
               "full_available_text_and_units_preserved": True, "coverage": sidecar["coverage"],
               "actual_srt_lexical_characters": actual_lexical,
               "unrenderable_reasons": dict(Counter(item["reason"] for item in sidecar["unrenderable"])),
               "unit_status": dict(Counter(unit.get("status", "ok") for unit in document["units"])),
               "unit_granularity": dict(Counter(unit.get("granularity", "unknown") for unit in document["units"])),
               "long_gt7_native_unit_count": sum(duration > 7 for duration in durations),
               "full_chapter_span_unit_count": sum(duration >= (scene["end"] - scene["start"]) * 0.8 for duration in durations),
               "max_native_unit_seconds": max(durations, default=None),
               "unified": metrics.cue_counts(sidecar["unified_cues"]), "native": metrics.cue_counts(sidecar["native_cues_preserved"])}
        rows.append(row)
    for record in snapshot_records.values():
        if metrics.digest(Path(record["source_path"])) != record["sha256"]:
            raise ValueError("Source artifact changed during held-out display replay")
    aggregates = metrics.aggregate(rows)
    for route, summary in aggregates.items():
        selected = [row for row in rows if row["route"] == route]
        summary["original_pipeline_status_counts"] = dict(Counter(row["original_pipeline_status"] for row in selected))
        summary["expected_slots"] = 16
        summary["retained_slots"] = len(selected)
    report = {"schema_version": 1, "scope": "all 80 frozen held-out slots; CPU display only; no inference",
              "fixed_reference_denominator": 620, "retained_slots": len(rows), "expected_slots": 80,
              "identities": identities, "writer_revision": "minimal-display-v1-2026-10-04",
              "source_snapshots": list(snapshot_records.values()), "aggregates": aggregates, "rows": rows,
              "status_counts": dict(Counter(row["original_pipeline_status"] for row in rows)),
              "derived_slot_policy": "Missing X0 ch12 retains complete available upstream ASR output as explicit untimed diagnostic; not actual X0 output",
              "failed_slot_policy": "Crisp ch20 original adapter failure remains failed even when partial timed units can render",
              "completed_status_note": "Execution completion alone does not qualify acoustic timing, generation completeness, or caption usability; generation caps have a separate status",
              "limitations": ["SRT lexical coverage is relative to complete available candidate text, not reference accuracy",
                              "Token-capped upstream generation is not a complete transcription of source audio",
                              "Full sidecar text does not imply complete SRT rendering",
                              "No acoustic timing/silence or caption-usability qualification"]}
    metrics.write(output / "display-report.json", report)
    print(json.dumps({"report": str(output / "display-report.json"), "report_sha256": metrics.digest(output / "display-report.json"),
                      "status_counts": report["status_counts"], "snapshots": len(snapshot_records), "aggregates": aggregates}))


if __name__ == "__main__":
    main()
