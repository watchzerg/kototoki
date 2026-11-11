"""`kototoki.guard` 与研究侧 `experiments.asr_robustness_v15.repeat` 的实时对照：选出规则时用的实现在同一组文本上
给出相同的命中与折叠结果。core 侧的同一组文本只钉结果摘要（`tests/core/test_guard.py::ResearchPinTests`）。"""

from __future__ import annotations

import unittest

from experiments.asr_robustness_v15 import repeat
from kototoki import guard
from tests.core.test_guard import equivalence_texts

RESEARCH_RULE = {key: guard.RULE[key] for key in ("min_period", "min_copies", "min_count", "min_length",
                                                  "min_coverage")}


def research_flagged(text: str) -> bool:
    return repeat.flagged(repeat.signals(text, RESEARCH_RULE), RESEARCH_RULE)


class ResearchEquivalenceTests(unittest.TestCase):
    """产品移植与 v15 研究实现（`repeat.flagged`／`repeat.collapse`，`repeat-strict` 参数）结果相同。"""

    def test_check_matches_research_flagged(self) -> None:
        texts = equivalence_texts()
        flagged = 0
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(guard.check(text), research_flagged(text))
            flagged += guard.check(text)
        self.assertGreater(flagged, 20)                # 两类结果都有足够样本
        self.assertGreater(len(texts) - flagged, 20)

    def test_apply_matches_research_collapse_then_recheck(self) -> None:
        actions = {"collapse": 0, "blank": 0}
        for text in equivalence_texts():
            if not research_flagged(text):
                continue
            collapsed, research = repeat.collapse(text, RESEARCH_RULE)
            blank = not research["collapsed"] or research_flagged(collapsed)
            new_text, record = guard.apply(text)
            with self.subTest(text=text):
                self.assertEqual(record["action"], "blank" if blank else "collapse")
                self.assertEqual(new_text, text if blank else collapsed)
                if research["collapsed"]:
                    self.assertEqual((record["period"], record["copies"], record["removed_raw_chars"]),
                                     (research["period"], research["copies"], research["removed_raw_chars"]))
            actions[record["action"]] += 1
        self.assertGreater(actions["collapse"], 10)
        self.assertGreater(actions["blank"], 0)


if __name__ == "__main__":
    unittest.main()
