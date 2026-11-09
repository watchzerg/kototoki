"""票据 04 `names_replace` 的离线测试：合成表与合成 cue，不读 `.local/`、不起 Strata。"""

from __future__ import annotations

import json
import unittest

from experiments.asr_robustness_v15 import names_replace as nr

TABLE = {"entries": [
    {"entity_ja": "遠坂凛", "confidence": "high", "zh": "远坂凛",
     "forms": [{"ja": "遠坂凛", "zh": "远坂凛"}, {"ja": "遠坂", "zh": "远坂"}, {"ja": "トウサカ", "zh": "远坂"}, {"ja": "父坂", "zh": "远坂"}]},
    {"entity_ja": "間桐桜", "confidence": "high", "zh": "间桐樱",
     "forms": [{"ja": "間桐桜", "zh": "间桐樱"}, {"ja": "さくら", "zh": "樱"}, {"ja": "サクラ", "zh": "樱"}, {"ja": "桜", "zh": "樱"}]},
    {"entity_ja": "エミヤシロウ", "confidence": "high", "zh": "卫宫士郎",
     "forms": [{"ja": "シロウ", "zh": "士郎"}, {"ja": "エミヤキリツム", "zh": "卫宫切嗣"}]},
    {"entity_ja": "エミヤ切嗣", "confidence": "high", "zh": "卫宫切嗣", "forms": [{"ja": "エミヤ・キリツグ", "zh": "卫宫切嗣"}]},
    {"entity_ja": "サクラ荘", "confidence": "high", "zh": "樱庄", "forms": []},
    {"entity_ja": "リン", "confidence": "high", "zh": "凛", "forms": []},
    {"entity_ja": "鈴", "confidence": "high", "zh": "铃", "forms": [{"ja": "リン", "zh": "铃"}]},
    {"entity_ja": "ランサー", "confidence": "medium", "zh": "Lancer", "forms": [{"ja": "ランサ", "zh": "Lancer"}]},
]}
TEXTS = ["遠坂さん", "トウサカ", "遠坂", "サクラ", "さくら", "さくら"]


class Groups(unittest.TestCase):
    def setUp(self):
        self.g = nr.build_groups(TABLE, TEXTS)

    def test_canonical_by_frequency_and_tie(self):
        by_zh = {g["zh"]: g for g in self.g["groups"]}
        self.assertEqual(by_zh["远坂"]["canonical"], "遠坂")
        self.assertEqual(sorted(by_zh["远坂"]["replace"]), ["トウサカ", "父坂"])
        self.assertEqual(by_zh["樱"]["canonical"], "さくら")          # 出现 2 次 > サクラ 1 次
        self.assertEqual(by_zh["樱"]["forms"], ["さくら", "サクラ"])  # 单字「桜」不参与
        self.assertEqual(by_zh["卫宫切嗣"]["canonical"], "エミヤ切嗣")  # 全 0 并列 → 条目 entity_ja
        self.assertTrue(by_zh["卫宫切嗣"]["tie"])

    def test_entity_rule_ignores_frequency(self):
        g = nr.build_groups(TABLE, TEXTS, "entity")
        by_zh = {x["zh"]: x for x in g["groups"]}
        self.assertEqual(by_zh["樱"]["canonical"], "さくら")       # 组内没有头写法 → 先列出的
        self.assertEqual(by_zh["卫宫切嗣"]["canonical"], "エミヤ切嗣")  # 与组 zh 同名条目的头写法
        self.assertEqual(g["canonical_rule"], "entity")
        freq = nr.build_groups(TABLE, ["サクラ"] * 3, "frequency")
        self.assertEqual(next(x for x in freq["groups"] if x["zh"] == "樱")["canonical"], "サクラ")

    def test_ambiguous_and_medium_excluded(self):
        self.assertEqual(self.g["ambiguous"], ["リン"])
        self.assertNotIn("リン", self.g["all_forms"])
        self.assertNotIn("ランサー", self.g["all_forms"])
        self.assertEqual(self.g["single_char"], ["桜", "鈴"])
        self.assertEqual(self.g["mapping"]["エミヤ・キリツグ"], "エミヤ切嗣")

    def test_name_lines_canonical_first(self):
        line = next(l for l in nr.name_lines(self.g) if l.startswith("遠坂／"))
        self.assertEqual(line, "遠坂／トウサカ／父坂")


class Replace(unittest.TestCase):
    def setUp(self):
        self.g = nr.build_groups(TABLE, TEXTS)

    def test_replace_non_canonical(self):
        text, reps = nr.replace_text("トウサカ凛とサクラが来た", self.g["mapping"], self.g["all_forms"])
        self.assertEqual(text, "遠坂凛とさくらが来た")
        self.assertEqual([(r["from"], r["to"]) for r in reps], [("トウサカ", "遠坂"), ("サクラ", "さくら")])

    def test_inside_longer_form_protected(self):
        text, reps = nr.replace_text("サクラ荘へ行く", self.g["mapping"], self.g["all_forms"])
        self.assertEqual((text, reps), ("サクラ荘へ行く", []))

    def test_canonical_untouched(self):
        text, reps = nr.replace_text("遠坂凛と遠坂", self.g["mapping"], self.g["all_forms"])
        self.assertEqual((text, reps), ("遠坂凛と遠坂", []))


class Guard(unittest.TestCase):
    def setUp(self):
        self.forms = nr.build_groups(TABLE, TEXTS)["all_forms"]

    def test_accepts_table_replacement(self):
        out = nr.table_guard("トーサカさんは来た", "遠坂さんは来た", self.forms)
        self.assertTrue(out["ok"])
        self.assertEqual(out["replacements"], [{"from": "トーサカ", "to": "遠坂"}])

    def test_extends_into_context(self):
        out = nr.table_guard("父坂さん", "遠坂さん", self.forms)   # diff 只有「父→遠」，扩一字成「遠坂」
        self.assertTrue(out["ok"])
        self.assertEqual(out["replacements"], [{"from": "父坂", "to": "遠坂"}])
        out = nr.table_guard("エミヤ・キリツム", "エミヤ切嗣", self.forms)
        self.assertTrue(out["ok"])
        self.assertEqual(out["replacements"][0]["to"], "エミヤ切嗣")

    def test_rejects_deletion_and_non_table(self):
        self.assertEqual(nr.table_guard("トーサカさんは来た", "さんは来た", self.forms)["reason"], "deletion")
        self.assertEqual(nr.table_guard("トーサカさんは来た", "遠坂君は来た", self.forms)["reason"], "not_table")
        self.assertEqual(nr.table_guard("今日は晴れ", "今日は雨", self.forms)["reason"], "not_table")
        self.assertEqual(nr.table_guard("同じ", "同じ", self.forms)["reason"], "unchanged")

    def test_apply_reply_counts(self):
        pack = {"targets": [{"index": 1, "text": "トウサカさん、おはようございます"}, {"index": 2, "text": "こんにちは"},
                            {"index": 3, "text": "トウサカ!"}]}
        reply = {"c1": "遠坂さん、おはようございます", "c2": "こんばんは", "c3": "遠坂!"}
        kept, counts = nr.apply_reply(pack, json.dumps(reply, ensure_ascii=False), self.forms)
        self.assertEqual(list(kept), ["c1"])  # c3 被 v14 的编辑比 ≤0.5 守卫先拦下（4/5）
        self.assertEqual((counts["proposed"], counts["accepted"], counts["rejected_not_table"], counts["ratio_rejected"]),
                         (3, 1, 1, 1))


class HitRate(unittest.TestCase):
    def test_before_after(self):
        reference = [{"start": 0.0, "end": 1.0, "text": "遠坂さん"}, {"start": 2.0, "end": 3.0, "text": "こんにちは"}]
        cues = [{"start": 0.0, "end": 1.0, "text": "トウサカさん"}, {"start": 2.0, "end": 3.0, "text": "こんにちは"}]
        before = nr.name_hit_rate(reference, cues, ["遠坂"])
        self.assertEqual((before["mentions"], before["hits"], before["units_with_names"]), (1, 0, 1))
        after = nr.name_hit_rate(reference, [{**cues[0], "text": "遠坂さん"}, cues[1]], ["遠坂"])
        self.assertEqual((after["mentions"], after["hits"], after["rate"]), (1, 1, 1.0))


if __name__ == "__main__":
    unittest.main()
