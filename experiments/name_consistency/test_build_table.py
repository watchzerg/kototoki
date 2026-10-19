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
        forms = [{"ja": f"写法{i}", "zh": f"译{i}"} for i in range(20)]
        entry = {"entity_ja": "写法0", "zh": "译0", "forms": forms,
                 "zh_variants": ["a"] * 3 + [f"译{i}" for i in range(12)], "evidence": [1, 1, 2, 3]}
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
        self.assertEqual(table["prompt_version"], "build-table-prompt-v4")
        self.assertEqual(table["entries"][0]["confidence"], "high")
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
