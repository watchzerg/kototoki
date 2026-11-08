"""v12: the Q1 translation step on Strata + Qwen3.8-Flash-Next IQ3_S (docs/research/2026-11-08-strata-flash-next-v12.md).

Same packs, neighbours, messages (``qwen.messages``), name-table injection and sampling as the Qwen3.8-27B path;
only the model and the inference engine change, plus the changes Strata forces (usage doc §5):

* no GBNF: the body carries no ``grammar`` (and no ``cache_prompt``, Strata has its own prefix cache); the reply is
  validated afterwards with ``qwen.parse`` and a failure gets the usual single retry with seed + 1;
* no ``/apply-template`` / ``/tokenize``: the input length is ``usage.prompt_tokens`` of the reply; a pack above the
  Q1 input budget is flagged (``over_q1_budget``), not failed (the server context is 32k);
* the first-request ``cache_n == 0`` check is recorded only (the service is attached, it may hold an older prefix);
* every request states ``chat_template_kwargs.enable_thinking`` (Strata has no server-wide reasoning switch); with
  ``qwen_options.thinking`` (F2) the thinking packs also send ``thinking_budget_tokens`` and get the budget as extra
  ``max_tokens``; there is no thought-prefix grammar.

The service is not started here (``kototoki.llama_server.ManagedServer`` cannot run Strata's engine): the executor
starts the ``kototoki-translate`` launch (usage doc §3) and ``session_factory`` attaches to it, holds the v3 GPU lock,
checks ``strata --version``, ``strata launch --status --output json`` (+ its run config), ``/v1/models`` and
``/v1/status`` against the fixed identity below, records the observed values, and samples ``/v1/status`` machine
memory while the session runs (``runtime/session-NN/resources.json``).
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from . import qwen
from . import recipes as R
from .common import atomic_write_json, object_hash, sha256_bytes, utc_now

MODEL = R.STRATA_MODEL
STRATA_VERSION = "0.2.12"
ENGINE_BUILD = "0.1.58"
PRESET = "kototoki-translate"
# usage doc §3; fixed for the whole round (v12 §4.0), part of the recipe identity.
LAUNCH_FLAGS = ("--family", "qwen", "--model", "iq3_s", "--context", "32k", "--parallel", "1", "--vision", "off",
                "--drafting", "mtp", "--access", "local", "--no-api-key", "--tune", "skip")
CONTEXT = 32768
REQUEST_SHAPE = "chat-completions+no-grammar+usage-prompt-tokens"
THINKING_REQUEST = "enable_thinking+thinking_budget_tokens"
SAMPLE_SECONDS = 5.0
# Server log lines counted per session (counts only; the log is not copied): the reasoning-loop recovery that raises
# temperature / presence penalty, and the non-finite-logits stop that ends a reply as "length".
LOG_EVENTS = {"reasoning_recoveries": "repeated reasoning detected", "nonfinite_logits": "logits became non-finite"}


def server_log(preset: str = PRESET) -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Strata" / "runtime" / f"launch-{preset}.server.log"


def log_offset(path: Path) -> int:
    return path.stat().st_size if path.is_file() else 0


def log_events(path: Path, offset: int) -> dict[str, int] | None:
    """Pattern counts in the part of the server log written after ``offset`` (None when there is no log)."""
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(offset)
        text = handle.read().decode("utf-8", errors="replace")
    return {key: text.count(pattern) for key, pattern in LOG_EVENTS.items()}


def versions(recipe: R.Recipe) -> dict[str, Any]:
    out = {"model": MODEL, "runtime": {"strata": STRATA_VERSION, "engine_build": ENGINE_BUILD, "preset": PRESET,
                                       "launch": list(LAUNCH_FLAGS), "context": CONTEXT},
           "prompt": [qwen.PROMPT_VERSION, sha256_bytes(qwen.system_template().encode())],
           "request": REQUEST_SHAPE, "seed_step": qwen.SEED_STEP}
    extra = qwen.option_versions(recipe, thinking_extra={"request": THINKING_REQUEST})
    if extra:
        out["options"] = extra
    return out


def fixed(recipe: R.Recipe) -> dict[str, Any]:
    options = recipe.qwen_options or {}
    return {"sampling": qwen.SAMPLING | {"seed": "<run seed>"}, "n_predict": R.N_PREDICT,
            "q1_input_budget": qwen.max_input_tokens(recipe), "server_context": CONTEXT,
            "max_attempts": R.MAX_ATTEMPTS, "chat_template_kwargs": {"enable_thinking": False},
            **({"thinking": dict(options["thinking"], packs="target cues >= min_visible",
                                 max_tokens="n_predict + budget", request=THINKING_REQUEST)}
               if "thinking" in options else {}),
            "grammar": None, "first_cache_check": "recorded-only",
            "overflow": "over-q1-budget-recorded-not-failed"}


def request_body(messages_: list[dict[str, str]], seed: int, *, think: bool = False, budget: int | None = None,
                 max_tokens_: int = R.N_PREDICT) -> dict[str, Any]:
    if type(seed) is not int or seed <= 0:
        raise ValueError("Strata takes only a positive integer seed")
    body = {"model": MODEL, "messages": messages_, **qwen.SAMPLING, "seed": seed, "max_tokens": max_tokens_,
            "chat_template_kwargs": {"enable_thinking": think}, "stream": False}
    if think:
        body["thinking_budget_tokens"] = budget
    return body


def run_step(client: Any, messages_: list[dict[str, str]], seed: int, ids: list[str], cache_state: dict[str, Any],
             record: dict[str, Any], recipe: R.Recipe) -> dict[str, str]:
    """``qwen.run_step`` without grammar and token-budget endpoints; at most two attempts (seed, seed + 1)."""
    from experiments.translation_demo.run import explicit_oom
    from .generate import CONTEXT_ERROR, FATAL_KINDS, StepFailed, _http_body, whitespace_ratio
    attempts: list[dict[str, Any]] = record.setdefault("attempts", [])
    last: StepFailed | None = None
    think = qwen.thinks(recipe, ids)
    budget = recipe.qwen_options["thinking"]["budget"] if think else None
    limit = qwen.max_tokens(recipe, ids)
    q1_budget = qwen.max_input_tokens(recipe, ids)
    for number in range(1, R.MAX_ATTEMPTS + 1):
        started = time.perf_counter()
        used_seed = seed + (number - 1) * qwen.SEED_STEP
        body = request_body(messages_, used_seed, think=think, budget=budget, max_tokens_=limit)
        attempt: dict[str, Any] = {"attempt": number, "seed": used_seed, "thinking": think,
                                   "prompt_sha256": sha256_bytes(json.dumps(messages_, ensure_ascii=False).encode()),
                                   "request_sha256": object_hash(body), "dispatched": True}
        attempts.append(attempt)
        try:
            completion_start = time.perf_counter()
            try:
                response = client.chat_completion(body)
            except HTTPError as exc:
                text = _http_body(client) + str(exc)
                kind = "oom" if explicit_oom(text) else "context" if CONTEXT_ERROR.search(text) else "server_error"
                raise StepFailed(f"HTTP {exc.code}: {text[:500]}", kind) from exc
            except (URLError, ConnectionError, TimeoutError) as exc:
                raise StepFailed(f"completion transport: {exc}", "server") from exc
            finally:
                attempt.update(completion_seconds=time.perf_counter() - completion_start,
                               exchange=getattr(client, "last_exchange", None))
            timings = response.get("timings") if isinstance(response.get("timings"), dict) else {}
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content")
            reasoning = message.get("reasoning_content")
            prompt_tokens = usage.get("prompt_tokens")
            attempt.update(input_tokens=prompt_tokens, output_tokens=usage.get("completion_tokens"),
                           tokens_evaluated=prompt_tokens, timings=timings, stop_type=choice.get("finish_reason"),
                           stopped_limit=choice.get("finish_reason") == "length", truncated=False,
                           content_chars=len(content) if isinstance(content, str) else None,
                           reasoning_chars=len(reasoning) if isinstance(reasoning, str) else 0,
                           over_q1_budget=type(prompt_tokens) is int and prompt_tokens > q1_budget)
            if not cache_state.get("checked"):
                reuse = timings.get("cache_n", (usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
                cache_state.update(checked=True, first_cache_n=reuse, verified=type(reuse) is int and reuse == 0,
                                   recorded_only=True, exchange=attempt.get("exchange"))
                attempt["cache_reset_check"] = dict(cache_state)
            if response.get("error") is not None:
                text = json.dumps(response["error"], ensure_ascii=False)
                raise StepFailed("server error: " + text, "oom" if explicit_oom(text) else "server_error")
            if attempt["stopped_limit"]:
                attempt["whitespace_ratio"] = whitespace_ratio(content)
                raise StepFailed("generation reached the output/context limit (or non-finite logits)", "limit")
            if not isinstance(content, str) or not content.strip():
                raise StepFailed("empty generated text", "parse")
            try:
                result = qwen.parse(content, ids)
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


# --- attaching to the running service ------------------------------------------------------------

def strata_cmd() -> str:
    """The Strata launcher (``strata`` is a PowerShell script on PATH; Python and Git Bash need the .cmd)."""
    path = Path(os.environ.get("LOCALAPPDATA", "")) / "Strata" / "terminal" / "current" / "bin" / "strata.cmd"
    return str(path) if path.is_file() else "strata"


def _cli(*args: str) -> str:
    return subprocess.run([strata_cmd(), *args], capture_output=True, text=True, encoding="utf-8", check=True,
                          timeout=120).stdout


def _get(url: str, timeout: float = 30.0) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _arg(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


def probe(port: int = 8080, *, cli: Callable[..., str] = _cli, get: Callable[[str], dict] = _get) -> dict[str, Any]:
    """Check the attached service against the fixed identity; return the observed values (no API key)."""
    version = cli("--version").strip()
    if f"strata {STRATA_VERSION} " not in version + " " or f"build {ENGINE_BUILD}" not in version:
        raise RuntimeError(f"Strata version differs from {STRATA_VERSION} / build {ENGINE_BUILD}: {version!r}")
    status = json.loads(cli("launch", "--status", "--output", "json"))
    running = [r for r in status.get("running", []) if r.get("state") == "ready"]
    if len(running) != 1 or running[0].get("port") != port:
        raise RuntimeError(f"Expected exactly one ready Strata launch on port {port}, got {status.get('running')!r}")
    launch = running[0]
    if launch.get("host") != "127.0.0.1" or launch.get("name") != PRESET:
        raise RuntimeError(f"Strata launch must be the local '{PRESET}' preset, got {launch.get('name')!r} "
                           f"on {launch.get('host')!r}")
    config = json.loads(Path(launch["config"]).read_text(encoding="utf-8-sig")) if launch.get("config") else {}
    args = [str(a) for a in config.get("args") or []]
    if config.get("model_name") != MODEL or _arg(args, "--max-context") != str(CONTEXT) or "--vision" in args:
        raise RuntimeError(f"Strata run config differs: model {config.get('model_name')!r}, "
                           f"--max-context {_arg(args, '--max-context')!r}, vision {'--vision' in args}")
    base = f"http://127.0.0.1:{port}"
    models = [m.get("id") for m in get(base + "/v1/models").get("data", [])]
    if MODEL not in models:
        raise RuntimeError(f"/v1/models does not serve {MODEL}: {models!r}")
    v1 = get(base + "/v1/status")
    serving = (v1.get("concurrency") or {}).get("serving")
    if (v1.get("context") or {}).get("native") != CONTEXT or serving != 1:
        raise RuntimeError(f"/v1/status differs: context {v1.get('context')!r}, concurrency {v1.get('concurrency')!r}")
    return {"version": version, "launch": {k: launch.get(k) for k in ("name", "profile", "state", "port", "host")},
            "config": {"model_name": config.get("model_name"), "exe": config.get("exe"), "args": args,
                       "host": config.get("host"), "log": config.get("log")},
            "kv": _arg(args, "--kv"), "kv_resident": _arg(args, "--kv-resident"), "spec": _arg(args, "--spec"),
            "drafting": "mtp" if "--mtp" in args else "dflash" if any("dflash" in a.lower() for a in args) else None,
            "models": models, "status": {k: v1.get(k) for k in ("model", "engine", "context", "concurrency",
                                                                 "structured_output", "vram", "machine")}}


class ResourceSampler:
    """Peak machine GPU / RAM use from ``/v1/status`` every few seconds (system totals, not the process)."""

    def __init__(self, url: str, get: Callable[[str], dict] = _get, every: float = SAMPLE_SECONDS):
        self.url, self.get, self.every = url, get, every
        self.peak: dict[str, Any] = {"gpu_used_mib": None, "ram_used_gib": None, "samples": 0, "errors": 0}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def sample(self) -> None:
        try:
            machine = (self.get(self.url + "/v1/status").get("machine") or {})
        except (URLError, ConnectionError, TimeoutError, ValueError, OSError):
            self.peak["errors"] += 1
            return
        self.peak["samples"] += 1
        for key, value in (("gpu_used_mib", (machine.get("gpu") or {}).get("used_mib")),
                           ("ram_used_gib", (machine.get("ram") or {}).get("used_gib"))):
            if isinstance(value, (int, float)) and (self.peak[key] is None or value > self.peak[key]):
                self.peak[key] = value

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            self.sample()

    def __enter__(self) -> "ResourceSampler":
        self.sample()
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=self.every + 35)
        self.sample()


def session_factory(root: Path, run_id: str, recipe: R.Recipe, *, port: int = 8080, break_stale_lock: bool = False,
                    timeout: float = 600.0, probe_fn: Callable[[int], dict] = probe,
                    get: Callable[[str], dict] = _get, client_factory: Callable[..., Any] | None = None,
                    log_path: Path | None = None):
    """Attach to the running Strata service: v3 gpu.lock + identity checks + loopback client with raw traces."""
    del root, recipe  # same signature as qwen.session_factory; nothing is started or verified on disk here

    @contextmanager
    def factory(run_dir: Path, index: int) -> Iterator[Any]:
        from kototoki.llama_server import LlamaClient
        from .generate import SessionHandle
        from .server import GpuLock
        lock = GpuLock(run_id)
        lock.acquire(break_stale=break_stale_lock)
        session_dir = run_dir / "runtime" / f"session-{index:02d}"
        try:
            started = time.perf_counter()
            log = log_path or server_log()
            offset = log_offset(log)
            observed = probe_fn(port)
            atomic_write_json(session_dir / "strata.json", dict(observed, attached_at_utc=utc_now()))
            url = f"http://127.0.0.1:{port}"
            make = client_factory or LlamaClient
            client = make(url, timeout=timeout, trace_dir=run_dir / "transport" / f"session-{index:02d}")
            sampler = ResourceSampler(url, get).__enter__()
            try:
                yield SessionHandle(client, {"candidate": MODEL, "strata": observed,
                                             "cold_load_seconds": time.perf_counter() - started,
                                             "gpu_lock_replaced_stale": lock.stale, "owner_pid": lock.pid,
                                             "owner_created": lock.created})
            finally:
                sampler.__exit__()
                atomic_write_json(session_dir / "resources.json", dict(sampler.peak, log_events=log_events(log, offset),
                                                                       server_log=str(log), finished_at_utc=utc_now()))
        finally:
            lock.release()
    return factory
