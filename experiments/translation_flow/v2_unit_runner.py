"""Prospective F5 source-unit diagnostics under the sole native global-six lease.

The original main proof and registered source frame are prerequisites. This
module never generates translations, changes primary scores, or unseals a
confirmation corpus. Its protocols and native probes require separate approval.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable

from experiments.translation_judge import integrity, runner as transport, scheduling
from . import v2_judge_dispatch as native, v2_unit_custody as custody
from . import v2_unit_diagnostics as helper, v2_unit_main_proof as main_factory

PHASES = ("native_fidelity", "cue_attribution")
STAGES = ("primary", "review", "adjudication")
PROFILES = {p: f"sol-high-F5-source-unit-{p}-v1" for p in PHASES}
SEEDS = (20261008, 20261009, 20261010)
ROOT_NAME = "evaluation-only"
MAX_ATTEMPTS = {"primary": 2, "review": 2, "adjudication": 1}
PROMPTS = {
    "native_fidelity": "Evaluate the complete Japanese target source batch against the intact output groups. "
        "Judge source-grounded fidelity, including omissions, additions and mistranslations. "
        "Do not infer a mapping, consult references, repair text, or grade groups as independent samples. "
        "An output group can be a joint unit or an original cue; its structure does not prove correctness. "
        "Return a whole-batch 0-4 native_semantic only when assessable; otherwise unresolved and null. ",
    "cue_attribution": "Evaluate whether the immutable native text spans are attributed to the supplied Japanese "
        "source cues and times. Mechanical partitions do not prove semantic attribution. "
        "Consider reordering, cross-cue dependencies and ambiguity; do not invent timing/audio evidence, "
        "repair a cut, consult references, or infer any other judge's opinion. "
        "Return supported, misattributed with exact evidence, or unresolved. ",
}


def identity(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _pointer(value: dict, expected: str | None = None) -> Path:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError("Exact independently pinned artifact pointer required")
    supplied = Path(value["path"])
    for part in (supplied, *supplied.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Evidence cannot be a link or junction")
    path = supplied.resolve()
    if identity(path) != value or expected is not None and value["sha256"] != expected:
        raise ValueError("Artifact bytes or external pin changed")
    return path


def _read(value: dict, expected: str | None = None) -> Any:
    return integrity.strict_parse(_pointer(value, expected).read_text(encoding="utf-8-sig"))


def _write(path: Path, value: Any) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(integrity.canonical_bytes(value))
    return identity(path)


def implementation() -> dict[str, dict[str, str]]:
    return {name: identity(Path(module.__file__)) for name, module in {
        "runner": __import__(__name__, fromlist=["__file__"]), "custody": custody,
        "helper": helper, "main_factory": main_factory, "native": native,
        "transport": transport, "integrity": integrity, "scheduling": scheduling}.items()}


def _key(slot: dict) -> str:
    return f"{slot['seed']}:{slot['batch_id']}"


def reliability_selection(slots: list[dict]) -> dict[str, list[str]]:
    """Source-only 20%, rounded up within each fixed seed; paired arms share it."""
    if len(slots) != 252 or len({_key(s) for s in slots}) != 252:
        raise ValueError("Exactly 252 unique source-fixed slots required")
    if any(type(s.get("seed")) is not int or s["seed"] not in SEEDS for s in slots):
        raise ValueError("Unexpected fixed source seed")
    selected = {}
    for phase in PHASES:
        ids = []
        for seed in SEEDS:
            members = [s for s in slots if s["seed"] == seed]
            if len(members) != 84:
                raise ValueError("Each fixed seed requires 84 complete source batches")
            ranked = sorted(members, key=lambda s: (
                helper.canonical_sha256(["F5-source-reliability-20pct-v1", phase, seed, s["batch_id"]]), _key(s)))
            ids.extend(_key(s) for s in ranked[:math.ceil(len(members) / 5)])
        selected[phase] = ids
    return selected


def _reliability_registration(pointer: dict, *, registration: dict,
        external_registration: dict, slots: list[dict], expected: str | None = None) -> dict:
    value = _read(pointer, expected)
    source_record = _read(registration)
    frame_pointer = source_record["frame"]
    if (value.get("schema") != "hy30-F5-source-reliability-root-registration-v1"
            or value.get("state") != "source_selection_frozen_before_F5_generation_and_quality"
            or value.get("source_registration") != registration
            or value.get("external_registration") != external_registration
            or value.get("source_frame") != frame_pointer
            or _read(frame_pointer).get("expected_slots") != slots
            or value.get("selection") != reliability_selection(slots)
            or value.get("fixed_slot_count") != 252 or value.get("source_batches_per_seed") != 84
            or value.get("selected_per_seed_per_phase") != 17
            or value.get("paired_control_fidelity_same_slots") is not True
            or value.get("candidate_native_root_exists_at_registration") is not False
            or value.get("native_calls_authorized") is not False):
        raise ValueError("Independently frozen exact source reliability registration required")
    at = datetime.fromisoformat(value["registered_at_utc"])
    if at.tzinfo is None:
        raise ValueError("Source reliability chronology requires an explicit timezone")
    proposal = _read(value["proposal"])
    if (proposal.get("registration") != registration or proposal.get("external_registration") != external_registration
            or proposal.get("frame") != frame_pointer or proposal.get("slot_manifest") != slots
            or proposal.get("selection") != value["selection"]
            or proposal.get("algorithm") != value.get("algorithm")):
        raise ValueError("Root reliability registration differs from its original source-only proposal")
    return value


def freeze_protocol(*, registration: dict, external_registration: dict,
                    expected_registration_sha256: str, expected_external_sha256: str,
                    reliability_registration: dict, expected_reliability_sha256: str,
                    output: Path) -> dict:
    """Create a source-only proposal before outputs; this never approves calls."""
    registered = custody.validate_registered_frame(registration, external_registration,
        expected_registration_sha256=expected_registration_sha256,
        expected_external_sha256=expected_external_sha256)
    slots = registered["frame"]["expected_slots"]
    _reliability_registration(reliability_registration, registration=registration,
        external_registration=external_registration, slots=slots, expected=expected_reliability_sha256)
    value = {"schema": "hy30-F5-unit-protocol-v1", "state": "proposal_not_calls_authorized",
        "registration": registration, "external_registration": external_registration,
        "reliability_registration": reliability_registration,
        "implementation": implementation(), "source_slots": slots,
        "reliability": reliability_selection(slots),
        "reliability_algorithm": "sha256-canonical-domain-phase-seed-batch; ascending; ceil(84/5)=17 per seed",
        "profiles": PROFILES, "prompts": PROMPTS, "max_attempts": MAX_ATTEMPTS,
        "model": transport.MODEL, "effort": transport.EFFORT,
        "max_phase_wall_seconds": 14400, "attempt_timeout_seconds": 600,
        "review_rule": "source-fixed reliability union eligible major/critical or material misattribution",
        "adjudication_rule": "contradictory evidence claims only; score differences are not disputes",
        "maximum_primary_jobs": {"native_fidelity": 504, "cue_attribution": 252},
        "logical_slot_denominator": 252, "generation_calls": 0, "primary_scores_changed": False}
    return _write(Path(output), value)


def _protocol(pointer: dict) -> dict:
    value = _read(pointer)
    if (value.get("schema") != "hy30-F5-unit-protocol-v1" or value.get("state") != "root_approved_no_implicit_calls"
            or value.get("implementation") != implementation() or value.get("profiles") != PROFILES
            or value.get("prompts") != PROMPTS or value.get("max_attempts") != MAX_ATTEMPTS
            or value.get("model") != transport.MODEL or value.get("effort") != transport.EFFORT
            or value.get("logical_slot_denominator") != 252
            or value.get("maximum_primary_jobs") != {"native_fidelity": 504, "cue_attribution": 252}
            or value.get("reliability") != reliability_selection(value["source_slots"])
            or type(value.get("max_phase_wall_seconds")) is not int or value["max_phase_wall_seconds"] <= 0
            or type(value.get("attempt_timeout_seconds")) is not int or value["attempt_timeout_seconds"] <= 0):
        raise ValueError("Root-approved exact source-unit protocol required")
    _reliability_registration(value["reliability_registration"], registration=value["registration"],
        external_registration=value["external_registration"], slots=value["source_slots"])
    return value


def make_split_main_validator(*, control_seal: dict, expected_control_seal_sha256: str,
        candidate_seal: dict | None, expected_candidate_seal_sha256: str | None) -> Callable[..., dict]:
    """Preserve separately registered historical control and future candidate seals."""
    control = main_factory.make_main_validator(seal=deepcopy(control_seal),
        expected_seal_sha256=expected_control_seal_sha256)
    if (candidate_seal is None) != (expected_candidate_seal_sha256 is None):
        raise ValueError("Candidate seal and independent hash must both exist or be unavailable")
    candidate = None if candidate_seal is None else main_factory.make_main_validator(
        seal=deepcopy(candidate_seal), expected_seal_sha256=expected_candidate_seal_sha256)

    def validate(receipt: dict, *, seed: int, role: str, external_registration: dict) -> dict:
        if role not in {"candidate", "control"} or seed not in SEEDS:
            raise ValueError("Unexpected role or generation seed")
        callback = control if role == "control" else candidate
        if callback is None:
            raise ValueError("Unavailable candidate seal cannot authenticate a present proof")
        return callback(receipt, seed=seed, role=role, external_registration=external_registration)
    return validate


def _main_slots(expected: list[dict], present: list[dict]) -> None:
    if len(expected) != 6 or {(e.get("seed"), e.get("role")) for e in expected} != {
            (seed, role) for seed in SEEDS for role in ("candidate", "control")}:
        raise ValueError("Exactly six externally expected main proof or unavailable slots required")
    for e in expected:
        if set(e) != {"seed", "role", "receipt", "unavailable_reason"}:
            raise ValueError("Main slot must explicitly record proof or unavailable reason")
        if e["receipt"] is None:
            if not isinstance(e["unavailable_reason"], str) or not e["unavailable_reason"].strip():
                raise ValueError("Unavailable main slot requires independently registered reason")
        elif e["unavailable_reason"] is not None:
            raise ValueError("Present main proof cannot be silently made unavailable")
    wanted = [{k: e[k] for k in ("seed", "role", "receipt")} for e in expected if e["receipt"] is not None]
    if present != wanted:
        raise ValueError("Externally expected present main proof missing, extra, or reordered")


def _custody(plan: dict) -> dict:
    value = custody.validate_prepared_unit_auxiliary(plan["custody"], expected_sha256=plan["custody"]["sha256"],
        expected_registration=plan["registration"], expected_external_registration=plan["external_registration"],
        expected_main_receipts=plan["main_receipts"], expected_validator=identity(Path(__file__)))
    _main_slots(plan["expected_main_slots"], value["main_receipts"])
    callback = make_split_main_validator(control_seal=plan["main_seals"]["control"],
        expected_control_seal_sha256=plan["main_seals"]["control"]["sha256"],
        candidate_seal=plan["main_seals"]["candidate"],
        expected_candidate_seal_sha256=None if plan["main_seals"]["candidate"] is None else plan["main_seals"]["candidate"]["sha256"])
    for entry in value["main_receipts"]:
        callback(entry["receipt"], seed=entry["seed"], role=entry["role"], external_registration=plan["external_registration"])
    return value


def prepare_run(*, custody_pointer: dict, expected_custody_sha256: str, registration: dict,
        external_registration: dict, expected_main_slots: list[dict], main_seals: dict,
        protocol: dict, expected_protocol_sha256: str, output: Path) -> dict:
    if Path(output).exists() or set(main_seals) != {"control", "candidate"}:
        raise ValueError("New destination and explicit separate main seals required")
    _pointer(custody_pointer, expected_custody_sha256)
    _pointer(protocol, expected_protocol_sha256)
    policy = _protocol(protocol)
    if policy["registration"] != registration or policy["external_registration"] != external_registration:
        raise ValueError("Protocol source registration changed")
    value = _read(custody_pointer)
    plan = {"schema": "hy30-F5-unit-run-plan-v1", "custody": custody_pointer,
        "registration": registration, "external_registration": external_registration,
        "expected_main_slots": expected_main_slots, "main_receipts": value["main_receipts"],
        "main_seals": main_seals, "protocol": protocol, "implementation": implementation(),
        "source_slots": policy["source_slots"], "logical_slots": 252,
        "generation_calls": 0, "new_independent_samples": False, "primary_scores_changed": False}
    accepted = _custody(plan)
    if [s["slot"] for s in accepted["slots"]] != plan["source_slots"]:
        raise ValueError("Custody source-fixed denominator differs from prospective protocol")
    present_main = {(e["seed"], e["role"]) for e in value["main_receipts"]}
    for slot in accepted["slots"]:
        seed = slot["slot"]["seed"]
        if (seed, "candidate") not in present_main and any(slot["views"][k] is not None for k in ("native_packet", "attribution_packet")):
            raise ValueError("Missing candidate main proof cannot expose native or attribution material")
        if (seed, "control") not in present_main and slot["views"]["c0_packet"] is not None:
            raise ValueError("Missing control main proof cannot expose cue-output control material")
    costs = accepted["original_generation_cost_authorities"]
    if len({(p["path"], p["sha256"]) for p in costs}) != len(costs):
        raise ValueError("Original generation cost identity duplicated")
    plan["original_generation_cost_authorities"] = costs
    Path(output).mkdir(parents=True)
    return _write(Path(output) / "run-plan.json", plan)


def _run_plan(pointer: dict, *, full: bool) -> tuple[dict, dict | None]:
    value = _read(pointer)
    if (value.get("schema") != "hy30-F5-unit-run-plan-v1" or value.get("implementation") != implementation()
            or value.get("logical_slots") != 252):
        raise ValueError("Run plan or implementation changed")
    policy = _protocol(value["protocol"])
    if value["source_slots"] != policy["source_slots"]:
        raise ValueError("Run source slots changed")
    return value, _custody(value) if full else None


def _blind(packet: dict, opaque: str) -> tuple[dict, dict]:
    groups = deepcopy(packet["output_groups"])
    labels = {g["group_id"]: f"g{i:04d}" for i, g in enumerate(groups)}
    for group in groups:
        group["group_id"] = labels[group["group_id"]]
    public = {"schema": helper.PACKET_SCHEMA, "phase": packet["phase"],
        "batch_id": opaque, "target_source_ids": deepcopy(packet["target_source_ids"]),
        "source_context": deepcopy(packet["source_context"]), "output_groups": groups,
        "scope": packet["scope"]}
    if packet["phase"] == "cue_attribution":
        public["mapped_cues"] = deepcopy(packet["mapped_cues"])
        for cue in public["mapped_cues"]:
            cue["group_id"] = labels[cue["group_id"]]
    return public, {"original_packet_sha256": helper.canonical_sha256(packet), "group_ids": labels}


def _prompt(packet: dict, stage: str, opinions: list[dict] | None = None) -> str:
    phase = packet["phase"]
    contract = {"profile": PROFILES[phase], "packet_sha256": helper.canonical_sha256(packet),
        "instruction": "Copy the literal packet_sha256 above into your response; do not compute a hash. "
                       "Return exactly the supplied response schema. Exact quotes are evidence, not proof of truth."}
    text = PROMPTS[phase] + "\nWrite reason and explanation in Simplified Chinese; preserve technical identifiers."
    text += "\nTRUSTED RESPONSE CONTRACT\n" + json.dumps(contract, ensure_ascii=False)
    if stage == "review":
        text += "\nIndependently review this original packet. No prior verdict is supplied."
    if stage == "adjudication":
        text += "\nResolve only these anonymous conflicting evidence claims; score differences alone are not a dispute.\n"
        text += json.dumps(opinions, ensure_ascii=False)
    return text + "\nORIGINAL BLIND PACKET\n" + json.dumps(packet, ensure_ascii=False)


def prepare_phase(*, run_plan: dict, expected_run_plan_sha256: str, phase: str,
                  fidelity_seal: dict | None = None) -> dict:
    if phase not in PHASES:
        raise ValueError("No confirmation or generic semantic phase")
    root = _pointer(run_plan, expected_run_plan_sha256).parent
    plan, material = _run_plan(run_plan, full=True)
    policy = _protocol(plan["protocol"])
    if phase == "cue_attribution":
        previous = _validated_seal(fidelity_seal, full_original=False)
        if (previous.get("schema") != "hy30-F5-unit-phase-seal-v1" or previous.get("phase") != "native_fidelity"
                or previous.get("run_plan") != run_plan or previous.get("drained") is not True
                or previous.get("logical_slots") != 252):
            raise ValueError("Independently sealed full fidelity phase required first")
    elif fidelity_seal is not None:
        raise ValueError("Fidelity cannot consume another phase opinion")
    directory = root / "phases" / phase
    if directory.exists():
        raise ValueError("Phase material already exists; use authenticated resume")
    directory.mkdir(parents=True)
    jobs, slots = [], []
    for number, slot in enumerate(material["slots"]):
        expected, views = slot["slot"], slot["views"]
        arms = (("candidate", "native_packet"), ("control", "c0_packet")) if phase == "native_fidelity" else (("candidate", "attribution_packet"),)
        for arm, key in arms:
            job_id = f"j{number:04d}-v{0 if arm == 'candidate' else 1}"
            original = views[key]
            row = {"slot": expected, "arm": arm, "job_id": job_id,
                "status": "scheduled" if original is not None else "unavailable",
                "reason": None if original is not None else views.get("reason") or views["c0_state" if arm == "control" else "native_state" if phase == "native_fidelity" else "attribution_state"]}
            slots.append(row)
            if original is None:
                continue
            packet, private = _blind(original, job_id)
            jobdir = directory / "jobs" / job_id
            packet_ptr = _write(jobdir / "packet.json", packet)
            private_ptr = _write(jobdir / "private-join.json", {**private, "slot": expected, "arm": arm})
            schema_ptr = _write(jobdir / "schema.json", helper.response_schema(packet))
            prompt = _prompt(packet, "primary")
            with (jobdir / "prompt.txt").open("xb") as stream:
                stream.write(prompt.encode("utf-8"))
            jobs.append({"job_id": job_id, "window_id": job_id, "slot_key": _key(expected), "arm": arm,
                "packet": packet_ptr, "join": private_ptr, "schema": schema_ptr, "prompt": identity(jobdir / "prompt.txt")})
    return _write(directory / "phase-plan.json", {"schema": "hy30-F5-unit-phase-plan-v1",
        "run_plan": run_plan, "phase": phase, "fidelity_seal": fidelity_seal,
        "implementation": implementation(), "slots": slots, "jobs": jobs,
        "reliability": policy["reliability"][phase], "logical_slots": 252,
        "entry_custody_sha256": plan["custody"]["sha256"], "primary_scores_changed": False})


def _phase(pointer: dict, *, full: bool) -> tuple[dict, dict, dict]:
    value = _read(pointer)
    if (value.get("schema") != "hy30-F5-unit-phase-plan-v1" or value.get("phase") not in PHASES
            or value.get("implementation") != implementation() or value.get("logical_slots") != 252):
        raise ValueError("Phase plan or code changed")
    plan, _ = _run_plan(value["run_plan"], full=full)
    policy = _protocol(plan["protocol"])
    if value["reliability"] != policy["reliability"][value["phase"]]:
        raise ValueError("Prospective source-only review frame changed")
    if [s["slot"] for s in value["slots"] if s["arm"] == "candidate"] != plan["source_slots"]:
        raise ValueError("Fixed phase denominator changed")
    expected = [s["job_id"] for s in value["slots"] if s["status"] == "scheduled"]
    if [j["job_id"] for j in value["jobs"]] != expected or len(set(expected)) != len(expected):
        raise ValueError("Phase jobs do not preserve exact available slots")
    if value["phase"] == "cue_attribution":
        previous = _validated_seal(value["fidelity_seal"], full_original=False) if full else _read(value["fidelity_seal"])
        if previous.get("run_plan") != value["run_plan"] or previous.get("phase") != "native_fidelity":
            raise ValueError("Independent fidelity barrier changed")
    return value, plan, policy


def _inputs(job: dict, stage: str, opinions: list[dict] | None = None) -> tuple[dict, bytes, bytes, str]:
    packet = _read(job["packet"])
    _pointer(job["join"])
    schema = _pointer(job["schema"]).read_bytes()
    if schema != integrity.canonical_bytes(helper.response_schema(packet)):
        raise ValueError("Submitted schema differs from closed original helper")
    prompt = _prompt(packet, stage, opinions).encode("utf-8")
    if _pointer(job["prompt"]).read_bytes() != _prompt(packet, "primary").encode("utf-8"):
        raise ValueError("Original primary prompt changed")
    return packet, schema, prompt, helper.canonical_sha256([job, stage, opinions, implementation()])


def _response(root: Path, job: dict, stage: str) -> dict | None:
    ledger = root / "execution" / stage / job["job_id"] / "job.json"
    if not ledger.exists():
        return None
    value = integrity.strict_parse(ledger.read_text(encoding="utf-8"))
    return value


def _risk(response: dict) -> bool:
    return (any(e["severity"] in {"major", "critical"} for e in response["errors"])
            or response["assessment"] == "misattributed")


def _dispute(first: dict, second: dict) -> bool:
    # Absence, severity or overlapping spans do not establish a common fact/root.
    # Callers have independently authenticated both responses to the SAME packet.
    if {first["assessment"], second["assessment"]} == {"supported", "misattributed"}:
        wrong = first if first["assessment"] == "misattributed" else second
        return any(e["source_evidence"] and e["target_evidence"] for e in wrong["errors"])
    return False


def _shape(value: Any, schema: dict) -> None:
    """Check only the frozen helper schema vocabulary, before evidence parsing."""
    types = schema.get("type")
    kinds = types if isinstance(types, list) else [types]
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "integer": type(value) is int,
        "boolean": type(value) is bool, "null": value is None}
    if types is not None and not any(checks.get(kind, False) for kind in kinds):
        raise RuntimeError("Response schema type mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise RuntimeError("Response schema enum mismatch")
    # Wrong trusted identity is evidence failure, never a semantic retry.
    if "const" in schema and value != schema["const"]:
        raise ValueError("Trusted response packet identity mismatch")
    if type(value) is int and (value < schema.get("minimum", value) or value > schema.get("maximum", value)):
        raise RuntimeError("Response schema integer range mismatch")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if not set(schema.get("required", [])) <= value.keys() or schema.get("additionalProperties") is False and not value.keys() <= properties.keys():
            raise RuntimeError("Response schema object coverage mismatch")
        for key, child in value.items():
            if key in properties:
                _shape(child, properties[key])
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise RuntimeError("Response schema array coverage mismatch")
        for child in value:
            _shape(child, schema.get("items", {}))


def _native_evidence(record: dict, launch: dict, *, drained: bool) -> None:
    spawn_failed = record.get("transport_status") == "spawn_failed" and not record.get("native_root_pid")
    if (record.get("native_dispatch_sha256") != implementation()["native"]["sha256"]
            or record.get("returned_models", []) not in ([], [transport.MODEL])
            or record.get("returned_efforts", []) not in ([], [transport.EFFORT]) or record.get("tool_events", [])
            or not spawn_failed and (record.get("containment") != "suspended-assign-resume-kill-on-close-job"
                or record.get("native_drain_proven") is not True or record.get("native_active_processes_after_drain") != 0)
            or type(record.get("custody_workers_reserved")) is not int or not 1 <= record["custody_workers_reserved"] <= 6):
        raise ValueError("Native CLI identity, tool isolation or drain proof changed")
    if record.get("transport_status") in {"completed", "timeout"} and (type(record.get("native_root_pid")) is not int or record["native_root_pid"] <= 0):
        raise ValueError("A completed or timed-out native call requires its actual owned root PID")
    receipt = integrity.inside(Path(launch["root"]) / ".judge-dispatch-receipts", Path(record["custody_receipt"]))
    value = integrity.strict_parse(receipt.read_text(encoding="utf-8"))
    if (value.get("schema") != "hy30-native-judge-custody-v1" or value.get("owner") != "evaluation_custodian"
            or value.get("token") != record.get("custody_token") or value.get("shared_limit") != 6
            or value.get("workers_reserved") != record["custody_workers_reserved"]
            or value.get("global_lock") != str(Path(launch["root"]) / ".judge-global-six.lock")
            or value.get("terminal_sha256") != launch["terminal_receipt"]["sha256"]
            or Path(value.get("terminal_receipt", "")).resolve() != Path(launch["terminal_receipt"]["path"]).resolve()
            or value.get("module_sha256") != implementation()["native"]["sha256"]
            or drained and (value.get("state") != "drained_released" or value.get("active_callbacks") != 0 or value.get("owned_job_objects") != 0)):
        raise ValueError("Native shared custody receipt differs from locked authority")
    _pointer(launch["terminal_receipt"])


def _schema_failure(attempt: Path) -> bool:
    stdout = attempt / "stdout.jsonl"
    if not stdout.exists():
        return False
    for line in stdout.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = integrity.strict_parse(line)
        except (ValueError, TypeError):
            continue
        if isinstance(event, dict):
            payload = event if event.get("type") in {"error", "turn.failed"} else event.get("item")
            if isinstance(payload, dict) and (payload is event or payload.get("type") == "error") and "invalid_json_schema" in json.dumps(payload):
                return True
    return False


def validate_native_probe(pointer: dict, *, phase: str, protocol: dict,
                          executable: dict, shared_root: Path) -> dict:
    """Authenticate an independently approved original one-call probe, not a flag."""
    probe = _read(pointer)
    if (probe.get("schema") != "hy30-F5-unit-native-probe-v1" or probe.get("state") != "root_reviewed_native_probe"
            or probe.get("phase") != phase or probe.get("profile") != PROFILES[phase]
            or probe.get("implementation") != implementation() or probe.get("protocol") != protocol
            or probe.get("exactly_one_fresh_attempt") is not True or probe.get("synthetic_material_declared") is not True
            or probe.get("source_independent_handwritten") is not True or probe.get("drained") is not True):
        raise ValueError("Exact independently reviewed original-schema native probe required")
    launch = _read(probe["probe_launch"])
    if (launch.get("schema") != "hy30-F5-unit-probe-launch-v1" or launch.get("phase") != phase
            or launch.get("protocol") != protocol or launch.get("profile") != PROFILES[phase]
            or launch.get("implementation") != implementation() or launch.get("calls_authorized") is not True
            or launch.get("owner") != "evaluation_custodian" or launch.get("maximum_workers") != 1
            or launch.get("model") != transport.MODEL or launch.get("effort") != transport.EFFORT
            or launch.get("executable") != executable or Path(launch.get("root", "")).resolve() != Path(shared_root).resolve()
            or launch.get("source_independent_handwritten") is not True):
        raise ValueError("Probe lacks separate exact native launch authority")
    _pointer(executable)
    _pointer(launch["terminal_receipt"])
    packet = _read(probe["packet"])
    if packet.get("phase") != phase or "mapped_cues" in packet and phase == "native_fidelity":
        raise ValueError("Probe exposes another phase")
    attempt_dir = _pointer(probe["attempt_record"]).parent
    if (attempt_dir.name != "attempt-1" or not attempt_dir.resolve().is_relative_to(Path(shared_root).resolve())
            or sorted(attempt_dir.parent.rglob("attempt.json")) != [attempt_dir / "attempt.json"]):
        raise ValueError("Exactly one original probe attempt; sibling calls cannot be hidden")
    for name in ("packet", "schema_artifact", "prompt"):
        if integrity.inside(attempt_dir, _pointer(probe[name])).parent != attempt_dir:
            raise ValueError("Probe material cannot be borrowed from another call")
    schema_path, prompt_path = _pointer(probe["schema_artifact"]), _pointer(probe["prompt"])
    if (schema_path.read_bytes() != integrity.canonical_bytes(helper.response_schema(packet))
            or prompt_path.read_bytes() != _prompt(packet, "primary").encode("utf-8")
            or (attempt_dir / "stdin.bin").read_bytes() != prompt_path.read_bytes()):
        raise ValueError("Original probe submitted schema, literal identity or stdin changed")
    record = _read(probe["attempt_record"])
    if (record.get("attempt") != 1 or record.get("status") != "succeeded" or not record.get("finished_at")
            or record.get("transport_status") != "completed" or record.get("returncode") != 0
            or record.get("profile") != PROFILES[phase] or record.get("packet_sha256") != helper.canonical_sha256(packet)
            or record.get("command") != transport.command(executable["path"], Path(record["isolated_cwd"]), schema_path, attempt_dir / "last-message.txt")
            or record.get("custody_workers_reserved") != 1):
        raise ValueError("Probe original invocation identity or exactly-one-call proof changed")
    observed = transport.event_evidence((attempt_dir / "stdout.jsonl").read_text(encoding="utf-8", errors="replace"))
    for key in ("returned_models", "returned_efforts", "tool_events", "usage_events"):
        if record.get(key) != observed[key]:
            raise ValueError("Probe returned identity/usage disagrees with actual CLI events")
    _native_evidence(record, launch, drained=True)
    accepted = probe["accepted"]
    if (integrity.inside(attempt_dir, Path(accepted["accepted_raw_response"])) != attempt_dir / "last-message.txt"
            or identity(Path(accepted["accepted_raw_response"]))["sha256"] != accepted["accepted_raw_response_sha256"]
            or identity(integrity.inside(attempt_dir, Path(accepted["accepted_canonical_snapshot"]))) ["sha256"] != accepted["response_sha256"]):
        raise ValueError("Probe accepted original raw/snapshot changed")
    response = integrity.inside(attempt_dir, Path(accepted["response"]))
    integrity.resume_success(accepted, attempt_dir / "attempt.json", response,
        lambda obj: helper.parse_response(json.dumps(obj, ensure_ascii=False), packet))
    inventory = [identity(p) for p in sorted(attempt_dir.iterdir()) if p.is_file()]
    if probe["attempt_inventory"] != inventory:
        raise ValueError("Probe original attempt inventory drifted or has extra calls")
    allowed = {"packet.json", "schema.json", "prompt.txt", "attempt.json", "stdin.bin", "stdout.jsonl", "stderr.txt", "last-message.txt", "accepted-canonical.json", "response.json"}
    if {p.name for p in attempt_dir.iterdir()} != allowed:
        raise ValueError("Probe attempt contains unexpected or missing material")
    for path in attempt_dir.parent.rglob("*"):
        if path.is_file() and path.parent != attempt_dir:
            raise ValueError("Unregistered original probe artifacts outside the single attempt")
    return probe


def _launch(pointer: dict, phase_ptr: dict, stage: str, workers: int) -> dict:
    value = _read(pointer)
    if (value.get("schema") != "hy30-F5-unit-launch-v1" or value.get("phase_plan") != phase_ptr
            or value.get("stage") != stage or value.get("calls_authorized") is not True
            or value.get("owner") != "evaluation_custodian" or value.get("implementation") != implementation()
            or value.get("model") != transport.MODEL or value.get("effort") != transport.EFFORT
            or value.get("maximum_workers") != 6 or type(workers) is not int or not 1 <= workers <= 6):
        raise ValueError("Separate root-approved exact native launch required")
    root = Path(value["root"]).resolve()
    if root.name != ROOT_NAME or value.get("global_lock") != str(root / ".judge-global-six.lock"):
        raise ValueError("Only the shared evaluation-only ROOT lock may dispatch")
    _pointer(value["executable"])
    _pointer(value["terminal_receipt"])
    # Compatibility receipts are never inferred from a protocol or frame.
    probes = value.get("probe_receipts")
    if not isinstance(probes, dict) or set(probes) != set(PHASES):
        raise ValueError("Both separately authorized original-schema native probes required")
    protocol = _read(_read(phase_ptr)["run_plan"])["protocol"]
    policy = _protocol(protocol)
    if value.get("reliability_registration") != policy["reliability_registration"]:
        raise ValueError("Native launch must explicitly pin the source-only reliability root registration")
    for phase, pin in probes.items():
        validate_native_probe(pin, phase=phase, protocol=protocol, executable=value["executable"], shared_root=root)
    return value


def _validate_stop(run_plan: dict, pointer: dict) -> dict:
    expected = _pointer(run_plan).parent / "global-stop.json"
    if _pointer(pointer) != expected:
        raise ValueError("Only this run's exact persisted global stop can justify a tail")
    value = _read(pointer)
    if (value.get("schema") != "hy30-F5-unit-global-stop-v1" or value.get("owner") != "evaluation_custodian"
            or value.get("run_plan") != run_plan or value.get("stage") not in STAGES
            or value.get("reason") not in {"invalid_json_schema", "access_failure", "submitted_material_mutation", "identity_or_evidence", "wall_budget"}):
        raise ValueError("Global stop ownership, scope or reason changed")
    phase = _read(value["phase_plan"])
    if phase.get("run_plan") != run_plan:
        raise ValueError("Global stop belongs to another native source run")
    _launch(value["launch"], value["phase_plan"], value["stage"], 1)
    return value


def _attempt_bytes(directory: Path, record: dict, schema: bytes, prompt: bytes,
                   launch: dict, *, drained: bool) -> None:
    attempt = directory / f"attempt-{record['attempt']}"
    if (attempt / "schema.json").read_bytes() != schema or (attempt / "prompt.txt").read_bytes() != prompt:
        raise ValueError("Original submitted attempt schema or prompt changed")
    stdin = attempt / "stdin.bin"
    if stdin.exists():
        if stdin.read_bytes() != prompt:
            raise ValueError("Actual native stdin differs from original submitted prompt")
    elif not (record.get("transport_status") == "spawn_failed" and not record.get("native_root_pid")):
        raise ValueError("Dispatched native attempt lacks original stdin evidence")
    if record.get("transport_status") is not None:
        _native_evidence(record, launch, drained=drained)
        observed = transport.event_evidence((attempt / "stdout.jsonl").read_text(encoding="utf-8", errors="replace"))
        for key in ("returned_models", "returned_efforts", "usage_events", "tool_events"):
            if record.get(key) != observed[key]:
                raise ValueError("Retained native identity/usage differs from actual CLI event bytes")
    for pin in record.get("artifacts", []):
        if integrity.inside(attempt, Path(pin["path"])).parent != attempt:
            raise ValueError("Native artifacts cannot come from another attempt")
        _pointer(pin)


def _previous(root: Path, job: dict, stage: str, launch: dict | None = None) -> dict | None:
    state = _response(root, job, stage)
    if state is None:
        return None
    opinions = None
    if stage == "adjudication":
        opinions = [_read(_response(root, job, s)["accepted_response"]) for s in ("primary", "review")]
    packet, schema, prompt, fingerprint = _inputs(job, stage, opinions)
    if (state.get("job_id") != job["job_id"] or state.get("stage") != stage or state.get("fingerprint") != fingerprint
            or [a.get("attempt") for a in state.get("attempts", [])] != list(range(1, len(state.get("attempts", [])) + 1))
            or len(state.get("attempts", [])) > MAX_ATTEMPTS[stage]):
        raise ValueError("Original job attempt identity or bounded order changed")
    directory = root / "execution" / stage / job["job_id"]
    if sorted(p.name for p in directory.glob("attempt-*")) != [f"attempt-{i}" for i in range(1, len(state["attempts"]) + 1)]:
        raise ValueError("Unrecorded original attempts cannot be silently retried")
    if not state["attempts"]:
        if state.get("status") != "not_run" or not state.get("global_stop"):
            raise ValueError("Empty attempt ledger cannot erase an eligible review or opinion")
        _validate_stop(_read(identity(root / "phase-plan.json"))["run_plan"], state["global_stop"])
    if state.get("terminal_failure") in {"invalid_json_schema", "access_failure", "submitted_material_mutation", "identity_or_evidence"}:
        if not state.get("global_stop"):
            raise ValueError("Terminal global failure lost its persisted stop proof")
        _validate_stop(_read(identity(root / "phase-plan.json"))["run_plan"], state["global_stop"])
    for record in state["attempts"]:
        attempt = directory / f"attempt-{record['attempt']}"
        if record != integrity.strict_parse((attempt / "attempt.json").read_text(encoding="utf-8")):
            raise ValueError("Attempt ledger differs from retained original")
        if (attempt / "schema.json").read_bytes() != schema or (attempt / "prompt.txt").read_bytes() != prompt:
            raise ValueError("Original attempt prompt/schema mutated")
        if record.get("status") == "started" or not record.get("finished_at"):
            raise ValueError("Started original attempt has no terminal/drain evidence; no free retry")
        original_launch = _launch(state["launch"], identity(root / "phase-plan.json"), stage, record.get("custody_workers_reserved", 1))
        expected_command = transport.command(original_launch["executable"]["path"], Path(record["isolated_cwd"]),
            attempt / "schema.json", attempt / "last-message.txt")
        if record.get("command") != expected_command:
            raise ValueError("Original CLI argv differs from the exact isolated profile")
        if record.get("transport_status") is not None:
            _attempt_bytes(directory, record, schema, prompt, original_launch, drained=True)
        elif record.get("status") == "succeeded" or not state.get("terminal_failure"):
            raise ValueError("Missing original native transport/custody evidence cannot authenticate or retry")
        if record.get("status") == "succeeded":
            if (attempt / "stdin.bin").read_bytes() != prompt:
                raise ValueError("Accepted native stdin differs from actual prompt")
    if state["status"] == "succeeded":
        accepted = [a for a in state["attempts"] if a.get("status") == "succeeded"]
        if len(accepted) != 1 or accepted[0] is not state["attempts"][-1]:
            raise ValueError("Accepted original attempt must be unique and last")
        raw_directory = directory / f"attempt-{accepted[0]['attempt']}"
        if integrity.inside(raw_directory, Path(state["accepted_raw_response"])) != raw_directory / "last-message.txt":
            raise ValueError("Accepted response must be the original last message of this attempt")
        snapshot = integrity.inside(raw_directory, Path(state["accepted_canonical_snapshot"]))
        if identity(snapshot)["sha256"] != state["response_sha256"]:
            raise ValueError("Accepted canonical snapshot changed even when response exists")
        if integrity.inside(root / "responses" / stage, Path(state["response"])) != root / "responses" / stage / (job["job_id"] + ".json"):
            raise ValueError("Canonical response cannot be borrowed from another job")
        integrity.resume_success(state, directory / "job.json", Path(state["response"]),
            lambda raw: helper.parse_response(json.dumps(raw, ensure_ascii=False), packet))
        if state["accepted_response"] != identity(Path(state["response"])):
            raise ValueError("Accepted response pointer differs from original canonical identity")
    return state


def run_phase(*, phase_plan: dict, expected_phase_plan_sha256: str, launch: dict,
              expected_launch_sha256: str, workers: int, stage: str = "primary",
              custody_owner: str = "evaluation_custodian") -> dict:
    """Only explicit native execution; tests patch the native module, not a callback."""
    if stage not in STAGES or custody_owner != "evaluation_custodian":
        raise ValueError("Unexpected diagnostic stage or dispatcher owner")
    root = _pointer(phase_plan, expected_phase_plan_sha256).parent
    if (root / "seal.json").exists():
        raise ValueError("Sealed phases are immutable; do not append cached resume artifacts")
    run_root = _read(phase_plan)["run_plan"]
    _pointer(launch, expected_launch_sha256)
    with transport.run_lock(root):
        phase, plan, policy = _phase(phase_plan, full=True)
        authority = _launch(launch, phase_plan, stage, workers)
        shared_root = Path(authority["root"]).resolve()
        if not root.resolve().is_relative_to(shared_root):
            raise ValueError("Phase artifacts must be inside custody's shared ROOT")
        stop_path = _pointer(run_root).parent / "global-stop.json"
        mutation_lock = threading.Lock()
        started = time.monotonic()
        states, selected = [], []
        new_attempts = 0
        new_callbacks = 0
        risk_slots = set()
        if stage == "review":
            for job in phase["jobs"]:
                primary = _previous(root, job, "primary")
                if primary and primary["status"] == "succeeded" and _risk(_read(primary["accepted_response"])):
                    risk_slots.add(job["slot_key"])

        def stop(reason: str) -> None:
            with mutation_lock:
                if not stop_path.exists():
                    _write(stop_path, {"schema": "hy30-F5-unit-global-stop-v1", "reason": reason,
                        "owner": "evaluation_custodian", "run_plan": run_root,
                        "phase_plan": phase_plan, "launch": launch, "stage": stage})
        if stop_path.exists():
            _validate_stop(run_root, identity(stop_path))

        for job in phase["jobs"]:
            previous = _previous(root, job, stage)
            if previous and previous["attempts"] and previous["launch"] != launch:
                raise ValueError("Accepted or failed original attempts cannot change locked launch on resume")
            if previous and (previous["status"] == "succeeded" or previous.get("terminal_failure") or len(previous["attempts"]) >= MAX_ATTEMPTS[stage]):
                states.append(previous)
                continue
            reason = None
            if stage != "primary":
                primary = _previous(root, job, "primary")
                if not primary or primary["status"] != "succeeded":
                    reason = "upstream_primary_unknown"
                elif stage == "review":
                    opinion = _read(primary["accepted_response"])
                    if job["slot_key"] not in phase["reliability"] and job["slot_key"] not in risk_slots:
                        reason = "not_selected_source_reliability_or_risk"
                else:
                    review = _previous(root, job, "review")
                    if not review or review["status"] != "succeeded":
                        reason = "review_unknown"
                    elif not _dispute(_read(primary["accepted_response"]), _read(review["accepted_response"])):
                        reason = "no_actual_evidence_dispute"
            if reason:
                states.append({"job_id": job["job_id"], "status": "not_required" if reason.startswith("not_selected") or reason == "no_actual_evidence_dispute" else "unknown", "reason": reason, "attempts": []})
            else:
                selected.append(job)

        def execute_job(job: dict) -> dict:
            nonlocal new_attempts, new_callbacks
            opinions = None if stage != "adjudication" else [_read(_response(root, job, s)["accepted_response"]) for s in ("primary", "review")]
            packet, schema, prompt, fingerprint = _inputs(job, stage, opinions)
            directory = root / "execution" / stage / job["job_id"]
            previous = _previous(root, job, stage)
            state = previous or {"job_id": job["job_id"], "stage": stage, "fingerprint": fingerprint,
                "status": "judge_failed", "attempts": [], "launch": launch,
                "response": str(root / "responses" / stage / (job["job_id"] + ".json"))}
            if previous and previous["launch"] != launch:
                raise ValueError("Resume cannot change original independently approved launch")
            directory.mkdir(parents=True, exist_ok=True)
            for number in range(len(state["attempts"]) + 1, MAX_ATTEMPTS[stage] + 1):
                if time.monotonic() - started >= policy["max_phase_wall_seconds"]:
                    stop("wall_budget")
                if stop_path.exists():
                    if not state["attempts"]:
                        state.update(status="not_run", reason="global_stop_or_wall_budget", global_stop=identity(stop_path))
                    break
                # Checks must precede every retry, including after a format failure.
                try:
                    _phase(phase_plan, full=False)
                    _launch(launch, phase_plan, stage, workers)
                    for prior in state["attempts"]:
                        _attempt_bytes(directory, prior, schema, prompt, authority, drained=False)
                    if _inputs(job, stage, opinions)[1:] != (schema, prompt, fingerprint):
                        raise ValueError("Local original material changed before retry")
                except (ValueError, KeyError, OSError):
                    stop("submitted_material_mutation")
                    state.update(terminal_failure="submitted_material_mutation", reason="integrity_block_before_retry")
                    state["global_stop"] = identity(stop_path)
                    break
                attempt = directory / f"attempt-{number}"
                attempt.mkdir()
                (attempt / "schema.json").write_bytes(schema)
                (attempt / "prompt.txt").write_bytes(prompt)
                record = {"attempt": number, "status": "started", "started_at": transport.utc(),
                    "profile": PROFILES[phase["phase"]], "packet_sha256": helper.canonical_sha256(packet),
                    "submitted_schema_sha256": integrity.sha(schema), "submitted_prompt_sha256": integrity.sha(prompt)}
                _write(attempt / "attempt.json", record)
                with mutation_lock:
                    new_attempts += 1
                state["attempts"].append(record)
                (directory / "job.json").write_bytes(integrity.canonical_bytes(state))
                try:
                    with tempfile.TemporaryDirectory(prefix="kototoki-F5-unit-") as temporary:
                        cwd = Path(temporary)
                        args = transport.command(authority["executable"]["path"], cwd, attempt / "schema.json", attempt / "last-message.txt")
                        record.update(command=args, isolated_cwd=str(cwd))
                        with mutation_lock:
                            new_callbacks += 1
                        record.update(native.execute(args, prompt.decode("utf-8"), cwd, attempt, policy["attempt_timeout_seconds"]))
                    if (record.get("custody_token") != guard.token or record.get("custody_receipt") != str(guard.owner_record)
                            or record.get("custody_workers_reserved") != guard.workers):
                        raise ValueError("Invocation must belong to this actual shared native guard")
                    if _schema_failure(attempt):
                        stop("invalid_json_schema")
                        state["terminal_failure"] = "invalid_json_schema"
                        raise ValueError("Deterministic invalid schema stops every phase")
                    _native_evidence(record, authority, drained=False)
                    _attempt_bytes(directory, record, schema, prompt, authority, drained=False)
                    if record.get("transport_status") != "completed" or record.get("returncode") != 0:
                        raise RuntimeError("Bounded native transport failure")
                    if (attempt / "stdin.bin").read_bytes() != prompt:
                        raise ValueError("Actual submitted stdin changed")
                    if _inputs(job, stage, opinions)[1:] != (schema, prompt, fingerprint):
                        raise ValueError("Original job changed during invocation")
                    raw_path = attempt / "last-message.txt"
                    # Invalid JSON is format-retryable; well-shaped wrong evidence is terminal.
                    raw = integrity.strict_parse(raw_path.read_text(encoding="utf-8-sig"))
                    _shape(raw, helper.response_schema(packet))
                    try:
                        helper.parse_response(json.dumps(raw, ensure_ascii=False), packet)
                    except (ValueError, KeyError, TypeError):
                        state["terminal_failure"] = "evidence_failure"
                        raise RuntimeError("Source quote, membership or native span evidence mismatch")
                    state.update(integrity.accept_response(raw_path, Path(state["response"]),
                        lambda obj: helper.parse_response(json.dumps(obj, ensure_ascii=False), packet)), status="succeeded")
                    state["accepted_response"] = identity(Path(state["response"]))
                    record["status"] = "succeeded"
                except RuntimeError as exc:
                    record.update(status="failed", error_kind="evidence_failure" if state.get("terminal_failure") == "evidence_failure" else "transport_or_format", reason=str(exc))
                except json.JSONDecodeError:
                    record.update(status="failed", error_kind="format", reason="invalid_json")
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    record.update(status="failed", error_kind="identity_or_evidence", reason=type(exc).__name__)
                    state["terminal_failure"] = state.get("terminal_failure", "identity_or_evidence")
                    stop(state["terminal_failure"])
                record["finished_at"] = transport.utc()
                record["artifacts"] = [identity(p) for p in sorted(attempt.iterdir()) if p.is_file() and p.name != "attempt.json"]
                record["access_failure"] = scheduling.classify_access_failure(attempt, record)
                if record["access_failure"]:
                    state["terminal_failure"] = "access_failure"
                    stop("access_failure")
                if stop_path.exists():
                    state["global_stop"] = identity(stop_path)
                (attempt / "attempt.json").write_bytes(integrity.canonical_bytes(record))
                (directory / "job.json").write_bytes(integrity.canonical_bytes(state))
                if state["status"] == "succeeded" or state.get("terminal_failure"):
                    break
            (directory / "job.json").write_bytes(integrity.canonical_bytes(state))
            return state

        if selected and not stop_path.exists():
            with native.CustodyGuard(shared_root, workers, Path(authority["terminal_receipt"]["path"]),
                    authority["terminal_receipt"]["sha256"], owner=custody_owner) as guard:
                if (type(guard) is not native.CustodyGuard or not guard.entered or guard.root != shared_root
                        or guard.workers != workers or guard.owner != custody_owner):
                    raise ValueError("Actual native joint ROOT guard required")
                scheduled, _ = scheduling.schedule_jobs(selected, workers, execute_job)
                states.extend(scheduled)
        else:
            states.extend({"job_id": j["job_id"], "status": "not_run", "reason": "global_stop", "attempts": []} for j in selected)
        # Large original inventories are checked once again after every callback drains.
        _phase(phase_plan, full=True)
        for job in phase["jobs"]:
            _previous(root, job, stage)
        completion = {"schema": "hy30-F5-unit-stage-completion-v1", "phase_plan": phase_plan,
            "stage": stage, "launch": launch, "states": states, "logical_slots": 252,
            "unavailable_views": sum(s["status"] == "unavailable" for s in phase["slots"]),
            "actual_attempts": sum(len(s["attempts"]) for s in states),
            "attempt_count_scope": "retained original attempts, including accepted resume history",
            "new_attempts": new_attempts, "new_native_callbacks": new_callbacks,
            "stop": None if not stop_path.exists() else identity(stop_path), "generation_calls": 0,
            "primary_scores_changed": False, "elapsed_seconds": time.monotonic() - started}
        return _write(root / "completions" / (stage + "-" + transport.utc().replace(":", "-") + ".json"), completion)


def _phase_inventory(root: Path, phase: dict, *, sealing: bool) -> list[dict]:
    job_ids = {j["job_id"] for j in phase["jobs"]}
    allowed_attempt_files = {"attempt.json", "schema.json", "prompt.txt", "stdin.bin", "stdout.jsonl", "stderr.txt", "last-message.txt", "accepted-canonical.json"}
    result = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).parts
        valid = rel in {("phase-plan.json",), (".judge-scheduler.lock",)}
        if rel == ("seal.json",):
            if sealing:
                raise ValueError("Already sealed phase is immutable")
            continue
        if len(rel) == 3 and rel[0] == "jobs" and rel[1] in job_ids and rel[2] in {"packet.json", "private-join.json", "schema.json", "prompt.txt"}:
            valid = True
        elif len(rel) == 4 and rel[0] == "execution" and rel[1] in STAGES and rel[2] in job_ids and rel[3] == "job.json":
            valid = True
        elif len(rel) == 5 and rel[0] == "execution" and rel[1] in STAGES and rel[2] in job_ids and rel[3] in {"attempt-1", "attempt-2"} and rel[4] in allowed_attempt_files:
            valid = True
        elif len(rel) == 3 and rel[0] == "responses" and rel[1] in STAGES and Path(rel[2]).stem in job_ids and rel[2].endswith(".json"):
            valid = True
        elif len(rel) == 2 and rel[0] == "completions" and any(rel[1].startswith(s + "-") for s in STAGES) and rel[1].endswith(".json"):
            valid = True
        if not valid:
            raise ValueError("Unexpected artifact outside frozen phase material inventory")
        if rel != (".judge-scheduler.lock",):
            pin = identity(path)
            _pointer(pin)
            result.append(pin)
    return result


def _terminal_summaries(root: Path, phase: dict, completions: dict, external_launch_pins: dict) -> dict:
    if set(completions) != set(STAGES) or set(external_launch_pins) != set(STAGES):
        raise ValueError("Every terminal stage and independent launch pin required")
    summaries = {}
    expected_ids = {j["job_id"] for j in phase["jobs"]}
    risk_slots = set()
    for job in phase["jobs"]:
        primary = _previous(root, job, "primary")
        if primary and primary["status"] == "succeeded" and _risk(_read(primary["accepted_response"])):
            risk_slots.add(job["slot_key"])
    for stage, pin in completions.items():
        summary = _read(pin)
        if (summary.get("schema") != "hy30-F5-unit-stage-completion-v1" or summary.get("stage") != stage
                or summary.get("phase_plan") != identity(root / "phase-plan.json") or summary.get("logical_slots") != 252
                or summary.get("launch") != external_launch_pins[stage]):
            raise ValueError("Wrong terminal stage or independently approved launch receipt")
        _launch(external_launch_pins[stage], summary["phase_plan"], stage, 1)
        if len(summary["states"]) != len(expected_ids) or {s["job_id"] for s in summary["states"]} != expected_ids:
            raise ValueError("Missing or extra terminal job denominator")
        indexed = {s["job_id"]: s for s in summary["states"]}
        for job in phase["jobs"]:
            previous = _previous(root, job, stage)
            state = indexed[job["job_id"]]
            if state.get("status") not in {"succeeded", "judge_failed", "not_run", "not_required", "unknown"}:
                raise ValueError("Nonterminal completion cannot seal")
            if previous is not None and previous != state:
                raise ValueError("Completion state differs from retained exact original ledger")
            if previous is None and state.get("attempts"):
                raise ValueError("Attempted completion requires its retained original job ledger")
            if state.get("attempts") and state.get("launch") != external_launch_pins[stage]:
                raise ValueError("Original attempted ledger launch differs from independent stage authority")
            if not state.get("attempts"):
                if state.get("attempts") or state.get("status") not in {"not_run", "not_required", "unknown"}:
                    raise ValueError("Completion invents an accepted or attempted original job")
                if stage == "primary":
                    if state["status"] != "not_run" or not summary.get("stop"):
                        raise ValueError("Unattempted primary needs exact global-stop authority")
                    _validate_stop(phase["run_plan"], summary["stop"])
                elif state["status"] == "not_run":
                    if not summary.get("stop"):
                        raise ValueError("Every unattempted stage requires exact persisted stop authority")
                    _validate_stop(phase["run_plan"], summary["stop"])
                else:
                    primary = _previous(root, job, "primary")
                    if not primary or primary["status"] != "succeeded":
                        expected_reason = "upstream_primary_unknown"
                    elif stage == "review":
                        if job["slot_key"] in phase["reliability"] or job["slot_key"] in risk_slots:
                            raise ValueError("Eligible reliability or paired risk review cannot disappear")
                        expected_reason = "not_selected_source_reliability_or_risk"
                    else:
                        review = _previous(root, job, "review")
                        if not review or review["status"] != "succeeded":
                            expected_reason = "review_unknown"
                        elif _dispute(_read(primary["accepted_response"]), _read(review["accepted_response"])):
                            raise ValueError("Actual complete-view attribution dispute cannot disappear")
                        else:
                            expected_reason = "no_actual_evidence_dispute"
                    if state.get("reason") != expected_reason:
                        raise ValueError("Unsupported stage selection reason")
                    expected_status = "not_required" if expected_reason in {"not_selected_source_reliability_or_risk", "no_actual_evidence_dispute"} else "unknown"
                    if state["status"] != expected_status:
                        raise ValueError("Stage selection reason cannot relabel unknown as not-required")
        summaries[stage] = summary
    return summaries


def _validated_seal(pointer: dict, *, full_original: bool = True) -> dict:
    value = _read(pointer)
    if (value.get("schema") != "hy30-F5-unit-phase-seal-v1" or value.get("drained") is not True
            or value.get("logical_slots") != 252):
        raise ValueError("Full authenticated drained phase seal required")
    root = _pointer(value["phase_plan"]).parent
    phase, _, _ = _phase(value["phase_plan"], full=full_original)
    if value["phase"] != phase["phase"] or value["run_plan"] != phase["run_plan"] or value["slots"] != phase["slots"]:
        raise ValueError("Sealed phase, source scope or view status differs")
    _terminal_summaries(root, phase, value["completions"], value["external_launch_pins"])
    if value["inventory"] != _phase_inventory(root, phase, sealing=False):
        raise ValueError("Sealed phase inventory drifted")
    return value


def seal_phase(*, phase_plan: dict, expected_phase_plan_sha256: str,
               completions: dict[str, dict], external_launch_pins: dict[str, dict]) -> dict:
    root = _pointer(phase_plan, expected_phase_plan_sha256).parent
    phase, plan, _ = _phase(phase_plan, full=True)
    if set(completions) != set(STAGES):
        raise ValueError("Every primary/review/adjudication terminal stage receipt required")
    summaries = {}
    known = {(stage, j["job_id"]) for stage in STAGES for j in phase["jobs"]}
    for path in (root / "execution").glob("*/*/job.json"):
        if (path.parent.parent.name, path.parent.name) not in known:
            raise ValueError("Unexpected job outside fixed phase inventory")
    summaries = _terminal_summaries(root, phase, completions, external_launch_pins)
    inventory = _phase_inventory(root, phase, sealing=True)
    return _write(root / "seal.json", {"schema": "hy30-F5-unit-phase-seal-v1", "run_plan": phase["run_plan"],
        "phase_plan": phase_plan, "phase": phase["phase"], "completions": completions,
        "external_launch_pins": external_launch_pins,
        "logical_slots": 252, "slots": phase["slots"], "drained": True,
        "inventory": inventory,
        "original_generation_cost_authorities": plan["original_generation_cost_authorities"],
        "generation_calls": 0, "primary_scores_changed": False, "semantic_accuracy_verified": False})


def seal_diagnostic(*, run_plan: dict, expected_run_plan_sha256: str,
                    fidelity_seal: dict, attribution_seal: dict) -> dict:
    root = _pointer(run_plan, expected_run_plan_sha256).parent
    plan, _ = _run_plan(run_plan, full=True)
    phases = {}
    for phase, pin in zip(PHASES, (fidelity_seal, attribution_seal)):
        value = _validated_seal(pin, full_original=False)
        if (value.get("schema") != "hy30-F5-unit-phase-seal-v1" or value.get("phase") != phase
                or value.get("run_plan") != run_plan or value.get("logical_slots") != 252 or value.get("drained") is not True):
            raise ValueError("Both independent original phase seals required")
        for item in value["inventory"]:
            _pointer(item)
        phases[phase] = pin
    attribution = _read(_read(attribution_seal)["phase_plan"])
    if attribution["fidelity_seal"] != fidelity_seal:
        raise ValueError("Attribution must follow this exact independent fidelity seal")
    views, judge_attempts = {}, {}
    for phase, seal in phases.items():
        sealed = _read(seal)
        phase_root = _pointer(sealed["phase_plan"]).parent
        phase_plan_value = _read(sealed["phase_plan"])
        stage_states = {stage: {s["job_id"]: s for s in _read(pin)["states"]}
                        for stage, pin in sealed["completions"].items()}
        for item in phase_plan_value["slots"]:
            key = (_key(item["slot"]), "control" if item["arm"] == "control" else phase)
            stages = {stage: stage_states[stage].get(item["job_id"]) for stage in STAGES}
            views[key] = {"available": item["status"] == "scheduled", "reason": item["reason"],
                "stages": stages, "interpretation": "保留各轮意见和所有严重错误信号；不能选择有利分数来消除未解决的复核分歧。"}
            for stage, state in stages.items():
                if state:
                    for record in state["attempts"]:
                        path = phase_root / "execution" / stage / item["job_id"] / f"attempt-{record['attempt']}" / "attempt.json"
                        judge_attempts[str(path)] = identity(path)
    final_slots = [{"slot": slot, "native_fidelity": views[(_key(slot), "native_fidelity")],
                    "control_fidelity": views[(_key(slot), "control")],
                    "cue_attribution": views[(_key(slot), "cue_attribution")]} for slot in plan["source_slots"]]
    for path in root.iterdir():
        if path.name not in {"run-plan.json", "global-stop.json", "phases"}:
            raise ValueError("Unexpected top-level artifact outside the prospective diagnostic run")
    return _write(root / "diagnostic-seal.json", {"schema": "hy30-F5-unit-diagnostic-seal-v1",
        "run_plan": run_plan, "phases": phases, "source_slots": plan["source_slots"],
        "logical_slots": 252, "original_generation_cost_authorities": plan["original_generation_cost_authorities"],
        "slots": final_slots, "judge_attempt_authorities": list(judge_attempts.values()),
        "unique_retained_judge_attempts": len(judge_attempts),
        "judge_cost_scope": "每个原诊断attempt只计一次；保留失败、重试、复核、adjudication与未知usage。它们不构成新的翻译计时或独立生成样本。",
        "original_generation_cost_counted_once": True, "generation_calls": 0,
        "new_independent_samples": False, "primary_scores_changed": False,
        "semantic_accuracy_verified": False, "interpretation": "仅供日文源文驱动的自动化机制诊断；所有未知尾段保留。"})
