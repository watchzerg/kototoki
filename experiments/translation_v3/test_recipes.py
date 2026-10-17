import json
import tempfile
import unittest
from pathlib import Path

from experiments.translation_demo import adapters
from experiments.translation_flow import v2_prepare, v2_recipes
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches, cue_positions
from experiments.translation_v3.test_support import make_scene


class C0EquivalenceTest(unittest.TestCase):
    def test_c0_prompt_grammar_request_match_v2(self):
        scene = make_scene("F2-W01_E001-S00001", 12)
        batch = build_batches(scene, R.BUILTIN["c0"])[1]
        window = batch.to_window(scene)
        item = {"recipe": "c0", "sampling": "official", "n_predict": 4096, "cache_prompt": True,
                "seed": 20261008, "max_attempts": 2}
        v2_prompt = v2_recipes.render_window("c0", window, item)
        v3_prompt = R.render_translation(R.BUILTIN["c0"], window)
        self.assertEqual(v3_prompt, v2_prompt)
        self.assertEqual(v3_prompt, adapters.render("hy-mt2-30b", window))
        tokens = [ord(ch) for ch in v3_prompt]
        ids = window["translate_ids"]
        v2_request = v2_recipes.completion_request(item, tokens, ids)
        v3_request = R.completion_request(tokens, 20261008, R.translation_grammar(R.BUILTIN["c0"], ids))
        self.assertEqual(json.dumps(v3_request, ensure_ascii=False), json.dumps(v2_request, ensure_ascii=False))

    def test_joint_changes_only_the_independence_instruction(self):
        scene = make_scene("S", 7)
        window = build_batches(scene, R.BUILTIN["c0"])[0].to_window(scene)
        c0 = R.render_translation(R.BUILTIN["c0"], window)
        joint = R.render_translation(R.BUILTIN["joint"], window)
        self.assertEqual(joint, c0.replace(R.C0_INSTRUCTION, R.JOINT_INSTRUCTION))
        self.assertNotEqual(joint, c0)

    def test_bounded_whitespace_grammar(self):
        ids = ["a", "b"]
        unbounded = R.translation_grammar(R.BUILTIN["c0"], ids)
        bounded = R.translation_grammar(R.BUILTIN["bws"], ids)
        self.assertEqual(bounded, unbounded.replace(R.UNBOUNDED_WS, R.BOUNDED_WS))
        self.assertNotIn("[ \\t\\n\\r]*", bounded)


class RecipeIdentityTest(unittest.TestCase):
    def test_hash_is_stable_and_name_independent(self):
        self.assertEqual(R.Recipe("c0").recipe_hash, R.BUILTIN["c0"].recipe_hash)
        self.assertEqual(R.compose("alias", "c0").recipe_hash, R.BUILTIN["c0"].recipe_hash)
        hashes = {r.recipe_hash for r in R.BUILTIN.values()}
        self.assertEqual(len(hashes), len(R.BUILTIN))

    def test_compose_and_files(self):
        combo = R.compose("tok400-ctx3", "tok400", context_before=3, context_after=3)
        self.assertEqual((combo.token_target, combo.batch_count, combo.context_before), (400, None, 3))
        self.assertEqual(R.compose("x", "tok400", batch_count=10).token_target, None)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "recipes").mkdir()
            (root / "recipes/tok400-joint.json").write_text(json.dumps({"name": "tok400-joint", "base": "tok400", "prompt": "joint"}), encoding="utf-8")
            loaded = R.load_recipe("tok400-joint", root)
            self.assertEqual((loaded.token_target, loaded.prompt), (400, "joint"))
            (root / "recipes/c0.json").write_text(json.dumps({"name": "c0", "batch_count": 7}), encoding="utf-8")
            with self.assertRaises(ValueError):
                R.load_recipe("c0", root)
        with self.assertRaises(ValueError):
            R.Recipe("bad__name")
        with self.assertRaises(ValueError):
            R.Recipe("x", batch_count=5, token_target=300)
        with self.assertRaises(ValueError):
            R.load_recipe("nope")

    def test_terms_parse_keeps_recurring_verbatim_terms(self):
        cues = [{"id": "a", "text": "ライオスが来た"}, {"id": "b", "text": "ライオス！"}, {"id": "c", "text": "マルシル"}]
        text = json.dumps({"terms": [{"source": "ライオス", "translation": "莱欧斯"},
                                     {"source": "マルシル", "translation": "玛露西尔"}]}, ensure_ascii=False)
        parsed = R.parse_terms(text, cues)
        self.assertEqual([t["source"] for t in parsed["terms"]], ["ライオス"])
        self.assertEqual(parsed["terms"][0]["evidence_ids"], ["a", "b"])
        self.assertEqual(parsed["rejected"], 1)
        window = {"context": [{"id": "c", "text": "x"}]}
        self.assertEqual(R.terms_for_window(parsed["terms"], window), [])
        self.assertIn('"\\"translation\\""', R.terms_grammar())
        self.assertIn(R.BOUNDED_WS, R.terms_grammar("bounded"))
        prompt = R.terms_prompt(cues)
        self.assertNotIn('"a"', prompt)
        self.assertIn("ライオスが来た\nライオス！\nマルシル", prompt)
        with self.assertRaises(ValueError):
            R.parse_terms('{"terms":[{"source":"x"}]}', cues)

    def test_risk_trigger(self):
        self.assertTrue(R.risk_triggered(["行かない"]))
        self.assertTrue(R.risk_triggered(["雨が降ったら"]))
        self.assertFalse(R.risk_triggered(["おはよう"]))


class BatchingTest(unittest.TestCase):
    def v2(self, scene, **kwargs):
        windows, _ = v2_prepare.pack_scene({"id": scene.scene_id, "scene_id": scene.scene_id, "translate_ids": scene.ids,
                                            "context": [{"id": c.id, "text": c.text} for c in scene.cues]}, **kwargs)
        return windows

    def test_matches_v2_packing(self):
        scene = make_scene("S", 23)
        for name, kwargs in (("c0", {}), ("b3", {"target_size": 3}), ("ctx3-1", {"context_before": 3, "context_after": 1}),
                             ("ctx0", {"context_before": 0, "context_after": 0})):
            batches = build_batches(scene, R.BUILTIN[name])
            self.assertEqual([b.to_window(scene) for b in batches], self.v2(scene, **kwargs), name)
        counts = {c.id: 40 + (i % 7) * 30 for i, c in enumerate(scene.cues)}
        batches = build_batches(scene, R.BUILTIN["tok300"], counts)
        self.assertEqual([b.to_window(scene) for b in batches], self.v2(scene, token_target=300, token_counts=counts))
        self.assertTrue(all(b.source_token_count <= 300 or len(b.target_ids) == 1 for b in batches))

    def test_positions_and_coverage(self):
        scene = make_scene("S", 11)
        batches = build_batches(scene, R.BUILTIN["c0"])
        self.assertEqual([len(b.target_ids) for b in batches], [5, 5, 1])
        self.assertEqual(batches[1].before_ids, (scene.ids[4],))
        self.assertEqual(batches[1].after_ids, (scene.ids[10],))
        positions = cue_positions(batches)
        self.assertEqual(set(positions), set(scene.ids))
        self.assertEqual(positions[scene.ids[0]]["position"], "first")
        self.assertEqual(positions[scene.ids[2]]["position"], "mid")
        self.assertEqual(positions[scene.ids[9]], {"batch_index": 1, "position": "last", "offset": 4, "batch_size": 5})
        self.assertEqual(positions[scene.ids[10]]["position"], "single")
        with self.assertRaises(ValueError):
            build_batches(scene, R.BUILTIN["tok400"], None)


if __name__ == "__main__":
    unittest.main()


class CategoryRoutingTest(unittest.TestCase):
    def test_unrouted_hash_is_unchanged_by_the_field(self):
        spec = R.BUILTIN["c0"].spec()
        self.assertNotIn("category_overrides", spec["recipe"])
        self.assertNotIn("routed", spec["versions"])

    def test_routes_by_scene_category(self):
        route = R.compose("route", "b10", category_overrides={"animation_movie": {"batch_count": 5, "prompt": "joint"}})
        series, movie = route.for_category("anime_series"), route.for_category("animation_movie")
        self.assertEqual((series.batch_count, series.prompt, series.category_overrides), (10, "c0", None))
        self.assertEqual((movie.batch_count, movie.prompt), (5, "joint"))
        self.assertIn("routed", route.spec()["versions"])
        self.assertNotEqual(route.recipe_hash, R.BUILTIN["b10"].recipe_hash)
        with self.assertRaises(ValueError):
            route.for_category(None)
        self.assertEqual(build_batches(make_scene("S", 12), movie)[0].target_ids,
                         build_batches(make_scene("S", 12), R.BUILTIN["c0"])[0].target_ids)

    def test_routing_validation_and_token_counts(self):
        with self.assertRaises(ValueError):
            R.compose("x", "c0", category_overrides={"documentary": {"batch_count": 5}})
        with self.assertRaises(ValueError):
            R.compose("x", "c0", category_overrides={"animation_movie": {"name": "y"}})
        with self.assertRaises(ValueError):
            R.compose("x", "c0", category_overrides={"animation_movie": {"batch_count": 0}})
        tok = R.compose("x", "c0", category_overrides={"anime_series": {"token_target": 400}})
        self.assertTrue(tok.needs_token_counts)
        self.assertFalse(R.BUILTIN["c0"].needs_token_counts)
        self.assertTrue(R.BUILTIN["tok400"].needs_token_counts)

    def test_routed_recipe_loads_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "recipes").mkdir()
            (root / "recipes" / "route.json").write_text(json.dumps(
                {"name": "route", "base": "b10", "category_overrides": {"animation_movie": {"batch_count": 5}}}),
                encoding="utf-8")
            recipe = R.load_recipe("route", root)
            self.assertEqual(recipe.for_category("animation_movie").batch_count, 5)


class AdoptedBaselineTest(unittest.TestCase):
    def test_b10_joint_identity_is_pinned(self):
        # ADR-0006: the adopted flow baseline must keep the hash of the screened/confirmed runs.
        recipe = R.BUILTIN["b10-joint"]
        self.assertEqual((recipe.batch_count, recipe.context_before, recipe.context_after, recipe.prompt),
                         (10, 1, 1, "joint"))
        self.assertEqual(recipe.recipe_hash, "2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a")

    def test_dp6_grp_identity_is_pinned(self):
        # ADR-0009: the adopted flow baseline keeps the hash of the v7 screening/replicate runs.
        recipe = R.BUILTIN["dp6-grp"]
        self.assertEqual((recipe.batch_count, recipe.context_before, recipe.context_after, recipe.prompt),
                         (10, 1, 1, "joint"))
        self.assertEqual(recipe.gap_pack["group_gap"], 1.0)
        self.assertEqual(recipe.recipe_hash, "ae473cdce915b16379a838cec15fc53e444d24686cd36c706e5f9d379ba2061e")
