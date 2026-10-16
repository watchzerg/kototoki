import unittest

from experiments.quality_v5.diversity import cue_similarity


class DiversityTest(unittest.TestCase):
    def test_identical_samples_score_one_and_disjoint_score_zero(self):
        self.assertEqual(cue_similarity(["你好", "你好", "你好"]), 1.0)
        self.assertEqual(cue_similarity(["猫", "狗"]), 0.0)


if __name__ == "__main__":
    unittest.main()
