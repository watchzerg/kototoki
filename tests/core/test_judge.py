"""kototoki.judge 的离线测试：分歧区间与合并、raw／normalized 假设、判定边界、空结果守卫、x0 清洗，
以及整文件裁判 `judge_file` 的逐窗决策。"""

from __future__ import annotations

import unittest

from kototoki import judge as J

MARGIN = -1.0

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

    def test_mapping_failure_falls_back_to_normalized_for_all_hypotheses(self):
        # ㍻ 一个原文字符展开为"平成"两个规范化字符，只替换"成"无法映射回原文。
        intervals, hyp_w, hyp_xs, form = J.hypotheses("㍻元年です。いい", "平静元年です。いや")
        self.assertEqual(form, "normalized")
        self.assertEqual(hyp_w, "平成元年ですいい")
        self.assertEqual([(it.w, it.x) for it in intervals], [("成", "静"), ("い", "や")])
        self.assertEqual(hyp_xs, ["平静元年ですいい", "平成元年ですいや"])



class DecideTests(unittest.TestCase):
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

    def test_single_interval_record(self):
        scorer = FakeScorer({"そうか。": -3.0, "そうだ。": -2.5})
        result = judge("そうか。", "そうだ。", scorer)
        self.assertEqual(scorer.calls, [["そうか。", "そうだ。"]])
        self.assertEqual((result.text, result.text_form, result.guard, result.identical),
                         ("そうだ。", "raw", None, False))
        self.assertEqual(result.intervals, ({"w": "か", "x": "だ", "kind": "substitution", "score_w": -3.0,
                                             "score_x": -2.5, "d": 0.5, "switched": True},))

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

    def test_empty_result_guard(self):
        raw_w = "こんにちは。"
        result = judge(raw_w, "", FakeScorer({raw_w: -50.0}))
        self.assertEqual((result.text, result.guard, result.text_form), (raw_w, "empty_result", "raw"))
        self.assertEqual(result.intervals[0]["d"], 50.0)
        self.assertFalse(result.intervals[0]["switched"])



class CleanX0Tests(unittest.TestCase):
    def test_drops_whitespace_next_to_non_ascii(self):
        self.assertEqual(J.clean_x0(" げん き 、OK  Google\nです "), "げんき、OK Googleです")
        self.assertEqual(J.clean_x0("a \t b"), "a b")
        self.assertEqual(J.clean_x0(""), "")


class JudgeFileTests(unittest.TestCase):
    """整文件裁判的逐窗决策规则，直接给文本、失败窗口与打分回调，不经 worker 伪对象。"""

    def judge_file(self, texts_w, texts_x, failed_w=(), failed_x=(), scores=None, errors=()):
        self.calls, self.errors = [], []

        def score_for(index):
            def score(texts):
                self.calls.append((index, list(texts)))
                if index in errors:
                    raise RuntimeError("scorer broke")
                return [0.0 if not text else (scores or {}).get(text, -10.0) for text in texts]
            return score
        return J.judge_file(texts_w, texts_x, set(failed_w), set(failed_x), score_for, margin=MARGIN, max_batch=16,
                            on_score_error=lambda index, error: self.errors.append((index, type(error).__name__)))

    def test_decisions_and_counts(self):
        # 0 相同；1 分歧并切换（x0 空白先清理）；2 w0 失败；3 x0 失败；4 打分出错；5 分歧但保持 w0
        result = self.judge_file(["そう。", "元気？", "失敗", "はい", "秘密", "そうか。"],
                                 ["そう", "げん き？", "x", "", "ひみつ", "そうだ。"],
                                 failed_w={2}, failed_x={3}, errors={4}, scores={"げんき？": -9.5, "そうか。": 0.0})
        self.assertEqual([r["decision"] for r in result.records],
                         ["identical", "judged", "w0_failed", "x0_failed", "score_error", "judged"])
        self.assertEqual(result.texts, ["そう。", "げんき？", "失敗", "はい", "秘密", "そうか。"])
        self.assertEqual(self.errors, [(4, "RuntimeError")])
        self.assertEqual([index for index, _ in self.calls], [1, 4, 5])  # 相同与失败窗口不打分
        self.assertEqual(self.calls[0], (1, ["元気？", "げんき？"]))
        self.assertEqual({k: result.summary[k] for k in ("windows", "identical", "scored", "intervals", "switched",
                                                         "w0_failed", "x0_failed", "score_error")},
                         {"windows": 6, "identical": 1, "scored": 2, "intervals": 2, "switched": 1,
                          "w0_failed": 1, "x0_failed": 1, "score_error": 1})
        self.assertEqual(list(result.summary)[:1], ["windows"])


if __name__ == "__main__":
    unittest.main()
