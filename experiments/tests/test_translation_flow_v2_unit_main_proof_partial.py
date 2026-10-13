"""Synthetic candidate-only partial delivery admission and unchanged regressions.

Only TEST module aliases select the new helper. Handwritten native-shaped
fixtures run real worker/parser code against temporary synthetic transport files;
no retained trial, reference, judge, model or native CLI is accessed.
"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from experiments.translation_flow import test_v2_unit_main_proof as original
from experiments.translation_flow import v2_unit_main_proof_partial as main
from experiments.translation_flow import v2_unit_custody as custody
from experiments.translation_flow import v2_delivery as delivery
from experiments.translation_eval import runner as evaluator
from experiments.tests import test_translation_flow_v2_unit_main_proof_singleton as singletontests


class PartialMainProofTests(singletontests.SingletonMainProofTests):
    def setUp(self):
        # TEST-ONLY selection; neither frozen verifier nor production parser is
        # rebound. The inherited fixture records the selected file's identity.
        alias = patch.object(singletontests, "main", main)
        alias.start()
        self.addCleanup(alias.stop)
        super().setUp()

    def partial_native(self, *, batch=0, cue=1, mapping_failure=False):
        marker, invalid = "甲😀。 ", "甲\n\n😀。 "
        native_batch = -1
        render_result = original.result

        def synthetic_result(content, **changes):
            nonlocal native_batch
            value = deepcopy(content)
            if isinstance(value, dict) and set(value.get("translations", {})) == {"u1"}:
                native_batch += 1
                if native_batch == batch:
                    text = value["translations"]["u1"]
                    value["translations"]["u1"] = "".join(
                        invalid if i == cue else marker for i in range(text.count(marker)))
            elif isinstance(value, dict) and "segments" in value and native_batch == batch:
                value["segments"][cue]["text"] = invalid
            return render_result(value, **changes)

        # Rewrite the synthetic payload before worker/parser/transport capture;
        # this never edits a generated native row or accepted attempt afterward.
        with patch.object(original, "result", synthetic_result):
            fixture = self.native(failure="mapping" if mapping_failure else None)
        terminal = fixture["root"] / "trial-completion.json"
        pointer = self.modify(terminal, lambda value: value.update(status="partial"))
        authority = custody._read(fixture["authority"])
        authority["entries"][0]["trial_completion"] = pointer
        fixture["entry"] = authority["entries"][0]
        fixture["authority"] = self.write("partial-authority.json", authority)
        return fixture

    def sidecar(self, fixture):
        return custody._read(main.identity(fixture["root"] / "delivery/scenes/scene/sidecar.json"))

    def synthetic_public_evaluation(self, fixture):
        # Mirror v2_evaluation's existing serialization-only normalization and
        # call the public structural preparation core with handwritten refs.
        # No judge is run, and these refs never leave the synthetic temp root.
        staging = self.root / "synthetic-evaluation-inputs"
        requests = evaluator.load_jsonl(fixture["root"] / "delivery/inputs.jsonl")
        refs = [{"id": request["id"], "work": "synthetic-work", "category": "anime_series",
                 "scored_ids": request["translate_ids"],
                 "units": [{"id": cue["id"], "ja": cue["text"], "zh": "合成参考。",
                            "score": cue["id"] in request["translate_ids"]} for cue in request["context"]]}
                for request in requests]
        evaluator.dump_jsonl(staging / "inputs.jsonl", requests)
        evaluator.dump_jsonl(staging / "references.jsonl", refs)
        for name in ("results", "ledger", "schedule"):
            rows = evaluator.load_jsonl(fixture["root"] / f"delivery/{name}.jsonl")
            evaluator.dump_jsonl(staging / f"{name}.jsonl",
                                 [{k: v for k, v in row.items() if k != "delivery_contract"} for row in rows])
        output = self.root / "synthetic-evaluation"
        evaluator.prepare(staging / "inputs.jsonl", staging / "references.jsonl",
            {"candidate": staging / "results.jsonl"}, output,
            candidate_ledgers={"candidate": staging / "ledger.jsonl"},
            candidate_schedules={"candidate": staging / "schedule.jsonl"})
        return evaluator.load_jsonl(output / "expected.jsonl"), evaluator.load_jsonl(output / "jobs.jsonl")

    def test_invalid_only_worker_success_is_full_scope_terminal_partial(self):
        fixture = self.partial_native()
        value = custody._read(self.authenticate(fixture))
        session = fixture["label"].parent
        self.assertTrue(custody._read(main.identity(session / "worker-completion.json"))["complete"])
        self.assertEqual(custody._read(main.identity(fixture["root"] / "execution/command-completion.json"))["returncode"], 0)
        self.assertFalse(value["native_complete"])
        self.assertEqual(value["generation_attempt_status"], "terminal_partial")
        self.assertEqual(value["actual_source_scope"]["source_cues"], 9)
        self.assertEqual((value["scheduled_batches"], value["attempted_batches"]), (3, 3))
        self.assertEqual(value["failed_batches"], [])
        self.assertEqual(len(value["approved_parser_snapshots"]), 9)
        self.assertEqual(value["original_cost_count"], 1)
        self.assertEqual(value["new_generation_calls"], 0)
        self.assertFalse(value["semantic_accuracy_verified"])
        attempts = [a for row in fixture["rows"] for a in row["attempts"] if a["completion_dispatched"]]
        self.assertEqual(len(attempts), 9)
        self.assertTrue(all(a["status"] == "accepted" for a in attempts))
        self.assertEqual([a["stage"] for a in fixture["rows"][0]["attempts"]],
                         ["source-planning", "joint-unit-translation", "semantic-remapping"])
        inventory = {ptr["path"] for ptr in value["inventory"]}
        self.assertTrue({str((Path(a["original_response"]) / "response.raw").resolve())
                         for a in attempts} <= inventory)
        costs = custody._read(main.identity(fixture["root"] / "delivery/costs.json"))
        self.assertEqual(costs["dispatched_completions"], 9)
        self.assertEqual(costs["input_tokens"]["measured_sum"], sum(a["input_tokens"] for a in attempts))
        self.assertEqual(self.sidecar(fixture)["coverage"]["status_counts"], {"delivered": 8, "invalid": 1})
        self.assertIn("\n\n", fixture["rows"][0]["native_unit_translations"]["u1"])
        self.assertEqual(fixture["rows"][0]["translations"]["s2"], "甲\n\n😀。 ")
        self.assertFalse((fixture["root"] / "delivery/scenes/scene/chn.srt").exists())

    def test_invalid_partial_exact20_proof_metadata_callback_and_raw_inventory(self):
        fixture = self.partial_native()
        admission = self.authenticate(fixture)
        proof = main.build_main_proof(admission=admission, expected_admission_sha256=admission["sha256"],
            authority=fixture["authority"], expected_authority_sha256=fixture["authority"]["sha256"],
            output=self.root / "partial-main.json")
        decoded = custody._read(proof)
        self.assertEqual(set(decoded), custody.MAIN_FIELDS)
        self.assertEqual(len(decoded), 20)
        self.assertFalse(decoded["native_complete"])
        seal = self.write("partial-seal.json", {"schema": main.SEAL_SCHEMA,
            "state": "root_reviewed_original_main_proofs", "verifier": main.identity(Path(main.__file__)),
            "authority": fixture["authority"], "proofs": [{"seed": 20261008, "role": "candidate",
                                                         "proof": proof, "admission": admission}]})
        validator = main.make_main_validator(seal=seal, expected_seal_sha256=seal["sha256"])
        with patch.object(custody, "_stage_material", side_effect=AssertionError("Metadata cannot replay text")):
            self.assertEqual(validator(proof, seed=20261008, role="candidate", external_registration=self.external), decoded)
        registered = custody.validate_registered_frame(self.registration, self.external,
            expected_registration_sha256=self.registration["sha256"], expected_external_sha256=self.external["sha256"])
        custody._main(proof, seed=20261008, role="candidate", registered=registered,
                      external_registration=self.external, validator=validator)
        raw = Path(fixture["rows"][0]["attempts"][-1]["original_response"]) / "response.raw"
        raw.write_bytes(raw.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            validator(proof, seed=20261008, role="candidate", external_registration=self.external)

    def test_mapping_null_and_invalid_have_separate_native_evidence_and_costs(self):
        fixture = self.partial_native(batch=1, cue=0, mapping_failure=True)
        value = custody._read(self.authenticate(fixture))
        coverage = self.sidecar(fixture)["coverage"]
        self.assertEqual(coverage["status_counts"], {"mapping_unjudgeable": 3, "invalid": 1, "delivered": 5})
        self.assertEqual(fixture["rows"][0]["status"], "mapping_unjudgeable")
        self.assertTrue(fixture["rows"][0]["native_unit_translations"])
        self.assertEqual(fixture["rows"][1]["status"], "delivered")
        self.assertIn("\n\n", fixture["rows"][1]["native_unit_translations"]["u1"])
        self.assertFalse(value["native_complete"])
        costs = custody._read(main.identity(fixture["root"] / "delivery/costs.json"))
        attempts = [a for r in fixture["rows"] for a in r["attempts"] if a["completion_dispatched"]]
        self.assertEqual(costs["dispatched_completions"], len(attempts))
        self.assertEqual(costs["input_tokens"]["measured_sum"], sum(a["input_tokens"] for a in attempts))
        self.assertEqual(len(attempts), 10)
        expected, jobs = self.synthetic_public_evaluation(fixture)
        self.assertEqual({row["structural_status"] for row in expected}, {"mapping_unjudgeable"})
        self.assertEqual(len(expected), 48)
        self.assertEqual(jobs, [])

    def assert_invalid_availability(self, *, cue, invalid_id, scored):
        fixture = self.partial_native(cue=cue)
        value = custody._read(self.authenticate(fixture))
        mechanical = custody._read(main.identity(fixture["root"] / "delivery/mechanical.jsonl"), lines=True)
        projected = custody._read(main.identity(fixture["root"] / "delivery/results.jsonl"), lines=True)
        affected = [row for row in mechanical if row["status_counts"].get("invalid")]
        self.assertEqual(len(affected), 24 if scored else 0)
        self.assertEqual(len(mechanical), 48)
        self.assertEqual(len(projected), 48)
        self.assertTrue(all(invalid_id not in row["translations"] for row in projected))
        self.assertFalse(value["native_complete"])
        self.assertFalse(value["semantic_accuracy_verified"])
        self.assertTrue(all(not ({"score", "native_semantic", "meaning_score"} & set(row)) for row in mechanical))
        packed = custody._read(main.identity(fixture["root"] / "prepared/packed-mapping.json"))
        aggregate = delivery.aggregate(packed, evaluator.load_jsonl(fixture["label"] / "results.jsonl"),
                                       fixture["rows"], [])
        recomputed = delivery.project_windows(packed, aggregate)
        self.assertEqual(projected, recomputed["results"])
        self.assertEqual(mechanical, recomputed["mechanical"])
        self.assertEqual({row["status"] for row in recomputed["ledger"]}, {"delivered"})
        expected, jobs = self.synthetic_public_evaluation(fixture)
        if not scored:
            self.assertEqual({row["structural_status"] for row in expected}, {"valid"})
            self.assertEqual(len(jobs), 48)
        else:
            affected_status = "delivery_zero" if invalid_id == "s2" else "partial_delivery"
            self.assertEqual(sum(row["structural_status"] == affected_status for row in expected), 24)
            self.assertEqual(sum(row["structural_status"] == "valid" for row in expected), 24)
            self.assertEqual(len(jobs), 24 if invalid_id == "s2" else 48)
            self.assertTrue(all(row["missing_ids"] == [invalid_id] for row in expected
                                if row["structural_status"] == affected_status))

    def test_scored_invalid_retains_all48_windows_and_explicit_unavailable_cue(self):
        self.assert_invalid_availability(cue=1, invalid_id="s2", scored=True)

    def test_unscored_invalid_still_prevents_whole_main_complete(self):
        self.assert_invalid_availability(cue=0, invalid_id="s1", scored=False)

    def test_scored_invalid_with_other_delivered_id_retains_existing_partial_delivery(self):
        self.assert_invalid_availability(cue=2, invalid_id="s3", scored=True)

    def test_invalid_does_not_authorize_missing_result_or_missing_raw(self):
        fixture = self.partial_native()
        result_path = fixture["label"] / "results.jsonl"
        previous = result_path.read_bytes()
        self.modify(result_path, lambda rows: rows.pop(), lines=True)
        with self.assertRaisesRegex(ValueError, "Full ordered"):
            self.authenticate(fixture)
        result_path.write_bytes(previous)
        ledger_path = fixture["label"] / "ledger.jsonl"
        row_path = fixture["label"] / f"window-{fixture['rows'][0]['window_id']}.json"
        originals = {path: path.read_bytes() for path in (result_path, ledger_path, row_path)}
        self.modify(result_path, lambda rows: rows[0]["translations"].pop("s1"), lines=True)
        self.modify(ledger_path, lambda rows: rows[0]["translations"].pop("s1"), lines=True)
        self.modify(row_path, lambda row: row["translations"].pop("s1"))
        # Keep result/ledger/durable row mutually consistent: the accepted native
        # partition, rather than an incidental row hash, must reject omission.
        with self.assertRaisesRegex(ValueError, "semantic delivery differs"):
            self.authenticate(fixture)
        for path, content in originals.items():
            path.write_bytes(content)
        raw = Path(fixture["rows"][0]["attempts"][-1]["original_response"]) / "response.raw"
        # The target is a direct file of this fixture's known temporary root.
        self.assertTrue(raw.resolve().is_relative_to(self.root.resolve()))
        raw.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.authenticate(fixture)

    def test_invalid_raw_payload_change_is_rejected_before_admission(self):
        fixture = self.partial_native()
        raw = Path(fixture["rows"][0]["attempts"][-1]["original_response"]) / "response.raw"
        self.modify(raw, lambda value: value.update(content="{}"))
        with self.assertRaises(ValueError):
            self.authenticate(fixture)

    def test_invalid_scene_counts_and_sidecar_states_cannot_be_relabelled(self):
        fixture = self.partial_native()
        delivery_path = fixture["root"] / "delivery/delivery.json"
        sidecar_path = fixture["root"] / "delivery/scenes/scene/sidecar.json"
        cases = ((delivery_path, lambda value: value["scenes"][0].update(expected_cues=8)),
                 (delivery_path, lambda value: value["scenes"][0].update(status_counts={"delivered": 9})),
                 (sidecar_path, lambda value: value["coverage"]["cue_states"]["s2"].update(status="delivered", text="甲😀。 ")),
                 (sidecar_path, lambda value: value["coverage"]["cue_states"]["s2"].update(reason="Hidden invalid")))
        for path, mutate in cases:
            previous = path.read_bytes()
            self.modify(path, mutate)
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, "counts|sidecar"):
                self.authenticate(fixture)
            path.write_bytes(previous)

    def test_invalid_only_complete_terminal_promotion_is_rejected(self):
        fixture = self.partial_native()
        pointer = self.modify(fixture["root"] / "trial-completion.json", lambda value: value.update(status="complete"))
        authority = custody._read(fixture["authority"])
        authority["entries"][0]["trial_completion"] = pointer
        fixture["authority"] = self.write("false-complete-authority.json", authority)
        with self.assertRaisesRegex(ValueError, "promoted"):
            self.authenticate(fixture)

    def test_old_control_declared17_captured21_diagnostic9_not_historical_execution(self):
        # Candidate-only authority cannot replace the original control verifier.
        fixture = self.native(control=True, retry=True)
        with self.assertRaisesRegex(ValueError, "authority entries"):
            self.authenticate(fixture)

    def test_real_empty_timeout_and_nonjson_http_retry_shapes_preserve_unknown_cost(self):
        # Both original transport shapes remain meaningful within this helper's
        # candidate-only domain. The unchanged original suite still tests C0.
        for index, (endpoint, raw, status) in enumerate((("/tokenize", b"", None), ("/completion", b"upstream unavailable", 503))):
            with self.subTest(endpoint=endpoint):
                fixture_root = self.root
                self.root = fixture_root / f"transport-case-{index}"
                self.root.mkdir()
                try:
                    original.TransportFailureClient.failed = False
                    original.TransportFailureClient.endpoint = endpoint
                    original.TransportFailureClient.raw = raw
                    original.TransportFailureClient.http_status = status
                    with patch.object(original.fixtures, "TraceClient", original.TransportFailureClient):
                        fixture = self.native()
                    value = custody._read(self.authenticate(fixture, f"transport-{index}.json"))
                    self.assertTrue(value["native_complete"])
                    self.assertEqual(fixture["rows"][0]["attempts"][0]["status"], "failed")
                    if endpoint == "/completion":
                        costs = custody._read(main.identity(fixture["root"] / "delivery/costs.json"))
                        self.assertEqual(costs["output_tokens"]["unknown_records"], 1)
                        self.assertFalse(costs["output_tokens"]["complete"])
                finally:
                    self.root = fixture_root
