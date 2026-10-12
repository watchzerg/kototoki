"""A source-only v2 session worker: one candidate/seed per fresh server."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable

from experiments.translation_demo import adapters
from experiments.translation_demo.client import LlamaClient
from experiments.translation_demo.run import explicit_oom, read_inputs, write_json
from . import v2_recipes as recipes
from .worker import (Budget, BudgetStopped, CANDIDATE, GUARD_TOKENS, append_json,
                     bounded_timeout, effective_settings, object_hash, positive_number,
                     sha256, source_snapshot, utc_now, validate_runtime)


SCHEMA = "hy30-flow-session-v2"
CHECKPOINT_SCHEMA = "hy30-flow-checkpoint-v2"
STAGES = ("qualification", "screening", "confirmation", "full-flow")


def _hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{name} must be an exact lowercase SHA256")


def _safe(value: Any, name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in (".", ".."):
        raise ValueError(f"Unsafe {name}")


def load_plan(path: Path) -> tuple[dict[str, Any], list[tuple[dict[str, Any], Path, list[dict[str, Any]]]]]:
    plan = adapters.strict_json(path.read_text(encoding="utf-8-sig"))
    required = {"schema", "stage", "lane", "budgets", "experiment_identity", "cache_reset", "workloads"}
    if (not isinstance(plan, dict) or not required <= set(plan) or set(plan) - required - {"resume", "token_count_source"}
            or plan["schema"] != SCHEMA or plan["stage"] not in STAGES or plan["lane"] != "P-flow"):
        raise ValueError("Expected a source-only hy30-flow-session-v2 plan")
    budgets = plan["budgets"]
    fields = {"max_translation_calls", "max_judge_calls", "max_estimated_tokens", "max_wall_seconds"}
    if not isinstance(budgets, dict) or set(budgets) != fields:
        raise ValueError("All four protection budgets must be explicit")
    for name in fields - {"max_judge_calls"}:
        positive_number(budgets[name], name, integer=name != "max_wall_seconds")
    if type(budgets["max_judge_calls"]) is not int or budgets["max_judge_calls"] < 0:
        raise ValueError("max_judge_calls must be nonnegative; evaluation owns this budget")
    identity = plan["experiment_identity"]
    if not isinstance(identity, dict) or set(identity) != {"source_manifest_sha256", "split", "seed", "recipe_id", "source_order_sha256"}:
        raise ValueError("Incomplete frozen experiment identity")
    _hash(identity["source_manifest_sha256"], "source_manifest_sha256")
    _hash(identity["source_order_sha256"], "source_order_sha256")
    _safe(identity["split"], "split")
    _safe(identity["recipe_id"], "recipe_id")
    if plan["cache_reset"] != {"method": "fresh-managed-server", "verification": "first-completion-cache-n-zero"}:
        raise ValueError("V2 requires a fresh managed server with measured empty-cache verification")
    workloads = plan["workloads"]
    if not isinstance(workloads, list) or len(workloads) != 1:
        raise ValueError("Each v2 candidate/seed requires its own server session and exactly one workload")
    item = workloads[0]
    keys = {"label", "inputs", "input_sha256", "recipe", "sampling", "cache_prompt", "n_predict", "seed", "max_attempts"}
    if not isinstance(item, dict) or not keys <= set(item) or set(item) - keys - {"terms", "background", "style", "review", "packed_mapping_sha256", "source_manifest_sha256", "source_preparation", "partition_grammar_limits"}:
        raise ValueError("Workload accepts only frozen source/settings fields")
    _safe(item["label"], "workload label")
    if item["recipe"] not in recipes.RECIPES or item["sampling"] not in ("official", "official-temperature0"):
        raise ValueError("V2 recipes must use an explicit official sampling profile")
    if type(item["cache_prompt"]) is not bool:
        raise ValueError("cache_prompt is independent and must be a boolean")
    positive_number(item["n_predict"], "n_predict", integer=True)
    if type(item["max_attempts"]) is not int or item["max_attempts"] not in (1, 2):
        raise ValueError("At most two identical attempts are permitted per pipeline step")
    if type(item["seed"]) is not int or item["seed"] != identity["seed"]:
        raise ValueError("Frozen experiment seed and workload seed differ")
    recipes.completion_request(item, [1])
    if item["recipe"] == "c0" and (item["sampling"] != "official" or item["n_predict"] != 4096 or not item["cache_prompt"]):
        raise ValueError("C0 must retain official sampling, cache and output4096")
    if not isinstance(item["inputs"], str):
        raise ValueError("Source inputs path must be a string")
    inputs = Path(item["inputs"])
    inputs = inputs.resolve() if inputs.is_absolute() else (path.parent / inputs).resolve()
    _hash(item["input_sha256"], "input_sha256")
    if sha256(inputs) != item["input_sha256"]:
        raise ValueError("Frozen source input hash changed")
    windows = read_inputs(inputs)
    if not windows:
        raise ValueError("V2 needs a nonempty frozen source sequence")
    if object_hash([window["id"] for window in windows]) != identity["source_order_sha256"]:
        raise ValueError("Frozen source request order changed")
    visible_ids: set[str] = set()
    for window in windows:
        _safe(window["id"], "window ID")
        ids = [row["id"] for row in window["context"]]
        targets = window["translate_ids"]
        positions = [ids.index(key) for key in targets]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError("Each frozen v2 batch must target a contiguous ordered source range")
        visible_ids.update(ids)
    recipes.validate_options(item, visible_ids)
    if "source_preparation" in item:
        source_options_by_window(item, path, windows)
    if item["recipe"] in recipes.SEMANTIC_RECIPES and item.get("review", False):
        raise ValueError("Semantic review invalidates exact native partition and needs a separately registered flow")
    for name in ("packed_mapping_sha256", "source_manifest_sha256"):
        if name in item:
            _hash(item[name], name)
    if item.get("source_manifest_sha256", identity["source_manifest_sha256"]) != identity["source_manifest_sha256"]:
        raise ValueError("Workload and experiment source manifest identities differ")
    if "token_count_source" in plan:
        auxiliary = plan["token_count_source"]
        if not isinstance(auxiliary, dict) or set(auxiliary) != {"inputs", "input_sha256"}:
            raise ValueError("token_count_source accepts only source inputs path/hash")
        _source_count_windows(auxiliary, path)
    if "resume" in plan:
        resume = plan["resume"]
        if not isinstance(resume, dict) or set(resume) != {"checkpoint", "sha256"} or not isinstance(resume["checkpoint"], str):
            raise ValueError("Resume requires immutable checkpoint path and SHA")
        _hash(resume["sha256"], "checkpoint sha256")
    return plan, [(item, inputs, windows)]


def source_options_by_window(item: dict[str, Any], plan_path: Path,
                             windows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recompute frozen scoped options from the complete source-preparation artifact."""
    if "source_preparation" not in item:
        return {}
    from .v2_source_preparation import load_options, options_for_window
    pointers = item["source_preparation"]
    if (not isinstance(pointers, dict) or set(pointers) != {"artifact", "batch_options"}
            or item["recipe"] == "c0" or item.get("terms") or item.get("background")):
        raise ValueError("Generated source preparation must have its own immutable scoped identity")
    def pointer(value: Any) -> Path:
        if not isinstance(value, dict) or set(value) != {"path", "sha256"} or not isinstance(value["path"], str):
            raise ValueError("Source preparation requires exact artifact pointers")
        _hash(value["sha256"], "source preparation pointer SHA256")
        path = Path(value["path"])
        path = path.resolve() if path.is_absolute() else (plan_path.parent / path).resolve()
        if sha256(path) != value["sha256"]:
            raise ValueError("Frozen source preparation pointer changed")
        return path
    artifact_path = pointer(pointers["artifact"])
    sidecar_path = pointer(pointers["batch_options"])
    artifact = load_options(artifact_path, pointers["artifact"]["sha256"])
    sidecar = adapters.strict_json(sidecar_path.read_text(encoding="utf-8-sig"))
    keys = {"schema", "source_preparation", "packed_mapping_sha256", "source_manifest_sha256",
            "source_scenes_sha256", "scene_ids", "seed", "mode", "windows"}
    version3 = isinstance(sidecar, dict) and sidecar.get("schema") == "hy30-flow-batch-options-v3"
    if version3:
        keys |= {"protocol", "projection"}
    if (not isinstance(sidecar, dict) or set(sidecar) != keys or sidecar["schema"] not in ("hy30-flow-batch-options-v2", "hy30-flow-batch-options-v3")
            or sidecar["source_preparation"] != pointers["artifact"]
            or sidecar["packed_mapping_sha256"] != item.get("packed_mapping_sha256")
            or sidecar["source_manifest_sha256"] != item.get("source_manifest_sha256")
            or sidecar["source_manifest_sha256"] != artifact["source"]["manifest_sha256"]
            or sidecar["source_scenes_sha256"] != artifact["source"]["scenes_sha256"]
            or sidecar["scene_ids"] != artifact["scene_ids"] or sidecar["mode"] != artifact["mode"]
            or sidecar["seed"] != item["seed"] or artifact["settings"]["seed"] != item["seed"]
            or not isinstance(sidecar["windows"], dict)
            or set(sidecar["windows"]) != {window["id"] for window in windows}):
        raise ValueError("Source preparation sidecar differs from frozen source/settings/batches")
    scenes = {row["scene_id"]: row for row in artifact["preparations"]}
    if len(scenes) != len(artifact["preparations"]) or list(scenes) != artifact["scene_ids"]:
        raise ValueError("Source preparation scene coverage or order differs")
    batches = {}
    if version3:
        from .v2_source_projection import project, validate_projection_mode
        if artifact["schema"] != "hy30-source-preparation-options-v3" or sidecar["protocol"] != artifact["protocol"]:
            raise ValueError("New projection requires explicitly matching preparation protocol")
        validate_projection_mode(artifact["mode"], artifact["protocol"], sidecar["projection"])
        mapping_path = plan_path.parent / "packed-mapping.json"
        if sha256(mapping_path) != item["packed_mapping_sha256"]:
            raise ValueError("Frozen projection mapping changed")
        mapping = adapters.strict_json(mapping_path.read_text(encoding="utf-8-sig"))
        if (mapping.get("source_preparation") != pointers["artifact"]
                or mapping.get("source_preparation_projection") != sidecar["projection"]
                or mapping.get("source_preparation_protocol") != sidecar["protocol"]):
            raise ValueError("Projection mapping protocol differs")
        batches = {batch["id"]: batch for batch in mapping["batches"]}
        if len(batches) != len(mapping["batches"]) or list(batches) != [window["id"] for window in windows]:
            raise ValueError("Projection mapping batch coverage/order differs")
    elif artifact["schema"] == "hy30-source-preparation-options-v3":
        raise ValueError("New preparation cannot silently use legacy projection")
    result = {}
    seen_order = []
    for window in windows:
        row = sidecar["windows"][window["id"]]
        if not isinstance(row, dict) or set(row) != ({"scene_id", "options", "visibility"} if version3 else {"scene_id", "options"}) or row["scene_id"] not in scenes:
            raise ValueError("Source preparation batch/scene identity invalid")
        if not seen_order or seen_order[-1] != row["scene_id"]:
            seen_order.append(row["scene_id"])
        if version3:
            batch = batches[window["id"]]
            preparation = scenes[row["scene_id"]]
            if batch["scene_id"] != row["scene_id"] or batch["target_ids"] != window["translate_ids"]:
                raise ValueError("Projection target/scene identity differs")
            local_ids = batch["original_readonly_ids"] + window["translate_ids"]
            if len(local_ids) != len(set(local_ids)):
                raise ValueError("Projection original local IDs duplicate targets")
            source = preparation["source_context"]
            if not set(local_ids) <= {cue["id"] for cue in source}:
                raise ValueError("Projection original local source ID unknown")
            original = {**window, "context": [deepcopy(cue) for cue in source if cue["id"] in set(local_ids)]}
            projected = project(artifact["mode"], artifact["protocol"], sidecar["projection"], preparation, original)
            if (object_hash(projected["window"]) != object_hash(window)
                    or object_hash(projected["visibility"]) != object_hash(row["visibility"])
                    or object_hash(batch.get("source_visibility")) != object_hash(row["visibility"])
                    or batch["readonly_ids"] != [cue["id"] for cue in window["context"] if cue["id"] not in window["translate_ids"]]):
                raise ValueError("Projection actual source/visibility differs from frozen mapping")
            expected = projected["options"]
        else:
            expected = options_for_window(scenes[row["scene_id"]], window)
        if row["options"] != expected:
            raise ValueError("Source preparation batch options differ from exact visible source evidence")
        recipes.validate_options({**item, **expected}, {cue["id"] for cue in window["context"]})
        result[window["id"]] = expected
    if seen_order != artifact["scene_ids"]:
        raise ValueError("Source preparation order differs from translated scene order")
    return result


def _source_count_windows(spec: dict[str, Any], plan_path: Path) -> list[dict[str, Any]]:
    if not isinstance(spec["inputs"], str):
        raise ValueError("Token-count source path must be a string")
    path = Path(spec["inputs"])
    path = path.resolve() if path.is_absolute() else (plan_path.parent / path).resolve()
    _hash(spec["input_sha256"], "token-count input_sha256")
    if sha256(path) != spec["input_sha256"]:
        raise ValueError("Token-count frozen source input changed")
    return read_inputs(path)


class StepFailed(RuntimeError):
    def __init__(self, message: str, kind: str | None = None):
        super().__init__(message)
        self.kind = kind


def run_step(client: Any, prompt: str, item: dict[str, Any], context_size: int,
             budget: Budget, attempts: list[dict[str, Any]], *, stage: str,
             parse: Callable[[str], Any], cache_state: dict[str, Any],
             ids: list[str] | None = None, grammar: str | None = None,
             clock: Callable[[], float] = time.perf_counter,
             on_reserve: Callable[[dict[str, Any]], None] | None = None) -> Any:
    """Count every auxiliary and failed completion before dispatch."""
    last_error = None
    for ordinal in range(item["max_attempts"]):
        start = clock()
        attempt: dict[str, Any] = {"stage": stage, "attempt": ordinal + 1,
                                   "prompt_sha256": object_hash(prompt), "completion_dispatched": False}
        if item["recipe"] == "semantic-partition":
            attempt["prompt"] = prompt
        attempts.append(attempt)
        response = None
        phase = "tokenize"
        try:
            bounded_timeout(client, budget)
            token_start = clock()
            try:
                tokens = client.tokenize(prompt)
            finally:
                attempt.update(tokenize_seconds=clock() - token_start, tokenize_exchange=client.last_exchange)
            attempt.update(input_tokens=len(tokens), input_token_ids_sha256=object_hash(tokens),
                           prompt_transport="token-ids-v1")
            if len(tokens) + item["n_predict"] + GUARD_TOKENS > context_size:
                raise BudgetStopped("context_budget: no silent source truncation")
            request = recipes.completion_request(item, tokens, ids, grammar=grammar)
            attempt.update(request=request, request_sha256=object_hash(request))
            bounded_timeout(client, budget)
            budget.reserve(len(tokens), item["n_predict"])
            if on_reserve:
                on_reserve(attempt)
            attempt["completion_dispatched"] = True
            phase = "completion"
            completion_start = clock()
            try:
                response = client.complete(request)
            finally:
                attempt.update(completion_seconds=clock() - completion_start, original_response=client.last_exchange)
            attempt["response"] = response
            if response.get("error") is not None:
                raise ValueError("Server error: " + json.dumps(response["error"], ensure_ascii=False))
            if not cache_state.get("first_response_checked"):
                reuse = response.get("timings", {}).get("cache_n") if isinstance(response.get("timings"), dict) else None
                cache_state.update(first_response_checked=True, first_response_cache_n=reuse,
                                   exchange=client.last_exchange, verified=type(reuse) is int and reuse == 0)
                attempt["cache_reset_evidence"] = deepcopy(cache_state)
                if not cache_state["verified"]:
                    raise StepFailed("First completion lacks measured empty-cache evidence or reused tokens", "cache")
            attempt["effective_settings"] = effective_settings(response, request)
            if response.get("prompt") is not None and response["prompt"] != prompt:
                raise ValueError("Effective server prompt differs from native template")
            if response.get("tokens_evaluated") is not None and response["tokens_evaluated"] != len(tokens):
                raise ValueError("Effective server token count differs from supplied IDs")
            if response.get("truncated") or response.get("stopped_limit") or response.get("stop_type") == "limit":
                raise ValueError("Generation reached output/context limit")
            content = response.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Empty generated text")
            phase = "validation"
            parse_start = clock()
            result = parse(content)
            attempt.update(validation_seconds=clock() - parse_start, status="accepted")
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            evidence = error
            if getattr(exc, "code", 0) >= 400 and isinstance(client.last_exchange, str):
                raw = Path(client.last_exchange) / "response.raw"
                if raw.is_file():
                    evidence += raw.read_text(encoding="utf-8", errors="replace")
            kind = ("oom" if explicit_oom(evidence) else "budget" if isinstance(exc, BudgetStopped)
                    else exc.kind if isinstance(exc, StepFailed) else None)
            attempt.update(status="failed", error=error, failure_stage=phase, error_kind=kind)
            last_error = StepFailed(error, kind)
            if kind:
                raise last_error from exc
        finally:
            attempt.update(elapsed_seconds=clock() - start, budget_after=budget.snapshot())
    assert last_error is not None
    raise last_error


def run_window(client: Any, window: dict[str, Any], item: dict[str, Any], context_size: int,
               budget: Budget, cache_state: dict[str, Any], *,
               clock: Callable[[], float] = time.perf_counter,
               on_reserve: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    started = clock()
    attempts: list[dict[str, Any]] = []
    row: dict[str, Any] = {"window_id": window["id"], "candidate": CANDIDATE,
                           "recipe": item["recipe"], "sampling_profile": item["sampling"],
                           "scored_ids": window["translate_ids"], "translations": {},
                           "attempts": attempts, "started_at_utc": utc_now()}
    stage = "translation"
    def step(prompt: str, parse: Callable[[str], Any], ids: list[str] | None = None,
             grammar: str | None = None) -> Any:
        return run_step(client, prompt, item, context_size, budget, attempts, stage=stage,
                        parse=parse, cache_state=cache_state, ids=ids, grammar=grammar,
                        clock=clock, on_reserve=on_reserve)
    try:
        if item["recipe"] in recipes.SEMANTIC_RECIPES:
            from . import v2_semantic as semantic
            stage = "source-planning"
            if item["recipe"] in ("semantic-structured", "semantic-partition"):
                if item["recipe"] == "semantic-partition":
                    from . import v2_semantic_partition_grammar as structured
                    row["native_protocol"] = structured.PROTOCOL
                else:
                    from . import v2_semantic_structured as structured
                required = structured.planning_required(window)
                row["planning_cost"] = {"model_planning_required": required}
                planning = (step(structured.planning_prompt(window),
                                 lambda text: structured.parse_planning(text, window),
                                 grammar=structured.planning_grammar(window))
                            if required else structured.parse_planning(None, window))
                row.update(planning)
                planned = planning["semantic_plan"]
            else:
                planned = step(semantic.planning_prompt(window), lambda text: semantic.parse_plan(text, window))
                row["semantic_plan"] = planned
            stage = "joint-unit-translation"
            prompt = (structured.native_prompt(window, planned) if item["recipe"] == "semantic-partition"
                      else semantic.joint_prompt(window, planned))
            extra = recipes.source_options(item, window)
            if extra:
                prompt = prompt.replace("<｜hy_Assistant｜>", "\n" + extra + "<｜hy_Assistant｜>", 1)
            units = [unit["id"] for unit in planned["units"]]
            native = step(prompt, lambda text: adapters.translations(text, units), units)
            row["native_unit_translations"] = native
            stage = "semantic-remapping"
            if item["recipe"] in ("semantic-anchors", "semantic-structured", "semantic-partition"):
                if item["recipe"] in ("semantic-structured", "semantic-partition"):
                    mapper = structured
                else:
                    from . import v2_semantic_anchors as mapper
                required = mapper.mapping_required(window, planned)
                row["mapping_cost"] = {"model_mapping_required": required}
                grammar = None
                if required and item["recipe"] == "semantic-partition":
                    limits = item.get("partition_grammar_limits", {
                        "max_states": mapper.DEFAULT_MAX_STATES,
                        "max_grammar_bytes": mapper.DEFAULT_MAX_GRAMMAR_BYTES})
                    build_started = clock()
                    build: dict[str, Any] = {"protocol": mapper.PROTOCOL, "limits": dict(limits),
                                             "native_text_truncated": False}
                    row["mapping_grammar_build"] = build
                    try:
                        built = mapper.build_mapping_grammar(window, planned, native, **limits)
                        grammar = built["grammar"]
                        build.update(status="accepted", diagnostics=built["diagnostics"],
                                     grammar_sha256=object_hash(grammar))
                    except mapper.GrammarComplexityError as exc:
                        build.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                                     diagnostics=getattr(exc, "diagnostics", {}))
                        raise StepFailed(str(exc), "grammar_complexity") from exc
                    except Exception as exc:
                        build.update(status="failed", error=f"{type(exc).__name__}: {exc}",
                                     diagnostics=getattr(exc, "diagnostics", {}))
                        raise StepFailed(f"Partition grammar build failed: {type(exc).__name__}: {exc}",
                                         "grammar_build") from exc
                    finally:
                        build["elapsed_seconds"] = clock() - build_started
                elif required and item["recipe"] == "semantic-structured":
                    grammar = structured.mapping_grammar(window, planned)
                mapping = (step(mapper.mapping_prompt(window, planned, native),
                                lambda text: mapper.parse_mapping(text, window, planned, native),
                                grammar=grammar)
                           if required else mapper.parse_mapping(None, window, planned, native))
            else:
                mapping = step(semantic.mapping_prompt(window, planned, native),
                               lambda text: semantic.parse_mapping(text, window, planned, native))
            row.update(mapping)
            row["delivery_contract"] = "source-cue-exact-unit-partition-v2"
        else:
            prompt = recipes.render_window(item["recipe"], window, item)
            if item["recipe"] == "id-text-ordered":
                from .v2_id_text import ORDERED_VERSION, ordered_grammar, parse_ordered_text
                row["native_protocol"] = ORDERED_VERSION
                row["native_output_layout"] = "one-marker-and-nonblank-body-per-line"
                row["translations"] = step(prompt, lambda text: parse_ordered_text(text, window["translate_ids"]),
                                           window["translate_ids"], grammar=ordered_grammar(window["translate_ids"]))
            elif item["recipe"] == "id-text-flex":
                from .v2_id_text import VERSION, parse_id_text
                parser = parse_id_text
                row["native_protocol"] = VERSION
                row["translations"] = step(prompt, lambda text: parser(text, window["translate_ids"]), window["translate_ids"])
            else:
                parser = recipes.parse_id_text if item["recipe"] == "id-text" else adapters.translations
                row["translations"] = step(prompt, lambda text: parser(text, window["translate_ids"]), window["translate_ids"])
            row["delivery_contract"] = "source-cue-preserved-v2"
        if item.get("review", False):
            if item["recipe"] in recipes.SEMANTIC_RECIPES:
                raise ValueError("Semantic review would invalidate exact native partition; register a separate flow")
            row["before_review"] = deepcopy(row["translations"])
            stage = "source-review"
            row["translations"] = step(recipes.review_prompt(window, row["translations"]),
                                        lambda text: adapters.translations(text, window["translate_ids"]),
                                        grammar=adapters.id_grammar(window["translate_ids"]))
        row["status"] = "delivered"
    except StepFailed as exc:
        row.update(status="mapping_unjudgeable" if stage == "semantic-remapping" else "translation_failed",
                   reason=str(exc), failure_stage=stage, error_kind=exc.kind)
        row["translations"] = {}
        if exc.kind in ("budget", "oom", "cache"):
            row["stop_reason"] = str(exc) if exc.kind == "budget" else exc.kind
        if not any(attempt["completion_dispatched"] for attempt in attempts):
            row["status"] = "setup_failed" if "context_budget" in str(exc) else "not_run"
    except Exception as exc:
        row.update(status="setup_failed", reason=f"{type(exc).__name__}: {exc}", failure_stage=stage)
        row["translations"] = {}
    auxiliary = [attempt for attempt in attempts if attempt["stage"] not in ("translation", "joint-unit-translation")]
    for name, phase in (("planning_cost", "source-planning"), ("mapping_cost", "semantic-remapping")):
        if name not in row:
            continue
        phase_attempts = [attempt for attempt in attempts if attempt["stage"] == phase]
        row[name].update(
            completion_calls=sum(attempt["completion_dispatched"] for attempt in phase_attempts),
            elapsed_seconds=sum(attempt["elapsed_seconds"] for attempt in phase_attempts),
            generation_seconds=sum(attempt.get("completion_seconds", 0) for attempt in phase_attempts),
            input_tokens=sum(attempt.get("input_tokens", 0) for attempt in phase_attempts),
            output_tokens=sum(attempt.get("response", {}).get("tokens_predicted", 0) for attempt in phase_attempts))
        if name == "mapping_cost" and "mapping_grammar_build" in row:
            build_seconds = row["mapping_grammar_build"]["elapsed_seconds"]
            row[name]["grammar_build_seconds"] = build_seconds
            row[name]["elapsed_seconds"] += build_seconds
    row.update(elapsed_seconds=clock() - started,
               auxiliary_seconds=(sum(attempt["elapsed_seconds"] for attempt in auxiliary)
                                  + row.get("mapping_grammar_build", {}).get("elapsed_seconds", 0)),
               generation_seconds=sum(attempt.get("completion_seconds", 0) for attempt in attempts),
               finished_at_utc=utc_now(), original_response=attempts[-1].get("original_response") if attempts else None)
    return row


def _managed_cache_evidence(identity: dict[str, Any]) -> dict[str, Any]:
    engine = identity["engine"]
    pid = engine.get("server_pid")
    command = engine.get("command")
    if type(pid) is not int or pid < 1 or not isinstance(command, list):
        raise ValueError("Fresh managed server PID and launch command evidence are required")
    try:
        if command[command.index("-np") + 1] != "1":
            raise ValueError("V2 requires the frozen single-slot runtime")
    except (ValueError, IndexError) as exc:
        raise ValueError("Single-slot launch evidence missing") from exc
    return {"method": "fresh-managed-server", "server_pid": pid, "verified": False,
            "first_response_checked": False,
            "verification_scope": "first completion timings.cache_n; tokens_cached is retained-state size, not reuse"}


def _checkpoint(path: Path, state: dict[str, Any]) -> None:
    """Atomically replace only this session's checkpoint, never prior artifacts."""
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _resume(plan: dict[str, Any], plan_path: Path, compatibility: str,
            windows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    if "resume" not in plan:
        return {}, None
    path = Path(plan["resume"]["checkpoint"])
    path = path.resolve() if path.is_absolute() else (plan_path.parent / path).resolve()
    if sha256(path) != plan["resume"]["sha256"]:
        raise ValueError("Resume checkpoint changed")
    state = adapters.strict_json(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(state, dict) or state.get("schema") != CHECKPOINT_SCHEMA
            or state.get("compatibility_sha256") != compatibility
            or state.get("expected_window_ids") != [window["id"] for window in windows]):
        raise ValueError("Resume source, recipe, seed, engine, template or state identity differs")
    completed = {}
    for artifact in state.get("completed", []):
        row_path = Path(artifact["path"])
        if sha256(row_path) != artifact["sha256"]:
            raise ValueError("Completed resume artifact changed")
        row = adapters.strict_json(row_path.read_text(encoding="utf-8-sig"))
        key = row.get("window_id")
        if key not in state["expected_window_ids"] or key in completed or row.get("status") != "delivered":
            raise ValueError("Resume artifact is not a unique completed frozen window")
        expected = next(window["translate_ids"] for window in windows if window["id"] == key)
        if set(row.get("translations", {})) != set(expected):
            raise ValueError("Resume output coverage differs")
        completed[key] = {"row": row, "artifact": artifact}
    return completed, state


def execute_plan(args: argparse.Namespace, client_factory: Any = LlamaClient,
                 identity_loader: Any = validate_runtime,
                 clock: Callable[[], float] = time.perf_counter) -> int:
    started = clock()
    if args.candidate != CANDIDATE:
        raise ValueError("V2 is fixed to APEX-I-Compact")
    plan, loaded = load_plan(args.session_plan)
    item, inputs, windows = loaded[0]
    scoped_options = source_options_by_window(item, args.session_plan, windows)
    scoped_provenance = {}
    if scoped_options:
        pointer = item["source_preparation"]["batch_options"]
        sidecar_path = Path(pointer["path"])
        if not sidecar_path.is_absolute():
            sidecar_path = args.session_plan.parent / sidecar_path
        if sha256(sidecar_path) != pointer["sha256"]:
            raise ValueError("Source preparation sidecar changed after validation")
        sidecar = adapters.strict_json(sidecar_path.read_text(encoding="utf-8-sig"))
        if sidecar["schema"] == "hy30-flow-batch-options-v3":
            scoped_provenance = {key: {"protocol": sidecar["protocol"], "projection": sidecar["projection"],
                                      "source_visibility": deepcopy(value["visibility"])}
                                 for key, value in sidecar["windows"].items()}
    identity = identity_loader(args)
    cache = _managed_cache_evidence(identity)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    budget = Budget(plan["budgets"], clock)
    budget.started = started
    code_hashes = source_snapshot(output)
    compatibility_plan = {key: value for key, value in plan.items() if key != "resume"}
    stable_engine = {key: value for key, value in identity["engine"].items()
                     if key in ("build", "cuda", "model_sha256", "executable_sha256", "custom_runtime_identity_sha256",
                                "context_size", "gpu_layers_requested", "threads", "threads_batch", "kv_type_k", "kv_type_v",
                                "prompt_cache_ram_mib", "runtime_source_sha256", "runtime_dll_sha256")}
    compatibility = object_hash({"plan": compatibility_plan, "context_size": args.context_size,
                                 "asset": identity["asset"], "engine": stable_engine,
                                 "template_sha256": identity["template_sha256"], "code_sha256": code_hashes})
    resumed, prior = _resume(plan, args.session_plan, compatibility, windows)
    if prior:
        previous = prior["budget"]
        budget.translation_calls = previous["translation_calls"]
        budget.estimated_tokens = previous["estimated_tokens"]
        budget.started -= previous["wall_seconds"]
    write_json(output / "session-plan.json", plan)
    client = client_factory(args.server_url, trace_dir=output / "transport")
    bounded_timeout(client, budget)
    props = client.request("/props")
    actual = props.get("model_path", props.get("model_alias"))
    if actual is not None and actual != CANDIDATE and Path(actual).resolve() != Path(identity["engine"]["model_path"]).resolve():
        raise ValueError("Live server differs from verified APEX asset")
    write_json(output / "session.json", {"schema": SCHEMA, "plan_sha256": sha256(args.session_plan),
               "created_at_utc": utc_now(), "identity": identity, "server_props": props,
               "code_sha256": code_hashes, "compatibility_sha256": compatibility,
               "recipe_version": recipes.VERSION, "cache_reset": cache,
               "memory_state": {"terms": item.get("terms", []), "background": item.get("background", []),
                                "state_sha256": object_hash({key: item.get(key, []) for key in ("terms", "background")}),
                                "scope": "frozen source-evidenced options; no implicit history"},
               "resume": plan.get("resume"), "performance_valid_for_fresh_flow": not bool(prior)})
    target = output / item["label"]
    target.mkdir()
    (target / "inputs.jsonl").write_bytes(inputs.read_bytes())
    write_json(target / "run.json", {"phase": "translation", "schema": SCHEMA, "lane": "P-flow",
               "candidate": CANDIDATE, "recipe": item["recipe"], "settings": item,
               "expected_window_ids": [window["id"] for window in windows],
               "input_sha256": item["input_sha256"], "session_plan_sha256": sha256(args.session_plan),
               "source_manifest_sha256": plan["experiment_identity"]["source_manifest_sha256"],
               "packed_mapping_sha256": item.get("packed_mapping_sha256"),
               "source_preparation": item.get("source_preparation"),
               "compatibility_sha256": compatibility, "code_sha256": code_hashes})
    for name in ("results.jsonl", "ledger.jsonl", "schedule.jsonl", "dispatch-journal.jsonl"):
        (target / name).touch(exist_ok=False)
    checkpoint = {"schema": CHECKPOINT_SCHEMA, "compatibility_sha256": compatibility,
                  "expected_window_ids": [window["id"] for window in windows],
                  "completed": [value["artifact"] for value in resumed.values()],
                  "budget": budget.snapshot(), "active_dispatch": None,
                  "cache_reset": cache, "source_options_sha256": object_hash(item)}
    def save() -> None:
        checkpoint.update(budget=budget.snapshot(), cache_reset=deepcopy(cache), updated_at_utc=utc_now())
        _checkpoint(output / "checkpoint.json", checkpoint)
    def reserve(attempt: dict[str, Any]) -> None:
        checkpoint["active_dispatch"] = {"window_id": current_id, "stage": attempt["stage"],
                                          "request_sha256": attempt["request_sha256"],
                                          "reserved_tokens": attempt["input_tokens"] + item["n_predict"]}
        append_json(target / "dispatch-journal.jsonl", {**checkpoint["active_dispatch"],
                    "status": "reserved_before_dispatch", "at_utc": utc_now(), "budget": budget.snapshot()})
        save()
    failures, count, reused = 0, 0, 0
    stopped = None
    token_count_completed = False
    token_count_summary = None
    append_json(output / "workload-ledger.jsonl", {"label": item["label"], "status": "started", "at_utc": utc_now()})
    save()
    for window in windows:
        current_id = window["id"]
        if stopped:
            append_json(target / "schedule.jsonl", {"window_id": current_id, "status": "not_run", "reason": stopped})
            continue
        if sha256(inputs) != item["input_sha256"]:
            stopped = "frozen_source_changed"
            failures += 1
            append_json(target / "schedule.jsonl", {"window_id": current_id, "status": "not_run", "reason": stopped})
            continue
        if current_id in resumed:
            previous = resumed[current_id]
            row = {**deepcopy(previous["row"]), "status": "delivered", "elapsed_seconds": None,
                   "generation_seconds": None, "auxiliary_seconds": None, "attempts": [],
                   "reused_artifact": previous["artifact"], "reused_not_new_measurement": True}
            reused += 1
        else:
            if scoped_options:
                for pointer in item["source_preparation"].values():
                    path = Path(pointer["path"])
                    path = path.resolve() if path.is_absolute() else (args.session_plan.parent / path).resolve()
                    if sha256(path) != pointer["sha256"]:
                        raise ValueError("Source preparation changed between frozen validation and dispatch")
            scoped_item = {**item, **scoped_options.get(current_id, {})}
            row = run_window(client, window, scoped_item, args.context_size, budget, cache,
                             clock=clock, on_reserve=reserve)
            if scoped_options:
                row["source_preparation"] = {"identity": item["source_preparation"],
                                              "visible_options_sha256": object_hash(scoped_options[current_id]),
                                              "cost_attribution": "shared separate preparation; no per-batch duplicate cost"}
                row["source_preparation"].update(deepcopy(scoped_provenance.get(current_id, {})))
        row_path = target / f"window-{current_id}.json"
        write_json(row_path, row)
        append_json(target / "ledger.jsonl", row)
        append_json(target / "results.jsonl", {"id": current_id, "translations": row["translations"],
                    "elapsed_seconds": row["elapsed_seconds"], "status": row["status"],
                    **({"source_span_to_target_span": row["source_span_to_target_span"]}
                       if "source_span_to_target_span" in row else {})})
        count += 1
        failures += row["status"] != "delivered"
        if row["status"] == "delivered" and current_id not in resumed:
            checkpoint["completed"].append({"window_id": current_id, "path": str(row_path), "sha256": sha256(row_path)})
        checkpoint["active_dispatch"] = None
        save()
        print(f"{item['label']} {count}/{len(windows)} {current_id} {row['status']}", flush=True)
        if row.get("error_kind") in ("budget", "oom", "cache"):
            stopped = row.get("stop_reason", row["error_kind"])
        if cache.get("verified") and not stopped and "token_count_source" in plan and not token_count_completed:
            try:
                source_windows = _source_count_windows(plan["token_count_source"], args.session_plan)
                token_count_summary = source_token_counts(client, source_windows, identity, budget,
                                                         output / "source-token-counts.json", clock=clock)
                token_count_completed = True
                save()
            except Exception as exc:
                stopped = f"source_token_count_failed: {type(exc).__name__}: {exc}"
                failures += 1
                count_path = output / "source-token-counts.json"
                if count_path.is_file():
                    count_report = adapters.strict_json(count_path.read_text(encoding="utf-8-sig"))
                    token_count_summary = {"artifact": str(count_path), "sha256": sha256(count_path),
                                           "attempts": len(count_report["attempts"]),
                                           "elapsed_seconds": count_report["elapsed_seconds"], "complete": False}
    remaining = [window["id"] for window in windows if not (target / f"window-{window['id']}.json").exists()]
    if "token_count_source" in plan and not token_count_completed and not stopped:
        stopped = "source_token_count_requires_fresh_completion_cache_verification"
        failures += 1
    write_json(target / "completion.json", {"windows": count, "expected_windows": len(windows),
               "remaining_window_ids": remaining, "stopped_reason": stopped, "failures": failures,
               "reused_windows": reused, "cache_reset": cache, "budget_after": budget.snapshot()})
    append_json(output / "workload-ledger.jsonl", {"label": item["label"], "status": "interrupted" if stopped else "phase_finished",
                "at_utc": utc_now(), "stopped_reason": stopped, "remaining_window_ids": remaining})
    save()
    write_json(output / "worker-completion.json", {"schema": SCHEMA, "complete": not failures and not stopped,
               "failures": failures, "stopped_reason": stopped, "budget": budget.snapshot(),
               "worker_wall_seconds": clock() - started, "finished_at_utc": utc_now(),
               "cache_reset": cache, "reused_windows": reused, "performance_valid_for_fresh_flow": not bool(prior),
               "cost_scope": "includes source validation, preparation, tokenize, every planning/translation/mapping/review/retry and durable artifacts; parent runtime startup SHA, load/unload, export and evaluation remain separately measured",
               "inherited_budget": prior["budget"] if prior else None,
               "source_token_count_cost": token_count_summary,
               "unresolved_prior_dispatch": prior.get("active_dispatch") if prior else None})
    return 1 if failures or stopped else 0


def source_token_counts(client: Any, windows: list[dict[str, Any]], identity: dict[str, Any],
                        budget: Budget, path: Path, *, clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """Freeze additive cue token estimates; full rendered prompts remain authoritative."""
    started = clock()
    sources: dict[str, str] = {}
    for window in windows:
        for row in window["context"]:
            key, text = row["id"], row["text"]
            if key in sources and sources[key] != text:
                raise ValueError("Same source cue ID has inconsistent source text")
            sources[key] = text
    attempts = []
    counts = {}
    report: dict[str, Any] = {"schema": "hy30-source-token-counts-v2", "complete": False,
                             "candidate": CANDIDATE, "asset": identity["asset"],
                             "engine_manifest_sha256": identity["engine_manifest_sha256"],
                             "template_sha256": identity["template_sha256"],
                             "source_text_sha256": object_hash(sources), "cue_token_counts": counts,
                             "tokenize_parameters": {"add_special": False, "parse_special": True},
                             "attempts": attempts,
                             "count_scope": "source cue text alone; additive packing estimate excludes prompt/template/IDs; exact batch tokenize check still required"}
    try:
        for key, text in sources.items():
            begin = clock()
            attempt = {"cue_id": key, "source_text_sha256": object_hash(text)}
            attempts.append(attempt)
            try:
                bounded_timeout(client, budget)
                tokens = client.tokenize(text)
                counts[key] = len(tokens)
                attempt.update(status="accepted", tokens=len(tokens))
            except Exception as exc:
                attempt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                raise
            finally:
                attempt.update(elapsed_seconds=clock() - begin, exchange=client.last_exchange)
        report["complete"] = True
    finally:
        report["elapsed_seconds"] = clock() - started
        write_json(path, report)
    return {"attempts": len(attempts), "elapsed_seconds": report["elapsed_seconds"],
            "artifact": str(path), "sha256": sha256(path), "complete": report["complete"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="第二轮源文字幕流程；每配方与seed使用新的受管理服务")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--session-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--engine-manifest", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=8192)
    parser.add_argument("--asset-manifest", type=Path, action="append")
    parser.add_argument("--stop-on-oom", action="store_true")
    args = parser.parse_args()
    if args.candidate != CANDIDATE:
        raise ValueError("V2 is fixed to APEX-I-Compact")
    positive_number(args.context_size, "context_size", integer=True)
    return execute_plan(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
