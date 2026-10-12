"""Custody-only F8 root transport, immutable stage inventories and dev release.

This module never chooses a gate or dispatches on preparation. Native execution
requires the existing shared ROOT guard and an external stage admission. Full
authentication occurs at barriers; attempts use immutable local bundles.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
from typing import Any, Callable
import uuid

from experiments.translation_judge import integrity, runner as transport, scheduling
from . import v2_judge_dispatch as native
from . import v2_review_root_evidence as helper


VERSION = "f8-root-custody-runner-v1"
ADAPTER_SHA256 = "8ec17c2a6e4b95c9ee34f64df870357aa0fbf72f36df7b9a2c76fea922b39698"
SPLIT_SHA256 = "f09d498c709d61e1cc7a4b85bc80390bf2dcdee26bea340d224e284d2a1a55fc"
STAGES = helper.STAGES
PREFIXES = {stage: [f"bundles/{stage}/", f"execution/{stage}/", f"responses/{stage}/", f"receipts/{stage}/"]
            for stage in STAGES}


class AdmissionBlocked(ValueError):
    """No root calls were authorized; retain the complete administrative scope."""
    expected_pairs = 144
    expected_root_job_slots = 288
    root_calls = 0


class IntegrityDrift(ValueError):
    """Input/provenance drift is terminal, including on a failed callback."""


def _sha(path: Path) -> str:
    return integrity.sha(path.read_bytes())


def _read(path: Path) -> Any:
    return integrity.strict_parse(path.read_bytes().decode("utf-8-sig"))


def _pointer(value: dict, expected: str | None = None) -> Path:
    return helper._pointer(value, expected)


def _identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": _sha(path)}


def _root(path: Path) -> Path:
    for entry in (path, *path.parents):
        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
            raise IntegrityDrift("workspace cannot traverse a symlink or junction")
    return path.resolve()


def _new(path: Path, value: Any) -> dict:
    payload = value if isinstance(value, bytes) else integrity.canonical_bytes(value)
    if path.exists():
        if path.read_bytes() != payload:
            raise IntegrityDrift("immutable artifact already exists with different bytes")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(payload)
    return _identity(path)


def _live(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending-" + uuid.uuid4().hex)
    with temporary.open("xb") as stream:
        stream.write(integrity.canonical_bytes(value))
    temporary.replace(path)


def _local(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or Path(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in relative.replace("\\", "/").split("/"))):
        raise IntegrityDrift("invalid relative artifact path")
    supplied = root / relative
    for entry in (supplied, *supplied.parents):
        if entry.is_symlink() or (hasattr(entry, "is_junction") and entry.is_junction()):
            raise IntegrityDrift("artifact cannot traverse a symlink or junction")
    return integrity.inside(root, supplied)


def _inventory(root: Path, prefixes: list[str] | None = None, *, excluded: set[str] | None = None) -> list[dict]:
    excluded = excluded or set()
    result = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        _local(root, relative)
        if not path.is_file() or relative in excluded:
            continue
        if prefixes is None or any(relative.startswith(prefix) for prefix in prefixes):
            result.append({"path": relative, "sha256": _sha(path)})
    return result


def _exact_inventory(root: Path, files: list[dict], prefixes: list[str] | None = None,
                     *, excluded: set[str] | None = None) -> None:
    if _inventory(root, prefixes, excluded=excluded) != files:
        raise IntegrityDrift("exact inventory changed or contains undeclared artifacts")


def implementation() -> dict:
    modules = {"adapter": helper, "native_dispatch": native, "transport": transport,
               "integrity": integrity, "scheduling": scheduling}
    result = {name: _identity(Path(module.__file__)) for name, module in modules.items()}
    result["runner"] = _identity(Path(__file__))
    if result["adapter"]["sha256"] != ADAPTER_SHA256:
        raise IntegrityDrift("frozen F8 adapter changed")
    return result


def _command_config() -> dict:
    return {"model": transport.MODEL, "effort": transport.EFFORT,
            "overrides": list(transport.OVERRIDES), "disabled_features": list(transport.DISABLED_FEATURES)}


def _shape(value: Any, schema: dict) -> None:
    """Only format checks; source evidence and identity use the frozen validator."""
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                _shape(value, branch)
                return
            except ValueError:
                pass
        raise ValueError("response format does not match any schema branch")
    kind = schema["type"]
    if (kind == "object" and not isinstance(value, dict) or kind == "array" and not isinstance(value, list)
            or kind == "string" and not isinstance(value, str) or kind == "boolean" and type(value) is not bool
            or kind == "integer" and type(value) is not int or kind == "null" and value is not None):
        raise ValueError("response format type mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("response format enum mismatch")
    if kind == "object":
        if set(value) != set(schema["required"]):
            raise ValueError("response format required/extra fields mismatch")
        for key, child in schema["properties"].items():
            _shape(value[key], child)
    elif kind == "array":
        for child in value:
            _shape(child, schema["items"])


def _schema_failure(attempt: Path, result: dict) -> bool:
    # Classify transport ERROR events only, never assistant last-message text.
    path = attempt / "stdout.jsonl"
    if not path.exists():
        return False
    for line in path.read_bytes().decode("utf-8", errors="replace").splitlines():
        try:
            event = integrity.strict_parse(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        payload = (event if event.get("type") == "error" else event.get("error")
                   if event.get("type") == "turn.failed" else event.get("item")
                   if isinstance(event.get("item"), dict) and event["item"].get("type") == "error" else None)
        pending = [payload]
        while pending:
            part = pending.pop()
            if isinstance(part, dict):
                if part.get("code") == "invalid_json_schema":
                    return True
                pending.extend(part.values())
            elif isinstance(part, str) and "invalid_json_schema" in part and re.search(r"\b400\b", part):
                return True
    return False


def _registration(pointer: dict, expected: str) -> dict:
    value = _read(_pointer(pointer, expected))
    helper._keys(value, {"schema", "kind", "synthetic_material_declared", "custody_root", "native_frame",
                        "split_registration", "phase_roots", "phase_seals", "phase_code",
                        "native_proof_code", "native_review_proofs", "root_protocol", "terminal_receipt",
                        "cli_executable"}, "native root registration")
    if (value["schema"] != "f8-root-native-registration-v1" or value["kind"] not in {"actual", "synthetic"}
            or value["synthetic_material_declared"] is not (value["kind"] == "synthetic")
            or Path(value["custody_root"]).resolve().name != "evaluation-only"):
        raise AdmissionBlocked("explicit custody registration and material identity required")
    if value["kind"] == "actual" and value["split_registration"]["sha256"] != SPLIT_SHA256:
        raise AdmissionBlocked("actual root study must use the externally frozen source split")
    seeds = {str(seed) for seed in helper.SEEDS}
    if set(value["phase_roots"]) != seeds or set(value["native_review_proofs"]) != seeds:
        raise AdmissionBlocked("three original runs and mechanical proofs are required")
    _root(Path(value["custody_root"]))
    for path in value["phase_roots"].values():
        _root(Path(path))
    implementation()
    return value


def _native_proofs(registration: dict) -> list[dict]:
    """Load only externally code-pinned mechanical authority, never a true flag."""
    code = _pointer(registration["native_proof_code"])
    spec = importlib.util.spec_from_file_location("_f8_review_proof_" + registration["native_proof_code"]["sha256"], code)
    if spec is None or spec.loader is None:
        raise AdmissionBlocked("native review proof module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if (getattr(module, "VERSION", None) != "hy30-native-review-main-admission-v1"
            or getattr(module, "PROFILE", None) != "hy30-main-source-review-private-v1"
            or not callable(getattr(module, "validate_receipt", None))):
        raise AdmissionBlocked("native review proof interface differs from external registration")
    _, frame = helper.evaluation.frame_metadata(registration["native_frame"],
        registered_frame_sha256=registration["native_frame"]["sha256"])
    proofs = []
    for index, seed in enumerate(helper.SEEDS):
        pointer = registration["native_review_proofs"][str(seed)]
        value = module.validate_receipt(pointer, registered_receipt_sha256=pointer["sha256"])
        scope = _read(_pointer(frame["scopes"][index]))
        expected = {"seed": seed, "source_manifest": scope["source_manifest"],
                    "original_run": scope["original_generation_cost_identity"],
                    "original_delivery": scope["original_delivery"],
                    "original_cost_identity": _identity(Path(scope["original_delivery"]["path"]).parent / "costs.json")}
        if value.get("root_binding") != expected:
            raise AdmissionBlocked("mechanical review authority is not the same original seed/source/run/draft/cost")
        for key, item in expected.items():
            if key != "seed":
                _pointer(item)
        proofs.append({"receipt": deepcopy(pointer), "code": deepcopy(registration["native_proof_code"]),
                       "root_binding": expected, "metadata": deepcopy(value)})
    return proofs


def _load_frame(registration: dict) -> helper.AuthenticatedFrame:
    try:
        _native_proofs(registration)
        if set(registration["phase_seals"]) != {str(seed) for seed in helper.SEEDS}:
            raise AdmissionBlocked("all three terminal phase seals require external registration")
        return helper.prepare_frame(registration["native_frame"],
            {seed: Path(registration["phase_roots"][str(seed)]) for seed in helper.SEEDS},
            {seed: registration["phase_seals"][str(seed)] for seed in helper.SEEDS},
            registration["split_registration"], registered_frame_sha256=registration["native_frame"]["sha256"],
            registered_split_sha256=registration["split_registration"]["sha256"],
            registered_phase_seal_sha256={seed: registration["phase_seals"][str(seed)]["sha256"] for seed in helper.SEEDS},
            expected_code_sha256={name: pointer["sha256"] for name, pointer in registration["phase_code"].items()},
            custody_root=Path(registration["custody_root"]))
    except (ValueError, KeyError, OSError) as exc:
        raise AdmissionBlocked("upstream authority is incomplete; 144 administrative unknown pairs, zero root calls") from exc


def _drain(pointer: dict, registration: dict) -> None:
    value = _read(_pointer(pointer))
    root = Path(registration["custody_root"]).resolve()
    if (value.get("schema") != "hy30-native-judge-custody-v1" or value.get("owner") != "evaluation_custodian"
            or value.get("state") != "drained_released" or value.get("active_callbacks") != 0
            or value.get("owned_job_objects") != 0 or value.get("module_sha256") != implementation()["native_dispatch"]["sha256"]
            or type(value.get("workers_reserved")) is not int or not 1 <= value["workers_reserved"] <= 6
            or Path(value.get("global_lock", "")).resolve() != root / ".judge-global-six.lock"):
        raise AdmissionBlocked("stage sealing requires existing shared native drain proof")


def seal_upstream_phases(registration_pointer: dict, *, registered_sha256: str,
                         drained_receipts_by_seed: dict[str, dict]) -> dict:
    """Seal existing finalized phase histories; never finalize or execute them."""
    registration = _registration(registration_pointer, registered_sha256)
    _native_proofs(registration)
    if (not isinstance(drained_receipts_by_seed, dict)
            or set(drained_receipts_by_seed) != {str(seed) for seed in helper.SEEDS}):
        raise AdmissionBlocked("exact three original per-seed native drains are required")
    # Validate the whole cohort before writing any seal. External V8 execution
    # snapshots independently require equality with each original seed's lease.
    for pointer in drained_receipts_by_seed.values():
        _drain(pointer, registration)
    code = helper._code_pins({name: p["sha256"] for name, p in registration["phase_code"].items()})
    seals, payloads = {}, {}
    for seed in helper.SEEDS:
        root = _root(Path(registration["phase_roots"][str(seed)]))
        meta = helper.evaluation.validate_prepared(root,
            registered_frame_sha256=registration["native_frame"]["sha256"])
        expected, finals = helper.e.load_jsonl(root / "expected.jsonl"), helper.e.load_jsonl(root / "final.jsonl")
        keyed = {(r["candidate_alias"], r["window_id"]): r for r in finals}
        if meta["seed"] != seed or len(expected) != 96 or len(finals) != 96 or len(keyed) != 96:
            raise AdmissionBlocked("upstream phase expected/final denominator differs")
        try:
            accepted, _ = helper._accepted_phases(root, expected)
            for row in expected:
                helper._used_evidence(row, keyed[row["candidate_alias"], row["window_id"]], accepted)
        except (ValueError, KeyError, OSError) as exc:
            raise AdmissionBlocked("upstream not_run/missing/nonterminal histories cannot be relabeled") from exc
        files = _inventory(root, excluded={"root-phase-inventory.json", ".judge-scheduler.lock"})
        seal = {"schema": "f8-root-phase-inventory-v1", "frame": registration["native_frame"], "seed": seed,
                "code": code, "expected_records": 96, "files": files,
                "native_drain_receipt": deepcopy(drained_receipts_by_seed[str(seed)])}
        payloads[str(seed)] = (root / "root-phase-inventory.json", seal)
    for seed, (path, seal) in payloads.items():
        seals[seed] = _new(path, seal)
    return {"schema": "f8-root-phase-seals-awaiting-external-registration-v1", "seals": seals,
            "expected_pairs": 144, "root_calls": 0, "automatic_dispatch": False}


def _bundle(root: Path, packet: dict, private: dict, protocol_pointer: dict, protocol: dict,
            dependencies: list[dict] | None = None) -> dict:
    stage, alias = packet["task_stage"], packet["pair_alias"]
    relative = f"bundles/{stage}/{alias}"
    directory = _local(root, relative)
    payloads = {"packet.json": integrity.canonical_bytes(packet), "private.json": integrity.canonical_bytes(private),
                "prompt.txt": helper.prompt(packet).encode("utf-8"),
                "schema.json": integrity.canonical_bytes(helper.response_schema(stage))}
    artifacts = {name: _new(directory / name, payload) for name, payload in payloads.items()}
    return {"job_id": f"{stage}/{alias}", "pair_key": private["pair_key"], "stage": stage,
            "bundle": relative, "fingerprint": helper.task_fingerprint(packet, protocol_pointer, protocol),
            "artifacts": artifacts, "dependencies": deepcopy(dependencies or [])}


def prepare_packets(root: Path, registration_pointer: dict, *, registered_sha256: str,
                    aliases: dict[str, str], phase_orders: dict[str, list[str]]) -> dict:
    """Authenticate once, freeze all slots and evidence bytes without dispatch."""
    started = time.perf_counter()
    registration = _registration(registration_pointer, registered_sha256)
    frame = _load_frame(registration)
    protocol = helper._protocol(frame, registration["root_protocol"], registration["root_protocol"]["sha256"])
    if str(_pointer(registration["cli_executable"])) != protocol["transport_settings"]["executable"]:
        raise AdmissionBlocked("CLI binary pointer differs from frozen transport settings")
    root = _root(root)
    root.mkdir(parents=True, exist_ok=False)
    plan = helper.freeze_plan(frame, registration["root_protocol"],
        registered_protocol_sha256=registration["root_protocol"]["sha256"], aliases=aliases, phase_orders=phase_orders)
    plan_pointer = _new(root / "common/root-plan.json", plan)
    pins = implementation()
    for name, pointer in pins.items():
        _new(root / f"common/implementation/{name}.py", _pointer(pointer).read_bytes())
    proofs = _native_proofs(registration)
    dependencies = _dependencies(frame, registration, proofs)
    context = {"schema": VERSION, "registration": registration_pointer, "implementation": pins,
               "command_config": _command_config(), "root_plan": plan_pointer,
               "protocol": registration["root_protocol"], "frame_sha256": frame._hash,
               "allowed_stage_prefixes": PREFIXES, "expected_pairs": 144, "expected_root_job_slots": 288,
               "native_cost_lineage": proofs, "launch_dependencies": _dedupe([
                   registration["cli_executable"], registration["terminal_receipt"], registration["native_frame"],
                   registration["split_registration"], *registration["phase_seals"].values()]),
               "automatic_dispatch": False}
    _new(root / "common/context.json", context)
    _new(root / "common/seal.json", {"schema": "f8-root-common-inventory-v1",
        "files": _inventory(root, ["common/"], excluded={"common/seal.json"})})
    planned = {p["pair_key"]: p for p in plan["pairs"]}
    jobs, slots = [], []
    for pair in frame._data["pairs"]:
        item = planned[pair["pair_key"]]
        slots.append({"pair_key": pair["pair_key"], "job_id": item["evidence_job_id"],
                      "status": "scheduled" if pair["mechanically_eligible"] else "mechanical_unknown"})
        if pair["mechanically_eligible"]:
            # Explicit, code-pinned pure projection of authenticated frame data.
            packet, private = helper._packet(pair, frame._hash, item["anonymous_alias"], tuple(item["phase_order"]))
            jobs.append(_bundle(root, packet, private, registration["root_protocol"], protocol,
                                dependencies[pair["pair_key"]]))
    manifest = {"schema": "f8-root-stage-preparation-v1", "stage": "evidence", "common": _identity(root / "common/seal.json"),
                "jobs": jobs, "expected_slots": slots, "expected_job_slots": 144, "maximum_attempts": 2,
                "prepare_seconds": time.perf_counter() - started}
    pointer = _new(root / "receipts/evidence/preparation.json", manifest)
    return {"preparation": pointer, "root_plan": plan_pointer, "common": _identity(root / "common/seal.json"),
            "expected_pairs": 144, "expected_root_job_slots": 288, "automatic_dispatch": False}


def _dedupe(pointers: list[dict]) -> list[dict]:
    result = {}
    for pointer in pointers:
        key = str(_pointer(pointer))
        if key in result and result[key] != pointer:
            raise IntegrityDrift("dependency has conflicting registered identities")
        result[key] = deepcopy(pointer)
    return [result[key] for key in sorted(result)]


def _dependencies(frame: helper.AuthenticatedFrame, registration: dict, proofs: list[dict]) -> dict:
    """Index once; per job hash only common masters and its actual native chains."""
    split = _read(_pointer(registration["split_registration"]))
    shared = [registration["native_frame"], registration["split_registration"], split["proposal"],
              registration["root_protocol"], registration["cli_executable"], registration["terminal_receipt"],
              registration["native_proof_code"], *registration["phase_code"].values()]
    result = {}
    for proof in proofs:
        seed, meta = proof["root_binding"]["seed"], proof["metadata"]
        masters = [proof["receipt"], proof["code"], *meta["retained"].values(),
                   *meta["trial"].values(), meta["source_inputs"], meta["source_qualification"],
                   *proof["root_binding"].values()]
        masters = [p for p in masters if isinstance(p, dict)]
        ledger = helper.e.load_jsonl(_pointer(meta["retained"]["ledger"]))
        packed = _read(_pointer(meta["retained"]["packed"]))
        batches = {b["id"]: b for b in packed["batches"]}
        phase_root = _root(Path(registration["phase_roots"][str(seed)]))
        phase_files = [{"path": str(phase_root / p["path"]), "sha256": p["sha256"]}
                       for p in _read(_pointer(registration["phase_seals"][str(seed)]))["files"]]
        expected = helper.e.load_jsonl(phase_root / "expected.jsonl")
        manifest_path = _pointer(proof["root_binding"]["source_manifest"])
        windows = {w.get("window_id", w["id"]): w for w in _read(manifest_path)["windows"]}
        for pair in (p for p in frame._data["pairs"] if p["seed"] == seed):
            ids = set(pair["source"]["scored_ids"])
            chains = []
            for row in ledger:
                batch = batches.get(row.get("batch_id", row.get("window_id", row.get("id"))))
                if batch is None:
                    # Some native ledgers use the batch's public id as job_id.
                    batch = batches.get(row.get("job_id"))
                if batch is None:
                    raise AdmissionBlocked("native ledger cannot be joined to its prepared batch")
                if batch["scene_id"] != pair["scene_id"] or not ids.intersection(batch["target_ids"]):
                    continue
                for attempt in row.get("attempts", []):
                    for name in ("original_response", "tokenize_exchange"):
                        if attempt.get(name):
                            directory = _root(Path(attempt[name]))
                            chains += [p for p in meta["inventory"] if Path(p["path"]).is_relative_to(directory)]
            selected = [r for r in expected if r["window_id"] == pair["window_id"]]
            prefixes = [str((phase_root / r["packet"]).resolve()) for r in selected]
            # Accepted opinions are in execution/<phase>/<alias-window> trees;
            # bind all terminal attempts for this window, including unused ones.
            phase = [p for p in phase_files if p["path"] in prefixes or pair["window_id"] in Path(p["path"]).name
                     or any(pair["window_id"] in part for part in Path(p["path"]).parts)]
            phase += [p for p in phase_files if Path(p["path"]).parent == phase_root]
            source = windows[pair["window_id"]]
            source_files = []
            for name in ("source_srt", "source_mapping"):
                file = Path(source[name])
                if not file.is_absolute():
                    file = manifest_path.parent / file
                source_files.append({"path": str(file.resolve()), "sha256": source[name + "_sha256"]})
            result[pair["pair_key"]] = _dedupe(shared + masters + source_files + chains + phase)
    return result


def _barrier(root: Path) -> tuple[dict, dict, helper.AuthenticatedFrame, dict, dict]:
    """Full external/native authentication once at each lifecycle boundary."""
    root = _root(root)
    common = _read(root / "common/seal.json")
    if common.get("schema") != "f8-root-common-inventory-v1":
        raise IntegrityDrift("common seal schema differs")
    _exact_inventory(root, common["files"], ["common/"], excluded={"common/seal.json"})
    context = _read(root / "common/context.json")
    if (context.get("schema") != VERSION or context["implementation"] != implementation()
            or context["command_config"] != _command_config() or context["allowed_stage_prefixes"] != PREFIXES):
        raise IntegrityDrift("current executed code/command surface differs from immutable preparation")
    for name, pointer in context["implementation"].items():
        if (root / f"common/implementation/{name}.py").read_bytes() != _pointer(pointer).read_bytes():
            raise IntegrityDrift("captured implementation differs from executed code")
    registration = _registration(context["registration"], context["registration"]["sha256"])
    frame = _load_frame(registration)
    plan, protocol = helper._plan(frame, context["root_plan"], context["root_plan"]["sha256"],
                                  context["protocol"]["sha256"])
    if frame._hash != context["frame_sha256"] or _native_proofs(registration) != context["native_cost_lineage"]:
        raise IntegrityDrift("native original frame/cost lineage changed")
    return context, registration, frame, plan, protocol


def _inputs(root: Path, job: dict, context: dict, protocol: dict) -> tuple[dict, dict, bytes, bytes]:
    if context["command_config"] != _command_config():
        raise IntegrityDrift("live command settings differ from immutable launch surface")
    if (job["stage"] not in STAGES or job["job_id"].split("/") != [job["stage"], Path(job["bundle"]).name]
            or job["bundle"] != f"bundles/{job['job_id']}"):
        raise IntegrityDrift("job descriptor escapes its stage/alias")
    directory = _local(root, job["bundle"])
    for name, pointer in job["artifacts"].items():
        if _pointer(pointer) != directory / name:
            raise IntegrityDrift("bundle pointer escapes its canonical path")
    if set(job["artifacts"]) != {"packet.json", "private.json", "prompt.txt", "schema.json"}:
        raise IntegrityDrift("bundle artifact set differs")
    for pointer in [*job["dependencies"], *context["implementation"].values(), *context["launch_dependencies"],
                    context["registration"], context["protocol"]]:
        _pointer(pointer)
    packet, private = _read(directory / "packet.json"), _read(directory / "private.json")
    prompt, schema = (directory / "prompt.txt").read_bytes(), (directory / "schema.json").read_bytes()
    helper.validate_packet(packet)
    if (packet["task_stage"] != job["stage"] or packet["pair_alias"] != Path(directory).name
            or private["pair_key"] != job["pair_key"]
            or prompt != helper.prompt(packet).encode("utf-8")
            or schema != integrity.canonical_bytes(helper.response_schema(job["stage"]))
            or helper.task_fingerprint(packet, context["protocol"], protocol) != job["fingerprint"]):
        raise IntegrityDrift("packet/prompt/schema/private identity differs from submitted task")
    return packet, private, prompt, schema


def _manifest(root: Path, stage: str, pointer: dict, expected: str, context: dict,
              frame: helper.AuthenticatedFrame, plan: dict, protocol: dict) -> dict:
    if _pointer(pointer, expected) != root / f"receipts/{stage}/preparation.json":
        raise AdmissionBlocked("stage preparation pointer is outside the canonical stage")
    value = _read(_pointer(pointer))
    if (value.get("schema") != "f8-root-stage-preparation-v1" or value["stage"] != stage
            or value["common"] != _identity(root / "common/seal.json") or value["expected_job_slots"] != 144
            or value["maximum_attempts"] != 2):
        raise AdmissionBlocked("stage denominator/settings differ")
    pairs, planned = {p["pair_key"]: p for p in frame._data["pairs"]}, {p["pair_key"]: p for p in plan["pairs"]}
    expected_slots = [{"pair_key": p["pair_key"], "job_id": planned[p["pair_key"]][
        "evidence_job_id" if stage == "evidence" else "review_job_id"],
        "status": "scheduled" if p["mechanically_eligible"] else "mechanical_unknown"} for p in frame._data["pairs"]]
    if value["expected_slots"] != expected_slots:
        raise IntegrityDrift("stage lost fixed pair/slot identity")
    jobs = {j["pair_key"]: j for j in value["jobs"]}
    if len(jobs) != len(value["jobs"]) or set(jobs) != {k for k, p in pairs.items() if p["mechanically_eligible"]}:
        raise IntegrityDrift("stage jobs differ from all mechanically eligible pairs")
    dependencies = _dependencies(frame, _registration(context["registration"], context["registration"]["sha256"]),
                                 context["native_cost_lineage"])
    for key, job in jobs.items():
        packet, private, _, _ = _inputs(root, job, context, protocol)
        item = planned[key]
        base, base_private = helper._packet(pairs[key], frame._hash, item["anonymous_alias"], tuple(item["phase_order"]))
        if stage == "evidence":
            if packet != base or private != base_private:
                raise IntegrityDrift("pure packet differs from authenticated public projection")
            if job["dependencies"] != dependencies[key]:
                raise IntegrityDrift("evidence direct native dependency whitelist differs")
        else:
            first, proof = _opinion(root, _read(root / "receipts/evidence/preparation.json"), key, context, protocol)
            derived, mapping = helper.build_review_packet(base, first)
            if packet != derived or private != {**base_private, "hypothesis_mapping": mapping}:
                raise IntegrityDrift("review packet is not the exact neutral first-opinion projection")
            prior = _read(root / "receipts/hypothesis_review/prior-stage.json")["evidence_seal"]
            if job["dependencies"] != _dedupe(dependencies[key] + _opinion_dependencies(proof) + [prior]):
                raise IntegrityDrift("hypothesis review dependency whitelist differs")
    return value


def _state(root: Path, job: dict, protocol: dict, status: str = "not_run") -> dict:
    settings = protocol["transport_settings"]
    return {"schema": VERSION, "job_id": job["job_id"], "profile": helper.PROFILE,
            "fingerprint": job["fingerprint"], "requested_model": settings["model"],
            "requested_effort": settings["effort"], "cli_version": settings["cli_version"],
            "status": status, "attempts": [], "classification_adjudication_jobs": 0,
            "response": str(_local(root, f"responses/{job['job_id']}.json"))}


def _attempts(root: Path, job: dict, state: dict, prompt: bytes, schema: bytes) -> None:
    history = state.get("attempts", [])
    if len(history) > 2 or [a.get("attempt") for a in history] != list(range(1, len(history) + 1)):
        raise IntegrityDrift("attempt history is not contiguous and bounded")
    for record in history:
        directory = _local(root, f"execution/{job['job_id']}/attempt-{record['attempt']}")
        for name, expected in (("prompt.txt", prompt), ("schema.json", schema)):
            if (directory / name).read_bytes() != expected:
                raise IntegrityDrift("attempt submitted prompt/schema bytes changed")
        stdin = directory / "stdin.bin"
        if stdin.exists():
            if stdin.read_bytes() != prompt or record.get("stdin_sha256") not in {None, integrity.sha(prompt)}:
                raise IntegrityDrift("native stdin bytes changed, including newline encoding")
        elif record.get("native_root_pid") or record.get("status") == "succeeded":
            raise IntegrityDrift("launched attempt is missing retained raw stdin")
        for name in ("stdout.jsonl", "stderr.txt", "last-message.txt"):
            if record.get(name + "_sha256") is not None and _sha(directory / name) != record[name + "_sha256"]:
                raise IntegrityDrift("attempt raw evidence changed")
        for name in ("stdout.jsonl", "stderr.txt"):
            if record.get(name.split(".")[0] + "_sha256") is not None and _sha(directory / name) != record[name.split(".")[0] + "_sha256"]:
                raise IntegrityDrift("attempt transport bytes changed")


def _accepted(root: Path, job: dict, context: dict, protocol: dict) -> tuple[dict | None, dict]:
    packet, _, prompt, schema = _inputs(root, job, context, protocol)
    ledger = _local(root, f"execution/{job['job_id']}/job.json")
    state = _read(ledger)
    expected = _state(root, job, protocol)
    if any(state.get(name) != expected[name] for name in (
            "job_id", "profile", "fingerprint", "requested_model", "requested_effort", "cli_version", "response")):
        raise IntegrityDrift("terminal ledger identity/canonical response path differs from exact admitted job")
    _attempts(root, job, state, prompt, schema)
    return helper.read_accepted_response(packet, _identity(ledger), registered_ledger_sha256=_sha(ledger),
        expected_fingerprint=job["fingerprint"], expected_job_id=job["job_id"], expected_settings=protocol["transport_settings"])


def _opinion(root: Path, manifest: dict, key: str, context: dict, protocol: dict) -> tuple[dict | None, dict]:
    job = next(j for j in manifest["jobs"] if j["pair_key"] == key)
    return _accepted(root, job, context, protocol)


def _run_job(root: Path, job: dict, context: dict, protocol: dict, *, execute: Callable,
             timeout: float, launch: dict, stop: threading.Event, resume_drained: bool = False,
             maximum_attempts: int = 2, lease: dict | None = None,
             resume_dependencies: list[dict] | None = None) -> dict:
    """Internal callback seam for offline tests; public dispatch fixes native.execute."""
    if maximum_attempts not in {1, 2}:
        raise AdmissionBlocked("fresh logical job must have one or two bounded attempts")
    packet, _, prompt, schema = _inputs(root, job, context, protocol)
    for pointer in resume_dependencies or []:
        _pointer(pointer)
    folder = _local(root, f"execution/{job['job_id']}")
    ledger = folder / "job.json"
    state = _state(root, job, protocol)
    if ledger.exists():
        previous = _read(ledger)
        for name in ("job_id", "fingerprint", "profile", "requested_model", "requested_effort", "cli_version", "response"):
            if previous.get(name) != state[name]:
                raise IntegrityDrift("resume terminal identity differs")
        _attempts(root, job, previous, prompt, schema)
        if previous["status"] == "succeeded":
            _accepted(root, job, context, protocol)
            return {**previous, "resumed": True}
        if previous["status"] not in {"not_run", "judge_failed"}:
            raise IntegrityDrift("unrecognized root ledger state cannot be repaired")
        state = previous
        if len(state["attempts"]) > maximum_attempts:
            raise IntegrityDrift("stored attempts exceed admitted job bound")
        if state.get("terminal_no_retry") or len(state["attempts"]) == maximum_attempts:
            return {**state, "resumed": True}
        if state["attempts"] and not resume_drained:
            raise AdmissionBlocked("resuming interrupted/failed attempts requires explicit prior native drain")
    for number in range(len(state["attempts"]) + 1, maximum_attempts + 1):
        _inputs(root, job, context, protocol)
        _pointer(launch)
        for pointer in resume_dependencies or []:
            _pointer(pointer)
        if stop.is_set():
            break
        attempt = folder / f"attempt-{number}"
        attempt.mkdir(parents=True, exist_ok=False)
        _new(attempt / "prompt.txt", prompt)
        _new(attempt / "schema.json", schema)
        record = {"attempt": number, "started_at": transport.utc(), "status": "interrupted",
                  "launch": deepcopy(launch), "input_bytes_sha256": integrity.sha(prompt),
                  "output_tokens": None, "input_tokens": None, "unknown_usage_reason": "not observed yet"}
        if lease is not None:
            record.update(deepcopy(lease))
        state["attempts"].append(record)
        state["status"] = "judge_failed"
        _live(ledger, state)
        started = time.perf_counter()
        # The CLI sees only a scratch schema, the source/self-output prompt and
        # its own raw result path. Custody private mappings never enter cwd.
        with tempfile.TemporaryDirectory(prefix="f8-root-cli-", dir=root.parent) as scratch:
            cwd = Path(scratch)
            schema_path, raw = cwd / "response-schema.json", attempt / "last-message.txt"
            schema_path.write_bytes(schema)
            args = transport.command(protocol["transport_settings"]["executable"], cwd, schema_path, raw)
            _new(attempt / "invocation.json", {"argv": args, "cwd": str(cwd), "launch": launch,
                 "prompt_sha256": integrity.sha(prompt), "schema_sha256": integrity.sha(schema),
                 "fresh_session": True, "tool_policy": "disabled"})
            try:
                result = execute(args, prompt.decode("utf-8"), cwd, attempt, timeout)
            except BaseException:
                record["elapsed_seconds"] = time.perf_counter() - started
                for name in ("stdin.bin", "stdout.jsonl", "stderr.txt", "last-message.txt"):
                    if (attempt / name).exists():
                        record[name + "_sha256"] = _sha(attempt / name)
                state["reason"] = "callback interrupted; native drain and external admission required before resume"
                _live(ledger, state)
                raise
            record.update(deepcopy(result), elapsed_seconds=time.perf_counter() - started,
                          status="failed", ended_at=transport.utc())
            if lease is not None and any(record.get(key) != value for key, value in lease.items()):
                state.update(terminal_no_retry=True, global_stop="native_lease_identity_drift")
                stop.set()
                _live(ledger, state)
                raise IntegrityDrift("callback returned a different custody native lease")
            try:
                # Run for EVERY return code before classifying retry eligibility.
                _inputs(root, job, context, protocol)
                _pointer(launch)
                for pointer in resume_dependencies or []:
                    _pointer(pointer)
                if schema_path.read_bytes() != schema:
                    raise IntegrityDrift("actual submitted schema changed during callback")
                for name, expected in (("prompt.txt", prompt), ("schema.json", schema)):
                    if (attempt / name).read_bytes() != expected:
                        raise IntegrityDrift("actual submitted prompt/schema bytes changed")
                stdin = attempt / "stdin.bin"
                if stdin.exists() and stdin.read_bytes() != prompt:
                    raise IntegrityDrift("actual submitted raw stdin differs, including Windows CRLF")
                if result.get("native_root_pid") and not stdin.exists():
                    raise IntegrityDrift("native launched process has no exact raw stdin")
            except (ValueError, OSError) as exc:
                record["failure_class"] = "integrity_drift"
                state.update(terminal_no_retry=True, global_stop="integrity_drift", reason=str(exc))
                stop.set()
                _live(ledger, state)
                raise IntegrityDrift(str(exc)) from exc
        for name in ("stdin.bin", "stdout.jsonl", "stderr.txt", "last-message.txt"):
            path = attempt / name
            if path.exists():
                record[name + "_sha256"] = _sha(path)
        record.update(stdout_sha256=record.get("stdout.jsonl_sha256"), stderr_sha256=record.get("stderr.txt_sha256"),
                      stdin_sha256=record.get("stdin.bin_sha256"),
                      unknown_usage_reason="CLI usage events retained; no inferred tokens or currency")
        failure = None
        if _schema_failure(attempt, result):
            failure = "invalid_json_schema"
            state.update(terminal_no_retry=True, global_stop=failure)
            stop.set()
        elif (result.get("returned_models", []) not in ([], [protocol["model"]])
              or result.get("returned_efforts", []) not in ([], [protocol["effort"]]) or result.get("tool_events", [])):
            failure = "transport_identity_or_tools"
            state["terminal_no_retry"] = True
        elif result.get("native_root_pid") and (result.get("native_drain_proven") is not True
                or result.get("native_active_processes_after_drain") != 0
                or result.get("containment") != "suspended-assign-resume-kill-on-close-job"):
            failure = "native_integrity"
            state.update(terminal_no_retry=True, global_stop=failure)
            stop.set()
        elif result.get("transport_status") != "completed" or result.get("returncode") != 0:
            failure = "transport"
        elif not raw.exists():
            failure = "format"
        else:
            try:
                value = _read(raw)
                _shape(value, helper.response_schema(job["stage"]))
            except (ValueError, KeyError, TypeError):
                failure = "format"
            else:
                try:
                    helper.validate_response(packet, value)
                except (ValueError, KeyError, TypeError):
                    failure = "source_quote_coverage_or_identity"
                    state["terminal_no_retry"] = True
                else:
                    if (result.get("native_drain_proven") is not True or result.get("native_active_processes_after_drain") != 0
                            or result.get("containment") != "suspended-assign-resume-kill-on-close-job" or not (attempt / "stdin.bin").exists()):
                        failure = "native_integrity"
                        state.update(terminal_no_retry=True, global_stop=failure)
                        stop.set()
                    else:
                        try:
                            accepted = integrity.accept_response(raw, Path(state["response"]),
                                lambda data: helper.validate_response(packet, data))
                        except (ValueError, OSError) as exc:
                            state.update(terminal_no_retry=True, global_stop="integrity_drift", reason=str(exc))
                            stop.set()
                            _live(ledger, state)
                            raise IntegrityDrift(str(exc)) from exc
                        state.update(accepted, status="succeeded")
                        record["status"] = "succeeded"
        record["failure_class"] = failure
        if failure:
            record["access_failure"] = scheduling.classify_access_failure(attempt, record)
            state["reason"] = failure
        _live(ledger, state)
        if state["status"] == "succeeded" or state.get("terminal_no_retry"):
            break
    _live(ledger, state)
    return state


def _seal(root: Path, stage: str, pointer: dict, expected: str) -> dict:
    if _pointer(pointer, expected) != root / f"stage-seals/{stage}.json":
        raise IntegrityDrift("stage seal must reside outside its stage prefix union")
    value = _read(_pointer(pointer))
    if value.get("schema") != "f8-root-stage-terminal-inventory-v1" or value["stage"] != stage:
        raise IntegrityDrift("stage terminal seal schema differs")
    _exact_inventory(root, value["files"], PREFIXES[stage])
    return value


def _known_files(root: Path) -> None:
    allowed = ["common/", "stage-seals/", "private/", *[p for prefixes in PREFIXES.values() for p in prefixes]]
    for row in _inventory(root, excluded={".judge-scheduler.lock", "root-terminal-inventory.json"}):
        if not any(row["path"].startswith(prefix) for prefix in allowed):
            raise IntegrityDrift("root contains undeclared artifact family")
        if row["path"].startswith("stage-seals/") and row["path"] not in {f"stage-seals/{s}.json" for s in STAGES}:
            raise IntegrityDrift("root contains undeclared stage seal")
        if row["path"].startswith("private/") and row["path"] not in {"private/snapshot.json", "private/cost-provenance.json", "private/closure.json"}:
            raise IntegrityDrift("root contains undeclared private final artifact")


def _resume_receipts(admission: dict) -> list[dict]:
    """V1 retains its one-lease ABI; V2 explicitly retains cumulative leases."""
    if admission["schema"] == "f8-root-stage-external-admission-v1":
        pointer = admission["resume_drain_receipt"]
        return [] if pointer is None else [pointer]
    receipts = admission["resume_drain_receipts"]
    if not isinstance(receipts, list):
        raise AdmissionBlocked("cumulative resume drains must be an explicit list")
    return receipts


def _admission(root: Path, stage: str, pointer: dict, expected: str, context: dict,
               registration: dict, preparation: dict, *, dispatch: bool = True) -> dict:
    path = _pointer(pointer, expected)
    if path.is_relative_to(root):
        raise AdmissionBlocked("external admission must remain outside the immutable root")
    value = _read(path)
    schema = value.get("schema")
    if schema not in {"f8-root-stage-external-admission-v1", "f8-root-stage-external-admission-v2"}:
        raise AdmissionBlocked("unknown external stage admission version")
    drain_key = "resume_drain_receipt" if schema.endswith("-v1") else "resume_drain_receipts"
    helper._keys(value, {"schema", "stage", "root", "common", "preparation", "implementation", "registration",
                        "protocol", "custody_root", "terminal_receipt", "workers", "timeout_seconds",
                        "maximum_attempts", drain_key, "resume_inventory", "compatibility_probe"}, "stage admission")
    if (value["stage"] != stage
            or _root(Path(value["root"])) != root or value["common"] != _identity(root / "common/seal.json")
            or value["implementation"] != context["implementation"] or value["registration"] != context["registration"]
            or value["protocol"] != context["protocol"] or value["maximum_attempts"] != 2
            or _root(Path(value["custody_root"])) != _root(Path(registration["custody_root"]))
            or value["terminal_receipt"] != registration["terminal_receipt"]
            or type(value["workers"]) is not int or not 1 <= value["workers"] <= 6
            or type(value["timeout_seconds"]) not in {int, float} or not math.isfinite(value["timeout_seconds"])
            or value["timeout_seconds"] <= 0):
        raise AdmissionBlocked("external stage admission changes fixed inputs/global custody/limits")
    _pointer(value["preparation"])
    if _read(_pointer(value["preparation"])) != preparation:
        raise IntegrityDrift("admission preparation differs from current stage")
    _pointer(value["terminal_receipt"])
    receipts = _resume_receipts(value)
    for receipt in receipts:
        _drain(receipt, registration)
    if (not receipts) != (value["resume_inventory"] is None):
        raise AdmissionBlocked("unsealed resume requires both externally registered prior native drain and exact inventory")
    if value["resume_inventory"] is not None:
        resume = _read(_pointer(value["resume_inventory"]))
        if resume.get("schema") != "f8-root-unsealed-stage-resume-inventory-v1" or resume.get("stage") != stage:
            raise IntegrityDrift("resume inventory stage identity differs")
        if dispatch:
            _exact_inventory(root, resume["files"], PREFIXES[stage])
        else:
            snapshot_root = root / f"receipts/{stage}/resume-snapshots/{pointer['sha256']}"
            if (snapshot_root / "inventory.json").read_bytes() != _pointer(value["resume_inventory"]).read_bytes():
                raise IntegrityDrift("retained pre-resume inventory differs from external registration")
            for row in resume["files"]:
                path = _local(root, row["path"])
                if row["path"].startswith(f"execution/{stage}/") and path.name == "job.json":
                    path = snapshot_root / path.parent.name / "job.json"
                if _sha(path) != row["sha256"]:
                    raise IntegrityDrift("retained pre-resume bytes changed")
        # A positive unrelated lease cannot authorize a retry. On sealing, use
        # the retained pre-resume ledgers rather than subsequently appended calls.
        prior_states = []
        for row in resume["files"]:
            path = _local(root, row["path"])
            if row["path"].startswith(f"execution/{stage}/") and path.name == "job.json":
                if not dispatch:
                    path = snapshot_root / path.parent.name / "job.json"
                prior_states.append(_read(path))
        _drain_lineage(receipts, registration, prior_states)
    elif dispatch:
        # Fail before the worker pool can dispatch another job while an existing
        # attempt awaits its own registered drain and immutable resume inventory.
        for job in preparation["jobs"]:
            ledger = _local(root, f"execution/{job['job_id']}/job.json")
            if ledger.exists() and _read(ledger).get("attempts"):
                raise AdmissionBlocked("every prior attempt requires pre-dispatch native drain lineage")
    if not dispatch:
        return value
    if registration["kind"] != "actual":
        raise AdmissionBlocked("full synthetic fixtures cannot authorize real native model calls")
    probe = validate_compatibility_probe(value["compatibility_probe"], registered_sha256=value["compatibility_probe"]["sha256"])
    if (probe.get("schema") != "f8-root-synthetic-compatibility-probe-v1" or probe.get("compatible") is not True
            or probe.get("implementation") != implementation() or probe.get("actual_corpus_used") is not False
            or probe.get("jobs") != 1 or probe.get("maximum_attempts") != 1
            or probe.get("profile") != helper.PROFILE):
        raise AdmissionBlocked("separately authorized one-job native compatibility probe is required")
    return value


def run_stage(root: Path, stage: str, *, admission_pointer: dict, registered_admission_sha256: str,
              custody_guard: native.CustodyGuard, registered_stage_seal: dict | None = None) -> dict:
    """Dispatch one admitted stage under custody's already-held shared ROOT lease.

    This API does not create a guard, invoke a semantic judge, or finalize upstream
    side discovery. Sealed-stage resume authenticates and returns with zero calls.
    """
    if stage not in STAGES:
        raise ValueError("unknown root stage")
    root = _root(root)
    with transport.run_lock(root):
        context, registration, frame, plan, protocol = _barrier(root)
        _known_files(root)
        admission = _read(_pointer(admission_pointer, registered_admission_sha256))
        manifest = _manifest(root, stage, admission["preparation"], admission["preparation"]["sha256"], context, frame, plan, protocol)
        seal_path = root / f"stage-seals/{stage}.json"
        if seal_path.exists():
            if registered_stage_seal is None:
                raise AdmissionBlocked("sealed resume requires external stage seal registration")
            seal = _seal(root, stage, registered_stage_seal, registered_stage_seal["sha256"])
            if seal["preparation"] != admission["preparation"] or seal["admission"] != admission_pointer:
                raise IntegrityDrift("sealed resume uses different external stage admission")
            _drain_lineage(seal["native_drain_lineage"], registration,
                [_read(_pointer(p)) for p in seal["ledgers"]])
            for job in manifest["jobs"]:
                _accepted(root, job, context, protocol)
            return {"schema": VERSION, "stage": stage, "resumed": True, "root_calls": 0, "seal": _identity(seal_path)}
        admitted = _admission(root, stage, admission_pointer, registered_admission_sha256, context, registration, manifest)
        _inherited_stop(root)
        for job in manifest["jobs"]:
            ledger = _local(root, f"execution/{job['job_id']}/job.json")
            if ledger.exists() and _read(ledger).get("global_stop"):
                raise AdmissionBlocked("inherited invalid schema/integrity stop cannot be retried under the same frozen inputs")
        if (type(custody_guard) is not native.CustodyGuard or not custody_guard.entered or custody_guard.closing
                or custody_guard.root != _root(Path(registration["custody_root"]))
                or custody_guard.owner != "evaluation_custodian" or custody_guard.workers != admitted["workers"]
                or custody_guard.implementation_sha256 != context["implementation"]["native_dispatch"]["sha256"]
                or custody_guard.terminal_receipt != _pointer(admitted["terminal_receipt"])
                or custody_guard.terminal_sha256 != admitted["terminal_receipt"]["sha256"]
                or native._ACTIVE_GUARD is not custody_guard):
            raise AdmissionBlocked("only custody's genuine existing global-six native guard may dispatch")
        if stage == "hypothesis_review":
            review_meta = _read(root / "receipts/hypothesis_review/prior-stage.json")
            _seal(root, "evidence", review_meta["evidence_seal"], review_meta["evidence_seal"]["sha256"])
        stop = threading.Event()
        circuit = scheduling.AccessCircuit(transport.utc())
        jobs = manifest["jobs"]
        next_index, states, fatal = 0, [], None
        started = time.perf_counter()
        resume_files = (_read(_pointer(admitted["resume_inventory"]))["files"]
                        if admitted["resume_inventory"] is not None else [])
        if admitted["resume_inventory"] is not None:
            snapshot_root = root / f"receipts/{stage}/resume-snapshots/{admission_pointer['sha256']}"
            _new(snapshot_root / "inventory.json", _pointer(admitted["resume_inventory"]).read_bytes())
            for row in resume_files:
                path = _local(root, row["path"])
                if row["path"].startswith(f"execution/{stage}/") and path.name == "job.json":
                    _new(snapshot_root / path.parent.name / "job.json", path.read_bytes())
        with ThreadPoolExecutor(max_workers=admitted["workers"]) as pool:
            pending = {}
            def refill():
                nonlocal next_index
                while not stop.is_set() and not circuit.tripped and len(pending) < admitted["workers"] and next_index < len(jobs):
                    job = jobs[next_index]
                    next_index += 1
                    pending[pool.submit(_run_job, root, job, context, protocol, execute=native.execute,
                        timeout=admitted["timeout_seconds"], launch=admission_pointer, stop=stop,
                        resume_drained=bool(_resume_receipts(admitted)),
                        lease={"custody_token": custody_guard.token, "custody_receipt": str(custody_guard.owner_record),
                               "native_dispatch_sha256": custody_guard.implementation_sha256,
                               "custody_workers_reserved": custody_guard.workers},
                        resume_dependencies=[{"path": str(_local(root, r["path"])), "sha256": r["sha256"]}
                            for r in resume_files if r["path"].startswith(f"execution/{job['job_id']}/attempt-")])] = job
            refill()
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.pop(future)
                    try:
                        state = future.result()
                    except BaseException as exc:
                        fatal = exc
                        stop.set()
                    else:
                        states.append(state)
                        circuit.observe(state)
                refill()
        for job in jobs[next_index:]:
            ledger = _local(root, f"execution/{job['job_id']}/job.json")
            if not ledger.exists():
                state = _state(root, job, protocol)
                state["reason"] = "stage stopped before dispatch; explicit unknown"
                _live(ledger, state)
        result = {"schema": VERSION, "stage": stage, "admission": admission_pointer,
                  "preparation": admitted["preparation"], "expected_job_slots": 144,
                  "elapsed_seconds": time.perf_counter() - started, "access_circuit": circuit.metadata(),
                  "global_stop": stop.is_set(), "native_guard_token": custody_guard.token,
                  "native_drain_pending": True, "automatic_sealing": False}
        _new(root / f"receipts/{stage}/invocations/{admission_pointer['sha256']}.json", result)
        if fatal is not None:
            raise fatal
        return result


def _opinion_dependencies(proof: dict) -> list[dict]:
    return [proof[name] for name in ("ledger", "accepted_raw", "accepted_canonical", "accepted_snapshot") if name in proof]


def _inherited_stop(root: Path) -> None:
    # Bounded metadata-only ledger scan, never raw transcripts or judge reasons.
    for stage in STAGES:
        prepared = root / f"receipts/{stage}/preparation.json"
        if not prepared.exists():
            continue
        for job in _read(prepared)["jobs"]:
            ledger = _local(root, f"execution/{job['job_id']}/job.json")
            if ledger.exists() and _read(ledger).get("global_stop"):
                raise AdmissionBlocked("root-wide inherited schema/native/integrity stop requires a NEW protocol and preparation")


def _stage_files(root: Path, manifest: dict) -> None:
    """No unexpected alias, attempt or executable artifacts may be sealed."""
    stage = manifest["stage"]
    jobs = {j["job_id"]: j for j in manifest["jobs"]}
    for row in _inventory(root, PREFIXES[stage]):
        parts = row["path"].split("/")
        family = parts[0]
        if family in {"bundles", "responses", "execution"}:
            alias = parts[2].removesuffix(".json") if family == "responses" else parts[2]
            key = stage + "/" + alias
            if key not in jobs:
                raise IntegrityDrift("stage contains unregistered alias artifacts")
            if family == "bundles" and (len(parts) != 4 or parts[3] not in jobs[key]["artifacts"]):
                raise IntegrityDrift("bundle contains extra files")
            if family == "responses" and (len(parts) != 3 or not parts[2].endswith(".json")):
                raise IntegrityDrift("response path is not canonical")
            if family == "execution":
                valid = (len(parts) == 4 and parts[3] == "job.json" or len(parts) == 5
                         and parts[3] in {"attempt-1", "attempt-2"}
                         and parts[4] in {"prompt.txt", "schema.json", "stdin.bin", "stdout.jsonl", "stderr.txt",
                                          "last-message.txt", "invocation.json", "accepted-canonical.json"})
                if not valid:
                    raise IntegrityDrift("execution contains extra attempt/artifact")
        elif family == "receipts":
            valid = (len(parts) == 3 and parts[2] in {"preparation.json", "prior-stage.json"}
                     or len(parts) == 4 and parts[2] == "invocations" and re.fullmatch(r"[0-9a-f]{64}\.json", parts[3])
                     or len(parts) in {5, 6} and parts[2] == "resume-snapshots" and re.fullmatch(r"[0-9a-f]{64}", parts[3])
                     and (len(parts) == 5 and parts[4] == "inventory.json" or len(parts) == 6 and parts[5] == "job.json"
                          and stage + "/" + parts[4] in jobs))
            if not valid:
                raise IntegrityDrift("stage receipt contains undeclared artifact")


def _drain_lineage(receipts: list[dict], registration: dict, states: list[dict]) -> list[dict]:
    lineage = _dedupe(receipts)
    tokens = {}
    for pointer in lineage:
        _drain(pointer, registration)
        value = _read(_pointer(pointer))
        if value.get("token") in tokens:
            raise IntegrityDrift("native drained lease token must be unique")
        tokens[value.get("token")] = (pointer, value)
    for state in states:
        for record in state["attempts"]:
            # Offline fixtures are explicitly separated from native authority.
            if registration.get("kind") == "synthetic" and "custody_token" not in record:
                continue
            token = record.get("custody_token")
            if token not in tokens or not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
                raise AdmissionBlocked("every attempted native lease requires its own externally retained drained receipt")
            pointer, value = tokens[token]
            if (Path(record.get("custody_receipt", "")).resolve() != _pointer(pointer)
                    or record.get("native_dispatch_sha256") != value["module_sha256"]
                    or record.get("custody_workers_reserved") != value["workers_reserved"]):
                raise IntegrityDrift("attempt native lease is not the supplied drained owner receipt")
    return lineage


def seal_stage(root: Path, stage: str, *, admission_pointer: dict, registered_admission_sha256: str,
               drained_receipt: dict, prior_drained_receipts: list[dict] | None = None) -> dict:
    """Offline post-drain seal; external registration is a separate custody step."""
    if stage not in STAGES:
        raise ValueError("unknown root stage")
    root = _root(root)
    with transport.run_lock(root):
        context, registration, frame, plan, protocol = _barrier(root)
        _drain(drained_receipt, registration)
        admission = _read(_pointer(admission_pointer, registered_admission_sha256))
        manifest = _manifest(root, stage, admission["preparation"], admission["preparation"]["sha256"], context, frame, plan, protocol)
        _admission(root, stage, admission_pointer, registered_admission_sha256, context, registration, manifest, dispatch=False)
        _known_files(root)
        _stage_files(root, manifest)
        ledgers, states = [], []
        for job in manifest["jobs"]:
            _, proof = _accepted(root, job, context, protocol)
            ledgers.append(proof["ledger"])
            states.append(_read(_pointer(proof["ledger"])))
        lineage = _drain_lineage([drained_receipt, *(prior_drained_receipts or [])], registration, states)
        value = {"schema": "f8-root-stage-terminal-inventory-v1", "stage": stage,
                 "common": _identity(root / "common/seal.json"), "preparation": admission["preparation"],
                 "admission": deepcopy(admission_pointer), "native_drain_receipt": drained_receipt,
                 "expected_job_slots": 144, "classification_adjudication_jobs": 0,
                 "native_drain_lineage": lineage, "ledgers": ledgers, "files": _inventory(root, PREFIXES[stage])}
        pointer = _new(root / f"stage-seals/{stage}.json", value)
        return {"seal": pointer, "expected_job_slots": 144, "automatic_dispatch": False,
                "requires_external_registration": True}


def prepare_hypothesis_review(root: Path, *, evidence_seal: dict, registered_evidence_seal_sha256: str) -> dict:
    """Prepare all eligible second jobs, including when first-stage format failed."""
    started = time.perf_counter()
    root = _root(root)
    with transport.run_lock(root):
        context, registration, frame, plan, protocol = _barrier(root)
        _inherited_stop(root)
        seal = _seal(root, "evidence", evidence_seal, registered_evidence_seal_sha256)
        _drain(seal["native_drain_receipt"], registration)
        first_manifest = _manifest(root, "evidence", seal["preparation"], seal["preparation"]["sha256"], context, frame, plan, protocol)
        _stage_files(root, first_manifest)
        _drain_lineage(seal["native_drain_lineage"], registration,
            [_read(_local(root, f"execution/{j['job_id']}/job.json")) for j in first_manifest["jobs"]])
        if (root / "receipts/hypothesis_review/preparation.json").exists():
            raise IntegrityDrift("review preparation already frozen; do not rewrite derived hypotheses")
        planned = {p["pair_key"]: p for p in plan["pairs"]}
        dependencies = _dependencies(frame, registration, context["native_cost_lineage"])
        jobs, slots = [], []
        for pair in frame._data["pairs"]:
            key, item = pair["pair_key"], planned[pair["pair_key"]]
            slots.append({"pair_key": key, "job_id": item["review_job_id"],
                          "status": "scheduled" if pair["mechanically_eligible"] else "mechanical_unknown"})
            if not pair["mechanically_eligible"]:
                continue
            packet, private = helper._packet(pair, frame._hash, item["anonymous_alias"], tuple(item["phase_order"]))
            first, proof = _opinion(root, first_manifest, key, context, protocol)
            review, mapping = helper.build_review_packet(packet, first)
            jobs.append(_bundle(root, review, {**private, "hypothesis_mapping": mapping}, context["protocol"], protocol,
                _dedupe(dependencies[key] + _opinion_dependencies(proof) + [evidence_seal])))
        _new(root / "receipts/hypothesis_review/prior-stage.json", {"schema": "f8-root-prior-stage-binding-v1",
             "evidence_seal": evidence_seal, "hypothesis_review_not_independent_discovery": True})
        manifest = {"schema": "f8-root-stage-preparation-v1", "stage": "hypothesis_review", "common": _identity(root / "common/seal.json"),
                    "jobs": jobs, "expected_slots": slots, "expected_job_slots": 144, "maximum_attempts": 2,
                    "prepare_seconds": time.perf_counter() - started}
        pointer = _new(root / "receipts/hypothesis_review/preparation.json", manifest)
        # Additions in the disjoint future prefix cannot invalidate first stage.
        _seal(root, "evidence", evidence_seal, registered_evidence_seal_sha256)
        return {"preparation": pointer, "expected_job_slots": 144, "automatic_dispatch": False,
                "requires_external_registration": True}


def _cost(root: Path, context: dict, manifests: list[dict], seals: list[dict], finish_seconds: float) -> dict:
    """Private cost provenance, with unavailable usage explicitly retained."""
    stages = []
    for manifest, seal in zip(manifests, seals):
        jobs = []
        for job in manifest["jobs"]:
            ledger = _local(root, f"execution/{job['job_id']}/job.json")
            state = _read(ledger)
            jobs.append({"job_id": job["job_id"], "pair_key": job["pair_key"], "status": state["status"],
                         "ledger": _identity(ledger), "attempts": [{key: deepcopy(a.get(key)) for key in (
                             "attempt", "status", "transport_status", "returncode", "failure_class", "elapsed_seconds",
                             "usage_events", "unknown_usage_reason", "stdin_sha256", "stdout_sha256", "stderr_sha256",
                             "native_drain_proven", "native_active_processes_after_drain", "launch")} for a in state["attempts"]]})
        invocations = [_identity(p) for p in sorted((root / f"receipts/{manifest['stage']}/invocations").glob("*.json"))]
        stages.append({"stage": manifest["stage"], "expected_slots": 144, "prepare_seconds": manifest["prepare_seconds"],
                       "invocations": invocations, "jobs": jobs, "native_drain_receipt": seal["native_drain_receipt"]})
    originals = [{"seed": p["root_binding"]["seed"], "proof": p["receipt"],
                  "run": p["root_binding"]["original_run"], "full_cost_count_once": p["root_binding"]["original_cost_identity"],
                  "trial": p["metadata"]["trial"], "generation_attempt_status": p["metadata"]["generation_attempt_status"]}
                 for p in context["native_cost_lineage"]]
    if len({p["full_cost_count_once"]["path"] for p in originals}) != 3:
        raise IntegrityDrift("original full trial cost identities must be three distinct runs counted once")
    admissions = [_read(_pointer(s["admission"])) for s in seals]
    registration = _registration(context["registration"], context["registration"]["sha256"])
    upstream = []
    for seed in helper.SEEDS:
        phase_root = _root(Path(registration["phase_roots"][str(seed)]))
        phase_seal = registration["phase_seals"][str(seed)]
        phase_jobs = []
        for file in _read(_pointer(phase_seal))["files"]:
            if file["path"].startswith("judge-execution/") and Path(file["path"]).name == "job.json":
                ledger = _identity(phase_root / file["path"])
                state = _read(_pointer(ledger))
                phase_jobs.append({"ledger": ledger, "job_id": state["job_id"], "status": state["status"],
                    "attempts": [{k: deepcopy(a.get(k)) for k in (
                        "attempt", "status", "transport_status", "returncode", "elapsed_seconds", "whole_attempt_seconds",
                        "usage_events", "input_tokens", "output_tokens", "stdout_sha256", "stderr_sha256")}
                        for a in state.get("attempts", [])]})
        upstream.append({"seed": seed, "expected_side_records": 96, "phase_seal": phase_seal,
                         "phase_run": _identity(phase_root / "run.json"), "jobs": phase_jobs,
                         "charged_once": True, "original_generation_recharged": False})
    return {"schema": "f8-root-private-cost-provenance-v1", "original_trials_count_once": originals,
            "new_generated_samples": 0, "standalone_flow_seconds": None, "standalone_flow_reason": "generation was already executed; reuse original complete trial cost",
            "stages": stages, "upstream_side_discovery_count_once": upstream,
            "compatibility_probes_count_once": _dedupe([a["compatibility_probe"] for a in admissions if a["compatibility_probe"] is not None]),
            "finish_validation_seconds": finish_seconds, "currency_cost": None,
            "currency_unknown_reason": "no price inference from token usage; all native logs and failures retained",
            "sealing_and_release_seconds": None, "sealing_unknown_reason": "external sealing/release command receipts are recorded outside the finally sealed root"}


def finish(root: Path, *, stage_seals: dict[str, dict], registered_stage_seal_sha256: dict[str, str],
           registered_terminal_inventory: dict | None = None, registered_existing_cost: dict | None = None) -> dict:
    """Rebuild the complete private 144-pair snapshot and then seal every file."""
    started = time.perf_counter()
    root = _root(root)
    if set(stage_seals) != set(STAGES) or set(registered_stage_seal_sha256) != set(STAGES):
        raise AdmissionBlocked("both externally registered terminal stage seals are required")
    with transport.run_lock(root):
        terminal_path = root / "root-terminal-inventory.json"
        if terminal_path.exists():
            if registered_terminal_inventory is None or _pointer(registered_terminal_inventory) != terminal_path:
                raise AdmissionBlocked("finished root requires external terminal registration for read-only resume")
            terminal = _read(_pointer(registered_terminal_inventory))
            _exact_inventory(root, terminal["files"], excluded={"root-terminal-inventory.json", ".judge-scheduler.lock"})
            closure = _read(_pointer(terminal["closure"]))
            if closure["stage_seals"] != stage_seals:
                raise IntegrityDrift("read-only finish uses different externally registered stage seals")
            _barrier(root)
            for stage in STAGES:
                seal = _seal(root, stage, stage_seals[stage], registered_stage_seal_sha256[stage])
                registration = _registration(_read(root / "common/context.json")["registration"],
                    _read(root / "common/context.json")["registration"]["sha256"])
                _drain_lineage(seal["native_drain_lineage"], registration,
                    [_read(_pointer(p)) for p in seal["ledgers"]])
            return {"terminal_inventory": registered_terminal_inventory, "snapshot": closure["snapshot"],
                    "cost": closure["cost"], "expected_pairs": 144, "expected_root_job_slots": 288,
                    "automatic_release": False, "resumed": True, "root_calls": 0}
        context, registration, frame, plan, protocol = _barrier(root)
        _known_files(root)
        seals, manifests = [], []
        for stage in STAGES:
            seal = _seal(root, stage, stage_seals[stage], registered_stage_seal_sha256[stage])
            _drain(seal["native_drain_receipt"], registration)
            manifest = _manifest(root, stage, seal["preparation"], seal["preparation"]["sha256"], context, frame, plan, protocol)
            _stage_files(root, manifest)
            _drain_lineage(seal["native_drain_lineage"], registration,
                [_read(_pointer(p)) for p in seal["ledgers"]])
            seals.append(seal)
            manifests.append(manifest)
        if _read(root / "receipts/hypothesis_review/prior-stage.json")["evidence_seal"] != stage_seals["evidence"]:
            raise IntegrityDrift("review parent seal differs from external final registration")
        bundles = {}
        for stage, manifest in zip(STAGES, manifests):
            for job in manifest["jobs"]:
                _, proof = _accepted(root, job, context, protocol)
                bundles.setdefault(job["pair_key"], {})["evidence_job" if stage == "evidence" else "review_job"] = {
                    "ledger": proof["ledger"], "registered_ledger_sha256": proof["ledger"]["sha256"],
                    "expected_fingerprint": job["fingerprint"], "expected_job_id": job["job_id"]}
        snapshot = helper.finalize_snapshot(frame, bundles, root_plan_pointer=context["root_plan"],
            registered_plan_sha256=context["root_plan"]["sha256"], registered_protocol_sha256=context["protocol"]["sha256"])
        snapshot_pointer = _new(root / "private/snapshot.json", snapshot)
        cost_path = root / "private/cost-provenance.json"
        elapsed = time.perf_counter() - started
        if cost_path.exists():
            if registered_existing_cost is None or _pointer(registered_existing_cost) != cost_path:
                raise AdmissionBlocked("partial finish recovery requires external registration of the existing immutable cost artifact")
            old_cost = _read(_pointer(registered_existing_cost))
            elapsed = old_cost["finish_validation_seconds"]
            if type(elapsed) not in {int, float} or not math.isfinite(elapsed) or elapsed < 0:
                raise IntegrityDrift("retained finish cost duration is invalid")
        cost_pointer = _new(cost_path, _cost(root, context, manifests, seals, elapsed))
        closure = _new(root / "private/closure.json", {"schema": "f8-root-private-closure-v1", "common": _identity(root / "common/seal.json"),
             "snapshot": snapshot_pointer, "snapshot_object_sha256": snapshot["snapshot_sha256"], "cost": cost_pointer,
             "stage_seals": stage_seals, "expected_pairs": 144, "expected_root_job_slots": 288,
             "development_pairs": 90, "withheld_pairs": 54, "classification_adjudication_jobs": 0})
        terminal = {"schema": "f8-root-whole-terminal-inventory-v1", "closure": closure,
                    "files": _inventory(root, excluded={"root-terminal-inventory.json", ".judge-scheduler.lock"})}
        final = _new(root / "root-terminal-inventory.json", terminal)
        return {"terminal_inventory": final, "snapshot": snapshot_pointer, "cost": cost_pointer,
                "expected_pairs": 144, "expected_root_job_slots": 288, "automatic_release": False,
                "requires_external_registration": True}


def release_development(root: Path, output: Path, *, terminal_inventory: dict,
                        registered_terminal_sha256: str, registered_snapshot_object_sha256: str) -> dict:
    """Authenticate privately, then create dev90 only outside the sealed root."""
    root, output = _root(root), _root(output)
    if output.is_relative_to(root):
        raise AdmissionBlocked("release and its registration must remain outside the finally sealed root")
    with transport.run_lock(root):
        path = _pointer(terminal_inventory, registered_terminal_sha256)
        if path != root / "root-terminal-inventory.json":
            raise IntegrityDrift("final terminal inventory is outside canonical root")
        terminal = _read(path)
        if terminal.get("schema") != "f8-root-whole-terminal-inventory-v1":
            raise IntegrityDrift("final terminal inventory schema differs")
        _exact_inventory(root, terminal["files"], excluded={"root-terminal-inventory.json", ".judge-scheduler.lock"})
        context, registration, frame, _, _ = _barrier(root)
        closure = _read(_pointer(terminal["closure"]))
        for stage, pointer in closure["stage_seals"].items():
            value = _seal(root, stage, pointer, pointer["sha256"])
            _drain(value["native_drain_receipt"], registration)
            _drain_lineage(value["native_drain_lineage"], registration,
                [_read(_pointer(p)) for p in value["ledgers"]])
        snapshot = _read(_pointer(closure["snapshot"]))
        released = helper.release_development(snapshot, frame, registered_snapshot_sha256=registered_snapshot_object_sha256)
        if len(released["records"]) != 90:
            raise IntegrityDrift("development release must contain exactly 90 registered pairs")
        # Do not copy private closure/cost/terminal totals into the public view.
        pointer = _new(output, released)
        _exact_inventory(root, terminal["files"], excluded={"root-terminal-inventory.json", ".judge-scheduler.lock"})
        return {"development_release": pointer, "released_pairs": 90, "withheld_pairs": 54,
                "global_aggregate_released": False, "root_calls": 0}


def prepare_compatibility_probe(root: Path, packet: dict, *, authorization: dict,
                                registered_authorization_sha256: str) -> dict:
    """Freeze one hand-authored deepest-stage packet; never dispatch here."""
    value = _read(_pointer(authorization, registered_authorization_sha256))
    helper._keys(value, {"schema", "profile", "root", "custody_root", "terminal_receipt", "cli_executable",
                        "transport_settings", "packet_sha256", "schema_sha256", "implementation",
                        "hand_authored_synthetic", "actual_corpus_used", "maximum_attempts", "workers",
                        "timeout_seconds"}, "single compatibility probe authorization")
    helper.validate_packet(packet)
    root = _root(root)
    if (value["schema"] != "f8-root-single-synthetic-probe-authorization-v1" or value["profile"] != helper.PROFILE
            or _root(Path(value["root"])) != root or _root(Path(value["custody_root"])).name != "evaluation-only"
            or value["implementation"] != implementation() or value["packet_sha256"] != helper.object_hash(packet)
            or value["schema_sha256"] != helper.object_hash(helper.response_schema("hypothesis_review"))
            or value["hand_authored_synthetic"] is not True or value["actual_corpus_used"] is not False
            or value["maximum_attempts"] != 1 or value["workers"] != 1 or packet["task_stage"] != "hypothesis_review"
            or type(value["timeout_seconds"]) not in {float, int} or not math.isfinite(value["timeout_seconds"]) or value["timeout_seconds"] <= 0):
        raise AdmissionBlocked("probe must be separately authorized one-job source-independent synthetic compatibility only")
    settings = value["transport_settings"]
    helper._keys(settings, {"cli_version", "executable", "surface", "model", "effort", "tool_policy", "fresh_session"}, "probe transport settings")
    if (settings["model"] != "gpt-6.1-sol" or settings["effort"] != "high" or settings["surface"] != "codex-cli"
            or settings["fresh_session"] is not True or settings["tool_policy"] != "disabled"
            or settings["executable"] != str(_pointer(value["cli_executable"])) or not settings["cli_version"]):
        raise AdmissionBlocked("probe transport identity differs")
    _pointer(value["terminal_receipt"])
    if _pointer(authorization).is_relative_to(root):
        raise AdmissionBlocked("probe authorization must be externally registered")
    root.mkdir(parents=True, exist_ok=False)
    protocol = {"schema": "f8-root-single-synthetic-probe-protocol-v1", "model": settings["model"], "effort": settings["effort"],
                "transport_settings": settings, "adapter_sha256": ADAPTER_SHA256,
                "frame_sha256": "synthetic-compatibility-only-no-native-frame"}
    protocol_pointer = _new(root / "protocol.json", protocol)
    context = {"implementation": implementation(), "command_config": _command_config(), "registration": authorization,
               "protocol": protocol_pointer, "launch_dependencies": [value["cli_executable"], value["terminal_receipt"]]}
    private = {"pair_key": "synthetic-compatibility-only", "no_real_quality_evidence": True}
    job = _bundle(root, packet, private, protocol_pointer, protocol)
    preparation = _new(root / "probe-preparation.json", {"schema": "f8-root-single-probe-preparation-v1", "authorization": authorization,
                    "context": context, "job": job, "expected_jobs": 1, "maximum_attempts": 1})
    return {"preparation": preparation, "automatic_dispatch": False, "no_real_quality_evidence": True}


def run_compatibility_probe(root: Path, *, preparation: dict, registered_preparation_sha256: str,
                            custody_guard: native.CustodyGuard) -> dict:
    """One separately authorized native job, sharing the original ROOT guard."""
    root = _root(root)
    with transport.run_lock(root):
        prepared = _read(_pointer(preparation, registered_preparation_sha256))
        if _pointer(preparation) != root / "probe-preparation.json" or prepared["expected_jobs"] != 1 or prepared["maximum_attempts"] != 1:
            raise AdmissionBlocked("single probe prepared identity differs")
        context, job = prepared["context"], prepared["job"]
        authority = _read(_pointer(prepared["authorization"]))
        if authority["implementation"] != implementation() or context["implementation"] != implementation():
            raise IntegrityDrift("probe executed code changed after registration")
        if (type(custody_guard) is not native.CustodyGuard or not custody_guard.entered or custody_guard.closing
                or native._ACTIVE_GUARD is not custody_guard or custody_guard.owner != "evaluation_custodian"
                or custody_guard.workers != 1 or custody_guard.root != _root(Path(authority["custody_root"]))
                or custody_guard.terminal_receipt != _pointer(authority["terminal_receipt"])
                or custody_guard.terminal_sha256 != authority["terminal_receipt"]["sha256"]
                or custody_guard.implementation_sha256 != implementation()["native_dispatch"]["sha256"]):
            raise AdmissionBlocked("single probe requires custody's existing native global-six lease")
        if (root / "compatibility-receipt.json").exists():
            raise AdmissionBlocked("sealed probe is read-only; validate its externally registered receipt")
        state = _run_job(root, job, context, _read(_pointer(context["protocol"])), execute=native.execute,
                         timeout=authority["timeout_seconds"], launch=prepared["authorization"], stop=threading.Event(),
                         maximum_attempts=1, lease={"custody_token": custody_guard.token,
                             "custody_receipt": str(custody_guard.owner_record),
                             "native_dispatch_sha256": custody_guard.implementation_sha256,
                             "custody_workers_reserved": custody_guard.workers})
        return {"status": state["status"], "native_drain_pending": True, "automatic_admission": False}


def seal_compatibility_probe(root: Path, *, preparation: dict, registered_preparation_sha256: str,
                             drained_receipt: dict) -> dict:
    root = _root(root)
    with transport.run_lock(root):
        prepared = _read(_pointer(preparation, registered_preparation_sha256))
        context, job = prepared["context"], prepared["job"]
        authority = _read(_pointer(prepared["authorization"]))
        _drain(drained_receipt, {"custody_root": authority["custody_root"]})
        opinion, proof = _accepted(root, job, context, _read(_pointer(context["protocol"])))
        state = _read(_pointer(proof["ledger"]))
        _drain_lineage([drained_receipt], {"custody_root": authority["custody_root"], "kind": "actual"}, [state])
        if len(state["attempts"]) != 1 or state["attempts"][0].get("native_dispatch_sha256") != implementation()["native_dispatch"]["sha256"]:
            raise IntegrityDrift("probe lacks the single actual native attempted transport")
        value = {"schema": "f8-root-synthetic-compatibility-probe-v1", "compatible": opinion is not None,
                 "implementation": implementation(), "profile": helper.PROFILE, "jobs": 1, "maximum_attempts": 1,
                 "actual_corpus_used": False, "preparation": preparation, "native_drain_receipt": drained_receipt,
                 "job": job, "context": context, "ledger": proof["ledger"], "quality_sensitivity_verified": False,
                 "files": _inventory(root, excluded={"compatibility-receipt.json", ".judge-scheduler.lock"})}
        return {"compatibility_receipt": _new(root / "compatibility-receipt.json", value), "requires_external_registration": True}


def validate_compatibility_probe(pointer: dict, *, registered_sha256: str) -> dict:
    path = _pointer(pointer, registered_sha256)
    value = _read(path)
    if (path.name != "compatibility-receipt.json" or value.get("schema") != "f8-root-synthetic-compatibility-probe-v1"
            or value.get("implementation") != implementation()):
        raise AdmissionBlocked("compatibility receipt/implementation differs")
    root = path.parent
    _exact_inventory(root, value["files"], excluded={"compatibility-receipt.json", ".judge-scheduler.lock"})
    authority = _read(_pointer(value["context"]["registration"]))
    _drain(value["native_drain_receipt"], {"custody_root": authority["custody_root"]})
    opinion, proof = _accepted(root, value["job"], value["context"], _read(_pointer(value["context"]["protocol"])))
    _drain_lineage([value["native_drain_receipt"]], {"custody_root": authority["custody_root"], "kind": "actual"},
                   [_read(_pointer(proof["ledger"]))])
    if proof["ledger"] != value["ledger"] or value["compatible"] is not (opinion is not None):
        raise IntegrityDrift("probe receipt accepted ledger changed")
    return value
