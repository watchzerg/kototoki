import math
import unittest

from experiments.quality_v5 import asr_pair_cross_score as x
from experiments.quality_v5 import asr_pair_ctc_judge as j
from experiments.quality_v5 import asr_pair_oracle as o
from kototoki_eval.schema import normalize


def interval(w0, x0):
    [it] = o.disagreement_intervals(normalize(w0).text, normalize(x0).text)
    return it


class RawTextTest(unittest.TestCase):
    def test_join_raw_drops_spaces_next_to_japanese(self):
        self.assertEqual(x.join_raw(["すぐ さま、", "燃やす。"]), "すぐさま、燃やす。")
        self.assertEqual(x.join_raw(["I am the bone", " of my sword."]), "I am the bone of my sword.")
        self.assertEqual(x.join_raw(["by H. ", "ありがとう"]), "by H.ありがとう")

    def test_substitution_keeps_w0_punctuation(self):
        w0, x0 = "疑心の書を、作っても。", "疑心の種を作っても!"
        self.assertEqual(x.raw_hypothesis(w0, x0, interval(w0, x0)), "疑心の種を、作っても。")

    def test_insertions_at_head_middle_and_end(self):
        w0 = "はい。そう"
        self.assertEqual(x.raw_hypothesis(w0, "あ、はい。そう", interval(w0, "あ、はい。そう")), "あはい。そう")
        self.assertEqual(x.raw_hypothesis(w0, "はい。あ、そう", interval(w0, "はい。あ、そう")), "はい。あそう")
        w1 = "そうだ。"
        self.assertEqual(x.raw_hypothesis(w1, "そうだね!", interval(w1, "そうだね!")), "そうだね。")

    def test_internal_x0_punctuation_is_kept_and_deletion_works(self):
        w0, x0 = "かき", "かあ、いき"
        self.assertEqual(x.raw_hypothesis(w0, x0, interval(w0, x0)), "かあ、いき")
        w1 = "あ…あ、なんだ"
        self.assertEqual(x.raw_hypothesis(w1, "あ、なんだ", interval(w1, "あ、なんだ")), "…あ、なんだ")  # 对齐删掉的是第一个"あ"

    def test_unit_hypotheses_fallback(self):
        tracks = {"ref": [{"start": 0, "end": 1, "text": "あい"}],
                  "w0": [{"start": 0, "end": 1, "text": "あ、え。"}],
                  "x0": [{"start": 0, "end": 1, "text": "あい!"}]}
        [unit] = o.build_units("t", tracks)
        hyps = x.unit_hypotheses(tracks, unit)
        self.assertEqual((hyps["raw"], hyps["norm"], hyps["raw_fallback"]), (["あ、え。", "あ、い。"], ["あえ", "あい"], False))
        unit.texts["w0"] = "かえ"  # 原文与规范化文本不一致 → 整单元回退到规范化文本
        hyps = x.unit_hypotheses(tracks, unit)
        self.assertTrue(hyps["raw_fallback"])
        self.assertEqual(hyps["raw"], hyps["norm"])


class DecisionTest(unittest.TestCase):
    def test_combine_treats_missing_as_zero_unless_all_missing(self):
        values = x.combine({"a": [1.0, math.nan, math.nan], "b": [2.0, 3.0, None]}, {"a": 1.0, "b": 0.5})
        self.assertEqual(values[:2].tolist(), [2.0, 1.5])
        self.assertTrue(math.isnan(values[2]))

    def test_linear_and_agree(self):
        self.assertEqual(x.linear_choose([3.0, 2.0, math.nan, -1.0], [0, 0, 0, 2], -1.0, 2.0).tolist(),
                         [True, False, False, False])
        self.assertEqual(x.linear_choose([-1.0], [2], -1.0, 0.0).tolist(), [True])  # 阈值 −2
        chosen = x.agree_choose([5.0, 5.0, math.nan], [5.0, -5.0, 5.0], [0, 0, 0], 0.0, 0.0, 0.0)
        self.assertEqual(chosen.tolist(), [True, False, False])


def unit(uid, ref, w0, x0):
    return o.Unit(uid, 0.0, 1.0, {"ref": [], "w0": [], "x0": []}, {"ref": ref, "w0": w0, "x0": x0})


def rows_for(units, d_w, d_q, d_m=None):
    rows, n = [], 0
    for u in units:
        for k, it in enumerate(o.disagreement_intervals(u.texts["w0"], u.texts["x0"])):
            rows.append({"unit_id": u.unit_id, "interval": k, "_interval": it, "d_W": d_w[n], "d_Q": d_q[n],
                         "d_M": math.nan if d_m is None else d_m[n], "dlen": len(it["x"]) - len(it["w"])})
            n += 1
    return rows


class TuneTest(unittest.TestCase):
    def setUp(self):
        # u1：x0 对；u2：w0 对；u3：x0 对
        self.units = [unit("u1", "あいう", "あえう", "あいう"), unit("u2", "かき", "かき", "かく"),
                      unit("u3", "さし", "さす", "さし")]

    def test_sum_beats_single_model(self):
        # Whisper 偏自己（全负），Qwen 偏自己（全正），两者之和才分得开
        rows = rows_for(self.units, [-1.0, -0.5, -1.0], [3.0, 1.0, 3.0])
        ev = j.FilmEvaluator(self.units, rows)
        grid = {"lambdas": [0.0], "margins": [-5.0, 0.0, 1.0, 5.0]}
        whisper = x.tune_grid([ev], x.Judge("W", "linear", {"d_W": 1.0}, **grid).candidates([rows]))
        both = x.tune_grid([ev], x.Judge("WQ", "linear", {"d_W": 1.0, "d_Q": 1.0}, **grid).candidates([rows]))
        self.assertEqual(whisper["edits"], 1)
        self.assertEqual((both["edits"], both["changes"], both["params"]["margin"]), (0, 2, 1.0))

    def test_agree_rule_and_tie_break(self):
        rows = rows_for(self.units, [2.0, 2.0, 2.0], [2.0, -2.0, 2.0])
        ev = j.FilmEvaluator(self.units, rows)
        judge = x.Judge("A", "agree", use_length=False, margins=[0.0, 1.0, 3.0])
        best = x.tune_grid([ev], judge.candidates([rows]))
        self.assertEqual((best["edits"], best["changes"]), (0, 2))
        self.assertEqual(best["params"], {"lambda": 0.0, "m_w": 0.0, "m_q": 0.0})  # Σ|参数| 最小者

    def test_mms_weight_is_tuned(self):
        rows = rows_for(self.units, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [4.0, -4.0, math.nan])
        ev = j.FilmEvaluator(self.units, rows)
        judge = x.Judge("3", "linear", {"d_W": 1.0, "d_Q": 1.0}, use_length=False, tune_mms_weight=True,
                        margins=[-1.0, 1.0])
        best = x.tune_grid([ev], judge.candidates([rows]))
        # MMS 缺失的第三行只靠 W＋Q＝0，m＝−1 才会改；第二行 −4w 在任何 w 下都不超过 −1
        self.assertEqual((best["edits"], best["changes"], best["params"]["margin"]), (0, 2, -1.0))
        self.assertEqual(best["params"]["w_mms"], 0.25)  # 平局取 Σ|参数| 最小
        self.assertTrue(x.on_edge(best["params"], judge.grids))

    def test_pooled_tuning_sums_films(self):
        rows = rows_for(self.units, [5.0, -5.0, 5.0], [0.0, 0.0, 0.0])
        ev = j.FilmEvaluator(self.units, rows)
        judge = x.Judge("W", "linear", {"d_W": 1.0}, use_length=False, margins=[0.0])
        self.assertEqual(x.tune_grid([ev, ev], judge.candidates([rows, rows]))["edits"], 0)


class StatsTest(unittest.TestCase):
    def test_preference_counts(self):
        rows = [{"marginal": -1, "d": -2.0}, {"marginal": -1, "d": 1.0}, {"marginal": 1, "d": -1.0},
                {"marginal": 0, "d": 0.0}, {"marginal": 0, "d": math.nan}]
        whisper = x.preference(rows, "d", -1)  # d < 0 ＝ 偏自己（w0）
        self.assertEqual((whisper["x0_better"]["own"], whisper["x0_better"]["other"]), (1, 1))
        self.assertEqual(whisper["w0_better"]["own_share"], 1.0)
        self.assertEqual((whisper["equivalent"]["n"], whisper["equivalent"]["tie"]), (1, 1))
        qwen = x.preference(rows, "d", +1)
        self.assertEqual(qwen["x0_better"]["own"], 1)

    def test_correlations(self):
        self.assertAlmostEqual(x.pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(x.spearman([1, 2, 3, 4], [1, 8, 27, 64]), 1.0)
        self.assertAlmostEqual(x.spearman([1, 2, 3, math.nan], [3, 2, 1, 0]), -1.0)
        self.assertEqual(x.ranks([5, 1, 5]), [1.5, 0.0, 1.5])

    def test_auc_higher_is_x(self):
        rows = [{"marginal": -1, "v": 3.0}, {"marginal": 1, "v": 1.0}, {"marginal": 0, "v": 9.0},
                {"marginal": 1, "v": math.nan}]
        result = x.auc_higher_is_x(rows, lambda r: r["v"])
        self.assertEqual((result["n"], result["n_x_better"], result["auc"]), (2, 1, 1.0))

    def test_shuffle_is_deterministic_permutation(self):
        self.assertEqual(sorted(x.shuffled("あいうえ", 3)), sorted("あいうえ"))
        self.assertEqual(x.shuffled("あいうえ", 3), x.shuffled("あいうえ", 3))


if __name__ == "__main__":
    unittest.main()
