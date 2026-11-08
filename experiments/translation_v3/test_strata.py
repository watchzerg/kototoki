"""v12 Strata backend: recipe identity, request body, no-grammar step, partial delivery, attach checks (offline)."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from experiments.translation_v3 import qwen, strata
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.generate import SessionHandle, StepFailed, run_generation
from experiments.translation_v3.test_qwen import WINDOW
from experiments.translation_v3.test_support import make_scene

NAMES = {"filter": "window", "tables": {"W": [{"source": "行く", "translation": "去"}]}}


def f1(**options) -> R.Recipe:
    return R.compose("f1", "qwen-wide", model=R.STRATA_MODEL, qwen_options={"names": NAMES, **options})


class FakeStrata:
    """Only /v1/chat/completions (no /apply-template, /tokenize); replies translate the target JSON."""

    def __init__(self, plan: dict[int, str] | None = None, first_cache_n: int = 0, prompt_tokens: int | None = None):
        self.plan, self.first_cache_n, self.prompt_tokens = plan or {}, first_cache_n, prompt_tokens
        self.bodies: list[dict] = []
        self.last_exchange = None

    def chat_completion(self, body: dict) -> dict:
        self.bodies.append(body)
        n = len(self.bodies)
        targets = json.loads(body["messages"][1]["content"].split("【待译 JSON】\n", 1)[1])["translations"]
        behaviour = self.plan.get(n)
        content = json.dumps({"translations": {k: "译" + k for k in targets}}, ensure_ascii=False)
        message = {"content": content}
        if behaviour == "prose":
            message["content"] = "好的，下面是译文：" + content
        if behaviour == "think":
            message["reasoning_content"] = "嗯"
        prompt = self.prompt_tokens or len("".join(m["content"] for m in body["messages"]))
        return {"choices": [{"message": message, "finish_reason": "length" if behaviour == "limit" else "stop"}],
                "usage": {"prompt_tokens": prompt, "completion_tokens": 9},
                "timings": {"cache_n": self.first_cache_n if n == 1 else 3}}


class StrataRecipeTest(unittest.TestCase):
    def test_identity(self):
        recipe = f1()
        q1 = R.compose("f1", "qwen-wide", qwen_options={"names": NAMES})
        self.assertNotEqual(recipe.recipe_hash, q1.recipe_hash)
        self.assertEqual(R.BUILTIN["qwen-wide"].recipe_hash,
                         "719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7")
        model = recipe.spec()["versions"]["model"]
        self.assertEqual(model["model"], "qwen3.8-flash-next-iq3_s")
        self.assertEqual(model["runtime"]["launch"], list(strata.LAUNCH_FLAGS))
        self.assertEqual((model["runtime"]["strata"], model["runtime"]["engine_build"]), ("0.2.12", "0.1.58"))
        self.assertEqual(model["prompt"], q1.spec()["versions"]["model"]["prompt"])
        self.assertEqual(model["options"]["names"], q1.spec()["versions"]["model"]["options"]["names"])
        fixed = recipe.spec()["fixed"]
        self.assertIsNone(fixed["grammar"])
        self.assertEqual(fixed["sampling"], q1.spec()["fixed"]["sampling"])
        self.assertNotIn("cache_prompt", fixed)
        think = f1(thinking={"budget": 1024, "min_visible": 1}).spec()["versions"]["model"]["options"]["thinking"]
        self.assertEqual(think, {"budget": 1024, "min_visible": 1, "request": strata.THINKING_REQUEST})
        with self.assertRaises(ValueError):
            R.compose("bad", "qwen-wide", model="qwen3.8-flash-next-iq3_xxs")

    def test_request_body(self):
        body = strata.request_body(qwen.messages(WINDOW), 20261011)
        self.assertEqual(body, {"model": strata.MODEL, "messages": qwen.messages(WINDOW), "temperature": 0.7,
                                "top_p": 0.8, "top_k": 20, "min_p": 0.0, "presence_penalty": 0.0, "seed": 20261011,
                                "max_tokens": 4096, "chat_template_kwargs": {"enable_thinking": False},
                                "stream": False})
        think = strata.request_body([], 5, think=True, budget=1024, max_tokens_=5120)
        self.assertEqual((think["chat_template_kwargs"], think["thinking_budget_tokens"], think["max_tokens"]),
                         ({"enable_thinking": True}, 1024, 5120))
        with self.assertRaises(ValueError):
            strata.request_body([], 0)


class StrataStepTest(unittest.TestCase):
    def step(self, client, recipe=None, cache=None):
        record: dict = {}
        recipe = recipe or f1()
        result = qwen.run_step(client, qwen.messages(WINDOW, recipe, "W"), "ignored", 7, ["b", "c"],
                               cache if cache is not None else {"checked": False}, record, recipe)
        return result, record

    def test_accepts_without_grammar(self):
        client = FakeStrata()
        result, record = self.step(client)
        self.assertEqual(result, {"b": "译b", "c": "译c"})
        self.assertTrue(all("grammar" not in b and "cache_prompt" not in b for b in client.bodies))
        attempt = record["attempts"][0]
        self.assertEqual((attempt["status"], attempt["over_q1_budget"]), ("accepted", False))
        self.assertIsInstance(attempt["input_tokens"], int)
        self.assertTrue(attempt["cache_reset_check"]["recorded_only"])

    def test_format_failure_retries_with_next_seed(self):
        client = FakeStrata(plan={1: "prose"})
        result, record = self.step(client)
        self.assertEqual([b["seed"] for b in client.bodies], [7, 8])
        self.assertEqual(record["attempts"][0]["error_kind"], "parse")
        self.assertEqual(result, {"b": "译b", "c": "译c"})
        with self.assertRaises(StepFailed) as ctx:
            self.step(FakeStrata(plan={1: "prose", 2: "limit"}))
        self.assertEqual(ctx.exception.kind, "limit")

    def test_cache_budget_and_reasoning_are_recorded_not_failed(self):
        _, record = self.step(FakeStrata(first_cache_n=40, prompt_tokens=20000, plan={1: "think"}))
        attempt = record["attempts"][0]
        self.assertEqual(attempt["status"], "accepted")
        self.assertFalse(attempt["cache_reset_check"]["verified"])
        self.assertTrue(attempt["over_q1_budget"])
        self.assertEqual(attempt["reasoning_chars"], 1)

    def test_thinking_packs(self):
        client = FakeStrata()
        self.step(client, f1(thinking={"budget": 1024, "min_visible": 1}))
        self.assertEqual((client.bodies[0]["thinking_budget_tokens"], client.bodies[0]["max_tokens"]), (1024, 5120))
        self.assertTrue(client.bodies[0]["chat_template_kwargs"]["enable_thinking"])


class StrataGenerationTest(unittest.TestCase):
    def test_failed_pack_leaves_only_its_cues(self):
        clients = []

        @contextmanager
        def factory(run_dir: Path, index: int):
            client = FakeStrata(plan={2: "prose", 3: "prose"})  # the second pack fails both attempts
            clients.append(client)
            yield SessionHandle(client, {"candidate": strata.MODEL})

        scene = make_scene("S1", 23)
        recipe = R.compose("f1", "qwen-wide", model=R.STRATA_MODEL)
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "f1__s5__dev"
            run_generation(run_dir, recipe, 5, [scene], scope="dev", sources={}, session_factory=factory,
                           log=lambda _: None)
            row = json.loads((run_dir / "scenes" / "S1.json").read_text(encoding="utf-8"))
        self.assertEqual(row["status"], "failed")
        self.assertEqual(len(row["failed_batches"]), 1)
        failed = set(row["failed_batches"][0]["target_ids"])
        self.assertEqual(set(row["translations"]), set(scene.ids) - failed)
        self.assertEqual(row["failure"]["batch_index"], 1)
        self.assertFalse(row["failure"]["infra"])

    def test_qwen_recipe_still_stops_at_failed_pack(self):
        @contextmanager
        def factory(run_dir: Path, index: int):
            from experiments.translation_v3.test_qwen import FakeChat
            yield SessionHandle(FakeChat(plan={1: "limit", 2: "limit"}), {})

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "qwen-wide__s5__dev"
            run_generation(run_dir, R.BUILTIN["qwen-wide"], 5, [make_scene("S1", 23)], scope="dev", sources={},
                           session_factory=factory, log=lambda _: None)
            row = json.loads((run_dir / "scenes" / "S1.json").read_text(encoding="utf-8"))
        self.assertEqual((row["status"], row["translations"]), ("failed", {}))
        self.assertNotIn("failed_batches", row)


class StrataAttachTest(unittest.TestCase):
    def fakes(self, tmp: Path, *, host="127.0.0.1", context=32768, args=None):
        config = tmp / "run.json"
        config.write_text(json.dumps({"model_name": strata.MODEL, "api_key": "secret", "args": args or [
            "--max-context", "32768", "--kv", "int8", "--spec", "4", "--mtp", "x"]}), encoding="utf-8")

        def cli(*a):
            if a == ("--version",):
                return "strata 0.2.12 (build 0.1.58; python 3.12.15 at x)\n"
            return json.dumps({"running": [{"name": strata.PRESET, "profile": "launch-" + strata.PRESET,
                                            "state": "ready", "port": 8080, "host": host, "config": str(config)}]})

        def get(url):
            if url.endswith("/v1/models"):
                return {"data": [{"id": strata.MODEL}]}
            return {"context": {"native": context}, "concurrency": {"serving": 1},
                    "machine": {"gpu": {"used_mib": 15000}, "ram": {"used_gib": 50.5}}}
        return cli, get

    def test_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli, get = self.fakes(Path(tmp))
            observed = strata.probe(8080, cli=cli, get=get)
            self.assertEqual((observed["kv"], observed["drafting"], observed["spec"]), ("int8", "mtp", "4"))
            self.assertNotIn("secret", json.dumps(observed))
            for bad in ({"host": "0.0.0.0"}, {"context": 131072}, {"args": ["--max-context", "32768", "--vision"]}):
                cli, get = self.fakes(Path(tmp), **bad)
                with self.assertRaises(RuntimeError, msg=bad):
                    strata.probe(8080, cli=cli, get=get)

    def test_session_records_identity_resources_and_log_events(self):
        from experiments.translation_v3 import server
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cli, get = self.fakes(tmp)
            log = tmp / "server.log"
            log.write_text("[strata] old repeated reasoning detected\n", encoding="utf-8")

            class Lock(server.GpuLock):
                def __init__(self, run_id):
                    super().__init__(run_id, path=tmp / "gpu.lock")

            class Client:
                def __init__(self, url, timeout, trace_dir):
                    self.url = url

            with mock.patch.object(server, "GpuLock", Lock):
                factory = strata.session_factory(tmp, "r", f1(), probe_fn=lambda port: strata.probe(port, cli=cli, get=get),
                                                 get=get, client_factory=Client, log_path=log)
                with factory(tmp / "run", 1) as handle:
                    self.assertEqual(handle.identity["candidate"], strata.MODEL)
                    self.assertTrue((tmp / "gpu.lock").is_file())
                    with log.open("a", encoding="utf-8") as f:
                        f.write("[strata] the engine's logits became non-finite after 3 tokens\n")
            self.assertFalse((tmp / "gpu.lock").exists())
            resources = json.loads((tmp / "run/runtime/session-01/resources.json").read_text(encoding="utf-8"))
            self.assertEqual((resources["gpu_used_mib"], resources["ram_used_gib"]), (15000, 50.5))
            self.assertEqual(resources["log_events"], {"reasoning_recoveries": 0, "nonfinite_logits": 1})
            self.assertTrue((tmp / "run/runtime/session-01/strata.json").is_file())


if __name__ == "__main__":
    unittest.main()
