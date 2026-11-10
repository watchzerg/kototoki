"""票据 05 的离线测试：运行顺序、两臂的日文来源、翻译汇总只含计数。"""

from __future__ import annotations

import unittest

from experiments.asr_robustness_v15 import common, translate_impact as T


class TranslateImpactTest(unittest.TestCase):
    def test_runs_pair_control_and_candidate_per_seed_and_film(self) -> None:
        rows = T.runs(("hf-ii", "hf-iii"))
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[:2], [(20261054, "hf-ii", "control"), (20261054, "hf-ii", "candidate")])
        self.assertEqual({seed for seed, _, _ in rows}, set(T.SEEDS))

    def test_arms_read_different_japanese(self) -> None:
        self.assertEqual(T.ja_path("control", "hf-ii"), common.FILMS["hf-ii"]["work"] / "ja.srt")
        candidate = T.ja_path("candidate", "hf-iii")
        self.assertEqual(candidate.parts[-4:], ("04", "c3a-entity", "hf-iii", "ja.srt"))

    def test_translate_summary_counts_fallbacks_per_arm(self) -> None:
        rows = [{"arm": "control", "film": "hf-ii", "seed": 20261054, "fallback_count": 0, "seconds": 10.0},
                {"arm": "candidate", "film": "hf-ii", "seed": 20261054, "fallback_count": 2, "seconds": 11.5},
                {"arm": "candidate", "film": "hf-iii", "seed": 20261055, "fallback_count": 0, "seconds": 9.0}]
        summary = T.translate_summary(rows)
        self.assertEqual(summary["control"], {"runs": 1, "fallback_cues": 0, "runs_with_fallback": 0, "seconds": 10.0,
                                              "by_run": {"HF-II.s20261054": 0}})
        self.assertEqual(summary["candidate"]["fallback_cues"], 2)
        self.assertEqual(summary["candidate"]["runs_with_fallback"], 1)
        self.assertEqual(summary["candidate"]["by_run"], {"HF-II.s20261054": 2, "HF-III.s20261055": 0})


if __name__ == "__main__":
    unittest.main()
