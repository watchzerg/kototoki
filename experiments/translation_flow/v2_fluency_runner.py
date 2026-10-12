"""Custom-schema fresh CLI sidecar driver; real dispatch is custodian-only.

Preparation is offline. No semantic run_job/import/finalizer is invoked. The
custodian must supply a live global-slot guard and reviewed protocol identity;
declaring an owner string alone does not establish a global concurrency lock.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable

from experiments.translation_judge import integrity, runner as transport, scheduling
from . import v2_fluency as fluency

PROTOCOL_SHA256 = "99327af26582b9d24c0ebe8c8ec39a81a2a53e36d6e8dfc2e0e1c459914165e4"
RUN_SCHEMA = "hy30-flow-v2-fluency-run-v1"
PHASES = {"calibration", "primary", "review"}


def _read(path: Path) -> Any:
    return integrity.strict_parse(path.read_text(encoding="utf-8-sig"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    """Write ledgers atomically; immutable artifacts use exclusive creation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("xb") as handle:
        handle.write(integrity.canonical_bytes(value))
    temporary.replace(path)


def _safe(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,179}", value) is None:
        raise ValueError("Job ID must be a safe single path component")
    return value


def _command_config() -> dict[str, Any]:
    return {"requested_model": transport.MODEL, "requested_effort": transport.EFFORT,
            "overrides": list(transport.OVERRIDES), "disabled_features": list(transport.DISABLED_FEATURES)}


def _implementation() -> dict[str, str]:
    return {"driver": _sha(Path(__file__)), "sidecar": _sha(Path(fluency.__file__)),
            "generic_transport": _sha(Path(transport.__file__)),
            "integrity": _sha(Path(integrity.__file__)), "scheduling": _sha(Path(scheduling.__file__))}


def _protocol(path: Path, expected_sha256: str) -> dict[str, Any]:
    if _sha(path) != expected_sha256:
        raise ValueError("Sidecar protocol differs from frozen reviewed identity")
    value = _read(path)
    if (value.get("profile") != fluency.PROFILE
            or value.get("primary_policy_sha256") != fluency.PRIMARY_POLICY_SHA256
            or value.get("implementation_sha256") != _sha(Path(fluency.__file__))
            or value.get("prompt_sha256") != hashlib.sha256(fluency.PROMPT.encode()).hexdigest()
            or value.get("response_schema_sha256") != fluency.object_hash(fluency.response_schema())
            or value.get("exploration_only") is not True):
        raise ValueError("Protocol/profile/prompt/schema/code binding disagrees")
    return value


def prepare_packets(root: Path, jobs: list[dict[str, Any]], protocol_path: Path, *,
                    expected_protocol_sha256: str = PROTOCOL_SHA256) -> dict[str, Any]:
    """Freeze explicitly supplied source-only packets; never reads model outputs.

    jobs contain only job_id, phase, generation_seed, judge_pass, packet. Repeated
    C0 calibration judgments retain one generation seed and distinct pass IDs.
    expected_protocol_sha256 override exists for isolated synthetic tests only.
    """
    protocol_path = protocol_path.resolve()
    _protocol(protocol_path, expected_protocol_sha256)
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("Explicit nonempty expected job list required")
    checked, keys, logical = [], set(), set()
    for value in jobs:
        if not isinstance(value, dict) or set(value) != {"job_id", "phase", "generation_seed", "judge_pass", "packet"}:
            raise ValueError("Unexpected sidecar preparation fields")
        job_id = _safe(value["job_id"])
        phase, seed, repeat = value["phase"], value["generation_seed"], value["judge_pass"]
        if (not isinstance(phase, str) or phase not in PHASES or type(seed) is not int or seed not in fluency.SEEDS
                or type(repeat) is not int or repeat not in ({1, 2, 3} if phase == "calibration" else {1})):
            raise ValueError("Unregistered phase, seed or judge repetition")
        if phase == "calibration" and seed != fluency.SEEDS[0]:
            raise ValueError("C0 calibration repeats one existing generation seed")
        packet = value["packet"]
        fluency.validate_packet(packet)
        identity = (phase, packet["window_id"], packet["candidate_alias"], seed, repeat)
        if job_id in keys or identity in logical:
            raise ValueError("Duplicate expected job or logical judgment")
        keys.add(job_id)
        logical.add(identity)
        checked.append(dict(value))
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    exported = []
    for value in checked:
        job_id, packet = value["job_id"], value["packet"]
        bundle = root / "bundles" / job_id
        fluency.export_bundle(packet, bundle)
        artifacts = {name: _sha(bundle / name) for name in ("packet.json", "schema.json", "prompt.txt", "bundle.json")}
        exported.append({"job_id": job_id, "window_id": packet["window_id"],
                         "candidate_alias": packet["candidate_alias"],
                         **{key: value[key] for key in ("phase", "generation_seed", "judge_pass")},
                         "bundle": str(bundle.relative_to(root)), "artifacts": artifacts,
                         "response": f"responses/{job_id}.json"})
    plan = {"schema": RUN_SCHEMA, "profile": fluency.PROFILE, "exploration_only": True,
            "protocol_path": str(protocol_path), "protocol_sha256": expected_protocol_sha256,
            "primary_policy_sha256": fluency.PRIMARY_POLICY_SHA256, "command_config": _command_config(),
            "implementation": _implementation(), "maximum_attempts": 2, "maximum_cli_workers": 6,
            "dispatch_owner": "evaluation_custodian", "jobs": exported,
            "expected_jobs": len(exported), "automatic_dispatch": False,
            "stage_zh": "仅冻结显式提供的匿名源文packet及执行身份，未运行裁判；这是传输计划，不是质量或确认结果。"}
    with (root / "run-plan.json").open("xb") as handle:
        handle.write(integrity.canonical_bytes(plan))
    with (root / "run-plan.sha256").open("x", encoding="ascii") as handle:
        handle.write(_sha(root / "run-plan.json") + "\n")
    return plan


def _job_inputs(root: Path, plan: dict[str, Any], job: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    bundle = transport.local_path(root, job["bundle"])
    for name, digest in job["artifacts"].items():
        if name not in {"packet.json", "schema.json", "prompt.txt", "bundle.json"} or _sha(bundle / name) != digest:
            raise ValueError("Frozen packet/prompt/schema/bundle bytes changed")
    if set(job["artifacts"]) != {"packet.json", "schema.json", "prompt.txt", "bundle.json"}:
        raise ValueError("Incomplete immutable bundle identities")
    packet, schema = _read(bundle / "packet.json"), _read(bundle / "schema.json")
    prompt = (bundle / "prompt.txt").read_text(encoding="utf-8")
    fluency.validate_packet(packet)
    if (packet["window_id"], packet["candidate_alias"]) != (job["window_id"], job["candidate_alias"]):
        raise ValueError("Job and packet identities differ")
    if schema != fluency.response_schema() or prompt != fluency.PROMPT + "\nPACKET:\n" + json.dumps(packet, ensure_ascii=False):
        raise ValueError("Sidecar bundle does not use its frozen custom schema/prompt")
    fingerprint = fluency.object_hash({"job": job, "protocol_sha256": plan["protocol_sha256"],
                                      "command_config": plan["command_config"], "implementation": plan["implementation"]})
    return packet, prompt, schema, fingerprint


def _load_plan(root: Path, expected_protocol_sha256: str) -> dict[str, Any]:
    plan_path = root / "run-plan.json"
    if _sha(plan_path) != (root / "run-plan.sha256").read_text(encoding="ascii").strip():
        raise ValueError("Frozen run plan bytes changed")
    plan = _read(plan_path)
    if (plan.get("schema") != RUN_SCHEMA or plan.get("profile") != fluency.PROFILE
            or plan.get("protocol_sha256") != expected_protocol_sha256
            or plan.get("primary_policy_sha256") != fluency.PRIMARY_POLICY_SHA256
            or plan.get("command_config") != _command_config() or plan.get("implementation") != _implementation()
            or plan.get("maximum_attempts") != 2 or plan.get("maximum_cli_workers") != 6
            or plan.get("dispatch_owner") != "evaluation_custodian" or plan.get("automatic_dispatch") is not False):
        raise ValueError("Frozen run profile/configuration/code identity changed")
    _protocol(Path(plan["protocol_path"]), expected_protocol_sha256)
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != plan["expected_jobs"] or not jobs:
        raise ValueError("Incomplete expected job denominator")
    if len({_safe(job["job_id"]) for job in jobs}) != len(jobs):
        raise ValueError("Duplicate frozen job ID")
    return plan


def _previous(root: Path, job: dict[str, Any], packet: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    directory = transport.local_path(root, "execution/" + job["job_id"])
    ledger = directory / "job.json"
    response = transport.local_path(root, job["response"])
    previous = _read(ledger) if ledger.exists() else None
    attempts = sorted(directory.glob("attempt-*"))
    if [p.name for p in attempts] != [f"attempt-{n}" for n in range(1, len(attempts) + 1)] or len(attempts) > 2:
        raise ValueError("Attempt directories violate bounded contiguous history")
    if response.exists() and (previous is None or previous.get("status") != "succeeded"):
        raise ValueError("Canonical response lacks successful transport ledger; preserve evidence")
    if previous and previous.get("fingerprint") != fingerprint:
        raise ValueError("Accepted job fingerprint changed; refuse before dispatch")
    if previous and previous.get("status") == "succeeded":
        if not {"accepted_raw_response_sha256", "response_sha256", "accepted_canonical_snapshot"} <= set(previous):
            raise ValueError("Sidecar success lacks original accepted byte evidence")
        snapshot = integrity.inside(directory, Path(previous["accepted_canonical_snapshot"]))
        if _sha(snapshot) != previous["response_sha256"]:
            raise ValueError("Accepted canonical byte snapshot changed")
        return integrity.resume_success(previous, ledger, response,
                                        lambda value: fluency.validate_response(packet, value))
    return previous


def _run_job(root: Path, plan: dict[str, Any], job: dict[str, Any], *, executable: str,
             cli_version: str, timeout: float, invoke: Callable[..., dict[str, Any]],
             restored_in_preflight: bool = False) -> dict[str, Any]:
    packet, prompt, schema, fingerprint = _job_inputs(root, plan, job)
    previous = _previous(root, job, packet, fingerprint)
    if previous and previous.get("status") == "succeeded":
        previous["canonical_restored"] = previous["canonical_restored"] or restored_in_preflight
        return previous
    directory = transport.local_path(root, "execution/" + job["job_id"])
    directory.mkdir(parents=True, exist_ok=True)
    ledger, response = directory / "job.json", transport.local_path(root, job["response"])
    attempts = sorted(directory.glob("attempt-*"))
    if [p.name for p in attempts] != [f"attempt-{n}" for n in range(1, len(attempts) + 1)] or len(attempts) > 2:
        raise ValueError("Attempt directories violate bounded contiguous history")
    state = {"job_id": job["job_id"], "window_id": job["window_id"], "candidate_alias": job["candidate_alias"],
             "generation_seed": job["generation_seed"], "judge_pass": job["judge_pass"], "phase": job["phase"],
             "profile": fluency.PROFILE, "fingerprint": fingerprint, "requested_model": transport.MODEL,
             "requested_effort": transport.EFFORT, "cli_version": cli_version,
             "cli_version_provenance": "custodian-provided observation, not server-returned identity",
             "status": "judge_failed", "diagnostic_status": "unknown", "response": str(response),
             "protocol_sha256": plan["protocol_sha256"], "attempts": [], "finalized_quality": False}
    for attempt in attempts:
        history = attempt / "attempt.json"
        state["attempts"].append(_read(history) if history.exists() else {
            "attempt": int(attempt.name.split("-")[1]), "status": "interrupted",
            "whole_attempt_seconds": None, "reason_zh": "中断记录保留，仍占一次尝试。"})
    for number in range(len(attempts) + 1, 3):
        started = time.perf_counter()
        attempt = directory / f"attempt-{number}"
        attempt.mkdir(exist_ok=False)
        (attempt / "schema.json").write_bytes(integrity.canonical_bytes(schema))
        (attempt / "prompt.txt").write_text(prompt, encoding="utf-8")
        raw = attempt / "last-message.txt"
        record = {"attempt": number, "started_at": transport.utc(), "status": "started",
                  "whole_attempt_seconds": None}
        _write(attempt / "attempt.json", record)
        with tempfile.TemporaryDirectory(prefix="kototoki-fluency-judge-") as temporary:
            cwd = Path(temporary)
            args = transport.command(executable, cwd, attempt / "schema.json", raw)
            record.update(command=args, isolated_cwd=str(cwd), schema_sha256=_sha(attempt / "schema.json"),
                          prompt_sha256=_sha(attempt / "prompt.txt"))
            _write(attempt / "attempt.json", record)
            try:
                result = invoke(args, prompt, cwd, attempt, timeout)
            except (OSError, TimeoutError) as exc:
                result = {"transport_status": "spawn_failed", "returncode": None,
                          "transport_error": str(exc), "elapsed_seconds": None}
            record.update(result)
        record["finished_at"] = transport.utc()
        try:
            if record.get("transport_status") != "completed" or record.get("returncode") != 0:
                raise ValueError("Fresh CLI transport did not complete successfully")
            if record.get("returned_models", []) not in ([], [transport.MODEL]):
                raise ValueError("Returned model differs from frozen request")
            if record.get("returned_efforts", []) not in ([], [transport.EFFORT]):
                raise ValueError("Returned effort differs from frozen request")
            if record.get("tool_events", []):
                raise ValueError("Judge invoked tools despite source-only contract")
            accepted = integrity.accept_response(raw, response,
                                                  lambda value: fluency.validate_response(packet, value))
            result = _read(response)
            record["status"] = "succeeded"
            state.update(status="succeeded", diagnostic_status=result["status"], **accepted)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            record.update(status="failed", error=str(exc))
        if record["status"] == "failed":
            record["access_failure"] = scheduling.classify_access_failure(attempt, record)
        record["whole_attempt_seconds"] = time.perf_counter() - started
        _write(attempt / "attempt.json", record)
        state["attempts"].append(record)
        _write(ledger, state)
        if state["status"] == "succeeded":
            break  # Valid semantic disagreement/uncertainty is never retried.
    _write(ledger, state)
    return state


def run(root: Path, *, executable: str, cli_version: str, workers: int = 6, timeout: float = 300,
        custody_owner: str, reviewed_protocol_sha256: str,
        dispatch_guard: Callable[[int], AbstractContextManager],
        invoke: Callable[..., dict[str, Any]] = transport.execute,
        expected_protocol_sha256: str = PROTOCOL_SHA256) -> dict[str, Any]:
    """Execute only inside a custodian-supplied live global six-slot guard.

    No CLI version probe or implicit preparation is performed. Successful unknown
    responses remain unknown; success means accepted transport, not final review.
    A guard must hold the shared global reservation until all submitted jobs and
    their child processes drain. Native transport process containment remains the
    custodian's responsibility; this API is not a standalone global limiter.
    """
    if (custody_owner != "evaluation_custodian" or reviewed_protocol_sha256 != expected_protocol_sha256
            or not callable(dispatch_guard)):
        raise ValueError("Dispatch requires sole custodian and reviewed frozen protocol/global-slot guard")
    if (type(workers) is not int or not 1 <= workers <= 6 or type(timeout) not in {int, float}
            or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("workers must be 1..6; timeout must be positive")
    if not isinstance(executable, str) or not executable or not isinstance(cli_version, str) or not cli_version:
        raise ValueError("Custodian must provide executable and observed CLI version")
    root = root.resolve()
    started, started_at = time.perf_counter(), transport.utc()
    with transport.run_lock(root):
        plan = _load_plan(root, expected_protocol_sha256)
        # Validate every bundle and accepted ledger before any new job is dispatched.
        restored = {}
        for job in plan["jobs"]:
            packet, _, _, fingerprint = _job_inputs(root, plan, job)
            previous = _previous(root, job, packet, fingerprint)
            restored[job["job_id"]] = bool(previous and previous.get("canonical_restored"))
        with dispatch_guard(workers):
            states, circuit = scheduling.schedule_jobs(plan["jobs"], workers,
                lambda job: _run_job(root, plan, job, executable=executable, cli_version=cli_version,
                                    timeout=timeout, invoke=invoke,
                                    restored_in_preflight=restored[job["job_id"]]), started_at=started_at)
        by_id = {job["job_id"]: job for job in plan["jobs"]}
        for state in states:
            if state["status"] == "not_run":
                original = by_id[state["job_id"]]
                state.update(profile=fluency.PROFILE, diagnostic_status="unknown", finalized_quality=False,
                             **{key: original[key] for key in ("candidate_alias", "generation_seed", "judge_pass", "phase")})
        states.sort(key=lambda state: state["job_id"])
        durations = [attempt.get("whole_attempt_seconds") for state in states for attempt in state.get("attempts", [])]
        measured = [value for value in durations if isinstance(value, (int, float))]
        summary = {"schema": RUN_SCHEMA, "profile": fluency.PROFILE, "exploration_only": True,
                   "primary_policy_sha256": fluency.PRIMARY_POLICY_SHA256,
                   "protocol_sha256": expected_protocol_sha256, "run_plan_sha256": _sha(root / "run-plan.json"),
                   "requested_model": transport.MODEL, "requested_effort": transport.EFFORT,
                   "cli_version": cli_version, "workers": workers, "dispatch_owner": custody_owner,
                   "global_slot_guard_supplied": True, "expected_jobs": plan["expected_jobs"],
                   "succeeded": sum(s["status"] == "succeeded" for s in states),
                   "judge_failed": sum(s["status"] == "judge_failed" for s in states),
                   "not_run": sum(s["status"] == "not_run" for s in states),
                   "accepted_unknown": sum(s.get("diagnostic_status") == "unknown" and s["status"] == "succeeded" for s in states),
                   "circuit_breaker": circuit, "jobs": states,
                   "command_wall_seconds_this_invocation": time.perf_counter() - started,
                   "all_attempt_seconds": sum(measured) if len(measured) == len(durations) else None,
                   "measured_attempt_seconds_subtotal": sum(measured), "unknown_attempt_durations": len(durations) - len(measured),
                   "billed_cost": None, "billed_cost_reason": "CLI does not expose billed amount; raw usage events remain in attempts",
                   "finalized_quality": False,
                   "limitations_zh": "成功仅表示源文侧轨响应通过传输与证据校验，尚须独立盲复评/必要裁决；全局六槽和子进程排空由负责人提供的guard及执行面保障，模块不自行宣称全局并发验证。"}
        invocation_id = f"{time.time_ns()}"
        _write(root / "invocations" / f"{invocation_id}.json", summary)
        _write(root / "latest-summary.json", summary)
        return summary
