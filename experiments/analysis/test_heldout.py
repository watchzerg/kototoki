"""Held-out orchestration guards tested with synthetic artifacts only."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from . import build_heldout as heldout
from .build_validation import preserved_failure_status


class HeldoutTests(unittest.TestCase):
    def test_complete_gate_precedes_any_artifact_read(self):
        with self.assertRaisesRegex(ValueError, "parent-confirmed complete"):
            heldout.build(Path("absent"), Path("absent"))

    def test_literal_repetition_is_numeric_description(self):
        result = heldout.repeated_unit_observation("abcdabcdabcd")
        self.assertEqual(result, {"unit_characters": 4, "repetitions": 3, "repeated_characters": 12})
        self.assertNotIn("abcd", json.dumps(result))
        self.assertEqual(heldout.repeated_unit_observation("abc")["repetitions"], 0)

    def test_raw_and_official_lengths_remain_separate(self):
        observations = heldout.qwen_decode_observations({"windows": [{"start_sample": 0, "end_sample": 5,
            "raw_asr": "zzzzzz", "text": "z", "generated_tokens": 9, "token_limit_reached": False}]})
        self.assertEqual(observations[0]["raw_decoded_characters"], 6)
        self.assertEqual(observations[0]["official_parsed_characters"], 1)
        self.assertIn("descriptive_only", observations[0]["classification"])
        self.assertNotIn("zzzzzz", json.dumps(observations))

    def test_missing_corrupt_and_wrong_top_level_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            self.assertEqual(heldout.load_json_artifact(path)[1], "missing")
            path.write_text("{", encoding="utf-8")
            self.assertEqual(heldout.load_json_artifact(path)[1], "corrupt_json_or_encoding")
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(heldout.load_json_artifact(path)[1], "corrupt_top_level_schema")
        self.assertEqual(heldout.normalized_artifact_error({"schema_version": 1, "text": [], "units": []}),
                         "corrupt_normalized_transcript_schema")

    def _preservation_fixture(self, root, group, *, complete=True, input_hash="audio", text="synthetic"):
        stem = "q0" if group == "X0" else "q1asr"
        directory = root / ".local/results" / f"h1-{stem}-ch04-r1"
        directory.mkdir(parents=True)
        saved = {"schema_version": 1, "text": text, "units": [], "cues": []}
        if group == "X0":
            saved.update(input_sha256=input_hash, source_start_seconds=0.0, duration_seconds=1.0,
                windows=[{"text": text, "raw_asr": text, "token_limit_reached": True, "start_sample": 0, "end_sample": 16000,
                    "offset": 0.0, "generated_tokens": 4096, "asr_input_evidence": {"parameter_devices": ["cuda:0"],
                        "input_devices": {"audio": "cuda:0"}, "output_device": "cuda:0"}}])
            if not complete:
                saved["windows"][0].pop("text")
        else:
            saved["manifest"] = {"status": "ok", "route": "crisp-qwen-f16-cli-asr-only", "input": {"sha256": input_hash}}
        (directory / "result.json").write_text(json.dumps(saved), encoding="utf-8")
        (directory / "manifest.json").write_text(json.dumps({"status": "completed" if complete else "failed",
            "returncode": 0 if complete else 1, "reference_unchanged": True, "audio_sha256": input_hash}), encoding="utf-8")

    def test_qwen_export_rejection_preserves_completed_asr_without_bridge_or_dependent_harness(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._preservation_fixture(root, "X0")
            with patch.object(heldout, "ROOT", root):
                saved, proof = heldout.preserve_saved_asr("X0", 4, expected_audio_sha256="audio", expected_offset=0, expected_duration=1)
            self.assertEqual(saved["text"], "synthetic")
            self.assertEqual(saved["units"], [])
            self.assertEqual(preserved_failure_status(saved, complete=False), "alignment_failed")
            self.assertEqual(proof["audio_sha256"], "audio")
            self.assertEqual(len(proof["source_harness_sha256"]), 64)

    def test_crisp_missing_dependent_harness_preserves_empty_complete_asr(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._preservation_fixture(root, "Q1", text="")
            with patch.object(heldout, "ROOT", root):
                saved, _ = heldout.preserve_saved_asr("Q1", 4, expected_audio_sha256="audio", expected_offset=0, expected_duration=1)
            self.assertEqual(saved["text"], "")
            self.assertTrue(saved["saved_asr_complete"])

    def test_failed_or_wrong_input_source_does_not_fabricate_completed_asr(self):
        for complete, input_hash in ((False, "audio"), (True, "another_audio")):
            with self.subTest(complete=complete, input_hash=input_hash), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self._preservation_fixture(root, "X0", complete=complete, input_hash=input_hash)
                with patch.object(heldout, "ROOT", root):
                    saved, _ = heldout.preserve_saved_asr("X0", 4, expected_audio_sha256="audio", expected_offset=0, expected_duration=1)
                self.assertIsNone(saved)

    def test_complete_asr_phase_survives_failed_fa_harness(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._preservation_fixture(root, "X0")
            directory = root / ".local/results/h1-q0-ch04-r1"
            partial = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            partial.update(status="failed", failure_type="AlignerError")
            (directory / "result.json").write_text(json.dumps(partial), encoding="utf-8")
            (directory / "manifest.json").write_text(json.dumps({"status": "failed", "returncode": 1,
                "reference_unchanged": True, "audio_sha256": "audio"}), encoding="utf-8")
            with patch.object(heldout, "ROOT", root):
                saved, _ = heldout.preserve_saved_asr("X0", 4, expected_audio_sha256="audio", expected_offset=0, expected_duration=1)
            self.assertEqual(saved["text"], "synthetic")
            self.assertEqual(preserved_failure_status(saved, complete=False), "alignment_failed")

    def test_sample_partition_and_actual_asr_devices_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._preservation_fixture(root, "X0")
            directory = root / ".local/results/h1-q0-ch04-r1"
            saved = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            harness = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            for change in ({"start_sample": 1}, {"end_sample": 15999}, {"text": "partial"},
                           {"offset": 1}, {"asr_input_evidence": {}}, {"raw_asr": None}, {"generated_tokens": None}):
                altered = {**saved, "windows": [{**saved["windows"][0], **change}]}
                with self.subTest(change=change):
                    self.assertFalse(heldout.qwen_asr_phase_complete(altered, harness,
                        expected_audio_sha256="audio", expected_offset=0, expected_duration=1))

    def test_reference_path_hash_pair_rejects_swapped_frozen_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / "first.json", root / "second.json"
            first.write_text('{"spans":[]}', encoding="utf-8")
            second.write_text('{"spans":[1]}', encoding="utf-8")
            files = [{"path": str(first), "sha256": heldout.digest(first)},
                     {"path": str(second), "sha256": heldout.digest(second)}]
            with patch.object(heldout, "ROOT", root):
                heldout.reference_identity(first, {"reference": str(first)}, files)
                first.write_bytes(second.read_bytes())
                with self.assertRaisesRegex(ValueError, "path and hash"):
                    heldout.reference_identity(first, {"reference": str(first)}, files)
                with self.assertRaisesRegex(ValueError, "path and hash"):
                    heldout.reference_identity(second, {"reference": str(first)}, files)


if __name__ == "__main__":
    unittest.main()
