"""Offline source registration and original F5 stage custody tests."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import v2_unit_custody as custody
from . import v2_prepare as packing
from . import v2_unit_diagnostics as diagnostics
from . import test_v2_unit_diagnostics as puretests
from .test_v2_worker import settings, result
from .test_worker import FakeClient, budget
from . import v2_worker as worker


def trusted_main_validator(receipt, *, seed, role, external_registration):
    """Synthetic seam: original session/cost admission belongs to its owner."""
    proof = custody._read(receipt)
    if proof["seed"] != seed or proof["role"] != role:
        raise ValueError("Synthetic external main admission rejected scope")
    return proof


def boolean_main_validator(receipt, *, seed, role, external_registration):
    return True


class TraceClient(FakeClient):
    def __init__(self, root, outputs):
        super().__init__(outputs)
        self.root = root
        self.ordinal = len(list((root / "transport").iterdir())) if (root / "transport").exists() else 0

    def exchange(self, endpoint, body, response):
        self.ordinal += 1
        path = self.root / "transport" / f"{self.ordinal:05d}"
        path.mkdir(parents=True)
        for name, value in (("request.json", {"endpoint": endpoint, "body": body}),
                            ("response.raw", response), ("transport.json", {"status": 200})):
            (path / name).write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
        self.last_exchange = str(path.resolve())

    def tokenize(self, prompt):
        tokens = list(range(self.tokens))
        self.exchange("/tokenize", {"content": prompt, "add_special": False, "parse_special": True}, {"tokens": tokens})
        return tokens

    def complete(self, request):
        response = super().complete(request)
        self.exchange("/completion", request, response)
        return response


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        synthetic = puretests.UnitDiagnosticTests()
        synthetic.setUp()
        self.scene, self.windows = synthetic.scene, synthetic.windows
        manifest = self.write("source-manifest.json", {"windows": self.windows})
        scenes = self.root / "scenes.jsonl"
        scenes.write_text(json.dumps(self.scene, ensure_ascii=False) + "\n", encoding="utf-8")
        self.freeze = self.write("freeze-manifest.json", {"synthetic": True})
        policy = self.write("policy.json", {"synthetic": True})
        self.source = {"manifest": manifest["path"], "manifest_sha256": manifest["sha256"],
                       "scenes": str(scenes.resolve()), "scenes_sha256": custody.identity(scenes)["sha256"]}
        self.codes = [custody.identity(Path(packing.__file__))]
        self.cards = []
        for seed in diagnostics.SEEDS:
            card = {"schema": "hy30-flow-trial-card-v2", "id": f"F5-{seed}", "family": "F5", "role": "candidate",
                "source": self.source, "source_freeze": self.freeze, "decision_policy": policy,
                "implementation_identity": self.codes, "fixed_runtime_contract": {"output_budget": 4096},
                "prepare": {"split": "screen-a", "stage": "screening", "recipe": "semantic-partition",
                    "recipe_id": f"F5-{seed}", "seed": seed, "target_size": 3,
                    "context_before": 1, "context_after": 1, "token_target": None,
                    "token_counts_path": None, "common_context": False, "offset": 0,
                    "selected_scene_ids": ["scene"], "options": {"review": False}}}
            self.cards.append(self.write(f"card-{seed}.json", card))
        self.entries = [{"id": f"F5-{seed}", "seed": seed, **ptr}
                        for seed, ptr in zip(diagnostics.SEEDS, self.cards, strict=True)]
        self.index = self.write("index.json", {"schema": "hy30-pending-v5-source-only-index-v1", "state": "frozen_not_executed", "cards": self.entries})
        self.bundle = self.write("bundle.json", {"schema": "hy30-pending-v5-source-only-freeze-v1", "state": "frozen_not_executed", "cards": self.entries, "index": self.index})
        self.gate = self.write("root-gate.json", {"schema": "hy30-pending-v5-registration-gate-v1", "state": "promoted-runtime-and-safe-audits-accepted",
            "source": self.source, "decision_policy": policy, "implementation_identity": self.codes,
            "approved_lanes": ["screen-a"], "controls": {"screen-a": {"cohort": {"split": "screen-a",
                "scenes": 1, "source_cues": 9, "score_windows": 48,
                "score_cues": sum(len(w["scored_ids"]) for w in self.windows), "batches_per_seed": 3,
                "seeds": list(diagnostics.SEEDS)}}}})

    def write(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return custody.identity(path)

    def register(self, **changes):
        args = dict(cards=self.cards, card_bundle=self.bundle, registered_index=self.index,
                    root_gate=self.gate, output=self.root / "registered")
        args.update(changes)
        # The authority gate is independently tested by v2_prepare; this seam
        # fixture tests native source-card/bundle metadata without reference files.
        with patch.object(packing, "verify_source_freeze") as gate:
            pointer = custody.register_frame(**args)
        self.assertEqual(gate.call_count, 3)
        return pointer

    def test_complete_fixed_slots_and_source_native_packing_parity(self):
        pointer = self.register()
        record = custody._read(pointer)
        self.assertEqual(record["scope"]["scored_windows"], 48)
        self.assertEqual(record["scope"]["source_cues"], 9)
        self.assertEqual(record["scope"]["scheduled_batches_per_seed"], 3)
        self.assertEqual(record["scope"]["selected_batches_per_seed"], 2)
        self.assertEqual(record["scope"]["expected_slots"], 6)
        self.assertFalse(record["actual_native_authenticated"])
        for seed, ptr in zip(diagnostics.SEEDS, record["packed"], strict=True):
            value = custody._read(ptr)
            _, expected = packing.pack_scene(self.scene, target_size=3, context_before=1, context_after=1)
            self.assertEqual(value["batches"], expected)
            self.assertEqual(value["seed"], seed)
        frame = custody._read(record["frame"])
        self.assertEqual([r["seed"] for r in frame["expected_slots"]], [20261008] * 2 + [20261009] * 2 + [20261010] * 2)

    def test_external_root_registration_required_and_replay_tamper_rejected(self):
        pointer = self.register()
        external = self.write("external.json", {"schema": custody.EXTERNAL_REGISTRATION_SCHEMA,
            "state": "frozen_before_generation", "registration": pointer, "root_gate": self.gate,
            "registered_at_utc": "2026-10-07T22:00:00+00:00"})
        result = custody.validate_registered_frame(pointer, external,
            expected_registration_sha256=pointer["sha256"], expected_external_sha256=external["sha256"])
        self.assertEqual(len(result["frame"]["expected_slots"]), 6)
        with self.assertRaisesRegex(ValueError, "pins"):
            custody.validate_registered_frame(pointer, external, expected_registration_sha256="0" * 64,
                                              expected_external_sha256=external["sha256"])
        changed = custody._read(external)
        changed["state"] = "locally_created_after_outputs"
        late = self.write("late.json", changed)
        with self.assertRaisesRegex(ValueError, "independently"):
            custody.validate_registered_frame(pointer, late, expected_registration_sha256=pointer["sha256"],
                                              expected_external_sha256=late["sha256"])
        Path(self.cards[0]["path"]).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            custody.validate_registered_frame(pointer, external, expected_registration_sha256=pointer["sha256"],
                                              expected_external_sha256=external["sha256"])

    def test_wrong_seed_missing_card_source_scope_and_byte_pins_rejected_before_write(self):
        cases = (dict(cards=self.cards[:2]), dict(cards=list(reversed(self.cards))),
                 dict(root_gate={**self.gate, "sha256": "0" * 64}))
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.register(**changes)
            self.assertFalse((self.root / "registered").exists())
        source = Path(self.source["manifest"])
        source.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Source authority"):
            self.register()

    def test_execution_and_explicit_scene_order_not_relabelled(self):
        for change in ("budget", "geometry", "stage", "runtime", "source_preparation"):
            cards = deepcopy(self.cards)
            value = custody._read(cards[-1])
            if change == "runtime":
                value["fixed_runtime_contract"]["output_budget"] = 3072
            elif change == "stage":
                value["prepare"]["stage"] = "confirmation"
            elif change == "source_preparation":
                value["prepare"]["source_preparation_path"] = "unread-generated.json"
            else:
                value["prepare"]["n_predict" if change == "budget" else "target_size"] = 3072 if change == "budget" else 4
            cards[-1] = self.write(f"changed-{change}.json", value)
            entries = [dict(e) for e in self.entries]
            entries[-1].update(cards[-1])
            index = self.write(f"index-{change}.json", {"schema": "hy30-pending-v5-source-only-index-v1", "state": "frozen_not_executed", "cards": entries})
            bundle = self.write(f"bundle-{change}.json", {"schema": "hy30-pending-v5-source-only-freeze-v1", "state": "frozen_not_executed", "cards": entries, "index": index})
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.register(cards=cards, registered_index=index, card_bundle=bundle)

    def test_existing_destination_is_never_modified(self):
        output = self.root / "registered"
        output.mkdir()
        marker = output / "original"
        marker.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.register()
        self.assertEqual(marker.read_bytes(), b"original")


class StageCustodyTests(unittest.TestCase):
    write = RegistrationTests.write
    register = RegistrationTests.register

    def setUp(self):
        RegistrationTests.setUp(self)
        self.registration = self.register()
        self.record = custody._read(self.registration)
        self.frame = custody._read(self.record["frame"])
        self.external = self.write("external.json", {"schema": custody.EXTERNAL_REGISTRATION_SCHEMA,
            "state": "frozen_before_generation", "registration": self.registration, "root_gate": self.gate,
            "registered_at_utc": "2020-01-01T00:00:00+00:00"})
        self.validator = custody.identity(Path(__file__))

    def write_in(self, root, name, value, *, lines=False):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = ("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in value) if lines else
                json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        path.write_text(text, encoding="utf-8")
        return custody.identity(path)

    def main_receipt(self, *, seed=20261008, control=False, failure=None, singleton=False):
        root = self.root / f"session-{seed}-{'control' if control else 'candidate'}"
        root.mkdir()
        label = root / "label"
        packed = custody._read(self.record["packed"][diagnostics.SEEDS.index(seed)])
        if control:
            _, packed["batches"] = packing.pack_scene(self.scene, target_size=2, context_before=1, context_after=1)
            packed["packing"]["target_size"] = 2
        source = diagnostics._source(packed)
        windows = [b["producer_input"] for b in source["batches"]]
        item = settings("c0" if control else "semantic-partition", seed=seed)
        rows = []
        native = ' 甲。\t乙😀丙 '
        for index, window in enumerate(windows):
            targets = window["translate_ids"]
            if control:
                outputs = [result({"translations": {sid: f"控制{sid}。" for sid in targets}})]
                if failure == "control" and index == 0:
                    outputs = [result({"translations": {"wrong": "bad"}})] * 2
            elif len(targets) == 1:
                outputs = [result({"translations": {"u1": native}})]
            elif singleton:
                decisions = {"boundaries": [{"join": False, "evidence_ids": [a, b], "uncertain": True}
                             for a, b in zip(targets, targets[1:])]}
                outputs = [result(decisions), result({"translations": {f"u{i + 1}": "原文😀。 " for i in range(len(targets))}})]
                if len(targets) == 1:
                    outputs.pop(0)
            else:
                decisions = {"boundaries": [{"join": True, "evidence_ids": [a, b], "uncertain": True}
                             for a, b in zip(targets, targets[1:])]}
                parts = [native[:3], native[3:6], native[6:]]
                mapped = {"segments": [{"unit_id": "u1", "source_id": sid, "text": part}
                                       for sid, part in zip(targets, parts, strict=True)]}
                outputs = [result(decisions), result({"translations": {"u1": native}}), result(mapped)]
                if failure == "mapping" and index == 0:
                    outputs[-1:] = [result({"unresolved": "Boundary unknown"})] * 2
                elif failure == "native" and index == 0:
                    outputs[1:] = [result({"translations": {"wrong": "bad"}})] * 2
                elif failure == "planning" and index == 0:
                    outputs[:] = [result({"unresolved": "Plan unknown"})] * 2
            client = TraceClient(root, outputs)
            row = worker.run_window(client, window, item, 4096 if failure == "preflight" else 8192,
                budget(max_estimated_tokens=200000), {"first_response_checked": False})
            rows.append(row)
        retained = {
            "packed": self.write_in(root, "packed.json", packed),
            "inputs": self.write_in(root, "inputs.jsonl", windows, lines=True),
            "ledger": self.write_in(label, "ledger.jsonl", rows, lines=True),
            "results": self.write_in(label, "results.jsonl", [{"id": r["window_id"], "status": r["status"],
                "translations": r["translations"]} for r in rows], lines=True),
            "schedule": self.write_in(label, "schedule.jsonl", [], lines=True)}
        run = {"schema": "hy30-flow-session-v2", "phase": "translation", "lane": "P-flow", "recipe": item["recipe"],
               "settings": item, "packed_mapping_sha256": retained["packed"]["sha256"],
               "source_manifest_sha256": self.record["source_authority"]["manifest"]["sha256"],
               "input_sha256": retained["inputs"]["sha256"], "expected_window_ids": [w["id"] for w in windows]}
        retained["run"] = self.write_in(label, "run.json", run)
        card = self.cards[diagnostics.SEEDS.index(seed)]
        if control:
            value = custody._read(card)
            value["prepare"].update(recipe="c0", target_size=2)
            card = self.write_in(root, "control-card.json", value)
        completion = self.write_in(root, "trial-completion.json", {"terminal": True})
        start = self.write_in(root, "trial-start.json", {"started_at_utc": "2026-10-08T00:00:00+00:00"})
        cost = self.write_in(root, "cost-proof.json", {"command": "original", "counted_once": True})
        proof = {"schema": custody.MAIN_PROOF_SCHEMA, "role": "control" if control else "candidate", "seed": seed,
            "card": card, "source_authority": self.record["source_authority"], "retained": retained,
            "session_root": str(root.resolve()), "trial": {"start": start, "completion": completion},
            "session_provenance": [completion], "approved_parser_snapshots": custody._dependencies(),
            "cost_authority": cost, "terminal_authority": completion,
            "external_registration": None if control else self.external,
            "actual_source_scope": {"split": packed["split"], "scene_ids": packed["scene_ids"], "source_cues": 9, "scored_windows": 48},
            "original_source_authority": self.record["source_authority"], "scoring_derivation": None,
            "original_generation_cost_identity": cost, "native_complete": failure is None,
            "generation_attempt_status": "delivered" if failure is None else "terminal_partial", "native_stage": "screening"}
        receipt = self.write_in(root, "main-proof.json", proof)
        return {"seed": seed, "role": proof["role"], "receipt": receipt}

    def prepare(self, entries, **changes):
        args = dict(registration=self.registration, external_registration=self.external,
            expected_registration_sha256=self.registration["sha256"], expected_external_sha256=self.external["sha256"],
            main_receipts=entries, expected_main_receipts=entries, main_validator=trusted_main_validator,
            validator_identity=self.validator, expected_validator_sha256=self.validator["sha256"], output=self.root / "prepared")
        args.update(changes)
        return custody.prepare_unit_auxiliary(**args)

    def remove_session_fixture(self):
        import shutil
        target = (self.root / "session-20261008-candidate").resolve()
        if not target.is_relative_to(self.root.resolve()) or target == self.root.resolve():
            raise ValueError("Synthetic cleanup must stay inside its explicit temporary root")
        shutil.rmtree(target)

    def alter(self, entry, field, mutate, *, lines=False):
        proof = custody._read(entry["receipt"])
        value = custody._read(proof["retained"][field], lines=lines)
        mutate(value)
        proof["retained"][field] = self.write_in(Path(proof["session_root"]), "altered-" + field + ".json", value, lines=lines)
        entry["receipt"] = self.write_in(Path(proof["session_root"]), "altered-proof.json", proof)

    def test_genuine_worker_stage_parity_exact_unicode_and_control_cross_batches(self):
        entries = [self.main_receipt(), self.main_receipt(control=True)]
        pointer = self.prepare(entries)
        value = custody._read(pointer)
        self.assertEqual(len(value["slots"]), 6)
        first = value["slots"][0]
        self.assertTrue(first["original_native_authenticated"])
        self.assertFalse(first["views"]["actual_native_authenticated"])
        self.assertEqual(first["original_stage_proof"]["mapping"], "original_accepted_exact_partition")
        self.assertEqual(first["views"]["native_packet"]["output_groups"][0]["text"], ' 甲。\t乙😀丙 ')
        self.assertEqual(first["views"]["attribution_packet"]["mapped_cues"][1]["target_span"], [3, 6])
        self.assertEqual(len(first["views"]["c0_producer_identity"]), 2)
        self.assertEqual(len(value["original_generation_cost_authorities"]), 2)
        self.assertTrue(all(s["views"]["status"] == "missing" for s in value["slots"][2:]))
        replay = custody.validate_prepared_unit_auxiliary(pointer, expected_sha256=pointer["sha256"],
            expected_registration=self.registration, expected_external_registration=self.external,
            expected_main_receipts=entries, expected_validator=self.validator)
        self.assertEqual(replay["slots"], value["slots"])
        raw = Path(value["raw_artifacts"][0]["path"])
        raw.write_bytes(raw.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            custody.validate_prepared_unit_auxiliary(pointer, expected_sha256=pointer["sha256"],
                expected_registration=self.registration, expected_external_registration=self.external,
                expected_main_receipts=entries, expected_validator=self.validator)

    def test_mapping_failure_keeps_native_fidelity_and_fixed_unknown_tail(self):
        entry = self.main_receipt(failure="mapping")
        value = custody._read(self.prepare([entry]))
        first = value["slots"][0]
        self.assertTrue(first["original_native_authenticated"])
        self.assertEqual(first["views"]["status"], "mapping_unjudgeable")
        self.assertIsNone(first["views"]["attribution_packet"])
        self.assertIsNotNone(first["views"]["native_packet"])
        self.assertEqual(value["original_generation_metadata"][0]["generation_attempt_status"], "terminal_partial")
        self.assertFalse(value["original_generation_metadata"][0]["native_complete"])

    def test_planning_native_failures_and_missing_all_keep_same_denominator(self):
        for failure in ("planning", "native"):
            entry = self.main_receipt(seed=20261008 if failure == "planning" else 20261009, failure=failure)
            pointer = self.prepare([entry], output=self.root / f"prepared-{failure}")
            value = custody._read(pointer)
            failed = next(s for s in value["slots"] if s["slot"]["seed"] == entry["seed"])
            self.assertFalse(failed["original_native_authenticated"])
            self.assertIsNone(failed["views"]["native_packet"])
            self.assertEqual(len(value["slots"]), 6)
        value = custody._read(self.prepare([]))
        self.assertEqual(len(value["slots"]), 6)
        self.assertTrue(all(s["views"]["status"] == "missing" for s in value["slots"]))

    def test_deterministic_singleton_units_need_zero_mapper_calls(self):
        entry = self.main_receipt(singleton=True)
        value = custody._read(self.prepare([entry]))
        self.assertEqual(value["slots"][0]["original_stage_proof"]["mapping"], "original_deterministic_singletons")
        proof = custody._read(entry["receipt"])
        rows = custody._read(proof["retained"]["ledger"], lines=True)
        self.assertEqual(rows[0]["mapping_cost"]["completion_calls"], 0)

    def test_original_plan_native_mapping_and_branch_tamper_rejected(self):
        mutations = {
            "plan": lambda rows: rows[0]["semantic_plan"]["units"][0].update(uncertain=False),
            "native": lambda rows: rows[0]["native_unit_translations"].update(u1='甲。\t乙😀丙'),
            "mapping": lambda rows: rows[0]["source_span_to_target_span"][0]["target_spans"].__setitem__(0, [0, 4]),
            "protocol": lambda rows: rows[0].update(native_protocol="unsupported-new-version"),
            "branch": lambda rows: rows[0]["planning_cost"].update(model_planning_required=False)}
        for index, (name, mutate) in enumerate(mutations.items()):
            with self.subTest(name=name):
                # Each native-format chain uses a distinct temp session scope.
                entry = self.main_receipt()
                self.alter(entry, "ledger", mutate, lines=True)
                with self.assertRaises(ValueError):
                    self.prepare([entry])
                self.remove_session_fixture()

    def test_native_tokenizer_and_raw_stage_proof_not_boolean(self):
        entry = self.main_receipt()
        proof = custody._read(entry["receipt"])
        rows = custody._read(proof["retained"]["ledger"], lines=True)
        token = Path(rows[0]["attempts"][0]["tokenize_exchange"]) / "request.json"
        value = json.loads(token.read_text(encoding="utf-8"))
        value["body"]["parse_special"] = False
        token.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "tokenizer"):
            self.prepare([entry])
        with self.assertRaisesRegex(ValueError, "code snapshot"):
            self.prepare([entry], validator_identity={**self.validator, "sha256": "0" * 64})
        with self.assertRaisesRegex(ValueError, "accepted pins"):
            self.prepare([entry], expected_main_receipts=[])

    def test_chronology_scope_parser_snapshot_and_false_complete_block(self):
        for name in ("chronology", "scope", "parser", "complete", "stage"):
            entry = self.main_receipt(failure="mapping" if name == "complete" else None)
            proof = custody._read(entry["receipt"])
            if name == "chronology":
                proof["trial"]["start"] = self.write_in(Path(proof["session_root"]), "late-start.json", {"started_at_utc": "2019-01-01T00:00:00+00:00"})
            elif name == "scope":
                proof["actual_source_scope"]["scored_windows"] = 96
            elif name == "parser":
                proof["approved_parser_snapshots"].pop()
            elif name == "complete":
                proof["native_complete"] = True
                proof["generation_attempt_status"] = "delivered"
            else:
                proof["native_stage"] = "confirmation"
            entry["receipt"] = self.write_in(Path(proof["session_root"]), "changed-proof.json", proof)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.prepare([entry])
            self.remove_session_fixture()

    def single_source_registration(self):
        cards = []
        for ptr in self.cards:
            card = custody._read(ptr)
            card["prepare"]["target_size"] = 1
            cards.append(self.write(f"singleton-{card['prepare']['seed']}.json", card))
        entries = [{"id": f"F5-{seed}", "seed": seed, **ptr} for seed, ptr in zip(diagnostics.SEEDS, cards, strict=True)]
        index = self.write("singleton-index.json", {"schema": "hy30-pending-v5-source-only-index-v1", "state": "frozen_not_executed", "cards": entries})
        bundle = self.write("singleton-bundle.json", {"schema": "hy30-pending-v5-source-only-freeze-v1", "state": "frozen_not_executed", "cards": entries, "index": index})
        gate = custody._read(self.gate)
        gate["controls"]["screen-a"]["cohort"]["batches_per_seed"] = 9
        self.gate = self.write("singleton-gate.json", gate)
        self.cards = cards
        self.registration = self.register(registered_index=index, card_bundle=bundle, output=self.root / "singleton-registration")
        self.record = custody._read(self.registration)
        self.frame = custody._read(self.record["frame"])
        self.external = self.write("singleton-external.json", {"schema": custody.EXTERNAL_REGISTRATION_SCHEMA,
            "state": "frozen_before_generation", "registration": self.registration, "root_gate": self.gate,
            "registered_at_utc": "2020-01-01T00:00:00+00:00"})

    def test_true_single_source_cue_needs_no_planner_or_mapper_attempt(self):
        self.single_source_registration()
        entry = self.main_receipt()
        value = custody._read(self.prepare([entry]))
        self.assertEqual(len(value["slots"]), 9)
        stage = value["slots"][0]["original_stage_proof"]
        self.assertEqual(stage["planning"], "original_deterministic_singleton")
        self.assertEqual(stage["mapping"], "original_deterministic_singletons")
        self.assertEqual(len(stage["raw_artifacts"]), 6)

    def test_original_preflight_singleton_plan_kept_without_manufacturing_native_text(self):
        self.single_source_registration()
        entry = self.main_receipt(failure="preflight")
        value = custody._read(self.prepare([entry]))
        first = value["slots"][0]
        self.assertFalse(first["original_native_authenticated"])
        self.assertEqual(first["views"]["status"], "setup_failed")
        self.assertEqual(first["views"]["planned_unit_count"], 1)
        self.assertIsNone(first["views"]["native_packet"])
        self.assertEqual(first["original_stage_proof"]["planning"], "original_deterministic_singleton")
        self.assertEqual(len(value["slots"]), 9)

    def test_missing_control_and_boolean_main_admission_do_not_manufacture_native_proof(self):
        entry = self.main_receipt(control=True, failure="control")
        value = custody._read(self.prepare([entry]))
        self.assertEqual(value["slots"][0]["views"]["c0_state"], "incomplete_whole_batch_control")
        self.assertIsNone(value["slots"][0]["views"]["c0_packet"])
        with self.assertRaisesRegex(ValueError, "exact artifact-bound"):
            self.prepare([entry], main_validator=boolean_main_validator, output=self.root / "bool-prepared")

    def test_historical_c0_preserves_original_source_and_zero_generation_derivation(self):
        entry = self.main_receipt(control=True)
        proof = custody._read(entry["receipt"])
        original = self.write("original-source.json", {"windows": self.windows, "version": "original"})
        original_freeze = self.write("original-freeze.json", {"source": original})
        proof["original_source_authority"] = {**self.record["source_authority"], "manifest": original, "freeze": original_freeze}
        proof["scoring_derivation"] = self.write("zero-generation-derivation.json", {
            "original_source": proof["original_source_authority"], "accepted_scoring_source": self.record["source_authority"],
            "zero_new_generation": True})
        root = Path(proof["session_root"])
        packed = custody._read(proof["retained"]["packed"])
        packed["source_manifest"] = original
        proof["retained"]["packed"] = self.write_in(root, "original-packed.json", packed)
        run = custody._read(proof["retained"]["run"])
        run["source_manifest_sha256"] = original["sha256"]
        run["packed_mapping_sha256"] = proof["retained"]["packed"]["sha256"]
        proof["retained"]["run"] = self.write_in(root / "label", "original-run.json", run)
        card = custody._read(proof["card"])
        card["source"].update(manifest=original["path"], manifest_sha256=original["sha256"])
        card["source_freeze"] = original_freeze
        proof["card"] = self.write_in(root, "original-card.json", card)
        entry["receipt"] = self.write_in(root, "derived-main-proof.json", proof)
        value = custody._read(self.prepare([entry]))
        self.assertIsNotNone(value["slots"][0]["views"]["c0_packet"])
        metadata = value["original_generation_metadata"][0]
        self.assertEqual(metadata["original_source_authority"]["manifest"], original)
        self.assertEqual(metadata["source_authority"], self.record["source_authority"])
        self.assertEqual(metadata["original_generation_cost_identity"], proof["cost_authority"])
        self.assertEqual(value["generation_calls"], 0)

    def test_original_completion_grammar_body_native_raw_and_transport_rejected(self):
        for name in ("grammar", "native_raw", "tokens", "http", "escape"):
            entry = self.main_receipt()
            proof = custody._read(entry["receipt"])
            rows = custody._read(proof["retained"]["ledger"], lines=True)
            attempt = rows[0]["attempts"][1 if name == "native_raw" else 0]
            path = Path(attempt["original_response"] if name != "tokens" else attempt["tokenize_exchange"])
            if name == "escape":
                rows[0]["attempts"][0]["original_response"] = str(self.root / "not-session")
                proof["retained"]["ledger"] = self.write_in(Path(proof["session_root"]), "escape-ledger.jsonl", rows, lines=True)
                entry["receipt"] = self.write_in(Path(proof["session_root"]), "escape-proof.json", proof)
            else:
                filename = "request.json" if name == "grammar" else "transport.json" if name == "http" else "response.raw"
                value = json.loads((path / filename).read_text(encoding="utf-8"))
                if name == "grammar":
                    value["body"]["grammar"] += "\nchanged"
                elif name == "native_raw":
                    value["content"] += " "
                elif name == "tokens":
                    value["tokens"].reverse()
                else:
                    value["status"] = 500
                (path / filename).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.prepare([entry])
            self.remove_session_fixture()


if __name__ == "__main__":
    unittest.main()
