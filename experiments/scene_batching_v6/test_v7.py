"""Offline tests for the v7 gap-aware packing and pause marks (no GPU, model, network or .local data)."""

from __future__ import annotations

import itertools
import json
import random
import tempfile
import unittest
from pathlib import Path

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches, gap_groups, gap_pack_cuts, silence, visible_pauses
from experiments.translation_v3.common import atomic_write_json
from experiments.translation_v3.data import Cue, Scene
from experiments.translation_v3.generate import translate_scene
from experiments.translation_v3.test_support import FakeClient
from experiments.scene_batching_v6 import q2, sim7, v7
from experiments.scene_batching_v6.test_v6 import RECORDED_HASHES

GSNAP5 = ("b10-joint", {"gap_split": {"snap": 2, "max": 12, "cut_gap": 5.0, "context_gap": 5.0, "max_visible": 12}},
          "f58afa3352a534f6dc6e957980547246c3b80c696a48851f6d6816a81d1846d3")
PACK = {"min": 6, "max": 12, "soft_gap": 2.0, "hard_gap": 10.0, "soft_weight": 1.0, "small_penalty": 1000.0,
        "group_gap": None, "group_max": 12, "context_both_below": 1.0, "context_before_below": 5.0, "max_visible": 12}
GROUPED = PACK | {"group_gap": 1.0}
DP6 = R.compose("dp6", "b10-joint", gap_pack=dict(PACK))
GRP = R.compose("dp6-grp", "b10-joint", gap_pack=dict(GROUPED))
MARK5 = R.compose("mark5", "b10-joint", pause_marks={"min_gap": 5.0})
CUT = R.BUILTIN["dp10-cut"]


def scene_from_gaps(gaps: list[float | None], name: str = "S") -> Scene:
    """Cues of 1 s each separated by the given silences (None: the next cue has no timestamps)."""
    cues, t = [Cue(f"{name}-J000", "台詞0", 0.0, 1.0)], 1.0
    for i, gap in enumerate(gaps, 1):
        if gap is None:
            cues.append(Cue(f"{name}-J{i:03d}", f"台詞{i}"))
            continue
        t += gap
        cues.append(Cue(f"{name}-J{i:03d}", f"台詞{i}", t, t + 1.0))
        t += 1.0
    return Scene(name, tuple(cues), "W01", "anime_series")


def random_gaps(rng: random.Random, n: int) -> list[float | None]:
    return [rng.choice([0.2, 0.5, 0.8, 1.5, 3.0, 6.0, 12.0, 40.0, None]) for _ in range(n - 1)]


def cost(scene: Scene, cuts: list[int], pack: dict, target: int = 10) -> float | None:
    total, bounds = 0.0, cuts + [len(scene.cues)]
    for a, b in zip(bounds, bounds[1:]):
        if b - a > pack["max"]:
            return None
        gaps = [g for i in range(a, b - 1) if (g := silence(scene, i)) is not None]
        if any(g >= pack["hard_gap"] for g in gaps):
            return None
        total += (b - a - target) ** 2 + (pack["small_penalty"] if b - a < pack["min"] else 0)
        total += sum(pack["soft_weight"] * g for g in gaps if g >= pack["soft_gap"])
        if b < len(scene.cues) and pack.get("cut_penalty"):
            g = silence(scene, b - 1)
            total += next((p for below, p in pack["cut_penalty"] if g is None or g < below), 0.0)
    return total


class HashTest(unittest.TestCase):
    def test_recorded_hashes_unchanged(self):
        for name, (base, overrides, digest) in (RECORDED_HASHES | {"gsnap5": GSNAP5}).items():
            recipe = R.compose(name, base, **overrides) if overrides else R.BUILTIN[base]
            self.assertEqual(recipe.recipe_hash, digest, name)
            self.assertFalse({"gap_pack", "pause_marks"} & set(recipe.spec()["recipe"]))
            self.assertFalse({"gap_pack", "pause_marks"} & set(recipe.spec()["versions"]))

    def test_new_fields_enter_hash(self):
        base = R.BUILTIN["b10-joint"].recipe_hash
        hashes = {DP6.recipe_hash, GRP.recipe_hash, MARK5.recipe_hash, base}
        self.assertEqual(len(hashes), 4)
        self.assertEqual(DP6.spec()["versions"]["gap_pack"], R.GAP_PACK_VERSION)
        self.assertEqual(MARK5.spec()["versions"]["pause_marks"][:2], [R.PAUSE_MARK_VERSION, R.PAUSE_MARK_KEY])
        self.assertNotEqual(R.compose("x", "b10-joint", gap_pack=PACK | {"soft_weight": 2.0}).recipe_hash, DP6.recipe_hash)

    def test_validation(self):
        for bad in (PACK | {"min": 11}, PACK | {"max": 9}, PACK | {"max_visible": 11}, PACK | {"group_max": 13},
                    PACK | {"soft_gap": 10.0}, PACK | {"soft_weight": -1}, PACK | {"group_gap": 0},
                    PACK | {"context_both_below": 6.0}, {k: v for k, v in PACK.items() if k != "min"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                R.compose("x", "b10-joint", gap_pack=bad)
        with self.assertRaises(ValueError):
            R.compose("x", "b10-joint", gap_pack=PACK, gap_split=GSNAP5[1]["gap_split"])
        for bad in ({}, {"min_gap": 0}, {"min_gap": 5, "x": 1}):
            with self.assertRaises(ValueError):
                R.compose("x", "b10-joint", pause_marks=bad)


class CutPenaltyTest(unittest.TestCase):
    """gap-pack-v2 (ADR-0010): per-cut penalty by the silence at the cut, used by dp10-cut."""

    def test_identity_and_validation(self):
        self.assertEqual(CUT.spec()["versions"]["gap_pack"], R.GAP_PACK_V2_VERSION)
        self.assertEqual(GRP.spec()["versions"]["gap_pack"], R.GAP_PACK_VERSION)
        self.assertNotEqual(R.compose("x", "dp10-cut", gap_pack=CUT.gap_pack | {"cut_penalty": [[1.0, 3.0]]}).recipe_hash,
                            CUT.recipe_hash)
        for bad in ([], [[1.0]], [[1.0, 0]], [[1.0, 3.0], [0.5, 6.0]], [(0.5, 6.0)], "x"):
            with self.assertRaises(ValueError, msg=str(bad)):
                R.compose("x", "dp10-cut", gap_pack=CUT.gap_pack | {"cut_penalty": bad})

    def test_dp_matches_brute_force(self):
        rng = random.Random(13)
        pack = CUT.gap_pack
        for trial in range(150):
            n = rng.randint(1, 15)
            scene = scene_from_gaps(random_gaps(rng, n))
            best = min(c for r in range(n) for inner in itertools.combinations(range(1, n), r)
                       if (c := cost(scene, [0, *inner], pack)) is not None)
            self.assertAlmostEqual(cost(scene, gap_pack_cuts(scene, 10, pack), pack), best, msg=f"trial {trial}")

    def test_cut_moves_to_longer_pause(self):
        # 18 cues: without a cut penalty the best split is 9/9 at a 0.2 s pause; with it, 10/8 at the 1.5 s pause
        scene = scene_from_gaps([0.2] * 9 + [1.5] + [0.2] * 7)
        self.assertEqual(gap_pack_cuts(scene, 10, CUT.gap_pack | {"cut_penalty": [[0.0001, 1.0]]}), [0, 9])
        self.assertEqual(gap_pack_cuts(scene, 10, CUT.gap_pack), [0, 10])

    def test_random_scene_invariants(self):
        rng = random.Random(17)
        for _ in range(200):
            scene = scene_from_gaps(random_gaps(rng, rng.randint(1, 80)))
            batches = build_batches(scene, CUT)
            self.assertEqual([k for b in batches for k in b.target_ids], scene.ids)
            hard = {i + 1 for i in range(len(scene.cues) - 1) if (g := silence(scene, i)) is not None and g >= 20}
            self.assertTrue(hard <= {b.start for b in batches})
            for b in batches:
                self.assertLessEqual(len(b.target_ids), 10)
                self.assertLessEqual(len(b.before_ids) + len(b.target_ids) + len(b.after_ids), 12)


class PackTest(unittest.TestCase):
    def test_dp_matches_brute_force(self):
        rng = random.Random(7)
        for trial in range(150):
            n = rng.randint(1, 15)
            scene = scene_from_gaps(random_gaps(rng, n))
            for pack in (PACK, GROUPED):
                allowed = set(gap_groups(scene, pack["group_gap"], pack["group_max"], 10)) if pack["group_gap"] else set(range(n))
                best = min(c for r in range(n) for inner in itertools.combinations(sorted(allowed - {0}), r)
                           if (c := cost(scene, [0, *inner], pack)) is not None)
                cuts = gap_pack_cuts(scene, 10, pack)
                self.assertAlmostEqual(cost(scene, cuts, pack), best, msg=f"trial {trial}")
                self.assertTrue(set(cuts) <= allowed)

    def test_random_scene_invariants(self):
        rng = random.Random(11)
        for _ in range(200):
            scene = scene_from_gaps(random_gaps(rng, rng.randint(1, 80)))
            for recipe in (DP6, GRP):
                batches = build_batches(scene, recipe)
                self.assertEqual([k for b in batches for k in b.target_ids], scene.ids)
                hard = [i + 1 for i in range(len(scene.cues) - 1) if (g := silence(scene, i)) is not None and g >= 10]
                starts = {b.start for b in batches}
                self.assertTrue(set(hard) <= starts)  # never across a hard boundary
                for b in batches:
                    self.assertLessEqual(len(b.target_ids), 12)
                    self.assertLessEqual(len(b.before_ids) + len(b.target_ids) + len(b.after_ids), 12)
                    self.assertEqual(b.pauses, ())
                if recipe is DP6:  # a short batch only where its hard-bounded segment is shorter than 6
                    edges = [0, *hard, len(scene.cues)]
                    for b in batches:
                        if len(b.target_ids) < 6:
                            seg = next(e2 - e1 for e1, e2 in zip(edges, edges[1:]) if e1 <= b.start < e2)
                            self.assertLess(seg, 6)

    def test_groups(self):
        # one 25-cue group splits 9/8/8; a 12-cue group stays whole; gaps >= 1 s end a group
        scene = scene_from_gaps([0.5] * 24 + [1.0] + [0.2] * 9 + [None, 0.3])
        self.assertEqual(gap_groups(scene, 1.0, 12, 10), [0, 9, 17, 25])
        self.assertEqual(gap_groups(scene_from_gaps([0.5] * 11), 1.0, 12, 10), [0])

    def test_neighbour_rules(self):
        # two batches of 10; the silence between them decides the neighbours
        scene = scene_from_gaps([0.5] * 9 + [0.5] + [0.5] * 9)
        batches = build_batches(scene, DP6)
        self.assertEqual([len(b.target_ids) for b in batches], [10, 10])
        self.assertEqual((len(batches[1].before_ids), len(batches[0].after_ids)), (1, 1))
        for gap, expected in ((0.9, (1, 1)), (1.0, (1, 0)), (4.9, (1, 0)), (5.0, (0, 0))):
            scene = scene_from_gaps([0.1] * 9 + [gap] + [0.1] * 9)
            first, second = build_batches(scene, DP6)
            self.assertEqual((len(second.before_ids), len(first.after_ids)), expected, gap)
        scene = scene_from_gaps([0.1] * 9 + [None] + [0.1] * 9)
        first, second = build_batches(scene, DP6)
        self.assertEqual((len(second.before_ids), len(first.after_ids)), (1, 1))
        # 12 targets leave no room: the after side goes first, then the before side
        scene = scene_from_gaps([0.1] * 23)
        self.assertEqual([len(b.target_ids) for b in build_batches(scene, DP6)], [12, 12])
        self.assertEqual([(len(b.before_ids), len(b.after_ids)) for b in build_batches(scene, DP6)], [(0, 0), (0, 0)])
        scene = scene_from_gaps([0.1] * 21)
        self.assertEqual([(len(b.target_ids), len(b.before_ids), len(b.after_ids)) for b in build_batches(scene, DP6)],
                         [(11, 0, 1), (11, 1, 0)])


class PauseMarkTest(unittest.TestCase):
    def test_batches_equal_b10_joint_apart_from_pauses(self):
        rng = random.Random(3)
        for _ in range(50):
            scene = scene_from_gaps(random_gaps(rng, rng.randint(1, 60)))
            own, ctl = build_batches(scene, MARK5), build_batches(scene, R.BUILTIN["b10-joint"])
            self.assertEqual([(b.target_ids, b.before_ids, b.after_ids) for b in own],
                             [(b.target_ids, b.before_ids, b.after_ids) for b in ctl])
            for b in own:
                lo = b.start - len(b.before_ids)
                self.assertEqual(b.pauses, visible_pauses(scene, lo, b.stop + len(b.after_ids), 5.0))
                self.assertTrue(all(g >= 5.0 for _, g in b.pauses))

    def test_marks_in_prompt_only(self):
        scene = scene_from_gaps([0.1, 7.4, 0.1, 30.0] + [0.1] * 7)
        batch = build_batches(scene, MARK5)[0]
        self.assertEqual(batch.pauses, ((2, 7.4), (4, 30.0)))
        window = batch.to_window(scene)
        plain = R.render_translation(R.BUILTIN["b10-joint"], window)
        marked = R.render_translation(MARK5, window, pauses=batch.pauses)
        self.assertEqual(R.render_translation(MARK5, window), plain)  # no pauses -> b10-joint prompt
        context = json.loads(marked.split("【只读日文上下文】\n", 1)[1].split("\n【待译 JSON】", 1)[0])
        self.assertEqual(context[2], {"pause": "此处约7秒无台词"})
        self.assertEqual(context[5], {"pause": "此处约30秒无台词"})
        self.assertEqual([c for c in context if "pause" not in c], window["context"])
        self.assertEqual(marked.split("【待译 JSON】", 1)[1], plain.split("【待译 JSON】", 1)[1])
        self.assertIn(R.JOINT_INSTRUCTION, marked)
        self.assertEqual(R.translation_grammar(MARK5, list(batch.target_ids)),
                         R.translation_grammar(R.BUILTIN["b10-joint"], list(batch.target_ids)))
        self.assertEqual(batch.record()["pauses"], [[2, 7.4], [4, 30.0]])
        self.assertNotIn("pauses", build_batches(scene, R.BUILTIN["b10-joint"])[0].record())

    def test_generation_sends_marks(self):
        scene = scene_from_gaps([0.1, 7.4] + [0.1] * 9)
        client = FakeClient()
        row = translate_scene(client, scene, MARK5, 7, {}, None)
        self.assertEqual(row["status"], "complete")
        prompts = ["".join(chr(t) for t in r["prompt"]) for r in client.requests]
        self.assertIn('{"pause": "此处约7秒无台词"}', prompts[0])
        self.assertNotIn('"pause"', prompts[1])

    def test_affected_includes_pause_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene = scene_from_gaps([0.1] * 4 + [7.0] + [0.1] * 14)
            for name, recipe in (("cand", MARK5), ("ctl", R.BUILTIN["b10-joint"])):
                atomic_write_json(Path(tmp) / name / "scenes" / "S.json",
                                  {"scene_id": "S", "batches": [b.record() for b in build_batches(scene, recipe)]})
            affected = q2.affected_cues(q2._batch_map(Path(tmp) / "cand"), q2._batch_map(Path(tmp) / "ctl"))
            self.assertEqual(affected, scene.ids[:10])


class DecisionTest(unittest.TestCase):
    def test_noninferiority_and_significance(self):
        def boot(lo, hi):
            return {"ci90": [lo, hi]}
        report = {"full": {"accuracy": {"delta": {"anime_series": -0.02, "animation_movie": 0.03, "overall": 0.005},
                                        "bootstrap": {"anime_series": boot(-0.05, 0.01), "animation_movie": boot(0.001, 0.06),
                                                      "overall": boot(-0.02, 0.03)}}},
                  "safety": {"critical": {"delta": {"overall": 0.001}}}}
        out = v7.decision(report)
        self.assertTrue(out["anime_series"]["noninferior"])
        self.assertFalse(out["animation_movie"]["noninferior"])
        self.assertTrue(out["animation_movie"]["significantly_worse"])
        self.assertFalse(out["noninferior_both"])
        self.assertTrue(out["critical_not_up"])


class SimTest(unittest.TestCase):
    def test_summary_counts(self):
        scene = scene_from_gaps([0.1] * 9 + [12.0] + [0.1] * 4)
        control = R.BUILTIN["b10-joint"]
        base = sim7.summarize([scene], control, control)
        self.assertEqual((base["requests"], base["cross_ge_10s"], base["affected_cue_share"]), (2, 0.0, 0.0))
        dp = sim7.summarize([scene], DP6, control)
        self.assertEqual(dp["requests"], 2)
        self.assertEqual(dp["affected_cue_share"], 1.0)  # neighbours across the 12 s gap are dropped
        mark = sim7.summarize([scene_from_gaps([0.1] * 4 + [6.0] + [0.1] * 4)], MARK5, control)
        self.assertEqual((mark["batches_with_pause_marks"], mark["pause_marks"]), (1.0, 1))


if __name__ == "__main__":
    unittest.main()
