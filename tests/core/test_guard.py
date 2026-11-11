"""ASR 整窗复读守卫（`kototoki.guard`，ADR-0023）的纯逻辑测试。

等价守门把产品移植在一组固定文本上的命中与折叠结果钉成 sha256；与研究侧 `experiments.asr_robustness_v15.repeat`
的实时对照在 `tests/equivalence/test_guard.py`（core 测试不导入 experiments）。
"""

from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
import unittest
from pathlib import Path

from kototoki import guard, recipes

REPO = Path(__file__).resolve().parents[2]
FILLER = "今日は良い天気なので外へ出かけて買い物をします明後晩"  # 26 个互不相同的字


def equivalence_texts() -> list[str]:
    """固定样本：手写边界用例加 300 条种子 23 的随机用例（`tests/equivalence/test_guard.py` 复用同一组）。"""
    fixed = ["", "うっ" * 9, "うっ" * 10, "うっ…" * 22, "あ" * 19, "あ" * 20, "あ" * 45, FILLER,
             "うっ" * 10 + FILLER[:20], "うっ" * 10 + FILLER[:21], "まって、" + "うっ…" * 22 + "だめ。",
             "ねえ" + "たすけて！" * 12 + "おわり", "".join(f"たすけ{index}" for index in range(10)),
             "うっ" * 30 + "あれ" * 12, "ｱｯ" * 12 + "ﾀﾞﾒ", "ABC abc " * 11, "はいはい" * 5 + "、" + "はい" * 3]
    rng = random.Random(23)
    generated = []
    for _ in range(300):
        unit = "".join(rng.choice("あいうっ、。") for _ in range(rng.randint(1, 5)))
        head = "".join(rng.choice(FILLER) for _ in range(rng.randint(0, 12)))
        tail = "".join(rng.choice(FILLER + "あ…") for _ in range(rng.randint(0, 30)))
        generated.append(head + unit * rng.randint(4, 14) + tail + unit * rng.randint(0, 6))
    return fixed + generated


class RuleTests(unittest.TestCase):
    def test_rule_is_the_recipe_block(self) -> None:
        self.assertEqual(guard.RULE, {"rule": "repeat-strict", "min_period": 2, "min_copies": 10, "min_count": 10,
                                      "min_length": 3, "min_coverage": 0.5})
        block = recipes.W0["guard"]
        self.assertEqual({key: block[key] for key in guard.RULE}, guard.RULE)
        self.assertEqual(set(block) - set(guard.RULE), {"action", "normalize"})

    def test_module_stays_in_the_base_layer(self) -> None:
        code = ("import sys, kototoki.guard; "
                "bad = [m for m in sys.modules if m.split('.')[0] in ('torch', 'experiments', 'kototoki_eval', "
                "'numpy')]; sys.exit(1 if bad else 0)")
        self.assertEqual(subprocess.run([sys.executable, "-c", code], cwd=REPO).returncode, 0)


class CheckTests(unittest.TestCase):
    def test_ten_copies_flag_and_nine_do_not(self) -> None:
        self.assertFalse(guard.check("うっ" * 9))
        self.assertFalse(guard.check("うっ" * 9 + "あ"))
        self.assertTrue(guard.check("うっ" * 10))
        self.assertTrue(guard.check("うっ…" * 10))  # 标点不计入

    def test_coverage_below_half_is_not_flagged(self) -> None:
        self.assertTrue(guard.check("うっ" * 10 + FILLER[:20]))   # 20 / 40
        self.assertFalse(guard.check("うっ" * 10 + FILLER[:21]))  # 20 / 41

    def test_single_character_run_counts_as_period_two(self) -> None:
        self.assertFalse(guard.check("あ" * 19))  # 9 份
        self.assertTrue(guard.check("あ" * 20))
        self.assertEqual(guard.apply("あ" * 21), ("あ" * 3, {"rule": "repeat-strict", "action": "collapse", "period": 2,
                                                             "copies": 10, "removed_raw_chars": 18}))

    def test_ordinary_and_empty_text_pass(self) -> None:
        for text in ("", "。", FILLER, "はい、はい、はい。そうですね、そうですね。"):
            with self.subTest(text=text):
                self.assertFalse(guard.check(text))
                self.assertEqual(guard.apply(text), (text, None))

    def test_text_that_cannot_be_normalized_is_not_flagged(self) -> None:
        text = "가" * 30  # 相邻的谚文字母在 NFKC 下跨簇合成，normalize 拒绝
        self.assertFalse(guard.check(text))
        self.assertEqual(guard.apply(text), (text, None))


class ApplyTests(unittest.TestCase):
    def test_period_two_run_of_22_copies_collapses_to_one(self) -> None:
        text, record = guard.apply("うっ" * 22)
        self.assertEqual(text, "うっ")
        self.assertEqual(record, {"rule": "repeat-strict", "action": "collapse", "period": 2, "copies": 22,
                                  "removed_raw_chars": 42})

    def test_punctuation_between_copies_is_removed_with_them(self) -> None:
        text, record = guard.apply("まって、" + "うっ…" * 22 + "だめ。")
        self.assertEqual(text, "まって、うっ…だめ。")  # 最后一份之后的标点属于区段之外，照抄
        self.assertEqual((record["action"], record["period"], record["copies"], record["removed_raw_chars"]),
                         ("collapse", 2, 22, 63))

    def test_longer_unit_keeps_text_before_and_after(self) -> None:
        text, record = guard.apply("ねえ" + "たすけて！" * 12 + "おわり")
        self.assertEqual(text, "ねえたすけて！おわり")
        self.assertEqual((record["period"], record["copies"]), (4, 12))

    def test_recurring_alone_is_blanked(self) -> None:
        source = "".join(f"たすけ{index}" for index in range(10))  # 不相邻：每份之间隔一个不同的字
        self.assertTrue(guard.check(source))
        self.assertEqual(guard.apply(source), (source, {"rule": "repeat-strict", "action": "blank", "period": None,
                                                        "copies": None, "removed_raw_chars": 0}))

    def test_still_flagged_after_collapse_is_blanked(self) -> None:
        source = "うっ" * 30 + "あれ" * 12
        text, record = guard.apply(source)
        self.assertEqual(text, source)
        self.assertEqual(record, {"rule": "repeat-strict", "action": "blank", "period": 2, "copies": 30,
                                  "removed_raw_chars": 58})


class ResearchPinTests(unittest.TestCase):
    """产品移植在固定样本上的逐条结果（是否命中、折叠或置空、折叠后文本、period、copies、removed_raw_chars）钉成 sha256。

    钉值取自 2026-11-11 的研究实现 `experiments.asr_robustness_v15.repeat`（`flagged`／`collapse`，`repeat-strict`
    参数，折叠后仍命中则置空），由 `tests/equivalence/test_guard.py` 实时对照。"""

    PINNED_SHA256 = "b18bedec9074643bcc31fe61cf3f7e5cb56a09007595f5fea759cddb3914ba4b"

    def test_results_on_the_fixed_texts_are_pinned(self) -> None:
        texts = equivalence_texts()
        results = []
        for text in texts:
            if not guard.check(text):
                results.append([False])
                continue
            new_text, record = guard.apply(text)
            results.append([True, record["action"], new_text, record["period"], record["copies"],
                            record["removed_raw_chars"]])
        flagged = sum(result[0] for result in results)
        self.assertGreater(flagged, 20)                # 两类结果都有足够样本
        self.assertGreater(len(texts) - flagged, 20)
        self.assertGreater(sum(result[1] == "collapse" for result in results if result[0]), 10)
        self.assertGreater(sum(result[1] == "blank" for result in results if result[0]), 0)
        digest = hashlib.sha256(json.dumps(results, ensure_ascii=False).encode("utf-8")).hexdigest()
        self.assertEqual(digest, self.PINNED_SHA256)


if __name__ == "__main__":
    unittest.main()
