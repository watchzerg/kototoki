"""专名建表的离线测试：不联网、不加载模型。

Parse／Cap／Shape／Honorific／PromptV5／JaShape／Confidence 用例移植自
`archive/2026-11-18-pre-research-restructure:experiments/name_consistency/test_build_table.py`，去掉 renormalize 与 main；
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


class ParseTests(unittest.TestCase):
    def test_clean_json_normalised(self):
        guess, entries = bt.parse_reply(json.dumps(GOOD, ensure_ascii=False), 3)
        self.assertEqual(guess, "新世紀エヴァンゲリオン")
        entry = entries[0]
        self.assertEqual([f["ja"] for f in entry["forms"]], ["碇シンジ", "シンジ", "真司"])
        self.assertEqual(entry["forms"][1], {"ja": "シンジ", "zh": "真嗣"})
        self.assertEqual(entry["zh_variants"], ["真司", "Shinji"])
        self.assertEqual(entry["evidence"], [2, 3])


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

    @staticmethod
    def parse(entries: list[dict]) -> tuple[list, list]:
        ja_shape: list = []
        _, out = bt.parse_reply(json.dumps({"entries": entries}, ensure_ascii=False), 10, None, None, ja_shape)
        return out, ja_shape


class ConfidenceTests(unittest.TestCase):
    @staticmethod
    def parse(kind: str, confidence: str, evidence: list[int]) -> dict:
        entry = {"entity_ja": "桜", "kind": kind, "confidence": confidence, "zh": "樱",
                 "forms": [{"ja": "桜", "zh": "樱"}], "evidence": evidence}
        return bt.parse_reply(json.dumps({"entries": [entry]}), 10)[1][0]

    def test_person_high_with_two_cues_downgraded_to_medium(self):
        entry = self.parse("person", "high", [3, 5])
        self.assertEqual(entry["confidence"], "medium")
        self.assertEqual(entry["confidence_note"], "downgraded: evidence<3")

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
        self.assertEqual((body["seed"], body["max_tokens"], body["stream"]), (20261019, 16384, False))
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(body["model"], "qwen3.8-flash-next-iq3_s")
        self.assertNotIn("response_format", body)  # Strata 会据此改写提示（v13 §4.0），不发
        self.assertEqual(list(body), ["messages", "temperature", "top_p", "top_k", "min_p", "presence_penalty",
                                      "seed", "max_tokens", "chat_template_kwargs", "stream", "model"])

    def test_length_first_then_success_bumps_seed(self):
        server = FakeServer(response(reply_text(), "length"), response(reply_text()))
        result = bt.build_table(document(), server.chat, server.tokenize, 100)
        self.assertEqual([b["seed"] for b in server.bodies], [100, 101])
        self.assertEqual((result.status, result.attempts), ("ok", 2))
        self.assertEqual(result.payload["meta"]["seed"], 101)
        self.assertEqual(result.payload["meta"]["attempt"], 2)
        self.assertEqual(len(result.payload["entries"]), 1)

    def test_empty_reply_is_accepted_with_one_request(self):
        server = FakeServer(response('{"work_guess": null, "entries": []}'), response(reply_text()))
        result = bt.build_table(document(), server.chat, server.tokenize, 100)
        self.assertEqual((result.status, result.attempts, len(server.bodies)), ("ok", 1, 1))
        self.assertEqual((result.payload["entries"], result.payload["build"]), ([], {"status": "ok", "reason": None}))

    def test_five_failures_return_failed_empty_table(self):
        server = FakeServer(*[response(reply_text(), "length")] * 4, response("不是 JSON\n第二行"))
        result = bt.build_table(document(), server.chat, server.tokenize, 100)
        self.assertEqual((result.status, result.attempts, len(server.bodies)), ("failed", 5, 5))
        self.assertEqual([b["seed"] for b in server.bodies], [100, 101, 102, 103, 104])
        payload = result.payload
        self.assertEqual((payload["entries"], payload["work_guess"]), ([], None))
        self.assertEqual(payload["build"]["status"], "failed")
        # 原因是最后一次错误的首行，不含回复正文
        self.assertNotIn("\n", payload["build"]["reason"])
        self.assertNotIn("第二行", payload["build"]["reason"])
        self.assertEqual((payload["meta"]["seed"], payload["meta"]["attempt"]), (104, 5))

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

    def test_zero_cues_calls_nothing(self):
        def boom(*args):
            raise AssertionError("must not be called")

        result = bt.build_table(parse_srt(""), boom, boom, 9)
        self.assertEqual((result.status, result.attempts, result.seconds), ("ok", 0, 0.0))
        self.assertEqual((result.payload["entries"], result.payload["work_guess"]), ([], None))
        self.assertEqual(result.payload["build"], {"status": "ok", "reason": None})
        self.assertEqual(result.payload["schema"], "name-table-v2")




if __name__ == "__main__":
    unittest.main()
