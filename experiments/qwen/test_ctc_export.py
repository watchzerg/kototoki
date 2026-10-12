"""Synthetic offline checks for identity-safe cached ASR export."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import wave
from export_ctc_input import export, ASR_CONFIG_SHA256
from run_qwen import ASR_ID, ASR_REVISION, ASR_SHA256

try:
    import numpy as np
    import soundfile
except ModuleNotFoundError as error:
    if error.name not in {"numpy", "soundfile"}:
        raise
    np = None
    EXPORT_DEPENDENCIES_AVAILABLE = False
else:
    EXPORT_DEPENDENCIES_AVAILABLE = True


@unittest.skipUnless(EXPORT_DEPENDENCIES_AVAILABLE, "Qwen export tests require numpy and soundfile in the isolated Qwen environment.")
class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / "source.wav"
        pcm = np.arange(32000, dtype=np.int16)
        with wave.open(str(self.audio), "wb") as file:
            file.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            file.writeframes(pcm.tobytes())
        f32 = pcm.astype(np.float32) / 32768.0
        evidence = {"parameter_devices": ["cuda:0"], "input_devices": {"input_ids": "cuda:0"},
                    "output_device": "cuda:0"}
        self.source = {"backend": "official-qwen-native-hf", "text": "前後",
                       "models": {"asr": {"id": ASR_ID, "revision": ASR_REVISION}},
                       "checkpoint_file_sha256": {"asr": {"model.safetensors": ASR_SHA256, "config.json": ASR_CONFIG_SHA256}},
                       "source_start_seconds": 10., "config": {"offset": 10.},
                       "input": {"sha256": hashlib.sha256(self.audio.read_bytes()).hexdigest(),
                                 "pcm_sha256": hashlib.sha256(f32.tobytes()).hexdigest(), "samples": len(pcm)},
                       "environment": {"devices": {"asr": evidence}}, "adapter_sha256": "synthetic",
                       "generation_config": {}, "windows": [
                           {"start_sample": start, "end_sample": start + 16000, "offset": 10. + start / 16000,
                            "text": text, "token_limit_reached": False, "asr_input_evidence": evidence,
                            "pcm_sha256": hashlib.sha256(f32[start:start + 16000].tobytes()).hexdigest()}
                           for start, text in [(0, "前"), (16000, "後")]]}
        self.path = self.root / "result.json"

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        self.path.write_text(json.dumps(self.source), encoding="utf-8")

    def test_dual_identity_and_original_windows_preserved(self):
        self.write()
        result = export(self.path, self.audio, 10.)
        self.assertEqual(result["original_segments"], [{"start": 0., "end": 1., "text": "前"},
                                                       {"start": 1., "end": 2., "text": "後"}])
        self.assertTrue(result["input"]["decoded_float32_exactly_equal"])
        self.assertNotEqual(result["input"]["pcm_sha256"], result["input"]["float32_pcm_sha256"])
        self.assertEqual(result["input"]["float32_pcm_sha256"], self.source["input"]["pcm_sha256"])

    def test_generation_cap_source_rejected(self):
        self.source["windows"][0]["token_limit_reached"] = True
        self.write()
        with self.assertRaisesRegex(ValueError, "generation cap"):
            export(self.path, self.audio, 10.)

    def test_completed_asr_only_source_accepted(self):
        self.source["config"]["asr_only"] = True
        self.source["alignment_status"] = "not_requested_asr_only"
        self.source["stage_execution"] = {"asr": "executed", "aligner": "not_requested_asr_only"}
        self.write()
        result = export(self.path, self.audio, 10.)
        self.assertEqual("".join(segment["text"] for segment in result["original_segments"]), self.source["text"])
        self.assertFalse(result["provenance"]["new_asr_inference"])

    def test_cuda_output_evidence_required(self):
        self.source["windows"][0]["asr_input_evidence"]["output_device"] = "cpu"
        self.write()
        with self.assertRaisesRegex(ValueError, "CUDA"):
            export(self.path, self.audio, 10.)

    def test_text_loss_rejected(self):
        self.source["text"] = "前後失"
        self.write()
        with self.assertRaisesRegex(ValueError, "alter"):
            export(self.path, self.audio, 10.)

    def test_audio_identity_change_rejected(self):
        self.source["input"]["sha256"] = "wrong"
        self.write()
        with self.assertRaisesRegex(ValueError, "WAV SHA256"):
            export(self.path, self.audio, 10.)

    def test_offset_change_rejected(self):
        self.write()
        with self.assertRaisesRegex(ValueError, "offset"):
            export(self.path, self.audio, 11.)


if __name__ == "__main__":
    unittest.main()
