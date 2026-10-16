"""Offline tests for the v6 scene-batching analysis (no GPU, model, network or .local data)."""

from __future__ import annotations

import random
import unittest

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches, gap_cuts
from experiments.translation_v3.data import Cue, Scene
from experiments.scene_batching_v6 import gaps as G
from experiments.scene_batching_v6 import q2
from experiments.scene_batching_v6 import stats6 as S


def cues(times: list[tuple[float, float]]) -> list[dict]:
    return [{"id": f"c{i}", "start": a, "end": b} for i, (a, b) in enumerate(times)]


class GapsTest(unittest.TestCase):
    def test_cue_gaps_and_missing_timestamps(self):
        rows = cues([(0, 1), (1.5, 2), (30, 31)]) + [{"id": "x", "start": None, "end": None}]
        self.assertEqual(G.cue_gaps(rows), [0.5, 28, None])

    def test_classify_minority_majority_clean(self):
        # gaps: big after cue 2 (inside batch 0) and none in batch 1
        g = [0.1, 0.1, 12.0, 0.1, 0.1, 0.1, 0.1, 0.1]
        labels = G.classify([(0, 6), (6, 9)], g, 10.0)
        # 3 vs 3: tied sides are both minority
        self.assertEqual([labels[i] for i in range(9)], ["minority"] * 6 + ["clean"] * 3)
        labels = G.classify([(0, 7)], g + [0.1], 10.0)
        self.assertEqual([labels[i] for i in range(7)], ["minority"] * 3 + ["majority"] * 4)

    def test_gap_adjacent_boundary_vs_inside(self):
        g = [0.1, 15.0, 0.1, 0.1, 20.0, 0.1]
        spans = [(0, 2), (2, 5), (5, 7)]  # gap after cue 1 is on a boundary; after cue 4 also boundary
        self.assertEqual(G.gap_adjacent(spans, g, 10.0), {1: "boundary", 2: "boundary", 4: "boundary", 5: "boundary"})
        spans = [(0, 3), (3, 7)]
        self.assertEqual(G.gap_adjacent(spans, g, 10.0), {1: "in_batch", 2: "in_batch", 4: "in_batch", 5: "in_batch"})
        # a cue touching an inside gap and a boundary gap is left out
        g2 = [15.0, 15.0]
        self.assertEqual(G.gap_adjacent([(0, 1), (1, 3)], g2, 10.0), {0: "boundary", 2: "in_batch"})

    def test_clean_position(self):
        g = [0.1] * 5 + [30.0] + [0.1] * 3
        labels = G.clean_position([(0, 5), (5, 10)], g, 10.0)
        self.assertEqual(labels, {0: "edge", 1: "interior", 2: "interior", 3: "interior", 4: "edge"})


class StatsTest(unittest.TestCase):
    def test_cue_metrics_categories(self):
        row = S.cue_metrics([("wrong-referent", "major"), ("mistranslation", "minor"), ("omission", "critical"),
                             ("unnatural", "major")])
        self.assertEqual(row["accuracy"], 16.0)
        self.assertEqual((row["wrong-referent"], row["mistranslation"], row["other"]), (5.0, 1.0, 10.0))
        self.assertEqual(S.cue_metrics([], undelivered=True)["other"], 10.0)

    def test_contrast_within_work_then_equal_weight(self):
        values, labels, scene_of = {}, {}, {}
        # work A (series): minority 2.0 vs clean 0.0; work B (series): 1.0 vs 0.0; work M (movie): 0 vs 1
        for work, scene, a, b in (("A", "sA", 2.0, 0.0), ("B", "sB", 1.0, 0.0), ("M", "sM", 0.0, 1.0)):
            for k, (label, v) in enumerate((("minority", a), ("clean", b), ("clean", b))):
                cue = f"{scene}-{k}"
                values[cue] = dict.fromkeys(S.METRICS, 0.0) | {"accuracy": v}
                labels[cue], scene_of[cue] = label, scene
        table = S.SceneTable(labels, values, scene_of, {"sA": "A", "sB": "B", "sM": "M"},
                             {"A": "anime_series", "B": "anime_series", "M": "animation_movie"})
        result = S.contrast(table, "minority", "clean", S.mean_diff("accuracy"), reps=50)
        self.assertAlmostEqual(result["anime_series"]["point"], 1.5)
        self.assertAlmostEqual(result["animation_movie"]["point"], -1.0)
        self.assertAlmostEqual(result["overall"]["point"], 0.25)


# Hashes recorded in existing v3/v4 run.json files (b10-joint is also fixed by AdoptedBaselineTest).
RECORDED_HASHES = {
    "b10-joint": ("b10-joint", {}, "2ba680540f055b2ae0c8122faa3ba537418eb12720a552f53c3aa5b652d0969a"),
    "c0": ("c0", {}, "f2a7501767abc205ceac336d5887061a77a3b00774cf9eb003445f8057d056a5"),
    "t03": ("b10-joint", {"sampling": {"temperature": 0.3}},
            "5281f1b28c4983ff78c1f0d9b7e7e17bfb9a5eaa74ef0638c6e85722f54486dd"),
    "mbr8c": ("b10-joint", {"candidates": 8, "selector": "mbr-chrf-cue"},
              "701c04a42c8701c94d0f7aee75603f713f7f9f2aa69f4a60cd3392d96ff8158d"),
    "tctx10": ("b10-joint", {"target_context": 10},
               "bc5487c19052dcd7cb0276eacf06235a588fbe1dffed1f9c2b365e1d9c85d978"),
}
SPLIT = {"snap": 2, "max": 12, "cut_gap": 5.0, "context_gap": 5.0, "max_visible": 12}


def scene(gaps: list[float], dur: float = 1.0) -> Scene:
    t, out = 0.0, []
    for i in range(len(gaps) + 1):
        out.append(Cue(f"c{i:03d}", f"t{i}", t, t + dur))
        t += dur + (gaps[i] if i < len(gaps) else 0)
    return Scene("s", tuple(out))


class GapSplitRecipeTest(unittest.TestCase):
    def test_existing_hashes_unchanged(self):
        for name, (base, overrides, digest) in RECORDED_HASHES.items():
            recipe = R.compose(name, base, **overrides) if overrides else R.BUILTIN[base]
            self.assertEqual(recipe.recipe_hash, digest, name)
            self.assertNotIn("gap_split", recipe.spec()["recipe"])

    def test_gap_split_enters_hash(self):
        recipe = R.compose("gs", "b10-joint", gap_split=dict(SPLIT))
        self.assertNotEqual(recipe.recipe_hash, R.BUILTIN["b10-joint"].recipe_hash)
        self.assertEqual(recipe.spec()["versions"]["gap_split"], R.GAP_SPLIT_VERSION)
        self.assertEqual(recipe.spec()["recipe"]["gap_split"], SPLIT)

    def test_validation(self):
        for bad in ({**SPLIT, "snap": 10}, {**SPLIT, "max": 9}, {**SPLIT, "max_visible": 11},
                    {**SPLIT, "cut_gap": None}, {**SPLIT, "cut_gap": -1}, {k: v for k, v in SPLIT.items() if k != "max"}):
            with self.assertRaises(ValueError):
                R.compose("gs", "b10-joint", gap_split=bad)
        with self.assertRaises(ValueError):
            R.compose("gs", "tok400", gap_split=dict(SPLIT))


class GapSplitBatchingTest(unittest.TestCase):
    def test_no_qualifying_gap_equals_plain_b10(self):
        sc = scene([0.5] * 34)
        plain = build_batches(sc, R.BUILTIN["b10-joint"])
        split = build_batches(sc, R.compose("gs", "b10-joint", gap_split=dict(SPLIT)))
        self.assertEqual([b.record() for b in plain], [b.record() for b in split])

    def test_snap_to_largest_gap_and_drop_neighbours(self):
        gaps = [0.5] * 24
        gaps[8] = 6.0   # silence before cue 9: grid point 10 snaps to 9
        gaps[20] = 7.0  # silence before cue 21: grid point 20 snaps to 21
        gaps[19] = 6.5  # smaller than gaps[20], so 21 wins
        sc = scene(gaps)
        batches = build_batches(sc, R.compose("gs", "b10-joint", gap_split=dict(SPLIT)))
        self.assertEqual([(b.start, b.stop) for b in batches], [(0, 9), (9, 21), (21, 25)])
        self.assertEqual(batches[0].after_ids, ())  # across the 6 s gap
        self.assertEqual(batches[1].before_ids, ())
        self.assertEqual(batches[1].after_ids, ())  # 12 targets, and the gap
        self.assertEqual(batches[2].before_ids, ())

    def test_neighbour_kept_below_context_gap_and_visible_cap(self):
        gaps = [0.5] * 24
        gaps[11] = 5.5  # before cue 12: grid point 10 moves to 12 -> 12 targets, no neighbours fit
        sc = scene(gaps)
        batches = build_batches(sc, R.compose("gs", "b10-joint", gap_split=dict(SPLIT)))
        self.assertEqual([(b.start, b.stop) for b in batches], [(0, 12), (12, 20), (20, 25)])
        self.assertEqual((batches[0].before_ids, batches[0].after_ids), ((), ()))
        self.assertEqual(batches[1].after_ids, ("c020",))
        self.assertEqual(batches[2].before_ids, ("c019",))

    def test_invariants_on_random_scenes(self):
        rng = random.Random(6)
        recipe = R.compose("gs", "b10-joint", gap_split=dict(SPLIT))
        for _ in range(300):
            n = rng.randint(1, 60)
            sc = scene([rng.choice([0.3, 0.8, 2.0, 5.0, 8.0, 30.0]) for _ in range(n - 1)])
            plain = build_batches(sc, R.BUILTIN["b10-joint"])
            batches = build_batches(sc, recipe)
            self.assertEqual(len(batches), len(plain))
            self.assertEqual([k for b in batches for k in b.target_ids], sc.ids)
            for b in batches:
                self.assertLessEqual(len(b.target_ids), SPLIT["max"])
                self.assertLessEqual(len(b.before_ids) + len(b.target_ids) + len(b.after_ids), 12)
            self.assertEqual(gap_cuts(sc, 10, SPLIT)[:1], [0])


class SubsetTest(unittest.TestCase):
    def test_affected_cues_from_batch_records(self):
        gaps = [0.5] * 24
        gaps[8] = 6.0
        sc = scene(gaps)

        def mapping(recipe):
            return {"s": {k: (b.target_ids, b.before_ids, b.after_ids)
                          for b in build_batches(sc, recipe) for k in b.target_ids}}
        cand = mapping(R.compose("gs", "b10-joint", gap_split=dict(SPLIT)))
        ctrl = mapping(R.BUILTIN["b10-joint"])
        # batches 0-9 and 9-20 changed; the last batch 20-25 keeps targets and neighbour c019
        self.assertEqual(q2.affected_cues(cand, ctrl), [f"c{i:03d}" for i in range(20)])
        with self.assertRaises(ValueError):
            q2.affected_cues(cand, {})


if __name__ == "__main__":
    unittest.main()
