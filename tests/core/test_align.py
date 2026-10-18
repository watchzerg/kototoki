"""kototoki.align 纯函数的离线测试：不构造 MmsAligner，不导入 torch／torchaudio／transformers。"""

from contextlib import contextmanager
from types import SimpleNamespace
import unittest

import numpy as np

from kototoki.align import (
    character_targets, clamp_window, map_records, mms_numeric_policy, model_dictionary,
    normalize_window, sample_window, torchaudio_supported,
)


def token(position, start, end, *, known=True):
    return {"original_position": position, "start_frame": start, "end_frame": end,
            "token_probability": 0.8, "evidence_kind": "vocabulary_token" if known else "wildcard",
            "lexical_interval_accepted": known}


class TorchaudioVersionTests(unittest.TestCase):
    def test_minimum_version_is_2_10(self):
        for version, expected in (("2.11.0+cu128", True), ("2.10.0", True), ("2.8.0", False),
                                  ("2.9.1+cu128", False), ("3.0.0", True)):
            with self.subTest(version=version):
                self.assertEqual(torchaudio_supported(version), expected)


class ModelDictionaryTests(unittest.TestCase):
    def test_lowercases_keys_and_drops_ids_outside_model_classes(self):
        dictionary, dropped = model_dictionary({"A": 1, "日": 2, "<pad>": 0, "|": 3}, 3)
        self.assertEqual(dictionary, {"a": 1, "日": 2, "<pad>": 0})
        self.assertEqual(dropped, {"|": 3})

    def test_transformers_5_added_delimiter_is_dropped(self):
        """transformers 5.x 的 MMS 分词器把 `|` 作为 id 2268 的 added token，模型只有 2268 类。"""
        vocabulary = {chr(0x4E00 + index): index for index in range(2268)}
        vocabulary["|"] = 2268
        dictionary, dropped = model_dictionary(vocabulary, 2268)
        self.assertEqual(len(dictionary), 2268)
        self.assertNotIn("|", dictionary)
        self.assertEqual(dropped, {"|": 2268})
        # `|` 不在字典里，因而被 character_targets 跳过；通配符列号等于字典长度。
        targets = character_targets("丁|?", dictionary, len(dictionary))
        self.assertEqual([row["original_position"] for row in targets], [0, 2])
        self.assertEqual(targets[0]["token_id"], 1)
        self.assertEqual(targets[1]["token_id"], 2268)
        self.assertFalse(targets[1]["lexical_interval_accepted"])

    def test_in_range_vocabulary_drops_nothing(self):
        dictionary, dropped = model_dictionary({"a": 0, "b": 1}, 2)
        self.assertEqual((dictionary, dropped), ({"a": 0, "b": 1}, {}))


class TargetTests(unittest.TestCase):
    def test_repeats_keep_positions_and_unknown_characters_use_wildcard(self):
        targets = character_targets(" \t日日? A|\n", {"日": 1, "a": 2}, 3)
        self.assertEqual([row["original_position"] for row in targets], [2, 3, 4, 6])
        self.assertEqual([row["token_id"] for row in targets], [1, 1, 3, 2])
        self.assertEqual([row["lexical_interval_accepted"] for row in targets], [True, True, False, True])

    def test_delimiter_absent_from_dictionary_is_skipped_and_wildcard_follows_dictionary(self):
        dictionary, _ = model_dictionary({"日": 1, "a": 2, "|": 3}, 3)
        targets = character_targets("日|?", dictionary, len(dictionary))
        self.assertEqual([row["original_position"] for row in targets], [0, 2])
        self.assertEqual(targets[1]["token_id"], len(dictionary))
        self.assertFalse(targets[1]["lexical_interval_accepted"])

    def test_known_internal_space_is_kept_and_blank_text_has_no_targets(self):
        targets = character_targets("a a", {"a": 1, " ": 2}, 3)
        self.assertEqual([row["token_id"] for row in targets], [1, 2, 1])
        self.assertEqual(character_targets(" \t\n", {" ": 2}, 3), [])

    def test_lowercase_expansion_is_an_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "token_character_count_mismatch"):
            character_targets("İ", {"i": 1}, 2)


class NumericPolicyTests(unittest.TestCase):
    def fake_torch(self, deterministic=False):
        cudnn = SimpleNamespace(enabled=False, benchmark=True, deterministic=True, allow_tf32=False)

        @contextmanager
        def flags(**requested):
            before = {name: getattr(cudnn, name) for name in requested}
            try:
                for name, value in requested.items():
                    setattr(cudnn, name, value)
                yield
            finally:
                for name, value in before.items():
                    setattr(cudnn, name, value)

        cudnn.flags = flags
        return SimpleNamespace(
            backends=SimpleNamespace(cuda=SimpleNamespace(matmul=SimpleNamespace(allow_tf32=True)), cudnn=cudnn),
            are_deterministic_algorithms_enabled=lambda: deterministic,
            get_float32_matmul_precision=lambda: "highest")

    def assert_restored(self, torch):
        self.assertTrue(torch.backends.cuda.matmul.allow_tf32)
        self.assertFalse(torch.backends.cudnn.enabled)
        self.assertTrue(torch.backends.cudnn.benchmark)
        self.assertTrue(torch.backends.cudnn.deterministic)
        self.assertFalse(torch.backends.cudnn.allow_tf32)

    def test_scoped_defaults_apply_inside_and_are_restored_after(self):
        torch = self.fake_torch(deterministic=True)
        with mms_numeric_policy(torch) as actual:
            self.assertEqual(actual, {
                "matmul_allow_tf32": False, "cudnn_allow_tf32": True, "cudnn_enabled": True,
                "cudnn_benchmark": False, "cudnn_deterministic": False,
                "deterministic_algorithms": True, "float32_matmul_precision": "highest"})
        self.assert_restored(torch)

    def test_failure_inside_scope_restores_flags(self):
        torch = self.fake_torch()
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with mms_numeric_policy(torch):
                raise RuntimeError("synthetic forward failure")
        self.assert_restored(torch)


class MapRecordsTests(unittest.TestCase):
    SEGMENTS = [{"text": " 日日? ", "start": 1.0, "end": 2.0}, {"text": "日", "start": 3.0, "end": 4.0}]
    RECORDS = [{"segment_index": 0, "frame_count": 10, "failure": None,
                "tokens": [token(1, 0, 2), token(2, 3, 6), token(3, 7, 8, known=False)]}]

    def test_every_character_gets_exactly_one_unit(self):
        result = map_records(self.SEGMENTS, self.RECORDS)
        self.assertEqual(result["text"], " 日日? 日")
        self.assertEqual([(u["char_start"], u["char_end"]) for u in result["units"]],
                         [(i, i + 1) for i in range(6)])
        self.assertEqual([u["status"] for u in result["units"]],
                         ["text_only", "ok", "ok", "text_only", "text_only", "text_only"])
        self.assertTrue(all(u["granularity"] == "character" and u["time_source"] == "api"
                            for u in result["units"]))

    def test_zero_offset_units_equal_local_times(self):
        result = map_records(self.SEGMENTS, self.RECORDS, 0)
        first = result["units"][1]
        self.assertEqual((first["start"], first["end"]), (1.0, 1.2))
        chars = result["derived_segments"][0]["chars"]
        self.assertEqual((chars[1]["start"], chars[1]["end"]), (first["start"], first["end"]))

    def test_offset_applies_to_units_only(self):
        local = map_records(self.SEGMENTS, self.RECORDS, 0)
        shifted = map_records(self.SEGMENTS, self.RECORDS, 100.0)
        for before, after in zip(local["units"], shifted["units"]):
            if before["status"] == "ok":
                self.assertAlmostEqual(after["start"], before["start"] + 100.0)
                self.assertAlmostEqual(after["end"], before["end"] + 100.0)
            else:
                self.assertIsNone(after["start"])
        self.assertEqual(shifted["derived_segments"], local["derived_segments"])
        self.assertEqual(shifted["records"], local["records"])

    def test_failed_or_invalid_records_become_text_only(self):
        segments = [{"text": "日日日", "start": 0, "end": 1}, {"text": "日", "start": 1, "end": 2}]
        records = [{"segment_index": 0, "frame_count": 10,
                    "tokens": [token(0, -1, 1), token(1, 2, 2), token(2, 9, 11)]},
                   {"segment_index": 1, "frame_count": 10, "failure": "CUDA failure",
                    "tokens": [token(0, 0, 1)]}]
        result = map_records(segments, records)
        self.assertEqual(len(result["units"]), 4)
        self.assertTrue(all(u["status"] == "text_only" and u["start"] is None and u["end"] is None
                            for u in result["units"]))

    def test_segment_without_record_keeps_its_text(self):
        result = map_records([{"text": "日日", "start": 0, "end": 1}], [])
        self.assertEqual([u["status"] for u in result["units"]], ["text_only", "text_only"])

    def test_empty_input_and_zero_frames(self):
        self.assertEqual(map_records([], []), {"text": "", "units": [], "records": [], "derived_segments": []})
        result = map_records([{"text": "日", "start": 0, "end": 0}],
                             [{"segment_index": 0, "frame_count": 0, "tokens": [token(0, 0, 1)]}])
        self.assertEqual(result["units"][0]["status"], "text_only")

    def test_invalid_offset_raises(self):
        for offset in (-1, float("inf"), float("nan")):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                map_records(self.SEGMENTS, self.RECORDS, offset)


class WindowTests(unittest.TestCase):
    def segment(self, start=0, end=1001):
        return {"text": "日", "start": start / 16000, "end": end / 16000,
                "start_sample": start, "end_sample": end}

    def test_clamp_window_bounds_and_invalid(self):
        self.assertEqual(clamp_window(-2, 4, 2), (0, 2))
        self.assertEqual(clamp_window(4, 5, 2), (2, 2))
        for values in ((1, 0, 2), (0, float("nan"), 2), (0, 1, -2), (True, 1, 2)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                clamp_window(*values)

    def test_sample_window_accepts_exact_bounds_and_legacy_windows(self):
        self.assertEqual(sample_window(self.segment(), 1001), (0, 1001))
        self.assertEqual(sample_window(self.segment(480000, 481001), 481001), (480000, 481001))
        self.assertIsNone(sample_window({"start": -10, "end": 100}, 1001))

    def test_sample_window_rejects_bad_sample_bounds(self):
        for updates in ({"start_sample": True}, {"end_sample": 1001.0}, {"start_sample": -1},
                        {"end_sample": 1002}, {"end_sample": 0}, {"start_sample": None}):
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, "integer"):
                sample_window({**self.segment(), **updates}, 1001)
        segment = self.segment()
        del segment["end_sample"]
        with self.assertRaisesRegex(ValueError, "integer"):
            sample_window(segment, 1001)

    def test_sample_window_rejects_seconds_not_matching_samples(self):
        for updates in ({"start": 0.1}, {"end": 1000 / 16000}, {"end": float("inf")},
                        {"end": True}, {"end": "0.0625625"}):
            with self.subTest(updates=updates), self.assertRaisesRegex(ValueError, "seconds must match"):
                sample_window({**self.segment(), **updates}, 1001)


class NormalizeWindowTests(unittest.TestCase):
    @staticmethod
    def extractor(waveform, **options):
        """假的 Wav2Vec2FeatureExtractor：对有效样本做零均值单位方差，右侧补零。"""
        length = options["max_length"]
        normalized = (waveform - waveform.mean()) / np.sqrt(waveform.var() + 1e-7)
        return {"input_values": np.pad(normalized, (0, length - len(waveform)))[None],
                "attention_mask": np.pad(np.ones(len(waveform)), (0, length - len(waveform)))[None]}

    def test_short_window_is_right_padded_to_minimum_length(self):
        waveform = np.linspace(0.2, 0.9, 160, dtype=np.float32)
        values, record = normalize_window(waveform, self.extractor)
        self.assertEqual(values.shape, (400,))
        np.testing.assert_array_equal(values[160:], 0)
        self.assertEqual((record["valid_samples"], record["padded_samples"]), (160, 400))
        self.assertFalse(record["model_attention_mask"])

    def test_long_window_is_not_padded_and_input_is_unchanged(self):
        waveform = np.linspace(0.2, 0.9, 801, dtype=np.float32)
        before = waveform.copy()
        values, record = normalize_window(waveform, self.extractor)
        self.assertEqual(len(values), 801)
        self.assertEqual(record["padded_samples"], 801)
        np.testing.assert_array_equal(waveform, before)

    def test_empty_window_raises(self):
        with self.assertRaisesRegex(ValueError, "Empty alignment waveform"):
            normalize_window(np.zeros(0, dtype=np.float32), self.extractor)


if __name__ == "__main__":
    unittest.main()
