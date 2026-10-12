"""Custom-schema fresh risk driver; dispatch requires a custodian guard/callback.

No semantic run_job, translation, score finalizer, or implicit CLI probe is used.
The custodian supplies the shared global six-slot guard and authorization receipt.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import math
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable

from experiments.translation_judge import integrity, runner as transport, scheduling
from . import v2_risk_reconciliation as risk

PROTOCOL_SHA256 = "d35571e4d5b4f60ccde72a1abf266b10d7923a2f71949fb0222f6c1221d51a14"
VERSION = "risk-reconciliation-run-v1"
PHASES = ("identity_match", "independent_review", "adjudication")


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
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    exported = []
    risk.export_bundle(root / "implementation-bundle")
    implementation_bundle = {path.name: _sha(path) for path in (root / "implementation-bundle").iterdir()}
    for item in bundles:
        directory = root / "bundles" / item["job_id"]
        directory.mkdir(parents=True)
        files = {"envelope.json": integrity.canonical_bytes(item["envelope"]),
                 "packet.json": integrity.canonical_bytes(item["envelope"]["judge_packet"]),
                 "schema.json": integrity.canonical_bytes(risk.response_schema()),
                 "prompt.txt": risk.prompt(item["envelope"]).encode("utf-8")}
        for name, payload in files.items():
            with (directory / name).open("xb") as stream:
                stream.write(payload)
        exported.append({"job_id": item["job_id"], "bundle": directory.relative_to(root).as_posix(),
                         "artifacts": {name: _sha(directory / name) for name in files}})
    plan = {"version": VERSION, "protocol": protocol_pointer, "implementation": _implementation(),
            "implementation_bundle": implementation_bundle,
            "command_config": _command_config(), "maximum_attempts": 2, "maximum_cli_workers": 6,
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
            or plan.get("command_config") != _command_config() or plan.get("maximum_attempts") != 2
            or plan.get("maximum_cli_workers") != 6 or plan.get("automatic_dispatch") is not False):
        raise ValueError("frozen driver/configuration implementation changed")
    _protocol(plan["protocol"], expected)
    if set(plan.get("implementation_bundle", {})) != {"response-schema.json", "judge-prompt.txt", "helper.py", "bundle.json"}:
        raise ValueError("incomplete frozen implementation bundle")
    for name, digest in plan["implementation_bundle"].items():
        if _sha(root / "implementation-bundle" / name) != digest:
            raise ValueError("frozen implementation bundle changed")
    if not plan.get("jobs") or len({job["job_id"] for job in plan["jobs"]}) != len(plan["jobs"]):
        raise ValueError("expected job denominator invalid")
    return plan


def _inputs(root: Path, plan: dict[str, Any], job: dict[str, Any], phase: str) -> tuple[dict[str, Any], str, str]:
    directory = transport.local_path(root, job["bundle"])
    if set(job["artifacts"]) != {"envelope.json", "packet.json", "schema.json", "prompt.txt"}:
        raise ValueError("incomplete risk bundle inventory")
    for name, digest in job["artifacts"].items():
        if _sha(directory / name) != digest:
            raise ValueError("frozen bundle bytes changed")
    envelope = _read(directory / "envelope.json")
    _envelope(envelope, plan["protocol"])
    prompt = (directory / "prompt.txt").read_text(encoding="utf-8")
    if (_read(directory / "packet.json") != envelope["judge_packet"]
            or _read(directory / "schema.json") != risk.response_schema() or prompt != risk.prompt(envelope)):
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
                              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()})
    return envelope, prompt, fingerprint


def _previous(root: Path, plan: dict[str, Any], job: dict[str, Any], phase: str) -> dict[str, Any] | None:
    envelope, _, fingerprint = _inputs(root, plan, job, phase)
    directory = root / "execution" / phase / job["job_id"]
    ledger, response = directory / "job.json", root / "responses" / phase / f"{job['job_id']}.json"
    attempts = sorted(directory.glob("attempt-*"))
    if len(attempts) > 2 or [p.name for p in attempts] != [f"attempt-{n}" for n in range(1, len(attempts) + 1)]:
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
             invoke: Callable[..., dict[str, Any]], launch_receipt: dict[str, Any]) -> dict[str, Any]:
    _receipt(root, plan, launch_receipt)
    envelope, prompt, fingerprint = _inputs(root, plan, job, phase)
    previous = _previous(root, plan, job, phase)
    if previous and previous["status"] == "succeeded":
        return previous
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
    for number in range(len(attempts) + 1, 3):
        started = time.perf_counter()
        attempt = directory / f"attempt-{number}"
        attempt.mkdir()
        (attempt / "schema.json").write_bytes(integrity.canonical_bytes(risk.response_schema()))
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
    _write(ledger, state)
    return state


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
        _receipt(root, plan, launch_receipt)
        _preflight(root, plan)  # Entire accepted history, before ANY new dispatch.
        selected = []
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
            selected.append(job)
        with dispatch_guard(workers):
            _receipt(root, plan, launch_receipt)
            states, circuit = scheduling.schedule_jobs(selected, workers,
                lambda job: _run_job(root, plan, job, phase, executable=executable, cli_version=cli_version,
                                    timeout=timeout, invoke=invoke, launch_receipt=launch_receipt),
                started_at=transport.utc())
        summary = {"version": VERSION, "phase": phase, "expected_scene_jobs": len(plan["jobs"]),
                   "selected_jobs": len(selected), "succeeded": sum(s.get("status") == "succeeded" for s in states),
                   "failed_or_not_run": sum(s.get("status") != "succeeded" for s in states),
                   "circuit_breaker": {key: circuit[key] for key in ("tripped", "kind", "consecutive")},
                   "accepted_unknown_occurrences": sum(
                       any(evidence["state"] == "unknown" for evidence in item["side_evidence"].values())
                       for state in states if state.get("status") == "succeeded"
                       for group in _read(Path(state["response"]))["roots"] for item in group["occurrences"]),
                   "primary_scores_modified": False,
                   "accepted_calls_modified": False, "semantic_accuracy_verified": False}
        _write(root / f"summary-{phase}.json", summary)
        return summary


def complete(root: Path, *, expected_protocol_sha256: str = PROTOCOL_SHA256) -> dict[str, Any]:
    """Freeze registries offline from accepted calls, then produce quote-free totals."""
    root = Path(root).resolve()
    with transport.run_lock(root):
        plan = _plan(root, expected_protocol_sha256)
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
