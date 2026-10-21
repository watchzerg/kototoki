"""v9 offline: cue metrics, the L1/L2 decisions, cost from run files, arm batch identity on the dev set."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from experiments.translation_v3.common import atomic_write_json
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT

from . import v9


def report(series: list[float], movie: list[float], **other: dict[str, list[float]]) -> dict:
    """A compare() report skeleton with accuracy CI90 per category (point = midpoint)."""
    def block(s, m):
        return {"delta": {"anime_series": sum(s) / 2, "animation_movie": sum(m) / 2, "overall": None},
                "bootstrap": {"anime_series": {"ci90": s}, "animation_movie": {"ci90": m}, "overall": None}}
    full = {"accuracy": block(series, movie)}
    for name, (s0, s1, m0, m1) in other.items():
        full[name] = block([s0, s1], [m0, m1])
    return {"full": full}


class CueRowTest(unittest.TestCase):
    def test_categories_and_undelivered(self):
        row = v9.cue_row([("omission", "major"), ("grammar", "minor"), ("terminology-inconsistency", "minor"),
                          ("wrong-referent", "critical")])
        self.assertEqual((row["accuracy"], row["omission"], row["wrong-referent"]), (15.0, 5.0, 10.0))
        self.assertEqual((row["fluency"], row["grammar"], row["major_plus"], row["critical"]), (2.0, 1.0, 1.0, 1.0))
        self.assertEqual(v9.cue_row([]), dict.fromkeys(v9.METRICS, 0.0))
        undelivered = v9.cue_row(None)
        self.assertEqual((undelivered["accuracy"], undelivered["major_plus"], undelivered["critical"]), (10.0, 1.0, 1.0))


class DecisionTest(unittest.TestCase):
    def test_l1_gate(self):
        close = lambda s, m: v9.decision(report(s, m))["l1_close"]
        self.assertTrue(close([0.01, 0.2], [0.02, 0.3]))        # both significantly worse
        self.assertTrue(close([0.06, 0.3], [-0.1, 0.1]))        # one beyond the margin, the other not better
        self.assertFalse(close([0.06, 0.3], [-0.2, -0.01]))     # ... unless the other is significantly better
        self.assertFalse(close([0.01, 0.2], [-0.1, 0.1]))       # one worse inside the margin: stays open
        self.assertFalse(close([-0.05, 0.04], [-0.1, 0.03]))

    def test_l2_flags_and_dimensions(self):
        d = v9.decision(report([-0.08, 0.04], [-0.2, -0.01], fluency=(-0.3, -0.1, -0.1, 0.1),
                               omission=(0.01, 0.2, -0.1, 0.1)))
        self.assertTrue(d["l2_noninferior_both"])
        self.assertEqual(d["l2_improved"], ["animation_movie"])
        self.assertEqual(d["dimensions_better"], ["fluency:anime_series"])
        self.assertEqual(d["dimensions_worse"], ["omission:anime_series"])
        self.assertFalse(v9.decision(report([-0.08, 0.06], [-0.2, -0.01]))["l2_noninferior_both"])


class NameRuleTest(unittest.TestCase):
    def test_name_error_evidence(self):
        self.assertTrue(v9.NAME_ERROR.search("人名“フリーレン”误译为“菲伦”"))
        self.assertTrue(v9.NAME_ERROR.search("称呼不当"))
        self.assertFalse(v9.NAME_ERROR.search("否定极性译反"))


class CostTest(unittest.TestCase):
    def test_cost_from_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "qwen-narrow__s1__dev"
            atomic_write_json(run / "run.json", {"wall_clock_seconds": 100.0, "resumed": False,
                                                 "sessions": [{"engine": {"cold_load_seconds": 12.5}}]})
            attempts = [{"input_tokens": 300, "output_tokens": 50, "reasoning_chars": 0,
                         "timings": {"predicted_n": 50, "predicted_ms": 1000.0, "prompt_n": 300, "prompt_ms": 150.0}},
                        {"input_tokens": 300, "output_tokens": 50, "prompt_token_mismatch": [300, 301],
                         "timings": {"predicted_n": 50, "predicted_ms": 1000.0, "prompt_n": 10, "prompt_ms": 10.0}}]
            atomic_write_json(run / "scenes" / "S.json", {"scene_id": "S", "status": "failed", "elapsed_seconds": 9.0,
                                                          "failure": {"kind": "parse"},
                                                          "requests": [{"status": "failed", "attempts": attempts}]})
            atomic_write_json(run / "runtime" / "session-01" / "engine-final.json", {"peak_device_memory_mib": 14000})
            c = v9.cost(run)
        self.assertEqual((c["requests"], c["attempts"], c["retried_requests"], c["failed_requests"]), (1, 2, 1, 1))
        self.assertEqual((c["failed_scenes"], c["failure_kinds"]), (["S"], {"parse": 1}))
        self.assertEqual((c["output_tokens"], c["generation_tok_per_s"], c["prompt_token_mismatches"]), (100, 50.0, 1))
        self.assertEqual((c["load_seconds"], c["peak_device_memory_mib"]), ([12.5], [14000]))


@unittest.skipUnless((V4_ROOT / "sets/dev/scenes.jsonl").is_file(), "v4 dev set not present")
class DevBatchIdentityTest(unittest.TestCase):
    def test_three_arms_identical_targets_on_dev(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = v9.check_batches(root=Path(tmp))
        self.assertTrue(result["offline_identical"])
        self.assertEqual(result["scenes"], 44)
        self.assertLessEqual(max(int(k) for k in result["visible_histogram"]["qwen-narrow"]), 12)

    def test_smoke_packs(self):
        packs = v9.smoke_batches()
        self.assertEqual([s.category for s, _ in packs], ["anime_series"] * 3 + ["animation_movie"] * 2)
        self.assertEqual(len({s.work_id for s, _ in packs}), 5)


if __name__ == "__main__":
    unittest.main()
