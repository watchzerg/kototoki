"""kototoki.vad 的离线测试：chunk_intervals 的取整、裁剪、并集、硬切、贪心合并与非法输入。"""

import math
import unittest

import numpy as np

from kototoki.schema import validate_windows
from kototoki.vad import MAX_CHUNK_SAMPLES, SAMPLE_RATE, chunk_intervals, validate_audio


class ChunkIntervalsTests(unittest.TestCase):
    def test_floor_start_and_ceil_end_retain_sub_sample_speech(self):
        """起点向下、终点向上取整，子样本级语音也被保留。"""
        chunks, metadata = chunk_intervals([[0.00001, 0.00007]], 10)
        self.assertEqual((chunks[0]["start_sample"], chunks[0]["end_sample"]), (0, 2))
        self.assertEqual(metadata["accounting"]["speech_samples"], 2)

    def test_out_of_source_bounds_are_clipped_and_counted(self):
        chunks, metadata = chunk_intervals([[-0.1, 0.2], [0.8, 1.1]], SAMPLE_RATE)
        self.assertEqual((chunks[0]["start_sample"], chunks[0]["end_sample"]), (0, SAMPLE_RATE))
        self.assertEqual(metadata["accounting"]["clipped_interval_count"], 2)
        self.assertEqual(metadata["raw_intervals"][0]["start"], -0.1)

    def test_interval_fully_outside_source_is_dropped_after_clip(self):
        chunks, metadata = chunk_intervals([[0.8, 1.1], [1.2, 1.3]], SAMPLE_RATE)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(metadata["accounting"]["dropped_interval_count"], 1)
        self.assertEqual(metadata["accounting"]["clipped_interval_count"], 2)
        chunks, metadata = chunk_intervals([[0, 1]], 0)
        self.assertEqual(chunks, [])
        self.assertEqual(metadata["accounting"]["dropped_interval_count"], 1)

    def test_overlaps_and_unsorted_order_form_one_union(self):
        chunks, metadata = chunk_intervals([[3, 5], [1, 4], [5, 6]], 10 * SAMPLE_RATE)
        self.assertEqual(chunks[0]["segments"], [[1, 6]])
        accounting = metadata["accounting"]
        self.assertEqual((accounting["raw_interval_count"], accounting["speech_interval_count"]), (3, 1))
        self.assertEqual(accounting["speech_samples"], 5 * SAMPLE_RATE)

    def test_interval_over_limit_is_hard_split(self):
        chunks, metadata = chunk_intervals([[1, 71]], 80 * SAMPLE_RATE)
        self.assertEqual([(c["start"], c["end"]) for c in chunks], [(1, 31), (31, 61), (61, 71)])
        self.assertEqual(metadata["accounting"]["hard_split_count"], 2)
        self.assertEqual(metadata["accounting"]["internal_silence_samples"], 0)

    def test_greedy_merge_keeps_span_within_limit(self):
        """恰好 480000 样本的跨度合并，超出一个样本就另起一窗。"""
        chunks, _ = chunk_intervals([[1, 2], [30, 31]], 32 * SAMPLE_RATE)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["end_sample"] - chunks[0]["start_sample"], MAX_CHUNK_SAMPLES)
        chunks, _ = chunk_intervals([[0, 1], [30, 31]], 32 * SAMPLE_RATE)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[1]["start_sample"], 30 * SAMPLE_RATE)

    def test_internal_silence_is_retained_and_accounted(self):
        chunks, metadata = chunk_intervals([[1, 3], [12, 14], [40, 42]], 50 * SAMPLE_RATE)
        self.assertEqual([(c["start"], c["end"]) for c in chunks], [(1, 14), (40, 42)])
        self.assertEqual(chunks[0]["segments"], [[1, 3], [12, 14]])
        accounting = metadata["accounting"]
        self.assertEqual(accounting["speech_samples"], 6 * SAMPLE_RATE)
        self.assertEqual(accounting["chunk_samples"], 15 * SAMPLE_RATE)
        self.assertEqual(accounting["internal_silence_samples"], 9 * SAMPLE_RATE)
        self.assertEqual(accounting["skipped_source_samples"], 35 * SAMPLE_RATE)

    def test_seconds_survive_int_conversion_back_to_samples(self):
        """下游仍用 int(seconds * 16000) 裁剪：奇数样本边界不能少一个样本。"""
        samples = 600000
        chunks, _ = chunk_intervals([[1001.5 / SAMPLE_RATE, 481000.5 / SAMPLE_RATE]], samples)
        chunk = chunks[0]
        self.assertEqual((chunk["start_sample"], chunk["end_sample"]), (1001, 481001))
        self.assertEqual(int(chunk["start"] * SAMPLE_RATE), 1001)
        self.assertEqual(int(chunk["end"] * SAMPLE_RATE), 481001)
        self.assertEqual(int(chunk["segments"][0][0] * SAMPLE_RATE), 1001)
        # 源末尾的样本保持精确的 sample / 16000。
        tail, _ = chunk_intervals([[1000.5 / SAMPLE_RATE, 1001 / SAMPLE_RATE]], 1001)
        self.assertEqual(tail[0]["end"], 1001 / SAMPLE_RATE)
        self.assertEqual(tail[0]["end_sample"], 1001)

    def test_empty_input_gives_no_windows(self):
        for samples in (0, SAMPLE_RATE):
            chunks, metadata = chunk_intervals([], samples)
            self.assertEqual(chunks, [])
            self.assertEqual(metadata["accounting"]["skipped_source_samples"], samples)

    def test_invalid_intervals_raise(self):
        invalid = [[[1, 1]], [[2, 1]], [[0, float("nan")]], [[0, float("inf")]],
                   [[True, 1]], [["0", 1]], [[0]], [[0, 1, 2]], [{"start": 0, "end": 1}]]
        for intervals in invalid:
            with self.subTest(intervals=intervals), self.assertRaises(ValueError):
                chunk_intervals(intervals, SAMPLE_RATE)

    def test_invalid_sample_count_raises(self):
        for samples in (-1, 1.5, True):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                chunk_intervals([], samples)

    def test_output_passes_window_schema(self):
        cases = [([[1, 3], [12, 14], [40, 42]], 50 * SAMPLE_RATE),
                 ([[1, 71]], 80 * SAMPLE_RATE),
                 ([[-0.1, 0.2], [0.8, 1.1]], SAMPLE_RATE),
                 ([[1001.5 / SAMPLE_RATE, 481000.5 / SAMPLE_RATE]], 600000)]
        for intervals, samples in cases:
            with self.subTest(intervals=intervals):
                chunks, _ = chunk_intervals(intervals, samples)
                validate_windows(chunks, samples)
                for chunk in chunks:
                    self.assertTrue(all(math.isfinite(v) for v in (chunk["start"], chunk["end"])))


class ValidateAudioTests(unittest.TestCase):
    def test_accepts_mono_float32(self):
        validate_audio(np.zeros(10, dtype=np.float32))
        validate_audio(np.zeros(0, dtype=np.float32))

    def test_rejects_wrong_shape_dtype_or_non_finite(self):
        for audio in (np.zeros(10, dtype=np.float64), np.zeros((1, 10), dtype=np.float32),
                      np.array([np.nan], dtype=np.float32), np.array([np.inf], dtype=np.float32), [0.0]):
            with self.subTest(audio=type(audio).__name__), self.assertRaises(ValueError):
                validate_audio(audio)


if __name__ == "__main__":
    unittest.main()
