"""Additive singleton-aware version of the frozen F5 whole-trial admission.

The original v2_unit_main_proof.py remains immutable for historical C0 proofs.
This version omits the model planning specification only when the frozen source
window requires deterministic singleton planning. It retains the closed parser
closure, exact20 proof ABI, retry/failure guards and original once-only costs.
Its own code identity requires new root-approved candidate authorities/seals;
it cannot stand in for the original helper or authorize historical relabeling.

This module never dispatches inference or judges. Authentication interprets
original source/native bytes; the subsequently exported validator only hashes
them. Historical executed snapshots and approved diagnostic parsers are two
different authorities. No artifact supplies executable Python.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Callable

from experiments.translation_demo import adapters
from . import v2_unit_custody as custody
from . import v2_unit_diagnostics as diagnostics
from . import v2_delivery as delivery
from . import v2_recipes as recipes
from . import v2_semantic_partition_grammar as partition
from .worker import effective_settings
from .recipes import sampling_settings

AUTHORITY_SCHEMA = "hy30-F5-original-main-admission-authority-v1"
ADMISSION_SCHEMA = "hy30-F5-original-whole-trial-admission-v1"
REPLAY_SCHEMA = "hy30-F5-approved-main-diagnostic-replay-v1"
SEAL_SCHEMA = "hy30-F5-main-proof-external-seal-v1"
AUTHORITY_FIELDS = {"schema", "state", "registration", "external_registration", "verifier",
                    "diagnostic_replay", "entries"}
ENTRY_FIELDS = {"seed", "role", "card", "trial_root", "trial_completion", "runtime",
                "declared_snapshot_count", "historical_authorities", "scoring_derivation"}
HISTORICAL_FIELDS = {"release", "lineage", "workload_archive", "behavior", "behavior_helper", "archive_resolver"}


def identity(path: Path) -> dict[str, str]:
    return custody.identity(path)


def _bytes(pointer: dict[str, str]) -> bytes:
    return custody._read_bytes(pointer)


def _read(pointer: dict[str, str], *, lines: bool = False) -> Any:
    return diagnostics._artifact({"identity": pointer, "content": _bytes(pointer)}, lines=lines)[0]


def _write(path: Path, value: Any) -> dict[str, str]:
    return custody._write(path, value)


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Original timestamps must have an explicit timezone")
    return result


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _inside(root: Path, value: str | Path) -> Path:
    return custody._inside(root, str(value))


def _raw_object(exchange: Path) -> dict | None:
    """Transport exceptions may preserve empty/nonJSON bytes, not a response."""
    try:
        value = json.loads((exchange / "response.raw").read_bytes())
    except (ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _authority(pointer: dict[str, str], expected_sha256: str, *, validate_frame: bool = True) -> tuple[dict, dict]:
    if pointer.get("sha256") != expected_sha256:
        raise ValueError("Original admission authority lacks independent root pins")
    value = _read(pointer)
    if (set(value) != AUTHORITY_FIELDS or value["schema"] != AUTHORITY_SCHEMA
            or value["state"] != "root_approved_offline_original_authentication"
            or value["verifier"] != identity(Path(__file__))):
        raise ValueError("Original admission authority/code is not approved")
    replay = _read(value["diagnostic_replay"])
    if (set(replay) != {"schema", "state", "verifier", "parsers", "historical_behavior"}
            or replay["schema"] != REPLAY_SCHEMA or replay["state"] != "root_approved_closed_parser_replay"
            or replay["verifier"] != value["verifier"] or replay["parsers"] != custody._dependencies()):
        raise ValueError("Diagnostic replay must pin the exact closed nine-parser closure")
    for parser in replay["parsers"]:
        _bytes(parser)
    if validate_frame:
        registered = custody.validate_registered_frame(value["registration"], value["external_registration"],
            expected_registration_sha256=value["registration"]["sha256"],
            expected_external_sha256=value["external_registration"]["sha256"])
    else:
        # The externally sealed callback must not decode frame/source/native
        # material. Its authentication was completed before root sealed it.
        record = _read(value["registration"])
        _bytes(value["external_registration"])
        for ptr in [record["frame"], *record["packed"], *record["cards"], *record["source_authority"].values()]:
            _bytes(ptr)
        registered = {"registration": record}
    slots = set()
    for entry in value["entries"]:
        if (set(entry) != ENTRY_FIELDS or entry["seed"] not in diagnostics.SEEDS
                or entry["role"] not in {"candidate", "control"}
                or (entry["seed"], entry["role"]) in slots):
            raise ValueError("Original authority entries must have unique frozen seed/role slots")
        slots.add((entry["seed"], entry["role"]))
        if entry["role"] == "control":
            historical = entry["historical_authorities"]
            if (not isinstance(historical, dict) or set(historical) != HISTORICAL_FIELDS
                    or historical["behavior"] != replay["historical_behavior"]):
                raise ValueError("Historical C0 requires separately approved matched29 lineage/behavior")
            for p in historical.values():
                _bytes(p)
        elif entry["historical_authorities"] is not None or entry["scoring_derivation"] is not None:
            raise ValueError("Prospective F5 cannot claim historical control derivation")
    return value, registered


def _settings(card: dict, item: dict) -> None:
    p = card["prepare"]
    if (p["recipe"] not in {"c0", "semantic-partition"} or item.get("recipe") != p["recipe"]
            or item.get("label") != p["recipe_id"] or item.get("seed") != p["seed"]
            or item.get("n_predict") != p.get("n_predict", 4096)
            or item.get("sampling") != "official" or item.get("cache_prompt") is not True
            or item.get("max_attempts") != 2 or card.get("source_preparation") is not None
            or any(item.get(key, default) != p.get("options", {}).get(key, default) for key, default in (
                ("terms", []), ("background", []), ("style", "neutral"), ("review", False)))
            or item.get("partition_grammar_limits") != p.get("options", {}).get("partition_grammar_limits")):
        raise ValueError("Original workload differs from the locked native card")
    allowed = {"label", "inputs", "input_sha256", "recipe", "sampling", "cache_prompt", "n_predict",
               "seed", "max_attempts", "packed_mapping_sha256", "source_manifest_sha256",
               "terms", "background", "style", "review", "partition_grammar_limits"}
    if set(item) - allowed or item.get("review") or item.get("terms") or item.get("background"):
        raise ValueError("This whole-main adapter has no auxiliary/review protocol")


def _source(card: dict, packed: dict, inputs: list[dict], registered: dict, role: str) -> dict:
    authority = {"manifest": {"path": card["source"]["manifest"], "sha256": card["source"]["manifest_sha256"]},
                 "scenes": {"path": card["source"]["scenes"], "sha256": card["source"]["scenes_sha256"]},
                 "freeze": card["source_freeze"]}
    manifest, scenes = _read(authority["manifest"]), _read(authority["scenes"], lines=True)
    _bytes(authority["freeze"])
    source = diagnostics._source(packed)
    originals = {s["id"]: s for s in scenes}
    if (packed["source_manifest"] != authority["manifest"] or packed["source_scenes"] != authority["scenes"]
            or packed["seed"] != card["prepare"]["seed"] or packed["recipe_id"] != card["prepare"]["recipe_id"]
            or packed["split"] != card["prepare"]["split"]
            or any(originals.get(s["id"]) != s for s in packed["scenes"])
            or inputs != [b["producer_input"] for b in source["batches"]]
            or any(w not in manifest["windows"] for w in packed["windows"])):
        raise ValueError("Original packed/source/request sequence is not artifact-bound")
    p = card["prepare"]
    expected_geometry = {k: p.get(k, default) for k, default in (("target_size", 5), ("context_before", 1),
        ("context_after", 1), ("token_target", None), ("common_context", False), ("offset", 0))}
    if packed["packing"] != expected_geometry or expected_geometry["token_target"] is not None:
        raise ValueError("Original source geometry changed or needs a different approved replay")
    if p.get("selected_scene_ids") is not None and p["selected_scene_ids"] != packed["scene_ids"]:
        raise ValueError("Original card scene enumeration differs from native complete order")
    record = registered["registration"]
    expected = _read(record["packed"][diagnostics.SEEDS.index(p["seed"])])
    # Original and scoring authorities are deliberately separate. C0 may have a
    # registered scoring derivation; the actual source cue sequence stays exact.
    expected_source = diagnostics._source(expected)
    if (packed["scenes"] != expected["scenes"] or packed["scene_ids"] != expected["scene_ids"]
            or source["batches"] != expected_source["batches"]):
        raise ValueError("Whole native source differs from the prospective fixed scene frame")
    scope = {"split": packed["split"], "scene_ids": packed["scene_ids"],
             "source_cues": sum(len(s["translate_ids"]) for s in packed["scenes"]),
             "scored_windows": len(packed["windows"])}
    if (scope != {k: record["scope"][k] for k in scope}
            or len(packed["batches"]) != record["scope"]["scheduled_batches_per_seed"]):
        raise ValueError("Selected auxiliary batches cannot stand in for full main scope")
    if role == "candidate" and authority != record["source_authority"]:
        raise ValueError("Candidate source differs from its prospective registered authority")
    return authority


def _snapshots(root: Path, card: dict, run: dict, count: int) -> list[dict]:
    code = run.get("code_sha256")
    declared = card.get("implementation_identity")
    if (not isinstance(code, dict) or not code or not isinstance(declared, list)
            or len(declared) != count or len({p["path"] for p in declared}) != count):
        raise ValueError("Original executed/declaration snapshot closure is missing")
    workspace = Path(__file__).resolve().parents[2]
    captured = []
    for relative, digest in code.items():
        file = _inside(root / "source", root / "source" / relative)
        ptr = identity(file)
        if ptr["sha256"] != digest:
            raise ValueError("Original captured native implementation bytes changed")
        captured.append({"relative_path": relative, **ptr})
    for ptr in declared:
        file = Path(ptr["path"]).resolve()
        if not file.is_relative_to(workspace) or code.get(file.relative_to(workspace).as_posix()) != ptr["sha256"]:
            raise ValueError("Original declared execution closure differs from captured snapshots")
    return captured


def _runtime(session: dict, worker: dict, expected: dict, attempts: list[dict], *, complete: bool) -> None:
    value = session["identity"]
    if (set(expected) != {"asset_sha256", "template_sha256", "engine"}
            or value.get("asset", {}).get("sha256") != expected["asset_sha256"]
            or value.get("engine", {}).get("model_sha256") != expected["asset_sha256"]
            or value.get("template_sha256") != expected["template_sha256"]
            or any(value.get("engine", {}).get(k) != v for k, v in expected["engine"].items())):
        raise ValueError("Original model/template/engine/residency differ from root runtime authority")
    engine = value["engine"]
    command = engine.get("command", [])
    fixed = {"engine", "release", "build", "commit", "cuda", "context_size", "gpu_layers_requested",
             "cpu_offload_allowed", "threads", "threads_batch", "kv_type_k", "kv_type_v", "prompt_cache_ram_mib"}
    residency = engine.get("residency", {})
    if (engine.get("context_size") != 8192 or engine.get("cpu_offload_allowed") is not False
            or not fixed <= set(expected["engine"]) or residency.get("layers_not_offloaded") != 0
            or residency.get("partial_layer_offload") is not False
            or type(residency.get("model_layers_total")) is not int or residency["model_layers_total"] <= 0
            or residency.get("gpu_layers_offloaded") != residency["model_layers_total"]
            or type(engine.get("server_pid")) is not int or engine["server_pid"] <= 0
            or "-np" not in command or command[command.index("-np") + 1] != "1"
            or session.get("resume") is not None or session.get("performance_valid_for_fresh_flow") is not True
            or worker.get("reused_windows") != 0 or worker.get("inherited_budget") is not None
            or worker.get("unresolved_prior_dispatch") is not None
            or worker.get("source_token_count_cost") is not None
            or worker.get("performance_valid_for_fresh_flow") is not True):
        raise ValueError("Original admission cannot relabel replay/resume as fresh generation")
    first = next((a for a in attempts if a.get("completion_dispatched")), None)
    cache = worker.get("cache_reset", {})
    if first is not None:
        actual = first.get("response", {}).get("timings", {}).get("cache_n")
        # A transport exception does not reach worker cache validation; the
        # first *received JSON response* is its measured cache boundary.
        measured = next((a for a in attempts if a.get("completion_dispatched") and "response" in a
                         and a["response"].get("error") is None), None)
        actual = measured.get("response", {}).get("timings", {}).get("cache_n") if measured else None
        verified = type(actual) is int and actual == 0
        if (cache.get("method") != "fresh-managed-server" or cache.get("server_pid") != engine["server_pid"]
                or measured is not None and (cache.get("verified") is not verified
                    or cache.get("first_response_cache_n") != actual or cache.get("exchange") != measured.get("original_response"))
                or measured is None and cache.get("verified") is True
                or complete and not verified
                or measured is not None and not verified and measured.get("error_kind") != "cache"):
            raise ValueError("Original first dispatched completion lacks measured empty-cache proof")
    elif cache.get("verified") is True:
        raise ValueError("No-dispatch trial cannot invent measured cache verification")


def _stage_specs(row: dict, window: dict, item: dict) -> dict[str, tuple]:
    if item["recipe"] == "c0":
        return {"translation": (recipes.render_window("c0", window, item), window["translate_ids"], None,
                                lambda text: adapters.translations(text, window["translate_ids"]))}
    specs = {}
    if partition.planning_required(window):
        specs["source-planning"] = (partition.planning_prompt(window), None, partition.planning_grammar(window),
                                    lambda text: partition.parse_planning(text, window))
    plan = row.get("semantic_plan")
    if plan is not None:
        specs["joint-unit-translation"] = (partition.native_prompt(window, plan), [u["id"] for u in plan["units"]], None,
                                           lambda text: adapters.translations(text, [u["id"] for u in plan["units"]]))
        native = row.get("native_unit_translations")
        if native is not None and partition.mapping_required(window, plan):
            limits = item.get("partition_grammar_limits", {"max_states": partition.DEFAULT_MAX_STATES,
                "max_grammar_bytes": partition.DEFAULT_MAX_GRAMMAR_BYTES})
            try:
                built = partition.build_mapping_grammar(window, plan, native, **limits)
            except partition.GrammarComplexityError:
                return specs
            specs["semantic-remapping"] = (partition.mapping_prompt(window, plan, native), None, built["grammar"],
                lambda text: partition.parse_mapping(text, window, plan, native))
    return specs


def _all_attempts(row: dict, window: dict, item: dict, root: Path) -> list[dict]:
    specs = _stage_specs(row, window, item)
    attempts = row.get("attempts", [])
    stages = ["translation"] if item["recipe"] == "c0" else list(custody.STAGES)
    order = [stages.index(a["stage"]) if a.get("stage") in stages else -1 for a in attempts]
    if -1 in order or order != sorted(order):
        raise ValueError("Original main stage order is inconsistent")
    for stage in stages:
        selected = [a for a in attempts if a["stage"] == stage]
        if (len(selected) > item["max_attempts"] or [a.get("attempt") for a in selected] != list(range(1, len(selected) + 1))
                or any(a.get("status") not in {"accepted", "failed"} for a in selected)
                or any(a["status"] == "accepted" for a in selected[:-1])):
            raise ValueError("Original retry ordinals/terminal acceptance changed")
    for attempt in attempts:
        if attempt["stage"] not in specs:
            raise ValueError("Original stage was dispatched without its accepted upstream material")
        prompt, ids, grammar, parse = specs[attempt["stage"]]
        if attempt.get("prompt_sha256") != diagnostics.canonical_sha256(prompt):
            raise ValueError("Original retry prompt differs from the approved closed renderer")
        tokens = None
        if attempt.get("tokenize_exchange") is not None:
            token = _inside(root / "transport", attempt["tokenize_exchange"])
            delivery._trace_artifacts(token, "tokenize_exchange", attempt)
            request = _read(identity(token / "request.json"))
            raw = _raw_object(token)
            if request.get("body") != {"content": prompt, "add_special": False, "parse_special": True}:
                raise ValueError("Original tokenizer retry changed source/prompt flags")
            transport = _read(identity(token / "transport.json"))
            tokens = raw.get("tokens") if raw and transport.get("status") == 200 and not transport.get("error") else None
            valid_tokens = isinstance(tokens, list) and bool(tokens) and all(type(n) is int and n >= 0 for n in tokens)
            if not valid_tokens:
                tokens = None
            if tokens is not None and (attempt.get("input_tokens") != len(tokens)
                    or attempt.get("input_token_ids_sha256") != diagnostics.canonical_sha256(tokens)):
                raise ValueError("Original tokenizer retry IDs/count differ")
            if tokens is None and attempt.get("failure_stage") != "tokenize":
                raise ValueError("Original tokenization exception cannot authorize generation")
        if attempt.get("completion_dispatched") is not True:
            if attempt.get("status") != "failed" or attempt.get("original_response") is not None:
                raise ValueError("Nondispatch attempt cannot contain accepted generation")
            if not attempt.get("error") or attempt.get("failure_stage") not in {"tokenize", "completion"}:
                raise ValueError("Failed nondispatch requires original failure evidence")
            continue
        if tokens is None or len(tokens) + item["n_predict"] + 64 > 8192:
            raise ValueError("Actual completion lacks bounded original tokenization")
        exchange = _inside(root / "transport", attempt["original_response"])
        delivery._trace_artifacts(exchange, "original_response", attempt)
        expected = recipes.completion_request(item, tokens, ids, grammar=grammar)
        response = _raw_object(exchange)
        request = _read(identity(exchange / "request.json"))
        if request.get("body") != expected or attempt.get("request_sha256") != diagnostics.canonical_sha256(expected):
            raise ValueError("Original dispatched retry settings/grammar differ from approved construction")
        if response is None:
            transport = _read(identity(exchange / "transport.json"))
            if (attempt["status"] != "failed" or attempt.get("failure_stage") != "completion"
                    or not attempt.get("error") or "response" in attempt
                    or transport.get("error") is not None and transport["error"] != attempt["error"]):
                raise ValueError("Original nonJSON transport exception lacks faithful failure evidence")
            continue
        effective = effective_settings(response, expected)
        if (attempt.get("effective_settings") is not None and attempt["effective_settings"] != effective
                or attempt["status"] == "accepted" and (effective.get("verified") is not True
                                                         or attempt.get("effective_settings") != effective)):
            raise ValueError("Original effective parameter evidence changed")
        successful_transport = _read(identity(exchange / "transport.json")).get("status") == 200
        usable = (successful_transport and response.get("error") is None
                  and not response.get("truncated") and not response.get("stopped_limit")
                  and response.get("stop_type") != "limit"
                  and (response.get("prompt") is None or response["prompt"] == prompt)
                  and (response.get("tokens_evaluated") is None or response["tokens_evaluated"] == len(tokens))
                  and isinstance(response.get("content"), str) and bool(response["content"].strip()))
        parsed = None
        if usable:
            try:
                parsed = parse(response["content"])
            except (ValueError, KeyError, TypeError):
                usable = False
        if attempt["status"] == "accepted":
            if not usable:
                raise ValueError("Original accepted response is not mechanically accepted by approved parser")
            if item["recipe"] == "c0" and parsed != row.get("translations"):
                raise ValueError("Original C0 accepted response differs from retained cue translations")
        elif (not attempt.get("error") or attempt.get("failure_stage") not in {"tokenize", "completion", "validation"}
              or usable and attempt.get("error_kind") != "cache"):
            raise ValueError("Failed raw completion cannot be silently reclassified as a valid acceptance")
        cache_n = response.get("timings", {}).get("cache_n")
        if attempt.get("error_kind") == "cache" and type(cache_n) is int and cache_n == 0:
            raise ValueError("Original cache failure cannot contradict measured zero reuse")
    if item["recipe"] == "semantic-partition":
        custody._stage_material(row, window, item, root)
    elif ((row["status"] == "delivered") != bool(attempts and attempts[-1]["status"] == "accepted")):
        raise ValueError("C0 terminal state disagrees with its original accepted completion")
    return attempts


def _transport_inventory(root: Path, attempts: list[dict]) -> None:
    lists = {key: [str(Path(a[key]).resolve()) for a in attempts if a.get(key) is not None]
             for key in ("tokenize_exchange", "original_response")}
    if (any(len(rows) != len(set(rows)) for rows in lists.values())
            or set(lists["tokenize_exchange"]) & set(lists["original_response"])):
        raise ValueError("Original retry transport exchanges cannot be counted more than once")
    used = {key: set(rows) for key, rows in lists.items()}
    actual = {"/tokenize": set(), "/completion": set()}
    props = 0
    for exchange in (root / "transport").iterdir():
        if not exchange.is_dir():
            raise ValueError("Original transport inventory contains an unsupported loose artifact")
        request = _read(identity(exchange / "request.json"))
        endpoint = request.get("endpoint")
        if endpoint in actual:
            actual[endpoint].add(str(exchange.resolve()))
        elif endpoint == "/props":
            props += 1
            session = _read(identity(root / "session.json"))
            native_props = _read(identity(root.parent / "runtime/props.json"))
            response = _raw_object(exchange)
            if (response != session.get("server_props") or native_props != response
                    or _read(identity(exchange / "transport.json")).get("status") != 200
                    or response.get("total_slots") != 1
                    or response.get("model_path") != session["identity"]["engine"].get("model_path")
                    or response.get("default_generation_settings", {}).get("n_ctx") != 8192):
                raise ValueError("Original props transport differs from actual native slot/context metadata")
        else:
            raise ValueError("Original transport contains an unaccounted native endpoint")
    if (actual["/tokenize"] != used["tokenize_exchange"]
            or actual["/completion"] != used["original_response"] or props != 1):
        raise ValueError("Full original transport has missing/extra calls outside the main ledger")


def _inventory(root: Path) -> list[dict]:
    if root.is_symlink() or root.is_junction():
        raise ValueError("Original inventory rejects linked trial roots")
    root = root.resolve()
    result = []
    for file in sorted(root.rglob("*")):
        if file.is_symlink() or file.is_junction() or not file.resolve().is_relative_to(root):
            raise ValueError("Original inventory contains an escaped/link artifact")
        if file.is_file():
            result.append(identity(file))
    return result


def _native_runtime(root: Path, session: dict, command: dict) -> list[dict]:
    engine_ptr = identity(root / "execution/runtime-run/runtime/engine.json")
    command_ptr = identity(root / "execution/command.json")
    engine, launched = _read(engine_ptr), _read(command_ptr)
    stable = {key: value for key, value in session["identity"]["engine"].items()
              if key not in {"cold_load_seconds", "peak_device_memory_mib"}}
    if any(engine.get(key) != value for key, value in stable.items()):
        raise ValueError("Actual native final engine metadata differs from original worker identity")
    if (launched.get("schema") != "hy30-flow-command-v2"
            or any(command.get(key) != value for key, value in launched.items())
            or Path(launched.get("prepared", "")).resolve() != root / "prepared"):
        raise ValueError("Actual original launch command differs from terminal managed command")
    args = launched.get("command", [])
    for key, expected in (("--session-worker", "experiments.translation_flow.v2_worker"),
                          ("--session-plan", str(root / "prepared/session-plan.json")),
                          ("--output-dir", str(root / "execution/runtime-run")),
                          ("--context-size", "8192"), ("--layers", "99")):
        if args.count(key) != 1 or args[args.index(key) + 1] != expected:
            raise ValueError("Actual original runtime launch arguments changed worker/source/GPU scope")
    return [engine_ptr, command_ptr, identity(root / "execution/runtime-run/runtime/props.json")]


def authenticate_original_trial(*, authority: dict[str, str], expected_authority_sha256: str,
                                role: str, seed: int, output: Path) -> dict[str, str]:
    """Authenticate the entire original trial, without changing its artifacts.

    The independently root-pinned authority authorizes original raw inspection.
    A retained partial/failed trial is a terminal partial, never a complete lane.
    Missing seed slots are left to the registered auxiliary frame, not generated.
    """
    if output.exists():
        raise ValueError("Original admission destination must be new")
    auth, registered = _authority(authority, expected_authority_sha256)
    entries = [e for e in auth["entries"] if (e["seed"], e["role"]) == (seed, role)]
    if len(entries) != 1:
        raise ValueError("Original seed/role is absent from root admission authority")
    entry, record = entries[0], registered["registration"]
    original_root = Path(entry["trial_root"])
    initial_inventory = _inventory(original_root)
    root = original_root.resolve()
    if output.resolve().is_relative_to(root):
        raise ValueError("Admission cannot modify the immutable original trial")
    card = _read(entry["card"])
    p = card["prepare"]
    if p["seed"] != seed or p["stage"] not in {"screening", "full-flow"} or p["split"] != record["scope"]["split"]:
        raise ValueError("Original card seed/source stage/split changed")
    if role == "candidate" and entry["card"] != record["cards"][diagnostics.SEEDS.index(seed)]:
        raise ValueError("Candidate original card is not its registered source-frame card")
    if (role == "candidate" and p["recipe"] != "semantic-partition"
            or role == "control" and p["recipe"] != "c0"):
        raise ValueError("Original role/recipe changed")
    start_ptr = identity(root / "trial-start.json")
    terminal_ptr = identity(root / "trial-completion.json")
    if terminal_ptr != entry["trial_completion"]:
        raise ValueError("Root authority does not bind exact original terminal bytes")
    start, terminal = _read(start_ptr), _read(terminal_ptr)
    for value in (start, terminal):
        if (value.get("schema") != "hy30-flow-trial-v2" or value.get("card") != card
                or value.get("card_sha256") != entry["card"]["sha256"]
                or Path(value.get("card_path", "")).resolve() != Path(entry["card"]["path"]).resolve()):
            raise ValueError("Original trial/card bytes differ from accepted authority")
    if (start.get("status") != "started" or terminal.get("status") not in {"complete", "partial", "failed"}
            or start.get("started_at_utc") != terminal.get("started_at_utc")
            or _time(terminal["finished_at_utc"]) <= _time(start["started_at_utc"])
            or not _number(terminal.get("total_flow_seconds"))
            or not terminal.get("phases") or any(not _number(v) for v in terminal["phases"].values())
            or sum(terminal["phases"].values()) > terminal["total_flow_seconds"] + 0.01):
        raise ValueError("Original terminal status/chronology/full-flow cost is incomplete")
    if role == "candidate" and _time(start["started_at_utc"]) <= _time(registered["registered_at_utc"]):
        raise ValueError("F5 original generation predates external prospective frame registration")
    packed_ptr = identity(root / "prepared/packed-mapping.json")
    packed = _read(packed_ptr)
    session_root = root / "execution/runtime-run/translation"
    run_root = session_root / p["recipe_id"]
    retained = {"packed": packed_ptr, **{key: identity(run_root / name) for key, name in (
        ("run", "run.json"), ("inputs", "inputs.jsonl"), ("ledger", "ledger.jsonl"),
        ("results", "results.jsonl"), ("schedule", "schedule.jsonl"))}}
    if role == "control":
        archived = _read(entry["historical_authorities"]["workload_archive"])
        rows = [r for r in archived.get("fresh_output_audits", []) if r.get("seed") == seed]
        if (len(rows) != 1 or rows[0].get("fresh_original_run") != retained["run"]
                or rows[0].get("fresh_ledger") != retained["ledger"]
                or rows[0].get("matched_batches") != record["scope"]["scheduled_batches_per_seed"]):
            raise ValueError("Historical accepted archive does not bind this actual matched control run/ledger")
    run, inputs = _read(retained["run"]), _read(retained["inputs"], lines=True)
    _settings(card, run["settings"])
    fixed = card.get("fixed_runtime_contract", {})
    if (fixed.get("asset_sha256") != entry["runtime"]["asset_sha256"]
            or fixed.get("context_tokens") != 8192 or fixed.get("output_reservation_tokens") != run["settings"]["n_predict"]
            or fixed.get("input_margin_tokens") != 64 or fixed.get("sampling") != "official"
            or fixed.get("cache_prompt") is not True or fixed.get("gpu_required") is not True
            or fixed.get("cpu_fallback") is not False or fixed.get("fresh_server_per_trial") is not True
            or fixed.get("max_attempts_per_step") != 2):
        raise ValueError("Original locked runtime contract differs from native dispatch authority")
    sampling = sampling_settings("official", seed)
    if any(fixed.get(key) != sampling[key] for key in ("temperature", "top_p", "top_k", "repeat_penalty", "samplers")):
        raise ValueError("Original locked sampling contract differs from native official decoding")
    original_source = _source(card, packed, inputs, registered, role)
    if (run.get("packed_mapping_sha256") != packed_ptr["sha256"]
            or run.get("source_manifest_sha256") != original_source["manifest"]["sha256"]
            or run.get("input_sha256") != retained["inputs"]["sha256"]
            or run.get("expected_window_ids") != [b["id"] for b in packed["batches"]]):
        raise ValueError("Original run does not bind whole packed request sequence")
    _, provenance = delivery._session_transport(run_root, run)
    plan_ptr, session_ptr = map(identity, provenance)
    plan, session = _read(plan_ptr), _read(session_ptr)
    if (identity(root / "prepared/session-plan.json") != {"path": str((root / "prepared/session-plan.json").resolve()),
            "sha256": plan_ptr["sha256"]} or plan.get("stage") != p["stage"] or "resume" in plan
            or plan.get("experiment_identity") != {"source_manifest_sha256": original_source["manifest"]["sha256"],
                "split": p["split"], "seed": seed, "recipe_id": p["recipe_id"],
                "source_order_sha256": diagnostics.canonical_sha256([i["id"] for i in inputs])}):
        raise ValueError("Original session plan changes native stage/source/seed/order")
    snapshots = _snapshots(session_root, card, run, entry["declared_snapshot_count"])
    if role == "candidate":
        workspace = Path(__file__).resolve().parents[2]
        if any(run["code_sha256"].get(Path(ptr["path"]).relative_to(workspace).as_posix()) != ptr["sha256"]
               for ptr in _read(auth["diagnostic_replay"])["parsers"]):
            raise ValueError("Prospective F5 executed parser snapshots differ from the approved diagnostic replay")
    declared_by_name = {Path(x["path"]).name: x for x in card["implementation_identity"]}
    if (start.get("code_sha256") != declared_by_name.get("v2_trial.py", {}).get("sha256")
            or terminal.get("code_sha256") != start["code_sha256"]):
        raise ValueError("Original trial launcher snapshot differs from declared execution")
    ledger, results, schedule = (_read(retained[k], lines=True) for k in ("ledger", "results", "schedule"))
    ids = [b["id"] for b in packed["batches"]]
    attempted = [r["window_id"] for r in ledger]
    tail = [r["window_id"] for r in schedule]
    if (attempted + tail != ids or [r["id"] for r in results] != attempted
            or any(r.get("reused_artifact") is not None or r.get("reused_not_new_measurement") for r in ledger)):
        raise ValueError("Full ordered main ledger/results/tail is incomplete or reused")
    for row in ledger:
        if _read(identity(run_root / f"window-{row['window_id']}.json")) != row:
            raise ValueError("Original durable batch artifact differs from ledger")
    aggregated = delivery.aggregate(packed, results, ledger, schedule)
    if any(states[cue]["status"] in {"missing", "invalid"} for states in aggregated["scenes"].values() for cue in states):
        raise ValueError("Whole native delivery contains missing/invalid cue evidence")
    attempts = []
    for row, window in zip(ledger, inputs, strict=False):
        if row.get("recipe") != p["recipe"] or row.get("candidate") != run.get("candidate") or row.get("scored_ids") != window["translate_ids"]:
            raise ValueError("Original batch identity/target coverage differs")
        attempts.extend(_all_attempts(row, window, run["settings"], session_root))
    _transport_inventory(session_root, attempts)
    worker_ptr, batch_ptr = identity(session_root / "worker-completion.json"), identity(run_root / "completion.json")
    worker, batch = _read(worker_ptr), _read(batch_ptr)
    command_ptr = identity(root / "execution/command-completion.json")
    command = _read(command_ptr)
    dispatched = [a for a in attempts if a.get("completion_dispatched")]
    failures = sum(r["status"] != "delivered" for r in ledger)
    stopped_rows = [r for r in ledger if r.get("error_kind") in {"budget", "oom", "cache"}]
    if stopped_rows and (len(stopped_rows) != 1 or stopped_rows[0] != ledger[-1]
                         or worker.get("stopped_reason") != stopped_rows[0].get("stop_reason")):
        raise ValueError("Original hard failure must preserve stopped worker/tail without later dispatch")
    if (command.get("schema") != "hy30-flow-command-v2" or command.get("worker") != "experiments.translation_flow.v2_worker"
            or command.get("plan_sha256") != plan_ptr["sha256"] or type(command.get("returncode")) is not int
            or command["returncode"] != terminal.get("runtime_exit_code") or not _number(command.get("command_seconds"))
            or command.get("code_sha256") != declared_by_name.get("v2_execute.py", {}).get("sha256")
            or batch.get("expected_windows") != len(ids) or batch.get("windows") != len(ledger)
            or batch.get("remaining_window_ids") != tail or batch.get("failures") != worker.get("failures")
            or batch.get("reused_windows") != 0 or type(worker.get("failures")) is not int or worker["failures"] < failures
            or type(worker.get("budget", {}).get("translation_calls")) is not int
            or type(worker.get("budget", {}).get("estimated_tokens")) is not int
            or worker.get("budget", {}).get("translation_calls") != len(dispatched)
            or worker.get("budget", {}).get("estimated_tokens") != sum(a["input_tokens"] + run["settings"]["n_predict"] for a in dispatched)):
        raise ValueError("Original terminal command/worker/retry cost accounting differs")
    complete = not tail and not failures
    _runtime(session, worker, entry["runtime"], attempts, complete=complete)
    native_runtime = _native_runtime(root, session, command)
    if (worker.get("complete") is not complete or terminal["status"] == "complete" and not complete
            or batch.get("stopped_reason") != worker.get("stopped_reason")
            or complete and (command["returncode"] != 0 or terminal["status"] != "complete"
                             or worker.get("failures") != 0 or worker.get("stopped_reason") is not None)):
        raise ValueError("Partial original main flow cannot be promoted to complete")
    if (terminal.get("expected_scene_ids") is not None and terminal["expected_scene_ids"] != packed["scene_ids"]
            or terminal.get("expected_scenes") is not None and terminal["expected_scenes"] != len(packed["scene_ids"])):
        raise ValueError("Original terminal scene scope differs from complete native packing")
    delivery_ptr = identity(root / "delivery/delivery.json")
    exported = _read(delivery_ptr)
    cost_ptr = identity(root / "delivery/costs.json")
    for artifact in exported.get("artifacts", []):
        _bytes(artifact)
    if (exported.get("source_manifest") != original_source["manifest"] or exported.get("packed_mapping") != packed_ptr
            or exported.get("seed") != seed or exported.get("costs") != aggregated["costs"]
            or _read(cost_ptr) != aggregated["costs"]
            or [s["scene_id"] for s in exported.get("scenes", [])] != packed["scene_ids"]):
        raise ValueError("Original export/costs differ from whole native aggregation")
    for scene, report in zip(packed["scenes"], exported["scenes"], strict=True):
        states = aggregated["scenes"][scene["id"]]
        scene_complete = all(s["status"] == "delivered" for s in states.values())
        srt = root / "delivery/scenes" / scene["id"] / "chn.srt"
        if report.get("status") != ("complete" if scene_complete else "incomplete"):
            raise ValueError("Original scene completion differs from full source cue states")
        if scene_complete:
            window = next(w for w in packed["windows"] if w["scene_id"] == scene["id"])
            document = delivery.scene_document(scene, window)
            expected = delivery.render_srt(document, {key: state["text"] for key, state in states.items()})
            if (srt.read_bytes() != expected.encode("utf-8") or report.get("exported_srt_sha256") != identity(srt)["sha256"]
                    or report.get("exported_srt") != f"scenes/{scene['id']}/chn.srt"):
                raise ValueError("Original complete SRT changed source index/timing/accepted cue text")
        elif srt.exists() or report.get("exported_srt") is not None:
            raise ValueError("Partial source scene cannot have a successful SRT")
    record_scope = {k: record["scope"][k] for k in ("split", "scene_ids", "source_cues", "scored_windows")}
    inventory = _inventory(root)
    if initial_inventory != inventory:
        raise ValueError("Original trial artifacts changed during whole-main authentication")
    generation_status = ("delivered" if complete else "terminal_partial" if dispatched
                         else "setup_failed" if any(r["status"] == "setup_failed" for r in ledger) else "not_run")
    record_value = {"schema": ADMISSION_SCHEMA, "authority": authority, "verifier": auth["verifier"],
        "diagnostic_replay": auth["diagnostic_replay"], "role": role, "seed": seed, "card": entry["card"],
        "retained": retained, "session_root": str(session_root.resolve()), "trial": {"start": start_ptr, "completion": terminal_ptr},
        "session_provenance": [plan_ptr, session_ptr, worker_ptr, batch_ptr, command_ptr, delivery_ptr, cost_ptr, *native_runtime],
        "original_source_authority": original_source, "source_authority": record["source_authority"],
        "scoring_derivation": entry["scoring_derivation"], "actual_source_scope": record_scope,
        "scheduled_batches": len(ids), "attempted_batches": len(ledger), "scheduled_tail": tail,
        "failed_batches": [{"id": r["window_id"], "status": r["status"], "failure_stage": r.get("failure_stage")} for r in ledger if r["status"] != "delivered"],
        "native_complete": complete, "generation_attempt_status": generation_status,
        "native_stage": p["stage"], "declared_executed_snapshots": card["implementation_identity"],
        "captured_executed_snapshots": snapshots, "approved_parser_snapshots": _read(auth["diagnostic_replay"])["parsers"],
        "historical_authorities": entry["historical_authorities"], "original_generation_run_identity": retained["run"],
        "original_cost_count": 1, "new_generation_calls": 0, "new_samples": 0, "new_timing_measurements": 0,
        "semantic_accuracy_verified": False, "inventory": inventory}
    output.parent.mkdir(parents=True, exist_ok=True)
    return _write(output, record_value)


def build_main_proof(*, admission: dict[str, str], expected_admission_sha256: str,
                     authority: dict[str, str], expected_authority_sha256: str, output: Path) -> dict[str, str]:
    """Export the immutable custody20 ABI from independently accepted admission."""
    if admission.get("sha256") != expected_admission_sha256 or output.exists():
        raise ValueError("Main factory needs accepted admission pins and a new destination")
    auth, _ = _authority(authority, expected_authority_sha256)
    value = _read(admission)
    if value.get("schema") != ADMISSION_SCHEMA or value.get("authority") != authority or value.get("verifier") != auth["verifier"]:
        raise ValueError("Main factory admission/code authority differs")
    trial_root = Path(next(e["trial_root"] for e in auth["entries"] if (e["seed"], e["role"]) == (value["seed"], value["role"]))).resolve()
    cost_path = output.with_name(output.stem + "-cost-authority.json")
    if output.resolve().is_relative_to(trial_root) or cost_path.resolve().is_relative_to(trial_root) or cost_path.exists():
        raise ValueError("Main factory cannot write into immutable original trial or overwrite cost proof")
    for ptr in value["inventory"]:
        _bytes(ptr)
    if _inventory(Path(next(e["trial_root"] for e in auth["entries"] if (e["seed"], e["role"]) == (value["seed"], value["role"])))) != value["inventory"]:
        raise ValueError("Original trial inventory gained or lost artifacts after authentication")
    cost = {"schema": "hy30-F5-original-cost-authority-v1", "admission": admission,
            "trial": value["trial"], "original_generation_run_identity": value["original_generation_run_identity"],
            "original_cost_count": 1, "new_generation_calls": 0, "new_samples": 0, "new_timing_measurements": 0}
    cost_ptr = _write(cost_path, cost)
    proof = {key: value[key] for key in ("role", "seed", "card", "source_authority", "retained", "session_root", "trial",
        "approved_parser_snapshots", "actual_source_scope", "original_source_authority", "scoring_derivation",
        "native_complete", "generation_attempt_status", "native_stage")}
    proof.update(schema=custody.MAIN_PROOF_SCHEMA, session_provenance=[*value["session_provenance"], admission],
        cost_authority=cost_ptr, original_generation_cost_identity=cost_ptr, terminal_authority=admission,
        external_registration=auth["external_registration"] if value["role"] == "candidate" else None)
    if set(proof) != custody.MAIN_FIELDS:
        raise ValueError("Main factory must preserve the exact frozen20 field ABI")
    return _write(output, proof)


def make_main_validator(*, seal: dict[str, str], expected_seal_sha256: str) -> Callable[..., dict]:
    """Create a code-pinned metadata/hash-only callback for frozen custody66c.

    Root independently seals exact proof/admission bytes after mechanical audit.
    This callback never parses the original source, native text or raw response.
    """
    if seal.get("sha256") != expected_seal_sha256:
        raise ValueError("Main validator requires independent external seal pins")
    accepted = diagnostics._pointer(seal)
    accepted_path, accepted_sha256 = accepted["path"], accepted["sha256"]

    def validate(receipt: dict[str, str], *, seed: int, role: str, external_registration: dict[str, str]) -> dict:
        # Capture immutable strings, never the caller's mutable pointer object.
        # Every invocation authenticates the originally root-accepted bytes.
        value = _read({"path": accepted_path, "sha256": accepted_sha256})
        if (set(value) != {"schema", "state", "verifier", "authority", "proofs"}
                or value["schema"] != SEAL_SCHEMA or value["state"] != "root_reviewed_original_main_proofs"
                or value["verifier"] != identity(Path(__file__))):
            raise ValueError("Main validator external seal/code authority differs")
        auth, _ = _authority(value["authority"], value["authority"]["sha256"], validate_frame=False)
        entries = [e for e in value["proofs"] if e.get("seed") == seed and e.get("role") == role]
        if (len(entries) != 1 or set(entries[0]) != {"seed", "role", "proof", "admission"}
                or entries[0]["proof"] != receipt or external_registration != auth["external_registration"]):
            raise ValueError("Main proof is not the independently registered seed/role receipt")
        proof, admission = _read(receipt), _read(entries[0]["admission"])
        if (set(proof) != custody.MAIN_FIELDS or proof.get("schema") != custody.MAIN_PROOF_SCHEMA
                or admission.get("schema") != ADMISSION_SCHEMA or admission.get("authority") != value["authority"]
                or admission.get("role") != role or admission.get("seed") != seed):
            raise ValueError("Main proof/admission metadata differs")
        for key in ("role", "seed", "card", "source_authority", "retained", "session_root", "trial", "actual_source_scope",
                    "original_source_authority", "scoring_derivation", "native_complete", "generation_attempt_status", "native_stage",
                    "approved_parser_snapshots"):
            if proof[key] != admission[key]:
                raise ValueError("Main proof metadata does not equal the retained whole-main admission")
        if (proof["session_provenance"] != [*admission["session_provenance"], entries[0]["admission"]]
                or proof["terminal_authority"] != entries[0]["admission"]
                or proof["external_registration"] != (external_registration if role == "candidate" else None)
                or proof["original_generation_cost_identity"] != proof["cost_authority"]):
            raise ValueError("Main proof terminal/session/cost chain changed")
        cost = _read(proof["cost_authority"])
        if cost != {"schema": "hy30-F5-original-cost-authority-v1", "admission": entries[0]["admission"],
            "trial": admission["trial"], "original_generation_run_identity": admission["original_generation_run_identity"],
            "original_cost_count": 1, "new_generation_calls": 0, "new_samples": 0, "new_timing_measurements": 0}:
            raise ValueError("Main proof original once-only cost identity differs")
        for ptr in [proof["card"], *proof["original_source_authority"].values(), *proof["source_authority"].values(),
                    *proof["retained"].values(), *proof["trial"].values(), *proof["session_provenance"],
                    *proof["approved_parser_snapshots"]]:
            _bytes(ptr)
        if proof["scoring_derivation"] is not None:
            _bytes(proof["scoring_derivation"])
        for ptr in admission["inventory"]:
            _bytes(ptr)
        root = Path(next(e["trial_root"] for e in auth["entries"] if (e["seed"], e["role"]) == (seed, role)))
        if _inventory(root) != admission["inventory"]:
            raise ValueError("Original trial inventory changed after root authentication")
        return proof

    return validate
