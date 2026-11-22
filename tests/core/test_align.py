"""kototoki.align 的离线测试：字符目标、记录到字符单元的映射、逐窗失败隔离与输入归一化；不加载模型，不导入 torch。"""

import unittest

import numpy as np

from kototoki.align import MmsAligner, character_targets, map_records, normalize_window


def token(position, start, end, *, known=True):
    return {"original_position": position, "start_frame": start, "end_frame": end,
            "token_probability": 0.8, "evidence_kind": "vocabulary_token" if known else "wildcard",
            "lexical_interval_accepted": known}


class TargetTests(unittest.TestCase):
    def test_repeats_keep_positions_and_unknown_characters_use_wildcard(self):
        targets = character_targets(" \t日日? A|\n", {"日": 1, "a": 2}, 3)
        self.assertEqual([row["original_position"] for row in targets], [2, 3, 4, 6])
        self.assertEqual([row["token_id"] for row in targets], [1, 1, 3, 2])
        self.assertEqual([row["lexical_interval_accepted"] for row in targets], [True, True, False, True])



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



class AlignLoopTests(unittest.TestCase):
    """`MmsAligner.align` 的逐窗循环：不加载模型，`_align_segment` 换成伪实现。"""

    def aligner(self, calls):
        aligner = MmsAligner.__new__(MmsAligner)
        aligner.blank_id = 0

        def align_segment(audio, text, record):
            calls.append((len(audio), text, record["window_start_sample"], record["window_end_sample"]))
            if text == "壊":
                raise RuntimeError("boom")
            record.update(frame_count=10, tokens=[token(0, 2, 4)])
        aligner._align_segment = align_segment
        return aligner

    def segment(self, text, start, end):
        return {"text": text, "start": start / 16000, "end": end / 16000, "start_sample": start, "end_sample": end}

    def test_records_use_sample_bounds_and_units_stay_local(self):
        calls = []
        audio = np.zeros(32000, dtype=np.float32)
        result = self.aligner(calls).align(audio, [self.segment("日", 16000, 32000), self.segment("壊", 0, 1600)])
        self.assertEqual(calls, [(32000, "日", 16000, 32000), (32000, "壊", 0, 1600)])
        first, second = result["records"]
        self.assertEqual((first["window_start"], first["window_end"]), (1.0, 2.0))
        self.assertEqual(list(first)[:8], ["segment_index", "window_start", "window_end", "blank_id", "tokens",
                                           "failure", "window_start_sample", "window_end_sample"])
        self.assertEqual((result["units"][0]["start"], result["units"][0]["end"]), (1.2, 1.4))
        self.assertEqual((second["failure"], second["tokens"], result["units"][1]["status"]),
                         ("RuntimeError: boom", [], "text_only"))



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


if __name__ == "__main__":
    unittest.main()
