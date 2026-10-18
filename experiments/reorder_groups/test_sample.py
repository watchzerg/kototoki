"""票据 02 小样驱动的离线测试：挑包准则、三臂渲染与汇总（合成场景，不启动服务器）。"""

from __future__ import annotations

import unittest

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.data import Cue, Scene

from . import sample


def scene(scene_id: str, category: str, rows: list[tuple[str, float, float]]) -> Scene:
    return Scene(scene_id, tuple(Cue(f"{scene_id}-c{i}", t, a, b) for i, (t, a, b) in enumerate(rows)), "W", category)


# 停顿都 <1 s；前三行以接续成分结尾（拆开的一句），后面是一问一答。
SPLIT = [("新聞に書いてあったんだけど", 0.0, 1.0), ("災害前って", 1.2, 2.0), ("ロボットを作って", 2.2, 3.0),
         ("監視されるらしいよ", 3.2, 5.0), ("そうか", 5.5, 6.0), ("うん", 6.3, 7.0)]
# 全是独立短句（句末标点），R2+ 下没有多 cue 组。
PLAIN = [("はい。", 0.0, 1.0), ("いいえ。", 1.2, 2.0), ("行こう！", 2.2, 3.0)]


class RankTest(unittest.TestCase):
    def test_continuation_lines_and_split_criterion(self):
        s = scene("A", "anime_series", SPLIT)
        groups = sample.sentence_groups(s, 0, 6, 1.0)
        self.assertEqual(groups, [(0, 6)])
        self.assertEqual(sample.continuation_lines(s, groups[0]), 4)  # けど・って・て・か；末行不计
        control = R.load_recipe(sample.CONTROL)
        picked = sample.rank_batches([scene("P", "anime_series", PLAIN), s], control, 1.0, 5, "split")
        self.assertEqual([(x.scene_id, b.index) for x, b in picked], [("A", 0)])
        picked = sample.rank_batches([s], control, 1.0, 5, "split", exclude={("A", 0)})
        self.assertEqual(picked, [])

    def test_plan_arms_and_alt_instruction(self):
        v2_before = R.JOINT2_INSTRUCTION
        rows = sample.plan([scene("A", "anime_series", SPLIT)], 1, "covered", alt=True)
        self.assertEqual(len(rows), 1)
        arms = rows[0]["arms"]
        self.assertEqual(set(arms), {sample.CONTROL, sample.CANDIDATE, sample.ALT})
        self.assertIn(R.JOINT_INSTRUCTION, arms[sample.CONTROL]["_prompt"])
        self.assertIn(v2_before, arms[sample.CANDIDATE]["_prompt"])
        self.assertIn(sample.ALT_INSTRUCTION, arms[sample.ALT]["_prompt"])
        self.assertNotIn(v2_before, arms[sample.ALT]["_prompt"])
        self.assertIs(R.JOINT2_INSTRUCTION, v2_before)  # 渲染后全局措辞已还原
        self.assertEqual(arms[sample.CONTROL]["_grammar"], arms[sample.ALT]["_grammar"])
        self.assertEqual(rows[0]["groups"], [[f"A-c{i}" for i in range(6)]])


class SummariseTest(unittest.TestCase):
    def test_reorder_per_arm(self):
        rows = sample.plan([scene("A", "anime_series", SPLIT)], 1, "covered", alt=True)
        ids = rows[0]["target_ids"]
        base = {k: "一二三" for k in ids}
        rows[0]["arms"][sample.CONTROL]["translations"] = base
        rows[0]["arms"][sample.CANDIDATE]["translations"] = dict(base)
        moved = dict(base, **{ids[0]: "一二三四五六七八九", ids[1]: "一"})
        rows[0]["arms"][sample.ALT]["translations"] = moved
        summary = sample.summarise(rows)
        self.assertEqual(summary["generated_pairs"], 1)
        self.assertEqual(summary["reorder"][sample.CANDIDATE]["reordered_share"]["0.2"], 0.0)
        self.assertEqual(summary["reorder"][sample.ALT]["reordered_share"]["0.2"], 1.0)
        self.assertEqual(summary["reorder"][f"{sample.ALT} vs {sample.CANDIDATE}"]["reordered_share"]["0.2"], 1.0)
        text = sample.markdown(rows)
        self.assertIn("grp1-alt", text)
        self.assertIn("[组1]", text)


if __name__ == "__main__":
    unittest.main()
