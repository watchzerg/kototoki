"""Offline external VAD provenance, identity and accounting contract tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from experiments.w0_demo.run import attach_vad_manifest, read_vad_manifest


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "vad.json"
        self.identity = {"path": "source.wav", "pcm_sha256": "pcm", "file_sha256": "file",
                         "sample_rate": 16000, "channels": 1, "samples": 640000,
                         "duration_s": 40., "representation": "float32 PCM16 / 32768"}
        self.manifest = {"schema_version": 1, "status": "ok", "input": self.identity.copy(),
                         "offset_s": 4.5, "vad_id": "silero", "recipe": "vad-silero-v1",
                         "metadata": {"fresh_inference": True, "device": "cpu"},
                         "stages": {"input_read_s": .1, "vad_load_s": 2., "vad_inference_s": 3.},
                         "chunks": [{"start": .1, "end": 2., "segments": [[.1, .5], [1., 2.]]}]}

    def load(self, manifest=None):
        self.path.write_text(json.dumps(self.manifest if manifest is None else manifest), encoding="utf-8")
        return read_vad_manifest(self.path, self.identity, 4.5)

    def test_complete_identity_allows_a_copy_at_another_path(self):
        self.manifest["input"]["path"] = "copied.wav"
        self.assertEqual(self.load()["chunks"], self.manifest["chunks"])
        for key in ("file_sha256", "pcm_sha256", "samples", "duration_s", "sample_rate", "channels"):
            for change in ("missing", "mismatch"):
                candidate = copy.deepcopy(self.manifest)
                if change == "missing":
                    del candidate["input"][key]
                else:
                    candidate["input"][key] = "wrong"
                with self.subTest(key=key, change=change), self.assertRaises(ValueError):
                    self.load(candidate)

    def test_offset_failure_and_invalid_costs_are_rejected(self):
        for key, value in (("offset_s", 0), ("offset_s", float("nan")), ("status", "failed"),
                           ("schema_version", True), ("vad_id", "../silero"), ("metadata", [])):
            candidate = copy.deepcopy(self.manifest)
            candidate[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.load(candidate)
        for costs in ({}, {"vad_load_s": 1, "vad_inference_s": -1},
                      {"vad_load_s": 1, "vad_inference_s": float("inf")},
                      {"vad_load_s": True, "vad_inference_s": 1}):
            candidate = copy.deepcopy(self.manifest)
            candidate["stages"] = costs
            with self.subTest(costs=costs), self.assertRaises(ValueError):
                self.load(candidate)

    def test_invalid_windows_fail_before_inference(self):
        for chunks in ([{"start": 0, "end": 31, "segments": []}],
                       [{"start": 0, "end": 1e-6, "segments": []}],
                       [{"start": 39, "end": 41, "segments": []}],
                       [{"start": 1, "end": 2, "segments": []},
                        {"start": 1.5, "end": 3, "segments": []}],
                       [{"start": 1, "end": 2, "segments": [[1, 3]]}],
                       [{"start": 1, "end": 2, "segments": [[1, 1.5], [1.4, 2]]}],
                       [{"start": True, "end": 2, "segments": []}]):
            candidate = copy.deepcopy(self.manifest)
            candidate["chunks"] = chunks
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                self.load(candidate)

    def test_exact_sample_bounds_must_be_paired_and_match_seconds(self):
        chunk = {"start": 1001 / 16000, "end": 2002 / 16000,
                 "start_sample": 1001, "end_sample": 2002, "segments": []}
        self.manifest["chunks"] = [chunk]
        self.assertEqual(self.load()["chunks"], [chunk])
        for key, value in (("end_sample", None), ("end_sample", 2001), ("start_sample", True)):
            candidate = copy.deepcopy(self.manifest)
            candidate["chunks"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load(candidate)

    def test_external_stage_costs_do_not_replace_replay_or_asr_costs(self):
        manifest = self.load()
        result = {"recipe": "w0-pyannote-mms-v1", "cached_inference": False,
                  "stages": {"vad_s": .001, "vad_load_s": .002, "asr_inference_s": 4.}}
        before = result["stages"].copy()
        attach_vad_manifest(result, manifest, self.path, "manifest-digest")
        self.assertEqual(result["stages"], before)
        self.assertEqual(result["recipe"], "w0-silero-mms-v1")
        self.assertFalse(result["cached_inference"])
        self.assertFalse(result["precomputed_vad"]["fresh_inference_in_runner"])
        self.assertEqual(result["precomputed_vad"]["stages"], manifest["stages"])
        self.assertEqual(result["precomputed_vad"]["input"], manifest["input"])
        self.assertEqual(result["vad_manifest_source"]["sha256"], "manifest-digest")


if __name__ == "__main__":
    unittest.main()
