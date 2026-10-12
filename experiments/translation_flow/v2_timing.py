"""Policy-bound fresh full-flow paired timing, separate from quality samples."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from experiments.translation_eval.runner import dump, load_jsonl, read_json, safe_id, sha
from .v2_prepare import identity as object_hash
from .v2_confirmation import CARD_NON_EXECUTION_FIELDS, validate_scope
from .v2_reproject import _original, _pointer, identity
from .v2_statistics import student_t_critical, summarize_paired_timing


SCHEMA = "hy30-flow-policy-timing-v1"
CONFIDENCE = .9944444444444445
HALF_WIDTH = 15
SAVING = 60


def read_metadata_fields(path: Path, fields: set[str]) -> dict:
    """Decode selected top-level metadata only, skipping semantic JSON values.

    This is an inventory reader, not a substitute for native protocol validation.
    Unselected values are scanned as bytes/text without constructing their objects.
    """
    if fields & {"preparations", "raw_responses", "translations", "attempts", "request", "response", "content", "terms", "background", "text"}:
        raise ValueError("semantic fields are outside the metadata reader scope")
    text = path.read_text(encoding="utf-8-sig")
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text) and text[index].isspace():
        index += 1
    if index == len(text) or text[index] != "{":
        raise ValueError("metadata inventory requires a JSON object")
    index += 1
    result, seen = {}, set()
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            raise ValueError("unterminated metadata object")
        if text[index] == "}":
            if text[index + 1:].strip():
                raise ValueError("extra metadata content")
            return result
        key, index = decoder.raw_decode(text, index)
        if not isinstance(key, str) or key in seen:
            raise ValueError("invalid or repeated metadata key")
        seen.add(key)
        while index < len(text) and text[index].isspace():
            index += 1
        if text[index:index + 1] != ":":
            raise ValueError("missing metadata colon")
        index += 1
        start, stack, quoted, escaped = index, [], False, False
        while index < len(text):
            char = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                if not stack:
                    break
                if stack.pop() != {"}": "{", "]": "["}[char]:
                    raise ValueError("unbalanced metadata value")
            elif char == "," and not stack:
                break
            index += 1
        if index == len(text) or quoted or stack:
            raise ValueError("unterminated metadata value")
        if key in fields:
            result[key] = json.loads(text[start:index])
        if text[index] == ",":
            index += 1
            if text[index:].lstrip().startswith("}"):
                raise ValueError("trailing metadata comma")


def _auxiliary_source(actual: dict, source: dict, freeze: dict) -> bool:
    expected = {**source, "freeze_sha256": freeze["sha256"]}
    return source.get("freeze_sha256", freeze["sha256"]) == freeze["sha256"] and actual == expected


def _utc(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("timing timestamps require an explicit timezone")
    return stamp


def _positive(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("positive finite measured full-flow seconds required")
    return value


def load_policy(policy: Path, interpretation: Path) -> dict:
    """Read public frozen policy only; never follow reference/evaluation pointers."""
    rule, clarification = read_json(policy), read_json(interpretation)
    timing, workload = rule["timing"], rule["freeze_provenance"]["source_workload"]
    if (rule.get("schema_version") != "hy30-flow-v2-decision-policy-v2"
            or timing.get("interval_confidence") != CONFIDENCE
            or rule["multiplicity"].get("individual_two_sided_confidence") != CONFIDENCE
            or rule["multiplicity"].get("family_size") != 9
            or rule["baseline"].get("seeds") != [20261008, 20261009, 20261010]
            or timing.get("target_half_width_seconds") != HALF_WIDTH
            or timing.get("practically_meaningful_savings_seconds") != SAVING
            or timing.get("exploratory_minimum_completed_pairs") != 4
            or timing.get("independent_confirmation_minimum_pairs") != 4
            or timing.get("exploratory_initial_order") != ["AB", "BA", "AB", "BA"]
            or timing.get("starting_cache_state") != "identical_empty_new_session"
            or timing.get("reused_outputs_or_same_prompt_replay_eligible_for_timing") is not False
            or workload.get("scenes") != 34 or workload.get("source_cues") != 4297
            or clarification.get("schema_version") != "hy30-flow-v2-timing-interpretation-v1"
            or clarification.get("policy_sha256") != sha(policy)
            or clarification.get("unchanged_decision_rules", {}).get("direction_based_early_stopping") is not False):
        raise ValueError("timing policy or interpretation differs from the frozen decision rule")
    return {"policy": identity(policy), "interpretation": identity(interpretation), "rule": rule}


def fixed_n(sample_sd: float) -> int:
    """Smallest even N>=4 meeting the adjusted Student-t precision target."""
    if not math.isfinite(sample_sd) or sample_sd < 0:
        raise ValueError("finite nonnegative exploratory sample SD required")
    def adequate(k: int) -> bool:
        n = 2 * k
        return student_t_critical(CONFIDENCE, n - 1) * sample_sd / math.sqrt(n) <= HALF_WIDTH
    low, high = 2, 2
    while not adequate(high):
        high *= 2
    while low < high:
        middle = (low + high) // 2
        if adequate(middle):
            high = middle
        else:
            low = middle + 1
    return low * 2


def _card(pointer: dict, root: Path, authority: dict) -> tuple[Path, dict]:
    path = _pointer(pointer, root)
    card = read_json(path)
    workload = authority["rule"]["freeze_provenance"]["source_workload"]
    source, settings = card["source"], card["prepare"]
    if (card.get("schema") != "hy30-flow-trial-card-v2" or settings.get("stage") not in ("screening", "full-flow")
            or settings.get("split") != "screening"
            or settings.get("measure_source_tokens") is not None
            or any(settings.get(key) is not None for key in ("source_preparation_path", "source_preparation_sha256"))
            or source.get("manifest_sha256") != workload["manifest_sha256"]
            or source.get("scenes_sha256") != workload["scenes_sha256"]
            or _pointer(card["decision_policy"], path.parent) != Path(authority["policy"]["path"])):
        raise ValueError("timing card changed stage, complete workload, source or decision policy")
    manifest = _pointer({"path": source["manifest"], "sha256": source["manifest_sha256"]}, path.parent)
    scenes = _pointer({"path": source["scenes"], "sha256": source["scenes_sha256"]}, path.parent)
    freeze = read_json(manifest.parent / "freeze-manifest.json")
    validate_scope(settings["stage"], settings["split"], freeze.get("role"), purpose="timing")
    if freeze.get("role") != "screening" or freeze.get("state") != "source_frozen_reference_qualified":
        raise ValueError("timing requires the qualified public screening workload")
    published = {Path(item["path"]).as_posix(): item["sha256"] for item in freeze["artifacts"]}
    for artifact in (manifest, scenes):
        if published.get(artifact.relative_to(manifest.parent).as_posix()) != sha(artifact):
            raise ValueError("timing workload differs from its source freeze")
    rows = load_jsonl(scenes)
    if len(rows) != 34 or sum(len(row["translate_ids"]) for row in rows) != 4297:
        raise ValueError("timing requires all 34 scenes and 4297 source cues")
    if settings.get("selected_scene_ids") not in (None, [row["id"] for row in rows]):
        raise ValueError("timing selected scenes must be the exact complete ordered workload")
    if "source_freeze" in card:
        if _pointer(card["source_freeze"], path.parent) != manifest.parent / "freeze-manifest.json":
            raise ValueError("timing card source freeze differs from its complete workload")
    if not card.get("implementation_identity"):
        raise ValueError("timing cards require frozen implementation artifacts")
    for artifact in card["implementation_identity"]:
        _pointer(artifact, path.parent)
    if "source_preparation" in card:
        spec = card["source_preparation"]
        auxiliary = read_json(_pointer({"path": spec["plan"], "sha256": spec["sha256"]}, path.parent))
        if (not _auxiliary_source(auxiliary["source"], source, identity(manifest.parent / "freeze-manifest.json"))
                or auxiliary["stage"] != settings["stage"]
                or auxiliary["settings"]["seed"] != settings["seed"]
                or auxiliary["scene_ids"] != [row["id"] for row in rows]):
            raise ValueError("source preparation plan differs from the full timing workload/seed")
    return path, card


def _configuration(card: dict, root: Path) -> dict:
    # Exact card bytes still bind every label/prose/lineage field per dispatched leg.
    # Unknown fields remain bound; exclusions are explicit historical metadata only.
    normalized = {key: deepcopy(value) for key, value in card.items()
                  if key not in CARD_NON_EXECUTION_FIELDS | {"control_reuse"}}
    settings = normalized["prepare"]
    for key in ("seed", "recipe_id"):
        if key in normalized:
            if type(normalized[key]) is not type(settings[key]) or normalized[key] != settings[key]:
                raise ValueError("top-level card identifier conflicts with preparation identity")
            normalized.pop(key)
        settings.pop(key)
    source = card["source"]
    normalized["source"] = {key: deepcopy(value) for key, value in source.items()
                            if key not in {"manifest", "manifest_sha256", "scenes", "scenes_sha256"}}
    normalized["source"].update({key: identity(_pointer({"path": source[key], "sha256": source[key + "_sha256"]}, root))
                                 for key in ("manifest", "scenes")})
    settings["selected_scene_ids"] = [row["id"] for row in load_jsonl(Path(normalized["source"]["scenes"]["path"]))]
    normalized["decision_policy"] = identity(_pointer(card["decision_policy"], root))
    normalized["implementation_identity"] = [identity(_pointer(item, root)) for item in card["implementation_identity"]]
    if "source_freeze" in card:
        normalized["source_freeze"] = identity(_pointer(card["source_freeze"], root))
    if "source_preparation" in card:
        spec = card["source_preparation"]
        auxiliary = read_json(_pointer({"path": spec["plan"], "sha256": spec["sha256"]}, root))
        auxiliary["settings"].pop("seed")
        normalized["source_preparation"] = auxiliary
    return normalized


def audit_native_metadata(directory: Path, prepared: Path, *, implementation_card: Path | None = None) -> dict:
    """Diagnostic inventory only: never read translations/attempts or grant timing eligibility.

    Supports historical managed-command roots and native trial execution roots. The
    receipt cannot substitute for collection-time hashes, a prospective plan or
    complete raw-attempt validation by the formal collector.
    """
    directory, prepared = directory.resolve(), prepared.resolve()
    execution = directory / "execution" if (directory / "execution").is_dir() else directory
    plan_path = prepared / "session-plan.json"
    plan = read_json(plan_path)
    workloads = plan.get("workloads", [])
    if len(workloads) != 1:
        raise ValueError("metadata audit requires one explicit native workload")
    label = workloads[0]["label"]
    safe_id(label)
    translation = execution / "runtime-run/translation"
    files = {"trial": directory / "trial-completion.json", "plan": plan_path,
             "command": execution / "command-completion.json", "session": translation / "session.json",
             "worker": translation / "worker-completion.json", "run": translation / label / "run.json",
             "completion": translation / label / "completion.json",
             "runtime": execution / "runtime-run/runtime/runtime-final.json"}
    records = {key: read_json(path) for key, path in files.items() if path.is_file()}
    required = {"trial": {"total_flow_seconds", "phases", "card_sha256", "expected_scene_ids", "complete_scenes"},
                "command": {"returncode", "command_seconds", "plan_sha256", "code_sha256"},
                "session": {"plan_sha256", "performance_valid_for_fresh_flow", "identity", "code_sha256"},
                "worker": {"complete", "reused_windows", "performance_valid_for_fresh_flow"},
                "run": {"settings", "expected_window_ids", "session_plan_sha256", "code_sha256"},
                "completion": {"remaining_window_ids", "failures", "reused_windows", "cache_reset"},
                "runtime": {"session_plan_sha256", "translation_exit_code", "server_process_exited", "worker_process_exited"}}
    gaps = {key: sorted(fields - records.get(key, {}).keys()) for key, fields in required.items()
            if fields - records.get(key, {}).keys()}
    declared = None
    declared_paths = None
    if implementation_card is not None:
        card = read_json(implementation_card)
        declared = {item["sha256"] for item in card["implementation_identity"]}
        declared_paths = {str((implementation_card.parent / item["path"]).resolve()): item["sha256"]
                          for item in card["implementation_identity"]}
    snapshots = {}
    for key in ("session", "run"):
        values = records.get(key, {}).get("code_sha256", {})
        if not isinstance(values, dict):
            values = {}
        snapshots[key] = {"recorded_files": len(values), "undeclared_files": None if declared is None
                          else sorted(name for name, digest in values.items() if digest not in declared),
                          "paths_outside_card": None if declared_paths is None else sorted(name for name in values
                              if str(Path(name).resolve()) not in declared_paths),
                          "declared_path_byte_mismatches": None if declared_paths is None else sorted(name
                              for name, digest in values.items() if str(Path(name).resolve()) in declared_paths
                              and declared_paths[str(Path(name).resolve())] != digest)}
    completion = records.get("completion", {})
    worker = records.get("worker", {})
    runtime = records.get("runtime", {})
    return {"schema": SCHEMA + "-metadata-audit", "diagnostic_only": True, "formal_eligible": False,
            "additional_generation_calls": 0, "additional_quality_samples": 0,
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "directory": str(directory),
            "artifacts": {key: identity(path) for key, path in files.items() if path.is_file()},
            "implementation_card": identity(implementation_card) if implementation_card else None,
            "field_types": {key: {field: type(value).__name__ for field, value in record.items()}
                            for key, record in records.items()}, "missing_formal_fields": gaps,
            "code_identity_coverage": snapshots,
            "observed_metadata": {"expected_batches": len(records.get("run", {}).get("expected_window_ids", [])),
                "completion_remaining": len(completion.get("remaining_window_ids", [])),
                "completion_failures": completion.get("failures"), "reused_windows": completion.get("reused_windows"),
                "worker_complete": worker.get("complete"), "cache_reset": completion.get("cache_reset"),
                "server_process_exited": runtime.get("server_process_exited"),
                "worker_process_exited": runtime.get("worker_process_exited")},
            "unverified": ["prospective_lock", "complete_source_delivery", "raw_attempts_and_replay",
                           "quiet_conditions", "independent_balanced_pairs", "full_flow_wall_time"],
            "scope": "metadata inventory only; no results, ledger, transport, SRT or evaluator files read"}


def _build(authority: dict, cards: dict, seeds: list[int], conditions: dict, phase: str,
           prefix: str, *, pilot: dict | None = None) -> dict:
    safe_id(prefix)
    if len(seeds) < 4 or len(seeds) % 2 or not prefix or any(type(seed) is not int for seed in seeds):
        raise ValueError("timing requires an even >=4 prefrozen seed schedule and unique prefix")
    if set(cards) != {"A", "B"} or not set(seeds) <= set(authority["rule"]["baseline"]["seeds"]):
        raise ValueError("timing requires A/B cards and the prefrozen generation seeds")
    if not isinstance(conditions, dict) or not conditions:
        raise ValueError("timing conditions and sampler policy must be prefrozen")
    pairs = []
    source_order = None
    source_freeze = None
    config = {}
    for side in ("A", "B"):
        for seed in set(seeds):
            card_path, card = _card(cards[side][str(seed)], Path.cwd(), authority)
            if card["prepare"].get("seed") != seed:
                raise ValueError("card seed differs from frozen timing schedule")
            if side == "A" and card["prepare"].get("recipe") != "c0":
                raise ValueError("timing side A must be the preregistered C0 baseline")
            if side == "A" and ("source_preparation" in card
                    or any(card["prepare"].get(key, default) != default for key, default in (
                        ("target_size", 5), ("context_before", 1), ("context_after", 1),
                        ("token_target", None), ("common_context", False), ("offset", 0)))
                    or any(card["prepare"].get("options", {}).get(key) for key in ("terms", "background", "review"))):
                raise ValueError("timing baseline card changes the adopted C0 packing/source options")
            signature = object_hash(_configuration(card, card_path.parent))
            if side in config and config[side] != signature:
                raise ValueError("recipe configuration changes across timing seeds")
            config[side] = signature
            scenes = load_jsonl(Path(card["source"]["scenes"]))
            order = [row["id"] for row in scenes]
            if source_order is not None and source_order != order:
                raise ValueError("timing legs have different frozen source order")
            source_order = order
            source_freeze = identity(Path(card["source"]["manifest"]).parent / "freeze-manifest.json")
    for number, seed in enumerate(seeds):
        pid = f"{prefix}-pair-{number + 1:04d}"
        pairs.append({"pair_id": pid, "order": "AB" if number % 2 == 0 else "BA", "seed": seed,
                      "legs": {side: {"measurement_id": f"{pid}-{side}", "card": cards[side][str(seed)]}
                               for side in ("A", "B")}})
    return {"schema": SCHEMA, "phase": phase, "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "authority": {key: authority[key] for key in ("policy", "interpretation")},
            "confidence": CONFIDENCE, "fixed_n": len(seeds), "source_order": source_order,
            "source_freeze": source_freeze,
            "starting_cache_state": "identical_empty_new_session", "conditions": deepcopy(conditions),
            "conditions_sha256": object_hash(conditions), "cards": deepcopy(cards), "pairs": pairs,
            "pilot": pilot, "additional_quality_seeds": 0,
            "stop_rule": "execute_all_prefrozen_pairs_no_direction_based_stopping"}


def create_exploratory_plan(policy: Path, interpretation: Path, cards: dict, seeds: list[int],
                            conditions: dict, output: Path, *, prefix: str) -> dict:
    """Freeze a balanced pilot before any trial measurement is dispatched."""
    if output.exists():
        raise FileExistsError("timing plan must be new")
    plan = _build(load_policy(policy, interpretation), cards, seeds, conditions, "exploratory", prefix)
    dump(output, plan)
    return plan


def _plan(path: Path) -> tuple[dict, dict]:
    plan = read_json(path)
    authority = load_policy(_pointer(plan["authority"]["policy"], path.parent),
                            _pointer(plan["authority"]["interpretation"], path.parent))
    seeds = [pair["seed"] for pair in plan["pairs"]]
    prefix = plan["pairs"][0]["pair_id"].rsplit("-pair-", 1)[0]
    rebuilt = _build(authority, plan["cards"], seeds, plan["conditions"], plan["phase"], prefix, pilot=plan.get("pilot"))
    rebuilt["created_at_utc"] = plan["created_at_utc"]
    if plan != rebuilt or plan["phase"] not in ("exploratory", "confirmation"):
        raise ValueError("timing schedule/configuration differs from the locked balanced plan")
    if plan["phase"] == "confirmation":
        pilot = plan["pilot"]
        pilot_plan = _pointer(pilot["plan"], path.parent)
        pilot_receipt = _pointer(pilot["receipt"], path.parent)
        measured = summarize_timing(pilot_plan, pilot_receipt)
        pilot_schedule = read_json(pilot_plan)
        if (measured["status"] != "pilot_ready" or plan["fixed_n"] != measured["required_fixed_n"]
                or pilot["sample_sd"] != measured["statistics"]["exploratory"]["standard_deviation_seconds"]
                or plan["cards"] != pilot_schedule["cards"] or plan["conditions"] != pilot_schedule["conditions"]
                or {pair["pair_id"] for pair in plan["pairs"]} & {pair["pair_id"] for pair in pilot_schedule["pairs"]}
                or _utc(plan["created_at_utc"]) <= _utc(read_json(pilot_receipt)["finished_at_utc"])):
            raise ValueError("confirmation N was not locked from the completed pilot before new measurements")
    return plan, authority


def freeze_confirmation_plan(pilot_plan: Path, pilot_receipt: Path, output: Path,
                             seeds: list[int], *, prefix: str) -> dict:
    """Select precision-driven fixed N; never inspect confirmation measurements."""
    if output.exists():
        raise FileExistsError("confirmation timing plan must be new")
    pilot, authority = _plan(pilot_plan)
    measured = summarize_timing(pilot_plan, pilot_receipt)
    if pilot["phase"] != "exploratory" or measured["status"] != "pilot_ready" or len(seeds) != measured["required_fixed_n"]:
        raise ValueError("complete balanced pilot and exact smallest even fixed N required")
    evidence = {"plan": identity(pilot_plan), "receipt": identity(pilot_receipt),
                "sample_sd": measured["statistics"]["exploratory"]["standard_deviation_seconds"]}
    plan = _build(authority, pilot["cards"], seeds, pilot["conditions"], "confirmation", prefix, pilot=evidence)
    dump(output, plan)
    _plan(output)
    return plan


def _native_leg(pointer: dict, root: Path, spec: dict, pair: dict, plan: dict, authority: dict) -> dict:
    path = _pointer(pointer, root)
    report = read_json(path)
    card_path, card = _card(spec["card"], root, authority)
    if (report.get("schema") != "hy30-flow-trial-v2" or report.get("card") != card
            or report.get("card_sha256") != sha(card_path) or Path(report.get("card_path", "")).resolve() != card_path
            or _utc(report["started_at_utc"]) < _utc(plan["created_at_utc"])
            or _utc(report["finished_at_utc"]) <= _utc(report["started_at_utc"])):
        raise ValueError("trial identity/configuration or prospective timing lock changed")
    elapsed = _positive(report["total_flow_seconds"])
    frozen_code = {pointer["sha256"] for pointer in card["implementation_identity"]}
    if report.get("code_sha256") not in frozen_code:
        raise ValueError("trial code differs from frozen implementation identity")
    if report.get("status") != "complete":
        return {"state": "failed", "seconds": elapsed, "trial": identity(path), "reason": report.get("error", report.get("status"))}
    directory = path.parent
    original, packed, aggregation, artifacts = _original(directory / "delivery")
    if "review_diagnostic" in original or "derivation" in original:
        raise ValueError("cached/scoring/review views are not fresh timing measurements")
    expected = plan["source_order"]
    if (report.get("runtime_exit_code") != 0 or report.get("expected_scene_ids") != expected
            or report.get("expected_scenes") != 34 or report.get("complete_scenes") != 34
            or any(report.get(key) != [] for key in ("missing_scene_ids", "unexpected_scene_ids", "duplicate_scene_ids"))
            or packed["scene_ids"] != expected or packed.get("seed") != pair["seed"]
            or packed["source_manifest"]["sha256"] != card["source"]["manifest_sha256"]
            or packed["source_scenes"]["sha256"] != card["source"]["scenes_sha256"]
            or packed["scenes"] != load_jsonl(Path(card["source"]["scenes"]))
            or sum(len(row["translate_ids"]) for row in packed["scenes"]) != 4297
            or any(state["status"] != "delivered" for states in aggregation["scenes"].values() for state in states.values())):
        raise ValueError("trial does not deliver the exact complete frozen 34-scene/4297-cue workload")
    run_dir = directory / "execution/runtime-run/translation" / card["prepare"]["recipe_id"]
    if Path(original["run"]).resolve() != run_dir.resolve():
        raise ValueError("trial reused a delivery from another measurement directory")
    session_dir, runtime = run_dir.parent, directory / "execution/runtime-run/runtime"
    command = read_json(directory / "execution/command-completion.json")
    runtime_receipt = read_json(runtime / "runtime-final.json")
    session, worker = read_json(session_dir / "session.json"), read_json(session_dir / "worker-completion.json")
    completion, run = read_json(run_dir / "completion.json"), read_json(run_dir / "run.json")
    session_plan_path = directory / "prepared/session-plan.json"
    session_plan = read_json(session_plan_path)
    item = session_plan["workloads"][0]
    source_identity = session_plan["experiment_identity"]
    if (len(session_plan["workloads"]) != 1 or session_plan["stage"] != card["prepare"]["stage"]
            or session_plan["experiment_identity"]["split"] != "screening"
            or session_plan.get("resume") or session.get("resume")
            or "token_count_source" in session_plan
            or item != run["settings"] or item["seed"] != pair["seed"]
            or item["label"] != card["prepare"]["recipe_id"] or item["recipe"] != card["prepare"]["recipe"]
            or source_identity.get("source_manifest_sha256") != card["source"]["manifest_sha256"]
            or source_identity.get("seed") != pair["seed"]
            or source_identity.get("source_order_sha256") != object_hash(run["expected_window_ids"])
            or session.get("performance_valid_for_fresh_flow") is not True
            or worker.get("performance_valid_for_fresh_flow") is not True
            or worker.get("complete") is not True or worker.get("reused_windows") != 0
            or completion.get("reused_windows") != 0 or completion.get("remaining_window_ids") != []
            or completion.get("failures") != 0 or command.get("returncode") != 0
            or command.get("plan_sha256") != sha(session_plan_path)
            or session.get("plan_sha256") != sha(session_plan_path)
            or run.get("session_plan_sha256") != sha(session_plan_path)
            or runtime_receipt.get("session_plan_sha256") != sha(session_plan_path)
            or runtime_receipt.get("translation_exit_code") != 0
            or runtime_receipt.get("server_process_exited") is not True
            or runtime_receipt.get("worker_process_exited") is not True):
        raise ValueError("trial session/cache/reuse/command provenance is not fresh and complete")
    if (command.get("code_sha256") not in frozen_code
            or not session.get("code_sha256") or not run.get("code_sha256")
            or not set(session["code_sha256"].values()) <= frozen_code
            or not set(run["code_sha256"].values()) <= frozen_code):
        raise ValueError("managed runtime/worker code differs from frozen card artifacts")
    if card["prepare"]["recipe"] == "c0" and (
            item.get("sampling") != "official" or item.get("n_predict") != 4096 or item.get("cache_prompt") is not True):
        raise ValueError("C0 timing must retain the adopted official sampling/cache recipe")
    engine = session["identity"]["engine"]
    if (engine.get("model_sha256") != authority["rule"]["baseline"]["model_sha256"]
            or engine.get("server_pid") != runtime_receipt.get("server_pid")):
        raise ValueError("timing engine/model identity differs from the managed trial")
    cache = completion["cache_reset"]
    rows = load_jsonl(run_dir / "ledger.jsonl")
    if [row["window_id"] for row in rows] != run["expected_window_ids"]:
        raise ValueError("timing source batch execution order changed")
    attempts = [attempt for row in rows for attempt in row["attempts"]]
    dispatched = [attempt for attempt in attempts if attempt.get("completion_dispatched") is True]
    if (not dispatched or cache.get("method") != "fresh-managed-server" or cache.get("verified") is not True
            or cache.get("first_response_checked") is not True or cache.get("first_response_cache_n") != 0
            or cache.get("server_pid") != engine["server_pid"]
            or dispatched[0].get("response", {}).get("timings", {}).get("cache_n") != 0
            or any(row.get("reused_not_new_measurement") or row.get("reused_artifact") for row in rows)):
        raise ValueError("first native completion did not prove an empty fresh cache")
    for row in rows:
        seen = {}
        for attempt in row["attempts"]:
            if attempt.get("completion_dispatched") is not True:
                continue
            trace = Path(attempt["original_response"])
            request, response = read_json(trace / "request.json"), read_json(trace / "response.raw")
            if request["body"] != attempt["request"] or response != attempt["response"]:
                raise ValueError("native attempt differs from preserved transport evidence")
            prompt = object_hash(attempt["request"])
            if prompt in seen and seen[prompt] != "failed":
                raise ValueError("warm successful prompt replay is not a timing trial retry")
            seen[prompt] = attempt["status"]
    phases = report["phases"]
    if (not {"preparation", "managed_command", "export"} <= phases.keys()
            or any(_positive(value) > elapsed for value in phases.values())
            or sum(phases.values()) > elapsed + .01
            or _positive(command["command_seconds"]) > phases["managed_command"] + .1
            or sum(_positive(row["elapsed_seconds"]) for row in rows) > command["command_seconds"] + .1):
        raise ValueError("trial full-flow wall time does not include all phases and managed command")
    if "source_preparation" in card:
        auxiliary = report.get("source_preparation")
        if (not auxiliary or "source_preparation" not in phases
                or auxiliary.get("runtime_exit_code") != 0
                or auxiliary.get("plan_sha256") != card["source_preparation"]["sha256"]):
            raise ValueError("auxiliary preparation was not freshly executed and charged once")
        auxiliary_root = directory / "source-preparation"
        options_path = _pointer(auxiliary["artifact"], directory)
        options = read_metadata_fields(options_path, {"complete", "source", "scene_ids", "settings", "mode", "stage",
            "protocol", "session_plan_sha256", "cache_reset", "cost_artifacts", "code_sha256", "identity"})
        auxiliary_plan = read_json(_pointer({"path": card["source_preparation"]["plan"],
                                            "sha256": card["source_preparation"]["sha256"]}, card_path.parent))
        auxiliary_worker = read_json(auxiliary_root / "runtime-run/translation/worker-completion.json")
        auxiliary_session = read_json(auxiliary_root / "runtime-run/translation/session.json")
        auxiliary_runtime = read_json(auxiliary_root / "runtime-run/runtime/runtime-final.json")
        auxiliary_cache = options.get("cache_reset", {})
        if (not options_path.is_relative_to(auxiliary_root.resolve()) or options.get("complete") is not True
                or not _auxiliary_source(options.get("source"), card["source"], plan["source_freeze"])
                or options.get("scene_ids") != expected
                or options.get("session_plan_sha256") != card["source_preparation"]["sha256"]
                or any(options.get(key) != auxiliary_plan.get(key) for key in ("settings", "mode", "stage", "protocol"))
                or auxiliary_cache.get("method") != "fresh-managed-server"
                or auxiliary_cache.get("verified") is not True or auxiliary_cache.get("first_response_checked") is not True
                or auxiliary_cache.get("first_response_cache_n") != 0
                or auxiliary_worker.get("complete") is not True or auxiliary_worker.get("failures") != 0
                or auxiliary_worker.get("cache_reset") != auxiliary_cache
                or _pointer(auxiliary_worker["artifact"], auxiliary_root) != options_path
                or auxiliary_session.get("plan_sha256") != card["source_preparation"]["sha256"]
                or auxiliary_session.get("expected_scene_ids") != expected
                or auxiliary_session.get("identity") != options.get("identity")
                or auxiliary_session.get("identity", {}).get("engine", {}).get("model_sha256") != authority["rule"]["baseline"]["model_sha256"]
                or auxiliary_cache.get("server_pid") != auxiliary_runtime.get("server_pid")
                or auxiliary_session.get("identity", {}).get("engine", {}).get("server_pid") != auxiliary_runtime.get("server_pid")
                or auxiliary_runtime.get("session_plan_sha256") != card["source_preparation"]["sha256"]
                or auxiliary_runtime.get("translation_exit_code") != 0
                or auxiliary_runtime.get("server_process_exited") is not True or auxiliary_runtime.get("worker_process_exited") is not True):
            raise ValueError("source preparation reused options or lacks a fresh complete auxiliary session")
        if (not options.get("code_sha256") or options["code_sha256"] != auxiliary_session.get("code_sha256")
                or not set(options["code_sha256"].values()) <= frozen_code):
            raise ValueError("auxiliary source preparation code differs from frozen card artifacts")
        if (_pointer(run["source_preparation"]["artifact"], session_plan_path.parent) != options_path
                or run["source_preparation"] != item.get("source_preparation")):
            raise ValueError("main trial did not consume its own fresh source preparation")
        cost = auxiliary["cost"]
        auxiliary_command = _pointer(cost["command"], directory)
        auxiliary_ledger = _pointer(cost["ledger"], directory)
        auxiliary_command_record = read_json(auxiliary_command)
        auxiliary_rows = load_jsonl(auxiliary_ledger)
        auxiliary_calls = [attempt for row in auxiliary_rows for attempt in row["attempts"] if attempt.get("completion_dispatched") is True]
        if (_positive(cost["command_seconds"]) > phases["source_preparation"] + .1
                or auxiliary_command_record.get("returncode") != 0
                or auxiliary_command_record.get("command_seconds") != cost["command_seconds"]
                or auxiliary_command_record.get("plan_sha256") != card["source_preparation"]["sha256"]
                or auxiliary_command_record.get("code_sha256") not in frozen_code
                or auxiliary_command != auxiliary_root / "command-completion.json"
                or auxiliary_ledger != auxiliary_root / "runtime-run/translation/ledger.jsonl"
                or options.get("cost_artifacts") != {"ledger.jsonl": sha(auxiliary_ledger)}
                or cost.get("scene_records") != len(expected)
                or [row["scene_id"] for row in auxiliary_rows] != expected
                or any(row.get("status") != "prepared" for row in auxiliary_rows)
                or cost.get("attempts") != sum(len(row["attempts"]) for row in auxiliary_rows)
                or cost.get("translation_calls") != len(auxiliary_calls)
                or not auxiliary_calls or auxiliary_calls[0]["response"]["timings"]["cache_n"] != 0):
            raise ValueError("auxiliary preparation costs are incomplete")
        for attempt in auxiliary_calls:
            trace = Path(attempt["original_response"]).resolve()
            if (not trace.is_relative_to(auxiliary_root.resolve())
                    or read_json(trace / "request.json")["body"] != attempt["request"]
                    or read_json(trace / "response.raw") != attempt["response"]):
                raise ValueError("auxiliary preparation reused or changed native transport evidence")
        artifacts.extend(path for path in auxiliary_root.rglob("*") if path.is_file())
    evidence = artifacts + [session_plan_path, directory / "execution/command-completion.json", runtime / "runtime-final.json",
                            session_dir / "session.json", session_dir / "worker-completion.json", run_dir / "completion.json"]
    return {"state": "complete", "seconds": elapsed, "trial": identity(path), "attempts": len(attempts),
            "dispatched_calls": len(dispatched), "costs": aggregation["costs"],
            "cold_load_seconds": runtime_receipt.get("cold_load_seconds"),
            "cold_load_scope": "separately visible when recorded; included once in full-flow wall time",
            "source_preparation_cost": report.get("source_preparation", {}).get("cost"),
            "session_identity": str(session_dir.resolve()), "artifacts": [identity(path) for path in dict.fromkeys(evidence)]}


def execute_plan(plan_path: Path, output: Path, *, observe_conditions: Callable[[], dict],
                 trial_runner: Callable[[Path, Path], int] | None = None) -> dict:
    """Execute every locked leg serially, retaining failed/unknown measurements."""
    plan, authority = _plan(plan_path)
    if output.exists():
        raise FileExistsError("each timing execution needs a new output directory")
    if trial_runner is None:
        from .v2_trial import trial
        trial_runner = trial
    output.mkdir(parents=True)
    receipt = {"schema": SCHEMA, "plan": identity(plan_path), "started_at_utc": datetime.now(timezone.utc).isoformat(), "pairs": []}
    interrupted = False
    for pair in plan["pairs"]:
        record = {"pair_id": pair["pair_id"], "legs": {}}
        for side in pair["order"]:
            spec = pair["legs"][side]
            destination = output / spec["measurement_id"]
            leg = {"measurement_id": spec["measurement_id"]}
            if interrupted:
                record["legs"][side] = {**leg, "trial": None, "reason": "not_run_after_explicit_interruption"}
                continue
            try:
                leg["conditions"] = observe_conditions()
                # Revalidate all frozen cards/code/source immediately before each dispatch.
                _plan(plan_path)
                if sha(_pointer(plan["authority"]["policy"], plan_path.parent)) != plan["authority"]["policy"]["sha256"]:
                    raise ValueError("timing policy changed before dispatch")
                card = _pointer(spec["card"], plan_path.parent)
                leg["invocation_attempted"] = True
                leg["returncode"] = trial_runner(card, destination)
            except BaseException as exc:
                leg["error"] = f"{type(exc).__name__}: {exc}"
                interrupted = not isinstance(exc, Exception)
            report = destination / "trial-completion.json"
            leg["trial"] = identity(report) if report.is_file() else None
            if leg["trial"]:
                try:
                    validated = _native_leg(leg["trial"], output, spec, pair, plan, authority)
                    leg["native_artifacts"] = validated.get("artifacts", [])
                except (ValueError, KeyError, OSError) as exc:
                    leg["validation_error"] = f"{type(exc).__name__}: {exc}"
            record["legs"][side] = leg
            dump(output / "timing-progress.json", {**receipt, "active_pair": record})
        receipt["pairs"].append(record)
    receipt["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    receipt["interrupted"] = interrupted
    dump(output / "timing-receipt.json", receipt)
    return receipt


def summarize_timing(plan_path: Path, receipt_path: Path, *, diagnostics: dict | None = None) -> dict:
    """Validate native trials; a statistical interval alone never clears diagnostics."""
    plan, authority = _plan(plan_path)
    receipt = read_json(receipt_path)
    if receipt.get("schema") != SCHEMA or _pointer(receipt["plan"], receipt_path.parent) != plan_path.resolve():
        raise ValueError("timing receipt belongs to another locked plan")
    if [row["pair_id"] for row in receipt["pairs"]] != [row["pair_id"] for row in plan["pairs"]][:len(receipt["pairs"])]:
        raise ValueError("timing receipt changed order, added pairs or skipped locked attempts")
    seen, sessions, pairs, failures, evidence, measurements = set(), set(), [], [], [], []
    previous_finish = _utc(receipt["started_at_utc"])
    for spec, actual in zip(plan["pairs"], receipt["pairs"], strict=False):
        legs = {}
        if list(actual["legs"]) != list(spec["order"]):
            raise ValueError("native timing leg execution order differs from AB/BA lock")
        for side in spec["order"]:
            leg = actual["legs"][side]
            if leg["measurement_id"] != spec["legs"][side]["measurement_id"]:
                raise ValueError("measurement identity changed")
            if leg.get("trial") is None:
                measured = {"state": "unknown", "seconds": None, "reason": leg.get("error", leg.get("reason", "trial receipt missing"))}
            else:
                trial_path = _pointer(leg["trial"], receipt_path.parent)
                if trial_path in seen:
                    raise ValueError("trial measurement artifact reused under another identity")
                seen.add(trial_path)
                report = read_json(trial_path)
                if _utc(report["started_at_utc"]) < previous_finish:
                    raise ValueError("timing legs overlap or violate AB/BA execution order")
                previous_finish = _utc(report["finished_at_utc"])
                measured = _native_leg(leg["trial"], receipt_path.parent, spec["legs"][side], spec, plan, authority)
                if measured["state"] == "complete":
                    for pointer in leg.get("native_artifacts", []):
                        _pointer(pointer, receipt_path.parent)
                    if leg.get("native_artifacts") != measured["artifacts"]:
                        raise ValueError("native trial receipts lack unchanged collection-time artifact hashes")
                    sid = measured["session_identity"]
                    if sid in sessions:
                        raise ValueError("managed model session reused across timing legs")
                    sessions.add(sid)
                    evidence.extend(measured["artifacts"])
            condition = leg.get("conditions", {})
            if measured["state"] == "complete" and leg.get("returncode") != 0:
                measured = {**measured, "state": "unknown", "reason": "trial invocation did not record a successful exit"}
            if condition.get("policy_sha256") != plan["conditions_sha256"] or condition.get("state") != "verified":
                measured = {**measured, "state": "unknown", "reason": "measurement conditions not verified against locked policy"}
            legs[side] = measured
        complete = all(leg["state"] == "complete" for leg in legs.values())
        measurements.append({"pair_id": spec["pair_id"], "legs": legs})
        if not complete:
            failures.append({"pair_id": spec["pair_id"], "legs": legs})
        pairs.append({"pair_id": spec["pair_id"], "phase": plan["phase"], "order": spec["order"],
                      "status": "completed" if complete else "failed", "baseline_completed": complete, "candidate_completed": complete,
                      "baseline_seconds": legs["A"]["seconds"], "candidate_seconds": legs["B"]["seconds"]})
    if _utc(receipt["finished_at_utc"]) < previous_finish:
        raise ValueError("timing receipt predates its actual trial completions")
    summary = summarize_paired_timing(pairs, confidence=CONFIDENCE, target_half_width_seconds=HALF_WIDTH,
                                     planned_confirmation_repetitions=plan["fixed_n"] if plan["phase"] == "confirmation" else None)
    full = len(pairs) == plan["fixed_n"] and not failures
    values = summary[plan["phase"]]
    if plan["phase"] == "exploratory":
        result = "pilot_ready" if full else "evidence_insufficient"
        required = fixed_n(values["standard_deviation_seconds"]) if full else None
    else:
        required = plan["fixed_n"]
        pilot = read_json(_pointer(plan["pilot"]["receipt"], plan_path.parent))
        pilot_trials = {str(_pointer(leg["trial"], plan_path.parent)) for pair in pilot["pairs"] for leg in pair["legs"].values() if leg.get("trial")}
        if {str(path) for path in seen} & pilot_trials:
            raise ValueError("exploratory measurements cannot be reused for independent confirmation")
        diagnostic_record = read_json(_pointer(diagnostics, receipt_path.parent)) if diagnostics is not None else {}
        resolved = (diagnostic_record.get("plan_sha256") == sha(plan_path)
                    and diagnostic_record.get("receipt_sha256") == sha(receipt_path)
                    and all(diagnostic_record.get(key) == "resolved" for key in ("independence", "normal_approximation", "order_and_drift")))
        result = ("timing_thresholds_met" if full and resolved and values["half_width_seconds"] <= HALF_WIDTH
                  and values["interval"]["lower"] >= SAVING else "evidence_insufficient")
    return {"schema": SCHEMA, "plan": identity(plan_path), "receipt": identity(receipt_path), "status": result,
            "statistics": summary, "required_fixed_n": required, "attempted_pairs": len(pairs), "expected_pairs": plan["fixed_n"],
            "failed_or_unknown_pairs": failures, "missing_pair_ids": [row["pair_id"] for row in plan["pairs"][len(pairs):]],
            "native_evidence": evidence, "diagnostics": diagnostics, "additional_quality_seeds": 0,
            "measurements": measurements,
            "recipe_confirmation": "not_decided_here_quality_severe_delivery_gates_required"}
