"""Prospective fresh confirmation evaluation bridge; no unseal or dispatch.

Custody pins must come from an external registry. Metadata guards precede all
source/reference packet preparation. Native generation lineage and complete
queue identities remain separate from fresh primary/review judgment costs.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from experiments.translation_eval import runner as e
from experiments.translation_judge import runner as j
from experiments.translation_judge.integrity import inside, _resolved_path
from . import v2_confirmation as c
from . import v2_confirmation_dispatch as d
from . import v2_delivery as delivery
from . import v2_evaluation as v
from . import v2_recipes as recipes
from . import v2_universal_review as u

EVIDENCE_SCHEMA = "hy30-confirmation-native-generation-evidence-v1"
FORBIDDEN_LINEAGE = {"universal_review_scope", "judgment_import", "matched_judgment_import",
                     "matched_control_scope", "matched_validation_provenance", "derivation"}


def authority_metadata(dispatch_authority: dict[str, str], generation_receipt: dict[str, str], *,
                       registered_lock_sha256: str, registered_unseal_sha256: str,
                       expected_policy_sha256: str = c.POLICY_SHA256) -> dict[str, Any]:
    """Authenticate a whole prospective queue using separately registered pins."""
    pins = {"registered_lock_sha256": registered_lock_sha256,
            "registered_unseal_sha256": registered_unseal_sha256,
            "expected_policy_sha256": expected_policy_sha256}
    plan = d.validate_dispatch_plan(dispatch_authority, **pins)
    receipt = d.validate_dispatch_receipt(generation_receipt, **pins)
    if receipt["plan"] != c._pointer(dispatch_authority):
        raise ValueError("Fresh evaluation requires the exact ordered terminal generation queue")
    authority = plan["confirmation_dispatch_authority"]
    lock = c.validate_lock(authority["lock"], expected_policy_sha256=expected_policy_sha256)
    contract = c._json(Path(lock["evaluation_contract"]["path"]))
    expected_prompt = (e.PROMPT + "\n").replace("\n", os.linesep).encode("utf-8")
    if (contract["profile"] != e.PROFILE or (j.MODEL, j.EFFORT) != ("gpt-6.1-sol", "high")
            or Path(c._pointer(contract["prompt"])["path"]).read_bytes() != expected_prompt):
        raise ValueError("Confirmation prompt/profile differs from the frozen native judge contract")
    return {"fresh_confirmation_scope": lock["evaluation_contract"],
            "confirmation_authority": {"lock": authority["lock"], "unseal": authority["unseal"],
                "evaluation_contract": lock["evaluation_contract"], "dispatch_authority": c._pointer(dispatch_authority),
                "source_scope_sha256": lock["source_scope_sha256"]},
            "confirmation_generation_receipt": c._pointer(generation_receipt),
            "source_scope": lock["source_scope"], "lock": lock, "plan": plan, "receipt": receipt}


def _selection(source: dict[str, Any]) -> list[str]:
    manifest = e.read_json(Path(source["manifest"]["path"]))
    rows = manifest.get("windows")
    if (not isinstance(rows, list) or len(rows) != 48
            or any(row.get("split") != "confirmation" or row.get("selection_type") != "representative" for row in rows)):
        raise ValueError("Confirmation manifest must contain exactly48 representative confirmation windows")
    ids = [e.safe_id(row["id"]) for row in rows]
    if len(set(ids)) != 48:
        raise ValueError("Confirmation window identities must be distinct")
    return ids


def _seconds(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def validate_source_preparation_metadata(locked_plan: dict[str, str], options_pointer: dict[str, str],
                                         source: dict[str, Any], *, seed: int, stage: str) -> dict[str, Any]:
    """Bind native auxiliary metadata without decoding proposals or raw responses.

    This intake proof does not validate preparation semantics or promote a
    qualification workload to screening/confirmation or formal timing evidence.
    """
    from .v2_timing import read_metadata_fields
    plan_pointer, artifact_pointer = c._pointer(locked_plan), c._pointer(options_pointer)
    fields = {"schema", "mode", "stage", "source", "scene_ids", "settings", "protocol"}
    plan = read_metadata_fields(Path(plan_pointer["path"]), fields)
    artifact = read_metadata_fields(Path(artifact_pointer["path"]), fields | {
        "complete", "session_plan_sha256", "session_plan_path", "cache_reset", "cost_artifacts"})
    c.validate_scope(stage, source["split"], source["role"])
    freeze = read_metadata_fields(Path(c._pointer(source["freeze"])["path"]), {"version", "role", "state"})
    if (freeze.get("version") != "hy30-flow-v2-source-v1" or freeze.get("role") != source["role"]
            or freeze.get("state") not in {"source_frozen_reference_unreviewed", "source_frozen_reference_qualified"}
            or (stage != "qualification" and freeze.get("state") != "source_frozen_reference_qualified")):
        raise ValueError("Preparation metadata source role/freeze state differs from the declared stage")
    for value, base in ((plan, Path(plan_pointer["path"]).parent), (artifact, Path(artifact_pointer["path"]).parent)):
        for key in ("manifest", "scenes"):
            given = {"path": value["source"][key], "sha256": value["source"][key + "_sha256"]}
            if c._pointer(given, base) != c._pointer(source[key]):
                raise ValueError("Preparation manifest/scenes differ from the locked source")
        if value["source"].get("freeze_sha256") != c._pointer(source["freeze"])["sha256"]:
            raise ValueError("Preparation source freeze differs from the locked source")
    if (plan.get("schema") not in {"hy30-source-preparation-session-v2", "hy30-source-preparation-session-v3"}
            or artifact.get("schema") not in {"hy30-source-preparation-options-v2", "hy30-source-preparation-options-v3"}
            or plan["schema"][-2:] != artifact["schema"][-2:] or plan.get("mode") not in {"terms", "background"}
            or artifact.get("complete") is not True or type(seed) is not int
            or plan.get("stage") != stage or artifact.get("stage") != stage
            or plan.get("settings", {}).get("seed") != seed
            or artifact.get("session_plan_sha256") != plan_pointer["sha256"]
            or any(artifact.get(key) != plan.get(key) for key in ("mode", "stage", "scene_ids", "settings", "protocol"))
            or (plan["schema"].endswith("-v3") and c._pointer({"path": artifact.get("session_plan_path"),
                "sha256": artifact["session_plan_sha256"]}) != plan_pointer)):
        raise ValueError("Native preparation metadata differs from the exact locked plan/stage/seed")
    cache = artifact.get("cache_reset", {})
    if (cache.get("verified") is not True or cache.get("first_response_checked") is not True
            or type(cache.get("first_response_cache_n")) is not int or cache["first_response_cache_n"] != 0):
        raise ValueError("Preparation intake lacks measured fresh-cache metadata")
    return {"locked_plan": plan_pointer, "artifact": artifact_pointer, "stage": stage, "seed": seed,
            "mode": plan["mode"], "protocol": plan.get("protocol"), "scene_ids": plan["scene_ids"],
            "source": {key: c._pointer(source[key]) for key in ("manifest", "scenes", "freeze")},
            "cost_artifacts": artifact.get("cost_artifacts", {}),
            "metadata_only": True, "preparation_semantics_validated": False, "formal_timing_eligible": False}


def _native_source_preparation(card: dict[str, Any], source: dict[str, Any], root: Path,
                                run: dict[str, Any], packed: dict[str, Any], report: dict[str, Any]) -> dict[str, Any] | None:
    spec = card.get("source_preparation")
    if spec is None:
        if run.get("source_preparation") is not None or packed.get("source_preparation") is not None or report.get("source_preparation") is not None:
            raise ValueError("Native generation used preparation absent from its locked card")
        return None
    from .v2_timing import read_metadata_fields
    plan_pointer = c._pointer({"path": spec["plan"], "sha256": spec["sha256"]})
    auxiliary = report.get("source_preparation", {})
    artifact = c._pointer(auxiliary["artifact"])
    if (auxiliary.get("plan_sha256") != plan_pointer["sha256"]
            or _resolved_path(Path(auxiliary.get("plan_path", ""))) != Path(plan_pointer["path"])
            or Path(artifact["path"]) != root / "source-preparation/runtime-run/translation/preparation-options.json"
            or auxiliary.get("runtime_exit_code") != 0
            or c._pointer(run["source_preparation"]["artifact"]) != artifact
            or run["source_preparation"] != run["settings"].get("source_preparation")
            or c._pointer(packed["source_preparation"]) != artifact):
        raise ValueError("Consumed auxiliary artifact differs from the locked native trial")
    proof = validate_source_preparation_metadata(plan_pointer, artifact, source,
        seed=card["prepare"]["seed"], stage="confirmation")
    command_path = inside(root, root / "source-preparation/command-completion.json")
    command = read_metadata_fields(command_path, {"schema", "worker", "plan_sha256", "returncode", "command_seconds"})
    worker_path = Path(artifact["path"]).parent / "worker-completion.json"
    worker = read_metadata_fields(worker_path, {"complete", "artifact", "protocol"})
    if (command.get("schema") != "hy30-flow-command-v2" or command.get("worker") != "experiments.translation_flow.v2_source_preparation"
            or command.get("returncode") != 0 or command.get("plan_sha256") != plan_pointer["sha256"]
            or not _seconds(command.get("command_seconds")) or worker.get("complete") is not True
            or c._pointer(worker["artifact"]) != artifact or worker.get("protocol") != proof["protocol"]):
        raise ValueError("Native preparation completion/cost metadata differs from its artifact")
    proof.update(command=c.pointer(command_path), worker_completion=c.pointer(worker_path),
                 command_seconds=command["command_seconds"], cost_attribution="native_auxiliary_command_once_per_trial")
    return proof


def _locked_workload(card: dict[str, Any], alias: str, item: dict[str, Any], packed: dict[str, Any],
                     inputs: list[dict[str, Any]], source_scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind explicit candidate budgets/footprints without changing legacy C0 defaults."""
    settings = card["prepare"]
    budget = settings.get("n_predict", 4096)
    if type(budget) is not int or budget < 1 or (settings.get("recipe", "c0") == "c0" and budget != 4096):
        raise ValueError("Locked native output budget is invalid or changes C0 output4096")
    fixed = {"label": settings["recipe_id"], "recipe": settings.get("recipe", "c0"), "seed": settings["seed"],
             "sampling": "official", "cache_prompt": True, "n_predict": budget, "max_attempts": 2}
    defaults = {"target_size": 5, "context_before": 1, "context_after": 1, "token_target": None,
                "common_context": False, "offset": 0}
    packing = {key: settings.get(key, value) for key, value in defaults.items()}
    block = settings.get("common_context_block_size")
    baseline = alias == "C0-official-cached"
    if baseline and (budget != 4096 or packing != defaults or block is not None):
        raise ValueError("Locked C0 must retain output4096 and the original baseline packing")
    policy = None
    if block is not None:
        if (type(block) is not int or block < 1 or type(packing["target_size"]) is not int
                or packing["target_size"] < 1 or block % packing["target_size"]
                or packing["common_context"] is not False or packing["token_target"] is not None
                or type(packing["offset"]) is not int or packing["offset"] != 0):
            raise ValueError("Locked common source block is incompatible with fixed target packing")
        packing["common_context_block_size"] = block
        policy = {"protocol": "hy30-common-source-macroblock-v1", "origin_position": 0,
            "block_size": block, "target_size": packing["target_size"], "outer_previous": packing["context_before"],
            "outer_next": packing["context_after"], "tail_block": "clipped-to-frozen-scene",
            "target_packing": "unchanged-scene-origin", "capacity_verification": "native-full-prompt-output-reservation-guard",
            "source_truncation": False}
    options = settings.get("options") or {}
    if ({"n_predict", "common_context_block_size"} & options.keys()
            or "common_context_block_size" in item
            or any(type(item.get(key)) is not type(value) or item.get(key) != value for key, value in fixed.items())
            or c._hash(packed.get("packing")) != c._hash(packing)
            or (policy is None and "source_visibility_policy" in packed)
            or (policy is not None and c._hash(packed.get("source_visibility_policy")) != c._hash(policy))
            or any(item.get(key, default) != options.get(key, default) for key, default in (
                ("terms", []), ("background", []), ("style", "neutral"), ("review", False), ("partition_grammar_limits", None)))):
        raise ValueError("Actual native recipe/options/packing differ from the complete locked card")
    if policy is None:
        if any("common_source_visibility" in batch for batch in packed["batches"]):
            raise ValueError("Native common source footprint was absent from its locked card")
        return options
    scenes = {row.get("scene_id", row["id"]): row for row in source_scenes}
    if [row["id"] for row in inputs] != [batch["id"] for batch in packed["batches"]]:
        raise ValueError("Native common source inputs differ from the packed batch order")
    for batch, request in zip(packed["batches"], inputs, strict=True):
        scene = scenes[batch["scene_id"]]
        cues, ids = scene["context"], scene["translate_ids"]
        start, stop = batch["start_position"], batch["end_position"]
        if (type(start) is not int or type(stop) is not int or start < 0 or start % packing["target_size"]
                or stop != min(len(ids), start + packing["target_size"])):
            raise ValueError("Native common source target packing differs from locked scene origin")
        block_start, block_stop = start // block * block, min(len(ids), (start // block + 1) * block)
        left, right = max(0, block_start - packing["context_before"]), min(len(ids), block_stop + packing["context_after"])
        footprint = batch.get("common_source_visibility", {})
        expected = {"protocol": policy["protocol"], "block_start_position": block_start, "block_end_position": block_stop,
                    "context_start_position": left, "context_end_position": right, "visible_ids": ids[left:right],
                    "full_scene_visible": left == 0 and right == len(ids), "visible_source_cue_count": right - left}
        if (set(footprint) != set(expected) | {"visible_source_text_token_count"}
                or any(type(footprint.get(key)) is not type(value) or footprint.get(key) != value for key, value in expected.items())
                or footprint["visible_source_text_token_count"] is not None and
                    (type(footprint["visible_source_text_token_count"]) is not int or footprint["visible_source_text_token_count"] < 0)
                or batch["target_ids"] != ids[start:stop] or batch["readonly_ids"] != ids[left:start] + ids[stop:right]
                or request["translate_ids"] != ids[start:stop]
                or request["context"] != [{"id": cue["id"], "text": cue["text"]} for cue in cues[left:right]]):
            raise ValueError("Native common source footprint differs from exact locked source bytes")
    return options


def _native_generation(job: dict[str, Any], source: dict[str, Any], window_ids: list[str]) -> dict[str, Any]:
    """Collect native managed-session/empty-cache metadata, never repair artifacts."""
    root = _resolved_path(Path(job["output"]))
    card = c._json(Path(job["card"]["path"]))
    recipe_id = card["prepare"]["recipe_id"]
    run_dir = root / "execution/runtime-run/translation" / recipe_id
    session_root = run_dir.parent
    paths = {"trial_start": root / "trial-start.json", "trial_completion": root / "trial-completion.json",
             "original_run": run_dir / "run.json", "generation_inputs": run_dir / "inputs.jsonl",
             "packed_mapping": root / "prepared/packed-mapping.json", "session_plan": session_root / "session-plan.json",
             "prepared_session_plan": root / "prepared/session-plan.json", "session": session_root / "session.json",
             "checkpoint": session_root / "checkpoint.json", "native_command": root / "execution/command-completion.json",
             "delivery": root / "delivery/delivery.json"}
    identities = {name: c.pointer(inside(root, path)) for name, path in paths.items()}
    run, session, plan, checkpoint, command = (e.read_json(paths[name]) for name in (
        "original_run", "session", "session_plan", "checkpoint", "native_command"))
    packed, projected = e.read_json(paths["packed_mapping"]), e.read_json(paths["delivery"])
    start, finish = e.read_json(paths["trial_start"]), e.read_json(paths["trial_completion"])
    if (identities["trial_completion"] != job["native_trial"]
            or start.get("card_sha256") != job["card"]["sha256"] or start.get("card") != card
            or c._utc(start["started_at_utc"]) < c._utc(job["accepted_at_utc"])
            or finish.get("started_at_utc") != start["started_at_utc"]
            or finish.get("total_flow_seconds") != job["native_total_flow_seconds"]
            or FORBIDDEN_LINEAGE & (run.keys() | projected.keys())
            or plan.get("resume") is not None or session.get("resume") is not None
            or session.get("performance_valid_for_fresh_flow") is not True
            or plan.get("stage") != "confirmation" or plan.get("experiment_identity", {}).get("split") != "confirmation"
            or plan["experiment_identity"].get("seed") != job["seed"]
            or plan["experiment_identity"].get("recipe_id") != recipe_id
            or plan["experiment_identity"].get("source_manifest_sha256") != source["manifest"]["sha256"]
            or identities["prepared_session_plan"]["sha256"] != identities["session_plan"]["sha256"]
            or c._utc(session["created_at_utc"]) < c._utc(job["accepted_at_utc"])
            or packed.get("seed") != job["seed"] or packed.get("recipe_id") != recipe_id
            or packed.get("schema") != "hy30-flow-packed-v2"
            or c._pointer(packed["source_manifest"]) != source["manifest"]
            or c._pointer(packed["source_scenes"]) != source["scenes"]
            or [row["id"] for row in packed["windows"]] != window_ids
            or projected.get("seed") != job["seed"] or projected.get("recipe_id") != recipe_id
            or c._pointer(projected["source_manifest"]) != source["manifest"]
            or c._pointer(projected["packed_mapping"]) != identities["packed_mapping"]
            or _resolved_path(Path(projected["run"])) != run_dir
            or run.get("input_sha256") != identities["generation_inputs"]["sha256"]
            or run.get("settings", {}).get("input_sha256") != identities["generation_inputs"]["sha256"]
            or run.get("packed_mapping_sha256") != identities["packed_mapping"]["sha256"]
            or run.get("source_manifest_sha256") != source["manifest"]["sha256"]
            or run.get("expected_window_ids") != [row["id"] for row in packed["batches"]]
            or command.get("schema") != "hy30-flow-command-v2" or command.get("returncode") != 0
            or command.get("worker") != "experiments.translation_flow.v2_worker"
            or command.get("plan_sha256") != identities["session_plan"]["sha256"]
            or c._utc(command["started_at_utc"]) < c._utc(start["started_at_utc"])
            or c._utc(command["finished_at_utc"]) > c._utc(finish["finished_at_utc"])
            or not _seconds(command.get("command_seconds"))):
        raise ValueError("Generation is not a fresh native locked confirmation slot")
    delivery._session_transport(run_dir, run)
    item = run["settings"]
    options = _locked_workload(card, job["candidate_alias"], item, packed, e.load_jsonl(paths["generation_inputs"]),
                              e.load_jsonl(Path(source["scenes"]["path"])) if card["prepare"].get("common_context_block_size") is not None else [])
    engine = session["identity"]["engine"]
    template = session["identity"].get("template_sha256")
    if (not isinstance(template, str) or len(template) != 64 or any(char not in "0123456789abcdef" for char in template)):
        raise ValueError("Native runtime requires exact model template hash evidence")
    cache = checkpoint.get("cache_reset", {})
    if (session["identity"]["asset"]["sha256"] != c.OFFICIAL_C0_RUNTIME["asset_sha256"]
            or engine.get("context_size") != 8192 or engine.get("gpu_layers_requested") != 99
            or cache.get("method") != "fresh-managed-server" or cache.get("verified") is not True
            or cache.get("first_response_checked") is not True
            or type(cache.get("first_response_cache_n")) is not int or cache["first_response_cache_n"] != 0
            or type(engine.get("server_pid")) is not int or engine["server_pid"] <= 0
            or cache.get("server_pid") != engine["server_pid"]
            or not isinstance(engine.get("command"), list)
            or "-np" not in engine["command"] or engine["command"][engine["command"].index("-np") + 1:][:1] != ["1"]):
        raise ValueError("Native managed GPU/empty-cache confirmation evidence is missing")
    exchange = inside(session_root / "transport", Path(cache["exchange"]))
    attempts = [attempt for row in e.load_jsonl(run_dir / "ledger.jsonl") for attempt in row.get("attempts", [])
                if attempt.get("completion_dispatched") is True]
    first = next((attempt for attempt in attempts
                  if attempt.get("completion_dispatched") is True), None)
    if first is None or _resolved_path(Path(first["original_response"])) != exchange:
        raise ValueError("First native completion is not bound to measured empty-cache evidence")
    request_contract = {key: value for key, value in recipes.completion_request(item, [1]).items() if key != "prompt"}
    if any(type(attempt.get("request", {}).get(key)) is not type(value) or attempt.get("request", {}).get(key) != value
           for attempt in attempts for key, value in request_contract.items()):
        raise ValueError("Actual completion settings differ from the locked official native workload")
    delivery._trace_artifacts(exchange, "original_response", first)
    response = e.read_json(exchange / "response.raw")
    if type(response.get("timings", {}).get("cache_n")) is not int or response["timings"]["cache_n"] != 0:
        raise ValueError("First raw completion actually reused cache or lacks evidence")
    identities["first_completion_response"] = c.pointer(exchange / "response.raw")
    identities["first_completion_request"] = c.pointer(exchange / "request.json")
    snapshots = []
    for relative, sha256 in run["code_sha256"].items():
        path = inside(session_root / "source", session_root / "source" / relative)
        identity = c.pointer(path)
        if identity["sha256"] != sha256:
            raise ValueError("Executed native implementation snapshot changed")
        snapshots.append({"relative_path": relative, **identity})
    workspace = Path(__file__).resolve().parents[2]
    for pointer in card["implementation_identity"]:
        original = Path(c._pointer(pointer)["path"])
        relative = original.relative_to(workspace).as_posix()
        if run["code_sha256"].get(relative) != pointer["sha256"]:
            raise ValueError("Executed native code differs from the complete locked card")
    auxiliary_proof = _native_source_preparation(card, source, root, run, packed, finish)
    return {"job_id": job["job_id"], "candidate_alias": job["candidate_alias"], "seed": job["seed"],
            "card": job["card"], **identities, "implementation_snapshots": snapshots,
            "native_expected_batch_ids": run["expected_window_ids"],
            "shared_runtime": {"asset_sha256": session["identity"]["asset"]["sha256"], "template_sha256": template,
                "engine": {key: engine[key] for key in ("build", "cuda", "executable_sha256", "custom_runtime_identity_sha256",
                    "context_size", "gpu_layers_requested", "threads", "threads_batch", "kv_type_k", "kv_type_v", "prompt_cache_ram_mib") if key in engine}},
            "locked_configuration": {"recipe": item["recipe"], "sampling": item["sampling"], "cache_prompt": item["cache_prompt"],
                "n_predict": item["n_predict"], "max_attempts": item["max_attempts"], "packing": packed["packing"], "options": options},
            "completion_settings": request_contract,
            "source_preparation": auxiliary_proof,
            "window_ids": window_ids, "cache_reset": {key: cache[key] for key in (
                "method", "server_pid", "verified", "first_response_checked", "first_response_cache_n")},
            "native_total_flow_seconds": job["native_total_flow_seconds"], "native_command_seconds": command["command_seconds"],
            "cost_attribution": "original_native_trial_and_session_once"}


def collect_generation_evidence(authority: dict[str, Any]) -> dict[str, Any]:
    """Inspect the complete authenticated queue after the metadata authority gate."""
    ids = _selection(authority["source_scope"])
    generations = []
    for job in authority["receipt"]["jobs"]:
        common = {"job_id": job["job_id"], "candidate_alias": job["candidate_alias"], "seed": job["seed"],
                  "status": job["status"], "attempted": job["attempted"], "native_complete": job["status"] == "complete"}
        if job["status"] == "complete":
            generations.append({**_native_generation(job, authority["source_scope"], ids), **common})
        else:
            generations.append({**common, "card": job["card"], "window_ids": ids,
                "original_run": None, "native_trial": job.get("native_trial"),
                "native_total_flow_seconds": job.get("native_total_flow_seconds"),
                "runner_seconds": job.get("runner_seconds"), "native_freshness_proven": False,
                "quality_status": "not_run" if job["status"] == "not_run" else "setup_failed"})
    complete = [row for row in generations if row["native_complete"]]
    if len({row["original_run"]["path"] for row in complete}) != len(complete):
        raise ValueError("Fresh slots cannot share an original generation identity")
    if complete and any(row["shared_runtime"] != complete[0]["shared_runtime"] for row in complete):
        raise ValueError("Complete confirmation slots must share the exact compatible engine/model/template settings")
    return {"schema": EVIDENCE_SCHEMA, "dispatch_authority": authority["confirmation_authority"]["dispatch_authority"],
            "generation_receipt": authority["confirmation_generation_receipt"],
            "source_scope_sha256": authority["confirmation_authority"]["source_scope_sha256"],
            "window_ids": ids, "generation_seeds": list(c.SEEDS), "generations": generations,
            "expected_generation_jobs": len(generations), "complete_generation_jobs": len(complete),
            "terminal_accounting_complete": True, "all_fresh_native_generations": len(complete) == len(generations),
            "screening_judgment_import_permitted": False}


def _prepare_denominator(source_manifest: Path, source_inputs: Path, references: Path,
                         candidate_deliveries: dict[str, Path], output: Path, reference_freeze: Path,
                         evidence: dict[str, Any], slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Native schedules preserve failed slots without claiming a generation exists."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="confirmation-prepare-") as temporary:
        staging = Path(temporary)
        validated_run = None
        if candidate_deliveries:
            v.prepare(source_manifest, source_inputs, references, candidate_deliveries, staging / "validated",
                      reference_freeze_path=reference_freeze, split="test", window_ids=evidence["window_ids"])
            validated_run = e.read_json(staging / "validated/run.json")
            contract = validated_run["p_flow_contract"]
        else:
            contract, _, _ = v.source_contract(source_manifest, source_inputs, references, reference_freeze, evidence["window_ids"])
            contract["candidate_artifacts"] = {}
        requests = e.indexed(e.load_jsonl(source_inputs))
        refs = e.indexed(e.load_jsonl(references))
        e.dump_jsonl(staging / "inputs.jsonl", [requests[wid] for wid in evidence["window_ids"]])
        e.dump_jsonl(staging / "references.jsonl", [refs[wid] for wid in evidence["window_ids"]])
        predictions, ledgers, schedules = {}, {}, {}
        for slot in slots:
            alias = slot["candidate_alias"]
            for name, collection in (("results", predictions), ("ledger", ledgers), ("schedule", schedules)):
                path = staging / alias / (name + ".jsonl")
                if slot["status"] == "complete":
                    rows = [{key: value for key, value in row.items() if key != "delivery_contract"}
                            for row in e.load_jsonl(candidate_deliveries[alias] / (name + ".jsonl"))]
                elif name == "schedule":
                    rows = [{"window_id": wid, "status": "not_run" if slot["status"] == "not_run" else "setup_failed",
                             "reason": "确认生成队列保留失败或未执行的锁定条目；没有完整 native generation 证据。"}
                            for wid in evidence["window_ids"]]
                else:
                    rows = []
                e.dump_jsonl(path, rows)
                collection[alias] = path
        e.prepare(staging / "inputs.jsonl", staging / "references.jsonl", predictions, output, split="test",
                  candidate_ledgers=ledgers, candidate_schedules=schedules, corpus_manifest=source_manifest)
        run = e.read_json(output / "run.json")
        for slot in slots:
            alias = slot["candidate_alias"]
            if slot["status"] == "complete":
                run["candidates"][alias] = validated_run["candidates"][alias]
                run["candidates"][alias].update(generation_attempt_status="complete", native_complete=True,
                    original_trial_attempt_identity=slot["native_trial"])
                shutil.copytree(staging / "validated/originals" / alias, output / "originals" / alias, dirs_exist_ok=True)
            else:
                meta = run["candidates"][alias]
                for name in ("results", "ledger", "schedule"):
                    path = output / "originals" / alias / (name + ".jsonl")
                    meta[name] = str(path.resolve())
                meta.update(seed=slot["seed"], original_generation_cost_identity=None,
                    recipe_id=c._json(Path(slot["card"]["path"]))["prepare"]["recipe_id"],
                    original_trial_attempt_identity=slot.get("native_trial"),
                    generation_attempt_status=slot["status"], native_complete=False,
                    delivery_contract=e.P_FLOW_CONTRACT, cost_attribution="attempted_native_cost_only_no_complete_generation_claim")
                contract["candidate_artifacts"][alias] = {"native_complete": False, "generation_attempt_status": slot["status"],
                    "seed": slot["seed"], "recipe_id": meta["recipe_id"],
                    "original_generation_cost_identity": None, "card": slot["card"], "native_trial": slot.get("native_trial")}
        expected = e.load_jsonl(output / "expected.jsonl")
        for row in expected:
            row.update(lane="P-flow", delivery_contract=e.P_FLOW_CONTRACT, judge_source_scope=v.SCOPE,
                scene_id=contract["window_mapping"][row["window_id"]]["scene_id"],
                source_mapping=contract["window_mapping"][row["window_id"]])
            packet = e.read_json(output / row["packet"])
            packet.update({key: row[key] for key in ("lane", "delivery_contract", "judge_source_scope", "scene_id", "source_mapping")})
            e.dump(output / row["packet"], packet)
        e.dump_jsonl(output / "expected.jsonl", expected)
        e.dump(output / "p-flow-scene-contract.json", contract)
        for name, path in (("inputs.jsonl", staging / "inputs.jsonl"), ("references.jsonl", staging / "references.jsonl"),
                ("reference-freeze.json", reference_freeze), ("source-qualification-freeze.json", Path(contract["source_qualification_freeze"]["path"]))):
            shutil.copyfile(path, output / name)
        run.update(lane="P-flow", split="confirmation", delivery_contract=e.P_FLOW_CONTRACT, p_flow_contract=contract,
            inputs=str(source_inputs.resolve()), inputs_sha256=e.sha(source_inputs),
            references=str(references.resolve()), references_sha256=e.sha(references),
            expected_sha256=e.sha(output / "expected.jsonl"),
            packet_sha256={row["packet"]: e.sha(output / row["packet"]) for row in expected},
            frozen_artifact_sha256={name: e.sha(output / name) for name in (
                "p-flow-scene-contract.json", "inputs.jsonl", "references.jsonl", "reference-freeze.json", "source-qualification-freeze.json")})
        e.dump(output / "run.json", run)
    return {"lane": "P-flow", "windows": 48, "candidates": len(slots), "expected_records": len(expected),
            "primary_jobs": len(e.load_jsonl(output / "jobs.jsonl"))}


def _no_imports(run: dict[str, Any], root: Path) -> None:
    if FORBIDDEN_LINEAGE & run.keys() or any((root / name).exists() for name in (
            "universal-judgment-import.json", "matched-judgment-import.json", "universal-review-scope.json")):
        raise ValueError("Fresh confirmation forbids screening scopes and judgment imports")


def prepare(source_manifest: Path, source_inputs: Path, references: Path, candidate_deliveries: dict[str, Path],
            output: Path, *, reference_freeze: Path, seed: int, dispatch_authority: dict[str, str],
            generation_receipt: dict[str, str], registered_lock_sha256: str, registered_unseal_sha256: str,
            expected_policy_sha256: str = c.POLICY_SHA256) -> dict[str, Any]:
    """Prepare a new complete per-seed confirmation root only after all guards."""
    if output.exists():
        raise FileExistsError("Confirmation evaluation root must be new")
    authority = authority_metadata(dispatch_authority, generation_receipt, registered_lock_sha256=registered_lock_sha256,
        registered_unseal_sha256=registered_unseal_sha256, expected_policy_sha256=expected_policy_sha256)
    source = authority["source_scope"]
    approved = c._json(Path(source["freeze"]["path"]))["reference_qualification"]
    if (type(seed) is not int or seed not in c.SEEDS or c.pointer(source_manifest) != source["manifest"]
            or c.pointer(reference_freeze) != {key: approved[key] for key in ("path", "sha256")}):
        raise ValueError("Evaluation source/reference/seed differs from fresh confirmation authority")
    jobs = [row for row in authority["receipt"]["jobs"] if row["seed"] == seed]
    complete_jobs = [row for row in jobs if row["status"] == "complete"]
    if set(candidate_deliveries) != {row["candidate_alias"] for row in complete_jobs}:
        raise ValueError("Every completed locked slot must use its fresh native delivery; failed slots remain scheduled unknown")
    if any(_resolved_path(candidate_deliveries[row["candidate_alias"]]) != Path(row["output"]) / "delivery" for row in complete_jobs):
        raise ValueError("Evaluation delivery is not the exact native frozen queue slot")
    evidence = collect_generation_evidence(authority)
    result = _prepare_denominator(source_manifest, source_inputs, references, candidate_deliveries, output,
                                  reference_freeze, evidence, jobs)
    run = e.read_json(output / "run.json")
    _no_imports(run, output)
    for row in evidence["generations"]:
        if row["seed"] == seed and run["candidates"][row["candidate_alias"]]["original_generation_cost_identity"] != row["original_run"]:
            raise ValueError("Prepared candidate changed its original native generation/cost identity")
    run.update({key: authority[key] for key in ("fresh_confirmation_scope", "confirmation_authority", "confirmation_generation_receipt")})
    run["confirmation_generation_seed"] = seed
    selection = {"scope_mode": c.SCOPE_MODE, "evaluation_contract": authority["fresh_confirmation_scope"],
                 "expected_sha256": run["expected_sha256"], "selected_ids": sorted(evidence["window_ids"]),
                 "selection": "all_expected_judgeable_windows_each_seed"}
    e.dump(output / "confirmation-review-selection.json", selection)
    e.dump(output / "confirmation-native-generation-evidence.json", evidence)
    run["confirmation_generation_evidence"] = c.pointer(output / "confirmation-native-generation-evidence.json")
    frozen = run["frozen_artifact_sha256"]
    for name in ("confirmation-review-selection.json", "confirmation-native-generation-evidence.json"):
        frozen[name] = e.sha(output / name)
    for name, pointer in {"confirmation-evaluation-contract.json": authority["fresh_confirmation_scope"],
            "confirmation-lock.json": authority["confirmation_authority"]["lock"],
            "confirmation-unseal.json": authority["confirmation_authority"]["unseal"],
            "confirmation-dispatch-plan.json": dispatch_authority,
            "confirmation-dispatch-receipt.json": generation_receipt}.items():
        shutil.copyfile(pointer["path"], output / name)
        frozen[name] = e.sha(output / name)
    shutil.copyfile(__file__, output / "confirmation-evaluation-adapter.py")
    frozen["confirmation-evaluation-adapter.py"] = e.sha(output / "confirmation-evaluation-adapter.py")
    e.dump(output / "run.json", run)
    return {**result, "scope_mode": c.SCOPE_MODE, "generation_seed": seed}


def validate_prepared(root: Path, *, registered_lock_sha256: str, registered_unseal_sha256: str,
                      expected_policy_sha256: str = c.POLICY_SHA256) -> dict[str, Any]:
    """Recheck external authority, immutable artifacts and fresh native identities."""
    root = _resolved_path(root)
    run = e.read_json(root / "run.json")
    _no_imports(run, root)
    u._prepared(root, run)
    authority = authority_metadata(run["confirmation_authority"]["dispatch_authority"], run["confirmation_generation_receipt"],
        registered_lock_sha256=registered_lock_sha256, registered_unseal_sha256=registered_unseal_sha256,
        expected_policy_sha256=expected_policy_sha256)
    if any(run[key] != authority[key] for key in ("confirmation_authority", "fresh_confirmation_scope", "confirmation_generation_receipt")):
        raise ValueError("Confirmation run authority was replaced")
    evidence_path = Path(c._pointer(run["confirmation_generation_evidence"])["path"])
    if evidence_path != root / "confirmation-native-generation-evidence.json":
        raise ValueError("Confirmation generation evidence must be the root's frozen proof")
    proof = e.read_json(evidence_path)
    if proof != collect_generation_evidence(authority):
        raise ValueError("Fresh native generation evidence changed")
    expected = e.load_jsonl(root / "expected.jsonl")
    seed = run["confirmation_generation_seed"]
    jobs = [row for row in authority["plan"]["jobs"] if row["seed"] == seed]
    if (seed not in c.SEEDS or run.get("split") != "confirmation" or run.get("profile") != e.PROFILE
            or set(run["candidates"]) != {row["candidate_alias"] for row in jobs}
            or {(row["candidate_alias"], row["window_id"]) for row in expected} !=
               {(row["candidate_alias"], wid) for row in jobs for wid in proof["window_ids"]}
            or len(expected) != 48 * len(jobs)
            or run["p_flow_contract"]["window_ids"] != proof["window_ids"]
            or e.read_json(root / "confirmation-review-selection.json")["selected_ids"] != sorted(proof["window_ids"])):
        raise ValueError("Prepared confirmation denominator/seed/review selection changed")
    for row in proof["generations"]:
        if row["seed"] == seed:
            meta = run["candidates"][row["candidate_alias"]]
            if (meta["original_generation_cost_identity"] != row["original_run"] or meta["seed"] != seed
                    or (row["native_complete"] and meta.get("cost_attribution") != "original_run_once")
                    or (not row["native_complete"] and (meta.get("native_complete") is not False
                        or meta.get("generation_attempt_status") != row["status"])) or FORBIDDEN_LINEAGE & meta.keys()):
                raise ValueError("Confirmation native generation/cost lineage was replaced")
    return run


def validate_metadata(root: Path, dispatch_authority: dict[str, str], **pins: Any) -> dict[str, Any]:
    """Comparator entry point: validate metadata before opening any final scores."""
    run = validate_prepared(root, **pins)
    if run["confirmation_authority"]["dispatch_authority"] != c._pointer(dispatch_authority):
        raise ValueError("Comparator authority differs from the externally registered queue")
    return {key: run[key] for key in ("fresh_confirmation_scope", "confirmation_authority",
        "confirmation_generation_receipt", "confirmation_generation_evidence", "confirmation_generation_seed")}


def review_coverage(root: Path) -> dict[str, Any]:
    """Count alias/window records; delivery zero and known score rules stay native."""
    expected = e.load_jsonl(root / "expected.jsonl")
    judgeable = [row for row in expected if row["structural_status"] not in e.NO_JUDGE_STATUSES]
    selection = e.read_json(root / "confirmation-review-selection.json")["selected_ids"]
    accepted = set()
    for row in judgeable:
        descriptor = e.job(row, "review")
        ledger = root / "judge-execution" / descriptor["job_id"] / "job.json"
        if ledger.is_file() and e.read_json(ledger).get("status") == "succeeded":
            _fresh_accepted(root, descriptor)
            accepted.add((row["candidate_alias"], row["window_id"]))
    final = e.load_jsonl(root / "final.jsonl") if (root / "final.jsonl").is_file() else []
    known = [row for row in final if row.get("status") != "delivery_zero"
             and (row.get("semantic") is not None or row.get("naturalness") is not None)]
    reviewed = sum((row["candidate_alias"], row["window_id"]) in accepted and row.get("reviewed") is True for row in known)
    selected_records = sum(row["window_id"] in selection for row in expected)
    return {"expected_records": len(expected), "judgeable_records": len(judgeable), "selected_records": selected_records,
            "accepted_review_records": len(accepted), "known_scored_reviewed_records": reviewed,
            "complete": selected_records == len(expected) and len(accepted) == len(judgeable) and reviewed == len(known)}


def _fresh_accepted(root: Path, descriptor: dict[str, Any]) -> None:
    _, state = u._accepted(root, descriptor)
    run = e.read_json(root / "run.json")
    receipt = c._json(Path(run["confirmation_generation_receipt"]["path"]))
    boundary = c._utc(receipt["finished_at_utc"])
    if (not state.get("attempts") or FORBIDDEN_LINEAGE & state.keys()
            or any(c._utc(attempt["started_at"]) < boundary
                   or c._utc(attempt["finished_at"]) < c._utc(attempt["started_at"])
                   for attempt in state["attempts"])):
        raise ValueError("Fresh confirmation judgment predates its terminal generation authority or carries import lineage")


def finalize(root: Path, **pins: Any) -> None:
    """Use native bounded adjudication with mandatory confirmation blind review."""
    validate_prepared(root, **pins)
    selection = e.read_json(root / "confirmation-review-selection.json")["selected_ids"]
    e.finalize(root, review_selection_override=selection)
    summary = e.read_json(root / "summary.json")
    summary["fresh_confirmation_scope"] = e.read_json(root / "run.json")["fresh_confirmation_scope"]
    summary["confirmation_review_coverage"] = review_coverage(root)
    e.dump(root / "summary.json", summary)


def seal_metadata(root: Path, **pins: Any) -> dict[str, Any]:
    """Return seal mirrors only; never seal, dispatch, unseal or import judgments."""
    run = validate_prepared(root, **pins)
    for filename in ("jobs.jsonl", "jobs-review.jsonl", "jobs-adjudication.jsonl"):
        for descriptor in e.load_jsonl(root / filename):
            _fresh_accepted(root, descriptor)
    coverage = review_coverage(root)
    if not coverage["complete"]:
        raise ValueError("Confirmation seal requires all expected blind review and known-score coverage")
    return {**{key: run[key] for key in ("fresh_confirmation_scope", "confirmation_authority",
        "confirmation_generation_receipt", "confirmation_generation_evidence")}, "confirmation_review_coverage": coverage,
        "candidate_identity": {alias: {key: value.get(key) for key in (
            "seed", "recipe_id", "original_generation_cost_identity", "original_trial_attempt_identity", "generation_attempt_status", "native_complete")}
            for alias, value in run["candidates"].items()}}
