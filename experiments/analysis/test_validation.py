"""Validation preparation remains synthetic and independent of model outputs."""

import unittest
from pathlib import Path

from .build_validation import build, pipeline_complete, preserved_failure_status, qwen_asr_verified, select_validation_lock, values


class ValidationTests(unittest.TestCase):
    def test_no_consumption_before_explicit_start(self):
        with self.assertRaisesRegex(ValueError, "before the parent"):
            build(Path("does-not-exist.json"), Path("does-not-exist-output"))

    def test_partial_asr_does_not_become_complete_alignment_failure(self):
        self.assertEqual(preserved_failure_status({"text": "partial"}, complete=False), "invocation_failed")
        result = {"text": "complete", "input_sha256": "input", "windows": [{"text": "complete"}]}
        self.assertEqual(preserved_failure_status(result, complete=False), "alignment_failed")
        self.assertEqual(preserved_failure_status({"text": "saved", "saved_asr_complete": True}, complete=False), "alignment_failed")

    def test_empty_complete_saved_asr_still_preserved(self):
        self.assertEqual(preserved_failure_status({"text": "", "saved_asr_complete": True}, complete=False), "alignment_failed")

    def test_asr_only_cuda_does_not_require_source_fa(self):
        evidence = {"parameter_devices": ["cuda:0"], "input_devices": {"input": "cuda:0"}, "output_device": "cuda:0"}
        result = {"config": {"offline": True}, "windows": [{"asr_input_evidence": evidence}]}
        harness = {"status": "completed", "returncode": 0, "reference_unchanged": True}
        self.assertTrue(qwen_asr_verified(result, harness))
        evidence["output_device"] = "cpu"
        self.assertFalse(qwen_asr_verified(result, harness))

    def test_pending_scene_prevents_any_role_lock(self):
        report = {"routes": [{"summary": {"missing_run_count": 1}}]}
        self.assertEqual(select_validation_lock(report)["status"], "not_run_pending_all_scheduled_validation_attempts")

    def test_frozen_identity_match_is_exact(self):
        self.assertEqual(values({"nested": ["a", {"identity": "b"}], "count": 151}), {"a", "b"})

    def test_exit_zero_does_not_override_adapter_failure(self):
        harness = {"status": "completed", "returncode": 0, "reference_unchanged": True}
        self.assertFalse(pipeline_complete({"schema_version": 1, "manifest": {"status": "failed"}}, harness))
        self.assertFalse(pipeline_complete({"schema_version": 1, "status": "failed", "saved_asr_complete": True}, harness))
        self.assertTrue(pipeline_complete({"schema_version": 1, "text": "", "units": [], "cues": []}, harness))


if __name__ == "__main__":
    unittest.main()
