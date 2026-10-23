"""v11 offline checks: silence-gap truncation of the wide neighbours, the name-table "targets" revision, the
diff-before-judging accounting on the product and dev sides; old hashes unchanged."""

from __future__ import annotations

import random
import unittest

from experiments.translation_v3 import judge as J
from experiments.translation_v3 import qwen
from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches
from experiments.translation_v3.data import Cue, Scene

from . import asr10, v11

WINDOW = {"id": "w", "source_language": "ja", "target_language": "zh-Hans",
          "context": [{"id": "a", "text": "ハルカが来た"}, {"id": "b", "text": "ミナトと行こう"}, {"id": "c", "text": "うん"}],
          "translate_ids": ["b", "c"]}
TABLE = {"W1": [{"source": "ハルカ", "translation": "遥"}, {"source": "ミナト", "translation": "凑"},
                {"source": "サクラ", "translation": "樱"}]}


def timed_scene(gaps: list[float], scene_id: str = "S") -> Scene:
    """Cues of 1 s each; ``gaps[i]`` is the silence between cue i and cue i+1."""
    cues, t = [], 0.0
    for i, gap in enumerate(gaps + [0.0]):
        cues.append(Cue(f"{scene_id}-{i:03d}", f"台詞{i}", t, t + 1.0))
        t += 1.0 + gap
    return Scene(scene_id, tuple(cues))


class WideContextV2Test(unittest.TestCase):
    def test_old_hashes_unchanged(self):
        self.assertEqual(R.BUILTIN["qwen-wide"].recipe_hash,
                         "719237b92c45c4d0f19971ece6b0944157c23ad2e33bbfe0644db60aabfcaef7")
        self.assertTrue(R.BUILTIN["dp10-cut"].recipe_hash.startswith("ee72ce66"))
        self.assertEqual(R.BUILTIN["qwen-wide"].spec()["versions"]["wide_context"], R.WIDE_CONTEXT_VERSION)

    def test_silence_gap_validates_and_versions(self):
        seg = R.compose("seg10", "qwen-wide", wide_context={"max_visible": 35, "silence_gap": 10.0})
        self.assertNotEqual(seg.recipe_hash, R.BUILTIN["qwen-wide"].recipe_hash)
        self.assertEqual(seg.spec()["versions"]["wide_context"], R.WIDE_CONTEXT_V2_VERSION)
        self.assertEqual(seg.spec()["recipe"]["wide_context"], {"max_visible": 35, "silence_gap": 10.0})
        for bad in ({"max_visible": 35, "silence_gap": 0}, {"max_visible": 35, "silence_gap": "10"},
                    {"max_visible": 35, "gap": 10.0}, {"silence_gap": 10.0}):
            with self.assertRaises(ValueError, msg=bad):
                R.compose("bad", "qwen-wide", wide_context=bad)

    def test_truncation_rule(self):
        # 40 cues, one pack per 10 cues (gaps >= 20 s at the cut points force the dp10-cut cuts there is no need:
        # use plain gaps below the pack's hard limit and check the neighbour rule on the resulting packs).
        gaps = [0.5] * 39
        gaps[9] = 12.0   # between cue 9 and 10: cuts the before-side of pack 2 and the after-side of pack 1
        gaps[14] = 11.0  # inside a pack: ignored for the pack itself, truncates neighbours of other packs
        gaps[29] = 3.0   # below the gap: not a cut
        scene = timed_scene(gaps)
        seg = R.compose("seg10", "qwen-wide", wide_context={"max_visible": 35, "silence_gap": 10.0})
        base, cut = build_batches(scene, R.BUILTIN["qwen-wide"]), build_batches(scene, seg)
        self.assertEqual([b.target_ids for b in base], [b.target_ids for b in cut])  # cuts unchanged
        for b, c in zip(base, cut):
            # the truncated neighbours are a suffix / prefix of the untruncated ones
            self.assertEqual(c.before_ids, b.before_ids[len(b.before_ids) - len(c.before_ids):])
            self.assertEqual(c.after_ids, b.after_ids[:len(c.after_ids)])
            self.assertLessEqual(len(c.before_ids) + len(c.target_ids) + len(c.after_ids), 35)
            left = c.start - len(c.before_ids)
            if left > 0 and c.start > 0 and left < c.start:
                # a visible before-side stops only at a gap >= 10 s (or the count / scene edge)
                self.assertGreaterEqual(gaps[left - 1], 10.0)
            for i in range(left, c.start - 1):  # no gap >= 10 s inside the visible before-side
                self.assertLess(gaps[i], 10.0)
            right = c.stop + len(c.after_ids)
            for i in range(c.stop, right - 1):
                self.assertLess(gaps[i], 10.0)
        # at least one pack lost neighbours on each side, and a pack far from any gap keeps them
        self.assertTrue(any(len(c.before_ids) < len(b.before_ids) for b, c in zip(base, cut)))
        self.assertTrue(any(len(c.after_ids) < len(b.after_ids) for b, c in zip(base, cut)))
        quiet = build_batches(timed_scene([0.5] * 39), seg)
        self.assertEqual([(b.before_ids, b.after_ids) for b in quiet],
                         [(b.before_ids, b.after_ids) for b in build_batches(timed_scene([0.5] * 39), R.BUILTIN["qwen-wide"])])

    def test_random_scenes_invariants(self):
        rng = random.Random(11)
        seg = R.compose("seg5", "qwen-wide", wide_context={"max_visible": 35, "silence_gap": 5.0})
        for _ in range(40):
            n = rng.randint(1, 60)
            gaps = [rng.choice([0.2, 0.8, 3.0, 6.0, 15.0]) for _ in range(n - 1)]
            scene = timed_scene(gaps)
            for b, c in zip(build_batches(scene, R.BUILTIN["qwen-wide"]), build_batches(scene, seg)):
                self.assertEqual(b.target_ids, c.target_ids)
                left = c.start - len(c.before_ids)
                self.assertTrue(all(gaps[i] < 5.0 for i in range(left, c.start - 1)))
                self.assertTrue(all(gaps[i] < 5.0 for i in range(c.stop, c.stop + len(c.after_ids) - 1)))
                self.assertTrue(len(c.before_ids) <= len(b.before_ids) and len(c.after_ids) <= len(b.after_ids))


class NamesTargetsTest(unittest.TestCase):
    def arm(self, filter_):
        return R.compose("arm", "qwen-wide", qwen_options={"names": {"filter": filter_, "tables": TABLE}})

    def test_targets_filter_and_header(self):
        window, targets = self.arm("window"), self.arm("targets")
        self.assertEqual([r["source"] for r in qwen.names_for_window(window, "W1", WINDOW)], ["ハルカ", "ミナト"])
        self.assertEqual([r["source"] for r in qwen.names_for_window(targets, "W1", WINDOW)], ["ミナト"])
        system = qwen.messages(WINDOW, targets, "W1")[0]["content"]
        self.assertIn(qwen.NAMES_HEADER_V2 + "ミナト → 凑", system)
        self.assertNotIn("ハルカ", system)
        self.assertIn(qwen.NAMES_HEADER + "ハルカ → 遥\nミナト → 凑", qwen.messages(WINDOW, window, "W1")[0]["content"])
        self.assertEqual(qwen.messages(WINDOW, window, "W1")[1], qwen.messages(WINDOW, targets, "W1")[1])
        self.assertEqual(window.spec()["versions"]["model"]["options"]["names"][0], qwen.NAMES_VERSION)
        self.assertEqual(targets.spec()["versions"]["model"]["options"]["names"][0], qwen.NAMES_VERSION_V2)
        self.assertNotEqual(window.recipe_hash, targets.recipe_hash)
        with self.assertRaises(ValueError):
            self.arm("cues")


class ProductDiffTest(unittest.TestCase):
    units = {"f": [{"bucket": b} for b in ["exact"] * 3 + ["light"] * 2 + ["heavy"] * 2]}

    def texts(self, same: set[int]):
        tx = {"f": [[f"x{i}s{k}" for k in range(2)] for i in range(7)]}
        ty = {"f": [[(f"x{i}s{k}" if i in same else f"y{i}s{k}") for k in range(2)] for i in range(7)]}
        return tx, ty

    def test_plan_items_skip_identical_keeps_sides(self):
        tx, ty = self.texts({0, 4})
        quotas = {"exact": "all", "light": "all", "heavy": "all"}
        full, none = asr10.plan_items(self.units, tx, ty, quotas, (1, 2), "y-vs-x")
        items, identical = asr10.plan_items(self.units, tx, ty, quotas, (1, 2), "y-vs-x", skip_identical=True)
        self.assertEqual(none, [])
        self.assertEqual(len(full), 7)
        self.assertEqual(len(items) + len(identical), 7)
        self.assertEqual(sorted(u["unit"] for u in identical), [0, 4])
        self.assertEqual([i["id"] for i in sorted(items, key=lambda i: i["id"])], [f"q{n:04d}" for n in range(1, 6)])
        # the A/B side of a judged unit is the same draw as in the full plan
        side = {(i["film"], i["unit"]): i["x_side"] for i in full}
        self.assertTrue(all(side[(i["film"], i["unit"])] == i["x_side"] for i in items))
        self.assertTrue(all(i["x"] != i["y"] for i in items))

    def test_summarize_counts_identical_as_zero(self):
        rows = [{"bucket": "exact", "film": "f", "px": 2, "py": 0, "winner": "y", "x_errors": [
            {"category": "terminology", "severity": "minor", "note": ""}], "y_errors": []}] * 4
        identical = [{"bucket": "exact", "film": "f", "unit": 1, "seed_index": 0}] * 4
        report = asr10.summarize("y-vs-x", rows, identical)
        exact = report["buckets"]["exact"]
        self.assertEqual((report["judged"], report["identical_delta_zero"]), (4, 4))
        self.assertEqual((exact["n"], exact["n_judged"], exact["n_identical"]), (8, 4, 4))
        self.assertEqual(exact["delta"], -1.0)          # (4 x -2 + 4 x 0) / 8
        self.assertEqual(exact["delta_judged"], -2.0)
        self.assertEqual(exact["mean_px"], 2.0)          # means over judged rows only
        self.assertEqual(exact["name_errors"], [4, 0])
        self.assertEqual(exact["pref_candidate"], 1.0)
        self.assertEqual(exact["tie"], 0.5)
        self.assertEqual(asr10.summarize("y-vs-x", rows)["buckets"]["exact"]["n"], 4)
        self.assertNotIn("light", report["buckets"])


class DevDiffTest(unittest.TestCase):
    def test_packet_id_matches_judge_planner(self):
        packets = J.plan_packets("run-x", {"dev-A": [f"w{i}" for i in range(9)]}, {f"w{i}" for i in range(9)})
        for p in packets:
            self.assertEqual(p["packet_id"], v11.packet_id("run-x", p["window_ids"]))

    def test_identical_packet_results(self):
        packets = [{"packet_id": "p1", "split": "dev-A", "window_ids": ["w1", "w2"]},
                   {"packet_id": "p2", "split": "dev-A", "window_ids": ["w3"]},
                   {"packet_id": "p3", "split": "dev-A", "window_ids": ["w4"]}]
        results = {"p1": {"packet_id": "p1", "profile_hash": "h", "surface": "cli", "meta": {"total_cost_usd": 0.2},
                          "judgement": {"w1": {}, "w2": {}}},
                   "p2": {"packet_id": "p2", "profile_hash": "h", "surface": "cli", "meta": {}, "judgement": {"w3": {}}}}
        cues = {"w1": ["c1", "c2"], "w2": ["c3"], "w3": ["c4"], "w4": ["c5"]}
        out = v11.identical_packet_results(packets, results, {"c1", "c2", "c3", "c5"}, cues, "cand")
        new_id = v11.packet_id("cand", ["w1", "w2"])
        self.assertEqual(list(out), [new_id])                   # p2 differs (c4), p3 has no control result
        self.assertEqual(out[new_id]["packet_id"], new_id)
        self.assertEqual(out[new_id]["surface"], "copied-identical")
        self.assertEqual(out[new_id]["meta"], {"copied_from_packet": "p1", "identical_cues": 3, "total_cost_usd": 0.0})
        self.assertEqual(out[new_id]["judgement"], results["p1"]["judgement"])
        self.assertEqual(results["p1"]["packet_id"], "p1")      # the control's record is not modified

    def test_apply_identical(self):
        cand = {"a": {"accuracy": 5.0}, "b": {"accuracy": 1.0}}
        ctrl = {"a": {"accuracy": 0.0}, "b": {"accuracy": 1.0}, "c": {"accuracy": 2.0}}
        self.assertEqual(v11.apply_identical(cand, ctrl, {"a", "c", "z"}), 1)
        self.assertEqual(cand, {"a": {"accuracy": 0.0}, "b": {"accuracy": 1.0}})
        self.assertEqual(ctrl["a"], {"accuracy": 0.0})


if __name__ == "__main__":
    unittest.main()
