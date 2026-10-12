"""Offline provenance and failure-accounting tests; no model or GPU imports."""
from __future__ import annotations

import unittest

from experiments.japanese_ctc.phonetic import convert_to_hiragana, map_reading_spans


def timed(text: str) -> list[dict]:
    return [{"char_start": i, "char_end": i + 1, "start": i * 0.1,
             "end": (i + 1) * 0.1, "score": 0.9, "lexical_interval_accepted": True}
            for i in range(len(text))]


class ReadingTests(unittest.TestCase):
    def test_native_recipe_preserves_original_offsets(self):
        def reader(value):
            self.assertEqual(value, "東京へ")
            return [{"orig": "東京", "hira": "とうきょう"}, {"orig": "へ", "hira": "へ"}]
        target = convert_to_hiragana(" 東京、へ。 ", reader)
        self.assertEqual(target.original_text, " 東京、へ。 ")
        self.assertEqual(target.target_text, "とうきょうへ")
        self.assertEqual([(r.original_start, r.original_end, r.target_start, r.target_end)
                          for r in target.ranges], [(1, 3, 0, 5), (4, 5, 5, 6)])

    def test_kanji_word_does_not_fabricate_character_times(self):
        target = convert_to_hiragana("東京", lambda _: [{"orig": "東京", "hira": "とうきょう"}])
        result = map_reading_spans(target, timed(target.target_text))
        self.assertTrue(all(c["start"] is None and c["end"] is None for c in result["chars"]))
        self.assertEqual(result["words"][0]["char_start"], 0)
        self.assertEqual(result["words"][0]["char_end"], 2)
        self.assertEqual(result["words"][0]["start"], 0)
        self.assertEqual(result["words"][0]["end"], 0.5)
        self.assertEqual(result["words"][0]["status"], "ok")

    def test_single_kanji_character_can_aggregate_reading(self):
        target = convert_to_hiragana("猫", lambda _: [{"orig": "猫", "hira": "ねこ"}])
        result = map_reading_spans(target, timed(target.target_text))
        self.assertEqual(result["chars"][0]["start"], 0)
        self.assertEqual(result["chars"][0]["end"], 0.2)
        self.assertEqual(result["words"], [])

    def test_direct_kana_identity_retains_real_character_times(self):
        target = convert_to_hiragana("シンジ", lambda _: [{"orig": "シンジ", "hira": "しんじ"}])
        result = map_reading_spans(target, timed(target.target_text))
        self.assertEqual(len(target.ranges), 3)
        self.assertEqual(result["chars"][1]["start"], 0.1)
        self.assertEqual(result["chars"][1]["end"], 0.2)

    def test_reading_failure_and_oov_leave_original_text_intact(self):
        target = convert_to_hiragana("東京", lambda _: [{"orig": "東京", "hira": "とうきょう"}])
        spans = timed(target.target_text)
        spans[2]["lexical_interval_accepted"] = False
        result = map_reading_spans(target, spans)
        self.assertEqual(result["text"], "東京")
        self.assertEqual(result["reading_mapping"][0]["status"], "unaligned")
        self.assertEqual(result["words"][0]["status"], "text_only")
        self.assertIsNone(result["words"][0]["start"])

    def test_missing_target_token_prevents_timing(self):
        target = convert_to_hiragana("猫", lambda _: [{"orig": "猫", "hira": "ねこ"}])
        result = map_reading_spans(target, timed(target.target_text)[:1])
        self.assertIsNone(result["chars"][0]["start"])

    def test_invalid_and_nonmonotonic_times_prevent_timing(self):
        target = convert_to_hiragana("猫", lambda _: [{"orig": "猫", "hira": "ねこ"}])
        for value in (float("nan"), -1, True, 0.05):
            with self.subTest(value=value):
                spans = timed(target.target_text)
                spans[1]["start"] = value
                self.assertIsNone(map_reading_spans(target, spans)["chars"][0]["start"])

    def test_crossing_original_range_does_not_guess_split(self):
        target = convert_to_hiragana("ねこ", lambda _: [{"orig": "ねこ", "hira": "ねこ"}])
        token = [{"char_start": 0, "char_end": 2, "start": 0, "end": 0.2,
                  "lexical_interval_accepted": True}]
        result = map_reading_spans(target, token)
        self.assertTrue(all(c["start"] is None for c in result["chars"]))

    def test_empty_reading_for_lexical_source_is_failure(self):
        target = convert_to_hiragana("猫", lambda _: [{"orig": "猫", "hira": ""}])
        self.assertEqual(map_reading_spans(target, [])["reading_mapping"][0]["status"], "unaligned")

    def test_numeric_and_english_are_not_given_invented_pronunciations(self):
        target = convert_to_hiragana("3ABC", lambda text: [{"orig": text, "hira": text}])
        self.assertEqual(target.target_text, "3ABC")
        self.assertEqual(len(target.ranges), 4)

    def test_omitted_and_reordered_reader_input_rejected(self):
        for chunks in ([{"orig": "京", "hira": "きょう"}], [{"orig": "東", "hira": "とう"}]):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                convert_to_hiragana("東京", lambda _: chunks)

    def test_empty_source_needs_no_converter(self):
        target = convert_to_hiragana(" 、。 ", lambda _: self.fail("Converter should not be needed"))
        self.assertEqual(target.target_text, "")
        self.assertEqual(target.ranges, ())


if __name__ == "__main__":
    unittest.main()
