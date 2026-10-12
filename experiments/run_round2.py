"""Freeze and resume the second local comparison without changing backend options."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ROUND = ROOT / ".local/round2"
TEMPLATES = {
    "w0": ("h1-w0-ch04-r1", "W0-no-context", []),
    "w1": ("h1-w1norm-ch04-r1", "W1-normalized-forced", []),
    "q0": ("h1-q0-ch04-r1", "Q0-window30", []),
    "q1asr": ("h1-q1asr-ch04-r1", "Q1-no-vad", []),
    "q1": ("h1-q1-ch04-r1", "Q1-no-vad", ["q1asr"]),
    "export": (None, "X0-Q0-window30-normalized-forced", ["q0"]),
    "x0": ("h1-x0-ch04-r1", "X0-Q0-window30-normalized-forced", ["export"]),
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def path(value: str) -> Path:
    return (ROOT / value).resolve()


def read_json(file: Path) -> dict:
    return json.loads(file.read_text(encoding="utf-8"))


def write_json(file: Path, data: dict) -> None:
    temporary = file.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(file)


def replace_option(command: list[str], name: str, value: str) -> None:
    if command.count(name) != 1:
        raise ValueError(f"Template must contain exactly one {name}")
    command[command.index(name) + 1] = value


def prepare(corpus_file: Path) -> dict:
    plan_file = ROUND / "plan.json"
    if plan_file.exists():
        raise FileExistsError("Round already frozen; use list/run, or identify a new round")
    corpus = read_json(corpus_file)
    clips = corpus["clips"]
    if len(clips) != 12:
        raise ValueError("Round requires twelve clips: six 300-second clips per primary film")
    counts = Counter(clip["film"] for clip in clips)
    if sorted(counts.values()) != [6, 6]:
        raise ValueError("Round requires six clips from each of two primary films")
    tasks = []
    inputs = {str(corpus_file.resolve()): sha256(corpus_file)}
    source_assets = {}
    seen = set()
    for clip in clips:
        if re.fullmatch(r"[A-Za-z0-9_-]+", clip["id"]) is None or clip["id"] in seen:
            raise ValueError("Clip identifiers must be unique simple filenames")
        seen.add(clip["id"])
        if abs(float(clip["duration"]) - 300) > 1e-6:
            raise ValueError("Frozen clips must be 300 seconds")
        if not math.isfinite(clip["offset"]) or clip["offset"] != clip["source_start_seconds"]:
            raise ValueError("Inference offset must equal original source_start_seconds exactly once")
        if read_json(path(clip["reference"])).get("time_coordinate") != "source_media_seconds":
            raise ValueError("Reference timestamps must use original source media coordinates")
        for key, hash_key in (("audio", "audio_sha256"), ("reference", "reference_sha256")):
            actual = sha256(path(clip[key]))
            if actual != clip[hash_key]:
                raise ValueError(f"Corpus {key} hash mismatch: {clip['id']}")
            inputs[str(path(clip[key]))] = actual
        for key, hash_key in (("source_srt", "source_srt_sha256"), ("source_audio", "source_audio_sha256")):
            asset = str(path(clip[key]))
            if asset not in source_assets:
                if sha256(Path(asset)) != clip[hash_key]:
                    raise ValueError(f"Original source {key} hash mismatch")
                source_assets[asset] = clip[hash_key]
            if key == "source_srt":
                inputs[asset] = clip[hash_key]
        for stage, (template, configuration, dependencies) in TEMPLATES.items():
            command = None
            if template:
                template_file = ROOT / ".local/results" / template / "manifest.json"
                previous = read_json(template_file)
                if previous["status"] != "completed" or previous.get("reference_unchanged") is not True:
                    raise ValueError(f"Template run is not verified completed: {template}")
                command = previous["command"]
                inputs[str(template_file)] = sha256(template_file)
            tasks.append({"id": f"{clip['id']}-{stage}", "clip": clip["id"], "stage": stage,
                          "configuration": configuration, "template": template,
                          "template_command": command,
                          "depends_on": [f"{clip['id']}-{dep}" for dep in dependencies],
                          "stage_cache": {"asr": "reused_from_this_round_q0" if stage in {"export", "x0"}
                                          else "reused_from_this_round_q1asr" if stage == "q1" else "fresh",
                                          "alignment": "fresh" if stage in {"w1", "q0", "q1", "x0"}
                                          else "not_executed"}})
    ROUND.mkdir(parents=True, exist_ok=True)
    source_hashes = {}
    frozen_files = [ROOT / "experiments/run_experiment.py", Path(__file__).resolve(),
                    ROOT / "experiments/analysis/aggregate.py"]
    for directory in ("experiments/whisper", "experiments/qwen", "experiments/crisp", "experiments/corpus", "kototoki_eval"):
        frozen_files += sorted(file for file in (ROOT / directory).glob("*")
                               if file.suffix in {".py", ".lock", ".in"} and not file.name.startswith("test_"))
    frozen_files += [ROOT / relative for relative in ("docs/testing/stt-evaluation.md", "docs/testing/fatestay-reference.md",
                    "docs/testing/validation.md", "docs/development/inference-selection.md")]
    frozen_files += [ROOT / name for name in ("pyproject.toml", "uv.lock", "mise.toml", "justfile")]
    for source in frozen_files:
        if not source.is_file():
            continue
        target = ROUND / "source" / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        source_hashes[str(source.relative_to(ROOT))] = sha256(target)
    plan = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
            "corpus": str(corpus_file.resolve()), "corpus_sha256": sha256(corpus_file),
            "clips": clips, "tasks": tasks, "source_sha256": source_hashes, "input_sha256": inputs,
            "source_asset_sha256": source_assets,
            "source_execution": "original paths, verified equal to frozen snapshots before every task",
            "performance_context": "serialized fresh GPU subprocesses; X0 and Q1 alignment reuse this round ASR stages",
            "selection": "five historical held-out configurations; no retuning on primary films"}
    with plan_file.open("x", encoding="utf-8") as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2)
    write_json(ROUND / "progress.json", {"schema_version": 1, "plan_sha256": sha256(plan_file), "tasks": {}})
    return plan


def verify_freeze(plan: dict) -> None:
    for relative, expected in plan["source_sha256"].items():
        if sha256(ROOT / relative) != expected or sha256(ROUND / "source" / relative) != expected:
            raise ValueError(f"Frozen source/configuration changed: {relative}")
    for file, expected in plan["input_sha256"].items():
        if sha256(Path(file)) != expected:
            raise ValueError(f"Frozen input changed: {file}")


def successful_result(result: dict) -> bool:
    return result.get("status", "ok") == "ok" and result.get("manifest", {}).get("status", "ok") == "ok"


def verified_completed(record: dict, clip: dict) -> bool:
    if record.get("status") != "completed":
        return False
    output = path(record["output"])
    if not output.is_file() or sha256(output) != record.get("output_sha256"):
        raise ValueError("Previously completed result was removed or changed")
    if not successful_result(read_json(output)):
        raise ValueError("Previously completed result is no longer successful")
    manifest_file = path(record["harness_manifest"])
    if sha256(manifest_file) != record.get("harness_manifest_sha256"):
        raise ValueError("Previously completed harness manifest changed")
    manifest = read_json(manifest_file)
    if (manifest.get("status") != "completed" or manifest.get("returncode") != 0
            or manifest.get("audio_sha256") != clip["audio_sha256"]
            or manifest.get("reference_sha256_expected") != clip["source_srt_sha256"]
            or manifest.get("reference_unchanged") is not True
            or manifest.get("command") != record["command"]):
        raise ValueError("Previously completed task has incomplete identity evidence")
    for dependency in record.get("dependency_artifacts", []):
        if sha256(path(dependency["path"])) != dependency["sha256"]:
            raise ValueError("Previously completed dependency artifact changed")
    return True


def build_command(task: dict, clip: dict, output: Path, records: dict) -> list[str]:
    if task["stage"] == "export":
        q0 = records[f"{clip['id']}-q0"]["output"]
        return [".local/envs/qwen-hf-final/Scripts/python.exe", "experiments/qwen/export_ctc_input.py",
                "--asr-result", q0, "--audio", clip["audio"], "--offset", str(clip["offset"]),
                "--output", str(output)]
    command = list(task["template_command"])
    for name, value in (("--audio", clip["audio"]), ("--offset", str(clip["offset"])),
                        ("--output", str(output))):
        replace_option(command, name, value)
    if task["stage"] == "q1":
        replace_option(command, "--text-file", records[f"{clip['id']}-q1asr"]["output"])
    if task["stage"] == "x0":
        replace_option(command, "--asr-result", records[f"{clip['id']}-export"]["output"])
    return command


def execute(task: dict, clip: dict, records: dict, timeout: float) -> dict:
    attempt = records.get(task["id"], {}).get("attempt", 0) + 1
    while (ROOT / ".local/results" / f"r2-{task['id']}-a{attempt:02d}").exists():
        attempt += 1
    run_id = f"r2-{task['id']}-a{attempt:02d}"
    run_dir = ROOT / ".local/results" / run_id
    output = run_dir / "result.json"
    manifest_file = run_dir / "manifest.json"
    command = build_command(task, clip, output, records)
    record = {"id": run_id, "attempt": attempt, "status": "running", "output": str(output),
              "harness_manifest": str(manifest_file), "command": command,
              "stage_cache": task["stage_cache"], "configuration": task["configuration"],
              "dependency_artifacts": [{"path": records[dep]["output"], "sha256": records[dep]["output_sha256"]}
                                       for dep in task["depends_on"]]}
    records[task["id"]] = record
    progress_file = ROUND / "progress.json"
    progress = read_json(progress_file)
    progress["tasks"] = records
    write_json(progress_file, progress)
    started = time.perf_counter()
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1", PYTHONUTF8="1")
    try:
        if task["stage"] == "export":
            run_dir.mkdir()
            manifest = {"id": run_id, "command": command, "status": "running", "gpu_task": False,
                        "audio_sha256": sha256(path(clip["audio"])),
                        "reference_sha256_expected": clip["source_srt_sha256"],
                        "reference_sha256_before": sha256(path(clip["source_srt"]))}
            write_json(manifest_file, manifest)
            with (run_dir / "stdout.log").open("wb") as stdout, (run_dir / "stderr.log").open("wb") as stderr:
                completed = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout,
                                           stderr=stderr, timeout=timeout, check=False)
            manifest.update(status="completed" if completed.returncode == 0 else "failed",
                            returncode=completed.returncode,
                            reference_sha256_after=sha256(path(clip["source_srt"])),
                            wall_seconds=time.perf_counter() - started)
            manifest["reference_unchanged"] = manifest["reference_sha256_after"] == manifest["reference_sha256_before"] == clip["source_srt_sha256"]
            write_json(manifest_file, manifest)
        else:
            harness = [sys.executable, "experiments/run_experiment.py", "--id", run_id,
                       "--audio", clip["audio"], "--reference", clip["source_srt"],
                       "--reference-sha256", clip["source_srt_sha256"], "--timeout", str(timeout),
                       "--performance-context", "round2; sequential GPU queue; cached stages explicitly reported", "--", *command]
            completed = subprocess.run(harness, cwd=ROOT, env=environment, check=False)
        record["returncode"] = completed.returncode
        if completed.returncode == 0 and output.is_file() and successful_result(read_json(output)):
            record["status"] = "completed"
        else:
            record.update(status="failed", reason="process or backend result failed")
            if task["stage"] == "export":
                record["reason"] = (run_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")[-2500:]
    except Exception as error:
        record.update(status="failed", reason=f"{type(error).__name__}: {error}")
    finally:
        record["wall_seconds"] = time.perf_counter() - started
        if output.exists():
            record["output_sha256"] = sha256(output)
        if manifest_file.exists():
            record["harness_manifest_sha256"] = sha256(manifest_file)
        write_json(run_dir / "orchestration.json", record) if run_dir.exists() else None
        progress["tasks"] = records
        write_json(progress_file, progress)
    if record["status"] == "completed":
        verified_completed(record, clip)
    return record


def run(plan: dict, limit: int | None, timeout: float) -> dict:
    progress_file = ROUND / "progress.json"
    progress = read_json(progress_file)
    if progress["plan_sha256"] != sha256(ROUND / "plan.json"):
        raise ValueError("Frozen plan changed")
    records = progress["tasks"]
    for file, expected in plan.get("source_asset_sha256", {}).items():
        if sha256(Path(file)) != expected:
            raise ValueError(f"Original source asset changed before batch: {file}")
    clips = {clip["id"]: clip for clip in plan["clips"]}
    count = 0
    for task in plan["tasks"]:
        clip = clips[task["clip"]]
        if verified_completed(records.get(task["id"], {}), clip):
            continue
        if limit is not None and count >= limit:
            break
        verify_freeze(plan)
        blocked = [dep for dep in task["depends_on"] if not verified_completed(records.get(dep, {}), clip)]
        if blocked:
            records[task["id"]] = {**records.get(task["id"], {}), "status": "blocked", "depends_on": blocked,
                                    "reason": "required current-round stage has no verified completed artifact",
                                    "configuration": task["configuration"], "stage_cache": task["stage_cache"]}
            progress["tasks"] = records
            write_json(progress_file, progress)
            print(json.dumps({"task": task["id"], "status": "blocked", "depends_on": blocked}), flush=True)
            continue
        record = execute(task, clip, records, timeout)
        count += 1
        print(json.dumps({"task": task["id"], "status": record["status"], "output": record["output"]}), flush=True)
    source_check = {}
    for file, expected in plan.get("source_asset_sha256", {}).items():
        actual = sha256(Path(file))
        source_check[file] = {"expected": expected, "after": actual, "unchanged": actual == expected}
    progress["source_assets_after_batch"] = source_check
    progress["tasks"] = records
    write_json(progress_file, progress)
    if any(not entry["unchanged"] for entry in source_check.values()):
        raise ValueError("Original source asset changed during batch")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "list", "run"])
    parser.add_argument("--corpus", type=Path, default=ROUND / "corpus/manifest.json")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=7200)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if args.action == "prepare":
        plan = prepare(args.corpus.resolve())
        print(json.dumps({"plan": str(ROUND / "plan.json"), "clips": len(plan["clips"]), "tasks": len(plan["tasks"])}))
        return 0
    plan = read_json(ROUND / "plan.json")
    if args.action == "run":
        records = run(plan, args.limit, args.timeout)
        return 1 if any(record["status"] in {"failed", "blocked"} for record in records.values()) else 0
    progress = read_json(ROUND / "progress.json")
    for task in plan["tasks"]:
        print(json.dumps({"task": task["id"], "configuration": task["configuration"],
                          "status": progress["tasks"].get(task["id"], {}).get("status", "pending")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
