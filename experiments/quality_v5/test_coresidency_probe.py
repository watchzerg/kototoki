import unittest

from experiments.quality_v5 import coresidency_probe as p


class ThresholdTest(unittest.TestCase):
    def test_binary_budget_boundary(self):
        # 13.5 GB = 13824 MiB，余量 1024 MiB → 峰值 ≤ 12800 MiB 才共驻
        self.assertTrue(p.threshold_decision(12800)["co_resident"])
        self.assertEqual(p.threshold_decision(12800)["verdict"], "co-resident")
        self.assertFalse(p.threshold_decision(12800.5)["co_resident"])
        self.assertEqual(p.threshold_decision(13000)["verdict"], "fallback-three-pass")

    def test_decimal_interpretation_is_stricter(self):
        result = p.threshold_decision(12000)
        self.assertTrue(result["binary"]["co_resident"])
        self.assertFalse(result["decimal"]["co_resident"])  # 13.5e9 B − 1e9 B ≈ 11921 MiB


class PhaseRecorderTest(unittest.TestCase):
    def test_samples_tagged_and_torch_peaks_per_phase(self):
        now = [0.0]
        resets = []
        peaks = iter([None, {"max_allocated": 2**30, "max_reserved": 2 * 2**30, "allocated": 0, "reserved": 2**30}])
        recorder = p.PhaseRecorder(clock=lambda: now[0], torch_stats=lambda: next(peaks),
                                   reset=lambda: resets.append(now[0]))
        recorder.sample(100)  # 还没进入阶段
        recorder.enter("idle")
        recorder.sample(1500)
        now[0] = 2.0
        recorder.sample(1600)
        recorder.enter("load-qwen")
        recorder.sample(5000)
        now[0] = 5.0
        recorder.sample(7000)
        recorder.close()
        recorder.close()  # 重复 close 无副作用
        rows = {r["phase"]: r for r in recorder.summary()}
        self.assertEqual(list(rows), ["idle", "load-qwen"])
        self.assertEqual(recorder.samples[0][1], "between")
        self.assertEqual(rows["idle"]["card_peak_mib"], 1600)
        self.assertEqual(rows["idle"]["wall_s"], 2.0)
        self.assertIsNone(rows["idle"]["torch_max_allocated_mib"])
        self.assertEqual(rows["load-qwen"]["card_peak_mib"], 7000)
        self.assertEqual(rows["load-qwen"]["card_min_mib"], 5000)
        self.assertEqual(rows["load-qwen"]["torch_max_allocated_mib"], 1024.0)
        self.assertEqual(rows["load-qwen"]["torch_max_reserved_mib"], 2048.0)
        self.assertEqual(len(resets), 2)  # 每次 enter 重置一次峰值


class JudgeTest(unittest.TestCase):
    def test_failed_and_identical_windows_are_not_scored(self):
        self.assertEqual(p.plan_window("はい", "はい", True, False)["status"], "w0_failed")
        self.assertEqual(p.plan_window("はい", "はい", False, True)["status"], "x0_failed")
        self.assertEqual(p.plan_window("はい。", "はい!", False, False)["status"], "identical")

    def test_independent_intervals_applied_together(self):
        w0, x0 = "疑心の書を、作っても。", "疑心の種を作ってよ!"
        plan = p.plan_window(w0, x0, False, False)
        self.assertEqual(plan["status"], "judge")
        self.assertEqual(plan["form"], "raw")
        self.assertEqual(len(plan["intervals"]), 2)
        self.assertEqual(plan["hyps"][0], w0)
        # 两区间 d 都 > −1 → 都取 x0，w0 的标点保留
        both = p.decide_window(plan, w0, x0, [-10.0, -10.5, -9.0])
        self.assertEqual(both["picks"], [True, True])
        self.assertEqual(both["merged"], "疑心の種を、作ってよ。")
        # d = −1 不取（严格大于）
        one = p.decide_window(plan, w0, x0, [-10.0, -11.0, -9.0])
        self.assertEqual(one["picks"], [False, True])
        self.assertEqual(one["merged"], "疑心の書を、作ってよ。")

    def test_empty_merge_keeps_w0(self):
        w0, x0 = "あ", ""
        plan = p.plan_window(w0, x0, False, False)
        decision = p.decide_window(plan, w0, x0, [-5.0, 0.0])
        self.assertTrue(decision["empty_guard"])
        self.assertEqual(decision["picks"], [False])
        self.assertEqual(decision["merged"], w0)


if __name__ == "__main__":
    unittest.main()
