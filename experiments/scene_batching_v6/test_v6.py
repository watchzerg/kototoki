"""Offline tests for the v6 scene-batching analysis (no GPU, model, network or .local data)."""

from __future__ import annotations

import unittest

from experiments.scene_batching_v6 import gaps as G
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


if __name__ == "__main__":
    unittest.main()
