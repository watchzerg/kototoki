"""Offline source/coverage/export tests; no model or reference data is read."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from experiments.translation_demo.adapters import validate_window
from experiments.translation_flow.srt import (
    IncompleteTranslationError, diagnostics, parse_srt, plan_batches, read_srt,
    render_srt, source_provenance, validate_translations, write_srt,
)


def sample(count: int = 12) -> str:
    return "\n\n".join(
        f"{i + 1}\n00:00:{i * 2:02d},000 --> 00:00:{i * 2 + 1:02d},500\n同じ台詞"
        for i in range(count)
    ) + "\n"


class SrtTests(unittest.TestCase):
    def test_original_text_index_time_tags_and_identity(self):
        text = '\ufeff007\r\n00:00:01,200\t-->  00:00:03,450\r\n <i>はい</i>\r\n🎵続く  \r\n'
        document = parse_srt(text)
        cue = document.cues[0]
        self.assertEqual((cue.index, cue.index_text, cue.start_ms, cue.end_ms), (7, "007", 1200, 3450))
        self.assertEqual(cue.time_line, '00:00:01,200\t-->  00:00:03,450')
        self.assertEqual(cue.text, ' <i>はい</i>\n🎵続く  ')
        self.assertEqual(document.source_sha256, hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(document, parse_srt(text))
        self.assertNotEqual(cue.id, parse_srt(text.replace('はい', 'いいえ')).cues[0].id)

    def test_repeated_text_is_not_repeated_identity(self):
        cues = parse_srt(sample()).cues
        self.assertEqual(len({cue.text for cue in cues}), 1)
        self.assertEqual(len({cue.id for cue in cues}), 12)

    def test_read_byte_hash_bom_crlf_and_explicit_encoding(self):
        raw = ('\ufeff' + sample(2).replace('\n', '\r\n')).encode('utf-8')
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'source.srt'
            path.write_bytes(raw)
            document = read_srt(path)
            self.assertEqual(document.source_sha256, hashlib.sha256(raw).hexdigest())
            self.assertEqual(document.source_path, str(path.resolve()))
            self.assertEqual(path.read_bytes(), raw)
            encoded = Path(root) / 'source-utf16.srt'
            encoded.write_bytes(sample(2).encode('utf-16'))
            with self.assertRaises(UnicodeDecodeError):
                read_srt(encoded)
            self.assertEqual(len(read_srt(encoded, encoding='utf-16').cues), 2)

    def test_duplicate_numeric_indices_including_zero_padding_rejected(self):
        for index in ('1', '01'):
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'duplicate'):
                parse_srt(sample(2).replace('\n\n2\n', f'\n\n{index}\n'))

    def test_invalid_index_body_and_time_are_explicit_errors(self):
        source = sample(1)
        bad = [
            '', ' \n', source.replace('1\n', '0\n', 1),
            source.replace('1\n', '-1\n', 1), source.replace('1\n', 'one\n', 1),
            source.replace('00:00:00,000', '00:60:00,000'),
            source.replace('00:00:00,000', '00:00:60,000'),
            source.replace('00:00:00,000', '00:00:00.000'),
            source.replace('00:00:01,500', '00:00:00,000'),
            source.replace('00:00:01,500', '00:00:00,000 X1:0'),
            source.replace('同じ台詞', '  '), '1\n00:00:00,000 --> 00:00:01,000\n',
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_srt(text)

    def test_batch_default_covers_edges_tail_and_readonly_once(self):
        document = parse_srt(sample())
        batches = plan_batches(document)
        self.assertEqual([len(batch.targets) for batch in batches], [5, 5, 2])
        self.assertEqual(batches[0].before, ())
        self.assertEqual(batches[-1].after, ())
        self.assertEqual(batches[0].after, (document.cues[5],))
        self.assertEqual(batches[1].before, (document.cues[4],))
        for batch in batches:
            self.assertTrue(set(batch.target_ids).isdisjoint(batch.readonly_ids))
            self.assertEqual(batch.source_sha256, document.source_sha256)
            validate_window(batch.to_window())

    def test_batch_coverage_all_lengths_and_sizes(self):
        for count in range(1, 15):
            document = parse_srt(sample(count))
            for size in range(1, 12):
                for policy in ('fixed', 'natural'):
                    batches = plan_batches(document, target_size=size, context_size=2, policy=policy)
                    flattened = tuple(cue for batch in batches for cue in batch.targets)
                    self.assertEqual(flattened, document.cues)
                    self.assertTrue(all(1 <= len(batch.targets) <= size for batch in batches))

    def test_natural_punctuation_keeps_source_cues_and_latest_boundary(self):
        text = sample(8).replace('同じ台詞', '続き', 2)
        # End cue 3 with punctuation; the other source cues have no boundaries.
        parts = text.split('\n\n')
        parts[2] = parts[2].replace('同じ台詞', '<i>終わり。</i>')
        document = parse_srt('\n\n'.join(parts))
        batches = plan_batches(document, policy='natural')
        self.assertEqual([len(batch.targets) for batch in batches], [3, 5])
        self.assertEqual(batches[0].after, (document.cues[3],))

    def test_natural_positive_gap_and_no_false_overlap_boundary(self):
        text = sample(7).replace('00:00:05,500', '00:00:04,500')
        document = parse_srt(text)
        batches = plan_batches(document, policy='natural', gap_ms=1000)
        self.assertEqual([len(batch.targets) for batch in batches], [3, 4])
        self.assertEqual([len(batch.targets) for batch in plan_batches(document)], [5, 2])
        # Zero threshold still requires a positive gap.
        overlapping = parse_srt(sample(7).replace(',500', ',500').replace('00:00:01,500', '00:00:20,500'))
        self.assertEqual(len(plan_batches(overlapping, target_size=1, policy='natural', gap_ms=0)), 7)

    def test_invalid_batch_policy_values(self):
        document = parse_srt(sample(1))
        for settings in ({'target_size': 0}, {'target_size': True}, {'target_size': 1.5},
                         {'context_size': -1}, {'context_size': False}, {'gap_ms': -1},
                         {'gap_ms': True}, {'policy': 'unknown'}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                plan_batches(document, **settings)

    def test_export_exact_mapping_preserves_order_indices_and_timing(self):
        document = parse_srt(sample(3).replace('1\n', '001\n', 1))
        mapping = {cue.id: f'译文{cue.index}\n第二行' for cue in reversed(document.cues)}
        output = render_srt(document, mapping)
        translated = parse_srt(output)
        self.assertEqual([cue.index_text for cue in translated.cues], ['001', '2', '3'])
        self.assertEqual([cue.time_line for cue in translated.cues], [cue.time_line for cue in document.cues])
        self.assertEqual([cue.text for cue in translated.cues], [mapping[cue.id] for cue in document.cues])

    def test_partial_and_unknown_mapping_never_produces_source_fallback(self):
        document = parse_srt(sample(3))
        mapping = {document.cues[0].id: '译文', document.cues[1].id: ' ', 'unknown': '译文'}
        report = validate_translations(document, mapping)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['valid_count'], 1)
        self.assertEqual(report['missing_ids'], [document.cues[2].id])
        self.assertEqual(report['unexpected_ids'], ['unknown'])
        self.assertEqual(report['invalid'][0]['id'], document.cues[1].id)
        with self.assertRaises(IncompleteTranslationError) as raised:
            render_srt(document, mapping)
        self.assertEqual(raised.exception.report, report)

    def test_blank_line_or_nonstring_translation_rejected(self):
        document = parse_srt(sample(1))
        for text in ('译文\n\n正文', '译文\n \n正文', '译文\n', 3, None):
            with self.subTest(text=text), self.assertRaises(IncompleteTranslationError):
                render_srt(document, {document.cues[0].id: text})

    def test_write_refuses_partial_existing_and_source_outputs(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'jpn.srt'
            raw = sample(2).encode()
            source.write_bytes(raw)
            document = read_srt(source)
            out = Path(root) / 'chn.srt'
            with self.assertRaises(IncompleteTranslationError):
                write_srt(document, {}, out)
            self.assertFalse(out.exists())
            mapping = {cue.id: '译文' for cue in document.cues}
            with self.assertRaisesRegex(ValueError, 'source'):
                write_srt(document, mapping, source)
            write_srt(document, mapping, out)
            with self.assertRaises(FileExistsError):
                write_srt(document, mapping, out)
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(out.read_bytes(), render_srt(document, mapping).encode())

    def test_all_overlaps_nested_and_nonchronological_are_diagnosed(self):
        source = ('2\n00:00:02,000 --> 00:00:03,000\nA\n\n'
                  '1\n00:00:00,000 --> 00:00:05,000\nB\n\n'
                  '3\n00:00:01,000 --> 00:00:04,000\nC\n\n'
                  '4\n00:00:05,000 --> 00:00:06,000\nD\n')
        document = parse_srt(source)
        report = diagnostics(document)
        self.assertEqual(len(report['overlaps']), 3)
        self.assertEqual(sorted(row['overlap_ms'] for row in report['overlaps']), [1000, 1000, 3000])
        self.assertEqual({row['reason'] for row in report['order_issues']}, {'start_time_decreases', 'index_decreases'})
        self.assertIsNone(report['thresholds'])

    def test_unicode_codepoint_cps_line_count_is_explicit_not_glyph_width(self):
        document = parse_srt('1\n00:00:00,000 --> 00:00:02,000\n甲😀\ne\u0301 🎵\n')
        row = diagnostics(document)['cues'][0]
        self.assertEqual(row['line_codepoint_lengths'], [2, 4])
        self.assertEqual(row['codepoint_count'], 6)
        self.assertEqual(row['line_count'], 2)
        self.assertEqual(row['codepoints_per_second'], 3)
        translated = diagnostics(document, {document.cues[0].id: '中'})['cues'][0]
        self.assertEqual(translated['codepoints_per_second'], 0.5)
        with self.assertRaises(IncompleteTranslationError):
            diagnostics(document, {})

    def test_sidecar_provenance_records_source_spans_and_display_times(self):
        document = parse_srt(sample(2))
        report = source_provenance(document)
        self.assertEqual(report['source_sha256'], document.source_sha256)
        self.assertEqual(report['timing_origin'], 'source_srt_display_cue')
        for row, cue in zip(report['cues'], document.cues):
            self.assertEqual(row['id'], cue.id)
            self.assertEqual(row['source_span'], [0, len(cue.text)])
            self.assertEqual(row['time_line'], cue.time_line)


if __name__ == '__main__':
    unittest.main()
