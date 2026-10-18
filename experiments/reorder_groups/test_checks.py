"""重排率与显示校验器的离线测试（合成场景与合成 run 目录，无 .local 数据、GPU 或模型）。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.data import Cue, Scene

from . import checks


def scene() -> Scene:
    # 两个包（batch_count=3）：c0–c2 停顿 0.2 → 一组；c3 后停顿 2 s，c4 单条……用 joint 配方 + groups
    rows = [("あの", 0.0, 1.0), ("ね", 1.2, 2.0), ("行こう", 2.2, 4.0), ("はい", 6.0, 7.0), ("え", 9.0, 10.0)]
    return Scene("S", tuple(Cue(f"c{i}", t, a, b) for i, (t, a, b) in enumerate(rows)), "W", "anime_series")


RECIPE = R.compose("g3", "joint", batch_count=3, groups={"gap": 1.0})


class HelpersTest(unittest.TestCase):
    def test_zh_len_ignores_punctuation_and_space(self):
        self.assertEqual(checks.zh_len("你好，世界！ OK…"), 6)
        self.assertEqual(checks.zh_len("……"), 0)

    def test_pack_groups(self):
        self.assertEqual(checks.pack_groups(scene(), RECIPE, 1.0), [[("c0", "c1", "c2")], [("c3",), ("c4",)]])
        plain = R.compose("p3", "joint", batch_count=3)
        self.assertEqual(checks.pack_groups(scene(), plain, 0.1), [[("c0",), ("c1",), ("c2",)], [("c3",), ("c4",)]])


class ReorderTest(unittest.TestCase):
    def test_l1_thresholds_and_singles(self):
        packs = [[("a", "b")], [("c", "d")], [("e",)], [("f", "g"), ("h",)]]
        control = {"a": "一二三四", "b": "五六七八", "c": "一二", "d": "三四", "e": "好", "f": "甲", "g": "乙", "h": "是"}
        candidate = dict(control, a="一二三四五六", b="七八",  # 0.5/0.5 -> 0.75/0.25: L1 0.5
                         c="一二！", e="好的", h="是吧")       # c: same length, different text
        result = checks.reorder(packs, control, candidate)
        self.assertEqual(result["multi_groups"], 3)
        self.assertEqual(result["reordered_share"], {"0.1": 1 / 3, "0.2": 1 / 3, "0.3": 1 / 3})
        self.assertAlmostEqual(result["verbatim_different_share"], 2 / 3)
        self.assertEqual(result["single_cues"], {"in_grouped_packs": {"cues": 1, "verbatim_different": 1},
                                                 "in_ungrouped_packs": {"cues": 1, "verbatim_different": 1}})

    def test_missing_translations_are_skipped(self):
        result = checks.reorder([[("a", "b")]], {"a": "x", "b": "y"}, {"a": "x"})
        self.assertEqual((result["multi_groups"], result["skipped_groups"]), (0, 1))
        self.assertIsNone(result["reordered_share"]["0.2"])


class DisplayTest(unittest.TestCase):
    def test_speed_and_share_deviation(self):
        s = scene()
        packs = checks.pack_groups(s, RECIPE, 1.0)
        # c0..c2 时长 1.0/0.8/1.8（占比 0.278/0.222/0.5）；整句塞进 c0 → 字数占比 0.8/0.1/0.1
        translations = {"c0": "一二三四五六七八", "c1": "九", "c2": "十", "c3": "是的", "c4": "诶"}
        result = checks.display([(s, packs)], translations)
        self.assertEqual(result["cues"], 5)
        self.assertEqual(result["multi_groups"], 1)
        self.assertEqual(result["deviation_flagged_share"], 1.0)
        self.assertAlmostEqual(result["over_speed_share"], 0.0)
        result = checks.display([(s, packs)], dict(translations, c0="一二三四五六七八九十"))
        self.assertAlmostEqual(result["over_speed_share"], 1 / 5)  # 10 字/1.0 s > 9
        balanced = {"c0": "一二三", "c1": "四五", "c2": "六七八九十", "c3": "是", "c4": "诶"}
        self.assertEqual(checks.display([(s, packs)], balanced)["deviation_flagged_share"], 0.0)


class AnalyseTest(unittest.TestCase):
    def test_reads_run_directories(self):
        s = scene()
        with tempfile.TemporaryDirectory() as tmp:
            runs = {}
            for arm, c0 in (("control", "一二"), ("candidate", "一二三四五六")):
                folder = Path(tmp) / arm / "scenes"
                folder.mkdir(parents=True)
                translations = {"c0": c0, "c1": "三四", "c2": "五六", "c3": "是", "c4": "诶"}
                (folder / "S.json").write_text(json.dumps({"status": "complete", "cue_ids": s.ids,
                                                           "translations": translations}), encoding="utf-8")
                runs[arm] = folder.parent
            report = checks.analyse([s], RECIPE, 1.0, runs)
        block = report["by_category"]["all"]
        self.assertEqual(block["scenes"], 1)
        self.assertEqual(block["reorder"]["multi_groups"], 1)
        self.assertEqual(block["reorder"]["reordered_share"]["0.3"], 1.0)
        self.assertEqual(set(block["display"]), {"control", "candidate"})
        self.assertIn("anime_series", report["by_category"])


if __name__ == "__main__":
    unittest.main()
