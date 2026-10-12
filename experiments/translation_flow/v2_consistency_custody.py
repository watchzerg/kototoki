"""Native-byte custody for bounded source-only F6/F7 consistency diagnostics.

Opaque hashes are not exposure proof. This module reconstructs actual accepted
tokenization/completion requests and original preparation parsing before it
builds the frozen pure-helper views. It never generates, repairs, or scores text.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from experiments.translation_eval import runner as e
from experiments.translation_judge import integrity
from . import v2_consistency as c
from . import v2_delivery as delivery
from . import v2_prepare as prepare
from . import v2_recipes as recipes
from . import v2_source_preparation as auxiliary
from . import v2_source_projection as projection
from . import v2_source_proposals as proposals
from . import v2_worker as worker

VERSION = "hy30-consistency-native-custody-v1"
ALIASES = {"baseline": "anon-1111111111111111", "treated": "anon-2222222222222222"}
EXECUTION_CARD_FIELDS = {"schema", "source", "prepare", "implementation_identity", "artifacts",
                         "decision_policy", "source_freeze", "fixed_runtime_contract", "source_preparation",
                         "source_preparation_contract"}
CARD_METADATA_FIELDS = {"id", "trial_id", "card_id", "label", "seed", "recipe_id", "candidate_group",
                        "family", "role", "hypothesis", "notes", "description", "created_at_utc",
                        "derivation", "historical_control_relation", "quality_scope", "source_estimate",
                        "prospective_descriptor_only", "frozen_origin", "decision_contract", "baseline_connection",
                        "qualification_prerequisite", "control_reuse", "resource_revision"}


def _neutral_options(options: dict | None) -> dict:
    """Accept only the native absent/neutral defaults, with exact field types."""
    if options is None:
        options = {}
    if (not isinstance(options, dict) or set(options) - {"terms", "background", "style", "review"}
            or options.get("terms", []) != [] or options.get("background", []) != []
            or options.get("style", "neutral") != "neutral" or options.get("review", False) is not False):
        raise ValueError("Consistency requires authentic C0 and the bounded native prepared per-ID treatment")
    return {"terms": [], "background": [], "style": "neutral", "review": False}


def identity(path: Path) -> dict[str, str]:
    return {"path": str(integrity._resolved_path(path)), "sha256": e.sha(path)}


def _pointer(value: dict[str, Any], root: Path | None = None) -> Path:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError("Consistency custody requires an exact file-byte pointer")
    path = Path(value["path"])
    if not path.is_absolute():
        raise ValueError("Consistency custody pointers must be absolute")
    path = integrity._resolved_path(path)
    if root is not None:
        integrity.inside(root, path)
    if not path.is_file() or e.sha(path) != value["sha256"]:
        raise ValueError("Consistency native artifact bytes changed")
    return path


def _main_recipe(card: dict) -> dict:
    """Compare explicit execution fields, retaining descriptors in separate proof."""
    if set(card) - EXECUTION_CARD_FIELDS - CARD_METADATA_FIELDS:
        raise ValueError("Unsupported card fields cannot be silently normalized")
    for key in ("seed", "recipe_id"):
        if key in card and (type(card[key]) is not type(card["prepare"].get(key))
                            or card[key] != card["prepare"].get(key)):
            raise ValueError("Top-level card identifiers disagree with preparation")
    result = {key: deepcopy(card[key]) for key in EXECUTION_CARD_FIELDS if key in card}
    requested = result["prepare"]
    requested.pop("seed", None)
    requested.pop("recipe_id", None)
    requested["options"] = _neutral_options(requested.get("options"))
    # Each original plan and accepted artifact remains in per-seed proofs. The
    # complete auxiliary plan (only seed removed) is compared separately.
    result.pop("source_preparation", None)
    artifacts = result.get("artifacts", {})
    for name in ("token_counts_path", "measure_source_tokens"):
        if requested.get(name) is not None:
            pointer = {"path": requested[name], "sha256": artifacts.get(name)}
            _pointer(pointer)
            requested[name] = {"authenticated_artifact_role": name}
            artifacts[name] = {"authenticated_artifact_role": name}
    return result


def _card_provenance(card: dict, card_pointer: dict) -> dict:
    """Keep full frozen identity and hash-check lineage without interpreting it."""
    metadata = {key: deepcopy(card[key]) for key in CARD_METADATA_FIELDS if key in card}
    for key in ("frozen_origin", "decision_contract", "baseline_connection"):
        if key in metadata and (not isinstance(metadata[key], str) or not metadata[key].strip()):
            raise ValueError("Declared native card descriptor must be a nonempty string")
    for key in ("qualification_prerequisite", "control_reuse", "resource_revision"):
        if key in metadata and not isinstance(metadata[key], dict):
            raise ValueError("Declared native lineage must retain its structured metadata")
    pointers = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if {"path", "sha256"} <= set(value):
                checked = identity(_pointer({key: value[key] for key in ("path", "sha256")}))
                pointers[checked["path"]] = checked
                for key, child in value.items():
                    if key not in {"path", "sha256"}:
                        visit(child)
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for key in ("derivation", "historical_control_relation", "qualification_prerequisite", "control_reuse", "resource_revision"):
        if key in metadata:
            visit(metadata[key])
    authorities = [identity(_pointer(card[key])) for key in ("source_freeze", "decision_policy") if key in card]
    return {"card": deepcopy(card_pointer), "metadata": metadata,
            "lineage_artifacts": list(pointers.values()), "authority_artifacts": authorities}


def _source_preparation_contract(card: dict, plan: dict | None, main: dict) -> None:
    """Bind a v5 declaration to the authenticated executed plan and settings."""
    contract = card.get("source_preparation_contract")
    if contract is not None:
        keys = {"protocol", "projection", "aux_output_reservation_tokens", "main_output_reservation_tokens",
                "cost_attribution", "fresh_server_per_phase"}
        actual_main_budget = (card["prepare"].get("n_predict", 4096) if main["missing"] else main["settings"]["n_predict"])
        if (plan is None or not isinstance(contract, dict) or set(contract) != keys
                or contract["protocol"] != plan["protocol"]
                or contract["projection"] != card["prepare"].get("source_preparation_projection")
                or not main["missing"] and contract["projection"] != main["projection"]
                or type(contract["aux_output_reservation_tokens"]) is not int
                or contract["aux_output_reservation_tokens"] != plan["settings"]["n_predict"]
                or type(contract["main_output_reservation_tokens"]) is not int
                or contract["main_output_reservation_tokens"] != actual_main_budget
                or contract["fresh_server_per_phase"] is not True
                or not isinstance(contract["cost_attribution"], str) or not contract["cost_attribution"].strip()):
            raise ValueError("Declared source preparation contract differs from authenticated native execution")
    revision = card.get("resource_revision")
    if revision is not None:
        change = revision.get("only_executed_parameter_change") if isinstance(revision, dict) else None
        item = change.get("source_preparation.settings.max_items") if isinstance(change, dict) else None
        if (plan is None or not isinstance(change, dict) or set(change) != {"source_preparation.settings.max_items"}
                or not isinstance(item, dict) or set(item) != {"from", "to"}
                or type(item["from"]) is not int or item["from"] < 1
                or type(item["to"]) is not int or item["to"] != plan["settings"]["max_items"]):
            raise ValueError("Declared resource revision differs from authenticated auxiliary settings")


def _source(scope_pointer: dict[str, str]) -> tuple[dict, list[dict], dict]:
    scope = e.read_json(_pointer(scope_pointer))
    if (scope.get("version") != "hy30-consistency-source-scope-v1"
            or scope.get("state") != "frozen_before_consistency_quality"
            or scope.get("split") != "screen-a" or scope.get("quality_inspected") is not False
            or scope.get("selection") != "explicit_complete_scenes"):
        raise ValueError("Consistency needs an explicit source-only screen-a authority")
    manifest, scenes_path, freeze = (_pointer(scope[name]) for name in ("source_manifest", "source_scenes", "source_freeze"))
    if freeze != manifest.parent / "freeze-manifest.json":
        raise ValueError("Consistency source freeze is not the original manifest authority")
    prepare.verify_source_freeze(manifest, scenes_path, "screen-a", stage="screening")
    windows, originals = e.read_json(manifest)["windows"], e.load_jsonl(scenes_path)
    ids = scope.get("scene_ids")
    if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
            or scope.get("selected_scene_count") != len(ids)
            or scope.get("full_scene_count") != len(originals)
            or scope.get("full_window_count") != len(windows)):
        raise ValueError("Selected and full screening source counts must remain distinct")
    index = e.indexed(originals)
    if not set(ids) <= set(index):
        raise ValueError("Consistency scene selection is outside the source authority")
    selected_windows = [row["id"] for row in windows if row["scene_id"] in ids and row["split"] == "screen-a"]
    if scope.get("window_ids") != selected_windows or scope.get("selected_window_count") != len(selected_windows):
        raise ValueError("Consistency must retain every registered selected screen-a window")
    scenes = [{"id": sid, "source_language": "ja", "target_language": "zh-Hans",
        "context": [{"id": cue["id"], "text": cue["text"]} for cue in index[sid]["context"]],
        "translate_ids": index[sid]["translate_ids"]} for sid in ids]
    for scene in scenes:
        c._scene(scene)
    return scope, scenes, index


def _snapshot(session_root: Path, code: dict[str, str], card: dict) -> list[dict]:
    if not code:
        raise ValueError("Native executed implementation snapshot is missing")
    result = []
    for relative, digest in code.items():
        path = integrity.inside(session_root / "source", session_root / "source" / relative)
        if e.sha(path) != digest:
            raise ValueError("Executed native implementation snapshot changed")
        result.append({"relative_path": relative, **identity(path)})
    workspace = Path(__file__).resolve().parents[2]
    if not card.get("implementation_identity"):
        raise ValueError("Generation card needs its frozen executed implementation identity")
    for pointer in card["implementation_identity"]:
        relative = Path(pointer["path"]).relative_to(workspace).as_posix()
        if code.get(relative) != pointer["sha256"]:
            raise ValueError("Native code does not match the approved generation card")
    # The reconstruction executes these live functions. A historical snapshot
    # requires a separately authorized archive loader, never a silent fallback.
    from experiments.translation_demo import adapters
    from experiments.translation_demo import client
    from . import recipes as legacy_recipes, worker as legacy_worker, srt, v2_scene_card, v2_reproject
    dependencies = (recipes, prepare, auxiliary, projection, proposals, worker, delivery, adapters,
                    client, legacy_recipes, legacy_worker, srt, v2_scene_card, v2_reproject)
    for module in dependencies:
        file = Path(module.__file__).resolve()
        relative = file.relative_to(workspace).as_posix()
        if code.get(relative) != e.sha(file):
            raise ValueError("Native rendering/parsing snapshot differs from the pinned reconstruction authority")
    return result


def _command(path: Path, plan_sha256: str, module: str) -> dict:
    evidence = e.read_json(path)
    if (evidence.get("schema") != "hy30-flow-command-v2" or evidence.get("plan_sha256") != plan_sha256
            or evidence.get("worker") != module or type(evidence.get("returncode")) is not int
            or type(evidence.get("command_seconds")) not in (int, float) or evidence["command_seconds"] < 0):
        raise ValueError("Native managed command does not bind its original plan/worker/elapsed accounting")
    return evidence


def _runtime(identity_value: dict, expected: dict) -> None:
    asset, engine = identity_value.get("asset", {}), identity_value.get("engine", {})
    cache = identity_value.get("cache_reset", {})
    if (asset.get("sha256") != expected["asset_sha256"]
            or engine.get("model_sha256") != expected["asset_sha256"]
            or identity_value.get("template_sha256") != expected["template_sha256"]
            or any(engine.get(key) != value for key, value in expected["engine"].items())):
        raise ValueError("Native model/template/engine differ from the approved runtime")
    if "cache_reset" in identity_value and (cache.get("method") != "fresh-managed-server" or cache.get("verified") is not True):
        raise ValueError("Native generation lacks fresh managed-runtime identity")


def _trace(attempt: dict, transport_root: Path, prompt: str, item: dict, *, ids: list[str] | None) -> tuple[str, list[dict]]:
    if attempt.get("completion_dispatched") is not True or attempt.get("status") != "accepted":
        raise ValueError("Consistency exposure requires an accepted dispatched native attempt")
    token = integrity.inside(transport_root, Path(attempt["tokenize_exchange"]))
    original = integrity.inside(transport_root, Path(attempt["original_response"]))
    paths = delivery._trace_artifacts(token, "tokenize_exchange", attempt) + delivery._trace_artifacts(original, "original_response", attempt)
    request = e.read_json(token / "request.json")
    tokens = e.read_json(token / "response.raw").get("tokens")
    if (request["body"]["content"] != prompt or not isinstance(tokens, list) or not tokens
            or any(type(value) is not int for value in tokens)
            or attempt.get("prompt_sha256") != c.object_hash(prompt)
            or attempt.get("input_token_ids_sha256") != c.object_hash(tokens)
            or attempt.get("input_tokens") != len(tokens)):
        raise ValueError("Native tokenize bytes do not match the reconstructed complete rendered prompt")
    expected = recipes.completion_request(item, tokens, ids)
    actual = e.read_json(original / "request.json")["body"]
    response = e.read_json(original / "response.raw")
    if (actual != expected or attempt.get("request_sha256") != c.object_hash(expected)
            or attempt.get("effective_settings") != worker.effective_settings(response, expected)
            or response.get("prompt") is not None and response["prompt"] != prompt
            or response.get("truncated") or response.get("stopped_limit") or response.get("stop_type") == "limit"):
        raise ValueError("Actual native completion settings/prompt differ from the approved reconstruction")
    for exchange in (token, original):
        status = e.read_json(exchange / "transport.json").get("status")
        if status != 200:
            raise ValueError("Accepted native exchange lacks successful original HTTP transport")
    content = response.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Accepted native response has no usable original content")
    return content, [identity(path) for path in paths]


def _auxiliary(root: Path, card: dict, terminal: dict, scope: dict, scenes: list[dict], expected_runtime: dict) -> tuple[list[dict], dict, list[dict]]:
    spec = card.get("source_preparation")
    if spec is None:
        raise ValueError("Treated F6/F7 card must bind an independent native preparation plan")
    plan_pointer = {"path": spec["plan"], "sha256": spec["sha256"]}
    plan_path = _pointer(plan_pointer)
    plan, plan_scenes = auxiliary.load_plan(plan_path)
    if (plan["schema"] != auxiliary.SESSION_SCHEMA or plan["stage"] != "screening"
            or plan["scene_ids"] != scope["scene_ids"] or plan_scenes != scenes
            or plan["settings"]["seed"] != card["prepare"]["seed"]
            or plan["source"]["manifest_sha256"] != scope["source_manifest"]["sha256"]
            or plan["source"]["scenes_sha256"] != scope["source_scenes"]["sha256"]
            or plan["source"]["freeze_sha256"] != scope["source_freeze"]["sha256"]
            or not 1 <= plan["settings"]["max_items"] <= 32):
        raise ValueError("Native preparation plan differs from the complete selected source/seed/stage")
    auxiliary_root = root / "source-preparation/runtime-run/translation"
    metadata = terminal.get("source_preparation", {})
    if metadata.get("plan_sha256") != plan_pointer["sha256"] or Path(metadata.get("plan_path", "")).resolve() != plan_path:
        raise ValueError("Trial preparation is not its exact approved plan")
    if not auxiliary_root.exists():
        if terminal["status"] == "complete" or terminal.get("failed_phase") != "source_preparation":
            raise ValueError("Preparation files absent without explicit native preparation failure")
        slots = [{"scene_id": scene["id"], "status": "not_run", "raw_response": None,
                  "reason": "Native auxiliary session did not start; original trial failed."} for scene in scenes]
        return slots, plan, [identity(plan_path)]
    session = e.read_json(auxiliary_root / "session.json")
    if (session["plan_sha256"] != plan_pointer["sha256"] or session["expected_scene_ids"] != scope["scene_ids"]
            or e.read_json(auxiliary_root / "session-plan.json") != plan):
        raise ValueError("Original auxiliary session/plan/scene inventory changed")
    _runtime(session["identity"], expected_runtime)
    cache = e.read_json(auxiliary_root / "worker-completion.json").get("cache_reset", {})
    if any(row.get("status") == "prepared" for row in e.load_jsonl(auxiliary_root / "ledger.jsonl")) and (
            cache.get("method") != "fresh-managed-server" or cache.get("verified") is not True
            or cache.get("first_response_checked") is not True or cache.get("first_response_cache_n") != 0):
        raise ValueError("Native preparation lacks measured fresh empty-cache evidence")
    snapshot = _snapshot(auxiliary_root, session["code_sha256"], card)
    worker_pointer = identity(auxiliary_root / "worker-completion.json")
    completion = e.read_json(Path(worker_pointer["path"]))
    artifact_path = _pointer(completion["artifact"], auxiliary_root)
    artifact = e.read_json(artifact_path)
    if metadata.get("artifact") != identity(artifact_path) and artifact["complete"]:
        raise ValueError("Trial does not bind its original auxiliary artifact")
    if metadata.get("artifact") is not None and metadata["artifact"] != identity(artifact_path):
        raise ValueError("Partial auxiliary artifact substitutes the original worker output")
    command_path = root / "source-preparation/command-completion.json"
    command = _command(command_path, plan_pointer["sha256"], "experiments.translation_flow.v2_source_preparation")
    cost = metadata.get("cost", {})
    if (cost.get("command") != identity(command_path) or cost.get("ledger") != identity(auxiliary_root / "ledger.jsonl")
            or cost.get("command_seconds") != command["command_seconds"]
            or command["returncode"] != metadata.get("runtime_exit_code")):
        raise ValueError("Auxiliary original command/ledger/cost lineage changed")
    if (artifact["session_plan_sha256"] != plan_pointer["sha256"] or artifact["source"] != plan["source"]
            or artifact["scene_ids"] != scope["scene_ids"] or artifact["settings"] != plan["settings"]
            or artifact.get("protocol") != plan["protocol"] or artifact.get("code_sha256") != session["code_sha256"]
            or artifact.get("identity") != session["identity"] or artifact["complete"] != completion["complete"]):
        raise ValueError("Native auxiliary complete/partial artifact differs from its original session")
    ledger_path, schedule_path = auxiliary_root / "ledger.jsonl", auxiliary_root / "schedule.jsonl"
    rows = e.indexed(e.load_jsonl(ledger_path), "scene_id")
    scheduled = e.indexed(e.load_jsonl(schedule_path), "scene_id") if schedule_path.is_file() else {}
    if set(rows) & set(scheduled) or set(rows) | set(scheduled) != set(scope["scene_ids"]):
        raise ValueError("Native auxiliary must account for every expected scene, including failed/tail slots")
    if artifact["cost_artifacts"]["ledger.jsonl"] != e.sha(ledger_path):
        raise ValueError("Native auxiliary cost ledger byte identity changed")
    attempts = [attempt for row in rows.values() for attempt in row.get("attempts", [])]
    dispatched = [attempt for attempt in attempts if attempt.get("completion_dispatched") is True]
    if (cost.get("scene_records") != len(rows) or cost.get("attempts") != len(attempts)
            or cost.get("translation_calls") != len(dispatched)):
        raise ValueError("Auxiliary attempts/calls cannot be duplicated or erased")
    slots, parsed, raw, proofs = [], [], [], [identity(plan_path), identity(command_path), worker_pointer, identity(artifact_path), identity(ledger_path), *snapshot]
    if schedule_path.is_file():
        proofs.append(identity(schedule_path))
    for scene in scenes:
        sid = scene["id"]
        if sid in scheduled:
            if scheduled[sid].get("status") != "not_run" or not scheduled[sid].get("reason"):
                raise ValueError("Native auxiliary tail needs an explicit not-run reason")
            slots.append({"scene_id": sid, "status": "not_run", "raw_response": None, "reason": scheduled[sid]["reason"]})
            continue
        row = rows[sid]
        if e.read_json(auxiliary_root / ("scene-" + sid + ".json")) != row:
            raise ValueError("Native auxiliary scene artifact differs from its original ledger")
        accepted = [attempt for attempt in row["attempts"] if attempt["status"] == "accepted"]
        if row["status"] == "preparation_failed":
            if accepted:
                raise ValueError("Failed preparation cannot contain an accepted output")
            slots.append({"scene_id": sid, "status": "preparation_failed", "raw_response": None, "reason": row.get("error") or "Native preparation failed."})
            continue
        if row["status"] != "prepared" or len(accepted) != 1:
            raise ValueError("Prepared scene requires one original accepted native completion")
        prompt = proposals.render_prompt(scene, plan["settings"]["max_items"]) if plan["mode"] == "terms" else auxiliary.render_prompt(plan["mode"], scene, plan["settings"]["max_items"])
        prompt_artifact = e.read_json(auxiliary_root / ("prompt-" + sid + ".json"))
        if prompt_artifact["prompt"] != prompt or prompt_artifact["prompt_sha256"] != c.object_hash(prompt):
            raise ValueError("Preparation prompt file differs from source-only native rendering")
        content, trace = _trace(accepted[0], auxiliary_root / "transport", prompt, {"recipe": "base-json", **plan["settings"]}, ids=None)
        expected = proposals.parse_proposals(content, scene, plan["settings"]["max_items"]) if plan["mode"] == "terms" else auxiliary.parse_response(content, plan["mode"], scene, plan["settings"]["max_items"])
        original_raw = {"scene_id": sid, "content": content,
                        "response_sha256": integrity.sha(content.encode("utf-8"))}
        if expected != row["preparation"] or row["accepted_raw_response"] != original_raw:
            raise ValueError("Native accepted proposal parsing/raw-byte lineage changed")
        parsed.append(expected)
        raw.append(original_raw)
        proofs.extend(trace)
        slots.append({"scene_id": sid, "status": "prepared", "raw_response": content, "reason": None})
    if artifact["preparations"] != parsed or artifact["raw_responses"] != raw or bool(artifact["complete"]) != all(row["status"] == "prepared" for row in slots):
        raise ValueError("Native complete/partial artifact drops or invents preparation slots")
    if artifact["complete"]:
        auxiliary.load_options(artifact_path, e.sha(artifact_path))
    return slots, plan, proofs


def _main(root: Path, card: dict, terminal: dict, scope: dict, scenes: list[dict], originals: dict,
          expected_runtime: dict, *, preparation_plan: dict | None = None) -> dict:
    if terminal["status"] != "complete" and not (root / "delivery/delivery.json").exists():
        return {"missing": True, "cost_identity": identity(root / "trial-completion.json"), "native": []}
    from .v2_reproject import _original
    document, packed, aggregate, artifacts = _original(root / "delivery")
    run_dir = integrity.inside(root, Path(document["run"]))
    run = e.read_json(run_dir / "run.json")
    transport_root, shared = delivery._session_transport(run_dir, run)
    if transport_root is None:
        raise ValueError("Consistency requires original fresh native managed generation")
    item = run["settings"]
    session_root = transport_root.parent
    session = e.read_json(session_root / "session.json")
    if session.get("resume") is not None or session.get("performance_valid_for_fresh_flow") is not True:
        raise ValueError("Consistency requires a fresh original session, not resumed history")
    _runtime(session["identity"], expected_runtime)
    snapshot = _snapshot(session_root, run["code_sha256"], card)
    command_path = root / "execution/command-completion.json"
    command = _command(command_path, run["session_plan_sha256"], "experiments.translation_flow.v2_worker")
    if command["returncode"] != terminal.get("runtime_exit_code"):
        raise ValueError("Main managed command exit differs from original trial accounting")
    approved = card["prepare"]
    expected_packing = {key: approved.get(key, default) for key, default in (
        ("target_size", 5), ("context_before", 1), ("context_after", 1), ("token_target", None),
        ("common_context", False), ("offset", 0))}
    expected_settings = {"label": approved["recipe_id"], "recipe": approved.get("recipe", "c0"),
                         "sampling": "official", "cache_prompt": True, "n_predict": 4096,
                         "seed": approved["seed"], "max_attempts": 2, **(approved.get("options") or {})}
    if packed["packing"] != expected_packing or any(item.get(key) != value for key, value in expected_settings.items()):
        raise ValueError("Actual main packing/options/settings differ from the approved card")
    neutral = _neutral_options({key: item[key] for key in ("terms", "background", "style", "review") if key in item})
    if (item["seed"] != card["prepare"]["seed"] or packed["seed"] != item["seed"]
            or packed["scene_ids"] != scope["scene_ids"]
            or packed["source_manifest"] != scope["source_manifest"] or packed["source_scenes"] != scope["source_scenes"]
            or packed["windows"] != [row for row in e.read_json(_pointer(scope["source_manifest"]))["windows"] if row["id"] in scope["window_ids"]]
            or run["source_manifest_sha256"] != scope["source_manifest"]["sha256"]):
        raise ValueError("Native selected packing/seed differs from the exact consistency source authority")
    for sid in scope["scene_ids"]:
        if e.indexed(packed["scenes"])[sid] != originals[sid]:
            raise ValueError("Native complete scene text/order/timing changed")
    plan_path = session_root / "session-plan.json"
    input_rows = e.load_jsonl(run_dir / "inputs.jsonl")
    if [row["id"] for row in input_rows] != [row["id"] for row in packed["batches"]]:
        raise ValueError("Native request sequence differs from selected packed targets")
    options = worker.source_options_by_window(item, plan_path, input_rows)
    if bool(options) != (preparation_plan is not None):
        raise ValueError("Native source-preparation use differs from the approved treated/baseline role")
    if preparation_plan is not None and item["source_preparation"]["artifact"] != terminal["source_preparation"]["artifact"]:
        raise ValueError("Main translation substitutes the original authenticated auxiliary artifact")
    main_settings = deepcopy(item)
    for key in ("seed", "label", "inputs", "input_sha256", "packed_mapping_sha256", "source_preparation"):
        main_settings.pop(key, None)
    main_settings.update(neutral)
    ledger = e.indexed(e.load_jsonl(run_dir / "ledger.jsonl"), "window_id")
    inputs = e.indexed(input_rows)
    proofs, exposure = [], {}
    batches = []
    for batch in packed["batches"]:
        bid = batch["id"]
        local = {"id": bid, "scene_id": batch["scene_id"], "target_ids": batch["target_ids"],
                 "readonly_ids": batch.get("original_readonly_ids", batch["readonly_ids"])}
        batches.append(local)
        window = inputs[bid]
        scene = next(row for row in scenes if row["id"] == batch["scene_id"])
        context_ids = set(batch["target_ids"] + batch["readonly_ids"])
        if window != {"id": bid, "source_language": "ja", "target_language": "zh-Hans",
                      "context": [cue for cue in scene["context"] if cue["id"] in context_ids], "translate_ids": batch["target_ids"]}:
            raise ValueError("Native main input/source context changed")
        current = deepcopy(item)
        current.update(options.get(bid, {}))
        accepted = [attempt for attempt in ledger.get(bid, {}).get("attempts", [])
                    if attempt.get("stage") == "translation" and attempt.get("status") == "accepted"]
        if not accepted:
            exposure[bid] = {"status": "missing", "options_sha256": None, "visibility_sha256": None}
            continue
        if len(accepted) != 1 or item.get("review") is True or item["recipe"] in recipes.SEMANTIC_RECIPES:
            raise ValueError("Consistency custody currently requires one accepted per-ID native translation stage")
        prompt = recipes.render_window(current["recipe"], window, current)
        content, traces = _trace(accepted[0], transport_root, prompt, current, ids=window["translate_ids"])
        from experiments.translation_demo import adapters
        if adapters.translations(content, window["translate_ids"]) != ledger[bid]["translations"]:
            raise ValueError("Delivered native cue text differs from accepted original completion")
        proofs.extend(traces)
        if preparation_plan is not None:
            sidecar_pointer = deepcopy(item["source_preparation"]["batch_options"])
            if not Path(sidecar_pointer["path"]).is_absolute():
                sidecar_pointer["path"] = str(session_root / sidecar_pointer["path"])
            sidecar = e.read_json(_pointer(sidecar_pointer))
            visibility = sidecar["windows"][bid]["visibility"]
            exposure[bid] = {"status": "verified", "options_sha256": c.object_hash(options[bid]),
                             "visibility_sha256": c.object_hash(visibility)}
    first = next((attempt for row in ledger.values() for attempt in row.get("attempts", []) if attempt.get("completion_dispatched")), None)
    if first is not None and e.read_json(Path(first["original_response"]) / "response.raw").get("timings", {}).get("cache_n") != 0:
        raise ValueError("Native first response does not prove empty cache")
    return {"missing": False, "aggregate": aggregate, "batches": batches, "packed": packed, "exposure_proofs": exposure,
            "projection": packed.get("source_preparation_projection"), "settings": item, "recipe_settings": main_settings,
            "cost_identity": identity(root / "trial-completion.json"), "native": [identity(command_path), *[identity(path) for path in artifacts + shared]] + snapshot + proofs}


def authenticate_generation_pair(scope_pointer: dict[str, str], pair_pointer: dict[str, str], *,
        generation_authorization_pointer: dict[str, str], registered_generation_authorization_sha256: str) -> dict[str, Any]:
    """Authenticate one complete seed pair; missing native legs remain unknown."""
    if generation_authorization_pointer["sha256"] != registered_generation_authorization_sha256:
        raise ValueError("Generation authorization differs from its externally registered hash")
    scope, scenes, originals = _source(scope_pointer)
    pair = e.read_json(_pointer(pair_pointer))
    authority = e.read_json(_pointer(generation_authorization_pointer))
    if (authority.get("version") != "hy30-consistency-generation-authority-v1"
            or authority.get("state") != "approved_before_generation" or authority.get("source_scope") != scope_pointer
            or authority.get("generation_seeds") != list(c.SEEDS)
            or pair.get("version") != "hy30-consistency-generation-pair-v1" or pair.get("source_scope") != scope_pointer
            or pair.get("seed") not in c.SEEDS or pair.get("group_id") != authority.get("group_id")
            or authority.get("mode") not in {"terms", "background"}):
        raise ValueError("Consistency source/group/three-seed generation authorization mismatch")
    slots = authority.get("trials", [])
    if [(row.get("seed"), row.get("role")) for row in slots] != [(seed, role) for seed in c.SEEDS for role in ALIASES]:
        raise ValueError("Generation authority must retain all six baseline/treated trial slots")
    authenticated, preparation_slots, plan, proof = {}, None, None, []
    for role in ALIASES:
        spec = pair[role]
        root = integrity._resolved_path(Path(spec["trial_root"]))
        terminal_path = _pointer(spec["terminal"], root)
        if terminal_path != root / "trial-completion.json":
            raise ValueError("Native trial terminal pointer escapes its original identity")
        approved = next(row for row in slots if row["seed"] == pair["seed"] and row["role"] == role)
        if approved["card"] != spec["card"] or Path(approved["output"]).resolve() != root:
            raise ValueError("Native pair substitutes an unapproved generation leg")
        card = e.read_json(_pointer(spec["card"]))
        terminal = e.read_json(terminal_path)
        if (card.get("schema") != "hy30-flow-trial-card-v2" or terminal.get("schema") != "hy30-flow-trial-v2" or terminal.get("card_sha256") != spec["card"]["sha256"]
                or Path(terminal["card_path"]).resolve() != Path(spec["card"]["path"])
                or terminal.get("card") != card or card["prepare"]["seed"] != pair["seed"]
                or terminal.get("status") not in {"complete", "partial", "failed"}):
            raise ValueError("Native terminal/card/seed identity mismatch")
        for name in ("manifest", "scenes"):
            key = "source_manifest" if name == "manifest" else "source_scenes"
            if {"path": card["source"][name], "sha256": card["source"][name + "_sha256"]} != scope[key]:
                raise ValueError("Generation card source differs from the selected complete-scene authority")
        if "source_freeze" in card and card["source_freeze"] != scope["source_freeze"]:
            raise ValueError("Generation card source freeze differs from its qualified source authority")
        if (card["prepare"].get("stage") != "screening" or card["prepare"].get("split") != "screen-a"
                or card["prepare"].get("selected_scene_ids") != scope["scene_ids"]):
            raise ValueError("Generation card is not the selected screen-a workload")
        recipe = card["prepare"].get("recipe", "c0")
        _neutral_options(card["prepare"].get("options"))
        if ((role == "baseline" and recipe != "c0") or (role == "treated" and recipe not in {"c0", "base-json"})):
            raise ValueError("Consistency requires authentic C0 and the bounded native prepared per-ID treatment")
        if role == "treated":
            preparation_slots, plan, native_aux = _auxiliary(root, card, terminal, scope, scenes, authority["runtime"])
            if plan["mode"] != authority["mode"] or plan["settings"]["max_items"] != authority["max_items"]:
                raise ValueError("Generation auxiliary mode/item limit changes the approved group")
            proof.extend(native_aux)
        elif card.get("source_preparation") is not None:
            raise ValueError("Baseline cannot silently inherit treated preparation")
        authenticated[role] = _main(root, card, terminal, scope, scenes, originals, authority["runtime"],
                                   preparation_plan=plan if role == "treated" else None)
        _source_preparation_contract(card, plan if role == "treated" else None, authenticated[role])
        authenticated[role]["recipe"] = _main_recipe(card)
        authenticated[role]["card_provenance"] = _card_provenance(card, spec["card"])
        proof.extend(authenticated[role]["card_provenance"]["lineage_artifacts"])
        proof.extend(authenticated[role]["card_provenance"]["authority_artifacts"])
        proof.extend([identity(terminal_path), identity(_pointer(spec["card"])), *authenticated[role]["native"]])
    baseline = authenticated["baseline"]
    if baseline["missing"]:
        partition = e.read_json(_pointer(authority["baseline_partition"]))
        if partition.get("source_scope") != scope_pointer or partition.get("scene_ids") != scope["scene_ids"]:
            raise ValueError("Missing baseline needs its original registered source-only target partition")
        for scene in scenes:
            c._batches(scene, [batch for batch in partition["batches"] if batch["scene_id"] == scene["id"]])
        baseline["batches"] = partition["batches"]
    expected_batches = baseline["batches"]
    treated = authenticated["treated"]
    if treated["missing"]:
        treated.update(batches=deepcopy(expected_batches), projection=pair["treated"]["projection"],
            exposure_proofs={row["id"]: {"status": "missing", "options_sha256": None, "visibility_sha256": None} for row in expected_batches})
    result_deliveries = {}
    for scene in scenes:
        sid = scene["id"]
        result_deliveries[sid] = {}
        for role, alias in ALIASES.items():
            value = authenticated[role]
            states = ({uid: {"status": "missing", "text": None, "batch_id": None} for uid in scene["translate_ids"]}
                      if value["missing"] else {uid: {"status": ("delivery_failed" if row["status"] == "translation_failed" else row["status"]),
                        "text": row.get("text") if row["status"] == "delivered" else None,
                        "batch_id": row.get("batch_id")} for uid, row in value["aggregate"]["scenes"][sid].items()})
            result_deliveries[sid][alias] = {"source_view_sha256": c.object_hash(scene),
                "provenance_sha256": c.object_hash(value["native"]), "cue_states": states}
    normalized_plan = deepcopy(plan)
    del normalized_plan["settings"]["seed"]
    return {"seed": pair["seed"], "group_id": pair["group_id"], "mode": authority["mode"], "scenes": scenes,
            "source_scope": scope_pointer, "pair_pointer": pair_pointer, "generation_authorization": generation_authorization_pointer,
            "preparations": preparation_slots, "deliveries": result_deliveries,
            "preparation_recipe": normalized_plan,
            "main_recipes": {role: authenticated[role]["recipe"] for role in ALIASES},
            "card_provenance": {role: authenticated[role]["card_provenance"] for role in ALIASES},
            "main_settings": {role: authenticated[role].get("recipe_settings") for role in ALIASES},
            "main_source_partitions": {role: (None if authenticated[role]["missing"] else authenticated[role]["batches"]) for role in ALIASES},
            "baseline_batches": expected_batches, "treated_batches": treated["batches"],
            "projection": treated["projection"], "exposure_proofs": treated["exposure_proofs"],
            "max_items": plan["settings"]["max_items"], "native_proofs": proof,
            "original_cost_identities": [authenticated[role]["cost_identity"] for role in ALIASES],
            "treated_main_not_started": treated["missing"]}


def freeze_source_frames(scope_pointer: dict[str, str], verified_pairs: list[dict], output: Path, *,
                         term_inventory_donor: dict[str, str] | None = None) -> dict[str, Any]:
    """Reauthenticate all three seeds, then freeze A/B expected slots and bundles."""
    if output.exists():
        raise FileExistsError("Consistency custody receipt must be a new immutable file")
    if [pair.get("seed") for pair in verified_pairs] != list(c.SEEDS):
        raise ValueError("Consistency frame requires the ordered full three-seed pair set")
    rebuilt = [authenticate_generation_pair(scope_pointer, pair["pair_pointer"],
        generation_authorization_pointer=pair["generation_authorization"],
        registered_generation_authorization_sha256=pair["generation_authorization"]["sha256"]) for pair in verified_pairs]
    if c.object_hash(rebuilt) != c.object_hash(verified_pairs):
        raise ValueError("Verified native pair views changed before the source-only freeze")
    scope, scenes, _ = _source(scope_pointer)
    first = rebuilt[0]
    if any(any(pair[name] != first[name] for name in ("group_id", "mode", "scenes", "max_items", "baseline_batches", "generation_authorization", "preparation_recipe")) for pair in rebuilt):
        raise ValueError("Consistency source inventory/pair partition differs across seeds")
    for role in ALIASES:
        if any(pair["main_recipes"][role] != first["main_recipes"][role] for pair in rebuilt):
            raise ValueError(f"Consistency {role} main recipe differs across seeds")
        known = [pair["main_source_partitions"][role] for pair in rebuilt if pair["main_source_partitions"][role] is not None]
        if known and any(partition != known[0] for partition in known):
            raise ValueError(f"Consistency {role} source partition differs across seeds")
        known_settings = [pair["main_settings"][role] for pair in rebuilt if pair["main_settings"][role] is not None]
        if known_settings and any(settings != known_settings[0] for settings in known_settings):
            raise ValueError(f"Consistency {role} actual main recipe differs across seeds")
    preparations = {pair["seed"]: pair["preparations"] for pair in rebuilt}
    metadata = {"split": "screening", "quality_inspected": False, "max_items": first["max_items"],
        "source_manifest_sha256": scope["source_manifest"]["sha256"], "scene_file_sha256": scope["source_scenes"]["sha256"],
        "source_freeze_sha256": scope["source_freeze"]["sha256"],
        "preparation_set_sha256": {str(seed): c.object_hash(preparations[seed]) for seed in c.SEEDS}}
    frame_b = c.freeze_frame(scenes, preparations, first["baseline_batches"], mode=first["mode"], metadata=metadata)
    frame_a = frame_b if first["mode"] == "terms" else None
    if term_inventory_donor is not None:
        if first["mode"] != "background":
            raise ValueError("Terms mode cannot substitute an inventory donor")
        donor = validate_receipt(term_inventory_donor)
        if donor["source_scope"] != scope_pointer or donor["frames"]["B"]["inputs"]["mode"] != "terms":
            raise ValueError("F7 term inventory donor must have the exact same registered source scope")
        frame_a = donor["frames"]["B"]
    jobs, slots = [], []
    for pair in rebuilt:
        for scene in scenes:
            sid, seed = scene["id"], pair["seed"]
            deliveries = pair["deliveries"][sid]
            for phase, frame in (("A", frame_a), ("B", frame_b)):
                if frame is None:
                    status = "term_inventory_unavailable"
                elif phase == "A" and not any(row["eligible"] for row in frame["inventory"][sid]):
                    status = "inventory_incomplete" if frame["coverage"][sid]["missing_preparation_slots"] else "not_assessed_zero_inventory"
                elif phase == "B" and frame["parsed"][str(seed)][sid] is not None and not frame["parsed"][str(seed)][sid]["records"]:
                    status = "not_assessed_zero_inventory"
                else:
                    status = "scheduled"
                job_id = f"{phase}-{sid}-{seed}"
                slots.append({"job_id": job_id, "phase": phase, "scene_id": sid, "seed": seed, "status": status})
                if status != "scheduled":
                    continue
                if phase == "A":
                    bundle = c.build_phase_a(frame, sid, seed, deliveries)
                else:
                    batches = [row for row in pair["treated_batches"] if row["scene_id"] == sid]
                    options = {"prepared_alias": ALIASES["treated"], "batches": batches, "projection": pair["projection"],
                               "exposure_proofs": {row["id"]: pair["exposure_proofs"][row["id"]] for row in batches}}
                    bundle = c.build_phase_b(frame, sid, seed, deliveries, **options)
                jobs.append({"job_id": job_id, "envelope": bundle})
    costs = [identity for pair in rebuilt for identity in pair["original_cost_identities"]]
    if len({value["path"] for value in costs}) != 6:
        raise ValueError("Consistency must preserve six distinct original generation/attempt cost identities")
    inventory = []
    for seed in c.SEEDS:
        for sid in frame_b["parsed"][str(seed)]:
            parsed = frame_b["parsed"][str(seed)][sid]
            if parsed and first["mode"] == "terms":
                scene = next(row for row in scenes if row["id"] == sid)
                owners = c._batches(scene, [row for row in first["baseline_batches"] if row["scene_id"] == sid])
                audit = deepcopy(parsed["proposals"])
                for proposal in audit:
                    batches = list(dict.fromkeys(owners[row["id"]] for row in proposal["occurrences"]))
                    proposal.update(baseline_batch_ids=batches, distinct_baseline_batch_count=len(batches),
                        phase_a_eligible=proposal["disposition"] == "accepted" and len(batches) >= 2,
                        phase_a_exclusion_reason=(proposal["reason"] if proposal["disposition"] == "declined" else
                                                  "repeated-within-one-C0-batch" if len(batches) < 2 else None))
                inventory.append({"scene_id": sid, "seed": seed, "proposals": audit,
                    "returned_count": parsed["returned_count"], "accepted_count": parsed["accepted_count"], "declined_count": parsed["declined_count"]})
    receipt = {"version": VERSION, "state": "frozen_before_first_consistency_call", "source_scope": scope_pointer,
        "preparation_recipe": first["preparation_recipe"], "preparation_recipe_sha256": c.object_hash(first["preparation_recipe"]),
        "main_recipes": first["main_recipes"], "main_recipe_sha256": c.object_hash(first["main_recipes"]),
        "card_provenance": {str(pair["seed"]): pair["card_provenance"] for pair in rebuilt},
        "main_source_partitions": {str(pair["seed"]): pair["main_source_partitions"] for pair in rebuilt},
        "main_settings": {str(pair["seed"]): pair["main_settings"] for pair in rebuilt},
        "generation_authorization": first["generation_authorization"], "pair_pointers": [pair["pair_pointer"] for pair in rebuilt],
        "frames": {"A": frame_a, "B": frame_b}, "term_inventory_donor": term_inventory_donor,
        "term_inventory_state": "available" if frame_a is not None else "term_inventory_unavailable",
        "expected_slots": slots, "jobs_sha256": c.object_hash(jobs), "jobs": jobs,
        "original_cost_identities": costs, "original_cost_count": 6, "new_generation_calls": 0,
        "cost_policy": "Count each unique original trial identity once across phases/scenes/windows/groups; diagnostic calls are separate.",
        "proposal_inventory_audit": inventory, "quality_inspected": False,
        "inventory_scope": "Three-seed proposed source terms only; unproposed source anchors remain outside this diagnostic.",
        "implementation": {"custody": e.sha(Path(__file__)), "helper": e.sha(Path(c.__file__))},
        "root_count": None, "root_count_reason": "No independently supported cross-record/scene/seed root identity is inferred."}
    e.dump(output, receipt)
    return {"jobs": jobs, "receipt": identity(output), "frames": receipt["frames"], "expected_slots": slots}


def validate_receipt(pointer: dict[str, str], jobs: list[dict] | None = None) -> dict[str, Any]:
    """Reconstruct frozen native frames/jobs instead of trusting self-consistent hashes."""
    path = _pointer(pointer)
    receipt = e.read_json(path)
    if (receipt.get("version") != VERSION or receipt.get("state") != "frozen_before_first_consistency_call"
            or receipt.get("quality_inspected") is not False
            or receipt.get("implementation") != {"custody": e.sha(Path(__file__)), "helper": e.sha(Path(c.__file__))}):
        raise ValueError("Consistency custody version/code/quality state changed")
    if jobs is not None and c.object_hash(jobs) != receipt["jobs_sha256"]:
        raise ValueError("Consistency prepared jobs differ from authenticated complete native custody")
    pairs = [authenticate_generation_pair(receipt["source_scope"], pair,
        generation_authorization_pointer=receipt["generation_authorization"],
        registered_generation_authorization_sha256=receipt["generation_authorization"]["sha256"]) for pair in receipt["pair_pointers"]]
    import tempfile
    with tempfile.TemporaryDirectory(dir=path.parent, prefix="consistency-rebind-") as temporary:
        rebuilt_path = Path(temporary) / "receipt.json"
        freeze_source_frames(receipt["source_scope"], pairs, rebuilt_path, term_inventory_donor=receipt["term_inventory_donor"])
        if c.object_hash(e.read_json(rebuilt_path)) != c.object_hash(receipt):
            raise ValueError("Consistency custody frames/inventory/jobs differ from actual original native bytes")
    return receipt
