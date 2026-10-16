import unittest

from experiments.quality_v5.confirm_series import patch
from experiments.translation_v4 import stats4


class ConfirmSeriesTest(unittest.TestCase):
    def test_overall_is_the_mean_of_present_categories(self):
        original = stats4.aggregate_sums
        try:
            patch()
            sums = {"W01": (1.0, 2), "W02": (3.0, 2)}
            result = stats4.aggregate_sums(sums, {"W01": "anime_series", "W02": "anime_series"})
            self.assertEqual(result["overall"], result["anime_series"])
            self.assertIsNone(result["animation_movie"])
            both = stats4.aggregate_sums({"W01": (1.0, 1), "M01": (3.0, 1)}, {"W01": "anime_series", "M01": "animation_movie"})
            self.assertEqual(both["overall"], original({"W01": (1.0, 1), "M01": (3.0, 1)},
                                                       {"W01": "anime_series", "M01": "animation_movie"})["overall"])
        finally:
            stats4.aggregate_sums = original


if __name__ == "__main__":
    unittest.main()
