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

    def test_dp10_cut_identity_is_pinned(self):
        # ADR-0010: the adopted flow baseline since 2026-10-17 (at most 10 targets, visible <= 12, hard 20 s).
        recipe = R.BUILTIN["dp10-cut"]
        self.assertEqual((recipe.batch_count, recipe.context_before, recipe.context_after, recipe.prompt),
                         (10, 1, 1, "joint"))
        self.assertEqual((recipe.gap_pack["max"], recipe.gap_pack["max_visible"], recipe.gap_pack["hard_gap"]), (10, 12, 20.0))
        self.assertEqual(recipe.recipe_hash, "ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70")


class GroupReorderTest(unittest.TestCase):
    """v8 group-reorder-v1: R2+ sentence groups, joint-understanding-v2 and the grp1 recipe."""

    # Hashes of every builtin before the groups field existed (2026-10-18); the field must not move them.
    PINNED = {
        "c0": "f2a7501767abc205ceac336d5887061a77a3b00774cf9eb003445f8057d056a5",
        "b3": "72690135e44d96d1824dfd6d5ba045637283aad8c4d7c81d03cbae97b20cef97",
        "b10": "cadbbe18d19a0ad2defe7cac1be1f5e42de93934285bdf08fbbdf8726691917f",
        "b20": "22985c94d39c8fabe97caab1cfa7049f93f55af30196e9e70972f570bf0c7dc0",
        "tok300": "a26ea3cea41f8ed5e6b9ec9aaa67fb60a28a8435ca01ef835628032e79d5c2ec",
        "tok400": "0621d84e342eec9dbf2dc2ee7cb5ca9407af1eafbfee01bfe2f55ac63e183c1c",
        "tok500": "fe3f08c0fd37fa41005a33d2936f13e1658abc13baed5428fbe75f7f02ca56f7",
        "ctx0": "d37713c9326a0ca31c961d90ee6e74e7a1c9ce62dda25414925bb5b4f5969bfc",
        "ctx3": "d62ce9cd5e8e9caf898f4ab31385c520daf7cb3e6941fbb4dbcef4e1e1dd5620",
        "ctx3-1": "55f49a894051de33e5c7188277c560a703b59c2f20fa7a1d659df9e6a46ff913",
        "joint": "79aca240d504ec053ee87b55c23527b3149a2fb3fec69aa8ee3bb195ddebf4bc",
        "terms": "abbd3b2c369d9030e449b24e4b4c7303933dcee407fc55b63dec396ea0da4d4f",
        "review": "274ac47a0bd827b7a3d1e3143b1a728b35e8a0a815bd715912620179bdb2d906",
        "bws": "f1ccc3db3f597365cd481c1dbb0da421aa842e85db8dcffa6d95962e75b952f1",
        "b10-joint": "2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a",
        "dp6-grp": "ae473cdce915b16379a838cec15fc53e444d24686cd36c706e5f9d379ba2061e",
        "dp10-cut": "ee72ce6683c89e5a1f83fd7ba99f54f3683966deed0e526c193780ad8c500b70",
    }

    @staticmethod
    def scene():
        from experiments.translation_v3.data import Cue, Scene
        # silences: 0.2, 0.3 (after ?), 0.2, 1.0 (= gap), -0.1 (overlap), 0.2 (after 」 closing 。), 0.4, None
        rows = [("あの", 0.0, 1.0), ("そうか?", 1.2, 2.0), ("でも…", 2.3, 3.0), ("それで、", 3.2, 4.0),
                ("はい", 5.0, 6.0), ("「行くぞ。」", 5.9, 7.0), ("うん", 7.2, 8.0), ("え", 8.4, None), ("お", None, 10.0)]
        return Scene("S", tuple(Cue(f"c{i}", text, start, end) for i, (text, start, end) in enumerate(rows)),
                     "W01", "anime_series")

    def test_existing_hashes_unchanged(self):
        self.assertEqual({k: R.BUILTIN[k].recipe_hash for k in self.PINNED}, self.PINNED)
        self.assertNotIn("groups", R.BUILTIN["dp10-cut"].spec()["recipe"])
        self.assertNotIn("groups", R.BUILTIN["dp10-cut"].spec()["versions"])

    def test_grp1_is_dp10_cut_plus_groups(self):
        grp1, base = R.BUILTIN["grp1"], R.BUILTIN["dp10-cut"]
        self.assertEqual(grp1, R.compose("grp1", "dp10-cut", groups={"gap": 1.0}))
        self.assertEqual(grp1.recipe_hash, "5aaf3e776bd39cf4fe718fc5016ece54f71685181af695e0c2f9cfb9a8792eaa")
        self.assertEqual(grp1.spec()["versions"]["groups"][0], R.GROUPS_VERSION)
        scene = make_scene("S", 37)
        strip = lambda b: (b.target_ids, b.before_ids, b.after_ids, b.pauses)
        self.assertEqual([strip(b) for b in build_batches(scene, grp1)], [strip(b) for b in build_batches(scene, base)])
        ids = ["a", "b"]
        self.assertEqual(R.translation_grammar(grp1, ids), R.translation_grammar(base, ids))

    def test_sentence_groups_rule(self):
        from experiments.translation_v3.batching import ends_sentence, sentence_groups
        self.assertTrue(ends_sentence("「行くぞ。」 "))
        self.assertTrue(ends_sentence("そうか?"))
        self.assertFalse(ends_sentence("でも…"))
        self.assertFalse(ends_sentence("それで、"))
        self.assertFalse(ends_sentence(""))
        scene = self.scene()
        self.assertEqual(sentence_groups(scene, 0, 9, 1.0), [(0, 2), (2, 4), (4, 6), (6, 9)])
        self.assertEqual(sentence_groups(scene, 0, 9, 1.5), [(0, 2), (2, 6), (6, 9)])
        self.assertEqual(sentence_groups(scene, 3, 5, 1.0), [(3, 4), (4, 5)])
        self.assertEqual(sentence_groups(scene, 7, 9, 1.0), [(7, 9)])

    def test_batch_groups_and_prompt(self):
        scene = self.scene()
        recipe = R.compose("g", "joint", batch_count=5, groups={"gap": 1.0})
        batches = build_batches(scene, recipe)
        self.assertEqual([b.groups for b in batches], [(("c0", "c1"), ("c2", "c3")), (("c6", "c7", "c8"),)])
        self.assertEqual(batches[0].record()["groups"], [["c0", "c1"], ["c2", "c3"]])
        window = batches[0].to_window(scene)
        plain = R.render_translation(R.BUILTIN["joint"], window)
        grouped = R.render_translation(recipe, window, groups=batches[0].groups)
        line = R.GROUPS_INJECTION + '{"groups": [["c0", "c1"], ["c2", "c3"]]}'
        self.assertEqual(grouped, R.inject(plain.replace(R.JOINT_INSTRUCTION, R.JOINT2_INSTRUCTION), line))
        # No group of >= 2 targets: identical to the recipe without groups.
        self.assertEqual(R.render_translation(recipe, window), plain)
        lone = R.compose("g1", "joint", batch_count=1, groups={"gap": 1.0})
        self.assertTrue(all(b.groups == () for b in build_batches(scene, lone)))
        with self.assertRaises(ValueError):
            R.render_translation(R.BUILTIN["joint"], window, groups=batches[0].groups)
        with self.assertRaises(ValueError):
            R.render_translation(recipe, window, groups=(("c0",),))
        with self.assertRaises(ValueError):
            R.render_translation(recipe, window, groups=(("c0", "c9"),))

    def test_groups_validation(self):
        with self.assertRaises(ValueError):
            R.compose("x", "c0", groups={"gap": 1.0})
        for bad in ({"gap": 0}, {"gap": "1"}, {"gap": 1.0, "max": 6}, {}):
            with self.assertRaises(ValueError):
                R.compose("x", "joint", groups=bad)
