import json
import tempfile
import unittest
from pathlib import Path

from experiments.quality_v5 import consistency as c


def work(rows):
    """rows：(日文, 中文)；补足背景 cue，避免特异性判定只看术语 cue。"""
    filler = [("今日はいい天気だ", "今天天气真好"), ("行こう", "走吧"), ("そうだね", "是啊")] * 3
    return list(rows) + filler


class ExtractTermsTest(unittest.TestCase):
    def test_katakana_and_honorific_names(self):
        ja = ["マルシルが来た", "マルシルさん", "おいマルシル", "桜さん、大丈夫？", "桜さんだ", "桜さんは",
              "衛宮くん", "衛宮は強い", "衛宮だ", "姉さん", "姉さん", "姉さん"]
        terms = c.extract_terms(ja)
        self.assertEqual(terms["マルシル"], [0, 1, 2])
        self.assertEqual(terms["桜"], [3, 4, 5])
        self.assertEqual(terms["衛宮"], [6, 7, 8])  # ≥2 字的名：不带敬称的出现也计
        self.assertNotIn("姉", terms)  # 亲属称谓不是人名

    def test_short_or_rare_terms_dropped(self):
        terms = c.extract_terms(["ダメだ", "ダメ", "ダメ", "ライオス", "ライオス"])
        self.assertEqual(terms, {})  # ダメ 只有 2 字；ライオス 只出现 2 次

    def test_substring_term_absorbed_by_longer(self):
        terms = c.extract_terms(["マルシル", "マルシルだ", "マルシルか"])
        self.assertEqual(list(terms), ["マルシル"])


class AnalyzeTest(unittest.TestCase):
    def test_transliteration_variant_is_alt(self):
        rows = [("アスナ", "亚丝娜"), ("アスナ、行くぞ", "亚丝娜，走吧"), ("アスナは強い", "亚丝娜很强"),
                ("アスナ！", "亚斯娜！")]
        [result] = c.analyze_work(work(rows))
        self.assertEqual((result.rendering, result.main, result.alt), ("亚丝娜", 3, 1))
        self.assertEqual(result.alt_examples, [{"rendering": "亚斯娜", "cue": 3}])

    def test_alternative_rendering_and_missing(self):
        rows = [("セイバー", "Saber"), ("セイバーだ", "是Saber"), ("セイバー！", "Saber！"),
                ("セイバー、下がれ", "剑兵，退下"), ("セイバーか", "是剑兵吗"), ("セイバー？", "你说什么？")]
        [result] = c.analyze_work(work(rows))
        self.assertEqual(result.rendering, "saber")
        self.assertEqual((result.main, result.alt, result.missing), (3, 2, 1))
        self.assertEqual(result.alternatives, ["剑兵"])

    def test_honorific_and_context_chars_do_not_count_as_variants(self):
        rows = [("フリーレン様", "芙莉莲大人"), ("フリーレン", "芙莉莲"), ("フリーレンは", "是芙莉莲"),
                ("フリーレン様だ", "芙莉莲大人啊")]
        [result] = c.analyze_work(work(rows))
        self.assertEqual((result.rendering, result.main, result.alt), ("芙莉莲", 4, 0))

    def test_generic_noun_with_context_padded_rendering_is_excluded(self):
        # "网球"在作品里到处出现（不特异），R1 只会是"打网球"这类带语境的串：不计入
        rows = [("テニスしよう", "去打网球吧"), ("テニスか", "打网球吗"), ("テニスだ", "是网球"),
                ("テニス大会", "地下网球大赛")]
        background = [("練習", "网球练习"), ("試合", "网球比赛"), ("ラケット", "网球拍")]
        self.assertEqual(c.analyze_work(work(rows + background)), [])

    def test_shared_core_is_same_rendering(self):
        self.assertTrue(c.overlaps("防止公会", "两个公会"))
        self.assertFalse(c.overlaps("弗莉蕾", "弗雷伦"))


class AggregateTest(unittest.TestCase):
    def result(self, term, main, alt):
        return c.TermResult(term, main + alt, main, alt, 0, "x")

    def test_category_means_are_work_equal(self):
        works = {"W1": c.work_summary([self.result("a", 9, 1)]), "W2": c.work_summary([self.result("b", 1, 1)]),
                 "M1": c.work_summary([self.result("c", 4, 0)])}
        means = c.category_means(works, {"W1": "anime_series", "W2": "anime_series", "M1": "animation_movie"})
        self.assertAlmostEqual(means["anime_series"], (0.1 + 0.5) / 2)
        self.assertAlmostEqual(means["overall"], (0.3 + 0.0) / 2)

    def test_bootstrap_delta_is_paired_on_terms(self):
        a = {"W1": [self.result("a", 4, 0), self.result("b", 4, 0)]}
        b = {"W1": [self.result("a", 2, 2), self.result("b", 4, 0)]}
        out = c.bootstrap_delta(a, b, {"W1": "anime_series"}, draws=200)
        self.assertAlmostEqual(out["delta"], 0.25)
        self.assertEqual(out["paired_terms"], 2)


class SrtTest(unittest.TestCase):
    def test_read_srt_texts_joins_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.srt"
            path.write_text("1\n00:00:01,000 --> 00:00:02,000\n第一行\n第二行\n\n2\n00:00:03,000 --> 00:00:04,000\n下一条\n",
                            encoding="utf-8")
            self.assertEqual(c.read_srt_texts(path), ["第一行 第二行", "下一条"])

    def test_precision_prompt_contains_only_text_fields(self):
        items = [{"id": "c01", "term": "アスナ", "rendering": "亚丝娜", "main_ja": "アスナ", "main_zh": "亚丝娜",
                  "alt": "亚斯娜", "alt_ja": "アスナ！", "alt_zh": "亚斯娜！"}]
        prompt = c.precision_prompt(items)
        self.assertIn("[c01]", prompt)
        self.assertIn("亚斯娜", prompt)
        json.dumps(c.PRECISION_SCHEMA)


if __name__ == "__main__":
    unittest.main()
