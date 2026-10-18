"""注入覆盖与 token 增量统计的离线测试（合成场景、按字符计数的假分词器；不读 GGUF）。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.data import Cue, Scene

from . import coverage


class CharTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> SimpleNamespace:
        return SimpleNamespace(ids=list(text))


class CoverageTest(unittest.TestCase):
    def test_counts_injected_packs_and_deltas(self):
        # 8 条：0–4 停顿 0.2 且前一行无句末 → 一组；4 后停顿 30 s（硬切）；5–7 每条以 。 结尾 → 单条组
        rows = [("あの", 0, 1), ("ね", 1.2, 2), ("その", 2.2, 3), ("時", 3.2, 4), ("はい。", 4.2, 5),
                ("うん。", 35, 36), ("え。", 36.2, 37), ("お。", 37.4, 38)]
        scene = Scene("S", tuple(Cue(f"c{i}", t, a, b) for i, (t, a, b) in enumerate(rows)), "W", "anime_series")
        result = coverage.coverage([scene], CharTokenizer())
        self.assertEqual((result["packs"], result["injected_packs"], result["grouped_cues"]), (2, 1, 5))
        swap = len(R.JOINT2_INSTRUCTION) - len(R.JOINT_INSTRUCTION)
        line = len("\n" + R.GROUPS_INJECTION + '{"groups": [["c0", "c1", "c2", "c3", "c4"]]}')
        delta = result["delta_per_injected_pack"]
        self.assertEqual((delta["joint_v1_to_v2"]["max"], delta["groups_line"]["max"], delta["total"]["max"]),
                         (swap, line, swap + line))
        self.assertEqual(result["input_tokens"]["grp1_over_limit"], 0)

    def test_pre_split_escapes_every_ascii_punctuation(self):
        head = coverage.PRE_SPLITS[2].split("][A-Za-z]+")[0]
        self.assertEqual(head[1::2].replace("\\", ""), "")  # 每个标点前都有反斜杠
        self.assertEqual(head[2::2], __import__("string").punctuation)


if __name__ == "__main__":
    unittest.main()
