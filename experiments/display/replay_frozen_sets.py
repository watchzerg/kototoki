"""Replay fixed validation and normalized-CTC development registries on CPU."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
WRITER = ROOT / "experiments/display/replay.py"
VALIDATION_REGISTRY = ROOT / ".local/analysis/validation/cpu-v2-r1/source-registry.json"
DEVELOPMENT_REGISTRY = ROOT / ".local/analysis/dev-comparison/cpu-v2-r7/source-registry.json"
FLASH_SECONDS = 0.5
DEVELOPMENT_ROUTES = {"W1-normalized-forced", "X0-Q0-window30-normalized-forced"}
VALIDATION_ROUTES = {"W0-no-context", "W1-W0-no-context", "W1-normalized-forced", "Q0-window30", "Q1-no-vad", "X0-Q0-window30-normalized-forced"}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def lexical_count(text: str) -> int:
    return sum(unicodedata.category(char)[0] in "LN" for char in text)


def actual_srt_lexical(path: Path) -> int:
    total = 0
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        if not block:
            continue
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].isdigit() or " --> " not in lines[1]:
            raise ValueError("Written SRT structure is invalid")
        total += lexical_count("\n".join(lines[2:]))
    return total


def cue_counts(cues: list[dict]) -> dict:
    valid = [cue for cue in cues if isinstance(cue.get("start"), (int, float))
             and isinstance(cue.get("end"), (int, float)) and math.isfinite(cue["start"])
             and math.isfinite(cue["end"]) and 0 <= cue["start"] < cue["end"]]
    durations = [cue["end"] - cue["start"] for cue in valid]
    return {"cues": len(cues), "invalid": len(cues) - len(valid),
            "flash_lt_0_5s": sum(duration < FLASH_SECONDS for duration in durations),
            "long_gt_7s": sum(duration > 7 for duration in durations),
            "overlap": sum(right["start"] < left["end"] for left, right in zip(valid, valid[1:])),
            "max_seconds": max(durations, default=None)}


def aggregate(rows: list[dict]) -> dict:
    result = {}
    for route in sorted({row["route"] for row in rows}):
        selected = [row for row in rows if row["route"] == route]
        full = sum(row["coverage"]["original_lexical_characters"] for row in selected)
        rendered = sum(row["actual_srt_lexical_characters"] for row in selected)
        row = {"chapters": len(selected), "full_lexical_characters": full,
               "actual_srt_lexical_characters": rendered,
               "srt_lexical_coverage": rendered / full if full else None,
               "missing_srt_lexical_characters": full - rendered,
               "unrenderable_reasons": dict(sum((Counter(item["unrenderable_reasons"]) for item in selected), Counter())),
               "unit_status": dict(sum((Counter(item["unit_status"]) for item in selected), Counter())),
               "unit_granularity": dict(sum((Counter(item["unit_granularity"]) for item in selected), Counter())),
               "long_gt7_native_unit_count": sum(item["long_gt7_native_unit_count"] for item in selected),
               "full_chapter_span_unit_count": sum(item["full_chapter_span_unit_count"] for item in selected),
               "max_native_unit_seconds": max((item["max_native_unit_seconds"] for item in selected if item["max_native_unit_seconds"] is not None), default=None)}
        for category in ["unified", "native"]:
            row[category] = {key: sum(item[category][key] for item in selected)
                             for key in ["cues", "invalid", "flash_lt_0_5s", "long_gt_7s", "overlap"]}
            row[category]["max_seconds"] = max((item[category]["max_seconds"] for item in selected if item[category]["max_seconds"] is not None), default=None)
        result[route] = row
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", default="validation-r1")
    args = parser.parse_args()
    if args.id in {"", ".", ".."} or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for char in args.id):
        parser.error("Simple unique output identity required")
    output = ROOT / ".local/analysis/display" / args.id
    display_output = ROOT / ".local/display" / args.id
    if output.exists() or display_output.exists():
        parser.error("Display analysis identity already exists; choose a fresh directory")
    output.mkdir(parents=True, exist_ok=False)
    display_output.mkdir(parents=True, exist_ok=False)
    freeze_path = ROOT / ".local/manifests/validation-freeze-v1.json"
    freeze = load(freeze_path)
    policy_path = ROOT / freeze["policy"]
    frozen_files = {item["path"]: item["sha256"] for item in freeze["files"]}
    writer_hash = digest(WRITER)
    if writer_hash != frozen_files["experiments/display/replay.py"] or digest(policy_path) != freeze["policy_sha256"]:
        raise ValueError("Frozen writer or screening policy identity differs")
    identity_paths = [freeze_path, policy_path, WRITER, VALIDATION_REGISTRY, DEVELOPMENT_REGISTRY,
                      ROOT / ".local/manifests/corpus-freeze.json"]
    identities = {str(path.relative_to(ROOT)): digest(path) for path in identity_paths}
    scenes = {scene["id"]: scene for scene in load(ROOT / ".local/manifests/corpus-freeze.json")["scenes"]}
    sets = [("validation", VALIDATION_REGISTRY, VALIDATION_ROUTES, {"chapter-03", "chapter-14", "chapter-23"}, 18),
            ("development-additions", DEVELOPMENT_REGISTRY, DEVELOPMENT_ROUTES, {"chapter-01", "chapter-02", "chapter-05", "chapter-07", "chapter-17"}, 10)]
    all_rows = {}
    for scope, registry_path, routes, chapter_ids, expected_count in sets:
        registry = load(registry_path)
        entries = [entry for entry in registry["runs"] if entry["route"] in routes and entry["scene_id"] in chapter_ids]
        if len(entries) != expected_count or {(entry["route"], entry["scene_id"]) for entry in entries} != {(route, chapter) for route in routes for chapter in chapter_ids}:
            raise ValueError("Registry does not contain the exact requested route/chapter scope")
        (display_output / scope).mkdir()
        (output / scope).mkdir()
        rows = []
        for entry in entries:
            if "result_path" not in entry:
                artifacts = {Path(item["path"]).name: item for item in entry["artifacts"]}
                entry = {**entry, "result_path": artifacts["result.json"]["path"],
                         "result_sha256": artifacts["result.json"]["sha256"],
                         "manifest_path": artifacts["manifest.json"]["path"],
                         "manifest_sha256": artifacts["manifest.json"]["sha256"]}
            for artifact in entry.get("artifacts", []) + entry.get("upstream_artifacts", []):
                if digest(Path(artifact["path"])) != artifact["sha256"]:
                    raise ValueError("Registered stage/upstream artifact identity differs")
            result_path, manifest_path = Path(entry["result_path"]), Path(entry["manifest_path"])
            if digest(result_path) != entry["result_sha256"] or digest(manifest_path) != entry["manifest_sha256"]:
                raise ValueError("Input result/manifest differs from private source registry")
            scene = scenes[entry["scene_id"]]
            audio_manifest_path = ROOT / ".local/manifests" / f"corpus-audio-{entry['scene_id']}.json"
            audio = load(audio_manifest_path)
            harness = load(manifest_path)
            if harness["status"] != "completed" or harness["audio_sha256"] != audio["wav_sha256"]:
                raise ValueError("Run audio/status differs from the frozen input")
            source = load(result_path)
            prefix = display_output / scope / entry["run_id"]
            command = [sys.executable, str(WRITER), "--input", str(result_path), "--output-prefix", str(prefix),
                       "--source-start", str(scene["start"]), "--source-end", str(scene["end"])]
            run = subprocess.run(command, capture_output=True, text=True)
            write(output / scope / f"{entry['run_id']}.replay.json", {"command": command, "returncode": run.returncode,
                                                                  "stdout": run.stdout, "stderr": run.stderr})
            if run.returncode:
                raise RuntimeError("Frozen display replay failed")
            sidecar_path, srt_path = Path(str(prefix) + ".display.json"), Path(str(prefix) + ".srt")
            sidecar = load(sidecar_path)
            actual = actual_srt_lexical(srt_path)
            if sidecar["input_identity"]["sha256"] != entry["result_sha256"] or sidecar["writer_source_sha256"] != writer_hash:
                raise ValueError("Replay source/writer identity differs")
            if source["text"] != sidecar["original_text"] or source["units"] != sidecar["original_units"]:
                raise ValueError("Complete text/native units were not preserved")
            if actual != sidecar["coverage"]["rendered_lexical_characters"]:
                raise ValueError("Actual SRT lexical count differs from sidecar")
            timed = [unit for unit in source["units"] if isinstance(unit.get("start"), (int, float))
                     and isinstance(unit.get("end"), (int, float)) and math.isfinite(unit["start"]) and math.isfinite(unit["end"])]
            durations = [unit["end"] - unit["start"] for unit in timed]
            rows.append({**entry, "scope": scope, "input_wav_sha256": audio["wav_sha256"],
                         "audio_manifest_sha256": digest(audio_manifest_path),
                         "srt_path": str(srt_path), "srt_sha256": digest(srt_path),
                         "sidecar_path": str(sidecar_path), "sidecar_sha256": digest(sidecar_path),
                         "coverage": sidecar["coverage"], "actual_srt_lexical_characters": actual,
                         "full_text_and_units_preserved": True,
                         "unrenderable_reasons": dict(Counter(item["reason"] for item in sidecar["unrenderable"])),
                         "unit_status": dict(Counter(unit.get("status", "ok") for unit in source["units"])),
                         "unit_granularity": dict(Counter(unit.get("granularity", "unknown") for unit in source["units"])),
                         "time_sources": dict(Counter(unit.get("time_source", "native") for unit in source["units"])),
                         "zero_or_negative_duration_units": sum(duration <= 0 for duration in durations),
                         "long_gt7_native_unit_count": sum(duration > 7 for duration in durations),
                         "full_chapter_span_unit_count": sum(duration >= (scene["end"] - scene["start"]) * 0.8 for duration in durations),
                         "max_native_unit_seconds": max(durations, default=None),
                         "unified": cue_counts(sidecar["unified_cues"]), "native": cue_counts(sidecar["native_cues_preserved"])})
            if digest(result_path) != entry["result_sha256"] or digest(manifest_path) != entry["manifest_sha256"]:
                raise ValueError("Input result changed during CPU replay")
            for artifact in entry.get("artifacts", []) + entry.get("upstream_artifacts", []):
                if digest(Path(artifact["path"])) != artifact["sha256"]:
                    raise ValueError("Registered stage/upstream artifact changed during CPU replay")
        all_rows[scope] = rows
    if any(digest(ROOT / relative) != expected for relative, expected in identities.items()):
        raise ValueError("Frozen inputs or policy changed during display analysis")
    report = {"schema_version": 1, "scope": "18 validation and 10 additional development display replays; no inference",
              "identities": identities, "analysis_script_sha256": digest(Path(__file__)),
              "writer_revision": "minimal-display-v1-2026-10-04", "flash_description_seconds": FLASH_SECONDS,
              "no_policy_or_writer_changes": True, "source_results_preserved": True,
              "all_actual_srt_lexical_counts_independently_checked": True,
              "no_human_listening_or_acoustic_silence_claim": True,
              "aggregates": {scope: aggregate(rows) for scope, rows in all_rows.items()}, "rows": all_rows}
    write(output / "display-report.json", report)
    print(json.dumps({"report": str(output / "display-report.json"), "identities": identities, "aggregates": report["aggregates"]}))


if __name__ == "__main__":
    main()
