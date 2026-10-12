"""Run multiple frozen workloads in the server session owned by the existing runtime."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

from experiments.translation_demo import adapters
from experiments.translation_demo.client import LlamaClient
from experiments.translation_demo.run import read_inputs
from experiments.translation_demo.run import main as demo_main
from .core import RECIPE, append_event, inspect_workload, is_oom, sha256, utc_now, write_json


def latency_quantile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_workload(path: Path, inputs: Path, process_seconds: float) -> dict[str, Any]:
    persisted_at = utc_now()
    windows = read_inputs(inputs)
    audit = inspect_workload(path, [row["id"] for row in windows])
    rows = list(audit.pop("rows").values())
    elapsed = [row["elapsed_seconds"] for row in rows if isinstance(row.get("elapsed_seconds"), (float, int))]
    starts = [row["started_at_utc"] for row in rows if row.get("started_at_utc")]
    ends = [row.get("persisted_at_utc", row.get("finished_at_utc")) for row in rows
            if row.get("persisted_at_utc", row.get("finished_at_utc"))]
    wall = (datetime.fromisoformat(persisted_at) - datetime.fromisoformat(min(starts))).total_seconds() if starts and ends else None
    attempts = [attempt for row in rows for attempt in row.get("attempts", [])]
    return {**audit, "started_at_utc": min(starts) if starts else None,
            "finished_at_utc": max(ends) if ends else None, "terminal_artifacts_observed_at_utc": persisted_at,
            "translation_wall_seconds": wall,
            "full_set_wall_seconds": wall if audit["complete"] else None,
            "subprocess_wall_seconds": process_seconds,
            "timing_scope": "first window start through final durable terminal artifact; tokenizer, validation, retries included",
            "timing_reason": None if wall is not None else "Window UTC timestamps unavailable",
            "scored_ids_expected": sum(len(row["translate_ids"]) for row in windows),
            "p50_seconds": latency_quantile(elapsed, .5), "p95_seconds": latency_quantile(elapsed, .95),
            "p99_seconds": latency_quantile(elapsed, .99), "max_seconds": max(elapsed, default=None),
            "retry_count": sum(max(0, len(row.get("attempts", [])) - 1) for row in rows),
            "retry_seconds": sum(attempt.get("elapsed_seconds", 0) for row in rows for attempt in row.get("attempts", [])[1:]),
            "input_tokens_attempts": sum(attempt.get("input_tokens", 0) for attempt in attempts),
            "output_tokens_attempts": sum(attempt.get("response", {}).get("tokens_predicted", 0) for attempt in attempts),
            "oom": is_oom(rows),
            "translation_hashes": {row["window_id"]: __import__("hashlib").sha256(
                json.dumps(row.get("translations", {}), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest() for row in rows}}


def prepare_probe(client: Any, output: Path) -> Path:
    """Find a synthetic source-only prompt near the 4096 - 1024 - 64 input budget."""
    budget = 4096 - 1024 - 64
    def window(repeats: int) -> dict[str, Any]:
        return {"id": "synthetic-budget-probe", "source_language": "ja", "target_language": "zh-Hans",
                "context": [{"id": "context", "text": "彼は明日駅へ行く予定です。" * repeats},
                            {"id": "target", "text": "本当に行くのですか。"}], "translate_ids": ["target"]}
    low, high, measurements = 1, 8192, []
    best = None
    while low <= high:
        middle = (low + high) // 2
        item = window(middle)
        count = len(client.tokenize(adapters.render("hy-mt2-30b", item)))
        measurements.append({"repeats": middle, "tokens": count, "at_utc": utc_now()})
        if count <= budget:
            best = (item, count)
            low = middle + 1
        else:
            high = middle - 1
    if best is None:
        raise ValueError("Synthetic probe template cannot fit reserved output budget")
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "inputs.jsonl"
    with inputs.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(best[0], ensure_ascii=False) + "\n")
    write_json(output / "probe.json", {"input_budget": budget, "input_tokens": best[1],
               "remaining_input_tokens": budget - best[1], "output_reserved": 1024,
               "guard_reserved": 64, "context_size": 4096, "measurements": measurements,
               "quality_sample": False, "purpose": "synthetic capacity stress; no quality scoring"})
    return inputs


def invoke_demo(args: argparse.Namespace, inputs: Path, output: Path) -> tuple[int, float]:
    output.mkdir(parents=True, exist_ok=False)
    cmd = ["experiments.translation_demo.run",
           "--candidate", args.candidate, "--inputs", str(inputs), "--output-dir", str(output),
           "--server-url", args.server_url, "--engine-manifest", str(args.engine_manifest),
           "--context-size", "4096", "--n-predict", "1024", "--max-attempts", "2", "--stop-on-oom"]
    for manifest in args.asset_manifest:
        cmd.extend(["--asset-manifest", str(manifest)])
    start = time.perf_counter()
    previous = sys.argv
    with (output / "worker.stdout.log").open("x", encoding="utf-8") as stdout, (output / "worker.stderr.log").open("x", encoding="utf-8") as stderr:
        try:
            sys.argv = cmd
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    code = demo_main()
                except Exception as exc:
                    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
                    code = 2
        finally:
            sys.argv = previous
    return code, time.perf_counter() - start


def execute_plan(args: argparse.Namespace, invoke: Any = invoke_demo, clock: Any = time.perf_counter) -> int:
    plan = json.loads(args.session_plan.read_text(encoding="utf-8"))
    if plan.get("recipe") != RECIPE or args.context_size != 4096:
        raise ValueError("Comparison worker requires frozen context4096 recipe")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "session-plan.json", plan)
    events = output / "workload-ledger.jsonl"
    interrupted = False
    failure = False
    for item in plan["workloads"]:
        label = item["label"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", label) or label in (".", ".."):
            raise ValueError("Unsafe workload artifact label")
        if interrupted:
            append_event(events, {"label": label, "status": "not_run", "reason": "preceding workload stopped session"})
            continue
        input_path = Path(item["inputs"])
        if sha256(input_path) != item["input_sha256"]:
            raise ValueError("Source input hash changed after freeze")
        read_inputs(input_path)
        if item.get("probe"):
            client = LlamaClient(args.server_url, trace_dir=output / "probe-tokenization")
            input_path = prepare_probe(client, output / "probe-source")
        started = clock()
        iteration = 0
        duration = item.get("repeat_until_seconds")
        if duration is not None and duration != 1800:
            raise ValueError("Frozen stability run requires 1800 seconds")
        while iteration == 0 or (duration is not None and clock() - started < duration):
            iteration += 1
            target = output / label / f"run-{iteration:05d}"
            target.parent.mkdir(parents=True, exist_ok=True)
            append_event(events, {"label": label, "iteration": iteration, "status": "started",
                                  "inputs": str(input_path), "quality_sample": item.get("quality_sample", False)})
            code, elapsed = invoke(args, input_path, target)
            summary = summarize_workload(target, input_path, elapsed)
            errors = (target / "worker.stderr.log").read_text(encoding="utf-8", errors="replace") if (target / "worker.stderr.log").exists() else ""
            summary.update(label=label, iteration=iteration, exit_code=code,
                           quality_sample=item.get("quality_sample", False),
                           artifact_dir=str(target.resolve()), oom=summary["oom"] or is_oom(errors))
            write_json(target / "workload-summary.json", summary)
            append_event(events, {**summary, "status": "completed" if summary["complete"] else "interrupted"})
            failure |= code != 0 or summary["failed"] > 0
            if summary["oom"] or code not in (0, 1) or summary["not_run"]:
                interrupted = True
                break
        append_event(events, {"label": label, "status": "phase_finished", "iterations": iteration,
                              "elapsed_seconds": clock() - started, "requested_seconds": duration,
                              "quality_sample": item.get("quality_sample", False)})
    write_json(output / "worker-completion.json", {"interrupted": interrupted, "failures": failure,
               "ended_at_utc": utc_now(), "quality_input_policy": "first formal round terminal attempt; repeated stress excluded"})
    return 1 if failure else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--session-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--engine-manifest", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=4096)
    parser.add_argument("--asset-manifest", type=Path, action="append", required=True)
    parser.add_argument("--stop-on-oom", action="store_true")
    return execute_plan(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
