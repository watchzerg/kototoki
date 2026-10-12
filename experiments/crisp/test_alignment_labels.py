"""Offline boundary checks; no native DLL, GPU, inference or reference data."""

import unittest

from alignment_labels import has_alignment_labels, is_alignment_punctuation


class AlignmentLabelTests(unittest.TestCase):
    def test_empty_and_native_separators_have_no_labels(self):
        for text in ('', ' ', '\t\r\n '):
            self.assertFalse(has_alignment_labels(text))

    def test_ascii_cjk_and_general_punctuation_have_no_labels(self):
        for text in ('!?.,', '\u3002\u300c\u300d', '\u2026', '\ufe10', '\ufe30'):
            self.assertFalse(has_alignment_labels(text))

    def test_native_keeps_apostrophe_emoji_and_punctuation_outside_blocks(self):
        for text in ("'", '\U0001f600', '\u05be'):
            self.assertTrue(has_alignment_labels(text))

    def test_native_fullwidth_filter_includes_letters_and_digits(self):
        for text in ('\uff21', '\uff10', '\uff65'):
            self.assertFalse(has_alignment_labels(text))
        self.assertTrue(has_alignment_labels('\uff66'))

    def test_lexical_content_still_requires_nonempty_words(self):
        for text in ('\u65e5\u672c', '\u65e5\u3002', 'abc!?', '42'):
            self.assertTrue(has_alignment_labels(text))
            self.assertTrue(has_alignment_labels(text) and not [])
        self.assertFalse(has_alignment_labels('\u2026') and not [])

    def test_native_nonseparator_whitespace_is_not_silently_generalized(self):
        for text in ('\v', '\f', '\u00a0'):
            self.assertTrue(has_alignment_labels(text))

    def test_all_filter_range_boundaries_match_frozen_source(self):
        for first, last in ((0x2000, 0x206F), (0x3000, 0x303F), (0xFE10, 0xFE1F), (0xFE30, 0xFE4F), (0xFF00, 0xFF65)):
            self.assertTrue(is_alignment_punctuation(first))
            self.assertTrue(is_alignment_punctuation(last))
            self.assertFalse(is_alignment_punctuation(first - 1))
            self.assertFalse(is_alignment_punctuation(last + 1))


if __name__ == '__main__':
    unittest.main()
