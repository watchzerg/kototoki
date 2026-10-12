"""Synthetic native bytes and pure frozen-frame regressions; no real assets."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval import runner as e
from experiments.translation_flow import v2_consistency as c
from experiments.translation_flow import v2_consistency_custody as custody
from experiments.translation_flow import v2_consistency_pair_bridge as bridge
from experiments.translation_flow import v2_unit_main_proof as main
from experiments.translation_flow import v2_unit_custody as unit
from experiments.translation_flow import test_v2_consistency as pure_fixtures
from experiments.translation_flow import test_v2_consistency_custody as native_fixtures
from experiments.translation_flow import test_v2_unit_main_proof as main_fixtures


class PairFrameTests(unittest.TestCase):
    def setUp(self):
        self.fixture = pure_fixtures.ConsistencyTests()
        self.fixture.setUp()
        self.source = {"source_manifest": {"path": "synthetic-source", "sha256": "1" * 64},
                       "source_scenes": {"path": "synthetic-scenes", "sha256": "2" * 64},
                       "source_freeze": {"path": "synthetic-freeze", "sha256": "3" * 64}}
        frame = self.fixture.frame()
        self.pairs = []
        for seed in c.SEEDS:
            p = self.fixture.b_packet()
            proof = {row["batch_id"]: {"status": "verified", "options_sha256": "unused", "visibility_sha256": "unused"}
                     for row in p["judge_packet"]["exposures"]}
            # Obtain the exact projection hashes from the original pure API.
            from experiments.translation_flow.v2_source_projection import project, TERMS
            prepared = frame["parsed"][str(seed)][self.fixture.scene["id"]]
            for batch in self.fixture.batches:
                scene = self.fixture.scene
                window = {**scene, "id": batch["id"], "context": [q for q in scene["context"] if q["id"] in batch["target_ids"]],
                          "translate_ids": batch["target_ids"]}
                result = project("terms", "eligibility-filtered-proposals-v1", TERMS, prepared, window)
                proof[batch["id"]] = {"status": "verified", "options_sha256": c.object_hash(result["options"]),
                                      "visibility_sha256": c.object_hash(result["visibility"])}
            self.pairs.append({"group_id": "F6-terms-proposals-max32", "seed": seed, "mode": "terms",
                "source_registration": {"path": "registered-source", "sha256": "4" * 64},
                "pair_authority": {"path": "registered-pairs", "sha256": "5" * 64},
                "external_registration": {"path": "external", "sha256": "6" * 64},
                "status": "authenticated_material", "scene_ids": [self.fixture.scene["id"]],
                "scenes": [self.fixture.scene], "source_scope": {"path": "scope", "sha256": "7" * 64},
                "max_items": 32, "baseline_batches": self.fixture.batches, "treated_batches": self.fixture.batches,
                "projection": TERMS, "preparation_recipe": {"mode": "terms", "settings": {"max_items": 32}},
                "preparations": frame["inputs"]["preparations"][str(seed)], "deliveries": {self.fixture.scene["id"]: self.fixture.deliveries()},
                "exposure_proofs": proof, "role_execution": {"control": {"recipe": "c0"}, "candidate": {"recipe": "base-json"}},
                "role_provenance": {"control": {"executed": 17, "captured": 70, "replay": 9}, "candidate": {"seed": seed}},
                "original_cost_identities": [{"path": f"original-control-{seed}", "sha256": "8" * 64},
                                             {"path": f"original-candidate-{seed}", "sha256": "9" * 64}]})

    def test_three_seed_frozen_helper_packet_and_schema_parity(self):
        value = bridge._frames(self.pairs, self.source)
        self.assertEqual(len(value["expected_slots"]), 6)
        self.assertEqual(len(value["jobs"]), 6)
        self.assertEqual(value["frames"]["B"], self.fixture.frame())
        for job in value["jobs"]:
            p = c.validate_packet(job["envelope"])
            response = self.fixture.a_response(job["envelope"]) if p["phase"] == "A" else self.fixture.b_response(job["envelope"])
            c.validate_response(job["envelope"], response)

    def test_missing_duplicate_or_wrong_seed_is_not_normalized(self):
        for pairs in (self.pairs[:-1], [self.pairs[0]] * 3, list(reversed(self.pairs))):
            with self.assertRaises(ValueError):
                bridge._frames(pairs, self.source)

    def test_same_role_configuration_changes_fail(self):
        for key, value in (("max_items", 16), ("projection", "source-only-control-v1"),
                           ("preparation_recipe", {"settings": {"max_items": 16}}),
                           ("role_execution", {"control": {"recipe": "c0"}, "candidate": {"recipe": "other"}})):
            pairs = deepcopy(self.pairs)
            pairs[1][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "invariants"):
                bridge._frames(pairs, self.source)

    def test_descriptive_per_seed_provenance_does_not_fake_execution_equality(self):
        pairs = deepcopy(self.pairs)
        for pair in pairs:
            pair["role_provenance"]["candidate"].update(label=f"seed-{pair['seed']}", lineage=f"original-{pair['seed']}")
        self.assertEqual(len(bridge._frames(pairs, self.source)["jobs"]), 6)

    def test_unstarted_MAIN_is_not_normalized_into_executed_configuration(self):
        pairs = deepcopy(self.pairs)
        for pair in pairs:
            pair["role_execution"]["candidate"]["actual_main"] = {"n_predict": 4096}
        pairs[1]["role_execution"]["candidate"]["actual_main"] = None
        for pair in pairs:
            pair["main_source_partitions"] = {"control": pair["baseline_batches"], "candidate": pair["treated_batches"]}
        pairs[1]["main_source_partitions"]["candidate"] = None
        value = bridge._frames(pairs, self.source)
        self.assertEqual(len(value["expected_slots"]), 6)
        self.assertIsNone(pairs[1]["role_execution"]["candidate"]["actual_main"])
        pairs[2]["role_execution"]["candidate"]["actual_main"]["n_predict"] = 2048
        with self.assertRaisesRegex(ValueError, "invariants"):
            bridge._frames(pairs, self.source)

    def test_actual_partition_changes_cannot_hide_behind_not_run_seed(self):
        pairs = deepcopy(self.pairs)
        for pair in pairs:
            pair["main_source_partitions"] = {"control": pair["baseline_batches"], "candidate": deepcopy(pair["treated_batches"])}
        pairs[1]["main_source_partitions"]["candidate"] = None
        pairs[2]["main_source_partitions"]["candidate"][0]["readonly_ids"] = ["j2"]
        with self.assertRaisesRegex(ValueError, "invariants"):
            bridge._frames(pairs, self.source)

    def test_one_unsupported_terminal_blocks_three_seed_frame_without_fake_preparations(self):
        pairs = deepcopy(self.pairs)
        pairs[1] = {k: v for k, v in pairs[1].items() if k in {"seed", "group_id", "mode", "source_registration", "pair_authority",
            "external_registration", "scene_ids", "original_cost_identities", "source_scope", "baseline_batches", "role_execution"}}
        pairs[1]["status"] = "admission_blocked_unknown"
        value = bridge._frames(pairs, self.source)
        self.assertEqual(value["frames"], {"A": None, "B": None})
        self.assertEqual(value["jobs"], [])
        self.assertEqual(len(value["expected_slots"]), 6)
        self.assertTrue(all(slot["status"] == "admission_blocked_unknown" for slot in value["expected_slots"]))
        self.assertEqual(len(value["original_cost_identities"]), 6)
        for key, changed in (("source_scope", {"path": "wrong-source", "sha256": "0" * 64}),
                             ("baseline_batches", []), ("role_execution", {"control": {"recipe": "other"}})):
            bad = deepcopy(pairs)
            bad[1][key] = changed
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "historical control"):
                bridge._frames(bad, self.source)

    def test_missing_preparation_slots_remain_unknown_in_original_frame(self):
        pairs = deepcopy(self.pairs)
        pairs[1]["preparations"][0].update(status="preparation_failed", raw_response=None, reason="synthetic failed AUX")
        value = bridge._frames(pairs, self.source)
        self.assertEqual(value["frames"]["B"]["coverage"][self.fixture.scene["id"]]["missing_preparation_slots"], 1)
        self.assertEqual(len(value["expected_slots"]), 6)

    def test_zero_inventory_does_not_claim_consistency_success(self):
        pairs = deepcopy(self.pairs)
        for pair in pairs:
            pair["preparations"][0]["raw_response"] = '{"terms":[]}'
        value = bridge._frames(pairs, self.source)
        self.assertEqual(value["jobs"], [])
        self.assertTrue(all(slot["status"] == "not_assessed_zero_inventory" for slot in value["expected_slots"]))

    def test_opaque_exposure_hash_cannot_pass_frozen_derivation(self):
        pairs = deepcopy(self.pairs)
        pairs[0]["exposure_proofs"]["batch0"]["options_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "exposure proof changed"):
            bridge._frames(pairs, self.source)

    def test_duplicate_cost_identity_cannot_create_six_original_runs(self):
        pairs = deepcopy(self.pairs)
        pairs[1]["original_cost_identities"][0] = pairs[0]["original_cost_identities"][0]
        with self.assertRaisesRegex(ValueError, "Six distinct"):
            bridge._frames(pairs, self.source)
        pairs[1]["original_cost_identities"][0] = {**pairs[0]["original_cost_identities"][0],
            "path": str(Path(pairs[0]["original_cost_identities"][0]["path"]).resolve().parent / "unused" / ".."
                        / Path(pairs[0]["original_cost_identities"][0]["path"]).name)}
        with self.assertRaisesRegex(ValueError, "Six distinct"):
            bridge._frames(pairs, self.source)

    def background_pairs(self):
        from experiments.translation_flow.v2_source_projection import SCENE_CARD, project
        rows = [{"text": "他一定会来。", "uncertain": True,
                 "evidence": [{"id": "j3", "quote": "来るかもしれない"}]}]
        frame = self.fixture.frame(mode="background", rows=rows, max_items=16)
        proofs = {}
        prepared = frame["parsed"][str(c.SEEDS[0])][self.fixture.scene["id"]]
        for batch in self.fixture.batches:
            window = {**self.fixture.scene, "id": batch["id"], "translate_ids": batch["target_ids"],
                      "context": [q for q in self.fixture.scene["context"] if q["id"] in batch["target_ids"]]}
            result = project("background", "quoted-background-with-uncertainty-v1", SCENE_CARD, prepared, window)
            proofs[batch["id"]] = {"status": "verified", "options_sha256": c.object_hash(result["options"]),
                                    "visibility_sha256": c.object_hash(result["visibility"])}
        pairs = deepcopy(self.pairs)
        for pair in pairs:
            pair.update(group_id="F7-evidence-scene-card", mode="background", max_items=16,
                        projection=SCENE_CARD, preparations=frame["inputs"]["preparations"][str(pair["seed"])],
                        preparation_recipe={"mode": "background", "settings": {"max_items": 16}},
                        exposure_proofs=proofs)
        return pairs

    def test_F7_without_term_donor_keeps_all_A_slots_unassessed(self):
        value = bridge._frames(self.background_pairs(), self.source)
        self.assertIsNone(value["frames"]["A"])
        self.assertEqual(len(value["expected_slots"]), 6)
        self.assertEqual(len(value["jobs"]), 3)
        self.assertTrue(all(row["status"] == "term_inventory_unavailable"
                            for row in value["expected_slots"] if row["phase"] == "A"))

    def test_F7_exact_term_donor_preserves_original_A_B_validators(self):
        value = bridge._frames(self.background_pairs(), self.source, self.fixture.frame())
        self.assertEqual(len(value["jobs"]), 6)
        for job in value["jobs"]:
            packet = c.validate_packet(job["envelope"])
            response = (self.fixture.a_response(job["envelope"]) if packet["phase"] == "A"
                        else self.fixture.b_response(job["envelope"], uncertainty=True))
            c.validate_response(job["envelope"], response)

    def test_F7_term_donor_cannot_change_source_text_or_C0_partition(self):
        for key in ("text", "partition"):
            fixture = pure_fixtures.ConsistencyTests()
            fixture.setUp()
            if key == "text":
                fixture.scene["context"][0]["text"] = "翼がない。"
            else:
                fixture.batches[0]["readonly_ids"] = ["j2"]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "exact complete source"):
                bridge._frames(self.background_pairs(), self.source, fixture.frame())


class NativeMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with redirect_stdout(io.StringIO()):
            cls.native = native_fixtures.NativeConsistencyFixture(native_v5_metadata=True,
                card_options={"terms": [], "background": [], "style": "neutral", "review": False},
                treated_target_sizes={seed: 5 for seed in c.SEEDS})
        cls.addClassCleanup(cls.native.close)

    def setUp(self):
        fixture, seed = self.native, c.SEEDS[0]
        self.scope, self.scenes, originals = custody._source(fixture.scope)
        self.originals = {sid: originals[sid] for sid in self.scope["scene_ids"]}
        root = fixture.roots[seed, "treated"]
        terminal = e.read_json(root / "trial-completion.json")
        card = e.read_json(fixture.cards[seed, "treated"])
        slots, _, _ = custody._auxiliary(root, card, terminal, self.scope, self.scenes, fixture.runtime)
        self.proof = {"trial_root": str(root.resolve()), "card": custody.identity(fixture.cards[seed, "treated"]),
            "original_trial_attempt_identity": custody.identity(root / "trial-completion.json"),
            "source_preparation_slots": [{k: v for k, v in row.items() if k != "raw_response"} for row in slots],
            "source": fixture.scope, "scope": {"scene_ids": self.scope["scene_ids"]}, "native_complete": True}
        self.auth = {"runtime": fixture.runtime, "source_scope": fixture.scope}

    def load_native(self, proof=None):
        # Exercise original native material APIs on supported all-success
        # fixtures. Production uses the independently pinned owner loader,
        # including its separately tested failed-first-HTTP/cache behavior.
        proof = proof or self.proof
        root = Path(proof["trial_root"])
        card, terminal = e.read_json(custody._pointer(proof["card"])), e.read_json(custody._pointer(proof["original_trial_attempt_identity"]))
        slots, plan, _ = custody._auxiliary(root, card, terminal, self.scope, self.scenes, self.auth["runtime"])
        current = custody._main(root, card, terminal, self.scope, self.scenes, self.originals, self.auth["runtime"], preparation_plan=plan)
        return {"scope": self.scope, "scenes": self.scenes, "originals": self.originals, "card": card,
                "terminal": terminal, "source_preparation_slots": slots, "source_preparation_plan": plan,
                "main": current, "card_provenance": custody._card_provenance(card, proof["card"]), "proof": proof}

    def test_native_preparation_and_actual_target_exposure_are_reauthenticated(self):
        material = bridge._candidate_material(self.proof, self.load_native(), self.scope, self.scenes, self.originals)
        self.assertEqual(material["max_items"], 32)
        self.assertEqual(len(material["preparations"]), 2)
        self.assertTrue(all(row["status"] == "verified" for row in material["exposure_proofs"].values()))
        self.assertEqual(material["cost_identity"], self.proof["original_trial_attempt_identity"])
        self.assertEqual(material["execution"]["actual_main"]["n_predict"], 4096)

    def test_metadata_only_proof_does_not_override_original_preparation_slots(self):
        bad = deepcopy(self.proof)
        bad["source_preparation_slots"][0]["status"] = "not_run"
        with self.assertRaisesRegex(ValueError, "whole-native admission"):
            bridge._candidate_material(bad, self.load_native(bad), self.scope, self.scenes, self.originals)

    def test_source_and_snapshot_tampering_remains_native_rejection(self):
        root = Path(self.proof["trial_root"])
        path = next((root / "execution/runtime-run/translation/source").rglob("v2_worker.py"))
        before = path.read_bytes()
        try:
            path.write_bytes(before + b"\n# synthetic tamper\n")
            with self.assertRaises(ValueError):
                self.load_native()
        finally:
            path.write_bytes(before)

    def test_missing_canonical_delivery_is_never_partial_material_success(self):
        path = Path(self.proof["trial_root"]) / "delivery/delivery.json"
        original = path.read_bytes()
        loaded = self.load_native()
        try:
            path.unlink()
            with self.assertRaisesRegex(ValueError, "unsupported"):
                bridge._candidate_material(self.proof, loaded, self.scope, self.scenes, self.originals)
        finally:
            path.write_bytes(original)

    def test_v5_descriptive_lineage_is_separate_and_unknown_fields_rejected(self):
        card = e.read_json(self.native.cards[c.SEEDS[0], "treated"])
        before = custody._main_recipe(card)
        changed = deepcopy(card)
        changed.update(id="descriptive", notes="synthetic lineage", seed=c.SEEDS[0], recipe_id=card["prepare"]["recipe_id"])
        self.assertEqual(custody._main_recipe(changed), before)
        for mutate in (lambda x: x.update(unregistered_execution=True),
                       lambda x: x.update(seed=c.SEEDS[1]),
                       lambda x: x["prepare"].update(options={"review": True})):
            bad = deepcopy(changed)
            mutate(bad)
            with self.assertRaises(ValueError):
                custody._main_recipe(bad)


class NativePartialAuxiliaryTests(unittest.TestCase):
    def test_genuine_partial_AUX_preserves_prepared_failed_slots_and_MAIN_not_run(self):
        with redirect_stdout(io.StringIO()):
            fixture = native_fixtures.NativeConsistencyFixture(partial_aux=True, native_v5_metadata=True,
                card_options={"terms": [], "background": [], "style": "neutral", "review": False})
        self.addCleanup(fixture.close)
        scope, scenes, originals = custody._source(fixture.scope)
        seed = c.SEEDS[0]
        root = fixture.roots[seed, "treated"]
        card = e.read_json(fixture.cards[seed, "treated"])
        terminal = e.read_json(root / "trial-completion.json")
        slots, plan, _ = custody._auxiliary(root, card, terminal, scope, scenes, fixture.runtime)
        missing = custody._main(root, card, terminal, scope, scenes, originals, fixture.runtime, preparation_plan=plan)
        self.assertTrue(missing["missing"])
        self.assertFalse((root / "execution").exists())
        proof = {"trial_root": str(root.resolve()), "card": custody.identity(fixture.cards[seed, "treated"]),
            "original_trial_attempt_identity": custody.identity(root / "trial-completion.json"),
            "source_preparation_slots": [{k: v for k, v in row.items() if k != "raw_response"} for row in slots],
            "scope": {"scene_ids": scope["scene_ids"]}, "native_complete": False}
        loaded = {"scope": scope, "scenes": scenes, "originals": originals, "card": card, "terminal": terminal,
                  "source_preparation_slots": slots, "source_preparation_plan": plan, "main": missing,
                  "card_provenance": custody._card_provenance(card, proof["card"]), "proof": proof}
        control_root = fixture.roots[seed, "baseline"]
        control_card = e.read_json(fixture.cards[seed, "baseline"])
        control_terminal = e.read_json(control_root / "trial-completion.json")
        baseline = custody._main(control_root, control_card, control_terminal, scope, scenes, originals, fixture.runtime)
        material = bridge._candidate_material(proof, loaded, scope, scenes, originals, baseline_batches=baseline["batches"])
        self.assertEqual([row["status"] for row in material["preparations"]], ["prepared", "preparation_failed"])
        self.assertIsNone(material["execution"]["actual_main"])
        self.assertTrue(material["provenance"]["main_execution_not_started"])
        self.assertEqual(material["provenance"]["whole_native"]["original_trial_attempt_identity"], proof["original_trial_attempt_identity"])
        self.assertEqual(material["cost_identity"], proof["original_trial_attempt_identity"])
        self.assertTrue(all(row["status"] == "not_run" and row["text"] is None
                            for states in material["aggregate"]["scenes"].values() for row in states.values()))
        self.assertTrue(all(row["status"] == "missing" for row in material["exposure_proofs"].values()))


class HistoricalNativeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = main_fixtures.MainProofTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def make(self):
        native = self.fixture.native(control=True)
        run_path = native["label"] / "run.json"
        run = e.read_json(run_path)
        session = native["label"].parent
        for index in range(70 - len(run["code_sha256"])):
            relative = f"synthetic-captured-unused/{index}.py"
            path = session / "source" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"# captured fixture only; never executed\n")
            run["code_sha256"][relative] = e.sha(path)
        self.fixture.put(run_path, run)
        session_value = e.read_json(session / "session.json")
        session_value["code_sha256"] = run["code_sha256"]
        self.fixture.put(session / "session.json", session_value)
        document_path = native["root"] / "delivery/delivery.json"
        document = e.read_json(document_path)
        document["artifacts"] = [main.identity(Path(ptr["path"])) for ptr in document["artifacts"]]
        self.fixture.put(document_path, document)
        # Register the completed SYNTHETIC capture before its first admission;
        # no sealed historical artifact is changed by this fixture construction.
        archive = self.fixture.write("synthetic-full70-archive.json", {"fresh_output_audits": [{
            "seed": c.SEEDS[0], "fresh_original_run": main.identity(run_path),
            "fresh_ledger": main.identity(native["label"] / "ledger.jsonl"),
            "matched_batches": len(e.load_jsonl(native["label"] / "inputs.jsonl"))}]})
        auth = e.read_json(custody._pointer(native["authority"]))
        auth["entries"][0]["historical_authorities"]["workload_archive"] = archive
        native["authority"] = self.fixture.write("synthetic-full70-authority.json", auth)
        admission = self.fixture.authenticate(native)
        proof = main.build_main_proof(admission=admission, expected_admission_sha256=admission["sha256"],
            authority=native["authority"], expected_authority_sha256=native["authority"]["sha256"], output=self.fixture.root / "control-main-proof.json")
        seal = self.fixture.write("control-seal.json", {"schema": main.SEAL_SCHEMA, "state": "root_reviewed_original_main_proofs",
            "verifier": main.identity(Path(main.__file__)), "authority": native["authority"],
            "proofs": [{"seed": c.SEEDS[0], "role": "control", "proof": proof, "admission": admission}]})
        validator = main.make_main_validator(seal=seal, expected_seal_sha256=seal["sha256"])
        registered = unit.validate_registered_frame(self.fixture.registration, self.fixture.external,
            expected_registration_sha256=self.fixture.registration["sha256"], expected_external_sha256=self.fixture.external["sha256"])
        retained, intake = unit._main(proof, seed=c.SEEDS[0], role="control", registered=registered,
            external_registration=self.fixture.external, validator=validator)
        return retained, intake, custody._pointer(admission)

    def test_historical17_captured70_replay9_real_native_intake_retains_cost_and_source(self):
        proof, intake, admission_path = self.make()
        admission = e.read_json(admission_path)
        self.assertEqual(len(admission["declared_executed_snapshots"]), 17)
        self.assertEqual(len(admission["captured_executed_snapshots"]), 70)
        self.assertEqual(len(admission["approved_parser_snapshots"]), 9)
        originals = {row["id"]: row for row in intake["data"]["packed"]["scenes"]}
        material = bridge._historical_material(proof, intake, originals)
        self.assertEqual(material["cost_identity"], proof["original_generation_cost_identity"])
        self.assertEqual(material["provenance"]["native_stage"], proof["native_stage"])
        self.assertEqual(material["execution"]["actual_main"]["recipe"], "c0")

    def test_same_id_changed_text_time_or_order_cannot_bridge_original_control(self):
        proof, intake, _ = self.make()
        for key, value in (("text", "changed synthetic source"), ("start_ms", 9999)):
            originals = {row["id"]: deepcopy(row) for row in intake["data"]["packed"]["scenes"]}
            originals[next(iter(originals))]["context"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "source text/time/order"):
                bridge._historical_material(proof, intake, originals)


class RegisteredMetadataTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".local" / "bridge-registration-synthetic-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scope = self.write("scope.json", {"version": "hy30-consistency-source-scope-v1", "split": "screen-a",
            "state": "frozen_before_consistency_quality", "quality_inspected": False, "scene_ids": ["synthetic1", "synthetic2"]})
        self.source = self.write("source-registration.json", {"schema": bridge.SOURCE_SCHEMA,
            "state": "source_only_scope_registered_for_consistency", "source_scope": self.scope,
            "ordered_scene_ids": ["synthetic1", "synthetic2"], "generation_seeds": list(c.SEEDS)})
        placeholder = self.write("not-a-material-proof.json", {"synthetic_registration_fixture_only": True})
        self.pair_value = {"schema": bridge.PAIR_SCHEMA, "state": "retained_control_and_preregistered_candidate",
            "source_registration": self.source, "implementation": bridge.implementation(), "generation_seeds": list(c.SEEDS),
            "groups": {"F6-terms-proposals-max32": {"mode": "terms", "control_seal": placeholder,
                "control_external_registration": placeholder, "candidate_authority": placeholder,
                "slots": [{"seed": seed, "role": role, "kind": "main_proof" if role == "control" else "native_proof",
                           "evidence": placeholder} for seed in c.SEEDS for role in ("control", "candidate")]}}}
        self.pair = self.write("pair-authority.json", self.pair_value)
        self.external = self.external_for(self.pair)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        e.dump(path, value)
        return custody.identity(path)

    def external_for(self, pair):
        return self.write("external.json", {"schema": bridge.EXTERNAL_SCHEMA,
            "state": "root_registered_before_actual_consistency_calls", "source_registration": self.source,
            "pair_authority": pair, "implementation": bridge.implementation()})

    def validate(self, pair=None, external=None):
        pair, external = pair or self.pair, external or self.external
        return bridge._registration(self.source, pair, external, self.source["sha256"], pair["sha256"], external["sha256"])

    def test_registration_does_not_decode_material_or_claim_dispatch_authority(self):
        source, pair, scope = self.validate()
        self.assertEqual(scope["scene_ids"], ["synthetic1", "synthetic2"])
        self.assertEqual(pair["state"], "retained_control_and_preregistered_candidate")
        self.assertNotIn("approved_before_generation", pair["state"])

    def test_missing_seed_role_unknown_slot_kind_or_changed_group_rejected(self):
        mutations = [lambda p: p["groups"]["F6-terms-proposals-max32"]["slots"].pop(),
                     lambda p: p["groups"]["F6-terms-proposals-max32"]["slots"][0].update(kind="native_proof"),
                     lambda p: p["groups"]["F6-terms-proposals-max32"].update(mode="background"),
                     lambda p: p.update(generation_seeds=[c.SEEDS[0]] * 3),
                     lambda p: p.update(approved=True)]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                bad = deepcopy(self.pair_value)
                mutate(bad)
                ptr = self.write(f"bad-{index}.json", bad)
                with self.assertRaises(ValueError):
                    self.validate(ptr, self.external_for(ptr))

    def test_missing_or_tampered_expected_proof_is_authentication_failure(self):
        path = Path(self.pair_value["groups"]["F6-terms-proposals-max32"]["slots"][0]["evidence"]["path"])
        before = path.read_bytes()
        try:
            path.write_bytes(before + b" ")
            with self.assertRaises(ValueError):
                self.validate()
            path.unlink()
            with self.assertRaises((ValueError, OSError)):
                self.validate()
        finally:
            path.write_bytes(before)

    def test_external_authority_cannot_redirect_scope_or_code(self):
        value = e.read_json(custody._pointer(self.external))
        for key, replacement in (("source_registration", self.pair), ("implementation", {})):
            bad = deepcopy(value)
            bad[key] = replacement
            ptr = self.write(f"bad-external-{key}.json", bad)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(external=ptr)

    def unsupported_fixture(self):
        root = self.root / "unsupported-native"
        (root / "execution").mkdir(parents=True)
        (root / "execution/native-started.json").write_text('{"synthetic":true}', encoding="utf-8")
        card = self.write("unsupported-card.json", {"prepare": {"seed": c.SEEDS[0]}})
        terminal = self.write("unsupported-native/trial-completion.json", {"schema": "hy30-flow-trial-v2",
            "status": "partial", "card": e.read_json(custody._pointer(card)), "card_path": card["path"],
            "card_sha256": card["sha256"], "failed_phase": "main", "error": "synthetic canonical delivery absent",
            "total_flow_seconds": 7.0, "phases": {"source_preparation": 2.0, "main": 5.0}})
        value = {"schema": bridge.UNKNOWN_SCHEMA, "state": "root_reviewed_unsupported_canonical_delivery",
            "candidate_group": "F6-terms-proposals-max32", "seed": c.SEEDS[0], "card": card,
            "trial_root": str(root.resolve()), "trial_completion": terminal,
            "retained_inventory": main._inventory(root), "reason": "canonical_delivery_missing", "original_cost_identity": terminal}
        seal = self.write("unsupported-seal.json", value)
        auth = {"entries": [{k: value[k] for k in ("candidate_group", "seed", "card", "trial_root", "trial_completion")}]}
        return seal, auth, value

    def test_explicit_unsupported_terminal_keeps_original_status_reason_and_cost(self):
        seal, auth, value = self.unsupported_fixture()
        result = bridge._unsupported(seal, gid="F6-terms-proposals-max32", seed=c.SEEDS[0], auth=auth)
        self.assertEqual(result["original_terminal"]["status"], "partial")
        self.assertEqual(result["original_terminal"]["total_flow_seconds"], 7.0)
        self.assertEqual(result["original_cost_identity"], value["trial_completion"])
        self.assertNotIn("preparations", result)

    def test_authenticated_candidate_proof_cannot_move_between_role_seed_entries(self):
        _, auth, value = self.unsupported_fixture()
        proof = {k: value[k] for k in ("candidate_group", "seed", "card", "trial_root")}
        proof["original_trial_attempt_identity"] = value["trial_completion"]
        bridge._candidate_slot(proof, gid=value["candidate_group"], seed=value["seed"], auth=auth)
        for key, replacement in (("seed", c.SEEDS[1]), ("seed", True),
                                  ("candidate_group", "F7-evidence-scene-card"),
                                  ("trial_root", str(self.root / "same-seed-sibling")),
                                  ("original_trial_attempt_identity", value["card"])):
            bad = deepcopy(proof)
            bad[key] = replacement
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "registered group/seed"):
                bridge._candidate_slot(bad, gid=value["candidate_group"], seed=value["seed"], auth=auth)

    def test_unsupported_terminal_cannot_promote_status_or_hide_canonical_material(self):
        seal, auth, value = self.unsupported_fixture()
        root = Path(value["trial_root"])
        (root / "delivery").mkdir()
        e.dump(root / "delivery/delivery.json", {"synthetic": True})
        with self.assertRaisesRegex(ValueError, "absence/inventory"):
            bridge._unsupported(seal, gid="F6-terms-proposals-max32", seed=c.SEEDS[0], auth=auth)

    def test_unsupported_terminal_missing_or_wrong_registered_identity_rejected(self):
        seal, auth, value = self.unsupported_fixture()
        for mutate in (lambda a: a["entries"].clear(), lambda a: a["entries"][0].update(seed=c.SEEDS[1])):
            changed = deepcopy(auth)
            mutate(changed)
            with self.assertRaisesRegex(ValueError, "registered original"):
                bridge._unsupported(seal, gid="F6-terms-proposals-max32", seed=c.SEEDS[0], auth=changed)


if __name__ == "__main__":
    unittest.main()
