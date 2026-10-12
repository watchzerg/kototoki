"""Recoverable, bounded orchestration of existing fresh Sol/high judge jobs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from experiments.translation_eval.runner import (NO_JUDGE_STATUSES, dump, dump_jsonl,
                                                  finalize, load_jsonl, read_json, sha)
from experiments.translation_judge.runner import EFFORT, MODEL, run, run_lock

TOKENS_PER_ATTEMPT = 15000
SCHEMA = "hy30-judge-loop-v1"
VERSION_TIMEOUT_SECONDS = 30
OVERHEAD_GUARD_SECONDS = 1


def attempt_counts(root: Path) -> dict[str, int]:
    """Count durable attempts even when interrupted before job.json was saved."""
    directory = root / "judge-execution"
    groups: dict[str, set[int]] = {}
    if not directory.exists():
        return {}
    for path in directory.rglob("attempt-*"):
        if not path.is_dir():
            continue
        job_id = path.parent.relative_to(directory).as_posix()
        try:
            number = int(path.name.removeprefix("attempt-"))
        except ValueError as exc:
            raise ValueError("invalid durable judge attempt directory") from exc
        groups.setdefault(job_id, set()).add(number)
    for path in directory.rglob("job.json"):
        state = read_json(path)
        job_id = path.parent.relative_to(directory).as_posix()
        for ordinal, attempt in enumerate(state.get("attempts", []), 1):
            number = int(str(attempt.get("attempt", ordinal)).removeprefix("attempt-"))
            groups.setdefault(job_id, set()).add(number)
    for numbers in groups.values():
        if not numbers <= {1, 2} or numbers != set(range(1, max(numbers, default=0) + 1)):
            raise ValueError("judge history violates the two-attempt transport limit")
    return {key: len(value) for key, value in groups.items()}


def job_state(root: Path, job_id: str) -> str | None:
    path = root / "judge-execution" / job_id / "job.json"
    return read_json(path).get("status") if path.is_file() else None


def orchestrate(output: Path, max_judge_calls: int, max_estimated_tokens: int,
                max_wall_seconds: float, workers: int = 6, timeout: float = 180,
                executable: str = "codex.exe", *, run_fn: Callable[..., dict[str, Any]] = run,
                finalize_fn: Callable[..., None] = finalize,
                clock: Callable[[], float] = time.time) -> dict[str, Any]:
    output = output.resolve()
    if (type(max_judge_calls) is not int or max_judge_calls < 0
            or type(max_estimated_tokens) is not int or max_estimated_tokens < 0
            or type(workers) is not int or not 1 <= workers <= 6
            or type(max_wall_seconds) not in (int, float) or not math.isfinite(max_wall_seconds)
            or max_wall_seconds <= 0 or type(timeout) not in (int, float)
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("explicit nonnegative call/token caps, positive wall/timeout and workers 1..6 required")
    prepared = read_json(output / "run.json")
    if prepared.get("judge_requested") != {"model": MODEL, "effort": EFFORT}:
        raise ValueError("prepared evaluation must request existing Sol/high profile")
    expected_path = output / "expected.jsonl"
    if sha(expected_path) != prepared.get("expected_sha256"):
        raise ValueError("prepared expected ledger changed")
    eligible = [row for row in load_jsonl(expected_path) if row["structural_status"] not in NO_JUDGE_STATUSES]
    possible_jobs = {f"{stage}/{row['candidate_alias']}/{row['window_id']}"
                     for stage in ("primary", "review", "adjudication") for row in eligible}
    policy = {"schema": SCHEMA, "expected_sha256": sha(expected_path),
              "primary_jobs_sha256": sha(output / "jobs.jsonl"), "model": MODEL, "effort": EFFORT,
              "max_judge_calls": max_judge_calls, "max_estimated_tokens": max_estimated_tokens,
              "max_wall_seconds": max_wall_seconds, "workers": workers, "timeout": timeout,
              "estimated_tokens_per_attempt": TOKENS_PER_ATTEMPT, "executable": executable}
    budget_path, state_path = output / "judge-loop-budget.json", output / "judge-loop-state.json"
    # Separate lock covers phase selection and budget bookkeeping; the existing
    # runner retains its own per-batch scheduler lock.
    with run_lock(output / ".judge-loop-lock"):
        counts = attempt_counts(output)
        if set(counts) - possible_jobs:
            raise ValueError("judge attempts exist outside the prepared eligible scope")
        used = sum(counts.values())
        prior = read_json(state_path) if state_path.exists() else {}
        if used < prior.get("attempts_accounted", 0):
            raise ValueError("durable judge history disappeared; budget cannot reset")
        if budget_path.exists():
            frozen = read_json(budget_path)
            if any(frozen.get(key) != value for key, value in policy.items()):
                raise ValueError("immutable judge-loop settings changed; resume with the original caps")
            if (prior.get("budget_sha256") not in (None, sha(budget_path))
                    or frozen["deadline_epoch"] != frozen["started_at_epoch"] + max_wall_seconds):
                raise ValueError("immutable judge-loop start/deadline changed")
        else:
            # Reserve both bounded transport attempts for all three possible
            # phases, not just the currently visible primary jobs.
            reservation = len(eligible) * 6
            if max_judge_calls < reservation or max_estimated_tokens < reservation * TOKENS_PER_ATTEMPT:
                raise ValueError(f"insufficient worst-case judge reservation: {reservation} calls / {reservation * TOKENS_PER_ATTEMPT} estimated tokens")
            started = clock()
            frozen = {**policy, "started_at_epoch": started,
                      "started_at_utc": datetime.fromtimestamp(started, timezone.utc).isoformat(),
                      "deadline_epoch": started + max_wall_seconds,
                      "initial_attempts_accounted": used, "worst_case_reserved_calls": reservation,
                      "token_estimate_reason": "15,000 tokens per transport attempt, calibrated by current probe; not billed cost"}
            dump(budget_path, frozen)

        def checkpoint(status: str, stage: str, reason: str | None = None) -> dict[str, Any]:
            observed = sum(attempt_counts(output).values())
            if observed < max(used, prior.get("attempts_accounted", 0), frozen["initial_attempts_accounted"]):
                raise ValueError("durable judge history disappeared; budget cannot reset")
            value = {"schema": SCHEMA, "status": status, "stage": stage, "reason": reason,
                     "budget_sha256": sha(budget_path),
                     "attempts_accounted": observed, "estimated_tokens_accounted": observed * TOKENS_PER_ATTEMPT,
                     "elapsed_wall_seconds": max(0, clock() - frozen["started_at_epoch"]),
                     "remaining_calls": max(0, max_judge_calls - observed),
                     "remaining_estimated_tokens": max(0, max_estimated_tokens - observed * TOKENS_PER_ATTEMPT),
                     "remaining_wall_seconds": max(0, frozen["deadline_epoch"] - clock()),
                     "billed_cost": None}
            dump(state_path, value)
            return value

        if prior.get("status") == "complete":
            return checkpoint("complete", "finalized")

        def execute_phase(stage: str, path: Path) -> dict[str, Any] | None:
            jobs = load_jsonl(path)
            if len({item["job_id"] for item in jobs}) != len(jobs) or any(
                    item["job_id"] not in possible_jobs or not item["job_id"].startswith(stage + "/") for item in jobs):
                raise ValueError("phase jobs differ from prepared eligible scope")
            for index in range(0, len(jobs), workers):
                batch = jobs[index:index + workers]
                counts_now = attempt_counts(output)
                attempts_now = sum(counts_now.values())
                reserve = sum(0 if job_state(output, item["job_id"]) == "succeeded"
                              else 2 - counts_now.get(item["job_id"], 0) for item in batch)
                if attempts_now + reserve > max_judge_calls or (attempts_now + reserve) * TOKENS_PER_ATTEMPT > max_estimated_tokens:
                    return checkpoint("budget_stopped", stage, "insufficient batch call/token reserve")
                remaining = frozen["deadline_epoch"] - clock()
                safe_timeout = min(timeout, (remaining - VERSION_TIMEOUT_SECONDS - OVERHEAD_GUARD_SECONDS) / 2)
                if safe_timeout <= 0:
                    return checkpoint("budget_stopped", stage, "deadline leaves no bounded transport reserve")
                batch_path = output / f"judge-loop-{stage}-batch-{index // workers:04d}.jsonl"
                dump_jsonl(batch_path, batch)
                checkpoint("running", stage)
                summary = run_fn(output, batch_path, executable, min(workers, len(batch)), safe_timeout)
                state = checkpoint("running", stage)
                if state["attempts_accounted"] > max_judge_calls or state["estimated_tokens_accounted"] > max_estimated_tokens:
                    return checkpoint("budget_stopped", stage, "observed accounting exceeds immutable budget")
                if summary.get("judge_failed", 0) or summary.get("not_run", 0):
                    return checkpoint("transport_stopped", stage, "failed/exhausted transport or access circuit; no downstream judge dispatch")
            return None

        for stage, path in (("primary", output / "jobs.jsonl"),
                            ("review", output / "jobs-review.jsonl"),
                            ("adjudication", output / "jobs-adjudication.jsonl")):
            stopped = execute_phase(stage, path)
            if stopped:
                return stopped
            if clock() >= frozen["deadline_epoch"]:
                return checkpoint("budget_stopped", stage, "deadline reached; no downstream work")
            finalize_fn(output, selection_only=stage == "primary")
        return checkpoint("complete", "finalized")


def main() -> None:
    parser = argparse.ArgumentParser(description="有冻结预算与恢复记录的 Sol/high 裁判闭环")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-judge-calls", type=int, required=True)
    parser.add_argument("--max-estimated-tokens", type=int, required=True)
    parser.add_argument("--max-wall-seconds", type=float, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 7), default=6)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--codex", default="codex.exe")
    args = parser.parse_args()
    try:
        result = orchestrate(args.output, args.max_judge_calls, args.max_estimated_tokens,
                             args.max_wall_seconds, args.workers, args.timeout, args.codex)
        if result["status"] != "complete":
            parser.exit(1, "裁判闭环停止；预算与原始尝试已保留，可按冻结设置恢复。\n")
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"裁判闭环错误：{exc}\n")


if __name__ == "__main__":
    main()
