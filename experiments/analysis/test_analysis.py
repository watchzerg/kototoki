"""Synthetic offline validation; no private corpus or held-out data is opened."""

import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from kototoki_eval import evaluate

from .aggregate import aggregate_manifest


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.counter = 0

    def write(self, document):
        self.counter += 1
        path = self.root / f"artifact-{self.counter}.json"
        data = json.dumps(document, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        return str(path), hashlib.sha256(data).hexdigest()

    def scene(self, name="scene-a", text="abc"):
        ref = {"schema_version": 1, "reference_kind": "srt_display",
               "spans": [{"id": "span-a", "text": text, "start": 0, "end": len(text)}] if text else []}
        path, digest = self.write(ref)
        return {"id": name, "reference_path": path, "reference_sha256": digest}, ref

    def make_run(self, scene, ref, text="abc", status="completed", offset=0):
        hyp = {"schema_version": 1, "text": text, "cues": [],
               "units": [{"char_start": i, "char_end": i + 1, "start": i + offset,
                          "end": i + offset + 1, "granularity": "character"} for i in range(len(text))]}
        path, digest = self.write(evaluate(ref, hyp))
        return {"scene_id": scene["id"], "run_id": "run-a", "status": status,
                "execution_verified": status == "completed", "evaluation_path": path, "evaluation_sha256": digest}

    def manifest(self, scenes, *routes):
        return {"schema_version": 1, "manifest_id": "synthetic-v1", "frozen": True,
                "reference_kind": "srt_display", "scenes": scenes, "routes": list(routes)}

    def route(self, name, runs):
        return {"id": name, "configuration_id": "fixed-v1", "runs": runs}

    def test_missing_run_keeps_full_denominator(self):
        scene, ref = self.scene()
        report = aggregate_manifest(self.manifest([scene], self.route("route", [])), base=self.root)
        result = report["routes"][0]["summary"]
        self.assertEqual(result["text"]["D"], 3)
        self.assertEqual(result["text"]["CER"], 1)
        self.assertEqual(result["timing"]["denominator"], 1)
        self.assertEqual(result["timing"]["status_counts"], {"missing_run": 1})
        self.assertEqual(result["missing_run_count"], 1)
        self.assertTrue(math.isinf(result["timing"]["joint_completeness_timing"]["p95"]))

    def test_alignment_failure_preserves_recognized_text(self):
        scene, ref = self.scene()
        run = self.make_run(scene, ref, status="alignment_failed")
        report = aggregate_manifest(self.manifest([scene], self.route("route", [run])), base=self.root)
        result = report["routes"][0]["summary"]
        self.assertEqual(result["text"]["CER"], 0)
        self.assertEqual(result["timing"]["status_counts"], {"alignment_failure": 1})
        self.assertEqual(result["timing"]["success"]["5.0"]["upper"], 0)
        self.assertEqual(result["alignment_failure_count"], 1)

    def test_invocation_failure_full_deletion_partial_separate(self):
        scene, ref = self.scene()
        run = self.make_run(scene, ref, text="ab", status="invocation_failed")
        report = aggregate_manifest(self.manifest([scene], self.route("route", [run])), base=self.root)
        record = report["routes"][0]["scene_records"][0]
        self.assertEqual(record["text"]["D"], 3)
        self.assertEqual(record["partial_output_text_counts"]["D"], 1)
        self.assertEqual(report["routes"][0]["summary"]["invocation_failure_count"], 1)

    def test_unknown_execution_retains_metrics_excludes_eligibility(self):
        scene, ref = self.scene()
        run = self.make_run(scene, ref, status="execution_unverified")
        report = aggregate_manifest(self.manifest([scene], self.route("route", [run])), base=self.root)
        result = report["routes"][0]["summary"]
        self.assertEqual(result["text"]["CER"], 0)
        self.assertEqual(result["timing"]["measurable_count"], 1)
        self.assertFalse(result["all_execution_verified"])
        self.assertEqual(result["execution_unverified_count"], 1)
        self.assertEqual(report["ranking"], "not_performed")

    def test_silence_insertion_enters_corpus_micro(self):
        speech, ref = self.scene()
        silent, silence_ref = self.scene("silent", "")
        report = aggregate_manifest(self.manifest([speech, silent], self.route("route", [
            self.make_run(speech, ref), self.make_run(silent, silence_ref, "xyz")])), base=self.root)
        self.assertEqual(report["routes"][0]["summary"]["text"]["CER"], 1)
        self.assertEqual(report["routes"][0]["summary"]["text"]["I"], 3)

    def test_common_valid_subset_keeps_original_coverage(self):
        scene, ref = self.scene()
        report = aggregate_manifest(self.manifest([scene], self.route("good", [self.make_run(scene, ref)]),
                                                 self.route("failed", [])), base=self.root)
        comparison = report["comparisons"][0]
        self.assertEqual(comparison["common_valid_count"], 0)
        self.assertEqual(comparison["left_full_coverage"], 1)
        self.assertEqual(comparison["right_full_coverage"], 0)
        self.assertIsNone(comparison["common_p95_difference"])
        self.assertEqual(comparison["paired_scene_bootstrap"]["status"], "not_run")

    def test_identity_and_rule_mismatch_rejected(self):
        scene, ref = self.scene()
        run = self.make_run(scene, ref)
        manifest = self.manifest([scene], self.route("route", [run]))
        bad = copy.deepcopy(manifest)
        bad["scenes"][0]["reference_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            aggregate_manifest(bad, base=self.root)
        data = json.loads(Path(run["evaluation_path"]).read_text(encoding="utf-8"))
        data["rule_version"] = "old-rule"
        path, digest = self.write(data)
        bad = copy.deepcopy(manifest)
        bad["routes"][0]["runs"][0].update(evaluation_path=path, evaluation_sha256=digest)
        with self.assertRaises(ValueError):
            aggregate_manifest(bad, base=self.root)

    def test_private_text_not_in_report(self):
        private = "privateSECRETutterance"
        scene, ref = self.scene(text=private)
        run = self.make_run(scene, ref, private)
        report = aggregate_manifest(self.manifest([scene], self.route("route", [run])), base=self.root)
        self.assertNotIn(private, json.dumps(report))

    def test_no_selective_extra_scene_or_duplicate_route(self):
        scene, ref = self.scene()
        run = self.make_run(scene, ref)
        run["scene_id"] = "not-frozen"
        with self.assertRaises(ValueError):
            aggregate_manifest(self.manifest([scene], self.route("route", [run])), base=self.root)
        with self.assertRaises(ValueError):
            aggregate_manifest(self.manifest([scene], self.route("route", []), self.route("route", [])), base=self.root)

    def test_bootstrap_scene_floor_seed_nonfinite_guard(self):
        scene, ref = self.scene()
        report = aggregate_manifest(self.manifest([scene], self.route("a", [self.make_run(scene, ref)]),
                                                 self.route("b", [])), base=self.root, bootstrap=True)
        self.assertEqual(report["comparisons"][0]["paired_scene_bootstrap"]["reason"], "fewer_than_10_fixed_scenes")
        scenes, left, right = [], [], []
        for i in range(10):
            scene, ref = self.scene(f"scene-{i}", "a")
            scenes.append(scene)
            left.append(self.make_run(scene, ref, "a"))
            right.append(self.make_run(scene, ref, "a", status="invocation_failed"))
        report = aggregate_manifest(self.manifest(scenes, self.route("a", left), self.route("b", right)),
                                    base=self.root, bootstrap=True)
        boot = report["comparisons"][0]["paired_scene_bootstrap"]
        self.assertEqual(boot["seed"], 20261004)
        self.assertEqual(boot["replicates"], 2000)
        self.assertEqual(boot["metrics"]["joint_p95"]["nonfinite_replicates"], 2000)
        self.assertIsNone(boot["metrics"]["joint_p95"]["finite_conditional_percentile_interval_95"])
        self.assertEqual(boot["metrics"]["CER"]["finite_conditional_percentile_interval_95"], [-1.0, -1.0])


if __name__ == "__main__":
    unittest.main()

