"""Required prospective confirmation queue wrapper; no runtime changes.

The caller obtains separate trusted lock/unseal SHA256 pins from the custody
ledger. This wrapper cannot establish ledger authenticity. Direct v2_trial is
still callable, but is not an authority-bound confirmation launch. Queue order
is for quality generation only; it is not the formal ABBA timing experiment.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable

from . import v2_confirmation as contract

PLAN_SCHEMA = "hy30-confirmation-dispatch-plan-v1"
RECEIPT_SCHEMA = "hy30-confirmation-dispatch-receipt-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pin(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Trusted custody SHA256 pins must be explicit lowercase hexadecimal")


def _authority(lock: dict[str, str], unseal: dict[str, str], lock_sha: str, unseal_sha: str,
               policy_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _pin(lock_sha)
    _pin(unseal_sha)
    if lock.get("sha256") != lock_sha or unseal.get("sha256") != unseal_sha:
        raise ValueError("Dispatch authority differs from the separately registered custody pins")
    value = contract.validate_lock(lock, expected_policy_sha256=policy_sha)
    first = Path(value["baseline"]["cards"][0]["card"]["path"])
    contract.validate_confirmation_dispatch(first, lock, unseal, expected_policy_sha256=policy_sha)
    return value, {"lock": contract._pointer(lock), "unseal": contract._pointer(unseal),
                   "registered_lock_sha256": lock_sha, "registered_unseal_sha256": unseal_sha}


def _payload(lock: dict[str, str], unseal: dict[str, str], output_root: Path,
             lock_sha: str, unseal_sha: str, policy_sha: str) -> dict[str, Any]:
    value, authority = _authority(lock, unseal, lock_sha, unseal_sha, policy_sha)
    root = output_root.resolve()
    jobs = []
    for group in [value["baseline"], *value["candidates"]]:
        for card in group["cards"]:
            index = len(jobs) + 1
            jobs.append({"job_id": f"trial-{index:03d}", "candidate_alias": group["candidate_alias"],
                         "seed": card["seed"], "card": card["card"],
                         "output": str(root / f"trial-{index:03d}"), "expected_quality_windows": 48})
    return {"schema": PLAN_SCHEMA, "state": "frozen_prospective_queue", "scope_mode": contract.SCOPE_MODE,
            "confirmation_dispatch_authority": authority,
            "confirmation_scope": {"source_scope_sha256": value["source_scope_sha256"],
                "source_scope": value["source_scope"], "evaluation_contract": value["evaluation_contract"],
                "generation_seeds": list(contract.SEEDS), "windows_per_group_seed": 48},
            "output_root": str(root), "jobs": jobs,
            "order": "C0_then_locked_candidate_order_each_in_frozen_seed_order",
            "quality_generation_only": True, "formal_ABBA_timing": False,
            "stop_on_failure": True, "automatic_retry": False, "resume_or_output_reuse": False,
            "new_quality_seeds": False, "screening_quality_history_preserved": True,
            "required_native_session": "same_locked_seed_identical_empty_new_managed_session",
            "implementation": contract.pointer(Path(__file__))}


def freeze_dispatch_plan(lock_pointer: dict[str, str], unseal_pointer: dict[str, str],
                         output_root: Path, output_plan: Path, *, registered_lock_sha256: str,
                         registered_unseal_sha256: str,
                         expected_policy_sha256: str = contract.POLICY_SHA256) -> dict[str, str]:
    """Freeze all jobs under one custody authority; no source decoding or launch."""
    root, plan = output_root.resolve(), output_plan.resolve()
    if root.exists():
        raise FileExistsError("Confirmation output root must be new")
    if plan.is_relative_to(root):
        raise ValueError("Frozen queue plan must be outside its future output root")
    value = _payload(lock_pointer, unseal_pointer, root, registered_lock_sha256,
                     registered_unseal_sha256, expected_policy_sha256)
    value["frozen_at_utc"] = _now()
    return contract._write_new(plan, value)


def validate_dispatch_plan(plan_pointer: dict[str, str], *, registered_lock_sha256: str,
                           registered_unseal_sha256: str,
                           expected_policy_sha256: str = contract.POLICY_SHA256) -> dict[str, Any]:
    """Rebuild the entire queue from the original authority, never from job inputs."""
    identity = contract._pointer(plan_pointer)
    value = contract._json(Path(identity["path"]))
    authority = value["confirmation_dispatch_authority"]
    expected = _payload(authority["lock"], authority["unseal"], Path(value["output_root"]),
                        registered_lock_sha256, registered_unseal_sha256, expected_policy_sha256)
    contract._utc(value["frozen_at_utc"])
    expected["frozen_at_utc"] = value["frozen_at_utc"]
    if contract._hash(expected) != contract._hash(value):
        raise ValueError("Frozen queue, ordering or canonical dispatch authority changed")
    if Path(identity["path"]).is_relative_to(Path(value["output_root"])):
        raise ValueError("Queue plan cannot occupy its future output root")
    return value


def _journal(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _native(job: dict[str, Any], accepted_at: str) -> dict[str, Any]:
    path = Path(job["output"]) / "trial-completion.json"
    if not path.exists():
        return {"native_trial": None, "native_total_flow_seconds": None,
                "native_status": "missing", "native_complete": False}
    identity = contract.pointer(path)
    value = contract._json(path)
    card = job["card"]
    seconds = value.get("total_flow_seconds")
    if (value.get("schema") != "hy30-flow-trial-v2" or value.get("card_sha256") != card["sha256"]
            or Path(value.get("card_path", "")).resolve() != Path(card["path"])
            or value.get("card") != contract._json(Path(card["path"]))
            or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0
            or contract._utc(value["started_at_utc"]) < contract._utc(accepted_at)
            or contract._utc(value["finished_at_utc"]) < contract._utc(value["started_at_utc"])
            or contract._utc(value["finished_at_utc"]) > datetime.now(timezone.utc)):
        raise ValueError("Native trial receipt identity, chronology or complete-flow cost is invalid")
    expected = value.get("expected_scene_ids")
    complete = (value.get("status") == "complete" and type(value.get("runtime_exit_code")) is int
                and value["runtime_exit_code"] == 0
                and isinstance(expected, list) and bool(expected)
                and all(isinstance(item, str) and item for item in expected) and len(set(expected)) == len(expected)
                and type(value.get("expected_scenes")) is int and value["expected_scenes"] == len(expected)
                and type(value.get("complete_scenes")) is int and value["complete_scenes"] == len(expected)
                and all(value.get(key) == [] for key in ("missing_scene_ids", "unexpected_scene_ids", "duplicate_scene_ids")))
    return {"native_trial": identity, "native_total_flow_seconds": seconds,
            "native_status": value.get("status"), "native_complete": complete}


def execute_dispatch_plan(plan_pointer: dict[str, str], *, registered_lock_sha256: str,
                          registered_unseal_sha256: str,
                          trial_runner: Callable[[Path, Path], int] | None = None,
                          expected_policy_sha256: str = contract.POLICY_SHA256) -> dict[str, str]:
    """Serial fresh launches; stop on any failure without replacing or retrying jobs.

    Native receipt presence/identity/cost is checked here. Actual managed-session
    freshness, delivery and raw transport still require the evaluation collector.
    """
    start, started_at = time.perf_counter(), _now()
    plan = validate_dispatch_plan(plan_pointer, registered_lock_sha256=registered_lock_sha256,
        registered_unseal_sha256=registered_unseal_sha256, expected_policy_sha256=expected_policy_sha256)
    plan_identity = deepcopy(plan_pointer)
    root = Path(plan["output_root"])
    root.mkdir(parents=True, exist_ok=False)
    journal = root / "dispatch-journal.jsonl"
    jobs = [{**row, "status": "not_run", "attempted": False, "runner_seconds": None,
             "native_trial": None, "native_total_flow_seconds": None} for row in plan["jobs"]]
    authority = plan["confirmation_dispatch_authority"]
    _journal(journal, {"event": "queue_accepted", "at_utc": _now(), "plan": plan_pointer,
                       "confirmation_dispatch_authority": authority, "expected_jobs": len(jobs)})
    if trial_runner is None:
        from .v2_trial import trial
        trial_runner = trial
    try:
        for job in jobs:
            runner_start = None
            try:
                contract._pointer(plan_pointer)
                contract.validate_confirmation_dispatch(Path(job["card"]["path"]), authority["lock"],
                    authority["unseal"], expected_policy_sha256=expected_policy_sha256)
                if Path(job["output"]).exists():
                    raise FileExistsError("Refusing a preexisting trial output; no resume or reuse")
                job["accepted_at_utc"] = _now()
                _journal(journal, {"event": "job_accepted", "at_utc": job["accepted_at_utc"],
                                   "job_id": job["job_id"], "card": job["card"]})
                job["attempted"] = True
                runner_start = time.perf_counter()
                result = trial_runner(Path(job["card"]["path"]), Path(job["output"]))
                job["runner_seconds"] = time.perf_counter() - runner_start
                if type(result) is not int:
                    raise ValueError("Native trial runner must return an explicit integer exit code")
                job["runner_exit_code"] = result
                contract.validate_confirmation_dispatch(Path(job["card"]["path"]), authority["lock"],
                    authority["unseal"], expected_policy_sha256=expected_policy_sha256)
                job.update(_native(job, job["accepted_at_utc"]))
                if result != 0 or job["native_complete"] is not True:
                    raise ValueError("Native trial failed, partial or missing; confirmation queue stops")
                job["status"] = "complete"
                _journal(journal, {"event": "job_complete", "at_utc": _now(), "job_id": job["job_id"],
                                   "native_trial": job["native_trial"]})
            except BaseException as exc:
                if runner_start is not None:
                    job["runner_seconds"] = time.perf_counter() - runner_start
                job["status"] = "failed" if job["attempted"] else "blocked_before_launch"
                job["error"] = f"{type(exc).__name__}: {exc}"
                if job["attempted"] and job["native_trial"] is None:
                    try:
                        job.update(_native(job, job["accepted_at_utc"]))
                    except Exception as native_error:
                        job["native_receipt_error"] = f"{type(native_error).__name__}: {native_error}"
                _journal(journal, {"event": "job_failed", "at_utc": _now(), "job_id": job["job_id"],
                                   "attempted": job["attempted"], "error": job["error"]})
                if not isinstance(exc, Exception):
                    raise
                break
    finally:
        for job in jobs:
            if job["status"] == "not_run":
                _journal(journal, {"event": "job_not_run", "at_utc": _now(), "job_id": job["job_id"],
                                   "reason": "queue_stopped_no_automatic_retry_or_replacement"})
        known = [job for job in jobs if job["native_total_flow_seconds"] is not None]
        attempted = [job for job in jobs if job["attempted"]]
        receipt = {"schema": RECEIPT_SCHEMA, "state": "complete" if all(j["status"] == "complete" for j in jobs) else "incomplete",
            "plan": plan_identity, "confirmation_dispatch_authority": authority,
            "confirmation_scope": plan["confirmation_scope"], "jobs": jobs,
            "expected_jobs": len(jobs), "attempted_jobs": len(attempted),
            "complete_jobs": sum(job["status"] == "complete" for job in jobs),
            "expected_quality_windows_per_job": 48, "full_expected_quality_denominator_preserved": True,
            "started_at_utc": started_at, "finished_at_utc": _now(),
            "wrapper_total_seconds": time.perf_counter() - start,
            "known_native_total_flow_seconds_sum": sum(job["native_total_flow_seconds"] for job in known),
            "missing_native_cost_job_ids": [job["job_id"] for job in attempted if job["native_total_flow_seconds"] is None],
            "native_runtime_freshness_verified": False, "native_runtime_collector_required": True,
            "quality_generation_only": True, "formal_ABBA_timing": False, "new_quality_seeds": False,
            "screening_quality_history_preserved": True, "journal": contract.pointer(journal)}
        identity = contract._write_new(root / "dispatch-receipt.json", receipt)
    return identity


def validate_dispatch_receipt(receipt_pointer: dict[str, str], *, registered_lock_sha256: str,
                              registered_unseal_sha256: str,
                              expected_policy_sha256: str = contract.POLICY_SHA256) -> dict[str, Any]:
    """Bind collector inputs to every original queue slot, including failures.

    This authenticates wrapper/native receipt bytes; it does not replace the
    collector's actual runtime, delivery, transport or freshness validation.
    """
    value = contract._json(Path(contract._pointer(receipt_pointer)["path"]))
    if value.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("Expected an authority-bound confirmation dispatch receipt")
    plan = validate_dispatch_plan(value["plan"], registered_lock_sha256=registered_lock_sha256,
        registered_unseal_sha256=registered_unseal_sha256, expected_policy_sha256=expected_policy_sha256)
    if (value.get("confirmation_dispatch_authority") != plan["confirmation_dispatch_authority"]
            or value.get("confirmation_scope") != plan["confirmation_scope"]
            or value.get("quality_generation_only") is not True or value.get("formal_ABBA_timing") is not False
            or value.get("new_quality_seeds") is not False or value.get("screening_quality_history_preserved") is not True
            or value.get("full_expected_quality_denominator_preserved") is not True
            or value.get("expected_quality_windows_per_job") != 48
            or value.get("native_runtime_freshness_verified") is not False
            or value.get("native_runtime_collector_required") is not True):
        raise ValueError("Dispatch receipt scope, custody authority or quality-history claims changed")
    jobs = value.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != len(plan["jobs"]):
        raise ValueError("Receipt must retain every original ordered queue slot")
    events = [("queue_accepted", None)]
    stopped = False
    for frozen, job in zip(plan["jobs"], jobs, strict=True):
        if not isinstance(job, dict) or any(job.get(key) != expected for key, expected in frozen.items()):
            raise ValueError("Receipt replaced, reordered or changed a frozen queue job")
        status, attempted = job.get("status"), job.get("attempted")
        if type(attempted) is not bool or status not in {"complete", "failed", "blocked_before_launch", "not_run"}:
            raise ValueError("Every job needs an explicit native launch status")
        if stopped and status != "not_run":
            raise ValueError("A stopped confirmation queue cannot retry, replace or continue")
        if status == "not_run":
            if not stopped or attempted or any(job.get(key) is not None for key in ("runner_seconds", "native_trial", "native_total_flow_seconds")):
                raise ValueError("Unattempted jobs cannot fabricate native execution or cost")
            events.append(("job_not_run", job["job_id"]))
            continue
        if attempted:
            seconds = job.get("runner_seconds")
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError("Attempted native jobs require measured runner elapsed time")
            contract._utc(job["accepted_at_utc"])
            events.append(("job_accepted", job["job_id"]))
            if job.get("native_trial") is not None:
                checked = contract._pointer(job["native_trial"])
                native = _native(job, job["accepted_at_utc"])
                if native["native_trial"] != checked or any(job.get(key) != expected for key, expected in native.items()):
                    raise ValueError("Native receipt or complete-flow cost changed after collection")
            elif job.get("native_total_flow_seconds") is not None:
                raise ValueError("Missing native receipts cannot provide fabricated native cost")
        if status == "complete":
            if (not attempted or type(job.get("runner_exit_code")) is not int
                    or job["runner_exit_code"] != 0 or job.get("native_complete") is not True
                    or job.get("native_trial") is None):
                raise ValueError("Completed job lacks a successful native receipt")
            events.append(("job_complete", job["job_id"]))
        else:
            if attempted != (status == "failed"):
                raise ValueError("Blocked and attempted failures must remain distinct")
            stopped = True
            events.append(("job_failed", job["job_id"]))
    complete = sum(job["status"] == "complete" for job in jobs)
    attempted = sum(job["attempted"] for job in jobs)
    known = [job for job in jobs if job["native_total_flow_seconds"] is not None]
    if (value.get("expected_jobs") != len(jobs) or value.get("attempted_jobs") != attempted
            or value.get("complete_jobs") != complete
            or value.get("state") != ("complete" if complete == len(jobs) else "incomplete")
            or value.get("known_native_total_flow_seconds_sum") != sum(job["native_total_flow_seconds"] for job in known)
            or value.get("missing_native_cost_job_ids") != [job["job_id"] for job in jobs
                if job["attempted"] and job["native_total_flow_seconds"] is None]):
        raise ValueError("Dispatch totals hid failed, unattempted or missing-cost slots")
    journal = contract._pointer(value["journal"])
    if Path(journal["path"]) != Path(plan["output_root"]) / "dispatch-journal.jsonl":
        raise ValueError("Dispatch journal escaped the frozen output root")
    rows = [contract.strict_json(line) for line in Path(journal["path"]).read_text(encoding="utf-8").splitlines()]
    if [(row.get("event"), row.get("job_id")) for row in rows] != events:
        raise ValueError("Dispatch journal does not match the complete serial queue history")
    if rows[0].get("plan") != value["plan"] or rows[0].get("confirmation_dispatch_authority") != value["confirmation_dispatch_authority"]:
        raise ValueError("Journal authority differs from its frozen plan")
    seconds = value.get("wrapper_total_seconds")
    if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0
            or contract._utc(value["started_at_utc"]) < contract._utc(plan["frozen_at_utc"])
            or contract._utc(value["finished_at_utc"]) < contract._utc(value["started_at_utc"])):
        raise ValueError("Wrapper chronology or measured elapsed time is invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="确认集整队列锁定校验与全新 trial dispatch")
    sub = parser.add_subparsers(dest="action", required=True)
    freeze = sub.add_parser("freeze", help="冻结完整确认生成队列，不运行模型")
    freeze.add_argument("--lock", type=Path, required=True)
    freeze.add_argument("--unseal", type=Path, required=True)
    freeze.add_argument("--output-root", type=Path, required=True)
    freeze.add_argument("--output-plan", type=Path, required=True)
    run = sub.add_parser("execute", help="校验后逐个调用现有 trial")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--plan-sha256", required=True)
    for command in (freeze, run):
        command.add_argument("--registered-lock-sha256", required=True)
        command.add_argument("--registered-unseal-sha256", required=True)
    args = parser.parse_args()
    pins = {"registered_lock_sha256": args.registered_lock_sha256,
            "registered_unseal_sha256": args.registered_unseal_sha256}
    if args.action == "freeze":
        result = freeze_dispatch_plan({"path": str(args.lock.resolve()), "sha256": args.registered_lock_sha256},
            {"path": str(args.unseal.resolve()), "sha256": args.registered_unseal_sha256},
            args.output_root, args.output_plan, **pins)
        code = 0
    else:
        result = execute_dispatch_plan({"path": str(args.plan.resolve()), "sha256": args.plan_sha256}, **pins)
        code = 0 if contract._json(Path(result["path"]))["state"] == "complete" else 1
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
