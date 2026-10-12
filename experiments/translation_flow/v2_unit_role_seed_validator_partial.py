"""Closed source-pinned F5 role/seed MAIN proof dispatcher; metadata only.

Controls retain the original helper/seal. Each candidate seed retains its own
literal seed-specific helper/authority/seal. No original text authentication, model,
judge, generation, reference or confirmation extraction occurs here.
"""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from typing import Callable
from experiments.translation_eval import runner as e
from . import v2_unit_main_proof as control_factory
from . import v2_unit_main_proof_singleton as singleton_factory
from . import v2_unit_main_proof_partial as partial_factory
from . import v2_unit_custody as unit_custody

BASE = Path(__file__).resolve().parents[2] / ".local/translation-evaluation/hy30-flow-v2-20261008"
SEEDS = (20261008, 20261009, 20261010)
CONTROL_FACTORY_SHA = "aec506822df7844377782759c06087e33ef9eaf095bace90bd57c7f9ee745c6d"
SINGLETON_FACTORY_SHA = "bbf81f0a8ba72aac601ba7085a2d2f2d55521183c94c75a673b485ace58acae7"
CONTROL_SEAL_SHA = "fbee32bdec993e576197edcc4fc87bba2f4cd96cce1587278cde5614444b64f6"
F5_EXTERNAL_SHA = "bc4c1961c4a25ecf81072d3e9f778bf1d884654e59ad7a24e5dc1c9986ce4038"
PROPAGATION_SHA = "9fac0350d92948c116af6e5b2f84f2ad67209fedf546c0905981a69392fde588"
PARTIAL_FACTORY_SHA = "76ec393bc6d377fb3611fe3a005f77c88b61870d734fa081df8323c51be6f093"
PARTIAL_ACCEPTANCE_SHA = "971731c890f9232df169433d6b27214cc9e38abd9fc30625b0c423170119232b"
REGISTRY_SCHEMA = "hy30-F5-partial-role-seed-main-registry-v1"
REGISTRY_FIELDS = {"schema", "state", "dispatcher", "propagation", "candidate_verifiers", "partial_acceptance",
                   "control_verifier", "control_seal", "external_registration", "slots"}
SLOT_FIELDS = {"seed", "role", "receipt", "seal", "authority", "unavailable_reason"}


def identity(path: Path) -> dict:
    return unit_custody.identity(path)


pointer = identity


def bound(value: dict) -> Path:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError("An exact independently pinned artifact pointer is required")
    unit_custody._read_bytes(value)
    return Path(value["path"]).resolve()


def factory_for(role: str, seed: int):
    """Literal closed mapping; the registry never chooses executable code."""
    if type(seed) is not int or seed not in SEEDS or role not in {"candidate", "control"}:
        raise ValueError("Explicit frozen role/seed required")
    if role == "control":
        return control_factory
    return partial_factory if seed == 20261009 else singleton_factory


def candidate_verifiers() -> dict[str, dict]:
    return {str(seed): identity(Path(factory_for("candidate", seed).__file__)) for seed in SEEDS}


def partial_acceptance() -> dict:
    return {"path": str((BASE / "summaries/F5-partial-mainproof-root-offline-acceptance-v1.json").resolve()),
            "sha256": PARTIAL_ACCEPTANCE_SHA}


def execution_dependencies() -> list[dict]:
    modules = (control_factory, singleton_factory, partial_factory, unit_custody, control_factory.diagnostics,
               control_factory.partition, e)
    paths = {str(Path(__file__).resolve()), *(str(Path(m.__file__).resolve()) for m in modules),
             *(p["path"] for p in unit_custody._dependencies())}
    return [identity(Path(p)) for p in sorted(paths)]


def verify_code() -> None:
    for module, expected in ((control_factory, CONTROL_FACTORY_SHA), (singleton_factory, SINGLETON_FACTORY_SHA),
                             (partial_factory, PARTIAL_FACTORY_SHA)):
        if e.sha(Path(module.__file__)) != expected:
            raise ValueError("Frozen role-specific F5 factory bytes changed")
    if e.sha(BASE / "summaries/F5-partial-mainproof-root-offline-acceptance-v1.json") != PARTIAL_ACCEPTANCE_SHA:
        raise ValueError("Approved partial helper root acceptance changed")
    if e.sha(BASE / "summaries/F5-singleton-helper-version-v1/propagation-boundary.json") != PROPAGATION_SHA:
        raise ValueError("Approved singleton propagation boundary changed")


def _closed_dispatch(callbacks: dict[tuple[str, int], Callable[..., dict]],
                     receipts: dict[tuple[str, int], dict | None], external_registration: dict) -> Callable[..., dict]:
    """Capture explicit factory callbacks; never infer role or replace source code."""
    functions = dict(callbacks)
    frozen_receipts = deepcopy(receipts)
    external = deepcopy(external_registration)
    if set(frozen_receipts) != {(role, seed) for role in ("candidate", "control") for seed in SEEDS}:
        raise ValueError("Exactly six fixed role/seed proof or unavailable slots required")

    def validate(receipt: dict, *, seed: int, role: str, external_registration: dict) -> dict:
        if type(seed) is not int or seed not in SEEDS or role not in {"candidate", "control"}:
            raise ValueError("Explicit frozen role and generation seed required")
        slot = role, seed
        if external_registration != external or receipt != frozen_receipts[slot] or slot not in functions:
            raise ValueError("Missing or mismatched role/seed/external proof cannot be admitted")
        proof = functions[slot](deepcopy(receipt), seed=seed, role=role, external_registration=deepcopy(external))
        if (set(proof) != unit_custody.MAIN_FIELDS or proof != e.read_json(bound(receipt))
                or proof["schema"] != unit_custody.MAIN_PROOF_SCHEMA or proof["role"] != role or proof["seed"] != seed):
            raise ValueError("Factory must return the exact artifact-bound20-field MAIN proof")
        return proof
    return validate

def validate_registry(pointer_value: dict, expected_sha256: str) -> tuple[dict, dict]:
    if pointer_value.get("sha256") != expected_sha256:
        raise ValueError("Role/seed registry needs an independent root SHA")
    value = e.read_json(bound(pointer_value))
    verify_code()
    if (set(value) != REGISTRY_FIELDS or value["schema"] != REGISTRY_SCHEMA
            or value["state"] != "root_reviewed_fixed_role_seed_slots"
            or value["dispatcher"] != pointer(Path(__file__))
            or value["candidate_verifiers"] != candidate_verifiers()
            or value["partial_acceptance"] != partial_acceptance()
            or value["control_verifier"] != pointer(Path(control_factory.__file__))
            or value["propagation"]["sha256"] != PROPAGATION_SHA
            or value["control_seal"]["sha256"] != CONTROL_SEAL_SHA
            or value["external_registration"]["sha256"] != F5_EXTERNAL_SHA):
        raise ValueError("Closed V11 role/helper/control/source identities required")
    for key in ("propagation", "partial_acceptance", "control_seal", "external_registration"):
        bound(value[key])
    slots = value["slots"]
    if (len(slots) != 6 or {(r.get("role"), r.get("seed")) for r in slots}
            != {(role, seed) for role in ("candidate", "control") for seed in SEEDS}):
        raise ValueError("Root registry cannot omit, duplicate, or replace a fixed role/seed slot")
    if [(r.get("seed"), r.get("role")) for r in slots] != [(seed, role) for seed in SEEDS for role in ("candidate", "control")]:
        raise ValueError("Fixed ascending seed order with candidate then control required")
    table = {}
    for row in slots:
        if set(row) != SLOT_FIELDS or type(row["seed"]) is not int:
            raise ValueError("Exact typed role/seed slot metadata required")
        key = row["role"], row["seed"]
        if row["receipt"] is None:
            if (row["role"] != "candidate" or row["seal"] is not None or row["authority"] is not None
                    or not isinstance(row["unavailable_reason"], str) or not row["unavailable_reason"].strip()):
                raise ValueError("Unavailable candidate retains an explicit administrative reason only")
        else:
            if row["unavailable_reason"] is not None:
                raise ValueError("Present native proof cannot be relabeled unavailable")
            for name in ("receipt", "seal", "authority"):
                bound(row[name])
            sealed = e.read_json(bound(row["seal"]))
            factory = factory_for(row["role"], row["seed"])
            if (set(sealed) != {"schema", "state", "verifier", "authority", "proofs"}
                    or sealed["schema"] != factory.SEAL_SCHEMA or sealed["state"] != "root_reviewed_original_main_proofs"
                    or sealed["verifier"] != pointer(Path(factory.__file__)) or sealed["authority"] != row["authority"]):
                raise ValueError("Each proof retains its own externally sealed helper/authority")
            matches = [r for r in sealed["proofs"] if (r.get("role"), r.get("seed")) == key]
            if len(matches) != 1 or matches[0].get("proof") != row["receipt"]:
                raise ValueError("External seal must pin the exact role/seed proof")
            if row["role"] == "control" and row["seal"] != value["control_seal"]:
                raise ValueError("Original controls cannot be reauthenticated or relabeled")
            if row["role"] == "candidate" and len(sealed["proofs"]) != 1:
                raise ValueError("Candidate requires its own per-seed seal, not an aggregate replacement authority")
            auth = e.read_json(bound(row["authority"]))
            entries = [r for r in auth["entries"] if (r.get("role"), r.get("seed")) == key]
            if row["role"] == "candidate" and len(auth["entries"]) != 1:
                raise ValueError("Candidate requires its own single-seed authority")
            if len(entries) != 1 or entries[0]["declared_snapshot_count"] != (17 if row["role"] == "control" else 21):
                raise ValueError("Original control17/candidate21 executed snapshot declarations are preserved")
        table[key] = row
    return value, table

def make_role_seed_main_validator(*, registry: dict, expected_registry_sha256: str) -> Callable[..., dict]:
    """Source-pinned66c callback; frozen13ca consumption needs a NEW runner seam."""
    value, table = validate_registry(registry, expected_registry_sha256)
    callbacks, receipts = {}, {}
    for key, row in table.items():
        receipts[key] = row["receipt"]
        if row["receipt"] is not None:
            factory = factory_for(*key)
            callbacks[key] = factory.make_main_validator(seal=deepcopy(row["seal"]), expected_seal_sha256=row["seal"]["sha256"])
    dispatch = _closed_dispatch(callbacks, receipts, value["external_registration"])
    frozen_registry = deepcopy(registry)

    def validate(receipt: dict, *, seed: int, role: str, external_registration: dict) -> dict:
        # Recheck the accepted registry, factories and original per-seed seals.
        validate_registry(frozen_registry, expected_registry_sha256)
        return dispatch(receipt, seed=seed, role=role, external_registration=external_registration)
    return validate
