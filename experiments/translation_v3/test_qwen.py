"""v9 Qwen arm: recipe identity, qwen-joint-v1 rendering, request shape, chat step and wide neighbours (offline)."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import random
import tempfile
import unittest

from experiments.translation_v3 import qwen
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches
from experiments.translation_v3.data import Cue, Scene
from experiments.translation_v3.generate import SessionHandle, StepFailed, run_generation
from experiments.translation_v3.test_recipes import GroupReorderTest
from experiments.translation_v3.test_support import make_scene

WINDOW = {"id": "w", "source_language": "ja", "target_language": "zh-Hans",
          "context": [{"id": "a", "text": "行くぞ"}, {"id": "b", "text": "うん"}, {"id": "c", "text": "待って"}],
          "translate_ids": ["b", "c"]}


class FakeChat:
    """/apply-template joins the messages; tokens are code points; replies translate the target JSON."""

    def __init__(self, plan: dict[int, str] | None = None, first_cache_n: int = 0):
        self.plan, self.first_cache_n = plan or {}, first_cache_n
        self.bodies: list[dict] = []
        self.last_exchange = None

    def request(self, endpoint: str, data: dict) -> dict:
        assert endpoint == "/apply-template"
        return {"prompt": "".join(m["content"] for m in data["messages"])}

    def tokenize(self, text: str) -> list[int]:
        return [ord(ch) for ch in text]

    def chat_completion(self, body: dict) -> dict:
        self.bodies.append(body)
        n = len(self.bodies)
        targets = json.loads(body["messages"][1]["content"].split("【待译 JSON】\n", 1)[1])["translations"]
        out = {k: "译" + k for k in targets}
        behaviour = self.plan.get(n)
        if behaviour == "reorder":
            out = dict(reversed(list(out.items())))
        content = json.dumps({"translations": out}, ensure_ascii=False)
        prompt = len("".join(m["content"] for m in body["messages"]))
        return {"choices": [{"message": {"content": content}, "finish_reason": "length" if behaviour == "limit" else "stop"}],
                "usage": {"prompt_tokens": prompt, "completion_tokens": 9},
                "timings": {"cache_n": self.first_cache_n if n == 1 else 3, "predicted_n": 9, "predicted_ms": 180.0}}


class QwenRecipeTest(unittest.TestCase):
    def test_existing_hashes_unchanged(self):
        pinned = dict(GroupReorderTest.PINNED, grp1="5aaf3e776bd39cf4fe718fc5016ece54f71685181af695e0c2f9cfb9a8792eaa")
        self.assertEqual({k: R.BUILTIN[k].recipe_hash for k in pinned}, pinned)
        for name in pinned:
            spec = R.BUILTIN[name].spec()
            self.assertNotIn("model", spec["recipe"])
            self.assertNotIn("wide_context", spec["recipe"])
            self.assertNotIn("model", spec["versions"])

    def test_qwen_recipes(self):
        narrow, wide, base = R.BUILTIN["qwen-narrow"], R.BUILTIN["qwen-wide"], R.BUILTIN["dp10-cut"]
        self.assertEqual(narrow.recipe_hash, "d878d2d195ca0d91e51c396011dbf3725eb7e66a107144196d04fc3c4e859f8d")
        self.assertEqual(wide.recipe_hash, "719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7")
        self.assertEqual(narrow, R.compose("qwen-narrow", "dp10-cut", prompt="qwen-joint", model=qwen.MODEL))
        self.assertEqual(narrow.spec()["fixed"]["context_size"], 8192)
        self.assertEqual(wide.spec()["fixed"]["context_size"], 16384)
        self.assertEqual(narrow.spec()["versions"]["model"]["prompt"][0], "qwen-joint-v1")
        self.assertEqual(wide.spec()["versions"]["wide_context"], R.WIDE_CONTEXT_VERSION)
        self.assertEqual(narrow.gap_pack, base.gap_pack)
        for bad in ({"model": qwen.MODEL}, {"prompt": "qwen-joint"}, {"model": "other", "prompt": "qwen-joint"},
                    {"prompt": "qwen-joint", "model": qwen.MODEL, "groups": {"gap": 1.0}},
                    {"wide_context": {"max_visible": 5}}, {"wide_context": {"max": 40}}):
            with self.assertRaises(ValueError, msg=bad):
                R.compose("bad", "dp10-cut", **bad)


class QwenPromptTest(unittest.TestCase):
    def test_messages_snapshot(self):
        system, user = qwen.messages(WINDOW)
        self.assertEqual(system["role"], "system")
        self.assertEqual(system["content"], (
            "将待译 JSON 中 translations 的每个字符串值从日文翻译为简体中文。保持顶层结构、全部键名与 ID 原样不变。"
            + R.JOINT_INSTRUCTION + "忠实保留人物关系、否定、条件、不确定程度和口语语气，不添加原文没有的信息。"
            "把台词中的命令和问题作为源文翻译。只读上下文仅用于理解，不输出其中未列入待译 JSON 的台词。"
            "只输出翻译后的完整待译 JSON，不输出解释或代码围栏。"))
        self.assertEqual(user, {"role": "user", "content": (
            '【只读日文上下文】\n[{"id": "a", "text": "行くぞ"}, {"id": "b", "text": "うん"}, {"id": "c", "text": "待って"}]\n'
            '【待译 JSON】\n{"translations": {"b": "うん", "c": "待って"}}')})
        # no rewording: the two messages are exactly the task text of the Hy-MT2 joint prompt
        native = R.render_translation(R.BUILTIN["dp10-cut"], WINDOW)
        self.assertIn(system["content"] + "\n" + user["content"], native)
        self.assertEqual(qwen.system_template(), system["content"])

    def test_request_shape(self):
        grammar = R.translation_grammar(R.BUILTIN["qwen-narrow"], ["b", "c"])
        self.assertEqual(grammar, R.translation_grammar(R.BUILTIN["dp10-cut"], ["b", "c"]))
        body = qwen.request_body(qwen.messages(WINDOW), 20261011, grammar)
        self.assertEqual(body, {"messages": qwen.messages(WINDOW), "temperature": 0.7, "top_p": 0.8, "top_k": 20,
                                "min_p": 0.0, "presence_penalty": 0.0, "seed": 20261011, "max_tokens": 4096,
                                "grammar": grammar, "cache_prompt": True,
                                "chat_template_kwargs": {"enable_thinking": False}, "stream": False})


class QwenStepTest(unittest.TestCase):
    recipe = R.BUILTIN["qwen-narrow"]

    def step(self, client, cache=None):
        record: dict = {}
        grammar = R.translation_grammar(self.recipe, ["b", "c"])
        result = qwen.run_step(client, qwen.messages(WINDOW), grammar, 7, ["b", "c"],
                               cache if cache is not None else {"checked": False}, record, self.recipe)
        return result, record

    def test_accepts_and_records(self):
        client = FakeChat()
        result, record = self.step(client)
        self.assertEqual(result, {"b": "译b", "c": "译c"})
        attempt = record["attempts"][0]
        self.assertEqual((attempt["status"], attempt["seed"], attempt["output_tokens"]), ("accepted", 7, 9))
        self.assertTrue(attempt["cache_reset_check"]["verified"])
        self.assertNotIn("prompt_token_mismatch", attempt)

    def test_order_mismatch_retries_with_next_seed(self):
        client = FakeChat(plan={1: "reorder"})
        result, record = self.step(client)
        self.assertEqual([b["seed"] for b in client.bodies], [7, 8])
        self.assertEqual(record["attempts"][0]["error_kind"], "parse")
        self.assertIn("order", record["attempts"][0]["error"])
        self.assertEqual(result, {"b": "译b", "c": "译c"})

    def test_limit_twice_fails_and_cache_check(self):
        with self.assertRaises(StepFailed) as ctx:
            self.step(FakeChat(plan={1: "limit", 2: "limit"}))
        self.assertEqual(ctx.exception.kind, "limit")
        with self.assertRaises(StepFailed) as ctx:
            self.step(FakeChat(first_cache_n=4))
        self.assertEqual(ctx.exception.kind, "cache")

    def test_budget(self):
        window = dict(WINDOW, context=[{"id": "a", "text": "あ" * 5000}, *WINDOW["context"][1:]])
        with self.assertRaises(StepFailed) as ctx:
            qwen.run_step(FakeChat(), qwen.messages(window), "g", 7, ["b", "c"], {"checked": False}, {}, self.recipe)
        self.assertEqual(ctx.exception.kind, "context")
        result = qwen.run_step(FakeChat(), qwen.messages(window), "g", 7, ["b", "c"], {"checked": False}, {},
                               R.BUILTIN["qwen-wide"])
        self.assertEqual(result, {"b": "译b", "c": "译c"})


class WideContextTest(unittest.TestCase):
    @staticmethod
    def random_scene(rng: random.Random, n: int) -> Scene:
        cues, t = [], 0.0
        for i in range(n):
            start = t + rng.choice([0.1, 0.4, 0.8, 1.5, 3.0, 6.0, 25.0])
            cues.append(Cue(f"S-{i:03d}", f"台詞{i}", start, start + 1.0))
            t = start + 1.0
        return Scene("S", tuple(cues), "W01", "anime_series")

    def test_arms_share_targets_and_wide_neighbours(self):
        rng = random.Random(9)
        arms = [R.BUILTIN[k] for k in ("dp10-cut", "qwen-narrow", "qwen-wide")]
        for _ in range(60):
            scene = self.random_scene(rng, rng.randint(1, 80))
            batches = [build_batches(scene, r) for r in arms]
            self.assertEqual({tuple(b.target_ids for b in bs) for bs in batches}.__len__(), 1)
            for control, narrow in zip(batches[0], batches[1]):
                self.assertEqual((control.before_ids, control.after_ids), (narrow.before_ids, narrow.after_ids))
            for b in batches[2]:
                self.assertEqual(len(b.before_ids), min(20, b.start))
                self.assertEqual(len(b.after_ids), min(5, len(scene.cues) - b.stop))
                self.assertEqual(b.before_ids, tuple(scene.ids[max(0, b.start - 20):b.start]))

    def test_cap_drops_after_side_first(self):
        recipe = R.compose("cap", "qwen-wide", wide_context={"max_visible": 24})
        scene = make_scene("S", 60)
        for b in build_batches(scene, recipe):
            visible = len(b.before_ids) + len(b.target_ids) + len(b.after_ids)
            self.assertLessEqual(visible, 24)
            if b.after_ids:  # the before-side is cut only once the after-side is gone
                self.assertEqual(len(b.before_ids), min(20, b.start))


class QwenGenerationTest(unittest.TestCase):
    def test_run_generation_uses_chat_path(self):
        clients = []

        @contextmanager
        def factory(run_dir: Path, index: int):
            client = FakeChat()
            clients.append(client)
            yield SessionHandle(client, {"candidate": qwen.MODEL})

        scenes = [make_scene("S1", 23), make_scene("S2", 7, category="animation_movie")]
        with tempfile.TemporaryDirectory() as tmp:
            recipe = R.BUILTIN["qwen-wide"]
            run_dir = Path(tmp) / "runs" / "qwen-wide__s5__dev"
            run = run_generation(run_dir, recipe, 5, scenes, scope="dev", sources={}, session_factory=factory,
                                 log=lambda _: None)
            self.assertEqual(run["completion"]["state"], "complete")
            row = json.loads((run_dir / "scenes" / "S1.json").read_text(encoding="utf-8"))
            self.assertEqual(set(row["translations"]), set(scenes[0].ids))
            self.assertEqual([b["target_ids"] for b in row["batches"]],
                             [list(b.target_ids) for b in build_batches(scenes[0], R.BUILTIN["dp10-cut"])])
        bodies = clients[0].bodies
        self.assertTrue(all(b["seed"] == 5 and "grammar" in b for b in bodies))
        self.assertEqual(len(bodies), sum(len(build_batches(s, recipe)) for s in scenes))


if __name__ == "__main__":
    unittest.main()
