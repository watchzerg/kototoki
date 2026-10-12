"""Read-only cost accounting for bounded flow trials; no inference or transcripts."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import math
from pathlib import Path
from typing import Any

from experiments.translation_eval.runner import dump, load_jsonl, parse, read_json


def number(value: Any, *, integer: bool = False) -> bool:
    return (type(value) in ((int,) if integer else (int, float))
            and math.isfinite(value) and value >= 0)


def metric(values: list[Any]) -> dict[str, Any]:
    known = [value for value in values if number(value)]
    return {"measured_sum": sum(known) if known else (0 if not values else None),
            "known_records": len(known), "unknown_records": len(values) - len(known),
            "complete": len(known) == len(values)}


def usage_tokens(value: Any) -> dict[str, int]:
    """Retain numeric usage only, never text or raw event payloads."""
    if not isinstance(value, dict):
        return {}
    fields = {"input_tokens": ("input_tokens", "prompt_tokens"),
              "output_tokens": ("output_tokens", "completion_tokens"),
              "cached_input_tokens": ("cached_input_tokens",), "total_tokens": ("total_tokens",)}
    result = {}
    for name, alternatives in fields.items():
        for field in alternatives:
            if number(value.get(field), integer=True):
                result[name] = value[field]
                break
    details = value.get("input_tokens_details", value.get("prompt_tokens_details", {}))
    if isinstance(details, dict) and number(details.get("cached_tokens"), integer=True):
        result["cached_input_tokens"] = details["cached_tokens"]
    return result


def judge_usage(path: Path, attempt: dict[str, Any]) -> tuple[dict[str, int], str]:
    # A terminal turn event is authoritative; intermediate cumulative usage must
    # not be added again. Multiple completed turns cannot be silently summed.
    completed, observed = [], []
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            try:
                event = parse(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            usage = usage_tokens(event.get("usage"))
            if usage:
                observed.append(usage)
                if event.get("type") == "turn.completed":
                    completed.append(usage)
    if len(completed) == 1:
        return completed[0], "single turn.completed usage event"
    if len(completed) > 1:
        return {}, "multiple completed turns; accounting scope unresolved"
    values = observed or [usage_tokens(value) for value in attempt.get("usage_events", [])]
    values = [value for value in values if value]
    if len(values) == 1:
        return values[0], "single exposed usage event"
    return {}, "usage unavailable or cumulative/multiple event scope unresolved"


def summarize(root: Path, budget_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("run-root must be an existing directory")
    evidence, gaps, translation, judges, worker_budgets = [], [], [], [], []
    windows, judge_states = Counter(), Counter()
    canonical_paths = sorted(path for path in root.rglob("run.json")
                             if not {"source", "originals"} & set(path.relative_to(root).parts))
    for manifest_path in canonical_paths:
        manifest = read_json(manifest_path)
        if manifest.get("phase") != "translation":
            continue
        directory = manifest_path.parent
        evidence.append(manifest_path)
        ledger_path = directory / "ledger.jsonl"
        rows = load_jsonl(ledger_path) if ledger_path.is_file() else []
        if ledger_path.is_file():
            evidence.append(ledger_path)
        else:
            gaps.append({"path": str(directory.relative_to(root)), "kind": "missing_translation_ledger"})
        # Window artifacts include attempts stopped before a completion dispatch;
        # these may be represented only in schedule.jsonl, never in the ledger.
        by_id = {row["window_id"]: row for row in rows}
        for path in sorted(directory.glob("window-*.json")):
            row = read_json(path)
            prior = by_id.get(row.get("window_id"))
            if prior is not None and prior != row:
                raise ValueError("window artifact and translator ledger disagree")
            by_id[row["window_id"]] = row
            evidence.append(path)
        for row in by_id.values():
            windows[row.get("status", "unknown")] += 1
            attempts = row.get("attempts")
            if not isinstance(attempts, list):
                gaps.append({"path": str(directory.relative_to(root)), "kind": "missing_translation_attempts"})
                continue
            completion_seen = 0
            for ordinal, attempt in enumerate(attempts):
                if not isinstance(attempt, dict):
                    raise ValueError("translation attempt must be an object")
                dispatched = attempt.get("completion_dispatched")
                if type(dispatched) is not bool:
                    gaps.append({"path": str(directory.relative_to(root)), "kind": "unknown_completion_dispatch"})
                request = attempt.get("request", {})
                response = attempt.get("response") or {}
                if not isinstance(request, dict) or not isinstance(response, dict):
                    raise ValueError("translation request/response must be objects")
                reserved = (attempt["input_tokens"] + request["n_predict"]
                            if dispatched is True and number(attempt.get("input_tokens"), integer=True)
                            and number(request.get("n_predict"), integer=True) else None)
                translation.append({"dispatched": dispatched, "retry": ordinal > 0,
                                    "completion_retry": dispatched is True and completion_seen > 0,
                                    "status": attempt.get("status", "unknown"), "reserved_tokens": reserved,
                                    "elapsed_seconds": attempt.get("elapsed_seconds"),
                                    "tokenize_seconds": attempt.get("tokenize_seconds"),
                                    "completion_seconds": attempt.get("completion_seconds"),
                                    "tokens_evaluated": response.get("tokens_evaluated"),
                                    "tokens_predicted": response.get("tokens_predicted")})
                completion_seen += dispatched is True
    for path in sorted(root.rglob("worker-completion.json")):
        if {"source", "originals"} & set(path.relative_to(root).parts):
            continue
        evidence.append(path)
        state = read_json(path)
        worker_budgets.append(state.get("budget", {}))
    judge_paths = set(root.rglob("job.json"))
    # Interrupted first attempts may have durable attempt metadata before their
    # aggregate job ledger is written. Keep these calls in the denominator.
    for metadata in root.rglob("attempt.json"):
        if "judge-execution" in metadata.relative_to(root).parts:
            judge_paths.add(metadata.parent.parent / "job.json")
    for path in sorted(judge_paths):
        parts = set(path.relative_to(root).parts)
        if not {"judge-execution", "subagent-execution"} & parts or {"source", "originals"} & parts:
            continue
        state = read_json(path) if path.is_file() else {"status": "interrupted"}
        if path.is_file():
            evidence.append(path)
        else:
            gaps.append({"path": str(path.relative_to(root)), "kind": "missing_judge_job_ledger"})
        judge_states[state.get("status", "unknown")] += 1
        attempts = state.get("attempts")
        attempts = attempts if isinstance(attempts, list) else []
        by_attempt = {str(value.get("attempt", number + 1)).removeprefix("attempt-"): value
                      for number, value in enumerate(attempts)}
        for directory in sorted(path.parent.glob("attempt-*")):
            metadata = directory / ("attempt.json" if "judge-execution" in parts else "invocation.json")
            if metadata.is_file():
                evidence.append(metadata)
                number_text = directory.name.split("-")[-1]
                by_attempt[number_text] = {**read_json(metadata), "attempt": number_text}
        if any(not value.isdigit() for value in by_attempt):
            raise ValueError("invalid judge attempt number")
        attempts = [by_attempt[key] for key in sorted(by_attempt, key=int)]
        if not attempts:
            gaps.append({"path": str(path.relative_to(root)), "kind": "missing_judge_attempts"})
        for ordinal, attempt in enumerate(attempts):
            raw_number = attempt.get("attempt", ordinal + 1)
            attempt_number = str(raw_number).removeprefix("attempt-")
            if not attempt_number.isdigit():
                raise ValueError("invalid judge attempt number")
            stdout = path.parent / f"attempt-{attempt_number}" / "stdout.jsonl"
            usage, reason = judge_usage(stdout, attempt)
            if stdout.is_file():
                evidence.append(stdout)
            judges.append({"retry": ordinal > 0, "status": attempt.get("status", "unknown"),
                           "elapsed_seconds": attempt.get("elapsed_seconds"), "usage": usage,
                           "usage_reason": reason})
    dispatched = [item for item in translation if item["dispatched"] is True]
    recorded_calls = sum(value["translation_calls"] for value in worker_budgets
                         if number(value.get("translation_calls"), integer=True))
    recorded_tokens = sum(value["estimated_tokens"] for value in worker_budgets
                          if number(value.get("estimated_tokens"), integer=True))
    reservation = metric([item["reserved_tokens"] for item in dispatched])
    actual_calls = max(len(dispatched), recorded_calls)
    estimated_tokens = max(reservation["measured_sum"] or 0, recorded_tokens)
    if recorded_calls and recorded_calls != len(dispatched):
        gaps.append({"kind": "worker_translation_call_counter_disagrees_with_attempts",
                     "worker_count": recorded_calls, "attempt_count": len(dispatched)})
    if recorded_tokens and recorded_tokens != (reservation["measured_sum"] or 0):
        gaps.append({"kind": "worker_reserved_tokens_disagree_with_attempts"})
    accounting_complete = not gaps and reservation["complete"]
    report = {"schema": "hy30-flow-costs-v1", "run_root": str(root),
              "translation": {"windows": dict(sorted(windows.items())), "attempts": len(translation),
                              "completion_calls_accounted": actual_calls, "traced_completion_calls": len(dispatched),
                              "tokenization_attempts": len(translation), "retries": sum(item["retry"] for item in translation),
                              "completion_retries": sum(item["completion_retry"] for item in dispatched),
                              "attempt_statuses": dict(sorted(Counter(item["status"] for item in translation).items())),
                              "elapsed_seconds": metric([item["elapsed_seconds"] for item in translation]),
                              "tokenization_seconds": metric([item["tokenize_seconds"] for item in translation]),
                              "generation_seconds": metric([item["completion_seconds"] for item in dispatched]),
                              "retry_elapsed_seconds": metric([item["elapsed_seconds"] for item in translation if item["retry"]]),
                              "reserved_tokens": reservation, "estimated_tokens_accounted": estimated_tokens,
                              "actual_server_input_tokens": metric([item["tokens_evaluated"] for item in dispatched]),
                              "actual_server_output_tokens": metric([item["tokens_predicted"] for item in dispatched])},
              "judge": {"jobs": sum(judge_states.values()),
                        "job_statuses": dict(sorted(judge_states.items())), "attempts": len(judges),
                        "retries": sum(item["retry"] for item in judges),
                        "attempt_statuses": dict(sorted(Counter(item["status"] for item in judges).items())),
                        "elapsed_seconds": metric([item["elapsed_seconds"] for item in judges]),
                        "retry_elapsed_seconds": metric([item["elapsed_seconds"] for item in judges if item["retry"]]),
                        "usage": {name: metric([item["usage"].get(name) for item in judges])
                                  for name in ("input_tokens", "output_tokens", "cached_input_tokens", "total_tokens")},
                        "usage_reasons": dict(sorted(Counter(item["usage_reason"] for item in judges).items()))},
              "worker_wall_seconds_sum": metric([value.get("wall_seconds") for value in worker_budgets]),
              "accounting_complete": accounting_complete, "missing_or_inconsistent_evidence": gaps,
              "billed_cost": None, "billed_cost_reason": "No billed-cost evidence; token usage is not a price.",
              "scope_note_zh": "包括目录内探针与失败重试。阶段耗时相加是累计工作时间，不是并行运行的关键路径墙钟；父运行器的冷加载、卸载和资源峰值另行记录。",
              "evidence": [{"path": path.relative_to(root).as_posix(),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                           for path in sorted(set(evidence))]}
    if budget_path:
        report["budget_audit"] = audit_budget(read_json(budget_path), actual_calls, len(judges),
                                               estimated_tokens, accounting_complete)
    return report


def audit_budget(card: dict[str, Any], calls: int, judges: int, tokens: int, complete: bool) -> dict[str, Any]:
    budgets = card.get("budgets", card)
    fields = {"max_translation_calls": calls, "max_judge_calls": judges,
              "max_estimated_tokens": tokens, "max_wall_seconds": card.get("observed_wall_seconds")}
    result = {}
    for key, used in fields.items():
        limit = budgets.get(key)
        if not number(limit, integer=key != "max_wall_seconds"):
            raise ValueError(f"budget requires numeric nonnegative {key}")
        if key == "max_wall_seconds" and used is None and card.get("started_at_utc") and card.get("finished_at_utc"):
            used = (datetime.fromisoformat(card["finished_at_utc"]) - datetime.fromisoformat(card["started_at_utc"])).total_seconds()
        known = number(used)
        result[key] = {"limit": limit, "used_accounted": used if known else None,
                       "remaining_upper_bound": max(0, limit - used) if known else None,
                       "exceeded": used > limit if known else None,
                       "remaining_is_exact": known and (key == "max_wall_seconds" or (
                           complete and (key != "max_estimated_tokens" or judges == 0)))}
    return {"dimensions": result, "complete_accounting": complete,
            "warning_zh": "缺失记录可能高估剩余额度；token额度仅统计本地翻译输入加输出上限，不能替代裁判的实际usage或未冻结的裁判token估算。墙钟须由阶段实测给出，不能用耗时之和替代。"}


def main() -> None:
    parser = argparse.ArgumentParser(description="离线汇总翻译与裁判成本，不读取或输出字幕内容")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--budget", type=Path)
    args = parser.parse_args()
    try:
        dump(args.output, summarize(args.run_root, args.budget))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.exit(2, f"cost accounting error: {exc}\n")


if __name__ == "__main__":
    main()
