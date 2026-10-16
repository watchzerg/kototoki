import unittest

from experiments.quality_v5.mbr_semantic import mbr_index


class MbrSemanticTest(unittest.TestCase):
    def test_picks_the_most_central_vector(self):
        vectors = [[1.0, 0.0], [0.6, 0.8], [0.8, 0.6]]
        self.assertEqual(mbr_index(vectors), 2)

    def test_ties_go_to_the_lowest_index_and_single_sample_is_zero(self):
        self.assertEqual(mbr_index([[1.0, 0.0], [1.0, 0.0]]), 0)
        self.assertEqual(mbr_index([[0.0, 1.0]]), 0)


if __name__ == "__main__":
    unittest.main()
