"""Bounded, fresh blind evaluation of two authentic same-run F8 views.

This is an exploration diagnostic, not a new generation or a C0 ablation.
All opinions are fresh. Error-root classification remains a separately bounded
prospective task; matching text evidence does not prove semantic correctness.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from experiments.translation_eval import runner as e
from experiments.translation_judge import runner as j
from experiments.translation_judge.integrity import inside, _resolved_path
from . import v2_evaluation as v
from . import v2_review_diagnostics as views
from . import v2_universal_review as u

VERSION = "f8-same-run-review-diagnostic-scope-v1"
ROLE = "exploration_only_same_run_review_diagnostic"
ALIASES = {"before": "c01", "after": "c02"}
SEEDS = (20261008, 20261009, 20261010)
FORBIDDEN = {"universal_review_scope", "judgment_import", "matched_judgment_import",
             "matched_control_scope", "fresh_confirmation_scope", "derivation"}


def _intake(source_manifest: Path, source_inputs: Path, references: Path, reference_freeze: Path,
            before: Path, after: Path, window_ids: list[str]) -> tuple[dict, dict, dict, dict]:
    contract, requests, refs = v.source_contract(source_manifest, source_inputs, references,
                                               reference_freeze, window_ids)
    projected, metadata = {}, {}
    for phase, directory in (("before", before), ("after", after)):
        document = e.read_json(directory / "delivery.json")
        canonical = views.validate_review_view(document, directory)
        if (document["review_diagnostic"]["phase"] != phase
                or v.checked_pointer(document["source_manifest"], directory) != source_manifest.resolve()
                or e.indexed(e.load_jsonl(directory / "inputs.jsonl")) != requests):
            raise ValueError("F8 diagnostic views must cover the exact frozen source/window scope")
        projected[phase], metadata[phase] = canonical, document
    first, second = metadata["before"], metadata["after"]
    for name in ("run", "seed", "recipe_id", "candidate", "packed_mapping", "source_manifest"):
        if first[name] != second[name]:
            raise ValueError("F8 before/after must belong to the same original run and seed")
    if (first["review_diagnostic"]["original_delivery"] != second["review_diagnostic"]["original_delivery"]
            or first["review_diagnostic"]["original_cost_identity"] != second["review_diagnostic"]["original_cost_identity"]
            or type(first["seed"]) is not int):
        raise ValueError("F8 diagnostic original delivery/cost/seed identity differs")
    return contract, requests, refs, {"projected": projected, "metadata": metadata}


def freeze_scope(source_manifest: Path, source_inputs: Path, references: Path, reference_freeze: Path,
                 before: Path, after: Path, output: Path, *, window_ids: list[str]) -> dict[str, str]:
    """Freeze only after qualified authentic views exist; never generate/unseal."""
    if output.exists():
        raise FileExistsError("F8 diagnostic scope must be a new immutable file")
    contract, _, _, intake = _intake(source_manifest, source_inputs, references, reference_freeze,
                                    before, after, window_ids)
    original = intake["metadata"]["before"]
    value = {"version": VERSION, "state": "frozen_before_diagnostic_judgments", "role": ROLE,
             "selection": "all_expected_windows", "window_ids": window_ids,
             "seed": original["seed"], "aliases": ALIASES, "profile": e.PROFILE,
             "model": j.MODEL, "effort": j.EFFORT, "prompt": e.PROMPT,
             "post_judgment_reuse": False, "new_generation_calls": 0, "new_generated_samples": 0,
             "standalone_flow_timing": False, "primary_comparison_changed": False,
             "source_manifest": u.identity(source_manifest), "source_inputs": u.identity(source_inputs),
             "references": u.identity(references), "reference_freeze": u.identity(reference_freeze),
             "source_qualification_freeze": contract["source_qualification_freeze"],
             "views": {phase: u.identity(directory / "delivery.json") for phase, directory in
                       (("before", before), ("after", after))},
             "original_delivery": original["review_diagnostic"]["original_delivery"],
             "original_generation_cost_identity": original["review_diagnostic"]["original_cost_identity"],
             "count_original_generation_cost_once": True,
             "budgets": {"primary_logical_jobs_max": 2 * len(window_ids),
                         "review_logical_jobs_max": 2 * len(window_ids),
                         "adjudication_logical_jobs_max": 2 * len(window_ids), "attempts_per_job_max": 2,
                         "root_evidence_logical_jobs_max": 2 * len(window_ids)},
             "root_evidence_state": "pending_separately_authorized_fresh_blind_evidence",
             "implementation": [u.identity(Path(module.__file__)) for module in (views, v, e, j, u)] + [u.identity(Path(__file__))]}
    if (j.MODEL, j.EFFORT) != ("gpt-6.1-sol", "high"):
        raise ValueError("F8 diagnostic requires the fixed Sol/high automated profile")
    e.dump(output, value)
    return u.identity(output)


def scope_metadata(pointer: dict[str, str], *, registered_scope_sha256: str) -> tuple[dict, dict]:
    """Validate an externally pinned diagnostic scope and all frozen dependencies."""
    if pointer.get("sha256") != registered_scope_sha256:
        raise ValueError("F8 diagnostic scope differs from the external registered hash")
    path = u._pointer(pointer, Path.cwd())
    value = e.read_json(path)
    ids = value.get("window_ids", [])
    if (value.get("version") != VERSION or value.get("state") != "frozen_before_diagnostic_judgments"
            or value.get("role") != ROLE or value.get("selection") != "all_expected_windows"
            or value.get("aliases") != ALIASES or not isinstance(ids, list) or not ids
            or len(ids) != len(set(ids)) or any(not isinstance(wid, str) for wid in ids)
            or value.get("profile") != e.PROFILE or value.get("prompt") != e.PROMPT
            or (value.get("model"), value.get("effort")) != (j.MODEL, j.EFFORT)
            or (j.MODEL, j.EFFORT) != ("gpt-6.1-sol", "high")
            or value.get("post_judgment_reuse") is not False or type(value.get("seed")) is not int
            or value.get("new_generation_calls") != 0 or value.get("new_generated_samples") != 0
            or value.get("standalone_flow_timing") is not False
            or value.get("primary_comparison_changed") is not False
            or value.get("count_original_generation_cost_once") is not True
            or value.get("budgets") != {"primary_logical_jobs_max": 2 * len(ids),
                "review_logical_jobs_max": 2 * len(ids), "adjudication_logical_jobs_max": 2 * len(ids),
                "attempts_per_job_max": 2, "root_evidence_logical_jobs_max": 2 * len(ids)}):
        raise ValueError("F8 diagnostic frozen policy/denominator/profile is invalid")
    for wid in ids:
        e.safe_id(wid)
    u._pointers(value, path.parent)
    return u.identity(path), value


def freeze_frame(scopes: list[dict[str, str]], output: Path) -> dict[str, str]:
    """Bind all three seeds before opinions; no per-seed selection is permitted."""
    if output.exists():
        raise FileExistsError("F8 diagnostic frame must be a new immutable file")
    values = [scope_metadata(pointer, registered_scope_sha256=pointer["sha256"])[1] for pointer in scopes]
    if len(values) != len(SEEDS) or [value["seed"] for value in values] != list(SEEDS):
        raise ValueError("F8 diagnostic requires the ordered complete three-seed frame")
    for value in values:
        if any(value[name] != values[0][name] for name in (
                "window_ids", "source_manifest", "source_inputs", "references", "reference_freeze", "source_qualification_freeze")):
            raise ValueError("F8 diagnostic seeds must share exact source/reference/window scope")
    if len({value["original_generation_cost_identity"]["path"] for value in values}) != 3:
        raise ValueError("F8 diagnostic seeds require distinct original F8 runs")
    e.dump(output, {"version": "f8-same-run-review-diagnostic-frame-v1", "role": ROLE,
        "state": "frozen_before_diagnostic_judgments", "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "seeds": list(SEEDS), "scopes": scopes, "window_ids": values[0]["window_ids"],
        "expected_pairs": 3 * len(values[0]["window_ids"]), "expected_records": 6 * len(values[0]["window_ids"]),
        "original_generation_cost_count": 3, "new_generated_samples": 0})
    return u.identity(output)


def frame_metadata(pointer: dict[str, str], *, registered_frame_sha256: str) -> tuple[dict, dict]:
    if pointer.get("sha256") != registered_frame_sha256:
        raise ValueError("F8 diagnostic frame differs from its external registered hash")
    path = u._pointer(pointer, Path.cwd())
    frame = e.read_json(path)
    if (frame.get("version") != "f8-same-run-review-diagnostic-frame-v1" or frame.get("role") != ROLE
            or frame.get("state") != "frozen_before_diagnostic_judgments" or frame.get("seeds") != list(SEEDS)
            or len(frame.get("scopes", [])) != 3):
        raise ValueError("F8 diagnostic complete frame is invalid")
    values = [scope_metadata(item, registered_scope_sha256=item["sha256"])[1] for item in frame["scopes"]]
    if ([value["seed"] for value in values] != list(SEEDS)
            or any(value["window_ids"] != frame["window_ids"] for value in values)
            or frame.get("expected_pairs") != 3 * len(frame["window_ids"])
            or frame.get("expected_records") != 6 * len(frame["window_ids"])
            or frame.get("original_generation_cost_count") != 3 or frame.get("new_generated_samples") != 0):
        raise ValueError("F8 diagnostic frame denominator changed")
    for value in values:
        if any(value[name] != values[0][name] for name in (
                "source_manifest", "source_inputs", "references", "reference_freeze", "source_qualification_freeze")):
            raise ValueError("F8 diagnostic frame source/reference scope changed")
    if len({value["original_generation_cost_identity"]["path"] for value in values}) != 3:
        raise ValueError("F8 diagnostic original generation identity is reused across seeds")
    if datetime.fromisoformat(frame["frozen_at_utc"]).tzinfo is None:
        raise ValueError("F8 diagnostic frame requires an aware freeze timestamp")
    return u.identity(path), frame


def prepare(frame_pointer: dict[str, str], output: Path, *, seed: int, registered_frame_sha256: str) -> dict[str, Any]:
    """Prepare both authentic views for fresh opinions; no donor/import path."""
    if output.exists():
        raise FileExistsError("F8 diagnostic evaluation must use a new root")
    frame_pointer, frame = frame_metadata(frame_pointer, registered_frame_sha256=registered_frame_sha256)
    if type(seed) is not int or seed not in SEEDS:
        raise ValueError("F8 diagnostic seed is outside the complete frozen frame")
    scope_pointer = frame["scopes"][SEEDS.index(seed)]
    scope, value = scope_metadata(scope_pointer, registered_scope_sha256=scope_pointer["sha256"])
    paths = {name: Path(value[name]["path"]) for name in
             ("source_manifest", "source_inputs", "references", "reference_freeze")}
    directories = {phase: Path(value["views"][phase]["path"]).parent for phase in ALIASES}
    contract, requests, refs, intake = _intake(**paths, before=directories["before"], after=directories["after"],
                                             window_ids=value["window_ids"])
    original = intake["metadata"]["before"]
    if (original["seed"] != value["seed"]
            or original["review_diagnostic"]["original_delivery"] != value["original_delivery"]
            or original["review_diagnostic"]["original_cost_identity"] != value["original_generation_cost_identity"]):
        raise ValueError("Frozen F8 original generation identity changed")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f8-diagnostic-", dir=output.parent) as temporary:
        stage = Path(temporary)
        e.dump_jsonl(stage / "inputs.jsonl", list(requests.values()))
        e.dump_jsonl(stage / "references.jsonl", list(refs.values()))
        candidates, ledgers, schedules = {}, {}, {}
        for phase, alias in ALIASES.items():
            for name, collection in (("results", candidates), ("ledger", ledgers), ("schedule", schedules)):
                path = stage / alias / (name + ".jsonl")
                e.dump_jsonl(path, [{key: val for key, val in row.items() if key != "delivery_contract"}
                                   for row in intake["projected"][phase][name]])
                collection[alias] = path
        e.prepare(stage / "inputs.jsonl", stage / "references.jsonl", candidates, output, split="dev",
                  candidate_ledgers=ledgers, candidate_schedules=schedules, corpus_manifest=paths["source_manifest"])
    run, expected = e.read_json(output / "run.json"), e.load_jsonl(output / "expected.jsonl")
    for phase, alias in ALIASES.items():
        directory = directories[phase]
        meta = run["candidates"][alias]
        for name in ("results", "ledger", "schedule"):
            path = directory / (name + ".jsonl")
            shutil.copyfile(path, output / "originals" / alias / path.name)
            meta[name] = str(path.resolve())
            meta["sha256" if name == "results" else name + "_sha256"] = e.sha(path)
        meta.update(delivery_contract=e.P_FLOW_CONTRACT, review_diagnostic=intake["metadata"][phase]["review_diagnostic"],
                    seed=value["seed"], recipe_id=original["recipe_id"], new_generated_samples=0,
                    original_generation_cost_identity=value["original_generation_cost_identity"],
                    cost_attribution="same_original_f8_run_once_across_both_views")
    for row in expected:
        wid = row["window_id"]
        row.update(lane="P-flow", delivery_contract=e.P_FLOW_CONTRACT, scene_id=contract["window_mapping"][wid]["scene_id"],
                   source_mapping=contract["window_mapping"][wid], judge_source_scope=v.SCOPE)
        packet = e.read_json(output / row["packet"])
        packet.update({key: row[key] for key in ("lane", "delivery_contract", "scene_id", "source_mapping", "judge_source_scope")})
        e.dump(output / row["packet"], packet)
    contract["candidate_artifacts"] = {alias: {"view": value["views"][phase],
        "original_delivery": value["original_delivery"], "review_diagnostic": deepcopy(intake["metadata"][phase]["review_diagnostic"])}
        for phase, alias in ALIASES.items()}
    e.dump_jsonl(output / "expected.jsonl", expected)
    e.dump(output / "p-flow-scene-contract.json", contract)
    e.dump_jsonl(output / "inputs.jsonl", list(requests.values()))
    e.dump_jsonl(output / "references.jsonl", list(refs.values()))
    shutil.copyfile(Path(scope["path"]), output / "review-diagnostic-scope.json")
    shutil.copyfile(Path(frame_pointer["path"]), output / "review-diagnostic-frame.json")
    selection = {"scope": scope, "selection": "all_expected_windows", "selected_ids": value["window_ids"],
                 "expected_records": len(expected), "expected_sha256": e.sha(output / "expected.jsonl")}
    e.dump(output / "review-diagnostic-selection.json", selection)
    run.update(lane="P-flow", delivery_contract=e.P_FLOW_CONTRACT, judge_source_scope=v.SCOPE,
               review_diagnostic_scope=scope, review_diagnostic_frame=frame_pointer, p_flow_contract=contract,
               expected_sha256=e.sha(output / "expected.jsonl"),
               packet_sha256={row["packet"]: e.sha(output / row["packet"]) for row in expected},
               inputs=str(paths["source_inputs"]), inputs_sha256=e.sha(paths["source_inputs"]),
               references=str(paths["references"]), references_sha256=e.sha(paths["references"]),
               original_generation_cost_identity=value["original_generation_cost_identity"],
               original_generation_cost_count=1, new_generation_calls=0, new_generated_samples=0,
               comparison_role=ROLE, diagnostic_generation_seed=value["seed"], post_judgment_reuse=False,
               frozen_artifact_sha256={name: e.sha(output / name) for name in (
                   "p-flow-scene-contract.json", "inputs.jsonl", "references.jsonl", "review-diagnostic-scope.json",
                   "review-diagnostic-selection.json", "review-diagnostic-frame.json")})
    e.dump(output / "run.json", run)
    validate_prepared(output, registered_frame_sha256=registered_frame_sha256)
    return {"windows": len(requests), "expected_records": len(expected), "primary_jobs": len(e.load_jsonl(output / "jobs.jsonl")),
            "scope": scope, "comparison_role": ROLE, "new_generation_calls": 0}


def validate_prepared(root: Path, *, registered_frame_sha256: str) -> dict[str, Any]:
    root = _resolved_path(root)
    run = e.read_json(root / "run.json")
    if (FORBIDDEN & run.keys() or any((root / name).exists() for name in
            ("universal-judgment-import.json", "matched-judgment-import.json"))
            or run.get("comparison_role") != ROLE or run.get("post_judgment_reuse") is not False):
        raise ValueError("F8 diagnostic forbids judgment imports and independent generation relabeling")
    _, frame = frame_metadata(run["review_diagnostic_frame"], registered_frame_sha256=registered_frame_sha256)
    seed = run.get("diagnostic_generation_seed")
    if seed not in SEEDS or run["review_diagnostic_scope"] != frame["scopes"][SEEDS.index(seed)]:
        raise ValueError("F8 diagnostic root is outside the frozen three-seed frame")
    scope, value = scope_metadata(run["review_diagnostic_scope"], registered_scope_sha256=run["review_diagnostic_scope"]["sha256"])
    u._prepared(root, run)
    if (root / "judge-prompt.txt").read_bytes() != (e.PROMPT + "\n").replace("\n", os.linesep).encode("utf-8"):
        raise ValueError("F8 diagnostic judge prompt differs from the frozen blind rubric")
    paths = {name: Path(value[name]["path"]) for name in ("source_manifest", "source_inputs", "references", "reference_freeze")}
    contract, requests, refs, intake = _intake(**paths,
        before=Path(value["views"]["before"]["path"]).parent, after=Path(value["views"]["after"]["path"]).parent,
        window_ids=value["window_ids"])
    for name in ("schema", "scope", "source_manifest", "source_inputs", "references", "reference_freeze",
                 "source_qualification_freeze", "window_ids", "allowed_source_scope", "window_mapping"):
        if run["p_flow_contract"].get(name) != contract.get(name):
            raise ValueError("F8 diagnostic prepared source/reference contract changed")
    for name, source_name in (("inputs", "source_inputs"), ("references", "references"), ("corpus_manifest", "source_manifest")):
        if u._pointer({"path": run[name], "sha256": run[name + "_sha256"]}, root) != paths[source_name]:
            raise ValueError("F8 diagnostic prepared source/reference pointer changed")
    expected = e.load_jsonl(root / "expected.jsonl")
    if ({(row["candidate_alias"], row["window_id"]) for row in expected}
            != {(alias, wid) for alias in ALIASES.values() for wid in value["window_ids"]}
            or len(expected) != 2 * len(value["window_ids"])
            or run.get("original_generation_cost_identity") != value["original_generation_cost_identity"]
            or run.get("diagnostic_generation_seed") != value["seed"]
            or run.get("original_generation_cost_count") != 1
            or run.get("new_generation_calls") != 0 or run.get("new_generated_samples") != 0):
        raise ValueError("F8 diagnostic pair denominator/seed/original cost identity changed")
    for phase, alias in ALIASES.items():
        directory = Path(value["views"][phase]["path"]).parent
        document = e.read_json(directory / "delivery.json")
        views.validate_review_view(document, directory)
        if run["candidates"][alias].get("review_diagnostic") != document["review_diagnostic"]:
            raise ValueError("F8 diagnostic phase provenance changed")
        predictions = e.indexed(intake["projected"][phase]["results"])
        terminals = e.indexed(intake["projected"][phase]["ledger"], "window_id")
        schedules = e.indexed(intake["projected"][phase]["schedule"], "window_id")
        for row in (item for item in expected if item["candidate_alias"] == alias):
            wid = row["window_id"]
            packet = e.read_json(inside(root, root / row["packet"]))
            units = e.indexed(refs[wid]["units"])
            ids = requests[wid]["translate_ids"]
            translations = predictions.get(wid, {}).get("translations", {})
            missing = [uid for uid in ids if not isinstance(translations.get(uid), str) or not translations[uid].strip()]
            terminal = terminals.get(wid, {})
            issues = (["missing_window"] if wid not in predictions else []) + (["missing_or_empty_ids"] if missing else [])
            if terminal.get("status") == "translation_failed":
                issues.append("translation_failed")
            status = schedules.get(wid, {}).get("status") or ("mapping_unjudgeable" if terminal.get("status") == "mapping_unjudgeable"
                else "delivery_zero" if len(missing) == len(ids) or terminal.get("status") == "translation_failed"
                else "partial_delivery" if missing else "valid")
            structural = {"status": status, "missing_ids": [] if wid in schedules else missing, "extra_ids": [],
                          "issues": [status] if wid in schedules else issues,
                          "mapping_reason": terminal.get("reason") if terminal.get("status") == "mapping_unjudgeable" else None}
            canonical = {"window_id": wid, "candidate_alias": alias, "context": requests[wid]["context"],
                         "scored_ids": ids, "reference": {uid: units[uid]["zh"] for uid in ids},
                         "translations": {uid: translations.get(uid) if isinstance(translations.get(uid), str)
                                          and translations[uid].strip() else None for uid in ids},
                         "lane": "P-flow", "delivery_contract": e.P_FLOW_CONTRACT,
                         "source_mapping": contract["window_mapping"][wid], "judge_source_scope": v.SCOPE,
                         "scene_id": contract["window_mapping"][wid]["scene_id"], "structural": structural}
            if packet != canonical:
                raise ValueError("F8 diagnostic packet differs from authentic source/reference/view bytes")
            if (row.get("scored_ids") != ids or row.get("source_mapping") != canonical["source_mapping"]
                    or row.get("structural_status") != status or row.get("structural_issues") != structural["issues"]):
                raise ValueError("F8 diagnostic expected source cue identities changed")
    for filename, phase in (("jobs.jsonl", "primary"), ("jobs-review.jsonl", "review"), ("jobs-adjudication.jsonl", "adjudication")):
        path = root / filename
        if path.is_file():
            descriptors = e.load_jsonl(path)
            rows = {(row["candidate_alias"], row["window_id"]): row for row in expected
                    if row["structural_status"] not in e.NO_JUDGE_STATUSES}
            if (len({item["job_id"] for item in descriptors}) != len(descriptors)
                    or (phase != "adjudication" and {(item["candidate_alias"], item["window_id"]) for item in descriptors} != set(rows))):
                raise ValueError("F8 diagnostic job inventory differs from its fixed expected phase")
            for descriptor in descriptors:
                key = descriptor["candidate_alias"], descriptor["window_id"]
                if key not in rows:
                    raise ValueError("F8 diagnostic job is outside its expected scope")
                canonical_job = e.job(rows[key], phase)
                if phase == "adjudication":
                    canonical_job["dispute"] = f"disputes/{key[0]}/{key[1]}.json"
                if descriptor != canonical_job:
                    raise ValueError("F8 diagnostic job descriptor differs from canonical native input")
            if len(descriptors) > value["budgets"][phase + "_logical_jobs_max"]:
                raise ValueError("F8 diagnostic phase exceeded its frozen budget")
            for descriptor in descriptors:
                ledger = root / "judge-execution" / descriptor["job_id"] / "job.json"
                if ledger.is_file():
                    state = e.read_json(ledger)
                    if len(state.get("attempts", [])) > 2 or any(datetime.fromisoformat(attempt["started_at"]) <
                            datetime.fromisoformat(frame["frozen_at_utc"]) for attempt in state.get("attempts", [])):
                        raise ValueError("F8 diagnostic forbids historical opinions or excess attempts")
                    if state.get("status") == "succeeded":
                        u._accepted(root, descriptor)
    return {"scope": scope, "frame": run["review_diagnostic_frame"], "window_ids": value["window_ids"],
            "seed": value["seed"], "expected_records": len(expected)}


def review_coverage(root: Path) -> dict[str, Any]:
    expected = e.load_jsonl(root / "expected.jsonl")
    finals = e.load_jsonl(root / "final.jsonl")
    judgeable = [row for row in expected if row["structural_status"] not in e.NO_JUDGE_STATUSES]
    accepted = 0
    for descriptor in e.load_jsonl(root / "jobs-review.jsonl"):
        ledger = root / "judge-execution" / descriptor["job_id"] / "job.json"
        if ledger.is_file() and e.read_json(ledger).get("status") == "succeeded":
            u._accepted(root, descriptor)
            accepted += 1
    known = [row for row in finals if row["status"] != "delivery_zero"
             and (row.get("semantic") is not None or row.get("naturalness") is not None)]
    reviewed = sum(row.get("reviewed") is True for row in known)
    selected = e.read_json(root / "review-selection.json")["selected_ids"]
    count = sum(row["window_id"] in selected for row in expected)
    return {"expected_records": len(expected), "judgeable_records": len(judgeable), "selected_records": count,
            "accepted_review_records": accepted, "known_scored_reviewed_records": reviewed,
            "complete": count == len(expected) and accepted == len(judgeable) and reviewed == len(known)}


def finalize(root: Path, *, registered_frame_sha256: str) -> dict[str, Any]:
    meta = validate_prepared(root, registered_frame_sha256=registered_frame_sha256)
    for descriptor in e.load_jsonl(root / "jobs.jsonl"):
        ledger = root / "judge-execution" / descriptor["job_id"] / "job.json"
        if not ledger.is_file() or e.read_json(ledger).get("status") not in {"succeeded", "judge_failed"}:
            raise ValueError("F8 diagnostic finalize requires terminal primary accounting before freezing review selection")
    e.finalize(root, review_selection_override=meta["window_ids"])
    coverage = review_coverage(root)
    e.dump(root / "review-diagnostic-coverage.json", coverage)
    return coverage


def classification_contract(root: Path, *, registered_frame_sha256: str) -> dict[str, Any]:
    """Expose the finite future source-evidence task; do not manufacture labels."""
    meta = validate_prepared(root, registered_frame_sha256=registered_frame_sha256)
    return {"version": "f8-paired-root-evidence-contract-v1", "scope": meta["scope"], "frame": meta["frame"],
            "state": "pending_separately_authorized_fresh_blind_evidence", "window_ids": meta["window_ids"],
            "seed": meta["seed"], "required_phases": ["fresh_blind_root_evidence", "independent_root_evidence_review"],
            "logical_jobs_max": 2 * len(meta["window_ids"]), "attempts_per_job_max": 2,
            "adjudication": "unresolved_on_disagreement_no_extra_adjudication_in_this_contract",
            "categories": ["corrected", "harmed", "missed", "unchanged_or_equivalent", "unresolved"],
            "severities": ["minor", "major", "critical"], "all_accepted_error_roots_required": True,
            "matching_basis": "source-supported proposition/cause; root ID spelling and score changes are not evidence",
            "root_record_required_fields": ["window_id", "root_id", "ids", "category", "source_evidence",
                "source_proposition_zh", "cause_zh", "before_evidence", "after_evidence", "before_error", "after_error", "reason_zh"],
            "error_record": {"type": ["mistranslation", "omission", "addition", "terminology", "fluency", "mapping"],
                             "severity": ["minor", "major", "critical"]},
            "score_delta_is_evidence": False, "root_matching_semantically_confirmed": False,
            "blindness": "anonymous phase order; no F8/C0 identity, prior opinions or internal review traces",
            "missing_bounds": {"fixed_pairs": len(meta["window_ids"]), "known_classified_pairs": 0,
                               "unknown_pairs": len(meta["window_ids"]),
                               "bound_unit": "window_pair_corrected_presence_minus_harmed_presence",
                               "error_root_count_bounds": None,
                               "net_corrected_minus_harmed_lower": -len(meta["window_ids"]),
                               "net_corrected_minus_harmed_upper": len(meta["window_ids"])}}


def validate_evidence_claims(root: Path, claims: list[dict[str, Any]], *, registered_frame_sha256: str) -> dict[str, Any]:
    """Check literal evidence membership only; independent semantic work is pending."""
    meta = validate_prepared(root, registered_frame_sha256=registered_frame_sha256)
    seen = set()
    for claim in claims:
        wid, rid = claim.get("window_id"), claim.get("root_id")
        if wid not in meta["window_ids"] or not isinstance(rid, str) or not rid or (wid, rid) in seen:
            raise ValueError("Root evidence requires a distinct frozen window/root identity")
        seen.add((wid, rid))
        if claim.get("category") not in {"corrected", "harmed", "missed", "unchanged_or_equivalent", "unresolved"}:
            raise ValueError("Unknown F8 root-evidence category")
        for name in ("source_proposition_zh", "cause_zh"):
            if not isinstance(claim.get(name), str) or not claim[name].strip():
                raise ValueError("Root matching requires the source proposition and error cause, not a root label or score")
        for name in ("before_error", "after_error"):
            if name not in claim:
                raise ValueError("Both phases must declare the error presence or absence")
            error = claim[name]
            if error is not None and (not isinstance(error, dict) or set(error) != {"type", "severity"}
                    or error["type"] not in {"mistranslation", "omission", "addition", "terminology", "fluency", "mapping"}
                    or error["severity"] not in {"minor", "major", "critical"}):
                raise ValueError("Root evidence error type/severity is invalid")
        category = claim["category"]
        before_error, after_error = claim["before_error"], claim["after_error"]
        if ((category == "corrected" and (before_error is None or after_error is not None))
                or (category == "harmed" and after_error is None)
                or (category == "missed" and (before_error is None or after_error is None))
                or (category == "unchanged_or_equivalent" and (before_error is not None or after_error is not None))):
            raise ValueError("Proposed category contradicts its explicit phase error presence")
        packets = {phase: e.read_json(root / "packets" / alias / (wid + ".json")) for phase, alias in ALIASES.items()}
        ids = claim.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or not set(ids) <= set(packets["before"]["scored_ids"]):
            raise ValueError("Root evidence must use distinct scored source IDs")
        for phase, field in (("before", "before_evidence"), ("after", "after_evidence")):
            excerpt = claim.get(field)
            text = "\n".join(packets[phase]["translations"].get(uid) or "" for uid in ids)
            phase_error = claim[phase + "_error"]
            omission_claim = isinstance(phase_error, dict) and phase_error.get("type") == "omission"
            if not isinstance(excerpt, str) or (excerpt and excerpt not in text) or (not excerpt and text and not omission_claim):
                raise ValueError("Candidate root evidence must be literal supplied text, or an actual omission")
        excerpt = claim.get("source_evidence")
        text = "\n".join(cue["text"] for cue in packets["before"]["context"] if cue["id"] in ids)
        if not isinstance(excerpt, str) or not excerpt or excerpt not in text or not isinstance(claim.get("reason_zh"), str) or not claim["reason_zh"].strip():
            raise ValueError("Root evidence requires literal Japanese source and an explanation")
    return {"state": "mechanically_valid_unverified_evidence", "claims": len(claims),
            "semantic_classification_confirmed": False, "score_derived_labels": False,
            "fixed_pairs": len(meta["window_ids"]), "confirmed_pairs": 0, "unknown_pairs": len(meta["window_ids"])}
