"""Offline frozen-registry, partial-alignment and process-cost tests."""

import json
from pathlib import Path
import tempfile
import unittest

from experiments.vad_comparison import evaluate as evaluator


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vad-eval-test-", dir=evaluator.ROOT / ".local")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.audio = self.base / "audio.wav"
        self.audio.write_bytes(b"synthetic identity fixture, never infer")
        self.reference = self.save("reference.json", {"schema_version": 1, "reference_kind": "srt_display",
            "spans": [{"id": "first", "text": "AB", "start": 11, "end": 12},
                      {"id": "second", "text": "CD", "start": 13, "end": 14}]})
        self.clip = {"id": "one", "film": "II", "offset": 10, "duration": 10,
            "audio": str(self.audio), "audio_sha256": evaluator.digest(self.audio),
            "reference": str(self.reference), "reference_sha256": evaluator.digest(self.reference)}
        self.plan = self.save("plan.json", {"clips": [self.clip]})
        self.result = {"schema_version": 1, "status": "ok", "text": "ABCD", "source_start_seconds": 10,
            "duration_seconds": 10, "input_sha256": evaluator.digest(self.audio), "cues": [],
            "units": [{"char_start": 0, "char_end": 2, "start": 11, "end": 12, "granularity": "word", "status": "ok"},
                      {"char_start": 2, "char_end": 4, "start": 13, "end": 14, "granularity": "word", "status": "ok"}],
            "chunks": [{"start": 0, "end": 5}, {"start": 5, "end": 10}],
            "original_segments": [{"text": "AB"}, {"text": "CD"}],
            "asr_traces": [{}, {}], "cached_inference": False, "offline_requested": True,
            "effective_parameters": {"asr": {"device": "cuda"}, "alignment": {"model": "cuda:0"}},
            "alignment_records": [{"model_output_device": "cuda:0", "decoder_input_device": "cuda:0",
                                   "decoder_output_device": "cuda:0", "normalization": {"actual_input_device": "cuda:0"}}]}
        self.result_path = self.save("result.json", self.result)
        self.run = {"clip_id": "one", "run_id": "synthetic", "status": "completed",
            "result_path": str(self.result_path), "result_sha256": evaluator.digest(self.result_path),
            "process_wall_s": 4, "vad_process_wall_s": 2}

    def save(self, name, document):
        path = self.base / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def study(self, runs=None):
        return {"schema_version": 1, "study_id": "synthetic", "terminal": True,
                "expected_route_ids": ["w0-original"],
                "source_plan_path": str(self.plan), "source_plan_sha256": evaluator.digest(self.plan),
                "clips": [self.clip], "routes": [{"id": "w0-original", "configuration_id": "synthetic-only",
                                                     "runs": [self.run] if runs is None else runs}]}

    def build(self, study, name="out"):
        path = self.save(name + "-study.json", study)
        return evaluator.evaluate_study(path, self.base / name, bootstrap=False)

    def summary(self, report):
        return report["report"]["pooled"]["routes"][0]["summary"]

    def test_missing_slots_preserve_all_reference_denominators(self):
        report = self.build(self.study([]))
        summary = self.summary(report)
        self.assertEqual(summary["text"]["D"], 4)
        self.assertEqual(summary["timing"]["denominator"], 2)
        self.assertEqual(summary["missing_run_count"], 1)
        self.assertIsNone(report["cost_rows"][0]["reconstructed_serial_wall_s"])
        diagnostics = json.loads((self.base / "out/diagnostics.json").read_text())
        self.assertEqual(len(diagnostics["runs"]), 1)
        self.assertEqual(diagnostics["runs"][0]["declared_status"], "missing")

    def test_partial_alignment_preserves_text_and_remaining_valid_timing(self):
        self.result["status"] = "partial"
        self.result["units"][1] = {"char_start": 2, "char_end": 4, "granularity": "word", "status": "text_only"}
        self.result["alignment_records"].append({"failure": "synthetic inference failure"})
        self.save("result.json", self.result)
        self.run.update(status="partial", result_sha256=evaluator.digest(self.result_path))
        report = self.build(self.study())
        summary = self.summary(report)
        self.assertEqual(summary["text"]["CER"], 0)
        self.assertEqual(summary["timing"]["denominator"], 2)
        self.assertEqual(summary["timing"]["measurable_count"], 1)
        self.assertEqual(summary["timing"]["success"]["0.5"]["success_count"], 1)
        self.assertEqual(summary["timing"]["status_counts"]["text_only"], 1)
        self.assertFalse(summary["all_execution_verified"])
        self.assertEqual(report["cost_rows"][0]["partial_run_count"], 1)

    def test_asr_invocation_failure_partial_text_only_diagnostic(self):
        report = self.build(self.study([{**self.run, "status": "invocation_failed"}]))
        self.assertEqual(self.summary(report)["text"]["D"], 4)
        record = report["report"]["pooled"]["routes"][0]["scene_records"][0]
        self.assertEqual(record["partial_output_text_counts"]["D"], 0)
        self.assertEqual(self.summary(report)["invocation_failure_count"], 1)

    def test_costs_separate_measurement_and_shared_reconstruction(self):
        report = self.build(self.study())
        self.assertEqual(report["cost_rows"][0]["reconstructed_serial_wall_s"], 6)
        diagnostics = json.loads((self.base / "out/diagnostics.json").read_text())
        costs = diagnostics["runs"][0]["costs"]
        self.assertEqual(costs["fresh_demo_process_wall_s"], 4)
        self.assertEqual(costs["shared_vad_process_wall_s"], 2)
        self.assertIn("not a separately measured", costs["scope"])

    def test_duplicate_unknown_active_slots_and_subset_registry_rejected(self):
        for change, message in (("duplicate", "Duplicate"), ("unknown", "unknown"), ("active", "terminal"),
                                ("subset", "exact complete"), ("notterminal", "terminal=true")):
            with self.subTest(change=change):
                study = self.study()
                if change == "duplicate":
                    study["routes"][0]["runs"] *= 2
                elif change == "unknown":
                    study["routes"][0]["runs"][0] = {**self.run, "clip_id": "outside"}
                elif change == "active":
                    study["routes"][0]["runs"][0] = {**self.run, "status": "running"}
                elif change == "subset":
                    study["clips"] = []
                else:
                    study["terminal"] = False
                with self.assertRaisesRegex(ValueError, message):
                    self.build(study, change)

    def test_reference_and_result_hash_changes_rejected(self):
        study = self.study()
        study["source_plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "plan SHA256"):
            self.build(study, "bad-plan")
        study = self.study([{**self.run, "result_sha256": "0" * 64}])
        with self.assertRaisesRegex(ValueError, "Result SHA256"):
            self.build(study, "bad-result")
        self.reference.write_text("{}")
        with self.assertRaisesRegex(ValueError, "reference SHA256"):
            self.build(self.study(), "bad-reference")

    def test_device_or_cache_unknown_retains_scores_without_eligibility(self):
        self.result["effective_parameters"]["asr"]["device"] = "cpu"
        self.save("result.json", self.result)
        self.run["result_sha256"] = evaluator.digest(self.result_path)
        summary = self.summary(self.build(self.study()))
        self.assertEqual(summary["text"]["CER"], 0)
        self.assertFalse(summary["all_execution_verified"])
        proof = evaluator.execution_proof({**self.result, "cached_inference": True})
        self.assertFalse(proof["execution_observations_pass"])

    def test_default_registry_requires_all_ten_routes(self):
        study = self.study()
        study.pop("expected_route_ids")
        with self.assertRaisesRegex(ValueError, "expected route IDs"):
            self.build(study)

    def test_native_vad_duration_is_union_and_keeps_raw_sum_separate(self):
        self.result["effective_parameters"]["vad"] = {"origin_metadata": {
            "raw_intervals": [{"start_seconds": 0, "end_seconds": 3}, {"start_seconds": 2, "end_seconds": 4}],
            "accounting": {"speech_samples": 64000, "chunk_samples": 160000}}}
        diagnostics = evaluator.chunk_diagnostics(self.result)
        self.assertEqual(diagnostics["raw_speech_duration_s"], 4)
        self.assertEqual(diagnostics["native_raw_interval_duration_sum_s"], 5)
        self.assertEqual(diagnostics["source_window_retained_duration_s"], 10)

    def test_inference_source_mismatch_exposes_mixed_route_ignoring_tests(self):
        baseline = {"clip_id": "one", "run_id": "first", "source_sha256": {
            "run.py": "a", "test_run.py": "old"}, "shared_source_sha256": {"schema.py": "s"}}
        tests_changed = {**baseline, "clip_id": "two", "run_id": "second",
                         "source_sha256": {"run.py": "a", "test_run.py": "new"}}
        self.assertEqual(evaluator.source_consistency([baseline, tests_changed])["status"], "consistent_in_observed_runs")
        changed = {**tests_changed, "shared_source_sha256": {"schema.py": "changed"}}
        diagnosis = evaluator.source_consistency([baseline, changed, {"clip_id": "three"}])
        self.assertEqual(diagnosis["status"], "heterogeneous")
        self.assertEqual(diagnosis["unique_inference_source_identity_count"], 2)
        self.assertEqual(diagnosis["source_evidence_missing_run_count"], 1)
        self.assertEqual(diagnosis["different_from_first_observed"], [{"clip_id": "two", "run_id": "second"}])

    def test_vad_manifest_identity_must_bind_demo_result(self):
        manifest = self.save("vad-manifest.json", {"input": {"file_sha256": evaluator.digest(self.audio)},
            "offset_s": 10, "metadata": {}, "stages": {}})
        self.run.update(vad_manifest_path=str(manifest), vad_manifest_sha256=evaluator.digest(manifest))
        with self.assertRaisesRegex(ValueError, "bind declared VAD"):
            self.build(self.study(), "unbound")
        self.result["vad_manifest_source"] = {"sha256": evaluator.digest(manifest)}
        self.save("result.json", self.result)
        self.run["result_sha256"] = evaluator.digest(self.result_path)
        self.assertEqual(self.summary(self.build(self.study()))["text"]["CER"], 0)

    def test_private_output_no_overwrite_and_no_transcript_text(self):
        report = self.build(self.study())
        self.assertNotIn("ABCD", json.dumps(report))
        self.assertNotIn("ABCD", (self.base / "out/diagnostics.json").read_text())
        with self.assertRaisesRegex(ValueError, "new analysis"):
            evaluator.evaluate_study(self.base / "out-study.json", self.base / "out")

    def test_partial_without_result_rejects_and_complete_missing_keeps_denominator(self):
        for status in ("partial", "alignment_failed"):
            with self.assertRaisesRegex(ValueError, "preserved ASR"):
                self.build(self.study([{**self.run, "status": status, "result_path": str(self.base / "missing.json")}]), status)
        report = self.build(self.study([{**self.run, "result_path": str(self.base / "missing.json")}]))
        self.assertEqual(self.summary(report)["missing_run_count"], 1)


if __name__ == "__main__":
    unittest.main()
