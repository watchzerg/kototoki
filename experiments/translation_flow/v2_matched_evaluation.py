"""Exact matched-workload input audit and accepted-judgment reuse, offline.

The validation preregistration, old universal control and new matched control
have distinct identities. Audit exports hashes only. Reuse requires complete
input bytes and verified accepted transport; changed inputs remain fresh jobs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from types import ModuleType
from typing import Any

from experiments.translation_eval import runner as e
from experiments.translation_judge import runner as j
from experiments.translation_judge.integrity import inside, _resolved_path
from . import v2_evaluation as v
from . import v2_prepare as p
from . import v2_universal_review as u

VALIDATION_VERSION = "matched-workload-validation-v1"
SCOPE_VERSION = "matched-control-evaluation-scope-v1"
IMPORT_VERSION = "matched-judgment-import-v1"
AUDIT_VERSION = "matched-evaluation-input-audit-v1"
COMPONENTS = ("packet_bytes", "prompt_bytes", "rendered_prompt", "schema_bytes", "settings_bytes", "task_bytes", "transport_contract")
PROMOTION_RECEIPT_SHA256 = "bd592f8dd67e6342749f7b0db2f493453a576276bfe8b81945bb90c5d1345a00"
ARCHIVABLE_DEPENDENCIES = {"experiments/translation_flow/v2_prepare.py", "experiments/translation_flow/v2_recipes.py"}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _disjoint(target: Path, donor: Path) -> None:
    if target == donor or target.is_relative_to(donor) or donor.is_relative_to(target):
        raise ValueError("matched target and donor must be disjoint")


def _native_text_bytes(value: str) -> bytes:
    # Match Path.write_text(..., encoding="utf-8") in the native transport.
    return value.replace("\n", os.linesep).encode("utf-8")


def render_material(packet_bytes: bytes, prompt_bytes: bytes, *,
                    adjudication: bool = False, dispute_bytes: bytes | None = None,
                    settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure reconstruction of exact run_job stdin/schema/settings/fingerprint bytes.

    Raw packet/prompt bytes stay separate: whitespace/BOM changes cannot become
    equal merely because parsed values or a transport fingerprint agree.
    """
    packet = e.parse(packet_bytes.decode("utf-8-sig"))
    prompt = prompt_bytes.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    prompt += "\nUse only the supplied packet. Do not use tools, files, memory, external knowledge, or any other conversation.\nPACKET:\n"
    prompt += json.dumps(packet, ensure_ascii=False)
    if adjudication:
        if dispute_bytes is None:
            raise ValueError("adjudication material requires an actual dispute")
        dispute = e.parse(dispute_bytes.decode("utf-8-sig"))
        prompt += "\nADJUDICATION:\n" + json.dumps({key: dispute[key] for key in ("judgments", "instruction")}, ensure_ascii=False)
    elif dispute_bytes is not None:
        raise ValueError("non-adjudication material cannot contain a dispute")
    requested = settings if settings is not None else {"model": j.MODEL, "effort": j.EFFORT,
        "overrides": j.OVERRIDES, "disabled_features": j.DISABLED_FEATURES}
    schema = j.response_schema(adjudication)
    settings_bytes = json.dumps(requested, sort_keys=True, ensure_ascii=False).encode("utf-8")
    task_bytes = json.dumps({"prompt": prompt, "schema": schema, **requested},
                            sort_keys=True, ensure_ascii=False).encode("utf-8")
    fingerprint = _hash(task_bytes)
    return {"packet_bytes": packet_bytes, "prompt_bytes": prompt_bytes,
            "rendered_prompt": prompt.encode("utf-8"), "prompt_file_bytes": _native_text_bytes(prompt),
            "schema_bytes": _native_text_bytes(json.dumps(schema, ensure_ascii=False, indent=2) + "\n"),
            "settings_bytes": settings_bytes, "task_bytes": task_bytes, "transport_contract": task_bytes,
            "dispute_bytes": dispute_bytes, "fingerprint": fingerprint,
            "dispute_fingerprint": fingerprint.encode("ascii") if adjudication else None}


def material_metadata(material: dict[str, Any]) -> dict[str, Any]:
    result = {name + "_sha256": _hash(material[name]) for name in COMPONENTS}
    result["fingerprint"] = material["fingerprint"]
    result["dispute_bytes_sha256"] = _hash(material["dispute_bytes"]) if material.get("dispute_bytes") is not None else None
    return result


def _material(root: Path, descriptor: dict[str, Any]) -> dict[str, Any]:
    phase = descriptor["job_id"].split("/")[0]
    return render_material(inside(root, root / descriptor["packet"]).read_bytes(),
                           inside(root, root / descriptor["prompt"]).read_bytes(),
                           adjudication=phase == "adjudication",
                           dispute_bytes=inside(root, root / descriptor["dispute"]).read_bytes()
                           if phase == "adjudication" else None)


def resolve_protocol_dependency(pointer: dict[str, Any], protocol_path: Path) -> dict[str, Any]:
    """Validate live bytes or the exact immutable promotion-bound original archive."""
    original = _resolved_path(Path(pointer["path"]))
    if not Path(pointer["path"]).is_absolute():
        raise ValueError("protocol dependency must use an absolute frozen pointer")
    if original.is_file() and e.sha(original) == pointer["sha256"]:
        return {"original_pointer": dict(pointer), "resolved_pointer": u.identity(original), "binding": "original_live_bytes"}
    receipt_path = protocol_path.parent / "runtime-promotion-r2.json"
    if not receipt_path.is_file() or e.sha(receipt_path) != PROMOTION_RECEIPT_SHA256:
        raise ValueError("protocol dependency lacks immutable promotion archive authority")
    receipt = e.read_json(receipt_path)
    manifest_path = u._pointer(receipt["promotion_manifest"], receipt_path.parent)
    manifest = e.read_json(manifest_path)
    workspace = _resolved_path(Path(manifest["original_root"]))
    base = receipt_path.parent.parent
    expected_stage = _resolved_path(base / "implementation-staging/next-protocols-v1")
    expected_backup = _resolved_path(base / "implementation-staging/pre-promotion-r2-backup")
    if (receipt.get("schema") != "root-runtime-promotion-v1"
            or manifest.get("schema") != "source-only-promotion-review-v1"
            or manifest_path != expected_stage / "promotion-manifest-r2.json"
            or _resolved_path(Path(manifest["stage_root"])) != expected_stage
            or _resolved_path(Path(receipt["backup"])) != expected_backup
            or receipt.get("files") != manifest.get("files")):
        raise ValueError("protocol archive promotion authority structure changed")
    staging_path = expected_stage / "staging-manifest.json"
    if e.sha(staging_path) != manifest["staging_manifest_sha256"]:
        raise ValueError("protocol archive staging authority changed")
    staging = e.read_json(staging_path)
    if (staging.get("schema") != "source-only-implementation-staging-v1"
            or _resolved_path(Path(staging["original_root"])) != workspace
            or _resolved_path(Path(staging["stage_root"])) != expected_stage):
        raise ValueError("protocol archive staging scope changed")
    relative = original.relative_to(workspace).as_posix()
    rows = [row for row in receipt["files"] if row.get("path") == relative]
    staged = [row for row in staging["files"] if row.get("path") == relative]
    if (relative not in ARCHIVABLE_DEPENDENCIES or len(rows) != 1 or len(staged) != 1
            or rows[0].get("change_type") != "modified"
            or rows[0].get("original_matches_baseline") is not True
            or rows[0].get("original_baseline_sha256") != pointer["sha256"]
            or rows[0].get("current_original_sha256") != pointer["sha256"]
            or staged[0].get("sha256") != pointer["sha256"]):
        raise ValueError("protocol dependency is not the exact bound promoted original")
    archive = inside(expected_backup, expected_backup / relative)
    if e.sha(archive) != pointer["sha256"]:
        raise ValueError("protocol dependency archived original bytes changed")
    live = u.identity(original) if original.is_file() else None
    promoted = {"path": str(original), "sha256": rows[0]["staged_sha256"]}
    return {"original_pointer": dict(pointer), "resolved_pointer": u.identity(archive),
            "binding": "immutable_promotion_original_archive", "live_pointer": live,
            "promoted_pointer": promoted, "live_matches_promoted": live == promoted,
            "archive_authority": u.identity(receipt_path), "promotion_manifest": u.identity(manifest_path),
            "staging_manifest": u.identity(staging_path)}


def _protocol(pointer: Path | dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    path = u._pointer(pointer, Path.cwd()) if isinstance(pointer, dict) else _resolved_path(pointer)
    value = e.read_json(path)
    ids, seeds = value.get("window_ids"), value.get("generation_seeds")
    if (value.get("version") != VALIDATION_VERSION
            or value.get("state") != "frozen_before_any_candidate_quality_inspection"
            or value.get("timing_declaration", {}).get("candidate_quality_results_inspected") is not False
            or not isinstance(ids, list) or not ids or any(not isinstance(wid, str) for wid in ids)
            or len(ids) != len(set(ids)) or value.get("matched_workload", {}).get("windows") != len(ids)
            or not isinstance(seeds, list) or not seeds or any(type(seed) is not int for seed in seeds)
            or len(seeds) != len(set(seeds))):
        raise ValueError("matched validation protocol lacks its frozen explicit workload")
    validation = deepcopy(value)
    resolutions = [resolve_protocol_dependency(item, path) for item in value.get("offline_audit_implementation", [])]
    validation["offline_audit_implementation"] = [item["resolved_pointer"] for item in resolutions]
    u._pointers(validation, path.parent)
    identity = {**u.identity(path), "version": value["version"], "state": value["state"]}
    if isinstance(pointer, dict) and any(pointer.get(name) != identity[name]
                                       for name in ("version", "state") if name in pointer):
        raise ValueError("validation declaration differs from frozen protocol bytes")
    value["_protocol_dependency_resolution"] = {"dependencies": resolutions,
        "source_gate_authority": next((item for item in resolutions
            if Path(item["original_pointer"]["path"]).name == "v2_prepare.py"), None)}
    value["_protocol_path"] = str(path)
    return identity, value


def load_protocol_module(pointer: dict[str, Any], protocol_path: Path) -> tuple[ModuleType, dict[str, Any]]:
    """Load exact validated implementation bytes without replacing live modules."""
    resolution = resolve_protocol_dependency(pointer, protocol_path)
    path = u._pointer(resolution["resolved_pointer"], protocol_path.parent)
    original = Path(pointer["path"])
    module = ModuleType("experiments.translation_flow._matched_frozen_" + original.stem)
    module.__package__ = "experiments.translation_demo" if original.parent.name == "translation_demo" else "experiments.translation_flow"
    module.__file__ = str(path)
    data = path.read_bytes()
    if _hash(data) != pointer["sha256"]:
        raise ValueError("protocol module changed before execution")
    exec(compile(data, str(path), "exec"), module.__dict__)
    return module, resolution


def scope_metadata(pointer: Path | dict[str, Any], validation_protocol: Path | dict[str, Any]) -> dict[str, Any]:
    """Require a distinct frozen matched denominator; never relabel universal96."""
    protocol, planned = _protocol(validation_protocol)
    path = u._pointer(pointer, Path.cwd()) if isinstance(pointer, dict) else _resolved_path(pointer)
    value = e.read_json(path)
    if (path == Path(protocol["path"]) or value.get("version") != SCOPE_VERSION
            or value.get("state") != "frozen_before_candidate_quality_inspection"
            or value.get("selection") != "explicit_matched_windows"
            or value.get("window_ids") != planned["window_ids"]
            or value.get("expected_windows_per_seed") != len(planned["window_ids"])
            or value.get("generation_seeds") != planned["generation_seeds"]
            or value.get("timing_declaration", {}).get("candidate_quality_results_inspected") is not False
            or u._pointer(value["validation_protocol"], path.parent) != Path(protocol["path"])
            or value["validation_protocol"]["sha256"] != protocol["sha256"]):
        raise ValueError("matched control needs a distinct prior-inspection frozen explicit scope")
    for name in ("source_manifest", "source_freeze", "decision_policy"):
        if (u._pointer(value[name], path.parent) != u._pointer(planned[name], Path(protocol["path"]).parent)
                or value[name]["sha256"] != planned[name]["sha256"]):
            raise ValueError("matched scope changes preregistered source/policy identity")
    universal = u.scope_metadata(value["universal_review_policy"])
    policy = e.read_json(Path(universal["path"]))
    for name in ("source_manifest", "source_freeze", "reference_freeze", "decision_policy"):
        if (u._pointer(value[name], path.parent) != u._pointer(policy[name], Path(universal["path"]).parent)
                or value[name]["sha256"] != policy[name]["sha256"]):
            raise ValueError("matched scope changes universal source/reference policy identity")
    u._pointers(value, path.parent)
    result = {**u.identity(path), **{name: value[name] for name in ("version", "state", "selection")},
              "expected_windows_per_seed": value["expected_windows_per_seed"]}
    if isinstance(pointer, dict) and any(pointer.get(name) != result[name] for name in result
                                       if name not in {"path", "sha256"} and name in pointer):
        raise ValueError("matched scope declaration differs from frozen bytes")
    return result


def _donor(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for path in root.rglob("*"):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("matched donor inventory rejects symlinks and junctions")
    seal = e.read_json(root / "finalization-manifest.json")
    u._inventory(root, seal)
    run = e.read_json(root / "run.json")
    u._prepared(root, run)
    u._bound_scope(run, u.scope_metadata(run["universal_review_scope"]), root)
    u._pointers(run.get("judgment_import", {}), root)
    expected = e.load_jsonl(root / "expected.jsonl")
    accepted = {}
    for descriptor in u._donor_jobs(root, expected):
        ledger, state = u._accepted(root, descriptor)
        if (state.get("requested_model"), state.get("requested_effort")) != (j.MODEL, j.EFFORT):
            raise ValueError("accepted donor requested settings differ from transport contract")
        material = _material(root, descriptor)
        if material["fingerprint"] != state["fingerprint"]:
            raise ValueError("accepted donor task fingerprint differs from exact rendered input")
        raw = inside(ledger.parent, Path(state["accepted_raw_response"]))
        actual_schema, actual_prompt = raw.parent / "schema.json", raw.parent / "prompt.txt"
        # These are the bytes actually written for the accepted invocation.
        material["schema_bytes"] = actual_schema.read_bytes()
        material["accepted_prompt_file_bytes"] = actual_prompt.read_bytes()
        accepted[descriptor["job_id"]] = {"job": descriptor, "ledger": ledger, "state": state,
                                             "material": material}
    u._inventory(root, seal)
    return run, seal, accepted


def _qualification(run: dict[str, Any], root: Path, protocol: dict[str, Any], *,
                   allow_legacy: bool = False) -> dict[str, Any]:
    """Recover legacy qualification only from previously hash-bound evidence."""
    contract = run["p_flow_contract"]
    canonical = u._pointer(protocol["source_freeze"], root)
    expected = u.identity(canonical)
    explicit = contract.get("source_qualification_freeze")
    evidence = []
    if explicit is not None:
        if u._pointer(explicit, root) != canonical or explicit["sha256"] != expected["sha256"]:
            raise ValueError("source qualification differs from preregistered frozen identity")
        evidence.append({"binding": "explicit_contract", "pointer": u.identity(canonical)})
    elif allow_legacy:
        for alias, candidate in contract.get("candidate_artifacts", {}).items():
            for index, pointer in enumerate(candidate.get("artifacts", [])):
                if (isinstance(pointer, dict) and isinstance(pointer.get("path"), str)
                        and Path(pointer["path"]).is_absolute()
                        and _resolved_path(Path(pointer["path"])) == canonical):
                    if u._pointer(pointer, root) != canonical or pointer["sha256"] != expected["sha256"]:
                        raise ValueError("legacy source qualification artifact identity changed")
                    evidence.append({"binding": "legacy_recorded_candidate_artifact", "candidate_alias": alias,
                                     "artifact_index": index, "pointer": u.identity(canonical)})
        for name, digest in run.get("frozen_artifact_sha256", {}).items():
            if digest == expected["sha256"]:
                path = inside(root, root / name)
                if e.sha(path) != digest:
                    raise ValueError("legacy frozen source qualification metadata changed")
                evidence.append({"binding": "legacy_frozen_metadata_artifact", "pointer": u.identity(path)})
    if not evidence:
        raise ValueError("source qualification lacks hash-bound donor preparation evidence")
    source = u._pointer(contract["source_manifest"], root)
    if canonical != _resolved_path(source.parent / "freeze-manifest.json"):
        raise ValueError("source qualification is outside its frozen source authority")
    freeze = e.read_json(canonical)
    actual = contract["reference_freeze"]
    approved = freeze.get("reference_qualification", {})
    if (freeze.get("state") != "source_frozen_reference_qualified"
            or approved.get("version") != v.REFERENCE_VERSION
            or approved.get("state") != "frozen_double_fresh_reference_review"
            or approved.get("inference_allowed") is not True
            or not isinstance(approved.get("path"), str) or not Path(approved["path"]).is_absolute()
            or u._pointer(approved, canonical.parent) != u._pointer(actual, root)
            or approved.get("sha256") != actual["sha256"]
            or actual.get("corpus_version") != v.REFERENCE_VERSION
            or actual.get("state") != approved["state"]):
        raise ValueError("source qualification reference identity differs from accepted evaluation freeze")
    scenes = u._pointer(protocol["source_scenes"], root)
    gate = p
    authority = protocol.get("_protocol_dependency_resolution", {}).get("source_gate_authority")
    if authority is not None:
        gate, checked = load_protocol_module(authority["original_pointer"], Path(protocol["_protocol_path"]))
        if checked != authority:
            raise ValueError("source gate dependency resolution changed before qualification")
    gate.verify_source_freeze(source, scenes, protocol.get("matched_workload", {}).get("split", "screen-a"), stage="screening")
    return {"canonical_source_qualification_freeze": expected, "evidence": evidence,
            "accepted_reference_qualification": approved,
            "original_source_freeze": freeze["original_source_freeze"], "state": freeze["state"]}


def _target(root: Path, protocol: dict[str, Any], donor_run: dict[str, Any], donor_root: Path
            ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    run = e.read_json(root / "run.json")
    u._prepared(root, run)
    rows = e.load_jsonl(root / "expected.jsonl")
    wanted = protocol["window_ids"]
    aliases = set(run["candidates"])
    if (not aliases or aliases != set(donor_run["candidates"])
            or len(rows) != len(wanted) * len(aliases)
            or {(row["candidate_alias"], row["window_id"]) for row in rows} !=
            {(alias, wid) for alias in aliases for wid in wanted}
            or run.get("p_flow_contract", {}).get("window_ids") != wanted):
        raise ValueError("target must retain the exact explicit matched expected scope")
    for name, scope_name in (("source_manifest", "source_manifest"), ("source_qualification_freeze", "source_freeze")):
        target = run["p_flow_contract"][name]
        if target["sha256"] != protocol[scope_name]["sha256"]:
            raise ValueError("matched target source differs from preregistered authority")
    for name in ("source_manifest", "references", "reference_freeze"):
        if run["p_flow_contract"][name] != donor_run["p_flow_contract"][name]:
            raise ValueError("matched evaluation changes frozen source/reference identity")
    target_qualification = _qualification(run, root, protocol)
    donor_qualification = _qualification(donor_run, donor_root, protocol, allow_legacy=True)
    if target_qualification["canonical_source_qualification_freeze"] != donor_qualification["canonical_source_qualification_freeze"]:
        raise ValueError("matched evaluation changes canonical qualified source identity")
    for alias, candidate in run["candidates"].items():
        original = donor_run["candidates"][alias]
        if candidate.get("seed") not in protocol["generation_seeds"] or candidate.get("seed") != original.get("seed"):
            raise ValueError("matched target and donor must retain the same translation seed")
        if set(candidate.get("delivery_window_ids", [])) != set(wanted):
            raise ValueError("matched generation delivery must be exact selected workload, not mixed full96")
        if candidate.get("original_generation_cost_identity") == original.get("original_generation_cost_identity"):
            raise ValueError("matched control must identify its new generation, separate from donor generation")
        controls = [row for row in protocol["seed_controls"] if row["seed"] == candidate["seed"]]
        if len(controls) != 1 or controls[0]["old_original_run"] != original["original_generation_cost_identity"]:
            raise ValueError("donor generation differs from preregistered historical seed control")
    return run, rows, {"target": target_qualification, "donor": donor_qualification}


def _comparison(target: dict[str, Any], donor: dict[str, Any]) -> dict[str, Any]:
    equal = {name: target[name] == donor[name] for name in COMPONENTS}
    equal["fingerprint"] = target["fingerprint"] == donor["fingerprint"]
    equal["dispute_bytes"] = target.get("dispute_bytes") == donor.get("dispute_bytes")
    equal["accepted_prompt_file_bytes"] = target["prompt_file_bytes"] == donor["accepted_prompt_file_bytes"]
    return {"target_material": material_metadata(target), "donor_material": material_metadata(donor),
            "equal_components": equal, "eligible": all(equal.values()),
            "reason": "complete_input_bytes_identical" if all(equal.values()) else "changed_complete_input_bytes"}


def audit_complete_inputs(prepared_target: Path, donor_root: Path,
                          validation_protocol_path: Path | dict[str, Any]) -> dict[str, Any]:
    """Audit before scope/import/dispatch; return only hashes and eligibility."""
    target, donor_root = _resolved_path(prepared_target), _resolved_path(donor_root)
    _disjoint(target, donor_root)
    protocol_pointer, protocol = _protocol(validation_protocol_path)
    donor_run, seal, accepted = _donor(donor_root)
    run, rows, qualification = _target(target, protocol, donor_run, donor_root)
    donor_expected = e.load_jsonl(donor_root / "expected.jsonl")
    donor_rows = {(row["candidate_alias"], row["window_id"]): row for row in donor_expected}
    historical_windows = protocol.get("historical_workload", {}).get("windows")
    if historical_windows is not None and len(donor_expected) != historical_windows * len(donor_run["candidates"]):
        raise ValueError("donor expected scope differs from declared historical workload")
    records = []
    for row in rows:
        for phase in u.PHASES:
            descriptor = e.job(row, phase)
            found = accepted.get(descriptor["job_id"])
            item = {"phase": phase, "job_id": descriptor["job_id"], "candidate_alias": row["candidate_alias"],
                    "window_id": row["window_id"], "eligible": False}
            if row["structural_status"] in e.NO_JUDGE_STATUSES:
                old = donor_rows.get((row["candidate_alias"], row["window_id"]))
                same = old is not None and old["structural_status"] == row["structural_status"]
                if old is not None and phase != "adjudication":
                    target_material = _material(target, descriptor)
                    old_material = _material(donor_root, e.job(old, phase))
                    same = same and all(target_material[name] == old_material[name] for name in COMPONENTS)
                    item.update(target_material=material_metadata(target_material), donor_material=material_metadata(old_material))
                item.update(decision="no_judge", reason=row["structural_status"],
                            mechanical_input_equal=same, donor_structural_status=old["structural_status"] if old else None)
            elif phase == "adjudication":
                descriptor["dispute"] = f"disputes/{row['candidate_alias']}/{row['window_id']}.json"
                if found is None:
                    item.update(decision="no_donor_adjudication", reason="bounded_by_target_disagreement")
                elif not (target / descriptor["dispute"]).is_file():
                    item.update(decision="pending_target_dispute", reason="requires_actual_same_dispute_bytes")
                else:
                    item.update(_comparison(_material(target, descriptor), found["material"]))
                    item["decision"] = "eligible" if item["eligible"] else "fresh_required"
            elif found is None:
                item.update(decision="fresh_required", reason="no_accepted_donor_phase")
            else:
                item.update(_comparison(_material(target, descriptor), found["material"]))
                item["decision"] = "eligible" if item["eligible"] else "fresh_required"
            records.append(item)
    primary_review = [row for row in records if row["phase"] in {"primary", "review"} and row["decision"] != "no_judge"]
    relevant = [row for row in records if row["decision"] not in {"no_judge", "no_donor_adjudication"}]
    mechanical_equal = all(row["mechanical_input_equal"] for row in records if row["decision"] == "no_judge")
    u._inventory(donor_root, seal)
    u._prepared(target, run)
    pending_adjudication = any(row["decision"] == "pending_target_dispute" for row in records)
    return {"version": AUDIT_VERSION, "validation_protocol": protocol_pointer,
            "target_root": str(target), "donor_root": str(donor_root), "target_run": u.identity(target / "run.json"),
            "donor_run": u.identity(donor_root / "run.json"),
            "donor_finalization": u.identity(donor_root / "finalization-manifest.json"),
            "window_ids": protocol["window_ids"], "expected_records": len(rows),
            "donor_expected_records": len(donor_expected),
            "source_qualification_bindings": qualification,
            "protocol_dependency_resolution": protocol["_protocol_dependency_resolution"],
            "target_generation": {alias: value["original_generation_cost_identity"] for alias, value in run["candidates"].items()},
            "donor_generation": {alias: value["original_generation_cost_identity"] for alias, value in donor_run["candidates"].items()},
            "records": records, "all_primary_review_inputs_identical": all(row["eligible"] for row in primary_review),
            "mechanical_no_judge_inputs_identical": mechanical_equal,
            "all_complete_inputs_identical": None if pending_adjudication else mechanical_equal and all(row["eligible"] for row in relevant),
            "complete_input_status": "incomplete_adjudication_material" if pending_adjudication else "complete",
            "new_network_calls": 0, "new_generated_samples": 0,
            "settings_evidence": "exact transport fingerprint serialization; accepted schema/prompt files compared as raw bytes"}


def _freeze_material(root: Path, descriptor: dict[str, Any], material: dict[str, Any]) -> list[dict[str, str]]:
    directory = inside(root, root / "matched-evaluation-material" / descriptor["job_id"])
    directory.mkdir(parents=True, exist_ok=True)
    files = []
    for name in COMPONENTS + ("prompt_file_bytes", "dispute_bytes", "dispute_fingerprint"):
        if material.get(name) is None:
            continue
        path = directory / (name + ".bin")
        if path.exists() and path.read_bytes() != material[name]:
            raise ValueError("matched frozen material changed")
        if not path.exists():
            path.write_bytes(material[name])
        files.append({"path": path.relative_to(root).as_posix(), "sha256": e.sha(path)})
    return files


def _import(root: Path, donor: Path, descriptor: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    ledger, state = u._accepted(donor, item["job"])
    canonical = inside(donor, Path(state["response"]))
    target_ledger = inside(root, root / "judge-execution" / descriptor["job_id"] / "job.json")
    if target_ledger.parent.exists() or inside(root, root / descriptor["response"]).exists():
        raise ValueError("matched judgment import cannot replace a target phase that already started")
    target_ledger.parent.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ledger.parent, target_ledger.parent)
    target_response = inside(root, root / descriptor["response"])
    target_response.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(canonical, target_response)
    copied = root / "matched-judgment-donor" / "ledgers" / descriptor["job_id"] / "job.json"
    copied.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ledger, copied)
    relocated = deepcopy(state)
    for name in u.RELOCATED_FIELDS:
        source = inside(donor if name == "response" else ledger.parent, Path(state[name]))
        relocated[name] = str(root / source.relative_to(donor))
    e.dump(target_ledger, relocated)
    u._accepted(root, descriptor)
    return {"phase": descriptor["job_id"].split("/")[0], "job_id": descriptor["job_id"],
            "candidate_alias": descriptor["candidate_alias"], "window_id": descriptor["window_id"],
            "fingerprint": state["fingerprint"], "donor_ledger": u.identity(ledger),
            "original_ledger_copy": u.identity(copied), "new_ledger": u.identity(target_ledger),
            "accepted_raw_response_sha256": state["accepted_raw_response_sha256"],
            "response_sha256": state["response_sha256"], "accepted_canonical_snapshot_sha256": state["response_sha256"],
            "files": [{"path": p.relative_to(root).as_posix(), "sha256": e.sha(p)}
                      for p in sorted(target_ledger.parent.rglob("*")) if p.is_file()]}


def _publish(root: Path, run: dict[str, Any], proof: dict[str, Any]) -> None:
    counts = Counter(row["phase"] for row in proof["imported_jobs"])
    proof["imported_phase_counts"] = {phase: counts[phase] for phase in u.PHASES}
    path = root / "matched-judgment-import.json"
    e.dump(path, proof)
    run["matched_judgment_import"] = {"version": IMPORT_VERSION, "donor_root": proof["donor_root"],
        "donor_run": proof["donor_run"], "donor_finalization": proof["donor_finalization"], "manifest": u.identity(path)}
    run["matched_validation_provenance"] = proof["validation_protocol"]
    frozen = run.setdefault("frozen_artifact_sha256", {})
    for path in (path, root / "matched-control-scope.json", root / "matched-validation-protocol.json",
                 root / "matched-evaluation-adapter.py", root / "matched-complete-input-audit.json",
                 root / "matched-pre-import-run.json"):
        frozen[path.relative_to(root).as_posix()] = e.sha(path)
    for entry in proof["material_files"]:
        frozen[entry["path"]] = entry["sha256"]
    for entry in proof["imported_jobs"]:
        copied = Path(entry["original_ledger_copy"]["path"])
        frozen[copied.relative_to(root).as_posix()] = entry["original_ledger_copy"]["sha256"]
    e.dump(root / "run.json", run)


def import_prepared(prepared_target: Path, donor_root: Path, *, validation_protocol_path: Path | dict[str, Any],
                    matched_scope_path: Path | dict[str, Any], universal_scope_path: Path | dict[str, Any]) -> dict[str, Any]:
    """Freeze the new explicit scope, then reuse eligible primary/review phases."""
    root, donor = _resolved_path(prepared_target), _resolved_path(donor_root)
    if (root / "judge-execution").exists() or any((root / phase).exists() for phase in u.PHASES):
        raise ValueError("matched scope/import must precede any target judgment started")
    if (root / "finalization-manifest.json").exists() or (root / "matched-judgment-import.json").exists():
        raise ValueError("matched import requires a new unsealed target")
    scope = scope_metadata(matched_scope_path, validation_protocol_path)
    universal = u.scope_metadata(universal_scope_path)
    declared = e.read_json(Path(scope["path"]))
    if u.scope_metadata(declared["universal_review_policy"]) != universal:
        raise ValueError("matched scope binds a different universal review policy")
    audit = audit_complete_inputs(root, donor, validation_protocol_path)
    donor_run, seal, accepted = _donor(donor)
    run = e.read_json(root / "run.json")
    snapshot = root / "matched-pre-import-run.json"
    shutil.copyfile(root / "run.json", snapshot)
    audit["observed_target_run_path"] = audit["target_run"]["path"]
    audit["target_run"] = u.identity(snapshot)
    u.apply_universal_scope(root, universal)
    run = e.read_json(root / "run.json")
    run["matched_control_scope"] = scope
    e.dump(root / "matched-complete-input-audit.json", audit)
    shutil.copyfile(Path(scope["path"]), root / "matched-control-scope.json")
    shutil.copyfile(Path(audit["validation_protocol"]["path"]), root / "matched-validation-protocol.json")
    shutil.copyfile(Path(__file__), root / "matched-evaluation-adapter.py")
    rows = {(row["candidate_alias"], row["window_id"]): row for row in e.load_jsonl(root / "expected.jsonl")}
    proof = {"version": IMPORT_VERSION, "target_root": str(root), "donor_root": str(donor),
             "target_pre_import_run": audit["target_run"], "donor_run": audit["donor_run"],
             "donor_finalization": audit["donor_finalization"], "donor_inventory_sha256": audit["donor_finalization"]["sha256"],
             "validation_protocol": audit["validation_protocol"], "matched_control_scope": scope,
             "universal_review_scope": universal, "window_ids": audit["window_ids"],
             "expected_records": audit["expected_records"], "target_generation": audit["target_generation"],
             "donor_expected_records": audit["donor_expected_records"],
             "source_identity": {name: run["p_flow_contract"][name] for name in (
                 "source_manifest", "source_inputs", "references", "reference_freeze", "source_qualification_freeze")},
             "source_qualification_bindings": audit["source_qualification_bindings"],
             "protocol_dependency_resolution": audit["protocol_dependency_resolution"],
             "donor_generation": audit["donor_generation"], "complete_input_audit": u.identity(root / "matched-complete-input-audit.json"),
             "ledger_path_relocation_allowlist": list(u.RELOCATED_FIELDS), "imported_jobs": [], "material_files": [],
             "new_network_calls": 0, "new_inference_calls": 0, "new_generated_samples": 0,
             "cost_attribution": "donor_accepted_judgment_once_target_generation_separate",
             "fresh_required_phase_counts": {}, "adjudication_audits": [], "adjudication_material_complete": False}
    for record in audit["records"]:
        if record["phase"] == "adjudication" or record["decision"] == "no_judge":
            continue
        descriptor = e.job(rows[record["candidate_alias"], record["window_id"]], record["phase"])
        proof["material_files"].extend(_freeze_material(root, descriptor, _material(root, descriptor)))
        if record["eligible"]:
            proof["imported_jobs"].append(_import(root, donor, descriptor, accepted[record["job_id"]]))
    proof["fresh_required_phase_counts"] = {phase: sum(record["phase"] == phase and record["decision"] == "fresh_required"
                                                       for record in audit["records"]) for phase in ("primary", "review")}
    proof["fresh_required_phase_counts"]["adjudication"] = 0
    _publish(root, run, proof)
    u._prepared(root, e.read_json(root / "run.json"))
    u._inventory(donor, seal)
    if u.identity(donor / "run.json") != audit["donor_run"] or u.identity(donor / "finalization-manifest.json") != audit["donor_finalization"]:
        raise ValueError("donor identity changed during matched import")
    return proof


def prepare_matched(source_manifest_path: Path, source_inputs_path: Path, references_path: Path,
                    candidate_deliveries: dict[str, Path], output: Path, *, reference_freeze_path: Path,
                    window_ids: list[str], donor_root: Path, validation_protocol_path: Path | dict[str, Any],
                    matched_scope_path: Path | dict[str, Any], universal_scope_path: Path | dict[str, Any],
                    split: str = "dev") -> dict[str, Any]:
    """Prepare a genuine new matched-generation root, then import eligible calls."""
    _, protocol = _protocol(validation_protocol_path)
    scope_metadata(matched_scope_path, validation_protocol_path)
    _disjoint(_resolved_path(output), _resolved_path(donor_root))
    if window_ids != protocol["window_ids"]:
        raise ValueError("matched prepare selection differs from frozen exact window order")
    v.prepare(source_manifest_path, source_inputs_path, references_path, candidate_deliveries, output,
              reference_freeze_path=reference_freeze_path, window_ids=window_ids, split=split)
    return import_prepared(output, donor_root, validation_protocol_path=validation_protocol_path,
                           matched_scope_path=matched_scope_path, universal_scope_path=universal_scope_path)


def import_adjudication(root: Path, donor_root: Path) -> dict[str, Any]:
    """Reuse an adjudication only after native finalize creates an actual dispute."""
    root, donor = _resolved_path(root), _resolved_path(donor_root)
    if (root / "finalization-manifest.json").exists():
        raise ValueError("sealed matched evaluation is immutable")
    run = e.read_json(root / "run.json")
    u._prepared(root, run)
    envelope = run["matched_judgment_import"]
    path = u._pointer(envelope["manifest"], root)
    proof = e.read_json(path)
    if (inside(root, path) != root / "matched-judgment-import.json" or proof.get("version") != IMPORT_VERSION
            or _resolved_path(Path(proof["target_root"])) != root
            or any(envelope.get(name) != proof.get(name) for name in ("donor_root", "donor_run", "donor_finalization"))):
        raise ValueError("matched import envelope differs from frozen manifest identity")
    scope_metadata(run["matched_control_scope"], proof["validation_protocol"])
    if _resolved_path(Path(proof["donor_root"])) != donor:
        raise ValueError("adjudication donor differs from frozen matched import")
    _, seal, accepted = _donor(donor)
    if u.identity(donor / "run.json") != proof["donor_run"] or u.identity(donor / "finalization-manifest.json") != proof["donor_finalization"]:
        raise ValueError("adjudication donor identity changed")
    # Actual disputes are complete only after every judgeable pair is accepted.
    for filename in ("jobs.jsonl", "jobs-review.jsonl"):
        for descriptor in e.load_jsonl(root / filename):
            u._accepted(root, descriptor)
    imported = {row["job_id"] for row in proof["imported_jobs"]}
    decisions = []
    for descriptor in e.load_jsonl(root / "jobs-adjudication.jsonl"):
        if descriptor["job_id"] in imported:
            u._accepted(root, descriptor)
            continue
        material = _material(root, descriptor)
        proof["material_files"].extend(_freeze_material(root, descriptor, material))
        found = accepted.get(descriptor["job_id"])
        decision = {"job_id": descriptor["job_id"], "phase": "adjudication", "eligible": False,
                    "decision": "fresh_required", "reason": "no_accepted_donor_adjudication"}
        if found:
            decision.update(_comparison(material, found["material"]))
            decision["decision"] = "eligible" if decision["eligible"] else "fresh_required"
        decisions.append(decision)
        target_ledger = inside(root, root / "judge-execution" / descriptor["job_id"] / "job.json")
        if target_ledger.exists():
            state = e.read_json(target_ledger)
            if state.get("status") == "succeeded":
                u._accepted(root, descriptor)
            decision["decision"] = "target_already_started"
            decision["reason"] = "keep_fresh_target_phase_identity_without_reclassification"
        elif decision["eligible"]:
            proof["imported_jobs"].append(_import(root, donor, descriptor, found))
    audits = {row["job_id"]: row for row in proof["adjudication_audits"] + decisions}
    actual_ids = {row["job_id"] for row in e.load_jsonl(root / "jobs-adjudication.jsonl")}
    proof["adjudication_audits"] = [audits[key] for key in sorted(actual_ids)]
    proof["material_files"] = list({row["path"]: row for row in proof["material_files"]}.values())
    imported_ids = {row["job_id"] for row in proof["imported_jobs"]}
    required = e.load_jsonl(root / "jobs-adjudication.jsonl")
    proof["fresh_required_phase_counts"]["adjudication"] = sum(row["job_id"] not in imported_ids for row in required)
    proof["adjudication_material_complete"] = True
    _publish(root, run, proof)
    u._inventory(donor, seal)
    return proof


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "import-adjudication"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--validation-protocol", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    if args.command == "audit":
        if args.validation_protocol is None or args.receipt is None:
            parser.error("audit requires --validation-protocol and --receipt")
        if _resolved_path(args.receipt).is_relative_to(_resolved_path(args.donor)):
            parser.error("audit receipt must not modify the immutable donor")
        e.dump(args.receipt, audit_complete_inputs(args.output, args.donor, args.validation_protocol))
    else:
        import_adjudication(args.output, args.donor)


if __name__ == "__main__":
    main()
