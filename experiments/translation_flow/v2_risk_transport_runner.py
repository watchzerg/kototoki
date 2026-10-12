"""Explicit transport-v2 projection; original semantic helper/driver stay frozen.

No semantic run_job, translation, score finalizer, or implicit CLI probe is used.
The custodian supplies the shared global six-slot guard and authorization receipt.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import math
from pathlib import Path
import re
import tempfile
import time
import threading
from typing import Any, Callable

from experiments.translation_judge import integrity, runner as transport, scheduling
from . import v2_risk_reconciliation as risk
from . import v2_risk_runner as legacy

PROTOCOL_SHA256 = "d35571e4d5b4f60ccde72a1abf266b10d7923a2f71949fb0222f6c1221d51a14"
VERSION = "risk-reconciliation-run-transport-v2"
PHASES = ("identity_match", "independent_review", "adjudication")


def _project(value: Any) -> Any:
    """Remove ONLY uniqueItems from the API schema; runtime validator is unchanged."""
    if isinstance(value, dict):
        return {key: _project(item) for key, item in value.items() if key != "uniqueItems"}
    if isinstance(value, list):
        return [_project(item) for item in value]
    return value


def projected_schema() -> dict[str, Any]:
    return _project(risk.response_schema())


def projection_declaration() -> dict[str, Any]:
    return {"version": "risk-schema-projection-v2", "removed_keywords": ["uniqueItems"],
            "original_schema_sha256": integrity.sha(integrity.canonical_bytes(risk.response_schema())),
            "submitted_schema_sha256": integrity.sha(integrity.canonical_bytes(projected_schema())),
            "validator_unchanged": True, "prompt_unchanged": True, "rubric_unchanged": True,
            "model_unchanged": True, "effort_unchanged": True, "protocol_unchanged": True}


def _schema_failure(attempt: Path, record: dict[str, Any]) -> bool:
    """Read transport ERROR events only, never assistant/raw last-message content."""
    if record.get("returncode") == 0:
        return False
    stdout = attempt / "stdout.jsonl"
    if not stdout.exists():
        return False
    for line in stdout.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = integrity.strict_parse(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "error":
            payload = event
        elif event.get("type") == "turn.failed" and isinstance(event.get("error"), dict):
            payload = event["error"]
        elif isinstance(event.get("item"), dict) and event["item"].get("type") == "error":
            payload = event["item"]
        else:
            continue
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


def _failed_lineage(root: Path, bundles: list[dict[str, Any]], expected: str,
                    seal_pointer: dict[str, Any]) -> dict[str, Any]:
    """Verify failed legacy metadata/packet bytes; never replay accepted opinions."""
    root = Path(root).resolve()
    seal_path = risk._pointer(seal_pointer)
    if seal_path != (root / "terminal-failure-manifest.json").resolve():
        raise ValueError("failed-root seal must bind its immutable terminal failure manifest")
    sealed = _read(seal_path)
    if (sealed.get("version") != "risk-transport-terminal-failure-v1"
            or sealed.get("state") != "sealed_global_schema_rejection"
            or sealed.get("failure_class") != "invalid_json_schema_uniqueItems"
            or sealed.get("accepted_opinions") != 0 or sealed.get("semantic_acceptance") is not False
            or sealed.get("primary_scores_modified") is not False
            or sealed.get("unknown_denominator_retained") is not True):
        raise ValueError("failed-root seal changes preserved failure class or evidence")
    declared = set()
    for item in sealed["files"]:
        if item["path"] in declared:
            raise ValueError("duplicate failed-root inventory path")
        declared.add(item["path"])
        if _sha(transport.local_path(root, item["path"])) != item["sha256"]:
            raise ValueError("failed-root frozen file changed")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
              and path.name not in {"terminal-failure-manifest.json", ".judge-scheduler.lock"}}
    if actual != declared:
        raise ValueError("failed-root seal requires full exact inventory")
    receipts = sealed.get("custody_receipts")
    if not isinstance(receipts, dict) or not receipts:
        raise ValueError("failed-root seal requires drained native custody receipts")
    for path, digest in receipts.items():
        value = _read(risk._pointer({"path": path, "sha256": digest}))
        if (value.get("state") != "drained_released" or value.get("active_callbacks") != 0
                or value.get("owned_job_objects") != 0):
            raise ValueError("old native callbacks/job objects are not proven drained")
        risk._pointer({"path": value["terminal_receipt"], "sha256": value["terminal_sha256"]})
    old = legacy._plan(root, expected)
    incoming = {item["job_id"]: item["envelope"] for item in bundles}
    if set(incoming) != {job["job_id"] for job in old["jobs"]}:
        raise ValueError("transport derivative must retain every original scene job")
    attempted, fingerprints = 0, {}
    if list((root / "responses").rglob("*.json")):
        raise ValueError("legacy accepted opinions cannot be replayed into transport-v2")
    for job in old["jobs"]:
        envelope, prompt, fingerprint = legacy._inputs(root, old, job, "identity_match")
        if envelope != incoming[job["job_id"]] or prompt != risk.prompt(incoming[job["job_id"]]):
            raise ValueError("transport revision changed original packet or prompt")
        fingerprints[job["job_id"]] = fingerprint
        ledger = root / "execution/identity_match" / job["job_id"] / "job.json"
        state = _read(ledger)
        if state.get("status") != "judge_failed" or state.get("fingerprint") != fingerprint:
            raise ValueError("legacy root must have zero accepted opinions and terminal failures")
        attempts = sorted(ledger.parent.glob("attempt-*"))
        if len(attempts) != 2 or len(state.get("attempts", [])) != 2:
            raise ValueError("legacy failed root lacks both preserved bounded attempts")
        for attempt in attempts:
            if not _schema_failure(attempt, _read(attempt / "attempt.json")):
                raise ValueError("legacy failure is not the declared deterministic schema rejection")
            attempted += 1
    inventory = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path)}
                 for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".judge-scheduler.lock"]
    if (sealed.get("expected_scene_jobs") != len(old["jobs"])
            or sealed.get("transport_attempts") != attempted or sealed.get("native_drained_attempts") != attempted):
        raise ValueError("failed-root seal job/attempt/native-drain denominator mismatch")
    return {"version": "risk-failed-transport-lineage-v2", "root": str(root), "terminal_failure_seal": seal_pointer,
            "drained_custody_receipts": receipts,
            "run_plan": {"path": str(root / "run-plan.json"), "sha256": _sha(root / "run-plan.json")},
            "original_job_fingerprints": fingerprints, "files": inventory,
            "original_scene_jobs": len(old["jobs"]), "original_failed_attempts": attempted,
            "accepted_opinions": 0, "accepted_call_replay": False,
            "revision_scope": "actual_transport_schema_only_no_semantic_change"}


def _failure_history(pointer: dict[str, Any]) -> None:
    """Verify failure authority metadata; it never donates another group's opinions."""
    path = risk._pointer(pointer)
    value = _read(path)
    if (path.name != "terminal-failure-manifest.json"
            or value.get("version") != "risk-transport-terminal-failure-v1"
            or value.get("state") != "sealed_global_schema_rejection"
            or value.get("failure_class") != "invalid_json_schema_uniqueItems"
            or value.get("accepted_opinions") != 0 or value.get("semantic_acceptance") is not False
            or value.get("primary_scores_modified") is not False
            or value.get("unknown_denominator_retained") is not True
            or type(value.get("expected_scene_jobs")) is not int or value["expected_scene_jobs"] <= 0
            or type(value.get("transport_attempts")) is not int or value["transport_attempts"] <= 0
            or value.get("transport_attempts") != value.get("native_drained_attempts")):
        raise ValueError("global failure history must preserve sealed zero-acceptance schema rejection")
    declared = set()
    for item in value["files"]:
        if item["path"] in declared:
            raise ValueError("duplicate global failure inventory path")
        declared.add(item["path"])
        if _sha(transport.local_path(path.parent, item["path"])) != item["sha256"]:
            raise ValueError("global failure authority inventory changed")
    actual = {entry.relative_to(path.parent).as_posix() for entry in path.parent.rglob("*")
              if entry.is_file() and entry.name not in {"terminal-failure-manifest.json", ".judge-scheduler.lock"}}
    if declared != actual or not value.get("custody_receipts"):
        raise ValueError("global failure authority requires exact inventory and drained custody")
    for receipt_path, digest in value["custody_receipts"].items():
        receipt = _read(risk._pointer({"path": receipt_path, "sha256": digest}))
        if (receipt.get("state") != "drained_released" or receipt.get("active_callbacks") != 0
                or receipt.get("owned_job_objects") != 0):
            raise ValueError("global failure authority native work not drained")
        risk._pointer({"path": receipt["terminal_receipt"], "sha256": receipt["terminal_sha256"]})


def _fresh_custody(pointer: dict[str, Any], bundles: list[dict[str, Any]]) -> None:
    value = _read(risk._pointer(pointer))
    if (value.get("version") != "risk-fresh-packet-custody-v2"
            or value.get("state") != "frozen_before_first_risk_call"
            or value.get("original_model_calls") != 0 or value.get("accepted_opinions") != 0
            or value.get("bundle_sha256") != {item["job_id"]: risk._hash(item["envelope"]) for item in bundles}):
        raise ValueError("fresh group needs exact no-call packet custody; no accepted opinion reuse")
    risk._pointer(value["source_join_custody"])


def _read(path: Path) -> Any:
    return integrity.strict_parse(path.read_text(encoding="utf-8-sig"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("xb") as stream:
        stream.write(integrity.canonical_bytes(value))
    temporary.replace(path)


def _safe(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", value) is None:
        raise ValueError("job ID must be a safe path component")
    return value


def _implementation() -> dict[str, str]:
    return {name: _sha(Path(module.__file__)) for name, module in (
        ("risk", risk), ("transport", transport), ("integrity", integrity), ("scheduling", scheduling))} | {
            "driver": _sha(Path(__file__))}


def _command_config() -> dict[str, Any]:
    return {"model": transport.MODEL, "effort": transport.EFFORT,
            "overrides": list(transport.OVERRIDES), "disabled_features": list(transport.DISABLED_FEATURES)}


def _protocol(pointer: dict[str, Any], expected: str) -> None:
    path = risk._pointer(pointer)
    value = _read(path)
    if (pointer["sha256"] != expected or value.get("version") != risk.VERSION
            or value.get("state") != "frozen_before_candidate_quality"):
        raise ValueError("protocol differs from reviewed frozen identity")


def _envelope(envelope: dict[str, Any], protocol: dict[str, Any]) -> None:
    if (envelope.get("version") != risk.VERSION or envelope.get("packet_sha256") != risk._hash(envelope["judge_packet"])
            or envelope["custody"]["protocol"] != protocol):
        raise ValueError("anonymous packet/custody/protocol identity mismatch")
    rows = envelope["judge_packet"]["pairs"]
    if not rows or len({row["scene_id"] for row in rows}) != 1:
        raise ValueError("each risk bundle must contain exactly one full scene")
    seals = envelope["custody"]["final_seals"]
    aliases = {envelope["custody"]["baseline_alias"], envelope["custody"]["candidate_alias"]}
    if len(aliases) != 2 or len(seals) != 6 or {(s["seed"], s["alias"]) for s in seals} != {
            (seed, alias) for seed in risk.SEEDS for alias in aliases}:
        raise ValueError("all six paired final seals required")
    for seal in seals:
        risk._seal(seal)
    custody = envelope["custody"]["pairs"]
    if set(custody) != {row["pair_id"] for row in rows}:
        raise ValueError("private pair mapping differs from anonymous scope")
    grids = {seed: set() for seed in risk.SEEDS}
    for row in rows:
        private = custody[row["pair_id"]]
        if private["seed"] not in grids or private["window_id"] in grids[private["seed"]]:
            raise ValueError("duplicate or unknown private seed/window")
        grids[private["seed"]].add(private["window_id"])
        if set(private["side_aliases"].values()) != aliases:
            raise ValueError("private anonymous side mapping invalid")
    if any(grid != grids[risk.SEEDS[0]] for grid in grids.values()):
        raise ValueError("three-seed shared window scope incomplete")


def prepare(root: Path, bundles: list[dict[str, Any]], protocol_pointer: dict[str, Any], *,
            failed_root: Path | None = None, failed_root_seal: dict[str, Any] | None = None,
            global_transport_failure_history: dict[str, Any] | None = None,
            fresh_packet_custody: dict[str, Any] | None = None,
            probe_receipt: dict[str, Any] | None = None,
            _synthetic_probe: bool = False,
            expected_protocol_sha256: str = PROTOCOL_SHA256) -> dict[str, Any]:
    """Freeze per-scene {job_id,envelope} bundles offline; never dispatches."""
    _protocol(protocol_pointer, expected_protocol_sha256)
    if not isinstance(bundles, list) or not bundles:
        raise ValueError("nonempty per-scene bundle list required")
    ids, scenes, seal_sets = set(), set(), set()
    for item in bundles:
        if set(item) != {"job_id", "envelope"}:
            raise ValueError("unexpected bundle input fields")
        job_id = _safe(item["job_id"])
        _envelope(item["envelope"], protocol_pointer)
        scene = item["envelope"]["judge_packet"]["pairs"][0]["scene_id"]
        if job_id in ids or scene in scenes:
            raise ValueError("duplicate risk job or scene")
        ids.add(job_id)
        scenes.add(scene)
        seal_sets.add(tuple(sorted(s["sha256"] for s in item["envelope"]["custody"]["final_seals"])))
    if len(seal_sets) != 1:
        raise ValueError("every scene bundle must bind the same six sealed runs")
    if _synthetic_probe:
        if (len(bundles) != 1 or failed_root is not None or failed_root_seal is not None or probe_receipt is not None
                or global_transport_failure_history is not None or fresh_packet_custody is not None):
            raise ValueError("synthetic transport probe requires one separate packet")
        lineage = None
    else:
        if probe_receipt is None:
            raise ValueError("full transport pool requires successful probe")
        if failed_root is not None:
            if failed_root_seal is None or global_transport_failure_history is not None or fresh_packet_custody is not None:
                raise ValueError("failed derivative requires its own seal, without fresh-group custody")
            lineage = _failed_lineage(failed_root, bundles, expected_protocol_sha256, failed_root_seal)
        else:
            if failed_root_seal is not None or global_transport_failure_history is None or fresh_packet_custody is None:
                raise ValueError("fresh group requires global failure authority and no-call packet custody")
            _failure_history(global_transport_failure_history)
            _fresh_custody(fresh_packet_custody, bundles)
            lineage = None
        _probe_verified(probe_receipt, expected_protocol_sha256)
    root = Path(root).resolve()
    if failed_root is not None and (root == Path(failed_root).resolve() or root.is_relative_to(Path(failed_root).resolve())):
        raise ValueError("new transport root must be distinct from preserved failures")
    root.mkdir(parents=True, exist_ok=False)
    exported = []
    risk.export_bundle(root / "implementation-bundle")
    for name, payload in {"projected-schema.json": integrity.canonical_bytes(projected_schema()),
                          "schema-projection.json": integrity.canonical_bytes(projection_declaration()),
                          "transport-driver.py": Path(__file__).read_bytes()}.items():
        with (root / "implementation-bundle" / name).open("xb") as stream:
            stream.write(payload)
    implementation_bundle = {path.name: _sha(path) for path in (root / "implementation-bundle").iterdir()}
    for item in bundles:
        directory = root / "bundles" / item["job_id"]
        directory.mkdir(parents=True)
        files = {"envelope.json": integrity.canonical_bytes(item["envelope"]),
                 "packet.json": integrity.canonical_bytes(item["envelope"]["judge_packet"]),
                 "original-schema.json": integrity.canonical_bytes(risk.response_schema()),
                 "schema.json": integrity.canonical_bytes(projected_schema()),
                 "schema-projection.json": integrity.canonical_bytes(projection_declaration()),
                 "prompt.txt": risk.prompt(item["envelope"]).encode("utf-8")}
        for name, payload in files.items():
            with (directory / name).open("xb") as stream:
                stream.write(payload)
        exported.append({"job_id": item["job_id"], "bundle": directory.relative_to(root).as_posix(),
                         "artifacts": {name: _sha(directory / name) for name in files}})
    plan = {"version": VERSION, "protocol": protocol_pointer, "implementation": _implementation(),
            "kind": "synthetic_transport_probe" if _synthetic_probe else "full_transport_derivative",
            "synthetic_material_declared": _synthetic_probe,
            "failed_root_lineage": lineage, "probe_receipt": probe_receipt,
            "global_transport_failure_history": global_transport_failure_history,
            "fresh_packet_custody": fresh_packet_custody,
            "schema_projection": projection_declaration(),
            "implementation_bundle": implementation_bundle,
            "command_config": _command_config(), "maximum_attempts": 1 if _synthetic_probe else 2, "maximum_cli_workers": 6,
            "final_seal_sha256": list(next(iter(seal_sets))), "jobs": exported,
            "automatic_dispatch": False, "primary_scores_modified": False}
    with (root / "run-plan.json").open("xb") as stream:
        stream.write(integrity.canonical_bytes(plan))
    (root / "run-plan.sha256").write_text(_sha(root / "run-plan.json") + "\n", encoding="ascii")
    return plan


def _plan(root: Path, expected: str) -> dict[str, Any]:
    if _sha(root / "run-plan.json") != (root / "run-plan.sha256").read_text(encoding="ascii").strip():
        raise ValueError("frozen run plan changed")
    plan = _read(root / "run-plan.json")
    if (plan.get("version") != VERSION or plan.get("implementation") != _implementation()
            or plan.get("command_config") != _command_config()
            or plan.get("maximum_attempts") != (1 if plan.get("kind") == "synthetic_transport_probe" else 2)
            or plan.get("synthetic_material_declared") is not (plan.get("kind") == "synthetic_transport_probe")
            or plan.get("maximum_cli_workers") != 6 or plan.get("automatic_dispatch") is not False):
        raise ValueError("frozen driver/configuration implementation changed")
    _protocol(plan["protocol"], expected)
    if set(plan.get("implementation_bundle", {})) != {"response-schema.json", "judge-prompt.txt", "helper.py", "bundle.json",
                                                     "projected-schema.json", "schema-projection.json", "transport-driver.py"}:
        raise ValueError("incomplete frozen implementation bundle")
    for name, digest in plan["implementation_bundle"].items():
        if _sha(root / "implementation-bundle" / name) != digest:
            raise ValueError("frozen implementation bundle changed")
    if plan.get("schema_projection") != projection_declaration():
        raise ValueError("actual submitted schema projection changed")
    if plan.get("kind") == "full_transport_derivative":
        _probe_verified(plan["probe_receipt"], expected)
        lineage = plan["failed_root_lineage"]
        if lineage is not None:
            risk._pointer(lineage["terminal_failure_seal"])
            for path, digest in lineage["drained_custody_receipts"].items():
                risk._pointer({"path": path, "sha256": digest})
            original_root = Path(lineage["root"])
            for item in lineage["files"]:
                if _sha(transport.local_path(original_root, item["path"])) != item["sha256"]:
                    raise ValueError("preserved failed transport root changed")
        else:
            _failure_history(plan["global_transport_failure_history"])
            bundles = [{"job_id": job["job_id"], "envelope": _read(root / job["bundle"] / "envelope.json")}
                       for job in plan["jobs"]]
            _fresh_custody(plan["fresh_packet_custody"], bundles)
    elif plan.get("kind") != "synthetic_transport_probe":
        raise ValueError("unregistered transport run kind")
    if not plan.get("jobs") or len({job["job_id"] for job in plan["jobs"]}) != len(plan["jobs"]):
        raise ValueError("expected job denominator invalid")
    return plan


def _inputs(root: Path, plan: dict[str, Any], job: dict[str, Any], phase: str) -> tuple[dict[str, Any], str, str]:
    directory = transport.local_path(root, job["bundle"])
    if set(job["artifacts"]) != {"envelope.json", "packet.json", "schema.json", "prompt.txt", "original-schema.json", "schema-projection.json"}:
        raise ValueError("incomplete risk bundle inventory")
    for name, digest in job["artifacts"].items():
        if _sha(directory / name) != digest:
            raise ValueError("frozen bundle bytes changed")
    envelope = _read(directory / "envelope.json")
    _envelope(envelope, plan["protocol"])
    prompt = (directory / "prompt.txt").read_text(encoding="utf-8")
    if (_read(directory / "packet.json") != envelope["judge_packet"]
            or _read(directory / "schema.json") != projected_schema()
            or _read(directory / "original-schema.json") != risk.response_schema()
            or _read(directory / "schema-projection.json") != projection_declaration()
            or prompt != risk.prompt(envelope)):
        raise ValueError("risk packet/schema/prompt mismatch")
    # The first two fresh invocations receive literally identical prompt bytes.
    priors = []
    if phase == "adjudication":
        for earlier in PHASES[:2]:
            state = _previous(root, plan, job, earlier)
            if not state or state["status"] != "succeeded":
                raise ValueError("adjudication requires both fresh accepted passes")
            priors.append(_read(Path(state["response"])))
        if risk._signature(priors[0]) == risk._signature(priors[1]):
            raise ValueError("adjudication requires an identity/evidence disagreement")
        prompt = risk.prompt(envelope, phase="adjudication", prior_responses=priors)
    fingerprint = risk._hash({"job": job, "phase": phase, "protocol": plan["protocol"],
                              "implementation": plan["implementation"], "config": plan["command_config"],
                              "submitted_schema_sha256": _sha(directory / "schema.json"),
                              "schema_projection": plan["schema_projection"],
                              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
    return envelope, prompt, fingerprint


def _previous(root: Path, plan: dict[str, Any], job: dict[str, Any], phase: str) -> dict[str, Any] | None:
    envelope, _, fingerprint = _inputs(root, plan, job, phase)
    directory = root / "execution" / phase / job["job_id"]
    ledger, response = directory / "job.json", root / "responses" / phase / f"{job['job_id']}.json"
    attempts = sorted(directory.glob("attempt-*"))
    if len(attempts) > plan["maximum_attempts"] or [p.name for p in attempts] != [f"attempt-{n}" for n in range(1, len(attempts) + 1)]:
        raise ValueError("bounded contiguous attempt history invalid")
    previous = _read(ledger) if ledger.exists() else None
    if previous and (previous.get("job_id") != job["job_id"] or previous.get("phase") != phase
                     or previous.get("fresh_invocation_id") != f"{phase}/{job['job_id']}"
                     or previous.get("model") != transport.MODEL or previous.get("effort") != transport.EFFORT):
        raise ValueError("accepted logical invocation identity changed")
    if response.exists() and (not previous or previous.get("status") != "succeeded"):
        raise ValueError("canonical response lacks accepted ledger")
    if previous and previous.get("fingerprint") != fingerprint:
        raise ValueError("accepted job fingerprint changed")
    if previous and previous.get("status") == "succeeded":
        if not {"accepted_raw_response_sha256", "response_sha256", "accepted_canonical_snapshot"} <= previous.keys():
            raise ValueError("success lacks original raw/canonical acceptance hashes")
        snapshot = integrity.inside(directory, Path(previous["accepted_canonical_snapshot"]))
        if _sha(snapshot) != previous["response_sha256"]:
            raise ValueError("accepted canonical snapshot changed")
        return integrity.resume_success(previous, ledger, response,
                                        lambda value: risk.validate_response(value, envelope))
    return previous


def _preflight(root: Path, plan: dict[str, Any]) -> None:
    known = {(phase, job["job_id"]) for phase in PHASES for job in plan["jobs"]}
    for ledger in (root / "execution").glob("*/*/job.json"):
        if (ledger.parent.parent.name, ledger.parent.name) not in known:
            raise ValueError("unexpected accepted ledger outside frozen job denominator")
    for response in (root / "responses").glob("*/*.json"):
        if (response.parent.name, response.stem) not in known:
            raise ValueError("unexpected canonical response outside frozen job denominator")
    for job in plan["jobs"]:
        _inputs(root, plan, job, "identity_match")
        for phase in PHASES:
            directory = root / "execution" / phase / job["job_id"]
            if directory.exists() or (root / "responses" / phase / f"{job['job_id']}.json").exists():
                _previous(root, plan, job, phase)


def _receipt(root: Path, plan: dict[str, Any], pointer: dict[str, Any]) -> None:
    receipt = _read(risk._pointer(pointer))
    if (receipt.get("version") != "risk-reconciliation-launch-v1"
            or receipt.get("protocol_sha256") != plan["protocol"]["sha256"]
            or receipt.get("run_plan_sha256") != _sha(root / "run-plan.json")
            or receipt.get("final_seal_sha256") != plan["final_seal_sha256"]
            or receipt.get("root_protocol_reviewed_safe") is not True
            or receipt.get("candidate_risk_calls_authorized") is not True
            or receipt.get("shared_core_complete") is not True
            or receipt.get("maximum_cli_workers") != 6
            or receipt.get("dispatch_owner") != "evaluation_custodian"):
        raise ValueError("launch requires later authorization, reviewed protocol, six seals and completed core")


def _run_job(root: Path, plan: dict[str, Any], job: dict[str, Any], phase: str, *,
             executable: str, cli_version: str, timeout: float,
             invoke: Callable[..., dict[str, Any]], launch_receipt: dict[str, Any],
             schema_stop: threading.Event) -> dict[str, Any]:
    _receipt(root, plan, launch_receipt)
    envelope, prompt, fingerprint = _inputs(root, plan, job, phase)
    previous = _previous(root, plan, job, phase)
    if previous and previous["status"] == "succeeded":
        return previous
    if previous and previous.get("global_invalid_json_schema") is True:
        schema_stop.set()
        return previous  # Never retry deterministic invalid schema with same config.
    if schema_stop.is_set():
        return {"job_id": job["job_id"], "status": "not_run", "attempts": [], "reason": "global_invalid_json_schema"}
    directory = root / "execution" / phase / job["job_id"]
    directory.mkdir(parents=True, exist_ok=True)
    ledger, response = directory / "job.json", root / "responses" / phase / f"{job['job_id']}.json"
    attempts = sorted(directory.glob("attempt-*"))
    state = {"job_id": job["job_id"], "phase": phase, "fingerprint": fingerprint,
             "status": "judge_failed", "response": str(response), "attempts": [],
             "fresh_invocation_id": f"{phase}/{job['job_id']}", "model": transport.MODEL,
             "effort": transport.EFFORT, "cli_version": cli_version, "launch_receipt": launch_receipt}
    for attempt in attempts:
        state["attempts"].append(_read(attempt / "attempt.json") if (attempt / "attempt.json").exists()
                                 else {"attempt": int(attempt.name.split("-")[1]), "status": "interrupted"})
    for number in range(len(attempts) + 1, plan["maximum_attempts"] + 1):
        if schema_stop.is_set():
            break
        started = time.perf_counter()
        attempt = directory / f"attempt-{number}"
        attempt.mkdir()
        (attempt / "schema.json").write_bytes(integrity.canonical_bytes(projected_schema()))
        (attempt / "prompt.txt").write_text(prompt, encoding="utf-8")
        raw = attempt / "last-message.txt"
        record = {"attempt": number, "status": "started", "started_at": transport.utc()}
        _write(attempt / "attempt.json", record)
        with tempfile.TemporaryDirectory(prefix="kototoki-risk-judge-") as temporary:
            cwd = Path(temporary)
            args = transport.command(executable, cwd, attempt / "schema.json", raw)
            record.update(command=args, isolated_cwd=str(cwd), prompt_sha256=_sha(attempt / "prompt.txt"),
                          schema_sha256=_sha(attempt / "schema.json"))
            _write(attempt / "attempt.json", record)
            try:
                record.update(invoke(args, prompt, cwd, attempt, timeout))
            except (OSError, TimeoutError) as exc:
                record.update(transport_status="spawn_failed", returncode=None, transport_error=str(exc))
        try:
            if _schema_failure(attempt, record):
                schema_stop.set()
                state["global_invalid_json_schema"] = True
                raise ValueError("deterministic global invalid_json_schema; identical-config retry prohibited")
            if (record.get("transport_status") != "completed" or record.get("returncode") != 0
                    or record.get("returned_models", []) not in ([], [transport.MODEL])
                    or record.get("returned_efforts", []) not in ([], [transport.EFFORT])
                    or record.get("tool_events", [])):
                raise ValueError("fresh source-only Sol/high transport identity/tool contract failed")
            _receipt(root, plan, launch_receipt)
            _, _, observed_fingerprint = _inputs(root, plan, job, phase)
            if observed_fingerprint != fingerprint:
                raise ValueError("frozen input changed during invocation")
            accepted = integrity.accept_response(raw, response, lambda value: risk.validate_response(value, envelope))
            record["status"] = "succeeded"
            state.update(status="succeeded", **accepted)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            record.update(status="failed", error=str(exc))
            record["access_failure"] = scheduling.classify_access_failure(attempt, record)
        record.update(finished_at=transport.utc(), whole_attempt_seconds=time.perf_counter() - started)
        _write(attempt / "attempt.json", record)
        state["attempts"].append(record)
        _write(ledger, state)
        if state["status"] == "succeeded":
            break  # Valid unknown/disagreement never triggers a format retry.
        if state.get("global_invalid_json_schema") is True:
            break
    _write(ledger, state)
    return state


def _schedule(jobs: list[dict[str, Any]], workers: int, invoke: Callable,
              schema_stop: threading.Event) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Stop refill on first schema rejection; hold guard until submitted work drains."""
    circuit = scheduling.AccessCircuit(transport.utc())
    states, next_index = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        def refill():
            nonlocal next_index
            while not schema_stop.is_set() and not circuit.tripped and len(pending) < workers and next_index < len(jobs):
                index = next_index
                next_index += 1
                pending[pool.submit(invoke, jobs[index])] = index
        refill()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda value: pending[value]):
                pending.pop(future)
                state = future.result()
                states.append(state)
                circuit.observe(state)
            refill()
    for job in jobs[next_index:]:
        states.append({"job_id": job["job_id"], "status": "not_run", "attempts": [],
                       "scheduled_this_invocation": False,
                       "reason": "global_invalid_json_schema" if schema_stop.is_set() else "explicit_access_circuit"})
    metadata = circuit.metadata()
    metadata["global_invalid_json_schema"] = schema_stop.is_set()
    return states, metadata


def run_stage(root: Path, phase: str, *, launch_receipt: dict[str, Any], custody_owner: str,
              dispatch_guard: Callable[[int], AbstractContextManager], invoke: Callable[..., dict[str, Any]],
              executable: str, cli_version: str, workers: int = 6, timeout: float = 300,
              expected_protocol_sha256: str = PROTOCOL_SHA256) -> dict[str, Any]:
    """Run one stage under a shared guard; first/review prompts are identical.

    Guard owns global concurrency/core priority and subprocess draining. Callback
    owns native process containment. Freshness metadata is transport evidence,
    not independent model-family validation. No callback is implicitly selected.
    """
    if phase not in PHASES or custody_owner != "evaluation_custodian" or not callable(dispatch_guard) or not callable(invoke):
        raise ValueError("custodian, explicit native callback, guard and valid phase required")
    if type(workers) is not int or not 1 <= workers <= 6 or type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("workers must be 1..6 and timeout finite positive")
    if not executable or not cli_version:
        raise ValueError("observed executable/CLI version required")
    root = Path(root).resolve()
    with transport.run_lock(root):
        plan = _plan(root, expected_protocol_sha256)
        if plan["kind"] == "synthetic_transport_probe" and (phase != "identity_match" or workers != 1):
            raise ValueError("synthetic probe permits only one fresh identity-match invocation")
        _receipt(root, plan, launch_receipt)
        _preflight(root, plan)  # Entire accepted history, before ANY new dispatch.
        selected, resumed = [], []
        for job in plan["jobs"]:
            if phase != "identity_match":
                primary = _previous(root, plan, job, "identity_match")
                if not primary or primary["status"] != "succeeded":
                    raise ValueError("later phase requires accepted identity match for every scene")
                if phase == "adjudication":
                    review = _previous(root, plan, job, "independent_review")
                    if not review or review["status"] != "succeeded":
                        raise ValueError("adjudication requires accepted independent review")
                    if risk._signature(_read(Path(primary["response"]))) == risk._signature(_read(Path(review["response"]))):
                        continue
            previous = _previous(root, plan, job, phase)
            if previous and previous["status"] == "succeeded":
                resumed.append(previous)
            else:
                selected.append(job)
        schema_stop = threading.Event()
        if any(_read(path).get("global_invalid_json_schema") is True
               for path in (root / "execution").glob("*/*/job.json")):
            schema_stop.set()
        with dispatch_guard(workers):
            _receipt(root, plan, launch_receipt)
            states, circuit = _schedule(selected, workers,
                lambda job: _run_job(root, plan, job, phase, executable=executable, cli_version=cli_version,
                                    timeout=timeout, invoke=invoke, launch_receipt=launch_receipt,
                                    schema_stop=schema_stop), schema_stop)
        states = resumed + states
        summary = {"version": VERSION, "phase": phase, "expected_scene_jobs": len(plan["jobs"]),
                   "selected_jobs": len(selected) + len(resumed), "succeeded": sum(s.get("status") == "succeeded" for s in states),
                   "failed_or_not_run": sum(s.get("status") != "succeeded" for s in states),
                   "not_run": sum(s.get("status") == "not_run" for s in states),
                   "global_invalid_json_schema": circuit["global_invalid_json_schema"],
                   "submitted_schema_sha256": plan["schema_projection"]["submitted_schema_sha256"],
                   "circuit_breaker": {key: circuit[key] for key in ("tripped", "kind", "consecutive")},
                   "accepted_unknown_occurrences": sum(
                       any(evidence["state"] == "unknown" for evidence in item["side_evidence"].values())
                       for state in states if state.get("status") == "succeeded"
                       for group in _read(Path(state["response"]))["roots"] for item in group["occurrences"]),
                   "primary_scores_modified": False,
                   "accepted_calls_modified": False, "semantic_accuracy_verified": False}
        _write(root / f"summary-{phase}.json", summary)
        return summary


def prepare_probe(root: Path, bundle: dict[str, Any], protocol_pointer: dict[str, Any], *,
                  synthetic_material_declared: bool,
                  expected_protocol_sha256: str = PROTOCOL_SHA256) -> dict[str, Any]:
    """Offline preparation of one explicitly synthetic transport probe packet."""
    if synthetic_material_declared is not True:
        raise ValueError("probe must be declared synthetic; actual candidate quality is outside probe scope")
    return prepare(root, [bundle], protocol_pointer, _synthetic_probe=True,
                   expected_protocol_sha256=expected_protocol_sha256)


def run_probe(root: Path, **kwargs: Any) -> dict[str, Any]:
    """Custodian callback runs ONE fresh synthetic call; no implicit network work."""
    root = Path(root).resolve()
    expected = kwargs.get("expected_protocol_sha256", PROTOCOL_SHA256)
    plan = _plan(root, expected)
    if plan["kind"] != "synthetic_transport_probe":
        raise ValueError("run_probe requires separate synthetic probe preparation")
    if kwargs.get("workers", 1) != 1:
        raise ValueError("probe has exactly one worker")
    kwargs["workers"] = 1
    result = run_stage(root, "identity_match", **kwargs)
    if result["succeeded"] != 1:
        return result
    state = _previous(root, plan, plan["jobs"][0], "identity_match")
    if len(state["attempts"]) != 1:
        raise ValueError("probe receipt requires one successful fresh invocation")
    receipt = {"version": "risk-transport-probe-success-v2", "state": "one_fresh_synthetic_probe_accepted",
               "probe_root": str(root), "probe_run_plan": {"path": str(root / "run-plan.json"), "sha256": _sha(root / "run-plan.json")},
               "protocol_sha256": plan["protocol"]["sha256"], "implementation": plan["implementation"],
               "schema_projection": plan["schema_projection"], "job_id": plan["jobs"][0]["job_id"],
               "accepted_raw_response_sha256": state["accepted_raw_response_sha256"],
               "response_sha256": state["response_sha256"], "fingerprint": state["fingerprint"],
               "synthetic_material_only": True, "quality_accuracy_verified": False}
    path = root / "probe-success-receipt.json"
    if path.exists():
        if _read(path) != receipt:
            raise ValueError("immutable successful probe receipt changed")
    else:
        with path.open("xb") as stream:
            stream.write(integrity.canonical_bytes(receipt))
    return {**result, "probe_receipt": {"path": str(path), "sha256": _sha(path)}}


def _probe_verified(pointer: dict[str, Any], expected: str) -> None:
    receipt = _read(risk._pointer(pointer))
    if (receipt.get("version") != "risk-transport-probe-success-v2"
            or receipt.get("state") != "one_fresh_synthetic_probe_accepted"
            or receipt.get("protocol_sha256") != expected or receipt.get("implementation") != _implementation()
            or receipt.get("schema_projection") != projection_declaration() or receipt.get("synthetic_material_only") is not True):
        raise ValueError("full pool requires successful same-schema/code/protocol synthetic transport probe")
    root = Path(receipt["probe_root"])
    risk._pointer(receipt["probe_run_plan"])
    plan = _plan(root, expected)
    if plan["kind"] != "synthetic_transport_probe" or len(plan["jobs"]) != 1 or plan["jobs"][0]["job_id"] != receipt["job_id"]:
        raise ValueError("probe receipt points to another prepared probe")
    state = _previous(root, plan, plan["jobs"][0], "identity_match")
    if not state or state["status"] != "succeeded" or len(state["attempts"]) != 1:
        raise ValueError("probe has no single accepted fresh call")
    for key in ("fingerprint", "accepted_raw_response_sha256", "response_sha256"):
        if receipt[key] != state[key]:
            raise ValueError("probe accepted-byte/fingerprint evidence changed")


def complete(root: Path, *, expected_protocol_sha256: str = PROTOCOL_SHA256) -> dict[str, Any]:
    """Freeze registries offline from accepted calls, then produce quote-free totals."""
    root = Path(root).resolve()
    with transport.run_lock(root):
        plan = _plan(root, expected_protocol_sha256)
        if plan["kind"] != "full_transport_derivative":
            raise ValueError("synthetic probe is not a candidate risk registry")
        _preflight(root, plan)
        summaries, ready = [], []
        for job in plan["jobs"]:
            envelope, _, _ = _inputs(root, plan, job, "identity_match")
            passes, pointers = [], {}
            for phase in PHASES:
                if phase == "adjudication" and not (root / "execution" / phase / job["job_id"]).exists():
                    continue
                state = _previous(root, plan, job, phase)
                if not state or state["status"] != "succeeded":
                    raise ValueError("risk registry incomplete: required fresh pass failed/missing")
                invocation = state["fresh_invocation_id"]
                passes.append({"phase": phase, "response": _read(Path(state["response"])),
                               "fresh_invocation_id": invocation, "model": state["model"], "effort": state["effort"]})
                pointers[invocation] = {"path": state["response"], "sha256": state["response_sha256"]}
            target = root / "registries" / f"{job['job_id']}.json"
            if target.exists():
                raise ValueError("registry already frozen; never overwrite")
            ready.append((envelope, passes, pointers, target))
        # Check the complete scene denominator before publishing any registry.
        for envelope, passes, pointers, target in ready:
            registry = risk.freeze_registry(envelope, passes, pointers=pointers, output=target)
            summaries.append(risk.aggregate_safe(registry))
        summary = {"version": VERSION, "expected_scenes": len(plan["jobs"]), "frozen_scenes": len(summaries),
                   "scenes": summaries, "primary_scores_modified": False, "accepted_calls_modified": False,
                   "semantic_accuracy_verified": False}
        with (root / "risk-summary.json").open("xb") as stream:
            stream.write(integrity.canonical_bytes(summary))
        return summary
