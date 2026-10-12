"""Offline character-loss boundaries for the six-route stack comparison."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.components import evaluate_vad_ctc as evaluator
from experiments.components.evaluate_vad_ctc import character_evidence


class VADCTCScorerTests(unittest.TestCase):
    def test_oov_and_untimed_punctuation_remain_distinct_and_text_is_private(self):
        result = {"text": "日A。", "original_segments": [{"text": "日A。"}],
            "units": [{"char_start": 0, "char_end": 1, "start": 10, "end": 11, "status": "ok"},
                      {"char_start": 1, "char_end": 3, "start": None, "end": None, "status": "text_only"}],
            "experimental_alignment": {"records": [{"segment_index": 0, "tokens": [
                {"original_position": 1, "evidence_kind": "wildcard"},
                {"original_position": 2, "evidence_kind": "wildcard"}]}]}}
        before = copy.deepcopy(result)
        facts = character_evidence(result)
        self.assertEqual(facts["wildcard_tokens"], 2)
        self.assertEqual(facts["lexical_wildcard_characters"], 1)
        self.assertEqual(facts["unmapped_lexical_characters"], 1)
        self.assertEqual(facts["untimed_nonlexical_characters"], 1)
        self.assertNotIn("日A", json.dumps(facts, ensure_ascii=False))
        self.assertEqual(result, before)

    def test_invalid_intervals_do_not_make_characters_timed_and_bad_token_mapping_is_rejected(self):
        result = {"text": "AB", "original_segments": [{"text": "AB"}], "units": [
            {"char_start": 0, "char_end": 1, "start": 10, "end": 10, "status": "ok"},
            {"char_start": 1, "char_end": 2, "start": 11, "end": 12, "status": "failed"}]}
        self.assertEqual(character_evidence(result)["unmapped_lexical_characters"], 2)
        result["experimental_alignment"] = {"records": [{"segment_index": 0, "tokens": [
            {"original_position": 2, "evidence_kind": "wildcard"}]}]}
        with self.assertRaisesRegex(ValueError, "wildcard position"):
            character_evidence(result)

    def test_stack_batch_is_terminal_before_any_snapshot_is_written(self):
        with tempfile.TemporaryDirectory(dir=evaluator.ROOT / ".local") as folder:
            base = Path(folder)
            local = base / "components"
            path = local / "synthetic" / "plan.json"
            path.parent.mkdir(parents=True)
            clips = [{"id": f"clip-{index}"} for index in range(12)]
            tasks = [{"id": f"task-{index}", "clip": clip["id"], "stage": "ctc", "bridge": {"path": "bridge"}}
                     for index, clip in enumerate(clips)]
            path.write_text(json.dumps({"id": "synthetic", "frozen": True, "clips": clips, "tasks": tasks}), encoding="utf-8")
            with patch.object(evaluator, "LOCAL", local), self.assertRaisesRegex(ValueError, "not terminal"):
                evaluator.assemble("synthetic", base / "evaluation.json")
            self.assertFalse((base / "evaluation.json").exists())

    def test_time_gain_and_content_cost_remain_visible_without_pareto_dominance(self):
        def route(name, cer, deleted, success):
            return {"route_id": name, "summary": {"text": {"CER": cer, "D": deleted, "I": 4,
                "deletion_rate": deleted / 100, "reference_characters": 100}, "timing": {
                "denominator": 10, "boundary_complete_count": 8, "measurable_coverage": .7,
                "success": {key: {"success_count": success, "lower": success / 10} for key in ("0.5", "2.0", "5.0")}}}}
        scope = {"routes": [route("w0-vad", .1, 5, 5), route("w0-vad-ctc", .2, 10, 7)],
            "comparisons": [{"left": "w0-vad", "right": "w0-vad-ctc", "common_valid_count": 5}]}
        report = {"pooled": scope, "films": {}}
        before = copy.deepcopy(report)
        diagnostic = evaluator.time_priority_diagnostics(report)["scopes"]["pooled"]["against"]["w0-vad"]
        self.assertFalse(diagnostic["candidate_dominates"])
        self.assertEqual(diagnostic["content_change_candidate_minus_baseline"]["D"], 5)
        self.assertEqual(diagnostic["success_count_change_candidate_minus_baseline"]["0.5"], 2)
        self.assertEqual(before, report)


if __name__ == "__main__":
    unittest.main()
