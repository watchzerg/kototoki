"""Prospective confirmation lock and source-role guards; no runtime hooks.

Manifest/scenes bytes are hashed, never decoded here. Only source-freeze metadata,
policy and recipe cards are decoded. A lock authenticates the preregistered bytes,
not the truth of a custodian's claim about when semantic access first occurred.
The caller must retain the externally registered lock/receipt hashes.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from experiments.translation_demo.adapters import strict_json

POLICY_SHA256 = "409553d1a5e2cbfb2e329d415a2b0e862b6a248550b5be5812dffcc4f3c85a9e"
SEEDS = (20261008, 20261009, 20261010)
LOCK_SCHEMA = "hy30-confirmation-candidate-lock-v1"
RECEIPT_SCHEMA = "hy30-confirmation-unseal-receipt-v1"
EVALUATION_SCHEMA = "hy30-confirmation-evaluation-contract-v1"
SCOPE_MODE = "fresh-independent-confirmation48-v1"
OFFICIAL_C0_RUNTIME = {
    "asset_sha256": "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a",
    "engine": "original compatible b11429 CUDA13.4", "context_tokens": 8192,
    "output_reservation_tokens": 4096, "input_margin_tokens": 64, "sampling": "official",
    "temperature": 0.7, "top_p": 1.0, "top_k": 0, "repeat_penalty": 1.0,
    "samplers": ["temperature"], "cache_prompt": True, "fresh_server_per_trial": True,
    "gpu_required": True, "cpu_fallback": False,
    "grammar": "recipe-native ID grammar; id-text protocol intentionally has no JSON grammar",
    "max_attempts_per_step": 2,
}
# These fields describe per-seed identity, prose or historical lineage, not execution.
# They remain bound by each complete card byte pointer in the candidate lock.
CARD_NON_EXECUTION_FIELDS = {
    "id", "trial_id", "card_id", "hypothesis", "notes", "description", "created_at_utc",
    "derivation", "historical_control_relation",
}


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = strict_json(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def _pointer(value: dict[str, Any], base: Path | None = None) -> dict[str, str]:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not value["path"]
            or not isinstance(value["sha256"], str) or len(value["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in value["sha256"])):
        raise ValueError("Expected an exact path/SHA256 pointer")
    path = Path(value["path"])
    if not path.is_absolute():
        if base is None:
            raise ValueError("Relative pointer requires an explicit artifact base")
        path = base / path
    path = path.resolve()
    if _sha(path) != value["sha256"]:
        raise ValueError("Frozen artifact bytes changed")
    return {"path": str(path), "sha256": value["sha256"]}


def pointer(path: Path) -> dict[str, str]:
    """Capture exact bytes; callers register and retain this pointer externally."""
    path = path.resolve()
    return {"path": str(path), "sha256": _sha(path)}


def validate_scope(stage: str, split: str, source_role: str, *, purpose: str = "quality") -> None:
    """Check native source stage; timing measurement phase is a separate concept."""
    if any(not isinstance(value, str) for value in (stage, split, source_role, purpose)):
        raise ValueError("Stage, split, source role and purpose must be explicit strings")
    if purpose == "timing":
        if stage not in {"screening", "full-flow"} or split != "screening" or source_role != "screening":
            raise ValueError("Timing requires the full screening source role/split, regardless of measurement phase")
        return
    if purpose != "quality":
        raise ValueError("Unknown source purpose")
    if stage == "confirmation":
        if split == "confirmation" and source_role == "confirmation":
            return
    elif stage in {"qualification", "screening", "full-flow"}:
        if split in {"screen-a", "screen-b", "screening"} and source_role == "screening":
            return
    raise ValueError("Native stage, source split and freeze role mismatch")


def _policy(path: Path, expected: str) -> tuple[dict[str, Any], dict[str, str]]:
    identity = pointer(path)
    if identity["sha256"] != expected:
        raise ValueError("Decision policy differs from registered pre-result bytes")
    value = _json(Path(identity["path"]))
    if (value.get("status") != "frozen_before_candidate_quality"
            or value.get("primary_endpoint", {}).get("generation_seeds") != list(SEEDS)
            or value["primary_endpoint"].get("confirmation_windows") != 48
            or value.get("confirmation_candidate_lock", {}).get("maximum_complete_candidates") != 3
            or value["confirmation_candidate_lock"].get("lock_all_before_confirmation_open") is not True
            or value["confirmation_candidate_lock"].get("replacement_after_confirmation_results") is not False
            or value["confirmation_candidate_lock"].get("unused_slots_may_be_filled_after_confirmation_results") is not False):
        raise ValueError("Policy does not preserve the prospective confirmation contract")
    return value, identity


def _source(scope: dict[str, Any]) -> dict[str, Any]:
    fields = {"role", "split", "expected_windows", "selection_type", "manifest", "scenes", "freeze"}
    if (not isinstance(scope, dict) or set(scope) != fields or scope["role"] != "confirmation"
            or scope["split"] != "confirmation" or type(scope["expected_windows"]) is not int
            or scope["expected_windows"] != 48 or scope["selection_type"] != "representative"):
        raise ValueError("Confirmation requires a distinct exact representative48 source declaration")
    checked = {**deepcopy(scope), **{key: _pointer(scope[key]) for key in ("manifest", "scenes", "freeze")}}
    freeze_path = Path(checked["freeze"]["path"])
    freeze = _json(freeze_path)
    if (freeze.get("version") != "hy30-flow-v2-source-v1"
            or freeze.get("state") != "source_frozen_reference_qualified"
            or freeze.get("role") != "confirmation" or type(freeze.get("windows")) is not int
            or freeze["windows"] != 48):
        raise ValueError("Future confirmation source requires qualified confirmation48 metadata")
    approved = freeze.get("reference_qualification", {})
    if (approved.get("version") != "hy30-flow-v2-reference-v1"
            or approved.get("state") != "frozen_double_fresh_reference_review"
            or approved.get("inference_allowed") is not True):
        raise ValueError("Confirmation source requires accepted reference qualification metadata")
    _pointer({key: approved.get(key) for key in ("path", "sha256")})
    original_pointer = _pointer(freeze.get("original_source_freeze"))
    original = _json(Path(original_pointer["path"]))
    if (original.get("version") != "hy30-flow-v2-source-v1"
            or original.get("role") != "confirmation"
            or original.get("state") != "source_frozen_reference_unreviewed"):
        raise ValueError("Qualified confirmation must retain its original confirmation freeze")
    artifacts = freeze.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Source freeze requires artifact hashes")
    recorded = {}
    for item in artifacts:
        name = Path(item["path"])
        if name.is_absolute() or name.drive or ".." in name.parts or item["path"] in recorded:
            raise ValueError("Source freeze artifact paths must be unique relative paths")
        recorded[item["path"]] = _pointer(item, freeze_path.parent)
    for key in ("manifest", "scenes"):
        if checked[key] not in recorded.values():
            raise ValueError("Confirmation source bytes are not bound by its freeze")
    return checked


def source_scope_sha256(source_scope: dict[str, Any]) -> str:
    """Bind the evaluation contract to normalized source metadata and opaque bytes."""
    return _hash(_source(source_scope))


def _evaluation(value: dict[str, Any], source: dict[str, Any]) -> dict[str, str]:
    identity = _pointer(value)
    contract = _json(Path(identity["path"]))
    if (contract.get("schema") != EVALUATION_SCHEMA
            or contract.get("state") != "frozen_before_confirmation_open"
            or contract.get("scope_mode") != SCOPE_MODE
            or contract.get("source_scope_sha256") != _hash(source)
            or contract.get("generation_seeds") != list(SEEDS)
            or contract.get("windows_per_seed") != 48
            or contract.get("profile") != "sol-high-auto-v1"
            or contract.get("review_selection") != "all_expected_judgeable_windows_each_seed"
            or contract.get("fresh_C0_required") is not True
            or contract.get("screening_judgment_import_permitted") is not False):
        raise ValueError("Evaluation contract must be a distinct fresh confirmation48 scope")
    _pointer(contract.get("prompt"))
    return identity


def _card(path: Path, alias: str, policy: dict[str, str], source: dict[str, Any], *, baseline: bool) -> dict[str, Any]:
    identity = pointer(path)
    path = Path(identity["path"])
    card = _json(path)
    if card.get("schema") != "hy30-flow-trial-card-v2" or card.get("candidate_group") != alias:
        raise ValueError("Confirmation requires explicit exact trial-card candidate groups")
    if _pointer(card.get("decision_policy"), path.parent) != policy:
        raise ValueError("Confirmation card changes decision policy")
    source_fields = card.get("source", {})
    for key in ("manifest", "scenes"):
        given = {"path": source_fields.get(key), "sha256": source_fields.get(key + "_sha256")}
        if _pointer(given, path.parent) != source[key]:
            raise ValueError("Confirmation card changes exact source scope")
    settings = card.get("prepare", {})
    validate_scope(settings.get("stage"), settings.get("split"), source["role"])
    if settings.get("stage") != "confirmation" or settings.get("selected_scene_ids") is not None:
        raise ValueError("Every confirmation card must retain the complete independent48 scope")
    seed = settings.get("seed")
    if type(seed) is not int or seed not in SEEDS:
        raise ValueError("Confirmation card seed is outside the three frozen quality seeds")
    if not isinstance(settings.get("recipe_id"), str) or not settings["recipe_id"].strip():
        raise ValueError("Confirmation requires an explicit recipe ID per seed")
    recipe = settings.get("recipe", "c0")
    if recipe == "c0":
        from .v2_recipes import validate_options
        options = settings.get("options")
        if options is None:
            options = {}
        if not isinstance(options, dict) or set(options) - {"terms", "background", "style", "review"}:
            raise ValueError("C0 accepts only the native empty terms/background and neutral single-pass defaults")
        validate_options({"recipe": "c0", **options}, set())
    if baseline:
        runtime = card.get("fixed_runtime_contract")
        if not isinstance(runtime, dict) or _hash(runtime) != _hash(OFFICIAL_C0_RUNTIME):
            raise ValueError("C0 fixed runtime contract differs from the official frozen APEX runtime")
    if baseline and (recipe != "c0" or settings.get("target_size") != 5
            or settings.get("context_before") != 1 or settings.get("context_after") != 1
            or any(type(settings.get(key)) is not int for key in ("target_size", "context_before", "context_after"))
            or settings.get("token_target") is not None or settings.get("common_context", False) is not False
            or type(settings.get("offset", 0)) is not int or settings.get("offset", 0) != 0
            or card.get("source_preparation") is not None):
        raise ValueError("Fresh confirmation baseline must preserve the complete C0 recipe")
    implementations = card.get("implementation_identity")
    if not isinstance(implementations, list) or not implementations:
        raise ValueError("Confirmation requires complete declared implementation bytes")
    checked_code = [_pointer(item, path.parent) for item in implementations]
    if len({item["path"] for item in checked_code}) != len(checked_code):
        raise ValueError("Repeated implementation identity")
    prepare_configuration = {key: value for key, value in settings.items() if key not in {"seed", "recipe_id"}}
    if recipe == "c0":
        prepare_configuration["options"] = {"terms": [], "background": [], "style": "neutral", "review": False}
    configuration = {key: deepcopy(value) for key, value in card.items()
                     if key not in CARD_NON_EXECUTION_FIELDS | {"source_preparation"}}
    configuration["prepare"] = prepare_configuration
    configuration["implementation_identity"] = checked_code
    configuration["decision_policy"] = policy
    configuration["source"] = {key: source[key] for key in ("manifest", "scenes")}
    if "source_freeze" in card:
        if _pointer(card["source_freeze"], path.parent) != source["freeze"]:
            raise ValueError("Card source freeze differs from locked confirmation scope")
        configuration["source_freeze"] = source["freeze"]
    for key, expected in (("seed", seed), ("recipe_id", settings["recipe_id"])):
        if key in card:
            if type(card[key]) is not type(expected) or card[key] != expected:
                raise ValueError("Top-level card identifier conflicts with preparation identity")
            configuration.pop(key)
    quality = card.get("quality_scope")
    if quality is not None and (not isinstance(quality, dict)
            or any(type(quality.get(key)) is not int for key in ("windows", "representative_windows", "risk_windows"))
            or quality.get("windows") != 48
            or quality.get("representative_windows") != 48 or quality.get("risk_windows") != 0
            or quality.get("seeds_for_candidate_decision") != list(SEEDS)):
        raise ValueError("Card quality scope imports the old matched screening48 descriptor")
    forbidden = {"source_preparation_path", "source_preparation_sha256", "source_preparation_protocol",
                 "source_preparation_schema", "protocol"}
    if forbidden & settings.keys():
        raise ValueError("Preparation options must originate from the locked auxiliary plan")
    artifacts = card.get("artifacts", {})
    for key in ("token_counts_path", "measure_source_tokens"):
        if settings.get(key) is not None:
            if not isinstance(artifacts, dict):
                raise ValueError("External token artifacts require their exact SHA256 declaration")
            given = {"path": str(settings[key]), "sha256": artifacts.get(key)}
            prepare_configuration[key] = _pointer(given, path.parent)
    auxiliary = card.get("source_preparation")
    if auxiliary is not None:
        if not isinstance(auxiliary, dict) or set(auxiliary) != {"plan", "sha256"}:
            raise ValueError("Source preparation requires its complete frozen plan identity")
        auxiliary_pointer = _pointer({"path": auxiliary["plan"], "sha256": auxiliary["sha256"]}, path.parent)
        auxiliary_plan = _json(Path(auxiliary_pointer["path"]))
        if (auxiliary_plan.get("schema") not in {"hy30-source-preparation-session-v2", "hy30-source-preparation-session-v3"}
                or auxiliary_plan.get("stage") != "confirmation"
                or type(auxiliary_plan.get("settings", {}).get("seed")) is not int
                or auxiliary_plan["settings"]["seed"] != seed):
            raise ValueError("Source preparation stage/seed differs from locked confirmation card")
        auxiliary_source = auxiliary_plan.get("source", {})
        for key in ("manifest", "scenes"):
            given = {"path": auxiliary_source.get(key), "sha256": auxiliary_source.get(key + "_sha256")}
            if _pointer(given, Path(auxiliary_pointer["path"]).parent) != source[key]:
                raise ValueError("Source preparation source differs from locked confirmation scope")
        if auxiliary_source.get("freeze_sha256") != source["freeze"]["sha256"]:
            raise ValueError("Source preparation freeze differs from locked confirmation scope")
        # Keep source/order/mode/budgets, excluding only the declared generation seed.
        auxiliary_configuration = deepcopy(auxiliary_plan)
        auxiliary_configuration["settings"].pop("seed")
        configuration["source_preparation"] = auxiliary_configuration
    elif settings.get("source_preparation_projection") is not None:
        raise ValueError("Source preparation projection requires a locked auxiliary plan")
    return {"card": identity, "seed": seed, "recipe_id": settings.get("recipe_id"),
            "configuration_sha256": _hash(configuration)}


def _cards(paths: list[Path], alias: str, policy: dict[str, str], source: dict[str, Any], *, baseline: bool) -> list[dict[str, Any]]:
    if not isinstance(paths, list) or len(paths) != len(SEEDS):
        raise ValueError("Exactly three frozen per-seed cards are required")
    cards = [_card(Path(path), alias, policy, source, baseline=baseline) for path in paths]
    if sorted(row["seed"] for row in cards) != list(SEEDS):
        raise ValueError("Cards must cover all three distinct frozen seeds")
    if len({row["configuration_sha256"] for row in cards}) != 1:
        raise ValueError("Complete recipe configuration differs across quality seeds")
    return sorted(cards, key=lambda row: row["seed"])


def _payload(policy_path: Path, source_scope: dict[str, Any], baseline_cards: list[Path],
             candidates: list[dict[str, Any]], screening_quality_already_seen: bool,
             expected_policy_sha256: str, evaluation_contract: dict[str, Any]) -> dict[str, Any]:
    policy, policy_identity = _policy(policy_path, expected_policy_sha256)
    source = _source(source_scope)
    evaluation = _evaluation(evaluation_contract, source)
    if type(screening_quality_already_seen) is not bool:
        raise ValueError("Screening quality history must be declared without resetting it")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        raise ValueError("Lock requires one to three complete candidates, all before unseal")
    baseline_alias = policy["baseline"]["alias"]
    baseline = _cards(baseline_cards, baseline_alias, policy_identity, source, baseline=True)
    locked, aliases = [], {baseline_alias}
    categories = set(policy["primary_endpoint"]["categories"])
    for candidate in candidates:
        if (not isinstance(candidate, dict) or set(candidate) != {"candidate_alias", "applicable_categories", "hypothesis", "intent", "cards"}
                or not isinstance(candidate["candidate_alias"], str) or not candidate["candidate_alias"].strip()
                or not isinstance(candidate["hypothesis"], str) or not candidate["hypothesis"].strip()
                or candidate["intent"] not in {"quality", "efficiency"}):
            raise ValueError("Candidate requires complete prospective scope and hypothesis")
        alias = candidate["candidate_alias"]
        if alias in aliases:
            raise ValueError("Candidate aliases must be unique and distinct from C0")
        aliases.add(alias)
        applicable = candidate["applicable_categories"]
        if (not isinstance(applicable, list) or not applicable or any(not isinstance(value, str) or value not in categories for value in applicable)
                or len(set(applicable)) != len(applicable)):
            raise ValueError("Applicable categories must be predeclared and unique")
        if candidate["intent"] == "efficiency" and set(applicable) != categories:
            raise ValueError("Efficiency requires both frozen quality categories")
        cards = _cards(candidate["cards"], alias, policy_identity, source, baseline=False)
        declaration = {key: deepcopy(candidate[key]) for key in ("candidate_alias", "applicable_categories", "hypothesis", "intent")}
        declaration["cards"] = cards
        declaration["complete_recipe_sha256"] = _hash(cards)
        locked.append(declaration)
    return {"schema": LOCK_SCHEMA, "state": "frozen_before_confirmation_unseal", "scope_mode": SCOPE_MODE,
        "decision_policy": policy_identity, "source_scope": source, "source_scope_sha256": _hash(source),
        "evaluation_contract": evaluation,
        "generation_seeds": list(SEEDS), "baseline": {"candidate_alias": baseline_alias, "cards": baseline},
        "candidates": locked, "replacement_or_slot_fill_allowed": False,
        "confirmation_quality_already_seen": False, "screening_quality_already_seen": screening_quality_already_seen,
        "screening_quality_history_preserved": True,
        "screening_source_identity": deepcopy(policy["freeze_provenance"]["source_workload"]),
        "primary_endpoint": deepcopy(policy["primary_endpoint"]),
        "evaluation_scope_requirement": "fresh_confirmation48_all_judgeable_expected_windows_each_seed",
        "generation_requirement": "fresh_complete_C0_and_candidate_sessions_no_screening_or_qualification_import",
        "cache_initial_state": "identical_empty_new_session",
        "request_order_requirement": "frozen_scene_source_order_from_start_not_scoring_window_resets"}


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Custody timestamps require explicit UTC")
    return parsed


def _write_new(path: Path, value: dict[str, Any]) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return pointer(path)


def freeze_lock(policy_path: Path, source_scope: dict[str, Any], baseline_cards: list[Path],
                candidates: list[dict[str, Any]], output: Path, *, screening_quality_already_seen: bool,
                evaluation_contract: dict[str, Any],
                expected_policy_sha256: str = POLICY_SHA256) -> dict[str, str]:
    """Create an immutable complete lock; never assert screening quality was unseen."""
    value = _payload(policy_path, source_scope, baseline_cards, candidates,
                     screening_quality_already_seen, expected_policy_sha256, evaluation_contract)
    value["locked_at_utc"] = datetime.now(timezone.utc).isoformat()
    return _write_new(output, value)


def validate_lock(lock_pointer: dict[str, Any], *, expected_policy_sha256: str = POLICY_SHA256) -> dict[str, Any]:
    checked = _pointer(lock_pointer)
    value = _json(Path(checked["path"]))
    if value.get("schema") != LOCK_SCHEMA:
        raise ValueError("Expected a prospective confirmation lock")
    _utc(value["locked_at_utc"])
    candidates = [{**{key: row[key] for key in ("candidate_alias", "applicable_categories", "hypothesis", "intent")},
                   "cards": [Path(item["card"]["path"]) for item in row["cards"]]} for row in value["candidates"]]
    expected = _payload(Path(value["decision_policy"]["path"]), value["source_scope"],
        [Path(item["card"]["path"]) for item in value["baseline"]["cards"]], candidates,
        value["screening_quality_already_seen"], expected_policy_sha256, value["evaluation_contract"])
    expected["locked_at_utc"] = value["locked_at_utc"]
    if _hash(expected) != _hash(value):
        raise ValueError("Lock declarations or exact registered card bytes changed")
    return value


def record_unseal(lock_pointer: dict[str, Any], output: Path, *,
                  expected_policy_sha256: str = POLICY_SHA256) -> dict[str, str]:
    """Custodian records access authorization AFTER externally registering the lock.

    This records an event; it does not open, publish or evaluate source contents.
    An external custody ledger must establish that no earlier access occurred.
    """
    lock = validate_lock(lock_pointer, expected_policy_sha256=expected_policy_sha256)
    value = {"schema": RECEIPT_SCHEMA, "state": "opened_after_candidate_lock",
        "lock": _pointer(lock_pointer), "source_scope_sha256": lock["source_scope_sha256"],
        "candidate_aliases": [row["candidate_alias"] for row in lock["candidates"]],
        "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        "screening_quality_history_preserved": True, "replacement_or_slot_fill_allowed": False}
    if _utc(value["opened_at_utc"]) < _utc(lock["locked_at_utc"]):
        raise ValueError("Unseal timestamp precedes candidate lock")
    return _write_new(output, value)


def validate_confirmation_dispatch(card_path: Path, lock_pointer: dict[str, Any],
                                   unseal_pointer: dict[str, Any], *,
                                   expected_policy_sha256: str = POLICY_SHA256) -> dict[str, Any]:
    """Authenticate one locked card before dispatch; no generation is performed."""
    lock = validate_lock(lock_pointer, expected_policy_sha256=expected_policy_sha256)
    receipt = _json(Path(_pointer(unseal_pointer)["path"]))
    fields = {"schema", "state", "lock", "source_scope_sha256", "candidate_aliases", "opened_at_utc",
              "screening_quality_history_preserved", "replacement_or_slot_fill_allowed"}
    if (set(receipt) != fields or receipt["schema"] != RECEIPT_SCHEMA
            or receipt["state"] != "opened_after_candidate_lock"
            or _pointer(receipt["lock"]) != _pointer(lock_pointer)
            or receipt["source_scope_sha256"] != lock["source_scope_sha256"]
            or receipt["candidate_aliases"] != [row["candidate_alias"] for row in lock["candidates"]]
            or receipt["screening_quality_history_preserved"] is not True
            or receipt["replacement_or_slot_fill_allowed"] is not False
            or _utc(receipt["opened_at_utc"]) < _utc(lock["locked_at_utc"])):
        raise ValueError("Unseal receipt differs from the complete prospective candidate lock")
    card_identity = pointer(card_path)
    for group in [lock["baseline"], *lock["candidates"]]:
        for card in group["cards"]:
            if card["card"] == card_identity:
                return {"candidate_alias": group["candidate_alias"], "seed": card["seed"],
                    "scope_mode": SCOPE_MODE, "lock": _pointer(lock_pointer),
                    "unseal": _pointer(unseal_pointer), "card": card_identity,
                    "quality_seed_is_frozen": True, "quality_history_reset": False}
    raise ValueError("Card is not an exact preregistered member; no replacement or slot filling")
