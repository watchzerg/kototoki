"""Synthetic mapping tests; no dependencies, models, GPU, or private fixtures."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("whisper_run", Path(__file__).with_name("run.py"))
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class MappingTests(unittest.TestCase):
    def test_split_merge_preserves_text_and_character_positions(self):
        original = [{"text": "今日は晴れ"}]
        units = [{"text": "今日は", "start": 1, "end": 2, "chars": [
            {"char": "今", "start": 1, "end": 1.2}, {"char": "日", "start": 1.2, "end": 1.4},
            {"char": "は", "start": 1.4, "end": 2}]},
            {"text": "晴れ", "start": 3, "end": 4, "chars": [
                {"char": "晴", "start": 3, "end": 3.5}, {"char": "れ", "start": 3.5, "end": 4}]}]
        split = run.evaluation(original, units, 10, character=True)
        merged = run.evaluation(original, [{"text": "今日は晴れ", "start": 1, "end": 4,
                                           "chars": units[0]["chars"] + units[1]["chars"]}], 10, character=True)
        self.assertEqual(split["text"], merged["text"])
        self.assertEqual(split["units"], merged["units"])
        self.assertEqual(split["units"][0]["start"], 11)

    def test_missing_words_keeps_full_text(self):
        original = [{"text": "弱い声", "start": 0, "end": 3}]
        result = run.evaluation(original, original, 0)
        self.assertEqual(result["text"], "弱い声")
        self.assertEqual(result["units"], [{"char_start": 0, "char_end": 3, "start": None, "end": None,
                                          "granularity": "segment", "time_source": "fallback", "status": "text_only"}])

    def test_repeated_text_maps_monotonically(self):
        source = [{"text": "はいはい"}]
        timed = [{"text": "はい", "start": 0, "end": 1, "words": [{"word": "はい", "start": 0, "end": 1}]},
                 {"text": "はい", "start": 2, "end": 3, "words": [{"word": "はい", "start": 2, "end": 3}]}]
        result = run.evaluation(source, timed, 0)
        self.assertEqual([u["char_start"] for u in result["units"]], [0, 2])

    def test_unmapped_and_missing_timing_remain_text_only(self):
        original = [{"text": "A B"}]
        timed = [{"text": "A B", "start": 1, "end": 2,
                  "chars": [{"char": "A", "start": 1, "end": 1.5}, {"char": "B"}]}]
        result = run.evaluation(original, timed, 0, character=True)
        self.assertEqual(sum(u["char_end"] - u["char_start"] for u in result["units"]), 3)
        self.assertEqual([u["status"] for u in result["units"]], ["ok", "text_only", "text_only"])

    def test_unknown_whitespace_cannot_delete_original(self):
        result = run.evaluation([{"text": " A B"}], [{"text": "AB", "start": 0, "end": 2}], 0)
        self.assertEqual(result["text"], " A B")
        self.assertEqual(result["units"][0]["char_end"], 4)


if __name__ == "__main__":
    unittest.main()
