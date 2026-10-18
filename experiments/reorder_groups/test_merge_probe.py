"""票据 07 合并预检的离线测试：合并窗口与渲染、语序判定、标点切回 DP（合成场景，不启动服务器）。"""

from __future__ import annotations

import unittest

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches
from experiments.translation_v3.data import Cue, Scene

from . import merge_probe as M


def scene() -> Scene:
    rows = [("前の行", 0.0, 1.0), ("新聞に書いてあったんだけど", 3.0, 4.0), ("災害前って", 4.2, 5.0),
            ("監視されるらしいよ", 5.2, 7.0), ("そうか。", 9.0, 10.0), ("うん。", 12.0, 13.0), ("後の行", 15.0, 16.0)]
    return Scene("S", tuple(Cue(f"S-c{i}", t, a, b) for i, (t, a, b) in enumerate(rows)), "W", "anime_series")


class MergedWindowTest(unittest.TestCase):
    def test_units_collapse_groups_in_source_order(self):
        folded = M.units(["a", "b", "c", "d"], [["b", "c"]])
        self.assertEqual(folded, [("a", ["a"]), ("b~2", ["b", "c"]), ("d", ["d"])])
        with self.assertRaises(ValueError):
            M.units(["a", "b", "c"], [["c", "a"]])

    def test_render_uses_plain_joint_v1_and_merged_ids(self):
        s = scene()
        recipe = R.load_recipe(M.CONTROL)
        batch = build_batches(s, recipe)[0]
        targets = list(batch.target_ids)
        group = targets[targets.index("S-c1"):targets.index("S-c3") + 1]
        prompt, grammar, ids, folded = M.render(s, batch, [group], recipe)
        self.assertIn(R.JOINT_INSTRUCTION, prompt)
        self.assertNotIn(R.JOINT2_INSTRUCTION, prompt)
        self.assertNotIn(R.GROUPS_INJECTION, prompt)
        self.assertIn("新聞に書いてあったんだけど　災害前って　監視されるらしいよ", prompt)
        self.assertIn('"S-c1~3"', prompt)
        self.assertNotIn('"S-c2"', prompt)
        self.assertEqual(grammar, R.translation_grammar(recipe, ids))
        self.assertEqual([c for _, cues in folded for c in cues], targets)
        self.assertIn("S-c1~3", ids)
        self.assertEqual(R.parse_translation('{"translations": {' + ", ".join(f'"{i}": "译"' for i in ids) + "}}", ids),
                         {i: "译" for i in ids})


class CompareTest(unittest.TestCase):
    def test_order_same_reordered_unmatched(self):
        self.assertEqual(M.order(["报纸上写着", "灾害前", "会被监视"], "报纸上写着，灾害前会被监视。")["verdict"],
                         "same_order")
        self.assertEqual(M.order(["报纸上写着", "灾害前", "会被监视"], "灾害前会被监视，报纸上写着。")["verdict"],
                         "reordered")
        self.assertEqual(M.order(["报纸上写着", "灾害前"], "完全不同的话")["verdict"], "unmatched")

    def test_split_dp_on_punctuation_only(self):
        result = M.split_points("一二三四，五六七八。九十", 2, [2.0, 1.0])
        self.assertTrue(result["splittable"])
        self.assertEqual(result["cuts"], [10])  # 8/10 字对 2/3 时长，偏差 ≈0.133（切在逗号后为 4/10，≈0.267）
        self.assertAlmostEqual(result["deviation"], abs(8 / 10 - 2 / 3))
        self.assertFalse(M.split_points("一二三四五六", 2, [1.0, 1.0])["splittable"])  # 无标点
        bad = M.split_points("一，二三四五六七八九十", 2, [1.0, 1.0])
        self.assertFalse(bad["splittable"])  # 只能 1:9 切，偏差 0.4 > 0.3
        self.assertAlmostEqual(bad["deviation"], 0.4)

    def test_compare_group_fields(self):
        row = M.compare_group(["报纸上写着，", "灾害前"], "报纸上写着灾害前。", [1.0, 1.0])
        self.assertTrue(row["identical_after_strip"])
        self.assertEqual(row["order"]["verdict"], "same_order")
        self.assertEqual(row["control_chars"], row["merged_chars"])
        self.assertFalse(row["split"]["splittable"])  # 合并译文里没有内部标点
        self.assertIsNone(M.compare_group(["甲", "乙"], "甲乙", [1.0, None])["split"])

    def test_compare_rows_with_reference(self):
        row = {"units": [["a~2", ["a", "b"]], ["c", ["c"]]], "durations": {"a": 1.0, "b": 1.0, "c": 1.0},
               "control": {"translations": {"a": "报纸上写着，", "b": "灾害前", "c": "嗯"}},
               "reference": {"a": "报纸上写着，", "b": "灾害前", "c": "嗯"},
               "merged": {"translations": {"a~2": "报纸上写着，灾害前。", "c": "嗯"}}}
        M.compare([row])
        self.assertEqual([g["key"] for g in row["groups"]], ["a~2"])
        self.assertEqual(row["groups"][0]["reference_ratio"], 1.0)
        self.assertTrue(row["groups"][0]["split"]["splittable"])


if __name__ == "__main__":
    unittest.main()
