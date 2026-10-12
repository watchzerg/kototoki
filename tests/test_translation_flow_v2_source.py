from __future__ import annotations

import unittest

from experiments.translation_corpus.flow_v2_source import (
    audit_isolation, event_keys, partitions, risk_tags, score_frame, select_scene, shuffled,
)


def cues(count: int = 120) -> list[dict]:
    return [{"id": f"j{i}", "ja_srt_index": i + 1, "zh_srt_index": i + 1,
             "start_ms": i * 1000, "end_ms": i * 1000 + 900,
             "ja": "それは来ないなら秘密です", "flags": [],
             "source_events": {lang: [{"Dialogue序号": i + 1}] for lang in ("ja", "zh")}}
            for i in range(count)]


def source() -> dict:
    return {"work_id": "M01", "work": "Synthetic", "category": "animation_movie",
            "episode_id": "M01", "source_sha256": "hash", "band": 0}


class FlowSourceTests(unittest.TestCase):
    def test_partition_deterministic_contiguous_and_bounded(self):
        ranges = partitions(cues(1230), "synthetic")
        self.assertEqual(ranges, partitions(cues(1230), "synthetic"))
        self.assertTrue(all(80 <= stop - start <= 160 for start, stop in ranges))
        self.assertTrue(all(a[1] == b[0] for a, b in zip(ranges, ranges[1:])))
        self.assertLess(1230 - ranges[-1][1], 80)

    def test_history_excludes_score_but_allows_context(self):
        items = cues()
        forbidden = event_keys("hash", items[:20])
        scene, windows, reserve, order, rejected = select_scene(source(), items, (0, 120), "scene", "screening", 3, 1, forbidden)
        self.assertEqual(len(windows), 3)
        self.assertTrue(windows[0]["historically_visible_context_events"] > 0)
        for row in windows:
            scored = [u for u in row["units"] if u["score"]]
            self.assertFalse(event_keys("hash", scored) & forbidden)
        self.assertEqual(len(scene["context"]), 120)
        self.assertTrue(reserve)
        self.assertTrue(rejected)

    def test_pairing_rejects_unpaired_scoring_only(self):
        items = cues()
        items[40]["zh_srt_index"] = None
        frame, rejected = score_frame(items, "hash", set(), "synthetic")
        self.assertTrue(frame)
        self.assertTrue(any(r["reason"] == "nonunique_time_pairing" for r in rejected))

    def test_full_context_overlap_fails_with_distinct_targets(self):
        base = {**source(), "units": [], "historically_visible_context_events": 0}
        a = {**base, "scene_id": "a", "split": "screen-a", "visible_start_index": 1,
             "visible_end_index": 120, "source_event_keys": ["e1"], "scored_ids": ["j1"]}
        b = {**base, "scene_id": "b", "split": "confirmation", "visible_start_index": 100,
             "visible_end_index": 220, "source_event_keys": ["e2"], "scored_ids": ["j200"]}
        with self.assertRaisesRegex(ValueError, "visible interval"):
            audit_isolation([a, b])
        b["visible_start_index"] = 121
        self.assertTrue(audit_isolation([a, b])["valid"])

    def test_whole_episode_isolation_and_window_cap(self):
        base = {**source(), "category": "anime_series", "historically_visible_context_events": 0,
                "visible_start_index": 1, "visible_end_index": 120, "source_event_keys": []}
        rows = [{**base, "scene_id": "a", "split": "screen-a", "scored_ids": ["j1"]},
                {**base, "scene_id": "b", "split": "confirmation", "scored_ids": ["j2"]}]
        with self.assertRaisesRegex(ValueError, "episode"):
            audit_isolation(rows)
        rows = [{**base, "scene_id": "a", "split": "screen-a", "scored_ids": [f"j{i}"]} for i in range(4)]
        with self.assertRaisesRegex(ValueError, "three"):
            audit_isolation(rows)

    def test_source_risk_tags_are_japanese_proxies(self):
        self.assertIn("negation_condition", risk_tags(cues(5)))
        self.assertIn("ellipsis_reference", risk_tags(cues(5)))

    def test_representative_probability_draw_precedes_risk_selection(self):
        items = cues()
        _, rows, _, order, _ = select_scene(source(), items, (0, 120), "scene", "screening", 3, 1, set())
        indexed = [{**x, "id": f"F2-M01-J{x['ja_srt_index']:05d}"} for x in items]
        frame, _ = score_frame(indexed, "hash", set(), "scene")
        expected = shuffled(frame, "representative|scene")[:2]
        representatives = [r["scored_ids"] for r in rows if r["selection_type"] == "representative"]
        self.assertEqual(representatives, [x["ids"] for x in expected])
        self.assertEqual(order["representative_conditional_probability"], 2 / len(frame))


if __name__ == "__main__":
    unittest.main()
