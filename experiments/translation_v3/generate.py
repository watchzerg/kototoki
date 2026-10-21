"""Resumable per-scene generation on a fresh managed server per session."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, ContextManager, Iterator
from urllib.error import HTTPError, URLError

from experiments.translation_demo.run import explicit_oom

from . import recipes as R
from .batching import Batch, build_batches, cue_positions
from .common import (atomic_write_json, code_identity, object_hash, read_json, safe_name,
                     sha256_bytes, utc_now)
from .data import Scene
from .recipes import Recipe

RUN_SCHEMA = "hy30-flow-v3-run-v1"
SCENE_SCHEMA = "hy30-flow-v3-scene-v1"
FATAL_KINDS = ("oom", "cache", "server")
# Infrastructure failures never become terminal scene files; the scene is retried by the next session.
INFRA_KINDS = ("oom", "cache", "server", "server_error")
# Only these, after the allowed attempts, are recorded as terminal scene failures.
TERMINAL_KINDS = ("context", "limit", "parse")
CONTEXT_ERROR = re.compile(r"exceed[s]? the available context|context size|n_ctx|context length", re.IGNORECASE)


def run_id_for(recipe: Recipe, seed: int, scope: str) -> str:
    return f"{recipe.recipe_id}__s{seed}__{safe_name(scope, 'scope')}"


@dataclass
class SessionHandle:
    client: Any
    identity: dict[str, Any]


SessionFactory = Callable[[Path, int], ContextManager[SessionHandle]]


def managed_session_factory(root: Path, run_id: str, *, port: int = 8080, break_stale_lock: bool = False,
                            timeout: float = 600.0) -> SessionFactory:
    """Real GPU session: v3 gpu.lock + fresh llama-server + loopback client with raw traces."""
    @contextmanager
    def factory(run_dir: Path, index: int) -> Iterator[SessionHandle]:
        from experiments.translation_demo.client import LlamaClient
        from .server import GpuLock, ManagedServer
        lock = GpuLock(run_id)
        lock.acquire(break_stale=break_stale_lock)
        try:
            with ManagedServer(run_dir / "runtime" / f"session-{index:02d}", port=port, root=root) as server:
                lock.update(server_pid=server.identity.get("server_pid"),
                            server_created=server.identity.get("server_created"))
                client = LlamaClient(server.url, timeout=timeout, trace_dir=run_dir / "transport" / f"session-{index:02d}")
                yield SessionHandle(client, dict(server.identity, gpu_lock_replaced_stale=lock.stale,
                                                 owner_pid=lock.pid, owner_created=lock.created))
        finally:
            lock.release()
    return factory


class StepFailed(RuntimeError):
    def __init__(self, message: str, kind: str):
        super().__init__(message)
        self.kind = kind


def whitespace_ratio(text: Any) -> float | None:
    if not isinstance(text, str) or not text:
        return None
    return sum(ch.isspace() for ch in text) / len(text)


def _http_body(client: Any) -> str:
    exchange = getattr(client, "last_exchange", None)
    if isinstance(exchange, str):
        raw = Path(exchange) / "response.raw"
        if raw.is_file():
            return raw.read_text(encoding="utf-8", errors="replace")
    return ""


def run_step(client: Any, prompt: str, grammar: str, seed: int, parse: Callable[[str], Any],
             cache_state: dict[str, Any], record: dict[str, Any], overrides: dict[str, Any] | None = None) -> Any:
    """Tokenize, guard the budget, complete, validate; at most two identical attempts."""
    attempts: list[dict[str, Any]] = record.setdefault("attempts", [])
    last: StepFailed | None = None
    for number in range(1, R.MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        attempt: dict[str, Any] = {"attempt": number, "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                                   "grammar_sha256": sha256_bytes(grammar.encode("utf-8")), "dispatched": False}
        attempts.append(attempt)
        try:
            try:
                tokens = client.tokenize(prompt)
            except (URLError, ConnectionError, TimeoutError) as exc:
                raise StepFailed(f"tokenize transport: {exc}", "server") from exc
            attempt.update(input_tokens=len(tokens), tokenize_exchange=getattr(client, "last_exchange", None))
            if len(tokens) > R.MAX_INPUT_TOKENS:
                raise StepFailed(f"context_budget: {len(tokens)} input tokens + {R.N_PREDICT} + {R.GUARD_TOKENS} "
                                 f"> {R.CONTEXT_SIZE}; no truncation or auto-shrink", "context")
            request = R.completion_request(tokens, seed, grammar, overrides)
            attempt["request_sha256"] = object_hash(request)
            attempt["dispatched"] = True
            completion_start = time.perf_counter()
            try:
                response = client.complete(request)
            except HTTPError as exc:
                body = _http_body(client) + str(exc)
                kind = "oom" if explicit_oom(body) else "context" if CONTEXT_ERROR.search(body) else "server_error"
                raise StepFailed(f"HTTP {exc.code}: {body[:500]}", kind) from exc
            except (URLError, ConnectionError, TimeoutError) as exc:
                raise StepFailed(f"completion transport: {exc}", "server") from exc
            finally:
                attempt.update(completion_seconds=time.perf_counter() - completion_start,
                               exchange=getattr(client, "last_exchange", None))
            timings = response.get("timings") if isinstance(response.get("timings"), dict) else {}
            content = response.get("content")
            attempt.update(output_tokens=response.get("tokens_predicted"), tokens_evaluated=response.get("tokens_evaluated"),
                           timings=timings, stop_type=response.get("stop_type"),
                           stopped_limit=bool(response.get("stopped_limit") or response.get("stop_type") == "limit"),
                           truncated=bool(response.get("truncated")),
                           content_chars=len(content) if isinstance(content, str) else None)
            if not cache_state.get("checked"):
                reuse = timings.get("cache_n")
                cache_state.update(checked=True, first_cache_n=reuse, verified=type(reuse) is int and reuse == 0,
                                   exchange=attempt.get("exchange"))
                attempt["cache_reset_check"] = dict(cache_state)
                if not cache_state["verified"]:
                    raise StepFailed(f"First completion lacks timings.cache_n == 0 (got {reuse!r})", "cache")
            if response.get("error") is not None:
                text = json.dumps(response["error"], ensure_ascii=False)
                raise StepFailed("server error: " + text, "oom" if explicit_oom(text) else "server_error")
            if response.get("tokens_evaluated") is not None and response["tokens_evaluated"] != len(tokens):
                raise StepFailed("server evaluated a different token count", "server_error")
            if attempt["stopped_limit"] or attempt["truncated"]:
                attempt["whitespace_ratio"] = whitespace_ratio(content)
                raise StepFailed("generation reached the output/context limit", "limit")
            if not isinstance(content, str) or not content.strip():
                raise StepFailed("empty generated text", "parse")
            try:
                result = parse(content)
            except ValueError as exc:
                attempt["whitespace_ratio"] = whitespace_ratio(content)
                raise StepFailed(f"validation: {exc}", "parse") from exc
            attempt["status"] = "accepted"
            record["status"] = "accepted"
            return result
        except StepFailed as exc:
            attempt.update(status="failed", error=str(exc)[:2000], error_kind=exc.kind)
            last = exc
            if exc.kind in FATAL_KINDS or exc.kind == "context":
                break
        finally:
            attempt["elapsed_seconds"] = time.perf_counter() - started
    assert last is not None
    record.update(status="failed", error_kind=last.kind)
    raise last


def translate_scene(client: Any, scene: Scene, recipe: Recipe, seed: int, cache_state: dict[str, Any],
                    token_counts: dict[str, int] | None) -> dict[str, Any]:
    started = time.perf_counter()
    recipe = recipe.for_category(scene.category)
    batches = build_batches(scene, recipe, token_counts)
    row: dict[str, Any] = {"schema": SCENE_SCHEMA, "scene_id": scene.scene_id, "started_at_utc": utc_now(),
                           "cue_ids": scene.ids, "positions": cue_positions(batches),
                           "batches": [batch.record() for batch in batches], "requests": [],
                           "translations": {}, "terms": None, "failure": None}
    stage, batch_index = "setup", None
    try:
        terms: list[dict[str, Any]] = []
        if recipe.preanalysis == "terms":
            stage = "terms"
            cues = [{"id": cue.id, "text": cue.text} for cue in scene.cues]
            record = {"stage": stage, "batch_index": None}
            row["requests"].append(record)
            row["terms"] = run_step(client, R.terms_prompt(cues), R.terms_grammar(recipe.grammar_ws),
                                    seed, lambda text: R.parse_terms(text, cues), cache_state, record)
            terms = row["terms"]["terms"]
        text_of = {cue.id: cue.text for cue in scene.cues}
        for batch in batches:
            batch_index = batch.index
            window = batch.to_window(scene)
            ids = list(batch.target_ids)
            stage = "translation"
            history = ([{"ja": text_of[key], "zh": row["translations"][key]} for key in scene.ids[:batch.start]]
                       if recipe.target_context else None)
            info = row["batches"][batch.index]
            if recipe.model:  # v9: chat completions on the general model (qwen.py), same packs and grammar
                from . import qwen
                record = {"stage": stage, "batch_index": batch.index}
                row["requests"].append(record)
                result = qwen.run_step(client, qwen.messages(window), R.translation_grammar(recipe, ids), seed, ids,
                                       cache_state, record, recipe)
                row["translations"].update(result)
                continue
            prompt = R.render_translation(recipe, window, terms, history, scene.work_id, batch.pauses,
                                         batch.groups)
            if recipe.candidates == 1:
                record = {"stage": stage, "batch_index": batch.index}
                row["requests"].append(record)
                result = run_step(client, prompt, R.translation_grammar(recipe, ids), seed,
                                  lambda text: R.parse_translation(text, ids), cache_state, record, recipe.sampling)
            else:
                result = _multi_sample(client, prompt, R.translation_grammar(recipe, ids), seed, ids, recipe,
                                       cache_state, row, info, batch.index)
            info["terms_injected"] = len(R.terms_for_window(terms, window))
            if recipe.glossary:
                info["glossary_injected"] = len(R.glossary_for_window(recipe, scene.work_id, window))
            if recipe.review == "risk-trigger":
                triggered = R.risk_triggered([cue.text for cue in scene.cues if cue.id in batch.target_ids])
                info["review_triggered"] = triggered
                if triggered:
                    stage = "review"
                    info["before_review"] = result
                    record = {"stage": stage, "batch_index": batch.index}
                    row["requests"].append(record)
                    result = run_step(client, R.review_prompt(window, result), R.translation_grammar(recipe, ids), seed,
                                      lambda text: R.parse_translation(text, ids), cache_state, record)
                    info["review_changed_ids"] = sorted(key for key in ids if result[key] != info["before_review"][key])
            row["translations"].update(result)
        row["status"] = "complete"
    except StepFailed as exc:
        row.update(status="failed", failure={"stage": stage, "batch_index": batch_index, "kind": exc.kind,
                                             "error": str(exc)[:2000], "fatal": exc.kind in FATAL_KINDS,
                                             "infra": exc.kind in INFRA_KINDS})
    row.update(finished_at_utc=utc_now(), elapsed_seconds=time.perf_counter() - started,
               totals={"requests": len(row["requests"]),
                       "attempts": sum(len(r.get("attempts", [])) for r in row["requests"]),
                       "input_tokens": sum(a.get("input_tokens") or 0 for r in row["requests"] for a in r.get("attempts", [])),
                       "output_tokens": sum(a.get("output_tokens") or 0 for r in row["requests"] for a in r.get("attempts", [])),
                       "limit_failures": sum(bool(a.get("stopped_limit")) for r in row["requests"] for a in r.get("attempts", []))})
    return row


def _multi_sample(client: Any, prompt: str, grammar: str, seed: int, ids: list[str], recipe: Recipe,
                  cache_state: dict[str, Any], row: dict[str, Any], info: dict[str, Any], batch_index: int) -> dict[str, str]:
    """N samples of one batch (same prompt, seeds via R.sample_seed), then the local selector.

    A sample that fails terminally (limit/parse after its attempts) is dropped and recorded; the
    batch fails only when every sample fails. Infrastructure failures stop the scene as usual."""
    from .mbr import select
    samples, failed, last = [], [], None
    for k in range(recipe.candidates):
        record = {"stage": "translation", "batch_index": batch_index, "sample": k}
        row["requests"].append(record)
        try:
            samples.append(run_step(client, prompt, grammar, R.sample_seed(seed, k),
                                    lambda text: R.parse_translation(text, ids), cache_state, record, recipe.sampling))
        except StepFailed as exc:
            if exc.kind in INFRA_KINDS or exc.kind == "context":
                raise
            failed.append({"sample": k, "kind": exc.kind})
            last = exc
    if not samples:
        assert last is not None
        raise last
    selected, choice = select(recipe.selector, samples, ids)
    info.update(candidates=samples, failed_samples=failed, selection=choice)
    return selected


def scene_state(run_dir: Path, scene_id: str) -> str | None:
    """complete / failed (terminal) / infra_failed (legacy file from an infrastructure stop: retried) / None."""
    path = run_dir / "scenes" / f"{scene_id}.json"
    if not path.is_file():
        return None
    row = read_json(path)
    if row.get("status") == "failed" and (row.get("failure") or {}).get("kind") in INFRA_KINDS:
        return "infra_failed"
    return row.get("status")


def _count_tokens(client: Any, run_dir: Path, scenes: list[Scene]) -> dict[str, int]:
    """Per-cue source tokens via /tokenize, cached per run (keyed by cue text hash)."""
    path = run_dir / "token-counts.json"
    cache: dict[str, Any] = read_json(path) if path.is_file() else {}
    pending = 0
    for scene in scenes:
        for cue in scene.cues:
            digest = sha256_bytes(cue.text.encode("utf-8"))
            if cache.get(cue.id, {}).get("text_sha256") != digest:
                cache[cue.id] = {"tokens": len(client.tokenize(cue.text)), "text_sha256": digest}
                pending += 1
                if pending % 100 == 0:
                    atomic_write_json(path, cache)
    atomic_write_json(path, cache)
    return {key: value["tokens"] for key, value in cache.items()}


def _next_session_index(run_dir: Path, run: dict[str, Any]) -> int:
    used = [len(run["sessions"])] + [s.get("index", 0) for s in run["sessions"]]
    for folder in ("runtime", "transport"):
        for path in (run_dir / folder).glob("session-*") if (run_dir / folder).is_dir() else []:
            suffix = path.name.removeprefix("session-")
            if suffix.isdigit():
                used.append(int(suffix))
    return max(used) + 1


SESSION_ENGINE_KEYS = ("candidate", "model_path", "engine_sha256", "engine_identity_sha256", "command", "server_pid",
                       "server_created", "kill_on_job_close", "owner_pid", "owner_created", "cold_load_seconds",
                       "residency", "model_verification", "gpu_lock_replaced_stale")


def run_generation(run_dir: Path, recipe: Recipe, seed: int, scenes: list[Scene], *, scope: str,
                   sources: dict[str, Any], session_factory: SessionFactory,
                   retry_failed: bool = False, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Generate all scenes in source order; skip written ones; one fresh server per session.

    A session is recorded only once its server has started. Infrastructure failures (OOM,
    transport, cache check, server errors) stop the session without a terminal scene file,
    so the next invocation retries that scene; evidence goes to ``infra-failures/``.
    """
    run_id = run_id_for(recipe, seed, scope)
    if run_dir.name != run_id:
        raise ValueError(f"Run directory must be named {run_id}")
    run_path = run_dir / "run.json"
    scene_ids = [scene.scene_id for scene in scenes]
    if run_path.is_file():
        run = read_json(run_path)
        if (run["recipe_hash"] != recipe.recipe_hash or run["seed"] != seed or run["scope"] != scope
                or run["sources"] != sources or run["scene_ids"] != scene_ids):
            raise ValueError(f"{run_id}: existing run.json differs in recipe/seed/scope/sources/scenes; use a new recipe name")
    else:
        run = {"schema": RUN_SCHEMA, "run_id": run_id, "recipe": recipe.to_json(), "recipe_hash": recipe.recipe_hash,
               "seed": seed, "scope": scope, "sources": sources, "scene_ids": scene_ids,
               "created_at_utc": utc_now(), "code": code_identity(), "sessions": [], "resumed": False,
               "completion": {"state": "not_started"}, "wall_clock_seconds": None}
    terminal = ("complete", "failed") if not retry_failed else ("complete",)
    pending = [scene for scene in scenes if scene_state(run_dir, scene.scene_id) not in terminal]
    if not pending:
        return _finish(run_dir, run, scenes) if run_path.is_file() else run
    index = _next_session_index(run_dir, run)
    session: dict[str, Any] = {"index": index, "started_at_utc": utc_now(), "code": code_identity(),
                               "pending_at_start": [scene.scene_id for scene in pending],
                               "scenes_written": [], "stop_reason": None, "infra_failure": None}
    started = time.perf_counter()
    cache_state: dict[str, Any] = {"checked": False}
    entered = False
    try:
        with session_factory(run_dir, index) as handle:
            entered = True
            session["engine"] = {key: handle.identity.get(key) for key in SESSION_ENGINE_KEYS}
            session["load_done_seconds"] = time.perf_counter() - started
            run["sessions"].append(session)
            atomic_write_json(run_path, run)
            counts = _count_tokens(handle.client, run_dir, scenes) if recipe.needs_token_counts else None
            for number, scene in enumerate(pending, 1):
                row = translate_scene(handle.client, scene, recipe, seed, cache_state, counts)
                row.update(run_id=run_id, session=index)
                failure = row.get("failure") or {}
                if row["status"] == "failed" and failure.get("kind") in INFRA_KINDS:
                    evidence = run_dir / "infra-failures" / f"{scene.scene_id}--session-{index:02d}.json"
                    atomic_write_json(evidence, row)
                    session["infra_failure"] = {"scene_id": scene.scene_id, "kind": failure["kind"],
                                                "error": failure.get("error"), "evidence": str(evidence)}
                    session["stop_reason"] = failure["kind"]
                    log(f"{run_id} scene {number}/{len(pending)} {scene.scene_id} infra failure "
                        f"({failure['kind']}); session stopped, scene will be retried")
                    break
                atomic_write_json(run_dir / "scenes" / f"{scene.scene_id}.json", row)
                session["scenes_written"].append(scene.scene_id)
                atomic_write_json(run_path, run)
                log(f"{run_id} scene {number}/{len(pending)} {scene.scene_id} {row['status']}")
    except Exception as exc:
        if entered:
            session["stop_reason"] = f"session_error: {type(exc).__name__}: {exc}"
        raise
    finally:
        if entered:
            session.update(ended_at_utc=utc_now(), wall_seconds=time.perf_counter() - started,
                           cache_reset=dict(cache_state))
            _finish(run_dir, run, scenes)
    return run


def _finish(run_dir: Path, run: dict[str, Any], scenes: list[Scene]) -> dict[str, Any]:
    states = {scene.scene_id: scene_state(run_dir, scene.scene_id) for scene in scenes}
    complete = [key for key, value in states.items() if value == "complete"]
    failed = [key for key, value in states.items() if value == "failed"]
    missing = [key for key, value in states.items() if value in (None, "infra_failed")]
    state = ("complete" if len(complete) == len(scenes) else "finished_with_failures" if not missing
             else "partial")
    run["completion"] = {"state": state, "scenes_total": len(scenes), "scenes_complete": len(complete),
                         "failed_scene_ids": failed, "missing_scene_ids": missing}
    run["wall_clock_seconds"] = sum(s.get("wall_seconds") or 0 for s in run["sessions"])
    working = [s for s in run["sessions"] if s.get("scenes_written") or s.get("infra_failure")]
    run["resumed"] = len(working) > 1
    run["performance_comparable"] = not run["resumed"]
    if not missing:
        run["ended_at_utc"] = run.get("ended_at_utc") or utc_now()
    atomic_write_json(run_dir / "run.json", run)
    return run


def load_run_translations(run_dir: Path) -> tuple[dict[str, str], set[str]]:
    """Translations of complete scenes only, and the set of cue IDs from failed scenes."""
    translations: dict[str, str] = {}
    failed: set[str] = set()
    for path in sorted((run_dir / "scenes").glob("*.json")):
        row = read_json(path)
        if row.get("status") == "complete":
            translations.update(row["translations"])
        else:
            failed.update(row.get("cue_ids", []))
    return translations, failed
