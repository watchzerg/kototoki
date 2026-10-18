"""划组统计的离线测试（合成场景，无 .local 数据、GPU 或模型）。"""

from __future__ import annotations

import unittest

from experiments.translation_v3.data import Cue, Scene

from . import stats


def scene(*rows: tuple[str, float, float]) -> Scene:
    return Scene("s", tuple(Cue(f"c{i}", text, start, end) for i, (text, start, end) in enumerate(rows)))


class SentenceEndTest(unittest.TestCase):
    def test_strict_vs_extended(self) -> None:
        self.assertTrue(stats.ends_sentence("そうか。", False))
        self.assertFalse(stats.ends_sentence("そうか?", False))
        self.assertTrue(stats.ends_sentence("そうか?", True))
        self.assertFalse(stats.ends_sentence("「そうか。」", False))
        self.assertTrue(stats.ends_sentence("「そうか。」", True))
        self.assertTrue(stats.ends_sentence("そうか！　", False))
        self.assertFalse(stats.ends_sentence("そうか…", True))
        self.assertFalse(stats.ends_sentence("", True))


class GroupTest(unittest.TestCase):
    def setUp(self) -> None:
        # 间隔：0.2、0.2（上一行以？结尾）、1.0（恰在门槛）、0.4
        self.scene = scene(("あ", 0.0, 1.0), ("い？", 1.2, 2.0), ("う", 2.2, 3.0), ("え", 4.0, 5.0), ("お", 5.4, 6.0))

    def test_r1_threshold_is_strict(self) -> None:
        self.assertEqual(stats.groups_in(self.scene, 0, 5, stats.R1, 1.0), [(0, 3), (3, 5)])
        self.assertEqual(stats.groups_in(self.scene, 0, 5, stats.R1, 1.5), [(0, 5)])

    def test_r2_cuts_after_sentence_end(self) -> None:
        self.assertEqual(stats.groups_in(self.scene, 0, 5, stats.R2, 1.0), [(0, 2), (2, 3), (3, 5)])

    def test_groups_are_truncated_at_pack_bounds(self) -> None:
        self.assertEqual(stats.groups_in(self.scene, 0, 2, stats.R1, 1.0), [(0, 2)])
        self.assertEqual(stats.groups_in(self.scene, 2, 5, stats.R1, 1.0), [(2, 3), (3, 5)])

    def test_truncation_counts_cut_inside_group(self) -> None:
        whole = stats.groups_in(self.scene, 0, 5, stats.R1, 1.0)
        result = stats.truncation([(whole, [2])])
        self.assertEqual((result["groups_multi"], result["groups_truncated"], result["cues_in_truncated"]), (2, 1, 3))
        self.assertEqual((result["cuts"], result["cuts_inside_group"]), (1, 1))
        self.assertEqual(stats.truncation([(whole, [3])])["groups_truncated"], 0)

    def test_size_distribution_buckets(self) -> None:
        dist = stats.size_distribution([1, 1, 2, 5])
        self.assertEqual(dist["group_share"], {"1": 0.5, "2": 0.25, "3": 0.0, "4+": 0.25})
        self.assertAlmostEqual(dist["cue_share"]["4+"], 5 / 9)


if __name__ == "__main__":
    unittest.main()
