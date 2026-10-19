"""build_table 的离线测试：不联网、不加载模型。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from experiments.name_consistency import build_table as bt

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


def write_srt(directory: str) -> Path:
    path = Path(directory) / "ja.srt"
    path.write_text(SRT, encoding="utf-8")
    return path


class RenderTests(unittest.TestCase):
    def test_timestamps_stripped_indices_kept_multiline_joined(self):
        with tempfile.TemporaryDirectory() as tmp:
            cues = bt.read_srt_cues(write_srt(tmp))
        self.assertEqual(cues, [(1, "お主は分かっておるな"), (2, "東坂が 来たのか"), (3, "ほう")])
        rendered = bt.render_lines(cues)
        self.assertEqual(rendered.splitlines()[1], "2\t東坂が 来たのか")
        self.assertNotIn("-->", rendered)

    def test_prompt_contains_lines_and_instructions(self):
        messages = bt.build_messages([(1, "ほう"), (2, "東坂が")])
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("2\t東坂が", messages[1]["content"])
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
        for needle in ("绝不收", "第七观测者", "指同一对象", "绝不把全名填给只说了姓或名的写法", "固定身份的称号", "forms"):
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

    def test_main_writes_meta_dropped_shape(self):
        reply = {"entries": [{"entity_ja": "桜", "zh": "樱", "forms": [{"ja": "桜", "zh": "樱"}, {"ja": "S", "zh": "樱(注)"}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            srt, out = write_srt(tmp), Path(tmp) / "table.json"
            response = {"model": "m", "choices": [{"message": {"content": json.dumps(reply, ensure_ascii=False)},
                                                   "finish_reason": "stop"}], "usage": {}}
            with mock.patch.object(bt, "post_chat", lambda *a: response):
                self.assertEqual(bt.main(["--srt", str(srt), "--work", "w", "--out", str(out)]), 0)
            table = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(table["meta"]["dropped_shape"],
                         [{"entity_ja": "桜", "field": "form.zh", "ja": "S", "value": "樱(注)"}])


class RenormalizeTests(unittest.TestCase):
    def test_renormalize_reuses_raw_reply_without_network(self):
        reply = {"entries": [
            {"entity_ja": "桜", "zh": "樱", "forms": [{"ja": "桜", "zh": "樱"}]},
            {"entity_ja": "マキリ", "zh": "间桐(误识为Makiri)", "forms": [{"ja": "マキリ", "zh": "间桐"}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            srt, old = write_srt(tmp), Path(tmp) / "old.json"
            reply_path = Path(tmp) / "old.json.reply.txt"
            reply_path.write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
            old.write_text(json.dumps({"schema": "name-table-v2", "work": "w", "prompt_version": "p", "source_srt": str(srt),
                                       "entries": [], "raw_reply_path": str(reply_path)}), encoding="utf-8")
            new = Path(tmp) / "new.json"
            with mock.patch.object(bt, "post_chat", side_effect=AssertionError("no network")):
                self.assertEqual(bt.main(["--renormalize", str(old), "--out", str(new)]), 0)
            table = json.loads(new.read_text(encoding="utf-8"))
        self.assertEqual([e["entity_ja"] for e in table["entries"]], ["桜"])
        self.assertEqual(table["meta"]["dropped_shape"][0]["entity_ja"], "マキリ")
        self.assertEqual((table["work"], table["prompt_version"]), ("w", "p"))


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

    def test_main_writes_meta_and_renormalize_applies_blacklist(self):
        reply = {"entries": [{"entity_ja": "時臣", "zh": "时臣", "forms": [
            {"ja": "時臣", "zh": "时臣"}, {"ja": "父さん", "zh": "时臣"}]}]}
        text = json.dumps(reply, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            srt, out = write_srt(tmp), Path(tmp) / "table.json"
            seeds = []

            def fake_post(url, body, timeout):
                seeds.append(body["seed"])
                return {"model": "m", "choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {}}

            with mock.patch.object(bt, "post_chat", fake_post):
                self.assertEqual(bt.main(["--srt", str(srt), "--work", "w", "--out", str(out), "--seed", "7"]), 0)
                table = json.loads(out.read_text(encoding="utf-8"))
                self.assertEqual(seeds, [7])
                self.assertEqual(table["meta"], {"seed": 7, "dropped_shape": [], "dropped_ja_shape": [],
                                                 "dropped_honorific": [{"entity_ja": "時臣", "ja": "父さん"}]})
                # 旧表（无 meta）重算：seed 从配对的请求文件取回
                old = json.loads(out.read_text(encoding="utf-8"))
                del old["meta"]
                out.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
                new = Path(tmp) / "new.json"
                self.assertEqual(bt.main(["--renormalize", str(out), "--out", str(new)]), 0)
            renorm = json.loads(new.read_text(encoding="utf-8"))
        self.assertEqual(renorm["meta"]["seed"], 7)
        self.assertEqual(renorm["meta"]["dropped_honorific"], [{"entity_ja": "時臣", "ja": "父さん"}])
        self.assertEqual([f["ja"] for f in renorm["entries"][0]["forms"]], ["時臣"])

    def test_default_seed_unchanged_and_retry_bumps(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt, out = write_srt(tmp), Path(tmp) / "table.json"
            seeds = []

            def fake_post(url, body, timeout):
                seeds.append(body["seed"])
                finish = "length" if len(seeds) == 1 else "stop"
                return {"model": "m", "choices": [{"message": {"content": json.dumps(GOOD, ensure_ascii=False)},
                                                   "finish_reason": finish}], "usage": {}}

            with mock.patch.object(bt, "post_chat", fake_post):
                bt.main(["--srt", str(srt), "--work", "w", "--out", str(out), "--seed", "100"])
            table = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(seeds, [100, 101])
        self.assertEqual(table["meta"]["seed"], 101)


class PromptV6Tests(unittest.TestCase):
    # 真实作品（EVA、Fate）的名字会污染输出：提示里只许出现虚构的示例名。
    REAL_WORK_NAMES = ("碇", "シンジ", "真嗣", "真司", "アスカ", "綾波", "绫波", "レイ", "明日香", "初号機", "初号机",
                       "弐号機", "使徒", "チルドレン", "適格者", "适格者", "エヴァ", "EVA", "Evangelion", "シロウ",
                       "士郎", "マトウ", "増健", "造剣", "キリエ", "エレイソン", "衛宮", "遠坂")

    def test_version_is_v6(self):
        self.assertEqual(bt.PROMPT_VERSION, "build-table-prompt-v6")

    def test_prompt_has_no_real_work_names(self):
        for name in self.REAL_WORK_NAMES:
            self.assertNotIn(name, bt.SYSTEM_PROMPT, name)

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

    def test_main_and_renormalize_write_meta_dropped_ja_shape(self):
        reply = {"entries": [{"entity_ja": "桜", "zh": "樱", "forms": [
            {"ja": "桜", "zh": "樱"}, {"ja": "桜が咲いた", "zh": "樱"}]}]}
        text = json.dumps(reply, ensure_ascii=False)
        expected = [{"entity_ja": "桜", "ja": "桜が咲いた"}]
        with tempfile.TemporaryDirectory() as tmp:
            srt, out, new = write_srt(tmp), Path(tmp) / "table.json", Path(tmp) / "new.json"
            response = {"model": "m", "choices": [{"message": {"content": text}, "finish_reason": "stop"}], "usage": {}}
            with mock.patch.object(bt, "post_chat", lambda *a: response):
                self.assertEqual(bt.main(["--srt", str(srt), "--work", "w", "--out", str(out)]), 0)
            table = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(table["meta"]["dropped_ja_shape"], expected)
            self.assertEqual([f["ja"] for f in table["entries"][0]["forms"]], ["桜"])
            # 重算读的是原始回复（旧表 meta 删掉也不影响），按当前规则同样丢掉句子写法
            del table["meta"]
            out.write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(bt, "post_chat", side_effect=AssertionError("no network")):
                self.assertEqual(bt.main(["--renormalize", str(out), "--out", str(new)]), 0)
            renorm = json.loads(new.read_text(encoding="utf-8"))
        self.assertEqual(renorm["meta"]["dropped_ja_shape"], expected)
        self.assertEqual([f["ja"] for f in renorm["entries"][0]["forms"]], ["桜"])


class ConfidenceTests(unittest.TestCase):
    @staticmethod
    def parse(kind: str, confidence: str, evidence: list[int]) -> dict:
        entry = {"entity_ja": "桜", "kind": kind, "confidence": confidence, "zh": "樱",
                 "forms": [{"ja": "桜", "zh": "樱"}], "evidence": evidence}
        return bt.parse_reply(json.dumps({"entries": [entry]}), 10)[1][0]

    def test_prompt_v6_states_confidence_criteria(self):
        self.assertEqual(bt.PROMPT_VERSION, "build-table-prompt-v6")
        prompt = bt.SYSTEM_PROMPT
        for needle in ("≥3", "medium", "low", "父さん", "ソルヴェ・テネブラス", "タクミ 与 タクマ", "ホズミ増尋"):
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


class MainTests(unittest.TestCase):
    def fake_response(self, reply: str) -> dict:
        return {"model": "Qwen3.8-27B", "choices": [{"message": {"content": reply}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45}}

    def test_end_to_end_writes_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = write_srt(tmp)
            out = Path(tmp) / "table.json"
            bodies = []

            def fake_post(url, body, timeout):
                bodies.append((url, body))
                return self.fake_response(json.dumps(GOOD, ensure_ascii=False))

            with mock.patch.object(bt, "post_chat", fake_post):
                code = bt.main(["--srt", str(srt), "--work", "hf3", "--out", str(out)])
            table = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertTrue(Path(table["raw_reply_path"]).exists())
        self.assertEqual(table["schema"], "name-table-v2")
        self.assertEqual(table["prompt_version"], "build-table-prompt-v6")
        # GOOD 的 evidence 只有 2 条有效 cue（2、3），person 的 high 被降级
        self.assertEqual(table["entries"][0]["confidence"], "medium")
        self.assertEqual(table["entries"][0]["confidence_note"], "downgraded: evidence<3")
        self.assertEqual(table["work"], "hf3")
        self.assertEqual(table["model"], {"url": "http://127.0.0.1:8081", "model_id_from_server": "Qwen3.8-27B", "think": False})
        self.assertEqual(table["timing"]["prompt_tokens"], 123)
        self.assertEqual(table["timing"]["completion_tokens"], 45)
        self.assertEqual(table["entries"][0]["entity_ja"], "碇シンジ")
        body = bodies[0][1]
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(body["temperature"], 0.7)
        self.assertEqual((body["top_p"], body["top_k"], body["presence_penalty"]), (0.8, 20, 1.5))
        self.assertEqual(body["seed"], 20261019)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertIs(body["response_format"]["json_schema"]["schema"], bt.RESPONSE_SCHEMA)
        self.assertEqual(table["timing"]["finish_reason"], "stop")

    def test_finish_reason_length_rejected_then_retry_with_bumped_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = write_srt(tmp)
            out = Path(tmp) / "table.json"
            seeds = []

            def fake_post(url, body, timeout):
                seeds.append(body["seed"])
                response = self.fake_response(json.dumps(GOOD, ensure_ascii=False))
                response["choices"][0]["finish_reason"] = "length" if len(seeds) == 1 else "stop"
                return response

            with mock.patch.object(bt, "post_chat", fake_post):
                code = bt.main(["--srt", str(srt), "--work", "w", "--out", str(out)])
            table = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(seeds, [20261019, 20261020])
        self.assertTrue(table["raw_reply_path"].endswith(".reply.2.txt"))

    def test_length_twice_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = write_srt(tmp)
            out = Path(tmp) / "table.json"

            def fake_post(url, body, timeout):
                response = self.fake_response(json.dumps(GOOD, ensure_ascii=False))
                response["choices"][0]["finish_reason"] = "length"
                return response

            with mock.patch.object(bt, "post_chat", fake_post):
                code = bt.main(["--srt", str(srt), "--work", "w", "--out", str(out)])
            self.assertNotEqual(code, 0)
            self.assertFalse(out.exists())

    def test_one_retry_then_fail_keeps_raw_replies(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = write_srt(tmp)
            out = Path(tmp) / "table.json"
            calls = []

            def fake_post(url, body, timeout):
                calls.append(1)
                return self.fake_response("不是 JSON")

            with mock.patch.object(bt, "post_chat", fake_post):
                code = bt.main(["--srt", str(srt), "--work", "w", "--out", str(out)])
            self.assertNotEqual(code, 0)
            self.assertEqual(len(calls), 2)
            self.assertFalse(out.exists())
            self.assertTrue(Path(f"{out}.reply.txt").exists())

    def test_dry_run_makes_no_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            srt = write_srt(tmp)
            out = Path(tmp) / "table.json"
            with mock.patch.object(bt, "post_chat", side_effect=AssertionError("no network")):
                code = bt.main(["--srt", str(srt), "--work", "w", "--out", str(out), "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn("2\t東坂が 来たのか", Path(f"{out}.prompt.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
