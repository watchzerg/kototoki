"""Freeze, execute serial sessions, and recover to new immutable directories."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from .core import (CANDIDATES, RECIPE, append_event, input_record, is_oom,
                   inspect_workload, make_schedule, pollution_evidence, recovery_subset, release_evidence, rotation, sha256, utc_now, validate_expanded_corpus, write_json)


def freeze(args: argparse.Namespace) -> int:
    inputs = {"smoke": input_record(args.smoke, 15), "dev": input_record(args.dev, 41)}
    if not set(inputs["smoke"]["window_ids"]) <= set(inputs["dev"]["window_ids"]):
        raise ValueError("Smoke must be a subset of frozen dev")
    if args.regression:
        inputs["regression"] = input_record(args.regression, 83)
    if args.expanded:
        inputs["expanded"] = input_record(args.expanded, None if args.allow_scale_shortfall else 1200)
        if not args.expanded_corpus_freeze:
            raise ValueError("Expanded formal input requires --expanded-corpus-freeze after completed double review")
    corpus_gate = validate_expanded_corpus(args.expanded_corpus_freeze, inputs["expanded"]) if args.expanded else None
    if "expanded" in inputs:
        existing = set(inputs["dev"]["window_ids"]) | set(inputs.get("regression", {}).get("window_ids", []))
        if existing & set(inputs["expanded"]["window_ids"]):
            raise ValueError("Expanded window IDs overlap old dev/regression")
    records = []
    for path in args.asset_manifest:
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        records.extend(rows)
    ids = [item["id"] for item in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate asset IDs across manifests")
    selected = {item["id"]: item for item in records if item["id"] in CANDIDATES}
    if set(selected) != set(CANDIDATES) or any(item.get("status") != "verified" for item in selected.values()):
        raise ValueError("All four verified candidate identities are required")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source-inputs"
    source.mkdir()
    for name, record in inputs.items():
        copy = source / f"{name}.jsonl"
        copy.write_bytes(Path(record["path"]).read_bytes())
        record["original_path"] = record["path"]
        record["path"] = str(copy)
    formal = "regression" in inputs and "expanded" in inputs
    engine = args.engine.resolve()
    identity = args.engine_identity.resolve()
    code = list(Path(__file__).parent.glob("*.py")) + list((Path(__file__).parent.parent / "translation_demo").glob("*.py"))
    code.extend([Path(__file__).parent.parent / "translation_demo_runtime.py", Path(__file__).parent.parent / "translation_monitor.py"])
    project = Path(__file__).resolve().parents[2]
    for name in ("translation_corpus", "translation_eval", "translation_judge"):
        code.extend((project / "experiments" / name).rglob("*.py"))
    code.extend(project / "experiments" / name for name in (
        "translation_four_stats.py", "translation_reference_judge.py",
        "translation_corpus/reference-review-prompt.md"))
    code.extend((project / "docs" / name) for name in (
        "plans/hy30-four-quantization-comparison.md", "agents/subtitle-translation-evaluation.md",
        "testing/translation-model-evaluation.md"))
    code.extend(path.resolve() for path in args.freeze_file)
    snapshots = output / "source-snapshot"
    snapshots.mkdir()
    copied = {}
    for index, path in enumerate(dict.fromkeys(path for path in code if path.exists())):
        target = snapshots / f"{index:04d}-{path.name}"
        target.write_bytes(path.read_bytes())
        copied[str(path.resolve())] = str(target)
    frozen = {"schema": "hy30-four-quantization-v1", "created_at_utc": utc_now(),
              "recipe": RECIPE, "candidate_ids": list(CANDIDATES), "assets": selected,
              "asset_manifests": [{"path": str(path.resolve()), "sha256": sha256(path)} for path in args.asset_manifest],
              "engine": str(engine), "engine_sha256": sha256(engine),
              "engine_identity": str(identity), "engine_identity_sha256": sha256(identity),
              "dll_sha256": {str(path.resolve()): sha256(path) for path in engine.parent.glob("*.dll")},
              "inputs": inputs, "warmup_window_ids": inputs["dev"]["window_ids"][:1],
              "rotation": rotation(), "schedule": make_schedule(formal),
              "formal_ready": formal, "expanded_scale_target": 1200,
              "expanded_corpus_gate": corpus_gate,
              "expanded_scale_sufficient": inputs.get("expanded", {}).get("windows", 0) >= 1200,
              "stability_seconds": 1800, "idle_baseline_seconds": 30,
              "pollution_criteria": {"shared_experiment_service": "contaminated",
                                     "gpu_driver_reset_error": "contaminated",
                                     "idle_memory_difference_mib": 512,
                                     "comparison_baseline": "first formal performance session idle median",
                                     "policy": "retain all original rounds; independently index reruns, never select by measured speed"},
              "source_sha256": {str(path.resolve()): sha256(path) for path in code if path.exists()},
              "source_snapshots": copied,
              "quality_policy": "first formal-round terminal result; never choose later rounds by score or output",
              "source_firewall": "exact demo schema; no reference/candidate scores/judge material read"}
    write_json(output / "freeze.json", frozen)
    print(json.dumps({"freeze": str(output / "freeze.json"), "formal_ready": formal}, ensure_ascii=False))
    return 0


def verify_freeze(frozen: dict[str, Any]) -> None:
    if frozen["recipe"] != RECIPE or frozen["rotation"] != rotation():
        raise ValueError("Frozen recipe or rotation differs from comparison contract")
    entries = [(Path(frozen["engine"]), frozen["engine_sha256"]),
               (Path(frozen["engine_identity"]), frozen["engine_identity_sha256"])]
    entries.extend((Path(item["path"]), item["sha256"]) for item in frozen["asset_manifests"])
    entries.extend((Path(item["path"]), item["sha256"]) for item in frozen["inputs"].values())
    entries.extend((Path(path), digest) for path, digest in frozen["source_sha256"].items())
    entries.extend((Path(path), digest) for path, digest in frozen["dll_sha256"].items())
    gate = frozen.get("expanded_corpus_gate")
    if gate:
        entries.append((Path(gate["path"]), gate["sha256"]))
        entries.extend((Path(item["path"]), item["sha256"]) for item in gate["files"].values())
    for path, digest in entries:
        if sha256(path) != digest:
            raise ValueError(f"Frozen file changed: {path}")
    for original, snapshot in frozen.get("source_snapshots", {}).items():
        if sha256(Path(snapshot)) != frozen["source_sha256"][original]:
            raise ValueError("Frozen source snapshot changed")
    for item in frozen["inputs"].values():
        input_record(Path(item["path"]))


def session_plan(task: dict[str, Any], frozen: dict[str, Any], output: Path,
                 evidence: dict[str, Path] | None = None) -> Path:
    inputs = frozen["inputs"]
    dev = Path(inputs["dev"]["path"])
    warmup = output / "warmup.jsonl"
    rows = [json.loads(line) for line in dev.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    by_id = {row["id"]: row for row in rows}
    with warmup.open("x", encoding="utf-8") as stream:
        for window_id in frozen["warmup_window_ids"]:
            stream.write(json.dumps(by_id[window_id], ensure_ascii=False) + "\n")
    workloads = [{"label": "warmup", "inputs": str(warmup), "input_sha256": sha256(warmup), "quality_sample": False}]
    if task["stage"] == "preflight":
        names = ["smoke", "dev"]
    elif task["stage"] == "performance":
        names = ["regression", "expanded"]
    else:
        names = []
    for name in names:
        if evidence and name in evidence:
            directory = evidence[name]
            audit = inspect_workload(directory, inputs[name]["window_ids"])
            old = json.loads((directory / "run.json").read_text(encoding="utf-8"))
            if not audit["complete"] or audit["failed"] or old["input_sha256"] != inputs[name]["sha256"] or old["candidate"] != task["candidate"]:
                raise ValueError("Existing preflight evidence incomplete, failed, or different frozen source/candidate")
            if old.get("settings", {}).get("context_size") != 4096 or old["settings"].get("n_predict") != 1024:
                raise ValueError("Existing preflight recipe differs")
            if old.get("engine", {}).get("executable_sha256") != frozen["engine_sha256"] or old.get("asset", {}).get("sha256") != frozen["assets"][task["candidate"]]["sha256"]:
                raise ValueError("Existing preflight engine or asset identity differs")
            from experiments.translation_demo_runtime import validate_residency
            validate_residency(old.get("engine", {}).get("residency", {}), 99, False)
            if old["engine"].get("gpu_layers_requested") != 99 or old["engine"].get("cpu_offload_allowed"):
                raise ValueError("Existing preflight evidence differs from full-GPU recipe")
            write_json(output / f"retained-{name}.json", {"source_dir": str(directory.resolve()),
                       "run_sha256": sha256(directory / "run.json"), "complete_windows": audit["attempted"],
                       "window_sha256": {window_id: sha256(directory / f"window-{window_id}.json") for window_id in inputs[name]["window_ids"]}})
            continue
        workloads.append({"label": name, "inputs": inputs[name]["path"], "input_sha256": inputs[name]["sha256"],
                          "quality_sample": task["quality_round"]})
    if task["stage"] in ("preflight", "stability"):
        workloads.append({"label": "near-budget-probe", "inputs": str(warmup), "input_sha256": sha256(warmup),
                          "probe": True, "quality_sample": False})
    if task["stage"] == "stability":
        workloads.append({"label": "repeated-source-block", "inputs": str(warmup), "input_sha256": sha256(warmup),
                          "repeat_until_seconds": frozen["stability_seconds"], "quality_sample": False})
    plan = output / "session-plan.json"
    write_json(plan, {"recipe": RECIPE, "task": task, "workloads": workloads})
    return plan


def read_histories(paths: list[Path], freeze_hash: str) -> list[dict[str, Any]]:
    history = []
    visited, active = set(), set()
    def visit(path: Path) -> None:
        path = path.resolve()
        if path in active:
            raise ValueError("Cyclic recovery history")
        if path in visited:
            return
        active.add(path)
        run = json.loads((path / "attempt.json").read_text(encoding="utf-8"))
        if run["freeze_sha256"] != freeze_hash:
            raise ValueError("Recovery attempts must use identical freeze hash")
        for parent in run.get("history", []):
            visit(Path(parent))
        ledger = path / "schedule-ledger.jsonl"
        if ledger.exists():
            for event in (json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()):
                for artifact, digest in event.get("artifact_sha256", {}).items():
                    if sha256(Path(artifact)) != digest:
                        raise ValueError(f"Historical task artifact changed: {artifact}")
                history.append(event)
        active.remove(path)
        visited.add(path)
    for path in paths:
        visit(path)
    return history


def execute_session(command: list[str], output: Path, baseline_seconds: float) -> int:
    # The existing runtime owns its monitor, idle baseline, model process, and cleanup.
    command = [*command, "--idle-baseline-seconds", str(baseline_seconds)]
    with (output / "runtime.stdout.log").open("xb") as stdout, (output / "runtime.stderr.log").open("xb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0)
        try:
            return process.wait()
        except KeyboardInterrupt:
            # Let Python runtime's finally block stop only its own server/worker.
            process.send_signal(__import__("signal").CTRL_BREAK_EVENT if sys.platform == "win32" else __import__("signal").SIGINT)
            process.wait(timeout=30)
            raise


def run(args: argparse.Namespace) -> int:
    frozen = json.loads(args.freeze.read_text(encoding="utf-8"))
    verify_freeze(frozen)
    digest = sha256(args.freeze)
    history = read_histories(args.resume_from, digest)
    if args.diagnostic_oom_retry:
        if args.stage != "preflight" or not args.candidate or len(args.candidate) != 1:
            raise ValueError("Diagnostic OOM retry requires --stage preflight and exactly one candidate")
        candidate = args.candidate[0]
        prior = [event for event in history if event.get("candidate") == candidate]
        if any(event.get("diagnostic_oom_retry") for event in prior):
            raise ValueError("This candidate already used its one diagnostic OOM retry")
        oom_event = next((event for event in reversed(prior) if event.get("oom")), None)
        if not oom_event:
            raise ValueError("Diagnostic retry requires retained explicit OOM evidence")
        final_path = Path(oom_event["artifact_dir"]) / "session" / "runtime" / "runtime-final.json"
        prior_runtime = json.loads(final_path.read_text(encoding="utf-8"))
        if prior_runtime.get("server_process_exited") is not True:
            raise ValueError("OOM process cleanup not proven; diagnostic retry blocked")
        if not release_evidence(final_path.parent)["memory_returned"]:
            raise ValueError("OOM memory return not proven; diagnostic retry blocked")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "attempt.json", {"created_at_utc": utc_now(), "freeze": str(args.freeze.resolve()),
               "freeze_sha256": digest, "history": [str(path.resolve()) for path in args.resume_from],
               "stage": args.stage, "port": args.port})
    ledger = output / "schedule-ledger.jsonl"
    completed = {event["task_id"] for event in history if event.get("status") == "completed"}
    capacity_failed = set()
    for event in history:
        if event.get("stage") == "preflight" and event.get("status") == "completed":
            capacity_failed.discard(event["candidate"])
        elif event.get("capacity_failed"):
            capacity_failed.add(event["candidate"])
    if args.diagnostic_oom_retry:
        capacity_failed.discard(args.candidate[0])
    evidence = {}
    if args.smoke_evidence or args.dev_evidence:
        if args.stage != "preflight" or not args.candidate or len(args.candidate) != 1:
            raise ValueError("Evidence reuse requires preflight and exactly one candidate")
        evidence = {name: path for name, path in (("smoke", args.smoke_evidence), ("dev", args.dev_evidence)) if path}
    common_baseline = next((event["pollution"]["idle_baseline"] for event in history
                            if event.get("stage") == "performance" and event.get("pollution", {}).get("idle_baseline")), None)
    failures = 0
    blocked = 0
    for task in frozen["schedule"]:
        if args.stage != "all" and task["stage"] != args.stage:
            continue
        if args.candidate and task["candidate"] not in args.candidate:
            continue
        event = {"task_id": task["id"], "candidate": task["candidate"], "stage": task["stage"]}
        if task["id"] in completed:
            append_event(ledger, {**event, "status": "retained", "reason": "completed immutable historical task"})
            continue
        if task["candidate"] in capacity_failed:
            append_event(ledger, {**event, "status": "not_run", "reason": "capacity preflight failed"})
            blocked += 1
            continue
        if task["stage"] != "preflight" and f"preflight-{task['candidate']}" not in completed:
            append_event(ledger, {**event, "status": "not_run", "reason": "successful full smoke/dev required"})
            failures += 1
            blocked += 1
            continue
        task_output = output / task["id"]
        task_output.mkdir()
        plan = session_plan(task, frozen, task_output, evidence)
        command = [sys.executable, "-X", "utf8", "-m", "experiments.translation_demo_runtime",
                   "--candidate", task["candidate"], "--inputs", frozen["inputs"]["dev"]["path"],
                   "--output-dir", str(task_output / "session"), "--engine", frozen["engine"],
                   "--engine-identity", frozen["engine_identity"], "--layers", "99", "--context-size", "4096",
                   "--port", str(args.port), "--session-worker", "experiments.translation_four_quantization.worker",
                   "--session-plan", str(plan)]
        for item in frozen["asset_manifests"]:
            command.extend(["--asset-manifest", item["path"]])
        append_event(ledger, {**event, "status": "started", "command": command,
                              "diagnostic_oom_retry": args.diagnostic_oom_retry,
                              "quality_round": task["quality_round"], "partial_history_policy": "fresh full performance rerun; preserve historical first quality results separately"})
        started = time.perf_counter()
        code = execute_session(command, task_output, frozen["idle_baseline_seconds"])
        runtime_path = task_output / "session" / "runtime" / "runtime-final.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8")) if runtime_path.exists() else {}
        worker_path = task_output / "session" / "translation" / "workload-ledger.jsonl"
        worker = [json.loads(line) for line in worker_path.read_text(encoding="utf-8").splitlines() if line.strip()] if worker_path.exists() else []
        oom = runtime.get("runtime_error_kind") == "oom" or is_oom(runtime) or is_oom(worker)
        error = (task_output / "runtime.stderr.log").read_text(encoding="utf-8", errors="replace")
        oom |= is_oom(error)
        pollution = pollution_evidence(task_output / "session" / "runtime", common_baseline if task["stage"] == "performance" else None)
        if "port already occupied" in error.lower():
            pollution["contaminated"] = True
            pollution["reasons"].append("unauthorized_shared_service")
        if task["stage"] == "performance" and common_baseline is None:
            common_baseline = pollution["idle_baseline"]
        status = "completed" if code == 0 and not pollution["contaminated"] else "contaminated" if pollution["contaminated"] else "failed"
        resource_events = task_output / "session" / "runtime" / "resource-events.jsonl"
        load_at = next((row.get("utc") for row in (json.loads(line) for line in resource_events.read_text(encoding="utf-8").splitlines()) if row.get("phase") == "load"), None) if resource_events.exists() else None
        terminal_at = [row["terminal_artifacts_observed_at_utc"] for row in worker if row.get("terminal_artifacts_observed_at_utc")]
        end_to_end = (datetime.fromisoformat(max(terminal_at)) - datetime.fromisoformat(load_at)).total_seconds() if terminal_at and load_at else None
        warmup_times = [row["translation_wall_seconds"] for row in worker if row.get("label") == "warmup" and row.get("translation_wall_seconds") is not None]
        session_timing = {"cold_load_seconds": runtime.get("cold_load_seconds"), "warmup_seconds": sum(warmup_times) if warmup_times else None,
                          "load_started_at_utc": load_at, "terminal_artifacts_at_utc": max(terminal_at) if terminal_at else None,
                          "end_to_end_load_to_terminal_seconds": end_to_end,
                          "scope": "load phase through terminal translation artifacts, includes warmup; excludes idle baseline/unload"}
        final = {**event, "status": status, "exit_code": code, "oom": oom,
                 "diagnostic_oom_retry": args.diagnostic_oom_retry,
                 "elapsed_seconds_including_baseline": time.perf_counter() - started,
                 "artifact_dir": str(task_output), "capacity_failed": task["stage"] == "preflight" and code != 0,
                 "pollution": pollution, "session_timing": session_timing}
        final["artifact_sha256"] = {str(path.resolve()): sha256(path) for pattern in (
            "window-*.json", "run.json", "workload-summary.json", "worker-completion.json", "results.jsonl", "ledger.jsonl")
            for path in (task_output / "session" / "translation").rglob(pattern)}
        append_event(ledger, final)
        if status == "completed":
            completed.add(task["id"])
        else:
            failures += 1
            if task["stage"] == "preflight":
                capacity_failed.add(task["candidate"])
        print(json.dumps(final, ensure_ascii=False), flush=True)
    write_json(output / "attempt-completion.json", {"ended_at_utc": utc_now(), "failed_sessions": failures, "blocked_sessions": blocked,
               "capacity_failed": sorted(capacity_failed), "oom_retry_policy": "no automatic diagnostic retry; explicit new immutable attempt allowed at most once"})
    return 1 if failures or blocked else 0


def export_quality(args: argparse.Namespace) -> int:
    """Export first formal attempt and explicit missingness for evaluation."""
    frozen = json.loads(args.freeze.read_text(encoding="utf-8"))
    verify_freeze(frozen)
    history = read_histories(args.attempt, sha256(args.freeze))
    expected = frozen["inputs"][args.split]["window_ids"]
    task_id = f"round-1-{args.candidate}"
    relevant = [event for event in history if event.get("task_id") == task_id]
    terminal = next((event for event in relevant
                     if event.get("status") in {"completed", "failed", "contaminated", "not_run"}), None)
    if terminal is None:
        raise ValueError("First formal-round session has no terminal disposition")
    if terminal["status"] == "not_run":
        if any(event.get("status") == "started" for event in relevant[:relevant.index(terminal)]):
            raise ValueError("An attempted first-round session cannot become not_run")
        directories = []
    else:
        if not terminal.get("artifact_dir"):
            raise ValueError("First formal-round terminal lacks artifact directory")
        directories = [Path(terminal["artifact_dir"]) / "session" / "translation" / args.split / "run-00001"]
    retained = {}
    for directory in directories:
        for window_id, row in inspect_workload(directory, expected)["rows"].items():
            retained.setdefault(window_id, (row, directory / f"window-{window_id}.json"))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with (output / "ledger.jsonl").open("x", encoding="utf-8") as ledger, (output / "results.jsonl").open("x", encoding="utf-8") as results, (output / "schedule.jsonl").open("x", encoding="utf-8") as schedule:
        for window_id in expected:
            if window_id not in retained:
                schedule.write(json.dumps({"window_id": window_id, "status": "not_run",
                                           "reason": "No durable first-formal-round window result; historical preflight/stress/later rounds excluded"}) + "\n")
                continue
            row, artifact = retained[window_id]
            (output / artifact.name).write_bytes(artifact.read_bytes())
            ledger.write(json.dumps(row, ensure_ascii=False) + "\n")
            results.write(json.dumps({"id": window_id, "translations": row.get("translations", {}),
                                      "elapsed_seconds": row.get("elapsed_seconds")}, ensure_ascii=False) + "\n")
    write_json(output / "quality-provenance.json", {"freeze_sha256": sha256(args.freeze),
               "candidate": args.candidate, "split": args.split, "expected": len(expected),
               "attempted": len(retained), "not_run": len(expected) - len(retained),
               "first_formal_artifacts": {key: str(value[1].resolve()) for key, value in retained.items()},
               "policy": "first terminal session only including failure and unattempted tail; no recovery or later round substitution"})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="四量化串行冻结、运行与不可变恢复")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("freeze")
    for name in ("smoke", "dev", "engine", "engine-identity", "output-dir"):
        setup.add_argument(f"--{name}", type=Path, required=True)
    setup.add_argument("--regression", type=Path)
    setup.add_argument("--expanded", type=Path)
    setup.add_argument("--expanded-corpus-freeze", type=Path)
    setup.add_argument("--allow-scale-shortfall", action="store_true")
    setup.add_argument("--asset-manifest", action="append", type=Path, required=True)
    setup.add_argument("--freeze-file", action="append", type=Path, default=[], help="额外冻结语料 manifest／构建审核提示／统计脚本")
    execute = commands.add_parser("run")
    execute.add_argument("--freeze", type=Path, required=True)
    execute.add_argument("--output-dir", type=Path, required=True)
    execute.add_argument("--resume-from", type=Path, action="append", default=[])
    execute.add_argument("--stage", choices=("all", "preflight", "performance", "stability"), default="all")
    execute.add_argument("--candidate", choices=CANDIDATES, action="append")
    execute.add_argument("--port", type=int, default=8080)
    execute.add_argument("--diagnostic-oom-retry", action="store_true")
    execute.add_argument("--smoke-evidence", type=Path)
    execute.add_argument("--dev-evidence", type=Path)
    recovery = commands.add_parser("recover-workload")
    recovery.add_argument("--inputs", type=Path, required=True)
    recovery.add_argument("--history", type=Path, action="append", required=True)
    recovery.add_argument("--output-dir", type=Path, required=True)
    export = commands.add_parser("export-quality")
    export.add_argument("--freeze", type=Path, required=True)
    export.add_argument("--candidate", choices=CANDIDATES, required=True)
    export.add_argument("--split", choices=("regression", "expanded"), required=True)
    export.add_argument("--attempt", type=Path, action="append", required=True)
    export.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        return freeze(args)
    if args.command == "run":
        return run(args)
    if args.command == "export-quality":
        return export_quality(args)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    record = recovery_subset(args.inputs, args.history, args.output_dir / "pending-inputs.jsonl")
    write_json(args.output_dir / "recovery.json", record)
    print(json.dumps({"pending": len(record["pending_ids"]), "retained": len(record["retained"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
