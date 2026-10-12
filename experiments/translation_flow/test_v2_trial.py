"""Mocked full-flow timing and preregistration guards; no model or GPU calls."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .cli import digest, read_json as actual_read_json
from .v2_trial import trial


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class TrialTests(unittest.TestCase):
    def fixture(self, root, *, recipe="c0", stage="screening", policy=True, scene_count=2):
        manifest, scenes = root / "source-manifest.json", root / "scenes.jsonl"
        write_json(manifest, {"synthetic_source_identity_only": True})
        scenes.write_text("{}\n", encoding="utf-8")
        card = {"schema": "hy30-flow-trial-card-v2",
                "source": {"manifest": str(manifest), "manifest_sha256": digest(manifest),
                           "scenes": str(scenes), "scenes_sha256": digest(scenes)},
                "prepare": {"split": "screen-a", "recipe_id": "trial-a", "recipe": recipe, "stage": stage}}
        if policy:
            policy_path = root / "decision-policy.json"
            write_json(policy_path, {"synthetic_frozen_policy": True})
            card["decision_policy"] = {"path": str(policy_path), "sha256": digest(policy_path)}
        path = root / "card.json"
        write_json(path, card)
        # Frozen mapping is virtual because all preparation/inference is mocked.
        reader = patch("experiments.translation_flow.v2_trial.read_json",
                       side_effect=lambda value: {"scene_ids": [f"scene-{i}" for i in range(scene_count)]}
                       if Path(value).name == "packed-mapping.json" else actual_read_json(value))
        reader.start()
        self.addCleanup(reader.stop)
        return path, card

    def completed(self, *states):
        return {"scenes": [{"scene_id": f"scene-{number}", "status": status}
                           for number, status in enumerate(states)]}

    def test_success_measures_entire_flow_and_passes_frozen_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, card = self.fixture(root, recipe="joint-json")
            output = root / "trial"
            with patch("experiments.translation_flow.v2_trial.prepare") as prep, \
                 patch("experiments.translation_flow.v2_trial.execute", return_value=0) as execute, \
                 patch("experiments.translation_flow.v2_trial.deliver", return_value=self.completed("complete", "complete")) as deliver, \
                 patch("experiments.translation_flow.v2_trial.time.perf_counter",
                       side_effect=[100, 101, 103, 104, 120, 121, 125, 130]):
                code = trial(path, output)
            self.assertEqual(code, 0)
            report = json.loads((output / "trial-completion.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["phases"], {"preparation": 2, "managed_command": 16, "export": 4})
            self.assertEqual(report["total_flow_seconds"], 30)
            self.assertEqual(report["complete_scenes"], 2)
            self.assertEqual(report["expected_scenes"], 2)
            self.assertEqual(report["card_sha256"], digest(path))
            self.assertIn("full weight hash", report["timing_scope"])
            self.assertIn("mechanical checks", report["timing_scope"])
            self.assertEqual(prep.call_args.kwargs["manifest"], Path(card["source"]["manifest"]))
            self.assertEqual(prep.call_args.kwargs["scenes"], Path(card["source"]["scenes"]))
            execute.assert_called_once_with(output / "prepared", output / "execution")
            deliver.assert_called_once_with(Path(card["source"]["manifest"]), output / "prepared/packed-mapping.json",
                                            output / "execution/runtime-run/translation/trial-a", output / "delivery")

    def test_candidate_policy_missing_or_changed_rejects_before_any_phase(self):
        for mode in ("missing", "changed"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card = self.fixture(root, recipe="joint-json", policy=mode != "missing")
                if mode == "changed":
                    policy_path = Path(card["decision_policy"]["path"])
                    policy_path.write_bytes(policy_path.read_bytes() + b"\n")
                output = root / "trial"
                with patch("experiments.translation_flow.v2_trial.prepare") as prep, \
                     patch("experiments.translation_flow.v2_trial.execute") as execute, \
                     patch("experiments.translation_flow.v2_trial.deliver") as deliver:
                    with self.assertRaisesRegex(ValueError, "frozen pre-result decision policy"):
                        trial(path, output)
                prep.assert_not_called()
                execute.assert_not_called()
                deliver.assert_not_called()
                self.assertFalse(output.exists())

    def test_engineering_qualification_does_not_require_candidate_policy(self):
        for recipe, stage in (("semantic", "qualification"), ("c0", "qualification")):
            with self.subTest(recipe=recipe, stage=stage), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, _ = self.fixture(root, recipe=recipe, stage=stage, policy=False, scene_count=1)
                with patch("experiments.translation_flow.v2_trial.prepare"), \
                     patch("experiments.translation_flow.v2_trial.execute", return_value=0), \
                     patch("experiments.translation_flow.v2_trial.deliver", return_value=self.completed("complete")):
                    self.assertEqual(trial(path, root / "trial"), 0)

    def test_c0_screening_candidate_or_control_requires_frozen_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, _ = self.fixture(root, recipe="c0", stage="screening", policy=False)
            with patch("experiments.translation_flow.v2_trial.prepare") as prep:
                with self.assertRaisesRegex(ValueError, "frozen pre-result decision policy"):
                    trial(path, root / "trial")
            prep.assert_not_called()
            self.assertFalse((root / "trial").exists())

    def test_source_manifest_or_scenes_drift_never_dispatches(self):
        for field in ("manifest", "scenes"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card = self.fixture(root)
                source = Path(card["source"][field])
                source.write_bytes(source.read_bytes() + b"\n")
                with patch("experiments.translation_flow.v2_trial.prepare") as prep, \
                     patch("experiments.translation_flow.v2_trial.execute") as execute:
                    with self.assertRaisesRegex(ValueError, "source differs from preregistration"):
                        trial(path, root / "trial")
                prep.assert_not_called()
                execute.assert_not_called()

    def test_partial_export_and_runtime_failure_remain_counted_with_all_phase_times(self):
        for code, states in ((0, ("complete", "incomplete")), (1, ("complete", "complete")), (2, ("incomplete", "incomplete"))):
            with self.subTest(code=code, states=states), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, _ = self.fixture(root)
                output = root / "trial"
                with patch("experiments.translation_flow.v2_trial.prepare"), \
                     patch("experiments.translation_flow.v2_trial.execute", return_value=code), \
                     patch("experiments.translation_flow.v2_trial.deliver", return_value=self.completed(*states)) as deliver, \
                     patch("experiments.translation_flow.v2_trial.time.perf_counter", side_effect=[100, 101, 103, 104, 120, 121, 125, 130]):
                    self.assertEqual(trial(path, output), 1)
                report = json.loads((output / "trial-completion.json").read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "partial")
                self.assertEqual(report["runtime_exit_code"], code)
                self.assertEqual(report["expected_scenes"], 2)
                self.assertEqual(report["complete_scenes"], states.count("complete"))
                self.assertEqual(report["total_flow_seconds"], 30)
                self.assertEqual(report["phases"], {"preparation": 2, "managed_command": 16, "export": 4})
                deliver.assert_called_once()

    def test_failure_in_each_phase_retains_preceding_and_failed_elapsed_evidence(self):
        cases = (("preparation", ValueError("synthetic preparation failure"), [100, 101, 104, 106], {"preparation": 3}),
                 ("managed_command", KeyboardInterrupt("synthetic interruption"), [100, 101, 103, 104, 109, 111],
                  {"preparation": 2, "managed_command": 5}),
                 ("export", FileNotFoundError("synthetic missing export run"), [100, 101, 103, 104, 120, 121, 126, 130],
                  {"preparation": 2, "managed_command": 16, "export": 5}))
        for phase, error, times, expected in cases:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, _ = self.fixture(root)
                output = root / "trial"
                with patch("experiments.translation_flow.v2_trial.prepare", side_effect=error if phase == "preparation" else None) as prep, \
                     patch("experiments.translation_flow.v2_trial.execute", return_value=1,
                           side_effect=error if phase == "managed_command" else None) as execute, \
                     patch("experiments.translation_flow.v2_trial.deliver", return_value=self.completed("complete"),
                           side_effect=error if phase == "export" else None) as deliver, \
                     patch("experiments.translation_flow.v2_trial.time.perf_counter", side_effect=times):
                    with self.assertRaises(type(error)):
                        trial(path, output)
                report = json.loads((output / "trial-completion.json").read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["failed_phase"], phase)
                self.assertEqual(report["phases"], expected)
                self.assertEqual(report["total_flow_seconds"], times[-1] - times[0])
                self.assertIn(type(error).__name__, report["error"])
                self.assertTrue((output / "trial-start.json").exists())
                if phase == "preparation":
                    execute.assert_not_called()
                    deliver.assert_not_called()
                elif phase == "managed_command":
                    deliver.assert_not_called()
                else:
                    self.assertEqual(report["runtime_exit_code"], 1)

    def test_optional_token_paths_convert_to_path_before_preparation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, card = self.fixture(root)
            card["prepare"]["token_counts_path"] = str(root / "counts.json")
            card["prepare"]["measure_source_tokens"] = str(root / "token-inputs.jsonl")
            for name in ("token_counts_path", "measure_source_tokens"):
                write_json(Path(card["prepare"][name]), {"synthetic": True})
            card["artifacts"] = {name: digest(Path(card["prepare"][name]))
                                 for name in ("token_counts_path", "measure_source_tokens")}
            write_json(path, card)
            with patch("experiments.translation_flow.v2_trial.prepare") as prep, \
                 patch("experiments.translation_flow.v2_trial.execute", return_value=0), \
                 patch("experiments.translation_flow.v2_trial.deliver", return_value=self.completed("complete", "complete")):
                self.assertEqual(trial(path, root / "trial"), 0)
            self.assertEqual(prep.call_args.kwargs["token_counts_path"], root / "counts.json")
            self.assertEqual(prep.call_args.kwargs["measure_source_tokens"], root / "token-inputs.jsonl")

    def test_optional_token_artifact_missing_hash_or_drift_never_dispatches(self):
        for name in ("token_counts_path", "measure_source_tokens"):
            for mode in ("missing", "drift"):
                with self.subTest(name=name, mode=mode), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    path, card = self.fixture(root)
                    artifact = root / "token-artifact.json"
                    write_json(artifact, {"synthetic": True})
                    card["prepare"][name] = str(artifact)
                    if mode == "drift":
                        card["artifacts"] = {name: digest(artifact)}
                        artifact.write_bytes(artifact.read_bytes() + b"\n")
                    write_json(path, card)
                    with patch("experiments.translation_flow.v2_trial.prepare") as prep:
                        with self.assertRaisesRegex(ValueError, "preregistered artifact SHA256"):
                            trial(path, root / "trial")
                    prep.assert_not_called()
                    self.assertFalse((root / "trial").exists())

    def test_export_empty_missing_extra_or_duplicate_scene_cannot_complete(self):
        exports = ([], [{"scene_id": "scene-0", "status": "complete"}],
                   [{"scene_id": "scene-0", "status": "complete"}, {"scene_id": "scene-1", "status": "complete"},
                    {"scene_id": "extra", "status": "complete"}],
                   [{"scene_id": "scene-0", "status": "complete"}, {"scene_id": "scene-0", "status": "complete"}])
        for number, records in enumerate(exports):
            with self.subTest(case=number), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, _ = self.fixture(root)
                with patch("experiments.translation_flow.v2_trial.prepare"), \
                     patch("experiments.translation_flow.v2_trial.execute", return_value=0), \
                     patch("experiments.translation_flow.v2_trial.deliver", return_value={"scenes": records}), \
                     patch("experiments.translation_flow.v2_trial.time.perf_counter", side_effect=[100, 101, 103, 104, 120, 121, 125, 130]):
                    self.assertEqual(trial(path, root / "trial"), 1)
                report = actual_read_json(root / "trial/trial-completion.json")
                self.assertEqual(report["status"], "partial")
                self.assertEqual(report["expected_scenes"], 2)
                self.assertEqual(report["exported_scene_records"], len(records))
                self.assertEqual(report["total_flow_seconds"], 30)
                self.assertTrue(report["missing_scene_ids"] or report["unexpected_scene_ids"] or report["duplicate_scene_ids"])


if __name__ == "__main__":
    unittest.main()
