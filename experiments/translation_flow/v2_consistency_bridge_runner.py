"""Closed native runner for separately registered historical-control bridges.

Preparation and proposals grant no dispatch authority. Native dispatch uses the
existing shared guard. Original schemas, validators and structural selection are
unchanged. A full original cohort is authenticated at entry and after draining;
individual dispatches check locally frozen bytes and their original launch.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
import re
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable

from experiments.translation_judge import integrity, runner as transport
from . import v2_consistency as helper, v2_consistency_runner as original
from . import v2_consistency_prompt_contract as prompts
from . import v2_consistency_pair_bridge as bridge, v2_judge_dispatch as native

VERSION = "hy30-consistency-bridge-run-v1"
PROTOCOL_SCHEMA = "hy30-consistency-bridge-material-protocol-v1"
LAUNCH_SCHEMA = "hy30-consistency-bridge-launch-v1"
SEAL_SCHEMA = "hy30-consistency-bridge-stage-seal-v1"
STOP_SCHEMA = "hy30-consistency-bridge-global-stop-v1"
STAGES = original.STAGES
MAXIMUM_ATTEMPTS = {"primary": 2, "independent_review": 2, "adjudication": 1}
ROOT = Path(__file__).resolve().parents[2] / ".local/translation-evaluation/hy30-flow-v2-20261008/evaluation-only"
TERMINAL_SHA256 = prompts.TERMINAL_SHA256
FROZEN = {"helper": original.HELPER_SHA256,
          "original_driver": "b6aebc5a68e54d95012009b09d18dfc24d3edbf4b84b4a674d640237f2f735d8",
          "prompt_contract": "757be87acb4e08ab30fbab6400ed51f105866be34ec5a75d8f44b25571119c03",
          "pair_bridge": "19ef9eb7b8d1193310af68fd0a3c1a123ff9b8658e216f9e89ec8d1d9c08e796"}


def _paths() -> dict[str, Path]:
    return {name: Path(module.__file__).resolve() for name, module in
            {"driver": __import__(__name__, fromlist=["__file__"]), "helper": helper,
             "original_driver": original, "prompt_contract": prompts, "pair_bridge": bridge,
             "native_dispatch": native, "generic_transport": transport,
             "integrity": integrity, "scheduling": original.scheduling}.items()}


def implementation() -> dict[str, str]:
    result = {key: original._sha(path) for key, path in _paths().items()}
    if any(result[key] != digest for key, digest in FROZEN.items()):
        raise ValueError("Frozen consistency implementation changed")
    # This also checks the bridge's independently pinned material verifiers.
    bridge.implementation()
    return result


def identity(path: Path) -> dict[str, str]:
    path = Path(path).resolve()
    return {"path": str(path), "sha256": original._sha(path)}


def phase_contracts() -> dict[str, Any]:
    return prompts.phase_contracts()


def _read(path: Path) -> Any:
    return original._read(path)


def _write(path: Path, value: Any, *, replace: bool = False) -> None:
    if path.exists() and not replace:
        raise FileExistsError("Immutable destination already exists")
    original._write(path, value)


def _ptr(pointer: dict[str, str], expected: str | None = None) -> Path:
    path = original._pointer(pointer, expected)
    if str(path) != pointer["path"] or path.is_symlink():
        raise ValueError("Canonical absolute pointer required")
    return path


def protocol(*, kind: str, shared_root: Path, cohort: dict | None = None,
             registration_pins: dict | None = None, probe_material: dict | None = None,
             profile_qualification: dict | None = None) -> dict:
    """Return a proposal requiring a separate external registration and pin."""
    if kind not in {"full_diagnostic", "handwritten_native_probe"} or Path(shared_root).resolve() != ROOT.resolve():
        raise ValueError("Closed material kind and exact shared custody root required")
    if kind == "full_diagnostic":
        if not cohort or not registration_pins or probe_material is not None:
            raise ValueError("Full cohort and separate pair registration required")
        _ptr(cohort)
    elif cohort is not None or registration_pins is not None or profile_qualification is not None or not probe_material:
        raise ValueError("Handwritten probe cannot inherit candidate material authority")
    else:
        prompts._material(probe_material)
    return {"schema": PROTOCOL_SCHEMA, "state": "proposal", "kind": kind,
            "shared_root": str(ROOT.resolve()), "cohort": deepcopy(cohort),
            "registration_pins": deepcopy(registration_pins), "probe_material": deepcopy(probe_material),
            "profile_qualification": deepcopy(profile_qualification), "implementation": implementation(),
            "phases": phase_contracts(), "command_config": original.command_config(),
            "maximum_attempts": deepcopy(MAXIMUM_ATTEMPTS),
            "adjudication_prompt_sha256": integrity.sha(original.ADJUDICATION_PROMPT.encode()),
            "full_authentication_boundaries": ["stage_entry_or_resume", "post_drain"],
            "automatic_dispatch": False, "primary_scores_modified": False}


def _protocol(pointer: dict, expected: str) -> dict:
    value = _read(_ptr(pointer, expected))
    proposed = protocol(kind=value["kind"], shared_root=Path(value["shared_root"]),
                        cohort=value["cohort"], registration_pins=value["registration_pins"],
                        probe_material=value["probe_material"], profile_qualification=value["profile_qualification"])
    proposed["state"] = "root_registered_material_protocol"
    if value != proposed:
        raise ValueError("Externally registered closed material protocol differs")
    return value


def _cohort(contract: dict) -> dict:
    if contract["kind"] == "handwritten_native_probe":
        return prompts._material(contract["probe_material"])
    return bridge.validate_registered_bridge_receipt(contract["cohort"], **contract["registration_pins"])


def _prepare(root: Path, contract_pointer: dict, expected: str, phase: str | None) -> dict:
    contract = _protocol(contract_pointer, expected)
    cohort = _cohort(contract)
    probe = contract["kind"] == "handwritten_native_probe"
    if probe != (phase is not None) or (probe and phase not in ("A", "B")):
        raise ValueError("Explicit one-phase probe or full cohort required")
    jobs = ([{"job_id": "probe-" + phase, "envelope": cohort["envelopes"][phase]}] if probe else cohort["jobs"])
    original._jobs(jobs, allow_empty=not probe)
    slots = ([{"job_id": jobs[0]["job_id"], "phase": phase, "status": "scheduled"}] if probe else cohort["expected_slots"])
    if not probe:
        scenes = {s["scene_id"] for s in slots}
        observed = {(s["scene_id"], s["seed"], s["phase"]) for s in slots}
        required = {(sid, seed, phase_id) for sid in scenes for seed in helper.SEEDS for phase_id in ("A", "B")}
        if len(scenes) != 29 or len(slots) != 174 or observed != required:
            raise ValueError("Exact full29 x three seeds x A/B denominator required")
    root = Path(root).resolve()
    if not root.is_relative_to(ROOT.resolve()) or root == ROOT.resolve():
        raise ValueError("New run must stay under exact shared custody root")
    root.mkdir(parents=True, exist_ok=False)
    _write(root / "cohort.json", cohort)
    snapshots = {}
    for key, source in _paths().items():
        target = root / "implementation" / (key + ".py")
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(source.read_bytes())
        snapshots[target.relative_to(root).as_posix()] = original._sha(target)
    exported = []
    for job in jobs:
        envelope = job["envelope"]
        phase_id = helper.validate_packet(envelope)["phase"]
        directory = root / "bundles" / job["job_id"]
        directory.mkdir(parents=True)
        files = {"envelope.json": integrity.canonical_bytes(envelope),
                 "packet.json": integrity.canonical_bytes(envelope["judge_packet"]),
                 "schema.json": integrity.canonical_bytes(helper.response_schema(phase_id)),
                 "prompt.txt": prompts.prompt(envelope).encode()}
        for name, payload in files.items():
            (directory / name).write_bytes(payload)
        exported.append({"job_id": job["job_id"], "phase": phase_id,
                         "bundle": directory.relative_to(root).as_posix(),
                         "artifacts": {name: original._sha(directory / name) for name in files}})
    plan = {"schema": VERSION, "kind": contract["kind"], "run_root": str(root), "shared_root": str(ROOT.resolve()),
            "protocol": deepcopy(contract_pointer), "cohort": identity(root / "cohort.json"),
            "implementation": implementation(), "implementation_snapshots": snapshots,
            "phases": phase_contracts(), "command_config": original.command_config(), "jobs": exported,
            "jobs_sha256": helper.object_hash(jobs), "expected_slots": deepcopy(slots),
            "maximum_attempts": ({"primary": 1} if probe else deepcopy(MAXIMUM_ATTEMPTS)),
            "automatic_dispatch": False, "primary_scores_modified": False}
    _write(root / "run-plan.json", plan)
    return identity(root / "run-plan.json")


def prepare_run(root: Path, bridge_receipt: dict, registration_pins: dict, protocol_pointer: dict,
                *, expected_protocol_sha256: str) -> dict:
    contract = _protocol(protocol_pointer, expected_protocol_sha256)
    if contract["kind"] != "full_diagnostic" or contract["cohort"] != bridge_receipt or contract["registration_pins"] != registration_pins:
        raise ValueError("Run material must equal externally registered bridge")
    return _prepare(root, protocol_pointer, expected_protocol_sha256, None)


def prepare_probe(root: Path, phase: str, protocol_pointer: dict, *, expected_protocol_sha256: str) -> dict:
    return _prepare(root, protocol_pointer, expected_protocol_sha256, phase)


def _job_inputs(root: Path, job: dict) -> tuple[dict, str]:
    directory = integrity.inside(root, root / job["bundle"])
    if set(job["artifacts"]) != {"envelope.json", "packet.json", "schema.json", "prompt.txt"}:
        raise ValueError("Closed bundle inventory required")
    for name, digest in job["artifacts"].items():
        if original._sha(directory / name) != digest:
            raise ValueError("Frozen bundle bytes changed")
    envelope = _read(directory / "envelope.json")
    if (helper.validate_packet(envelope)["phase"] != job["phase"]
            or (directory / "packet.json").read_bytes() != integrity.canonical_bytes(envelope["judge_packet"])
            or (directory / "schema.json").read_bytes() != integrity.canonical_bytes(helper.response_schema(job["phase"]))
            or (directory / "prompt.txt").read_bytes() != prompts.prompt(envelope).encode()):
        raise ValueError("Original packet/schema/trusted prompt differs")
    return envelope, (directory / "prompt.txt").read_text(encoding="utf-8")


def _plan(root: Path, expected: str, *, full_local: bool = True) -> tuple[dict, dict]:
    root = Path(root).resolve()
    plan = _read(_ptr(identity(root / "run-plan.json"), expected))
    contract = _protocol(plan["protocol"], plan["protocol"]["sha256"])
    if (plan.get("schema") != VERSION or plan.get("run_root") != str(root) or plan.get("shared_root") != str(ROOT.resolve())
            or not root.is_relative_to(ROOT.resolve()) or root == ROOT.resolve()
            or plan.get("kind") != contract["kind"] or plan.get("implementation") != implementation()
            or plan.get("phases") != phase_contracts() or plan.get("command_config") != original.command_config()
            or plan.get("automatic_dispatch") is not False or plan.get("primary_scores_modified") is not False
            or plan.get("maximum_attempts") != ({"primary": 1} if plan["kind"] == "handwritten_native_probe" else MAXIMUM_ATTEMPTS)):
        raise ValueError("Exact root/code/material plan changed")
    if _ptr(plan["cohort"]) != root / "cohort.json":
        raise ValueError("Local cohort must be frozen in this run")
    for key, digest in plan["implementation"].items():
        path = root / "implementation" / (key + ".py")
        if original._sha(path) != digest or plan["implementation_snapshots"].get(path.relative_to(root).as_posix()) != digest:
            raise ValueError("Frozen code snapshot changed")
    if full_local:
        jobs = [{"job_id": j["job_id"], "envelope": _job_inputs(root, j)[0]} for j in plan["jobs"]]
        original._jobs(jobs, allow_empty=plan["kind"] == "full_diagnostic")
        cohort = _read(root / "cohort.json")
        expected_jobs = ([{"job_id": "probe-" + plan["jobs"][0]["phase"], "envelope": cohort["envelopes"][plan["jobs"][0]["phase"]]}]
                         if plan["kind"] == "handwritten_native_probe" else cohort["jobs"])
        if helper.object_hash(jobs) != plan["jobs_sha256"] or jobs != expected_jobs:
            raise ValueError("Frozen complete job inventory differs")
        if plan["kind"] == "full_diagnostic" and plan["expected_slots"] != cohort["expected_slots"]:
            raise ValueError("Fixed denominator changed")
    return plan, contract


def _full_authentication(root: Path, plan: dict, contract: dict) -> None:
    if _cohort(contract) != _read(_ptr(plan["cohort"])):
        raise ValueError("Original cohort reauthentication differs from frozen material")


def _stage_root(root: Path, stage: str) -> Path:
    if stage not in STAGES:
        raise ValueError("Unknown diagnostic stage")
    return root / "stages" / stage


def launch_proposal(root: Path, stage: str, *, expected_plan_sha256: str, executable: str,
                    cli_version: str, terminal_receipt: dict, workers: int = 6,
                    _full_local: bool = True) -> dict:
    root = Path(root).resolve()
    plan, contract = _plan(root, expected_plan_sha256, full_local=_full_local)
    _stage_root(root, stage)
    if type(workers) is not int or not 1 <= workers <= 6 or not cli_version:
        raise ValueError("Explicit native worker count and CLI version required")
    if plan["kind"] == "handwritten_native_probe" and (stage != "primary" or workers != 1):
        raise ValueError("New handwritten probe permits one primary worker only")
    _ptr(terminal_receipt, TERMINAL_SHA256)
    integrity.inside(ROOT.resolve(), Path(terminal_receipt["path"]))
    priors = {s: identity(_stage_root(root, s) / "seal.json") for s in STAGES[:STAGES.index(stage)]}
    return {"schema": LAUNCH_SCHEMA, "state": "proposal", "run_root": str(root), "shared_root": str(ROOT.resolve()),
            "global_lock": str(ROOT.resolve() / ".judge-global-six.lock"), "stage": stage,
            "plan": identity(root / "run-plan.json"), "protocol": deepcopy(plan["protocol"]),
            "implementation": implementation(), "native_dispatch_sha256": implementation()["native_dispatch"],
            "executable": identity(Path(executable)), "cli_version": cli_version, "terminal_receipt": deepcopy(terminal_receipt),
            "maximum_workers": workers, "dispatch_owner": "evaluation_custodian",
            "profile_qualification": deepcopy(contract["profile_qualification"]), "prior_stage_seals": priors}


def _qualification(value: dict | None, plan: dict, launch: dict) -> None:
    if plan["kind"] == "handwritten_native_probe":
        if value is not None:
            raise ValueError("Probe cannot inherit profile qualification")
        return
    if not isinstance(value, dict) or set(value) != {"A", "B"}:
        raise ValueError("Two NEW externally pinned native profile probes required")
    for phase, pointers in value.items():
        if not isinstance(pointers, dict) or set(pointers) != {"plan", "seal"}:
            raise ValueError("Exact new probe plan/seal pointers required")
        probe_root = _ptr(pointers["plan"]).parent
        probe_plan, _ = _plan(probe_root, pointers["plan"]["sha256"])
        if (probe_plan["kind"] != "handwritten_native_probe" or len(probe_plan["jobs"]) != 1
                or probe_plan["jobs"][0]["phase"] != phase or probe_plan["phases"] != plan["phases"]):
            raise ValueError("Historical or another-profile probe is not new authority")
        if _ptr(pointers["seal"]) != _stage_root(probe_root, "primary") / "seal.json":
            raise ValueError("New probe seal root differs")
        seal = validate_run_receipt(probe_root, "primary", expected_plan_sha256=pointers["plan"]["sha256"],
                                    expected_seal_sha256=pointers["seal"]["sha256"])
        states = _read(_stage_root(probe_root, "primary") / "jobs.json")
        prior_launch = _read(_ptr(seal["launch"]))
        if (len(states) != 1 or states[0]["status"] != "succeeded" or len(states[0]["attempts"]) != 1
                or prior_launch["executable"] != launch["executable"] or prior_launch["cli_version"] != launch["cli_version"]
                or prior_launch["maximum_workers"] != 1):
            raise ValueError("New native probe must have one accepted original attempt with exact CLI")


def _authority(root: Path, plan: dict, pointer: dict, expected: str, executable: str,
               cli_version: str, workers: int, *, qualify: bool = True) -> dict:
    launch = _read(_ptr(pointer, expected))
    proposal = launch_proposal(root, launch["stage"], expected_plan_sha256=identity(root / "run-plan.json")["sha256"],
                               executable=executable, cli_version=cli_version, terminal_receipt=launch["terminal_receipt"], workers=workers,
                               _full_local=False)
    proposal["state"] = "root_authorized_exact_stage"
    if launch != proposal:
        raise ValueError("Exact externally pinned stage launch differs")
    if qualify:
        _qualification(launch["profile_qualification"], plan, launch)
    return launch


def _stop(root: Path, plan: dict, reason: str, *, stage: str, job_id: str | None = None) -> None:
    path = root / "global-stop.json"
    value = {"schema": STOP_SCHEMA, "plan": identity(root / "run-plan.json"), "protocol": plan["protocol"],
             "implementation": plan["implementation"], "reason": reason, "stage": stage, "job_id": job_id}
    if not path.exists():
        _write(path, value)


def _stopped(root: Path, plan: dict) -> bool:
    path = root / "global-stop.json"
    if not path.exists():
        return False
    value = _read(path)
    if (value.get("schema") != STOP_SCHEMA or value.get("plan") != identity(root / "run-plan.json")
            or value.get("protocol") != plan["protocol"] or value.get("implementation") != plan["implementation"]
            or value.get("stage") not in STAGES or value.get("reason") not in {"invalid_json_schema", "native_identity", "integrity"}):
        raise ValueError("Durable global stop binding changed")
    return True


def _native_identity(record: dict, launch: dict, guard: Any | None = None) -> None:
    if (record.get("native_dispatch_sha256") != launch["native_dispatch_sha256"]
            or record.get("returned_models", []) not in ([], [transport.MODEL])
            or record.get("returned_efforts", []) not in ([], [transport.EFFORT]) or record.get("tool_events", [])
            or record.get("custody_workers_reserved") != launch["maximum_workers"]
            or not record.get("custody_token") or not record.get("custody_receipt")):
        raise ValueError("Native identity/tools/custody mismatch")
    if guard is not None and (record["custody_token"] != guard.token or record["custody_receipt"] != str(guard.owner_record)):
        raise ValueError("Invocation belongs to another original native lease")
    if record.get("transport_status") != "spawn_failed" or record.get("native_root_pid"):
        if (record.get("containment") != "suspended-assign-resume-kill-on-close-job"
                or record.get("native_drain_proven") is not True or record.get("native_active_processes_after_drain") != 0):
            raise ValueError("Started native invocation lacks positive process drain")


def _drained(record: dict, launch: dict) -> None:
    _native_identity(record, launch)
    pointer = record.get("drained_lease")
    path = _ptr(pointer)
    if path != Path(record["custody_receipt"]).resolve():
        raise ValueError("Original drained lease pointer differs")
    integrity.inside(ROOT.resolve() / ".judge-dispatch-receipts", path)
    value = _read(path)
    if (value.get("schema") != "hy30-native-judge-custody-v1" or value.get("state") != "drained_released"
            or value.get("owner") != "evaluation_custodian" or value.get("token") != record["custody_token"]
            or value.get("global_lock") != launch["global_lock"] or value.get("shared_limit") != 6
            or value.get("workers_reserved") != launch["maximum_workers"]
            or value.get("terminal_sha256") != launch["terminal_receipt"]["sha256"]
            or value.get("terminal_receipt") != launch["terminal_receipt"]["path"]
            or value.get("module_sha256") != launch["native_dispatch_sha256"]
            or value.get("active_callbacks") != 0 or value.get("owned_job_objects") != 0):
        raise ValueError("Original native lease has no independently pinned positive drain")
    _ptr(launch["terminal_receipt"], TERMINAL_SHA256)


def _state(root: Path, stage: str, job_id: str) -> dict | None:
    path = _stage_root(root, stage) / "execution" / job_id / "job.json"
    return _read(path) if path.exists() else None


def _inputs(root: Path, job: dict, stage: str) -> tuple[dict, str]:
    envelope, prompt = _job_inputs(root, job)
    if stage == "adjudication":
        opinions = []
        for prior in STAGES[:2]:
            state = _state(root, prior, job["job_id"])
            if not state or state["status"] != "succeeded":
                raise ValueError("Adjudication requires both original accepted opinions")
            opinions.append(_read(_ptr(state["response"])))
        prompt += original.ADJUDICATION_PROMPT + integrity.canonical_bytes(opinions).decode()
    return envelope, prompt


def _attempts(root: Path, plan: dict) -> list[tuple[Path, dict]]:
    known = {j["job_id"]: j for j in plan["jobs"]}
    result, launches = [], {}
    for stage_dir in (root / "stages").glob("*"):
        if not stage_dir.is_dir() or stage_dir.name not in STAGES:
            raise ValueError("Unknown stage inventory")
        for directory in (stage_dir / "execution").glob("*"):
            if not directory.is_dir() or directory.name not in known:
                raise ValueError("Attempt outside fixed denominator")
            job = known[directory.name]
            paths = sorted(directory.glob("attempt-*"), key=lambda p: int(p.name.split("-")[-1]))
            maximum = plan["maximum_attempts"].get(stage_dir.name, 0)
            if len(paths) > maximum or [p.name for p in paths] != ["attempt-" + str(n) for n in range(1, len(paths) + 1)]:
                raise ValueError("Original attempt limits/contiguous inventory differ")
            state = _state(root, stage_dir.name, job["job_id"])
            if (not state or state.get("job_id") != job["job_id"] or state.get("stage") != stage_dir.name
                    or state.get("status") not in {"succeeded", "judge_failed"} or len(state.get("attempts", [])) != len(paths)):
                raise ValueError("Missing original attempt ledger")
            for path, stored in zip(paths, state["attempts"], strict=True):
                record = _read(path / "attempt.json")
                launch_key = (record["launch"]["path"], record["launch"]["sha256"])
                if launch_key not in launches:
                    launch = _read(_ptr(record["launch"]))
                    _authority(root, plan, record["launch"], record["launch"]["sha256"], launch["executable"]["path"],
                               launch["cli_version"], launch["maximum_workers"], qualify=False)
                    launches[launch_key] = launch
                launch = launches[launch_key]
                envelope, prompt = _inputs(root, job, stage_dir.name)
                if (record != stored or record.get("stage") != stage_dir.name or record.get("job_id") != job["job_id"]
                        or launch["stage"] != stage_dir.name or record.get("implementation") != plan["implementation"]
                        or record.get("prompt_sha256") != integrity.sha(prompt.encode())
                        or record.get("schema_sha256") != job["artifacts"]["schema.json"]
                        or (path / "prompt.txt").read_bytes() != prompt.encode()
                        or original._sha(path / "schema.json") != job["artifacts"]["schema.json"]
                        or (path / "stdin.bin").read_bytes() != prompt.encode()
                        or record.get("argv") != transport.command(launch["executable"]["path"], path / "cwd", path / "schema.json", path / "last-message.txt")):
                    raise ValueError("Original submitted native bytes/command/ledger changed")
                expected_native_files = {n for n in ("stdin.bin", "stdout.jsonl", "stderr.txt", "last-message.txt") if (path / n).exists()}
                if (set(record.get("native_files", {})) != expected_native_files
                        or not {"stdin.bin", "stdout.jsonl", "stderr.txt"} <= expected_native_files):
                    raise ValueError("Original native byte inventory is incomplete")
                for name, digest in record["native_files"].items():
                    if original._sha(path / name) != digest:
                        raise ValueError("Original native output bytes changed")
                if (state.get("global_invalid_json_schema") or original._schema_failure(path, record)) and not _stopped(root, plan):
                    raise ValueError("Original invalid_json_schema requires durable global stop")
                _drained(record, launch)
                if record["status"] == "succeeded":
                    raw = path / "last-message.txt"
                    accepted = _read(_ptr(record["response"]))
                    if original._sha(raw) != record["accepted_raw_response_sha256"]:
                        raise ValueError("Accepted original response bytes changed")
                    if helper.validate_response(envelope, integrity.strict_parse(raw.read_text(encoding="utf-8-sig"))) != accepted:
                        raise ValueError("Accepted response no longer matches original validator")
                    if (_ptr({"path": record["accepted_canonical_snapshot"], "sha256": record["response_sha256"]}) != path / "accepted-canonical.json"
                            or _ptr(record["response"]) != path.parent / "response.json"
                            or record["response"]["sha256"] != record["response_sha256"]
                            or state["status"] != "succeeded"
                            or any(state.get(k) != record.get(k) for k in ("response", "accepted_raw_response", "accepted_raw_response_sha256", "response_sha256", "accepted_canonical_snapshot"))):
                        raise ValueError("Original accepted job identity differs from attempt")
                result.append((path, record))
            if state["status"] == "succeeded" and (not paths or state["attempts"][-1]["status"] != "succeeded"):
                raise ValueError("Successful state lacks original accepted final attempt")
    return result


def _inventory(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): original._sha(p) for p in sorted(directory.rglob("*"))
            if p.is_file() and p != directory / "seal.json"}


def _validate_seal_local(root: Path, stage: str, plan: dict, pointer: dict) -> dict:
    path = _ptr(pointer)
    directory = _stage_root(root, stage)
    value = _read(path)
    if (path != directory / "seal.json" or value.get("schema") != SEAL_SCHEMA or value.get("stage") != stage
            or value.get("plan") != identity(root / "run-plan.json") or value.get("protocol") != plan["protocol"]
            or value.get("inventory") != _inventory(directory) or value.get("implementation") != plan["implementation"]):
        raise ValueError("Independently pinned original stage prefix seal differs")
    launch = _read(_ptr(value["launch"]))
    summary = _read(_ptr(value["summary"]))
    if value.get("global_stop") != summary.get("global_stop"):
        raise ValueError("Original stage summary and global stop binding differ")
    if value["global_stop"] is not None:
        if _ptr(value["global_stop"]) != root / "global-stop.json" or not _stopped(root, plan):
            raise ValueError("Original independently pinned global stop is missing or changed")
    _authority(root, plan, value["launch"], value["launch"]["sha256"], launch["executable"]["path"], launch["cli_version"], launch["maximum_workers"], qualify=False)
    for prior, seal in launch["prior_stage_seals"].items():
        _validate_seal_local(root, prior, plan, seal)
    return value


def validate_run_receipt(root: Path, stage: str, *, expected_plan_sha256: str, expected_seal_sha256: str) -> dict:
    """Offline replay requires the independent original seal hash, never itself."""
    root = Path(root).resolve()
    plan, contract = _plan(root, expected_plan_sha256)
    _full_authentication(root, plan, contract)
    _attempts(root, plan)
    _stopped(root, plan)
    seal = _validate_seal_local(root, stage, plan, {"path": str(_stage_root(root, stage) / "seal.json"), "sha256": expected_seal_sha256})
    return {**seal, **_read(_ptr(seal["summary"]))}


def _selection(root: Path, plan: dict, stage: str) -> tuple[list[dict], list[dict], dict]:
    selected, states, primary_unknown = [], [], {}
    for job in plan["jobs"]:
        uid = job["job_id"]
        if stage == "independent_review":
            primary = _state(root, "primary", uid)
            primary_unknown[uid] = not primary or primary["status"] != "succeeded" or _read(_ptr(primary["response"]))["status"] == "unknown"
        if stage == "adjudication":
            prior = [_state(root, s, uid) for s in STAGES[:2]]
            if any(not s or s["status"] != "succeeded" for s in prior):
                states.append({"job_id": uid, "status": "not_run", "reason": "earlier_opinion_not_accepted"})
                continue
            opinions = [_read(_ptr(s["response"])) for s in prior]
            if original.structural_signature(opinions[0], job["phase"]) == original.structural_signature(opinions[1], job["phase"]):
                states.append({"job_id": uid, "status": "not_required_agreed", "reason": "no_structural_disagreement", "agreed_unknown": opinions[0]["status"] == "unknown"})
                continue
        state = _state(root, stage, uid)
        if state and (state["status"] == "succeeded" or state.get("terminal_evidence_failure") or state.get("terminal_identity_failure")
                      or len(state["attempts"]) >= plan["maximum_attempts"][stage]):
            states.append(state)
        else:
            selected.append(job)
    return selected, states, primary_unknown


def run_stage(root: Path, stage: str, *, launch_receipt: dict, expected_launch_sha256: str,
              expected_plan_sha256: str, dispatch_guard: Callable, invoke: Callable,
              executable: str, cli_version: str, workers: int = 6, timeout: float = 300,
              expected_existing_seal_sha256: str | None = None) -> dict:
    """Run only the exact externally authorized stage through native custody."""
    if (stage not in STAGES or invoke is not native.execute or not callable(dispatch_guard)
            or type(workers) is not int or not 1 <= workers <= 6
            or type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("Concrete native callback/stage/workers/timeout required")
    root = Path(root).resolve()
    with transport.run_lock(root):
        plan, contract = _plan(root, expected_plan_sha256)
        try:
            launch = _authority(root, plan, launch_receipt, expected_launch_sha256, executable, cli_version, workers)
            if launch["stage"] != stage:
                raise ValueError("Exact stage launch required")
            _full_authentication(root, plan, contract)
            _attempts(root, plan)
            for prior, ptr in launch["prior_stage_seals"].items():
                _validate_seal_local(root, prior, plan, ptr)
            _stopped(root, plan)
        except (ValueError, KeyError, TypeError, OSError):
            _stop(root, plan, "integrity", stage=stage)
            raise
        directory = _stage_root(root, stage)
        if (directory / "seal.json").exists():
            if expected_existing_seal_sha256 is None:
                raise ValueError("Resume of sealed stage requires independent original seal hash")
            _validate_seal_local(root, stage, plan, {"path": str(directory / "seal.json"), "sha256": expected_existing_seal_sha256})
            return identity(directory / "seal.json")
        selected, states, primary_unknown = _selection(root, plan, stage)
        stop_lock = threading.Lock()
        results: dict[str, dict] = {s["job_id"]: s for s in states}

        def halt(reason: str, uid: str) -> None:
            with stop_lock:
                _stop(root, plan, reason, stage=stage, job_id=uid)

        for wave in range(plan["maximum_attempts"][stage]):
            if _stopped(root, plan) or not selected:
                break
            # Each retry is a new drained lease, not another callback under an
            # unclosed old lease. Verify every original prior attempt first.
            _attempts(root, plan)
            completed: list[tuple[Path, dict, dict]] = []
            with dispatch_guard(workers) as guard:
                if (type(guard) is not native.CustodyGuard or not guard.entered or guard.owner != "evaluation_custodian"
                        or native._ACTIVE_GUARD is not guard or guard.closing
                        or guard.workers != workers or guard.root.resolve() != ROOT.resolve()
                        or str(guard.root / ".judge-global-six.lock") != launch["global_lock"]
                        or str(guard.terminal_receipt) != launch["terminal_receipt"]["path"]
                        or guard.terminal_sha256 != launch["terminal_receipt"]["sha256"]
                        or guard.implementation_sha256 != launch["native_dispatch_sha256"]):
                    halt("native_identity", "guard")
                    raise ValueError("Concrete guard differs from externally pinned native custody")

                def run_job(job: dict) -> tuple[Path, dict, dict]:
                    uid = job["job_id"]
                    old = _state(root, stage, uid)
                    attempts = deepcopy(old["attempts"]) if old else []
                    path = directory / "execution" / uid / ("attempt-" + str(len(attempts) + 1))
                    path.mkdir(parents=True, exist_ok=False)
                    record = {"stage": stage, "job_id": uid, "status": "started", "launch": deepcopy(launch_receipt),
                              "implementation": plan["implementation"]}
                    state = {"job_id": uid, "stage": stage, "status": "judge_failed", "attempts": attempts}
                    try:
                        _plan(root, expected_plan_sha256, full_local=False)
                        _authority(root, plan, launch_receipt, expected_launch_sha256, executable, cli_version, workers, qualify=False)
                        if native._ACTIVE_GUARD is not guard or guard.closing:
                            halt("native_identity", uid)
                            raise ValueError("Actual active native guard changed before callback")
                        envelope, prompt = _inputs(root, job, stage)
                        (path / "schema.json").write_bytes(integrity.canonical_bytes(helper.response_schema(job["phase"])))
                        (path / "prompt.txt").write_bytes(prompt.encode())
                        (path / "cwd").mkdir()
                        argv = transport.command(executable, path / "cwd", path / "schema.json", path / "last-message.txt")
                        record.update(prompt_sha256=integrity.sha(prompt.encode()), schema_sha256=job["artifacts"]["schema.json"], argv=argv)
                        _write(path / "attempt.json", record)
                        if native._ACTIVE_GUARD is not guard or guard.closing:
                            halt("native_identity", uid)
                            raise ValueError("Actual active native guard changed immediately before callback")
                        returned = invoke(argv, prompt, str(path / "cwd"), path, timeout)
                        record.update(returned)
                        record["native_files"] = {n: original._sha(path / n) for n in ("stdin.bin", "stdout.jsonl", "stderr.txt", "last-message.txt") if (path / n).exists()}
                        try:
                            _native_identity(record, launch, guard)
                        except (ValueError, KeyError, TypeError):
                            state["terminal_identity_failure"] = True
                            halt("native_identity", uid)
                            raise
                        if original._schema_failure(path, record):
                            state["global_invalid_json_schema"] = True
                            halt("invalid_json_schema", uid)
                            raise ValueError("Native invalid_json_schema stops every stage")
                        if record.get("transport_status") != "completed" or record.get("returncode") != 0:
                            raise ValueError("Native transport failed")
                        try:
                            _plan(root, expected_plan_sha256, full_local=False)
                            _authority(root, plan, launch_receipt, expected_launch_sha256, executable, cli_version, workers, qualify=False)
                            if ((path / "stdin.bin").read_bytes() != prompt.encode()
                                    or _inputs(root, job, stage)[1] != prompt
                                    or original._sha(path / "schema.json") != record["schema_sha256"]
                                    or original._sha(path / "prompt.txt") != record["prompt_sha256"]):
                                raise ValueError("Submitted native bytes changed")
                        except (ValueError, KeyError, TypeError, OSError):
                            halt("integrity", uid)
                            state["terminal_identity_failure"] = True
                            raise

                        def validate(value: dict) -> dict:
                            helper._shape(value, helper.response_schema(job["phase"]))
                            try:
                                return helper.validate_response(envelope, value)
                            except (ValueError, KeyError, TypeError) as exc:
                                state["terminal_evidence_failure"] = True
                                raise ValueError("Original evidence/coverage mismatch; no retry") from exc

                        response_path = path.parent / "response.json"
                        accepted = integrity.accept_response(path / "last-message.txt", response_path, validate)
                        state.update(accepted, status="succeeded", response=identity(response_path))
                        record.update(accepted, status="succeeded", response=identity(response_path))
                    except (ValueError, KeyError, TypeError, OSError) as exc:
                        record.update(status="failed", error=str(exc))
                        if not record.get("custody_receipt"):
                            halt("integrity", uid)
                            state["terminal_identity_failure"] = True
                    _write(path / "attempt.json", record, replace=True)
                    state["attempts"].append(record)
                    _write(path.parent / "job.json", state, replace=(path.parent / "job.json").exists())
                    return path, record, state

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    pending, index = {}, 0
                    while pending or (index < len(selected) and not _stopped(root, plan)):
                        while index < len(selected) and len(pending) < workers and not _stopped(root, plan):
                            pending[pool.submit(run_job, selected[index])] = index
                            index += 1
                        if pending:
                            done, _ = wait(pending, return_when=FIRST_COMPLETED)
                            for future in sorted(done, key=lambda f: pending[f]):
                                pending.pop(future)
                                completed.append(future.result())
                for job in selected[index:]:
                    results[job["job_id"]] = {"job_id": job["job_id"], "status": "not_run", "reason": "durable_global_stop", "attempts": []}
            # The guard has now sealed the original positive drain. Attach its
            # exact bytes to each attempt before any later wave/stage dispatch.
            for path, record, state in completed:
                try:
                    record["drained_lease"] = identity(Path(record["custody_receipt"]))
                    _drained(record, launch)
                except (ValueError, KeyError, TypeError, OSError):
                    halt("native_identity", record["job_id"])
                    _write(path / "attempt.json", record, replace=True)
                    state["attempts"][-1] = record
                    _write(path.parent / "job.json", state, replace=True)
                    raise
                _write(path / "attempt.json", record, replace=True)
                state["attempts"][-1] = record
                _write(path.parent / "job.json", state, replace=True)
                results[state["job_id"]] = state
            selected = [job for job in selected if (results.get(job["job_id"], {}).get("status") == "judge_failed"
                        and not results[job["job_id"]].get("terminal_identity_failure")
                        and not results[job["job_id"]].get("terminal_evidence_failure")
                        and len(results[job["job_id"]]["attempts"]) < plan["maximum_attempts"][stage])]
        for job in selected:
            results.setdefault(job["job_id"], {"job_id": job["job_id"], "status": "not_run", "reason": "durable_global_stop", "attempts": []})
        ordered = [results[j["job_id"]] for j in plan["jobs"]]
        try:
            _plan(root, expected_plan_sha256)
            _full_authentication(root, plan, contract)
            _attempts(root, plan)
        except (ValueError, KeyError, TypeError, OSError):
            _stop(root, plan, "integrity", stage=stage)
            raise
        # Reuse the original fixed UNKNOWN accounting without modifying any
        # primary opinions or promoting unavailable administrative slots.
        summary_states = [{**s, **({"response": s["response"]["path"]} if s.get("response") else {})} for s in ordered]
        summary = original._summary(plan, stage, summary_states, _stopped(root, plan), primary_unknown)
        summary["global_stop"] = identity(root / "global-stop.json") if _stopped(root, plan) else None
        summary["original_generation_costs_modified"] = False
        _write(directory / "jobs.json", ordered)
        _write(directory / "summary.json", summary)
        seal = {"schema": SEAL_SCHEMA, "stage": stage, "plan": identity(root / "run-plan.json"),
                "protocol": plan["protocol"], "launch": deepcopy(launch_receipt), "implementation": plan["implementation"],
                "inventory": _inventory(directory), "summary": identity(directory / "summary.json"),
                "global_stop": summary["global_stop"], "primary_scores_modified": False}
        _write(directory / "seal.json", seal)
        return identity(directory / "seal.json")
