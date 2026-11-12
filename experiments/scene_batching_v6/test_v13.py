"""v13 (offline): S1 identity, the Strata callbacks of build_table, the gate, table quality helpers, any table -> Q2."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from experiments.translation_v3 import recipes as R
from experiments.translation_v3 import strata
from experiments.translation_v3.common import read_json
from experiments.translation_v3.recipes import load_recipe

from . import names11, v10, v11, v12, v13

# q3-names-v2 (ADR-0026; q3-names-v1 was d3317926…). The 27B-era product recipe S1 was derived from was 5b8d1b76…;
# the product ``BUILD["build"]`` is the S1 v4 block except max_tokens / context / prompt_budget (ADR-0026).
PRODUCT_BUILD_HASH = "2dbd324e5ee847d0a0171840d4a064cd6b45a3df4c2123b7075cfe1a38b379ba"
S1_LIMITS = {"max_tokens": 8192, "context": 24576, "prompt_budget": 15872}
Q3_BUILD_HASH = "38cb7bcda96534db70fb5823c05330cd212057058c381e88cadf756f26d308d0"  # names-strata-v4, ADR-0021
Q2_DEV_HASH = "4c3d0f70a94e43207dbe439893284d078993a041bf5ebb3dd378aefeb42b0499"      # ADR-0017
Q2_PRODUCT_HASH = "86b61ec93da4ad38fc0ff709bb973a8b659660ab6dc1b3be08f068b91be908b7"  # ADR-0017
GOOD = json.dumps({"work_guess": None, "entries": [
    {"entity_ja": "シンジ", "kind": "person", "confidence": "high", "zh": "真嗣", "forms": [{"ja": "シンジ", "zh": "真嗣"}],
     "zh_variants": [], "evidence": [1, 2, 3]}]}, ensure_ascii=False)


def reply(content: str, finish: str = "stop") -> dict:
    return {"id": "x", "object": "chat.completion", "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40}, "timings": {}}


class FakePost:
    def __init__(self, replies: list[dict], count_tokens: int | Exception = 50):
        self.replies, self.count_tokens, self.bodies = list(replies), count_tokens, []

    def __call__(self, url: str, body: dict, timeout: float) -> dict:
        self.bodies.append((url, body))
        if url.endswith(v13.COUNT_TOKENS):
            if isinstance(self.count_tokens, Exception):
                raise self.count_tokens
            return {"input_tokens": self.count_tokens}
        return self.replies.pop(0)


def doc():
    from kototoki.srt import SourceCue, SourceDocument
    cues = tuple(SourceCue(id=f"c{i}", ordinal=i, index=i, index_text=str(i), time_line="", start_ms=0, end_ms=0,
                           text="シンジ") for i in (1, 2, 3))
    return SourceDocument(source_sha256="0" * 64, cues=cues, encoding="utf-8")


class IdentityTest(unittest.TestCase):
    def test_product_build_hash_unchanged_and_s1_separate(self):
        from kototoki.names.recipes import BUILD, BUILD_RECIPE_HASH
        self.assertEqual(BUILD_RECIPE_HASH, PRODUCT_BUILD_HASH)
        s1 = v13.s1_recipe("v2")
        self.assertEqual(s1["build"], BUILD["build"] | S1_LIMITS | {"attempts": 2})
        self.assertEqual(v13.s1_recipe("v4")["build"], BUILD["build"] | S1_LIMITS)
        self.assertEqual(v13.s1_hash("v4"), Q3_BUILD_HASH)
        self.assertEqual((s1["build"]["max_tokens"], s1["build"]["context"], s1["build"]["prompt_budget"]),
                         (8192, 24576, 15872))  # 24576 - 8192 - 512
        self.assertEqual((s1["model"], s1["runtime"]["launch"], s1["request"]["response_format"]),
                         (strata.MODEL, "default", None))
        self.assertNotEqual(v13.s1_hash(), BUILD_RECIPE_HASH)
        self.assertEqual(v13.s1_hash(), v13.s1_hash())


class ClientTest(unittest.TestCase):
    def test_body_drops_response_format_and_states_no_thinking(self):
        from kototoki.names.table import _request_body
        product = _request_body([{"role": "user", "content": "x"}], 20261019)
        self.assertNotIn("response_format", product)  # the product stopped sending it with ADR-0022
        body = v13.strata_body(product | {"response_format": {"type": "json_schema"}})
        self.assertNotIn("response_format", body)
        self.assertEqual((body["model"], body["chat_template_kwargs"], body["max_tokens"]),
                         (strata.MODEL, {"enable_thinking": False}, 8192))
        self.assertEqual({k: body[k] for k in ("temperature", "top_p", "top_k", "min_p", "presence_penalty")},
                         {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 1.5})
        with self.assertRaises(ValueError):
            v13.strata_body(dict(product, chat_template_kwargs={"enable_thinking": True}))
        with self.assertRaises(ValueError):
            v13.strata_body(dict(product, seed=0))

    def test_parse_failure_retries_with_next_seed(self):
        post = FakePost([reply("not json"), reply(GOOD)])
        client = v13.NamesClient(post=post)
        result, record = v13.build_one(doc(), client)
        self.assertEqual((result.status, result.attempts, record["first_attempt_failed"]), ("ok", 2, True))
        chats = [b for u, b in post.bodies if u.endswith("/chat/completions")]
        self.assertEqual([b["seed"] for b in chats], [20261019, 20261020])
        self.assertTrue(all("response_format" not in b for b in chats))
        self.assertEqual((record["count_tokens"], record["prompt_tokens"], record["prompt_tokens_minus_count"]),
                         (100, 120, 20))
        self.assertEqual((record["entries"], record["high_entries"], record["reasoning_chars"]), (1, 1, 0))
        self.assertNotIn("シンジ", json.dumps(record, ensure_ascii=False))  # counts only

    def test_count_tokens_fallback(self):
        error = HTTPError("u", 404, "nf", {}, None)
        client = v13.NamesClient(post=FakePost([reply(GOOD)], count_tokens=error))
        result, record = v13.build_one(doc(), client)
        self.assertEqual((result.status, record["count_tokens_ok"], record["count_tokens"]), ("ok", False, None))
        self.assertFalse(record["over_budget_by_usage"])

    def test_preflight_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "gpu.lock"
            ok = dict(cli=lambda *a, **k: '{"running": []}', ram=lambda: 55.0, lock=lock, processes=lambda: [])
            self.assertEqual(v13.preflight(**ok)["available_ram_gib"], 55.0)
            for bad in ({"ram": lambda: 51.9}, {"processes": lambda: ["llama-server.exe"]},
                        {"cli": lambda *a, **k: '{"running": [{"name": "x", "state": "ready"}]}'}):
                with self.assertRaises(SystemExit, msg=bad):
                    v13.preflight(**(ok | bad))
            lock.write_text("{}")
            with self.assertRaises(SystemExit):
                v13.preflight(**ok)


class VariantTest(unittest.TestCase):
    def test_hashes(self):
        self.assertEqual(v13.s1_hash("v2"), "eb4b1c6d91517683f18fd6e83cda12fc6ea0c6cdbf9b31a43ccfc002d8d5b920")
        self.assertEqual(v13.s1_hash("v4"), Q3_BUILD_HASH)
        self.assertEqual(len({v13.s1_hash(v) for v in ("v2", "v3", "v4")}), 3)
        self.assertEqual((v13.s1_recipe("v3")["build"]["attempts"], v13.s1_recipe("v4")["build"]["attempts"]), (5, 5))
        self.assertIsNone(v13.s1_recipe("v4")["request"]["response_format"])
        self.assertEqual(v13.s1_recipe("v3")["request"]["response_format"]["type"], "json_schema")

    def test_v3_keeps_response_format_and_502_is_a_failed_attempt(self):
        from io import BytesIO
        from kototoki.names.table import _request_body
        self.assertIn("response_format", v13.strata_body(_request_body([], 1), response_format=True))
        error = HTTPError("u", 502, "bad", {}, BytesIO(b'{"error": {"code": "structured_output_failed"}}'))

        class Post(FakePost):
            def __call__(self, url, body, timeout):
                if url.endswith("/chat/completions") and len([1 for u, _ in self.bodies if u.endswith("/chat/completions")]) == 0:
                    self.bodies.append((url, body))
                    raise error
                return super().__call__(url, body, timeout)

        post = Post([reply(GOOD)])
        result, record = v13.build_one(doc(), v13.NamesClient(post=post, variant="v3"))
        self.assertEqual((result.status, record["attempts"], record["failed_attempt_kinds"]),
                         ("ok", 2, {"structured_output_failed": 1}))
        self.assertTrue(all("response_format" in b for u, b in post.bodies if u.endswith("/chat/completions")))
        self.assertTrue(v13.gate({"builds": {"dev/W": record}}, root=Path(tempfile.mkdtemp()))["checks"]
                        ["sampling_accepted"])

    def test_v4_retries_up_to_five_attempts_on_consecutive_seeds(self):
        post = FakePost([reply("x", "length")] * 4 + [reply(GOOD)])
        result, record = v13.build_one(doc(), v13.NamesClient(post=post, variant="v4"))
        seeds = [b["seed"] for u, b in post.bodies if u.endswith("/chat/completions")]
        self.assertEqual((result.status, seeds, record["failed_attempt_kinds"]),
                         ("ok", list(range(20261019, 20261024)), {"length": 4}))
        self.assertEqual(record["count_tokens"], 100)  # the first call's two segments only
        post = FakePost([reply("x", "length")] * 5)
        result, record = v13.build_one(doc(), v13.NamesClient(post=post, variant="v4"))
        self.assertEqual((result.status, record["attempts"], len(post.replies)), ("failed", 5, 0))
        post = FakePost([reply("x", "length")] * 2)
        result, record = v13.build_one(doc(), v13.NamesClient(post=post, variant="v2"))
        self.assertEqual((result.status, record["attempts"]), ("failed", 2))


class GateTest(unittest.TestCase):
    def build(self, status="ok", first=False, **request) -> dict:
        return {"status": status, "first_attempt_failed": first, "reason": None, "count_tokens_ok": True,
                "attempts": 2 if first else 1,
                "prompt_tokens_minus_count": 3, "over_budget_by_usage": False,
                "requests": [{"reasoning_chars": 0, "think_tag": False, "error": None, "extra_response_keys": []}
                             | request]}

    def test_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            builds = {f"dev/W{i}": self.build() for i in range(15)} | {
                "product/HF-II": self.build(), "product/HF-III": self.build(), "product-aa/HF-II": self.build()}
            self.assertTrue(v13.gate({"builds": builds}, root=Path(tmp))["passed"])
            two = dict(builds, **{"dev/W0": self.build(first=True), "dev/W1": self.build(first=True)})
            self.assertTrue(v13.gate({"builds": two}, root=Path(tmp))["passed"])
            three = dict(two, **{"dev/W2": self.build(first=True)})
            self.assertFalse(v13.gate({"builds": three}, root=Path(tmp))["checks"]["first_attempt_failures_ok"])
            for bad, check in ((self.build("failed"), "all_ok"), (self.build(reasoning_chars=5), "no_thinking_output"),
                               (self.build(http_status=400), "sampling_accepted"),
                               (self.build(extra_response_keys=["warnings"]), "sampling_accepted")):
                gate = v13.gate({"builds": dict(builds, **{"product-aa/HF-II": bad} if check != "all_ok"
                                                else {"dev/W3": bad})}, root=Path(tmp))
                self.assertFalse(gate["checks"][check], msg=check)
            self.assertFalse(v13.gate({"builds": {k: v for k, v in builds.items() if k != "dev/W0"}},
                                      root=Path(tmp))["checks"]["all_ok"])


class QualityTest(unittest.TestCase):
    def test_agreement_and_overlap(self):
        rows = [{"work": "A", "confidence": "high", "occurrences": 4, "reference_agrees": 1, "agreement": 0.25},
                {"work": "A", "confidence": "medium", "occurrences": 6, "reference_agrees": 6, "agreement": 1.0},
                {"work": "B", "confidence": "high", "occurrences": 0, "reference_agrees": 0, "agreement": None},
                {"work": "B", "confidence": "high", "occurrences": 10, "reference_agrees": 9, "agreement": 0.9}]
        self.assertEqual(v13.agreement_stats(rows, ["A", "B"]), {"agreement": 0.8, "high_disagree": 0.5})
        self.assertEqual(v13.agreement_stats(rows, ["A", "A"])["agreement"], 0.7)
        e = lambda ja, zh, conf="high", forms=None: {"entity_ja": ja, "zh": zh, "confidence": conf,  # noqa: E731
                                                     "forms": forms or [{"ja": ja, "zh": zh}]}
        a = [e("シンジ", "真嗣"), e("レイ", "丽", "medium")]
        b = [e("シンジ", "真嗣"), e("レイ", "零"), e("トウジ", "真嗣")]
        self.assertEqual(v13.overlap(a, b), {"forms_a": 2, "forms_b": 3, "ja_shared": 2, "same_zh": 1,
                                             "pair_jaccard": 1 / 3, "same_zh_of_shared": 0.5})
        self.assertEqual(v13.overlap(a, b, True)["forms_a"], 1)
        self.assertEqual((v13.zh_collisions(a), v13.zh_collisions(b)), (0, 2))


class RecipeTest(unittest.TestCase):
    def test_high_rows_match_v11(self):
        entries = [{"confidence": "high", "forms": [{"ja": "a", "zh": "A"}, {"ja": "a", "zh": "B"}, {"ja": " ", "zh": "C"}]},
                   {"confidence": "medium", "forms": [{"ja": "b", "zh": "B"}]}]
        self.assertEqual(v13.high_rows(entries), [{"source": "a", "translation": "A"}])

    def write_and_load(self, data: dict) -> R.Recipe:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recipes" / f"{data['name']}.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return load_recipe(data["name"], Path(tmp))

    @unittest.skipUnless((v10.V10_ROOT / "E/dev-name-tables.json").is_file(), "needs the v10 dev tables")
    def test_27b_tables_give_the_adr_0017_q2_instances(self):
        dev = v13.q2_data(names11.dev_tables(v10.V10_ROOT), v13.T0, "c", keep_empty=False)
        self.assertEqual(dev["qwen_options"]["names"]["tables"], names11.nstar_tables("high"))
        self.assertEqual(self.write_and_load(dev).recipe_hash, Q2_DEV_HASH)
        prod = v13.q2_data(v13.product_entries("27b"), v13.T0, "c", keep_empty=True)
        self.assertEqual(prod["qwen_options"]["names"]["tables"], names11.product_tables("high"))
        self.assertEqual(self.write_and_load(prod).recipe_hash, Q2_PRODUCT_HASH)
        recipe = self.write_and_load(dev)
        self.assertEqual((recipe.model, recipe.qwen_options["strata_launch"], recipe.qwen_options["names"]["filter"]),
                         (R.STRATA_MODEL, "default", "window"))

    @unittest.skipUnless((v12.V12_ROOT / "recipes/qwen-names-dev-high.json").is_file(), "needs the v12 recipes")
    def test_older_hashes_unchanged(self):
        self.assertEqual(load_recipe(v12.Q1_DEV, v12.V12_ROOT).recipe_hash[:8], "9c444d3c")
        self.assertEqual(load_recipe(v12.F1, v12.V12_ROOT).recipe_hash[:8], "60bd457f")
        self.assertEqual(load_recipe(v12.F1, v12.D_ROOT / "root").recipe_hash[:8], "a2075b25")


class GateFunctionsTest(unittest.TestCase):
    def test_dev_gate(self):
        s = {"accuracy": {"anime_series": [0.0, [-0.02, 0.04]], "animation_movie": [0.0, [-0.05, -0.01]]},
             "wrong-referent": {"anime_series": [0.0, [-0.01, 0.01]], "animation_movie": [0.0, [0.0, 0.02]]}}
        self.assertEqual((v13.dev_gate(s)["noninferior"], v13.dev_gate(s)["improved"]), (True, True))
        s["wrong-referent"]["animation_movie"] = [0.01, [0.001, 0.02]]
        self.assertFalse(v13.dev_gate(s)["noninferior"])

    def test_product_gate(self):
        est = {"buckets": {"all": {"ci90": [-0.1, 0.03], "name_error_delta_ci90": [-0.01, 0.004]}}}
        inc = {v13.T0: {"mean_inconsistency": 0.02}, v13.T1: {"mean_inconsistency": 0.029}}
        fail = {v13.T0: {"HF-II.s1": 0}, v13.T1: {"HF-II.s1": 0}}
        gate = v13.product_gate(est, inc, fail)
        self.assertEqual((gate["noninferior"], gate["improved"]), (True, False))
        self.assertFalse(v13.product_gate(est, inc, {**fail, v13.T1: {"HF-II.s1": 3}})["noninferior"])
        self.assertFalse(v13.product_gate(est, {**inc, v13.T1: {"mean_inconsistency": 0.031}}, fail)["noninferior"])


if __name__ == "__main__":
    unittest.main()
