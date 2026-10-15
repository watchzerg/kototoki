import json
import tempfile
import unittest
from pathlib import Path

from experiments.quality_v5 import asr_source as a


def cue(start, end, text):
    return {"index": 0, "start": start, "end": end, "text": text}


class UnitsTest(unittest.TestCase):
    def test_overlap_components(self):
        reference = [cue(0, 2, "あ"), cue(2.5, 4, "い"), cue(10, 11, "う")]
        product = [cue(0.5, 3, "x"), cue(3.5, 4.5, "y"), cue(20, 21, "z")]
        units = a.overlap_units(reference, product)
        self.assertEqual(units, [([0, 1], [0, 1]), ([2], []), ([], [2])])

    def test_touching_intervals_do_not_overlap(self):
        self.assertEqual(a.overlap_units([cue(0, 1, "あ")], [cue(1, 2, "x")]), [([0], []), ([], [0])])

    def test_cer_ignores_punctuation_and_width(self):
        self.assertEqual(a.cer("こんにちは、世界！", "こんにちは世界"), 0)
        self.assertAlmostEqual(a.cer("あいうえ", "あいう"), 0.25)
        self.assertIsNone(a.cer("……", "あ"))

    def test_buckets(self):
        self.assertEqual(a.bucket_of("……", "あ", None), "inserted")
        self.assertEqual(a.bucket_of("あ", "", None), "missed")
        self.assertEqual(a.bucket_of("あい", "あい", 0), "exact")
        self.assertEqual(a.bucket_of("あいうえ", "あいう", 0.25), "light")
        self.assertEqual(a.bucket_of("あいうえ", "か", 1.0), "heavy")

    def test_build_units_joins_texts_per_seed(self):
        reference = [cue(0, 2, "あい"), cue(2.5, 4, "うえ")]
        product = [cue(0.5, 3.5, "あいうえ")]
        clean = [[cue(0, 2, "甲"), cue(2.5, 4, "乙")], [cue(0, 2, "甲2"), cue(2.5, 4, "乙2")]]
        asr = [[cue(0.5, 3.5, "甲乙")], [cue(0.5, 3.5, "甲乙2")]]
        [unit] = a.build_units("f", reference, product, clean, asr)
        self.assertEqual((unit.ref_ja, unit.asr_ja, unit.bucket), ("あいうえ", "あいうえ", "exact"))
        self.assertEqual(unit.clean_zh, ["甲 乙", "甲2 乙2"])
        self.assertEqual(unit.asr_zh, ["甲乙", "甲乙2"])
        with self.assertRaises(ValueError):
            a.build_units("f", reference, product, [clean[0][:1]], asr)


def units_fixture():
    units = []
    for i, bucket in enumerate(["exact", "light", "heavy", "missed", "inserted"] * 4):
        units.append({"film": "f", "bucket": bucket, "ref_ja": f"日{i}", "clean_zh": [f"c{i}a", f"c{i}b", f"c{i}c"],
                      "asr_zh": [f"a{i}a", f"a{i}b", f"a{i}c"]})
    return {"f": units}


class PlanTest(unittest.TestCase):
    def test_plan_arms_and_blinding(self):
        units = units_fixture()
        items = a.plan_items(units, {"exact": 2, "light": 2, "heavy": 2, "missed": 2, "calib-same": 3,
                                     "calib-seed": 3, "calib-repeat": 2}, seed=1)
        arms = [i["arm"] for i in items]
        self.assertEqual(arms.count("main"), 8)
        self.assertEqual(arms.count("calib-same"), 3)
        self.assertEqual(arms.count("calib-repeat"), 2)
        self.assertEqual(len({i["id"] for i in items}), len(items))
        for item in items:
            x_text = item["a"] if item["x_side"] == "A" else item["b"]
            self.assertEqual(x_text, item["x"])
            if item["arm"] == "main":
                self.assertTrue(item["x"].startswith("c") and item["y"].startswith("a"))
            if item["arm"] == "calib-same":
                self.assertEqual(item["a"], item["b"])
            if item["arm"] == "calib-repeat":
                original = next(i for i in items if i["id"] == item["repeat_of"])
                self.assertEqual((item["a"], item["b"]), (original["a"], original["b"]))
            self.assertNotEqual(item["bucket"], "inserted")

    def test_prompt_marks_empty_candidate(self):
        units = units_fixture()
        item = {"id": "q0001", "film": "f", "unit": 3, "a": "", "b": "中文"}
        prompt = a.packet_prompt([item], units)
        self.assertIn("A：（空）", prompt)
        self.assertIn("日文原文：日3", prompt)


class EstimateTest(unittest.TestCase):
    def test_collect_maps_sides_and_penalties(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plan = {"items": [{"id": "q1", "arm": "main", "bucket": "heavy", "film": "f", "unit": 0,
                               "seed_index": 0, "x_side": "B"}]}
            (folder / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            result = {"items": [{"id": "q1", "preference": "B",
                                 "errors_a": [{"category": "mistranslation", "severity": "major", "note": ""}],
                                 "errors_b": []}]}
            (folder / "packet-001.json").write_text(json.dumps({"result": result}), encoding="utf-8")
            [row] = a.collect(folder / "plan.json", folder)
        self.assertEqual((row["px"], row["py"], row["winner"]), (0, 5, "x"))

    def test_ratio_weights_buckets_by_unit_count(self):
        rows = {"exact": [{"px": 1, "py": 1}], "heavy": [{"px": 1, "py": 5}]}
        # 总惩罚 10·1 + 2·5 = 20，ASR 多出 2·4 = 8
        self.assertAlmostEqual(a.ratio(rows, {"exact": 10, "heavy": 2}, ("exact", "heavy")), 0.4)
        self.assertAlmostEqual(a.ratio(rows, {"exact": 10, "heavy": 2}, ("heavy",)), 0.4)

    def test_calibration_repeat_agreement(self):
        rows = [{"id": "q1", "arm": "main", "winner": "x", "px": 0, "py": 5, "repeat_of": None},
                {"id": "q2", "arm": "calib-repeat", "winner": "x", "px": 0, "py": 1, "repeat_of": "q1"},
                {"id": "q3", "arm": "calib-same", "winner": "tie", "px": 1, "py": 1, "repeat_of": None}]
        calib = a.calibration(rows)
        self.assertEqual(calib["repeat"]["winner_agree"], 1.0)
        self.assertEqual(calib["repeat"]["mean_abs_diff_py"], 4)
        self.assertEqual(calib["same"]["tie"], 1.0)


if __name__ == "__main__":
    unittest.main()
