"""Sequential source-only flow trials in a managed, bounded llama.cpp session."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable

from experiments.translation_demo import adapters
from experiments.translation_demo.client import LlamaClient
from experiments.translation_demo.gguf import metadata
from experiments.translation_demo.run import (
    ASSET_IDENTITY_FIELDS, asset_manifest_paths, explicit_oom, load_assets,
    read_inputs, select_asset, validate_template, write_json,
)
from .recipes import RECIPES, RECIPE_VERSION, SAMPLING_PROFILES, completion_request, render_window


SCHEMA = "hy30-flow-session-v1"
CANDIDATE = "hy-mt2-30b-a3b-apex-i-compact"
GUARD_TOKENS = 64


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def object_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def append_json(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()


def positive_number(value: Any, name: str, integer: bool = False) -> None:
    if (type(value) not in ((int,) if integer else (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(f"{name} must be explicitly positive")


def load_plan(path: Path) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Path, list[dict[str, Any]]]]]:
    plan = adapters.strict_json(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(plan, dict) or not {"schema", "stage", "budgets", "workloads"} <= set(plan)
            or set(plan) - {"schema", "stage", "budgets", "workloads", "lane"}
            or plan["schema"] != SCHEMA or plan["stage"] not in ("P0", "P1", "P2", "P3", "P4", "P5")):
        raise ValueError("Expected a frozen hy30-flow-session-v1 plan with stage/budgets/workloads only")
    if plan.get("lane", "V2-native-adapted") not in {"V2-native-adapted", "P-flow"}:
        raise ValueError("Unsupported flow input lane")
    budgets = plan["budgets"]
    required = {"max_translation_calls", "max_judge_calls", "max_estimated_tokens", "max_wall_seconds"}
    if not isinstance(budgets, dict) or set(budgets) != required:
        raise ValueError("All four stage budgets must be supplied")
    for name in required - {"max_judge_calls"}:
        positive_number(budgets[name], name, integer=name != "max_wall_seconds")
    if type(budgets["max_judge_calls"]) is not int or budgets["max_judge_calls"] < 0:
        raise ValueError("max_judge_calls must be an explicit nonnegative integer; evaluation owns this budget")
    workloads = plan["workloads"]
    maximum = 2 if plan["stage"] in ("P0", "P4", "P5") else 3
    if not isinstance(workloads, list) or not 1 <= len(workloads) <= maximum:
        raise ValueError(f"Stage {plan['stage']} permits at most {maximum} sequential recipes")
    loaded = []
    labels = set()
    for item in workloads:
        keys = {"label", "inputs", "input_sha256", "recipe", "sampling"}
        if not isinstance(item, dict) or not keys <= set(item) or set(item) - keys - {"seed", "n_predict", "max_attempts"}:
            raise ValueError("Workloads accept only source-input identity and declared recipe settings")
        label = item["label"]
        if (not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", label)
                or label in (".", "..") or label in labels):
            raise ValueError("Unsafe or duplicate workload label")
        labels.add(label)
        if item["recipe"] not in RECIPES or item["sampling"] not in SAMPLING_PROFILES:
            raise ValueError("Unknown recipe/sampling profile")
        positive_number(item.get("n_predict", 1024), "n_predict", integer=True)
        if type(item.get("max_attempts", 2)) is not int or item.get("max_attempts", 2) not in (1, 2):
            raise ValueError("At most two identical attempts are allowed")
        completion_request(item["recipe"], item["sampling"], {"translate_ids": ["probe"]},
                           [1], item.get("n_predict", 1024), item.get("seed", 20261006))
        if not isinstance(item["inputs"], str) or not isinstance(item["input_sha256"], str):
            raise ValueError("Source path/hash must be strings")
        inputs = Path(item["inputs"])
        inputs = inputs.resolve() if inputs.is_absolute() else (path.parent / inputs).resolve()
        if sha256(inputs) != item["input_sha256"]:
            raise ValueError("Source input hash changed after freeze")
        windows = read_inputs(inputs)  # Strict allowlist rejects references/judgments.
        window_cap = {"P0": 6, "P1": 20, "P2": 40, "P3": 20}.get(plan["stage"])
        if window_cap is not None and len(windows) > window_cap:
            raise ValueError("Selected source exceeds this small-stage window cap")
        loaded.append((item, inputs, windows))
    return plan, loaded


class BudgetStopped(RuntimeError):
    pass


class Budget:
    """Reserve a full output cap before dispatch; failed/unknown calls keep it."""

    def __init__(self, limits: dict[str, Any], clock: Callable[[], float] = time.perf_counter):
        self.limits = limits
        self.clock = clock
        self.started = clock()
        self.translation_calls = 0
        self.estimated_tokens = 0

    def remaining_seconds(self) -> float:
        return self.limits["max_wall_seconds"] - (self.clock() - self.started)

    def check_wall(self) -> None:
        if self.remaining_seconds() <= 0:
            raise BudgetStopped("max_wall_seconds")

    def reserve(self, input_tokens: int, n_predict: int) -> None:
        self.check_wall()
        if self.translation_calls >= self.limits["max_translation_calls"]:
            raise BudgetStopped("max_translation_calls")
        if self.estimated_tokens + input_tokens + n_predict > self.limits["max_estimated_tokens"]:
            raise BudgetStopped("max_estimated_tokens")
        self.translation_calls += 1
        self.estimated_tokens += input_tokens + n_predict

    def snapshot(self) -> dict[str, Any]:
        return {"translation_calls": self.translation_calls, "estimated_tokens": self.estimated_tokens,
                "wall_seconds": self.clock() - self.started,
                "remaining_translation_calls": self.limits["max_translation_calls"] - self.translation_calls,
                "remaining_estimated_tokens": self.limits["max_estimated_tokens"] - self.estimated_tokens,
                "remaining_wall_seconds": max(0.0, self.remaining_seconds()),
                "token_accounting": "exact tokenized input plus maximum output reservation per dispatched completion; failed calls included"}


def bounded_timeout(client: Any, budget: Budget) -> None:
    budget.check_wall()
    client.timeout = max(.001, min(300.0, budget.remaining_seconds()))


def effective_settings(response: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    settings = response.get("generation_settings")
    if not isinstance(settings, dict):
        return {"verified": False, "reason": "Server response omitted generation_settings", "settings": None}
    missing = []
    for key, value in request.items():
        if key in ("prompt", "grammar", "cache_prompt", "stream", "stop"):
            continue
        if key not in settings:
            missing.append(key)
        elif (not math.isclose(settings[key], value, rel_tol=1e-6, abs_tol=1e-7)
              if isinstance(value, float) and type(settings[key]) in (int, float)
              else settings[key] != value):
            raise ValueError(f"Server effective {key} differs from requested value")
    return {"verified": not missing, "missing_requested_fields": missing, "settings": settings}


def run_window(client: Any, window: dict[str, Any], item: dict[str, Any], context_size: int,
               budget: Budget, clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    started = clock()
    prompt = render_window(item["recipe"], window)
    attempts: list[dict[str, Any]] = []
    row: dict[str, Any] = {"window_id": window["id"], "candidate": CANDIDATE,
                           "recipe": item["recipe"], "sampling_profile": item["sampling"],
                           "scored_ids": window["translate_ids"], "translations": {},
                           "attempts": attempts, "started_at_utc": utc_now(), "auxiliary_seconds": 0.0}
    for number in range(item.get("max_attempts", 2)):
        attempt: dict[str, Any] = {"attempt": number + 1,
                                   "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
        attempt_start = clock()
        response = None
        dispatched = False
        stage = "tokenize"
        try:
            bounded_timeout(client, budget)
            tokenize_start = clock()
            tokens = client.tokenize(prompt)
            attempt.update(tokenize_seconds=clock() - tokenize_start,
                           tokenize_exchange=client.last_exchange, input_tokens=len(tokens),
                           input_token_ids_sha256=object_hash(tokens), prompt_transport="token-ids-v1")
            n_predict = item.get("n_predict", 1024)
            if len(tokens) + n_predict + GUARD_TOKENS > context_size:
                raise BudgetStopped("context_budget: no silent source truncation")
            request = completion_request(item["recipe"], item["sampling"], window, tokens,
                                         n_predict, item.get("seed", 20261006))
            attempt.update(request=request, request_sha256=object_hash(request))
            bounded_timeout(client, budget)
            budget.reserve(len(tokens), n_predict)
            dispatched = True
            stage = "completion"
            completion_start = clock()
            try:
                response = client.complete(request)
            finally:
                attempt["completion_seconds"] = clock() - completion_start
                attempt["original_response"] = client.last_exchange
            attempt["response"] = response
            attempt["effective_settings"] = effective_settings(response, request)
            if response.get("error") is not None:
                raise ValueError("Server error: " + json.dumps(response["error"], ensure_ascii=False))
            if response.get("prompt") is not None and response["prompt"] != prompt:
                raise ValueError("Effective server prompt differs from rendered native prompt")
            if response.get("tokens_evaluated") is not None and response["tokens_evaluated"] != len(tokens):
                raise ValueError("Effective server token count differs from supplied IDs")
            if response.get("truncated") or response.get("stopped_limit") or response.get("stop_type") == "limit":
                raise ValueError("Generation reached output/context limit")
            content = response.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty or invalid generated text")
            row["translations"] = adapters.translations(content, window["translate_ids"])
            attempt["status"] = "accepted"
            row["status"] = "delivered"
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            attempt.update(status="failed", error=error, failure_stage=stage)
            if stage == "tokenize":
                attempt.setdefault("tokenize_exchange", client.last_exchange)
                attempt.setdefault("tokenize_seconds", clock() - attempt_start)
            # Only error/transport bodies are OOM evidence; generated text is data.
            evidence = error
            if getattr(exc, "code", 0) >= 400 and isinstance(client.last_exchange, str):
                raw = Path(client.last_exchange) / "response.raw"
                if raw.is_file():
                    evidence += raw.read_text(encoding="utf-8", errors="replace")
            if explicit_oom(evidence):
                attempt["error_kind"] = row["error_kind"] = "oom"
            if isinstance(exc, BudgetStopped):
                attempt["error_kind"] = row["error_kind"] = "budget"
                row["stop_reason"] = str(exc)
            row.update(status="translation_failed", reason=error)
        finally:
            attempt.update(elapsed_seconds=clock() - attempt_start, completion_dispatched=dispatched,
                           budget_after=budget.snapshot())
            attempts.append(attempt)
        if row["status"] == "delivered" or row.get("error_kind") in ("oom", "budget"):
            break
    row.update(elapsed_seconds=clock() - started, generation_seconds=clock() - started,
               original_response=attempts[-1].get("original_response"), finished_at_utc=utc_now())
    if not any(attempt["completion_dispatched"] for attempt in attempts):
        row["status"] = "setup_failed" if row.get("stop_reason", "").startswith("context_budget") or row.get("error_kind") != "budget" else "not_run"
    return row


def validate_runtime(args: argparse.Namespace) -> dict[str, Any]:
    if args.candidate != CANDIDATE:
        raise ValueError("Flow optimization is fixed to the adopted APEX-I-Compact asset")
    root = Path(__file__).resolve().parents[2]
    paths = asset_manifest_paths(args.asset_manifest, root)
    asset = select_asset(load_assets(paths), CANDIDATE)
    model = (Path(asset["directory"]) / asset["file"]).resolve()
    engine = adapters.strict_json(args.engine_manifest.read_text(encoding="utf-8-sig"))
    if (engine.get("model_sha256") != asset["sha256"]
            or Path(engine.get("model_path", "")).resolve() != model
            or engine.get("build") != 11429 or engine.get("cuda") != "13.4"
            or not engine.get("custom_runtime_identity_sha256")
            or engine.get("context_size") != args.context_size
            or any(engine.get("asset", {}).get(key) != asset[key] for key in ("id", *ASSET_IDENTITY_FIELDS))):
        raise ValueError("Managed runtime must prove frozen asset SHA, compatible b11429 loader and context")
    # The managed runtime hashes the full model before loading; reuse that evidence.
    model_metadata = metadata(model)
    template = model_metadata.get("tokenizer.chat_template", "")
    validate_template("hy-mt2-30b", template)
    return {"asset": asset, "engine": engine, "model_metadata": model_metadata,
            "engine_manifest_sha256": sha256(args.engine_manifest),
            "asset_manifests": [{"path": str(path), "sha256": sha256(path)} for path in paths],
            "template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest()}


def source_snapshot(output: Path) -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    paths = list(Path(__file__).parent.glob("*.py"))
    paths += list((root / "experiments/translation_demo").glob("*.py"))
    paths += [root / "experiments/translation_demo_runtime.py", root / "experiments/translation_monitor.py"]
    hashes = {}
    for source in sorted(paths):
        relative = source.relative_to(root)
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        hashes[relative.as_posix()] = sha256(source)
    return hashes


def execute_plan(args: argparse.Namespace, client_factory: Any = LlamaClient,
                 identity_loader: Any = validate_runtime,
                 clock: Callable[[], float] = time.perf_counter) -> int:
    started = clock()
    plan, loaded = load_plan(args.session_plan)
    identity = identity_loader(args)
    output = args.output_dir.resolve()
    # Replays/resumes always use a fresh path; no partial-cache reuse is implicit.
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(plan["budgets"], clock)
    budget.started = started  # Preparation/identity time is part of the wall budget.
    write_json(output / "session-plan.json", plan)
    code_hashes = source_snapshot(output)
    events = output / "workload-ledger.jsonl"
    client = client_factory(args.server_url, trace_dir=output / "transport")
    bounded_timeout(client, budget)
    props = client.request("/props")
    actual = props.get("model_path", props.get("model_alias", props.get("default_generation_settings", {}).get("model")))
    if actual is not None and actual != CANDIDATE and Path(actual).resolve() != Path(identity["engine"]["model_path"]).resolve():
        raise ValueError("Live server model differs from verified managed runtime")
    write_json(output / "session.json", {"schema": SCHEMA, "plan_sha256": sha256(args.session_plan),
               "created_at_utc": utc_now(), "candidate": CANDIDATE, "recipe_version": RECIPE_VERSION,
               "identity": identity, "server_props": props, "code_sha256": code_hashes,
               "resume_policy": "fresh output directory required; no implicit cache reuse",
               "wall_budget_scope": "worker preparation through durable session artifacts; parent runtime cold load/unload recorded separately"})
    stop_reason = None
    failures = 0
    for item, inputs, windows in loaded:
        label = item["label"]
        target = output / label
        target.mkdir()
        if sha256(inputs) != item["input_sha256"]:
            raise ValueError("Source changed between frozen validation and dispatch")
        (target / "inputs.jsonl").write_bytes(inputs.read_bytes())
        client = client_factory(args.server_url, trace_dir=target / "transport")
        write_json(target / "run.json", {"created_at": utc_now(), "lane": plan.get("lane", "V2-native-adapted"),
                   "candidate": CANDIDATE, "phase": "translation", "recipe": item["recipe"],
                   "recipe_version": RECIPE_VERSION, "settings": item,
                   "input_path": str(inputs), "input_sha256": sha256(inputs),
                   "expected_window_ids": [window["id"] for window in windows],
                   "asset": identity["asset"], "engine": identity["engine"],
                   "engine_manifest_sha256": identity["engine_manifest_sha256"],
                   "template_sha256": identity["template_sha256"], "server_props": props,
                   "code_sha256": code_hashes, "session_plan_sha256": sha256(args.session_plan)})
        (target / "results.jsonl").touch(exist_ok=False)
        (target / "ledger.jsonl").touch(exist_ok=False)
        (target / "schedule.jsonl").touch(exist_ok=False)
        if stop_reason:
            for window in windows:
                append_json(target / "schedule.jsonl", {"window_id": window["id"], "status": "not_run", "reason": stop_reason})
            write_json(target / "completion.json", {"windows": 0, "expected_windows": len(windows),
                       "remaining_window_ids": [window["id"] for window in windows], "stopped_reason": stop_reason,
                       "budget_after": budget.snapshot(), "mapping_required": False})
            append_json(events, {"label": label, "status": "not_run", "reason": stop_reason, "at_utc": utc_now()})
            continue
        append_json(events, {"label": label, "status": "started", "at_utc": utc_now()})
        count = 0
        for window in windows:
            row = run_window(client, window, item, args.context_size, budget, clock)
            write_json(target / f"window-{window['id']}.json", row)
            if row["status"] in ("not_run", "setup_failed"):
                append_json(target / "schedule.jsonl", {"window_id": window["id"], "status": row["status"], "reason": row["reason"]})
            else:
                append_json(target / "ledger.jsonl", row)
                append_json(target / "results.jsonl", {"id": window["id"], "translations": row["translations"],
                                                       "elapsed_seconds": row["elapsed_seconds"]})
            count += 1
            failures += row["status"] != "delivered"
            print(f"{label} {count}/{len(windows)} {window['id']} {row['status']}", flush=True)
            if row.get("error_kind") in ("oom", "budget"):
                stop_reason = row.get("stop_reason", row["error_kind"])
                break
        remaining = [window["id"] for window in windows[count:]]
        for window_id in remaining:
            append_json(target / "schedule.jsonl", {"window_id": window_id, "status": "not_run", "reason": stop_reason})
        write_json(target / "completion.json", {"windows": count, "expected_windows": len(windows),
                   "remaining_window_ids": remaining, "stopped_reason": stop_reason,
                   "budget_after": budget.snapshot(), "mapping_required": False})
        append_json(events, {"label": label, "status": "interrupted" if stop_reason else "phase_finished",
                            "at_utc": utc_now(), "windows": count, "remaining_window_ids": remaining,
                            "stopped_reason": stop_reason, "budget_after": budget.snapshot()})
    write_json(output / "worker-completion.json", {"failures": failures, "stopped_reason": stop_reason,
               "complete": stop_reason is None, "budget": budget.snapshot(), "finished_at_utc": utc_now()})
    return 1 if failures or stop_reason else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="有硬预算的本地 Hy30 源文流程实验")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--session-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--engine-manifest", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=4096)
    parser.add_argument("--asset-manifest", type=Path, action="append")
    parser.add_argument("--stop-on-oom", action="store_true")
    args = parser.parse_args()
    positive_number(args.context_size, "context_size", integer=True)
    return execute_plan(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
