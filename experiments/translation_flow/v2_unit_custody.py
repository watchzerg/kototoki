"""Prospective F5 source frames and authenticated original-stage packet custody.

This adapter has no inference, judge client or scheduler. Source registration
requires external authority pins; its locally created timestamp is not evidence
that a frame was registered before generation. Native stage proof is separate.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import inspect
from typing import Any, Callable

from experiments.translation_demo import adapters
from . import v2_prepare as packing
from . import v2_unit_diagnostics as diagnostics
from . import v2_delivery as delivery
from . import v2_recipes as recipes
from . import v2_semantic_partition_grammar as partition
from .worker import effective_settings

REGISTRATION_SCHEMA = "hy30-F5-source-frame-registration-v1"
EXTERNAL_REGISTRATION_SCHEMA = "hy30-F5-external-frame-registration-v1"
MAIN_PROOF_SCHEMA = "hy30-F5-authenticated-main-proof-v1"
PREPARED_SCHEMA = "hy30-F5-unit-auxiliary-custody-v1"
MAIN_FIELDS = {"schema", "role", "seed", "card", "source_authority", "retained", "session_root",
               "trial", "session_provenance", "approved_parser_snapshots", "cost_authority",
               "external_registration", "terminal_authority", "actual_source_scope",
               "original_source_authority", "scoring_derivation", "original_generation_cost_identity",
               "native_complete", "generation_attempt_status", "native_stage"}
RETAINED_FIELDS = {"packed", "run", "inputs", "ledger", "results", "schedule"}
STAGES = ("source-planning", "joint-unit-translation", "semantic-remapping")
NON_EXECUTION_FIELDS = {"id", "trial_id", "card_id", "hypothesis", "notes", "description",
                        "created_at_utc", "derivation", "historical_control_relation"}


def identity(path: Path) -> dict[str, str]:
    """Return the identity of existing bytes without interpreting their content."""
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _read(pointer: dict[str, str], *, lines: bool = False) -> Any:
    pointer = diagnostics._pointer(pointer)
    content = Path(pointer["path"]).read_bytes()
    return diagnostics._artifact({"identity": pointer, "content": content}, lines=lines)[0]


def _write(path: Path, value: Any) -> dict[str, str]:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return identity(path)


def _card_execution(card: dict[str, Any]) -> dict[str, Any]:
    execution = deepcopy(card)
    for key in NON_EXECUTION_FIELDS:
        execution.pop(key, None)
    for key in ("seed", "recipe_id"):
        if key in execution and execution[key] != card["prepare"].get(key):
            raise ValueError("Top-level card identifiers disagree with preparation")
        execution.pop(key, None)
        execution["prepare"].pop(key, None)
    return execution


def _source_packing(card: dict[str, Any]) -> dict[str, Any]:
    source, settings = card["source"], card["prepare"]
    manifest, scenes = Path(source["manifest"]), Path(source["scenes"])
    packing.verify_source_freeze(manifest, scenes, settings["split"], stage=settings["stage"])
    data, all_scenes = packing.read_json(manifest), packing.read_rows(scenes)
    windows = [w for w in data["windows"] if w["split"] == settings["split"] or
               settings["split"] == "screening" and w["split"] in ("screen-a", "screen-b")]
    selected = settings.get("selected_scene_ids")
    scene_ids = {w["scene_id"] for w in windows}
    if selected is not None:
        if (not isinstance(selected, list) or len(set(selected)) != len(selected)
                or not set(selected) <= scene_ids):
            raise ValueError("Requested ordered scenes differ from frozen split")
        scene_ids = set(selected)
        windows = [w for w in windows if w["scene_id"] in scene_ids]
    rows = [s for s in all_scenes if s.get("scene_id", s["id"]) in scene_ids]
    ordered = [s.get("scene_id", s["id"]) for s in rows]
    if len(rows) != len(scene_ids) or selected is not None and selected != ordered:
        raise ValueError("Card scene selection changes canonical source order")
    # Registration never measures tokens or consumes generated auxiliary content.
    if (settings.get("measure_source_tokens") is not None or settings.get("source_preparation_path") is not None
            or settings.get("source_preparation") is not None):
        raise ValueError("F5 source registration cannot consume generated preparation")
    token_path = settings.get("token_counts_path")
    counts = packing.verified_counts(Path(token_path), rows) if token_path else None
    geometry = {key: settings.get(key, default) for key, default in (
        ("target_size", 5), ("context_before", 1), ("context_after", 1),
        ("token_target", None), ("common_context", False), ("offset", 0))}
    if settings.get("common_context_block_size") is not None:
        raise ValueError("Register F5 native-unit frames independently of common-block experiments")
    batches = []
    for scene in rows:
        _, mapped = packing.pack_scene(scene, token_counts=counts, **geometry)
        batches.extend(mapped)
    return {"schema": "hy30-flow-packed-v2", "source_manifest": identity(manifest),
        "source_scenes": identity(scenes), "split": settings["split"], "recipe_id": settings["recipe_id"],
        "seed": settings["seed"], "packing": geometry, "scene_ids": ordered,
        "batches": batches, "windows": windows, "scenes": rows,
        "token_counts": identity(Path(token_path)) if token_path else None}


def register_frame(*, cards: list[dict[str, str]], card_bundle: dict[str, str],
                   registered_index: dict[str, str], root_gate: dict[str, str], output: Path) -> dict[str, str]:
    """Write one source-only fixed frame; root must externally pin it before dispatch.

    All pointer hashes are supplied by the caller's accepted registration. The
    three cards must be in frozen seed order. No candidate output is opened.
    """
    if output.exists():
        raise ValueError("Source frame destination already exists")
    bundle, index, gate = _read(card_bundle), _read(registered_index), _read(root_gate)
    if (bundle.get("schema") != "hy30-pending-v5-source-only-freeze-v1"
            or index.get("schema") != "hy30-pending-v5-source-only-index-v1"
            or gate.get("schema") != "hy30-pending-v5-registration-gate-v1"
            or bundle.get("state") != "frozen_not_executed" or index.get("state") != "frozen_not_executed"
            or bundle.get("index") != registered_index
            or gate.get("state") != "promoted-runtime-and-safe-audits-accepted"):
        raise ValueError("Source-only card registration authority is not accepted")
    decoded = [_read(pointer) for pointer in cards]
    if len(decoded) != 3 or [c.get("prepare", {}).get("seed") for c in decoded] != list(diagnostics.SEEDS):
        raise ValueError("The prospective frame requires all three ordered seed cards")
    for pointer, card in zip(cards, decoded, strict=True):
        entry = {"path": pointer["path"], "sha256": pointer["sha256"]}
        for authority in (bundle, index):
            matches = [r for r in authority.get("cards", []) if r.get("id") == card.get("id")]
            if (len(matches) != 1 or {k: matches[0].get(k) for k in entry} != entry
                    or matches[0].get("seed") != card.get("prepare", {}).get("seed")):
                raise ValueError("Card bytes are absent from the externally frozen bundle/index")
        p = card.get("prepare", {})
        if (card.get("schema") != "hy30-flow-trial-card-v2" or card.get("family") != "F5"
                or card.get("role") != "candidate" or p.get("recipe") != "semantic-partition"
                or p.get("stage") != "screening" or p.get("split") not in ("screen-a", "screening")
                or card.get("source") != gate.get("source")
                or card.get("decision_policy") != gate.get("decision_policy")
                or card.get("implementation_identity") != gate.get("implementation_identity")):
            raise ValueError("F5 card differs from the accepted source/runtime registration")
        for code in card["implementation_identity"]:
            _read_bytes(code)
        packer = next((p for p in card["implementation_identity"] if
                       Path(p["path"]).resolve() == Path(packing.__file__).resolve()), None)
        if packer is None or packer != identity(Path(packing.__file__)):
            raise ValueError("The live source packer is not the approved execution snapshot")
        source = card["source"]
        if (identity(Path(source["manifest"]))["sha256"] != source["manifest_sha256"]
                or identity(Path(source["scenes"]))["sha256"] != source["scenes_sha256"]):
            raise ValueError("Source authority bytes differ from frozen card")
        freeze = Path(source["manifest"]).parent / "freeze-manifest.json"
        if card.get("source_freeze") != identity(freeze):
            raise ValueError("Source freeze is not the exact card authority")
        _read(card["decision_policy"])
    if any(_card_execution(c) != _card_execution(decoded[0]) for c in decoded[1:]):
        raise ValueError("Execution contracts differ across the three seed cards")
    packed = [_source_packing(c) for c in decoded]
    shapes = [diagnostics._source(p) for p in packed]
    if any(s != shapes[0] for s in shapes[1:]):
        raise ValueError("Source packing changes across the frozen seed slots")
    selection = [w["id"] for w in packed[0]["windows"]]
    if len(selection) != (48 if packed[0]["split"] == "screen-a" else 96):
        raise ValueError("The complete registered split must remain exactly scored48/96")
    lane = "screen-a" if packed[0]["split"] == "screen-a" else "full96"
    cohort = gate.get("controls", {}).get(lane, {}).get("cohort")
    actual = {"split": packed[0]["split"], "scenes": len(packed[0]["scenes"]),
        "source_cues": sum(len(s["translate_ids"]) for s in packed[0]["scenes"]),
        "score_windows": len(selection), "score_cues": sum(len(w["scored_ids"]) for w in packed[0]["windows"]),
        "batches_per_seed": len(packed[0]["batches"]), "seeds": list(diagnostics.SEEDS)}
    if lane not in gate.get("approved_lanes", []) or cohort != actual:
        raise ValueError("Complete source lane counts differ from the registered actual C0 control scope")
    output.mkdir(parents=True)
    packed_pointers = [_write(output / f"source-packed-seed{seed}.json", p)
                       for seed, p in zip(diagnostics.SEEDS, packed, strict=True)]
    authority = {"manifest": packed[0]["source_manifest"], "scenes": packed[0]["source_scenes"],
                 "freeze": decoded[0]["source_freeze"]}
    frame = diagnostics.freeze_frame(Path(packed_pointers[0]["path"]).read_bytes(), packed_pointers[0],
                                    selection, source_authority=authority)
    frame_pointer = _write(output / "frame.json", frame)
    return _write(output / "registration.json", {"schema": REGISTRATION_SCHEMA,
        "state": "source_only_awaiting_external_registration_before_generation", "frame": frame_pointer,
        "frame_canonical_sha256": diagnostics.canonical_sha256(frame), "source_authority": authority,
        "cards": cards, "card_bundle": card_bundle, "registered_index": registered_index,
        "root_gate": root_gate, "packed": packed_pointers, "helper": identity(Path(diagnostics.__file__)),
        "registrar": identity(Path(__file__)),
        "execution_contract_sha256": diagnostics.canonical_sha256(_card_execution(decoded[0])),
        "scope": {"split": packed[0]["split"], "scene_ids": packed[0]["scene_ids"],
            "source_cues": sum(len(s["translate_ids"]) for s in packed[0]["scenes"]),
            "scheduled_batches_per_seed": len(packed[0]["batches"]), "scored_windows": len(selection),
            "selected_batches_per_seed": len(frame["batches"]), "expected_slots": len(frame["expected_slots"])},
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "output_accessed": False,
        "generation_calls": 0, "judge_calls": 0, "actual_native_authenticated": False})


def _read_bytes(pointer: dict[str, str]) -> bytes:
    pointer = diagnostics._pointer(pointer)
    content = Path(pointer["path"]).read_bytes()
    if hashlib.sha256(content).hexdigest() != pointer["sha256"]:
        raise ValueError("Retained artifact or approved parser snapshot changed")
    return content


def validate_registered_frame(registration: dict[str, str], external_registration: dict[str, str], *,
                              expected_registration_sha256: str, expected_external_sha256: str) -> dict[str, Any]:
    """Replay a separately pinned root receipt; no local timestamp promotion."""
    if registration["sha256"] != expected_registration_sha256 or external_registration["sha256"] != expected_external_sha256:
        raise ValueError("Registration pointers differ from externally accepted pins")
    record, external = _read(registration), _read(external_registration)
    if (record.get("schema") != REGISTRATION_SCHEMA or external.get("schema") != EXTERNAL_REGISTRATION_SCHEMA
            or external.get("state") != "frozen_before_generation"
            or external.get("registration") != registration or external.get("root_gate") != record["root_gate"]):
        raise ValueError("Root has not independently registered this exact source frame")
    at = datetime.fromisoformat(external["registered_at_utc"])
    if at.tzinfo is None:
        raise ValueError("External registration requires an explicit timezone")
    frame = _read(record["frame"])
    if diagnostics.canonical_sha256(frame) != record["frame_canonical_sha256"]:
        raise ValueError("Source frame canonical identity changed")
    for pointer in record["cards"] + record["packed"] + [record[k] for k in (
            "card_bundle", "registered_index", "root_gate", "helper")]:
        _read_bytes(pointer)
    if record["helper"] != identity(Path(diagnostics.__file__)) or record["registrar"] != identity(Path(__file__)):
        raise ValueError("The diagnostic helper/registrar differs from its registered snapshot")
    for card_pointer in record["cards"]:
        card = _read(card_pointer)
        for code in card["implementation_identity"]:
            _read_bytes(code)
    for pointer in record["source_authority"].values():
        _read_bytes(pointer)
    packed = _read(record["packed"][0])
    rebuilt = diagnostics.freeze_frame(_read_bytes(record["packed"][0]), record["packed"][0],
        [w["id"] for w in packed["windows"]], source_authority=record["source_authority"])
    if rebuilt != frame:
        raise ValueError("Registered frame no longer matches its original source packing")
    return {"registration": record, "frame": frame, "external": external,
            "registered_at_utc": at.astimezone(timezone.utc).isoformat()}


def _inside(root: Path, value: str) -> Path:
    path = Path(value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Original stage trace escapes the authenticated managed session")
    return path


def _dependencies() -> list[dict[str, str]]:
    # Closed supported live parser/renderer versions. Never load code supplied by
    # a raw artifact; a historical archive adapter needs separate root approval.
    from . import v2_worker, v2_semantic, v2_semantic_structured, worker
    from experiments.translation_demo import client
    return [identity(Path(module.__file__)) for module in (
        recipes, partition, v2_semantic, v2_semantic_structured,
        v2_worker, worker, adapters, client, delivery)]


def _attempts(row: dict[str, Any], stage: str, item: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = row.get("attempts", [])
    if not isinstance(attempts, list) or any(a.get("stage") not in STAGES for a in attempts):
        raise ValueError("F5 original attempts contain an unsupported stage")
    order = [STAGES.index(a["stage"]) for a in attempts]
    if order != sorted(order):
        raise ValueError("Original F5 stages were reordered")
    selected = [a for a in attempts if a["stage"] == stage]
    if (len(selected) > item["max_attempts"] or [a.get("attempt") for a in selected] != list(range(1, len(selected) + 1))
            or any(a.get("status") not in {"accepted", "failed"} for a in selected)
            or any(a.get("status") == "accepted" for a in selected[:-1])):
        raise ValueError("Original stage retry/accepted attempt order is inconsistent")
    return selected


def _trace(attempt: dict[str, Any], prompt: str, item: dict[str, Any], root: Path, *,
           ids: list[str] | None = None, grammar: str | None = None) -> tuple[str, list[dict[str, str]]]:
    if attempt.get("status") != "accepted" or attempt.get("completion_dispatched") is not True:
        raise ValueError("Native material requires the original accepted dispatched attempt")
    token = _inside(root / "transport", attempt["tokenize_exchange"])
    original = _inside(root / "transport", attempt["original_response"])
    paths = delivery._trace_artifacts(token, "tokenize_exchange", attempt)
    paths += delivery._trace_artifacts(original, "original_response", attempt)
    tokenize = packing.read_json(token / "request.json")
    body = {"content": prompt, "add_special": False, "parse_special": True}
    tokens = packing.read_json(token / "response.raw").get("tokens")
    if (tokenize.get("body") != body or not isinstance(tokens, list)
            or any(type(n) is not int or n < 0 for n in tokens)
            or attempt.get("prompt_sha256") != diagnostics.canonical_sha256(prompt)
            or attempt.get("input_token_ids_sha256") != diagnostics.canonical_sha256(tokens)
            or attempt.get("input_tokens") != len(tokens) or attempt.get("prompt") != prompt):
        raise ValueError("Original tokenizer/prompt/token IDs disagree with the frozen renderer")
    expected = recipes.completion_request(item, tokens, ids, grammar=grammar)
    request, response = packing.read_json(original / "request.json"), packing.read_json(original / "response.raw")
    if (request.get("body") != expected or attempt.get("request_sha256") != diagnostics.canonical_sha256(expected)
            or attempt.get("effective_settings") != effective_settings(response, expected)
            or response.get("prompt") is not None and response["prompt"] != prompt
            or response.get("tokens_evaluated") is not None and response["tokens_evaluated"] != len(tokens)
            or response.get("error") is not None or response.get("truncated") or response.get("stopped_limit")
            or response.get("stop_type") == "limit"):
        raise ValueError("Original completion request/effective response differs from the locked stage")
    if any(packing.read_json(exchange / "transport.json").get("status") != 200 for exchange in (token, original)):
        raise ValueError("Accepted original stage transport was not successful")
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Original native response is empty")
    return content, [identity(path) for path in paths]


def _retry_pointers(row: dict[str, Any], root: Path) -> list[dict[str, str]]:
    paths = {}
    for attempt in row.get("attempts", []):
        for key in ("tokenize_exchange", "original_response"):
            if attempt.get(key) is not None:
                exchange = _inside(root / "transport", attempt[key])
                for path in delivery._trace_artifacts(exchange, key, attempt):
                    paths[str(path)] = identity(path)
    return list(paths.values())


def _stage_material(row: dict[str, Any], window: dict[str, Any], item: dict[str, Any], root: Path) -> dict[str, Any]:
    evidence = {"batch_id": window["id"], "status": row["status"], "original_stage": row.get("failure_stage"),
                "raw_artifacts": _retry_pointers(row, root), "planning": "unavailable",
                "native": "unavailable", "mapping": "unavailable", "native_text_hashes": {},
                "semantic_accuracy_verified": False}
    planning = _attempts(row, STAGES[0], item)
    native_attempts = _attempts(row, STAGES[1], item)
    mapping_attempts = _attempts(row, STAGES[2], item)
    if row.get("semantic_plan") is None:
        if row.get("native_unit_translations") is not None or native_attempts or mapping_attempts:
            raise ValueError("Native/map stages lack their accepted original source plan")
        if any(a["status"] == "accepted" for a in planning) or row["status"] == "delivered":
            raise ValueError("Accepted planning material was removed from terminal row")
        return evidence
    required = partition.planning_required(window)
    if row.get("planning_cost", {}).get("model_planning_required") is not required:
        raise ValueError("Original planning branch does not match frozen source scope")
    if required:
        if not planning or planning[-1]["status"] != "accepted":
            raise ValueError("Source plan does not have its original accepted planning response")
        content, _ = _trace(planning[-1], partition.planning_prompt(window), item, root,
                            grammar=partition.planning_grammar(window))
    else:
        if planning:
            raise ValueError("Deterministic singleton planning must have zero model attempts")
        content = None
    planned = partition.parse_planning(content, window)
    if any(row.get(key) != value for key, value in planned.items()):
        raise ValueError("Original planner response does not produce the retained plan/provenance")
    evidence["planning"] = "original_accepted" if required else "original_deterministic_singleton"
    if row.get("native_protocol") != partition.PROTOCOL:
        raise ValueError("Native partition protocol differs from the approved snapshot")
    if row.get("native_unit_translations") is None:
        if any(a["status"] == "accepted" for a in native_attempts) or mapping_attempts or row["status"] == "delivered":
            raise ValueError("Accepted native material was removed or replaced")
        return evidence
    if not native_attempts or native_attempts[-1]["status"] != "accepted":
        raise ValueError("Retained native strings have no accepted original native attempt")
    plan = planned["semantic_plan"]
    prompt = partition.native_prompt(window, plan)
    extra = recipes.source_options(item, window)
    if extra:
        prompt = prompt.replace("<｜hy_Assistant｜>", "\n" + extra + "<｜hy_Assistant｜>", 1)
    text, _ = _trace(native_attempts[-1], prompt, item, root, ids=[u["id"] for u in plan["units"]])
    native = adapters.translations(text, [u["id"] for u in plan["units"]])
    if native != row["native_unit_translations"] or any(any(0xD800 <= ord(c) <= 0xDFFF for c in s) for s in native.values()):
        raise ValueError("Immutable native strings differ from the accepted raw response")
    evidence["native"] = "original_accepted_intact"
    evidence["native_content_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    evidence["native_text_hashes"] = {key: hashlib.sha256(value.encode("utf-8")).hexdigest() for key, value in native.items()}
    required = partition.mapping_required(window, plan)
    if row.get("mapping_cost", {}).get("model_mapping_required") is not required:
        raise ValueError("Original mapping branch differs from the approved source plan")
    grammar = None
    if required:
        limits = item.get("partition_grammar_limits", {"max_states": partition.DEFAULT_MAX_STATES,
                                                      "max_grammar_bytes": partition.DEFAULT_MAX_GRAMMAR_BYTES})
        build = row.get("mapping_grammar_build", {})
        if build.get("limits") != limits or build.get("native_text_truncated") is not False:
            raise ValueError("Original mapper grammar limits/native text identity changed")
        try:
            built = partition.build_mapping_grammar(window, plan, native, **limits)
        except partition.GrammarComplexityError as exc:
            if (row["status"] != "mapping_unjudgeable" or mapping_attempts or build.get("status") != "failed"
                    or build.get("diagnostics") != exc.diagnostics):
                raise ValueError("Grammar complexity failure differs from the original stage") from exc
            return evidence
        grammar = built["grammar"]
        if (build.get("status") != "accepted" or build.get("diagnostics") != built["diagnostics"]
                or build.get("grammar_sha256") != diagnostics.canonical_sha256(grammar)):
            raise ValueError("Original mapper grammar snapshot differs")
        if not mapping_attempts or mapping_attempts[-1]["status"] != "accepted":
            if row["status"] != "mapping_unjudgeable" or row.get("failure_stage") != STAGES[2]:
                raise ValueError("Unaccepted mapping cannot claim final delivered cues")
            return evidence
        text, _ = _trace(mapping_attempts[-1], partition.mapping_prompt(window, plan, native), item, root, grammar=grammar)
    else:
        if mapping_attempts:
            raise ValueError("Deterministic singleton remapping must have zero model attempts")
        text = None
    mapped = partition.parse_mapping(text, window, plan, native)
    if row["status"] != "delivered" or any(row.get(key) != value for key, value in mapped.items()):
        raise ValueError("Accepted original mapper does not produce the retained exact cue partition")
    evidence["mapping"] = "original_accepted_exact_partition" if required else "original_deterministic_singletons"
    return evidence


def _main(receipt: dict[str, str], *, seed: int, role: str, registered: dict[str, Any],
          external_registration: dict[str, str], validator: Callable[..., dict[str, Any]]) -> tuple[dict, dict]:
    proof = validator(receipt, seed=seed, role=role, external_registration=external_registration)
    if not isinstance(proof, dict) or set(proof) != MAIN_FIELDS or proof != _read(receipt):
        raise ValueError("Trusted main validator must return the exact artifact-bound metadata proof")
    record, frame = registered["registration"], registered["frame"]
    if (proof["schema"] != MAIN_PROOF_SCHEMA or proof["role"] != role or proof["seed"] != seed
            or proof["source_authority"] != record["source_authority"]
            or set(proof["retained"]) != RETAINED_FIELDS
            or set(proof["trial"]) != {"start", "completion"}
            or not proof["session_provenance"]):
        raise ValueError("Authenticated main receipt scope/source/terminal chain differs")
    for pointer in [proof["card"], *proof["retained"].values(), *proof["trial"].values(),
                    *proof["session_provenance"], proof["cost_authority"], proof["terminal_authority"]]:
        _read_bytes(pointer)
    native_authority = proof["original_source_authority"]
    if not isinstance(native_authority, dict) or set(native_authority) != {"manifest", "scenes", "freeze"}:
        raise ValueError("Original native source authority must remain separate and explicit")
    for pointer in native_authority.values():
        _read_bytes(pointer)
    if (proof["original_generation_cost_identity"] != proof["cost_authority"]
            or type(proof["native_complete"]) is not bool
            or proof["generation_attempt_status"] not in {"delivered", "terminal_partial", "not_run", "setup_failed"}):
        raise ValueError("Original generation cost/complete/partial identity is not explicit")
    if native_authority != record["source_authority"]:
        if role != "control" or proof["scoring_derivation"] is None:
            raise ValueError("Only an authenticated historical C0 derivation may change scoring authority")
        _read_bytes(proof["scoring_derivation"])
    elif proof["scoring_derivation"] is not None:
        raise ValueError("Unchanged native source cannot claim a replacement scoring derivation")
    card = _read(proof["card"])
    if card.get("prepare", {}).get("seed") != seed:
        raise ValueError("Original main card seed differs")
    if proof["native_stage"] != card["prepare"].get("stage") or proof["native_stage"] not in {"screening", "full-flow"}:
        raise ValueError("Original native source stage must remain its authenticated screening/full-flow stage")
    original_source = card.get("source", {})
    if (native_authority["manifest"] != {"path": original_source.get("manifest"), "sha256": original_source.get("manifest_sha256")}
            or native_authority["scenes"] != {"path": original_source.get("scenes"), "sha256": original_source.get("scenes_sha256")}
            or native_authority["freeze"] != card.get("source_freeze")):
        raise ValueError("Original source authority differs from the authentic generation card")
    if role == "candidate":
        expected_card = record["cards"][diagnostics.SEEDS.index(seed)]
        if proof["card"] != expected_card or proof["external_registration"] != external_registration:
            raise ValueError("Original F5 main receipt does not bind its prospective registration/card")
        start = _read(proof["trial"]["start"])
        timestamp = datetime.fromisoformat(start["started_at_utc"])
        if timestamp.tzinfo is None or timestamp <= datetime.fromisoformat(registered["registered_at_utc"]):
            raise ValueError("Source frame was not externally registered before F5 generation")
    elif proof["external_registration"] is not None or card.get("prepare", {}).get("recipe") != "c0":
        raise ValueError("Historical C0 control must keep its original cue-output identity")
    approved = proof["approved_parser_snapshots"]
    if not isinstance(approved, list) or any(dependency not in approved for dependency in _dependencies()):
        raise ValueError("Original main proof does not approve the exact live parser snapshots")
    for pointer in approved:
        _read_bytes(pointer)
    retained = {key: {"identity": ptr, "content": _read_bytes(ptr)} for key, ptr in proof["retained"].items()}
    original_frame = deepcopy(frame)
    if role == "control":
        # Preserve original bytes/run hashes. The trusted main proof authorizes
        # scoring lineage; this temporary comparison view only aligns authority
        # pointers, and the helper still checks exact full Japanese scene/times.
        original_frame["source_authority"] = native_authority
    intake = diagnostics._intake(original_frame, seed, retained, control=role == "control")
    intake["original_retained_bytes"] = retained
    scope = {"split": intake["data"]["packed"]["split"],
        "scene_ids": intake["data"]["packed"]["scene_ids"],
        "source_cues": sum(len(s["translate_ids"]) for s in intake["data"]["packed"]["scenes"]),
        "scored_windows": len(intake["data"]["packed"]["windows"])}
    if proof["actual_source_scope"] != scope:
        raise ValueError("Actual native lane/scope counts differ from the original packing")
    if role == "candidate" and scope != {k: record["scope"][k] for k in scope}:
        raise ValueError("Candidate actual native scope is not the full registered lane")
    complete = not intake["schedule"] and set(intake["ledger"]) == set(intake["results"]) == {
        b["batch_id"] for b in intake["source"]["batches"]} and all(r["status"] == "delivered" for r in intake["ledger"].values())
    if (proof["native_complete"] and (not complete or proof["generation_attempt_status"] != "delivered")
            or proof["generation_attempt_status"] == "delivered" and not proof["native_complete"]):
        raise ValueError("Partial original generation cannot be promoted to complete")
    if role == "candidate" and intake["data"]["run"].get("recipe") != "semantic-partition":
        raise ValueError("This approved native stage adapter supports semantic-partition only")
    item = intake["data"]["run"]["settings"]
    expected = card["prepare"]
    if (item.get("recipe") != expected["recipe"] or item.get("n_predict") != expected.get("n_predict", 4096)
            or item.get("sampling") != "official" or item.get("cache_prompt") is not True
            or item.get("max_attempts") != 2
            or any(item.get(key, default) != expected.get("options", {}).get(key, default) for key, default in (
                ("terms", []), ("background", []), ("style", "neutral"), ("review", False)))
            or item.get("partition_grammar_limits") != expected.get("options", {}).get("partition_grammar_limits")):
        raise ValueError("Native workload settings differ from the exact original locked card")
    root = Path(proof["session_root"]).resolve()
    if Path(proof["retained"]["run"]["path"]).resolve().parent.parent != root:
        raise ValueError("Original run is outside its authenticated managed session")
    return proof, intake


def _validator_pin(validator: Callable[..., dict[str, Any]], pointer: dict[str, str], expected: str) -> None:
    path = inspect.getsourcefile(validator)
    if path is None or pointer["sha256"] != expected or identity(Path(path)) != pointer:
        raise ValueError("Main validator callable is not the externally approved code snapshot")


def prepare_unit_auxiliary(*, registration: dict[str, str], external_registration: dict[str, str],
        expected_registration_sha256: str, expected_external_sha256: str,
        main_receipts: list[dict[str, Any]], expected_main_receipts: list[dict[str, Any]],
        main_validator: Callable[..., dict[str, Any]], validator_identity: dict[str, str],
        expected_validator_sha256: str, output: Path) -> dict[str, str]:
    """Authenticate selected original stages, then seal all fixed packet/null slots.

    The existing custody owner supplies the code-pinned main validator. Its proof
    must cover terminal partials separately; this module never promotes a partial
    generation to whole-flow completion or invents unknown historical costs.
    """
    if output.exists():
        raise ValueError("Prepared auxiliary destination already exists")
    if main_receipts != expected_main_receipts:
        raise ValueError("Main receipt inputs differ from independent accepted pins")
    _validator_pin(main_validator, validator_identity, expected_validator_sha256)
    registered = validate_registered_frame(registration, external_registration,
        expected_registration_sha256=expected_registration_sha256, expected_external_sha256=expected_external_sha256)
    frame = registered["frame"]
    intakes, proofs = {}, []
    for entry in main_receipts:
        if set(entry) != {"seed", "role", "receipt"} or entry["seed"] not in diagnostics.SEEDS or entry["role"] not in {"candidate", "control"}:
            raise ValueError("Main receipts require explicit fixed seed/role/pointer slots")
        key = (entry["seed"], entry["role"])
        if key in intakes:
            raise ValueError("Duplicate original main receipt slot")
        proof, intake = _main(entry["receipt"], seed=entry["seed"], role=entry["role"], registered=registered,
            external_registration=external_registration, validator=main_validator)
        intakes[key] = (proof, intake)
        proofs.append(proof)
    slots, raw_pointers = [], {}
    for expected in frame["expected_slots"]:
        seed, bid = expected["seed"], expected["batch_id"]
        candidate = intakes.get((seed, "candidate"))
        control = intakes.get((seed, "control"))
        retained = lambda value: None if value is None else value[1]["original_retained_bytes"]
        stage, row, source_only_preflight = None, None, False
        if candidate is not None:
            proof, intake = candidate
            row = intake["ledger"].get(bid)
            if row is not None:
                window = next(b["producer_input"] for b in intake["source"]["batches"] if b["batch_id"] == bid)
                stage = _stage_material(row, window, intake["data"]["run"]["settings"], Path(proof["session_root"]))
                for pointer in stage["raw_artifacts"]:
                    raw_pointers[pointer["path"]] = pointer
                source_only_preflight = (row["status"] in {"not_run", "setup_failed"}
                    and row.get("semantic_plan") is not None and row.get("native_unit_translations") is None
                    and stage["planning"] == "original_deterministic_singleton"
                    and not any(a.get("completion_dispatched") for a in row.get("attempts", [])))
        view = diagnostics.build_packets(frame, expected_frame_sha256=diagnostics.canonical_sha256(frame),
            batch_id=bid, seed=seed, retained=None if source_only_preflight else retained(candidate))
        if source_only_preflight:
            # Genuine native worker preflight can retain a deterministic source
            # plan without any dispatched generation. Preserve that original
            # fact/null slot; never rewrite the six original retained artifacts.
            view.update(status=row["status"], reason=row.get("reason"), failure_stage=row.get("failure_stage"),
                native_state="native_not_dispatched_original_singleton_source_plan_retained", planned_unit_count=1,
                retained_inputs_validated=True)
            view["provenance"]["candidate"] = candidate[1]["pointers"]
        if control is not None:
            control_frame = deepcopy(frame)
            control_frame["source_authority"] = control[0]["original_source_authority"]
            control_view = diagnostics.build_packets(control_frame,
                expected_frame_sha256=diagnostics.canonical_sha256(control_frame), batch_id=bid, seed=seed,
                c0_retained=retained(control))
            for key in ("c0_packet", "c0_state"):
                view[key] = control_view[key]
            view["provenance"]["c0"] = control_view["provenance"]["c0"]
        if stage is not None:
            if view["native_packet"] is not None and stage["native"] != "original_accepted_intact":
                raise ValueError("Native packet lacks original accepted raw stage authentication")
            if view["attribution_packet"] is not None and stage["mapping"] == "unavailable":
                raise ValueError("Attribution packet lacks original mapper authentication")
        if control is not None and view["c0_packet"] is not None:
            proof, intake = control
            producers = []
            covered = set(expected["expected_source_ids"])
            for batch in intake["source"]["batches"]:
                if batch["scene_id"] != expected["scene_id"] or not covered.intersection(batch["source_ids"]):
                    continue
                row = intake["ledger"].get(batch["batch_id"])
                attempts = [] if row is None else row.get("attempts", [])
                if (not attempts or any(a.get("stage") != "translation" for a in attempts)
                        or attempts[-1].get("status") != "accepted" or len(attempts) > 2
                        or [a.get("attempt") for a in attempts] != list(range(1, len(attempts) + 1))
                        or any(a.get("status") != "failed" for a in attempts[:-1])):
                    raise ValueError("C0 wholebatch control lacks its accepted original cue producer")
                last = attempts[-1]
                # The legacy C0 worker omits inline prompt; tokenizer bytes are
                # still reconstructed and bound. Do not alter the retained row.
                prompt = recipes.render_window("c0", batch["producer_input"], intake["data"]["run"]["settings"])
                if "prompt" in last and last["prompt"] != prompt:
                    raise ValueError("Retained C0 inline prompt contradicts its original tokenizer")
                attempt = {**last, "prompt": prompt}
                text, pointers = _trace(attempt, prompt, intake["data"]["run"]["settings"],
                    Path(proof["session_root"]), ids=batch["source_ids"])
                if adapters.translations(text, batch["source_ids"]) != row["translations"]:
                    raise ValueError("Original C0 raw cue envelope differs from retained control strings")
                pointers += _retry_pointers(row, Path(proof["session_root"]))
                for pointer in pointers:
                    raw_pointers[pointer["path"]] = pointer
                producers.append({"batch_id": batch["batch_id"],
                                  "source_ids": [sid for sid in batch["source_ids"] if sid in covered]})
            view["c0_producer_identity"] = producers
        slots.append({"slot": expected, "views": view, "original_stage_proof": stage,
                      "original_native_authenticated": stage is not None and stage["native"] == "original_accepted_intact"})
    output.mkdir(parents=True)
    return _write(output / "custody.json", {"schema": PREPARED_SCHEMA, "registration": registration,
        "external_registration": external_registration, "main_receipts": main_receipts,
        "validator": validator_identity, "adapter": identity(Path(__file__)),
        "helper": identity(Path(diagnostics.__file__)), "parser_snapshots": _dependencies(),
        "slots": slots, "raw_artifacts": list(raw_pointers.values()),
        "original_generation_cost_authorities": list({p["cost_authority"]["path"]: p["cost_authority"] for p in proofs}.values()),
        "original_generation_metadata": [{k: p[k] for k in ("role", "seed", "original_source_authority",
            "source_authority", "scoring_derivation", "actual_source_scope", "native_complete",
            "generation_attempt_status", "original_generation_cost_identity", "native_stage")} for p in proofs],
        "original_generation_cost_counted_once": True, "generation_calls": 0, "judge_calls": 0,
        "new_independent_samples": False, "primary_score_changed": False,
        "semantic_accuracy_verified": False, "runner_requirement": "custodian_global6_fidelity_then_independent_attribution"})


def validate_prepared_unit_auxiliary(pointer: dict[str, str], *, expected_sha256: str,
        expected_registration: dict[str, str], expected_external_registration: dict[str, str],
        expected_main_receipts: list[dict[str, Any]], expected_validator: dict[str, str]) -> dict[str, Any]:
    """Metadata/hash replay after the original stage proof, without new parsing.

    This is the dispatcher gate, not the source of the first native proof. The
    caller must independently pin this custody receipt after preparation.
    """
    if pointer["sha256"] != expected_sha256:
        raise ValueError("Prepared custody receipt differs from independent accepted pin")
    value = _read(pointer)
    if (value.get("schema") != PREPARED_SCHEMA or value["registration"] != expected_registration
            or value["external_registration"] != expected_external_registration
            or value["main_receipts"] != expected_main_receipts or value["validator"] != expected_validator
            or value["adapter"] != identity(Path(__file__)) or value["helper"] != identity(Path(diagnostics.__file__))
            or value["parser_snapshots"] != _dependencies()):
        raise ValueError("Prepared source/main/parser custody identities differ from the accepted proof")
    registered = validate_registered_frame(expected_registration, expected_external_registration,
        expected_registration_sha256=expected_registration["sha256"], expected_external_sha256=expected_external_registration["sha256"])
    expected = registered["frame"]["expected_slots"]
    if [slot["slot"] for slot in value["slots"]] != expected:
        raise ValueError("Prepared fixed three-seed slot denominator changed")
    pointers = [value["validator"], *value["raw_artifacts"], *value["original_generation_cost_authorities"]]
    for entry in value["main_receipts"]:
        proof = _read(entry["receipt"])
        pointers.extend([entry["receipt"], proof["card"], *proof["retained"].values(),
            *proof["trial"].values(), *proof["session_provenance"], *proof["approved_parser_snapshots"],
            proof["cost_authority"], proof["terminal_authority"], *proof["original_source_authority"].values()])
        if proof["scoring_derivation"] is not None:
            pointers.append(proof["scoring_derivation"])
    for artifact in pointers:
        _read_bytes(artifact)
    return value


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Register source-only F5 three-seed diagnostic scope")
    parser.add_argument("--card", nargs=2, action="append", required=True, metavar=("PATH", "SHA256"))
    for name in ("card-bundle", "registered-index", "root-gate"):
        parser.add_argument("--" + name, nargs=2, required=True, metavar=("PATH", "SHA256"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def pointer(pair: list[str]) -> dict[str, str]:
        return {"path": str(Path(pair[0]).resolve()), "sha256": pair[1]}
    result = register_frame(cards=[pointer(p) for p in args.card], card_bundle=pointer(args.card_bundle),
        registered_index=pointer(args.registered_index), root_gate=pointer(args.root_gate), output=args.output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
