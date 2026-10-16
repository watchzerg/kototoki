import unittest

from experiments.quality_v5.mbr_cheap import batch_samples, consensus, request_seconds, stop_point


class MbrCheapTest(unittest.TestCase):
    def test_consensus_min_and_mean(self):
        same = [{"a": "你好世界", "b": "猫"}, {"a": "你好世界", "b": "狗"}, {"a": "你好世界", "b": "鸟"}]
        self.assertEqual(consensus(same, ["a"]), 1.0)
        self.assertEqual(consensus(same, ["a", "b"], "min"), 0.0)
        self.assertEqual(consensus(same, ["a", "b"], "mean"), 0.5)

    def test_stop_point_respects_kmin_and_falls_back_to_all(self):
        agree = [(k, {"a": "完全一样的译文"}) for k in range(8)]
        self.assertEqual(stop_point(agree, ["a"], 3, 0.9), 3)
        differ = [(k, {"a": f"译文{chr(0x4e00 + k * 7)}{chr(0x4e10 + k * 11)}"}) for k in range(8)]
        self.assertEqual(stop_point(differ, ["a"], 3, 0.99), 8)

    def test_failed_samples_keep_their_index(self):
        batch = {"candidates": [{"a": "x"}, {"a": "y"}], "failed_samples": [{"sample": 1}]}
        self.assertEqual([k for k, _ in batch_samples({}, batch, 3)], [0, 2])

    def test_request_seconds_by_batch_and_sample(self):
        row = {"requests": [{"batch_index": 0, "sample": 0, "attempts": [{"elapsed_seconds": 2.0}]},
                            {"batch_index": 0, "sample": 1, "attempts": [{"elapsed_seconds": 1.0},
                                                                         {"elapsed_seconds": 0.5}]}]}
        self.assertEqual(request_seconds(row), {(0, 0): 2.0, (0, 1): 1.5})


if __name__ == "__main__":
    unittest.main()
