"""Explicit F9 output reservations without changing C0 or retry/failure accounting."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .cli import digest
from .test_worker import FakeClient, budget
from .test_v2_common_source import construction, item, source_fixture
from .v2_prepare import main, pack_scene, prepare
from .v2_recipes import completion_request, render_window
from .v2_worker import GUARD_TOKENS, load_plan, run_window


def output_item(**changes):
    return {**item(), "recipe": "base-json", "n_predict": 3072, **changes}


def response(window, **changes):
    return {"content": json.dumps({"translations": {cue: "译文" for cue in window["translate_ids"]}},
                                  ensure_ascii=False),
            "tokens_predicted": 100, "stop_type": "eos", "truncated": False,
            "timings": {"cache_n": 0}, **changes}


class OutputBudgetTests(unittest.TestCase):
    def run_one(self, *, tokens=7, outputs=None, settings=None):
        windows, _ = pack_scene({"id": "scene", "context": [{"id": f"s{i}", "text": f"台詞{i}"} for i in range(135)],
                                "translate_ids": [f"s{i}" for i in range(135)]}, target_size=80)
        window = windows[0]
        client = FakeClient(outputs if outputs is not None else [response(window)], tokens=tokens)
        limits = budget(max_estimated_tokens=100000)
        cache = {"verified": False, "first_response_checked": False}
        result = run_window(client, window, settings or output_item(), 8192, limits, cache)
        return result, client, limits, cache, window

    def test_explicit_budget_frozen_in_plan_and_provenance_without_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            args = source_fixture(Path(temp))
            original, mapping = pack_scene(json.loads(args["scenes"].read_text(encoding="utf-8")), target_size=80)
            prepare(**args, recipe="base-json", target_size=80, n_predict=3072)
            root = args["output"]
            plan, workloads = load_plan(root / "session-plan.json")
            actual = [json.loads(line) for line in (root / "inputs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(actual, original)
            self.assertEqual(workloads[0][0]["n_predict"], 3072)
            self.assertEqual(workloads[0][0]["max_attempts"], 2)
            provenance = json.loads((root / "preparation.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["session_plan_sha256"], digest(root / "session-plan.json"))
            self.assertEqual(provenance["generation_budget"], {
                "protocol": "hy30-main-output-budget-v1", "n_predict": 3072,
                "input_margin_tokens": GUARD_TOKENS, "source_truncation": False,
                "capacity_verification": "native-full-prompt-output-reservation-guard"})
            self.assertEqual(sum(len(window["translate_ids"]) for window in actual), 135)

    def test_default_and_explicit4096_preserve_old_plan_mapping_and_all_native_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            args = source_fixture(Path(temp))
            first = args["output"]
            second = first.with_name("explicit4096")
            prepare(**args, target_size=20)
            prepare(**{**args, "output": second}, target_size=20, n_predict=4096)
            for name in ("inputs.jsonl", "packed-mapping.json", "session-plan.json", "position-audit.json"):
                self.assertEqual((first / name).read_bytes(), (second / name).read_bytes(), name)
            for directory in (first, second):
                provenance = json.loads((directory / "preparation.json").read_text(encoding="utf-8"))
                self.assertNotIn("generation_budget", provenance)
            # Frozen runtime21 canonical construction is also checked by the
            # inherited common-source tests for nine lengths/sizes and defaults.
            for count, size in ((23, 3), (135, 5), (160, 20)):
                payload = construction(count, size)
                for window, request in zip(payload["windows"], payload["requests"], strict=True):
                    self.assertEqual(request, completion_request(item(), [11, 22, 33], window["translate_ids"]))

    def test_c0_output_changes_reject_before_source_access_or_publication(self):
        for value in (1, 3072, 4095, 4097, 8192):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaisesRegex(ValueError, "C0 must retain output4096"):
                    prepare(manifest=root / "absent.json", scenes=root / "absent.jsonl",
                            output=root / "prepared", split="screen-a", recipe_id="C0-invalid", n_predict=value)
                self.assertFalse((root / "prepared").exists())

    def test_invalid_budget_types_reject_before_source_access_or_publication(self):
        for value in (None, False, True, 0, -1, 3072.0, "3072"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    prepare(manifest=root / "absent.json", scenes=root / "absent.jsonl",
                            output=root / "prepared", split="screen-a", recipe_id="F9-invalid",
                            recipe="base-json", n_predict=value)
                self.assertFalse((root / "prepared").exists())

    def test_options_cannot_bypass_explicit_budget_field(self):
        with tempfile.TemporaryDirectory() as temp:
            args = source_fixture(Path(temp))
            with self.assertRaisesRegex(ValueError, "overwrite frozen workload identities"):
                prepare(**args, recipe="base-json", options={"n_predict": 3072})
            self.assertFalse(args["output"].exists())

    def test_main_cli_forwards_typed_budget_and_defaults4096(self):
        command = ["prepare", "--manifest", "source.json", "--scenes", "scenes.jsonl",
                   "--output", "prepared", "--split", "screen-a", "--recipe-id", "F9",
                   "--recipe", "base-json"]
        for suffix, expected in (([], 4096), (["--n-predict", "3072"], 3072)):
            with self.subTest(expected=expected), patch.object(sys, "argv", command + suffix), \
                    patch("experiments.translation_flow.v2_prepare.prepare", return_value={}) as frozen:
                main()
                self.assertEqual(frozen.call_args.kwargs["n_predict"], expected)
        # A real parser call rejects nonintegral spelling before preparation.
        completed = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "experiments.translation_flow.v2_prepare",
                                    *command[1:], "--n-predict", "3072.5"], cwd=Path(__file__).resolve().parents[2],
                                   capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("invalid int value", completed.stderr)

    def test_base_json_changes_only_explicit_output_request_field(self):
        windows, _ = pack_scene({"id": "s", "context": [{"id": "s1", "text": "台詞"}], "translate_ids": ["s1"]})
        source = windows[0]
        self.assertEqual(render_window("c0", source, item()), render_window("base-json", source, output_item()))
        before = completion_request(item(), [11, 22, 33], source["translate_ids"])
        after = completion_request(output_item(), [11, 22, 33], source["translate_ids"])
        self.assertEqual({key for key in before if before[key] != after[key]}, {"n_predict"})

    def test_observed4211_input_fits_new_budget_without_truncating80_target_packet(self):
        row, client, limits, cache, source = self.run_one(tokens=4211)
        self.assertEqual(row["status"], "delivered", row)
        self.assertEqual(len(source["translate_ids"]), 80)
        self.assertEqual(len(source["context"]), 81)
        self.assertEqual(limits.estimated_tokens, 4211 + 3072)
        self.assertEqual(len(client.requests[0]["prompt"]), 4211)
        self.assertEqual(client.requests[0]["n_predict"], 3072)
        self.assertTrue(cache["verified"])
        old, old_client, old_limits, _, _ = self.run_one(tokens=4211, settings=item())
        self.assertEqual(old["status"], "setup_failed")
        self.assertEqual(old_client.requests, [])
        self.assertEqual(old_limits.translation_calls, 0)

    def test_exact_native_guard_boundary_preserves_full_source_and_counts_failed_tokenization(self):
        for tokens, expected in ((5056, "delivered"), (5057, "setup_failed")):
            with self.subTest(tokens=tokens):
                row, client, limits, _, source = self.run_one(tokens=tokens)
                self.assertEqual(row["status"], expected, row)
                self.assertEqual(row["attempts"][0]["input_tokens"], tokens)
                self.assertIn("tokenize_seconds", row["attempts"][0])
                self.assertEqual(len(source["context"]), 81)
                if expected == "setup_failed":
                    self.assertEqual(client.requests, [])
                    self.assertEqual(limits.translation_calls, 0)
                    self.assertIn("context_budget", row["reason"])
                else:
                    self.assertEqual(limits.estimated_tokens, tokens + 3072)

    def test_limit_or_truncation_retains_both_identical_attempts_and_full_reservations(self):
        for changes in ({"stop_type": "limit"}, {"truncated": True}, {"stopped_limit": True}):
            with self.subTest(changes=changes):
                dummy, _ = pack_scene({"id": "scene", "context": [{"id": f"s{i}", "text": f"台詞{i}"} for i in range(135)],
                                       "translate_ids": [f"s{i}" for i in range(135)]}, target_size=80)
                outputs = [response(dummy[0], tokens_predicted=3072, **changes) for _ in range(2)]
                row, client, limits, _, source = self.run_one(outputs=outputs)
                self.assertEqual(row["status"], "translation_failed", row)
                self.assertEqual(row["translations"], {})
                self.assertEqual(len(row["attempts"]), 2)
                self.assertEqual(limits.translation_calls, 2)
                self.assertEqual(limits.estimated_tokens, 2 * (7 + 3072))
                self.assertEqual(client.requests[0], client.requests[1])
                self.assertEqual(sum(attempt["response"]["tokens_predicted"] for attempt in row["attempts"]), 6144)
                self.assertTrue(all(attempt["request"]["n_predict"] == 3072 for attempt in row["attempts"]))
                self.assertEqual(len(source["translate_ids"]), 80)

    def test_common_source_policy_and_output_budget_provenance_coexist_explicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            args = source_fixture(Path(temp))
            prepare(**args, recipe="base-json", target_size=20, common_context_block_size=60, n_predict=3072)
            provenance = json.loads((args["output"] / "preparation.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["source_visibility_policy"]["block_size"], 60)
            self.assertEqual(provenance["generation_budget"]["n_predict"], 3072)
            packed = json.loads((args["output"] / "packed-mapping.json").read_text(encoding="utf-8"))
            self.assertEqual(packed["source_visibility_policy"], provenance["source_visibility_policy"])
            self.assertEqual(len(packed["batches"]), 7)


if __name__ == "__main__":
    unittest.main()
