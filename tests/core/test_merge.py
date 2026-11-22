"""kototoki.merge 的离线测试：中上日下、保留编号与时间、译文换行折叠、覆盖校验。"""

from __future__ import annotations

import unittest

from kototoki.merge import merge
from kototoki.srt import IncompleteTranslationError, parse_srt

JA_SRT = "1\n00:00:01,000 --> 00:00:02,500\nこんにちは\n\n2\n00:00:03,000 --> 00:00:04,000\nさようなら\n"


def _document():
    return parse_srt(JA_SRT)


def _text_lines(srt: str) -> list[list[str]]:
    """每个 cue 块去掉编号与时间行后的文字行。"""
    return [block.split("\n")[2:] for block in srt.strip().split("\n\n")]


class MergeTests(unittest.TestCase):
    def test_zh_on_top_ja_below_and_header_preserved(self):
        document = _document()
        ids = [cue.id for cue in document.cues]
        result = merge(document, {ids[0]: "你好", ids[1]: "再见"})
        self.assertEqual(result, "1\n00:00:01,000 --> 00:00:02,500\n你好\nこんにちは\n\n"
                                 "2\n00:00:03,000 --> 00:00:04,000\n再见\nさようなら\n")

    def test_multiline_translation_joined_with_space(self):
        document = _document()
        ids = [cue.id for cue in document.cues]
        result = merge(document, {ids[0]: "你好\n世界", ids[1]: "再见\r\n世界\r\n朋友"})
        self.assertEqual(_text_lines(result), [["你好 世界", "こんにちは"], ["再见 世界 朋友", "さようなら"]])
        for lines in _text_lines(result):
            self.assertEqual(len(lines), 2)

    def test_untranslated_cue_has_only_the_japanese_line(self):
        document = _document()
        ids = [cue.id for cue in document.cues]
        result = merge(document, {ids[0]: None, ids[1]: "再见"})
        self.assertEqual(result, "1\n00:00:01,000 --> 00:00:02,500\nこんにちは\n\n"
                                 "2\n00:00:03,000 --> 00:00:04,000\n再见\nさようなら\n")
        self.assertEqual(len(parse_srt(result).cues), 2)

    def test_zero_cue_document_gives_empty_string(self):
        self.assertEqual(merge(parse_srt(""), {}), "")


class IncompleteTranslationTests(unittest.TestCase):
    def test_missing_translation_raises(self):
        document = _document()
        with self.assertRaises(IncompleteTranslationError) as caught:
            merge(document, {document.cues[0].id: "你好"})
        self.assertEqual(caught.exception.report["missing_ids"], [document.cues[1].id])


if __name__ == "__main__":
    unittest.main()
