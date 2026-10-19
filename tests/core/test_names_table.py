"""专名建表的离线测试：不联网、不加载模型。

Parse／Cap／Shape／Honorific／PromptV5／JaShape／Confidence 用例移植自
`experiments/name_consistency/test_build_table.py`（不导入 experiments），去掉 renormalize 与 main；
Render 与 BuildTable 针对产品接口 `build_messages(SourceDocument)`、`build_table(document, chat, tokenize, seed)`。
"""

from __future__ import annotations

import json
import unittest

from kototoki.names import table as bt
from kototoki.srt import parse_srt

SRT = (
    "1\n00:00:47,847 --> 00:00:49,829\nお主は分かっておるな\n\n"
    "2\n00:00:51,650 --> 00:00:54,392\n東坂が\n来たのか\n\n"
    "3\n00:01:00,138 --> 00:01:00,938\nほう\n"
)

GOOD = {
    "work_guess": "新世紀エヴァンゲリオン",
    "entries": [{"entity_ja": "碇シンジ", "kind": "person", "confidence": "high", "zh": "碇真嗣",
                 "forms": [{"ja": "碇シンジ", "zh": "碇真嗣"}, {"ja": "シンジ", "zh": "真嗣"},
                           {"ja": "真司", "zh": "真嗣"}],
                 "zh_variants": ["真司", "Shinji"], "evidence": [2, 3, 99, "x", 0]}],
}


def document(text: str = SRT):
    return parse_srt(text)


class RenderTests(unittest.TestCase):
    def test_timestamps_stripped_indices_kept_multiline_joined(self):
        user = bt.build_messages(document())[1]["content"]
        lines = user.splitlines()
        self.assertEqual(lines[2:5], ["1\tお主は分かっておるな", "2\t東坂が 来たのか", "3\tほう"])
        self.assertNotIn("-->", user)
        self.assertIn("（共 3 条）", user)

    def test_srt_indices_used_not_ordinal(self):
        text = "7\n00:00:01,000 --> 00:00:02,000\nほう\n\n12\n00:00:03,000 --> 00:00:04,000\n東坂が\n"
        lines = bt.build_messages(document(text))[1]["content"].splitlines()
        self.assertEqual(lines[2:4], ["7\tほう", "12\t東坂が"])

    def test_multiline_cue_newlines_become_spaces(self):
        text = "1\n00:00:01,000 --> 00:00:02,000\n一行目\n二行目\n三行目\n"
        user = bt.build_messages(document(text))[1]["content"]
        self.assertIn("1\t一行目 二行目 三行目\n", user)
        self.assertEqual(user.count("\n"), 4)  # 前缀两个、后缀两个，台词内无换行

    def test_prompt_contains_lines_and_instructions(self):
        messages = bt.build_messages(document())
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("2\t東坂が 来たのか", messages[1]["content"])
        self.assertIn("work_guess", messages[0]["content"])
        self.assertIn("お兄ちゃん", messages[0]["content"])
        self.assertIn("不要任何解释文字", messages[0]["content"])


class ParseTests(unittest.TestCase):
    def test_clean_json_normalised(self):
        guess, entries = bt.parse_reply(json.dumps(GOOD, ensure_ascii=False), 3)
        self.assertEqual(guess, "新世紀エヴァンゲリオン")
        entry = entries[0]
        self.assertEqual([f["ja"] for f in entry["forms"]], ["碇シンジ", "シンジ", "真司"])
        self.assertEqual(entry["forms"][1], {"ja": "シンジ", "zh": "真嗣"})
        self.assertEqual(entry["zh_variants"], ["真司", "Shinji"])
        self.assertEqual(entry["evidence"], [2, 3])

    def test_wrapped_in_prose_and_fences(self):
        reply = "好的，结果如下：\n```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```\n以上。"
        self.assertEqual(len(bt.parse_reply(reply, 3)[1]), 1)

    def test_think_block_removed(self):
        reply = "<think>{不是 json}</think>" + json.dumps(GOOD, ensure_ascii=False)
        self.assertEqual(len(bt.parse_reply(reply, 3)[1]), 1)

    def test_invalid_raises(self):
        bad_entry = '{"entries": [{"entity_ja": "", "zh": "x", "forms": []}]}'
        no_forms = '{"entries": [{"entity_ja": "桜", "zh": "（樱）", "forms": [{"ja": "桜", "zh": "（樱）"}]}]}'
        for reply in ("没有 JSON", "{坏掉的", '{"entries": []}', bad_entry, no_forms):
            with self.assertRaises(ValueError):
                bt.parse_reply(reply, 3)

    def test_bad_kind_becomes_other_and_duplicate_entities_dropped(self):
        entry = {"entity_ja": "桜", "zh": "樱", "kind": "weird", "forms": [{"ja": "桜", "zh": "樱"}]}
        _, entries = bt.parse_reply(json.dumps({"entries": [entry, entry]}), 3)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "other")
        self.assertEqual(entries[0]["confidence"], "medium")
        self.assertIsNone(bt.parse_reply(json.dumps({"entries": [entry]}), 3)[0])

    def test_entity_added_as_form_when_missing(self):
        entry = {"entity_ja": "綾波レイ", "zh": "绫波丽", "forms": [{"ja": "レイ", "zh": "丽"}]}
        _, entries = bt.parse_reply(json.dumps({"entries": [entry]}, ensure_ascii=False), 3)
        self.assertEqual(entries[0]["forms"], [{"ja": "綾波レイ", "zh": "绫波丽"}, {"ja": "レイ", "zh": "丽"}])

    def test_forms_deduped_by_ja_first_wins(self):
        forms = [{"ja": "シンジ", "zh": "真嗣"}, {"ja": "シンジ", "zh": "碇真嗣"}, {"ja": " シンジ ", "zh": "新治"}]
        entry = {"entity_ja": "シンジ", "zh": "真嗣", "forms": forms}
        _, entries = bt.parse_reply(json.dumps({"entries": [entry]}, ensure_ascii=False), 3)
        self.assertEqual(entries[0]["forms"], [{"ja": "シンジ", "zh": "真嗣"}])

    def test_forms_with_bad_zh_shape_dropped(self):
        bad = ["佐仓杏子＋模型注释", "真嗣（主角）", "真嗣 注", "真嗣:", "真嗣：x", "[真嗣]", "【真嗣】", "x" * 21, "", None, 5]
        forms = [{"ja": f"写法{i}", "zh": zh} for i, zh in enumerate(bad)] + [{"ja": "シンジ", "zh": "真嗣"}]
        entry = {"entity_ja": "シンジ", "zh": "真嗣", "forms": forms}
        _, entries = bt.parse_reply(json.dumps({"entries": [entry]}, ensure_ascii=False), 3)
        self.assertEqual(entries[0]["forms"], [{"ja": "シンジ", "zh": "真嗣"}])

    def test_entry_without_any_valid_form_dropped(self):
        bad = {"entity_ja": "桜", "zh": "樱（间桐）", "forms": [{"ja": "桜", "zh": "樱 x"}]}
        good = {"entity_ja": "凛", "zh": "凛", "forms": [{"ja": "凛", "zh": "凛"}]}
        _, entries = bt.parse_reply(json.dumps({"entries": [bad, good]}, ensure_ascii=False), 3)
        self.assertEqual([e["entity_ja"] for e in entries], ["凛"])


class CapTests(unittest.TestCase):
    def test_caps_after_dedupe(self):
        zh = [f"译{chr(0x4e00 + i)}" for i in range(20)]  # zh 不许含数字，用不同汉字区分
        forms = [{"ja": f"写{chr(0x4e00 + i)}", "zh": zh[i]} for i in range(20)]  # ja 不许含数字，同样用汉字区分
        entry = {"entity_ja": "写一", "zh": zh[0], "forms": forms,
                 "zh_variants": ["a"] * 3 + zh[:12], "evidence": [1, 1, 2, 3]}
        _, entries = bt.parse_reply(json.dumps({"entries": [entry]}, ensure_ascii=False), 3)
        self.assertEqual(len(entries[0]["forms"]), 12)
        self.assertEqual(len(entries[0]["zh_variants"]), 8)
        self.assertEqual(entries[0]["zh_variants"][0], "a")
        self.assertEqual(entries[0]["evidence"], [1, 2, 3])

    def test_schema_requires_all_fields(self):
        item = bt.RESPONSE_SCHEMA["properties"]["entries"]["items"]
        self.assertEqual(set(item["required"]), set(item["properties"]))
        self.assertEqual(item["properties"]["kind"]["enum"], list(bt.KINDS))
        self.assertEqual(item["properties"]["confidence"]["enum"], ["high", "medium", "low"])
        forms = item["properties"]["forms"]
        self.assertEqual(forms["maxItems"], 12)
        self.assertEqual(forms["items"]["required"], ["ja", "zh"])
        self.assertFalse(forms["items"]["additionalProperties"])
        self.assertNotIn("ja_variants", item["properties"])

    def test_prompt_states_granularity_and_variant_rules(self):
        prompt = bt.SYSTEM_PROMPT
        for needle in ("绝不收", "第三适格者", "指同一对象", "绝不把全名填给只说了姓或名的写法", "固定身份的称号", "forms"):
            self.assertIn(needle, prompt)


class ShapeTests(unittest.TestCase):
    @staticmethod
    def parse(entry: dict) -> tuple[list, list]:
        dropped: list = []
        _, entries = bt.parse_reply(json.dumps({"entries": [entry]}, ensure_ascii=False), 10, dropped)
        return entries, dropped

    def test_annotated_entity_zh_drops_whole_entity_and_is_recorded(self):
        good = {"entity_ja": "凛", "zh": "凛", "forms": [{"ja": "凛", "zh": "凛"}]}
        bad = {"entity_ja": "マキリ", "kind": "org", "zh": "间桐(误识为Makiri)",
               "forms": [{"ja": "マキリ", "zh": "间桐"}]}
        dropped: list = []
        _, entries = bt.parse_reply(json.dumps({"entries": [bad, good]}, ensure_ascii=False), 10, dropped)
        self.assertEqual([e["entity_ja"] for e in entries], ["凛"])
        self.assertEqual(dropped, [{"entity_ja": "マキリ", "field": "zh", "value": "间桐(误识为Makiri)"}])

    def test_bad_form_zh_drops_only_that_form(self):
        entry = {"entity_ja": "間桐", "zh": "间桐", "forms": [
            {"ja": "間桐", "zh": "间桐"}, {"ja": "マトウ", "zh": "间桐（误识）"}, {"ja": "マキリ", "zh": "Makiri"}]}
        entries, dropped = self.parse(entry)
        self.assertEqual([f["ja"] for f in entries[0]["forms"]], ["間桐", "マキリ"])
        self.assertEqual(dropped, [{"entity_ja": "間桐", "field": "form.zh", "ja": "マトウ", "value": "间桐（误识）"}])

    def test_bad_variant_drops_only_that_variant(self):
        entry = {"entity_ja": "セイバー", "zh": "Saber", "forms": [{"ja": "セイバー", "zh": "Saber"}],
                 "zh_variants": ["塞巴", "Saber Alter", "Unit-01", "Saber"]}
        entries, dropped = self.parse(entry)
        self.assertEqual(entries[0]["zh_variants"], ["塞巴", "Saber"])
        self.assertEqual([(d["field"], d["value"]) for d in dropped],
                         [("zh_variants", "Saber Alter"), ("zh_variants", "Unit-01")])

    def test_ascii_names_and_long_separated_names_pass(self):
        long_name = "伊莉雅丝菲尔·冯·爱因兹贝伦"  # 去掉间隔号后 12 字
        for zh in ("Saber", "Rider", long_name, "阿尔托莉雅・潘德拉贡"):
            entry = {"entity_ja": "セイバー", "zh": zh, "forms": [{"ja": "セイバー", "zh": zh}], "zh_variants": [zh]}
            entries, dropped = self.parse(entry)
            self.assertEqual((entries[0]["zh"], dropped), (zh, []), zh)
            self.assertEqual(entries[0]["zh_variants"], [zh])

    def test_length_and_character_limits(self):
        # 13 字、仅间隔号、含数字、含空白、全角标点、全角字母
        for zh in ("一二三四五六七八九十甲乙丙", "·", "真嗣2", "真 嗣", "真嗣，", "ｓａｂｅｒ", ""):
            self.assertIsNone(bt._clean_zh(zh), zh)
        self.assertEqual(bt._clean_zh(" 真嗣 "), "真嗣")
        self.assertEqual(bt._clean_zh("一二三四五六七八九十甲乙"), "一二三四五六七八九十甲乙")


class HonorificTests(unittest.TestCase):
    @staticmethod
    def parse(entries: list[dict]) -> tuple[list, list]:
        honorific: list = []
        _, out = bt.parse_reply(json.dumps({"entries": entries}, ensure_ascii=False), 10, None, honorific)
        return out, honorific

    def test_is_honorific_matching(self):
        for ja in ("父さん", "お父さん", "父様", "父上", "ご父さん", "兄ちゃん", "お兄ちゃん", "先輩", "あの人", "君",
                   "お主", "僕", "お 父 さ ん", "皆さん", "みんな", "おじさん"):
            self.assertTrue(bt.is_honorific(ja), ja)
        for ja in ("衛宮くん", "衛宮君", "衛宮士郎", "シロウ", "遠坂", "桜ちゃん", "セイバー", "マスター", "サーヴァント",
                   "さん", "くん", "お", ""):
            self.assertFalse(bt.is_honorific(ja), ja)

    def test_honorific_form_dropped_and_recorded(self):
        entry = {"entity_ja": "遠坂時臣", "zh": "远坂时臣", "forms": [
            {"ja": "遠坂時臣", "zh": "远坂时臣"}, {"ja": "父さん", "zh": "时臣"}, {"ja": "時臣", "zh": "时臣"}]}
        entries, honorific = self.parse([entry])
        self.assertEqual([f["ja"] for f in entries[0]["forms"]], ["遠坂時臣", "時臣"])
        self.assertEqual(honorific, [{"entity_ja": "遠坂時臣", "ja": "父さん"}])

    def test_entity_with_only_honorific_forms_dropped(self):
        bad = {"entity_ja": "父さん", "zh": "父亲", "forms": [{"ja": "お父さん", "zh": "父亲"}]}
        good = {"entity_ja": "凛", "zh": "凛", "forms": [{"ja": "凛", "zh": "凛"}]}
        entries, honorific = self.parse([bad, good])
        self.assertEqual([e["entity_ja"] for e in entries], ["凛"])
        self.assertEqual(honorific, [{"entity_ja": "父さん", "ja": "父さん"}, {"entity_ja": "父さん", "ja": "お父さん"}])

    def test_name_with_kun_suffix_kept(self):
        entry = {"entity_ja": "衛宮士郎", "zh": "卫宫士郎", "forms": [
            {"ja": "衛宮士郎", "zh": "卫宫士郎"}, {"ja": "衛宮くん", "zh": "卫宫"}, {"ja": "衛宮君", "zh": "卫宫"}]}
        entries, honorific = self.parse([entry])
        self.assertEqual(len(entries[0]["forms"]), 3)
        self.assertEqual(honorific, [])

    def test_all_honorifics_in_list_are_matched(self):
        for ja in bt.HONORIFIC_JA:
            self.assertTrue(bt.is_honorific(ja), ja)


class PromptV5Tests(unittest.TestCase):
    # 第六轮试过把示例全换成虚构作品（v6）：模型更常把写法挂错实体，已回退到 v5 的真实作品示例。

    def test_version_is_v5(self):
        self.assertEqual(bt.PROMPT_VERSION, "build-table-prompt-v5")

    def test_prompt_keeps_every_illustration(self):
        prompt = bt.SYSTEM_PROMPT
        for needle in ("汉字误替", "片假名变体", "写错的汉字", "片假名被转成平假名", "粒度必须一致", "绝不能合并成一个实体",
                       "不属于", "裸形式", "不带助词", "残留的中文字", "zh_variants", "正例", "反例", "不成词的碎片",
                       "祷词"):
            self.assertIn(needle, prompt)


class JaShapeTests(unittest.TestCase):
    KEEP = ("しろ", "あすか", "あすかー", "白", "衛宮くん", "衛宮君", "お嬢", "ご主人", "桜ちゃん", "エミヤ・キリツグ",
            "キシュア・ゼルレッチ・シュバインオーグ", "遠坂", "的場", "セイバー", "佐々木")
    DROP = ("アサシンと契約を結べ", "サーヴァント ライダー", "アインツベルンの聖杯が取り込んだアーチャ", "キリツグは 前回",
            "トウサカの庭に埋めてきた", "アインツベルンとマキリー遠坂の御三家は", "的レイ", "アスカの代わりに?", "Shirou",
            "士郎1", "シンジを呼んでいる", "シンジ、", "「シンジ」", "ｓａｂｅｒ", "", "   ", "・", "ー", "あの人の", "言うた",
            "x" * 21, "ア" * 21, "鷺宮 タクミ", "間桐 さくら", None, 5)

    def test_keep_and_drop_examples(self):
        for ja in self.KEEP:
            self.assertEqual(bt._clean_ja(ja), ja, ja)
        for ja in self.DROP:
            self.assertIsNone(bt._clean_ja(ja), ja)

    def test_whitespace_removed_only_between_kanji(self):
        self.assertEqual(bt._clean_ja("間桐 桜"), "間桐桜")
        self.assertEqual(bt._clean_ja(" 間桐\u3000桜 "), "間桐桜")  # 全角空格、首尾空白
        self.assertEqual(bt._clean_ja("衛宮 士 郎"), "衛宮士郎")
        for ja in ("間桐 サクラ", "マキリ 桜", "キリツグは 前回", "サーヴァント ライダー"):
            self.assertIsNone(bt._clean_ja(ja), ja)

    def test_length_boundary(self):
        self.assertEqual(bt._clean_ja("ア" * 20), "ア" * 20)
        self.assertIsNone(bt._clean_ja("ア" * 21))
        # 间隔号计入长度：5 组"アアア・"去掉末尾间隔号共 19 字，6 组共 23 字
        self.assertIsNotNone(bt._clean_ja(("アアア・" * 5)[:-1]))
        self.assertIsNone(bt._clean_ja(("アアア・" * 6)[:-1]))

    def test_hiragana_only_inside_prefix_and_suffix(self):
        for ja in ("お嬢", "ご主人", "衛宮くん", "衛宮さん", "衛宮ちゃん", "衛宮さま", "衛宮たん", "おセイバーさん"):
            self.assertEqual(bt._clean_ja(ja), ja, ja)
        for ja in ("衛宮のくん", "衛宮は", "遠坂が", "シンジと", "お嬢の", "お衛宮お", "おかしな士郎", "士郎へ"):
            self.assertIsNone(bt._clean_ja(ja), ja)

    def test_nfkc_normalised(self):
        self.assertEqual(bt._clean_ja("ｾｲﾊﾞｰ"), "セイバー")  # 半角片假名
        self.assertIsNone(bt._clean_ja("Ｓａｂｅｒ"))  # 全角字母规范化为 ASCII 后丢弃

    @staticmethod
    def parse(entries: list[dict]) -> tuple[list, list]:
        ja_shape: list = []
        _, out = bt.parse_reply(json.dumps({"entries": entries}, ensure_ascii=False), 10, None, None, ja_shape)
        return out, ja_shape

    def test_forms_filtered_recorded_and_deduped(self):
        entry = {"entity_ja": "遠坂凛", "zh": "远坂凛", "forms": [
            {"ja": "遠坂凛", "zh": "远坂凛"}, {"ja": "遠坂 凛", "zh": "远坂凛"}, {"ja": "凛", "zh": "凛"},
            {"ja": "トウサカの庭に埋めてきた", "zh": "远坂"}, {"ja": "サーヴァント ライダー", "zh": "骑兵"},
            {"ja": "Rin", "zh": "凛"}]}
        entries, ja_shape = self.parse([entry])
        self.assertEqual([f["ja"] for f in entries[0]["forms"]], ["遠坂凛", "凛"])
        self.assertEqual(ja_shape, [{"entity_ja": "遠坂凛", "ja": ja} for ja in
                                    ("トウサカの庭に埋めてきた", "サーヴァント ライダー", "Rin")])

    def test_shape_runs_before_honorific(self):
        entry = {"entity_ja": "時臣", "zh": "时臣", "forms": [
            {"ja": "時臣", "zh": "时臣"}, {"ja": "父さん", "zh": "时臣"}, {"ja": "あの人は", "zh": "时臣"}]}
        honorific: list = []
        ja_shape: list = []
        entries = bt.parse_reply(json.dumps({"entries": [entry]}, ensure_ascii=False), 10, None, honorific, ja_shape)[1]
        self.assertEqual([f["ja"] for f in entries[0]["forms"]], ["時臣"])
        self.assertEqual(honorific, [{"entity_ja": "時臣", "ja": "父さん"}])
        self.assertEqual(ja_shape, [{"entity_ja": "時臣", "ja": "あの人は"}])

    def test_entity_ja_with_whitespace_replaced_by_cleaned(self):
        entry = {"entity_ja": "間桐 桜", "zh": "间桐樱", "forms": [{"ja": "間桐 桜", "zh": "间桐樱"}, {"ja": "桜", "zh": "樱"}]}
        entries, ja_shape = self.parse([entry])
        self.assertEqual(entries[0]["entity_ja"], "間桐桜")
        self.assertEqual([f["ja"] for f in entries[0]["forms"]], ["間桐桜", "桜"])
        self.assertEqual(ja_shape, [])

    def test_bad_entity_ja_replaced_by_first_kept_form(self):
        entry = {"entity_ja": "アサシンと契約を結べ", "zh": "暗杀者", "forms": [
            {"ja": "アサシンと契約を結べ", "zh": "暗杀者"}, {"ja": "アサシン", "zh": "暗杀者"}, {"ja": "暗殺者", "zh": "暗杀者"}]}
        entries, ja_shape = self.parse([entry])
        self.assertEqual(entries[0]["entity_ja"], "アサシン")
        self.assertEqual([f["ja"] for f in entries[0]["forms"]], ["アサシン", "暗殺者"])
        self.assertEqual(ja_shape, [{"entity_ja": "アサシンと契約を結べ", "ja": "アサシンと契約を結べ"}])

    def test_entity_dropped_when_no_form_survives(self):
        bad = {"entity_ja": "サーヴァント ライダー", "zh": "骑兵", "forms": [{"ja": "サーヴァント ライダー", "zh": "骑兵"},
                                                                   {"ja": "Rider", "zh": "骑兵"}]}
        good = {"entity_ja": "凛", "zh": "凛", "forms": [{"ja": "凛", "zh": "凛"}]}
        entries, ja_shape = self.parse([bad, good])
        self.assertEqual([e["entity_ja"] for e in entries], ["凛"])
        self.assertEqual(ja_shape, [
            {"entity_ja": "サーヴァント ライダー", "ja": "サーヴァント ライダー"},
            {"entity_ja": "サーヴァント ライダー", "ja": "Rider"},
            {"entity_ja": "サーヴァント ライダー", "field": "entity", "ja": "サーヴァント ライダー"}])

    def test_all_bad_raises_like_before(self):
        entry = {"entity_ja": "アサシンと契約を結べ", "zh": "暗杀者", "forms": [{"ja": "アサシンと契約を結べ", "zh": "暗杀者"}]}
        with self.assertRaises(ValueError):
            self.parse([entry])

    def test_cleaned_entity_collides_with_earlier_entity_dropped(self):
        a = {"entity_ja": "間桐桜", "zh": "间桐樱", "forms": [{"ja": "間桐桜", "zh": "间桐樱"}]}
        b = {"entity_ja": "間桐 桜", "zh": "间桐樱", "forms": [{"ja": "間桐 桜", "zh": "间桐樱"}]}
        entries, _ = self.parse([a, b])
        self.assertEqual([e["entity_ja"] for e in entries], ["間桐桜"])


class ConfidenceTests(unittest.TestCase):
    @staticmethod
    def parse(kind: str, confidence: str, evidence: list[int]) -> dict:
        entry = {"entity_ja": "桜", "kind": kind, "confidence": confidence, "zh": "樱",
                 "forms": [{"ja": "桜", "zh": "樱"}], "evidence": evidence}
        return bt.parse_reply(json.dumps({"entries": [entry]}), 10)[1][0]

    def test_prompt_v5_states_confidence_criteria(self):
        self.assertEqual(bt.PROMPT_VERSION, "build-table-prompt-v5")
        prompt = bt.SYSTEM_PROMPT
        for needle in ("≥3", "medium", "low", "父さん", "キリエ・エレイソン", "シンジ 与 シロウ", "マトウ増健"):
            self.assertIn(needle, prompt)
        self.assertIn('"confidence": "medium"', prompt)  # JSON 示例里有 medium 条目
        self.assertIn("绝不能合并成一个实体", prompt)

    def test_person_high_with_two_cues_downgraded_to_medium(self):
        entry = self.parse("person", "high", [3, 5])
        self.assertEqual(entry["confidence"], "medium")
        self.assertEqual(entry["confidence_note"], "downgraded: evidence<3")

    def test_invalid_cues_do_not_count_toward_threshold(self):
        entry = self.parse("person", "high", [3, 5, 99, 0])  # 99、0 越界，被剔除
        self.assertEqual(entry["confidence"], "medium")

    def test_person_high_with_three_cues_unchanged(self):
        entry = self.parse("person", "high", [3, 5, 7])
        self.assertEqual(entry["confidence"], "high")
        self.assertNotIn("confidence_note", entry)

    def test_non_person_and_non_high_not_downgraded(self):
        for kind in ("class", "org", "place", "other"):
            entry = self.parse(kind, "high", [1])
            self.assertEqual(entry["confidence"], "high")
            self.assertNotIn("confidence_note", entry)
        for confidence in ("medium", "low"):
            entry = self.parse("person", confidence, [])
            self.assertEqual(entry["confidence"], confidence)
            self.assertNotIn("confidence_note", entry)


def reply_text(entity: str = "桜", evidence: tuple[int, ...] = (1, 2, 3)) -> str:
    entry = {"entity_ja": entity, "kind": "person", "confidence": "high", "zh": "樱",
             "forms": [{"ja": entity, "zh": "樱"}], "zh_variants": [], "evidence": list(evidence)}
    return json.dumps({"work_guess": "作品", "entries": [entry]}, ensure_ascii=False)


def response(content: str, finish_reason: str = "stop", usage: dict | None = ...) -> dict:
    result = {"model": "m", "choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}
    if usage is ...:
        usage = {"prompt_tokens": 123, "completion_tokens": 45}
    if usage is not None:
        result["usage"] = usage
    return result


class FakeServer:
    """记录请求体与 tokenize 输入的假 server；`responses` 按次序吐出。"""

    def __init__(self, *responses: dict, system_tokens: int = 60, user_tokens: int = 40):
        self.responses = list(responses)
        self.bodies: list[dict] = []
        self.tokenized: list[str] = []
        self.system_tokens = system_tokens
        self.user_tokens = user_tokens

    def chat(self, body: dict) -> dict:
        self.bodies.append(body)
        return self.responses.pop(0)

    def tokenize(self, text: str) -> int:
        self.tokenized.append(text)
        return self.system_tokens if text == bt.SYSTEM_PROMPT else self.user_tokens


class BuildTableTests(unittest.TestCase):
    def test_success_payload_and_request_body(self):
        server = FakeServer(response(json.dumps(GOOD, ensure_ascii=False)))
        result = bt.build_table(document(), server.chat, server.tokenize, 20261019)
        self.assertEqual((result.status, result.attempts), ("ok", 1))
        payload = result.payload
        self.assertEqual(payload["schema"], "name-table-v2")
        self.assertEqual(payload["prompt_version"], "build-table-prompt-v5")
        self.assertEqual(payload["work_guess"], "新世紀エヴァンゲリオン")
        # GOOD 的 evidence 只有 2 条有效 cue（2、3），person 的 high 被降级
        self.assertEqual(payload["entries"][0]["confidence"], "medium")
        self.assertEqual(payload["entries"][0]["confidence_note"], "downgraded: evidence<3")
        self.assertEqual(payload["build"], {"status": "ok", "reason": None})
        meta = payload["meta"]
        self.assertEqual((meta["seed"], meta["attempt"], meta["prompt_tokens"], meta["completion_tokens"]),
                         (20261019, 1, 123, 45))
        self.assertEqual((meta["dropped_shape"], meta["dropped_honorific"], meta["dropped_ja_shape"]), ([], [], []))
        self.assertIsInstance(meta["seconds"], float)
        self.assertAlmostEqual(result.seconds, meta["seconds"], places=1)
        # tokenize 对 system、user 两段文本各调一次
        self.assertEqual(server.tokenized, [m["content"] for m in bt.build_messages(document())])
        body = server.bodies[0]
        self.assertEqual(body["messages"], bt.build_messages(document()))
        self.assertEqual((body["temperature"], body["top_p"], body["top_k"], body["min_p"], body["presence_penalty"]),
                         (0.7, 0.8, 20, 0.0, 1.5))
        self.assertEqual((body["seed"], body["max_tokens"], body["stream"]), (20261019, 4096, False))
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertEqual(body["response_format"]["json_schema"]["name"], "name_table")
        self.assertIs(body["response_format"]["json_schema"]["schema"], bt.RESPONSE_SCHEMA)

    def test_missing_usage_is_none(self):
        for usage in (None, {}):
            server = FakeServer(response(reply_text(), usage=usage))
            meta = bt.build_table(document(), server.chat, server.tokenize, 1).payload["meta"]
            self.assertEqual((meta["prompt_tokens"], meta["completion_tokens"]), (None, None))

    def test_dropped_items_recorded_in_meta(self):
        reply = {"entries": [{"entity_ja": "桜", "zh": "樱", "forms": [
            {"ja": "桜", "zh": "樱"}, {"ja": "S", "zh": "樱(注)"}, {"ja": "父さん", "zh": "樱"},
            {"ja": "桜が咲いた", "zh": "樱"}]}]}
        server = FakeServer(response(json.dumps(reply, ensure_ascii=False)))
        meta = bt.build_table(document(), server.chat, server.tokenize, 1).payload["meta"]
        self.assertEqual(meta["dropped_shape"], [{"entity_ja": "桜", "field": "form.zh", "ja": "S", "value": "樱(注)"}])
        self.assertEqual(meta["dropped_honorific"], [{"entity_ja": "桜", "ja": "父さん"}])
        self.assertEqual(meta["dropped_ja_shape"], [{"entity_ja": "桜", "ja": "桜が咲いた"}])

    def test_evidence_validated_against_max_cue_index(self):
        text = "7\n00:00:01,000 --> 00:00:02,000\nほう\n\n12\n00:00:03,000 --> 00:00:04,000\n東坂が\n"
        server = FakeServer(response(reply_text(evidence=(7, 12, 13, 2))))
        entries = bt.build_table(document(text), server.chat, server.tokenize, 1).payload["entries"]
        self.assertEqual(entries[0]["evidence"], [2, 7, 12])

    def test_length_first_then_success_bumps_seed(self):
        server = FakeServer(response(reply_text(), "length"), response(reply_text()))
        result = bt.build_table(document(), server.chat, server.tokenize, 100)
        self.assertEqual([b["seed"] for b in server.bodies], [100, 101])
        self.assertEqual((result.status, result.attempts), ("ok", 2))
        self.assertEqual(result.payload["meta"]["seed"], 101)
        self.assertEqual(result.payload["meta"]["attempt"], 2)
        self.assertEqual(len(result.payload["entries"]), 1)

    def test_invalid_json_then_success(self):
        server = FakeServer(response("不是 JSON"), response(reply_text()))
        result = bt.build_table(document(), server.chat, server.tokenize, 5)
        self.assertEqual(([b["seed"] for b in server.bodies], result.status), ([5, 6], "ok"))

    def test_two_failures_return_failed_empty_table(self):
        server = FakeServer(response(reply_text(), "length"), response("不是 JSON\n第二行"))
        result = bt.build_table(document(), server.chat, server.tokenize, 100)
        self.assertEqual((result.status, result.attempts, len(server.bodies)), ("failed", 2, 2))
        payload = result.payload
        self.assertEqual((payload["entries"], payload["work_guess"]), ([], None))
        self.assertEqual(payload["build"]["status"], "failed")
        # 原因是最后一次错误的首行，不含回复正文
        self.assertNotIn("\n", payload["build"]["reason"])
        self.assertNotIn("第二行", payload["build"]["reason"])
        self.assertEqual((payload["meta"]["seed"], payload["meta"]["attempt"]), (101, 2))

    def test_two_length_failures_reason(self):
        server = FakeServer(response(reply_text(), "length"), response(reply_text(), "length"))
        result = bt.build_table(document(), server.chat, server.tokenize, 1)
        self.assertEqual(result.status, "failed")
        self.assertIn("finish_reason=length", result.payload["build"]["reason"])

    def test_prompt_over_budget_skips_chat(self):
        def chat(body):
            raise AssertionError("chat must not be called")

        # 两段各自都不超预算，只有相加才超
        server = FakeServer(system_tokens=bt.PROMPT_BUDGET // 2, user_tokens=bt.PROMPT_BUDGET - bt.PROMPT_BUDGET // 2 + 1)
        result = bt.build_table(document(), chat, server.tokenize, 7)
        self.assertEqual(len(server.tokenized), 2)
        self.assertEqual((result.status, result.attempts), ("too_long", 0))
        self.assertEqual((result.payload["entries"], result.payload["work_guess"]), ([], None))
        self.assertEqual(result.payload["build"]["status"], "too_long")
        self.assertIn(str(bt.PROMPT_BUDGET + 1), result.payload["build"]["reason"])
        self.assertEqual(result.payload["meta"]["seed"], 7)

    def test_prompt_exactly_at_budget_is_sent(self):
        server = FakeServer(response(reply_text()), system_tokens=bt.PROMPT_BUDGET // 2,
                            user_tokens=bt.PROMPT_BUDGET - bt.PROMPT_BUDGET // 2)
        self.assertEqual(bt.build_table(document(), server.chat, server.tokenize, 1).status, "ok")
        self.assertEqual((len(server.tokenized), len(server.bodies)), (2, 1))

    def test_user_message_alone_under_budget_but_system_pushes_over(self):
        # 回归：只数 user 消息会放过这个提示（总数超预算，请求会撑破 20480 上下文）
        server = FakeServer(system_tokens=1500, user_tokens=bt.PROMPT_BUDGET - 1000)
        result = bt.build_table(document(), server.chat, server.tokenize, 1)
        self.assertEqual((result.status, server.bodies), ("too_long", []))
        self.assertIn(str(1500 + bt.PROMPT_BUDGET - 1000), result.payload["build"]["reason"])

    def test_zero_cues_calls_nothing(self):
        def boom(*args):
            raise AssertionError("must not be called")

        result = bt.build_table(parse_srt(""), boom, boom, 9)
        self.assertEqual((result.status, result.attempts, result.seconds), ("ok", 0, 0.0))
        self.assertEqual((result.payload["entries"], result.payload["work_guess"]), ([], None))
        self.assertEqual(result.payload["build"], {"status": "ok", "reason": None})
        self.assertEqual(result.payload["schema"], "name-table-v2")

    def test_budget_is_context_minus_output_minus_guard(self):
        self.assertEqual(bt.PROMPT_BUDGET, 20480 - 4096 - 512)


if __name__ == "__main__":
    unittest.main()
