"""Offline accounting, identity and unchanged-text ablation evaluator tests."""

import json
from pathlib import Path
import tempfile
import unittest

from experiments.components import evaluate as evaluator


class ComponentEvaluationTests(unittest.TestCase):
    def setUp(self):
        private = evaluator.ROOT / ".local"
        private.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="component-evaluator-test-", dir=private)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.audio = self.base / "synthetic.wav"
        self.audio.write_bytes(b"synthetic audio identity; no inference")
        self.reference = {"schema_version": 1, "reference_kind": "srt_display", "corpus_revision": "synthetic",
            "spans": [{"id": "edge", "text": "AB", "start": 9, "end": 11},
                      {"id": "inside", "text": "CD", "start": 12, "end": 13}]}
        self.reference_path = self.save("reference.json", self.reference)
        self.transcript = {"schema_version": 1, "text": "ABCD", "source_start_seconds": 10, "duration_seconds": 10,
            "input_sha256": evaluator.digest(self.audio), "units": [
                {"char_start": 0, "char_end": 2, "start": 10, "end": 11, "granularity": "word"},
                {"char_start": 2, "char_end": 4, "start": 12, "end": 13, "granularity": "word"}],
            "cues": [{"text": "ABCD", "start": 10, "end": 13}]}
        self.result_path = self.save("result.json", self.transcript)
        self.clip = {"id": "window-1", "film": "II", "offset": 10, "duration": 10,
            "audio": self.audio.name, "audio_sha256": evaluator.digest(self.audio),
            "reference": self.reference_path.name, "reference_sha256": evaluator.digest(self.reference_path)}
        self.run = {"clip_id": self.clip["id"], "run_id": "one", "status": "completed", "execution_verified": True,
            "result_path": self.result_path.name, "result_sha256": evaluator.digest(self.result_path)}

    def save(self, name, document):
        path = self.base / name
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        return path

    def manifest(self, runs=None):
        return {"schema_version": 1, "manifest_id": "synthetic", "frozen": True, "clips": [self.clip],
            "source_sha256": {"reference.json": evaluator.digest(self.reference_path)},
            "configurations": [{"id": "baseline", "configuration_id": "synthetic-baseline", "runs": [self.run] if runs is None else runs}]}

    def build(self, manifest, name="output", bootstrap=False):
        path = self.save(f"{name}-manifest.json", manifest)
        report = evaluator.build(path, self.base / name, bootstrap=bootstrap)
        return report

    def test_missing_slot_and_missing_declared_file_keep_full_denominator(self):
        for runs, name in (([], "absent-slot"), ([{**self.run, "result_path": "missing.json"}], "absent-artifact")):
            with self.subTest(name=name):
                report = self.build(self.manifest(runs), name)
                summary = report["pooled"]["routes"][0]["summary"]
                self.assertEqual(summary["text"]["reference_characters"], 4)
                self.assertEqual(summary["text"]["D"], 4)
                self.assertEqual(summary["text"]["CER"], 1)
                self.assertEqual(summary["timing"]["denominator"], 2)
                self.assertEqual(summary["missing_run_count"], 1)
                self.assertEqual(summary["timing"]["status_counts"], {"missing_run": 2})

    def test_crossing_boundary_remains_uncertain_at_every_threshold(self):
        report = self.build(self.manifest())
        route = report["pooled"]["routes"][0]
        self.assertEqual(route["summary"]["text"]["CER"], 0)
        self.assertEqual(route["summary"]["timing"]["denominator"], 2)
        self.assertEqual(route["summary"]["timing"]["measurable_count"], 1)
        for threshold in ("0.5", "2.0", "5.0"):
            success = route["summary"]["timing"]["success"][threshold]
            self.assertEqual(success["success_count"], 1)
            self.assertEqual(success["unresolved_count"], 1)
            self.assertEqual((success["lower"], success["upper"]), (.5, 1))
        self.assertEqual(route["interior_timing_only"]["denominator"], 1)
        self.assertEqual(report["pooled"]["edge_reference"]["cue_ids_by_scene"], {"window-1": ["edge"]})

    def test_full_transcript_unchanged_and_unrendered_insertions_are_scored(self):
        self.transcript["text"] += "TAIL"
        self.result_path = self.save("result.json", self.transcript)
        self.run["result_sha256"] = evaluator.digest(self.result_path)
        before = self.result_path.read_bytes()
        report = self.build(self.manifest())
        text = report["pooled"]["routes"][0]["summary"]["text"]
        self.assertEqual(text["I"], 4)
        self.assertEqual(text["candidate_characters"], 8)
        self.assertEqual(before, self.result_path.read_bytes())
        facts = json.loads((self.base / "output/execution-evidence.json").read_text(encoding="utf-8"))
        coverage = facts["runs"]["0:0"]["display"]["coverage"]
        self.assertEqual(coverage["full_original_characters"], 8)
        self.assertEqual(coverage["unrendered_characters"], 4)
        for value in (report, facts):
            self.assertNotIn("ABCD", json.dumps(value))
            self.assertNotIn("TAIL", json.dumps(value))

    def test_invocation_failure_counts_all_deletions_and_retains_partial_diagnostics(self):
        report = self.build(self.manifest([{**self.run, "status": "invocation_failed"}]))
        route = report["pooled"]["routes"][0]
        self.assertEqual(route["summary"]["text"]["D"], 4)
        self.assertEqual(route["summary"]["invocation_failure_count"], 1)
        self.assertEqual(route["scene_records"][0]["partial_output_text_counts"]["D"], 0)
        self.assertEqual(route["summary"]["timing"]["status_counts"], {"invocation_failure": 2})

    def test_alignment_failure_preserves_text_and_excludes_all_timing(self):
        report = self.build(self.manifest([{**self.run, "status": "alignment_failed"}]))
        summary = report["pooled"]["routes"][0]["summary"]
        self.assertEqual(summary["text"]["D"], 0)
        self.assertEqual(summary["text"]["candidate_characters"], 4)
        self.assertEqual(summary["timing"]["status_counts"], {"alignment_failure": 2})
        self.assertEqual(summary["alignment_failure_count"], 1)
        with self.assertRaisesRegex(ValueError, "independently complete"):
            self.build(self.manifest([{**self.run, "status": "alignment_failed", "result_path": "absent.json"}]), "absent-asr")

    def test_unverified_execution_does_not_discard_scores(self):
        report = self.build(self.manifest([{**self.run, "execution_verified": False}]))
        summary = report["pooled"]["routes"][0]["summary"]
        self.assertEqual(summary["text"]["CER"], 0)
        self.assertFalse(summary["all_execution_verified"])
        self.assertEqual(summary["execution_status_counts"], {"execution_unverified": 1})

    def test_hash_mismatch_and_source_mapping_rejected(self):
        manifest = self.manifest()
        manifest["configurations"][0]["runs"][0]["result_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.build(manifest, "wrong-result-hash")
        self.transcript["source_start_seconds"] = 0
        self.save("result.json", self.transcript)
        self.run["result_sha256"] = evaluator.digest(self.result_path)
        with self.assertRaisesRegex(ValueError, "offset differs"):
            self.build(self.manifest(), "wrong-offset")

    def test_frozen_input_and_source_file_hashes_rejected(self):
        manifest = self.manifest()
        manifest["clips"][0]["audio_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Input/source SHA256 mismatch"):
            self.build(manifest, "wrong-audio")
        self.clip["audio_sha256"] = evaluator.digest(self.audio)
        manifest = self.manifest()
        manifest["source_sha256"]["reference.json"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Input/source SHA256 mismatch"):
            self.build(manifest, "wrong-source")

    def test_pairwise_common_subset_and_bootstrap_at_ten_fixed_windows(self):
        manifest = self.manifest()
        manifest["clips"] = [{**self.clip, "id": f"clip-{index}", "film": "II" if index < 6 else "III"} for index in range(10)]
        runs = [{**self.run, "clip_id": clip["id"]} for clip in manifest["clips"]]
        manifest["configurations"] = [
            {"id": "left", "configuration_id": "left-fixed", "runs": runs},
            {"id": "right", "configuration_id": "right-fixed", "runs": runs[:-1]}]
        report = self.build(manifest, bootstrap=True)
        pair = report["pooled"]["comparisons"][0]
        self.assertEqual(pair["common_valid_count"], 9)
        self.assertEqual(pair["full_denominator"], 20)
        self.assertEqual(pair["left_full_coverage"], .5)
        self.assertEqual(pair["right_full_coverage"], .45)
        bootstrap = pair["paired_scene_bootstrap"]
        self.assertEqual(bootstrap["scene_count"], 10)
        self.assertEqual(bootstrap["seed"], 20261004)
        self.assertEqual(bootstrap["replicates"], 2000)
        self.assertEqual(bootstrap["status"], "descriptive_only")
        for film in report["films"].values():
            self.assertEqual(film["comparisons"][0]["paired_scene_bootstrap"]["status"], "not_run")
        self.assertEqual(report["films"]["III"]["routes"][1]["summary"]["missing_run_count"], 1)
        saved = (self.base / "output/report.json").read_text(encoding="utf-8")
        self.assertIn('"infinity"', saved)
        self.assertNotIn("Infinity", saved)

    def test_registry_rejects_duplicate_or_foreign_runs(self):
        for runs in ([self.run, self.run], [{**self.run, "clip_id": "unknown"}]):
            with self.subTest(runs=runs), self.assertRaises(ValueError):
                self.build(self.manifest(runs))
        self.assertFalse((self.base / "output").exists())

    def test_output_must_be_new_and_private(self):
        manifest_path = self.save("manifest.json", self.manifest())
        with self.assertRaisesRegex(ValueError, "new private"):
            evaluator.build(manifest_path, evaluator.ROOT / "public-component-report")
        self.build(self.manifest())
        saved = (self.base / "output/report.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "new private"):
            evaluator.build(manifest_path, self.base / "output")
        self.assertEqual(saved, (self.base / "output/report.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
