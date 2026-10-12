"""Offline tests for CTC-only reuse and complete cached-transcript protection."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.components import align_raw_w0 as align
from experiments.components.run import digest, read, write_new


class AlignRawW0Tests(unittest.TestCase):
    def fixture(self):
        clip = {"audio_sha256": "a" * 64, "pcm_sha256": "b" * 64, "offset": 120}
        segments = [{"text": "日本語", "start": 1, "end": 2, "words": []}]
        result = {"route": "W0", "cached_inference": False, "offset_s": 120,
                  "input": {"file_sha256": clip["audio_sha256"], "pcm_sha256": clip["pcm_sha256"]},
                  "text": "日本語", "original_segments": segments, "native": {"segments": deepcopy(segments)},
                  "devices": {"asr": {"device": "cuda", "compute_type": "float16", "device_index": [0],
                                       "inference_requested": True}},
                  "effective_parameters": {"transcribe": {"language": "ja", "task": "transcribe", "beam_size": 5,
                        "word_timestamps": True, "vad_filter": False, "chunk_length": 30,
                        "condition_on_previous_text": False},
                        "info": {"transcription_options": {"temperatures": [0, 0.2, 0.4, 0.6, 0.8, 1]}}}}
        return result, clip

    def test_complete_cached_asr_is_accepted_without_model_imports(self):
        result, clip = self.fixture()
        align.validate_cached_asr(result, clip)

    def test_incomplete_text_wrong_gpu_or_changed_configuration_is_rejected(self):
        result, clip = self.fixture()
        variants = []
        candidate = deepcopy(result)
        candidate["text"] = "日本"
        variants.append(candidate)
        candidate = deepcopy(result)
        candidate["devices"]["asr"]["device"] = "cpu"
        variants.append(candidate)
        candidate = deepcopy(result)
        candidate["effective_parameters"]["transcribe"]["condition_on_previous_text"] = True
        variants.append(candidate)
        candidate = deepcopy(result)
        candidate["effective_parameters"]["info"]["transcription_options"]["temperatures"] = [0]
        variants.append(candidate)
        candidate = deepcopy(result)
        candidate["experimental_vad"] = {"empty_speech": False}
        variants.append(candidate)
        for candidate in variants:
            with self.assertRaises(ValueError):
                align.validate_cached_asr(candidate, clip)

    def test_ctc_cannot_silently_omit_text_or_change_source_origin(self):
        saved, clip = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "ctc.json"
            task = {"output": str(output), "source_asr": {"path": "original-asr.json"}}
            result = {"route": "W1", "input": saved["input"], "offset_s": 120, "text": saved["text"],
                      "original_segments": saved["original_segments"],
                      "native": {"reused_asr_file": "original-asr.json"}, "effective_parameters": {"asr_reused": True}}
            write_new(output, result)
            with patch.object(align, "validate_ctc_evidence", return_value={}) as evidence:
                align.verify_ctc(task, clip, saved)
                evidence.assert_called_once()
            result["text"] = "日本"
            output.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaises(ValueError):
                align.verify_ctc(task, clip, saved)

    def test_upstream_hashes_prevent_stale_cached_asr_reuse(self):
        result, clip = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent, asr, progress, harness, vad, vad_harness = [root / name for name in
                ("plan.json", "asr.json", "progress.json", "harness.json", "vad.json", "vad-harness.json")]
            for path in (parent, progress, harness, vad, vad_harness):
                write_new(path, {})
            write_new(asr, result)
            upstream = {}
            for path_key, hash_key, path in (("path", "sha256", asr), ("progress_path", "progress_sha256", progress),
                ("harness_path", "harness_sha256", harness), ("vad_manifest", "vad_manifest_sha256", vad),
                ("vad_harness_path", "vad_harness_sha256", vad_harness)):
                upstream[path_key], upstream[hash_key] = str(path), digest(path)
            task, plan = {"source_asr": upstream}, {"source_plan": {"path": str(parent), "sha256": digest(parent)}}
            self.assertEqual(align.verify_upstream(task, clip, plan)["text"], result["text"])
            progress.write_text('{"status":"failed"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                align.verify_upstream(task, clip, plan)

    def test_prepare_refuses_incomplete_cached_source_without_creating_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            source = local / align.SOURCE_NAME / "plan.json"
            clips = [{"id": f"clip-{index}"} for index in range(12)]
            write_new(source, {"clips": clips, "source_sha256": {}, "model_sha256": {},
                               "tasks": [{"id": "not-complete", "clip": clip["id"], "stage": "w0"} for clip in clips]})
            write_new(local / ".local/round2/progress.json", {"tasks": {f"{clip['id']}-w0": {} for clip in clips}})
            with (patch.multiple(align, ROOT=local, LOCAL=local), patch.object(align, "verify_sources"),
                  patch.object(align, "verify_clip"),
                  patch.object(align, "source_asr", side_effect=ValueError("incomplete"))):
                with self.assertRaises(ValueError):
                    align.prepare("ctc-not-ready")
            self.assertFalse((local / "ctc-not-ready").exists())

    def test_failed_ctc_preserves_complete_cached_asr_for_every_slot(self):
        saved, _ = self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            local = root / ".local/components"
            asr = root / "complete-asr.json"
            write_new(asr, saved)
            clips, tasks = [], []
            for index in range(12):
                clip = {"id": f"clip-{index}", "source_srt": "reference.srt", "source_srt_sha256": "a" * 64}
                clips.append(clip)
                tasks.append({"id": f"failed-ctc-{index}", "clip": clip["id"], "stage": "ctc",
                    "audio": "original.wav", "command": ["python", "unchanged-ctc.py"],
                    "output": str(root / ".local/results" / f"failed-ctc-{index}" / "result.json"),
                    "source_asr": {"path": str(asr), "sha256": digest(asr), "cached_asr_complete": True}})
            write_new(local / "failed-ctc/plan.json", {"id": "failed-ctc", "frozen": True,
                       "clips": clips, "tasks": tasks})
            with (patch.multiple(align, ROOT=root, LOCAL=local), patch.object(align, "verify_sources"),
                  patch.object(align, "verify_clip"), patch.object(align, "verify_upstream", return_value=saved),
                  patch.object(align.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as inference,
                  patch("builtins.print")):
                align.run("failed-ctc")
                self.assertEqual(inference.call_count, 12)
            records = [read(path) for path in (local / "failed-ctc/progress").glob("*.json")]
            self.assertEqual(len(records), 12)
            for record in records:
                self.assertEqual(record["evaluation_status"], "alignment_failed")
                self.assertTrue(record["cached_asr_complete"])
                self.assertFalse(record["new_asr_inference"])
                self.assertEqual(record["source_asr"]["sha256"], digest(asr))


if __name__ == "__main__":
    unittest.main()
