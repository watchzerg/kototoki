"""Native offline F8 diagnostic bridge integration using only synthetic text."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from experiments.translation_eval import runner as e
from experiments.translation_judge import runner as j
from . import test_v2_evaluation as fixtures
from . import v2_delivery as delivery
from . import v2_review_diagnostics as views
from . import v2_review_evaluation as bridge
from .test_v2_universal_review import judgment


class ReviewEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SceneEvaluationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.scopes, self.exported = [], {}
        self.calls, self.review_score = [], 4
        for seed in bridge.SEEDS:
            original = self.native(seed)
            directory = self.root / f"views-{seed}"
            views.export_review_views(original, directory)
            self.exported[seed] = directory
            self.scopes.append(bridge.freeze_scope(self.fixture.manifest_path, self.fixture.input_path,
                self.fixture.reference_path, self.fixture.freeze_path, directory / "before", directory / "after",
                self.root / f"scope-{seed}.json", window_ids=[row["id"] for row in self.fixture.windows]))
        self.frame = bridge.freeze_frame(self.scopes, self.root / "frame.json")
        self.pins = {"registered_frame_sha256": self.frame["sha256"]}

    def native(self, seed, *, review_failed=False, tail=False):
        states = {"scene-b-J2": "not_run"} if tail else {}
        old = self.fixture.delivery(f"seed-{seed}" + ("-failure" if review_failed else ""), states=states)
        metadata = e.read_json(old / "delivery.json")
        packed_path = Path(metadata["packed_mapping"]["path"])
        packed = e.read_json(packed_path)
        packed["seed"] = seed
        e.dump(packed_path, packed)
        original = Path(metadata["run"])
        run = e.read_json(original / "run.json")
        run.update(recipe="c0", settings={"recipe": "c0", "review": True}, packed_mapping_sha256=e.sha(packed_path))
        e.dump(original / "run.json", run)
        ledger, results = e.load_jsonl(original / "ledger.jsonl"), e.load_jsonl(original / "results.jsonl")
        for number, row in enumerate(ledger):
            before = {uid: f"合成初译{uid}" for uid in row["translations"]}
            row["before_review"] = before
            row["attempts"] = []
            for phase, values in (("translation", before), ("source-review", row["translations"])):
                request = {"prompt": [1], "n_predict": 4096}
                response = {"content": json.dumps({"translations": values}, ensure_ascii=False), "tokens_predicted": 5}
                exchange = original / "transport" / f"{number}-{phase}"
                e.dump(exchange / "request.json", {"endpoint": "/completion", "body": request})
                e.dump(exchange / "response.raw", response)
                e.dump(exchange / "transport.json", {"status": 200})
                row["attempts"].append({"stage": phase, "status": "accepted", "completion_dispatched": True,
                    "request": request, "response": response, "original_response": str(exchange),
                    "input_tokens": 10, "elapsed_seconds": .01})
            if review_failed and "scene-a-J1" in before:
                row.update(status="translation_failed", translations={}, failure_stage="source-review", reason="Synthetic review failure")
                row["attempts"][-1]["status"] = "failed"
                results[number].update(status="translation_failed", translations={})
        e.dump_jsonl(original / "ledger.jsonl", ledger)
        e.dump_jsonl(original / "results.jsonl", results)
        output = self.root / (f"authentic-{seed}" + ("-failure" if review_failed else ""))
        delivery.deliver(self.fixture.manifest_path, packed_path, original, output)
        return output

    def prepare(self, seed=bridge.SEEDS[0]):
        root = self.root / f"evaluation-{seed}"
        result = bridge.prepare(self.frame, root, seed=seed, **self.pins)
        return root, result

    def fake(self, args, prompt, cwd, attempt, timeout):
        packet = json.loads(prompt.split("\nPACKET:\n", 1)[1].split("\nADJUDICATION:\n", 1)[0])
        phase = attempt.parents[2].name
        self.calls.append((phase, packet["candidate_alias"], packet["window_id"]))
        value = judgment(packet, self.review_score if phase == "review" else 4)
        if phase == "adjudication":
            value.update(resolved=True, resolution_zh="合成裁决。")
        e.dump(attempt / "last-message.txt", value)
        return {"transport_status": "completed", "returncode": 0, "returned_models": [j.MODEL],
                "returned_efforts": [j.EFFORT], "tool_events": [], "elapsed_seconds": .01}

    def execute(self, root, filename):
        for descriptor in e.load_jsonl(root / filename):
            self.assertEqual(j.run_job(root, descriptor, "synthetic", "synthetic", 1, self.fake)["status"], "succeeded")

    def finish(self, root):
        self.execute(root, "jobs.jsonl")
        bridge.finalize(root, **self.pins)
        self.execute(root, "jobs-review.jsonl")
        bridge.finalize(root, **self.pins)
        self.execute(root, "jobs-adjudication.jsonl")
        return bridge.finalize(root, **self.pins)

    def test_actual_export_prepare_fresh_primary_review_all_three_seed_frame(self):
        for seed in bridge.SEEDS:
            root, result = self.prepare(seed)
            self.assertEqual(result["expected_records"], 6)
            self.assertEqual(result["primary_jobs"], 6)
            run = e.read_json(root / "run.json")
            self.assertEqual(run["original_generation_cost_count"], 1)
            self.assertEqual(run["new_generated_samples"], 0)
            self.assertNotIn("universal_review_scope", run)
            self.assertEqual(run["comparison_role"], bridge.ROLE)
            for row in e.load_jsonl(root / "expected.jsonl"):
                packet = e.read_json(root / row["packet"])
                self.assertEqual(packet["lane"], "P-flow")
                self.assertEqual(len(packet["context"]), 3)
                self.assertEqual(set(packet["reference"]), set(row["scored_ids"]))
                self.assertNotIn("review_diagnostic", packet)
                self.assertNotIn("before", packet)
            self.assertTrue(self.finish(root)["complete"])
            state = bridge.classification_contract(root, **self.pins)
            self.assertFalse(state["root_matching_semantically_confirmed"])
            self.assertEqual(state["severities"], ["minor", "major", "critical"])
            self.assertEqual(state["missing_bounds"]["unknown_pairs"], 3)
        self.assertEqual(len(self.calls), 36)

    def test_actual_dispute_adjudication_remains_bounded(self):
        self.review_score = 2
        root, _ = self.prepare()
        coverage = self.finish(root)
        self.assertTrue(coverage["complete"])
        self.assertEqual(len(e.load_jsonl(root / "jobs-adjudication.jsonl")), 6)
        self.assertEqual(len(self.calls), 18)

    def test_failed_review_and_not_run_tail_preserve_full_pair_denominator(self):
        scopes = []
        for seed in bridge.SEEDS:
            original = self.native(seed, review_failed=True, tail=True)
            directory = self.root / f"failed-views-{seed}"
            views.export_review_views(original, directory)
            scopes.append(bridge.freeze_scope(self.fixture.manifest_path, self.fixture.input_path,
                self.fixture.reference_path, self.fixture.freeze_path, directory / "before", directory / "after",
                self.root / f"failed-scope-{seed}.json", window_ids=[row["id"] for row in self.fixture.windows]))
        self.frame = bridge.freeze_frame(scopes, self.root / "failed-frame.json")
        self.pins = {"registered_frame_sha256": self.frame["sha256"]}
        root, result = self.prepare()
        self.assertEqual(result["expected_records"], 6)
        statuses = {(row["candidate_alias"], row["window_id"]): row["structural_status"] for row in e.load_jsonl(root / "expected.jsonl")}
        self.assertEqual(statuses["c01", "scene-a-Q1"], "valid")
        self.assertEqual(statuses["c02", "scene-a-Q1"], "delivery_zero")
        self.assertEqual(statuses["c01", "scene-b-Q2"], "not_run")
        self.assertEqual(statuses["c02", "scene-b-Q2"], "not_run")
        self.assertTrue(self.finish(root)["complete"])
        finals = {(row["candidate_alias"], row["window_id"]): row for row in e.load_jsonl(root / "final.jsonl")}
        self.assertIsNone(finals["c02", "scene-b-Q2"]["semantic"])

    def test_external_pin_incomplete_frame_seed_and_view_tamper_rejected(self):
        with self.assertRaises(ValueError):
            bridge.prepare(self.frame, self.root / "bad", seed=bridge.SEEDS[0], registered_frame_sha256="a" * 64)
        with self.assertRaisesRegex(ValueError, "three-seed"):
            bridge.freeze_frame(self.scopes[:2], self.root / "short-frame.json")
        with self.assertRaises(ValueError):
            bridge.prepare(self.frame, self.root / "bad", seed=1, **self.pins)
        directory = self.exported[bridge.SEEDS[0]] / "before"
        result = e.load_jsonl(directory / "results.jsonl")
        result[0]["translations"] = {"scene-a-J1": "tampered"}
        e.dump_jsonl(directory / "results.jsonl", result)
        with self.assertRaisesRegex(ValueError, "immutable same-run"):
            self.prepare()
        self.assertFalse((self.root / f"evaluation-{bridge.SEEDS[0]}").exists())

    def test_wrong_phase_cost_seed_and_reference_binding_rejected(self):
        directory = self.exported[bridge.SEEDS[0]] / "before"
        document = e.read_json(directory / "delivery.json")
        for field, value in (("seed", 0), ("costs", {})):
            changed = deepcopy(document)
            changed[field] = value
            e.dump(directory / "delivery.json", changed)
            with self.assertRaises(ValueError):
                bridge.freeze_scope(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path,
                    self.fixture.freeze_path, directory, self.exported[bridge.SEEDS[0]] / "after", self.root / "bad-scope.json",
                    window_ids=[row["id"] for row in self.fixture.windows])
        e.dump(directory / "delivery.json", document)
        with self.assertRaises(ValueError):
            bridge.freeze_scope(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path,
                self.fixture.freeze_path, self.exported[bridge.SEEDS[0]] / "after", directory, self.root / "bad-scope.json",
                window_ids=[row["id"] for row in self.fixture.windows])
        self.fixture.freeze("primary_only")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_import_relabel_packet_tamper_and_historical_opinions_rejected(self):
        root, _ = self.prepare()
        run = e.read_json(root / "run.json")
        e.dump(root / "run.json", {**run, "judgment_import": {}})
        with self.assertRaises(ValueError):
            bridge.validate_prepared(root, **self.pins)
        e.dump(root / "run.json", run)
        self.execute(root, "jobs.jsonl")
        descriptor = e.load_jsonl(root / "jobs.jsonl")[0]
        ledger = root / "judge-execution" / descriptor["job_id"] / "job.json"
        state = e.read_json(ledger)
        state["attempts"][0]["started_at"] = "2020-01-01T00:00:00+00:00"
        e.dump(ledger, state)
        with self.assertRaisesRegex(ValueError, "historical"):
            bridge.finalize(root, **self.pins)

    def test_literal_root_evidence_validation_does_not_assert_semantic_categories(self):
        root, _ = self.prepare()
        claim = {"window_id": "scene-a-Q1", "root_id": "fact-1", "ids": ["scene-a-J1"], "category": "corrected",
                 "source_evidence": "台詞1-1", "before_evidence": "合成初译scene-a-J1",
                 "after_evidence": "合成译文scene-a-J1", "reason_zh": "合成命题对应，须独立语义核验。",
                 "source_proposition_zh": "合成源命题。", "cause_zh": "合成初译事实错误。",
                 "before_error": {"type": "mistranslation", "severity": "minor"}, "after_error": None}
        state = bridge.validate_evidence_claims(root, [claim], **self.pins)
        self.assertFalse(state["semantic_classification_confirmed"])
        self.assertEqual(state["unknown_pairs"], 3)
        for field in ("source_evidence", "before_evidence", "after_evidence"):
            with self.assertRaises(ValueError):
                bridge.validate_evidence_claims(root, [{**claim, field: "invented"}], **self.pins)
        with self.assertRaises(ValueError):
            bridge.validate_evidence_claims(root, [{"window_id": "scene-a-Q1", "root_id": "score+1", "category": "corrected"}], **self.pins)
        with self.assertRaises(ValueError):
            bridge.validate_evidence_claims(root, [claim, claim], **self.pins)
        for error in ({"type": "mistranslation", "severity": "major"}, {"type": "omission", "severity": "critical"}):
            state = bridge.validate_evidence_claims(root, [{**claim, "category": "missed", "before_error": error,
                "after_error": error, **({"before_evidence": "", "after_evidence": ""} if error["type"] == "omission" else {})}], **self.pins)
            self.assertFalse(state["semantic_classification_confirmed"])

    def test_self_consistent_packet_and_structural_rewrite_cannot_replace_authentic_views(self):
        root, _ = self.prepare()
        run = e.read_json(root / "run.json")
        relative = next(iter(run["packet_sha256"]))
        original = e.read_json(root / relative)
        for field, data in (("translations", {"scene-a-J1": "forged"}),
                            ("structural", {"status": "not_run"}), ("before", True)):
            e.dump(root / relative, {**original, field: data})
            changed = deepcopy(run)
            changed["packet_sha256"][relative] = e.sha(root / relative)
            e.dump(root / "run.json", changed)
            with self.assertRaisesRegex(ValueError, "packet differs"):
                bridge.validate_prepared(root, **self.pins)

    def test_pending_primary_and_review_failure_keep_unknown_pair_bounds(self):
        root, _ = self.prepare()
        with self.assertRaisesRegex(ValueError, "terminal primary"):
            bridge.finalize(root, **self.pins)
        jobs = e.load_jsonl(root / "jobs.jsonl")
        def failure(*args):
            return {"transport_status": "failed", "returncode": 1, "returned_models": [], "returned_efforts": [], "tool_events": []}
        self.assertEqual(j.run_job(root, jobs[0], "synthetic", "synthetic", 1, failure)["status"], "judge_failed")
        for descriptor in jobs[1:]:
            j.run_job(root, descriptor, "synthetic", "synthetic", 1, self.fake)
        bridge.finalize(root, **self.pins)
        finals = e.load_jsonl(root / "final.jsonl")
        self.assertEqual(len(finals), 6)
        failed = next(row for row in finals if (row["candidate_alias"], row["window_id"]) ==
                      (jobs[0]["candidate_alias"], jobs[0]["window_id"]))
        self.assertIsNone(failed["semantic"])
        jobs = e.load_jsonl(root / "jobs-review.jsonl")
        for descriptor in jobs[1:]:
            j.run_job(root, descriptor, "synthetic", "synthetic", 1, self.fake)
        coverage = bridge.finalize(root, **self.pins)
        self.assertFalse(coverage["complete"])
        row = next(row for row in e.load_jsonl(root / "final.jsonl") if (row["candidate_alias"], row["window_id"]) ==
                   (jobs[0]["candidate_alias"], jobs[0]["window_id"]))
        self.assertIn(row["status"], {"review_failed", "judge_failed"})
        self.assertIsNone(row["semantic"])
        bounds = bridge.classification_contract(root, **self.pins)["missing_bounds"]
        self.assertEqual((bounds["known_classified_pairs"], bounds["unknown_pairs"]), (0, 3))


if __name__ == "__main__":
    unittest.main()
