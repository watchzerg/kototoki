"""Offline tests for externally planned source crops and no-speech results."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import RECIPES
from .chunks import validate_chunks
from .pipeline import build_result, validate_asr
from .run import orchestrate, parser
from .stages import asr_stage, align_stage
from .storage import ROOT, read_json, sha256, write_json
from .vad import import_vad_plan


class VadTests(unittest.TestCase):
    def setUp(self):
        private = ROOT / ".local/x0-demo"
        private.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=private)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.identity = {"file_sha256": "file", "pcm_sha256": "pcm", "samples": 640001,
                         "channels": 1, "sample_rate": 16000, "duration_s": 640001/16000}
        self.manifest = {"schema_version": 1, "status": "ok", "input": self.identity,
                         "offset_s": 3.25, "vad_id": "test-vad", "recipe": "vad-test-v1",
                         "metadata": {"device": "cpu"}, "stages": {"vad_load_s": 2, "vad_inference_s": 1},
                         "chunks": [{"start": .25, "end": 10.25, "segments": [[.25, 2], [4, 10.25]]},
                                    {"start": 39, "end": 640001/16000, "segments": [[39, 640001/16000]]}]}

    def reference(self, value):
        path = self.root / "manifest.json"
        path.unlink(missing_ok=True)
        write_json(path, value)
        return {"frozen_path": str(path), "sha256": sha256(path), "execution": "precomputed_external_manifest"}

    def plan(self, chunks, metadata, provenance):
        retained = sum(c["end_sample"]-c["start_sample"] for c in chunks)
        return {"recipe": RECIPES["vad"], "segmentation": "vad", "chunks": chunks,
                "input": self.identity, "offset_s": 3.25, "effective_parameters": metadata,
                "vad_id": "test-vad", "vad_provenance": provenance, "source_sha256": {},
                "retained_samples": retained, "removed_samples": self.identity["samples"]-retained,
                "runtime_identity": {}, "stages": {}}

    def test_source_spans_keep_internal_gap_and_odd_tail(self):
        chunks, metadata, provenance = import_vad_plan(self.reference(self.manifest), self.identity, 3.25)
        self.assertEqual((chunks[0]["start_sample"], chunks[0]["end_sample"]), (4000, 164000))
        self.assertEqual(chunks[-1]["end_sample"], 640001)
        self.assertEqual(chunks[0]["vad_window"]["segments"], [[.25, 2], [4, 10.25]])
        self.assertFalse(metadata["retain_all_samples"])
        self.assertEqual(provenance["precomputed_stages"]["vad_load_s"], 2)
        with self.assertRaises(ValueError):
            validate_chunks(chunks, self.identity["samples"])

    def test_manifest_identity_offset_window_errors_and_tampering_rejected(self):
        for change in ("identity", "offset", "overlap", "cap", "member", "subsample"):
            bad = copy.deepcopy(self.manifest)
            if change == "identity":
                bad["input"]["pcm_sha256"] = "other"
            elif change == "offset":
                bad["offset_s"] = 0
            elif change == "overlap":
                bad["chunks"][1]["start"] = 5
            elif change == "cap":
                bad["chunks"][0]["end"] = 31
            elif change == "member":
                bad["chunks"][0]["segments"] = [[.25, 11]]
            else:
                bad["chunks"] = [{"start": .25, "end": .250001, "segments": []}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_vad_plan(self.reference(bad), self.identity, 3.25)
        reference = self.reference(self.manifest)
        Path(reference["frozen_path"]).write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            import_vad_plan(reference, self.identity, 3.25)

    def test_explicit_integer_boundaries_preserve_float_roundtrip_sample(self):
        # 1001 / 16000 * 16000 is smaller than 1001 on this runtime.
        self.manifest["chunks"] = [{"start": 1001/16000, "end": 2002/16000,
            "start_sample": 1001, "end_sample": 2002, "segments": [[1001/16000, 2002/16000]]}]
        chunks, _, _ = import_vad_plan(self.reference(self.manifest), self.identity, 3.25)
        self.assertEqual((chunks[0]["start_sample"], chunks[0]["end_sample"]), (1001, 2002))

    def test_empty_vad_skips_model_load_preserves_cost_provenance_and_source_extent(self):
        self.manifest["chunks"] = []
        chunks, metadata, provenance = import_vad_plan(self.reference(self.manifest), self.identity, 3.25)
        plan = self.plan(chunks, metadata, provenance)
        write_json(self.root / "plan.json", plan)
        with patch("experiments.x0_demo.stages.load_plan", return_value=(plan, [0])), \
                patch("experiments.x0_demo.asr.QwenAsr") as asr, \
                patch("experiments.w0_demo.alignment.MmsAligner") as aligner:
            asr_stage(self.root, {})
            align_stage(self.root, {})
            asr.assert_not_called()
            aligner.assert_not_called()
        result = read_json(self.root / "alignment.json")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["units"], [])
        self.assertEqual(result["removed_samples"], 640001)
        self.assertEqual(result["source_end_seconds"], 3.25+640001/16000)
        self.assertEqual(result["stage_execution"]["asr"], "skipped_no_speech")
        self.assertNotIn("vad_load_s", result["stages"])
        self.assertEqual(result["vad_provenance"]["precomputed_stages"]["vad_load_s"], 2)

    def test_noncontiguous_asr_result_uses_exact_windows_and_retention_accounting(self):
        chunks, metadata, provenance = import_vad_plan(self.reference(self.manifest), self.identity, 3.25)
        plan = self.plan(chunks, metadata, provenance)
        saved = {"text": "あい", "original_segments": [{**c, "text": t} for c, t in zip(chunks, "あい")],
                 "asr_traces": [{"chunk_index": i, "start_sample": c["start_sample"],
                    "end_sample": c["end_sample"], "pcm_float32_sha256": "hash"} for i, c in enumerate(chunks)],
                 "effective_parameters": {}}
        aligned = {"text": "あい", "records": [], "derived_segments": [], "units": [
            {"char_start": i, "char_end": i+1, "status": "text_only", "granularity": "character"}
            for i in range(2)]}
        result = build_result(plan, saved, aligned, {}, {})
        self.assertEqual(result["retained_samples"], 176001)
        self.assertEqual(result["removed_samples"], 464000)
        with self.assertRaises(ValueError):
            validate_asr(saved, chunks, 640001)
        saved["original_segments"][0]["end_sample"] -= 1
        with self.assertRaises(ValueError):
            validate_asr(saved, chunks, 640001, retain_all=False)

    def test_vad_manifest_requires_explicit_opt_in(self):
        for options in (["--segmentation", "vad"], ["--vad-manifest", "plan.json"]):
            args = parser().parse_args(["--audio", "missing.wav", "--out", "irrelevant", *options])
            with self.assertRaisesRegex(ValueError, "supplied together"):
                orchestrate(args)


if __name__ == "__main__":
    unittest.main()
