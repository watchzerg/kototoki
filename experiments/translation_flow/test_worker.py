"""Offline source-firewall, request, budget and interruption tests."""

import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_demo.run import run_window as legacy_window
from .recipes import completion_request, render_window, sampling_settings
from .worker import Budget, CANDIDATE, SCHEMA, execute_plan, load_plan, run_window, sha256


def window(key="a"):
    return {"id": key, "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": key + "-1", "text": "明日は行きません。"}],
            "translate_ids": [key + "-1"]}


def response(key="a", text="明天不去。"):
    return {"content": json.dumps({"translations": {key + "-1": text}}, ensure_ascii=False),
            "tokens_predicted": 8, "tokens_evaluated": 7}


class FakeClient:
    def __init__(self, outputs=None, tokens=7):
        self.outputs = outputs or [response()]
        self.tokens = tokens
        self.requests = []
        self.last_exchange = None
        self.timeout = 300

    def tokenize(self, prompt):
        self.last_exchange = "fake-tokenize"
        return list(range(self.tokens))

    def request(self, endpoint):
        return {"model_alias": CANDIDATE, "default_generation_settings": {"top_k": 40, "min_p": .05}}

    def complete(self, request):
        self.requests.append(copy.deepcopy(request))
        self.last_exchange = "fake-completion"
        result = self.outputs.pop(0)
        if isinstance(result, Exception):
            raise result
        result = copy.deepcopy(result)
        result.setdefault("generation_settings", {k: v for k, v in request.items() if k != "prompt"})
        return result


def budget(**kwargs):
    return Budget({"max_translation_calls": 10, "max_judge_calls": 20,
                   "max_estimated_tokens": 20000, "max_wall_seconds": 60, **kwargs})


def recipe(name="single-source", **kwargs):
    return {"label": name, "recipe": name, "sampling": "b0", **kwargs}


class WorkerTests(unittest.TestCase):
    def test_b0_matches_legacy_prompt_and_entire_completion_request(self):
        old_client, new_client = FakeClient(), FakeClient()
        old = legacy_window(old_client, window(), "hy-mt2-30b",
                            {"n_predict": 1024, "context_size": 4096, "max_attempts": 2,
                             "stop": ["<eos:6124c78e>"]})
        new = run_window(new_client, window(), recipe("b0"), 4096, budget())
        self.assertEqual(old["translations"], new["translations"])
        self.assertEqual(old_client.requests, new_client.requests)
        self.assertNotIn("top_k", new_client.requests[0])

    def test_official_profile_disables_additional_truncation_and_seed_is_explicit(self):
        profile = sampling_settings("official", 42)
        self.assertEqual(profile["temperature"], .7)
        self.assertEqual(profile["top_k"], 0)
        self.assertEqual(profile["top_p"], 1)
        self.assertEqual(profile["min_p"], 0)
        self.assertEqual(profile["repeat_penalty"], 1)
        self.assertEqual(profile["samplers"], ["temperature"])
        self.assertEqual(profile["seed"], 42)
        self.assertEqual(sampling_settings("official-temperature0")["temperature"], 0)
        with self.assertRaisesRegex(ValueError, "B0"):
            completion_request("b0", "official", window(), [1])

    def test_single_source_prompt_has_only_one_source_occurrence_and_fixed_targets(self):
        prompt = render_window("single-source", window())
        self.assertEqual(prompt.count("明日は行きません。"), 1)
        request = completion_request("single-source", "b0", window(), [1])
        self.assertIn("grammar", request)
        self.assertNotIn("grammar", completion_request("single-source-unconstrained", "b0", window(), [1]))

    def test_parse_failure_retries_identical_request_and_counts_both_reservations(self):
        client = FakeClient([{"content": '{"translations":{"wrong":"错"}}'}, response()])
        limits = budget()
        row = run_window(client, window(), recipe(), 4096, limits)
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(client.requests[0], client.requests[1])
        self.assertEqual(limits.translation_calls, 2)
        self.assertEqual(limits.estimated_tokens, 2 * (7 + 1024))
        self.assertEqual(len(row["attempts"]), 2)

    def test_context_budget_blocks_completion_and_does_not_fill_source(self):
        client = FakeClient(tokens=3100)
        row = run_window(client, window(), recipe(), 4096, budget())
        self.assertEqual(row["status"], "setup_failed")
        self.assertEqual(row["translations"], {})
        self.assertEqual(row["error_kind"], "budget")
        self.assertEqual(client.requests, [])
        self.assertEqual(len(row["attempts"]), 1)

    def test_tokens_calls_and_wall_limits_stop_before_dispatch(self):
        for limits in (budget(max_estimated_tokens=1030), budget(max_translation_calls=1)):
            if limits.limits["max_translation_calls"] == 1:
                limits.reserve(1, 1)
            client = FakeClient()
            row = run_window(client, window(), recipe(), 4096, limits)
            self.assertEqual(row["status"], "not_run")
            self.assertEqual(client.requests, [])
        limits = budget()
        limits.started -= 61
        row = run_window(FakeClient(), window(), recipe(), 4096, limits)
        self.assertEqual(row["stop_reason"], "max_wall_seconds")

    def test_effective_parameter_mismatch_is_failure_and_absent_fields_are_not_claimed_verified(self):
        wrong = response()
        wrong["generation_settings"] = {"temperature": .2}
        row = run_window(FakeClient([wrong]), window(), recipe(max_attempts=1), 4096, budget())
        self.assertEqual(row["status"], "translation_failed")
        self.assertIn("effective temperature", row["reason"])
        missing = response()
        missing["generation_settings"] = {}
        row = run_window(FakeClient([missing]), window(), recipe(), 4096, budget())
        self.assertFalse(row["attempts"][0]["effective_settings"]["verified"])

    def test_oom_stops_after_one_attempt_but_generated_oom_phrase_is_ordinary_text(self):
        client = FakeClient([ValueError("CUDA_ERROR_OUT_OF_MEMORY"), response()])
        row = run_window(client, window(), recipe(), 4096, budget())
        self.assertEqual(row["error_kind"], "oom")
        self.assertEqual(len(client.requests), 1)
        row = run_window(FakeClient([response(text="out of memory")]), window(), recipe(), 4096, budget())
        self.assertEqual(row["status"], "delivered")
        self.assertNotIn("error_kind", row)

    def test_limit_and_duplicate_json_fail_without_source_fallback(self):
        for result in ({**response(), "stopped_limit": True},
                       {"content": '{"translations":{"a-1":"一","a-1":"二"}}'}):
            row = run_window(FakeClient([result]), window(), recipe(max_attempts=1), 4096, budget())
            self.assertEqual(row["status"], "translation_failed")
            self.assertEqual(row["translations"], {})

    def make_plan(self, root, windows=None, workloads=None, **budget_overrides):
        inputs = root / "source.jsonl"
        inputs.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in (windows or [window()])), encoding="utf-8")
        workloads = workloads or [recipe()]
        items = [{**item, "inputs": "source.jsonl", "input_sha256": sha256(inputs)} for item in workloads]
        plan = {"schema": SCHEMA, "stage": "P0", "budgets": budget(**budget_overrides).limits, "workloads": items}
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        args = argparse.Namespace(candidate=CANDIDATE, session_plan=plan_path, output_dir=root / "out",
                                  server_url="http://127.0.0.1:8080", context_size=4096,
                                  engine_manifest=root / "engine.json", asset_manifest=[], stop_on_oom=True)
        return plan, args

    def identity(self, args):
        return {"asset": {"id": CANDIDATE}, "engine": {"model_path": "fake.gguf"},
                "engine_manifest_sha256": "synthetic", "template_sha256": "synthetic"}

    def test_plan_source_firewall_hash_and_mandatory_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bad = {**window(), "reference": "不可输入"}
            _, args = self.make_plan(root, [bad])
            with self.assertRaisesRegex(ValueError, "model-input"):
                load_plan(args.session_plan)
            plan, args = self.make_plan(root)
            plan["budgets"].pop("max_wall_seconds")
            args.session_plan.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "four stage budgets"):
                load_plan(args.session_plan)
            _, args = self.make_plan(root)
            (root / "source.jsonl").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash changed"):
                load_plan(args.session_plan)

    def test_session_interrupt_preserves_actual_failure_and_schedules_all_tail_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, args = self.make_plan(root, [window("a"), window("b")],
                                     [recipe("b0"), recipe("single-source")])
            client = FakeClient([ValueError("CUDA_ERROR_OUT_OF_MEMORY")])
            code = execute_plan(args, lambda *a, **k: client, self.identity)
            self.assertEqual(code, 1)
            ledger = [json.loads(line) for line in (args.output_dir / "b0/ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["window_id"] for row in ledger], ["a"])
            self.assertEqual(ledger[0]["status"], "translation_failed")
            tail = [json.loads(line) for line in (args.output_dir / "b0/schedule.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(tail, [{"window_id": "b", "status": "not_run", "reason": "oom"}])
            future = [json.loads(line) for line in (args.output_dir / "single-source/schedule.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["window_id"] for row in future], ["a", "b"])
            self.assertEqual((args.output_dir / "single-source/results.jsonl").read_text(), "")
            self.assertTrue((args.output_dir / "source/experiments/translation_flow/worker.py").is_file())
            with self.assertRaises(FileExistsError):
                execute_plan(args, lambda *a, **k: client, self.identity)

    def test_exhausted_session_budget_is_schedule_not_delivery_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, args = self.make_plan(root, [window("a"), window("b")], max_translation_calls=1)
            client = FakeClient()
            self.assertEqual(execute_plan(args, lambda *a, **k: client, self.identity), 1)
            ledger = (args.output_dir / "single-source/ledger.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(ledger), 1)
            schedule = json.loads((args.output_dir / "single-source/schedule.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(schedule["status"], "not_run")
            self.assertEqual(schedule["window_id"], "b")


if __name__ == "__main__":
    unittest.main()
