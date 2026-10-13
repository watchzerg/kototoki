"""Synthetic evaluation-root comparison tests; no model/judge/reference reads."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_eval.runner import NO_JUDGE_STATUSES, dump, dump_jsonl, load_jsonl, read_json, sha
from experiments.translation_flow.v2_compare import MATCHED_SCOPE, MATCHED_SCOPE_SHA256, RECIPE_CODE, UNIVERSAL_REVIEW, _matched_import_lineage, _review_coverage, compare, main
from experiments.translation_flow.v2_statistics import BASELINE, ESTIMATOR, SEEDS

# Exercise the real auxiliary worker, packing and projection metadata boundary.
import argparse
import shutil
from experiments.translation_eval import runner as e
from experiments.translation_flow import v2_compare as comparison, v2_prepare, v2_delivery, v2_evaluation
from experiments.translation_flow import test_v2_evaluation as source_fixtures
from experiments.translation_flow.v2_source_preparation import SESSION_SCHEMA, BACKGROUND_PROTOCOL, execute_plan
from experiments.translation_flow.v2_source_projection import SOURCE_CONTROL
from experiments.translation_flow.test_worker import FakeClient
from experiments.translation_flow.test_v2_worker import result
from tests import test_translation_flow_v2_source_preparation as auxiliary_fixtures


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".local/v2-comparison-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.source, self.policy = self.root / "source.json", self.root / "policy.json"
        self.recipe_source = self.root / "source" / RECIPE_CODE
        self.recipe_source.parent.mkdir(parents=True)
        self.recipe_source.write_bytes(b"# Synthetic frozen recipe implementation\n")
        self.references, self.freeze = self.root / "references.private", self.root / "freeze.private"
        # The comparison hashes these opaque reference files; it must not parse them.
        self.references.write_bytes(b"PRIVATE REFERENCE; deliberately not JSON")
        self.freeze.write_bytes(b"PRIVATE REFERENCE FREEZE; deliberately not JSON")
        self.windows = [{"id": f"w{index:03}", "scene_id": f"scene{index:03}", "work_id": "M01" if index % 2 else "W01",
            "work": "Movie title" if index % 2 else "Series title", "category": "animation_movie" if index % 2 else "anime_series",
            "split": "screen-a" if index < 48 else "screen-b", "selection_type": "risk" if index % 4 == 0 else "representative",
            "scored_ids": ["u1"], "series_cluster": "SAO" if index % 2 else None} for index in range(96)]
        dump(self.source, {"windows": self.windows})
        dump(self.policy, {"status": "frozen_before_candidate_quality", "baseline": {"alias": BASELINE},
            "primary_endpoint": {"generation_seeds": list(SEEDS), "estimator": ESTIMATOR},
            "freeze_provenance": {"source_workload": {"manifest_sha256": sha(self.source)}},
            "multiplicity": {"bootstrap_iterations": 50, "bootstrap_seed": 20261008, "family_confidence": .95, "family_size": 9}})
        self.scope = self.root / "universal-review.json"
        dump(self.scope, {"version": UNIVERSAL_REVIEW, "state": "frozen_before_candidate_quality",
            "selection": "all_expected_windows", "decision_policy": self.pointer(self.policy),
            "source_manifest": self.pointer(self.source), "reference_freeze": self.pointer(self.freeze),
            "generation_seeds": list(SEEDS), "baseline_windows_per_seed": 96,
            "candidate_windows": "all_card_selected_expected_windows",
            "primary_policy": "reuse_verified_accepted_without_repeat", "review_policy": "fresh_only_missing_blind_reviews",
            "no_judge_statuses": sorted(NO_JUDGE_STATUSES), "blind_review_prior_opinions_visible": False,
            "unknown_policy": "retain_null_and_full_expected_denominator",
            "adjudication_policy": "unchanged_bounded_dispute_resolution"})
        self.cards = [self.card(seed) for seed in SEEDS]
        self.baselines = [self.evaluation("baseline", seed, self.windows) for seed in SEEDS]
        self.candidates = [self.evaluation("candidate", seed, self.windows[:48]) for seed in SEEDS]

    def tearDown(self):
        self.temp.cleanup()

    def pointer(self, path):
        return {"path": str(path), "sha256": sha(path)}

    def card(self, seed, group="F1-b20"):
        path = self.root / f"{group}-{seed}-card.json"
        dump(path, {"schema": "hy30-flow-trial-card-v2", "candidate_group": group,
            "source": {"manifest": str(self.source), "manifest_sha256": sha(self.source)},
            "decision_policy": self.pointer(self.policy),
            "implementation_identity": [{"path": RECIPE_CODE, "sha256": sha(self.recipe_source)}],
            "prepare": {"recipe_id": f"{group}-seed{seed}", "recipe": "c0", "seed": seed,
                        "split": "screen-a", "stage": "screening", "target_size": 20}})
        return path

    def evaluation(self, role, seed, windows, *, final=True):
        root = self.root / f"{role}-{seed}"
        root.mkdir()
        recipe_id = BASELINE if role == "baseline" else f"F1-b20-seed{seed}"
        original = root / "original-run.json"
        dump(original, {"recipe": "c0", "settings": {"recipe": "c0", "label": recipe_id, "seed": seed,
             "sampling": "official", "cache_prompt": True, "n_predict": 4096, "max_attempts": 2},
             "code_sha256": {RECIPE_CODE: sha(self.recipe_source)},
             "runtime_identity": {"engine": {"model_sha256": "b" * 64, "context_size": 8192},
                                  "template_sha256": "c" * 64}})
        rows, finals = [], []
        for source in windows:
            row = {"candidate_alias": "c01", "window_id": source["id"], "work": source["work"],
                "category": "movie" if source["category"] == "animation_movie" else source["category"],
                "scene_id": source["scene_id"], "scored_ids": source["scored_ids"], "structural_status": "valid"}
            rows.append(row)
            finals.append(dict(row, semantic=2 if role == "baseline" else 3, naturalness=2, status="scored", errors=[], reviewed=True,
                               summary_zh="PRIVATE SEMANTIC SUMMARY", primary={"evidence": "PRIVATE NESTED"}))
        dump_jsonl(root / "expected.jsonl", rows)
        if final:
            dump_jsonl(root / "final.jsonl", finals)
        contract = {"window_ids": [source["id"] for source in windows], "source_manifest": self.pointer(self.source),
            "references": self.pointer(self.references), "reference_freeze": {**self.pointer(self.freeze),
                 "corpus_version": "fixture-v1", "state": "frozen_double_fresh_reference_review"},
            "candidate_artifacts": {"c01": {"seed": seed, "recipe_id": recipe_id,
                                             "original_generation_cost_identity": self.pointer(original)}}}
        dump(root / "run.json", {"lane": "P-flow", "profile": "sol-high-auto-v1", "split": "dev",
            "universal_review_scope": {**self.pointer(self.scope), "version": UNIVERSAL_REVIEW,
                 "state": "frozen_before_candidate_quality", "selection": "all_expected_windows"},
            "candidates": {"c01": {}}, "p_flow_contract": contract, "expected_sha256": sha(root / "expected.jsonl"),
            "references_sha256": sha(self.references), "corpus_manifest_sha256": sha(self.source)})
        if final:
            self.seal(root)
        return root

    def seal(self, root):
        run = read_json(root / "run.json")
        artifacts = run["p_flow_contract"]["candidate_artifacts"]
        expected = [json.loads(line) for line in (root / "expected.jsonl").read_text().splitlines()]
        finals = [json.loads(line) for line in (root / "final.jsonl").read_text().splitlines()]
        judgeable = sum(row["structural_status"] not in NO_JUDGE_STATUSES for row in expected)
        accepted = sum(row.get("reviewed") is True for row in finals)
        known = sum((row.get("semantic") is not None or row.get("naturalness") is not None)
                    and row.get("reviewed") is True and row["status"] != "delivery_zero" for row in finals)
        dump(root / "finalization-manifest.json", {"state": "required_fresh_judgments_completed",
            "matched_control_scope": run.get("matched_control_scope"),
            "matched_validation_provenance": run.get("matched_validation_provenance"),
            "matched_judgment_import": run.get("matched_judgment_import"),
            "universal_review_scope": run.get("universal_review_scope"), "judgment_import": run.get("judgment_import"),
            "universal_review_coverage": {"expected_records": len(expected), "selected_records": len(expected),
                  "judgeable_records": judgeable, "accepted_review_records": accepted,
                  "known_scored_reviewed_records": known, "complete": accepted == judgeable},
            "final": self.pointer(root / "final.jsonl"), "expected": self.pointer(root / "expected.jsonl"),
            "run": self.pointer(root / "run.json"), "reference_freeze": run["p_flow_contract"]["reference_freeze"],
            "source_manifest": run["p_flow_contract"]["source_manifest"],
            "candidate_identity": {alias: {key: value[key] for key in ("seed", "recipe_id", "original_generation_cost_identity")}
                                   for alias, value in artifacts.items()},
            "expected_records": len((root / "expected.jsonl").read_text().splitlines()),
            "files": [{"path": path.relative_to(root).as_posix(), "sha256": sha(path)}
                for path in sorted(root.rglob("*")) if path.is_file() and
                path.relative_to(root).as_posix() not in {"finalization-manifest.json", ".judge-scheduler.lock"}]})

    def build(self, baseline=None, candidates=None, cards=None):
        return compare(baseline or self.baselines, candidates or self.candidates, self.source, self.policy,
                       card_paths=self.cards if cards is None else cards, expected_policy_sha256=sha(self.policy),
                       expected_review_scope_sha256=sha(self.scope),
                       expected_matched_scope_sha256=sha(self.matched_scope) if hasattr(self, "matched_scope") else MATCHED_SCOPE_SHA256)

    def matched_controls(self):
        ids = [row["id"] for row in self.windows[:48]]
        qualification_path = self.root / "freeze-manifest.json"
        approval = {**self.pointer(self.freeze), "version": "fixture-v1",
                    "state": "frozen_double_fresh_reference_review", "inference_allowed": True}
        dump(qualification_path, {"state": "source_frozen_reference_qualified",
            "reference_qualification": approval, "original_source_freeze": self.pointer(self.source)})
        qualification = {"canonical_source_qualification_freeze": self.pointer(qualification_path),
            "evidence": [{"binding": "explicit_contract", "pointer": self.pointer(qualification_path)}],
            "accepted_reference_qualification": approval, "original_source_freeze": self.pointer(self.source),
            "state": "source_frozen_reference_qualified"}
        for donor in self.baselines:
            self.update_run(donor, lambda run: run["p_flow_contract"].update(
                source_inputs=self.pointer(self.source), source_qualification_freeze=self.pointer(qualification_path)))
        controls = {seed: self.card(seed, BASELINE) for seed in SEEDS}
        for path in controls.values():
            card = read_json(path)
            card["prepare"]["target_size"] = 5
            card["prepare"].update(context_before=1, context_after=1, token_target=None, common_context=False, offset=0,
                selected_scene_ids=[row["scene_id"] for row in self.windows[:48]])
            card["source"]["scenes_sha256"] = sha(self.source)
            card["source_estimate"] = {"batches": 48}
            dump(path, card)
        protocol_path = self.root / "matched-validation.json"
        dump(protocol_path, {"version": "matched-workload-validation-v1", "state": "frozen_before_any_candidate_quality_inspection",
            "timing_declaration": {"candidate_quality_results_inspected": False}, "unchanged_thresholds": True,
            "window_ids": ids, "generation_seeds": list(SEEDS), "source_manifest": self.pointer(self.source),
            "source_freeze": self.pointer(qualification_path), "decision_policy": self.pointer(self.policy),
            "seed_controls": [{"seed": seed, "old_original_run": read_json(old / "run.json")["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"]}
                              for seed, old in zip(SEEDS, self.baselines, strict=True)]})
        protocol_pointer = {**self.pointer(protocol_path), "version": "matched-workload-validation-v1",
                            "state": "frozen_before_any_candidate_quality_inspection"}
        queue_path = self.root / "matched-queue.json"
        dump(queue_path, {"validation_protocol": self.pointer(protocol_path),
            "jobs": [{"card": str(path), "card_sha256": sha(path)} for path in controls.values()]})
        self.matched_scope = self.root / "matched-scope.json"
        dump(self.matched_scope, {"version": MATCHED_SCOPE, "state": "frozen_before_candidate_quality_inspection",
            "selection": "explicit_matched_windows", "window_ids": ids, "expected_windows_per_seed": 48,
            "generation_seeds": list(SEEDS), "candidate_group": BASELINE,
            "universal_review_selection": "all_expected_judgeable48_windows_each_seed",
            "generation_attribution": "new_matched29_generation_identity_and_cost_preserved",
            "primary_policy_modified": False, "decision_thresholds_modified": False, "old96_roots_modified": False,
            "mixed96_single_generation_ledger_permitted": False, "timing_declaration": {"candidate_quality_results_inspected": False},
            "source_manifest": self.pointer(self.source), "source_freeze": self.pointer(qualification_path),
            "reference_freeze": self.pointer(self.freeze), "decision_policy": self.pointer(self.policy),
            "validation_protocol": self.pointer(protocol_path), "matched_execution_queue": self.pointer(queue_path),
            "universal_review_policy": self.pointer(self.scope)})
        scope_pointer = {**self.pointer(self.matched_scope), "version": MATCHED_SCOPE,
            "state": "frozen_before_candidate_quality_inspection", "selection": "explicit_matched_windows",
            "expected_windows_per_seed": 48}
        matched = []
        for seed, donor in zip(SEEDS, self.baselines, strict=True):
            root = self.evaluation("matched", seed, self.windows[:48])
            card = read_json(controls[seed])
            native = root / "execution/runtime-run/translation" / card["prepare"]["recipe_id"] / "run.json"
            native.parent.mkdir(parents=True)
            inputs = native.parent / "inputs.jsonl"
            inputs.write_bytes(b"Synthetic source-only model inputs; hash, never parse")
            batches = [{"id": row["scene_id"] + "-b0001"} for row in self.windows[:48]]
            packed_path = root / "prepared/packed-mapping.json"
            packed_path.parent.mkdir()
            dump(packed_path, {"packing": {key: card["prepare"][key] for key in (
                    "target_size", "context_before", "context_after", "token_target", "common_context", "offset")},
                "scene_ids": card["prepare"]["selected_scene_ids"], "source_manifest": self.pointer(self.source),
                "source_scenes": self.pointer(self.source), "batches": batches})
            original = read_json(root / "original-run.json")
            original["settings"]["label"] = card["prepare"]["recipe_id"]
            original["settings"].update(input_sha256=sha(inputs), packed_mapping_sha256=sha(packed_path))
            original["expected_window_ids"] = [row["id"] for row in batches]
            dump(native, original)
            saved = native.parent.parent / "source" / RECIPE_CODE
            saved.parent.mkdir(parents=True)
            saved.write_bytes(self.recipe_source.read_bytes())
            dump(root / "trial-start.json", {"card_path": str(controls[seed]), "card_sha256": sha(controls[seed]), "card": card})
            run = read_json(root / "run.json")
            run["p_flow_contract"].update(source_inputs=self.pointer(self.source),
                                        source_qualification_freeze=self.pointer(qualification_path))
            run["p_flow_contract"]["candidate_artifacts"]["c01"].update(recipe_id=card["prepare"]["recipe_id"],
                original_generation_cost_identity=self.pointer(native))
            run["candidates"]["c01"] = {"delivery_window_ids": ids}
            before = root / "matched-target-pre-import-run.json"
            dump(before, run)
            target_generation = {"c01": self.pointer(native)}
            donor_run = read_json(donor / "run.json")
            donor_generation = {"c01": donor_run["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"]}
            audit_path = root / "matched-complete-input-audit.json"
            audit = {"version": "matched-evaluation-input-audit-v1", "window_ids": ids, "expected_records": 48,
                "donor_run": self.pointer(donor / "run.json"), "donor_finalization": self.pointer(donor / "finalization-manifest.json"),
                "target_generation": target_generation, "donor_generation": donor_generation,
                "source_qualification_bindings": {"target": deepcopy(qualification), "donor": deepcopy(qualification)},
                "all_complete_inputs_identical": False, "complete_input_status": "complete",
                "records": [{"job_id": f"{phase}/c01/{wid}", "phase": phase, "candidate_alias": "c01", "window_id": wid,
                             "eligible": False, "decision": "fresh_required" if phase != "adjudication" else "no_donor_adjudication"}
                            for phase in ("primary", "review", "adjudication") for wid in ids]}
            dump(audit_path, audit)
            dump_jsonl(root / "jobs-adjudication.jsonl", [])
            proof_path = root / "matched-judgment-import.json"
            proof = {"version": "matched-judgment-import-v1", "target_root": str(root), "donor_root": str(donor),
                "target_pre_import_run": self.pointer(before), "donor_run": audit["donor_run"], "donor_finalization": audit["donor_finalization"],
                "donor_inventory_sha256": audit["donor_finalization"]["sha256"], "validation_protocol": protocol_pointer,
                "matched_control_scope": scope_pointer, "universal_review_scope": run["universal_review_scope"],
                "window_ids": ids, "expected_records": 48, "donor_expected_records": 96, "target_generation": target_generation,
                "donor_generation": donor_generation, "source_identity": {name: run["p_flow_contract"][name]
                    for name in ("source_manifest", "source_inputs", "references", "reference_freeze", "source_qualification_freeze")},
                "source_qualification_bindings": audit["source_qualification_bindings"], "complete_input_audit": self.pointer(audit_path),
                "ledger_path_relocation_allowlist": ["response", "accepted_raw_response", "accepted_canonical_snapshot"],
                "imported_jobs": [], "material_files": [], "imported_phase_counts": {"primary": 0, "review": 0, "adjudication": 0},
                "fresh_required_phase_counts": {"primary": 48, "review": 48, "adjudication": 0}, "adjudication_audits": [],
                "adjudication_material_complete": True, "new_network_calls": 0, "new_inference_calls": 0, "new_generated_samples": 0,
                "cost_attribution": "donor_accepted_judgment_once_target_generation_separate"}
            dump(proof_path, proof)
            run.update(matched_control_scope=scope_pointer, matched_validation_provenance=protocol_pointer,
                matched_judgment_import={"version": proof["version"], "donor_root": str(donor), "donor_run": proof["donor_run"],
                    "donor_finalization": proof["donor_finalization"], "manifest": self.pointer(proof_path)})
            dump(root / "run.json", run)
            self.seal(root)
            matched.append(root)
        return matched

    def update_run(self, root, fn):
        path = root / "run.json"
        value = read_json(path)
        fn(value)
        dump(path, value)
        if (root / "finalization-manifest.json").is_file():
            self.seal(root)

    def test_exact_card48_groups_opaque_aliases_and_filters_baseline96(self):
        result = self.build()
        self.assertEqual(result["expected_windows_per_candidate"], 48)
        self.assertEqual(set(result["coverage_and_gates"]), {BASELINE, "F1-b20"})
        self.assertEqual(result["interpretation"], "exploratory_screening")
        self.assertIsNone(result["automatic_winner"])
        self.assertEqual(result["statistics"]["candidate_aliases"], [BASELINE, "F1-b20"])
        movie = result["statistics"]["splits"]["screen-a"]["strata"]["representative"]["categories"]["movie"]
        self.assertEqual(movie["pairs"][0]["semantic_difference"], 1)
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE", serialized)
        self.assertNotIn("summary_zh", serialized)

    def test_confirmation_frame_requires_external_authority_before_loading_quality(self):
        for window in self.windows:
            window.update(split="confirmation", selection_type="representative")
        dump(self.source, {"windows": self.windows[:48]})
        with patch("experiments.translation_flow.v2_compare._evaluation") as quality:
            with self.assertRaisesRegex(ValueError, "separately pinned authority"):
                self.build()
            quality.assert_not_called()

    def test_screening_rejects_confirmation_authority_before_loading_quality(self):
        with patch("experiments.translation_flow.v2_compare._evaluation") as quality:
            with self.assertRaisesRegex(ValueError, "confirmation-only frame"):
                compare(self.baselines, self.candidates, self.source, self.policy,
                    card_paths=self.cards, expected_policy_sha256=sha(self.policy),
                    confirmation_authority=self.pointer(self.scope))
            quality.assert_not_called()

    def test_missing_seed_and_unrun_final_preserve_all_denominators(self):
        (self.candidates[1] / "final.jsonl").unlink()
        (self.candidates[1] / "finalization-manifest.json").unlink()
        result = self.build(candidates=self.candidates[:2])
        self.assertEqual(result["missing_generation_seeds"]["F1-b20"], [SEEDS[2]])
        gate = result["coverage_and_gates"]["F1-b20"]
        self.assertEqual(gate["expected_records"], 144)
        self.assertEqual(gate["known_records"], 48)
        self.assertEqual(gate["severe_state"], "unknown")
        self.assertIsNone(gate["severe_confirmation_gate_passed"])
        movie = result["statistics"]["splits"]["screen-a"]["strata"]["representative"]["categories"]["movie"]
        self.assertEqual(movie["candidates"]["F1-b20"]["semantic_lower"]["mean"], 1)
        self.assertAlmostEqual(movie["candidates"]["F1-b20"]["semantic_upper"]["mean"], 11/3)

    def test_null_judgment_is_unknown_and_delivery_zero_stays_zero(self):
        path = self.candidates[0] / "final.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0].update(status="review_failed", semantic=None, naturalness=None, provisional_primary={"semantic": 4})
        rows[1].update(status="delivery_zero", semantic=0, naturalness=None, structural_status="delivery_zero")
        # Structural final/expected disagreement is intentionally permitted: final
        # scoring identity is fixed, delivery status may be updated by evaluation.
        dump_jsonl(path, rows)
        self.seal(self.candidates[0])
        result = self.build()
        self.assertEqual(result["coverage_and_gates"]["F1-b20"]["known_records"], 143)
        self.assertEqual(result["coverage_and_gates"]["F1-b20"]["severe_state"], "unknown")

    def test_cross_seed_recipe_and_original_seed_mismatch_rejected(self):
        original = self.candidates[1] / "original-run.json"
        value = read_json(original)
        value["settings"]["seed"] = SEEDS[0]
        dump(original, value)
        self.update_run(self.candidates[1], lambda run: run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
            original_generation_cost_identity=self.pointer(original)))
        with self.assertRaisesRegex(ValueError, "generation seed differs"):
            self.build()
        value["settings"]["seed"] = SEEDS[1]
        value["settings"]["n_predict"] = 2048
        dump(original, value)
        self.update_run(self.candidates[1], lambda run: run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
            original_generation_cost_identity=self.pointer(original)))
        with self.assertRaisesRegex(ValueError, "recipe changed"):
            self.build()

    def test_reference_mismatch_and_tampered_expected_rejected(self):
        alternate = self.root / "alternate-freeze.private"
        alternate.write_bytes(b"different freeze identity")
        self.update_run(self.candidates[0], lambda run: run["p_flow_contract"].update(reference_freeze={**self.pointer(alternate),
            "corpus_version": "fixture-v1", "state": "frozen_double_fresh_reference_review"}))
        with self.assertRaisesRegex(ValueError, "source/reference identity mismatch"):
            self.build()
        self.update_run(self.candidates[0], lambda run: run["p_flow_contract"].update(reference_freeze={**self.pointer(self.freeze),
            "corpus_version": "fixture-v1", "state": "frozen_double_fresh_reference_review"}))
        with (self.candidates[0] / "expected.jsonl").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "expected ledger changed"):
            self.build()

    def test_card_scope_policy_seed_and_no_implicit_suffix_grouping(self):
        with self.assertRaisesRegex(ValueError, "exact frozen card"):
            self.build(cards=[])
        with self.assertRaisesRegex(ValueError, "all expected generation seeds"):
            self.build(candidates=self.candidates[:1], cards=self.cards[:1])
        value = read_json(self.cards[0])
        value.pop("candidate_group")
        dump(self.cards[0], value)
        with self.assertRaisesRegex(ValueError, "stable candidate_group"):
            self.build()

    def test_duplicate_seed_missing_scope_and_mixed_stage_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate candidate generation seed"):
            self.build(candidates=self.candidates + self.candidates[:1])
        self.update_run(self.baselines[0], lambda run: run["p_flow_contract"].update(window_ids=["w001"]))
        with self.assertRaisesRegex(ValueError, "exact window scope"):
            self.build()

    def test_cli_writes_only_aggregates_and_binds_production_sha(self):
        output = self.root / "summary"
        args = ["--source-manifest", str(self.source), "--policy", str(self.policy), "--output", str(output)]
        for path in self.baselines:
            args += ["--baseline", str(path)]
        for path in self.candidates:
            args += ["--candidate", str(path)]
        for path in self.cards:
            args += ["--card", str(path)]
        with patch("experiments.translation_flow.v2_compare.POLICY_SHA256", sha(self.policy)), \
             patch("experiments.translation_flow.v2_compare.UNIVERSAL_REVIEW_SHA256", sha(self.scope)):
            self.assertEqual(main(args), 0)
        self.assertEqual(set(path.name for path in output.iterdir()), {"summary.json", "report.md"})
        self.assertNotIn("PRIVATE", (output / "summary.json").read_text())
        with self.assertRaisesRegex(ValueError, "pre-candidate frozen SHA256"):
            compare(self.baselines, self.candidates, self.source, self.policy, card_paths=self.cards)

    def test_completion_seal_required_before_provisional_scores_can_enter_stats(self):
        (self.candidates[0] / "finalization-manifest.json").unlink()
        result = self.build()
        self.assertEqual(result["coverage_and_gates"]["F1-b20"]["known_records"], 96)
        self.assertFalse(result["evaluation_provenance"][3]["final_eligible_for_statistics"])
        self.assertEqual(result["coverage_and_gates"]["F1-b20"]["severe_state"], "unknown")
        self.seal(self.candidates[0])
        path = self.candidates[0] / "final.jsonl"
        with path.open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "provenance artifact bytes changed"):
            self.build()

    def test_exact_executed_trial_card_lineage_and_transparent_cached_reprojection(self):
        root = self.candidates[0]
        original = root / "original-run.json"
        trial = self.root / "runtime-trial"
        native = trial / "execution/runtime-run/translation/F1-b20-seed20261008/run.json"
        native.parent.mkdir(parents=True)
        native.write_bytes(original.read_bytes())
        copied_recipe = native.parent.parent / "source" / RECIPE_CODE
        copied_recipe.parent.mkdir(parents=True)
        copied_recipe.write_bytes(self.recipe_source.read_bytes())
        dump(trial / "trial-start.json", {"schema": "hy30-flow-trial-v2", "card_path": str(self.cards[0]),
            "card_sha256": sha(self.cards[0]), "card": read_json(self.cards[0])})
        self.update_run(root, lambda run: run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
            original_generation_cost_identity=self.pointer(native)))
        result = self.build()
        evidence = next(row for row in result["generation_provenance"] if row["candidate_group"] == "F1-b20" and row["seed"] == SEEDS[0])
        self.assertEqual(evidence["trial_lineage"]["card_sha256"], sha(self.cards[0]))
        different_card = self.root / "qualification-card.json"
        qualification = deepcopy(read_json(self.cards[0]))
        qualification["prepare"]["stage"] = "qualification"
        dump(different_card, qualification)
        dump(trial / "trial-start.json", {"schema": "hy30-flow-trial-v2", "card_path": str(different_card),
            "card_sha256": sha(different_card), "card": qualification})
        with self.assertRaisesRegex(ValueError, "exact per-seed executed trial card"):
            self.build()
        self.update_run(root, lambda run: run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
            derivation={"original_run": self.pointer(native)}, new_inference_calls=0, new_generated_samples=0))
        result = self.build()
        evidence = next(row for row in result["generation_provenance"] if row["candidate_group"] == "F1-b20" and row["seed"] == SEEDS[0])
        self.assertTrue(evidence["cached_scoring_reprojection"])
        self.assertEqual(evidence["new_inference_calls"], 0)

    def test_declared_used_code_enforced_while_unused_snapshot_changes_allowed(self):
        original = self.candidates[1] / "original-run.json"
        value = read_json(original)
        value["code_sha256"]["experiments/translation_flow/unused_new_module.py"] = "d" * 64
        dump(original, value)
        self.update_run(self.candidates[1], lambda run: run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
            original_generation_cost_identity=self.pointer(original)))
        self.build()
        value["code_sha256"][RECIPE_CODE] = "f" * 64
        dump(original, value)
        self.update_run(self.candidates[1], lambda run: run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
            original_generation_cost_identity=self.pointer(original)))
        with self.assertRaisesRegex(ValueError, "declared used implementation differs"):
            self.build()

    def test_changed_model_or_template_cannot_be_paired(self):
        original = self.candidates[0] / "original-run.json"
        value = read_json(original)
        value["runtime_identity"]["template_sha256"] = "e" * 64
        dump(original, value)
        self.update_run(self.candidates[0], lambda run: run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
            original_generation_cost_identity=self.pointer(original)))
        with self.assertRaisesRegex(ValueError, "model/template/runtime identity changed"):
            self.build()

    def test_selective_roots_and_differing_universal_scopes_are_rejected(self):
        self.update_run(self.baselines[0], lambda run: run.pop("universal_review_scope"))
        with self.assertRaisesRegex(ValueError, "selective review roots are ineligible"):
            self.build()
        scope_pointer = {**self.pointer(self.scope), "version": UNIVERSAL_REVIEW,
            "state": "frozen_before_candidate_quality", "selection": "all_expected_windows"}
        self.update_run(self.baselines[0], lambda run: run.update(universal_review_scope=scope_pointer))
        alternate = self.root / "alternate-scope.json"
        value = read_json(self.scope)
        value["audit_note"] = "Different preregistration identity"
        dump(alternate, value)
        self.update_run(self.candidates[0], lambda run: run.update(universal_review_scope={
            **scope_pointer, **self.pointer(alternate)}))
        with self.assertRaisesRegex(ValueError, "review scope differs from pre-candidate frozen"):
            self.build()

    def test_unreviewed_known_final_and_bad_review_coverage_rejected(self):
        path = self.candidates[0] / "final.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["reviewed"] = False
        dump_jsonl(path, rows)
        self.seal(self.candidates[0])
        with self.assertRaisesRegex(ValueError, "without independent review"):
            self.build()
        rows[0].update(semantic=None, naturalness=None, status="review_failed")
        dump_jsonl(path, rows)
        self.seal(self.candidates[0])
        result = self.build()
        coverage = result["evaluation_provenance"][3]["universal_review_coverage"]
        self.assertFalse(coverage["transport_complete"])
        self.assertEqual(result["coverage_and_gates"]["F1-b20"]["known_records"], 143)
        seal = read_json(self.candidates[0] / "finalization-manifest.json")
        seal["universal_review_coverage"]["complete"] = True
        dump(self.candidates[0] / "finalization-manifest.json", seal)
        with self.assertRaisesRegex(ValueError, "coverage seal is inconsistent"):
            self.build()

    def test_derivative_import_binds_old_sealed_donor_without_reading_donor_semantics(self):
        root = self.baselines[0]
        donor = self.root / "immutable-selective-donor"
        donor.mkdir()
        for name in ("run.json", "expected.jsonl"):
            (donor / name).write_bytes((root / name).read_bytes())
        # A malformed JSON ledger proves donor final is hashed, never parsed.
        (donor / "final.jsonl").write_bytes(b"PRIVATE DONOR FINAL; NOT JSON")
        donor_run = read_json(donor / "run.json")
        donor_run.pop("universal_review_scope")
        dump(donor / "run.json", donor_run)
        self.seal_donor = {"state": "required_fresh_judgments_completed",
            "run": self.pointer(donor / "run.json"), "expected": self.pointer(donor / "expected.jsonl"),
            "final": self.pointer(donor / "final.jsonl"),
            "source_manifest": self.pointer(self.source), "reference_freeze": self.pointer(self.freeze),
            "candidate_identity": read_json(root / "finalization-manifest.json")["candidate_identity"]}
        dump(donor / "finalization-manifest.json", self.seal_donor)
        manifest_path = root / "universal-judgment-import.json"
        imported = {"donor_root": str(donor), "donor_run": self.pointer(donor / "run.json"),
            "donor_finalization": self.pointer(donor / "finalization-manifest.json")}
        manifest = {"version": "universal-judgment-import-v1", **imported, "target_root": str(root),
            "universal_review_scope": read_json(root / "run.json")["universal_review_scope"],
            "imported_phase_counts": {"primary": 0, "review": 0, "adjudication": 0},
            "imported_jobs": [], "frozen_prepared_files": [], "new_network_calls": 0,
            "donor_inventory_sha256": imported["donor_finalization"]["sha256"],
            "new_generated_samples": 0, "new_inference_calls": 0,
            "cost_attribution": "original_accepted_judgment_once"}
        dump(manifest_path, manifest)
        imported["manifest"] = self.pointer(manifest_path)
        self.update_run(root, lambda run: run.update(judgment_import=imported))
        result = self.build()
        provenance = result["evaluation_provenance"][0]["judgment_import"]
        self.assertEqual(provenance["new_inference_calls"], 0)
        self.assertNotIn("PRIVATE", json.dumps(result))
        donor_run["p_flow_contract"]["candidate_artifacts"]["c01"]["seed"] = SEEDS[1]
        dump(donor / "run.json", donor_run)
        self.seal_donor["run"] = self.pointer(donor / "run.json")
        dump(donor / "finalization-manifest.json", self.seal_donor)
        imported.update(donor_run=self.pointer(donor / "run.json"),
                        donor_finalization=self.pointer(donor / "finalization-manifest.json"))
        manifest.update({key: imported[key] for key in ("donor_run", "donor_finalization")})
        manifest["donor_inventory_sha256"] = imported["donor_finalization"]["sha256"]
        dump(manifest_path, manifest)
        imported["manifest"] = self.pointer(manifest_path)
        self.update_run(root, lambda run: run.update(judgment_import=imported))
        with self.assertRaisesRegex(ValueError, "changes original generation identity"):
            self.build()

    def test_universal_seal_exact_inventory_rejects_extra_or_duplicate_files(self):
        root = self.candidates[0]
        (root / "post-seal-file.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "exact root files"):
            self.build()
        self.seal(root)
        self.build()
        (root / ".judge-scheduler.lock").write_text("synthetic lock")
        self.build()
        path = root / "finalization-manifest.json"
        value = read_json(path)
        value["files"].append(value["files"][0])
        dump(path, value)
        with self.assertRaisesRegex(ValueError, "duplicate or noncanonical"):
            self.build()

    def test_explicit_matched48_keeps_new_generation_and_old96_judgment_lineage(self):
        controls = self.matched_controls()
        result = self.build(baseline=controls)
        self.assertEqual(result["baseline_scope_mode"], "explicit_matched48")
        self.assertEqual(result["matched_control_scope_sha256"], sha(self.matched_scope))
        self.assertEqual(result["expected_seeds"], list(SEEDS))
        self.assertEqual(result["coverage_and_gates"][BASELINE]["expected_records"], 144)
        for record in result["evaluation_provenance"][:3]:
            proof = record["matched_judgment_import"]
            self.assertEqual(proof["target_expected_records"], 48)
            self.assertEqual(proof["donor_expected_records"], 96)
            self.assertNotEqual(proof["target_generation"], proof["donor_generation"])
            self.assertEqual(proof["fresh_required_phase_counts"]["review"], 48)
        self.assertNotIn("PRIVATE", json.dumps(result))
        original = self.build()
        self.assertEqual(original["baseline_scope_mode"], "original_universal96")

    def test_matched_controls_cannot_mix_with_original_seeds_or_fake_old_generation(self):
        controls = self.matched_controls()
        with self.assertRaisesRegex(ValueError, "cannot mix original96"):
            self.build(baseline=controls[:2]+self.baselines[2:])
        root = controls[0]
        proof_path = root / "matched-judgment-import.json"
        proof = read_json(proof_path)
        proof["target_generation"] = proof["donor_generation"]
        dump(proof_path, proof)
        self.update_run(root, lambda run: run["matched_judgment_import"].update(manifest=self.pointer(proof_path)))
        with self.assertRaisesRegex(ValueError, "generation identity differs"):
            self.build(baseline=controls)

    def test_matched_scope_is_explicit_relation_not_equal_hash_or_changed_threshold(self):
        controls = self.matched_controls()
        root = controls[0]
        value = read_json(self.matched_scope)
        value["decision_thresholds_modified"] = True
        dump(self.matched_scope, value)
        self.update_run(root, lambda run: run["matched_control_scope"].update(self.pointer(self.matched_scope)))
        with self.assertRaisesRegex(ValueError, "unchanged policy"):
            self.build(baseline=controls)

    def test_matched_adjudication_pending_is_historical_but_final_material_is_required(self):
        controls = self.matched_controls()
        root = controls[0]
        audit_path = root / "matched-complete-input-audit.json"
        audit = read_json(audit_path)
        audit.update(complete_input_status="incomplete_adjudication_material", all_complete_inputs_identical=None)
        audit["records"][-1]["decision"] = "pending_target_dispute"
        dump(audit_path, audit)
        proof_path = root / "matched-judgment-import.json"
        proof = read_json(proof_path)
        proof["complete_input_audit"] = self.pointer(audit_path)
        dump(proof_path, proof)
        self.update_run(root, lambda run: run["matched_judgment_import"].update(manifest=self.pointer(proof_path)))
        result = self.build(baseline=controls)
        self.assertIsNone(result["evaluation_provenance"][0]["matched_judgment_import"]["initial_all_complete_inputs_identical"])
        proof["adjudication_material_complete"] = False
        dump(proof_path, proof)
        self.update_run(root, lambda run: run["matched_judgment_import"].update(manifest=self.pointer(proof_path)))
        with self.assertRaisesRegex(ValueError, "actual adjudication material audit"):
            self.build(baseline=controls)

    def test_matched_control_exact_executed_card_identity_required(self):
        controls = self.matched_controls()
        trial_start = controls[0] / "trial-start.json"
        value = read_json(trial_start)
        value["card_path"] = str(self.cards[0])
        value["card_sha256"] = sha(self.cards[0])
        dump(trial_start, value)
        self.seal(controls[0])
        with self.assertRaisesRegex(ValueError, "exact per-seed executed trial card"):
            self.build(baseline=controls)

    def test_matched_judgment_reuse_requires_every_frozen_complete_material_component(self):
        controls = self.matched_controls()
        root, donor = controls[0], self.baselines[0]
        job_id = "primary/c01/w000"
        audit_path, proof_path = root / "matched-complete-input-audit.json", root / "matched-judgment-import.json"
        audit, proof = read_json(audit_path), read_json(proof_path)
        decision = next(row for row in audit["records"] if row["job_id"] == job_id)
        material = {}
        files = []
        names = ("packet_bytes", "prompt_bytes", "rendered_prompt", "schema_bytes", "settings_bytes", "task_bytes", "transport_contract")
        for name in names:
            path = root / "matched-evaluation-material" / job_id / (name + ".bin")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Synthetic frozen component")
            material[name + "_sha256"] = sha(path)
            files.append({"path": path.relative_to(root).as_posix(), "sha256": sha(path)})
        material["fingerprint"] = material["task_bytes_sha256"]
        material["dispute_bytes_sha256"] = None
        decision.update(eligible=True, decision="eligible", target_material=material, donor_material=deepcopy(material),
            equal_components={name: True for name in (*names, "fingerprint", "dispute_bytes", "accepted_prompt_file_bytes")})
        donor_ledger = donor / "accepted-primary-proof.json"
        donor_ledger.write_bytes(b"Synthetic accepted ledger metadata")
        self.seal(donor)
        copied, new = root / "original-primary-proof.json", root / "new-primary-proof.json"
        copied.write_bytes(donor_ledger.read_bytes())
        new.write_bytes(b"Synthetic relocated ledger metadata")
        audit["donor_finalization"] = self.pointer(donor / "finalization-manifest.json")
        dump(audit_path, audit)
        proof.update(complete_input_audit=self.pointer(audit_path), donor_finalization=audit["donor_finalization"],
            donor_inventory_sha256=audit["donor_finalization"]["sha256"], material_files=files,
            imported_phase_counts={"primary": 1, "review": 0, "adjudication": 0},
            fresh_required_phase_counts={"primary": 47, "review": 48, "adjudication": 0},
            imported_jobs=[{"job_id": job_id, "phase": "primary", "candidate_alias": "c01", "window_id": "w000",
                "fingerprint": material["fingerprint"], "donor_ledger": self.pointer(donor_ledger),
                "original_ledger_copy": self.pointer(copied), "new_ledger": self.pointer(new),
                "accepted_raw_response_sha256": "a"*64, "response_sha256": "b"*64,
                "accepted_canonical_snapshot_sha256": "b"*64, "files": []}])
        dump(proof_path, proof)
        self.update_run(root, lambda run: run["matched_judgment_import"].update(
            donor_finalization=proof["donor_finalization"], manifest=self.pointer(proof_path)))
        result = self.build(baseline=controls)
        self.assertEqual(result["evaluation_provenance"][0]["matched_judgment_import"]["imported_phase_counts"]["primary"], 1)
        decision["equal_components"]["schema_bytes"] = False
        dump(audit_path, audit)
        proof["complete_input_audit"] = self.pointer(audit_path)
        dump(proof_path, proof)
        self.update_run(root, lambda run: run["matched_judgment_import"].update(manifest=self.pointer(proof_path)))
        with self.assertRaisesRegex(ValueError, "exact complete-input equality"):
            self.build(baseline=controls)

    def test_matched_control_native_input_and_packing_bytes_remain_bound(self):
        controls = self.matched_controls()
        root = controls[0]
        original = read_json(root / "run.json")["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"]
        inputs = Path(original["path"]).parent / "inputs.jsonl"
        previous = inputs.read_bytes()
        inputs.write_bytes(previous+b"changed")
        self.seal(root)
        with self.assertRaisesRegex(ValueError, "provenance artifact bytes changed"):
            self.build(baseline=controls)
        inputs.write_bytes(previous)
        packed_path = root / "prepared/packed-mapping.json"
        packed_path.write_bytes(packed_path.read_bytes()+b" ")
        self.seal(root)
        with self.assertRaisesRegex(ValueError, "packing bytes changed"):
            self.build(baseline=controls)


class NativeMatchedAPIIntegrationTests(unittest.TestCase):
    """Exercise production preparation/import with tiny synthetic fake judges."""

    def setUp(self):
        from experiments.translation_flow.test_v2_matched_evaluation import MatchedEvaluationTests
        self.fixture = MatchedEvaluationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def complete_donor(self, *, legacy=False, disagreement=False):
        fixture = self.fixture
        if legacy:
            fixture.legacy_qualification_metadata()
        fixture.review_score = 3 if disagreement else 4
        fixture.complete_donor()
        # The native module fixture uses a minimal transport seal. Add the
        # comparator's metadata fields without changing any frozen donor files.
        seal = read_json(fixture.donor / "finalization-manifest.json")
        run = read_json(fixture.donor / "run.json")
        seal.update(universal_review_scope=run["universal_review_scope"],
                    **{name: run["p_flow_contract"][name] for name in ("source_manifest", "reference_freeze")})
        dump(fixture.donor / "finalization-manifest.json", seal)

    def validate_native_lineage(self):
        fixture = self.fixture
        run = read_json(fixture.target / "run.json")
        matched = {"pointer": run["matched_control_scope"], "scope": read_json(fixture.scope_path),
                   "protocol": read_json(fixture.protocol_path)}
        wanted = {(row["candidate_alias"], row["window_id"])
                  for row in load_jsonl(fixture.target / "expected.jsonl")}
        seal = {name: run[name] for name in ("matched_control_scope", "matched_judgment_import", "matched_validation_provenance")}
        return _matched_import_lineage(run, fixture.target, run["p_flow_contract"], seal, matched, wanted)

    def rewrite_native_proof(self, change):
        fixture = self.fixture
        path = fixture.target / "matched-judgment-import.json"
        proof = read_json(path)
        change(proof)
        dump(path, proof)
        run = read_json(fixture.target / "run.json")
        run["matched_judgment_import"]["manifest"] = {"path": str(path.resolve()), "sha256": sha(path)}
        dump(fixture.target / "run.json", run)

    def test_native_legacy_source_binding_pending_audit_and_fresh_resumed_adjudication(self):
        from experiments.translation_eval import runner as evaluation
        from experiments.translation_flow import v2_matched_evaluation as matched
        fixture = self.fixture
        self.complete_donor(legacy=True, disagreement=True)
        fixture.prepare_target()
        initial = fixture.import_target()
        self.assertIn("source_inputs", initial["source_identity"])
        initial_audit = read_json(Path(initial["complete_input_audit"]["path"]))
        self.assertIsNone(initial_audit["all_complete_inputs_identical"])
        initial_bytes = Path(initial["complete_input_audit"]["path"]).read_bytes()
        evaluation.finalize(fixture.target)
        fixture.execute(fixture.target, "jobs-adjudication.jsonl")
        completed = matched.import_adjudication(fixture.target, fixture.donor)
        evaluation.finalize(fixture.target)
        self.assertEqual(Path(initial["complete_input_audit"]["path"]).read_bytes(), initial_bytes)
        self.assertEqual({row["decision"] for row in completed["adjudication_audits"]}, {"target_already_started"})
        result = self.validate_native_lineage()
        self.assertEqual(result["target_expected_records"], 2)
        self.assertEqual(result["donor_expected_records"], 3)
        self.assertEqual(result["imported_phase_counts"], {"primary": 2, "review": 2, "adjudication": 0})
        self.assertEqual(result["fresh_required_phase_counts"]["adjudication"], 2)
        self.assertIsNone(result["initial_all_complete_inputs_identical"])
        self.assertNotEqual(result["target_generation"], result["donor_generation"])
        self.rewrite_native_proof(lambda proof: proof["fresh_required_phase_counts"].update(adjudication=0))
        with self.assertRaisesRegex(ValueError, "adjudication imported/fresh denominator"):
            self.validate_native_lineage()

    def test_native_changed_packet_is_fresh_and_forged_reuse_is_rejected(self):
        from experiments.translation_eval import runner as evaluation
        from experiments.translation_flow import v2_matched_evaluation as matched
        fixture = self.fixture
        self.complete_donor()
        fixture.prepare_target(changed=True)
        proof = fixture.import_target()
        audit = read_json(Path(proof["complete_input_audit"]["path"]))
        changed = [row for row in audit["records"] if row["phase"] == "primary" and row["decision"] == "fresh_required"]
        self.assertTrue(changed)
        self.assertFalse(audit["all_primary_review_inputs_identical"])
        self.assertNotIn(changed[0]["job_id"], {row["job_id"] for row in proof["imported_jobs"]})
        fixture.execute(fixture.target, "jobs.jsonl")
        evaluation.finalize(fixture.target)
        fixture.execute(fixture.target, "jobs-review.jsonl")
        evaluation.finalize(fixture.target)
        matched.import_adjudication(fixture.target, fixture.donor)
        evaluation.finalize(fixture.target)
        self.validate_native_lineage()
        row = changed[0]
        self.rewrite_native_proof(lambda manifest: manifest["imported_jobs"].append({
            "job_id": row["job_id"], "phase": row["phase"], "candidate_alias": row["candidate_alias"],
            "window_id": row["window_id"]}))
        with self.assertRaisesRegex(ValueError, "exact complete-input equality"):
            self.validate_native_lineage()
        scope = read_json(fixture.scope_path)
        scope["window_ids"] = scope["window_ids"][:1]
        dump(fixture.scope_path, scope)
        with self.assertRaisesRegex(ValueError, "frozen explicit scope"):
            matched.scope_metadata(fixture.scope_path, fixture.protocol_path)


class NativeConfirmationComparisonTests(unittest.TestCase):
    """Use real lock, dispatch, preparation and finalization with fake inference."""

    def setUp(self):
        from experiments.translation_flow.test_v2_confirmation_evaluation import ConfirmationEvaluationTests
        self.fixture = ConfirmationEvaluationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def prepare(self, fail_at=None):
        self.fixture.create_queue(fail_at=fail_at)
        roots = []
        for seed in SEEDS:
            root = self.fixture.prepare_seed(seed)
            mirrors = self.fixture.finish(root)
            self.seal(root, mirrors)
            roots.append(root)
        return roots

    def seal(self, root, mirrors):
        run = read_json(root / "run.json")
        pointer = lambda path: {"path": str(path.resolve()), "sha256": sha(path)}
        proof = read_json(Path(run["confirmation_generation_evidence"]["path"]))
        seed = run["confirmation_generation_seed"]
        identities = {slot["candidate_alias"]: {"seed": seed,
            "recipe_id": read_json(Path(slot["card"]["path"]))["prepare"]["recipe_id"],
            "original_generation_cost_identity": slot["original_run"],
            "original_trial_attempt_identity": slot.get("trial_completion", slot.get("native_trial")),
            "generation_attempt_status": slot["status"], "native_complete": slot["native_complete"]}
            for slot in proof["generations"] if slot["seed"] == seed}
        dump(root / "finalization-manifest.json", {"state": "required_fresh_judgments_completed", **mirrors,
            "candidate_identity": identities,
            "run": pointer(root / "run.json"), "expected": pointer(root / "expected.jsonl"),
            "final": pointer(root / "final.jsonl"), "expected_records": len(load_jsonl(root / "expected.jsonl")),
            "source_manifest": run["p_flow_contract"]["source_manifest"],
            "reference_freeze": run["p_flow_contract"]["reference_freeze"],
            "files": [{"path": path.relative_to(root).as_posix(), "sha256": sha(path)}
                for path in sorted(root.rglob("*")) if path.is_file()
                and path.name not in {"finalization-manifest.json", ".judge-scheduler.lock"}]})

    def compare(self, roots, *, authority=None, cards=None):
        fixture = self.fixture
        lock = read_json(Path(fixture.lock["path"]))
        locked_cards = [Path(item["card"]["path"]) for group in [lock["baseline"], *lock["candidates"]]
                        for item in group["cards"]]
        return compare(roots, roots, fixture.source.manifest_path, fixture.lock_fixture.policy_path,
            card_paths=locked_cards if cards is None else cards,
            expected_policy_sha256=fixture.pins["expected_policy_sha256"],
            confirmation_authority=fixture.plan if authority is None else authority)

    def test_native_confirmation_all_locked_groups_fresh_lineage_and_review(self):
        roots = self.prepare()
        result = self.compare(roots)
        self.assertEqual(result["baseline_scope_mode"], "fresh_confirmation48")
        self.assertIsNone(result["universal_review_scope_sha256"])
        self.assertIsNone(result["matched_control_scope_sha256"])
        self.assertIsNone(result["automatic_winner"])
        self.assertEqual(result["expected_windows_per_candidate"], 48)
        self.assertTrue(all(gate["known_records"] == 144 for gate in result["coverage_and_gates"].values()))
        self.assertEqual(len(result["generation_provenance"]), 6)
        self.assertTrue(all(row["native_complete"] for row in result["generation_provenance"]))
        self.assertNotIn("Synthetic native response", json.dumps(result))
        self.assertNotIn("summary_zh", json.dumps(result))
        with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
            self.compare(roots, authority={**self.fixture.plan, "sha256": "f" * 64})
        with self.assertRaisesRegex(ValueError, "every exact locked"):
            self.compare(roots, cards=[])
        with self.assertRaisesRegex(ValueError, "exactly three"):
            self.compare(roots[:2])
        seal_path = roots[1] / "finalization-manifest.json"
        original_seal = seal_path.read_bytes()
        seal_path.unlink()
        provisional = self.compare(roots)
        self.assertTrue(all(gate["known_records"] == 96 for gate in provisional["coverage_and_gates"].values()))
        self.assertTrue(all(gate["expected_records"] == 144 for gate in provisional["coverage_and_gates"].values()))
        seal_path.write_bytes(original_seal)
        native = read_json(Path(result["evaluation_provenance"][0]["confirmation_generation_evidence"]["path"]))
        response_path = Path(next(row["first_completion_response"]["path"] for row in native["generations"] if row["native_complete"]))
        response_bytes = response_path.read_bytes()
        response = read_json(response_path)
        response["timings"]["cache_n"] = 1
        dump(response_path, response)
        with self.assertRaises(ValueError):
            self.compare(roots)
        response_path.write_bytes(response_bytes)
        identity_seal = roots[0] / "finalization-manifest.json"
        identity_bytes = identity_seal.read_bytes()
        invalid = read_json(identity_seal)
        invalid["candidate_identity"][BASELINE]["original_generation_cost_identity"] = None
        dump(identity_seal, invalid)
        with self.assertRaisesRegex(ValueError, "original generation or attempted-slot identity"):
            self.compare(roots)
        identity_seal.write_bytes(identity_bytes)
        final_path = roots[0] / "final.jsonl"
        final_bytes = final_path.read_bytes()
        conflicting = load_jsonl(final_path)
        conflicting[0]["seed"] = SEEDS[-1]
        dump_jsonl(final_path, conflicting)
        mirrors = read_json(identity_seal)
        self.seal(roots[0], {key: mirrors[key] for key in ("fresh_confirmation_scope", "confirmation_authority",
            "confirmation_generation_receipt", "confirmation_generation_evidence", "confirmation_review_coverage")})
        with self.assertRaisesRegex(ValueError, "final/expected scoring identity"):
            self.compare(roots)
        final_path.write_bytes(final_bytes)
        identity_seal.write_bytes(identity_bytes)
        run = read_json(roots[0] / "run.json")
        run["judgment_import"] = None
        dump(roots[0] / "run.json", run)
        with self.assertRaisesRegex(ValueError, "forbids screening"):
            self.compare(roots)

    def test_native_terminal_failed_queue_preserves_unknowns_and_no_fake_generation(self):
        roots = self.prepare(fail_at=4)
        result = self.compare(roots)
        candidate = result["coverage_and_gates"]["candidate-b10"]
        self.assertEqual(candidate["expected_records"], 144)
        self.assertEqual(candidate["known_records"], 0)
        self.assertIsNone(candidate["severe_confirmation_gate_passed"])
        self.assertEqual(result["missing_generation_seeds"]["candidate-b10"], list(SEEDS))
        failed = [row for row in result["generation_provenance"] if row["candidate_alias"] == "candidate-b10"]
        self.assertEqual({row["status"] for row in failed}, {"failed", "not_run"})
        self.assertTrue(all(row["original_run"] is None for row in failed))
        for layer in result["statistics"]["splits"]["confirmation"]["strata"]["representative"]["categories"].values():
            for pair in layer["pairs"]:
                self.assertEqual(pair["complete_paired_windows"], 0)
                self.assertIsNone(pair["semantic_difference"])
                self.assertLess(pair["missing_0_4_difference_bounds"]["lower"], pair["missing_0_4_difference_bounds"]["upper"])
        # A score cannot be supplied for a slot without native generation proof.
        rows = load_jsonl(roots[0] / "final.jsonl")
        for row in rows:
            if row["candidate_alias"] == "candidate-b10":
                row.update(semantic=4, naturalness=2, reviewed=True)
        dump_jsonl(roots[0] / "final.jsonl", rows)
        seal = read_json(roots[0] / "finalization-manifest.json")
        self.seal(roots[0], {key: seal[key] for key in ("fresh_confirmation_scope", "confirmation_authority",
            "confirmation_generation_receipt", "confirmation_generation_evidence", "confirmation_review_coverage")})
        with self.assertRaises(ValueError):
            self.compare(roots)


class UniversalReviewCoverageTests(unittest.TestCase):
    def test_known_scores_require_review_but_nulls_and_mechanical_zero_do_not_fabricate_it(self):
        expected = {("c01", "w1"), ("c01", "w2"), ("c01", "w3"), ("c01", "w4")}
        rows = {("c01", "w1"): {"semantic": 3, "naturalness": 2, "status": "scored", "reviewed": True},
                ("c01", "w2"): {"semantic": None, "naturalness": None, "status": "review_failed", "reviewed": False},
                ("c01", "w3"): {"semantic": 0, "naturalness": None, "status": "delivery_zero", "reviewed": False}}
        coverage = _review_coverage(rows, expected)
        self.assertEqual(coverage["expected_records"], 4)
        self.assertEqual(coverage["independently_reviewed_records"], 1)
        self.assertEqual(coverage["mechanical_delivery_zero_records"], 1)
        self.assertEqual(coverage["semantic_unknown_or_missing_records"], 2)
        rows["c01", "w1"]["reviewed"] = False
        with self.assertRaisesRegex(ValueError, "without independent review"):
            _review_coverage(rows, expected)
        rows["c01", "w1"].update(semantic=None, naturalness=2)
        with self.assertRaisesRegex(ValueError, "without independent review"):
            _review_coverage(rows, expected)




def pointer(path):
    return {"path": str(path.resolve()), "sha256": sha(path)}

class AuxiliaryComparisonTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/".local/translation-evaluation-tests"
        scratch.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        temporary=patch.object(tempfile,"tempdir",self.temp.name)
        temporary.start()
        self.addCleanup(temporary.stop)
        self.fixture=source_fixtures.SceneEvaluationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.fixture.scenes=[{**scene,"scene_id":scene["id"],"source_language":"ja","target_language":"zh-Hans"}
                             for scene in self.fixture.scenes]
        e.dump_jsonl(self.fixture.scene_path,self.fixture.scenes)
        # This native fixture creates qualified source metadata using synthetic references.
        self.fixture.delivery("source-bootstrap")
        self.policy=self.root/"policy.json"
        e.dump(self.policy,{"status":"frozen_before_candidate_quality"})
        self.roots=[]
        self.plans=[]
        self.items=[]
        recipe_source=Path(__file__).resolve().parents[1]/comparison.RECIPE_CODE
        self.recipe_pin=e.sha(recipe_source)
        for seed in SEEDS:
            self.native_seed(seed)
        self.assertEqual(e.sha(recipe_source),self.recipe_pin,"Used recipe source changed during native fixture capture")

    def native_seed(self,seed):
        f=self.fixture
        seed_root=self.root/str(seed)
        seed_root.mkdir()
        aux_plan={"schema":SESSION_SCHEMA,"mode":"background","protocol":BACKGROUND_PROTOCOL,"stage":"qualification",
            "source":{"manifest":str(f.manifest_path),"manifest_sha256":e.sha(f.manifest_path),"scenes":str(f.scene_path),
                "scenes_sha256":e.sha(f.scene_path),"freeze_sha256":e.sha(f.source/"freeze-manifest.json")},
            "scene_ids":["scene-a","scene-b"],"settings":{"sampling":"official","cache_prompt":True,"n_predict":2048,
                "seed":seed,"max_attempts":2,"max_items":16},
            "budgets":{"max_translation_calls":20,"max_judge_calls":0,"max_estimated_tokens":200000,"max_wall_seconds":120}}
        plan_path=seed_root/"aux-plan.json"
        e.dump(plan_path,aux_plan)
        args=argparse.Namespace(candidate="hy-mt2-30b-a3b-apex-i-compact",session_plan=plan_path,output_dir=seed_root/"source-preparation/runtime-run/translation",
            server_url="http://127.0.0.1:8080",context_size=8192,engine_manifest=seed_root/"fake-engine.json",asset_manifest=[],stop_on_oom=True)
        client=FakeClient([result({"background":[]}),result({"background":[]})],tokens=7)
        self.assertEqual(execute_plan(args,lambda *a,**kw:client,auxiliary_fixtures.SourcePreparationWorkerTests().identity),0)
        artifact=args.output_dir/"preparation-options.json"
        e.dump(seed_root/"source-preparation/command-completion.json",{"schema":"hy30-flow-command-v2",
            "worker":"experiments.translation_flow.v2_source_preparation","plan_sha256":e.sha(plan_path),
            "returncode":0,"command_seconds":1.25})
        prepared=seed_root/"prepared"
        recipe_id=f"F7-native-fixture-{seed}"
        v2_prepare.prepare(manifest=f.manifest_path,scenes=f.scene_path,output=prepared,split="screen-a",stage="qualification",
            recipe_id=recipe_id,recipe="id-text",target_size=1,seed=seed,source_preparation_path=artifact,
            source_preparation_sha256=e.sha(artifact),source_preparation_projection=SOURCE_CONTROL)
        plan=e.read_json(prepared/"session-plan.json")
        item=plan["workloads"][0]
        self.items.append(item)
        session_root=seed_root/"execution/runtime-run/translation"
        run_dir=session_root/recipe_id
        run_dir.mkdir(parents=True)
        shutil.copyfile(prepared/"inputs.jsonl",run_dir/"inputs.jsonl")
        shutil.copyfile(prepared/"batch-options.json",run_dir/"batch-options.json")
        shutil.copyfile(prepared/"session-plan.json",session_root/"session-plan.json")
        packed=e.read_json(prepared/"packed-mapping.json")
        code={comparison.RECIPE_CODE:e.sha(Path(__file__).resolve().parents[1]/comparison.RECIPE_CODE)}
        snapshot=session_root/"source"/comparison.RECIPE_CODE
        snapshot.parent.mkdir(parents=True)
        shutil.copyfile(Path(__file__).resolve().parents[1]/comparison.RECIPE_CODE,snapshot)
        asset={"id":"synthetic","sha256":"b"*64}
        runtime={"asset":asset,"engine":{"asset":asset,"model_sha256":asset["sha256"],"context_size":8192},"template_sha256":"c"*64}
        e.dump(session_root/"session.json",{"schema":"hy30-flow-session-v2","plan_sha256":e.sha(session_root/"session-plan.json"),
            "identity":runtime,"compatibility_sha256":"d"*64,"code_sha256":code})
        e.dump(run_dir/"run.json",{"schema":"hy30-flow-session-v2","lane":"P-flow","candidate":"synthetic",
            "recipe":item["recipe"],"settings":item,"source_preparation":item["source_preparation"],"source_manifest_sha256":e.sha(f.manifest_path),
            "packed_mapping_sha256":e.sha(prepared/"packed-mapping.json"),"input_sha256":e.sha(run_dir/"inputs.jsonl"),
            "expected_window_ids":[b["id"] for b in packed["batches"]],"session_plan_sha256":e.sha(session_root/"session-plan.json"),
            "compatibility_sha256":"d"*64,"code_sha256":code})
        (session_root/"transport").mkdir()
        values=[{"id":b["id"],"translations":{uid:"合成译文" for uid in b["target_ids"]},"status":"delivered"} for b in packed["batches"]]
        e.dump_jsonl(run_dir/"results.jsonl",values)
        e.dump_jsonl(run_dir/"ledger.jsonl",[{"window_id":r["id"],"status":"delivered","translations":r["translations"],"attempts":[]} for r in values])
        e.dump_jsonl(run_dir/"schedule.jsonl",[])
        delivery=seed_root/"delivery"
        v2_delivery.deliver(f.manifest_path,prepared/"packed-mapping.json",run_dir,delivery)
        command=seed_root/"source-preparation/command-completion.json"
        trial_finish=seed_root/"trial-completion.json"
        e.dump(trial_finish,{"source_preparation":{"runtime_exit_code":0,"plan_sha256":e.sha(plan_path),
            "artifact":pointer(artifact),"cost":{"command":pointer(command),"ledger":pointer(artifact.parent/"ledger.jsonl")}}})
        evaluation=seed_root/"evaluation"
        v2_evaluation.prepare(f.manifest_path,f.input_path,f.reference_path,{"c01":delivery},evaluation,reference_freeze_path=f.freeze_path)
        run=e.read_json(evaluation/"run.json")
        run["p_flow_contract"]["candidate_artifacts"]["c01"]["original_trial_attempt_identity"]=pointer(trial_finish)
        scope={"version":comparison.UNIVERSAL_REVIEW,"state":"frozen_before_candidate_quality","selection":"all_expected_windows",
            "decision_policy":pointer(self.policy),"source_manifest":run["p_flow_contract"]["source_manifest"],
            "reference_freeze":run["p_flow_contract"]["reference_freeze"],"generation_seeds":list(SEEDS),"baseline_windows_per_seed":3,
            "candidate_windows":"all_card_selected_expected_windows","primary_policy":"reuse_verified_accepted_without_repeat",
            "review_policy":"fresh_only_missing_blind_reviews","adjudication_policy":"unchanged_bounded_dispute_resolution",
            "no_judge_statuses":sorted(e.NO_JUDGE_STATUSES),"blind_review_prior_opinions_visible":False,
            "unknown_policy":"retain_null_and_full_expected_denominator"}
        scope_path=seed_root/"scope.json"
        e.dump(scope_path,scope)
        run["universal_review_scope"]={**pointer(scope_path),**{key:scope[key] for key in ["version","state","selection"]}}
        e.dump(evaluation/"run.json",run)
        self.roots.append(evaluation)
        self.plans.append(plan_path)

    def test_native_three_seed_same_complete_auxiliary_recipe_is_one_identity(self):
        metadata=[comparison._evaluation(root)["metadata"]["c01"] for root in self.roots]
        identities=[m["recipe_identity_sha256"] for m in metadata]
        codes=[row["recipe_code_sha256"] for row in metadata]
        varying=[key for key in metadata[0]["recipe_settings"]
                 if len({json.dumps(row["recipe_settings"][key],sort_keys=True) for row in metadata})!=1]
        self.assertEqual(codes,[self.recipe_pin]*3,"Used recipe code changed between paired synthetic seeds")
        self.assertEqual(len(set(identities)),1,f"Same native auxiliary plan except seed must be one recipe; varying keys={varying}; code={codes}")

    def test_card_identity_must_include_locked_auxiliary_max_items(self):
        f=self.fixture
        windows={row["id"]:row for row in f.windows}
        card={"schema":"hy30-flow-trial-card-v2","candidate_group":"F7-native-fixture",
            "source":{"manifest":str(f.manifest_path),"manifest_sha256":e.sha(f.manifest_path),
                                                    "scenes":str(f.scene_path),"scenes_sha256":e.sha(f.scene_path)},"decision_policy":pointer(self.policy),
            "prepare":{"recipe_id":"F7-native-fixture-20261008","recipe":"id-text","seed":SEEDS[0],"split":"screen-a",
                "stage":"screening","target_size":1,"source_preparation_projection":SOURCE_CONTROL},
            "implementation_identity":[{"path":comparison.RECIPE_CODE,"sha256":e.sha(Path(__file__).resolve().parents[1]/comparison.RECIPE_CODE)}],
            "source_preparation":{"plan":str(self.plans[0]),"sha256":e.sha(self.plans[0])}}
        first=self.root/"card-first.json"
        e.dump(first,card)
        changed=e.read_json(self.plans[0])
        changed["settings"]["max_items"]=15
        altered=self.root/"changed-plan.json"
        e.dump(altered,changed)
        second=self.root/"card-second.json"
        e.dump(second,{**card,"source_preparation":{"plan":str(altered),"sha256":e.sha(altered)}})
        a=comparison._card(first,f.manifest_path,self.policy,windows)
        b=comparison._card(second,f.manifest_path,self.policy,windows)
        self.assertNotEqual(a["configuration_sha256"],b["configuration_sha256"],"Auxiliary max_items is complete-recipe configuration")

    def parsed_card(self,index=0,mutate=None):
        f=self.fixture
        seed=SEEDS[index]
        card={"schema":"hy30-flow-trial-card-v2","candidate_group":"F7-native-fixture",
            "source":{"manifest":str(f.manifest_path),"manifest_sha256":e.sha(f.manifest_path),
                                                    "scenes":str(f.scene_path),"scenes_sha256":e.sha(f.scene_path)},"decision_policy":pointer(self.policy),
            "prepare":{"recipe_id":f"F7-native-fixture-{seed}","recipe":"id-text","seed":seed,"split":"screen-a",
                                                        "stage":"screening","target_size":1,"source_preparation_projection":SOURCE_CONTROL},
            "implementation_identity":[{"path":comparison.RECIPE_CODE,"sha256":e.sha(Path(__file__).resolve().parents[1]/comparison.RECIPE_CODE)}],
            "source_preparation":{"plan":str(self.plans[index]),"sha256":e.sha(self.plans[index])}}
        if mutate:mutate(card)
        path=self.root/f"card-{index}.json"
        e.dump(path,card)
        return comparison._card(path,f.manifest_path,self.policy,{row["id"]:row for row in f.windows})

    def test_native_per_seed_auxiliary_cost_and_consumed_artifacts_remain_distinct(self):
        proof=[]
        for index,root in enumerate(self.roots):
            metadata=comparison._evaluation(root)["metadata"]["c01"]
            comparison._card_generation(metadata,self.parsed_card(index))
            proof.append(comparison._auxiliary_provenance(metadata["source_preparation"]))
        self.assertEqual(len({row["artifact"]["sha256"] for row in proof}),3)
        self.assertEqual(len({row["command"]["path"] for row in proof}),3)
        self.assertEqual([row["command_seconds"] for row in proof],[1.25]*3)
        self.assertEqual([row["seed"] for row in proof],list(SEEDS))
        self.assertTrue(all(row["cost_attribution"]=="native_auxiliary_command_once_per_trial" for row in proof))
        self.assertTrue(all("preparations" not in row and "raw_responses" not in row for row in proof))

    def test_full_plan_budget_and_projection_drift_cannot_match_native_generation(self):
        metadata=comparison._evaluation(self.roots[0])["metadata"]["c01"]
        original=e.read_json(self.plans[0])
        for key in ("max_items","n_predict","max_wall_seconds"):
            changed=deepcopy(original)
            container=changed["budgets"] if key=="max_wall_seconds" else changed["settings"]
            container[key]+=1
            alternate=self.root/f"changed-{key}.json"
            e.dump(alternate,changed)
            card=self.parsed_card(mutate=lambda card:card.update(source_preparation={"plan":str(alternate),"sha256":e.sha(alternate)}))
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,"complete auxiliary plan"):
                comparison._card_generation(metadata,card)
        from experiments.translation_flow.v2_source_projection import SCENE_CARD
        card=self.parsed_card(mutate=lambda card:card["prepare"].update(source_preparation_projection=SCENE_CARD))
        with self.assertRaisesRegex(ValueError,"complete auxiliary plan"):
            comparison._card_generation(metadata,card)

    def test_auxiliary_source_mode_protocol_seed_and_order_tamper_are_rejected(self):
        original=e.read_json(self.plans[0])
        changes=[lambda plan:plan["source"].update(manifest_sha256="f"*64),
                                            lambda plan:plan.update(protocol="unregistered-protocol"),
                                            lambda plan:plan.update(mode="terms"),lambda plan:plan["settings"].update(seed=SEEDS[1]),
                                            lambda plan:plan.update(scene_ids=["scene-a","scene-a"])]
        for index,change in enumerate(changes):
            altered=deepcopy(original)
            change(altered)
            path=self.root/f"tampered-{index}.json"
            e.dump(path,altered)
            with self.subTest(index=index),self.assertRaises(ValueError):
                self.parsed_card(mutate=lambda card:card.update(source_preparation={"plan":str(path),"sha256":e.sha(path)}))

    def test_missing_and_unexpected_auxiliary_are_not_silently_ignored(self):
        metadata=comparison._evaluation(self.roots[0])["metadata"]["c01"]
        with self.assertRaisesRegex(ValueError,"missing or unexpected"):
            comparison._card_generation({**metadata,"source_preparation":None},self.parsed_card())
        def without_aux(card):
            card.pop("source_preparation")
            card["prepare"].pop("source_preparation_projection")
        with self.assertRaisesRegex(ValueError,"missing or unexpected"):
            comparison._card_generation(metadata,self.parsed_card(mutate=without_aux))
        with self.assertRaisesRegex(ValueError,"projection requires"):
            self.parsed_card(mutate=lambda card:card.pop("source_preparation"))
        root=self.roots[0]
        run=e.read_json(root/"run.json")
        run["p_flow_contract"]["candidate_artifacts"]["c01"].pop("original_trial_attempt_identity")
        e.dump(root/"run.json",run)
        with self.assertRaisesRegex(ValueError,"frozen original trial completion"):
            comparison._evaluation(root)

    def test_full_screening_auxiliary_scope_is_read_from_bound_native_main_plan(self):
        root=self.roots[0]
        run=e.read_json(root/"run.json")
        original_path=Path(run["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"]["path"])
        original=e.read_json(original_path)
        plan_path=original_path.parent.parent/"session-plan.json"
        plan=e.read_json(plan_path)
        plan["experiment_identity"]["split"]="screening"
        e.dump(plan_path,plan)
        original["session_plan_sha256"]=e.sha(plan_path)
        e.dump(original_path,original)
        run["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"]=pointer(original_path)
        e.dump(root/"run.json",run)
        metadata=comparison._evaluation(root)["metadata"]["c01"]
        self.assertEqual(metadata["source_preparation"]["generation_split"],"screening")
        card=self.parsed_card(mutate=lambda card:card["prepare"].update(split="screening"))
        comparison._card_generation(metadata,card)

    def test_native_auxiliary_cost_sidecar_and_declared_code_bytes_are_verified(self):
        metadata=comparison._evaluation(self.roots[0])["metadata"]["c01"]
        auxiliary=metadata["source_preparation"]
        for key in ("ledger","batch_options","command"):
            path=Path(auxiliary[key]["path"])
            saved=path.read_bytes()
            path.write_bytes(saved+b" ")
            with self.subTest(key=key),self.assertRaises(ValueError):comparison._evaluation(self.roots[0])
            path.write_bytes(saved)
        code=auxiliary["source_snapshot_root"]/comparison.RECIPE_CODE
        code.write_bytes(b"# Changed auxiliary source implementation\n")
        with self.assertRaisesRegex(ValueError,"auxiliary implementation"):
            comparison._card_generation(metadata,self.parsed_card())

    def test_no_auxiliary_recipe_identity_bytes_are_unchanged(self):
        fixture=ComparisonTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        metadata=comparison._evaluation(fixture.candidates[0])["metadata"]["c01"]
        import hashlib
        previous=hashlib.sha256(json.dumps({"settings":metadata["recipe_settings"],
                        "code_sha256":metadata["recipe_code_sha256"]},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(metadata["recipe_identity_sha256"],previous)
        self.assertIsNone(metadata["source_preparation"])

    def test_fresh_slot_entry_reuses_native_auxiliary_projection_and_code_guards(self):
        metadata=comparison._evaluation(self.roots[0])["metadata"]["c01"]
        card=self.parsed_card()
        windows={row["id"]:row for row in self.fixture.windows}
        def bind(parsed):
            comparison._fresh_auxiliary_binding(metadata["source_preparation"],pointer(Path(parsed["path"])),
                self.root,self.fixture.manifest_path,self.policy,windows)
        bind(card)
        from experiments.translation_flow.v2_source_projection import SCENE_CARD
        changed=self.parsed_card(mutate=lambda card:card["prepare"].update(source_preparation_projection=SCENE_CARD))
        with self.assertRaisesRegex(ValueError,"complete auxiliary plan/projection"):
            bind(changed)
        card=self.parsed_card()
        code=metadata["source_preparation"]["source_snapshot_root"]/comparison.RECIPE_CODE
        code.write_bytes(b"# Changed native auxiliary implementation only\n")
        with self.assertRaisesRegex(ValueError,"auxiliary implementation"):
            bind(card)


if __name__ == "__main__":
    unittest.main()
