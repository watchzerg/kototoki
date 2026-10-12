"""Sequential immutable flow plans sharing one externally managed model server."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import sys
import time
from typing import Any, Callable

from experiments.translation_eval.runner import dump, read_json, safe_id, sha
from .worker import CANDIDATE, append_json, execute_plan, load_plan, utc_now

SCHEMA = "hy30-flow-dispatch-v1"


def load_dispatch(path: Path) -> list[dict[str, Any]]:
    """Validate every child plan and source hash before the first execution."""
    plan = read_json(path)
    if (not isinstance(plan, dict) or set(plan) != {"schema", "entries"}
            or plan["schema"] != SCHEMA or not isinstance(plan["entries"], list) or not plan["entries"]):
        raise ValueError("dispatch requires hy30-flow-dispatch-v1 with nonempty ordered entries only")
    labels, result = set(), []
    for entry in plan["entries"]:
        if (not isinstance(entry, dict) or set(entry) != {"label", "plan", "plan_sha256"}
                or not isinstance(entry["plan"], str)):
            raise ValueError("dispatch entries accept only label, plan, plan_sha256")
        label = safe_id(entry["label"])
        if label in labels:
            raise ValueError("dispatch labels must be unique")
        labels.add(label)
        child = Path(entry["plan"])
        child = child.resolve() if child.is_absolute() else (path.parent / child).resolve()
        if sha(child) != entry["plan_sha256"]:
            raise ValueError("dispatch child plan hash changed")
        frozen, loaded = load_plan(child)
        result.append({"label": label, "plan": str(child), "plan_sha256": entry["plan_sha256"],
                       "stage": frozen["stage"], "lane": frozen.get("lane", "V2-native-adapted"),
                       "source_inputs": [{"path": str(inputs), "sha256": item["input_sha256"],
                                          "windows": len(windows), "workload_label": item["label"]}
                                         for item, inputs, windows in loaded]})
    return result


def execute_dispatch(args: argparse.Namespace, *, execute_fn: Callable[..., int] = execute_plan,
                     clock: Callable[[], float] = time.perf_counter) -> int:
    started = clock()
    if args.candidate != CANDIDATE:
        raise ValueError("dispatch is fixed to the adopted APEX-I-Compact candidate")
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("dispatch output must be a fresh directory")
    initial_sha = sha(args.session_plan)
    entries = load_dispatch(args.session_plan)
    if sha(args.session_plan) != initial_sha:
        raise ValueError("dispatch plan changed during preflight")
    output.mkdir(parents=True)
    (output / "dispatch-plan.json").write_bytes(args.session_plan.read_bytes())
    (output / "dispatch-source.py").write_bytes(Path(__file__).read_bytes())
    worker_source = Path(__file__).with_name("worker.py")
    code_hashes = {"dispatch.py": sha(Path(__file__)), "worker.py": sha(worker_source)}
    dump(output / "dispatch.json", {"schema": SCHEMA, "created_at_utc": utc_now(),
         "dispatch_plan_path": str(args.session_plan.resolve()), "dispatch_plan_sha256": initial_sha,
         "candidate": args.candidate, "entries": entries, "code_sha256": code_hashes,
         "server_url": args.server_url, "engine_manifest": str(args.engine_manifest),
         "context_size": args.context_size,
         "cost_scope_zh": "模型由父 runtime 加载一次。冷加载、卸载和共享资源峰值仅在父 runtime 记账；子计划保留自身推理成本。"})
    events = output / "workload-ledger.jsonl"
    records, stopped = [], None
    for entry in entries:
        child_output = output / entry["label"]
        if stopped:
            records.append({**entry, "output_dir": str(child_output), "status": "not_run",
                            "exit_code": None, "elapsed_seconds": None, "reason": "previous_child_failed"})
            append_json(events, {"label": entry["label"], "status": "not_run", "reason": "previous_child_failed", "at_utc": utc_now()})
            continue
        child_args = argparse.Namespace(**deepcopy(vars(args)))
        child_args.session_plan = Path(entry["plan"])
        child_args.output_dir = child_output
        child_started = clock()
        append_json(events, {"label": entry["label"], "status": "started", "at_utc": utc_now()})
        error_kind = error_message = None
        try:
            if sha(child_args.session_plan) != entry["plan_sha256"]:
                raise ValueError("child plan changed after dispatch preflight")
            load_plan(child_args.session_plan)  # Recheck source hashes between children.
            code = execute_fn(child_args)
            if type(code) is not int or code < 0:
                raise ValueError("worker must return a nonnegative integer exit code")
        except Exception as exc:
            code, error_kind, error_message = 1, type(exc).__name__, str(exc)[:2000]
        status = "succeeded" if code == 0 else "failed"
        record = {**entry, "output_dir": str(child_output), "status": status, "exit_code": code,
                  "elapsed_seconds": clock() - child_started, "error_kind": error_kind,
                  "error_message": error_message}
        records.append(record)
        append_json(events, {"label": entry["label"], "status": "phase_finished" if code == 0 else "interrupted",
                             "exit_code": code, "at_utc": utc_now()})
        if code:
            stopped = entry["label"]
        dump(output / "dispatch-progress.json", {"schema": SCHEMA, "entries": records,
                                                  "stopped_after": stopped})
    dump(output / "dispatch-completion.json", {"schema": SCHEMA, "complete": stopped is None,
         "stopped_after": stopped, "entries": records, "finished_at_utc": utc_now(),
         "whole_wall_seconds": clock() - started, "code_sha256": code_hashes,
         "dispatch_plan_sha256": initial_sha, "cold_load_seconds": None,
         "resource_peak": None, "shared_cost_reason": "record once in parent managed runtime",
         "resume_policy": "fresh dispatch directory only; preserve successful child outputs unchanged"})
    return 1 if stopped else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="复用同一个受管理模型的冻结计划串行调度")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--session-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--engine-manifest", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=4096)
    parser.add_argument("--asset-manifest", type=Path, action="append")
    parser.add_argument("--stop-on-oom", action="store_true")
    args = parser.parse_args()
    try:
        return execute_dispatch(args)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print(f"dispatch error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
