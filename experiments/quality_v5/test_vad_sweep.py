import unittest

import numpy as np
from pyannote.core import SlidingWindow, SlidingWindowFeature

from experiments.quality_v5.vad_sweep import CURRENT, additive_chunks, coverage, grid, intervals, merge, overlap_seconds, union_seconds


def feature(values: list[float], step: float = 0.1) -> SlidingWindowFeature:
    return SlidingWindowFeature(np.asarray(values, dtype=np.float32)[:, None],
                                SlidingWindow(start=0.0, duration=step, step=step))


class VadSweepTest(unittest.TestCase):
    def test_merge_and_union(self):
        spans = [[3.0, 4.0], [0.0, 1.0], [0.5, 2.0]]
        self.assertEqual(merge(spans), [[0.0, 2.0], [3.0, 4.0]])
        self.assertAlmostEqual(union_seconds(spans), 3.0)

    def test_overlap_seconds(self):
        self.assertAlmostEqual(overlap_seconds([[0.0, 2.0], [3.0, 5.0]], [[1.0, 4.0]]), 2.0)
        self.assertEqual(overlap_seconds([[0.0, 1.0]], [[2.0, 3.0]]), 0.0)

    def test_lower_onset_recovers_weak_frames(self):
        scores = feature([0.0] * 5 + [0.3] * 5 + [0.8] * 10 + [0.0] * 5)
        current = intervals(scores, 40000, CURRENT)
        lower = intervals(scores, 40000, {**CURRENT, "onset": 0.2, "offset": 0.2})
        self.assertEqual(len(current), 1)
        self.assertLess(lower[0][0], current[0][0])

    def test_pad_extends_and_merges(self):
        scores = feature([0.0] * 5 + [0.9] * 5 + [0.0] * 3 + [0.9] * 5 + [0.0] * 5)
        plain = intervals(scores, 40000, CURRENT)
        padded = intervals(scores, 40000, {**CURRENT, "pad": 0.2})
        self.assertEqual(len(plain), 2)
        self.assertEqual(len(padded), 1)
        self.assertGreaterEqual(padded[0][0], 0.0)

    def test_coverage_counts_reference(self):
        speech = [[0.0, 1.0], [5.0, 6.0]]
        reference = [{"start": 0.0, "end": 2.0}, {"start": 5.0, "end": 6.0}]
        result = coverage(speech, reference, 16000 * 10, "x")
        self.assertAlmostEqual(result["ref_time_recall"], 2 / 3, places=3)
        self.assertEqual(result["ref_cue_half_covered"], 1.0)
        self.assertEqual(result["outside_ref_s"], 0.0)

    def test_grid_contains_current_and_valid_offsets(self):
        rows = grid()
        self.assertIn(CURRENT, rows)
        self.assertTrue(all(0 < row["offset"] <= row["onset"] for row in rows))

    def test_additive_keeps_current_windows(self):
        from kototoki.vad import chunk_intervals

        samples = 16000 * 100
        current, _ = chunk_intervals([[10.0, 20.0], [50.0, 60.0]], samples)
        speech = [[9.0, 21.0], [30.0, 31.0], [35.0, 35.2], [49.5, 62.0]]
        merged, info = additive_chunks(current, speech, samples, 0.5)
        for chunk in current:
            self.assertIn(chunk, merged)
        added = [c for c in merged if c not in current]
        self.assertEqual(info["added_windows"], len(added))
        for chunk in added:
            self.assertFalse(any(chunk["start"] < c["end"] and c["start"] < chunk["end"] for c in current))
        starts = [c["start_sample"] for c in merged]
        self.assertEqual(starts, sorted(starts))
        self.assertTrue(any(c["start"] <= 30.0 and c["end"] >= 31.0 for c in added))
        self.assertTrue(any(c["end"] <= 10.0 for c in added))  # 9–10 s 的前沿补段


if __name__ == "__main__":
    unittest.main()
