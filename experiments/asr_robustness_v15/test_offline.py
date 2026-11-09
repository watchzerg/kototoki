"""v15 研究包的离线单元测试：合成数据，不加载模型、不起 Strata、不读 `.local/`、不碰 GPU。"""

from __future__ import annotations

import unittest

from experiments.asr_robustness_v15 import actions, inventory, repeat, scan


class TandemDetector(unittest.TestCase):
    def test_runs_and_best(self):
        text = "あいう" + "かき" * 7 + "さしす"
        best = repeat.best_tandem(text, min_period=2, min_copies=3)
        self.assertEqual((best["period"], best["copies"], best["run_chars"], best["start"]), (2, 7, 14, 3))
        self.assertAlmostEqual(best["coverage"], 14 / 20, places=4)

    def test_same_char_run_counts_as_period_two(self):
        self.assertEqual(repeat.best_tandem("ああああああ", min_period=1)["copies"], 6)
        same = repeat.best_tandem("ああああああ", min_period=2)
        self.assertEqual((same["period"], same["copies"]), (2, 3))
        self.assertIsNone(repeat.best_tandem("あああああ", min_period=2, min_copies=3))  # 5 字：p=2 只有 2 份

    def test_no_repeat(self):
        self.assertIsNone(repeat.best_tandem("あいうえおかきくけこ"))
        self.assertIsNone(repeat.best_recurring("あいうえおかきくけこ"))

    def test_recurring_non_adjacent(self):
        text = "はいそうですねはいそうですかはいそうですよ"
        best = repeat.best_recurring(text, min_length=3, min_count=3)
        self.assertEqual((best["length"], best["count"]), (6, 3))  # 「はいそうです」×3（6 字）

    def test_signals_normalize_punctuation(self):
        raw = "終わったな…うっ…" + "うっ…" * 20
        for rule in (repeat.RULE_DEFAULT, scan.REPEAT_RULES["repeat-strict"]):
            sig = repeat.signals(raw, rule)
            self.assertEqual((sig["tandem"]["period"], sig["tandem"]["copies"]), (2, 21))
            self.assertTrue(repeat.flagged(sig, rule))

    def test_flagged_thresholds(self):
        strict = scan.REPEAT_RULES["repeat-strict"]
        six = "イリア!" * 6  # 真实连呼：p=3、6 次、覆盖 100%
        self.assertTrue(repeat.flagged(repeat.signals(six, scan.REPEAT_RULES["repeat"]), scan.REPEAT_RULES["repeat"]))
        self.assertFalse(repeat.flagged(repeat.signals(six, strict), strict))
        self.assertTrue(repeat.flagged(repeat.signals("あ" * 40, strict), strict))   # p=2 × 20 份
        self.assertFalse(repeat.flagged(repeat.signals("あ" * 19, strict), strict))  # p=2 只有 9 份
        alternating = "うんそう" * 5 + "ね" + "うんそう" * 5  # 相邻只有 5 份，但「うんそう」不重叠出现 10 次
        sig = repeat.signals(alternating, strict)
        self.assertIsNone(sig["tandem"])
        self.assertEqual((sig["recurring"]["length"], sig["recurring"]["count"]), (4, 10))
        self.assertTrue(repeat.flagged(sig, strict))

    def test_rule_aware_best(self):
        # 纯重复字符：各档阈值下 tandem 都按 p=2 计，份数随阈值不变，记录里带上所用参数
        loose = repeat.signals("あ" * 40, scan.REPEAT_RULES["repeat-loose"])
        self.assertEqual((loose["tandem"]["period"], loose["tandem"]["copies"]), (2, 20))
        self.assertEqual(loose["rule"]["min_copies"], 4)


class Collapse(unittest.TestCase):
    def test_collapse_keeps_first_unit_and_tail(self):
        raw = "終わったな…" + "うっ…" * 12 + "貴様!"
        out, rec = repeat.collapse(raw, scan.REPEAT_RULES["repeat-strict"])
        self.assertEqual(out, "終わったな…うっ…貴様!")
        self.assertTrue(rec["collapsed"])
        self.assertEqual((rec["period"], rec["copies"]), (2, 12))
        self.assertEqual(rec["chars_before"] - rec["removed_raw_chars"], rec["chars_after"])

    def test_collapse_noop_below_threshold(self):
        raw = "イリア!イリア!イリア!"
        out, rec = repeat.collapse(raw, scan.REPEAT_RULES["repeat-strict"])
        self.assertEqual(out, raw)
        self.assertFalse(rec["collapsed"])

    def test_collapse_only_tandem_not_recurring(self):
        raw = "うんそう" * 5 + "ね" + "うんそう" * 5  # 只被 recurring 命中：不折叠，由调用方置空
        out, rec = repeat.collapse(raw, scan.REPEAT_RULES["repeat-strict"])
        self.assertEqual(out, raw)
        self.assertFalse(rec["collapsed"])

    def test_collapse_same_char_run(self):
        out, rec = repeat.collapse("あ" * 40 + "!", scan.REPEAT_RULES["repeat-strict"])
        self.assertEqual(out, "ああ!")
        self.assertEqual((rec["period"], rec["copies"]), (2, 20))


class ScanRules(unittest.TestCase):
    def window(self, text, cr=1.0, alp=-0.2, cap=False):
        return {"compression_ratio": cr, "avg_logprob": alp, "cap_reached": cap, "repeat": scan.repeat_signals(text)}

    def test_rule_combinations(self):
        loop = self.window("うっ…" * 12, cr=3.5)
        self.assertTrue(scan.flagged(loop, scan.RULES["doc-default"]))
        self.assertTrue(scan.flagged(loop, scan.RULES["repeat-strict"]))
        self.assertTrue(scan.flagged(loop, scan.RULES["repeat-or-cr2.4"]))
        quiet = self.window("はぁ", cr=1.0, alp=-1.3)
        self.assertTrue(scan.flagged(quiet, scan.RULES["whisper-or"]))
        self.assertFalse(scan.flagged(quiet, scan.RULES["doc-default"]))
        self.assertFalse(scan.flagged(quiet, scan.RULES["repeat"]))
        lyric = self.window("ゴーゴーゴーゴーゴー", cr=2.6)
        self.assertTrue(scan.flagged(lyric, scan.RULES["repeat-or-cr2.4"]))  # 压缩比单独命中
        self.assertFalse(scan.flagged(lyric, scan.RULES["repeat-strict"]))

    def test_window_rows_fields(self):
        sample = {"id": "s", "group": "product", "film": None}
        loaded = {"segments": [{"text": "あいう", "start": 1.0, "end": 2.5, "avg_logprob": -0.3}],
                  "traces": [{"tokens": [1, 2, 3], "prompt": [1] * 4}], "source_start_s": 10.0}
        rows = scan.window_rows(sample, loaded)
        self.assertEqual((rows[0]["start"], rows[0]["end"], rows[0]["duration_s"]), (11.0, 12.5, 1.5))
        self.assertEqual((rows[0]["chars"], rows[0]["tokens"], rows[0]["failed"]), (3, 3, False))
        self.assertIn("tandem", rows[0]["repeat"]["repeat-strict"])


class Inventory(unittest.TestCase):
    def test_film_of(self):
        self.assertEqual(inventory.film_of("w0-pyannote-current-hf-iii-full"), "hf-iii")
        self.assertEqual(inventory.film_of("vad-comparison-v1-w0-silero-hf-ii-window-01"), "hf-ii")
        self.assertIsNone(inventory.film_of("parliament-20261005-v1"))


class Actions(unittest.TestCase):
    def test_collapse_window_then_guard(self):
        folded = actions.collapse_window("うっ…" * 12 + "貴様!", -0.4, {"tokens": [1] * 40, "prompt": [1] * 4}, "repeat-strict")
        self.assertTrue(folded["collapsed"])
        self.assertFalse(folded["still_flagged"])
        self.assertEqual(folded["text"], "うっ…貴様!")

    def test_collapse_window_still_flagged_without_tandem(self):
        folded = actions.collapse_window("うんそう" * 5 + "ね" + "うんそう" * 5, -0.4, None, "repeat-strict")
        self.assertFalse(folded["collapsed"])
        self.assertTrue(folded["still_flagged"])

    def test_repeat_params_fallback(self):
        self.assertEqual(actions.repeat_params("doc-default"), scan.REPEAT_RULES["repeat"])
        self.assertEqual(actions.repeat_params("repeat-strict"), scan.REPEAT_RULES["repeat-strict"])


if __name__ == "__main__":
    unittest.main()
