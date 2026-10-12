"""Synthetic prospective custody and exact-byte membership checks; no inference."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import v2_confirmation as confirmation


class ConfirmationContractTests(unittest.TestCase):
    def setUp(self):
        workspace_temp = Path(__file__).resolve().parents[2] / ".local/tests"
        workspace_temp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=workspace_temp)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy_path = self.write("policy.json", {
            "status": "frozen_before_candidate_quality", "baseline": {"alias": "C0-official-cached"},
            "primary_endpoint": {"generation_seeds": list(confirmation.SEEDS), "confirmation_windows": 48,
                                 "categories": ["anime_series", "movie"], "metric": "final_semantic"},
            "confirmation_candidate_lock": {"maximum_complete_candidates": 3,
                "lock_all_before_confirmation_open": True, "replacement_after_confirmation_results": False,
                "unused_slots_may_be_filled_after_confirmation_results": False},
            "freeze_provenance": {"source_workload": {"scenes": 34, "source_cues": 4297,
                "scoring_windows": 96, "manifest_sha256": "a" * 64, "scenes_sha256": "b" * 64}}})
        self.policy_sha = confirmation.pointer(self.policy_path)["sha256"]
        self.manifest = self.root / "source-manifest.bin"
        self.manifest.write_bytes(b"Opaque synthetic source bytes; must not be JSON decoded.")
        self.scenes = self.root / "scenes.bin"
        self.scenes.write_bytes(b"Opaque synthetic scene bytes; no actual confirmation IDs or text.")
        reference = self.write("reference-metadata.json", {"synthetic_metadata_only": True})
        original = self.write("original-source-freeze.json", {"version": "hy30-flow-v2-source-v1",
            "role": "confirmation", "state": "source_frozen_reference_unreviewed"})
        self.freeze = self.write("source-freeze.json", {
            "version": "hy30-flow-v2-source-v1", "state": "source_frozen_reference_qualified",
            "role": "confirmation", "windows": 48,
            "original_source_freeze": confirmation.pointer(original),
            "reference_qualification": {**confirmation.pointer(reference),
                "version": "hy30-flow-v2-reference-v1", "state": "frozen_double_fresh_reference_review",
                "inference_allowed": True},
            "artifacts": [{"path": p.name, "sha256": confirmation.pointer(p)["sha256"]}
                          for p in (self.manifest, self.scenes)]})
        self.source = {"role": "confirmation", "split": "confirmation", "expected_windows": 48,
                       "selection_type": "representative", "manifest": confirmation.pointer(self.manifest),
                       "scenes": confirmation.pointer(self.scenes), "freeze": confirmation.pointer(self.freeze)}
        prompt = self.root / "judge-prompt.txt"
        prompt.write_text("Synthetic frozen evaluation prompt", encoding="utf-8")
        self.evaluation = self.write("evaluation-contract.json", {
            "schema": "hy30-confirmation-evaluation-contract-v1", "state": "frozen_before_confirmation_open",
            "scope_mode": confirmation.SCOPE_MODE, "source_scope_sha256": confirmation.source_scope_sha256(self.source),
            "generation_seeds": list(confirmation.SEEDS), "windows_per_seed": 48,
            "profile": "sol-high-auto-v1", "review_selection": "all_expected_judgeable_windows_each_seed",
            "fresh_C0_required": True, "screening_judgment_import_permitted": False,
            "prompt": confirmation.pointer(prompt)})
        code = self.root / "synthetic-recipe.py"
        code.write_text("# Synthetic recipe identity, never executed.\n", encoding="utf-8")
        self.code = code
        self.baseline_cards = self.cards("C0-official-cached", "c0", 5)
        self.candidates = [self.candidate("F1-b10", "c0", 10)]

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def cards(self, alias, recipe, size):
        paths = []
        for seed in confirmation.SEEDS:
            card = {"schema": "hy30-flow-trial-card-v2", "candidate_group": alias,
                "decision_policy": confirmation.pointer(self.policy_path),
                "source": {"manifest": str(self.manifest), "manifest_sha256": self.source["manifest"]["sha256"],
                           "scenes": str(self.scenes), "scenes_sha256": self.source["scenes"]["sha256"]},
                "prepare": {"stage": "confirmation", "split": "confirmation", "seed": seed,
                    "recipe_id": f"{alias}-{seed}", "recipe": recipe, "target_size": size,
                    "context_before": 1, "context_after": 1},
                "fixed_runtime_contract": deepcopy(confirmation.OFFICIAL_C0_RUNTIME),
                "implementation_identity": [confirmation.pointer(self.code)]}
            paths.append(self.write(f"{alias}-{seed}.json", card))
        return paths

    def candidate(self, alias, recipe="c0", size=10):
        return {"candidate_alias": alias, "applicable_categories": ["anime_series", "movie"],
                "hypothesis": "Synthetic prospective hypothesis", "intent": "quality",
                "cards": self.cards(alias, recipe, size)}

    def lock(self, *, candidates=None, source=None, name="lock.json"):
        return confirmation.freeze_lock(self.policy_path, self.source if source is None else source,
            self.baseline_cards, self.candidates if candidates is None else candidates,
            self.root / name, screening_quality_already_seen=True,
            evaluation_contract=confirmation.pointer(self.evaluation), expected_policy_sha256=self.policy_sha)

    def read(self, pointer):
        return json.loads(Path(pointer["path"]).read_text(encoding="utf-8"))

    def open(self, lock):
        return confirmation.record_unseal(lock, self.root / "unseal.json", expected_policy_sha256=self.policy_sha)

    def dispatch(self, card, lock, receipt):
        return confirmation.validate_confirmation_dispatch(card, lock, receipt, expected_policy_sha256=self.policy_sha)

    def test_lock_has_exact_three_seeds_fresh_scope_and_preserved_screening_history(self):
        lock = self.lock()
        value = confirmation.validate_lock(lock, expected_policy_sha256=self.policy_sha)
        self.assertEqual(value["scope_mode"], "fresh-independent-confirmation48-v1")
        self.assertEqual(value["generation_seeds"], list(confirmation.SEEDS))
        self.assertEqual(len(value["baseline"]["cards"]), 3)
        self.assertTrue(value["screening_quality_already_seen"])
        self.assertTrue(value["screening_quality_history_preserved"])
        self.assertFalse(value["confirmation_quality_already_seen"])
        self.assertEqual(value["screening_source_identity"]["scoring_windows"], 96)
        self.assertEqual(value["evaluation_contract"], confirmation.pointer(self.evaluation))

    def test_manifest_and_scene_bytes_are_hashed_but_never_decoded(self):
        original = confirmation._json
        paths = []
        def record(path):
            paths.append(path.resolve())
            return original(path)
        with patch.object(confirmation, "_json", side_effect=record):
            self.lock()
        self.assertNotIn(self.manifest.resolve(), paths)
        self.assertNotIn(self.scenes.resolve(), paths)

    def test_lock_and_receipt_creation_never_overwrite(self):
        lock = self.lock()
        before = Path(lock["path"]).read_bytes()
        with self.assertRaises(FileExistsError):
            self.lock()
        self.assertEqual(Path(lock["path"]).read_bytes(), before)
        receipt = self.open(lock)
        with self.assertRaises(FileExistsError):
            self.open(lock)
        self.dispatch(self.baseline_cards[0], lock, receipt)

    def test_dispatch_requires_unseal_receipt_and_exact_locked_members(self):
        lock = self.lock()
        with self.assertRaises(FileNotFoundError):
            self.dispatch(self.baseline_cards[0], lock, {"path": str(self.root / "missing"), "sha256": "a" * 64})
        receipt = self.open(lock)
        result = self.dispatch(self.candidates[0]["cards"][0], lock, receipt)
        self.assertEqual(result["seed"], confirmation.SEEDS[0])
        self.assertFalse(result["quality_history_reset"])
        newcomer = self.candidate("late-candidate")
        with self.assertRaisesRegex(ValueError, "not an exact preregistered"):
            self.dispatch(newcomer["cards"][0], lock, receipt)

    def test_maximum_three_no_duplicate_alias_or_missing_seed(self):
        self.lock(candidates=[self.candidate(f"candidate{i}") for i in range(3)])
        cases = [[], [self.candidate(f"too-many{i}") for i in range(4)], self.candidates * 2]
        for candidates in cases:
            with self.subTest(count=len(candidates)), self.assertRaises(ValueError):
                self.lock(candidates=candidates, name="bad-lock.json")
        missing = deepcopy(self.candidates)
        missing[0]["cards"] = missing[0]["cards"][:2]
        with self.assertRaisesRegex(ValueError, "three"):
            self.lock(candidates=missing, name="missing.json")
        duplicate = deepcopy(self.candidates)
        duplicate[0]["cards"][2] = duplicate[0]["cards"][0]
        with self.assertRaisesRegex(ValueError, "distinct frozen seeds"):
            self.lock(candidates=duplicate, name="duplicate.json")

    def test_configuration_drift_partial_scope_wrong_seed_or_c0_change_rejected(self):
        path = self.candidates[0]["cards"][1]
        original = json.loads(path.read_text(encoding="utf-8"))
        for change in ({"target_size": 11}, {"seed": True}, {"selected_scene_ids": ["synthetic-subset"]},
                       {"stage": "screening"}, {"split": "screen-a"}):
            changed = deepcopy(original)
            changed["prepare"].update(change)
            self.write(path.name, changed)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.lock(name="drift.json")
        self.write(path.name, original)
        baseline = json.loads(self.baseline_cards[0].read_text(encoding="utf-8"))
        baseline["prepare"]["context_after"] = 3
        self.write(self.baseline_cards[0].name, baseline)
        with self.assertRaisesRegex(ValueError, "complete C0"):
            self.lock()

    def test_source_role_count_qualification_and_old_screen_scope_rejected(self):
        for key, value in (("role", "screening"), ("split", "screen-a"),
                           ("expected_windows", 96), ("selection_type", "risk")):
            source = deepcopy(self.source)
            source[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.lock(source=source)
        original = self.read(confirmation.pointer(self.evaluation))
        for key, value in (("scope_mode", "explicit_matched48"), ("fresh_C0_required", False),
                           ("screening_judgment_import_permitted", True), ("windows_per_seed", 96),
                           ("generation_seeds", list(confirmation.SEEDS[:2]))):
            self.write(self.evaluation.name, dict(original, **{key: value}))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "distinct fresh"):
                self.lock()

    def test_post_open_card_source_policy_code_and_declaration_changes_fail(self):
        lock = self.lock()
        receipt = self.open(lock)
        path = self.candidates[0]["cards"][0]
        card = json.loads(path.read_text(encoding="utf-8"))
        self.write(path.name, {**card, "new_explanation": "changed bytes"})
        with self.assertRaises(ValueError):
            self.dispatch(path, lock, receipt)
        self.write(path.name, card)
        for target in (self.manifest, self.code, self.policy_path):
            before = target.read_bytes()
            target.write_bytes(before + b" ")
            with self.subTest(target=target.name), self.assertRaises(ValueError):
                self.dispatch(path, lock, receipt)
            target.write_bytes(before)
        changed_lock = self.read(lock)
        changed_lock["candidates"][0]["applicable_categories"] = ["movie"]
        alternative = self.write("changed-lock.json", changed_lock)
        with self.assertRaisesRegex(ValueError, "Unseal receipt"):
            self.dispatch(path, confirmation.pointer(alternative), receipt)

    def test_source_freeze_requires_qualification_and_exact_unique_artifacts(self):
        original = self.read(confirmation.pointer(self.freeze))
        for key in ("state", "qualification", "missing-artifact", "duplicate-artifact", "traversal"):
            changed = deepcopy(original)
            if key == "state":
                changed["state"] = "source_frozen_reference_unreviewed"
            elif key == "qualification":
                changed["reference_qualification"]["inference_allowed"] = False
            elif key == "missing-artifact":
                changed["artifacts"] = changed["artifacts"][:1]
            elif key == "duplicate-artifact":
                changed["artifacts"].append(changed["artifacts"][0])
            else:
                changed["artifacts"][0]["path"] = "../outside.bin"
            self.write(self.freeze.name, changed)
            source = deepcopy(self.source)
            source["freeze"] = confirmation.pointer(self.freeze)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.lock(source=source, name=f"bad-freeze-{key}.json")

    def test_receipt_wrong_lock_alias_history_or_chronology_fails(self):
        lock = self.lock()
        receipt = self.open(lock)
        original = self.read(receipt)
        before = (datetime.fromisoformat(self.read(lock)["locked_at_utc"]) - timedelta(days=1)).isoformat()
        for key, value in (("candidate_aliases", []), ("screening_quality_history_preserved", False),
                           ("replacement_or_slot_fill_allowed", True), ("opened_at_utc", before),
                           ("source_scope_sha256", "0" * 64)):
            alternative = self.write("changed-receipt.json", dict(original, **{key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.dispatch(self.baseline_cards[0], lock, confirmation.pointer(alternative))

    def test_scope_guard_distinguishes_native_source_stage_from_timing_phase(self):
        for stage in ("screening", "full-flow"):
            confirmation.validate_scope(stage, "screening", "screening", purpose="timing")
        confirmation.validate_scope("screening", "screen-a", "screening")
        confirmation.validate_scope("confirmation", "confirmation", "confirmation")
        bad = [("confirmation", "screen-a", "screening", "quality"),
               ("screening", "confirmation", "confirmation", "quality"),
               ("qualification", "confirmation", "confirmation", "quality"),
               ("confirmation", "confirmation", "confirmation", "timing"),
               ("screening", "screen-a", "screening", "timing")]
        for stage, split, role, purpose in bad:
            with self.subTest(stage=stage, split=split, purpose=purpose), self.assertRaises(ValueError):
                confirmation.validate_scope(stage, split, role, purpose=purpose)

    def add_auxiliary_plans(self):
        for seed, path in zip(confirmation.SEEDS, self.candidates[0]["cards"], strict=True):
            card = json.loads(path.read_text(encoding="utf-8"))
            plan = self.write(f"auxiliary-{seed}.json", {
                "schema": "hy30-source-preparation-session-v3", "stage": "confirmation",
                "mode": "terms", "protocol": "eligibility-filtered-proposals-v1",
                "source": {**card["source"], "freeze_sha256": self.source["freeze"]["sha256"]},
                "scene_ids": ["synthetic-scene"], "settings": {"seed": seed, "max_items": 16},
                "budgets": {"max_translation_calls": 2}})
            card["source_preparation"] = {"plan": str(plan), "sha256": confirmation.pointer(plan)["sha256"]}
            card["prepare"]["source_preparation_projection"] = "eligible-quoted-local-terms-v1"
            self.write(path.name, card)

    def test_auxiliary_plan_binds_source_seed_freeze_and_configuration(self):
        self.add_auxiliary_plans()
        lock = self.lock()
        receipt = self.open(lock)
        self.dispatch(self.candidates[0]["cards"][0], lock, receipt)
        path = self.candidates[0]["cards"][1]
        card = json.loads(path.read_text(encoding="utf-8"))
        plan_path = Path(card["source_preparation"]["plan"])
        original = json.loads(plan_path.read_text(encoding="utf-8"))
        for key in ("seed", "freeze", "source", "budget", "order", "mode"):
            changed = deepcopy(original)
            if key == "seed":
                changed["settings"]["seed"] = confirmation.SEEDS[0]
            elif key == "freeze":
                changed["source"]["freeze_sha256"] = "0" * 64
            elif key == "source":
                changed["source"]["scenes_sha256"] = "0" * 64
            elif key == "budget":
                changed["budgets"]["max_translation_calls"] = 3
            elif key == "order":
                changed["scene_ids"] = ["different-synthetic-scene"]
            else:
                changed["mode"] = "background"
            self.write(plan_path.name, changed)
            card["source_preparation"]["sha256"] = confirmation.pointer(plan_path)["sha256"]
            self.write(path.name, card)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.lock(name=f"bad-auxiliary-{key}.json")

    def test_external_token_artifact_bytes_and_projection_are_bound(self):
        artifact = self.root / "synthetic-counts.bin"
        artifact.write_bytes(b"Synthetic immutable token counts")
        for path in self.candidates[0]["cards"]:
            card = json.loads(path.read_text(encoding="utf-8"))
            card["prepare"]["token_counts_path"] = str(artifact)
            card["artifacts"] = {"token_counts_path": confirmation.pointer(artifact)["sha256"]}
            self.write(path.name, card)
        lock = self.lock()
        receipt = self.open(lock)
        artifact.write_bytes(b"Changed synthetic token counts")
        with self.assertRaises(ValueError):
            self.dispatch(self.candidates[0]["cards"][0], lock, receipt)
        artifact.write_bytes(b"Synthetic immutable token counts")
        card = json.loads(self.candidates[0]["cards"][0].read_text(encoding="utf-8"))
        card["prepare"]["source_preparation_projection"] = "eligible-quoted-local-terms-v1"
        self.write(self.candidates[0]["cards"][0].name, card)
        with self.assertRaisesRegex(ValueError, "requires a locked auxiliary"):
            self.lock(name="projection-without-plan.json")

    def native_metadata(self):
        # Match native v4 card fields using synthetic source/lineage only.
        for group in [self.baseline_cards, self.candidates[0]["cards"]]:
            for seed, path in zip(confirmation.SEEDS, group, strict=True):
                card = json.loads(path.read_text(encoding="utf-8"))
                card.update(id=f"synthetic-{seed}", family="C0" if group is self.baseline_cards else "F1",
                    role="fresh_control" if group is self.baseline_cards else "candidate",
                    hypothesis="Synthetic prospective native-format hypothesis",
                    source_freeze=confirmation.pointer(self.freeze), prospective_descriptor_only=True,
                    quality_scope={"windows": 48, "representative_windows": 48, "risk_windows": 0,
                        "scored_ids": 240, "works": 1, "seeds_for_candidate_decision": list(confirmation.SEEDS)},
                    source_estimate={"scenes": 1, "source_cues": 240, "batches": 48},
                    derivation={"parent_card": {"path": f"synthetic-parent-{seed}", "sha256": "a" * 64}},
                    historical_control_relation={"parent_card": {"path": f"synthetic-parent-{seed}", "sha256": "a" * 64},
                        "no_generation_relabel": True, "no_time_identity_equivalence": True})
                card["prepare"]["options"] = {"terms": [], "background": [], "style": "neutral", "review": False}
                self.write(path.name, card)

    def test_native_v4_defaults_and_per_seed_identity_are_supported(self):
        self.native_metadata()
        # Missing/default/explicit-empty forms have identical C0 execution behavior.
        first = json.loads(self.baseline_cards[0].read_text(encoding="utf-8"))
        first["prepare"].pop("options")
        self.write(self.baseline_cards[0].name, first)
        second = json.loads(self.baseline_cards[1].read_text(encoding="utf-8"))
        second["prepare"]["options"] = {}
        self.write(self.baseline_cards[1].name, second)
        lock = self.lock()
        receipt = self.open(lock)
        self.dispatch(self.baseline_cards[2], lock, receipt)

    def test_native_c0_runtime_and_nondefault_options_rejected_even_when_shared(self):
        originals = [json.loads(path.read_text(encoding="utf-8")) for path in self.baseline_cards]
        cases = [("context_tokens", 4096), ("output_reservation_tokens", 1024), ("temperature", 0.0),
                 ("engine", "different-engine"), ("asset_sha256", "0" * 64), ("cpu_fallback", True)]
        for key, value in cases:
            for path, original in zip(self.baseline_cards, originals, strict=True):
                card = deepcopy(original)
                card["fixed_runtime_contract"][key] = value
                self.write(path.name, card)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "official frozen APEX"):
                self.lock(name=f"bad-runtime-{key}.json")
        for options in ({"style": "natural-dialogue"}, {"review": True}, {"unknown_option": False}):
            for path, original in zip(self.baseline_cards, originals, strict=True):
                card = deepcopy(original)
                card["prepare"]["options"] = options
                self.write(path.name, card)
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.lock(name="bad-defaults.json")

    def test_cross_seed_launch_runtime_budget_and_fixed_contract_drift_rejected(self):
        self.native_metadata()
        path = self.candidates[0]["cards"][1]
        original = json.loads(path.read_text(encoding="utf-8"))
        for field, value in (("runtime", {"threads": 4, "engine": "synthetic-other-engine"}),
                             ("budgets", {"max_wall_seconds": 100}),
                             ("launch_options", {"context_size": 4096}),
                             ("fixed_runtime_contract", {**original["fixed_runtime_contract"], "temperature": 0.0})):
            self.write(path.name, {**original, field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "differs across quality seeds"):
                self.lock(name=f"bad-launch-{field}.json")
        changed = deepcopy(original)
        changed["quality_scope"].update(representative_windows=36, risk_windows=12)
        self.write(path.name, changed)
        with self.assertRaisesRegex(ValueError, "old matched screening48"):
            self.lock(name="old-native-quality-scope.json")

    def test_production_policy_hash_cannot_be_bypassed_by_changed_policy_bytes(self):
        with self.assertRaisesRegex(ValueError, "registered pre-result"):
            confirmation.freeze_lock(self.policy_path, self.source, self.baseline_cards, self.candidates,
                self.root / "wrong-policy-lock.json", screening_quality_already_seen=True,
                evaluation_contract=confirmation.pointer(self.evaluation))


if __name__ == "__main__":
    unittest.main()
