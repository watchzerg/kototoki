"""Offline evidence guards for the development snapshot adapter."""

import unittest

from .build_development import decoding_sanity, gpu_verified


class CrispEvidenceTests(unittest.TestCase):
    def fixture(self):
        return {"manifest": {
            "route": "crisp-cli-asr-explicit-gpu-fa-replay",
            "actual_fa_gpu_verified": True, "process_exit_code": 0,
            "cpu_fallback_allowed": False, "fallback_warnings": [],
            "actual_gpu_markers": ["crispasr_init_gpu_backend: using preferred GPU backend: Vulkan0"],
            "asr_manifest": {"status": "ok", "process_exit_code": 0,
                             "device_evidence": {"gpu_only_contexts_verified": True,
                                                 "asr": "Vulkan0", "fallback_warnings": []}}}}, {
            "status": "completed", "returncode": 0, "reference_unchanged": True}

    def test_saved_asr_and_current_fa_are_both_required(self):
        result, harness = self.fixture()
        self.assertTrue(gpu_verified(result, harness))
        result["manifest"]["asr_manifest"]["device_evidence"]["asr"] = None
        self.assertFalse(gpu_verified(result, harness))

    def test_fa_summary_does_not_replace_actual_marker(self):
        result, harness = self.fixture()
        result["manifest"]["device_evidence"] = {"gpu_only_contexts_verified": True}
        result["manifest"]["actual_gpu_markers"] = []
        self.assertFalse(gpu_verified(result, harness))

    def test_fallback_is_not_qualified(self):
        result, harness = self.fixture()
        result["manifest"]["fallback_warnings"] = ["CPU fallback"]
        self.assertFalse(gpu_verified(result, harness))

    def test_compression_criterion_comes_from_saved_options(self):
        result = {"effective_parameters": {"info": {"transcription_options": {
            "temperatures": [0.0], "compression_ratio_threshold": 2.4}}},
            "original_segments": [{"text": "aaaa!", "compression_ratio": 2.4}]}
        self.assertFalse(decoding_sanity(result)["single_temperature_exhausted_compression_fallback"])
        result["original_segments"][0]["compression_ratio"] = 3.0
        sanity = decoding_sanity(result)
        self.assertTrue(sanity["single_temperature_exhausted_compression_fallback"])
        self.assertEqual(sanity["max_literal_character_repeat"], 4)
        result["effective_parameters"]["info"]["transcription_options"]["temperatures"] = [0.0, 1.0]
        self.assertFalse(decoding_sanity(result)["single_temperature_exhausted_compression_fallback"])
        self.assertEqual(decoding_sanity(result)["compression_threshold_exceeded_segment_count"], 1)


if __name__ == "__main__":
    unittest.main()
