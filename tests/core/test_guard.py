"""ASR 整窗复读守卫（`kototoki.guard`，ADR-0030「复读 repeat-strict」、语速、已知幻听句）的纯逻辑测试。"""

from __future__ import annotations

import unittest

from kototoki import guard

FILLER = "今日は良い天気なので外へ出かけて買い物をします明後晩"  # 26 个互不相同的字


class RepeatTests(unittest.TestCase):
    def test_ten_copies_flag_and_nine_do_not(self) -> None:
        self.assertFalse(guard.check_repeat("うっ" * 9))
        self.assertTrue(guard.check_repeat("うっ" * 10))

    def test_period_two_run_of_22_copies_collapses_to_one(self) -> None:
        text, record = guard.apply_repeat("うっ" * 22)
        self.assertEqual(text, "うっ")
        self.assertEqual(record, {"rule": "repeat-strict", "action": "collapse", "period": 2, "copies": 22,
                                  "removed_raw_chars": 42})

    def test_recurring_alone_is_blanked(self) -> None:
        source = "".join(f"たすけ{index}" for index in range(10))  # 不相邻：每份之间隔一个不同的字
        self.assertEqual(guard.apply_repeat(source), (source, {"rule": "repeat-strict", "action": "blank", "period": None,
                                                        "copies": None, "removed_raw_chars": 0}))


class WindowGuardTests(unittest.TestCase):
    """`guard.apply`：复读之后在（折叠后的）文字上看语速与已知幻听句（ADR-0030）。"""

    def test_speech_rate_over_twenty_chars_per_second_is_blanked(self) -> None:
        self.assertEqual(guard.apply(FILLER[:20], 1.0), (FILLER[:20], None))  # 恰好 20 字/秒不置空
        text = "ありがとうございました。"  # 规范化 11 字
        self.assertEqual(guard.apply(text, 0.253), (text, {"rule": "speech-rate", "action": "blank", "chars": 11,
                                                           "duration_s": 0.253}))

    def test_whole_window_hallucination_phrase_is_blanked(self) -> None:
        text = "ご視聴ありがとうございました。"
        self.assertEqual(guard.apply(text, 27.0), (text, {"rule": "hallucination-phrase", "action": "blank",
                                                          "phrase_index": 0}))

    def test_repeat_runs_first_and_the_later_rules_see_the_collapsed_text(self) -> None:
        source = "まって、" + "うっ…" * 22 + "だめ。"
        text, record = guard.apply(source, 1.0)  # 原文规范化 51 字 > 20，折叠后 7 字：只折叠
        self.assertEqual((text, record["rule"], record["action"]), ("まって、うっ…だめ。", "repeat-strict", "collapse"))


if __name__ == "__main__":
    unittest.main()
