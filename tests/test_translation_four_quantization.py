"""Offline failure/resume/denominator tests, no model loads or GPU calls."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_four_quantization.core import (
    CANDIDATES, RECIPE, input_record, inspect_workload, make_schedule,
    is_oom, pollution_evidence, recovery_subset, rotation, sha256, validate_expanded_corpus, write_json)
from experiments.translation_four_quantization.worker import execute_plan, prepare_probe, summarize_workload
from experiments.translation_four_quantization.__main__ import export_quality, read_histories, run


def window(key: str) -> dict:
    return {"id": key, "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": f"{key}-1", "text": "明日は行きません。"}], "translate_ids": [f"{key}-1"]}


def write_inputs(path: Path, keys: list[str]) -> None:
    path.write_text("".join(json.dumps(window(key), ensure_ascii=False) + "\n" for key in keys), encoding="utf-8")


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs.jsonl"
        write_inputs(self.inputs, ["a", "b", "c"])

    def tearDown(self):
        self.temp.cleanup()

    def result(self, directory: Path, key: str, status: str = "delivered", reason: str | None = None):
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat()
        row = {"window_id": key, "status": status, "translations": {f"{key}-1": "明天不去。"} if status == "delivered" else {},
               "started_at_utc": now, "finished_at_utc": now, "elapsed_seconds": .2,
               "attempts": [{"elapsed_seconds": .1}, {"elapsed_seconds": .1}], "reason": reason}
        write_json(directory / f"window-{key}.json", row)

    def test_rotation_each_candidate_each_position_once_and_fixed_preflight_order(self):
        rounds = rotation()
        self.assertEqual(rounds, rotation())
        for position in range(4):
            self.assertEqual({row[position] for row in rounds}, set(CANDIDATES))
        tasks = make_schedule()
        self.assertEqual([row["candidate"] for row in tasks[:4]], list(CANDIDATES))
        self.assertEqual(sum(row["quality_round"] for row in tasks), 4)
        self.assertEqual(len(tasks), 24)

    def test_structured_oom_recognized_but_generated_marker_is_not_failure_evidence(self):
        self.assertTrue(is_oom({"error_kind": "oom", "reason": "HTTPError500"}))
        self.assertFalse(is_oom({"translations": {"a": "out of memory"}, "response": {"content": "out of memory"}}))

    def test_resume_recursively_includes_ancestor_attempts_once(self):
        one, two = self.root / "one", self.root / "two"
        for path in (one, two):
            path.mkdir()
        write_json(one / "attempt.json", {"freeze_sha256": "same"})
        write_json(two / "attempt.json", {"freeze_sha256": "same", "history": [str(one)]})
        (one / "schedule-ledger.jsonl").write_text('{"task_id":"old","status":"completed"}\n')
        (two / "schedule-ledger.jsonl").write_text('{"task_id":"new","status":"completed"}\n')
        rows = read_histories([two, one], "same")
        self.assertEqual([row["task_id"] for row in rows], ["old", "new"])

    def test_source_only_firewall_rejects_reference_and_duplicate_ids(self):
        item = window("a")
        item["reference"] = "偷看答案"
        self.inputs.write_text(json.dumps(item), encoding="utf-8")
        with self.assertRaises(ValueError):
            input_record(self.inputs)
        write_inputs(self.inputs, ["a", "a"])
        with self.assertRaises(ValueError):
            input_record(self.inputs)

    def test_staged_unreviewed_corpus_cannot_become_formal_inference(self):
        corpus = self.root / "corpus.json"
        write_json(corpus, {"state": "staged_unreviewed_not_for_inference", "inference_allowed": False})
        with self.assertRaisesRegex(ValueError, "not finalized"):
            validate_expanded_corpus(corpus, input_record(self.inputs))

    def test_capacity_blocked_selected_performance_returns_nonzero(self):
        candidate = CANDIDATES[0]
        frozen = self.root / "freeze.json"
        write_json(frozen, {"schedule": [{"id": f"round-1-{candidate}", "stage": "performance",
                                         "candidate": candidate, "quality_round": True}]})
        args = argparse.Namespace(freeze=frozen, resume_from=[], output_dir=self.root / "blocked",
               diagnostic_oom_retry=False, candidate=[candidate], stage="performance", port=8080,
               smoke_evidence=None, dev_evidence=None)
        with patch("experiments.translation_four_quantization.__main__.verify_freeze"), patch(
                "experiments.translation_four_quantization.__main__.read_histories", return_value=[
                    {"task_id": f"preflight-{candidate}", "stage": "preflight", "candidate": candidate,
                     "status": "failed", "capacity_failed": True}]):
            self.assertEqual(run(args), 1)
        completion = json.loads((args.output_dir / "attempt-completion.json").read_text())
        self.assertEqual(completion["blocked_sessions"], 1)

    def test_missing_tail_remains_not_run_and_incomplete_timing_not_full_speed(self):
        directory = self.root / "attempt"
        self.result(directory, "a")
        self.result(directory, "b", "translation_failed", "CUDA out of memory")
        audit = inspect_workload(directory, ["a", "b", "c"])
        self.assertEqual((audit["expected"], audit["success"], audit["failed"], audit["not_run"]), (3, 1, 1, 1))
        summary = summarize_workload(directory, self.inputs, .5)
        self.assertIsNone(summary["full_set_wall_seconds"])
        self.assertTrue(summary["oom"])
        self.assertEqual(summary["retry_count"], 2)

    def test_resume_keeps_first_failure_and_only_absent_windows_without_mutating_history(self):
        first, second = self.root / "first", self.root / "second"
        self.result(first, "a", "translation_failed", "format failure")
        self.result(second, "a")
        self.result(second, "b")
        before = sha256(first / "window-a.json")
        subset = self.root / "pending.jsonl"
        record = recovery_subset(self.inputs, [first, second], subset)
        self.assertEqual(record["pending_ids"], ["c"])
        self.assertEqual(record["retained"]["a"], str((first / "window-a.json").resolve()))
        self.assertEqual(before, sha256(first / "window-a.json"))
        self.assertEqual(input_record(subset)["window_ids"], ["c"])
        with self.assertRaises(FileExistsError):
            recovery_subset(self.inputs, [first], subset)

    def worker_args(self, workloads):
        plan = self.root / "plan.json"
        write_json(plan, {"recipe": RECIPE, "workloads": workloads})
        return argparse.Namespace(session_plan=plan, output_dir=self.root / "out", context_size=4096)

    def workload(self, label, **values):
        return {"label": label, "inputs": str(self.inputs), "input_sha256": sha256(self.inputs), "quality_sample": False, **values}

    def test_oom_worker_stops_without_inventing_tail_failures_or_running_next_split(self):
        args = self.worker_args([self.workload("regression"), self.workload("expanded")])
        calls = []
        def invoke(_, inputs, output):
            calls.append(output)
            self.result(output, "a", "translation_failed", "CUDA out of memory")
            return 1, .2
        self.assertEqual(execute_plan(args, invoke), 1)
        self.assertEqual(len(calls), 1)
        summary = json.loads((calls[0] / "workload-summary.json").read_text())
        self.assertEqual((summary["failed"], summary["not_run"]), (1, 2))
        events = [json.loads(line) for line in (args.output_dir / "workload-ledger.jsonl").read_text().splitlines()]
        self.assertTrue(any(row.get("label") == "expanded" and row.get("status") == "not_run" for row in events))

    def test_stability_repeats_fixed_block_unique_directories_without_quality_samples(self):
        args = self.worker_args([self.workload("repeated-source-block", repeat_until_seconds=1800)])
        tick = [0]
        paths = []
        def clock():
            return tick[0]
        def invoke(_, inputs, output):
            paths.append(output)
            for key in ["a", "b", "c"]:
                self.result(output, key)
            tick[0] += 1000
            return 0, 1000
        self.assertEqual(execute_plan(args, invoke, clock), 0)
        self.assertEqual(len(paths), 2)
        self.assertNotEqual(paths[0], paths[1])
        for path in paths:
            summary = json.loads((path / "workload-summary.json").read_text())
            self.assertFalse(summary["quality_sample"])

    def test_probe_reserves_1024_output_and_source_firewall(self):
        class Tokenizer:
            def tokenize(self, prompt):
                return list(range(len(prompt)))
        output = self.root / "probe"
        inputs = prepare_probe(Tokenizer(), output)
        record = json.loads((output / "probe.json").read_text())
        self.assertLessEqual(record["input_tokens"] + record["output_reserved"] + record["guard_reserved"], 4096)
        self.assertLess(record["remaining_input_tokens"], 15)
        self.assertFalse(record["quality_sample"])
        self.assertEqual(input_record(inputs)["windows"], 1)

    def test_frozen_input_change_stops_before_inference(self):
        item = self.workload("regression")
        args = self.worker_args([item])
        self.inputs.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            execute_plan(args, lambda *_: self.fail("Must not call model"))

    def test_pollution_threshold_is_predeclared_not_an_oom_assertion(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        (runtime / "resource-samples.jsonl").write_text(json.dumps({"phase": "idle_baseline", "gpu": {
            "memory_used_mib": 1100, "memory_free_mib": 15000, "age_seconds": .1}}) + "\n")
        evidence = pollution_evidence(runtime, {"memory_used_mib": 500, "memory_free_mib": 15600})
        self.assertTrue(evidence["contaminated"])
        self.assertEqual(evidence["reasons"], ["preload_median_memory_difference_over_512_mib"])

    def test_quality_export_retains_first_failure_and_explicit_unattempted_denominator(self):
        frozen = self.root / "freeze.json"
        write_json(frozen, {"inputs": {"expanded": {"window_ids": ["a", "b", "c"]}}})
        attempts = []
        candidate = CANDIDATES[0]
        for number in (1, 2):
            attempt = self.root / f"attempt-{number}"
            attempt.mkdir()
            write_json(attempt / "attempt.json", {"freeze_sha256": sha256(frozen)})
            task = attempt / "task"
            directory = task / "session" / "translation" / "expanded" / "run-00001"
            self.result(directory, "a", "translation_failed" if number == 1 else "delivered")
            if number == 2:
                self.result(directory, "b")
            (attempt / "schedule-ledger.jsonl").write_text(json.dumps({"task_id": f"round-1-{candidate}",
                "status": "failed", "artifact_dir": str(task)}) + "\n")
            attempts.append(attempt)
        args = argparse.Namespace(freeze=frozen, attempt=attempts, split="expanded", candidate=candidate,
                                  output_dir=self.root / "export")
        with patch("experiments.translation_four_quantization.__main__.verify_freeze"):
            self.assertEqual(export_quality(args), 0)
        ledger = [json.loads(line) for line in (args.output_dir / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(ledger[0]["status"], "translation_failed")
        schedule = [json.loads(line) for line in (args.output_dir / "schedule.jsonl").read_text().splitlines()]
        self.assertEqual([row["window_id"] for row in schedule], ["b", "c"])
        self.assertTrue(all(row["status"] == "not_run" for row in schedule))
        self.assertEqual(len(ledger), 1)
        self.assertEqual(len(ledger) + len(schedule), 3)


if __name__ == "__main__":
    unittest.main()
