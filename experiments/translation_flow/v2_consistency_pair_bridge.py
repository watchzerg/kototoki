"""Root-pinned mechanical bridge for retained C0 and preregistered F6/F7.

No dispatch, repair, archive execution, scorer or implicit material admission.
Historical execution and current approved diagnostic replay remain distinct.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import tempfile
from typing import Any

from experiments.translation_eval import runner as e
from experiments.translation_judge import integrity
from . import v2_consistency as c, v2_consistency_custody as custody
from . import v2_delivery as delivery, v2_unit_custody as unit
from . import v2_unit_main_proof as main

VERSION = "hy30-consistency-historical-pair-bridge-v1"
SOURCE_SCHEMA = "hy30-consistency-bridge-source-registration-v1"
PAIR_SCHEMA = "hy30-consistency-bridge-pair-authority-v1"
EXTERNAL_SCHEMA = "hy30-consistency-bridge-external-registration-v1"
UNKNOWN_SCHEMA = "hy30-consistency-unsupported-terminal-seal-v1"
CANDIDATE_SHA = "2834a429837df39674d6c13e46ea056b319430e43c3ef77e27b370bb1fb65c21"
GROUPS = {"F6-terms-proposals-max32": "terms", "F7-evidence-scene-card": "background"}
FROZEN = {
    "v2_consistency.py": "91105706247c769d49927cec995c5e729f21b9137f164e304dbbd1b09021a312",
    "v2_consistency_custody.py": "270596ca396f62620d3af2df6a6bccba033b0fdfe1cb9d376043d8e4baf4756e",
    "v2_consistency_runner.py": "b6aebc5a68e54d95012009b09d18dfc24d3edbf4b84b4a674d640237f2f735d8",
    "v2_consistency_prompt_contract.py": "757be87acb4e08ab30fbab6400ed51f105866be34ec5a75d8f44b25571119c03",
    "v2_unit_main_proof.py": "aec506822df7844377782759c06087e33ef9eaf095bace90bd57c7f9ee745c6d",
    "v2_unit_custody.py": "66c9c6415ab8e28122823011225427c60f4e72bba45d1f99c6c1dce4e748d8c6"}


def _read(pointer: dict[str, str], expected: str | None = None) -> Any:
    path = custody._pointer(pointer if expected is None else _pinned(pointer, expected))
    return integrity.strict_parse(path.read_text(encoding="utf-8-sig"))


def _pinned(pointer: dict[str, str], expected: str) -> dict[str, str]:
    if pointer.get("sha256") != expected:
        raise ValueError("Independent external pointer pin differs")
    return pointer


def implementation() -> dict[str, str]:
    root = Path(__file__).parent
    for name, digest in FROZEN.items():
        if integrity.sha((root / name).read_bytes()) != digest:
            raise ValueError("Immutable consistency/main boundary changed")
    return {**FROZEN, "bridge": integrity.sha(Path(__file__).read_bytes()),
            "candidate_native_helper": CANDIDATE_SHA}


def _candidate_helper():
    # Fixed code location and independent code pin; never an artifact-supplied
    # executable/module or historical snapshot substituted for live code.
    path = Path(__file__).resolve().parents[2] / ".local/translation-evaluation/hy30-flow-v2-20261008/methods/native_source_preparation_main_admission_v1.py"
    if integrity.sha(path.read_bytes()) != CANDIDATE_SHA:
        raise ValueError("Approved candidate native helper changed")
    spec = importlib.util.spec_from_file_location("kototoki_consistency_candidate_admission", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registration(source: dict, pair: dict, external: dict, source_sha: str,
                  pair_sha: str, external_sha: str) -> tuple[dict, dict, dict]:
    implementation()
    s, p, x = _read(source, source_sha), _read(pair, pair_sha), _read(external, external_sha)
    c._exact(s, {"schema", "state", "source_scope", "ordered_scene_ids", "generation_seeds"})
    c._exact(p, {"schema", "state", "source_registration", "implementation", "groups", "generation_seeds"})
    c._exact(x, {"schema", "state", "source_registration", "pair_authority", "implementation"})
    if (s["schema"] != SOURCE_SCHEMA or s["state"] != "source_only_scope_registered_for_consistency"
            or s["generation_seeds"] != list(c.SEEDS) or p["generation_seeds"] != list(c.SEEDS)
            or p["schema"] != PAIR_SCHEMA or p["state"] != "retained_control_and_preregistered_candidate"
            or p["source_registration"] != source or p["implementation"] != implementation()
            or x != {"schema": EXTERNAL_SCHEMA, "state": "root_registered_before_actual_consistency_calls",
                     "source_registration": source, "pair_authority": pair, "implementation": implementation()}):
        raise ValueError("Independent source/pair/bridge registration differs")
    scope = _read(s["source_scope"])
    if (scope.get("version") != "hy30-consistency-source-scope-v1" or scope.get("split") != "screen-a"
            or scope.get("state") != "frozen_before_consistency_quality" or scope.get("quality_inspected") is not False
            or scope.get("scene_ids") != s["ordered_scene_ids"] or not s["ordered_scene_ids"]
            or len(set(s["ordered_scene_ids"])) != len(s["ordered_scene_ids"])):
        raise ValueError("Original complete-scene source registration differs")
    if not isinstance(p["groups"], dict) or not p["groups"] or set(p["groups"]) - set(GROUPS):
        raise ValueError("Registered F6/F7 groups required")
    for gid, group in p["groups"].items():
        c._exact(group, {"mode", "control_seal", "control_external_registration", "candidate_authority", "slots"})
        if group["mode"] != GROUPS[gid] or [(r.get("seed"), r.get("role")) for r in group["slots"]] != [
                (seed, role) for seed in c.SEEDS for role in ("control", "candidate")]:
            raise ValueError("All ordered three-seed role slots required")
        for slot in group["slots"]:
            c._exact(slot, {"seed", "role", "kind", "evidence"})
            if slot["kind"] not in ({"main_proof"} if slot["role"] == "control" else {"native_proof", "unsupported_terminal"}):
                raise ValueError("Explicit original admission kind required")
            custody._pointer(slot["evidence"])
        for key in ("control_seal", "control_external_registration", "candidate_authority"):
            custody._pointer(group[key])
    return s, p, scope


def _normalized_main(card: dict, settings: dict | None) -> dict:
    recipe = custody._main_recipe(card)
    # Actual settings are checked against the original card by each native
    # verifier; slot-varying paths stay retained in provenance, not invariants.
    actual = None
    if settings is not None:
        actual = deepcopy(settings)
        for key in ("seed", "label", "inputs", "input_sha256", "packed_mapping_sha256", "source_preparation"):
            actual.pop(key, None)
        actual.update(custody._neutral_options({k: settings[k] for k in ("terms", "background", "style", "review") if k in settings}))
    return {"declared_execution": recipe, "actual_main": actual}


def _historical_material(proof: dict, intake: dict, originals: dict) -> dict:
    packed, run = intake["data"]["packed"], intake["data"]["run"]
    if packed["scene_ids"] != list(originals) or packed["scenes"] != list(originals.values()):
        raise ValueError("Historical complete source text/time/order differs")
    aggregate = delivery.aggregate(packed, intake["data"]["results"], intake["data"]["ledger"], intake["data"]["schedule"])
    card = _read(proof["card"])
    return {"aggregate": aggregate, "batches": _batches(packed), "card": card,
            "execution": _normalized_main(card, run["settings"]),
            "provenance": deepcopy(proof), "cost_identity": proof["original_generation_cost_identity"]}


def _batches(packed: dict) -> list[dict]:
    return [{"id": b["id"], "scene_id": b["scene_id"], "target_ids": list(b["target_ids"]),
             "readonly_ids": list(b.get("original_readonly_ids", b["readonly_ids"]))} for b in packed["batches"]]


def _candidate_material(proof: dict, loaded: dict, scope: dict, scenes: list[dict], originals: dict,
                        *, baseline_batches: list[dict] | None = None) -> dict:
    root, card = Path(proof["trial_root"]).resolve(), _read(proof["card"])
    terminal = _read(proof["original_trial_attempt_identity"])
    if not (root / "delivery/delivery.json").is_file() and (root / "execution").exists():
        raise ValueError("Canonical delivery unsupported; use independently sealed terminal UNKNOWN, never material success")
    if (loaded["proof"] != proof or loaded["scope"] != scope or loaded["scenes"] != scenes
            or any(loaded["originals"].get(sid) != row for sid, row in originals.items())
            or loaded["card"] != card or loaded["terminal"] != terminal):
        raise ValueError("Pinned candidate original-material view differs")
    slots, plan, current = loaded["source_preparation_slots"], loaded["source_preparation_plan"], loaded["main"]
    custody._source_preparation_contract(card, plan, current)
    if ([{k: v for k, v in row.items() if k != "raw_response"} for row in slots] != proof["source_preparation_slots"]
            or proof["scope"]["scene_ids"] != scope["scene_ids"]
            or bool(terminal["status"] == "complete") != proof["native_complete"]):
        raise ValueError("Candidate material differs from whole-native admission")
    if current["missing"]:
        # Accepted AUX-only failure has no started MAIN. Preserve the actual
        # AUX slots and original not_run delivery denominator, as frozen270.
        # The authenticated C0 target partition is only a source denominator;
        # it is never reported as an executed candidate partition.
        if (root / "execution").exists() or terminal["status"] == "complete" or baseline_batches is None:
            raise ValueError("Missing MAIN requires admitted absence and original source denominator")
        current = {**current, "aggregate": {"scenes": {
            scene["id"]: {uid: {"status": "not_run", "text": None, "batch_id": None}
                          for uid in scene["translate_ids"]} for scene in scenes}},
            "batches": deepcopy(baseline_batches), "projection": card["prepare"]["source_preparation_projection"],
            "exposure_proofs": {row["id"]: {"status": "missing", "options_sha256": None, "visibility_sha256": None}
                                for row in baseline_batches}, "settings": None}
    normalized_plan = deepcopy(plan)
    normalized_plan["settings"].pop("seed")
    return {"aggregate": current["aggregate"], "batches": current["batches"], "card": card,
            "preparations": slots, "preparation_recipe": normalized_plan,
            "projection": current["projection"], "exposure_proofs": current["exposure_proofs"],
            "execution": _normalized_main(card, current["settings"]),
            "provenance": {"whole_native": deepcopy(proof), "native_material": current["native"],
                           "card_provenance": loaded["card_provenance"],
                           "main_execution_not_started": current["missing"]},
            "cost_identity": proof["original_trial_attempt_identity"], "max_items": plan["settings"]["max_items"]}


def _unsupported(pointer: dict, *, gid: str, seed: int, auth: dict) -> dict:
    value = _read(pointer)
    c._exact(value, {"schema", "state", "candidate_group", "seed", "card", "trial_root", "trial_completion",
                     "retained_inventory", "reason", "original_cost_identity"})
    if (value["schema"] != UNKNOWN_SCHEMA or value["state"] != "root_reviewed_unsupported_canonical_delivery"
            or value["candidate_group"] != gid or type(value["seed"]) is not int or value["seed"] != seed
            or value["reason"] != "canonical_delivery_missing"
            or value["original_cost_identity"] != value["trial_completion"]):
        raise ValueError("Explicit sealed unsupported terminal identity required")
    matches = [r for r in auth["entries"] if (r["candidate_group"], r["seed"]) == (gid, seed)]
    if len(matches) != 1 or any(value[k] != matches[0][k] for k in ("card", "trial_root", "trial_completion")):
        raise ValueError("Unsupported terminal is not the registered original candidate")
    root = Path(value["trial_root"]).resolve()
    if (not (root / "execution").is_dir() or (root / "delivery/delivery.json").exists()
            or main._inventory(root) != value["retained_inventory"]):
        raise ValueError("Unsupported canonical absence/inventory changed")
    terminal, card = _read(value["trial_completion"]), _read(value["card"])
    if (terminal.get("schema") != "hy30-flow-trial-v2" or terminal.get("status") not in {"partial", "failed"}
            or terminal.get("card") != card or terminal.get("card_sha256") != value["card"]["sha256"]
            or Path(terminal.get("card_path", "")).resolve() != Path(value["card"]["path"]).resolve()
            or card["prepare"]["seed"] != seed):
        raise ValueError("Original unsupported terminal/card/status differs")
    return {"seal": deepcopy(pointer), "original_terminal": terminal,
            "original_cost_identity": value["original_cost_identity"], "reason": value["reason"]}


def _candidate_slot(proof: dict, *, gid: str, seed: int, auth: dict) -> None:
    matches = [row for row in auth["entries"] if (row["candidate_group"], row["seed"]) == (gid, seed)]
    if (proof.get("candidate_group") != gid or type(proof.get("seed")) is not int or proof["seed"] != seed
            or len(matches) != 1 or proof.get("card") != matches[0]["card"]
            or proof.get("original_trial_attempt_identity") != matches[0]["trial_completion"]
            or Path(proof.get("trial_root", "")).resolve() != Path(matches[0]["trial_root"]).resolve()):
        raise ValueError("Candidate proof cannot move between registered group/seed slots")


def authenticate_pair_views(*, source_registration: dict, pair_authority: dict,
                            external_registration: dict, expected_source_sha256: str,
                            expected_pair_sha256: str, expected_external_sha256: str,
                            group_id: str, seed: int) -> dict:
    """Read original material ONLY after exact independently pinned admissions."""
    s, p, scope_meta = _registration(source_registration, pair_authority, external_registration,
        expected_source_sha256, expected_pair_sha256, expected_external_sha256)
    if group_id not in p["groups"] or type(seed) is not int or seed not in c.SEEDS:
        raise ValueError("Registered group and strict generation seed required")
    group = p["groups"][group_id]
    selected = {r["role"]: r for r in group["slots"] if r["seed"] == seed}
    helper = _candidate_helper()
    auth = helper._authority(group["candidate_authority"], group["candidate_authority"]["sha256"])
    if auth["source_scope"] != s["source_scope"]:
        raise ValueError("Candidate original source authority differs")
    control_ptr = selected["control"]["evidence"]
    control_validator = main.make_main_validator(seal=group["control_seal"], expected_seal_sha256=group["control_seal"]["sha256"])
    control_proof = control_validator(control_ptr, seed=seed, role="control", external_registration=group["control_external_registration"])
    # UNKNOWN still requires the original control to belong to this exact
    # canonical source/workload. A metadata-only proof cannot establish that
    # join; reauthenticate and compare before either candidate branch returns.
    scope, scenes, all_originals = custody._source(s["source_scope"])
    originals = {sid: all_originals[sid] for sid in s["ordered_scene_ids"]}
    seal = _read(group["control_seal"])
    old_auth, registered = main._authority(seal["authority"], seal["authority"]["sha256"])
    if group["control_external_registration"] != old_auth["external_registration"]:
        raise ValueError("Historical F5 external registration cannot be substituted")
    historical_proof, intake = unit._main(control_ptr, seed=seed, role="control", registered=registered,
        external_registration=group["control_external_registration"], validator=control_validator)
    historical = _historical_material(historical_proof, intake, originals)
    for scene in scenes:
        c._batches(scene, [b for b in historical["batches"] if b["scene_id"] == scene["id"]])
    base = {"version": VERSION, "group_id": group_id, "seed": seed, "mode": group["mode"],
            "source_registration": source_registration, "pair_authority": pair_authority,
            "external_registration": external_registration, "scene_ids": s["ordered_scene_ids"],
            "control_proof": control_ptr, "candidate_evidence": selected["candidate"]["evidence"],
            "source_scope": s["source_scope"], "baseline_batches": historical["batches"],
            "role_execution": {"control": historical["execution"]},
            "implementation": implementation(), "new_generation_calls": 0, "primary_scores_modified": False}
    if selected["candidate"]["kind"] == "unsupported_terminal":
        unknown = _unsupported(selected["candidate"]["evidence"], gid=group_id, seed=seed, auth=auth)
        return {**base, "status": "admission_blocked_unknown", "unsupported_terminal": unknown,
                "original_cost_identities": [historical["cost_identity"], unknown["original_cost_identity"]]}
    candidate_ptr = selected["candidate"]["evidence"]
    proof = helper.validate_admission(proof=candidate_ptr, expected_proof_sha256=candidate_ptr["sha256"],
        authority=group["candidate_authority"], expected_authority_sha256=group["candidate_authority"]["sha256"])
    _candidate_slot(proof, gid=group_id, seed=seed, auth=auth)
    loaded = helper.load_original_material(proof=candidate_ptr, expected_proof_sha256=candidate_ptr["sha256"],
        authority=group["candidate_authority"], expected_authority_sha256=group["candidate_authority"]["sha256"])
    candidate = _candidate_material(proof, loaded, scope, scenes, originals, baseline_batches=historical["batches"])
    for scene in scenes:
        c._batches(scene, [b for b in candidate["batches"] if b["scene_id"] == scene["id"]])
    deliveries = {}
    for scene in scenes:
        deliveries[scene["id"]] = {}
        for role, material in (("baseline", historical), ("treated", candidate)):
            states = material["aggregate"]["scenes"][scene["id"]]
            normalized = {}
            for uid in scene["translate_ids"]:
                row = states[uid]
                status = row["status"] if row["status"] in c.DELIVERY_STATES else (
                    "delivery_failed" if row["status"] == "translation_failed" else "missing")
                normalized[uid] = {"status": status, "text": row.get("text") if status == "delivered" else None,
                                   "batch_id": row.get("batch_id")}
            deliveries[scene["id"]][custody.ALIASES[role]] = {"source_view_sha256": c.object_hash(scene),
                "provenance_sha256": c.object_hash(material["provenance"]), "cue_states": normalized}
    return {**base, "status": "authenticated_material", "scenes": scenes, "source_scope": s["source_scope"],
            "preparations": candidate["preparations"], "preparation_recipe": candidate["preparation_recipe"],
            "max_items": candidate["max_items"], "baseline_batches": historical["batches"],
            "treated_batches": candidate["batches"], "projection": candidate["projection"],
            "exposure_proofs": candidate["exposure_proofs"], "deliveries": deliveries,
            "role_execution": {"control": historical["execution"], "candidate": candidate["execution"]},
            "main_source_partitions": {"control": historical["batches"], "candidate": (
                None if candidate["provenance"]["main_execution_not_started"] else candidate["batches"])},
            "role_provenance": {"control": historical["provenance"], "candidate": candidate["provenance"]},
            "original_cost_identities": [historical["cost_identity"], candidate["cost_identity"]]}


def _frames(pairs: list[dict], source: dict, term_frame: dict | None = None) -> dict:
    """Pure derivation from authenticated views; not a public admission surface."""
    if [r["seed"] for r in pairs] != list(c.SEEDS):
        raise ValueError("All ordered three-seed pairs required")
    first = pairs[0]
    for row in pairs:
        if any(row[k] != first[k] for k in ("group_id", "mode", "source_registration", "pair_authority", "external_registration", "scene_ids")):
            raise ValueError("Pair identity differs across seeds")
        if (row["source_scope"] != first["source_scope"] or row["baseline_batches"] != first["baseline_batches"]
                or row["role_execution"]["control"] != first["role_execution"]["control"]):
            raise ValueError("Authenticated historical control source/partition/execution differs across seeds")
    costs = [ptr for pair in pairs for ptr in pair["original_cost_identities"]]
    if len({Path(ptr["path"]).resolve() for ptr in costs}) != 6:
        raise ValueError("Six distinct original role/seed cost identities required")
    if any(row["status"] == "admission_blocked_unknown" for row in pairs):
        return {"frames": {"A": None, "B": None}, "jobs": [], "original_cost_identities": costs,
                "expected_slots": [{"job_id": f"{phase}-{sid}-{row['seed']}", "phase": phase,
                    "scene_id": sid, "seed": row["seed"], "status": "admission_blocked_unknown",
                    "reason": "unsupported_canonical_delivery_seed_prevents_honest_three_seed_frame"}
                    for row in pairs for sid in first["scene_ids"] for phase in ("A", "B")]}
    if any(row["status"] != "authenticated_material" for row in pairs):
        raise ValueError("Unknown material admission status")
    for row in pairs:
        if any(row[k] != first[k] for k in ("scenes", "source_scope", "max_items", "baseline_batches", "projection", "preparation_recipe")):
            raise ValueError("Strict same-role three-seed execution/source invariants differ")
    if any(set(row["role_execution"]) != {"control", "candidate"} for row in pairs):
        raise ValueError("Both original role configurations required")
    for role in ("control", "candidate"):
        configurations = [row["role_execution"][role] for row in pairs]
        partitions = [row.get("main_source_partitions", {"control": row["baseline_batches"],
                      "candidate": row["treated_batches"]})[role] for row in pairs]
        known_partitions = [value for value in partitions if value is not None]
        declared = [{k: v for k, v in value.items() if k != "actual_main"} for value in configurations]
        observed = [value["actual_main"] for value in configurations if value.get("actual_main") is not None]
        if (any(value != declared[0] for value in declared) or any(value != observed[0] for value in observed)
                or any(value != known_partitions[0] for value in known_partitions)):
            raise ValueError("Strict same-role three-seed execution/source invariants differ")
    preparations = {row["seed"]: row["preparations"] for row in pairs}
    frame_b = c.freeze_frame(first["scenes"], preparations, first["baseline_batches"], mode=first["mode"], metadata={
        "split": "screening", "quality_inspected": False, "max_items": first["max_items"],
        "source_manifest_sha256": source["source_manifest"]["sha256"], "scene_file_sha256": source["source_scenes"]["sha256"],
        "source_freeze_sha256": source["source_freeze"]["sha256"],
        "preparation_set_sha256": {str(seed): c.object_hash(preparations[seed]) for seed in c.SEEDS}})
    frame_a = frame_b if first["mode"] == "terms" else term_frame
    if frame_a is not None:
        c.validate_frame(frame_a)
        if frame_a["inputs"]["mode"] != "terms" or frame_a["inputs"]["scenes"] != first["scenes"] or frame_a["inputs"]["c0_batches"] != first["baseline_batches"]:
            raise ValueError("Term donor must retain exact complete source and C0 partition")
    jobs, slots = [], []
    for pair in pairs:
        for scene in first["scenes"]:
            sid, seed = scene["id"], pair["seed"]
            for phase, frame in (("A", frame_a), ("B", frame_b)):
                status = "scheduled"
                if frame is None:
                    status = "term_inventory_unavailable"
                elif phase == "A" and not any(a["eligible"] for a in frame["inventory"][sid]):
                    status = "inventory_incomplete" if frame["coverage"][sid]["missing_preparation_slots"] else "not_assessed_zero_inventory"
                elif phase == "B" and frame["parsed"][str(seed)][sid] is not None and not frame["parsed"][str(seed)][sid]["records"]:
                    status = "not_assessed_zero_inventory"
                job_id = f"{phase}-{sid}-{seed}"
                slots.append({"job_id": job_id, "phase": phase, "scene_id": sid, "seed": seed, "status": status})
                if status != "scheduled":
                    continue
                options = {}
                if phase == "B":
                    batches = [b for b in pair["treated_batches"] if b["scene_id"] == sid]
                    options = {"prepared_alias": custody.ALIASES["treated"], "batches": batches,
                               "projection": pair["projection"], "exposure_proofs": {b["id"]: pair["exposure_proofs"][b["id"]] for b in batches}}
                bundle = c.build_phase_a(frame, sid, seed, pair["deliveries"][sid]) if phase == "A" else c.build_phase_b(frame, sid, seed, pair["deliveries"][sid], **options)
                c.validate_bindings(bundle, frame, pair["deliveries"][sid], **options)
                jobs.append({"job_id": job_id, "envelope": bundle})
    return {"frames": {"A": frame_a, "B": frame_b}, "jobs": jobs, "expected_slots": slots, "original_cost_identities": costs}


def freeze_registered_consistency_frames(*, source_registration: dict, pair_authority: dict,
        external_registration: dict, expected_source_sha256: str, expected_pair_sha256: str,
        expected_external_sha256: str, group_id: str, output: Path,
        term_inventory_donor: dict | None = None) -> dict:
    """Reauthenticate all original seeds into a NEW bridge receipt; no dispatch."""
    if output.exists():
        raise FileExistsError("New immutable bridge receipt destination required")
    pins = dict(source_registration=source_registration, pair_authority=pair_authority,
                external_registration=external_registration, expected_source_sha256=expected_source_sha256,
                expected_pair_sha256=expected_pair_sha256, expected_external_sha256=expected_external_sha256)
    s, p, scope = _registration(
        source_registration, pair_authority, external_registration, expected_source_sha256, expected_pair_sha256, expected_external_sha256)
    pairs = [authenticate_pair_views(**pins, group_id=group_id, seed=seed) for seed in c.SEEDS]
    term_frame = None
    if term_inventory_donor is not None:
        donor_metadata = _read(term_inventory_donor)
        if (group_id != "F7-evidence-scene-card" or donor_metadata.get("group_id") != "F6-terms-proposals-max32"
                or donor_metadata.get("term_inventory_donor") is not None):
            raise ValueError("Only an acyclic F6-to-F7 term donor is supported")
        donor = validate_registered_bridge_receipt(term_inventory_donor, **pins)
        if donor["group_id"] != "F6-terms-proposals-max32" or donor["source_registration"] != source_registration:
            raise ValueError("Exact authenticated F6 term inventory donor required")
        term_frame = donor["frames"]["B"]
    derived = _frames(pairs, scope, term_frame)
    receipt = {"version": VERSION, "state": "mechanical_bridge_frozen_no_dispatch_authority", "group_id": group_id,
               **{k: deepcopy(v) for k, v in pins.items() if not k.startswith("expected_")},
               "implementation": implementation(), "pairs": pairs, "term_inventory_donor": term_inventory_donor,
               **derived, "jobs_sha256": c.object_hash(derived["jobs"]), "new_generation_calls": 0,
               "semantic_accuracy_verified": False, "primary_scores_modified": False, "dispatch_authorization": False}
    output = output.resolve()
    protected = [Path(ptr["path"]).resolve().parent for pair in pairs for ptr in pair["original_cost_identities"]]
    protected.extend(Path(_read(pair["control_proof"])["trial"]["completion"]["path"]).resolve().parent for pair in pairs)
    protected.extend(Path(scope[key]["path"]).resolve().parent for key in ("source_manifest", "source_scenes", "source_freeze"))
    if any(output.is_relative_to(path) for path in protected):
        raise ValueError("Bridge receipt cannot write into original evidence roots")
    output.parent.mkdir(parents=True, exist_ok=True)
    return {"receipt": unit._write(output, receipt), "jobs": derived["jobs"], "expected_slots": derived["expected_slots"]}


def validate_registered_bridge_receipt(pointer: dict, *, source_registration: dict, pair_authority: dict,
        external_registration: dict, expected_source_sha256: str, expected_pair_sha256: str,
        expected_external_sha256: str) -> dict:
    """Compare to complete original reauthentication, never self-consistent hashes."""
    observed = _read(pointer)
    path = Path(pointer["path"]).resolve()
    if observed.get("version") != VERSION or observed.get("dispatch_authorization") is not False:
        raise ValueError("Bridge receipt version/dispatch boundary differs")
    with tempfile.TemporaryDirectory(prefix="consistency-bridge-rebind-", dir=path.parent) as temporary:
        rebuilt = freeze_registered_consistency_frames(source_registration=source_registration,
            pair_authority=pair_authority, external_registration=external_registration,
            expected_source_sha256=expected_source_sha256, expected_pair_sha256=expected_pair_sha256,
            expected_external_sha256=expected_external_sha256, group_id=observed["group_id"],
            term_inventory_donor=observed["term_inventory_donor"], output=Path(temporary) / "rebuilt.json")
        if c.object_hash(_read(rebuilt["receipt"])) != c.object_hash(observed):
            raise ValueError("Bridge receipt differs from authenticated original views")
    return observed
