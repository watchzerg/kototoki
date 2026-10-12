import json
import tempfile
import unittest
from pathlib import Path

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.common import read_json
from experiments.translation_v3.generate import run_generation, run_id_for
from experiments.translation_v3.mbr import chrf, mbr_index, select
from experiments.translation_v3.test_support import FakeClient, FakeSessions, make_scene

from experiments.translation_v4 import reference as REF
from experiments.translation_v4.gen import seed_block

# Hashes recorded in the v3 runs (before the v4 fields existed): the new fields must not move them.
V3_HASHES = {"c0": "f2a7501767abc205ceac336d5887061a77a3b00774cf9eb003445f8057d056a5",
             "b10-joint": "2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a",
             "joint": "79aca240d504ec053ee87b55c23527b3149a2fb3fec69aa8ee3bb195ddebf4bc",
             "tok400": "0621d84e342eec9dbf2dc2ee7cb5ca9407af1eafbfee01bfe2f55ac63e183c1c"}


def quiet(_message: str) -> None:
    pass


class RecordingClient(FakeClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prompts = []

    def complete(self, request):
        self.prompts.append("".join(chr(t) for t in request["prompt"]))
        return super().complete(request)


class VariedClient(RecordingClient):
    """Sample-dependent output: the seed decides one of three wordings."""

    def complete(self, request):
        response = super().complete(request)
        content = json.loads(response["content"])
        variant = ["甲", "甲", "乙"][request["seed"] % 3]
        content["translations"] = {k: v + variant for k, v in content["translations"].items()}
        return response | {"content": json.dumps(content, ensure_ascii=False)}


class RecipeFieldsTest(unittest.TestCase):
    def test_v3_hashes_unchanged(self):
        for name, digest in V3_HASHES.items():
            self.assertEqual(R.BUILTIN[name].recipe_hash, digest, name)

    def test_sampling_override_request(self):
        recipe = R.compose("t0", "b10-joint", sampling={"temperature": 0.0})
        self.assertNotEqual(recipe.recipe_hash, R.BUILTIN["b10-joint"].recipe_hash)
        base = R.completion_request([1, 2], 5, "g")
        request = R.completion_request([1, 2], 5, "g", recipe.sampling)
        self.assertEqual(list(base), list(request))
        self.assertEqual(request["temperature"], 0.0)
        self.assertEqual({k: v for k, v in request.items() if k != "temperature"},
                         {k: v for k, v in base.items() if k != "temperature"})
        self.assertEqual(recipe.spec()["versions"]["sampling"], {"temperature": 0.0})
        with self.assertRaises(ValueError):
            R.compose("bad", "c0", sampling={"temperature": 3})
        with self.assertRaises(ValueError):
            R.compose("bad", "c0", sampling={"samplers": ["nucleus"]})

    def test_multi_requires_selector(self):
        with self.assertRaises(ValueError):
            R.compose("m", "b10-joint", candidates=4)
        with self.assertRaises(ValueError):
            R.compose("m", "b10-joint", selector="mbr-chrf-batch")
        recipe = R.compose("m", "b10-joint", candidates=4, selector="mbr-chrf-batch")
        self.assertIn("multi", recipe.spec()["versions"])

    def test_sample_seeds(self):
        self.assertEqual(R.sample_seed(7, 0), 7)
        self.assertEqual(R.sample_seed(7, 2), 7 + 2 * R.SAMPLE_SEED_STRIDE)
        self.assertEqual(R.sample_seed(2**32 - 1, 1), (2**32 - 1 + R.SAMPLE_SEED_STRIDE) % 2**32)


class GenerationV4Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def generate(self, recipe, client, n=23):
        scene = make_scene("S0", n)
        run_id = run_id_for(recipe, 7, "dev")
        run = run_generation(self.root / "runs" / run_id, recipe, 7, [scene], scope="dev", sources={},
                             session_factory=FakeSessions([client]), log=quiet)
        return run, read_json(self.root / "runs" / run_id / "scenes/S0.json")

    def test_target_context_uses_own_earlier_translations(self):
        recipe = R.compose("tctx", "b10-joint", target_context=4)
        client = RecordingClient()
        run, scene = self.generate(recipe, client)
        self.assertEqual(run["completion"]["state"], "complete")
        self.assertNotIn("previous_translations", client.prompts[0])
        second = client.prompts[1].split(R.TARGET_CONTEXT_INJECTION, 1)[1]
        history, _ = json.JSONDecoder().raw_decode(second)
        self.assertEqual([h["zh"] for h in history["previous_translations"]],
                         [scene["translations"][f"S0-J{i:03d}"] for i in range(6, 10)])
        self.assertEqual(history["previous_translations"][0]["ja"], "台詞6ですね")

    def test_multi_sample_selects_and_records(self):
        recipe = R.compose("mbr3", "b10-joint", candidates=3, selector="mbr-chrf-batch")
        client = VariedClient()
        run, scene = self.generate(recipe, client, n=10)
        self.assertEqual(run["completion"]["state"], "complete")
        self.assertEqual([r["seed"] for r in client.requests], [R.sample_seed(7, k) for k in range(3)])
        batch = scene["batches"][0]
        self.assertEqual(len(batch["candidates"]), 3)
        variants = [R.sample_seed(7, k) % 3 for k in range(3)]
        majority = "甲" if [v < 2 for v in variants].count(True) >= 2 else "乙"
        self.assertTrue(scene["translations"]["S0-J000"].endswith(majority))
        self.assertEqual([r.get("sample") for r in scene["requests"]], [0, 1, 2])

    def test_failed_sample_is_dropped(self):
        recipe = R.compose("mbr2", "b10-joint", candidates=2, selector="mbr-chrf-cue")
        # completion 1 = sample 0 first attempt, 2 = retry; both bad -> sample 0 dropped.
        client = RecordingClient(plan={1: "bad_json", 2: "bad_json"})
        run, scene = self.generate(recipe, client, n=10)
        self.assertEqual(run["completion"]["state"], "complete")
        self.assertEqual(scene["batches"][0]["failed_samples"], [{"sample": 0, "kind": "parse"}])


class MbrTest(unittest.TestCase):
    def test_chrf(self):
        self.assertAlmostEqual(chrf("我喜欢猫", "我喜欢猫"), 1.0)
        self.assertLess(chrf("我喜欢猫", "他讨厌狗"), 0.1)
        self.assertGreater(chrf("我很喜欢猫", "我喜欢猫"), chrf("他喜欢狗", "我喜欢猫"))

    def test_mbr(self):
        self.assertEqual(mbr_index(["他讨厌狗", "我喜欢猫", "我喜欢猫咪"]), 1)
        self.assertEqual(mbr_index(["a"]), 0)
        samples = [{"x": "我喜欢猫", "y": "走吧"}, {"x": "他讨厌狗", "y": "走吧"}, {"x": "我喜欢猫咪", "y": "快走"}]
        chosen, record = select("mbr-chrf-cue", samples, ["x", "y"])
        self.assertEqual(chosen, {"x": "我喜欢猫", "y": "走吧"})
        self.assertEqual(record, {"cue": {"x": 0, "y": 0}})


class ReferenceTest(unittest.TestCase):
    def test_tile(self):
        self.assertEqual(REF.tile(12), [(0, 5), (5, 12)])
        self.assertEqual(REF.tile(13), [(0, 5), (5, 10), (10, 13)])
        self.assertEqual(REF.tile(2), [(0, 2)])

    def test_validate_review(self):
        scene = {"cues": [{"id": "a", "ja": "x", "fansub_zh": "甲"}, {"id": "b", "ja": "y", "fansub_zh": None}]}
        row = lambda i, changed, zh="", ct="none", conf="high", why="": {
            "id": i, "changed": changed, "zh_revised": zh, "change_type": ct, "confidence": conf,
            "confidence_reason_zh": why, "ambiguity_zh": ""}
        ok = {"cues": [row("a", False), row("b", True, "乙", "omission")]}
        self.assertEqual(len(REF.validate_review(ok, scene)), 2)
        for bad in ({"cues": [row("a", False), row("b", False)]},                  # null fansub must change
                    {"cues": [row("a", True, "", "mistranslation"), row("b", True, "乙", "omission")]},
                    {"cues": [row("a", False, conf="medium"), row("b", True, "乙", "omission")]},
                    {"cues": [row("b", True, "乙", "omission"), row("a", False)]}):
            with self.assertRaises(Exception):
                REF.validate_review(bad, scene)

    def test_seed_blocks(self):
        self.assertEqual(seed_block("dev", 20261012), 1)
        self.assertEqual(seed_block("dev", 20261023), 2)
        self.assertIsNone(seed_block("confirm", 20261031))
        with self.assertRaises(ValueError):
            seed_block("dev", 1)


if __name__ == "__main__":
    unittest.main()


class DeriveTest(unittest.TestCase):
    def test_derived_runs_match_real_recipe(self):
        from experiments.translation_v4.derive import derive
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "recipes").mkdir()
            (root / "recipes" / "m4.json").write_text(json.dumps({"name": "m4", "base": "b10-joint", "candidates": 4,
                                                                  "selector": "mbr-chrf-batch"}), encoding="utf-8")
            recipe = R.load_recipe("m4", root)
            scene = make_scene("S0", 10)
            run_id = run_id_for(recipe, 7, "dev")
            client = VariedClient()
            run_generation(root / "runs" / run_id, recipe, 7, [scene], scope="dev", sources={},
                           session_factory=FakeSessions([client]), log=quiet)
            three = derive(root, root / "runs" / run_id, "m3-cue", 3, "mbr-chrf-cue")
            one = derive(root, root / "runs" / run_id, "m1", 1, None)
            real = R.compose("m3-cue", "b10-joint", candidates=3, selector="mbr-chrf-cue")
            self.assertEqual(read_json(three / "run.json")["recipe_hash"], real.recipe_hash)
            self.assertEqual(read_json(one / "run.json")["recipe_hash"], R.BUILTIN["b10-joint"].recipe_hash)
            sample0 = read_json(root / "runs" / run_id / "scenes/S0.json")["batches"][0]["candidates"][0]
            self.assertEqual(read_json(one / "scenes/S0.json")["translations"], sample0)
