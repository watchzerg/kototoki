"""Offline five-family comparison, completeness, and denominator checks."""

import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from experiments.asr_candidates import evaluate as evaluator


class RegistryTests(unittest.TestCase):
    def asr_only(self):
        return {"text": "AB", "original_segments": [{"text": "AB"}], "total_chunks": 1,
            "cached_inference": False, "offline_requested": True,
            "effective_parameters": {"candidate_id": "nemotron", "device_map": {"": "cuda:0"}},
            "asr_traces": [{"chunk_index": 0, "token_limit_reached": False, "asr_input_evidence": {
                "parameter_devices": ["cuda:0"], "buffer_devices": ["cuda:0"],
                "input_devices": {"input_features": "cuda:0"}, "output_device": "cuda:0"}}]}

    def test_asr_only_native_cuda_evidence_survives_missing_alignment_export(self):
        for family in ("x0", "cohere", "granite", "nemotron"):
            proof = evaluator.execution_observations(self.asr_only(), family)
            self.assertTrue(proof["asr_gpu_observed"])
            self.assertEqual(proof["asr_gpu_observation_status"], "observed_cuda")
            self.assertTrue(proof["asr_trace_plan_coverage_complete"])
            self.assertFalse(proof["alignment_gpu_observed"])
            self.assertFalse(proof["execution_observations_pass"])
            self.assertEqual(proof["alignment_observation_status"], "not_observed_in_asr_only_artifact")
            self.assertTrue(proof["fresh_asr"])
            self.assertIsNone(proof["fresh_asr_alignment"])

    def test_asr_only_partial_trace_coverage_is_not_cuda_failure(self):
        document = self.asr_only()
        document["total_chunks"] = 2
        proof = evaluator.execution_observations(document, "cohere")
        self.assertTrue(proof["asr_gpu_observed"])
        self.assertFalse(proof["asr_trace_plan_coverage_complete"])
        self.assertEqual(proof["asr_observed_trace_count"], 1)
        self.assertFalse(proof["execution_observations_pass"])

    def test_final_granite_195_windows_preserves_cuda_and_counts_12_failed_caps(self):
        failed_indices = {27, 33, 81, 84, 103, 125, 137, 145, 148, 160, 163, 171}
        trace = self.asr_only()["asr_traces"][0]
        document = self.asr_only()
        document.update(chunks=[{} for _ in range(195)], total_chunks=195,
            effective_parameters={"asr": {"candidate_id": "granite"}, "alignment": {"model": "cuda:0"}},
            asr_traces=[{**copy.deepcopy(trace), "chunk_index": index} for index in range(195) if index not in failed_indices],
            failed_chunks=[{"chunk_index": index, "partial_traces": [{**copy.deepcopy(trace), "chunk_index": index,
                "generated_tokens": 1024, "token_limit_reached": True}]} for index in sorted(failed_indices)],
            alignment_records=[{"model_output_device": "cuda:0", "decoder_input_device": "cuda:0",
                "decoder_output_device": "cuda:0", "normalization": {"actual_input_device": "cuda:0"}},
                {"failure": "CTC source window too short"}])
        proof = evaluator.execution_observations(document, "granite")
        self.assertTrue(proof["asr_gpu_observed"])
        self.assertTrue(proof["alignment_gpu_observed"])
        self.assertEqual(proof["asr_successful_trace_count"], 183)
        self.assertEqual(proof["asr_failed_partial_trace_count"], 12)
        self.assertEqual(proof["asr_successful_cuda_trace_count"], 183)
        self.assertEqual(proof["asr_failed_partial_cuda_trace_count"], 12)
        self.assertEqual(proof["asr_unobserved_chunk_count"], 0)
        self.assertTrue(proof["asr_trace_plan_coverage_complete"])
        self.assertFalse(proof["asr_successful_trace_plan_coverage_complete"])
        self.assertEqual(proof["token_cap_chunk_count"], 12)
        self.assertEqual(proof["failed_partial_trace_token_cap_count"], 12)
        self.assertFalse(proof["token_cap_clear"])
        self.assertFalse(proof["execution_observations_pass"])
        document["failed_chunks"][0]["partial_traces"] = []
        proof = evaluator.execution_observations(document, "granite")
        self.assertTrue(proof["asr_gpu_observed"])
        self.assertFalse(proof["asr_trace_plan_coverage_complete"])
        self.assertEqual(proof["asr_unobserved_chunk_indices"], [27])
        self.assertFalse(proof["execution_observations_pass"])

    def test_asr_only_missing_tensor_evidence_remains_unknown_and_cpu_is_reported(self):
        document = self.asr_only()
        document["asr_traces"][0]["asr_input_evidence"].pop("output_device")
        proof = evaluator.execution_observations(document, "granite")
        self.assertFalse(proof["asr_gpu_observed"])
        self.assertEqual(proof["asr_gpu_observation_status"], "incomplete_evidence")
        document = self.asr_only()
        document["asr_traces"][0]["asr_input_evidence"]["buffer_devices"] = ["cpu"]
        proof = evaluator.execution_observations(document, "nemotron")
        self.assertFalse(proof["asr_gpu_observed"])
        self.assertEqual(proof["asr_gpu_observation_status"], "observed_non_cuda")
        self.assertFalse(proof["asr_buffer_devices_cuda"])

    def test_empty_asr_only_artifact_does_not_assert_alignment_was_observed(self):
        document = self.asr_only()
        document.update(text="", original_segments=[], asr_traces=[], total_chunks=0)
        proof = evaluator.execution_observations(document, "nemotron")
        self.assertFalse(proof["asr_gpu_observed"])
        self.assertEqual(proof["asr_gpu_observation_status"], "no_trace_evidence")
        self.assertFalse(proof["alignment_gpu_observed"])
        self.assertFalse(proof["execution_observations_pass"])
        self.assertIsNone(proof["empty_vad_inference_skipped"])

    def test_candidate_native_gpu_observations_check_buffers_and_use_generic_identity(self):
        document = {"chunks": [{}], "asr_traces": [{"token_limit_reached": False,
            "asr_input_evidence": {"parameter_devices": ["cuda:0"], "buffer_devices": ["cuda:0"],
                                   "input_devices": {"input_features": "cuda:0"}, "output_device": "cuda:0"}}]}
        proof = evaluator.execution_observations(document, "nemotron")
        self.assertTrue(proof["asr_gpu_observed"])
        self.assertEqual(proof["asr_gpu_evidence_kind"], "native_parameter_input_output_tensors")
        document["asr_traces"][0]["asr_input_evidence"]["buffer_devices"] = ["cpu"]
        self.assertFalse(evaluator.execution_observations(document, "nemotron")["asr_gpu_observed"])

    def test_all_requested_candidates_required_and_single_strategy(self):
        routes = [{"id": family, "family": family, "segmentation": "pyannote-current"} for family in evaluator.FAMILIES]
        evaluator.validate_registry({"routes": routes})
        with self.assertRaisesRegex(ValueError, "exactly one"):
            evaluator.validate_registry({"routes": routes[:-1]})
        routes[0]["segmentation"] = "cut-merge"
        with self.assertRaisesRegex(ValueError, "pyannote-current"):
            evaluator.validate_registry({"routes": routes})

    def test_cost_is_unknown_for_missing_or_invalid_stage(self):
        self.assertIsNone(evaluator.cost_summary({})["reconstructed_serial_wall_s"])
        for invalid in (None, True, -1, float("nan"), "1"):
            run = {"processes": {"asr": {"wall_s": 4}, "align": {"wall_s": invalid}}, "segmentation_process_wall_s": 2}
            self.assertIsNone(evaluator.cost_summary(run)["reconstructed_serial_wall_s"])
        self.assertEqual(evaluator.cost_summary({"processes": {"asr": {"wall_s": 4}, "align": {"wall_s": 3}}, "segmentation_process_wall_s": 2})["reconstructed_serial_wall_s"], 9)


@unittest.skipUnless(importlib.util.find_spec("rapidfuzz"), "Existing VAD environment supplies RapidFuzz")
class CandidateEvaluationTests(unittest.TestCase):
    def setUp(self):
        private = evaluator.ROOT / ".local"
        private.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=private)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.clips, bins_by_film = [], {}
        self.result = {"schema_version": 1, "status": "ok", "text": "ABCDZZ", "duration_seconds": 900,
            "original_segments": [{"text": "AB", "start": 10, "end": 20}, {"text": "CD", "start": 310, "end": 320}, {"text": "ZZ", "start": 610, "end": 620}],
            "units": [{"char_start": 0, "char_end": 2, "start": 11, "end": 12, "granularity": "word"},
                      {"char_start": 2, "char_end": 4, "start": 311, "end": 312, "granularity": "word"},
                      {"char_start": 4, "char_end": 6, "start": 611, "end": 612, "granularity": "word"}],
            "cues": [], "failed_chunks": [], "alignment_records": [], "cached_inference": False, "offline_requested": True}
        for film in ("ii", "iii"):
            audio = self.base / (film + ".wav")
            audio.write_bytes(b"synthetic audio identity; no inference")
            bins = [{"id": f"{film}-{index}", "source_start_seconds": index * 300, "source_end_seconds": (index + 1) * 300, "duration_seconds": 300} for index in range(3)]
            reference = {"schema_version": 1, "reference_kind": "srt_display", "spans": [
                {"id": "a", "text": "AB", "start": 11, "end": 12, "bin_id": bins[0]["id"]},
                {"id": "b", "text": "CD", "start": 311, "end": 312, "bin_id": bins[1]["id"]}]}
            path = self.save(film + "-reference.json", reference)
            self.clips.append({"id": film + "-full", "film": film, "duration": 900,
                "audio": str(audio), "audio_sha256": evaluator.core.digest(audio),
                "reference": str(path), "reference_sha256": evaluator.core.digest(path)})
            bins_by_film[film] = bins
        self.plan = self.save("plan.json", {"clips": self.clips, "bins_by_film": bins_by_film})
        self.routes = []
        for family in evaluator.FAMILIES:
            runs = []
            for clip in self.clips:
                path = self.save(family + "-" + clip["id"] + ".json", self.result)
                runs.append({"clip_id": clip["id"], "status": "completed", "run_id": family + "-" + clip["id"],
                    "result_path": str(path), "result_sha256": evaluator.core.digest(path),
                    "processes": {"asr": {"wall_s": 4}, "align": {"wall_s": 3}}, "segmentation_process_wall_s": 2})
            self.routes.append({"id": family, "family": family, "segmentation": "pyannote-current", "runs": runs})

    def save(self, name, document):
        path = self.base / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def build(self, name="out", study_changes=None):
        study = {"schema_version": 1, "study_id": "synthetic-candidates", "terminal": True,
            "corpus_plan_path": str(self.plan), "corpus_plan_sha256": evaluator.core.digest(self.plan),
            "clips": self.clips, "routes": self.routes, "expected_route_ids": [row["id"] for row in self.routes]}
        study.update(study_changes or {})
        path = self.save(name + "-study.json", study)
        with redirect_stdout(io.StringIO()):
            return evaluator.evaluate_study(path, self.base / name)

    def rows(self, report):
        return report["views"]["including_failures"]

    def change_result(self, document, status="partial"):
        run = self.routes[0]["runs"][0]
        path = self.save(Path(run["result_path"]).name, document)
        run.update(status=status, result_sha256=evaluator.core.digest(path))

    def test_ten_full_slots_pool_edits_without_losing_eof_or_timing_denominator(self):
        report = self.build()
        rows = self.rows(report)
        self.assertEqual(len(rows["films"]), 10)
        self.assertEqual(len(rows["pooled"]), 5)
        self.assertEqual(set(report["views"]), {"including_failures"})
        for row in rows["films"]:
            self.assertEqual(row["summary"]["text"]["I"], 2)
            self.assertEqual(row["summary"]["text"]["CER"], .5)
            self.assertEqual(row["summary"]["timing"]["denominator"], 2)
            self.assertEqual(row["summary"]["reference_empty_bins"]["candidate_characters"], 2)
        for row in rows["pooled"]:
            self.assertEqual(row["summary"]["text"]["reference_characters"], 8)
            self.assertEqual(row["summary"]["text"]["I"], 4)
            self.assertEqual(row["summary"]["timing"]["denominator"], 4)
            self.assertEqual(row["reconstructed_serial_wall_s"], 18)
        self.assertNotIn("ABCDZZ", json.dumps(report))
        summary = (self.base / "out/summary.md").read_text(encoding="utf-8")
        self.assertIn("两片加权合并", summary)
        self.assertIn("nemotron", summary)

    def test_blocked_and_missing_remain_visible_and_keep_full_denominator(self):
        self.routes[2]["runs"] = [{"clip_id": "ii-full", "status": "blocked_access", "failure_reason": "unsupported native Windows runtime"}]
        report = self.build()
        rows = [row for row in self.rows(report)["films"] if row["family"] == "cohere"]
        self.assertEqual([row["declared_status"] for row in rows], ["blocked_access", "missing"])
        for row in rows:
            self.assertIsNone(row["summary"]["text"]["D"])
            self.assertIsNone(row["summary"]["text"]["CER"])
            self.assertEqual(row["full_denominator_accounting"]["D"], 4)
            self.assertEqual(row["summary"]["timing"]["denominator"], 2)
            self.assertEqual(row["summary"]["failed_bin_count"], 3)
            self.assertIsNone(row["reconstructed_serial_wall_s"])
        self.assertEqual(self.rows(report)["pooled"][2]["declared_status_counts"], {"blocked_access": 1, "missing": 1})
        self.assertIsNone(self.rows(report)["pooled"][2]["summary"]["text"]["CER"])
        self.assertIn("unsupported native Windows runtime", (self.base / "out/summary.md").read_text(encoding="utf-8"))

    def test_unobserved_film_prevents_pooled_quality_but_keeps_accounting(self):
        self.routes[2]["runs"] = self.routes[2]["runs"][:1]
        report = self.build()
        pooled = self.rows(report)["pooled"][2]
        self.assertEqual(pooled["quality_scope"], "partial_corpus")
        self.assertIsNone(pooled["summary"]["text"]["CER"])
        self.assertEqual(pooled["summary"]["text"]["reference_characters"], 8)
        self.assertEqual(pooled["full_denominator_accounting"]["D"], 4)
        self.assertIn("部分覆盖", (self.base / "out/summary.md").read_text(encoding="utf-8"))

    def test_hashed_stage_failure_preserves_initialization_type_and_reason(self):
        failure_path = self.save("failure.json", {"status": "failed", "stage": "asr",
            "failure_kind": "model_initialization_failed", "message": "native CUDA model load failed",
            "exception": "ModelInitializationError", "worker_wall_s": 2})
        run = self.routes[2]["runs"][0]
        run.pop("result_path")
        run.pop("result_sha256")
        run.update(status="invocation_failed", failure_path=str(failure_path), failure_sha256=evaluator.core.digest(failure_path))
        report = self.build()
        row = self.rows(report)["films"][4]
        self.assertEqual(row["stage_failure_kind"], "model_initialization_failed")
        self.assertEqual(row["reason"], "native CUDA model load failed")
        self.assertIsNone(row["summary"]["text"]["CER"])
        identities = json.loads((self.base / "out/identities.json").read_text())
        self.assertEqual(identities["files"][str(failure_path)], run["failure_sha256"])
        run["failure_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "failure_path SHA256"):
            self.build("tampered-failure")

    def test_pooled_cer_weights_reference_characters_instead_of_averaging_rates(self):
        reference_path = Path(self.clips[1]["reference"])
        reference = json.loads(reference_path.read_text())
        reference["spans"][1]["text"] = "CDXX"
        reference_path.write_text(json.dumps(reference), encoding="utf-8")
        self.clips[1]["reference_sha256"] = evaluator.core.digest(reference_path)
        plan = json.loads(self.plan.read_text())
        plan["clips"] = self.clips
        self.plan.write_text(json.dumps(plan), encoding="utf-8")
        report = self.build()
        films = self.rows(report)["films"][:2]
        pooled = self.rows(report)["pooled"][0]["summary"]["text"]
        self.assertEqual(pooled["reference_characters"], 10)
        self.assertEqual(pooled["S"] + pooled["D"] + pooled["I"], 4)
        self.assertEqual(pooled["CER"], .4)
        self.assertNotEqual(pooled["CER"], sum(row["summary"]["text"]["CER"] for row in films) / 2)

    def test_failed_chunk_partial_text_is_diagnostic_and_success_kept(self):
        document = copy.deepcopy(self.result)
        document["failed_chunks"] = [{"start": 21, "end": 29, "chunk_index": 9,
            "partial_segments": [{"text": "FAILED-PARTIAL", "start": 21, "end": 29}]}]
        self.change_result(document)
        report = self.build()
        row = self.rows(report)["films"][0]
        self.assertEqual(row["summary"]["text"]["candidate_characters"], 6)
        self.assertEqual(row["summary"]["text"]["reference_characters"], 4)
        self.assertEqual(row["summary"]["failed_bin_count"], 1)
        diagnostic = json.loads((self.base / "out/diagnostics.json").read_text())["runs"][0]
        self.assertEqual(diagnostic["partial_failed_asr_raw_characters"], 14)
        self.assertGreater(diagnostic["including_failed_chunk_partial_text_diagnostic"]["candidate_characters"], 6)
        self.assertNotIn("FAILED-PARTIAL", json.dumps(diagnostic))

    def test_missing_alignment_keeps_asr_text_but_no_fake_timing(self):
        document = copy.deepcopy(self.result)
        document["units"] = []
        self.change_result(document, "invocation_failed")
        run = self.routes[0]["runs"][0]
        run["asr_path"], run["asr_sha256"] = run.pop("result_path"), run.pop("result_sha256")
        report = self.build()
        row = self.rows(report)["films"][0]
        self.assertFalse(row["final_result_observed"])
        self.assertEqual(row["summary"]["text"]["candidate_characters"], 6)
        self.assertEqual(row["summary"]["timing"]["denominator"], 2)
        self.assertEqual(row["summary"]["timing"]["measurable_count"], 0)
        self.assertEqual(row["summary"]["failed_bin_count"], 3)

    def test_native_asr_only_run_reports_cuda_and_preserves_missing_alignment(self):
        run = self.routes[2]["runs"][0]
        document = copy.deepcopy(self.result)
        document["units"] = []
        document["total_chunks"] = 1
        document["effective_parameters"] = {"candidate_id": "cohere", "device_map": {"": "cuda:0"}}
        document["asr_traces"] = RegistryTests().asr_only()["asr_traces"]
        path = self.save(Path(run["result_path"]).name, document)
        run.pop("result_path")
        run.pop("result_sha256")
        run.update(asr_path=str(path), asr_sha256=evaluator.core.digest(path), status="invocation_failed")
        report = self.build()
        diagnostic = json.loads((self.base / "out/diagnostics.json").read_text())["runs"][4]
        proof = diagnostic["execution_proof"]
        self.assertTrue(proof["asr_gpu_observed"])
        self.assertFalse(proof["alignment_gpu_observed"])
        self.assertFalse(proof["execution_observations_pass"])
        row = self.rows(report)["films"][4]
        self.assertEqual(row["summary"]["text"]["candidate_characters"], 6)
        self.assertEqual(row["summary"]["timing"]["denominator"], 2)
        self.assertEqual(row["summary"]["timing"]["measurable_count"], 0)

    def test_active_run_and_sampled_corpus_rejected(self):
        self.routes[0]["runs"][0]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "terminal"):
            self.build("active")
        self.routes[0]["runs"][0]["status"] = "completed"
        with self.assertRaisesRegex(ValueError, "exact full corpus"):
            self.build("sample", {"clips": self.clips[:1]})

    def test_hash_integrity_new_output_and_execution_scope(self):
        self.routes[0]["runs"][0]["result_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.build("bad-hash")
        self.routes[0]["runs"][0]["result_sha256"] = evaluator.core.digest(Path(self.routes[0]["runs"][0]["result_path"]))
        report = self.build()
        for row in [*self.rows(report)["films"], *self.rows(report)["pooled"]]:
            self.assertNotIn("all_execution_verified", row["summary"])
        with self.assertRaisesRegex(ValueError, "new private"):
            evaluator.evaluate_study(self.base / "out-study.json", self.base / "out")


if __name__ == "__main__":
    unittest.main()
