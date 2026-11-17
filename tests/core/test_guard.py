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
from kototoki.judge import normalize

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
    def test_rules_are_the_recipe_block(self) -> None:
        self.assertEqual(guard.REPEAT, {"rule": "repeat-strict", "min_period": 2, "min_copies": 10, "min_count": 10,
                                        "min_length": 3, "min_coverage": 0.5})
        self.assertEqual(guard.SPEECH_RATE, {"rule": "speech-rate", "max_chars_per_s": 20})
        self.assertEqual(guard.PHRASES, {"rule": "hallucination-phrase", "phrases": (
            "ご視聴ありがとうございました", "チャンネル登録よろしくお願いします", "byH")})
        block = recipes.W0["guard"]
        self.assertEqual(set(block), {"normalize", "order", "repeat", "speech_rate", "hallucination_phrases"})
        self.assertEqual({key: block["repeat"][key] for key in guard.REPEAT}, guard.REPEAT)
        self.assertEqual(set(block["repeat"]) - set(guard.REPEAT), {"action"})

    def test_phrases_are_already_normalized(self) -> None:
        for phrase in guard.PHRASES["phrases"]:
            with self.subTest(phrase=phrase):
                self.assertEqual(normalize(phrase).text, phrase)

    def test_module_stays_in_the_base_layer(self) -> None:
        code = ("import sys, kototoki.guard; "
                "bad = [m for m in sys.modules if m.split('.')[0] in ('torch', 'experiments', 'kototoki_eval', "
                "'numpy')]; sys.exit(1 if bad else 0)")
        self.assertEqual(subprocess.run([sys.executable, "-c", code], cwd=REPO).returncode, 0)


class CheckTests(unittest.TestCase):
    def test_ten_copies_flag_and_nine_do_not(self) -> None:
        self.assertFalse(guard.check_repeat("うっ" * 9))
        self.assertFalse(guard.check_repeat("うっ" * 9 + "あ"))
        self.assertTrue(guard.check_repeat("うっ" * 10))
        self.assertTrue(guard.check_repeat("うっ…" * 10))  # 标点不计入

    def test_coverage_below_half_is_not_flagged(self) -> None:
        self.assertTrue(guard.check_repeat("うっ" * 10 + FILLER[:20]))   # 20 / 40
        self.assertFalse(guard.check_repeat("うっ" * 10 + FILLER[:21]))  # 20 / 41

    def test_single_character_run_counts_as_period_two(self) -> None:
        self.assertFalse(guard.check_repeat("あ" * 19))  # 9 份
        self.assertTrue(guard.check_repeat("あ" * 20))
        self.assertEqual(guard.apply_repeat("あ" * 21), ("あ" * 3, {"rule": "repeat-strict", "action": "collapse", "period": 2,
                                                             "copies": 10, "removed_raw_chars": 18}))

    def test_ordinary_and_empty_text_pass(self) -> None:
        for text in ("", "。", FILLER, "はい、はい、はい。そうですね、そうですね。"):
            with self.subTest(text=text):
                self.assertFalse(guard.check_repeat(text))
                self.assertEqual(guard.apply_repeat(text), (text, None))

    def test_text_that_cannot_be_normalized_is_not_flagged(self) -> None:
        text = "가" * 30  # 相邻的谚文字母在 NFKC 下跨簇合成，normalize 拒绝
        self.assertFalse(guard.check_repeat(text))
        self.assertEqual(guard.apply_repeat(text), (text, None))


class ApplyTests(unittest.TestCase):
    def test_period_two_run_of_22_copies_collapses_to_one(self) -> None:
        text, record = guard.apply_repeat("うっ" * 22)
        self.assertEqual(text, "うっ")
        self.assertEqual(record, {"rule": "repeat-strict", "action": "collapse", "period": 2, "copies": 22,
                                  "removed_raw_chars": 42})

    def test_punctuation_between_copies_is_removed_with_them(self) -> None:
        text, record = guard.apply_repeat("まって、" + "うっ…" * 22 + "だめ。")
        self.assertEqual(text, "まって、うっ…だめ。")  # 最后一份之后的标点属于区段之外，照抄
        self.assertEqual((record["action"], record["period"], record["copies"], record["removed_raw_chars"]),
                         ("collapse", 2, 22, 63))

    def test_longer_unit_keeps_text_before_and_after(self) -> None:
        text, record = guard.apply_repeat("ねえ" + "たすけて！" * 12 + "おわり")
        self.assertEqual(text, "ねえたすけて！おわり")
        self.assertEqual((record["period"], record["copies"]), (4, 12))

    def test_recurring_alone_is_blanked(self) -> None:
        source = "".join(f"たすけ{index}" for index in range(10))  # 不相邻：每份之间隔一个不同的字
        self.assertTrue(guard.check_repeat(source))
        self.assertEqual(guard.apply_repeat(source), (source, {"rule": "repeat-strict", "action": "blank", "period": None,
                                                        "copies": None, "removed_raw_chars": 0}))

    def test_still_flagged_after_collapse_is_blanked(self) -> None:
        source = "うっ" * 30 + "あれ" * 12
        text, record = guard.apply_repeat(source)
        self.assertEqual(text, source)
        self.assertEqual(record, {"rule": "repeat-strict", "action": "blank", "period": 2, "copies": 30,
                                  "removed_raw_chars": 58})


class WindowGuardTests(unittest.TestCase):
    """`guard.apply`：复读之后在（折叠后的）文字上看语速与已知幻听句（ADR-0030）。"""

    def test_ordinary_window_passes(self) -> None:
        self.assertEqual(guard.apply("こんにちは。元気？", 1.0), ("こんにちは。元気？", None))
        self.assertEqual(guard.apply("", 0.017), ("", None))

    def test_speech_rate_over_twenty_chars_per_second_is_blanked(self) -> None:
        self.assertEqual(guard.apply(FILLER[:20], 1.0), (FILLER[:20], None))  # 恰好 20 字/秒不置空
        text = "ありがとうございました。"  # 规范化 11 字
        self.assertEqual(guard.apply(text, 0.253), (text, {"rule": "speech-rate", "action": "blank", "chars": 11,
                                                           "duration_s": 0.253}))
        self.assertEqual(guard.apply(text, 0.6), (text, None))

    def test_punctuation_does_not_count_towards_speech_rate(self) -> None:
        self.assertEqual(guard.apply("はい！！！……。、。", 0.1), ("はい！！！……。、。", None))  # 规范化 2 字 ÷ 0.1 s = 20，不超限

    def test_whole_window_hallucination_phrase_is_blanked(self) -> None:
        for index, text in enumerate(("ご視聴ありがとうございました。", " チャンネル登録よろしくお願いします", "by H.")):
            with self.subTest(text=text):
                self.assertEqual(guard.apply(text, 27.0), (text, {"rule": "hallucination-phrase", "action": "blank",
                                                                  "phrase_index": index}))

    def test_phrase_inside_longer_text_or_other_thanks_pass(self) -> None:
        for text in ("お疲れ様でした。ご視聴ありがとうございました", "ありがとうございました。", "BY H"):
            with self.subTest(text=text):
                self.assertEqual(guard.apply(text, 27.0), (text, None))

    def test_repeat_runs_first_and_the_later_rules_see_the_collapsed_text(self) -> None:
        source = "まって、" + "うっ…" * 22 + "だめ。"
        text, record = guard.apply(source, 1.0)  # 原文规范化 51 字 > 20，折叠后 7 字：只折叠
        self.assertEqual((text, record["rule"], record["action"]), ("まって、うっ…だめ。", "repeat-strict", "collapse"))
        self.assertEqual(guard.apply(source, 0.3), (source, {"rule": "speech-rate", "action": "blank", "chars": 7,
                                                             "duration_s": 0.3}))
        phrase = "ご視聴ありがとうございました" + "。ご視聴ありがとうございました" * 11
        self.assertEqual(guard.apply(phrase, 27.0), (phrase, {"rule": "hallucination-phrase", "action": "blank",
                                                              "phrase_index": 0}))  # 折叠成一句后命中幻听句

    def test_repeat_blank_wins_and_unnormalizable_text_passes(self) -> None:
        source = "".join(f"たすけ{index}" for index in range(10))
        self.assertEqual(guard.apply(source, 0.1)[1]["rule"], "repeat-strict")
        jamo = "가" * 30  # 同 CheckTests：相邻的谚文字母无法规范化
        self.assertEqual(guard.apply(jamo, 0.1), (jamo, None))

    def test_duration_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            guard.apply("はい", 0.0)


class ResearchPinTests(unittest.TestCase):
    """产品移植在固定样本上的逐条结果（是否命中、折叠或置空、折叠后文本、period、copies、removed_raw_chars）钉成 sha256。

    钉值取自 2026-11-11 的研究实现 `experiments.asr_robustness_v15.repeat`（`flagged`／`collapse`，`repeat-strict`
    参数，折叠后仍命中则置空），由 `tests/equivalence/test_guard.py` 实时对照。"""

    PINNED_SHA256 = "b18bedec9074643bcc31fe61cf3f7e5cb56a09007595f5fea759cddb3914ba4b"

    def test_results_on_the_fixed_texts_are_pinned(self) -> None:
        texts = equivalence_texts()
        results = []
        for text in texts:
            if not guard.check_repeat(text):
                results.append([False])
                continue
            new_text, record = guard.apply_repeat(text)
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
