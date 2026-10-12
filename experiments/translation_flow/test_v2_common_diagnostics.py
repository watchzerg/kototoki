"""Synthetic sealed common-source diagnostics; no corpus/model/judge access."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from experiments.translation_eval.runner import dump, dump_jsonl, load_jsonl, read_json, sha
from tests import test_translation_flow_v2_compare as comparison_fixtures
from . import v2_common_diagnostics as diagnostics
from . import v2_compare as comparison
from . import v2_statistics as statistics_module
from .v2_prepare import pack_scene
from .v2_statistics import BASELINE, SEEDS


ROLES = ("original_C0", "common_b3", "common_b5", "common_b20")
GROUPS = {"original_C0": BASELINE, "common_b3": "synthetic-common-b3",
          "common_b5": "synthetic-common-b5", "common_b20": "synthetic-common-b20"}


class CommonDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = comparison_fixtures.ComparisonTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        self.root = f.root
        # Keep the original96 donor frame while the new matched frame has48
        # windows in29 scenes. All units here are metadata, never dialogue.
        for index, row in enumerate(f.windows):
            scene = index % 29 if index < 48 else index
            movie = scene < 10
            work = scene % 3
            row.update(scene_id=f"scene{scene:03}", work_id=f"{'M' if movie else 'W'}{work:02}",
                       work=f"Synthetic {'movie' if movie else 'series'} {work}",
                       category="animation_movie" if movie else "anime_series",
                       series_cluster="shared-movies" if movie and work < 2 else None,
                       units=[{"id": f"scene{scene:03}-u{cue}"} for cue in range(1, 63 if scene == 0 else 3)],
                       scored_ids=[f"scene{scene:03}-u1"])
        dump(f.source, {"windows": f.windows})
        policy = read_json(f.policy)
        policy["freeze_provenance"]["source_workload"]["manifest_sha256"] = sha(f.source)
        dump(f.policy, policy)
        scope = read_json(f.scope)
        scope.update(source_manifest=f.pointer(f.source), decision_policy=f.pointer(f.policy))
        dump(f.scope, scope)
        f.baselines = [f.evaluation("donor", seed, f.windows) for seed in SEEDS]
        for root in f.baselines:
            original = read_json(root / "original-run.json")
            original["settings"]["label"] = BASELINE
            dump(root / "original-run.json", original)
            run = read_json(root / "run.json")
            run["p_flow_contract"]["candidate_artifacts"]["c01"].update(
                recipe_id=BASELINE, original_generation_cost_identity=f.pointer(root / "original-run.json"))
            dump(root / "run.json", run)
            f.seal(root)
        self.window_ids = [row["id"] for row in f.windows[:48]]
        self.scene_ids = list(dict.fromkeys(row["scene_id"] for row in f.windows[:48]))
        self.scene_units = {row["scene_id"]: row["units"] for row in f.windows[:48]}
        self.source_cues_checked = sum(len(units) for units in self.scene_units.values())
        def matched_fixture_dump(path, value):
            value = deepcopy(value)
            if value.get("schema") == "hy30-flow-trial-card-v2" and "selected_scene_ids" in value["prepare"]:
                value["prepare"]["selected_scene_ids"] = list(dict.fromkeys(value["prepare"]["selected_scene_ids"]))
            if "packing" in value and "scene_ids" in value:
                value["scene_ids"] = list(dict.fromkeys(value["scene_ids"]))
            if value.get("version") == comparison.MATCHED_SCOPE:
                value["control_scene_ids"] = self.scene_ids
            dump(path, value)
        # Adapt fixture construction itself; all production provenance guards
        # remain real and validate the resulting freshly bound identities.
        with patch.object(comparison_fixtures, "dump", matched_fixture_dump):
            self.baselines = f.matched_controls()
        self.design_path = self.root / "design.json"
        dump(self.design_path, {"schema": "hy30-common-source-paired-diagnostic-comparison-design-v1",
            "state": "design_frozen_no_common_screening_quality_read_no_helper_execution_authorized",
            "scope": {"source_manifest": f.pointer(f.source),
            "split": "screen-a", "window_ids": self.window_ids},
            "decision_policy": f.pointer(f.policy), "implementations": {
                "main_comparator": f.pointer(Path(comparison.__file__)),
                "statistics": f.pointer(Path(statistics_module.__file__))}})
        self.visibility_path = self.root / "visibility.json"
        self.release_path = self.root / "release.json"
        self.entries = []
        self.visibility_entries = []
        self.native = {}
        for seed, root in zip(SEEDS, self.baselines, strict=True):
            self.set_scores(root, "original_C0")
            self.entries.append(self.release_entry("original_C0", seed, root,
                self.root / f"{BASELINE}-{seed}-card.json"))
        for role, size in (("common_b3", 3), ("common_b5", 5), ("common_b20", 20)):
            for seed in SEEDS:
                root, card, native, packed, inputs, footprints = self.common_root(role, size, seed)
                self.native[role, seed] = (root, card, native, packed, inputs, footprints)
                self.entries.append(self.release_entry(role, seed, root, card))
                verification = footprints.with_suffix(".native-verification.json")
                transport_proof = footprints.with_suffix(".token-request-projection.json")
                dump(transport_proof, {"synthetic_only": True, "actual_full_prompt_verified": True,
                    "source_truncated": False, "token_request_projection_checked": True})
                dump(verification, {"schema": "common-source-native-visibility-verification-v1",
                    "state": "actual_native_source_visibility_verified", "card": f.pointer(card),
                    "original_generation": f.pointer(native), "inputs": f.pointer(inputs),
                    "packed_mapping": f.pointer(packed), "footprints": f.pointer(footprints), "scene_ids": self.scene_ids,
                    "source_cues_checked": self.source_cues_checked,
                    "native_expected_batch_ids": read_json(native)["expected_window_ids"],
                    "token_request_projection_proofs": [f.pointer(transport_proof)],
                    "actual_full_prompt_verified": True, "source_truncated": False})
                self.visibility_entries.append({"role": role, "seed": seed, "card": f.pointer(card),
                    "original_generation": f.pointer(native), "packed_mapping": f.pointer(packed),
                    "inputs": f.pointer(inputs), "footprints": f.pointer(footprints),
                    "native_verification": f.pointer(verification)})
        dump(self.visibility_path, {"schema": "common-source-full29-visibility-equality-v1",
            "state": "actual_full_scope_verified", "design": f.pointer(self.design_path),
            "source_manifest": f.pointer(f.source), "decision_policy": f.pointer(f.policy),
            "window_ids": self.window_ids, "scene_ids": self.scene_ids,
            "source_cues_checked": self.source_cues_checked, "entries": self.visibility_entries})
        self.original_release_path = self.root / "original-control-release.json"
        dump(self.original_release_path, {"version": "matched-paired-quality-inspection-gate-v1",
            "state": "cleared_for_paired_quality_inspection", "source_manifest": f.pointer(f.source),
            "decision_policy": f.pointer(f.policy), "universal_review_scope": f.pointer(f.scope),
            "matched_control_scope": f.pointer(f.matched_scope), "paired_groups": [{"pairs": [
                {"seed": entry["seed"], "baseline": {"root": entry["evaluation_root"], "run": entry["run"],
                    "finalization": entry["seal"], "original_generation_cost_identity": entry["original_generation"]}}
                for entry in self.entries if entry["role"] == "original_C0"]}]})
        self.original_release_pin = sha(self.original_release_path)
        self.release = {"schema": "common-source-diagnostic-quality-release-v1",
            "state": "released_for_registered_diagnostics", "design": f.pointer(self.design_path),
            "source_manifest": f.pointer(f.source), "decision_policy": f.pointer(f.policy),
            "visibility_proof": f.pointer(self.visibility_path), "groups": GROUPS,
            "original_control_release": f.pointer(self.original_release_path),
            "entries": self.entries}
        dump(self.release_path, self.release)
        self.release_pin = sha(self.release_path)
        self.visibility_pin = sha(self.visibility_path)

    def release_entry(self, role, seed, root, card):
        f = self.fixture
        original = read_json(root / "run.json")["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"]
        return {"role": role, "seed": seed, "evaluation_root": str(root), "card": f.pointer(card),
                "run": f.pointer(root / "run.json"), "expected": f.pointer(root / "expected.jsonl"),
                "final": f.pointer(root / "final.jsonl"), "seal": f.pointer(root / "finalization-manifest.json"),
                "original_generation": original}

    def set_scores(self, root, role):
        rows = load_jsonl(root / "final.jsonl")
        for row in rows:
            variation = int(row["work"].rsplit(" ", 1)[1]) % 2
            row["semantic"] = {"original_C0": 1, "common_b3": 2 + variation,
                               "common_b5": 3 + variation, "common_b20": 1 + variation}[role]
        dump_jsonl(root / "final.jsonl", rows)
        self.fixture.seal(root)

    def common_root(self, role, size, seed):
        f = self.fixture
        card = f.card(seed, GROUPS[role])
        raw_card = read_json(card)
        raw_card["prepare"].update(target_size=size, context_before=1, context_after=1,
            token_target=None, common_context=False, offset=0, common_context_block_size=60,
            selected_scene_ids=self.scene_ids)
        raw_card["source"]["scenes_sha256"] = sha(f.source)
        batches, footprints_rows = [], []
        for sid, units in self.scene_units.items():
            windows, mapping = pack_scene({"id": sid, "context": [{"id": unit["id"], "text": unit["id"]}
                for unit in units], "translate_ids": [unit["id"] for unit in units]},
                target_size=size, common_context_block_size=60)
            batches.extend(mapping)
            footprints_rows.extend({"scene_id": sid, "target_cue_id": target,
                "visible_source": [{"id": unit["id"], "text_sha256": hashlib.sha256(unit["text"].encode()).hexdigest()}
                                   for unit in window["context"]]}
                for window in windows for target in window["translate_ids"])
        raw_card["source_estimate"] = {"batches": len(batches)}
        dump(card, raw_card)
        root = f.evaluation(role, seed, f.windows[:48])
        native = root / "execution/runtime-run/translation" / raw_card["prepare"]["recipe_id"] / "run.json"
        native.parent.mkdir(parents=True)
        inputs = native.parent / "inputs.jsonl"
        inputs.write_bytes(b"Synthetic opaque source-only input identity, never parse\n")
        packed = root / "prepared/packed-mapping.json"
        packed.parent.mkdir()
        packing = {key: raw_card["prepare"][key] for key in ("target_size", "context_before", "context_after",
            "token_target", "common_context", "offset", "common_context_block_size")}
        dump(packed, {"packing": packing, "scene_ids": self.scene_ids, "source_manifest": f.pointer(f.source),
            "source_scenes": f.pointer(f.source), "batches": batches})
        original = read_json(root / "original-run.json")
        original["settings"].update(label=raw_card["prepare"]["recipe_id"], input_sha256=sha(inputs),
                                   packed_mapping_sha256=sha(packed))
        original["expected_window_ids"] = [batch["id"] for batch in batches]
        dump(native, original)
        saved = native.parent.parent / "source" / comparison.RECIPE_CODE
        saved.parent.mkdir(parents=True)
        saved.write_bytes(f.recipe_source.read_bytes())
        dump(root / "trial-start.json", {"card_path": str(card), "card_sha256": sha(card), "card": raw_card})
        run = read_json(root / "run.json")
        run["p_flow_contract"]["candidate_artifacts"]["c01"].update(recipe_id=raw_card["prepare"]["recipe_id"],
            original_generation_cost_identity=f.pointer(native))
        run["generation_packed_mapping"] = f.pointer(packed)
        dump(root / "run.json", run)
        footprints = self.root / f"{role}-{seed}-footprints.jsonl"
        dump_jsonl(footprints, footprints_rows)
        self.set_scores(root, role)
        return root, card, native, packed, inputs, footprints

    def build(self):
        f = self.fixture
        return diagnostics.summarize(f.pointer(self.design_path), f.pointer(self.release_path),
            f.pointer(self.visibility_path), expected_release_sha256=self.release_pin,
            expected_visibility_sha256=self.visibility_pin, expected_design_sha256=sha(self.design_path),
            expected_source_sha256=sha(f.source), expected_policy_sha256=sha(f.policy),
            expected_review_scope_sha256=sha(f.scope), expected_matched_scope_sha256=sha(f.matched_scope),
            expected_original_control_release_sha256=self.original_release_pin,
            expected_comparator_sha256=sha(Path(comparison.__file__)),
            expected_statistics_sha256=sha(Path(statistics_module.__file__)))

    def republish(self):
        f = self.fixture
        for entry in self.entries:
            root = Path(entry["evaluation_root"])
            f.seal(root)
            entry.update(self.release_entry(entry["role"], entry["seed"], root, Path(entry["card"]["path"])))
        for entry in self.visibility_entries:
            for key in ("card", "original_generation", "packed_mapping", "inputs", "footprints"):
                entry[key] = f.pointer(Path(entry[key]["path"]))
            verification_path = Path(entry["native_verification"]["path"])
            verification = read_json(verification_path)
            verification.update({key: entry[key] for key in ("card", "original_generation", "packed_mapping", "inputs", "footprints")})
            dump(verification_path, verification)
            entry["native_verification"] = f.pointer(verification_path)
        proof = read_json(self.visibility_path)
        proof["entries"] = self.visibility_entries
        dump(self.visibility_path, proof)
        self.release["visibility_proof"] = f.pointer(self.visibility_path)
        dump(self.release_path, self.release)
        self.release_pin = sha(self.release_path)
        self.visibility_pin = sha(self.visibility_path)

    def assert_gate_without_final_parse(self):
        original = Path.read_text
        parsed = []
        def guarded(path, *args, **kwargs):
            if path.name == "final.jsonl":
                parsed.append(str(path))
                raise AssertionError("quality ledger parsed before all release gates passed")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", guarded), self.assertRaises((ValueError, OSError)):
            self.build()
        self.assertEqual(parsed, [])

    def category_pairs(self, statistics):
        return [pair for layer in statistics["splits"]["screen-a"]["strata"].values()
                for category in layer["categories"].values() for pair in category["pairs"]]

    def test_all_five_contrasts_use_real_paired_statistics_and_preserve_scope(self):
        with patch.object(statistics_module, "build_statistics", wraps=statistics_module.build_statistics) as arithmetic:
            summary = self.build()
        self.assertEqual(arithmetic.call_count, 5)
        self.assertEqual(summary["schema"], "hy30-common-source-diagnostic-summary-v1")
        self.assertEqual(summary["arithmetic_reference"], "common_b5")
        self.assertEqual(summary["official_baseline"], BASELINE)
        self.assertEqual(summary["expected_records_by_role"], dict.fromkeys(ROLES, 144))
        contrasts = summary["contrasts"]
        self.assertEqual(set(contrasts), {"common_b3_minus_common_b5", "common_b20_minus_common_b5",
            "common_b3_minus_original_C0", "common_b5_minus_original_C0", "common_b20_minus_original_C0"})
        for call in arithmetic.call_args_list:
            expected = call.args[0]
            self.assertEqual(len(expected), 288)
            self.assertEqual({row["seed"] for row in expected}, set(SEEDS))
            self.assertEqual({row["window_id"] for row in expected}, set(self.window_ids))
        for pair in self.category_pairs(contrasts["common_b3_minus_common_b5"]):
            self.assertEqual(pair["semantic_difference"], -1)
            for name in ("work_cluster_interval", "series_cluster_interval", "simultaneous_interval"):
                self.assertEqual((pair[name]["lower"], pair[name]["upper"]), (-1, -1))
            self.assertEqual(pair["complete_seed_pairs"], pair["complete_paired_windows"] * 3)
            self.assertIn("leave_one_work_out", pair)
            self.assertIn("leave_one_series_cluster_out", pair)
        representative = contrasts["common_b3_minus_original_C0"]["splits"]["screen-a"]["strata"]["representative"]
        movie = representative["categories"]["movie"]["pairs"][0]
        self.assertGreater(movie["work_cluster_interval"]["upper"], movie["work_cluster_interval"]["lower"])
        self.assertLess(movie["series_cluster_interval"]["cluster_count"], movie["work_cluster_interval"]["cluster_count"])
        for stats in contrasts.values():
            self.assertEqual(set(stats["splits"]["screen-a"]["strata"]), {"representative", "risk"})
            self.assertTrue(stats["splits"]["screen-a"]["strata"]["risk"]["diagnostic_only"])
        self.assertNotIn("PRIVATE", json.dumps(summary))

    def test_null_delivery_zero_and_absent_final_keep_all_144_expected_records(self):
        root = self.native["common_b3", SEEDS[0]][0]
        finals = load_jsonl(root / "final.jsonl")
        finals[0].update(status="unresolved", semantic=None, naturalness=None,
                         provisional_primary={"semantic": 4})
        finals[1].update(status="delivery_zero", semantic=0, naturalness=None,
                         structural_status="delivery_zero", reviewed=False)
        missing = finals.pop(2)
        expected = load_jsonl(root / "expected.jsonl")
        expected[1]["structural_status"] = "delivery_zero"
        dump_jsonl(root / "expected.jsonl", expected)
        dump_jsonl(root / "final.jsonl", finals)
        run = read_json(root / "run.json")
        run["expected_sha256"] = sha(root / "expected.jsonl")
        dump(root / "run.json", run)
        self.republish()
        summary = self.build()
        self.assertEqual(summary["expected_records_by_role"]["common_b3"], 144)
        stats = summary["contrasts"]["common_b3_minus_original_C0"]
        candidates = [layer["candidates"][GROUPS["common_b3"]]
            for stratum in stats["splits"]["screen-a"]["strata"].values()
            for layer in stratum["categories"].values()]
        self.assertEqual(sum(row["expected_seed_records"] for row in candidates), 144)
        self.assertEqual(sum(row["semantic_scored_seed_records"] for row in candidates), 142)
        self.assertEqual(sum(row["naturalness_scored_seed_records"] for row in candidates), 141)
        self.assertEqual(sum(row["status_counts"].get("not_run", 0) for row in candidates), 1)
        self.assertEqual(sum(row["status_counts"].get("delivery_zero", 0) for row in candidates), 1)
        self.assertEqual(sum(row["status_counts"].get("unresolved", 0) for row in candidates), 1)
        missing_work = next(row for row in candidates if missing["window_id"] in row["windows"])
        self.assertLess(missing_work["semantic_lower"]["mean"], missing_work["semantic_upper"]["mean"])
        for pair in self.category_pairs(stats):
            self.assertEqual(pair["interval_scope"], "complete_all_seeds_paired_window_subset_only")
            self.assertIn("missing_0_4_difference_bounds", pair)

    def test_release_and_visibility_require_external_registered_hashes(self):
        self.visibility_path.write_bytes(self.visibility_path.read_bytes() + b" ")
        self.assert_gate_without_final_parse()

    def test_missing_last_seal_blocks_every_quality_ledger(self):
        Path(self.entries[-1]["seal"]["path"]).unlink()
        self.assert_gate_without_final_parse()

    def test_original_control_quality_authorization_is_required_before_finals(self):
        self.original_release_path.unlink()
        self.assert_gate_without_final_parse()

    def test_original_control_quality_authorization_cannot_change(self):
        self.original_release_path.write_bytes(self.original_release_path.read_bytes() + b" ")
        self.assert_gate_without_final_parse()

    def test_missing_release_seed_is_not_replaced_by_qualification(self):
        self.release["entries"] = self.entries[:-1]
        dump(self.release_path, self.release)
        self.release_pin = sha(self.release_path)
        self.assert_gate_without_final_parse()

    def test_qualification_only_visibility_does_not_establish_full_scope(self):
        proof = read_json(self.visibility_path)
        proof["source_cues_checked"] = 270
        proof["scene_ids"] = self.scene_ids[:2]
        dump(self.visibility_path, proof)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_footprint_source_order_and_hash_changes_are_rejected_before_finals(self):
        path = self.native["common_b20", SEEDS[-1]][-1]
        rows = load_jsonl(path)
        rows[-1]["visible_source"].reverse()
        dump_jsonl(path, rows)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_scored_cues_only_visibility_cannot_replace_full_source_cues(self):
        for entry in self.visibility_entries:
            path = Path(entry["footprints"]["path"])
            rows = [row for row in load_jsonl(path) if row["target_cue_id"].endswith("-u1")]
            dump_jsonl(path, rows)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_all_nine_identical_but_wrong_source_footprints_are_rejected(self):
        for entry in self.visibility_entries:
            path = Path(entry["footprints"]["path"])
            rows = load_jsonl(path)
            for row in rows:
                if row["scene_id"] == "scene000":
                    row["visible_source"] = [unit for unit in row["visible_source"] if unit["id"] == row["target_cue_id"]]
            dump_jsonl(path, rows)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_macroblock_clipping_and_boundary_use_full_native_geometry(self):
        path = self.native["common_b3", SEEDS[0]][-1]
        footprints = {row["target_cue_id"]: row["visible_source"] for row in load_jsonl(path)}
        self.assertEqual([row["id"] for row in footprints["scene000-u1"]],
                         [f"scene000-u{index}" for index in range(1, 62)])
        self.assertEqual([row["id"] for row in footprints["scene000-u62"]],
                         [f"scene000-u{index}" for index in range(60, 63)])
        self.assertEqual(len(footprints["scene001-u1"]), 2)
        self.assertEqual(self.build()["expected_records_by_role"], dict.fromkeys(ROLES, 144))

    def test_native_visibility_receipt_must_verify_full_untruncated_prompt(self):
        path = Path(self.visibility_entries[-1]["native_verification"]["path"])
        value = read_json(path)
        value.update(actual_full_prompt_verified=False, source_truncated=True)
        dump(path, value)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_native_visibility_receipt_requires_token_request_projection_proof(self):
        path = Path(self.visibility_entries[-1]["native_verification"]["path"])
        value = read_json(path)
        value["token_request_projection_proofs"] = []
        dump(path, value)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_changed_native_token_request_projection_proof_is_rejected(self):
        verification = read_json(Path(self.visibility_entries[-1]["native_verification"]["path"]))
        path = Path(verification["token_request_projection_proofs"][0]["path"])
        path.write_bytes(path.read_bytes() + b"changed")
        self.assert_gate_without_final_parse()

    def test_common_b5_cannot_use_the_official_c0_group(self):
        self.release["groups"] = {**GROUPS, "common_b5": BASELINE}
        dump(self.release_path, self.release)
        self.release_pin = sha(self.release_path)
        self.assert_gate_without_final_parse()

    def test_native_input_bytes_must_remain_bound_to_original_generation(self):
        inputs = self.native["common_b3", SEEDS[-1]][4]
        inputs.write_bytes(inputs.read_bytes() + b"changed")
        self.republish()
        self.assert_gate_without_final_parse()

    def test_card_packing_and_scene_scope_are_exact(self):
        card = self.native["common_b5", SEEDS[-1]][1]
        value = read_json(card)
        value["prepare"]["common_context_block_size"] = 20
        dump(card, value)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_source_manifest_pointer_drift_is_rejected_before_finals(self):
        proof = read_json(self.visibility_path)
        proof["source_manifest"]["sha256"] = "0" * 64
        dump(self.visibility_path, proof)
        self.republish()
        self.assert_gate_without_final_parse()

    def test_sealed_runtime_drift_across_seeds_cannot_enter_statistics(self):
        root, _, original, _, _, _ = self.native["common_b20", SEEDS[-1]]
        value = read_json(original)
        value["runtime_identity"]["engine"]["context_size"] = 16384
        dump(original, value)
        run = read_json(root / "run.json")
        run["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"] = self.fixture.pointer(original)
        dump(root / "run.json", run)
        self.republish()
        with self.assertRaisesRegex(ValueError, "runtime|model|template"):
            self.build()

    def test_sealed_generation_seed_drift_is_not_a_new_measurement(self):
        root, _, original, _, _, _ = self.native["common_b3", SEEDS[-1]]
        value = read_json(original)
        value["settings"]["seed"] = SEEDS[0]
        dump(original, value)
        run = read_json(root / "run.json")
        run["p_flow_contract"]["candidate_artifacts"]["c01"]["original_generation_cost_identity"] = self.fixture.pointer(original)
        dump(root / "run.json", run)
        self.republish()
        with self.assertRaisesRegex(ValueError, "seed"):
            self.build()


if __name__ == "__main__":
    unittest.main()
