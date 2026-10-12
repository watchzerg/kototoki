"""Freeze, execute and score Japanese CTC substitutions against cached ASR."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.components import evaluate as evaluator
from kototoki_eval.schema import validate_transcript

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / ".local/japanese-ctc"
BASE = ROOT / ".local/components/comp-w0-vad-ctc-dev-v1/evaluation.json"
BRIDGES = ROOT / ".local/components/comp-w0-ctc-envelope-dev-v1/bridges"
CANDIDATES = {
    "reazon": "japanese-wav2vec2-large-rs35kh",
    "mms": "mms-1b-all",
    "hiragana": "wav2vec2-xls-r-300m-japanese-hiragana",
    "jonatas": "wav2vec2-large-xlsr-53-japanese",
}
BASELINES = ("w0-baseline", "w1-baseline", "x0-baseline", "w0-ctc")
ROUTES = ("w0", "w1", "x0")


def read(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def digest(path: str | Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path: str | Path, expected: str | None = None) -> dict[str, str]:
    target = Path(path).resolve()
    actual = digest(target)
    if expected is not None and actual != expected:
        raise ValueError(f"Frozen SHA256 changed: {target}")
    return {"path": str(target), "sha256": actual}


def write_new(path: Path, document: dict[str, Any]) -> None:
    evaluator.write_new(path, document)


def validate_name(name: str) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name):
        raise ValueError("Name must be a simple nonempty filename")


def verify_clip(clip: dict[str, Any]) -> None:
    for field in ("audio", "reference", "source_srt"):
        identity(clip[field], clip[f"{field}_sha256"])


def verify_upstream(document: dict[str, Any], saved: dict[str, Any], clip: dict[str, Any]) -> None:
    segments = document.get("original_segments")
    if (document.get("text") != saved["text"] or not isinstance(segments, list)
            or "".join(row["text"] for row in segments) != saved["text"]):
        raise ValueError("Upstream must preserve complete cached ASR text")
    for row in segments:
        if (not isinstance(row.get("text"), str)
                or any(isinstance(row.get(k), bool) or not isinstance(row.get(k), (int, float))
                       or not math.isfinite(row[k]) for k in ("start", "end"))
                or not 0 <= row["start"] < row["end"] <= clip["duration"]):
            raise ValueError("Invalid frozen alignment search window")


def model_identity(candidate: str) -> dict[str, Any]:
    manifest_path = ROOT / ".local/manifests" / f"model-{CANDIDATES[candidate]}.json"
    manifest = read(manifest_path)
    if manifest.get("complete") is not True or not manifest.get("revision") or not manifest.get("files"):
        raise ValueError("Model requires a provisioned revision and file registry")
    files = []
    for item in manifest["files"]:
        path = Path(item["path"])
        path = path if path.is_absolute() else ROOT / path
        files.append(identity(path, item["sha256"]))
    directories = {str(Path(item["path"]).parent) for item in files}
    if len(directories) != 1:
        raise ValueError("Model files must share one local model directory")
    return {**identity(manifest_path), "model_dir": directories.pop(), "repo": manifest["repo"],
            "revision": manifest["revision"], "files": files}


def prepare(name: str, candidates: list[str], *, routes: tuple[str, ...] = ROUTES,
            scope: str = "pilot", zero_pad_seconds: float = 0) -> dict[str, Any]:
    """Create a new complete immutable registry, requiring explicit model arms."""
    validate_name(name)
    if (not candidates or len(set(candidates)) != len(candidates)
            or any(c not in CANDIDATES for c in candidates)):
        raise ValueError("Declare nonempty unique candidate arms explicitly")
    if (not routes or len(set(routes)) != len(routes) or any(r not in ROUTES for r in routes)
            or scope not in {"pilot", "full"}):
        raise ValueError("Invalid routes or scope")
    if (not math.isfinite(zero_pad_seconds) or zero_pad_seconds < 0
            or zero_pad_seconds and any(c not in {"reazon", "hiragana"} for c in candidates)):
        raise ValueError("Physical zero padding requires a nonnegative native-token-only batch")
    destination = LOCAL / name
    if destination.exists():
        raise FileExistsError("Use a new immutable batch identity")
    baseline = read(BASE)
    if baseline.get("frozen") is not True or baseline.get("strict_hashes") is not True:
        raise ValueError("A strict frozen baseline registry is required")
    configurations = baseline["configurations"][:4]
    if tuple(c["id"] for c in configurations) != BASELINES:
        raise ValueError("Expected exact four retained baseline configurations")
    clips = [deepcopy(c) for c in baseline["clips"]
             if scope == "full" or c["id"].endswith(("-01", "-04"))]
    if len(clips) != (4 if scope == "pilot" else 12):
        raise ValueError("Expected four pilot or twelve full II/III windows")
    ids = {c["id"] for c in clips}
    baselines = deepcopy(configurations)
    artifacts: dict[str, str] = {str(BASE.resolve()): digest(BASE)}
    for config in baselines:
        config["runs"] = [r for r in config["runs"] if r["clip_id"] in ids]
        if {r["clip_id"] for r in config["runs"]} != ids:
            raise ValueError("Baseline has missing or duplicate source slots")
        for slot in config["runs"]:
            if slot["status"] != "completed" or slot.get("execution_verified") is not True:
                raise ValueError("Baseline cached ASR must be independently completed")
            artifacts.update({slot["result_path"]: identity(slot["result_path"], slot["result_sha256"])["sha256"]})
            for item in slot.get("evidence", {}).get("artifacts", []):
                artifacts[item["path"]] = identity(item["path"], item["sha256"])["sha256"]
    models = {c: model_identity(c) for c in candidates}
    sources = {}
    for folder in ("experiments/japanese_ctc", "experiments/whisper", "experiments/components", "kototoki_eval"):
        for path in sorted((ROOT / folder).glob("*.py")):
            if not path.name.startswith("test_"):
                sources[str(path.resolve())] = digest(path)
    sources[str(ROOT / "experiments/run_experiment.py")] = digest(ROOT / "experiments/run_experiment.py")
    provision = ROOT / "experiments/provision/japanese_ctc.py"
    if provision.is_file():
        sources[str(provision)] = digest(provision)
    products = []
    tasks = []
    for clip in clips:
        verify_clip(clip)
        for route in routes:
            slot = next(r for c in baselines if c["id"] == f"{route}-baseline"
                        for r in c["runs"] if r["clip_id"] == clip["id"])
            cached = {"path": slot["result_path"], "sha256": slot["result_sha256"]}
            saved = read(cached["path"])
            validate_transcript(saved)
            if route == "w0":
                upstream_path = BRIDGES / f"{clip['id']}.json"
                upstream = identity(upstream_path)
                if artifacts.get(upstream["path"]) != upstream["sha256"]:
                    raise ValueError("W0 bridge not declared in retained CTC baseline")
                bridge = read(upstream_path)
            else:
                upstream_path = destination / "upstream" / f"{clip['id']}-{route}.json"
                bridge = {"schema_version": 1, "text": saved["text"],
                          "original_segments": deepcopy(saved["original_segments"]),
                          "input": deepcopy(saved["input"]), "offset_s": clip["offset"],
                          "source_start_seconds": clip["offset"], "duration_seconds": clip["duration"],
                          "source_result": cached, "new_asr_inference": False}
                upstream = {"path": str(upstream_path), "sha256": None}
                products.append((upstream, bridge))
            verify_upstream(bridge, saved, clip)
            for candidate in candidates:
                run_id = f"{name}-{clip['id']}-{route}-{candidate}"
                output = ROOT / ".local/results" / run_id / "result.json"
                if output.parent.exists():
                    raise FileExistsError("Preexisting run artifacts cannot enter a new batch")
                tasks.append({"id": run_id, "clip_id": clip["id"], "route": route,
                              "candidate": candidate, "cached_result": cached, "upstream": upstream,
                              "output": str(output)})
    plan = {"schema_version": 1, "id": name, "frozen": True, "scope": scope,
            "clips": clips, "baselines": baselines, "candidates": candidates, "routes": list(routes),
            "models": models, "tasks": tasks, "source_sha256": sources, "artifact_sha256": artifacts,
            "baseline_manifest": identity(BASE), "new_asr_inference": False,
            "zero_pad_seconds": zero_pad_seconds,
            "policy": "Same complete text and upstream search windows; failed windows retain cached text without timing; frozen existing evaluator"}
    for upstream, bridge in products:
        write_new(Path(upstream["path"]), bridge)
        upstream["sha256"] = digest(upstream["path"])
    for path, expected in sources.items():
        snapshot = destination / "source" / Path(path).relative_to(ROOT)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, snapshot)
        identity(snapshot, expected)
    write_new(destination / "plan.json", plan)
    return plan


def verify_plan(name: str) -> tuple[dict[str, Any], str]:
    validate_name(name)
    path = LOCAL / name / "plan.json"
    plan = read(path)
    if plan.get("id") != name or plan.get("frozen") is not True:
        raise ValueError("Matching frozen plan required")
    for source, expected in plan["source_sha256"].items():
        identity(source, expected)
        identity(LOCAL / name / "source" / Path(source).relative_to(ROOT), expected)
    for artifact, expected in plan["artifact_sha256"].items():
        identity(artifact, expected)
    for candidate, model in plan["models"].items():
        identity(model["path"], model["sha256"])
        for item in model["files"]:
            identity(item["path"], item["sha256"])
    for clip in plan["clips"]:
        verify_clip(clip)
    for task in plan["tasks"]:
        identity(task["upstream"]["path"], task["upstream"]["sha256"])
    return plan, digest(path)


def command(task: dict[str, Any], clip: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    model = plan["models"][task["candidate"]]
    result = [str(ROOT / ".local/envs/whisper-latest/Scripts/python.exe"),
              str(ROOT / "experiments/japanese_ctc/run.py")]
    values = {"audio": clip["audio"], "asr-result": task["upstream"]["path"],
              "align-model": model["model_dir"], "candidate": task["candidate"],
              "route": task["route"].upper(), "output": task["output"], "offset": clip["offset"],
              "zero-pad-seconds": plan.get("zero_pad_seconds", 0),
              "dll-dir": ROOT / ".local/tools/whisper-runtime-provisional"}
    for key, value in values.items():
        result.extend([f"--{key}", str(value)])
    return result


def validate_result(result: dict[str, Any], task: dict[str, Any], clip: dict[str, Any]) -> None:
    validate_transcript(result)
    saved = read(task["cached_result"]["path"])
    if (result["text"] != saved["text"] or result.get("input", {}).get("file_sha256") != clip["audio_sha256"]
            or result.get("input", {}).get("pcm_sha256") != clip["pcm_sha256"]
            or result.get("source_start_seconds") != clip["offset"]
            or result.get("original_segments") != read(task["upstream"]["path"])["original_segments"]):
        raise ValueError("CTC result changed complete cached text or input identity")


def validate_gpu(result: dict[str, Any]) -> None:
    aligner = result.get("devices", {}).get("aligner", {})
    forwards = aligner.get("forward_observation", [])
    records = result.get("experimental_alignment", {}).get("records", [])
    preprocessing = result.get("experimental_preprocessing", {}).get("records", [])
    if (not str(aligner.get("model", "")).startswith("cuda:") or not forwards
            or any(not str(device).startswith("cuda:") for device in forwards)):
        raise ValueError("Model/forward CUDA execution evidence required")
    successful = [record for record in records if not record.get("failure") and "decoder_input_device" in record]
    if not successful or not preprocessing:
        raise ValueError("Successful CUDA decoding and normalization evidence required")
    if (any(not str(record.get("actual_input_device", "")).startswith("cuda:") for record in preprocessing)
            or any(not str(record.get("decoder_input_device", "")).startswith("cuda:")
                   or not str(record.get("decoder_output_device", "")).startswith("cuda:") for record in successful)):
        raise ValueError("Normalization/decoder CUDA execution evidence required")


def run(name: str) -> None:
    plan, plan_hash = verify_plan(name)
    for task in plan["tasks"]:
        clip = next(c for c in plan["clips"] if c["id"] == task["clip_id"])
        progress = LOCAL / name / "progress" / f"{task['id']}.json"
        if progress.exists():
            verify_progress(read(progress), task, plan_hash)
            continue
        backend = command(task, clip, plan)
        harness_path = ROOT / ".local/results" / task["id"] / "manifest.json"
        if harness_path.parent.exists():
            raise RuntimeError("Interrupted run artifacts retained; use a new attempt identity")
        harness_command = [sys.executable, str(ROOT / "experiments/run_experiment.py"), "--id", task["id"],
                           "--audio", clip["audio"], "--reference", clip["source_srt"],
                           "--reference-sha256", clip["source_srt_sha256"], "--timeout", "3600", "--", *backend]
        print(json.dumps({"starting": task["id"]}), flush=True)
        completed = subprocess.run(harness_command, cwd=ROOT, check=False)
        record = {"plan_sha256": plan_hash, "task_id": task["id"], "command": backend,
                  "returncode": completed.returncode, "status": "failed", "artifacts": {},
                  "new_asr_inference": False}
        for path in (harness_path, Path(task["output"]), Path(task["output"]).with_suffix(".sha256")):
            if path.is_file():
                record["artifacts"][str(path)] = digest(path)
        try:
            harness = read(harness_path)
            if (harness.get("audio_sha256") != clip["audio_sha256"]
                    or harness.get("reference_unchanged") is not True or harness.get("command") != backend):
                raise ValueError("Harness input/reference/command verification failed")
            result = read(task["output"])
            validate_result(result, task, clip)
            validate_gpu(result)
            if completed.returncode == 0 and harness.get("status") == "completed" and result.get("status") == "ok":
                record["status"] = "completed"
            record["alignment_summary"] = result.get("alignment_summary")
            record["harness_wall_seconds"] = harness.get("wall_seconds")
        except (OSError, ValueError, KeyError) as exc:
            record["failure_reason"] = str(exc)
        verify_clip(clip)
        write_new(progress, record)
        print(json.dumps({"finished": task["id"], "status": record["status"]}), flush=True)
    verify_plan(name)


def verify_progress(record: dict[str, Any], task: dict[str, Any], plan_hash: str) -> None:
    if record.get("plan_sha256") != plan_hash or record.get("task_id") != task["id"]:
        raise ValueError("Progress belongs to another plan or task")
    if record.get("status") not in {"completed", "failed"}:
        raise ValueError("Batch has a nonterminal task")
    for path, expected in record["artifacts"].items():
        identity(path, expected)


def parity(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """Compare actual unit provenance and times without tolerance-based repairs."""
    keys = ("char_start", "char_end", "granularity", "time_source", "status", "start", "end")
    units = lambda doc: [{k: u.get(k) for k in keys} for u in doc.get("units", [])]
    left, right = units(new), units(old)
    return {"complete_text_equal": new["text"] == old["text"], "units_equal": left == right,
            "new_unit_count": len(left), "old_unit_count": len(right),
            "matching_unit_prefix": next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right))),
            "scope": "Direct Jonatas port against existing normalized standard CTC; differences remain diagnostic"}


def score(name: str, *, output: Path | None = None, bootstrap: bool = True) -> dict[str, Any]:
    plan, plan_hash = verify_plan(name)
    destination = LOCAL / name
    manifest_path = destination / "evaluation.json"
    output = output or destination / "analysis"
    if manifest_path.exists() or output.exists():
        raise FileExistsError("Use a new scoring snapshot")
    configurations = deepcopy(plan["baselines"])
    arms = {}
    diagnostics = []
    for task in plan["tasks"]:
        progress_path = destination / "progress" / f"{task['id']}.json"
        if not progress_path.is_file():
            raise ValueError("Batch is not terminal; every frozen slot must have progress")
        record = read(progress_path)
        verify_progress(record, task, plan_hash)
        clip = next(c for c in plan["clips"] if c["id"] == task["clip_id"])
        arm = f"{task['route']}-{task['candidate']}"
        config = arms.setdefault(arm, {"id": arm, "configuration_id": f"japanese-ctc-{arm}-v1", "runs": []})
        slot = {"clip_id": clip["id"], "run_id": task["id"], "execution_verified": record["status"] == "completed",
                "input_audio_path": clip["audio"], "input_audio_sha256": clip["audio_sha256"],
                "status": "completed" if record["status"] == "completed" else "alignment_failed",
                "failure_reason": record.get("failure_reason")}
        if record["status"] == "completed":
            result = read(task["output"])
            validate_result(result, task, clip)
            validate_gpu(result)
            slot.update(result_path=task["output"], result_sha256=digest(task["output"]))
        else:
            saved = read(task["cached_result"]["path"])
            failed = {**saved, "units": [], "cues": [], "status": "alignment_failed"}
            path = destination / "failed-text" / f"{task['id']}.json"
            write_new(path, failed)
            slot.update(result_path=str(path), result_sha256=digest(path))
        config["runs"].append(slot)
        row = {"task_id": task["id"], "progress": identity(progress_path), "status": slot["status"],
               "cached_text_retained": True, "harness_wall_seconds": record.get("harness_wall_seconds"),
               "alignment_summary": record.get("alignment_summary")}
        if task["candidate"] == "jonatas" and record["status"] == "completed":
            old_arm = "w0-ctc" if task["route"] == "w0" else f"{task['route']}-baseline"
            old_slot = next(r for c in plan["baselines"] if c["id"] == old_arm for r in c["runs"] if r["clip_id"] == clip["id"])
            row["jonatas_parity"] = parity(result, read(old_slot["result_path"]))
        diagnostics.append(row)
    configurations.extend(arms.values())
    manifest = {"schema_version": 1, "manifest_id": name, "frozen": True, "strict_hashes": True,
                "clips": plan["clips"], "configurations": configurations, "source_sha256": plan["source_sha256"],
                "assembly": {"plan_sha256": plan_hash, "scope": plan["scope"], "receipts": diagnostics}}
    write_new(manifest_path, manifest)
    report = evaluator.build(manifest_path, output, bootstrap=bootstrap)
    write_new(output / "ctc-diagnostics.json", manifest["assembly"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run", "score"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--candidate", choices=CANDIDATES, action="append")
    parser.add_argument("--routes", default=",".join(ROUTES))
    parser.add_argument("--scope", choices=("pilot", "full"), default="pilot")
    parser.add_argument("--zero-pad-seconds", type=float, default=0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-bootstrap", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        value = prepare(args.name, args.candidate or [], routes=tuple(args.routes.split(",")),
                        scope=args.scope, zero_pad_seconds=args.zero_pad_seconds)
        print(json.dumps({"plan": str(LOCAL / args.name / "plan.json"), "task_count": len(value["tasks"])}))
    elif args.action == "run":
        run(args.name)
    else:
        value = score(args.name, output=args.output, bootstrap=not args.no_bootstrap)
        print(json.dumps({"table_rows": value["pooled"]["table_rows"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
