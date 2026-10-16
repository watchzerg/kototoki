from types import SimpleNamespace
import unittest

from experiments.quality_v5.diff_judge import differing_windows


def window(scene, scored, context):
    return SimpleNamespace(meta=SimpleNamespace(scene_id=scene), units=tuple({"id": i} for i in scored),
                           context=tuple({"id": i} for i in context))


class DiffJudgeTest(unittest.TestCase):
    def test_only_scored_cues_decide_and_other_scenes_are_skipped(self):
        windows = {"w1": window("s1", ["a"], ["a", "b"]), "w2": window("s1", ["b"], ["a", "b"]),
                   "w3": window("s2", ["c"], ["c"])}
        cand = {"a": "甲", "b": "乙二", "c": "丙二"}
        base = {"a": "甲", "b": "乙", "c": "丙"}
        self.assertEqual(differing_windows(windows, {"s1"}, cand, base), ({"w2"}, {"w1"}))


if __name__ == "__main__":
    unittest.main()
