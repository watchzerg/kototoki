"""kototoki.judge 的离线测试：分歧区间、raw／normalized 假设、判定边界、分批打分、合并、守卫与汇总，
以及与研究脚本 `experiments/quality_v5` 在合成样例上的逐项对照（只在测试内导入研究模块）。"""

from __future__ import annotations

import subprocess
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

from kototoki import judge as J

REPO_ROOT = Path(__file__).resolve().parents[2]
MARGIN = -1.0

# (w0 原文, x0 原文)：替换、标点相邻合并、插入、删除、多区间、半角浊点簇、NFKC 展开映射失败、空串。
SAMPLES = [
    ("そうか、わかった。", "そうだ、分かった！"),
    ("あいうえおかきくけこ", "あいXえおかきYけこZ"),
    ("今日はいい天気ですね。", "今日はいい天気ね"),
    ("ｶﾞｷ", "ガキだ"),
    ("㍻元年です。", "平静元年です"),
    ("", "こんにちは"),
    ("こんにちは。", ""),
    ("abcdef", "azcdyf"),
    ("ab", "ba"),
    ("", ""),
]


class FakeScorer:
    """按文本查表给分（缺省 0.0，空串恒 0.0），记录每次调用的批。"""

    def __init__(self, scores: dict[str, float] | None = None):
        self.scores = scores or {}
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[float]:
        self.calls.append(list(texts))
        return [0.0 if not text else self.scores.get(text, 0.0) for text in texts]


def judge(raw_w: str, raw_x: str, scorer: FakeScorer, max_batch: int = 16) -> J.WindowJudgement:
    return J.judge_window(raw_w, raw_x, scorer, margin=MARGIN, max_batch=max_batch)


class IntervalTests(unittest.TestCase):
    def test_kinds_and_indices(self):
        intervals = J.disagreement_intervals("あいうえお", "あXうえおか")
        self.assertEqual([(it.w_start, it.w_end, it.x_start, it.x_end, it.w, it.x, it.kind) for it in intervals],
                         [(1, 2, 1, 2, "い", "X", "substitution"), (5, 5, 5, 6, "", "か", "x0_extra")])
        self.assertEqual([it.kind for it in J.disagreement_intervals("あいう", "あう")], ["w0_extra"])

    def test_adjacent_edits_form_one_interval(self):
        self.assertEqual([(it.w, it.x) for it in J.disagreement_intervals("あいうえ", "あXYえ")], [("いう", "XY")])

    def test_compose(self):
        w, x = "あいうえおか", "あXうえYか"
        intervals = J.disagreement_intervals(w, x)
        self.assertEqual(J.compose(w, intervals, [True, False]), "あXうえおか")
        self.assertEqual(J.compose(w, intervals, [True, True]), x)
        self.assertEqual(J.compose(w, intervals, [False, False]), w)


class HypothesisTests(unittest.TestCase):
    def test_raw_form_keeps_w0_punctuation(self):
        intervals, hyp_w, hyp_xs, form = J.hypotheses("そうか、わかった。", "そうだ、分かった！")
        self.assertEqual(form, "raw")
        self.assertEqual(hyp_w, "そうか、わかった。")
        self.assertEqual([(it.w, it.x) for it in intervals], [("かわ", "だ分")])
        self.assertEqual(hyp_xs, ["そうだ、分かった。"])

    def test_insertion_at_end_goes_before_w0_final_punctuation(self):
        _, _, hyp_xs, form = J.hypotheses("わかった。", "わかったよ")
        self.assertEqual((form, hyp_xs), ("raw", ["わかったよ。"]))

    def test_mapping_failure_falls_back_to_normalized_for_all_hypotheses(self):
        # ㍻ 一个原文字符展开为"平成"两个规范化字符，只替换"成"无法映射回原文。
        intervals, hyp_w, hyp_xs, form = J.hypotheses("㍻元年です。いい", "平静元年です。いや")
        self.assertEqual(form, "normalized")
        self.assertEqual(hyp_w, "平成元年ですいい")
        self.assertEqual([(it.w, it.x) for it in intervals], [("成", "静"), ("い", "や")])
        self.assertEqual(hyp_xs, ["平静元年ですいい", "平成元年ですいや"])

    def test_halfwidth_voicing_cluster_maps(self):
        _, hyp_w, hyp_xs, form = J.hypotheses("ｶﾞｷ", "ガキだ")
        self.assertEqual((form, hyp_w, hyp_xs), ("raw", "ｶﾞｷ", ["ｶﾞｷだ"]))

    def test_empty_w0(self):
        intervals, hyp_w, hyp_xs, form = J.hypotheses("", "こんにちは。")
        self.assertEqual([it.kind for it in intervals], ["x0_extra"])
        self.assertEqual((form, hyp_w, hyp_xs), ("raw", "", ["こんにちは"]))

    def test_empty_x0(self):
        intervals, hyp_w, hyp_xs, form = J.hypotheses("こんにちは。", "")
        self.assertEqual([it.kind for it in intervals], ["w0_extra"])
        self.assertEqual((form, hyp_w, hyp_xs), ("raw", "こんにちは。", ["。"]))


class DecideTests(unittest.TestCase):
    def test_margin_boundary_keeps_w0(self):
        self.assertFalse(J.decide(-1.0, margin=-1.0))
        self.assertTrue(J.decide(-0.999, margin=-1.0))
        self.assertFalse(J.decide(-1.001, margin=-1.0))
        self.assertFalse(J.decide(float("nan"), margin=-1.0))

    def test_window_margin_boundary(self):
        raw_w, raw_x = "そうか。", "そうだ。"
        at = judge(raw_w, raw_x, FakeScorer({raw_w: -5.0, raw_x: -6.0}))
        self.assertEqual((at.text, at.intervals[0]["d"], at.intervals[0]["switched"]), (raw_w, -1.0, False))
        above = judge(raw_w, raw_x, FakeScorer({raw_w: -5.0, raw_x: -5.5}))
        self.assertEqual((above.text, above.intervals[0]["switched"]), (raw_x, True))


class JudgeWindowTests(unittest.TestCase):
    def test_identical_after_normalization_is_not_scored(self):
        scorer = FakeScorer()
        result = judge("そうか、わかった。", "そうか わかった！", scorer)
        self.assertEqual(result, J.WindowJudgement("そうか、わかった。", True, "unscored", (), None))
        self.assertEqual(scorer.calls, [])

    def test_both_empty_is_identical(self):
        scorer = FakeScorer()
        result = judge("", "", scorer)
        self.assertTrue(result.identical)
        self.assertEqual((result.text, scorer.calls), ("", []))

    def test_single_interval_record(self):
        scorer = FakeScorer({"そうか。": -3.0, "そうだ。": -2.5})
        result = judge("そうか。", "そうだ。", scorer)
        self.assertEqual(scorer.calls, [["そうか。", "そうだ。"]])
        self.assertEqual((result.text, result.text_form, result.guard, result.identical),
                         ("そうだ。", "raw", None, False))
        self.assertEqual(result.intervals, ({"w": "か", "x": "だ", "kind": "substitution", "score_w": -3.0,
                                             "score_x": -2.5, "d": 0.5, "switched": True},))

    def test_empty_w0_scores_empty_hypothesis_through_scorer(self):
        scorer = FakeScorer({"はい": -0.5})
        result = judge("", "はい。", scorer)
        self.assertEqual(scorer.calls, [["", "はい"]])
        self.assertEqual((result.text, result.intervals[0]["kind"], result.intervals[0]["d"]), ("はい", "x0_extra", -0.5))

    def test_multiple_flips_compose_in_raw_form(self):
        raw_w, raw_x = "あい、うえおか、きくけこ。", "あX、うえおかY、きくZこ！"
        _, _, hyp_xs, form = J.hypotheses(raw_w, raw_x)
        self.assertEqual(form, "raw")
        self.assertEqual(hyp_xs, ["あX、うえおか、きくけこ。", "あい、うえおか、Yきくけこ。", "あい、うえおか、きくZこ。"])
        # 插入点落在下一个规范化字符之前（w0 的"、"之后），同研究 raw_span。
        # 接受第 1、3 个区间，拒绝第 2 个；各自独立判定后一起应用。
        scorer = FakeScorer({raw_w: -10.0, hyp_xs[0]: -9.0, hyp_xs[1]: -12.0, hyp_xs[2]: -10.5})
        result = judge(raw_w, raw_x, scorer)
        self.assertEqual([r["switched"] for r in result.intervals], [True, False, True])
        self.assertEqual(result.text, "あX、うえおか、きくZこ。")
        intervals = J.disagreement_intervals(J.normalize(raw_w).text, J.normalize(raw_x).text)
        self.assertEqual(J.normalize(result.text).text,
                         J.compose(J.normalize(raw_w).text, intervals, [True, False, True]))

    def test_all_flips_in_raw_form_reach_x0_content(self):
        raw_w, raw_x = "あいうえおかきくけこ", "あいXえおかきYけこZ"
        result = judge(raw_w, raw_x, FakeScorer({raw_w: -100.0}))
        self.assertEqual(result.text, raw_x)

    def test_normalized_form_merge_and_no_flip_keeps_raw_w0(self):
        raw_w, raw_x = "㍻元年です。いい", "平静元年です。いや"
        flipped = judge(raw_w, raw_x, FakeScorer({"平成元年ですいい": -10.0}))
        self.assertEqual((flipped.text_form, flipped.text), ("normalized", "平静元年ですいや"))
        kept = judge(raw_w, raw_x, FakeScorer({"平静元年ですいい": -10.0, "平成元年ですいや": -10.0}))
        self.assertEqual((kept.text_form, kept.text), ("normalized", raw_w))
        self.assertEqual([r["switched"] for r in kept.intervals], [False, False])

    def test_batches_hyp_w_scored_once_in_first_chunk(self):
        raw_w = "あいうえおかきくけこさしすせそ"  # 15 字；x0 隔字替换 → 8 个区间
        raw_x = "".join("X" if k % 2 == 0 else ch for k, ch in enumerate(raw_w))
        intervals, hyp_w, hyp_xs, _ = J.hypotheses(raw_w, raw_x)
        self.assertEqual(len(intervals), 8)
        scorer = FakeScorer()
        result = judge(raw_w, raw_x, scorer, max_batch=3)
        self.assertEqual(scorer.calls, [[hyp_w, *hyp_xs[:2]], hyp_xs[2:5], hyp_xs[5:8]])
        self.assertEqual(sum(batch.count(hyp_w) for batch in scorer.calls), 1)
        self.assertEqual(len(result.intervals), 8)
        exact = FakeScorer()
        judge(raw_w, raw_x, exact, max_batch=9)
        self.assertEqual(exact.calls, [[hyp_w, *hyp_xs]])

    def test_score_count_mismatch_raises(self):
        with self.assertRaises(ValueError):
            judge("そうか。", "そうだ。", lambda texts: [0.0])

    def test_empty_result_guard(self):
        raw_w = "こんにちは。"
        result = judge(raw_w, "", FakeScorer({raw_w: -50.0}))
        self.assertEqual((result.text, result.guard, result.text_form), (raw_w, "empty_result", "raw"))
        self.assertEqual(result.intervals[0]["d"], 50.0)
        self.assertFalse(result.intervals[0]["switched"])

    def test_empty_x0_kept_when_w0_preferred(self):
        raw_w = "こんにちは。"
        result = judge(raw_w, "", FakeScorer({raw_w: 2.0}))
        self.assertEqual((result.text, result.guard), (raw_w, None))

    def test_unnormalizable_text_keeps_w0(self):
        # 朝鲜文字母 L＋V 跨簇组合，normalize 拒绝映射。
        scorer = FakeScorer()
        result = judge("가", "가나", scorer)
        self.assertEqual(result, J.WindowJudgement("가", False, "unscored", (), "normalize_failed"))
        self.assertEqual(scorer.calls, [])


class SummarizeTests(unittest.TestCase):
    def test_counts(self):
        judgements = [
            judge("そうか。", "そうか！", FakeScorer()),                              # 相同
            judge("そうか。", "そうだ。", FakeScorer({"そうか。": -3.0})),             # 替换，翻转
            judge("あいうえ", "あいうえお", FakeScorer({"あいうえ": 1.0})),           # x0 多出，不翻转
            judge("こんにちは。", "", FakeScorer({"こんにちは。": -50.0})),           # 守卫
            judge("㍻元年です。いい", "平静元年です。いや", FakeScorer({"平成元年ですいい": -10.0})),  # normalized
            judge("가", "가", FakeScorer()),                               # 无法规范化
        ]
        self.assertEqual(J.summarize(judgements), {
            "windows": 6, "identical": 1, "scored": 4, "normalized_form": 1, "intervals": 5, "switched": 3,
            "guards": {"empty_result": 1, "normalize_failed": 1},
            "by_kind": {"substitution": {"switched": 3, "total": 3}, "w0_extra": {"switched": 0, "total": 1},
                        "x0_extra": {"switched": 0, "total": 1}}})

    def test_empty(self):
        self.assertEqual(J.summarize([])["windows"], 0)


class ResearchEquivalenceTests(unittest.TestCase):
    """与研究脚本逐项对照；研究模块只在此导入，产品模块不导入。"""

    def test_align_intervals_compose_match_oracle(self):
        from experiments.quality_v5 import asr_pair_oracle as o

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
        from experiments.quality_v5 import asr_pair_cross_score as cs
        from experiments.quality_v5 import asr_pair_ctc_judge as c
        from kototoki_eval.schema import normalize as eval_normalize

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


class ImportBoundaryTests(unittest.TestCase):
    def test_judge_is_base_layer(self):
        code = (
            "import sys, kototoki.judge\n"
            "banned = {'torch', 'ctranslate2', 'faster_whisper', 'transformers', 'kototoki_eval', 'experiments'}\n"
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in banned)\n"
            "print(bad)\n"
            "sys.exit(1 if bad else 0)\n")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
