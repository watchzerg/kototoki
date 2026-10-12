"""Frozen universal review and offline import of sealed accepted judgments.

Only the three declared functional ledger paths are relocated. Historical
commands, attempts, raw responses, canonical bytes and fingerprints stay intact.
The donor is verified twice and is never repaired or finalized by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import shutil
from typing import Any

from experiments.translation_eval import runner as e
from experiments.translation_judge import runner as j
from experiments.translation_judge.integrity import inside, _resolved_path

VERSION = "evaluation-scope-universal-v1"
IMPORT_VERSION = "universal-judgment-import-v1"
SEAL_VERSION = "hy30-flow-v2-evaluation-finalization-v1"
RELOCATED_FIELDS = ("response", "accepted_raw_response", "accepted_canonical_snapshot")
PHASES = ("primary", "review", "adjudication")


def identity(path: Path) -> dict[str, str]:
    return {"path": str(_resolved_path(path)), "sha256": e.sha(path)}


def _pointer(value: dict[str, Any], root: Path) -> Path:
    path = Path(value["path"])
    path = _resolved_path(path if path.is_absolute() else root / path)
    if not path.is_file() or e.sha(path) != value.get("sha256"):
        raise ValueError("frozen provenance pointer changed")
    return path


def _pointers(value: Any, root: Path) -> None:
    """Hash pointers without reading reference or candidate semantic content."""
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and "sha256" in value:
            _pointer(value, root)
        for item in value.values():
            _pointers(item, root)
    elif isinstance(value, list):
        for item in value:
            _pointers(item, root)


def scope_metadata(pointer: Path | dict[str, Any]) -> dict[str, Any]:
    """Validate the shared decision/source/reference scope and return its identity."""
    path = _pointer(pointer, Path.cwd()) if isinstance(pointer, dict) else _resolved_path(pointer)
    value = e.read_json(path)
    if (value.get("version") != VERSION
            or value.get("state") != "frozen_before_candidate_quality"
            or value.get("selection") != "all_expected_windows"
            or value.get("candidate_quality_judgments_started") is not False
            or set(value.get("no_judge_statuses", [])) != e.NO_JUDGE_STATUSES):
        raise ValueError("universal review scope lacks the required prior frozen policy")
    for name in ("decision_policy", "source_manifest", "source_freeze", "reference_freeze"):
        _pointer(value[name], path.parent)
    source = e.read_json(_pointer(value["source_freeze"], path.parent))
    approved = source.get("reference_qualification", {})
    actual = value["reference_freeze"]
    if (source.get("state") != "source_frozen_reference_qualified"
            or _pointer(approved, path.parent) != _pointer(actual, path.parent)
            or approved.get("sha256") != actual["sha256"]
            or approved.get("version") != "hy30-flow-v2-reference-v1"
            or approved.get("state") != "frozen_double_fresh_reference_review"
            or approved.get("inference_allowed") is not True):
        raise ValueError("universal scope reference differs from accepted source qualification")
    _pointers(value, path.parent)
    result = {**identity(path), **{name: value[name] for name in ("version", "state", "selection")}}
    if isinstance(pointer, dict) and any(pointer.get(name) != result[name]
                                       for name in ("version", "state", "selection") if name in pointer):
        raise ValueError("universal scope metadata differs from frozen bytes")
    return result


def _bound_scope(run: dict[str, Any], scope: dict[str, Any], root: Path) -> None:
    value = e.read_json(Path(scope["path"]))
    contract = run.get("p_flow_contract", {})
    for name, scope_name in (("source_manifest", "source_manifest"),
                             ("source_qualification_freeze", "source_freeze"),
                             ("reference_freeze", "reference_freeze")):
        if name in contract and (_pointer(contract[name], root) != _pointer(value[scope_name], Path(scope["path"]).parent)
                                 or contract[name]["sha256"] != value[scope_name]["sha256"]):
            raise ValueError("prepared source/reference identity differs from universal scope")
    if run.get("corpus_manifest") and (_resolved_path(Path(run["corpus_manifest"])) !=
                                      _pointer(value["source_manifest"], Path(scope["path"]).parent)
                                      or run.get("corpus_manifest_sha256") != value["source_manifest"]["sha256"]):
        raise ValueError("prepared corpus identity differs from universal scope")


def _prepared(root: Path, run: dict[str, Any]) -> dict[str, str]:
    frozen = {"expected.jsonl": run["expected_sha256"], "judge-prompt.txt": run["prompt_sha256"],
              **run["packet_sha256"], **run.get("frozen_artifact_sha256", {})}
    for name, digest in frozen.items():
        path = inside(root, root / name)
        if e.sha(path) != digest:
            raise ValueError("frozen prepared artifact changed")
    for name in ("inputs", "references", "corpus_manifest"):
        if run.get(name):
            _pointer({"path": run[name], "sha256": run[name + "_sha256"]}, root)
    for candidate in run.get("candidates", {}).values():
        for name in ("results", "ledger", "schedule"):
            if candidate.get(name):
                digest = candidate["sha256" if name == "results" else name + "_sha256"]
                _pointer({"path": candidate[name], "sha256": digest}, root)
                if candidate.get("preserved_" + name):
                    path = inside(root, root / candidate["preserved_" + name])
                    if e.sha(path) != digest:
                        raise ValueError("preserved candidate provenance changed")
                    frozen[candidate["preserved_" + name]] = digest
    _pointers(run.get("p_flow_contract", {}), root)
    return frozen


def _selection(root: Path, scope: dict[str, Any], run: dict[str, Any]) -> None:
    expected = e.load_jsonl(root / "expected.jsonl")
    selection = {"version": VERSION, "selection": "all_expected_windows", "scope": scope,
                 "expected_sha256": run["expected_sha256"],
                 "selected_ids": sorted({row["window_id"] for row in expected}),
                 "expected_records": len(expected),
                 "judgeable_records": sum(row["structural_status"] not in e.NO_JUDGE_STATUSES for row in expected)}
    e.dump(root / "universal-review-selection.json", selection)
    jobs = [e.job(row, "review") for row in expected if row["structural_status"] not in e.NO_JUDGE_STATUSES]
    e.dump_jsonl(root / "jobs-review.jsonl", sorted(jobs, key=lambda item: e.order_key(item["job_id"], "review-jobs-20261006")))


def _apply(root: Path, scope: dict[str, Any], run: dict[str, Any]) -> None:
    _bound_scope(run, scope, root)
    _selection(root, scope, run)
    shutil.copyfile(Path(scope["path"]), root / "universal-review-scope.json")
    shutil.copyfile(Path(__file__), root / "universal-review-adapter.py")
    run["universal_review_scope"] = scope
    frozen = run.setdefault("frozen_artifact_sha256", {})
    for name in ("universal-review-selection.json", "universal-review-scope.json", "universal-review-adapter.py"):
        frozen[name] = e.sha(root / name)
    e.dump(root / "run.json", run)


def apply_universal_scope(root: Path, scope_path: Path | dict[str, Any]) -> dict[str, Any]:
    """Freeze universal review before a freshly prepared candidate's first primary."""
    root = _resolved_path(root)
    if ((root / "finalization-manifest.json").exists() or (root / "judge-execution").exists()
            or any((root / phase).exists() for phase in PHASES)
            or (root / "primary.jsonl").exists() or (root / "review-selection.json").exists()):
        raise ValueError("universal scope must be applied before any primary judgment started")
    run = e.read_json(root / "run.json")
    _prepared(root, run)
    scope = scope_metadata(scope_path)
    if "universal_review_scope" in run:
        if run["universal_review_scope"] != scope:
            raise ValueError("universal scope is already frozen to a different identity")
        return scope
    _apply(root, scope, run)
    return scope


def _inventory(root: Path, seal: dict[str, Any]) -> dict[str, str]:
    if (seal.get("version") != SEAL_VERSION or seal.get("state") != "required_fresh_judgments_completed"
            or seal.get("accepted_raw_canonical_integrity_verified") is not True):
        raise ValueError("donor lacks a completed accepted-judgment seal")
    declared = {}
    for row in seal["files"]:
        name = row["path"]
        path = inside(root, root / name)
        if Path(name).is_absolute() or path.relative_to(root).as_posix() != name or name in declared:
            raise ValueError("donor inventory has escaping, noncanonical or duplicate paths")
        declared[name] = row["sha256"]
        if not path.is_file() or e.sha(path) != row["sha256"]:
            raise ValueError("sealed donor inventory changed")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
              and path.relative_to(root).as_posix() not in {"finalization-manifest.json", ".judge-scheduler.lock"}}
    if actual != set(declared):
        raise ValueError("sealed donor inventory has missing or extra artifacts")
    for name, filename in (("run", "run.json"), ("expected", "expected.jsonl"), ("final", "final.jsonl")):
        if _pointer(seal[name], root) != root / filename or seal[name]["sha256"] != declared[filename]:
            raise ValueError("donor seal identity differs from its inventory")
    return declared


def _offline(*args: Any) -> dict[str, Any]:
    raise ValueError("judgment import must not dispatch any inference")


def _accepted(root: Path, descriptor: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    ledger = inside(root, root / "judge-execution" / descriptor["job_id"] / "job.json")
    state = e.read_json(ledger)
    if state.get("status") != "succeeded" or state.get("job_id") != descriptor["job_id"]:
        raise ValueError("donor required judgment is not accepted")
    canonical = inside(root, Path(state["response"]))
    if canonical != inside(root, root / descriptor["response"]):
        raise ValueError("accepted canonical identity differs from declared job")
    raw = inside(ledger.parent, Path(state["accepted_raw_response"]))
    snapshot = inside(ledger.parent, Path(state["accepted_canonical_snapshot"]))
    # Requiring all members prevents run_job from repairing an immutable donor.
    if (e.sha(raw) != state["accepted_raw_response_sha256"]
            or e.sha(canonical) != state["response_sha256"]
            or e.sha(snapshot) != state["response_sha256"]
            or canonical.read_bytes() != snapshot.read_bytes()):
        raise ValueError("accepted raw/canonical/snapshot identity changed")
    observed = ledger.read_bytes()
    result = j.run_job(root, descriptor, "unused", "offline-import", 1, _offline)
    if not result.get("resumed") or result.get("canonical_restored") or ledger.read_bytes() != observed:
        raise ValueError("offline judgment validation changed donor evidence")
    return ledger, state


def _donor_jobs(root: Path, expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = {(row["candidate_alias"], row["window_id"]): row for row in expected}
    if len(rows) != len(expected):
        raise ValueError("duplicate expected judgment identity")
    declared = {}
    for filename, phase in (("jobs.jsonl", "primary"), ("jobs-review.jsonl", "review"),
                            ("jobs-adjudication.jsonl", "adjudication")):
        for descriptor in e.load_jsonl(root / filename):
            key = descriptor["candidate_alias"], descriptor["window_id"]
            if key not in rows or rows[key]["structural_status"] in e.NO_JUDGE_STATUSES:
                raise ValueError("donor judgment job differs from expected judgeable scope")
            canonical = e.job(rows[key], phase)
            if phase == "adjudication":
                canonical["dispute"] = f"disputes/{key[0]}/{key[1]}.json"
            if descriptor != canonical or descriptor["job_id"] in declared:
                raise ValueError("donor judgment descriptor differs from canonical identity")
            declared[descriptor["job_id"]] = descriptor
    # Verify every accepted ledger, including any extra historical accepted call.
    for ledger in (root / "judge-execution").rglob("job.json"):
        state = e.read_json(ledger)
        if state.get("status") != "succeeded":
            continue
        job_id = ledger.parent.relative_to(root / "judge-execution").as_posix()
        pieces = job_id.split("/")
        if len(pieces) != 3 or pieces[0] not in PHASES or tuple(pieces[1:]) not in rows:
            raise ValueError("accepted donor job is outside expected phase/window scope")
        if job_id not in declared:
            row = rows[tuple(pieces[1:])]
            if row["structural_status"] in e.NO_JUDGE_STATUSES:
                raise ValueError("accepted donor job is unjudgeable")
            descriptor = e.job(row, pieces[0])
            if pieces[0] == "adjudication":
                descriptor["dispute"] = f"disputes/{pieces[1]}/{pieces[2]}.json"
            declared[job_id] = descriptor
    primary_ids = {item["job_id"] for item in declared.values() if item["job_id"].startswith("primary/")}
    if primary_ids != {e.job(row, "primary")["job_id"] for row in expected if row["structural_status"] not in e.NO_JUDGE_STATUSES}:
        raise ValueError("sealed donor lacks the complete expected primary scope")
    return [declared[key] for key in sorted(declared)]


def prepare_derivative(donor_root: Path, output: Path, scope_path: Path | dict[str, Any]) -> dict[str, Any]:
    """Import only verified accepted calls; freeze universal review in a new root."""
    donor_root, output = _resolved_path(donor_root), _resolved_path(output)
    if output == donor_root or output.is_relative_to(donor_root) or donor_root.is_relative_to(output):
        raise ValueError("derivative and donor roots must be disjoint")
    if output.exists() and any(output.iterdir()):
        raise ValueError("derivative output must be empty")
    scope = scope_metadata(scope_path)
    seal_path = donor_root / "finalization-manifest.json"
    seal_pointer = identity(seal_path)
    seal = e.read_json(seal_path)
    inventory = _inventory(donor_root, seal)
    run = e.read_json(donor_root / "run.json")
    if "universal_review_scope" in run or "judgment_import" in run:
        raise ValueError("donor must be an original sealed selective-review root")
    frozen = _prepared(donor_root, run)
    _bound_scope(run, scope, donor_root)
    expected = e.load_jsonl(donor_root / "expected.jsonl")
    final = e.load_jsonl(donor_root / "final.jsonl")
    if ({(v["candidate_alias"], v["window_id"]) for v in final} !=
            {(v["candidate_alias"], v["window_id"]) for v in expected} or len(final) != len(expected)):
        raise ValueError("sealed donor final denominator differs from expected")
    descriptors = _donor_jobs(donor_root, expected)
    accepted = [(descriptor, *_accepted(donor_root, descriptor)) for descriptor in descriptors]
    _inventory(donor_root, seal)
    if identity(seal_path) != seal_pointer:
        raise ValueError("donor seal changed during import verification")
    output.mkdir(parents=True, exist_ok=True)
    names = set(frozen) | {"jobs.jsonl", "aggregation-runner.py"}
    for name in sorted(names):
        source, target = inside(donor_root, donor_root / name), inside(output, output / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    proof = {"version": IMPORT_VERSION, "donor_root": str(donor_root), "target_root": str(output),
             "donor_run": identity(donor_root / "run.json"), "donor_finalization": seal_pointer,
             "universal_review_scope": scope, "donor_inventory_sha256": e.sha(seal_path),
             "frozen_prepared_files": [{"path": name, "sha256": e.sha(output / name)} for name in sorted(names)],
             "ledger_path_relocation_allowlist": list(RELOCATED_FIELDS),
             "imported_jobs": [], "imported_phase_counts": {}, "new_network_calls": 0,
             "new_generated_samples": 0, "new_inference_calls": 0,
             "cost_attribution": "original_accepted_judgment_once"}
    disputes = {}
    for descriptor, ledger, state in accepted:
        relative = ledger.parent.relative_to(donor_root)
        target_directory = output / relative
        shutil.copytree(ledger.parent, target_directory)
        canonical = inside(donor_root, Path(state["response"]))
        target_response = output / canonical.relative_to(donor_root)
        target_response.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(canonical, target_response)
        original_copy = output / "judgment-import-donor" / "ledgers" / descriptor["job_id"] / "job.json"
        original_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ledger, original_copy)
        relocated = deepcopy(state)
        for name in RELOCATED_FIELDS:
            source = inside(donor_root if name == "response" else ledger.parent, Path(state[name]))
            relocated[name] = str(output / source.relative_to(donor_root))
        new_ledger = target_directory / "job.json"
        e.dump(new_ledger, relocated)
        if "dispute" in descriptor:
            name = descriptor["dispute"]
            target = inside(output, output / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(inside(donor_root, donor_root / name), target)
            disputes[name] = e.sha(target)
        _accepted(output, descriptor)
        proof["imported_jobs"].append({"phase": descriptor["job_id"].split("/")[0],
            "job_id": descriptor["job_id"], "candidate_alias": descriptor["candidate_alias"],
            "window_id": descriptor["window_id"], "fingerprint": state["fingerprint"],
            "donor_ledger": identity(ledger), "original_ledger_copy": identity(original_copy),
            "new_ledger": identity(new_ledger),
            "accepted_raw_response_sha256": state["accepted_raw_response_sha256"],
            "response_sha256": state["response_sha256"],
            "accepted_canonical_snapshot_sha256": state["response_sha256"],
            "dispute": identity(output / descriptor["dispute"]) if "dispute" in descriptor else None,
            "files": [{"path": p.relative_to(output).as_posix(), "sha256": e.sha(p)}
                      for p in sorted(target_directory.rglob("*")) if p.is_file()]})
    counts = Counter(row["phase"] for row in proof["imported_jobs"])
    proof["imported_phase_counts"] = {phase: counts[phase] for phase in PHASES}
    for filename in ("run.json", "finalization-manifest.json"):
        target = output / "judgment-import-donor" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(donor_root / filename, target)
    proof_path = output / "universal-judgment-import.json"
    e.dump(proof_path, proof)
    run["judgment_import"] = {"donor_root": str(donor_root), "donor_run": proof["donor_run"],
                              "donor_finalization": proof["donor_finalization"], "manifest": identity(proof_path)}
    for path in (proof_path, output / "judgment-import-donor/run.json", output / "judgment-import-donor/finalization-manifest.json"):
        run.setdefault("frozen_artifact_sha256", {})[path.relative_to(output).as_posix()] = e.sha(path)
    for row in proof["imported_jobs"]:
        copied = Path(row["original_ledger_copy"]["path"])
        run["frozen_artifact_sha256"][copied.relative_to(output).as_posix()] = e.sha(copied)
    _apply(output, scope, run)
    # Native selection/disputes are regenerated from the same accepted bytes.
    e.finalize(output)
    for name, digest in disputes.items():
        if e.sha(output / name) != digest:
            raise ValueError("imported adjudication dispute changed; accepted call cannot be reused")
    for descriptor, _, _ in accepted:
        _accepted(output, descriptor)
    _inventory(donor_root, seal)
    if identity(seal_path) != seal_pointer:
        raise ValueError("donor seal changed during derivative publication")
    return proof


def finalize(root: Path, selection_only: bool = False) -> None:
    """Use the native aggregator's automatic frozen universal selection."""
    e.finalize(root, selection_only)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    derive = sub.add_parser("prepare-derivative")
    derive.add_argument("--donor", type=Path, required=True)
    derive.add_argument("--output", type=Path, required=True)
    derive.add_argument("--scope", type=Path, required=True)
    apply = sub.add_parser("apply-scope")
    apply.add_argument("--output", type=Path, required=True)
    apply.add_argument("--scope", type=Path, required=True)
    finish = sub.add_parser("finalize")
    finish.add_argument("--output", type=Path, required=True)
    finish.add_argument("--selection-only", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare-derivative":
        prepare_derivative(args.donor, args.output, args.scope)
    elif args.command == "apply-scope":
        apply_universal_scope(args.output, args.scope)
    else:
        finalize(args.output, args.selection_only)


if __name__ == "__main__":
    main()
