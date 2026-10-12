"""Synthetic accepted-call import and universal selection; no inference services."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_eval import runner as e
from experiments.translation_eval.test_runner import window, judgment
from experiments.translation_judge import runner as j
from . import v2_universal_review as u


class UniversalReviewTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        temporary = patch.object(j.tempfile, "tempdir", str(self.root))
        temporary.start()
        self.addCleanup(temporary.stop)
        self.donor = self.root / "donor"
        self.output = self.root / "universal"
        self.calls = []
        self.review_score = 4
        fixtures = [window(f"w{number}", count=1) for number in range(5)]
        e.dump_jsonl(self.root / "inputs.jsonl", [item[0] for item in fixtures])
        e.dump_jsonl(self.root / "references.jsonl", [item[1] for item in fixtures])
        e.dump_jsonl(self.root / "results.jsonl", [{"id": item[0]["id"], "translations": {
            uid: "忠实译文" for uid in item[0]["translate_ids"]}} for item in fixtures])
        e.dump(self.root / "source-manifest.json", {"windows": [{"id": item[0]["id"]} for item in fixtures]})
        e.dump(self.root / "reference-freeze.json", {"corpus_version": "hy30-flow-v2-reference-v1",
               "state": "frozen_double_fresh_reference_review", "inference_allowed": True})
        e.dump(self.root / "source-freeze.json", {"state": "source_frozen_reference_qualified",
               "reference_qualification": {**u.identity(self.root / "reference-freeze.json"),
                 "version": "hy30-flow-v2-reference-v1", "state": "frozen_double_fresh_reference_review",
                 "inference_allowed": True}})
        e.dump(self.root / "decision-policy.json", {"version": "synthetic-policy"})
        self.scope_path = self.root / "evaluation-scope.json"
        e.dump(self.scope_path, {"version": u.VERSION, "state": "frozen_before_candidate_quality",
            "selection": "all_expected_windows", "candidate_quality_judgments_started": False,
            "no_judge_statuses": sorted(e.NO_JUDGE_STATUSES),
            **{name: u.identity(self.root / filename) for name, filename in (
                ("source_manifest", "source-manifest.json"), ("source_freeze", "source-freeze.json"),
                ("reference_freeze", "reference-freeze.json"), ("decision_policy", "decision-policy.json"))}})
        self.prepare(self.donor)

    def prepare(self, directory):
        e.prepare(self.root / "inputs.jsonl", self.root / "references.jsonl",
                  {"A": self.root / "results.jsonl"}, directory,
                  corpus_manifest=self.root / "source-manifest.json")

    def fake(self, args, prompt, cwd, attempt, timeout):
        packet = json.loads(prompt.split("\nPACKET:\n", 1)[1].split("\nADJUDICATION:\n", 1)[0])
        phase = attempt.parents[2].name
        self.calls.append((phase, packet["window_id"]))
        record = judgment(packet, self.review_score if phase == "review" else 4)
        if phase == "adjudication":
            record.update(resolved=True, resolution_zh="合成裁决。")
        e.dump(attempt / "last-message.txt", record)
        return {"transport_status": "completed", "returncode": 0, "returned_models": [j.MODEL],
                "returned_efforts": [j.EFFORT], "tool_events": [], "elapsed_seconds": 0.25}

    def execute(self, root, filename):
        for descriptor in e.load_jsonl(root / filename):
            result = j.run_job(root, descriptor, "synthetic", "fake-1", 1, self.fake)
            self.assertEqual(result["status"], "succeeded")

    def seal(self):
        inventory = [{"path": p.relative_to(self.donor).as_posix(), "sha256": e.sha(p)}
                     for p in sorted(self.donor.rglob("*")) if p.is_file()
                     and p.name not in {"finalization-manifest.json", ".judge-scheduler.lock"}]
        seal = {"version": u.SEAL_VERSION, "state": "required_fresh_judgments_completed",
                "accepted_raw_canonical_integrity_verified": True, "files": inventory,
                **{name: u.identity(self.donor / filename) for name, filename in (
                    ("run", "run.json"), ("expected", "expected.jsonl"), ("final", "final.jsonl"))}}
        e.dump(self.donor / "finalization-manifest.json", seal)

    def complete_donor(self):
        self.execute(self.donor, "jobs.jsonl")
        e.finalize(self.donor, True)
        self.execute(self.donor, "jobs-review.jsonl")
        e.finalize(self.donor)
        self.execute(self.donor, "jobs-adjudication.jsonl")
        e.finalize(self.donor)
        self.seal()

    def hashes(self, directory):
        return {p.relative_to(directory).as_posix(): e.sha(p) for p in directory.rglob("*") if p.is_file()}

    def test_import_reuses_accepted_bytes_and_only_missing_reviews_dispatch(self):
        self.complete_donor()
        original = self.hashes(self.donor)
        count = len(self.calls)
        proof = u.prepare_derivative(self.donor, self.output, self.scope_path)
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.hashes(self.donor), original)
        self.assertEqual(proof["imported_phase_counts"], {"primary": 5, "review": 1, "adjudication": 0})
        run = e.read_json(self.output / "run.json")
        self.assertEqual(run["judgment_import"]["manifest"], u.identity(self.output / "universal-judgment-import.json"))
        for item in proof["frozen_prepared_files"]:
            self.assertEqual((self.output / item["path"]).read_bytes(), (self.donor / item["path"]).read_bytes())
        for item in proof["imported_jobs"]:
            donor = e.read_json(Path(item["donor_ledger"]["path"]))
            target = e.read_json(Path(item["new_ledger"]["path"]))
            for field in u.RELOCATED_FIELDS:
                self.assertTrue(Path(target[field]).is_relative_to(self.output))
                target[field] = donor[field]
            self.assertEqual(donor, target)
            self.assertEqual(Path(item["original_ledger_copy"]["path"]).read_bytes(),
                             Path(item["donor_ledger"]["path"]).read_bytes())
        self.assertFalse((self.output / "finalization-manifest.json").exists())
        self.execute(self.output, "jobs.jsonl")
        self.assertEqual(len(self.calls), count)
        coverage = e.read_json(self.output / "summary.json")["universal_review_coverage"]
        self.assertEqual(coverage, {"expected_records": 5, "judgeable_records": 5, "selected_records": 5,
                                   "accepted_review_records": 1, "known_scored_reviewed_records": 1, "complete": False})
        self.execute(self.output, "jobs-review.jsonl")
        self.assertEqual(len(self.calls), count + 4)
        u.finalize(self.output)
        self.assertTrue(e.read_json(self.output / "summary.json")["universal_review_coverage"]["complete"])
        self.assertTrue(all(row["reviewed"] for row in e.load_jsonl(self.output / "final.jsonl")))
        self.assertEqual(self.hashes(self.donor), original)

    def test_existing_same_dispute_adjudication_imports_without_repeat(self):
        self.review_score = 3
        self.complete_donor()
        count = len(self.calls)
        proof = u.prepare_derivative(self.donor, self.output, self.scope_path)
        self.assertEqual(proof["imported_phase_counts"].get("adjudication"), 1)
        self.execute(self.output, "jobs-adjudication.jsonl")
        self.assertEqual(len(self.calls), count)
        item = next(row for row in proof["imported_jobs"] if row["phase"] == "adjudication")
        self.assertEqual(item["dispute"]["sha256"], e.sha(Path(item["dispute"]["path"])))

    @unittest.skipUnless(os.name == "nt", "native Windows extended-drive evidence")
    def test_windows_extended_paths_are_relocated_but_historical_commands_preserved(self):
        self.complete_donor()
        for ledger in (self.donor / "judge-execution").rglob("job.json"):
            state = e.read_json(ledger)
            for field in u.RELOCATED_FIELDS:
                state[field] = "\\\\?\\" + state[field]
            e.dump(ledger, state)
        self.seal()
        original = self.hashes(self.donor)
        proof = u.prepare_derivative(self.donor, self.output, self.scope_path)
        self.assertEqual(self.hashes(self.donor), original)
        for item in proof["imported_jobs"]:
            donor = e.read_json(Path(item["original_ledger_copy"]["path"]))
            imported = e.read_json(Path(item["new_ledger"]["path"]))
            self.assertEqual(imported["attempts"], donor["attempts"])
            self.assertEqual(imported["fingerprint"], donor["fingerprint"])

    def test_inventory_rejects_raw_packet_and_extra_file_tamper(self):
        self.complete_donor()
        raw = next((self.donor / "judge-execution").rglob("last-message.txt"))
        packet = self.donor / e.load_jsonl(self.donor / "expected.jsonl")[0]["packet"]
        for path in (raw, packet, self.donor / "unexpected.txt"):
            with self.subTest(path=path.name):
                original = path.read_bytes() if path.exists() else None
                path.write_bytes((original or b"") + b" ")
                with self.assertRaisesRegex(ValueError, "inventory"):
                    u.prepare_derivative(self.donor, self.output, self.scope_path)
                self.assertFalse(self.output.exists())
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_replayed_fingerprint_is_rejected_even_with_updated_seal(self):
        self.complete_donor()
        ledger = next((self.donor / "judge-execution").rglob("job.json"))
        state = e.read_json(ledger)
        state["fingerprint"] = "0" * 64
        e.dump(ledger, state)
        self.seal()
        with self.assertRaisesRegex(ValueError, "packet/settings changed"):
            u.prepare_derivative(self.donor, self.output, self.scope_path)
        self.assertFalse(self.output.exists())

    def test_snapshot_tamper_is_rejected_even_with_updated_inventory(self):
        self.complete_donor()
        snapshot = next((self.donor / "judge-execution").rglob("accepted-canonical.json"))
        snapshot.write_bytes(snapshot.read_bytes() + b" ")
        self.seal()
        with self.assertRaisesRegex(ValueError, "raw/canonical/snapshot"):
            u.prepare_derivative(self.donor, self.output, self.scope_path)

    def test_scope_freeze_hash_policy_and_reference_binding(self):
        pointer = u.scope_metadata(self.scope_path)
        self.assertEqual(u.scope_metadata(pointer), pointer)
        with self.assertRaisesRegex(ValueError, "pointer changed"):
            u.scope_metadata({**pointer, "sha256": "0" * 64})
        value = e.read_json(self.scope_path)
        for key, changed in (("state", "late"), ("selection", "risk"),
                             ("candidate_quality_judgments_started", True), ("no_judge_statuses", [])):
            with self.subTest(key=key):
                e.dump(self.scope_path, {**value, key: changed})
                with self.assertRaisesRegex(ValueError, "prior frozen policy"):
                    u.scope_metadata(self.scope_path)
        e.dump(self.scope_path, value)
        source = e.read_json(self.root / "source-freeze.json")
        alternate = self.root / "alternative-reference-freeze.json"
        e.dump(alternate, {"state": "successful-alternate"})
        source["reference_qualification"] = u.identity(alternate)
        e.dump(self.root / "source-freeze.json", source)
        value["source_freeze"] = u.identity(self.root / "source-freeze.json")
        e.dump(self.scope_path, value)
        with self.assertRaisesRegex(ValueError, "accepted source qualification"):
            u.scope_metadata(self.scope_path)

    def test_fresh_scope_apply_is_before_primary_and_automatic_at_finalize(self):
        scope = u.apply_universal_scope(self.donor, self.scope_path)
        self.assertEqual(u.apply_universal_scope(self.donor, self.scope_path), scope)
        self.assertEqual(len(e.load_jsonl(self.donor / "jobs-review.jsonl")), 5)
        self.execute(self.donor, "jobs.jsonl")
        with self.assertRaisesRegex(ValueError, "before any primary"):
            u.apply_universal_scope(self.donor, self.scope_path)
        e.finalize(self.donor, True)
        self.assertEqual(e.read_json(self.donor / "review-selection.json")["selected_ids"], [f"w{number}" for number in range(5)])
        with self.assertRaisesRegex(ValueError, "all expected"):
            e.finalize(self.donor, True, review_selection_override=["w0"])

    def test_override_requires_expected_unique_superset_without_weakening_default(self):
        self.execute(self.donor, "jobs.jsonl")
        primary = {(rec["candidate_alias"], rec["window_id"]): rec for rec in
                   (e.read_json(self.donor / descriptor["response"]) for descriptor in e.load_jsonl(self.donor / "jobs.jsonl"))}
        default = e.select_review(e.load_jsonl(self.donor / "expected.jsonl"), primary)["selected_ids"]
        others = [f"w{number}" for number in range(5) if f"w{number}" not in default]
        for selection in (others, default + ["unknown"], default + default):
            with self.subTest(selection=selection):
                with self.assertRaisesRegex(ValueError, "unique expected-window superset"):
                    e.finalize(self.donor, True, review_selection_override=selection)
        e.finalize(self.donor, True, review_selection_override=[f"w{number}" for number in range(5)])
        self.assertEqual(len(e.load_jsonl(self.donor / "jobs-review.jsonl")), 5)

    def test_universal_denominator_preserves_all_no_judge_states_and_nullable_scores(self):
        rows = e.load_jsonl(self.donor / "expected.jsonl")
        for row, status in zip(rows[1:], sorted(e.NO_JUDGE_STATUSES)):
            row.update(structural_status=status, mapping_reason="合成映射未知。", schedule_reason="合成未执行。")
        e.dump_jsonl(self.donor / "expected.jsonl", rows)
        e.dump_jsonl(self.donor / "jobs.jsonl", [e.job(rows[0], "primary")])
        run = e.read_json(self.donor / "run.json")
        run["expected_sha256"] = e.sha(self.donor / "expected.jsonl")
        e.dump(self.donor / "run.json", run)
        u.apply_universal_scope(self.donor, self.scope_path)
        self.assertEqual(len(e.load_jsonl(self.donor / "jobs-review.jsonl")), 1)
        def unknown(args, prompt, cwd, attempt, timeout):
            result = self.fake(args, prompt, cwd, attempt, timeout)
            record = e.read_json(attempt / "last-message.txt")
            record.update(semantic=None, status="source_ambiguous", uncertainties=[{
                "ids": rows[0]["scored_ids"], "reason_zh": "合成证据未知。"}])
            e.dump(attempt / "last-message.txt", record)
            return result
        for filename in ("jobs.jsonl", "jobs-review.jsonl"):
            for descriptor in e.load_jsonl(self.donor / filename):
                self.assertEqual(j.run_job(self.donor, descriptor, "fake", "fake", 1, unknown)["status"], "succeeded")
        e.finalize(self.donor)
        coverage = e.read_json(self.donor / "summary.json")["universal_review_coverage"]
        self.assertEqual(coverage, {"expected_records": 5, "judgeable_records": 1, "selected_records": 5,
            "accepted_review_records": 1, "known_scored_reviewed_records": 1, "complete": True})
        final = e.load_jsonl(self.donor / "final.jsonl")
        self.assertIsNone(final[0]["semantic"])
        self.assertEqual(final[0]["naturalness"], 2)
        self.assertEqual({row["status"] for row in final[1:]}, e.NO_JUDGE_STATUSES)
        for row in final[1:]:
            self.assertEqual(row["semantic"], 0 if row["status"] == "delivery_zero" else None)
            self.assertIsNone(row["naturalness"])

    def test_frozen_scope_pointer_cannot_rebind_another_prepared_corpus(self):
        alternate = self.root / "alternate-source-manifest.json"
        e.dump(alternate, {"windows": []})
        value = e.read_json(self.scope_path)
        value["source_manifest"] = u.identity(alternate)
        e.dump(self.scope_path, value)
        with self.assertRaisesRegex(ValueError, "prepared corpus identity"):
            u.apply_universal_scope(self.donor, self.scope_path)
        self.assertNotIn("universal_review_scope", e.read_json(self.donor / "run.json"))

    def test_missing_canonical_is_rejected_without_repairing_donor(self):
        self.complete_donor()
        canonical = next((self.donor / "primary").rglob("*.json"))
        canonical.unlink()
        self.seal()
        with self.assertRaises(OSError):
            u.prepare_derivative(self.donor, self.output, self.scope_path)
        self.assertFalse(canonical.exists())
        self.assertFalse(self.output.exists())

    def test_donor_and_derivative_must_be_disjoint_and_new(self):
        self.complete_donor()
        for directory in (self.donor, self.donor / "child", self.root):
            with self.assertRaisesRegex(ValueError, "disjoint"):
                u.prepare_derivative(self.donor, directory, self.scope_path)
        self.output.mkdir()
        (self.output / "existing.txt").write_text("existing", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must be empty"):
            u.prepare_derivative(self.donor, self.output, self.scope_path)


if __name__ == "__main__":
    unittest.main()
