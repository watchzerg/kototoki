"""Synthetic offline checks for full-film denominator and paired failure removal."""

import copy
import importlib.util
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from kototoki_eval.alignment import align
from experiments.fullfilm_comparison import evaluate as evaluator


@unittest.skipUnless(importlib.util.find_spec("rapidfuzz"), "Existing VAD environment supplies RapidFuzz")
class FullFilmEvaluationTests(unittest.TestCase):
    def setUp(self):
        private = evaluator.ROOT / ".local"
        private.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=private)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.audio = self.base / "audio.wav"
        self.audio.write_bytes(b"synthetic audio identity; no inference")
        self.bins = [{"id": f"film-bin-{i + 1}", "source_start_seconds": i * 300,
                      "source_end_seconds": (i + 1) * 300, "duration_seconds": 300} for i in range(3)]
        self.reference = {"schema_version": 1, "reference_kind": "srt_display", "spans": [
            {"id": "a", "text": "AB", "start": 11, "end": 12, "bin_id": "film-bin-1"},
            {"id": "b", "text": "CD", "start": 311, "end": 312, "bin_id": "film-bin-2"}]}
        self.reference_path = self.save("reference.json", self.reference)
        self.clip = {"id": "film-full", "film": "film", "duration": 900,
            "audio": str(self.audio), "audio_sha256": evaluator.digest(self.audio),
            "reference": str(self.reference_path), "reference_sha256": evaluator.digest(self.reference_path)}
        self.plan = self.save("plan.json", {"clips": [self.clip], "bins_by_film": {"film": self.bins}})
        self.result = {"schema_version": 1, "status": "ok", "text": "ABCDZZ", "duration_seconds": 900,
            "original_segments": [{"text": "AB", "start": 10, "end": 20},
                                  {"text": "CD", "start": 310, "end": 320},
                                  {"text": "ZZ", "start": 610, "end": 620}],
            "units": [{"char_start": 0, "char_end": 2, "start": 11, "end": 12, "granularity": "word"},
                      {"char_start": 2, "char_end": 4, "start": 311, "end": 312, "granularity": "word"},
                      {"char_start": 4, "char_end": 6, "start": 611, "end": 612, "granularity": "word"}],
            "cues": [], "failed_chunks": [], "alignment_records": [],
            "cached_inference": False, "offline_requested": True}
        self.routes = []
        for strategy in ("pyannote-current", "cut-merge"):
            path = self.save(strategy + ".json", self.result)
            self.routes.append({"id": "w0-" + strategy, "family": "w0", "segmentation": strategy,
                "runs": [{"clip_id": "film-full", "status": "completed", "run_id": strategy,
                    "result_path": str(path), "result_sha256": evaluator.digest(path),
                    "processes": {"asr": {"wall_s": 4}, "align": {"wall_s": 3}},
                    "segmentation_process_wall_s": 2}]})

    def save(self, name, document):
        path = self.base / name
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def change_result(self, index, document, status="partial"):
        run = self.routes[index]["runs"][0]
        path = self.save(Path(run["result_path"]).name, document)
        run.update(status=status, result_sha256=evaluator.digest(path))

    def study(self):
        return {"schema_version": 1, "study_id": "synthetic", "terminal": True,
                "corpus_plan_path": str(self.plan), "corpus_plan_sha256": evaluator.digest(self.plan),
                "clips": [self.clip], "expected_route_ids": [row["id"] for row in self.routes],
                "routes": self.routes}

    def build(self, name="out"):
        study = self.save(name + "-study.json", self.study())
        return evaluator.evaluate_study(study, self.base / name)

    def rows(self, report, view="including_failures"):
        return report["views"][view]["films"]

    def test_exact_global_distance_exhaustive_with_unicode(self):
        strings = ["".join(chars) for length in range(4) for chars in itertools.product("a日", repeat=length)]
        for reference in strings:
            for candidate in strings:
                counts = evaluator.edit_counts(reference, candidate)
                self.assertEqual(sum(counts), align(reference, candidate).distance)
                self.assertEqual(len(reference) - counts[1] + counts[2], len(candidate))
        self.assertEqual(evaluator.text_score("ｶﾞ、Ａ", "ガA")["CER"], 0)

    def test_complete_global_reference_and_unreferenced_tail_preserved(self):
        report = self.build()
        for row in self.rows(report):
            summary = row["summary"]
            self.assertEqual(summary["text"]["reference_characters"], 4)
            self.assertEqual(summary["text"]["candidate_characters"], 6)
            self.assertEqual(summary["text"]["I"], 2)
            self.assertEqual(summary["timing"]["denominator"], 2)
            self.assertEqual(summary["timing"]["success"]["0.5"]["success_count"], 2)
            self.assertEqual(summary["reference_empty_bins"]["candidate_characters"], 2)
        self.assertEqual(report["views"]["including_failures"]["pooled"][0]["summary"]["text"]["CER"], .5)

    def test_content_metrics_do_not_report_placeholder_gpu_verification(self):
        report = self.build()
        for view in report["views"].values():
            for row in [*view["films"], *view["pooled"]]:
                summary = row["summary"]
                self.assertNotIn("all_execution_verified", summary)
                self.assertNotIn("execution_unverified_count", summary)
                self.assertNotIn("execution_status_counts", summary)
                self.assertEqual(summary["execution_verification"]["status"], "not_evaluated_by_bin_scorer")
        bins = json.loads((self.base / "out/bin-scores.json").read_text())
        for run in bins["runs"]:
            for record in run["records"]:
                self.assertNotIn("execution_verified", record)
                self.assertNotIn("execution_status", record)

    def test_asr_failure_preserves_other_success_inside_failed_bin(self):
        result = copy.deepcopy(self.result)
        result["failed_chunks"] = [{"chunk_index": 9, "start": 21, "end": 29,
                                    "partial_segments": [{"text": "FAILED-PARTIAL", "start": 21, "end": 29}]}]
        self.change_result(0, result)
        report = self.build()
        self.assertEqual(self.rows(report)[0]["summary"]["text"]["candidate_characters"], 6)
        excluded = self.rows(report, "excluding_paired_failure_union")
        for row in excluded:
            self.assertEqual(row["removed"]["removed_reference_characters"], 2)
            self.assertEqual(row["summary"]["text"]["reference_characters"], 2)
            self.assertEqual(row["summary"]["text"]["candidate_characters"], 4)
            self.assertEqual(row["removed"]["removed_duration_seconds"], 300)
        diagnostics = json.loads((self.base / "out/diagnostics.json").read_text())
        self.assertEqual(diagnostics["runs"][0]["partial_failed_asr_raw_characters"], 14)
        self.assertGreater(diagnostics["runs"][0]["including_failed_chunk_partial_text_diagnostic"]["candidate_characters"], 6)
        self.assertNotIn("FAILED-PARTIAL", json.dumps(report))
        self.assertNotIn("FAILED-PARTIAL", json.dumps(diagnostics))
        self.assertEqual(diagnostics["runs"][0]["reconstructed_serial_wall_s"], 9)

    def test_union_removal_identical_denominators_and_touching_half_open(self):
        first = copy.deepcopy(self.result)
        first["failed_chunks"] = [{"chunk_index": 0, "start": 290, "end": 300}]
        second = copy.deepcopy(self.result)
        second["alignment_records"] = [{"segment_index": 1, "failure": "synthetic"}]
        second["units"][1] = {"char_start": 2, "char_end": 4, "granularity": "word", "status": "text_only"}
        self.change_result(0, first)
        self.change_result(1, second)
        report = self.build()
        full = self.rows(report)
        self.assertEqual(full[0]["summary"]["failed_bin_count"], 1)
        self.assertEqual(full[1]["summary"]["text"]["candidate_characters"], 6)
        self.assertEqual(full[1]["summary"]["timing"]["measurable_count"], 1)
        for row in self.rows(report, "excluding_paired_failure_union"):
            self.assertEqual(row["removed"]["removed_bin_ids"], ["film-bin-1", "film-bin-2"])
            self.assertEqual(row["summary"]["text"]["reference_characters"], 0)
            self.assertEqual(row["summary"]["text"]["I"], 2)
            self.assertIsNone(row["summary"]["text"]["CER"])

    def test_missing_slots_keep_full_reference_and_remove_union_for_both(self):
        self.routes[0]["runs"] = []
        report = self.build()
        row = self.rows(report)[0]
        self.assertEqual(row["summary"]["text"]["D"], 4)
        self.assertEqual(row["summary"]["timing"]["denominator"], 2)
        self.assertEqual(row["summary"]["failed_bin_count"], 3)
        for row in self.rows(report, "excluding_paired_failure_union"):
            self.assertEqual(row["summary"]["bin_count"], 0)
            self.assertEqual(row["removed"]["removed_duration_seconds"], 900)

    def test_missing_alignment_export_retains_independent_asr(self):
        run = self.routes[0]["runs"][0]
        run["asr_path"] = run.pop("result_path")
        run["asr_sha256"] = run.pop("result_sha256")
        run["status"] = "invocation_failed"
        report = self.build()
        self.assertEqual(self.rows(report)[0]["summary"]["text"]["candidate_characters"], 6)
        self.assertEqual(self.rows(report)[0]["summary"]["failed_bin_count"], 3)
        for row in self.rows(report, "excluding_paired_failure_union"):
            self.assertEqual(row["removed"]["removed_reference_characters"], 4)

    def test_midpoint_boundary_assignment_once_independent_of_ctc(self):
        reference = copy.deepcopy(self.reference)
        reference["spans"][0].update(start=299, end=301, bin_id="film-bin-2")
        document = copy.deepcopy(self.result)
        document["original_segments"][0].update(start=299, end=301)
        document["units"][0].update(start=800, end=810)
        assigned = evaluator.partition(reference, document, self.bins)
        self.assertEqual(assigned["bins"]["film-bin-1"]["text"], "")
        self.assertEqual(assigned["bins"]["film-bin-2"]["text"], "ABCD")
        self.assertEqual(assigned["boundary"]["crossing_reference_cue_ids"], ["a"])
        self.assertEqual(assigned["boundary"]["crossing_asr_segment_indices"], [0])
        self.assertEqual(sum(len(row["text"]) for row in assigned["bins"].values()), 6)
        scored = evaluator.score_bins(reference, document, self.bins, {"status": "completed"})
        summary = evaluator.summarize(scored, reference, document, self.bins, set())
        self.assertEqual(summary["timing"]["denominator"], 2)
        self.assertEqual(summary["interior_timing_only"]["denominator"], 1)
        self.assertIn("Candidate chunks crossing boundaries are retained", summary["interior_timing_only"]["scope"])

    def test_main_global_cer_differs_from_bin_local_without_changing_reference(self):
        result = copy.deepcopy(self.result)
        result["original_segments"][0].update(text="CD")
        result["original_segments"][1].update(text="AB")
        result["text"] = "CDABZZ"
        self.change_result(0, result, "completed")
        report = self.build()
        score = self.rows(report)[0]["summary"]
        self.assertEqual(score["text"], evaluator.text_score("ABCD", "CDABZZ"))
        self.assertEqual(score["text"]["reference_characters"], score["bin_local_text"]["reference_characters"])

    def test_whole_unit_crossing_chunk_rejected_without_interpolation(self):
        result = copy.deepcopy(self.result)
        result["units"][0].update(char_end=4)
        with self.assertRaisesRegex(ValueError, "crosses complete ASR"):
            evaluator.partition(self.reference, result, self.bins)

    def test_active_and_incomplete_registry_rejected(self):
        self.routes[0]["runs"][0]["status"] = "running"
        with self.assertRaisesRegex(ValueError, "terminal"):
            self.build()
        self.routes[0]["runs"][0]["status"] = "completed"
        study = self.study()
        study["clips"] = []
        path = self.save("bad-study.json", study)
        with self.assertRaisesRegex(ValueError, "exact full corpus"):
            evaluator.evaluate_study(path, self.base / "bad")

    def test_hash_no_overwrite_and_privacy(self):
        self.routes[0]["runs"][0]["result_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256"):
            self.build("bad")
        self.routes[0]["runs"][0]["result_sha256"] = evaluator.digest(Path(self.routes[0]["runs"][0]["result_path"]))
        report = self.build()
        self.assertNotIn("ABCDZZ", json.dumps(report))
        with self.assertRaisesRegex(ValueError, "new private"):
            evaluator.evaluate_study(self.base / "out-study.json", self.base / "out")


if __name__ == "__main__":
    unittest.main()
