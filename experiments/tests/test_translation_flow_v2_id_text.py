"""Strict exact-ID nonJSON protocol with two explicitly permitted layouts."""

import unittest

from experiments.translation_flow import v2_id_text


class IDTextProtocolTests(unittest.TestCase):
    def test_inline_and_marker_only_layouts_are_explicitly_permitted(self) -> None:
        self.assertEqual(v2_id_text.parse_id_text('[[a]]甲\n[[b]]乙', ['a', 'b']), {'a': '甲', 'b': '乙'})
        self.assertEqual(v2_id_text.parse_id_text('[[a]]\n甲\n[[b]]\n乙', ['a', 'b']), {'a': '甲', 'b': '乙'})

    def test_mixed_layout_retains_genuine_subtitle_newlines(self) -> None:
        raw = '\n[[a]]第一行\n第二行\n[[b]] \t\n第三行\n第四行\n'
        self.assertEqual(v2_id_text.parse_id_text(raw, ['a', 'b']),
                         {'a': '第一行\n第二行', 'b': '第三行\n第四行'})

    def test_newline_normalization_retains_body_text_and_spaces(self) -> None:
        self.assertEqual(v2_id_text.parse_id_text('[[a]] 甲 \r\n乙\r[[b]]\r\n丙', ['a', 'b']),
                         {'a': ' 甲 \n乙', 'b': '丙'})

    def test_original_marker_only_protocol_boundary_newlines_remain_valid(self) -> None:
        raw = '[[a]]\n\n甲\n\n[[b]]\n乙\n'
        self.assertEqual(v2_id_text.parse_id_text(raw, ['a', 'b']), {'a': '甲', 'b': '乙'})

    def test_missing_extra_unknown_duplicate_and_wrong_order_are_rejected(self) -> None:
        for raw in ('[[a]]甲', '[[a]]甲\n[[b]]乙\n[[extra]]丙', '[[unknown]]甲\n[[b]]乙',
                    '[[a]]甲\n[[a]]乙\n[[b]]丙', '[[b]]乙\n[[a]]甲'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v2_id_text.parse_id_text(raw, ['a', 'b'])

    def test_nonempty_preamble_code_fences_and_malformed_markers_are_rejected(self) -> None:
        for raw in ('译文如下：\n[[a]]甲', '```\n[[a]]甲\n```', '[[a]]甲\n~~~', '[[a ]]甲', ' [[a]]甲',
                    '[[a]]甲[[extra]]乙', '[[a]]甲\n正文[[extra]]乙', '[[a]]甲\n[[wrong id]]乙'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v2_id_text.parse_id_text(raw, ['a'])

    def test_empty_cues_and_blank_internal_lines_are_rejected(self) -> None:
        for raw in ('[[a]]', '[[a]]\n[[b]]乙', '[[a]]甲\n\n乙\n[[b]]丙', '[[a]]甲\n \n[[b]]乙'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v2_id_text.parse_id_text(raw, ['a', 'b'])

    def test_safe_ids_are_exact_literals_without_fuzzy_repair(self) -> None:
        expected = 'F2-W01_E001-J00241'
        for actual in ('F2-W01_E001-J241', 'f2-W01_E001-J00241', 'F2-W01_E001-J00242'):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                v2_id_text.parse_id_text(f'[[{actual}]]甲', [expected])

    def test_invalid_expected_id_sets_are_rejected(self) -> None:
        for ids in ([], ['a', 'a'], ['wrong id'], [1]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                v2_id_text.parse_id_text('[[a]]甲', ids)

    def test_prompt_versions_the_new_layout_without_reference_fields(self) -> None:
        window = {'id': 'batch', 'source_language': 'ja', 'target_language': 'zh-Hans',
                  'context': [{'id': 'a', 'text': '行く。'}, {'id': 'b', 'text': '待つ。'}],
                  'translate_ids': ['a', 'b']}
        prompt = v2_id_text.render_prompt(window)
        self.assertIn('同一行', prompt)
        self.assertIn('下一行', prompt)
        self.assertIn('不输出只读上下文', prompt)
        self.assertNotIn('reference', prompt)
        self.assertEqual(v2_id_text.VERSION, 'id-text-exact-markers-flex-v1')


if __name__ == '__main__':
    unittest.main()
