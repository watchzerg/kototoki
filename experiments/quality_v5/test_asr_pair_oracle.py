import unittest

from experiments.quality_v5 import asr_pair_oracle as o
from experiments.quality_v5 import asr_source as a


def cue(start, end, text):
    return {"index": 0, "start": start, "end": end, "text": text}


class ComponentsTest(unittest.TestCase):
    def test_three_tracks_connect(self):
        tracks = {"ref": [cue(0, 2, "あ"), cue(10, 11, "い")],
                  "w0": [cue(1, 3, "x"), cue(20, 21, "z")],
                  "x0": [cue(2.5, 4, "y"), cue(10.5, 12, "w")]}
        units = o.overlap_components(tracks)
        self.assertEqual(units, [{"ref": [0], "w0": [0], "x0": [0]}, {"ref": [1], "w0": [], "x0": [1]},
                                 {"ref": [], "w0": [1], "x0": []}])

    def test_touching_does_not_connect(self):
        units = o.overlap_components({"ref": [cue(0, 1, "あ")], "w0": [cue(1, 2, "い")], "x0": []})
        self.assertEqual(len(units), 2)

    def test_two_tracks_match_asr_source(self):
        reference = [cue(0, 2, "あ"), cue(2.5, 4, "い"), cue(10, 11, "う")]
        product = [cue(0.5, 3, "x"), cue(3.5, 4.5, "y"), cue(20, 21, "z")]
        got = o.overlap_components({"ref": reference, "w0": product})
        want = a.overlap_units(reference, product)
        self.assertEqual([(g["ref"], g["w0"]) for g in got], want)

    def test_same_track_does_not_connect_alone(self):
        units = o.overlap_components({"ref": [], "w0": [cue(0, 2, "a"), cue(1, 3, "b")], "x0": []})
        self.assertEqual(len(units), 2)


class AlignTest(unittest.TestCase):
    def test_sdi_counts_and_distance(self):
        self.assertEqual(o.sdi("あいうえ", "あいうえ"), {"S": 0, "D": 0, "I": 0})
        self.assertEqual(o.sdi("あいうえ", "あいう"), {"S": 0, "D": 1, "I": 0})
        self.assertEqual(o.sdi("あい", "あいう"), {"S": 0, "D": 0, "I": 1})
        self.assertEqual(o.sdi("あいう", "あえう"), {"S": 1, "D": 0, "I": 0})
        for ref, hyp in [("こんにちは世界", "こんばんは世"), ("", "あ"), ("あい", "")]:
            self.assertEqual(o.edits(o.sdi(ref, hyp)), a.edit_distance(ref, hyp))

    def test_correct_reference_chars(self):
        self.assertEqual(o.correct_reference_chars("あいう", "あえう"), [True, False, True])
        self.assertEqual(o.correct_reference_chars("あい", ""), [False, False])


class IntervalsTest(unittest.TestCase):
    def test_substitution_and_gap(self):
        self.assertEqual(o.disagreement_intervals("あいうえお", "あいうえお"), [])
        [it] = o.disagreement_intervals("あいうえお", "あいかえお")
        self.assertEqual((it["w"], it["x"]), ("う", "か"))
        two = o.disagreement_intervals("あいうえお", "かいうえく")
        self.assertEqual([(i["w"], i["x"]) for i in two], [("あ", "か"), ("お", "く")])

    def test_insertion_deletion_and_empty(self):
        [it] = o.disagreement_intervals("あいう", "あいえう")
        self.assertEqual((it["w"], it["x"], o.interval_kind(it)), ("", "え", "x0 多出"))
        [it] = o.disagreement_intervals("あいえう", "あいう")
        self.assertEqual((it["w"], it["x"], o.interval_kind(it)), ("え", "", "w0 多出"))
        [it] = o.disagreement_intervals("あいう", "")
        self.assertEqual((it["w"], it["x"], it["w_start"], it["w_end"]), ("あいう", "", 0, 3))

    def test_compose_roundtrip(self):
        w0, x0 = "こんにちは世界です", "こんばんは世海でした"
        intervals = o.disagreement_intervals(w0, x0)
        self.assertEqual(o.compose(w0, intervals, ["w"] * len(intervals)), w0)
        self.assertEqual(o.compose(w0, intervals, ["x"] * len(intervals)), x0)


class LatticeTest(unittest.TestCase):
    def test_picks_per_interval(self):
        ref, w0, x0 = "あいうえおかきく", "あいうえおかきく".replace("う", "ア"), "あいうえおかきく".replace("き", "キ")
        intervals = o.disagreement_intervals(w0, x0)
        picks = o.lattice_pick(ref, w0, x0, intervals)
        self.assertEqual(o.compose(w0, intervals, picks), ref)

    def test_tie_goes_to_w0(self):
        ref = "あ"
        intervals = o.disagreement_intervals("い", "う")
        self.assertEqual(o.lattice_pick(ref, "い", "う", intervals), ["w"])

    def test_splice_never_worse_than_select_or_singles(self):
        cases = [("今日はいい天気ですね", "今日は良い天気ですよ", "京はいい天気ですね"),
                 ("遠坂凛が来た", "東坂倫が来た", "遠坂凛がきた"),
                 ("", "あ", ""), ("あいう", "", "あいう"), ("ありがとう", "ありがとうございました", "")]
        for ref, w0, x0 in cases:
            intervals = o.disagreement_intervals(w0, x0)
            picks = o.lattice_pick(ref, w0, x0, intervals)
            splice = o.edits(o.sdi(ref, o.compose(w0, intervals, picks)))
            best_single = min(o.edits(o.sdi(ref, w0)), o.edits(o.sdi(ref, x0)))
            self.assertLessEqual(splice, best_single, (ref, w0, x0))

    def test_splice_matches_bruteforce(self):
        ref, w0, x0 = "あいうえおかきくけこ", "あアうえおカきくけコ", "あいうエおかキくけこ"
        intervals = o.disagreement_intervals(w0, x0)
        picks = o.lattice_pick(ref, w0, x0, intervals)
        got = o.edits(o.sdi(ref, o.compose(w0, intervals, picks)))
        best = min(o.edits(o.sdi(ref, o.compose(w0, intervals, [("w", "x")[(mask >> k) & 1] for k in range(len(intervals))])))
                   for mask in range(2 ** len(intervals)))
        self.assertEqual(got, best)


class AnalyzeTest(unittest.TestCase):
    def build(self):
        tracks = {"ref": [cue(0, 2, "遠坂凛です"), cue(5, 6, "セイバー"), cue(10, 11, "ふむ")],
                  "w0": [cue(0, 2, "東坂凛です"), cue(5, 6, "セイバー"), cue(20, 21, "ありがとう")],
                  "x0": [cue(0, 2, "遠坂凛です"), cue(5, 6, "セイマー")]}
        return o.build_units("t", tracks)

    def test_units_and_totals(self):
        units = self.build()
        self.assertEqual([u.texts["ref"] for u in units], ["遠坂凛です", "セイバー", "ふむ", ""])
        result = o.analyze_film("t", units)
        cer = result["cer"]
        self.assertEqual(result["ref_chars"], 5 + 4 + 2)
        self.assertEqual(cer["w0"]["edits"], 1 + 0 + 2 + 5)  # 遠→東；ふむ 缺失；ありがとう 插入
        self.assertEqual(cer["x0"]["edits"], 0 + 1 + 2 + 0)
        self.assertEqual(cer["select"]["edits"], 0 + 0 + 2 + 0)  # 末单元 oracle 选 x0 的空
        self.assertEqual(cer["splice"]["edits"], 2)
        self.assertLessEqual(cer["splice"]["edits"], cer["select"]["edits"])
        self.assertEqual(result["disagreement"]["units"], 3)
        self.assertEqual(result["correlation_units"],
                         {"w0 对／x0 错": 1, "w0 错／x0 对": 1, "w0 错／x0 错": 1})
        self.assertEqual(result["correlation_chars"]["w0 错／x0 错"], 2)  # ふむ 两字两路都没有

    def test_merge_and_sample(self):
        result = o.analyze_film("t", self.build())
        total = o.merge_films([result, result])
        self.assertEqual(total["ref_chars"], 22)
        self.assertEqual(total["cer"]["w0"]["edits"], 16)
        intervals = result["_intervals"]
        self.assertEqual(len(o.sample_intervals(intervals, 30, 1)), len(intervals))
        self.assertEqual(o.sample_intervals(intervals, 2, 1), o.sample_intervals(intervals, 2, 1))


if __name__ == "__main__":
    unittest.main()
