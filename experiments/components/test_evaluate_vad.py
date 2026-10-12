"""GPU-free VAD source identity, text preservation and terminal-gate checks."""

import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from experiments.components import evaluate_vad as evaluator
from experiments.components.separate import read_pcm


class VadEvaluationTests(unittest.TestCase):
    def setUp(self):
        private = evaluator.ROOT / ".local"
        private.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="vad-evaluation-test-", dir=private)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.audio = self.base / "audio.wav"
        self.pcm = struct.pack("<320h", *range(-160, 160))
        with wave.open(str(self.audio), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            stream.writeframes(self.pcm)
        _, self.identity = read_pcm(self.audio)
        self.clip = {"id": "clip", "film": "II", "audio": str(self.audio),
            "audio_sha256": self.identity["file_sha256"], "offset": 10, "duration": .02}
        self.vad = {"schema_version": 1, "status": "ok", "component": "pyannote-vad-speech-crops",
            "input": self.identity, "source_origin_s": 10, "source_origin_sample": 160000,
            "empty_speech": False, "device": {"actual": "cuda:0", "forward_evidence":
                {"count": 1, "input_devices": ["cuda:0"], "output_devices": ["cuda:0"]}},
            "config": {"onset": .5, "offset": .363, "chunk_size_s": 30, "binarize_min_duration_on_s": 0,
                "binarize_min_duration_off_s": 0, "native_padding_s": 0, "requested_crop_context_s": .2,
                "concatenated_audio": False, "masking": False},
            "chunks": [{"start_sample": 0, "end_sample_exclusive": 160,
                "source_start_sample": 160000, "source_end_sample_exclusive": 160160, "source_offset_s": 10,
                "audio": {"pcm_sha256": hashlib.sha256(self.pcm[:320]).hexdigest(), "samples": 160,
                    "sample_rate": 16000, "channels": 1, "representation": "PCM16"}}]}
        waveform = evaluator.float32_pcm(self.pcm)
        self.raw = {"schema_version": 1, "backend": "official-qwen-native-hf-vad", "status": "ok", "text": "AB",
            "units": [], "cues": [], "input": {"sha256": self.identity["file_sha256"], "samples": 320,
                "pcm_sha256": hashlib.sha256(waveform).hexdigest()}, "source_start_seconds": 10, "duration_seconds": .02,
            "config": {"language": "ja", "dtype": "bfloat16", "attention": "sdpa", "max_new_tokens": 4096,
                "do_sample": False, "batch_size": 1, "offset": 10, "asr_only": True, "offline": True, "alignment_only": None},
            "cache_reused": False, "models": {"asr": {"id": evaluator.ASR_ID, "revision": evaluator.ASR_REVISION}},
            "checkpoint_file_sha256": {"asr": {"model.safetensors": evaluator.ASR_SHA256, "config.json": evaluator.ASR_CONFIG_SHA256}},
            "experimental_vad": {"file_sha256": "vad", "sample_mapping_exact": True, "concatenated_audio": False,
                "reference_text_used": False, "empty_speech": False}, "stage_execution": {"asr": "executed"},
            "windows": [{"start_sample": 0, "end_sample": 160, "offset": 10, "source_start_sample": 160000,
                "source_end_sample_exclusive": 160160, "text": "AB", "raw_asr": "AB", "token_limit_reached": False,
                "pcm_sha256": hashlib.sha256(waveform[:640]).hexdigest(), "crop_pcm16_sha256": hashlib.sha256(self.pcm[:320]).hexdigest(),
                "asr_input_evidence": {"parameter_devices": ["cuda:0"], "input_devices": {"audio": "cuda:0"}, "output_device": "cuda:0"}}]}

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_stdlib_pcm_float_bytes_match_known_binary_conversion(self):
        pcm = struct.pack("<5h", -32768, -1, 0, 1, 32767)
        expected = struct.pack("<5f", -1, -1 / 32768, 0, 1 / 32768, 32767 / 32768)
        self.assertEqual(evaluator.float32_pcm(pcm), expected)

    def test_exact_source_windows_and_full_text_are_independently_verified(self):
        before = copy.deepcopy(self.raw)
        self.assertTrue(evaluator.verify_qwen(self.raw, self.vad, self.pcm, self.identity, self.clip, "vad"))
        self.assertEqual(before, self.raw)
        for mutation in ("cpu", "cap", "changed_text", "crop_hash", "incomplete"):
            raw = copy.deepcopy(self.raw)
            if mutation == "cpu":
                raw["windows"][0]["asr_input_evidence"]["output_device"] = "cpu"
            elif mutation == "cap":
                raw["windows"][0]["token_limit_reached"] = True
            elif mutation == "changed_text":
                raw["text"] = "AC"
            elif mutation == "crop_hash":
                raw["windows"][0]["pcm_sha256"] = "wrong"
            else:
                raw["windows"] = []
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                evaluator.verify_qwen(raw, self.vad, self.pcm, self.identity, self.clip, "vad")

    def test_empty_vad_keeps_asr_unqualified(self):
        self.vad.update(chunks=[], empty_speech=True)
        self.raw.update(text="", windows=[], stage_execution={"asr": "not_executed_empty_vad"})
        self.raw["experimental_vad"]["empty_speech"] = True
        self.assertFalse(evaluator.verify_qwen(self.raw, self.vad, self.pcm, self.identity, self.clip, "vad"))

    def test_w0_clip_contract_uses_original_feature_coordinates(self):
        contract = evaluator.w0_contract(self.vad, self.identity, 10)
        document = {"schema_version": 1, "text": "AB", "units": [], "cues": [], "input": self.identity,
            "source_start_seconds": 10, "duration_seconds": .02, "original_segments": [{"text": "AB"}],
            "offline_requested": True, "experimental_vad": {"file_sha256": "vad", **contract},
            "effective_parameters": {"transcribe": {"language": "ja", "task": "transcribe", "beam_size": 5,
                "word_timestamps": True, "vad_filter": False, "chunk_length": 30, "condition_on_previous_text": False,
                "clip_timestamps": contract["clip_timestamps"]}},
            "devices": {"asr": {"device": "cuda", "compute_type": "float16"}}}
        self.assertTrue(evaluator.verify_w0(document, self.vad, self.identity, self.clip, "vad"))
        document["effective_parameters"]["transcribe"]["clip_timestamps"] = [0, .02]
        with self.assertRaisesRegex(ValueError, "configuration"):
            evaluator.verify_w0(document, self.vad, self.identity, self.clip, "vad")

    def test_bridge_never_alters_text_or_original_audio_identity(self):
        raw_path = self.base / "raw.json"
        self.save(raw_path, self.raw)
        bridge = {"text": "AB", "original_segments": [{"start": 0, "end": .01, "text": "AB"}], "offset_s": 10,
            "input": {"file_sha256": self.identity["file_sha256"], "pcm_sha256": self.identity["pcm_sha256"],
                "float32_pcm_sha256": self.raw["input"]["pcm_sha256"]},
            "provenance": {"source_result": str(raw_path), "source_result_sha256": evaluator.digest(raw_path),
                "operation": "fresh-qwen-vad-to-whisperx-ctc-bridge-v1", "reference_text_used": False, "source_fa_times_used": False}}
        evaluator.verify_bridge(bridge, self.raw, raw_path, self.identity, self.clip)
        bridge["original_segments"][0]["text"] = "AC"
        with self.assertRaisesRegex(ValueError, "bridge identity"):
            evaluator.verify_bridge(bridge, self.raw, raw_path, self.identity, self.clip)

    def test_missing_progress_blocks_before_scoring_or_manifest_write(self):
        name = "synthetic"
        local = self.base / "components"
        plan_path = local / name / "plan.json"
        self.save(plan_path, {"frozen": True, "id": name, "tasks": [{"id": "pending", "clip": "clip", "stage": "vad"}]})
        destination = self.base / "evaluation.json"
        with patch.object(evaluator, "LOCAL", local), self.assertRaisesRegex(ValueError, "not terminal"):
            evaluator.assemble(name, destination)
        self.assertFalse(destination.exists())

    def test_complete_asr_survives_ctc_failure_without_invented_timestamps(self):
        slot = {"run_id": "failed-ctc", "status": "invocation_failed", "execution_verified": False}
        before = copy.deepcopy(self.raw)
        evaluator.preserve_asr(slot, self.raw, self.clip, self.base / "evaluation.json")
        saved = json.loads(Path(slot["result_path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["text"], "AB")
        self.assertEqual(saved["units"], [])
        self.assertEqual(saved["cues"], [])
        self.assertEqual(saved["source_start_seconds"], 10)
        self.assertEqual(slot["status"], "alignment_failed")
        self.assertEqual(slot["result_sha256"], evaluator.digest(Path(slot["result_path"])))
        self.assertEqual(before, self.raw)


if __name__ == "__main__":
    unittest.main()
