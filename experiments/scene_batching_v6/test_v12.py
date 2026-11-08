"""v12 (offline): F1/F2 recipe files from Q1, run statistics, A/A diff and the feasibility gate."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.recipes import load_recipe

from . import v12

Q1 = {"name": "qwen-names-dev-high", "base": "qwen-wide", "comment": "c",
      "qwen_options": {"names": {"filter": "window", "tables": {"W": [{"source": "行く", "translation": "去"}]}}}}


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def attempt(status="accepted", kind=None, **extra) -> dict:
    return {"status": status, "error_kind": kind, "elapsed_seconds": 2.0, "completion_seconds": 1.0,
            "output_tokens": 100, "reasoning_chars": 0, **extra}


def fake_run(root: Path, requests: list[dict], translations: dict, resources: dict | None = None) -> Path:
    write(root / "run.json", {"wall_clock_seconds": 10.0, "sessions": [{}]})
    write(root / "scenes/S1.json", {"scene_id": "S1", "requests": requests, "translations": translations,
                                    "batches": [{"index": 0, "target_ids": ["a", "b"]}, {"index": 1, "target_ids": ["c"]}]})
    if resources is not None:
        write(root / "runtime/session-01/resources.json", resources)
    return root


class RecipeTest(unittest.TestCase):
    def test_f1_f2_are_q1_with_strata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "recipes/q1.json", dict(Q1, name="q1"))
            write(root / "recipes/f1.json", v12.strata_recipe_data(Q1, "f1", "x"))
            write(root / "recipes/f2.json", v12.strata_recipe_data(Q1, "f2", "x", v12.THINKING))
            q1, f1, f2 = (load_recipe(n, root) for n in ("q1", "f1", "f2"))
        self.assertEqual((q1.model, f1.model), (R.QWEN_MODEL, R.STRATA_MODEL))
        self.assertEqual(f1.qwen_options, q1.qwen_options)
        self.assertEqual({k: v for k, v in vars(f1).items() if k not in ("name", "model")},
                         {k: v for k, v in vars(q1).items() if k not in ("name", "model")})
        self.assertEqual(f2.qwen_options["thinking"], {"budget": 1024, "min_visible": 1})
        with self.assertRaises(ValueError):
            v12.strata_recipe_data(dict(Q1, model="x"), "f1", "x")


class StatsTest(unittest.TestCase):
    def test_run_stats_and_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = fake_run(Path(tmp) / "a", [
                {"stage": "translation", "status": "accepted", "attempts": [attempt()]},
                {"stage": "translation", "status": "accepted",
                 "attempts": [attempt("failed", "parse"), attempt(cache_reset_check={"first_cache_n": 0})]},
            ], {"a": "1", "b": "2", "c": "3"},
                {"gpu_used_mib": 15000, "ram_used_gib": 51.0, "log_events": {"nonfinite_logits": 0}})
            stats = v12.run_stats(run)
            self.assertEqual((stats["packs"], stats["first_attempt_failures"], stats["delivery_failures"]), (2, 1, 0))
            self.assertEqual(stats["first_attempt_failure_kinds"], {"parse": 1})
            self.assertEqual((stats["peak_gpu_used_mib"], stats["log_events"]), (15000, {"nonfinite_logits": 0}))
            self.assertEqual(stats["pack_seconds"]["max"], 4.0)
            gate = v12.feasibility([stats])
            self.assertFalse(gate["passed"])  # 1 of 2 first attempts failed > 5 %
            self.assertTrue(gate["checks"]["delivery_failures_zero"])
            clean = dict(stats, first_attempt_failures=0)
            self.assertTrue(v12.feasibility([clean, clean])["passed"])
            self.assertIsNone(v12.feasibility([dict(clean, log_events=None)])["checks"]["no_nonfinite_logits"])
            self.assertFalse(v12.feasibility([dict(clean, attempts_with_reasoning=1)])["passed"])

    def test_aa_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = fake_run(Path(tmp) / "a", [], {"a": "1", "b": "2", "c": "3"})
            b = fake_run(Path(tmp) / "b", [], {"a": "1", "b": "X", "c": "3"})
            diff = v12.aa_diff(a, b)
        self.assertEqual((diff["packs"], diff["packs_different"], diff["cues"], diff["cues_different"]), (2, 1, 3, 1))


if __name__ == "__main__":
    unittest.main()
