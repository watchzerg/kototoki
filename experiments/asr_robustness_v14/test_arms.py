"""v14 臂模块（guard／fill／correct／decode 纯函数）的离线单元测试：合成数据，不加载模型、不起 Strata、不读 `.local/`。"""

from __future__ import annotations

import json
import unittest
from typing import Any

from experiments.asr_robustness_v14 import correct, decode, fill, guard
from kototoki import artifacts, strata


def edits(s: int, d: int, i: int) -> dict[str, int]:
    return {"S": s, "D": d, "I": i}


def make_cues(n: int) -> list[dict[str, Any]]:
    return [{"index": k, "start": float(k), "end": k + 0.9, "text": f"あ{k}"} for k in range(1, n + 1)]


class BlankAlign(unittest.TestCase):
    def setUp(self):
        self.texts = ["あい", "うえお", "かき"]
        self.asr = {"original_segments": [{"text": t} for t in self.texts]}
        text = "".join(self.texts)
        self.align = {
            "text": text,
            "units": [{"text": ch, "char_start": k, "char_end": k + 1, "start": k * 0.1, "end": k * 0.1 + 0.1, "status": "ok"}
                      for k, ch in enumerate(text)],
            "original_segments": [{"text": t} for t in self.texts],
            "failed_windows": [],
            "identity": {"x": 1},
        }

    def test_blank_middle_window(self):
        out = guard.blank_align(self.align, self.asr, [1], "guard:test")
        self.assertEqual(out["text"], "あいかき")
        self.assertEqual([(u["char_start"], u["char_end"]) for u in out["units"]], [(0, 1), (1, 2), (2, 3), (3, 4)])
        self.assertEqual([u["text"] for u in out["units"]], ["あ", "い", "か", "き"])
        self.assertEqual(out["original_segments"][1]["text"], "")
        self.assertEqual(out["failed_windows"], [{"chunk_index": 1, "reason": "guard:test", "text": "うえお"}])
        self.assertNotIn("identity", out)
        # 输入不被改动
        self.assertEqual(self.align["original_segments"][1]["text"], "うえお")
        self.assertEqual(self.align["failed_windows"], [])
        self.assertEqual(len(self.align["units"]), 7)

    def test_text_mismatch_raises(self):
        self.align["text"] = "ちがう"
        with self.assertRaises(ValueError):
            guard.blank_align(self.align, self.asr, [1], "r")


class Gate(unittest.TestCase):
    def result(self, ii_after, iii_after):
        return {"hf-ii": {"before": edits(10, 5, 5), "after": ii_after},
                "hf-iii": {"before": edits(10, 5, 5), "after": iii_after}}

    def test_candidate(self):
        # 合计降 100 次编辑 / 22134 ≈ 0.45 pp
        gate = guard.gate(self.result(edits(10, 5, 5 - 20), edits(10, 5, 5 - 80)))
        self.assertEqual(guard.TOTAL_REF_CHARS, {"hf-ii": 10781, "hf-iii": 11353})
        self.assertEqual(gate["delta_edits"], {"hf-ii": -20, "hf-iii": -80})
        self.assertTrue(gate["both_drop"])
        self.assertGreaterEqual(gate["combined_drop_pp"], 0.3)
        self.assertEqual(gate["verdict"], "candidate")
        self.assertTrue(gate["passes"])

    def test_effective_but_insufficient(self):
        gate = guard.gate(self.result(edits(10, 5, 4), edits(10, 5, 4)))
        self.assertTrue(gate["both_drop"])
        self.assertLess(gate["combined_drop_pp"], 0.3)
        self.assertEqual(gate["verdict"], "effective-but-insufficient")
        self.assertFalse(gate["passes"])

    def test_no_gain_when_one_film_does_not_drop(self):
        gate = guard.gate(self.result(edits(10, 5, 5 - 90), edits(10, 5, 5)))
        self.assertFalse(gate["both_drop"])
        self.assertEqual(gate["verdict"], "no-gain")
        self.assertFalse(gate["passes"])


class Fill(unittest.TestCase):
    TEXT = "あいうえお"

    def test_insert_before_first_char_after_end(self):
        times = [0.1, None, 1.0, 1.2, 1.4]
        self.assertEqual(fill.insert_position(self.TEXT, times, 0.5), 2)
        self.assertEqual(fill.insert_position(self.TEXT, times, 1.0), 3)  # 严格大于

    def test_append_when_none_after(self):
        times = [0.1, None, 0.3, 0.4, 0.5]
        self.assertEqual(fill.insert_position(self.TEXT, times, 9.0), len(self.TEXT))
        self.assertEqual(fill.merge_fill(self.TEXT, times, [(9.0, "X")]), self.TEXT + "X")

    def test_merge_two_positions_keep_order(self):
        times = [0.1, 0.2, 1.0, 2.0, 3.0]
        merged = fill.merge_fill(self.TEXT, times, [(2.5, "Y"), (0.5, "X")])
        self.assertEqual(merged, "あいXうえYお")

    def test_same_position_ordered_by_end_time(self):
        times = [0.1, 0.2, 5.0, 6.0, 7.0]
        merged = fill.merge_fill(self.TEXT, times, [(2.0, "B"), (1.0, "A")])
        self.assertEqual(merged, "あいABうえお")

    def test_no_fills_keeps_text(self):
        self.assertEqual(fill.merge_fill(self.TEXT, [0.1] * 5, []), self.TEXT)


class Packs(unittest.TestCase):
    def test_pack_split(self):
        cues = make_cues(45)
        result = correct.packs(cues)
        self.assertEqual([len(p["targets"]) for p in result], [20, 20, 5])
        self.assertEqual([len(p["before"]) for p in result], [0, 10, 10])
        self.assertEqual([len(p["after"]) for p in result], [5, 5, 0])
        self.assertEqual([p["number"] for p in result], [1, 2, 3])
        self.assertEqual(result[1]["before"][0]["index"], 11)
        self.assertEqual(result[1]["after"][0]["index"], 41)

    def test_cue_id(self):
        self.assertEqual(correct.cue_id({"index": 7}), "c7")


class NameLines(unittest.TestCase):
    def test_entity_first_dedupe_and_skip_low(self):
        table = {"entries": [
            {"entity_ja": "エミヤシロウ", "confidence": "high",
             "forms": [{"ja": "シロウ", "zh": "x"}, {"ja": "エミヤシロウ", "zh": "y"}]},
            {"entity_ja": "低", "confidence": "low", "forms": []},
        ]}
        self.assertEqual(correct.name_lines(table), ["エミヤシロウ／シロウ"])


class Messages(unittest.TestCase):
    def pack(self, before, after):
        cues = make_cues(4)
        return {"number": 1, "before": before, "targets": cues[1:3], "after": after}

    def test_system_without_and_with_names(self):
        pack = self.pack([], [])
        system = correct.messages(pack, "ja-correct-v1", None)[0]
        self.assertEqual(system, {"role": "system", "content": correct.PROMPTS["ja-correct-v1"]})
        with_names = correct.messages(pack, "ja-correct-v1", ["アイ／ウ", "カキ"])[0]["content"]
        self.assertIn(correct.NAMES_HEADER, with_names)
        self.assertIn("アイ／ウ\nカキ", with_names)
        self.assertTrue(with_names.startswith(correct.PROMPTS["ja-correct-v1"]))

    def test_user_layout(self):
        cues = make_cues(4)
        user = correct.messages(self.pack(cues[:1], cues[3:]), "ja-correct-v1", None)[1]
        self.assertEqual(user["role"], "user")
        content = user["content"]
        for header in (correct.CONTEXT_BEFORE, correct.TARGET_HEADER, correct.CONTEXT_AFTER):
            self.assertIn(header, content)
        self.assertIn("c1: あ1", content)
        self.assertIn("c4: あ4", content)
        self.assertIn(json.dumps({"c2": "あ2", "c3": "あ3"}, ensure_ascii=False), content)
        self.assertNotIn("（无）", content)

    def test_empty_context_marked(self):
        content = correct.messages(self.pack([], []), "ja-correct-v1", None)[1]["content"]
        self.assertEqual(content.count("（无）"), 2)

    def test_request_body(self):
        msgs = correct.messages(self.pack([], []), "ja-correct-v1", None)
        body = correct.request_body(msgs, 42)
        self.assertEqual(body["model"], strata.MODEL)
        self.assertEqual(body["messages"], msgs)
        for key, value in correct.SAMPLING.items():
            self.assertEqual(body[key], value)
        self.assertEqual(body["seed"], 42)
        self.assertEqual(body["max_tokens"], 2048)
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertIs(body["stream"], False)


class ApplyReply(unittest.TestCase):
    def setUp(self):
        texts = {1: "あいう", 2: "かきく", 3: "さしす", 4: "たちつ", 5: "なにぬ", 6: "はひふ"}
        self.pack = {"targets": [{"index": k, "text": t} for k, t in texts.items()]}

    def test_counts(self):
        reply_ = json.dumps({"c1": "あいえ",        # 接受（比 1/3）
                             "c2": "かきく",        # 未改
                             "c3": "",              # 空
                             "c4": 5,               # 非字符串
                             "c5": "ろれる",        # 全换：比例 1.0
                             "c99": "あ"}, ensure_ascii=False)  # 未知 id
        accepted, counts = correct.apply_reply(self.pack, reply_)
        self.assertEqual(accepted, {"c1": "あいえ"})
        self.assertEqual(counts, {"proposed": 6, "unknown_id": 1, "not_string": 1, "empty": 1, "unchanged": 1,
                                  "ratio_rejected": 1, "accepted": 1})

    def test_empty_object(self):
        accepted, counts = correct.apply_reply(self.pack, "{}")
        self.assertEqual(accepted, {})
        self.assertEqual(counts["proposed"], 0)

    def test_invalid_replies_raise(self):
        for bad in ("[]", '"x"', "not json", '{"c1": "あ", "c1": "い"}'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                correct.apply_reply(self.pack, bad)


class FakeClient:
    """按顺序返回预设回复的假 `Client`，并记录请求体。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies: list[dict[str, Any]] = []

    def chat(self, body):
        self.bodies.append(body)
        return self.replies.pop(0)


def reply(content, finish="stop", **record):
    return {"record": {"seconds": 0.1, "finish_reason": finish, **record}, "content": content}


class CorrectFilm(unittest.TestCase):
    def setUp(self):
        self.cues = [{"index": k, "start": float(k), "end": k + 0.9, "text": t}
                     for k, t in enumerate(["あいうえお", "かきくけこ", "さしすせそ"], 1)]
        self.good = json.dumps({"c1": "あいうえこ"}, ensure_ascii=False)

    def run_film(self, replies):
        client = FakeClient(replies)
        return correct.correct_film(self.cues, client, "ja-correct-v1", None), client

    def test_normal_reply_changes_cue(self):
        result, client = self.run_film([reply(self.good)])
        self.assertEqual(result["cues"][0]["text"], "あいうえこ")
        self.assertEqual(result["cues"][1]["text"], "かきくけこ")
        self.assertEqual(self.cues[0]["text"], "あいうえお")  # 输入不被改动
        self.assertEqual(result["summary"]["accepted"], 1)
        self.assertEqual(result["summary"]["packs"], 1)
        self.assertEqual(result["summary"]["requests"], 1)
        self.assertEqual(result["changes"][0]["before"], "あいうえお")
        self.assertEqual(result["changes"][0]["after"], "あいうえこ")
        self.assertEqual(client.bodies[0]["seed"], correct.SEED)

    def test_length_then_retry_uses_next_seed(self):
        result, client = self.run_film([reply(None, finish="length"), reply(self.good)])
        self.assertEqual([b["seed"] for b in client.bodies], [correct.SEED, correct.SEED + 1])
        self.assertEqual(result["summary"]["retried"], 1)
        self.assertEqual(result["summary"]["length_failures"], 1)
        self.assertEqual(result["summary"]["pack_failed"], 0)
        self.assertEqual(result["summary"]["accepted"], 1)

    def test_two_parse_failures_leave_cues_unchanged(self):
        result, _ = self.run_film([reply("not json"), reply("[]")])
        self.assertEqual(result["summary"]["pack_failed"], 1)
        self.assertEqual(result["summary"]["parse_failures"], 2)
        self.assertEqual(result["summary"]["accepted"], 0)
        self.assertEqual([c["text"] for c in result["cues"]], [c["text"] for c in self.cues])

    def test_reasoning_counted(self):
        result, _ = self.run_film([reply(self.good, reasoning_chars=12)])
        self.assertEqual(result["summary"]["reasoning_nonempty"], 1)
        self.assertEqual(result["summary"]["accepted"], 1)


class ClassifyChanges(unittest.TestCase):
    def test_verdict_and_rewrite(self):
        def cue(k, text):
            return {"index": k, "start": float(k), "end": k + 0.9, "text": text}

        reference = [cue(1, "あいう"), cue(2, "かきく"), cue(3, "さしす"), cue(4, "たちつ")]
        control = [cue(1, "あいえ"), cue(2, "かきく"), cue(3, "さしす"), cue(4, "たちつ")]
        changes = [
            {"id": "c1", "index": 1, "start": 1.0, "end": 1.9, "before": "あいえ", "after": "あいう", "pack": 1},
            {"id": "c3", "index": 3, "start": 3.0, "end": 3.9, "before": "さしす", "after": "さしそ", "pack": 1},
            {"id": "c4", "index": 4, "start": 4.0, "end": 4.9, "before": "たちつ", "after": "たちて", "pack": 1},
        ]
        rows, summary = correct.classify_changes(reference, control, changes)
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["c1"]["verdict"], "improved")
        self.assertFalse(by_id["c1"]["rewrite"])  # 引入的"う"在参考单元里
        self.assertEqual(by_id["c1"]["delta"], -1)
        self.assertEqual(by_id["c3"]["verdict"], "worsened")
        self.assertTrue(by_id["c3"]["rewrite"])  # 引入的"そ"不在参考里
        self.assertEqual(by_id["c4"]["verdict"], "worsened")
        self.assertEqual((summary["changes"], summary["improved"], summary["worsened"], summary["neutral"]), (3, 1, 2, 0))
        self.assertEqual(summary["rewrite_cues"], 2)
        self.assertEqual(summary["delta_edits_sum"], 1)
        self.assertEqual(summary["introduced_chars"], 3)
        self.assertEqual(summary["introduced_absent_from_reference"], 2)


class PlanDownload(unittest.TestCase):
    def test_nothing_to_download(self):
        text = "plan\n  download  Nothing to download: the model is already on this computer.\nother 3 GB line\n"
        self.assertEqual(correct.plan_download_mib(text), 0.0)

    def test_gb_line(self):
        self.assertAlmostEqual(correct.plan_download_mib("x\ndownload  1.2 GB\n"), 1228.8)

    def test_no_download_line(self):
        self.assertIsNone(correct.plan_download_mib("launch  ok\nmemory  52 GiB\n"))


class Recipe(unittest.TestCase):
    def test_arms_and_hash_stable(self):
        c1, c2 = correct.recipe("ja-correct-v1", "c1"), correct.recipe("ja-correct-v1", "c2")
        self.assertIsNone(c1["names"])
        self.assertIsInstance(c2["names"], dict)
        self.assertEqual(artifacts.object_hash(c1), artifacts.object_hash(correct.recipe("ja-correct-v1", "c1")))
        self.assertNotEqual(artifacts.object_hash(c1), artifacts.object_hash(c2))
        self.assertEqual(c1["model"], strata.MODEL)


class DecodePure(unittest.TestCase):
    def test_signal_of_keys(self):
        decoded = {"text": "あ", "compression_ratio": 1.5, "cap_reached": False, "avg_logprob": -0.3, "tokens": [1, 2]}
        self.assertEqual(decode.signal_of(decoded),
                         {"compression_ratio": 1.5, "cap_reached": False, "avg_logprob": -0.3})

    def test_models_sha256_copies(self):
        models = {"w0": "a" * 64}
        asr = {"identity": {"models": models}}
        out = decode.models_sha256(asr)
        self.assertEqual(out, models)
        out["w0"] = "b" * 64
        self.assertEqual(models["w0"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
