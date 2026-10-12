"""Closed mixed partial routing: REAL factories, TEST root metadata only."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from experiments.translation_eval import runner as e
from experiments.translation_flow import v2_unit_role_seed_validator_partial as shared
LITERALS = {name: getattr(shared, name) for name in
            ("CONTROL_SEAL_SHA", "F5_EXTERNAL_SHA", "PROPAGATION_SHA", "PARTIAL_ACCEPTANCE_SHA")}

class PartialDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kototoki-v10-router-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.external = self.write("external.json", {"handwritten_root_external": True})

    def write(self, name, value):
        path = self.root / name
        e.dump(path, value)
        return shared.identity(path)

    def real_synthetic_registry(self):
        """Use both real metadata factories; only root authority pins are TEST fixtures.

        These handwritten sealed admissions are not whole-trial authentication.
        The existing prepared auxiliary view parser remains an explicit stub.
        No factory, registry parser, router or callback implementation is mocked.
        """
        router = shared
        leaf = self.write("router-fixture/leaf.json", {"handwritten_metadata_only": True})
        source = {name: leaf for name in ("manifest", "scenes", "freeze")}
        registration = self.write("router-fixture/registration.json", {
            "frame": leaf, "packed": [leaf], "cards": [leaf], "source_authority": source})
        propagation = self.write("summaries/F5-singleton-helper-version-v1/propagation-boundary.json",
                                 {"handwritten_TEST_propagation": True})
        acceptance = self.write("summaries/F5-partial-mainproof-root-offline-acceptance-v1.json",
                                {"handwritten_TEST_partial_acceptance": True})
        authorities, admissions, receipts, costs = {}, {}, {}, []
        control_rows = []
        for seed in shared.SEEDS:
            trial = self.root / "router-fixture" / f"empty-original-control-{seed}"
            trial.mkdir(parents=True)
            control_rows.append({"seed": seed, "role": "control", "card": leaf, "trial_root": str(trial),
                "trial_completion": leaf, "runtime": leaf, "declared_snapshot_count": 17,
                "historical_authorities": {field: leaf for field in router.control_factory.HISTORICAL_FIELDS},
                "scoring_derivation": None})
        for role in ("control", "candidate"):
            for seed in shared.SEEDS:
                factory = router.factory_for(role, seed)
                replay = self.write(f"router-fixture/{role}-{seed}-replay.json", {"schema": factory.REPLAY_SCHEMA,
                    "state": "root_approved_closed_parser_replay", "verifier": router.identity(Path(factory.__file__)),
                    "parsers": shared.unit_custody._dependencies(), "historical_behavior": leaf})
                trial = self.root / "router-fixture" / f"empty-original-{role}-{seed}"
                trial.mkdir(parents=True, exist_ok=True)
                entries = control_rows if role == "control" else [{"seed": seed, "role": role,
                    "card": leaf, "trial_root": str(trial), "trial_completion": leaf, "runtime": leaf,
                    "declared_snapshot_count": 21, "historical_authorities": None, "scoring_derivation": None}]
                authority = authorities["control", shared.SEEDS[0]] if role == "control" and seed != shared.SEEDS[0] else self.write(
                    f"router-fixture/{role}-{seed}-authority.json", {
                        "schema": factory.AUTHORITY_SCHEMA, "state": "root_approved_offline_original_authentication",
                        "registration": registration, "external_registration": self.external,
                        "verifier": router.identity(Path(factory.__file__)), "diagnostic_replay": replay, "entries": entries})
                authorities[role, seed] = authority
                metadata = {"role": role, "seed": seed, "card": leaf, "source_authority": source,
                    "retained": {field: leaf for field in shared.unit_custody.RETAINED_FIELDS},
                    "session_root": str(trial), "trial": {"start": leaf, "completion": leaf},
                    "actual_source_scope": {"split": "screen-a", "scene_ids": ["handwritten"],
                                           "source_cues": 0, "scored_windows": 0},
                    "original_source_authority": source, "scoring_derivation": None, "native_complete": False,
                    "generation_attempt_status": "terminal_partial" if role == "candidate" else "not_run",
                    "native_stage": "full-flow" if role == "control" else "screening",
                    "approved_parser_snapshots": shared.unit_custody._dependencies()}
                admission = self.write(f"router-fixture/{role}-{seed}-admission.json", {**metadata,
                    "schema": factory.ADMISSION_SCHEMA, "authority": authority, "session_provenance": [leaf],
                    "original_generation_run_identity": leaf, "inventory": []})
                admissions[role, seed] = admission
                cost = self.write(f"router-fixture/{role}-{seed}-cost.json", {
                    "schema": "hy30-F5-original-cost-authority-v1", "admission": admission,
                    "trial": metadata["trial"], "original_generation_run_identity": leaf, "original_cost_count": 1,
                    "new_generation_calls": 0, "new_samples": 0, "new_timing_measurements": 0})
                costs.append(cost)
                receipts[role, seed] = self.write(f"router-fixture/{role}-{seed}-proof.json", {**metadata,
                    "schema": shared.unit_custody.MAIN_PROOF_SCHEMA, "session_provenance": [leaf, admission],
                    "cost_authority": cost, "original_generation_cost_identity": cost, "terminal_authority": admission,
                    "external_registration": self.external if role == "candidate" else None})
        # One historical control seal owns all three original control proofs.
        control_authority = authorities["control", shared.SEEDS[0]]
        control_seal = self.write("router-fixture/control-seal.json", {
            "schema": router.control_factory.SEAL_SCHEMA, "state": "root_reviewed_original_main_proofs",
            "verifier": router.identity(Path(router.control_factory.__file__)), "authority": control_authority,
            "proofs": [{"role": "control", "seed": seed, "proof": receipts["control", seed],
                        "admission": admissions["control", seed]} for seed in shared.SEEDS]})
        slots = []
        for seed in shared.SEEDS:
            candidate_seal = self.write(f"router-fixture/candidate-{seed}-seal.json", {
                "schema": router.factory_for("candidate", seed).SEAL_SCHEMA, "state": "root_reviewed_original_main_proofs",
                "verifier": router.identity(Path(router.factory_for("candidate", seed).__file__)), "authority": authorities["candidate", seed],
                "proofs": [{"role": "candidate", "seed": seed, "proof": receipts["candidate", seed],
                            "admission": admissions["candidate", seed]}]})
            for role in ("candidate", "control"):
                slots.append({"seed": seed, "role": role, "receipt": receipts[role, seed],
                    "seal": candidate_seal if role == "candidate" else control_seal,
                    "authority": authorities[role, seed] if role == "candidate" else control_authority,
                    "unavailable_reason": None})
        self.addCleanup(patch.stopall)
        patch.multiple(router, BASE=self.root, CONTROL_SEAL_SHA=control_seal["sha256"],
                       F5_EXTERNAL_SHA=self.external["sha256"], PROPAGATION_SHA=propagation["sha256"], PARTIAL_ACCEPTANCE_SHA=acceptance["sha256"]).start()
        registry = self.write("router-fixture/registry.json", {"schema": router.REGISTRY_SCHEMA,
            "state": "root_reviewed_fixed_role_seed_slots", "dispatcher": router.identity(Path(router.__file__)),
            "propagation": propagation, "candidate_verifiers": router.candidate_verifiers(), "partial_acceptance": acceptance,
            "control_verifier": router.identity(Path(router.control_factory.__file__)),
            "control_seal": control_seal, "external_registration": self.external, "slots": slots})
        return registry, slots

    def callback(self):
        registry, rows = self.real_synthetic_registry()
        return registry, rows, shared.make_role_seed_main_validator(
            registry=registry, expected_registry_sha256=registry["sha256"])

    def test_all_six_real_role_seed_factories_and_exact_callback_source_pin(self):
        _, rows, callback = self.callback()
        own = shared.identity(Path(shared.__file__))
        shared.unit_custody._validator_pin(callback, own, own["sha256"])
        with self.assertRaises(ValueError):
            shared.unit_custody._validator_pin(callback, shared.identity(Path(shared.control_factory.__file__)), own["sha256"])
        for row in rows:
            proof = callback(row["receipt"], seed=row["seed"], role=row["role"], external_registration=self.external)
            self.assertEqual(proof, e.read_json(shared.bound(row["receipt"])))
            self.assertEqual(set(proof), shared.unit_custody.MAIN_FIELDS)
            self.assertEqual(proof["external_registration"], self.external if row["role"] == "candidate" else None)
            self.assertFalse(proof["native_complete"])

    def test_wrong_seed_role_external_or_receipt_cannot_enter_factory(self):
        _, rows, callback = self.callback()
        for seed, role, receipt, external in (
                (shared.SEEDS[1], "candidate", rows[0]["receipt"], self.external),
                (shared.SEEDS[0], "control", rows[0]["receipt"], self.external),
                (True, "candidate", rows[0]["receipt"], self.external),
                (shared.SEEDS[0], "candidate", rows[0]["receipt"], {"path": "other", "sha256": "0" * 64})):
            with self.subTest(seed=seed, role=role), self.assertRaises(ValueError):
                callback(receipt, seed=seed, role=role, external_registration=external)

    def test_unavailable_slot_never_returns_fabricated_proof_but_control_can_complete(self):
        registry, rows, _ = self.callback()
        doc = e.read_json(shared.bound(registry))
        doc["slots"][0].update(receipt=None, seal=None, authority=None, unavailable_reason="Administrative proof pending")
        other = self.write("unavailable.json", doc)
        callback = shared.make_role_seed_main_validator(registry=other, expected_registry_sha256=other["sha256"])
        with self.assertRaises(ValueError):
            callback(rows[0]["receipt"], seed=shared.SEEDS[0], role="candidate", external_registration=self.external)
        self.assertEqual(callback(rows[1]["receipt"], seed=shared.SEEDS[0], role="control", external_registration=self.external),
                         e.read_json(shared.bound(rows[1]["receipt"])))

    def test_fixed_order_scope_and_unavailable_reason_are_closed(self):
        registry, _, _ = self.callback()
        original = e.read_json(shared.bound(registry))
        variants = []
        value = deepcopy(original); value["slots"].pop(); variants.append(value)
        value = deepcopy(original); value["slots"].reverse(); variants.append(value)
        value = deepcopy(original); value["slots"][0]["seed"] = True; variants.append(value)
        value = deepcopy(original); value["slots"][0]["unavailable_reason"] = "pending"; variants.append(value)
        value = deepcopy(original); value["slots"][1].update(receipt=None, seal=None, authority=None, unavailable_reason="missing control"); variants.append(value)
        for index, value in enumerate(variants):
            pointer = self.write(f"bad-registry-{index}.json", value)
            with self.subTest(index=index), self.assertRaises(ValueError):
                shared.validate_registry(pointer, pointer["sha256"])

    def test_helper_dispatcher_and_literal_external_control_pins_are_required(self):
        registry, _, _ = self.callback()
        original = e.read_json(shared.bound(registry))
        for name in ("dispatcher", "candidate_verifiers", "control_verifier", "partial_acceptance"):
            value = deepcopy(original); value[name] = value["external_registration"]
            pointer = self.write(f"bad-{name}.json", value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                shared.validate_registry(pointer, pointer["sha256"])
        for name, literal in (("CONTROL_SEAL_SHA", LITERALS["CONTROL_SEAL_SHA"]), ("F5_EXTERNAL_SHA", LITERALS["F5_EXTERNAL_SHA"]),
                              ("PROPAGATION_SHA", LITERALS["PROPAGATION_SHA"]), ("PARTIAL_ACCEPTANCE_SHA", LITERALS["PARTIAL_ACCEPTANCE_SHA"])):
            with self.subTest(name=name), patch.object(shared, name, literal), self.assertRaises(ValueError):
                shared.validate_registry(registry, registry["sha256"])
        with self.assertRaises(ValueError):
            shared.validate_registry(registry, "0" * 64)

    def test_candidate_helper_and_authority_cannot_be_swapped_or_aggregated(self):
        registry, rows, _ = self.callback()
        original = e.read_json(shared.bound(registry))
        for name in ("seal", "authority"):
            value = deepcopy(original); value["slots"][0][name] = rows[1][name]
            ptr = self.write(f"bad-candidate-{name}.json", value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                shared.validate_registry(ptr, ptr["sha256"])
        value = deepcopy(original)
        sealed = e.read_json(shared.bound(rows[0]["seal"]))
        sealed["proofs"].append(deepcopy(sealed["proofs"][0]))
        value["slots"][0]["seal"] = self.write("aggregate.json", sealed)
        ptr = self.write("aggregate-registry.json", value)
        with self.assertRaises(ValueError):
            shared.validate_registry(ptr, ptr["sha256"])

    def test_three_single_proof_seals_cannot_share_aggregate_candidate_authority(self):
        registry, rows, _ = self.callback()
        document = e.read_json(shared.bound(registry))
        authority = e.read_json(shared.bound(rows[0]["authority"]))
        authority["entries"] = [e.read_json(shared.bound(row["authority"]))["entries"][0]
                                for row in rows if row["role"] == "candidate"]
        aggregate = self.write("aggregate-candidate-authority.json", authority)
        for row in document["slots"]:
            if row["role"] == "candidate":
                seal = e.read_json(shared.bound(row["seal"]))
                seal["authority"] = aggregate
                row["authority"] = aggregate
                row["seal"] = self.write(f"aggregate-bound-{row['seed']}-seal.json", seal)
        pointer = self.write("aggregate-authority-registry.json", document)
        with self.assertRaisesRegex(ValueError, "single-seed authority"):
            shared.validate_registry(pointer, pointer["sha256"])

    def test_cost_source_terminal_budget_and_full_inventory_tamper_are_rejected(self):
        _, rows, callback = self.callback()
        row = rows[0]
        proof = e.read_json(shared.bound(row["receipt"]))
        cost_path = shared.bound(proof["cost_authority"])
        original_cost = cost_path.read_bytes()
        for name, value in (("original_cost_count", 2), ("new_generation_calls", 1), ("new_samples", 1),
                            ("new_timing_measurements", 1)):
            cost = json.loads(original_cost); cost[name] = value
            e.dump(cost_path, cost)
            with self.subTest(name=name), self.assertRaises(ValueError):
                callback(row["receipt"], seed=row["seed"], role=row["role"], external_registration=self.external)
            cost_path.write_bytes(original_cost)
        original_proof = shared.bound(row["receipt"]).read_bytes()
        for name in ("actual_source_scope", "terminal_authority", "native_complete"):
            altered = deepcopy(proof); altered[name] = True if name == "native_complete" else False
            e.dump(Path(row["receipt"]["path"]), altered)
            with self.subTest(name=name), self.assertRaises(ValueError):
                callback(row["receipt"], seed=row["seed"], role=row["role"], external_registration=self.external)
            Path(row["receipt"]["path"]).write_bytes(original_proof)
        (Path(proof["session_root"]) / "extra-terminal.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            callback(row["receipt"], seed=row["seed"], role=row["role"], external_registration=self.external)

    def test_registry_and_seal_mutation_after_callback_construction_refuse(self):
        registry, rows, callback = self.callback()
        for pointer in (registry, rows[0]["seal"]):
            path = shared.bound(pointer); original = path.read_bytes(); path.write_bytes(original + b" ")
            with self.assertRaises(ValueError):
                callback(rows[0]["receipt"], seed=shared.SEEDS[0], role="candidate", external_registration=self.external)
            path.write_bytes(original)

    def test_fixed_candidate08_10_singleton09_partial_and_all_controls_original(self):
        registry, rows, callback = self.callback()
        expected = {20261008: shared.singleton_factory, 20261009: shared.partial_factory,
                    20261010: shared.singleton_factory}
        for row in rows:
            factory = shared.control_factory if row["role"] == "control" else expected[row["seed"]]
            self.assertIs(shared.factory_for(row["role"], row["seed"]), factory)
            self.assertEqual(e.read_json(shared.bound(row["seal"]))["verifier"], shared.identity(Path(factory.__file__)))
            self.assertEqual(callback(row["receipt"], seed=row["seed"], role=row["role"], external_registration=self.external),
                             e.read_json(shared.bound(row["receipt"])))
        document = e.read_json(shared.bound(registry))
        for seed in shared.SEEDS:
            altered = deepcopy(document)
            wrong_factory = shared.singleton_factory if seed == 20261009 else shared.partial_factory
            altered["candidate_verifiers"][str(seed)] = shared.identity(Path(wrong_factory.__file__))
            pointer = self.write(f"helper-choice-{seed}.json", altered)
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                shared.validate_registry(pointer, pointer["sha256"])

    def test_correct_top_mapping_does_not_allow_wrong_seed_helper_seal(self):
        registry, _, _ = self.callback()
        document = e.read_json(shared.bound(registry))
        for seed in shared.SEEDS:
            altered = deepcopy(document)
            row = next(r for r in altered["slots"] if (r["role"], r["seed"]) == ("candidate", seed))
            sealed = e.read_json(shared.bound(row["seal"]))
            wrong_factory = shared.singleton_factory if seed == 20261009 else shared.partial_factory
            sealed["verifier"] = shared.identity(Path(wrong_factory.__file__))
            row["seal"] = self.write(f"wrong-fixed-helper-{seed}-seal.json", sealed)
            pointer = self.write(f"wrong-fixed-helper-{seed}-registry.json", altered)
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                shared.validate_registry(pointer, pointer["sha256"])
