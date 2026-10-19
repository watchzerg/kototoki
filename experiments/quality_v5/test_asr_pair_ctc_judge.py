import itertools
import math
import unittest

import numpy as np

from experiments.quality_v5 import asr_pair_ctc_judge as j
from experiments.quality_v5 import asr_pair_oracle as o


def emission(t, c, seed=0):
    rng = np.random.default_rng(seed)
    logits = rng.normal(size=(t, c))
    return (logits - np.log(np.exp(logits).sum(axis=1, keepdims=True))).astype(np.float32)


def collapse(path):
    out, previous = [], None
    for label in path:
        if label != previous and label != j.BLANK:
            out.append(label)
        previous = label
    return out


def brute(matrix, ids):
    """枚举全部路径：(对数和概率, 最优单路径对数概率)。matrix 的列号即 id。"""
    total, best = 0.0, -math.inf
    for path in itertools.product(range(matrix.shape[1]), repeat=len(matrix)):
        if collapse(path) == ids:
            score = float(sum(matrix[t, k] for t, k in enumerate(path)))
            total += math.exp(score)
            best = max(best, score)
    return (math.log(total) if total else -math.inf), best


class CtcScoreTest(unittest.TestCase):
    def test_forward_matches_enumeration(self):
        e = emission(5, 4)
        for ids in ([1, 2], [1, 1], [3], [2, 1, 3]):
            want, _ = brute(e.astype(np.float64), ids)
            self.assertAlmostEqual(j.ctc_loglik(e, ids), want, places=5)

    def test_viterbi_matches_best_path(self):
        e = emission(5, 4, seed=1)
        for ids in ([1, 2], [1, 1], [3, 2]):
            _, want = brute(e.astype(np.float64), ids)
            self.assertAlmostEqual(j.viterbi_score(e, ids), want, places=4)

    def test_empty_and_infeasible(self):
        e = emission(3, 4)
        self.assertAlmostEqual(j.ctc_loglik(e, []), float(e[:, 0].astype(np.float64).sum()), places=6)
        self.assertEqual(j.viterbi_score(e, []), j.ctc_loglik(e, []))
        self.assertEqual(j.frames_needed([1, 1, 2]), 4)
        self.assertEqual(j.ctc_loglik(e, [1, 1, 2]), -math.inf)
        self.assertEqual(j.viterbi_score(e, [1, 1, 2]), -math.inf)

    def test_oov_uses_constant_column_not_wildcard(self):
        e = emission(4, 3, seed=2)
        augmented = np.concatenate([e, np.full((4, 1), j.OOV_LOGPROB, dtype=np.float32)], axis=1)
        want, _ = brute(augmented.astype(np.float64), [1, 3])
        self.assertAlmostEqual(j.ctc_loglik(e, [1, j.PENALTY_ID]), want, places=5)
        # 通配列（非 blank 最大值）会给出更高的似然；常数列不会白给概率
        wildcard = np.concatenate([e, e[:, 1:].max(axis=1, keepdims=True)], axis=1)
        free, _ = brute(wildcard.astype(np.float64), [1, 3])
        self.assertGreater(free, want)

    def test_target_ids_and_oov(self):
        dictionary = {"a": 1, "あ": 2}
        self.assertEqual(j.target_ids("Aあ漢", dictionary), [1, 2, j.PENALTY_ID])
        self.assertTrue(j.has_oov("あ漢", dictionary))
        self.assertFalse(j.has_oov("aあ", dictionary))


class DecisionTest(unittest.TestCase):
    def test_hypothesis_x(self):
        w0, x0 = "あいうえお", "あいかきえお"
        [it] = o.disagreement_intervals(w0, x0)
        self.assertEqual(j.hypothesis_x(w0, it), x0)
        [it] = o.disagreement_intervals("あいう", "")
        self.assertEqual(j.hypothesis_x("あいう", it), "")
        [it] = o.disagreement_intervals("", "かき")
        self.assertEqual(j.hypothesis_x("", it), "かき")

    def test_decide(self):
        self.assertTrue(j.decide(3.0, 0, 0.0, 2.0))
        self.assertFalse(j.decide(2.0, 0, 0.0, 2.0))  # 恰好等于阈值保持 w0
        self.assertTrue(j.decide(-1.0, 2, -1.0, 0.0))  # 长度奖励：x 长 2 字，阈值降到 −2
        self.assertTrue(j.decide(math.inf, 0, 0.0, 100.0))
        self.assertFalse(j.decide(-math.inf, 0, 0.0, -100.0))
        self.assertFalse(j.decide(math.nan, 0, 0.0, -100.0))

    def test_buckets_and_kana(self):
        self.assertEqual(j.length_bucket({"w": "あ", "x": ""}), "1")
        self.assertEqual(j.length_bucket({"w": "あい", "x": "う"}), "2")
        self.assertEqual(j.length_bucket({"w": "あいうえ", "x": ""}), "3–5")
        self.assertEqual(j.length_bucket({"w": "あいうえおか", "x": ""}), "6+")
        self.assertTrue(j.same_kana_reading("さくら", "サクラ"))
        self.assertFalse(j.same_kana_reading("桜", "さくら"))
        self.assertFalse(j.same_kana_reading("", "う"))


def unit(uid, ref, w0, x0):
    return o.Unit(uid, 0.0, 1.0, {"ref": [], "w0": [], "x0": []}, {"ref": ref, "w0": w0, "x0": x0})


def rows_for(units, d_values):
    rows, n = [], 0
    for u in units:
        for k, it in enumerate(o.disagreement_intervals(u.texts["w0"], u.texts["x0"])):
            rows.append({"unit_id": u.unit_id, "interval": k, "_interval": it, "d": d_values[n],
                         "dlen": len(it["x"]) - len(it["w"]), "scorable": True})
            n += 1
    return rows


class TuneTest(unittest.TestCase):
    def setUp(self):
        # u1：x0 对（替换）；u2：w0 对（替换）；u3：无分歧
        self.units = [unit("u1", "あいう", "あえう", "あいう"), unit("u2", "かき", "かき", "かく"),
                      unit("u3", "さ", "さ", "さ")]

    def test_evaluator_totals_and_marginal(self):
        rows = rows_for(self.units, [5.0, -5.0])
        ev = j.FilmEvaluator(self.units, rows)
        self.assertEqual(o.edits(ev.total([False, False])), 1)
        self.assertEqual(o.edits(ev.total([True, False])), 0)
        self.assertEqual(o.edits(ev.total([True, True])), 1)
        self.assertEqual([ev.marginal(0), ev.marginal(1)], [-1, 1])
        self.assertEqual(ev.ref_chars, 6)

    def test_tune_finds_separating_margin(self):
        rows = rows_for(self.units, [5.0, -5.0])
        best = j.tune(rows, j.FilmEvaluator(self.units, rows), lambdas=[0.0], margins=[-10.0, 0.0, 10.0])
        self.assertEqual((best["edits"], best["changes"], best["margin"]), (0, 1, 0.0))

    def test_tune_prefers_fewer_changes_on_tie(self):
        units = [unit("u1", "あいう", "あえう", "あおう")]  # 两路都错一字，换不换一样
        rows = rows_for(units, [5.0])
        best = j.tune(rows, j.FilmEvaluator(units, rows), lambdas=[0.0], margins=[0.0, 10.0])
        self.assertEqual((best["changes"], best["margin"]), (0, 10.0))

    def test_unscorable_rows_stay_w0(self):
        rows = rows_for(self.units, [5.0, -5.0])
        rows[0]["scorable"] = False
        self.assertEqual(j.picks_for(rows, 0.0, -10.0), [False, True])
        self.assertEqual(j.picks_for(rows, 0.0, 0.0, use_acoustic=False), [False, False])

    def test_accuracy_and_changes(self):
        rows = [{"oracle_pick": "x0", "marginal": -1, "kind": "a"}, {"oracle_pick": "w0", "marginal": 0, "kind": "a"},
                {"oracle_pick": "w0", "marginal": 2, "kind": "b"}]
        table = j.accuracy_table(rows, [True, True, False], lambda r: r["kind"])
        self.assertEqual((table["a"]["correct"], table["a"]["always_w0_correct"], table["b"]["correct"]), (1, 1, 1))
        changes = j.change_breakdown(rows, [True, True, True])
        self.assertEqual((changes["oracle_x0"], changes["marginal_better"], changes["marginal_neutral"],
                          changes["marginal_worse"], changes["marginal_sum"]), (1, 1, 1, 1, 1))


class DropTest(unittest.TestCase):
    def items(self):
        rows = [("", "ありがとう", -5.0, "insertion"), ("あい", "あい", -0.5, "exact"),
                ("かきく", "かき", -2.0, "other"), ("", "ふ", -4.0, "insertion")]
        out = []
        for ref, hyp, value, label in rows:
            keep, drop = j.drop_edits(ref, hyp)
            out.append({"ref": ref, "label": label, "f": value, "keep": keep, "drop": drop})
        return out

    def test_threshold_minimizes_edits(self):
        items = self.items()
        best = j.tune_drop_threshold(items, "f")
        # 丢两个插入单元（−6 编辑）；再丢 "かき"（参考 3 字，保留时 1 编辑）会 +2
        self.assertEqual((best["dropped"], best["keep_edits"], best["edits"]), (2, 7, 1))
        self.assertAlmostEqual(best["threshold"], -3.0)
        applied = j.apply_drop(items, "f", best["threshold"])
        self.assertEqual((applied["dropped"], applied["precision"], applied["recall"]), (2, 1.0, 1.0))
        self.assertEqual(o.edits(applied["sdi"]), 1)

    def test_no_drop_threshold(self):
        items = [it for it in self.items() if it["label"] != "insertion"]
        self.assertEqual(j.tune_drop_threshold(items, "f")["threshold"], -math.inf)

    def test_auc(self):
        self.assertEqual(j.auc_lower_is_positive([1, 2], [3, 4]), 1.0)
        self.assertEqual(j.auc_lower_is_positive([3], [3]), 0.5)
        self.assertIsNone(j.auc_lower_is_positive([], [1]))


class SpanTest(unittest.TestCase):
    def test_span_pad_and_clamp(self):
        cues = [{"start": 0.1, "end": 1.0}, {"start": 2.0, "end": 3.0}]
        self.assertEqual(j.span_samples(cues, 0.2, 16000 * 10), (0, int(3.2 * 16000)))
        self.assertEqual(j.span_samples(cues, 0.2, 16000 * 3), (0, 48000))

    def test_plan_shares_identical_spans(self):
        tracks = {"ref": [{"start": 0, "end": 1, "text": "あい"}],
                  "w0": [{"start": 0, "end": 1, "text": "あえ"}],
                  "x0": [{"start": 0, "end": 1, "text": "あい"}]}
        units = o.build_units("t", tracks)
        plan = j.plan_spans(tracks, units, 16000 * 5)
        self.assertEqual(plan["A"], plan["B"])
        self.assertEqual(plan["A"]["t-u0001"], "0-19200")


if __name__ == "__main__":
    unittest.main()
