"""Offline public-contract checks for native Crisp timestamp conversion."""

import unittest
from run import PINS, device_evidence, normalize
from run_session import configure_decoding, decode_native_segments
from align_only import replay_segments


class AdapterTests(unittest.TestCase):
    def test_original_text_missing_punctuation_and_source_offset(self):
        raw = {'transcription': [{'text': 'こんにちは。世界！', 'offsets': {'from': 0, 'to': 3000},
              'words': [{'text': 'こんにちは', 't0': 5, 't1': 100},
                        {'text': '世界', 'offsets': {'from': 1500, 'to': 2200}}]}]}
        result = normalize(raw, 10)
        self.assertEqual(result['text'], 'こんにちは。世界！')
        self.assertEqual([(u['char_start'], u['char_end']) for u in result['units']], [(0, 5), (5, 6), (6, 8), (8, 9)])
        self.assertEqual(result['units'][0]['start'], 10.05)
        self.assertEqual(result['units'][2]['end'], 12.2)
        self.assertIsNone(result['units'][1]['start'])

    def test_repetition_mapping_is_monotone_and_missing_time_fails(self):
        raw = {'transcription': [{'text': 'はいはい', 'words': [
            {'text': 'はい', 't0': 1, 't1': 20}, {'text': 'はい', 't0': -1, 't1': -1}]}]}
        units = normalize(raw)['units']
        self.assertEqual([u['char_start'] for u in units], [0, 2])
        self.assertEqual(units[1]['status'], 'failed')
        self.assertIsNone(units[1]['end'])

    def test_empty_words_do_not_delete_text(self):
        result = normalize({'transcription': [{'text': '失敗', 'offsets': {'from': 0, 'to': 0}}]})
        self.assertEqual(result['text'], '失敗')
        self.assertEqual(result['units'][0]['status'], 'text_only')

    def test_two_contexts_required_for_asr_and_fa(self):
        marker = 'crispasr_init_gpu_backend: using preferred GPU backend: Vulkan0\n'
        self.assertFalse(device_evidence(marker, 'vulkan', True)['gpu_only_contexts_verified'])
        self.assertTrue(device_evidence(marker * 2, 'vulkan', True)['gpu_only_contexts_verified'])
        self.assertFalse(device_evidence(marker * 2 + 'falling back to auto', 'vulkan', True)['gpu_only_contexts_verified'])

    def test_qwen_sticky_temperature_minus2_is_recorded(self):
        calls = []
        def temperature(session, value, seed):
            calls.append((session, value, seed))
            return -2
        result = configure_decoding(temperature, lambda session, value: 0, lambda session, value: 0, 123, 512)
        self.assertEqual(result['temperature'], -2)
        self.assertEqual(calls, [(123, 0, 42)])

    def test_other_setter_failure_still_fails_with_named_control(self):
        with self.assertRaisesRegex(RuntimeError, 'max_new_tokens failed: -2'):
            configure_decoding(lambda *args: -2, lambda *args: -2, lambda *args: 0, 123, 512)

    def test_utf8_segment_fragment_join_is_lossless(self):
        text, error = decode_native_segments([b'\xe6\x97', b'\xa5'])
        self.assertEqual(text, '日')
        self.assertEqual(error, {})

    def test_malformed_native_bytes_remain_failed_without_replacement(self):
        text, error = decode_native_segments([b'ok\xe5bad'])
        self.assertIsNone(text)
        self.assertEqual(error['raw_segment_bytes_hex'], ['6f6be5626164'])
        self.assertFalse(error['quality_valid'])
        self.assertFalse(error['replacement_used'])

    def test_replay_preserves_native_asr_range_without_reference(self):
        saved = {'manifest': {'route': 'crisp-qwen-f16-cli-asr-only', 'status': 'ok', 'pins': PINS},
                 'native': {'transcription': [{'text': '日本', 'offsets': {'from': 1100, 'to': 3300}}]}}
        plan = replay_segments(saved, 64000)
        self.assertEqual((plan[0]['start_sample'], plan[0]['end_sample'], plan[0]['offset_cs']),
                         (17600, 52800, 110))

    def test_replay_rejects_post_aligned_or_failed_source(self):
        with self.assertRaisesRegex(ValueError, 'ASR-only'):
            replay_segments({'manifest': {'route': 'crisp-qwen-f16-fa-f16', 'status': 'ok'}}, 64000)


if __name__ == '__main__':
    unittest.main()
