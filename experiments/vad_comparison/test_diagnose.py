"""Synthetic exact-deletion, timing-support and unavailable-pair tests."""

import json
from pathlib import Path
import tempfile
import unittest

from . import diagnose


class DiagnosticTests(unittest.TestCase):
    def reference(self, text="ABCDE"):
        return {"schema_version": 1, "reference_kind": "srt_display",
                "spans": [{"id": "reference", "text": text, "start": 100, "end": 110}]}

    def transcript(self, text="ABCDE"):
        return {"schema_version": 1, "status": "ok", "text": text,
                "source_start_seconds": 100, "duration_seconds": 10,
                "units": [{"char_start": i, "char_end": i + 1, "start": 100 + i,
                           "end": 100.5 + i, "granularity": "character", "status": "ok"}
                          for i in range(len(text))], "cues": [],
                "chunks": [{"start": 0, "end": 10}]}

    def test_exact_new_deletions_bucket_baseline_time_against_candidate_windows(self):
        baseline, candidate = self.transcript(), self.transcript("AE")
        candidate["chunks"] = [{"start": 1.25, "end": 3}]
        baseline["units"][3] = {"char_start": 3, "char_end": 4, "granularity": "character", "status": "text_only"}
        result = diagnose.diagnose_pair(self.reference(), baseline, candidate)
        self.assertEqual(result["reference_characters"], 5)
        self.assertEqual(result["newly_deleted_invariant_characters"], 3)
        self.assertEqual(result["deletion_support_buckets"], {"outside": 0, "crossing_boundary": 1, "inside": 1, "baseline_untimed": 1})
        self.assertEqual(sum(result["reference_character_status_counts"].values()), 5)
        self.assertNotIn("ABCDE", json.dumps(result))

    def test_outside_is_no_positive_overlap_not_boundary_touch(self):
        self.assertEqual(diagnose.support((1, 2), [(2, 3)]), ("outside", False))
        self.assertEqual(diagnose.support((1, 2), [(1, 2)]), ("inside", True))
        self.assertEqual(diagnose.support((1, 2), []), ("outside", False))

    def test_nonzero_source_offset_is_added_to_integer_candidate_windows(self):
        candidate = self.transcript("A")
        candidate["chunks"] = [{"start_sample": 16000, "end_sample": 24000}]
        self.assertEqual(diagnose.source_windows(candidate), [(101, 101.5)])
        self.assertEqual(diagnose.support((101, 101.5), diagnose.source_windows(candidate)), ("inside", True))

    def test_crossing_adjacent_windows_can_retain_every_sample(self):
        self.assertEqual(diagnose.support((1, 3), [(0, 2), (2, 4)]), ("crossing_boundary", True))
        self.assertEqual(diagnose.support((1, 3), [(0, 2), (2.1, 4)]), ("crossing_boundary", False))

    def test_repeated_text_deletion_ambiguity_never_gets_arbitrary_bucket(self):
        result = diagnose.diagnose_pair(self.reference("AA"), self.transcript("AA"), self.transcript("A"))
        self.assertEqual(result["newly_deleted_invariant_characters"], 0)
        self.assertEqual(result["reference_character_status_counts"]["baseline_correct_candidate_matching_ambiguous"], 2)
        result = diagnose.diagnose_pair(self.reference("AA"), self.transcript("A"), self.transcript(""))
        self.assertEqual(result["newly_deleted_invariant_characters"], 0)
        self.assertEqual(result["reference_character_status_counts"]["baseline_matching_ambiguous"], 2)

    def test_coarse_and_interpolated_times_do_not_fake_character_intervals(self):
        for changed in ({"granularity": "word"}, {"time_source": "interpolated"}, {"start": 100.5, "end": 100.5},
                        {"status": "failed"}):
            baseline = self.transcript("A")
            baseline["units"][0].update(changed)
            result = diagnose.diagnose_pair(self.reference("A"), baseline, self.transcript(""))
            self.assertEqual(result["deletion_support_buckets"]["baseline_untimed"], 1)
            if changed.get("start") == changed.get("end") == 100.5:
                self.assertEqual(result["baseline_untimed_reason_counts"], {"zero_duration": 1})

    def test_nfkc_character_expansion_preserves_raw_cluster_and_counts_normalized_chars(self):
        baseline = self.transcript("ﬁ")
        result = diagnose.diagnose_pair(self.reference("fi"), baseline, self.transcript(""))
        self.assertEqual(result["newly_deleted_invariant_characters"], 2)
        self.assertEqual(result["deletion_support_buckets"]["inside"], 2)
        self.assertEqual(result["deleted_character_observations"][1]["baseline_raw_character_span"], [0, 1])

    def test_substitution_is_not_called_new_deletion(self):
        result = diagnose.diagnose_pair(self.reference("AB"), self.transcript("AB"), self.transcript("AX"))
        self.assertEqual(result["newly_deleted_invariant_characters"], 0)
        self.assertEqual(result["reference_character_status_counts"]["baseline_correct_candidate_substituted"], 1)

    def test_build_retains_unavailable_pair_denominator_without_scoring_it(self):
        with tempfile.TemporaryDirectory(prefix="vad-diagnose-test-", dir=diagnose.ROOT / ".local") as folder:
            base = Path(folder).resolve()
            def save(name, value):
                path = base / name
                path.write_text(json.dumps(value), encoding="utf-8")
                return path
            audio = base / "audio.wav"
            audio.write_bytes(b"no inference; synthetic identity")
            reference = save("reference.json", self.reference())
            clip = {"id": "one", "film": "II", "offset": 100, "duration": 10,
                    "audio": str(audio), "audio_sha256": diagnose.digest(audio),
                    "reference": str(reference), "reference_sha256": diagnose.digest(reference)}
            plan = save("plan.json", {"clips": [clip]})
            routes = [{"id": "w0-original", "runs": []}, {"id": "w0-silero", "runs": []}]
            study = save("study.json", {"schema_version": 1, "study_id": "synthetic", "terminal": True,
                "source_plan_path": str(plan), "source_plan_sha256": diagnose.digest(plan), "clips": [clip],
                "expected_route_ids": [route["id"] for route in routes], "routes": routes})
            report = diagnose.build(study, base / "out")
            summary = report["summary_rows"][0]
            self.assertEqual(summary["registry_pair_count"], 1)
            self.assertEqual(summary["unavailable_pair_count"], 1)
            self.assertEqual(summary["full_registry_reference_characters"], 5)
            self.assertEqual(summary["eligible_pair_reference_characters"], 0)
            self.assertEqual(summary["unavailable_pair_reference_characters"], 5)
            self.assertIsNone(report["pairs"][0]["diagnostic"])
            self.assertFalse((base / "scoring").exists())
            # A fresh pair retains exact result/manifest identities and supplies
            # actual-observation-shaped GPU evidence without loading a model.
            manifest = save("vad.json", {"input": {"file_sha256": clip["audio_sha256"]}, "offset_s": 100})
            for route, text in zip(routes, ("ABCDE", "AE")):
                document = self.transcript(text)
                document.update(input_sha256=clip["audio_sha256"], original_segments=[{"text": text}],
                    asr_traces=[{}], cached_inference=False, offline_requested=True,
                    effective_parameters={"asr": {"device": "cuda"}, "alignment": {"model": "cuda:0"}},
                    alignment_records=[{"model_output_device": "cuda:0", "decoder_input_device": "cuda:0",
                        "decoder_output_device": "cuda:0", "normalization": {"actual_input_device": "cuda:0"}}])
                if route["id"] == "w0-silero":
                    document["chunks"] = [{"start": 1.25, "end": 3}]
                    document["vad_manifest_source"] = {"sha256": diagnose.digest(manifest)}
                result_path = save(route["id"] + ".json", document)
                run = {"clip_id": "one", "run_id": route["id"], "status": "completed",
                       "result_path": str(result_path), "result_sha256": diagnose.digest(result_path)}
                if route["id"] == "w0-silero":
                    run.update(vad_manifest_path=str(manifest), vad_manifest_sha256=diagnose.digest(manifest))
                route["runs"] = [run]
            changed_study = json.loads(study.read_text())
            changed_study["routes"] = routes
            save("study.json", changed_study)
            valid = diagnose.build(study, base / "complete-out")
            summary = valid["summary_rows"][0]
            self.assertEqual(summary["eligible_complete_pair_count"], 1)
            self.assertEqual(summary["known_newly_deleted_invariant_characters"], 3)
            self.assertEqual(summary["known_deletion_support_buckets"], {"outside": 1, "crossing_boundary": 1, "inside": 1, "baseline_untimed": 0})
            manifest.write_text("{}")
            with self.assertRaisesRegex(ValueError, "VAD manifest identity"):
                diagnose.build(study, base / "changed-manifest")

    def test_only_verified_complete_pairs_eligible(self):
        run = {"status": "partial"}
        self.assertFalse(diagnose.eligible(run, self.transcript())[0])
        self.assertFalse(diagnose.eligible({"status": "completed"}, self.transcript())[0])
        self.assertEqual(diagnose.eligible(None, None)[1], "missing_run_slot")


if __name__ == "__main__":
    unittest.main()
