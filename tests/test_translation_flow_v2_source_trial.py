"""Offline integration of frozen source preparation and full translation trials."""

from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_flow.cli import digest, read_json
from experiments.translation_flow.v2_execute import execute, execute_source_preparation
from experiments.translation_flow.v2_trial import trial
from tests import test_translation_flow_v2_source_preparation as source_fixtures


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class SourceTrialTests(unittest.TestCase):
    def fixture(self, root):
        plan, args = source_fixtures.SourcePreparationWorkerTests().fixture(root)
        manifest = Path(plan["source"]["manifest"])
        write_json(manifest, {"windows": [
            {"id": "scoring-a", "scene_id": "scene-a", "split": "screen-a", "scored_ids": ["scene-a-2"]},
            {"id": "scoring-b", "scene_id": "scene-a", "split": "screen-a", "scored_ids": ["scene-a-3"]}]})
        freeze = manifest.parent / "freeze-manifest.json"
        frozen = read_json(freeze)
        frozen["artifacts"][0]["sha256"] = digest(manifest)
        write_json(freeze, frozen)
        plan["source"]["manifest_sha256"] = digest(manifest)
        plan["source"]["freeze_sha256"] = digest(freeze)
        write_json(args.session_plan, plan)
        card = {"schema": "hy30-flow-trial-card-v2",
                "source": {key: plan["source"][key] for key in ("manifest", "manifest_sha256", "scenes", "scenes_sha256")},
                "prepare": {"split": "screen-a", "recipe_id": "trial-a", "recipe": "base-json",
                            "stage": "qualification", "seed": plan["settings"]["seed"]},
                "source_preparation": {"plan": args.session_plan.name, "sha256": digest(args.session_plan)}}
        path = root / "card.json"
        write_json(path, card)
        return path, card, plan, args.session_plan

    def fake_source(self, card, plan, *, partial=False, code=0):
        def run(path, output):
            output.mkdir()
            runtime = output / "runtime-run/translation"
            runtime.mkdir(parents=True)
            write_json(output / "command-completion.json", {"command_seconds": 9})
            attempts = [{"completion_dispatched": True, "input_tokens": 7, "request": {"n_predict": 4096}},
                        {"completion_dispatched": True, "input_tokens": 7, "request": {"n_predict": 4096}}]
            from experiments.translation_flow.v2_source_preparation import ARTIFACT_SCHEMA, parse_response
            response = source_fixtures.term_response() if plan["mode"] == "terms" else source_fixtures.background_response()
            preparation = parse_response(json.dumps(response, ensure_ascii=False), plan["mode"], source_fixtures.source_scene())
            (runtime / "ledger.jsonl").write_text(json.dumps({"scene_id": "scene-a", "mode": plan["mode"],
                       "status": "prepared", "preparation": preparation, "attempts": attempts}) + "\n", encoding="utf-8")
            write_json(runtime / "preparation-options.json", {"schema": ARTIFACT_SCHEMA, "complete": not partial,
                       "session_plan_sha256": card["source_preparation"]["sha256"], "source": plan["source"],
                       "scene_ids": plan["scene_ids"], "settings": plan["settings"], "mode": plan["mode"],
                       "stage": plan["stage"], "preparations": [preparation],
                       "identity": source_fixtures.SourcePreparationWorkerTests().identity(None),
                       "code_sha256": {"synthetic.py": "a" * 64}, "semantic_quality_checked": False,
                       "cache_reset": {"verified": True, "first_response_checked": True, "first_response_cache_n": 0},
                       "cost_artifacts": {"ledger.jsonl": digest(runtime / "ledger.jsonl")}})
            return code
        return run

    def fake_prepare(self, **kwargs):
        kwargs["output"].mkdir()
        write_json(kwargs["output"] / "packed-mapping.json", {"scene_ids": ["scene-a"]})

    def test_complete_terms_and_background_run_distinct_sessions_and_charge_once(self):
        for mode in ("terms", "background"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card, plan, plan_path = self.fixture(root)
                plan["mode"] = mode
                write_json(plan_path, plan)
                card["source_preparation"]["sha256"] = digest(plan_path)
                write_json(path, card)
                order = []
                def source(*args):
                    order.append("source")
                    return self.fake_source(card, plan)(*args)
                def prepare(**kwargs):
                    order.append("prepare")
                    self.fake_prepare(**kwargs)
                def translate(*args):
                    order.append("translation")
                    return 0
                def deliver(*args):
                    order.append("delivery")
                    return {"scenes": [{"scene_id": "scene-a", "status": "complete"}]}
                with patch("experiments.translation_flow.v2_trial.execute_source_preparation", side_effect=source) as aux, \
                     patch("experiments.translation_flow.v2_trial.prepare", side_effect=prepare) as prep, \
                     patch("experiments.translation_flow.v2_trial.execute", side_effect=translate), \
                     patch("experiments.translation_flow.v2_trial.deliver", side_effect=deliver), \
                     patch("experiments.translation_flow.v2_trial.time.perf_counter",
                           side_effect=[100, 101, 110, 111, 113, 114, 130, 131, 135, 140]):
                    self.assertEqual(trial(path, root / "trial"), 0)
                self.assertEqual(order, ["source", "prepare", "translation", "delivery"])
                aux.assert_called_once_with(plan_path.resolve(), root / "trial/source-preparation")
                artifact = root / "trial/source-preparation/runtime-run/translation/preparation-options.json"
                self.assertEqual(prep.call_args.kwargs["source_preparation_path"], artifact)
                self.assertEqual(prep.call_args.kwargs["source_preparation_sha256"], digest(artifact))
                report = read_json(root / "trial/trial-completion.json")
                self.assertEqual(report["phases"], {"source_preparation": 9, "preparation": 2, "managed_command": 16, "export": 4})
                self.assertEqual(report["total_flow_seconds"], 40)
                cost = report["source_preparation"]["cost"]
                self.assertEqual(cost["translation_calls"], 2)
                self.assertEqual(cost["estimated_tokens"], 2 * 4103)
                self.assertEqual(cost["scene_records"], 1)
                self.assertEqual(cost["command_seconds"], 9)
                self.assertEqual(cost["ledger"]["sha256"], digest(Path(cost["ledger"]["path"])))
                self.assertEqual(set(report["source_preparation"]["budgets"]),
                                 {"max_translation_calls", "max_judge_calls", "max_estimated_tokens", "max_wall_seconds"})

    def test_partial_or_failed_preparation_never_runs_main(self):
        for partial, code in ((True, 0), (False, 1)):
            with self.subTest(partial=partial, code=code), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card, plan, _ = self.fixture(root)
                with patch("experiments.translation_flow.v2_trial.execute_source_preparation", side_effect=self.fake_source(card, plan, partial=partial, code=code)), \
                     patch("experiments.translation_flow.v2_trial.prepare") as prep, \
                     patch("experiments.translation_flow.v2_trial.execute") as translation:
                    with self.assertRaises(ValueError):
                        trial(path, root / "trial")
                prep.assert_not_called()
                translation.assert_not_called()
                report = read_json(root / "trial/trial-completion.json")
                self.assertEqual(report["failed_phase"], "source_preparation")
                self.assertEqual(report["source_preparation"]["cost"]["translation_calls"], 2)
                self.assertGreater(report["total_flow_seconds"], 0)

    def test_artifact_identity_mismatch_and_ledger_drift_stop_before_main(self):
        for changed in ("stage", "seed", "plan", "source", "ledger"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card, plan, _ = self.fixture(root)
                def source(path, output):
                    self.fake_source(card, plan)(path, output)
                    artifact = output / "runtime-run/translation/preparation-options.json"
                    options = read_json(artifact)
                    if changed == "stage":
                        options["stage"] = "screening"
                    elif changed == "seed":
                        options["settings"]["seed"] += 1
                    elif changed == "plan":
                        options["session_plan_sha256"] = "a" * 64
                    elif changed == "source":
                        options["source"]["manifest_sha256"] = "a" * 64
                    elif changed == "ledger":
                        ledger = output / "runtime-run/translation/ledger.jsonl"
                        ledger.write_bytes(ledger.read_bytes() + b"\n")
                    write_json(artifact, options)
                    return 0
                with patch("experiments.translation_flow.v2_trial.execute_source_preparation", side_effect=source), \
                     patch("experiments.translation_flow.v2_trial.prepare") as prep, \
                     patch("experiments.translation_flow.v2_trial.execute") as translation:
                    with self.assertRaises(ValueError):
                        trial(path, root / "trial")
                prep.assert_not_called()
                translation.assert_not_called()

    def test_plan_card_and_selection_drift_rejected_before_any_output(self):
        for mode in ("hash", "stage", "seed", "scenes", "unknown", "direct-artifact", "source"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card, plan, plan_path = self.fixture(root)
                if mode == "hash":
                    plan_path.write_bytes(plan_path.read_bytes() + b"\n")
                elif mode == "stage":
                    card["prepare"]["stage"] = "screening"
                    card["prepare"]["recipe"] = "c0"
                elif mode == "seed":
                    card["prepare"]["seed"] += 1
                elif mode == "scenes":
                    card["prepare"]["selected_scene_ids"] = []
                elif mode == "unknown":
                    card["source_preparation"]["mode"] = "terms"
                elif mode == "direct-artifact":
                    card["prepare"]["source_preparation_path"] = "old-options.json"
                elif mode == "source":
                    other = root / "other-manifest.json"
                    other.write_bytes(Path(card["source"]["manifest"]).read_bytes())
                    card["source"]["manifest"] = str(other)
                write_json(path, card)
                with patch("experiments.translation_flow.v2_trial.execute_source_preparation") as aux:
                    with self.assertRaises(ValueError):
                        trial(path, root / "trial")
                aux.assert_not_called()
                self.assertFalse((root / "trial").exists())

    def test_frozen_implementation_identity_requires_unchanged_unique_artifacts(self):
        for mode in ("valid", "drift", "duplicate", "extra"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card, plan, _ = self.fixture(root)
                code = root / "implementation.py"
                code.write_text("# synthetic implementation\n", encoding="utf-8")
                card["implementation_identity"] = [{"path": code.name, "sha256": digest(code)}]
                if mode == "drift":
                    code.write_bytes(code.read_bytes() + b"\n")
                if mode == "duplicate":
                    card["implementation_identity"].append(deepcopy(card["implementation_identity"][0]))
                if mode == "extra":
                    card["implementation_identity"][0]["extra"] = True
                write_json(path, card)
                with patch("experiments.translation_flow.v2_trial.execute_source_preparation", side_effect=self.fake_source(card, plan)), \
                     patch("experiments.translation_flow.v2_trial.prepare", side_effect=self.fake_prepare), \
                     patch("experiments.translation_flow.v2_trial.execute", return_value=0), \
                     patch("experiments.translation_flow.v2_trial.deliver", return_value={"scenes": [{"scene_id": "scene-a", "status": "complete"}]}):
                    if mode == "valid":
                        self.assertEqual(trial(path, root / "trial"), 0)
                    else:
                        with self.assertRaisesRegex(ValueError, "implementation identity"):
                            trial(path, root / "trial")
                        self.assertFalse((root / "trial").exists())


class SourceTrialVersion3Tests(unittest.TestCase):
    def fixture(self, root, *, mode="terms", projection=None):
        path, card, plan, plan_path = SourceTrialTests().fixture(root)
        from experiments.translation_flow.v2_source_preparation import SESSION_SCHEMA, TERMS_PROTOCOL, BACKGROUND_PROTOCOL
        plan.update(schema=SESSION_SCHEMA, mode=mode,
                    protocol=TERMS_PROTOCOL if mode == "terms" else BACKGROUND_PROTOCOL)
        plan["settings"]["n_predict"] = 2048
        write_json(plan_path, plan)
        card["source_preparation"]["sha256"] = digest(plan_path)
        card["prepare"]["source_preparation_projection"] = projection or (
            "eligible-quoted-local-terms-v1" if mode == "terms" else "background-supported-scene-context-v1")
        write_json(path, card)
        return path, card, plan, plan_path

    def source(self, plan, response):
        def run(plan_path, output):
            output.mkdir()
            write_json(output / "command-completion.json", {"command_seconds": 9})
            args = argparse.Namespace(candidate=source_fixtures.CANDIDATE, session_plan=plan_path,
                                      output_dir=output / "runtime-run/translation",
                                      server_url="http://127.0.0.1:8080", context_size=8192,
                                      engine_manifest=output / "engine.json", asset_manifest=[], stop_on_oom=True)
            code, _ = source_fixtures.SourcePreparationWorkerTests().run_fake(args, [source_fixtures.result(response)])
            return code
        return run

    def test_terms_background_and_source_only_control_forward_explicit_projection(self):
        pairs = (("terms", "eligible-quoted-local-terms-v1"),
                 ("background", "background-supported-scene-context-v1"),
                 ("background", "background-supported-source-only-control-v1"))
        for mode, projection in pairs:
            with self.subTest(mode=mode, projection=projection), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card, plan, _ = self.fixture(root, mode=mode, projection=projection)
                response = (source_fixtures.SourcePreparationVersion3Tests().proposals(mixed=True) if mode == "terms"
                            else source_fixtures.background_response(uncertain=True))
                with patch("experiments.translation_flow.v2_trial.execute_source_preparation", side_effect=self.source(plan, response)), \
                     patch("experiments.translation_flow.v2_trial.prepare", side_effect=SourceTrialTests().fake_prepare) as prep, \
                     patch("experiments.translation_flow.v2_trial.execute", return_value=0) as translate, \
                     patch("experiments.translation_flow.v2_trial.deliver", return_value={"scenes": [{"scene_id": "scene-a", "status": "complete"}]}):
                    self.assertEqual(trial(path, root / "trial"), 0)
                self.assertEqual(prep.call_args.kwargs["source_preparation_projection"], projection)
                self.assertEqual(prep.call_args.kwargs["source_preparation_sha256"],
                                 digest(prep.call_args.kwargs["source_preparation_path"]))
                translate.assert_called_once()
                report = read_json(root / "trial/trial-completion.json")
                self.assertEqual(report["source_preparation"]["protocol"], plan["protocol"])
                self.assertEqual(report["source_preparation"]["projection"], projection)
                cost = report["source_preparation"]["cost"]
                self.assertEqual(cost["translation_calls"], 1)
                self.assertEqual(cost["estimated_tokens"], 2055)
                if mode == "terms":
                    self.assertEqual((cost["returned_count"], cost["accepted_count"], cost["declined_count"]), (3, 1, 2))
                    self.assertEqual(cost["zero_effect_scene_records"], 0)
                else:
                    self.assertNotIn("accepted_count", cost)

    def test_empty_eligible_terms_are_explicit_zero_effect_complete_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, _, plan, _ = self.fixture(root)
            response = source_fixtures.SourcePreparationVersion3Tests().proposals()
            with patch("experiments.translation_flow.v2_trial.execute_source_preparation", side_effect=self.source(plan, response)), \
                 patch("experiments.translation_flow.v2_trial.prepare", side_effect=SourceTrialTests().fake_prepare), \
                 patch("experiments.translation_flow.v2_trial.execute", return_value=0), \
                 patch("experiments.translation_flow.v2_trial.deliver", return_value={"scenes": [{"scene_id": "scene-a", "status": "complete"}]}):
                self.assertEqual(trial(path, root / "trial"), 0)
            cost = read_json(root / "trial/trial-completion.json")["source_preparation"]["cost"]
            self.assertEqual(cost["accepted_count"], 0)
            self.assertEqual(cost["declined_count"], 2)
            self.assertEqual(cost["zero_effect_scene_records"], 1)
            self.assertEqual(cost["translation_calls"], 1)

    def test_missing_wrong_or_legacy_projection_and_protocol_override_stop_before_dispatch(self):
        for changed in ("missing", "wrong-mode", "unknown", "legacy", "override"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                path, card, plan, plan_path = self.fixture(root)
                if changed == "missing":
                    del card["prepare"]["source_preparation_projection"]
                elif changed == "wrong-mode":
                    card["prepare"]["source_preparation_projection"] = "background-supported-scene-context-v1"
                elif changed == "unknown":
                    card["prepare"]["source_preparation_projection"] = "unregistered"
                elif changed == "legacy":
                    plan["schema"] = source_fixtures.SCHEMA
                    del plan["protocol"]
                    write_json(plan_path, plan)
                    card["source_preparation"]["sha256"] = digest(plan_path)
                else:
                    card["prepare"]["source_preparation_protocol"] = plan["protocol"]
                write_json(path, card)
                with patch("experiments.translation_flow.v2_trial.execute_source_preparation") as source:
                    with self.assertRaises(ValueError):
                        trial(path, root / "trial")
                source.assert_not_called()
                self.assertFalse((root / "trial").exists())

    def test_legacy_artifact_cannot_replace_frozen_versioned_preparation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path, card, plan, _ = self.fixture(root)
            with patch("experiments.translation_flow.v2_trial.execute_source_preparation", side_effect=SourceTrialTests().fake_source(card, plan)), \
                 patch("experiments.translation_flow.v2_trial.prepare") as prep, \
                 patch("experiments.translation_flow.v2_trial.execute") as translate:
                with self.assertRaisesRegex(ValueError, "artifact differs"):
                    trial(path, root / "trial")
            prep.assert_not_called()
            translate.assert_not_called()


class ManagedPreparationCommandTests(unittest.TestCase):
    def test_source_runtime_command_uses_separate_worker_and_complete_startup_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, args = source_fixtures.SourcePreparationWorkerTests().fixture(root)
            output = root / "managed"
            with patch("experiments.translation_flow.v2_execute.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(execute_source_preparation(args.session_plan, output, port=8091), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--session-worker") + 1], "experiments.translation_flow.v2_source_preparation")
            self.assertEqual(command[command.index("--output-dir") + 1], str((output / "runtime-run").resolve()))
            self.assertEqual(command[command.index("--port") + 1], "8091")
            completion = read_json(output / "command-completion.json")
            self.assertIn("pre-load model SHA256", completion["measurement_scope"])
            self.assertEqual(completion["plan_sha256"], digest(args.session_plan))

    def test_managed_interruption_retains_elapsed_failure_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, args = source_fixtures.SourcePreparationWorkerTests().fixture(root)
            with patch("experiments.translation_flow.v2_execute.subprocess.run", side_effect=KeyboardInterrupt("synthetic stop")):
                with self.assertRaises(KeyboardInterrupt):
                    execute_source_preparation(args.session_plan, root / "managed")
            completion = read_json(root / "managed/command-completion.json")
            self.assertIsNone(completion["returncode"])
            self.assertGreater(completion["command_seconds"], 0)
            self.assertIn("KeyboardInterrupt", completion["error"])

    def test_main_runtime_retains_both_frozen_preparation_checks(self):
        for changed in ("session-plan.json", "packed-mapping.json"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                prepared = root / "prepared"
                prepared.mkdir()
                for name in ("session-plan.json", "packed-mapping.json"):
                    write_json(prepared / name, {})
                write_json(prepared / "preparation.json", {"session_plan_sha256": digest(prepared / "session-plan.json"),
                                                           "mapping_sha256": digest(prepared / "packed-mapping.json")})
                artifact = prepared / changed
                artifact.write_bytes(artifact.read_bytes() + b"\n")
                with patch("experiments.translation_flow.v2_execute.subprocess.run") as run:
                    with self.assertRaisesRegex(ValueError, "prepared identities changed"):
                        execute(prepared, root / "runtime")
                run.assert_not_called()
                self.assertFalse((root / "runtime").exists())


if __name__ == "__main__":
    unittest.main()
