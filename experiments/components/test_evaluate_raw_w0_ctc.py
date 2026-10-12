"""Offline boundaries for terminal raw W0 CTC assembly."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.components import evaluate_raw_w0_ctc as evaluator


class RawW0CTCScoringTests(unittest.TestCase):
    def test_failed_alignment_preserves_exact_full_text_without_invented_timing(self):
        saved = {"text": "未変更 AB", "units": [{"start": 1, "end": 2}], "original_segments": []}
        before = copy.deepcopy(saved)
        with tempfile.TemporaryDirectory(dir=evaluator.ROOT / ".local") as folder:
            slot = {"run_id": "failed", "status": "completed", "execution_verified": True}
            evaluator.preserve_slot(slot, saved, {"audio_sha256": "a" * 64, "offset": 10, "duration": 20},
                                    Path(folder) / "evaluation.json")
            document = json.loads(Path(slot["result_path"]).read_text(encoding="utf-8"))
            self.assertEqual(document["text"], saved["text"])
            self.assertEqual(document["units"], [])
            self.assertEqual(document["cues"], [])
            self.assertEqual(document["source_start_seconds"], 10)
            self.assertEqual(slot["status"], "alignment_failed")
            self.assertFalse(slot["execution_verified"])
        self.assertEqual(saved, before)

    def test_partial_decoder_diagnostics_do_not_mutate_or_disclose_transcript(self):
        result = {"text": "PRIVATE", "units": [{"status": "ok"}, {"status": "text_only"}],
            "devices": {"aligner": {"model": "cuda:0", "forward_observation": ["cuda:0", "cuda:0"]}},
            "experimental_alignment": {"records": [
                {"segment_index": 0, "decoder_input_device": "cuda:0", "decoder_output_device": "cuda:0"},
                {"segment_index": 1, "failure": "targets length is too long"}]},
            "experimental_preprocessing": {"records": [{"actual_input_device": "cuda:0"}]}}
        before = copy.deepcopy(result)
        facts = evaluator.phase_diagnostics(result)
        self.assertEqual(facts["decoder_failure_count"], 1)
        self.assertEqual(facts["retained_unit_count"], 2)
        self.assertEqual(facts["unit_status_counts"], {"ok": 1, "failed": 0, "text_only": 1})
        self.assertTrue(facts["all_successful_decoder_devices_cuda"])
        self.assertNotIn("PRIVATE", json.dumps(facts))
        self.assertEqual(before, result)

    def test_missing_progress_refuses_partial_scoring_before_writes(self):
        with tempfile.TemporaryDirectory(dir=evaluator.ROOT / ".local") as folder:
            base = Path(folder)
            local = base / "components"
            plan = local / "synthetic" / "plan.json"
            plan.parent.mkdir(parents=True)
            plan.write_text(json.dumps({"id": "synthetic", "frozen": True,
                "clips": [{"id": "clip"}], "tasks": [{"id": "ctc", "clip": "clip", "stage": "ctc"}]}), encoding="utf-8")
            with patch.object(evaluator, "LOCAL", local), self.assertRaisesRegex(ValueError, "not terminal"):
                evaluator.assemble("synthetic", base / "evaluation.json")
            self.assertFalse((base / "evaluation.json").exists())
            self.assertFalse((base / "preserved-asr").exists())


if __name__ == "__main__":
    unittest.main()
