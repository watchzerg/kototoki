"""Frozen new source protocols through packing, native dispatch and delivery."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_demo import adapters

from experiments.translation_flow.cli import digest
from experiments.translation_flow.v2_prepare import prepare
from experiments.translation_flow.v2_worker import execute_plan, load_plan, source_options_by_window, run_window
from experiments.translation_flow.test_worker import budget
from experiments.translation_flow.test_worker import FakeClient
from experiments.translation_flow.test_v2_worker import result
from experiments.translation_flow import v2_recipes
from tests import test_translation_flow_v2_source_preparation as fixtures


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class NewSourceIntegrationTests(unittest.TestCase):
    def fixture(self, root, *, mode="terms", projection=None, proposals=None):
        helper = fixtures.SourcePreparationWorkerTests()
        plan, args = helper.fixture(root, mode=mode)
        manifest = Path(plan["source"]["manifest"])
        dump(manifest, {"windows": [{"id": "score-a", "window_id": "score-a", "scene_id": "scene-a",
             "split": "screen-a", "scored_ids": ["scene-a-1", "scene-a-2", "scene-a-3"]}]})
        freeze = manifest.parent / "freeze-manifest.json"
        frozen = json.loads(freeze.read_text(encoding="utf-8"))
        frozen["artifacts"][0]["sha256"] = digest(manifest)
        dump(freeze, frozen)
        plan["source"].update(manifest_sha256=digest(manifest), freeze_sha256=digest(freeze))
        plan.update(schema="hy30-source-preparation-session-v3",
                    protocol="eligibility-filtered-proposals-v1" if mode == "terms" else "quoted-background-with-uncertainty-v1")
        plan["settings"]["n_predict"] = 2048
        dump(args.session_plan, plan)
        if mode == "terms":
            response = proposals if proposals is not None else {"terms": [
                {"source": "隊長", "translation": "队长", "uncertain": True},
                {"source": "雨", "translation": "雨", "uncertain": False}]}
            projection = projection or "eligible-quoted-local-terms-v1"
        else:
            response = fixtures.background_response(uncertain=True)
            response["background"][0]["evidence"].append({"id": "scene-a-3", "quote": "隊長を呼んでください。"})
            projection = projection or "background-supported-scene-context-v1"
        code, client = helper.run_fake(args, [result(response)])
        self.assertEqual(code, 0)
        self.assertEqual(len(client.requests), 1)
        artifact = args.output_dir / "preparation-options.json"
        prepared = root / "prepared"
        prepare(manifest=manifest, scenes=Path(plan["source"]["scenes"]), output=prepared,
                split="screen-a", recipe_id="new-source", recipe="base-json", stage="qualification",
                target_size=1, context_before=0, context_after=0,
                source_preparation_path=artifact, source_preparation_sha256=digest(artifact),
                source_preparation_projection=projection)
        return helper, args, artifact, prepared

    def test_terms_preserve_declines_uncertainty_costs_and_complete_denominators(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helper, args, artifact, prepared = self.fixture(root)
            _, loaded = load_plan(prepared / "session-plan.json")
            item, _, windows = loaded[0]
            options = source_options_by_window(item, prepared / "session-plan.json", windows)
            first = options[windows[0]["id"]]["quoted_terms"]
            self.assertEqual((first["returned_proposal_count"], first["accepted_proposal_count"], first["declined_proposal_count"]), (2, 1, 1))
            self.assertTrue(first["terms"][0]["uncertain"])
            self.assertTrue(options[windows[1]["id"]]["quoted_terms"]["zero_effective_injection"])
            prompt = v2_recipes.render_window("base-json", windows[0], options[windows[0]["id"]])
            self.assertIn('"uncertain": true', prompt)
            self.assertIn('"quote": "隊長"', prompt)
            for key in ("protocol", "source_scene_sha256", "preparation_record_sha256", "cost_attribution", "proposal_count", "semantic_quality_checked"):
                self.assertNotIn(key, prompt)
            args = deepcopy(args)
            args.session_plan, args.output_dir = prepared / "session-plan.json", root / "main-run"
            client = FakeClient([result({"translations": {window["translate_ids"][0]: "台词"}}) for window in windows])
            sidecar_parses = []
            original_parse = adapters.strict_json
            def counted_parse(content):
                if '"hy30-flow-batch-options-v3"' in content:
                    sidecar_parses.append(content)
                return original_parse(content)
            with patch.object(adapters, "strict_json", side_effect=counted_parse):
                self.assertEqual(execute_plan(args, lambda *a, **k: client, helper.identity), 0)
            # Two immutable validation passes and one dispatch cache load, never
            # a full-sidecar parse for each translated batch.
            self.assertEqual(len(sidecar_parses), 3)
            completion = json.loads((args.output_dir / "worker-completion.json").read_text(encoding="utf-8"))
            self.assertEqual(completion["budget"]["translation_calls"], 3)
            ledger = [json.loads(line) for line in (args.output_dir / "new-source/ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["source_preparation"]["source_visibility"]["injected_items"] for row in ledger], [1, 0, 1])
            self.assertEqual(len(json.loads(artifact.read_text(encoding="utf-8"))["preparations"][0]["proposals"]), 2)

    def test_empty_eligible_is_complete_zero_effect_not_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, prepared = self.fixture(Path(temp), proposals={"terms": [{"source": "雨", "translation": "雨", "uncertain": False}]})
            _, loaded = load_plan(prepared / "session-plan.json")
            item, _, windows = loaded[0]
            options = source_options_by_window(item, prepared / "session-plan.json", windows)
            self.assertEqual(len(windows), 3)
            self.assertTrue(all(row["quoted_terms"]["zero_effective_injection"] for row in options.values()))
            self.assertNotIn("源文术语建议", v2_recipes.render_window("base-json", windows[0], options[windows[0]["id"]]))

    def test_scene_card_expands_only_exact_support_and_control_matches_visibility(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, prepared = self.fixture(Path(temp), mode="background")
            _, loaded = load_plan(prepared / "session-plan.json")
            item, _, windows = loaded[0]
            options = source_options_by_window(item, prepared / "session-plan.json", windows)
            first = windows[0]
            self.assertEqual([cue["id"] for cue in first["context"]], ["scene-a-1", "scene-a-3"])
            self.assertEqual(first["translate_ids"], ["scene-a-1"])
            card = options[first["id"]]["scene_card"]
            self.assertEqual(card["new_readonly_ids"], ["scene-a-3"])
            self.assertTrue(card["background"][0]["uncertain"])
            self.assertFalse(card["full_scene_visible"])
            prompt = v2_recipes.render_window("base-json", first, options[first["id"]])
            self.assertIn("保留每条 uncertain", prompt)
            self.assertIn('"quote": "隊長を呼んでください。"', prompt)
            for key in ("full_scene_source_hash", "source_preparation_record_sha256", "cost_attribution", "semantic_quality_checked"):
                self.assertNotIn(key, prompt)
            middle = options[windows[1]["id"]]["scene_card"]
            self.assertTrue(middle["full_scene_visible"])
            self.assertIn("已覆盖完整场景原文", v2_recipes.render_window("base-json", windows[1], options[windows[1]["id"]]))
            expected_contexts = [window["context"] for window in windows]
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, prepared = self.fixture(Path(temp), mode="background", projection="background-supported-source-only-control-v1")
            _, loaded = load_plan(prepared / "session-plan.json")
            item, _, windows = loaded[0]
            options = source_options_by_window(item, prepared / "session-plan.json", windows)
            self.assertEqual([window["context"] for window in windows], expected_contexts)
            self.assertTrue(all(row == {} for row in options.values()))
            self.assertNotIn("源文只读场景卡", v2_recipes.render_window("base-json", windows[0], options[windows[0]["id"]]))

    def test_rehashed_sidecar_forgery_rejected(self):
        for field in ("options", "visibility"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                _, _, _, prepared = self.fixture(Path(temp))
                sidecar_path = prepared / "batch-options.json"
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                row = next(iter(sidecar["windows"].values()))
                if field == "options":
                    row[field]["quoted_terms"]["terms"][0]["translation"] = "forged"
                else:
                    row[field]["actual_context_ids"] += ["foreign"]
                dump(sidecar_path, sidecar)
                plan_path = prepared / "session-plan.json"
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                plan["workloads"][0]["source_preparation"]["batch_options"]["sha256"] = digest(sidecar_path)
                dump(plan_path, plan)
                with self.assertRaises(ValueError):
                    load_plan(plan_path)

    def test_expanded_prompt_capacity_stops_before_completion_and_retains_all_source(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, prepared = self.fixture(Path(temp), mode="background")
            path = prepared / "session-plan.json"
            _, loaded = load_plan(path)
            item, _, windows = loaded[0]
            scoped = source_options_by_window(item, path, windows)
            item = {**item, **scoped[windows[0]["id"]]}
            client = FakeClient(tokens=4033)
            row = run_window(client, windows[0], item, 8192, budget(max_estimated_tokens=50000), {})
            self.assertEqual(client.requests, [])
            self.assertEqual(row["status"], "setup_failed")
            self.assertIn("no silent source truncation", row["reason"])
            self.assertEqual(row["attempts"][0]["input_tokens"], 4033)
            self.assertFalse(row["attempts"][0]["completion_dispatched"])
            self.assertEqual([cue["id"] for cue in windows[0]["context"]], ["scene-a-1", "scene-a-3"])

    def test_rich_options_cannot_override_static_workload_or_c0(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, _, prepared = self.fixture(Path(temp))
            plan_path = prepared / "session-plan.json"
            _, loaded = load_plan(plan_path)
            item, _, windows = loaded[0]
            options = source_options_by_window(item, plan_path, windows)
            with self.assertRaises(ValueError):
                v2_recipes.validate_options({"recipe": "c0", **options[windows[0]["id"]]}, {cue["id"] for cue in windows[0]["context"]})
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["workloads"][0].update(options[windows[0]["id"]])
            dump(plan_path, plan)
            with self.assertRaises(ValueError):
                load_plan(plan_path)


if __name__ == "__main__":
    unittest.main()
