"""Synthetic round-two scoring and failed-source preservation checks."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kototoki_eval import evaluate
from .aggregate import aggregate_manifest
from . import build_round2 as round2


class Round2Tests(unittest.TestCase):
    def reference(self):
        return {"schema_version": 1, "reference_kind": "srt_display", "corpus_revision": "synthetic",
                "spans": [{"id": "edge", "text": "AB", "start": 9, "end": 11},
                          {"id": "inside", "text": "CD", "start": 12, "end": 13}]}

    def transcript(self):
        return {"schema_version": 1, "text": "ABCD", "units": [
            {"char_start": 0, "char_end": 2, "start": 9, "end": 11, "granularity": "word"},
            {"char_start": 2, "char_end": 4, "start": 12, "end": 13, "granularity": "word"}], "cues": []}

    def test_gate_precedes_reads(self):
        with self.assertRaisesRegex(ValueError, "parent-confirmed"):
            round2.build(Path("absent"), Path("absent"), Path("absent"), Path("absent"))

    def source_fixture(self, root, name, content):
        current = root / name
        snapshot = root / ".local/round2/source" / name
        current.parent.mkdir(parents=True, exist_ok=True)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        current.write_text(content, encoding="utf-8")
        snapshot.write_text(content, encoding="utf-8")
        return current, snapshot, {"source_sha256": {name: round2.digest(snapshot)}}

    def test_updated_working_prose_uses_immutable_frozen_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            current, snapshot, plan = self.source_fixture(root, "docs/policy.md", "status pending")
            current.write_text("status completed", encoding="utf-8")
            with patch.object(round2, "ROOT", root):
                checks = round2.verify_frozen_sources(plan)
            self.assertEqual(checks[0]["status"], "current_document_updated")
            self.assertEqual(checks[0]["snapshot_sha256"], plan["source_sha256"]["docs/policy.md"])
            self.assertEqual(checks[0]["current_sha256"], round2.digest(current))
            self.assertNotEqual(checks[0]["current_sha256"], checks[0]["snapshot_sha256"])

    def test_frozen_policy_snapshot_tampering_always_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            _, snapshot, plan = self.source_fixture(root, "docs/policy.md", "status pending")
            snapshot.write_text("different policy", encoding="utf-8")
            with patch.object(round2, "ROOT", root), self.assertRaisesRegex(ValueError, "snapshot identity"):
                round2.verify_frozen_sources(plan)

    def test_executable_and_config_current_mutation_rejects(self):
        for name in ("code.py", "uv.lock"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                current, _, plan = self.source_fixture(root, name, "frozen")
                current.write_text("changed", encoding="utf-8")
                with patch.object(round2, "ROOT", root), self.assertRaisesRegex(ValueError, "executable/configuration"):
                    round2.verify_frozen_sources(plan)

    def test_original_media_final_identity_is_not_only_input_crop_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.flac"
            source.write_bytes(b"original audio")
            plan = {"source_asset_sha256": {str(source): round2.digest(source)}}
            self.assertEqual(round2.verify_source_assets(plan)[0]["status"], "matches_frozen_original")
            source.write_bytes(b"modified audio")
            with self.assertRaisesRegex(ValueError, "original source asset"):
                round2.verify_source_assets(plan)

    def test_edge_correct_prediction_cannot_be_certain_success(self):
        score = evaluate(self.reference(), self.transcript())
        original = copy.deepcopy(score)
        changed = round2.uncertain_edge_score(score, {"edge"})
        self.assertEqual(changed["text"], score["text"])
        self.assertEqual(changed["spans"][0]["status"], "matching_ambiguity")
        self.assertEqual(changed["spans"][0]["unresolved_possible_thresholds"], [.5, 2.0, 5.0])
        self.assertNotIn("error", changed["spans"][0])
        self.assertEqual(score, original)

    def test_edge_sensitivity_accounts_for_unknown_shorter_denominator(self):
        result = round2.edge_sensitivity({"reference_characters": 100, "S": 2, "D": 3, "I": 5}, 4)
        self.assertEqual(result["edit_distance_lower"], 6)
        self.assertEqual(result["edit_distance_upper"], 14)
        self.assertAlmostEqual(result["conditional_CER_lower"], .06)
        self.assertAlmostEqual(result["conditional_CER_upper"], 14 / 96)
        self.assertIsNone(round2.edge_sensitivity({"reference_characters": 2, "S": 0, "D": 0, "I": 0}, 2)["conditional_CER_upper"])

    def test_fixed_source_coordinates_detect_crossing_not_candidate_times(self):
        clip = {"offset": 10, "duration": 10}
        self.assertEqual(round2.edge_ids(clip, self.reference()), {"edge"})

    def test_failure_preserves_independent_asr_and_denominator(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            source = {"schema_version": 1, "text": "ABCD", "units": [], "cues": []}
            progress = {"s-x0": {"id": "x0", "status": "blocked"}, "s-q0": {"id": "q0", "status": "failed"}}
            clip = {"id": "s", "offset": 10, "duration": 10, "audio_sha256": "a"}
            harness = {"status": "failed", "audio_sha256": "a", "reference_unchanged": True}
            with patch.object(round2, "artifact", side_effect=[(None, None, []), (source, harness, [])]), \
                    patch.object(round2, "complete_asr", return_value=True), patch.object(round2, "input_identity"), \
                    patch.object(round2, "qwen_decode_observations", return_value=[]):
                record, facts = round2.derive_run("x0", clip, progress, self.reference(), output)
            self.assertEqual(record["status"], "alignment_failed")
            self.assertTrue(facts["upstream_complete_text_retained"])
            score = json.loads(Path(record["evaluation_path"]).read_text(encoding="utf-8"))
            self.assertEqual(score["text"]["D"], 0)
            self.assertEqual(score["text"]["candidate_characters"], 4)
            self.assertEqual(len(score["spans"]), 2)
            self.assertNotIn("ABCD", json.dumps(facts))

    def test_incomplete_source_never_becomes_alignment_failure(self):
        clip = {"id": "s", "offset": 10, "duration": 10, "audio_sha256": "a"}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(round2, "artifact", return_value=(None, None, [])), \
                patch.object(round2, "complete_asr", return_value=False):
            record, _ = round2.derive_run("q1", clip, {}, self.reference(), Path(folder))
            self.assertEqual(record["status"], "missing")

    def test_source_mapping_and_audio_must_match(self):
        clip = {"offset": 10, "duration": 10, "audio_sha256": "audio"}
        harness = {"audio_sha256": "audio", "reference_unchanged": True}
        result = {"input": {"file_sha256": "audio", "duration_s": 10}, "source_start_seconds": 10}
        round2.input_identity(result, harness, clip)
        result["source_start_seconds"] = 0
        with self.assertRaisesRegex(ValueError, "offset"):
            round2.input_identity(result, harness, clip)

    def test_grouped_reports_keep_edges_and_disable_small_film_bootstrap(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            reference = self.reference()
            round2.write(base / "reference.json", reference)
            score = round2.uncertain_edge_score(evaluate(reference, self.transcript()), {"edge"})
            round2.write(base / "score.json", score)
            clips = [{"id": f"{film}-{index}", "film": film, "offset": 10, "duration": 10} for film in ("II", "III") for index in range(6)]
            manifest = {"schema_version": 1, "frozen": True, "manifest_id": "synthetic", "reference_kind": "srt_display",
                "scenes": [{"id": clip["id"], "reference_path": str(base / "reference.json"), "reference_sha256": round2.digest(base / "reference.json")} for clip in clips],
                "routes": [{"id": name, "configuration_id": name, "runs": [
                    {"scene_id": clip["id"], "run_id": clip["id"], "status": "completed", "execution_verified": True,
                     "evaluation_path": str(base / "score.json"), "evaluation_sha256": round2.digest(base / "score.json")}
                    for clip in clips]} for name in ("left", "right")]}
            report = round2.aggregate_groups(manifest, clips, {clip["id"]: reference for clip in clips}, base=base)
            summary = report["pooled"]["routes"][0]["summary"]["timing"]
            self.assertEqual(summary["denominator"], 24)
            self.assertEqual(summary["success"]["0.5"]["success_count"], 12)
            self.assertEqual(summary["success"]["0.5"]["unresolved_count"], 12)
            self.assertEqual(report["pooled"]["routes"][0]["interior_timing_only"]["denominator"], 12)
            self.assertEqual(report["pooled"]["comparisons"][0]["paired_scene_bootstrap"]["scene_count"], 12)
            for film in report["films"].values():
                self.assertEqual(film["comparisons"][0]["paired_scene_bootstrap"]["status"], "not_run")
            self.assertNotIn('"ABCD"', json.dumps(report))


if __name__ == "__main__":
    unittest.main()
