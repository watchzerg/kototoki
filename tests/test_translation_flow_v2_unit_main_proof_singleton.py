"""Native-shaped singleton admission and unchanged F5 proof regression fixtures.

The inherited 19 tests run the original handwritten fixture with its TEST module
alias rebound to the new verifier. Original production modules and test bytes are
unchanged. No model, native CLI, original material or reference is accessed.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from experiments.translation_flow import test_v2_unit_main_proof as original
from experiments.translation_flow import v2_unit_main_proof_singleton as main
from experiments.translation_flow import v2_unit_custody as custody
from experiments.translation_flow import v2_worker as worker
from experiments.translation_flow import v2_semantic_partition_grammar as partition
from experiments.translation_flow.test_v2_unit_custody import TraceClient
from experiments.translation_flow.test_v2_worker import settings, result
from experiments.translation_flow.test_worker import budget


class SingletonMainProofTests(original.MainProofTests):
    def setUp(self):
        # TEST-ONLY module selection: original fixture emits the new verifier's
        # actual file identity in its replay/authority/seal. No production
        # callable, parser, source bytes or old helper is monkeypatched.
        alias = patch.object(original, "main", main)
        alias.start()
        self.addCleanup(alias.stop)
        super().setUp()

    def singleton_row(self, *, outputs=None):
        window = {"id": "handwritten-singleton-tail", "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": "before", "text": "まだです。"}, {"id": "target", "text": "行きます。"},
                        {"id": "after", "text": "はい。"}], "translate_ids": ["target"]}
        root = self.root / "singleton-row"
        (root / "transport").mkdir(parents=True)
        item = settings("semantic-partition", terms=[], background=[], style="neutral", review=False)
        client = TraceClient(root, outputs or [result({"translations": {"u1": "合成台词。"}})])
        limits = budget()
        row = worker.run_window(client, window, item, 8192, limits,
                                {"verified": False, "first_response_checked": False})
        return row, window, item, root, client, limits

    def singleton_geometry(self):
        # Nine handwritten cues -> 4+4+1. The frozen original fixture has the
        # same three-batch/source denominator; only synthetic packing is rebuilt.
        cards = []
        for ptr in self.cards:
            card = custody._read(ptr)
            card["prepare"]["target_size"] = 4
            cards.append(self.write(f"singleton-card-{card['prepare']['seed']}.json", card))
        self.cards = cards
        self.entries = [{"id": f"F5-{seed}", "seed": seed, **ptr}
                        for seed, ptr in zip(original.diagnostics.SEEDS, cards, strict=True)]
        self.index = self.write("singleton-index.json", {"schema": "hy30-pending-v5-source-only-index-v1",
            "state": "frozen_not_executed", "cards": self.entries})
        self.bundle = self.write("singleton-bundle.json", {"schema": "hy30-pending-v5-source-only-freeze-v1",
            "state": "frozen_not_executed", "cards": self.entries, "index": self.index})
        self.registration = self.register(output=self.root / "singleton-registered")
        self.record = custody._read(self.registration)
        self.external = self.write("singleton-external.json", {"schema": custody.EXTERNAL_REGISTRATION_SCHEMA,
            "state": "frozen_before_generation", "registration": self.registration, "root_gate": self.gate,
            "registered_at_utc": "2020-01-01T00:00:00+00:00"})

    def test_single_target_planning0_native1_mapping0_is_authenticated(self):
        row, window, item, root, client, limits = self.singleton_row()
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(set(main._stage_specs(row, window, item)), {"joint-unit-translation"})
        self.assertEqual([a["stage"] for a in main._all_attempts(row, window, item, root)],
                         ["joint-unit-translation"])
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(limits.translation_calls, 1)
        for name in ("planning_cost", "mapping_cost"):
            self.assertEqual(row[name]["completion_calls"], 0)
            self.assertEqual(row[name]["input_tokens"], 0)
            self.assertEqual(row[name]["output_tokens"], 0)
        self.assertEqual(row["planning_provenance"]["model_planning_required"], False)
        self.assertEqual(row["translations"], {"target": "合成台词。"})

    def test_whole_native_trial_singleton_tail_and_exact20_metadata_factory(self):
        self.singleton_geometry()
        fixture = self.native()
        self.assertEqual([len(row["scored_ids"]) for row in fixture["rows"]], [4, 4, 1])
        self.assertEqual([a["stage"] for a in fixture["rows"][-1]["attempts"]], ["joint-unit-translation"])
        admission = self.authenticate(fixture)
        accepted = custody._read(admission)
        self.assertTrue(accepted["native_complete"])
        self.assertEqual(accepted["scheduled_batches"], 3)
        self.assertEqual(accepted["original_cost_count"], 1)
        self.assertEqual(accepted["new_generation_calls"], 0)
        proof = main.build_main_proof(admission=admission, expected_admission_sha256=admission["sha256"],
            authority=fixture["authority"], expected_authority_sha256=fixture["authority"]["sha256"],
            output=self.root / "singleton-main.json")
        self.assertEqual(set(custody._read(proof)), custody.MAIN_FIELDS)
        seal = self.write("singleton-seal.json", {"schema": main.SEAL_SCHEMA,
            "state": "root_reviewed_original_main_proofs", "verifier": main.identity(Path(main.__file__)),
            "authority": fixture["authority"], "proofs": [{"seed": 20261008, "role": "candidate",
                                                         "proof": proof, "admission": admission}]})
        validator = main.make_main_validator(seal=seal, expected_seal_sha256=seal["sha256"])
        with patch.object(custody, "_stage_material", side_effect=AssertionError("Metadata callback cannot replay material")):
            self.assertEqual(validator(proof, seed=20261008, role="candidate", external_registration=self.external),
                             custody._read(proof))

    def test_illegal_singleton_planning_attempt_is_rejected_not_skipped(self):
        row, window, item, root, _, _ = self.singleton_row()
        injected = deepcopy(row["attempts"][0])
        injected["stage"] = "source-planning"
        row["attempts"].insert(0, injected)
        with self.assertRaisesRegex(ValueError, "stage was dispatched without its accepted upstream"):
            main._all_attempts(row, window, item, root)

    def test_wrong_deterministic_singleton_plan_is_rejected(self):
        row, window, item, root, _, _ = self.singleton_row()
        row["planning_provenance"]["deterministic_single_target"] = False
        with self.assertRaisesRegex(ValueError, "retained plan/provenance"):
            main._all_attempts(row, window, item, root)

    def test_multiple_target_missing_planner_is_rejected(self):
        row, window, item, root, _, _ = self.singleton_row()
        window["translate_ids"] = ["target", "after"]
        row.pop("semantic_plan")
        self.assertEqual(set(main._stage_specs(row, window, item)), {"source-planning"})
        with self.assertRaisesRegex(ValueError, "stage was dispatched without its accepted upstream"):
            main._all_attempts(row, window, item, root)

    def test_one_joined_unit_does_not_allow_multiple_target_planning_skip(self):
        _, window, item, _, _, _ = self.singleton_row()
        window["translate_ids"] = ["target", "after"]
        planned = partition.parse_planning(json.dumps({"boundaries": [{"join": True,
            "evidence_ids": ["target", "after"], "uncertain": False}]}), window)
        self.assertEqual(len(planned["semantic_plan"]["units"]), 1)
        self.assertIn("source-planning", main._stage_specs(planned, window, item))

    def test_failed_singleton_native_attempts_remain_failed_and_costed(self):
        row, window, item, root, client, limits = self.singleton_row(
            outputs=[result({"translations": {"wrong": "无效。"}})] * 2)
        attempts = main._all_attempts(row, window, item, root)
        self.assertEqual(row["status"], "translation_failed")
        self.assertEqual(row["failure_stage"], "joint-unit-translation")
        self.assertEqual([a["status"] for a in attempts], ["failed", "failed"])
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(limits.translation_calls, 2)
        self.assertFalse(row["translations"])

    def test_unknown_stage_does_not_gain_singleton_skip_authority(self):
        row, window, item, root, _, _ = self.singleton_row()
        row["attempts"][0]["stage"] = "unregistered-stage"
        with self.assertRaisesRegex(ValueError, "stage order"):
            main._all_attempts(row, window, item, root)

    def test_mapping_grammar_complexity_retains_native_without_fake_mapper(self):
        row, window, item, root, client, _ = self.singleton_row()
        window["translate_ids"] = ["target", "after"]
        item["partition_grammar_limits"] = {"max_states": 1, "max_grammar_bytes": 1}
        client.outputs = [result({"boundaries": [{"join": True, "evidence_ids": ["target", "after"],
                                                     "uncertain": False}]}),
                          result({"translations": {"u1": "合成联合台词。"}})]
        row = worker.run_window(client, window, item, 8192, budget(),
                                {"verified": False, "first_response_checked": False})
        self.assertEqual(row["status"], "mapping_unjudgeable")
        attempts = main._all_attempts(row, window, item, root)
        self.assertEqual([a["stage"] for a in attempts], ["source-planning", "joint-unit-translation"])
        self.assertEqual(row["native_unit_translations"], {"u1": "合成联合台词。"})
        self.assertEqual(row["mapping_cost"]["completion_calls"], 0)
        self.assertFalse(row["translations"])
