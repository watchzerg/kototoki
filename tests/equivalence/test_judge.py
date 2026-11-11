"""`kototoki.judge` 与研究脚本 `experiments/quality_v5` 在合成样例上的逐项实时对照。core 侧只钉结果摘要
（`tests/core/test_judge.py::ResearchPinTests`）。"""

from __future__ import annotations

import unittest
from dataclasses import asdict

from experiments.quality_v5 import asr_pair_cross_score as cs
from experiments.quality_v5 import asr_pair_ctc_judge as c
from experiments.quality_v5 import asr_pair_oracle as o
from kototoki import judge as J
from kototoki_eval.schema import normalize as eval_normalize
from tests.core.test_judge import SAMPLES


class ResearchEquivalenceTests(unittest.TestCase):
    def test_align_intervals_compose_match_oracle(self):
        kind_names = {"替换": "substitution", "w0 多出": "w0_extra", "x0 多出": "x0_extra"}
        for raw_w, raw_x in SAMPLES:
            with self.subTest(w=raw_w, x=raw_x):
                w, x = J.normalize(raw_w).text, J.normalize(raw_x).text
                self.assertEqual(J.align_ops(w, x), o.align_ops(w, x))
                ours = J.disagreement_intervals(w, x)
                theirs = o.disagreement_intervals(w, x)
                self.assertEqual([{k: v for k, v in asdict(it).items() if k != "kind"} for it in ours], theirs)
                self.assertEqual([it.kind for it in ours], [kind_names[o.interval_kind(it)] for it in theirs])
                for mask in range(1 << len(ours)):
                    picks = [bool(mask >> k & 1) for k in range(len(ours))]
                    self.assertEqual(J.compose(w, ours, picks),
                                     o.compose(w, theirs, ["x" if p else "w" for p in picks]))

    def test_raw_hypotheses_match_cross_score(self):
        for raw_w, raw_x in SAMPLES:
            with self.subTest(w=raw_w, x=raw_x):
                for raw in (raw_w, raw_x):
                    ours_n, theirs_n = J.normalize(raw), eval_normalize(raw)
                    self.assertEqual((ours_n.text, ours_n.raw_spans), (theirs_n.text, theirs_n.raw_spans))
                intervals, hyp_w, hyp_xs, form = J.hypotheses(raw_w, raw_x)
                theirs = cs.o.disagreement_intervals(eval_normalize(raw_w).text, eval_normalize(raw_x).text)
                raw = [cs.raw_hypothesis(raw_w, raw_x, it) for it in theirs]
                if all(h is not None for h in raw):
                    self.assertEqual((form, hyp_w, hyp_xs), ("raw", raw_w, raw))
                else:
                    w = eval_normalize(raw_w).text
                    self.assertEqual((form, hyp_w, hyp_xs),
                                     ("normalized", w, [c.hypothesis_x(w, it) for it in theirs]))


if __name__ == "__main__":
    unittest.main()
