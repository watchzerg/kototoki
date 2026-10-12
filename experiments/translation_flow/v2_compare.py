"""Offline, provenance-bound flow-v2 comparison; exports aggregates only.

Read evaluation roots, never translation outputs, judge packets or reference
contents. Reference bytes are hashed for identity only. Final error evidence stays
inside this evaluation process for conservative root deduplication; no raw row is
exported. Screening is exploratory and this entry point never selects a winner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from experiments.translation_eval.runner import CATEGORY_MAP, NO_JUDGE_STATUSES, dump, load_jsonl, read_json, sha
from experiments.translation_judge.integrity import inside
from .v2_statistics import ESTIMATOR, SEEDS, build_statistics

POLICY_SHA256 = "409553d1a5e2cbfb2e329d415a2b0e862b6a248550b5be5812dffcc4f3c85a9e"
RECIPE_CODE = "experiments/translation_flow/v2_recipes.py"
UNIVERSAL_REVIEW = "evaluation-scope-universal-v1"
UNIVERSAL_REVIEW_SHA256 = "b747c4d22462d5756e8fff258213a8ba79771fe2f500c56135dc955643d7e209"
MATCHED_SCOPE_SHA256 = "6b72e98045a99689b58770338fe9639d75877ab270fce97600eb3687e4244ca0"
MATCHED_SCOPE = "matched-control-evaluation-scope-v1"


def _auxiliary_plan(pointer: dict[str, Any], root: Path, seed: int) -> dict[str, Any]:
    """Authenticate the full source-only plan without opening source dialogue."""
    path = _pointer(pointer, root)
    plan = read_json(path)
    version3 = plan.get("schema") == "hy30-source-preparation-session-v3"
    fields = {"schema", "mode", "stage", "source", "scene_ids", "settings", "budgets"}
    if version3:
        fields.add("protocol")
    settings, budgets, source = plan.get("settings", {}), plan.get("budgets", {}), plan.get("source", {})
    if (set(plan) != fields or plan.get("schema") not in {"hy30-source-preparation-session-v2", "hy30-source-preparation-session-v3"}
        or plan.get("mode") not in {"terms", "background"}
        or plan.get("stage") not in {"qualification", "screening", "confirmation", "full-flow"}
        or set(settings) != {"sampling", "cache_prompt", "n_predict", "seed", "max_attempts", "max_items"}
        or settings.get("seed") != seed or type(settings.get("seed")) is not int
        or settings.get("sampling") != "official" or settings.get("cache_prompt") is not True
        or type(settings.get("max_attempts")) is not int or settings["max_attempts"] not in (1, 2)
        or any(type(settings.get(key)) is not int or settings[key] <= 0 for key in ("n_predict", "max_items"))
        or set(budgets) != {"max_translation_calls", "max_judge_calls", "max_estimated_tokens", "max_wall_seconds"}
        or type(budgets.get("max_judge_calls")) is not int or budgets["max_judge_calls"] != 0
        or any(type(budgets.get(key)) is not int or budgets[key] <= 0 for key in ("max_translation_calls", "max_estimated_tokens"))
        or type(budgets.get("max_wall_seconds")) not in (int, float)
        or not math.isfinite(budgets["max_wall_seconds"]) or budgets["max_wall_seconds"] <= 0
        or set(source) != {"manifest", "manifest_sha256", "scenes", "scenes_sha256", "freeze_sha256"}
        or not isinstance(plan.get("scene_ids"), list) or not plan["scene_ids"]
        or any(not isinstance(sid, str) or not sid for sid in plan["scene_ids"])
        or len(set(plan["scene_ids"])) != len(plan["scene_ids"])):
        raise ValueError("auxiliary recipe requires its complete frozen plan/settings/budgets/seed")
    if version3:
        from .v2_source_preparation import _validate_protocol
        _validate_protocol(plan)
    paths = {name: _pointer({"path": source[name], "sha256": source[name + "_sha256"]}, path.parent)
             for name in ("manifest", "scenes")}
    freeze = _pointer({"path": str(paths["manifest"].parent / "freeze-manifest.json"),
                       "sha256": source["freeze_sha256"]}, path.parent)
    # Relocation is allowed only after every pointed byte identity is verified.
    configuration = {**plan, "settings": {key: value for key, value in settings.items() if key != "seed"},
                     "source": {key: source[key] for key in ("manifest_sha256", "scenes_sha256", "freeze_sha256")}}
    return {"plan": {"path": str(path), "sha256": pointer["sha256"]}, "configuration": configuration,
            "source": {**{key: {"path": str(value), "sha256": source[key + "_sha256"]} for key, value in paths.items()},
                       "freeze": {"path": str(freeze), "sha256": source["freeze_sha256"]}},
            "stage": plan["stage"], "seed": seed}


def _auxiliary_generation(settings: dict[str, Any], original: dict[str, Any], original_path: Path,
                          source_pointer: dict[str, Any], attempt_pointer: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Keep per-seed consumed artifacts and once-per-trial auxiliary cost proof."""
    from .v2_timing import read_metadata_fields
    from .v2_confirmation_evaluation import validate_source_preparation_metadata
    consumed = settings.get("source_preparation")
    if consumed is None:
        if original.get("source_preparation") is not None:
            raise ValueError("unexpected auxiliary generation identity")
        return None
    if not isinstance(consumed, dict) or set(consumed) != {"artifact", "batch_options"}:
        raise ValueError("auxiliary generation requires artifact and batch-options identities")
    if original.get("source_preparation") != consumed:
        raise ValueError("native auxiliary settings and consumed identity differ")
    artifact_path = _pointer(consumed["artifact"], original_path.parent)
    sidecar_path = _pointer(consumed["batch_options"], original_path.parent)
    fields = {"schema", "mode", "stage", "source", "scene_ids", "settings", "protocol", "session_plan_sha256",
              "session_plan_path", "cost_artifacts", "code_sha256"}
    artifact = read_metadata_fields(artifact_path, fields)
    plan_pointer = {"path": artifact.get("session_plan_path", str(artifact_path.parent / "session-plan.json")),
                    "sha256": artifact.get("session_plan_sha256")}
    plan = _auxiliary_plan(plan_pointer, artifact_path.parent, settings["seed"])
    if plan["source"]["manifest"]["sha256"] != source_pointer["sha256"]:
        raise ValueError("auxiliary plan source differs from evaluation source")
    freeze = read_json(Path(plan["source"]["freeze"]["path"]))
    main_plan_path = _pointer({"path": str(original_path.parent.parent / "session-plan.json"),
                              "sha256": original.get("session_plan_sha256")}, original_path.parent)
    main_plan = read_metadata_fields(main_plan_path, {"experiment_identity", "stage"})
    generation_split = main_plan.get("experiment_identity", {}).get("split")
    source = {**plan["source"], "role": freeze.get("role"),
              "split": generation_split}
    proof = validate_source_preparation_metadata(plan["plan"],
        {"path": str(artifact_path), "sha256": consumed["artifact"]["sha256"]}, source,
        seed=settings["seed"], stage=plan["stage"])
    sidecar = read_metadata_fields(sidecar_path, {"schema", "source_preparation", "packed_mapping_sha256",
        "source_manifest_sha256", "source_scenes_sha256", "scene_ids", "seed", "mode", "protocol", "projection"})
    if (sidecar.get("schema") not in {"hy30-flow-batch-options-v2", "hy30-flow-batch-options-v3"}
        or _pointer(sidecar.get("source_preparation"), sidecar_path.parent) != artifact_path
        or sidecar["source_preparation"]["sha256"] != consumed["artifact"]["sha256"]
        or sidecar.get("packed_mapping_sha256") != settings.get("packed_mapping_sha256")
        or any(sidecar.get(key) != artifact.get(key) for key in ("scene_ids", "mode", "protocol"))
        or sidecar.get("seed") != settings["seed"]
        or sidecar.get("source_manifest_sha256") != plan["source"]["manifest"]["sha256"]
        or sidecar.get("source_scenes_sha256") != plan["source"]["scenes"]["sha256"]):
        raise ValueError("native auxiliary batch-options differ from plan/artifact/source/packing")
    projection = sidecar.get("projection")
    if artifact["schema"].endswith("-v3"):
        from .v2_source_projection import validate_projection_mode
        validate_projection_mode(artifact["mode"], artifact["protocol"], projection)
        if sidecar["schema"] != "hy30-flow-batch-options-v3":
            raise ValueError("v3 auxiliary generation requires versioned batch-options")
    elif projection is not None:
        raise ValueError("legacy auxiliary generation cannot use a v3 projection")
    costs = artifact.get("cost_artifacts")
    if not isinstance(costs, dict) or set(costs) != {"ledger.jsonl"}:
        raise ValueError("auxiliary generation lacks its original scene cost ledger")
    ledger = {"path": str(artifact_path.parent / "ledger.jsonl"), "sha256": costs["ledger.jsonl"]}
    _pointer(ledger, artifact_path.parent)
    worker_path = artifact_path.parent / "worker-completion.json"
    worker = read_metadata_fields(worker_path, {"complete", "artifact", "protocol", "worker_wall_seconds"})
    if (worker.get("complete") is not True or _pointer(worker.get("artifact"), worker_path.parent) != artifact_path
        or worker["artifact"]["sha256"] != consumed["artifact"]["sha256"] or worker.get("protocol") != artifact.get("protocol")):
        raise ValueError("auxiliary worker completion differs from consumed artifact")
    command_path = artifact_path.parents[2] / "command-completion.json"
    if attempt_pointer is None:
        raise ValueError("auxiliary command cost requires frozen original trial completion identity")
    attempt_path = _pointer(attempt_pointer, original_path.parent)
    attempt = read_metadata_fields(attempt_path, {"source_preparation"}).get("source_preparation", {})
    if (attempt.get("runtime_exit_code") != 0 or attempt.get("plan_sha256") != plan["plan"]["sha256"]
        or _pointer(attempt.get("artifact"), attempt_path.parent) != artifact_path
        or attempt["artifact"]["sha256"] != consumed["artifact"]["sha256"]
        or _pointer(attempt.get("cost", {}).get("command"), attempt_path.parent) != command_path
        or _pointer(attempt.get("cost", {}).get("ledger"), attempt_path.parent) != Path(ledger["path"])
        or attempt["cost"]["ledger"]["sha256"] != ledger["sha256"]):
        raise ValueError("original trial auxiliary plan/artifact/command cost identity differs")
    command = read_metadata_fields(command_path, {"schema", "worker", "plan_sha256", "returncode", "command_seconds"})
    if (command.get("schema") != "hy30-flow-command-v2" or command.get("worker") != "experiments.translation_flow.v2_source_preparation"
        or command.get("returncode") != 0 or command.get("plan_sha256") != plan["plan"]["sha256"]
        or type(command.get("command_seconds")) not in (int, float)
        or not math.isfinite(command["command_seconds"]) or command["command_seconds"] < 0):
        raise ValueError("auxiliary generation lacks original native command cost proof")
    proof.update(configuration={**plan["configuration"], "projection": projection, "generation_split": generation_split},
        generation_split=generation_split,
        batch_options={"path": str(sidecar_path), "sha256": consumed["batch_options"]["sha256"]},
        ledger=ledger, worker_completion={"path": str(worker_path), "sha256": sha(worker_path)},
        command={"path": str(command_path), "sha256": sha(command_path)}, command_seconds=command["command_seconds"],
        original_trial_attempt_identity={"path": str(attempt_path), "sha256": attempt_pointer["sha256"]},
        code_sha256=artifact.get("code_sha256", {}), source_snapshot_root=artifact_path.parent / "source",
        cost_attribution="native_auxiliary_command_once_per_trial")
    return proof


def _auxiliary_provenance(proof: dict[str, Any]) -> dict[str, Any]:
    """Export identities and native cost once, without any preparation contents."""
    return {key: proof[key] for key in ("locked_plan", "artifact", "batch_options", "ledger", "command",
        "worker_completion", "original_trial_attempt_identity", "command_seconds", "seed", "stage", "generation_split", "mode", "protocol", "scene_ids", "source",
        "metadata_only", "preparation_semantics_validated", "formal_timing_eligible", "cost_attribution")}


def _auxiliary_card_binding(auxiliary: dict[str, Any] | None, card: dict[str, Any]) -> None:
    if (auxiliary is None) != (card.get("source_preparation") is None):
        raise ValueError("missing or unexpected auxiliary generation against frozen card")
    if auxiliary is None:
        return
    if auxiliary["configuration"] != card["source_preparation"]:
        raise ValueError("complete auxiliary plan/projection differs from frozen card")
    for relative, digest in card["implementation_identity"].items():
        saved = inside(auxiliary["source_snapshot_root"], auxiliary["source_snapshot_root"] / relative)
        if auxiliary["code_sha256"].get(relative) != digest or sha(saved) != digest:
            raise ValueError("declared auxiliary implementation differs from original snapshot")


def _fresh_auxiliary_binding(auxiliary: dict[str, Any] | None, card_pointer: dict[str, Any], root: Path,
                             source_manifest: Path, policy: Path, windows: dict[str, Any]) -> None:
    """Apply the same auxiliary guards to already-authorized fresh native slots."""
    path = _pointer(card_pointer, root)
    raw_card = read_json(path)
    if auxiliary is None:
        if raw_card.get("source_preparation") is not None:
            raise ValueError("missing or unexpected auxiliary generation against frozen card")
    else:
        _auxiliary_card_binding(auxiliary, _card(path, source_manifest, policy, windows))


def _series_sensitivity(stats: dict[str, Any]) -> None:
    """Describe sensitivity to removing a whole correlated series cluster."""
    for scope in stats["splits"].values():
        for stratum in scope["strata"].values():
            for category in stratum["categories"].values():
                for pair in category["pairs"]:
                    values = {work: row["mean"] for work, row in pair["hierarchy"]["works"].items() if row["mean"] is not None}
                    sensitivity = {}
                    for cluster, members in pair["series_cluster_interval"]["members"].items():
                        retained = [value for work, value in values.items() if work not in members]
                        sensitivity[cluster] = {"removed_works": members, "remaining_paired_works": len(retained),
                            "semantic_difference": sum(retained)/len(retained) if retained else None}
                    pair["leave_one_series_cluster_out"] = sensitivity


def _review_coverage(final: dict[tuple[str, str], dict[str, Any]],
                     expected: set[tuple[str, str]]) -> dict[str, int]:
    """Require a blind review before using any judged non-null final score.

    Wholly unusable delivery has a mechanical zero and no text to review. Missing
    or failed reviews retain null final semantic; coverage never fabricates a zero.
    Freshness and imported-review provenance are checked by the scope seal.
    """
    for row in final.values():
        known = row.get("semantic") is not None or row.get("naturalness") is not None
        if known and row.get("status") != "delivery_zero" and row.get("reviewed") is not True:
            raise ValueError("universal review scope cannot use a known judged score without independent review")
    return {"expected_records": len(expected), "final_records": len(final),
            "independently_reviewed_records": sum(row.get("reviewed") is True for row in final.values()),
            "mechanical_delivery_zero_records": sum(row.get("status") == "delivery_zero" for row in final.values()),
            "semantic_unknown_or_missing_records": len(expected)-sum(row.get("semantic") is not None for row in final.values())}


def _relative_code(path: str) -> str:
    normalized = path.replace("\\", "/")
    if "/experiments/" in normalized:
        return "experiments/" + normalized.split("/experiments/", 1)[1]
    if normalized.startswith("experiments/") and ".." not in normalized.split("/"):
        return normalized
    raise ValueError("declared used implementation must identify a project experiment module")


def _pointer(pointer: dict[str, Any], root: Path, *, check_bytes: bool = True) -> Path:
    if not isinstance(pointer, dict) or not isinstance(pointer.get("path"), str):
        raise ValueError("provenance pointer requires path/SHA256")
    path = Path(pointer["path"])
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    digest = pointer.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("provenance pointer lacks SHA256")
    if check_bytes and sha(path) != digest:
        raise ValueError("provenance artifact bytes changed")
    return path


def _root(path: Path) -> Path:
    return (path.parent if path.name == "final.jsonl" else path).resolve()


def _seal_inventory(seal: dict[str, Any], root: Path, *, exact: bool) -> None:
    declared = set()
    for pointer in seal.get("files", []):
        relative = pointer.get("path")
        if (not isinstance(relative, str) or Path(relative).is_absolute()
            or Path(relative).as_posix() != relative or ".." in relative.split("/")
            or relative in declared):
            raise ValueError("finalization inventory path is duplicate or noncanonical")
        declared.add(relative)
        path = inside(root, root / relative)
        if sha(path) != pointer.get("sha256"):
            raise ValueError("finalization inventory artifact bytes changed")
    if exact:
        present = set()
        canonical_root = inside(root, root)
        for path in root.rglob("*"):
            if path.is_symlink() or (getattr(path, "is_junction", lambda: False)()):
                raise ValueError("universal finalization inventory rejects symlinks or junctions")
            if path.is_file():
                present.add(inside(root, path).relative_to(canonical_root).as_posix())
        present -= {"finalization-manifest.json", ".judge-scheduler.lock"}
        if declared != present:
            raise ValueError("universal finalization inventory differs from exact root files")


def _universal_scope(run: dict[str, Any], root: Path, source: dict[str, Any],
                     freeze: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    pointer = run.get("universal_review_scope")
    if not isinstance(pointer, dict):
        raise ValueError("comparison requires universal blind-review scope; selective review roots are ineligible")
    scope = read_json(_pointer(pointer, root))
    for field, value in (("version", UNIVERSAL_REVIEW), ("state", "frozen_before_candidate_quality"),
                         ("selection", "all_expected_windows")):
        if pointer.get(field) != value or scope.get(field) != value:
            raise ValueError("universal blind-review scope declaration mismatch")
    for name, identity in (("source_manifest", source), ("reference_freeze", freeze)):
        _pointer(scope.get(name), root)
        if scope[name]["sha256"] != identity["sha256"]:
            raise ValueError("universal review scope source/reference identity mismatch")
    _pointer(scope.get("decision_policy"), root)
    if (scope.get("generation_seeds") != list(SEEDS)
        or scope.get("candidate_windows") != "all_card_selected_expected_windows"
        or type(scope.get("baseline_windows_per_seed")) is not int
        or scope["baseline_windows_per_seed"] <= 0
        or scope.get("primary_policy") != "reuse_verified_accepted_without_repeat"
        or scope.get("review_policy") != "fresh_only_missing_blind_reviews"
        or scope.get("adjudication_policy") != "unchanged_bounded_dispute_resolution"
        or scope.get("no_judge_statuses") != sorted(NO_JUDGE_STATUSES)
        or scope.get("blind_review_prior_opinions_visible") is not False
        or scope.get("unknown_policy") != "retain_null_and_full_expected_denominator"):
        raise ValueError("universal review scope policy differs from frozen evaluation contract")
    return pointer, scope


def _matched_scope(run: dict[str, Any], root: Path, contract: dict[str, Any],
                   universal: dict[str, Any]) -> dict[str, Any] | None:
    pointer = run.get("matched_control_scope")
    if pointer is None:
        if run.get("matched_judgment_import") is not None:
            raise ValueError("matched judgment import requires explicit matched control scope")
        return None
    path = _pointer(pointer, root)
    scope = read_json(path)
    for field, value in (("version", MATCHED_SCOPE), ("state", "frozen_before_candidate_quality_inspection"),
                         ("selection", "explicit_matched_windows")):
        if pointer.get(field) != value or scope.get(field) != value:
            raise ValueError("matched control scope declaration mismatch")
    ids = scope.get("window_ids")
    if (not isinstance(ids, list) or len(ids) != len(set(ids)) or not ids
        or scope.get("expected_windows_per_seed") != len(ids)
        or contract.get("window_ids") != ids
        or scope.get("generation_seeds") != list(SEEDS)
        or scope.get("candidate_group") != "C0-official-cached"
        or scope.get("universal_review_selection") != "all_expected_judgeable48_windows_each_seed"
        or scope.get("generation_attribution") != "new_matched29_generation_identity_and_cost_preserved"
        or scope.get("decision_thresholds_modified") is not False
        or scope.get("primary_policy_modified") is not False
        or scope.get("old96_roots_modified") is not False
        or scope.get("mixed96_single_generation_ledger_permitted") is not False
        or scope.get("timing_declaration", {}).get("candidate_quality_results_inspected") is not False):
        raise ValueError("matched control scope must retain explicit independent workload and unchanged policy")
    for name in ("source_manifest", "reference_freeze"):
        _pointer(scope.get(name), path.parent)
        if scope[name]["sha256"] != contract[name]["sha256"]:
            raise ValueError("matched control source/reference identity mismatch")
    for name in ("decision_policy", "source_freeze", "validation_protocol", "matched_execution_queue", "universal_review_policy"):
        _pointer(scope.get(name), path.parent)
    if contract.get("source_qualification_freeze", {}).get("sha256") != scope["source_freeze"]["sha256"]:
        raise ValueError("matched target lacks the explicitly bound qualified source")
    if scope["universal_review_policy"]["sha256"] != universal["sha256"]:
        raise ValueError("matched48 scope has no explicit relation to the original universal review policy")
    protocol = read_json(_pointer(scope["validation_protocol"], path.parent))
    if (protocol.get("version") != "matched-workload-validation-v1"
        or protocol.get("state") != "frozen_before_any_candidate_quality_inspection"
        or protocol.get("window_ids") != ids or protocol.get("generation_seeds") != list(SEEDS)
        or protocol.get("timing_declaration", {}).get("candidate_quality_results_inspected") is not False
        or protocol.get("unchanged_thresholds") is not True):
        raise ValueError("matched validation preregistration differs from explicit scope")
    for name in ("source_manifest", "source_freeze", "decision_policy"):
        if protocol.get(name, {}).get("sha256") != scope[name]["sha256"]:
            raise ValueError("matched validation changes source or decision policy")
    queue = read_json(_pointer(scope["matched_execution_queue"], path.parent))
    if queue.get("validation_protocol", {}).get("sha256") != scope["validation_protocol"]["sha256"]:
        raise ValueError("matched execution queue changes validation protocol")
    cards = {}
    for job in queue.get("jobs", []):
        card_pointer = {"path": job.get("card"), "sha256": job.get("card_sha256")}
        card_path = _pointer(card_pointer, path.parent)
        card = read_json(card_path)
        seed = card.get("prepare", {}).get("seed")
        if seed not in SEEDS or seed in cards or card.get("candidate_group") != scope["candidate_group"]:
            raise ValueError("matched queue requires exact control cards for all generation seeds")
        cards[seed] = card_path
    if set(cards) != set(SEEDS):
        raise ValueError("matched queue requires exact control cards for all generation seeds")
    return {"pointer": pointer, "scope": scope, "protocol": protocol, "cards": cards}


def _import_lineage(run: dict[str, Any], root: Path, contract: dict[str, Any],
                    seal: dict[str, Any] | None, wanted: set[tuple[str, str]]) -> dict[str, Any] | None:
    imported = run.get("judgment_import")
    if imported is None:
        if seal is not None and seal.get("judgment_import") is not None:
            raise ValueError("finalization seal has undeclared judgment import")
        return None
    if not isinstance(imported, dict) or (seal is not None and seal.get("judgment_import") != imported):
        raise ValueError("finalization seal judgment import differs from run")
    donor_path = Path(imported["donor_root"])
    donor = _root(donor_path if donor_path.is_absolute() else root / donor_path)
    donor_run_path = _pointer(imported.get("donor_run"), root)
    donor_seal_path = _pointer(imported.get("donor_finalization"), root)
    if (inside(donor, donor_run_path) != inside(donor, donor / "run.json")
        or inside(donor, donor_seal_path) != inside(donor, donor / "finalization-manifest.json")):
        raise ValueError("judgment donor identity is outside declared donor root")
    donor_run, donor_seal = read_json(donor_run_path), read_json(donor_seal_path)
    if donor_seal.get("state") != "required_fresh_judgments_completed":
        raise ValueError("judgment donor must have a completed immutable seal")
    for name in ("run", "expected", "final"):
        bound = _pointer(donor_seal.get(name), donor)
        if inside(donor, bound) != inside(donor, donor / (name + (".json" if name == "run" else ".jsonl"))):
            raise ValueError("judgment donor seal binds another artifact")
    donor_contract = donor_run.get("p_flow_contract", {})
    for name in ("source_manifest", "references", "reference_freeze"):
        if donor_contract.get(name, {}).get("sha256") != contract.get(name, {}).get("sha256"):
            raise ValueError("judgment import changes source/reference identity")
    for name in ("source_manifest", "reference_freeze"):
        _pointer(donor_seal.get(name), donor)
        if donor_seal[name]["sha256"] != contract[name]["sha256"]:
            raise ValueError("judgment donor seal source/reference identity mismatch")
    _seal_inventory(donor_seal, donor, exact=False)
    donor_rows = load_jsonl(donor / "expected.jsonl")
    donor_expected = {(row.get("candidate_alias"), row.get("window_id")) for row in donor_rows}
    if (donor_expected != wanted or len(donor_rows) != len(wanted)
        or donor_run.get("expected_sha256") != sha(donor / "expected.jsonl")):
        raise ValueError("judgment import changes exact expected scope")
    donor_artifacts = donor_contract.get("candidate_artifacts", {})
    artifacts = contract["candidate_artifacts"]
    if set(donor_artifacts) != set(artifacts):
        raise ValueError("judgment import changes opaque candidate identities")
    for alias, artifact in artifacts.items():
        for field in ("seed", "recipe_id", "original_generation_cost_identity"):
            if donor_artifacts[alias].get(field) != artifact.get(field):
                raise ValueError("judgment import changes original generation identity")
        if donor_seal.get("candidate_identity", {}).get(alias) != {
                field: artifact.get(field) for field in ("seed", "recipe_id", "original_generation_cost_identity")}:
            raise ValueError("judgment donor seal generation identity mismatch")
    # Import manifests are metadata-only inventories. Never open imported raw
    # primary/review jobs or donor final contents to reconstruct their semantics.
    manifest_path = _pointer(imported.get("manifest"), root)
    manifest = read_json(manifest_path)
    if (manifest.get("version") != "universal-judgment-import-v1"
        or _root(Path(manifest.get("donor_root", ""))) != donor
        or _root(Path(manifest.get("target_root", ""))) != root
        or manifest.get("donor_run") != imported.get("donor_run")
        or manifest.get("donor_finalization") != imported.get("donor_finalization")
        or manifest.get("universal_review_scope") != run.get("universal_review_scope")
        or manifest.get("donor_inventory_sha256") != imported["donor_finalization"]["sha256"]
        or any(type(manifest.get(field)) is not int or manifest[field] != 0
               for field in ("new_network_calls", "new_generated_samples", "new_inference_calls"))
        or manifest.get("cost_attribution") != "original_accepted_judgment_once"):
        raise ValueError("judgment import manifest identity or cost attribution mismatch")
    counts = {"primary": 0, "review": 0, "adjudication": 0}
    seen_jobs = set()
    for job in manifest.get("imported_jobs", []):
        phase = job.get("phase")
        key = phase, job.get("job_id")
        if (phase not in counts or not isinstance(key[1], str) or key in seen_jobs
            or (job.get("candidate_alias"), job.get("window_id")) not in wanted):
            raise ValueError("judgment import job identity or scope mismatch")
        seen_jobs.add(key)
        counts[phase] += 1
        for name, directory in (("donor_ledger", donor), ("original_ledger_copy", root), ("new_ledger", root)):
            inside(directory, _pointer(job.get(name), directory))
        for name in ("accepted_raw_response_sha256", "response_sha256", "accepted_canonical_snapshot_sha256"):
            digest = job.get(name)
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("judgment import lacks accepted-response hash identity")
        for pointer in job.get("files", []):
            inside(root, _pointer(pointer, root))
    if manifest.get("imported_phase_counts") != counts:
        raise ValueError("judgment import phase count mismatch")
    for pointer in manifest.get("frozen_prepared_files", []):
        inside(root, _pointer(pointer, root))
    return {"donor_root": str(donor), "donor_run_sha256": sha(donor_run_path),
            "donor_finalization_sha256": sha(donor_seal_path), "manifest_sha256": sha(manifest_path),
            "imported_phase_counts": counts, "new_network_calls": 0, "new_generated_samples": 0,
            "new_inference_calls": 0, "cost_attribution": "original_accepted_judgment_once"}


def _matched_qualification_bindings(proof: dict[str, Any], run: dict[str, Any], root: Path,
                                   donor_run: dict[str, Any], donor: Path,
                                   protocol: dict[str, Any]) -> None:
    """Verify qualified-source metadata without inventing a legacy donor binding."""
    bindings = proof.get("source_qualification_bindings", {})
    if set(bindings) != {"target", "donor"}:
        raise ValueError("matched qualified source requires target and donor binding proofs")
    canonical = _pointer(protocol.get("source_freeze"), root)
    freeze = read_json(canonical)
    approved = freeze.get("reference_qualification", {})
    for role, prepared, directory in (("target", run, root), ("donor", donor_run, donor)):
        binding = bindings[role]
        contract = prepared["p_flow_contract"]
        bound = binding.get("canonical_source_qualification_freeze", {})
        reference = contract["reference_freeze"]
        if (_pointer(bound, directory) != canonical or bound.get("sha256") != protocol["source_freeze"]["sha256"]
            or canonical != _pointer(contract["source_manifest"], directory).parent / "freeze-manifest.json"
            or binding.get("state") != "source_frozen_reference_qualified" or freeze.get("state") != binding["state"]
            or binding.get("accepted_reference_qualification") != approved
            or binding.get("original_source_freeze") != freeze.get("original_source_freeze")
            or approved.get("inference_allowed") is not True or approved.get("version") != reference.get("corpus_version")
            or approved.get("state") != "frozen_double_fresh_reference_review" or approved.get("state") != reference.get("state")
            or _pointer(approved, canonical.parent) != _pointer(reference, directory)
            or approved.get("sha256") != reference.get("sha256")):
            raise ValueError("matched qualified source/reference metadata identity mismatch")
        _pointer(binding["original_source_freeze"], canonical.parent)
        evidence = binding.get("evidence", [])
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("matched qualified source lacks immutable preparation evidence")
        modern = False
        for item in evidence:
            pointer = item.get("pointer", {})
            path = _pointer(pointer, directory)
            if pointer.get("sha256") != bound["sha256"]:
                raise ValueError("matched qualification evidence bytes differ from canonical freeze")
            kind = item.get("binding")
            if kind == "explicit_contract":
                declared = contract.get("source_qualification_freeze")
                if not isinstance(declared, dict) or _pointer(declared, directory) != canonical or path != canonical:
                    raise ValueError("matched explicit qualification evidence is not recorded in run")
                modern = True
            elif kind == "legacy_recorded_candidate_artifact" and role == "donor":
                artifacts = contract.get("candidate_artifacts", {}).get(item.get("candidate_alias"), {}).get("artifacts", [])
                index = item.get("artifact_index")
                if (type(index) is not int or index < 0 or index >= len(artifacts)
                    or _pointer(artifacts[index], directory) != canonical or path != canonical
                    or artifacts[index].get("sha256") != bound["sha256"]):
                    raise ValueError("legacy qualification evidence is not a recorded donor artifact")
            elif kind == "legacy_frozen_metadata_artifact" and role == "donor":
                relative = inside(directory, path).relative_to(directory).as_posix()
                if prepared.get("frozen_artifact_sha256", {}).get(relative) != bound["sha256"]:
                    raise ValueError("legacy qualification evidence is not frozen donor preparation metadata")
            else:
                raise ValueError("matched qualification evidence uses an unsupported binding")
        if role == "target" and not modern:
            raise ValueError("matched target must explicitly bind its qualified source")


def _matched_import_lineage(run: dict[str, Any], root: Path, contract: dict[str, Any],
                            seal: dict[str, Any] | None, matched: dict[str, Any] | None,
                            wanted: set[tuple[str, str]]) -> dict[str, Any] | None:
    pointer = run.get("matched_judgment_import")
    if matched is None:
        if seal is not None and (seal.get("matched_control_scope") is not None or seal.get("matched_judgment_import") is not None):
            raise ValueError("finalization seal has undeclared matched lineage")
        return None
    if run.get("judgment_import") is not None:
        raise ValueError("matched48 cannot masquerade as unchanged universal96 judgment import")
    if (not isinstance(pointer, dict) or pointer.get("version") != "matched-judgment-import-v1"
        or (seal is not None and (seal.get("matched_judgment_import") != pointer
                                 or seal.get("matched_control_scope") != matched["pointer"]))):
        raise ValueError("matched finalization seal lineage differs from run")
    proof_path = _pointer(pointer.get("manifest"), root)
    proof = read_json(proof_path)
    if (proof.get("version") != "matched-judgment-import-v1" or _root(Path(proof.get("target_root", ""))) != root
        or proof.get("matched_control_scope") != matched["pointer"]
        or any(proof.get(name) != pointer.get(name) for name in ("donor_root", "donor_run", "donor_finalization"))
        or run.get("matched_validation_provenance") != proof.get("validation_protocol")
        or (seal is not None and seal.get("matched_validation_provenance") != run.get("matched_validation_provenance"))
        or proof.get("universal_review_scope") != run.get("universal_review_scope")
        or proof.get("validation_protocol", {}).get("sha256") != matched["scope"]["validation_protocol"]["sha256"]
        or proof.get("window_ids") != matched["scope"]["window_ids"] or proof.get("expected_records") != len(wanted)
        or proof.get("ledger_path_relocation_allowlist") != ["response", "accepted_raw_response", "accepted_canonical_snapshot"]
        or proof.get("cost_attribution") != "donor_accepted_judgment_once_target_generation_separate"
        or any(type(proof.get(field)) is not int or proof[field] != 0
               for field in ("new_network_calls", "new_inference_calls", "new_generated_samples"))):
        raise ValueError("matched import manifest changes explicit scope or attribution")
    before = read_json(_pointer(proof.get("target_pre_import_run"), root))
    if (before.get("p_flow_contract") != contract or before.get("candidates") != run.get("candidates")
        or before.get("expected_sha256") != run.get("expected_sha256")):
        raise ValueError("matched import changes prepared new-generation identity")
    donor = _root(Path(proof["donor_root"]))
    if donor == root or donor in root.parents or root in donor.parents:
        raise ValueError("matched target and donor roots must be disjoint")
    donor_run_path, donor_seal_path = _pointer(proof.get("donor_run"), root), _pointer(proof.get("donor_finalization"), root)
    if (inside(donor, donor_run_path) != inside(donor, donor / "run.json")
        or inside(donor, donor_seal_path) != inside(donor, donor / "finalization-manifest.json")
        or proof.get("donor_inventory_sha256") != proof["donor_finalization"]["sha256"]):
        raise ValueError("matched donor seal identity mismatch")
    donor_run, donor_seal = read_json(donor_run_path), read_json(donor_seal_path)
    if donor_seal.get("state") != "required_fresh_judgments_completed":
        raise ValueError("matched donor must have a completed universal96 seal")
    _seal_inventory(donor_seal, donor, exact=True)
    for name in ("run", "expected", "final"):
        bound = _pointer(donor_seal.get(name), donor)
        expected_path = donor / (name + (".json" if name == "run" else ".jsonl"))
        if inside(donor, bound) != inside(donor, expected_path):
            raise ValueError("matched donor seal binds another artifact")
    donor_contract = donor_run["p_flow_contract"]
    for name in ("source_manifest", "references", "reference_freeze"):
        if donor_contract[name]["sha256"] != contract[name]["sha256"]:
            raise ValueError("matched donor changes source/reference identity")
    for name in ("source_manifest", "reference_freeze"):
        _pointer(donor_seal.get(name), donor)
        if donor_seal[name]["sha256"] != contract[name]["sha256"]:
            raise ValueError("matched donor seal source/reference identity mismatch")
    if (donor_run.get("matched_control_scope") is not None
        or donor_run.get("universal_review_scope", {}).get("sha256") != run["universal_review_scope"]["sha256"]
        or donor_seal.get("universal_review_scope") != donor_run.get("universal_review_scope")):
        raise ValueError("matched donor is not the declared immutable universal96 control")
    donor_scope = read_json(_pointer(donor_run["universal_review_scope"], donor))
    donor_rows = load_jsonl(donor / "expected.jsonl")
    donor_keys = {(row.get("candidate_alias"), row.get("window_id")) for row in donor_rows}
    if (len(donor_rows) != len(donor_keys) or not wanted < donor_keys
        or len(donor_keys) != donor_scope["baseline_windows_per_seed"] * len(contract["candidate_artifacts"])
        or donor_run.get("expected_sha256") != sha(donor / "expected.jsonl")):
        raise ValueError("matched target48 and donor96 denominators must remain distinct")
    if proof.get("donor_expected_records") != len(donor_keys):
        raise ValueError("matched manifest donor denominator mismatch")
    source_identity = proof.get("source_identity", {})
    required_source = {"source_manifest", "references", "reference_freeze"}
    if "source_inputs" in contract:
        required_source.add("source_inputs")
    if "source_qualification_freeze" in contract:
        required_source.add("source_qualification_freeze")
    if set(source_identity) != required_source:
        raise ValueError("matched source identity proof is incomplete")
    for name, identity in source_identity.items():
        _pointer(identity, root)
        if name not in contract or identity["sha256"] != contract[name]["sha256"]:
            raise ValueError("matched manifest source identity differs from generation")
    _matched_qualification_bindings(proof, run, root, donor_run, donor, matched["protocol"])
    target_generations = {alias: item["original_generation_cost_identity"] for alias, item in contract["candidate_artifacts"].items()}
    donor_generations = {alias: item["original_generation_cost_identity"] for alias, item in donor_contract["candidate_artifacts"].items()}
    if proof.get("target_generation") != target_generations or proof.get("donor_generation") != donor_generations:
        raise ValueError("matched generation identity differs from declared lineage")
    for alias, item in contract["candidate_artifacts"].items():
        old = donor_contract["candidate_artifacts"].get(alias, {})
        controls = [control for control in matched["protocol"].get("seed_controls", []) if control["seed"] == item["seed"]]
        if (old.get("seed") != item["seed"] or target_generations[alias] == donor_generations.get(alias)
            or len(controls) != 1 or controls[0]["old_original_run"] != donor_generations[alias]
            or set(run["candidates"][alias].get("delivery_window_ids", [])) != {wid for _, wid in wanted}):
            raise ValueError("matched control must preserve new generation and exact delivery scope separately from donor")
    audit_path = _pointer(proof.get("complete_input_audit"), root)
    inside(root, audit_path)
    audit = read_json(audit_path)
    if (audit.get("version") != "matched-evaluation-input-audit-v1" or audit.get("window_ids") != proof["window_ids"]
        or audit.get("expected_records") != len(wanted) or audit.get("donor_run") != proof["donor_run"]
        or audit.get("donor_finalization") != proof["donor_finalization"]
        or audit.get("source_qualification_bindings") != proof.get("source_qualification_bindings")
        or audit.get("target_generation") != target_generations or audit.get("donor_generation") != donor_generations):
        raise ValueError("matched complete-input audit identity mismatch")
    initial_records = audit.get("records", [])
    expected_audit_jobs = {f"{phase}/{alias}/{wid}" for phase in ("primary", "review", "adjudication") for alias, wid in wanted}
    if (len(initial_records) != len(expected_audit_jobs)
        or {row.get("job_id") for row in initial_records} != expected_audit_jobs
        or any(row.get("job_id") != f"{row.get('phase')}/{row.get('candidate_alias')}/{row.get('window_id')}" for row in initial_records)):
        raise ValueError("matched input audit does not retain every expected phase/window")
    decisions = {}
    actual_adjudication = {row["job_id"] for row in load_jsonl(root / "jobs-adjudication.jsonl")}
    final_adjudication_audits = proof.get("adjudication_audits", [])
    if seal is not None and {row.get("job_id") for row in final_adjudication_audits} != actual_adjudication:
        raise ValueError("matched final adjudication audits differ from actual target job scope")
    for row in [*initial_records, *final_adjudication_audits]:
        job_id = row.get("job_id")
        if not isinstance(job_id, str):
            raise ValueError("matched complete-input audit lacks job identity")
        decisions[job_id] = row
    imported_counts = {"primary": 0, "review": 0, "adjudication": 0}
    imported_ids = set()
    material_files = {}
    for material in proof.get("material_files", []):
        path = inside(root, _pointer(material, root))
        if path in material_files and material_files[path] != material["sha256"]:
            raise ValueError("matched material has contradictory identity")
        material_files[path] = material["sha256"]
    for job in proof.get("imported_jobs", []):
        job_id, phase = job.get("job_id"), job.get("phase")
        key = job.get("candidate_alias"), job.get("window_id")
        decision = decisions.get(job_id, {})
        equal = decision.get("equal_components", {})
        required = {"packet_bytes", "prompt_bytes", "rendered_prompt", "schema_bytes", "settings_bytes", "task_bytes",
                    "transport_contract", "fingerprint", "dispute_bytes", "accepted_prompt_file_bytes"}
        if (phase not in imported_counts or key not in wanted or job_id in imported_ids
            or job_id != f"{phase}/{key[0]}/{key[1]}" or decision.get("phase") != phase
            or (phase == "adjudication" and job_id not in actual_adjudication)
            or decision.get("eligible") is not True or set(equal) != required or not all(value is True for value in equal.values())):
            raise ValueError("matched imported judgment lacks exact complete-input equality")
        imported_ids.add(job_id)
        imported_counts[phase] += 1
        for component in required - {"fingerprint", "dispute_bytes", "accepted_prompt_file_bytes"}:
            digest = decision.get("target_material", {}).get(component + "_sha256")
            if digest != decision.get("donor_material", {}).get(component + "_sha256"):
                raise ValueError("matched input material hashes contradict equality")
            path = inside(root, root / "matched-evaluation-material" / job_id / (component + ".bin"))
            if material_files.get(path) != digest:
                raise ValueError("matched imported judgment material is not frozen")
        if (job.get("fingerprint") != decision.get("target_material", {}).get("fingerprint")
            or job.get("fingerprint") != decision.get("donor_material", {}).get("fingerprint")
            or decision.get("target_material", {}).get("dispute_bytes_sha256") != decision.get("donor_material", {}).get("dispute_bytes_sha256")):
            raise ValueError("matched imported judgment task fingerprint mismatch")
        if phase == "adjudication":
            digest = decision["target_material"].get("dispute_bytes_sha256")
            dispute_path = inside(root, root / "matched-evaluation-material" / job_id / "dispute_bytes.bin")
            fingerprint_path = inside(root, root / "matched-evaluation-material" / job_id / "dispute_fingerprint.bin")
            if (digest is None or material_files.get(dispute_path) != digest
                or material_files.get(fingerprint_path) != hashlib.sha256(job["fingerprint"].encode("ascii")).hexdigest()):
                raise ValueError("matched adjudication lacks frozen actual dispute identity")
        for name in ("accepted_raw_response_sha256", "response_sha256", "accepted_canonical_snapshot_sha256"):
            digest = job.get(name)
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("matched import lacks accepted-response hash identity")
        for name, directory in (("donor_ledger", donor), ("original_ledger_copy", root), ("new_ledger", root)):
            inside(directory, _pointer(job.get(name), directory))
        for file in job.get("files", []):
            inside(root, _pointer(file, root))
    if proof.get("imported_phase_counts") != imported_counts:
        raise ValueError("matched imported judgment phase count mismatch")
    fresh_counts = proof.get("fresh_required_phase_counts", {})
    if any(type(fresh_counts.get(phase)) is not int or fresh_counts[phase] < 0 for phase in imported_counts):
        raise ValueError("matched fresh judgment phase denominator is invalid")
    for phase in ("primary", "review"):
        required_records = sum(row.get("phase") == phase and row.get("decision") != "no_judge"
                               for row in audit.get("records", []))
        if imported_counts[phase] + fresh_counts[phase] != required_records:
            raise ValueError("matched imported/fresh judgment phase denominator mismatch")
    if imported_counts["adjudication"] + fresh_counts["adjudication"] != len(actual_adjudication):
        raise ValueError("matched adjudication imported/fresh denominator mismatch")
    if seal is not None and (proof.get("adjudication_material_complete") is not True
                            or any(job_id not in decisions or decisions[job_id].get("decision") not in {"eligible", "fresh_required", "target_already_started"}
                                   for job_id in actual_adjudication)):
        raise ValueError("sealed matched root lacks actual adjudication material audit")
    if seal is not None:
        for job_id in actual_adjudication - imported_ids:
            decision = decisions[job_id]
            for component in ("packet_bytes", "prompt_bytes", "rendered_prompt", "schema_bytes", "settings_bytes",
                              "task_bytes", "transport_contract", "dispute_bytes", "dispute_fingerprint"):
                path = inside(root, root / "matched-evaluation-material" / job_id / (component + ".bin"))
                digest = material_files.get(path)
                declared = decision.get("target_material", {}).get(component + "_sha256")
                if digest is None or (declared is not None and digest != declared):
                    raise ValueError("matched fresh adjudication lacks frozen actual input material")
            task = material_files[inside(root, root / "matched-evaluation-material" / job_id / "task_bytes.bin")]
            fingerprint = material_files[inside(root, root / "matched-evaluation-material" / job_id / "dispute_fingerprint.bin")]
            if fingerprint != hashlib.sha256(task.encode("ascii")).hexdigest():
                raise ValueError("matched fresh adjudication fingerprint differs from actual task")
    return {"scope_sha256": matched["pointer"]["sha256"], "manifest_sha256": sha(proof_path),
            "donor_root": str(donor), "donor_run_sha256": sha(donor_run_path), "donor_finalization_sha256": sha(donor_seal_path),
            "target_generation": target_generations, "donor_generation": donor_generations,
            "target_expected_records": len(wanted), "donor_expected_records": len(donor_keys),
            "imported_phase_counts": imported_counts, "fresh_required_phase_counts": proof.get("fresh_required_phase_counts"),
            "initial_complete_input_status": audit.get("complete_input_status"),
            "initial_all_complete_inputs_identical": audit.get("all_complete_inputs_identical"),
            "actual_adjudication_records": len(actual_adjudication), "new_network_calls_during_import": 0,
            "cost_attribution": proof["cost_attribution"]}


def _evaluation(path: Path) -> dict[str, Any]:
    root = _root(path)
    run = read_json(root / "run.json")
    if "fresh_confirmation_scope" in run or run.get("split") == "confirmation":
        raise ValueError("fresh confirmation requires the explicitly registered confirmation authority branch")
    if run.get("lane") != "P-flow" or run.get("profile") != "sol-high-auto-v1":
        raise ValueError("comparison requires frozen P-flow sol-high-auto-v1 evaluation roots")
    contract = run.get("p_flow_contract", {})
    expected_path = root / "expected.jsonl"
    if sha(expected_path) != run.get("expected_sha256"):
        raise ValueError("evaluation expected ledger changed")
    source = contract.get("source_manifest")
    _pointer(source, root)
    references, freeze = contract.get("references"), contract.get("reference_freeze")
    _pointer(references, root)
    _pointer(freeze, root)
    if freeze.get("state") != "frozen_double_fresh_reference_review" or not isinstance(freeze.get("corpus_version"), str):
        raise ValueError("comparison reference freeze is not qualified")
    if run.get("references_sha256") != references["sha256"]:
        raise ValueError("run and contract reference identity mismatch")
    if run.get("corpus_manifest_sha256") != source["sha256"]:
        raise ValueError("run and contract source identity mismatch")
    scope_pointer, review_scope = _universal_scope(run, root, source, freeze)
    matched = _matched_scope(run, root, contract, scope_pointer)
    window_ids = contract.get("window_ids")
    if not isinstance(window_ids, list) or not window_ids or len(set(window_ids)) != len(window_ids):
        raise ValueError("evaluation requires exact unique contract window IDs")
    expected = load_jsonl(expected_path)
    aliases = set(contract.get("candidate_artifacts", {}))
    if not aliases or aliases != set(run.get("candidates", {})):
        raise ValueError("evaluation candidate metadata differs from frozen contract")
    wanted = {(alias, wid) for alias in aliases for wid in window_ids}
    expected_index = {}
    for row in expected:
        key = row.get("candidate_alias"), row.get("window_id")
        if key in expected_index:
            raise ValueError("duplicate evaluation expected candidate/window")
        expected_index[key] = row
    if set(expected_index) != wanted:
        raise ValueError("evaluation expected rows differ from contract exact window scope")
    final_path = root / "final.jsonl"
    seal_path = root / "finalization-manifest.json"
    seal = read_json(seal_path) if seal_path.is_file() else None
    if seal is not None:
        if seal.get("state") != "required_fresh_judgments_completed":
            raise ValueError("quality finalization seal is not terminal")
        for name in ("final", "expected", "run"):
            bound = _pointer(seal.get(name), root)
            expected_file = {"final": final_path, "expected": expected_path, "run": root / "run.json"}[name]
            if inside(root, bound) != inside(root, expected_file):
                raise ValueError("finalization seal binds a different evaluation artifact")
        for name, pointer in (("reference_freeze", freeze), ("source_manifest", source)):
            _pointer(seal.get(name), root)
            if seal[name]["sha256"] != pointer["sha256"]:
                raise ValueError("finalization seal source/reference identity mismatch")
        _seal_inventory(seal, root, exact=True)
        if seal.get("expected_records") != len(expected):
            raise ValueError("finalization seal expected denominator mismatch")
        if seal.get("universal_review_scope") != scope_pointer:
            raise ValueError("finalization seal universal review scope differs from run")
    import_provenance = _import_lineage(run, root, contract, seal, wanted)
    matched_import = _matched_import_lineage(run, root, contract, seal, matched, wanted)
    # A provisional final ledger is not final quality evidence. Absence of its
    # completion seal retains every expected item as an unknown, not a zero.
    finals = load_jsonl(final_path) if seal is not None else []
    final_index = {}
    for row in finals:
        key = row.get("candidate_alias"), row.get("window_id")
        if key in final_index or key not in wanted:
            raise ValueError("duplicate or unexpected evaluation final candidate/window")
        scope = expected_index[key]
        for field in ("work", "category", "scored_ids", "scene_id"):
            if row.get(field) != scope.get(field):
                raise ValueError("final/expected scoring identity mismatch")
        final_index[key] = row
    review_coverage = _review_coverage(final_index, wanted)
    if seal is not None:
        coverage = seal.get("universal_review_coverage", {})
        known_reviewed = sum((row.get("semantic") is not None or row.get("naturalness") is not None)
                             and row.get("reviewed") is True and row.get("status") != "delivery_zero"
                             for row in final_index.values())
        counts = ("expected_records", "judgeable_records", "selected_records", "accepted_review_records", "known_scored_reviewed_records")
        if (any(type(coverage.get(field)) is not int or coverage[field] < 0 for field in counts)
            or coverage["expected_records"] != len(wanted) or coverage["selected_records"] != len(wanted)
            or coverage["known_scored_reviewed_records"] != known_reviewed
            or coverage["judgeable_records"] != sum(row.get("structural_status") not in NO_JUDGE_STATUSES
                                                     for row in expected_index.values())
            or not known_reviewed <= coverage["accepted_review_records"] <= coverage["judgeable_records"] <= len(wanted)
            or type(coverage.get("complete")) is not bool
            or coverage["complete"] != (coverage["accepted_review_records"] == coverage["judgeable_records"])):
            raise ValueError("universal review coverage seal is inconsistent")
        review_coverage["transport_complete"] = coverage["complete"]
        review_coverage["accepted_review_records"] = coverage["accepted_review_records"]
        review_coverage["judgeable_records"] = coverage["judgeable_records"]
    metadata = {}
    for alias, artifact in contract["candidate_artifacts"].items():
        original_pointer = artifact.get("original_generation_cost_identity")
        original_path = _pointer(original_pointer, root)
        original = read_json(original_path)
        settings = original.get("settings", {})
        generation_seed = artifact.get("seed")
        if type(generation_seed) is not int or generation_seed not in SEEDS or settings.get("seed") != generation_seed:
            raise ValueError("generation seed differs from frozen original run metadata")
        recipe_id = artifact.get("recipe_id")
        if not isinstance(recipe_id, str) or not recipe_id or settings.get("label") != recipe_id:
            raise ValueError("recipe ID differs from frozen original run label")
        recipe = original.get("recipe")
        if recipe != settings.get("recipe") or not isinstance(recipe, str):
            raise ValueError("recipe protocol differs from original frozen settings")
        recipe_code = original.get("code_sha256", {}).get(RECIPE_CODE)
        if not isinstance(recipe_code, str) or len(recipe_code) != 64:
            raise ValueError("original generation lacks frozen recipe implementation SHA256")
        # Input/packing hashes vary by seed and projection; retain each original
        # identity separately while comparing only recipe configuration fields.
        excluded = {"seed", "label", "inputs", "input_sha256", "packed_mapping_sha256", "source_manifest_sha256"}
        recipe_settings = {name: value for name, value in settings.items() if name not in excluded}
        attempt_pointer = artifact.get("original_trial_attempt_identity")
        if settings.get("source_preparation") is not None and attempt_pointer is None:
            trial_finish = original_path.parents[4] / "trial-completion.json"
            for given in artifact.get("artifacts", []):
                if _pointer(given, root, check_bytes=False) == trial_finish:
                    attempt_pointer = given
                    break
        auxiliary = _auxiliary_generation(settings, original, original_path, source, attempt_pointer)
        if auxiliary is not None:
            recipe_settings["source_preparation"] = auxiliary["configuration"]
        identity = hashlib.sha256(json.dumps({"settings": recipe_settings, "code_sha256": recipe_code},
                                             sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        session_path = original_path.parent.parent / "session.json"
        session = read_json(session_path) if session_path.is_file() else None
        runtime = session.get("identity") if session is not None else original.get("runtime_identity")
        if not isinstance(runtime, dict):
            raise ValueError("original generation lacks frozen model/template/runtime identity")
        engine = runtime.get("engine", {})
        stable_engine = {key: value for key, value in engine.items() if key in (
            "build", "cuda", "model_sha256", "executable_sha256", "custom_runtime_identity_sha256",
            "context_size", "gpu_layers_requested", "threads", "threads_batch", "kv_type_k", "kv_type_v",
            "prompt_cache_ram_mib", "runtime_source_sha256", "runtime_dll_sha256")}
        if not isinstance(stable_engine.get("model_sha256"), str) or not isinstance(runtime.get("template_sha256"), str):
            raise ValueError("original generation model/template identity incomplete")
        runtime_hash = hashlib.sha256(json.dumps({"engine": stable_engine, "template_sha256": runtime["template_sha256"]},
                                                sort_keys=True).encode()).hexdigest()
        metadata[alias] = {"seed": generation_seed, "recipe_id": recipe_id, "recipe": recipe,
            "recipe_settings": recipe_settings, "recipe_identity_sha256": identity,
            "recipe_code_sha256": recipe_code, "original_generation": original_pointer,
            "all_snapshot_hashes": original.get("code_sha256", {}),
            "source_snapshot_root": original_path.parent.parent / "source",
            "runtime_identity_sha256": runtime_hash, "model_sha256": stable_engine["model_sha256"],
            "session_sha256": sha(session_path) if session is not None else None,
            "derivation": artifact.get("derivation"), "new_inference_calls": artifact.get("new_inference_calls"),
            "new_generated_samples": artifact.get("new_generated_samples"), "trial_lineage": None}
        metadata[alias]["source_preparation"] = auxiliary
        metadata[alias]["native_expected_batch_ids"] = original.get("expected_window_ids")
        metadata[alias]["native_inputs"] = {"path": str(original_path.parent / "inputs.jsonl"), "sha256": settings.get("input_sha256")}
        metadata[alias]["native_packed_mapping_sha256"] = settings.get("packed_mapping_sha256")
        # This is the documented v2_trial layout, not a guessed trial ID:
        # trial/execution/runtime-run/translation/<label>/run.json.
        if (original_path.parent.parent.name == "translation"
            and original_path.parent.parent.parent.name == "runtime-run"
            and original_path.parents[3].name == "execution"):
            trial_start = original_path.parents[4] / "trial-start.json"
            if trial_start.is_file():
                started = read_json(trial_start)
                card_path = Path(started["card_path"])
                if not card_path.is_absolute():
                    card_path = trial_start.parent / card_path
                if sha(card_path) != started.get("card_sha256"):
                    raise ValueError("original v2 trial card execution lineage changed")
                metadata[alias]["trial_lineage"] = {"trial_start_sha256": sha(trial_start),
                    "trial_root": str(trial_start.parent),
                    "card_sha256": started["card_sha256"], "card_path": str(card_path.resolve()),
                    "original_stage": started.get("card", {}).get("prepare", {}).get("stage")}
        if seal is not None:
            identity = seal.get("candidate_identity", {}).get(alias)
            if (not isinstance(identity, dict) or identity.get("seed") != generation_seed
                or identity.get("recipe_id") != recipe_id
                or identity.get("original_generation_cost_identity") != original_pointer):
                raise ValueError("finalization seal candidate generation identity mismatch")
        for row in [*expected_index.values(), *final_index.values()]:
            if row["candidate_alias"] == alias and "seed" in row and row["seed"] != generation_seed:
                raise ValueError("ledger seed conflicts with original generation seed")
    return {"root": root, "run": run, "metadata": metadata, "window_ids": set(window_ids), "matched": matched,
            "universal_review_scope": review_scope, "universal_review_scope_sha256": scope_pointer["sha256"],
            "expected": expected_index, "final": final_index, "source_sha256": source["sha256"],
            "reference_identity": {"references_sha256": references["sha256"], "freeze_sha256": freeze["sha256"],
                                   "corpus_version": freeze["corpus_version"]},
            "provenance": {"root": str(root), "run_sha256": sha(root / "run.json"),
                           "expected_sha256": sha(expected_path),
                           "final_sha256": sha(final_path) if final_path.is_file() else None,
                           "final_eligible_for_statistics": seal is not None,
                           "universal_review_scope_sha256": scope_pointer["sha256"],
                           "universal_review_coverage": review_coverage, "judgment_import": import_provenance,
                           "matched_judgment_import": matched_import,
                           "finalization_manifest_sha256": sha(seal_path) if seal is not None else None}}


def _card(path: Path, source_manifest: Path, policy: Path, windows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    card = read_json(path)
    if card.get("schema") != "hy30-flow-trial-card-v2":
        raise ValueError("comparison card must be frozen v2 trial card")
    source, decision = card.get("source", {}), card.get("decision_policy", {})
    if source.get("manifest_sha256") != sha(source_manifest):
        raise ValueError("card/source qualified manifest identity mismatch")
    if decision.get("sha256") != sha(policy):
        raise ValueError("card/frozen decision policy identity mismatch")
    _pointer({"path": source.get("manifest"), "sha256": source.get("manifest_sha256")}, path.parent)
    _pointer(decision, path.parent)
    settings = card.get("prepare", {})
    split, stage = settings.get("split"), settings.get("stage")
    if stage not in {"screening", "confirmation"} or split not in {"screen-a", "screen-b", "screening", "confirmation"}:
        raise ValueError("engineering or ambiguous-stage cards cannot establish comparative quality scope")
    if (stage == "confirmation") != (split == "confirmation"):
        raise ValueError("card stage/source split mismatch")
    selected_scenes = settings.get("selected_scene_ids")
    ids = {wid for wid, row in windows.items() if (row["split"] == split or
          (split == "screening" and row["split"] in {"screen-a", "screen-b"})) and
          (selected_scenes is None or row["scene_id"] in selected_scenes)}
    if not ids:
        raise ValueError("card selects no frozen source windows")
    if type(settings.get("seed")) is not int or settings["seed"] not in SEEDS:
        raise ValueError("representative card seed not in frozen generation seed set")
    group = card.get("candidate_group")
    if not isinstance(group, str) or not group:
        raise ValueError("comparison card requires explicitly declared stable candidate_group")
    configuration = {name: value for name, value in settings.items() if name not in {"seed", "recipe_id"}}
    implementation = {}
    for pointer in card.get("implementation_identity", []):
        relative = _relative_code(pointer["path"])
        if relative in implementation or not isinstance(pointer.get("sha256"), str) or len(pointer["sha256"]) != 64:
            raise ValueError("declared used implementation has duplicate or missing SHA256")
        implementation[relative] = pointer["sha256"]
    if not implementation:
        raise ValueError("candidate card lacks declared used implementation identity")
    auxiliary = card.get("source_preparation")
    auxiliary_identity = None
    if auxiliary is not None:
        if not isinstance(auxiliary, dict) or set(auxiliary) != {"plan", "sha256"}:
            raise ValueError("card auxiliary identity requires its complete frozen plan")
        auxiliary_identity = _auxiliary_plan({"path": auxiliary["plan"], "sha256": auxiliary["sha256"]},
                                             path.parent, settings["seed"])
        aux_source = auxiliary_identity["source"]
        if (aux_source["manifest"]["sha256"] != source["manifest_sha256"]
            or aux_source["scenes"]["sha256"] != source.get("scenes_sha256")
            or (selected_scenes is not None and auxiliary_identity["configuration"]["scene_ids"] != selected_scenes)
            or not {windows[wid]["scene_id"] for wid in ids} <= set(auxiliary_identity["configuration"]["scene_ids"])
            or (stage == "confirmation" and auxiliary_identity["stage"] != "confirmation")
            or (stage == "screening" and auxiliary_identity["stage"] not in {"screening", "qualification"})):
            raise ValueError("card auxiliary plan differs from selected source/stage/order")
        projection = settings.get("source_preparation_projection")
        if auxiliary_identity["configuration"]["schema"].endswith("-v3"):
            from .v2_source_projection import validate_projection_mode
            validate_projection_mode(auxiliary_identity["configuration"]["mode"],
                                     auxiliary_identity["configuration"]["protocol"], projection)
        elif projection is not None:
            raise ValueError("legacy auxiliary card cannot use a v3 projection")
        configuration["source_preparation"] = {**auxiliary_identity["configuration"], "projection": projection, "generation_split": split}
    elif settings.get("source_preparation_projection") is not None:
        raise ValueError("card projection requires a declared auxiliary plan")
    return {"candidate_group": group, "recipe_id": settings["recipe_id"], "recipe": settings.get("recipe", "c0"),
            "representative_seed": settings["seed"], "window_ids": ids, "stage": stage,
            "implementation_identity": implementation,
            "packing": {key: settings.get(key) for key in ("target_size", "context_before", "context_after", "token_target", "common_context", "offset")},
            "selected_scene_ids": selected_scenes, "source_manifest_sha256": sha(source_manifest),
            "source_scenes_sha256": source.get("scenes_sha256"), "source_estimate": card.get("source_estimate", {}),
            "source_preparation": configuration.get("source_preparation"),
            "configuration_sha256": hashlib.sha256(json.dumps({"settings": configuration, "implementation": implementation},
                                                                 sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "options": settings.get("options") or {}, "path": str(path.resolve()), "sha256": sha(path)}


def _card_generation(metadata: dict[str, Any], card: dict[str, Any], *, matched_control: bool = False) -> None:
    if metadata["seed"] != card["representative_seed"] or metadata["recipe_id"] != card["recipe_id"]:
        raise ValueError("generation seed/recipe differs from exact frozen card")
    for relative, digest in card["implementation_identity"].items():
        if metadata["all_snapshot_hashes"].get(relative) != digest:
            raise ValueError("declared used implementation differs from original generation snapshot")
        saved = inside(metadata["source_snapshot_root"], metadata["source_snapshot_root"] / relative)
        if sha(saved) != digest:
            raise ValueError("saved declared implementation source bytes changed")
    _auxiliary_card_binding(metadata.get("source_preparation"), card)
    lineage = metadata["trial_lineage"]
    if matched_control and lineage is None:
        raise ValueError("matched control requires exact preregistered v2 trial execution lineage")
    if lineage is not None and lineage["card_sha256"] != card["sha256"]:
        reuse = (not matched_control and metadata["derivation"] is not None and metadata["new_inference_calls"] == 0
                 and metadata["new_generated_samples"] == 0 and lineage["original_stage"] == "qualification")
        if not reuse:
            raise ValueError("candidate comparison card differs from exact per-seed executed trial card")
    if matched_control:
        _pointer(metadata["native_inputs"], Path(lineage["trial_root"]))
        packed_path = Path(lineage["trial_root"]) / "prepared/packed-mapping.json"
        if sha(packed_path) != metadata["native_packed_mapping_sha256"]:
            raise ValueError("matched control packing bytes changed")
        packed = read_json(packed_path)
        if (packed.get("packing") != card["packing"] or packed.get("scene_ids") != card["selected_scene_ids"]
            or packed.get("source_manifest", {}).get("sha256") != card["source_manifest_sha256"]
            or packed.get("source_scenes", {}).get("sha256") != card["source_scenes_sha256"]
            or not isinstance(metadata["native_expected_batch_ids"], list)
            or len(metadata["native_expected_batch_ids"]) != card["source_estimate"].get("batches")
            or [row["id"] for row in packed.get("batches", [])] != metadata["native_expected_batch_ids"]):
            raise ValueError("matched control local packing/request scope differs from exact frozen card")


def _confirmation_compare(paths: list[Path], source_manifest: Path, policy_path: Path,
                          windows: dict[str, dict[str, Any]], policy: dict[str, Any],
                          card_paths: list[Path], authority: dict[str, str],
                          expected_policy_sha256: str) -> dict[str, Any]:
    """Read fresh per-seed multi-alias roots only after external queue validation.

    Native preparation retains every locked slot even after a stopped dispatch.
    An unrun slot has no original generation identity and remains unknown.
    """
    from . import v2_confirmation as c
    from . import v2_confirmation_dispatch as dispatch
    from . import v2_confirmation_evaluation as bridge

    plan = read_json(_pointer(authority, Path.cwd()))
    pins = {"registered_lock_sha256": plan["confirmation_dispatch_authority"]["registered_lock_sha256"],
            "registered_unseal_sha256": plan["confirmation_dispatch_authority"]["registered_unseal_sha256"],
            "expected_policy_sha256": expected_policy_sha256}
    plan = dispatch.validate_dispatch_plan(authority, **pins)
    lock = c.validate_lock(plan["confirmation_dispatch_authority"]["lock"],
                           expected_policy_sha256=expected_policy_sha256)
    if (lock["source_scope"]["manifest"] != c.pointer(source_manifest)
        or set(windows) != set(bridge._selection(lock["source_scope"]))
        or len(windows) != 48 or any(row.get("split") != "confirmation"
            or row.get("selection_type") != "representative" for row in windows.values())):
        raise ValueError("fresh confirmation must use the complete locked representative48 source")
    groups = [lock["baseline"], *lock["candidates"]]
    aliases = {row["candidate_alias"] for row in groups}
    baseline = lock["baseline"]["candidate_alias"]
    required_cards = {item["card"]["path"]: item["card"]["sha256"]
                      for group in groups for item in group["cards"]}
    supplied_cards = {str(path.resolve()): sha(path) for path in card_paths}
    if supplied_cards != required_cards or len(card_paths) != len(required_cards):
        raise ValueError("fresh confirmation requires every exact locked C0 and candidate card")
    roots = sorted({_root(path) for path in paths})
    if len(roots) != len(SEEDS):
        raise ValueError("fresh confirmation requires exactly three complete per-seed evaluation denominators")
    contexts, seen_seeds = [], set()
    # All roots must pass the native metadata guard before any final is opened.
    for root in roots:
        run = read_json(root / "run.json")
        if "fresh_confirmation_scope" not in run or run.get("split") != "confirmation":
            raise ValueError("fresh confirmation cannot mix screening evaluation lineage")
        context = bridge.validate_metadata(root, authority, **pins)
        seed = context["confirmation_generation_seed"]
        if seed in seen_seeds:
            raise ValueError("duplicate fresh confirmation generation seed")
        seen_seeds.add(seed)
        contexts.append((root, context, run))
    if seen_seeds != set(SEEDS):
        raise ValueError("fresh confirmation seed scope differs from locked queue")
    expected, final, provenance, generations = [], [], [], []
    reference_identity = None
    receipt_identity = None
    runtime_identity = None
    recipe_identities = {}
    for root, context, run in contexts:
        seed = context["confirmation_generation_seed"]
        contract = run["p_flow_contract"]
        source, freeze, references = (contract[key] for key in ("source_manifest", "reference_freeze", "references"))
        for pointer in (source, freeze, references):
            _pointer(pointer, root)
        identity = {"references_sha256": references["sha256"], "freeze_sha256": freeze["sha256"],
                    "corpus_version": freeze["corpus_version"]}
        if reference_identity is not None and reference_identity != identity:
            raise ValueError("fresh confirmation paired reference bytes/version differ")
        reference_identity = identity
        receipt = context["confirmation_generation_receipt"]
        if receipt_identity is not None and receipt != receipt_identity:
            raise ValueError("fresh confirmation roots use different terminal queues")
        receipt_identity = receipt
        rows = load_jsonl(root / "expected.jsonl")
        wanted = {(alias, wid) for alias in aliases for wid in windows}
        indexed = {(row["candidate_alias"], row["window_id"]): row for row in rows}
        if len(rows) != len(wanted) or set(indexed) != wanted:
            raise ValueError("fresh confirmation expected denominator differs from locked groups")
        for (alias, wid), row in indexed.items():
            window = windows[wid]
            if (("seed" in row and row["seed"] != seed)
                or row.get("work") != window.get("work", window.get("work_id"))
                or CATEGORY_MAP.get(row.get("category")) != CATEGORY_MAP.get(window["category"])
                or row.get("scene_id") != window["scene_id"] or row.get("scored_ids") != window["scored_ids"]):
                raise ValueError("fresh confirmation expected/source scoring identity differs")
            expected.append({"candidate_alias": alias, "window_id": wid, "seed": seed,
                "work": window.get("work", window.get("work_id")), "work_id": window.get("work_id", window.get("work")),
                "category": CATEGORY_MAP[window["category"]], "scene_id": window["scene_id"], "scored_ids": window["scored_ids"]})
        evidence = read_json(_pointer(context["confirmation_generation_evidence"], root))
        seed_generations = [row for row in evidence["generations"] if row["seed"] == seed]
        slot_identities = {slot["candidate_alias"]: {"seed": seed,
            "recipe_id": read_json(_pointer(slot["card"], root))["prepare"]["recipe_id"],
            "original_generation_cost_identity": slot["original_run"],
            "original_trial_attempt_identity": slot.get("trial_completion", slot.get("native_trial")),
            "generation_attempt_status": slot["status"], "native_complete": slot["native_complete"]}
            for slot in seed_generations}
        seal_path = root / "finalization-manifest.json"
        seal = read_json(seal_path) if seal_path.is_file() else None
        accepted = {}
        if seal is not None:
            if seal.get("state") != "required_fresh_judgments_completed":
                raise ValueError("fresh confirmation quality seal is not terminal")
            if bridge.FORBIDDEN_LINEAGE & seal.keys():
                raise ValueError("fresh confirmation seal cannot carry screening judgment lineage")
            if seal.get("candidate_identity") != slot_identities:
                raise ValueError("fresh confirmation seal changes original generation or attempted-slot identity")
            for name in ("run", "expected", "final"):
                if inside(root, _pointer(seal.get(name), root)) != inside(root, root / (name + (".json" if name == "run" else ".jsonl"))):
                    raise ValueError("fresh confirmation seal binds different artifacts")
            _seal_inventory(seal, root, exact=True)
            mirrors = bridge.seal_metadata(root, **pins)
            if any(seal.get(key) != value for key, value in mirrors.items()) or seal.get("expected_records") != len(wanted):
                raise ValueError("fresh confirmation seal authority/review coverage differs")
            for name, pointer in (("reference_freeze", freeze), ("source_manifest", source)):
                _pointer(seal.get(name), root)
                if seal[name]["sha256"] != pointer["sha256"]:
                    raise ValueError("fresh confirmation seal source/reference differs")
            for row in load_jsonl(root / "final.jsonl"):
                key = row["candidate_alias"], row["window_id"]
                if key not in wanted or key in accepted:
                    raise ValueError("fresh confirmation duplicate or unexpected final row")
                if (("seed" in row and row["seed"] != seed)
                    or any(row.get(field) != indexed[key].get(field) for field in ("work", "category", "scene_id", "scored_ids"))):
                    raise ValueError("fresh confirmation final/expected scoring identity differs")
                accepted[key] = row
            _review_coverage(accepted, wanted)
        for slot in seed_generations:
            alias = slot["candidate_alias"]
            auxiliary = None
            if not slot["native_complete"]:
                if any(accepted.get((alias, wid), {}).get("semantic") is not None
                       or accepted.get((alias, wid), {}).get("naturalness") is not None for wid in windows):
                    raise ValueError("unrun or failed confirmation generation cannot have quality scores")
            else:
                original_path = _pointer(slot["original_run"], root)
                original = read_json(original_path)
                session = read_json(_pointer(slot["session"], root))
                engine = session["identity"]["engine"]
                stable_runtime = {"engine": {key: value for key, value in engine.items() if key in (
                    "build", "cuda", "model_sha256", "executable_sha256", "custom_runtime_identity_sha256",
                    "context_size", "gpu_layers_requested", "threads", "threads_batch", "kv_type_k", "kv_type_v",
                    "prompt_cache_ram_mib", "runtime_source_sha256", "runtime_dll_sha256")},
                    "template_sha256": session["identity"].get("template_sha256")}
                if not isinstance(stable_runtime["template_sha256"], str) or len(stable_runtime["template_sha256"]) != 64:
                    raise ValueError("fresh confirmation lacks a frozen template identity")
                if runtime_identity is not None and stable_runtime != runtime_identity:
                    raise ValueError("fresh confirmation paired model/template/runtime differs")
                runtime_identity = stable_runtime
                excluded = {"seed", "label", "inputs", "input_sha256", "packed_mapping_sha256", "source_manifest_sha256"}
                configuration = {key: value for key, value in original["settings"].items() if key not in excluded}
                auxiliary = _auxiliary_generation(original["settings"], original, original_path, source,
                    slot.get("trial_completion", slot.get("native_trial")))
                _fresh_auxiliary_binding(auxiliary, slot["card"], root, source_manifest, policy_path, windows)
                if auxiliary is not None:
                    configuration["source_preparation"] = auxiliary["configuration"]
                code = original["code_sha256"].get(RECIPE_CODE)
                recipe_identity = {"recipe": original["recipe"], "recipe_code_sha256": code,
                    "recipe_identity_sha256": hashlib.sha256(json.dumps({"settings": configuration, "code_sha256": code},
                        sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
                if alias in recipe_identities and recipe_identities[alias] != recipe_identity:
                    raise ValueError("fresh confirmation complete recipe differs across generation seeds")
                recipe_identities[alias] = recipe_identity
            generations.append({**{key: slot.get(key) for key in ("candidate_alias", "seed", "status", "attempted",
                "native_complete", "original_run", "trial_completion", "native_trial", "native_total_flow_seconds")},
                **({"source_preparation": _auxiliary_provenance(auxiliary)} if auxiliary is not None else {})})
        for (alias, wid), row in accepted.items():
            final.append({"candidate_alias": alias, "window_id": wid, "seed": seed,
                **{key: row.get(key) for key in ("semantic", "naturalness", "status", "errors", "reviewed", "structural_status")}})
        provenance.append({"root": str(root), "run_sha256": sha(root / "run.json"),
            "expected_sha256": sha(root / "expected.jsonl"), "final_eligible_for_statistics": seal is not None,
            "final_sha256": sha(root / "final.jsonl") if (root / "final.jsonl").is_file() else None,
            "finalization_manifest_sha256": sha(seal_path) if seal else None, **context})
    mult = policy["multiplicity"]
    stats = build_statistics(expected, final, {"windows": list(windows.values())}, baseline,
        seeds=SEEDS, bootstrap_iterations=mult["bootstrap_iterations"], seed=mult["bootstrap_seed"],
        confidence=mult["family_confidence"], family_size=mult["family_size"])
    _series_sensitivity(stats)
    gates = {alias: {"known_records": sum(row["semantic"] is not None for row in final if row["candidate_alias"] == alias),
        "expected_records": 48 * len(SEEDS), "severe_state": "unknown", "severe_confirmation_gate_passed": None,
        "delivery_confirmation_gate_passed": None} for alias in sorted(aliases)}
    for gate in gates.values():
        gate["missing_or_unscorable_records"] = gate["expected_records"] - gate["known_records"]
    return {"schema_version": "hy30-flow-v2-comparison-v1", "stage": "confirmation",
        "interpretation": "confirmation_descriptive_no_automatic_decision", "automatic_winner": None,
        "policy_gates_automatically_evaluated": False, "decision_policy_sha256": sha(policy_path),
        "source_manifest_sha256": sha(source_manifest), "baseline_scope_mode": "fresh_confirmation48",
        "universal_review_scope_sha256": None, "matched_control_scope_sha256": None,
        "fresh_confirmation_scope_sha256": lock["evaluation_contract"]["sha256"],
        "locked_candidate_categories": {group["candidate_alias"]: group["applicable_categories"] for group in lock["candidates"]},
        "confirmation_authority": contexts[0][1]["confirmation_authority"], "reference_identity": reference_identity,
        "window_ids": sorted(windows), "expected_windows_per_candidate": 48, "expected_seeds": list(SEEDS),
        "coverage_and_gates": gates, "statistics": stats, "evaluation_provenance": provenance,
        "generation_provenance": generations, "recipe_identities": recipe_identities,
        "missing_generation_seeds": {alias: [row["seed"] for row in generations
            if row["candidate_alias"] == alias and not row["native_complete"]] for alias in sorted(aliases)},
        "cards": [{"path": path, "sha256": digest} for path, digest in sorted(required_cards.items())],
        "limitations_zh": ["独立确认严格绑定锁定候选、开封及全新生成队列；本入口不自动宣布胜者。",
            "失败或未执行条目保留全部48窗口与3seed分母，未生成条目没有原始生成身份。",
            "无完成封存清单的暂定final不作为终评质量证据；严重根因及交付确认门仍需独立判断。",
            "配对区间仅覆盖完整配对子集，缺分0／4界不是置信区间；仅描述冻结抽样框与分配。"]}


def compare(baseline_paths: list[Path], candidate_paths: list[Path], source_manifest: Path,
            policy_path: Path, *, card_paths: list[Path] | None = None,
            expected_policy_sha256: str = POLICY_SHA256,
            expected_review_scope_sha256: str = UNIVERSAL_REVIEW_SHA256,
            expected_matched_scope_sha256: str = MATCHED_SCOPE_SHA256,
            confirmation_authority: dict[str, str] | None = None) -> dict[str, Any]:
    """Reconcile all frozen seeds, retaining absent final rows and unrun seeds.

    The expected-policy override supports synthetic fixtures; the CLI always binds
    the project's frozen policy SHA256. Evaluation aliases are labels only; seed
    and recipe identity come from original frozen generation metadata.
    """
    if sha(policy_path) != expected_policy_sha256:
        raise ValueError("decision policy differs from pre-candidate frozen SHA256")
    policy = read_json(policy_path)
    if policy.get("status") != "frozen_before_candidate_quality":
        raise ValueError("decision policy must be frozen before candidate quality")
    endpoint = policy.get("primary_endpoint", {})
    seeds = tuple(endpoint.get("generation_seeds", []))
    if seeds != SEEDS or endpoint.get("estimator") != ESTIMATOR:
        raise ValueError("policy seed set or estimator differs from flow-v2 contract")
    baseline_alias = policy.get("baseline", {}).get("alias")
    if not isinstance(baseline_alias, str) or not baseline_alias:
        raise ValueError("policy requires explicit baseline alias")
    manifest = read_json(source_manifest)
    windows = {}
    for row in manifest.get("windows", []):
        wid = row.get("id", row.get("window_id"))
        if not isinstance(wid, str) or wid in windows:
            raise ValueError("source metadata requires unique window IDs")
        windows[wid] = row
    if not windows or not baseline_paths or not candidate_paths:
        raise ValueError("source windows and baseline/candidate roots required")
    confirmation_frame = any(row.get("split") == "confirmation" for row in windows.values())
    if confirmation_frame or confirmation_authority is not None:
        if not confirmation_frame or confirmation_authority is None:
            raise ValueError("fresh confirmation requires a separately pinned authority and confirmation-only frame")
        return _confirmation_compare([*baseline_paths, *candidate_paths], source_manifest, policy_path,
            windows, policy, card_paths or [], confirmation_authority, expected_policy_sha256)
    cards = [_card(path, source_manifest, policy_path, windows) for path in card_paths or []]
    card_by_recipe, card_groups = {}, {}
    for card in cards:
        if card["recipe_id"] in card_by_recipe:
            raise ValueError("duplicate exact frozen recipe card")
        card_by_recipe[card["recipe_id"]] = card
        group = card["candidate_group"]
        if group in card_groups and card_groups[group][0]["configuration_sha256"] != card["configuration_sha256"]:
            raise ValueError("candidate card configuration changed across generation seeds")
        card_groups.setdefault(group, []).append(card)
        if len({item["representative_seed"] for item in card_groups[group]}) != len(card_groups[group]):
            raise ValueError("duplicate candidate-group card seed")
    evaluations = [("baseline", _evaluation(path)) for path in baseline_paths]
    evaluations += [("candidate", _evaluation(path)) for path in candidate_paths]
    selected = None
    aliases: dict[str, dict[str, Any]] = {}
    loaded = []
    seen = set()
    reference_identity = None
    runtime_identity = None
    review_scope_identity = None
    matched_scope_identity = None
    baseline_scope_mode = None
    for role, evaluation in evaluations:
        scope = evaluation["universal_review_scope"]
        if evaluation["universal_review_scope_sha256"] != expected_review_scope_sha256:
            raise ValueError("universal review scope differs from pre-candidate frozen SHA256")
        if scope["decision_policy"]["sha256"] != sha(policy_path):
            raise ValueError("universal review scope decision-policy identity mismatch")
        if review_scope_identity is None:
            review_scope_identity = evaluation["universal_review_scope_sha256"]
        elif review_scope_identity != evaluation["universal_review_scope_sha256"]:
            raise ValueError("paired universal review scope differs between candidates or seeds")
        matched = evaluation["matched"]
        if matched is not None:
            if role != "baseline" or matched["pointer"]["sha256"] != expected_matched_scope_sha256:
                raise ValueError("matched control differs from role or pre-inspection frozen SHA256")
            if matched["scope"]["decision_policy"]["sha256"] != sha(policy_path):
                raise ValueError("matched control scope changes frozen decision policy")
            if matched_scope_identity is None:
                matched_scope_identity = matched["pointer"]["sha256"]
            elif matched_scope_identity != matched["pointer"]["sha256"]:
                raise ValueError("matched control scope differs across generation seeds")
        if role == "baseline":
            mode = "explicit_matched48" if matched is not None else "original_universal96"
            if baseline_scope_mode is not None and baseline_scope_mode != mode:
                raise ValueError("baseline seeds cannot mix original96 and newly generated matched48 controls")
            baseline_scope_mode = mode
            count = matched["scope"]["expected_windows_per_seed"] if matched is not None else scope["baseline_windows_per_seed"]
            if len(evaluation["window_ids"]) != count:
                raise ValueError("universal C0 review must retain the full frozen baseline window scope")
        if evaluation["source_sha256"] != sha(source_manifest):
            raise ValueError("evaluation source differs from qualified comparison source")
        if reference_identity is None:
            reference_identity = evaluation["reference_identity"]
        elif reference_identity != evaluation["reference_identity"]:
            raise ValueError("paired reference version/bytes differ between candidates or seeds")
        if len(evaluation["metadata"]) != 1:
            raise ValueError("comparison CLI role requires singleton evaluation alias; do not guess multiple opaque identities")
        for original_alias, metadata in evaluation["metadata"].items():
            if runtime_identity is None:
                runtime_identity = metadata["runtime_identity_sha256"]
            elif runtime_identity != metadata["runtime_identity_sha256"]:
                raise ValueError("paired model/template/runtime identity changed")
            frozen_model = policy.get("baseline", {}).get("model_sha256")
            if frozen_model is not None and frozen_model != metadata["model_sha256"]:
                raise ValueError("generation model differs from frozen baseline model identity")
            card = card_by_recipe.get(metadata["recipe_id"])
            if role == "baseline":
                if matched is not None:
                    card = _card(matched["cards"][metadata["seed"]], source_manifest, policy_path, windows)
                    _card_generation(metadata, card, matched_control=True)
                    if card["window_ids"] != evaluation["window_ids"]:
                        raise ValueError("matched control generation does not match exact selected card scope")
                alias = baseline_alias
                declared = metadata["recipe_id"] == baseline_alias or (card is not None and
                    card["candidate_group"] == baseline_alias and card["representative_seed"] == metadata["seed"])
                settings = metadata["recipe_settings"]
                if (metadata["recipe"] != "c0" or not declared or settings.get("sampling") != "official"
                    or settings.get("cache_prompt") is not True or settings.get("n_predict") != 4096):
                    raise ValueError("explicit baseline root must use the declared C0 protocol")
            else:
                if card is None:
                    raise ValueError("candidate requires exact frozen card and explicit candidate_group")
                alias = card["candidate_group"]
                if alias == baseline_alias:
                    raise ValueError("candidate card cannot masquerade as baseline group")
                _card_generation(metadata, card)
            key = alias, metadata["seed"]
            if key in seen:
                raise ValueError("duplicate candidate generation seed; repeated evaluation is not a new seed")
            seen.add(key)
            if alias in aliases and aliases[alias]["recipe_identity_sha256"] != metadata["recipe_identity_sha256"]:
                raise ValueError("complete recipe changed across generation seeds")
            aliases[alias] = metadata
            if role == "candidate":
                ids = evaluation["window_ids"]
                if selected is not None and selected != ids:
                    raise ValueError("candidate roots do not share exact scoring window scope")
                selected = ids
                if card is not None:
                    if card["window_ids"] != ids or card["recipe"] != metadata["recipe"]:
                        raise ValueError("candidate evaluation does not match frozen card recipe/scope")
                    for option, value in card["options"].items():
                        if metadata["recipe_settings"].get(option) != value:
                            raise ValueError("candidate auxiliary options differ from frozen card")
            loaded.append((alias, original_alias, metadata["seed"], evaluation))
    if selected is None or baseline_alias not in aliases or len(aliases) < 2 or not selected <= set(windows):
        raise ValueError("comparison lacks baseline/candidate or valid selected source windows")
    splits = {windows[wid]["split"] for wid in selected}
    confirmation = splits == {"confirmation"}
    if "confirmation" in splits and not confirmation:
        raise ValueError("screening and confirmation cannot share a comparison")
    stage = "confirmation" if confirmation else "screening"
    if not splits <= {"screen-a", "screen-b", "confirmation"}:
        raise ValueError("unsupported comparison source split")
    if stage == "screening":
        bound_source = policy.get("freeze_provenance", {}).get("source_workload", {}).get("manifest_sha256")
        if bound_source != sha(source_manifest):
            raise ValueError("screening source differs from decision-policy qualified workload")
    else:
        if (len(selected) != endpoint.get("confirmation_windows")
            or any(windows[wid].get("selection_type", windows[wid].get("stratum")) != "representative" for wid in selected)):
            raise ValueError("confirmation must retain the frozen independent representative-window denominator")
        maximum = policy.get("confirmation_candidate_lock", {}).get("maximum_complete_candidates")
        if type(maximum) is not int or len(aliases)-1 > maximum:
            raise ValueError("confirmation candidate count exceeds the frozen lock")
    for alias in aliases:
        if alias != baseline_alias:
            if {card["representative_seed"] for card in card_groups[alias]} != set(seeds):
                raise ValueError("candidate group requires exact frozen cards for all expected generation seeds")
            if any(card["window_ids"] != selected for card in card_groups[alias]):
                raise ValueError("candidate cards do not share exact frozen scoring window scope")
    for card in cards:
        if card["stage"] != stage:
            raise ValueError("card stage differs from selected source metadata stage")
    expected, final = [], []
    missing_seeds = {alias: [value for value in seeds if (alias, value) not in seen] for alias in sorted(aliases)}
    for alias in sorted(aliases):
        for generation_seed in seeds:
            for wid in sorted(selected):
                source = windows[wid]
                expected.append({"candidate_alias": alias, "window_id": wid, "seed": generation_seed,
                    "work": source.get("work", source.get("work_id")), "work_id": source.get("work_id", source.get("work")),
                    "category": CATEGORY_MAP[source["category"]], "scene_id": source["scene_id"],
                    "scored_ids": source["scored_ids"]})
    for alias, original_alias, generation_seed, evaluation in loaded:
        if not selected <= evaluation["window_ids"]:
            raise ValueError("baseline lacks candidate exact scoring scope")
        if evaluation["matched"] is not None and selected != evaluation["window_ids"]:
            raise ValueError("matched48 comparison cannot project or expand its preregistered scope")
        for wid in sorted(selected):
            row = evaluation["expected"][original_alias, wid]
            source = windows[wid]
            if (row.get("work") != source.get("work", source.get("work_id"))
                or CATEGORY_MAP.get(row.get("category")) != CATEGORY_MAP.get(source.get("category"))
                or row.get("scored_ids") != source.get("scored_ids") or row.get("scene_id") != source.get("scene_id")):
                raise ValueError("expected evaluation/source scoring scope mismatch")
            value = evaluation["final"].get((original_alias, wid))
            if value is not None:
                # Drop nested original/primary/review prose immediately; final
                # accepted evidence is retained internally only for deduplication.
                final.append({"candidate_alias": alias, "window_id": wid, "seed": generation_seed,
                    "semantic": value.get("semantic"), "naturalness": value.get("naturalness"),
                    "status": value["status"], "errors": value.get("errors", []),
                    "reviewed": value.get("reviewed", False), "structural_status": value.get("structural_status")})
    multiplicity = policy.get("multiplicity", {})
    stats = build_statistics(expected, final, {"windows": [windows[wid] for wid in sorted(selected)]}, baseline_alias,
        seeds=seeds, bootstrap_iterations=multiplicity["bootstrap_iterations"],
        seed=multiplicity["bootstrap_seed"], confidence=multiplicity["family_confidence"],
        family_size=multiplicity["family_size"], combine_screening=splits == {"screen-a", "screen-b"})
    _series_sensitivity(stats)
    gates = {}
    for alias in sorted(aliases):
        records = [row for row in final if row["candidate_alias"] == alias]
        known = sum(row["semantic"] is not None for row in records)
        expected_count = len(selected) * len(seeds)
        gates[alias] = {"severe_state": "unknown" if known != expected_count else "known_findings_require_supported_candidate_specific_assessment",
                       "known_records": known, "expected_records": expected_count,
                       "missing_or_unscorable_records": expected_count-known,
                       "severe_confirmation_gate_passed": None, "delivery_confirmation_gate_passed": None}
    return {"schema_version": "hy30-flow-v2-comparison-v1", "stage": stage,
            "interpretation": "exploratory_screening" if stage == "screening" else "confirmation_descriptive_no_automatic_decision",
            "automatic_winner": None, "policy_gates_automatically_evaluated": False,
            "decision_policy_sha256": sha(policy_path), "source_manifest_sha256": sha(source_manifest),
            "universal_review_scope_sha256": review_scope_identity,
            "baseline_scope_mode": baseline_scope_mode, "matched_control_scope_sha256": matched_scope_identity,
            "reference_identity": reference_identity, "window_ids": sorted(selected),
            "expected_windows_per_candidate": len(selected), "expected_seeds": list(seeds),
            "missing_generation_seeds": missing_seeds, "coverage_and_gates": gates,
            "recipe_identities": {alias: {key: row[key] for key in ("recipe", "recipe_identity_sha256", "recipe_code_sha256")}
                                  for alias, row in sorted(aliases.items())},
            "generation_provenance": [{"candidate_group": alias, "evaluation_alias": original_alias,
                 "seed": generation_seed, "recipe_id": evaluation["metadata"][original_alias]["recipe_id"],
                 "original_generation": evaluation["metadata"][original_alias]["original_generation"],
                 "runtime_identity_sha256": evaluation["metadata"][original_alias]["runtime_identity_sha256"],
                 "session_sha256": evaluation["metadata"][original_alias]["session_sha256"],
                 "trial_lineage": evaluation["metadata"][original_alias]["trial_lineage"],
                 "cached_scoring_reprojection": evaluation["metadata"][original_alias]["derivation"] is not None,
                 "new_inference_calls": evaluation["metadata"][original_alias]["new_inference_calls"],
                 "new_generated_samples": evaluation["metadata"][original_alias]["new_generated_samples"],
                 **({"source_preparation": _auxiliary_provenance(evaluation["metadata"][original_alias]["source_preparation"])}
                    if evaluation["metadata"][original_alias]["source_preparation"] is not None else {})}
                 for alias, original_alias, generation_seed, evaluation in loaded],
            "cards": [{key: card[key] for key in ("path", "sha256", "candidate_group", "recipe_id", "representative_seed", "stage", "configuration_sha256")} for card in cards],
            "evaluation_provenance": [evaluation["provenance"] for _, evaluation in evaluations],
            "statistics": stats,
            "limitations_zh": ["筛选为探索性比较，独立确认需锁定候选后另行判断；本入口不自动宣布胜者。",
                "缺失seed、未执行窗口与终评缺分保留全部分母；严重风险未知不能当作通过。",
                "严重错误的候选特异新增根因须在评估侧独立处理，本程序不从文本相似度推断。",
                "无完成封存清单的暂定final不作为终评质量证据；原始生成与缓存重投影身份分别保留。",
                "全部预期窗口要求独立盲审；统一盲审的运输完成不代表终评分数全已知，旧选择性盲审仅保留为派生来源。",
                "匹配48窗分支保留新C0生成与旧96窗评审donor的独立来源；复用判断不增加seed或重复归属生成成本。",
                "配对区间仅覆盖完整配对子集，缺分0／4界不是置信区间；仅描述冻结抽样框与分配。"]}


def report(summary: dict[str, Any]) -> str:
    lines = ["# 第二轮流程配对统计", "", "阶段：" + ("探索筛选" if summary["stage"] == "screening" else "独立确认描述性统计"),
             f"每候选预期{summary['expected_windows_per_candidate']}窗口，{len(summary['expected_seeds'])}生成seed。未自动判定胜者。", "",
             "| 候选 | 已知语义记录／预期 | 严重风险状态 |", "| --- | --- | --- |"]
    for alias, gate in summary["coverage_and_gates"].items():
        label = "未知" if gate["severe_state"] == "unknown" else "已知发现，仍需候选特异风险审查"
        lines.append(f"| {alias} | {gate['known_records']}/{gate['expected_records']} | {label} |")
    def number(value: Any) -> str:
        return "未知" if value is None else f"{value:.4f}"
    for split, scope in summary["statistics"]["splits"].items():
        for stratum, layer in scope["strata"].items():
            for category, results in layer["categories"].items():
                lines += ["", f"## {split}／{stratum}／{category}", "",
                    "| 候选 | 完整配对窗口／预期 | 与C0语义差 | 全分母缺分界 | 预设同时区间 |",
                    "| --- | --- | --- | --- | --- |"]
                for pair in results["pairs"]:
                    if pair["left_alias"] != summary["statistics"]["baseline_alias"]:
                        continue
                    bounds, interval = pair["missing_0_4_difference_bounds"], pair["simultaneous_interval"]
                    lines.append(f"| {pair['right_alias']} | {pair['complete_paired_windows']}/{pair['expected_windows']} | "
                        f"{number(pair['semantic_difference'])} | [{number(bounds['lower'])}, {number(bounds['upper'])}] | "
                        f"[{number(interval['lower'])}, {number(interval['upper'])}] |")
    lines += ["", *summary["limitations_zh"], "", "完整分层均值、覆盖及逐作品／系列剔除敏感性见summary.json。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线核验并汇总第二轮流程比较；仅导出聚合结果")
    parser.add_argument("--baseline", action="append", type=Path, required=True)
    parser.add_argument("--candidate", action="append", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--card", action="append", type=Path, required=True,
                        help="各候选全部预期seed的冻结card；显式candidate_group将同配方各seed连接起来")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirmation-authority", type=Path,
                        help="独立确认整条冻结dispatch plan；3个per-seed多候选root须保留全部锁定条目")
    parser.add_argument("--confirmation-authority-sha256", help="外部登记的dispatch plan SHA256")
    args = parser.parse_args(argv)
    try:
        if bool(args.confirmation_authority) != bool(args.confirmation_authority_sha256):
            raise ValueError("confirmation authority path and externally registered SHA256 must be supplied together")
        authority = ({"path": str(args.confirmation_authority.resolve()), "sha256": args.confirmation_authority_sha256}
                     if args.confirmation_authority else None)
        summary = compare(args.baseline, args.candidate, args.source_manifest, args.policy,
                          card_paths=args.card, expected_policy_sha256=POLICY_SHA256,
                          expected_review_scope_sha256=UNIVERSAL_REVIEW_SHA256,
                          expected_matched_scope_sha256=MATCHED_SCOPE_SHA256,
                          confirmation_authority=authority)
        args.output.mkdir(parents=True, exist_ok=False)
        dump(args.output / "summary.json", summary)
        (args.output / "report.md").write_text(report(summary), encoding="utf-8")
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
