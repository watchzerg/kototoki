"""Offline generated scene cards through frozen batch options and the main worker."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_flow.cli import digest
from experiments.translation_flow.v2_prepare import prepare
from experiments.translation_flow.v2_worker import execute_plan, load_plan, source_options_by_window
from experiments.translation_flow.test_worker import FakeClient
from experiments.translation_flow.test_v2_worker import result
from experiments.tests import test_translation_flow_v2_source_preparation as source_fixtures


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class SourceIntegrationTests(unittest.TestCase):
    def fixture(self, root):
        helper = source_fixtures.SourcePreparationWorkerTests()
        plan, args = helper.fixture(root)
        manifest = Path(plan["source"]["manifest"])
        dump(manifest, {"windows": [{"id": "score-a", "window_id": "score-a", "scene_id": "scene-a",
                                    "split": "screen-a", "scored_ids": ["scene-a-1", "scene-a-2", "scene-a-3"]}]})
        freeze = manifest.parent / "freeze-manifest.json"
        frozen = json.loads(freeze.read_text(encoding="utf-8"))
        frozen["artifacts"][0]["sha256"] = digest(manifest)
        dump(freeze, frozen)
        plan["source"]["manifest_sha256"] = digest(manifest)
        plan["source"]["freeze_sha256"] = digest(freeze)
        dump(args.session_plan, plan)
        self.assertEqual(helper.run_fake(args, [result(source_fixtures.term_response())])[0], 0)
        artifact = args.output_dir / "preparation-options.json"
        prepared = root / "main-prepared"
        prepare(manifest=manifest, scenes=Path(plan["source"]["scenes"]), output=prepared,
                split="screen-a", recipe_id="F6-terms", recipe="base-json", stage="qualification",
                target_size=1, context_before=0, context_after=0,
                source_preparation_path=artifact, source_preparation_sha256=digest(artifact))
        return helper, args, artifact, prepared

    def test_scoped_generated_options_reach_only_visible_batches_and_costs_remain_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helper, args, artifact, prepared = self.fixture(root)
            plan, loaded = load_plan(prepared / "session-plan.json")
            item, _, windows = loaded[0]
            options = source_options_by_window(item, prepared / "session-plan.json", windows)
            self.assertEqual(options[windows[0]["id"]]["terms"][0]["evidence_ids"], ["scene-a-1"])
            self.assertEqual(options[windows[1]["id"]], {"terms": []})
            self.assertEqual(options[windows[2]["id"]]["terms"][0]["evidence_ids"], ["scene-a-3"])
            args = deepcopy(args)
            args.session_plan = prepared / "session-plan.json"
            args.output_dir = root / "main-run"
            client = FakeClient([result({"translations": {window["translate_ids"][0]: "中文台词"}}) for window in windows])
            self.assertEqual(execute_plan(args, lambda *a, **k: client, helper.identity), 0)
            completed = json.loads((args.output_dir / "worker-completion.json").read_text(encoding="utf-8"))
            self.assertEqual(completed["budget"]["translation_calls"], 3)
            run = json.loads((args.output_dir / "F6-terms/run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["source_preparation"]["artifact"]["sha256"], digest(artifact))
            first = json.loads((args.output_dir / f"F6-terms/window-{windows[0]['id']}.json").read_text(encoding="utf-8"))
            self.assertIn("shared separate preparation", first["source_preparation"]["cost_attribution"])
            self.assertEqual(len(first["attempts"]), 1)

    def test_changed_sidecar_or_generated_source_identity_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, artifact, prepared = self.fixture(root)
            sidecar = prepared / "batch-options.json"
            sidecar.write_bytes(sidecar.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "pointer changed"):
                load_plan(prepared / "session-plan.json")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, artifact, prepared = self.fixture(root)
            scene_options = json.loads(artifact.read_text(encoding="utf-8"))
            scene_options["settings"]["seed"] += 1
            dump(artifact, scene_options)
            original = json.loads((prepared / "packed-mapping.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "identity differs"):
                prepare(manifest=Path(original["source_manifest"]["path"]), scenes=Path(original["source_scenes"]["path"]),
                        output=root / "wrong-seed", split="screen-a", recipe_id="F6-terms", recipe="base-json",
                        stage="qualification", source_preparation_path=artifact, source_preparation_sha256=digest(artifact))

    def test_rehashing_tampered_visible_options_does_not_bypass_projection_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, _, prepared = self.fixture(root)
            sidecar = prepared / "batch-options.json"
            scoped = json.loads(sidecar.read_text(encoding="utf-8"))
            first = next(iter(scoped["windows"].values()))
            first["options"]["terms"][0]["translation"] = "伪造约定"
            dump(sidecar, scoped)
            path = prepared / "session-plan.json"
            plan = json.loads(path.read_text(encoding="utf-8"))
            plan["workloads"][0]["source_preparation"]["batch_options"]["sha256"] = digest(sidecar)
            dump(path, plan)
            with self.assertRaisesRegex(ValueError, "exact visible source evidence"):
                load_plan(path)

    def test_rehashed_extra_preparation_context_cannot_expand_frozen_scene(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, _, artifact, prepared = self.fixture(root)
            auxiliary = json.loads(artifact.read_text(encoding="utf-8"))
            auxiliary["preparations"][0]["source_context"].append({"id": "unfrozen-1", "text": "隊長の秘密です。"})
            ledger = artifact.parent / "ledger.jsonl"
            row = json.loads(ledger.read_text(encoding="utf-8"))
            row["preparation"] = deepcopy(auxiliary["preparations"][0])
            dump(ledger, row)
            auxiliary["cost_artifacts"]["ledger.jsonl"] = digest(ledger)
            dump(artifact, auxiliary)
            packed = json.loads((prepared / "packed-mapping.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "exact frozen scenes"):
                prepare(manifest=Path(packed["source_manifest"]["path"]), scenes=Path(packed["source_scenes"]["path"]),
                        output=root / "expanded-context", split="screen-a", recipe_id="F6-terms", recipe="base-json",
                        stage="qualification", source_preparation_path=artifact, source_preparation_sha256=digest(artifact))
            self.assertFalse((root / "expanded-context").exists())


if __name__ == "__main__":
    unittest.main()
