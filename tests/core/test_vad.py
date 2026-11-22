"""kototoki.vad 的离线测试：chunk_intervals 的并集、硬切与贪心合并。"""

import unittest

from kototoki.vad import MAX_CHUNK_SAMPLES, SAMPLE_RATE, chunk_intervals


class ChunkIntervalsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
