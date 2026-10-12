"""Offline terminal gating and unchanged eight-axis diagnostics for W0 VAD."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.components import evaluate_w0_vad as evaluator


class W0VadExtensionTests(unittest.TestCase):
    def report(self):
        def route(name, cer, deleted, inserted, complete, measurable, success):
            return {"route_id": name, "summary": {"text": {"CER": cer, "deletion_rate": deleted,
                "I": inserted, "reference_characters": 100}, "timing": {"denominator": 10,
                "boundary_complete_count": complete, "measurable_coverage": measurable,
                "success": {key: {"lower": success, "upper": success + .1} for key in ("0.5", "2.0", "5.0")}}}}
        baseline = route("w0-baseline", .2, .1, 5, 8, .5, .4)
        vad = route("w0-vad", .15, .08, 3, 9, .6, .5)
        scope = {"routes": [baseline, vad], "comparisons": [{"left": "w0-baseline", "right": "w0-vad",
            "common_valid_count": 4, "paired_scene_bootstrap": {"status": "not_run", "scene_count": 2}}]}
        return {"pooled": scope, "films": {"II": copy.deepcopy(scope), "III": copy.deepcopy(scope)}}

    def test_eight_axes_and_all_success_bounds_are_preserved(self):
        report = self.report()
        before = copy.deepcopy(report)
        diagnostics = evaluator.decision_diagnostics(report)
        self.assertEqual(len(diagnostics["axes"]), 8)
        for scope in diagnostics["scopes"].values():
            self.assertTrue(scope["vad_dominates_baseline"])
            self.assertFalse(scope["baseline_dominates_vad"])
            self.assertEqual(set(scope["success_bounds"]), {"0.5", "2.0", "5.0"})
            self.assertEqual(scope["success_bounds"]["0.5"]["baseline"], {"lower": .4, "upper": .5})
            self.assertEqual(scope["paired_scene_bootstrap"]["status"], "not_run")
        self.assertEqual(before, report)

    def test_worse_insertions_prevent_pareto_dominance_despite_timing_gains(self):
        report = self.report()
        report["pooled"]["routes"][1]["summary"]["text"]["I"] = 8
        result = evaluator.decision_diagnostics(report)["scopes"]["pooled"]
        self.assertFalse(result["vad_dominates_baseline"])
        self.assertFalse(result["baseline_dominates_vad"])

    def test_extension_rejects_missing_progress_and_extra_pipeline_stages(self):
        private = evaluator.ROOT / ".local"
        with tempfile.TemporaryDirectory(prefix="w0-vad-wrapper-test-", dir=private) as folder:
            base = Path(folder).resolve()
            name = "synthetic"
            local = base / "components"
            plan_path = local / name / "plan.json"
            plan_path.parent.mkdir(parents=True)
            plan = {"id": name, "frozen": True, "clips": [{"id": "clip"}],
                "tasks": [{"id": "vad", "clip": "clip", "stage": "vad"}, {"id": "w0", "clip": "clip", "stage": "w0"}]}
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with patch.object(evaluator, "LOCAL", local), self.assertRaisesRegex(ValueError, "not terminal"):
                evaluator.assemble(name, base / "evaluation.json")
            plan["tasks"].append({"id": "x0", "clip": "clip", "stage": "x0"})
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with patch.object(evaluator, "LOCAL", local), self.assertRaisesRegex(ValueError, "exactly VAD/W0"):
                evaluator.assemble(name, base / "evaluation.json")
            self.assertFalse((base / "evaluation.json").exists())


if __name__ == "__main__":
    unittest.main()
