import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_four_performance import (
    BASELINE, aggregate, align_window, engineering_report, resource_curve,
    sanitize_window, stress_summary, write_report,
)
from experiments.translation_four_quantization.core import sha256


def put(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def lines(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in data)+"\n", encoding="utf-8")


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.other = "other"
        schedule = [{"id": f"round-{number}-{candidate}", "stage": "performance", "candidate": candidate, "round": number}
                    for number in range(1, 5) for candidate in (BASELINE, self.other)]
        self.freeze = self.root/"freeze.json"
        put(self.freeze, {"candidate_ids": [BASELINE, self.other], "schedule": schedule,
                          "inputs": {"regression": {"window_ids": ["a", "b"], "scored_ids": 7, "sha256": "input"},
                                     "expanded": {"window_ids": ["c"], "scored_ids": 2, "sha256": "expanded"}}})

    def attempt(self, name="attempt", partial=None, contaminated=None, output_change=False):
        directory = self.root/name
        put(directory/"attempt.json", {"freeze": str(self.freeze), "freeze_sha256": sha256(self.freeze), "history": []})
        ledger = []
        for number in range(1, 5):
            for candidate in (BASELINE, self.other):
                task = f"round-{number}-{candidate}"
                artifact = directory/task
                ledger.append({"task_id": task, "candidate": candidate, "stage": "performance", "status": "contaminated" if contaminated == (number, candidate) else "completed", "artifact_dir": str(artifact), "pollution": {"contaminated": contaminated == (number, candidate)}, "session_timing": {"cold_load_seconds": 3, "warmup_seconds": 1, "end_to_end_load_to_terminal_seconds": 30}})
                for split, keys, input_hash in (("regression", ["a", "b"], "input"), ("expanded", ["c"], "expanded")):
                    target = artifact/"session"/"translation"/split/"run-00001"
                    put(target/"run.json", {"input_sha256": input_hash})
                    put(target/"workload-summary.json", {"translation_wall_seconds": number*(10 if candidate == BASELINE else 20), "terminal_artifacts_observed_at_utc": "2026-01-01T00:00:10Z"})
                    for index, key in enumerate(keys):
                        if partial == (number, candidate) and key == "b":
                            continue
                        put(target/f"window-{key}.json", {"window_id": key, "status": "delivered", "elapsed_seconds": index+1,
                                                          "started_at_utc": "2026-01-01T00:00:00Z", "finished_at_utc": "2026-01-01T00:00:01Z", "translations": {"x": "PRIVATE" if not output_change or number != 4 else "DIFFERENT"},
                                                          "attempts": [{"input_tokens": 10, "elapsed_seconds": .8, "response": {"tokens_predicted": 3, "timings": {"prompt_ms": 100, "predicted_ms": 200}}}]})
        lines(directory/"schedule-ledger.jsonl", ledger)
        return directory

    def test_unequal_denominators_and_four_round_median(self):
        report = aggregate(self.freeze, [self.attempt()])
        regression = report["comparisons"]["regression"]
        item = regression[self.other]
        self.assertEqual(item["comparative_median_seconds"], 50)
        self.assertEqual(item["relative_to_baseline"], {"ratio": 2, "delta_seconds": 25, "delta_percent": 100})
        self.assertEqual(item["expected_windows_per_round"], 2)
        self.assertEqual(item["scored_ids_per_round"], 7)
        self.assertEqual(report["comparisons"]["expanded"][self.other]["expected_windows_per_round"], 1)
        self.assertEqual(item["all_request_latency_seconds"]["count"], 8)
        self.assertEqual(len(item["paired_window_latency"]), 8)
        self.assertEqual(item["determinism"]["identical"], 2)

    def test_partial_is_not_full_wall_or_faster_evidence(self):
        report = aggregate(self.freeze, [self.attempt(partial=(3, self.other))])
        item = report["comparisons"]["regression"][self.other]
        self.assertFalse(item["comparative_speed_eligible"])
        self.assertIsNone(item["relative_to_baseline"])
        self.assertIsNone(item["comparative_median_seconds"])
        run = next(run for run in report["runs"] if run["candidate"] == self.other and run["round"] == 3)
        work = run["workloads"]["regression"][0]
        self.assertEqual((work["success"], work["failed"], work["not_run"]), (1, 0, 1))
        self.assertIsNone(work["full_set_wall_seconds"])

    def test_contaminated_round_retained_and_first_quality_not_replaced(self):
        first = self.attempt("first", contaminated=(1, self.other))
        second = self.attempt("retry", output_change=True)
        report = aggregate(self.freeze, [first, second, first])
        self.assertEqual(len(report["runs"]), 16)
        item = report["comparisons"]["regression"][self.other]
        self.assertTrue(item["comparative_speed_eligible"])
        self.assertIn("first", item["first_quality_artifacts"]["a"]["artifact"])
        self.assertTrue(any(run.get("contaminated") for run in report["runs"]))

    def test_determinism_and_privacy_safe_exports(self):
        report = aggregate(self.freeze, [self.attempt(output_change=True)])
        item = report["comparisons"]["regression"][self.other]
        self.assertEqual(item["determinism"]["different_ids"], ["a", "b"])
        self.assertEqual(item["determinism"]["identical"], 0)
        output = self.root/"out"
        write_report(report, output)
        for path in output.iterdir():
            self.assertNotIn("PRIVATE", path.read_text(encoding="utf-8-sig"))
            self.assertNotIn("DIFFERENT", path.read_text(encoding="utf-8-sig"))
        self.assertTrue((output/"window-alignment.csv").exists())
        with self.assertRaises(FileExistsError):
            write_report(report, output)

    def test_utc_alignment_does_not_borrow_stale_or_outside_sample(self):
        curve = resource_curve([
            {"utc": "2026-01-01T00:00:00.5Z", "gpu": {"utc": "2026-01-01T00:00:00.25Z", "age_seconds": .25, "memory_used_mib": 4}, "memory": {"shared_gpu_bytes": 10}},
            {"utc": "2026-01-01T00:00:01.5Z", "gpu": {"utc": "2026-01-01T00:00:00.5Z", "age_seconds": 1, "memory_used_mib": 99}, "memory": {"shared_gpu_bytes": 99}},
            {"utc": "2026-01-01T00:00:02Z", "gpu": {"utc": "2026-01-01T00:00:02Z", "age_seconds": 0, "memory_used_mib": 300}},
        ])
        aligned = align_window({"started_at_utc": "2026-01-01T08:00:00+08:00", "finished_at_utc": "2026-01-01T08:00:01+08:00"}, curve)
        self.assertEqual(aligned["fields"]["memory_used_mib"]["maximum"], 4)
        self.assertEqual(aligned["fields"]["shared_gpu_bytes"]["maximum"], 10)
        self.assertEqual(aligned["gpu_sample_count"], 1)
        missing = align_window({"started_at_utc": "2026-01-01T00:00:03Z", "finished_at_utc": "2026-01-01T00:00:04Z"}, curve)
        self.assertIsNone(missing["fields"]["memory_used_mib"]["maximum"])

    def test_stress_actual_requests_and_cutoff(self):
        rows = [{"window_id": "same", "status": "delivered", "started_at_utc": f"2026-01-01T00:{minute:02d}:00Z", "finished_at_utc": f"2026-01-01T00:{minute:02d}:01Z", "elapsed_seconds": latency, "input_tokens": 50, "output_tokens": 10, "attempt_count": 2} for minute, latency in ((0, 1), (10, 1), (20, 2), (30, 2))]
        work = [{"windows": [row]} for row in rows]
        short = stress_summary(work, [{"label": "repeated-source-block", "status": "phase_finished", "elapsed_seconds": 1799.9, "requested_seconds": 1800}], [])
        self.assertFalse(short["at_least_1800_seconds"])
        full = stress_summary(work, [{"label": "repeated-source-block", "status": "phase_finished", "elapsed_seconds": 1800.1, "requested_seconds": 1800}], [])
        self.assertTrue(full["at_least_1800_seconds"])
        self.assertEqual(full["actual_window_requests"], 4)
        self.assertEqual(full["actual_engine_request_attempts"], 8)
        self.assertEqual(full["second_half_first_half_median_latency_ratio"], 2)
        self.assertEqual(full["quality_samples"], 0)
        work.append({"windows": [{**rows[0], "started_at_utc": None, "finished_at_utc": None}]})
        missing = stress_summary(work, [], [])
        self.assertEqual(missing["windows_missing_utc"], 1)
        self.assertEqual(missing["actual_window_requests"], 5)

    def test_immutable_hash_change_rejected(self):
        attempt = self.attempt()
        ledger = [json.loads(line) for line in (attempt/"schedule-ledger.jsonl").read_text().splitlines()]
        ledger[0]["artifact_sha256"] = {str(self.freeze): "bad"}
        lines(attempt/"schedule-ledger.jsonl", ledger)
        with self.assertRaisesRegex(ValueError, "Immutable artifact changed"):
            aggregate(self.freeze, [attempt])

    def test_failure_and_unattempted_tail_are_distinct_and_oom_is_explicit(self):
        attempt = self.attempt(partial=(1, self.other))
        target = attempt/f"round-1-{self.other}"/"session"/"translation"/"regression"/"run-00001"/"window-a.json"
        row = json.loads(target.read_text())
        row.update(status="translation_failed", elapsed_seconds=10000, error="request timed out")
        put(target, row)
        report = aggregate(self.freeze, [attempt])
        run = next(run for run in report["runs"] if run["round"] == 1 and run["candidate"] == self.other)
        work = run["workloads"]["regression"][0]
        self.assertEqual((work["success"], work["failed"], work["not_run"]), (0, 1, 1))
        self.assertFalse(run["oom"])
        self.assertIsNone(report["comparisons"]["regression"][self.other]["relative_to_baseline"])
        row["error"] = "CUDA_ERROR_OUT_OF_MEMORY"
        put(target, row)
        report = aggregate(self.freeze, [attempt])
        self.assertTrue(next(run for run in report["runs"] if run["round"] == 1 and run["candidate"] == self.other)["oom"])

    def test_mismatched_freeze_preserved_but_excluded_from_formal_comparison(self):
        attempt = self.attempt()
        old_freeze = self.root/"engineering.json"
        old = json.loads(self.freeze.read_text())
        old["phase"] = "engineering"
        put(old_freeze, old)
        put(attempt/"attempt.json", {"freeze": str(old_freeze), "freeze_sha256": sha256(old_freeze), "history": []})
        report = aggregate(self.freeze, [attempt])
        self.assertEqual(len(report["runs"]), 8)
        self.assertFalse(report["comparisons"]["regression"][self.other]["comparative_speed_eligible"])
        self.assertTrue(all(task["status"] == "not_run" for task in report["schedule_coverage"]))

    def test_timeout_response_fields_remain_unknown_with_measured_request_cost(self):
        attempt = self.attempt()
        target = attempt/f"round-1-{self.other}"/"session"/"translation"/"regression"/"run-00001"/"window-a.json"
        row = json.loads(target.read_text())
        row.update(status="translation_failed", translations={}, attempts=[{
            "elapsed_seconds": .2, "input_tokens": 10,
            "error": "Synthetic HTTP timeout after completion submitted",
        }])
        put(target, row)
        report = aggregate(self.freeze, [attempt])
        run = next(run for run in report["runs"] if run["round"] == 1 and run["candidate"] == self.other)
        workload = run["workloads"]["regression"][0]
        window = workload["windows"][0]
        self.assertEqual(window["request_seconds"], .2)
        self.assertEqual(window["input_tokens"], 10)
        for key in ("output_tokens", "prompt_eval_seconds", "decode_seconds"):
            self.assertIsNone(window[key])
            self.assertEqual(window["measurement_coverage"][key]["known_attempts"], 0)
            self.assertEqual(window["measurement_coverage"][key]["missing_attempts"], 1)
            self.assertIsNone(workload["totals"][key])
            self.assertEqual(workload["measurement_coverage"][key]["known_attempts"], 1)
            self.assertEqual(workload["measurement_coverage"][key]["missing_attempts"], 1)
        self.assertEqual(workload["measurement_coverage"]["output_tokens"]["observed_total"], 3)
        self.assertIsNone(workload["output_tokens_per_second"])

    def test_mixed_attempts_preserve_partial_costs_and_real_zero(self):
        raw = {"window_id": "mixed", "status": "translation_failed", "attempts": [
            {"elapsed_seconds": .2, "input_tokens": 10},
            {"response": {"tokens_predicted": 0, "timings": {"prompt_ms": 0, "predicted_ms": 0}}},
        ]}
        row = sanitize_window(raw, self.root/"mixed.json", [])
        for key, observed in (("request_seconds", .2), ("input_tokens", 10),
                              ("output_tokens", 0), ("prompt_eval_seconds", 0), ("decode_seconds", 0)):
            self.assertIsNone(row[key])
            self.assertEqual(row["measurement_coverage"][key]["observed_total"], observed)
            self.assertEqual(row["measurement_coverage"][key]["missing_attempts"], 1)
        self.assertEqual(row["retry_count"], 1)
        self.assertIsNone(row["retry_seconds"])
        zero = sanitize_window({**raw, "attempts": [raw["attempts"][1]]}, self.root/"zero.json", [])
        for key in ("output_tokens", "prompt_eval_seconds", "decode_seconds"):
            self.assertEqual(zero[key], 0)
            self.assertEqual(zero["measurement_coverage"][key]["missing_attempts"], 0)
        no_attempts = sanitize_window({**raw, "attempts": []}, self.root/"none.json", [])
        self.assertIsNone(no_attempts["output_tokens"])
        self.assertIsNone(no_attempts["request_seconds"])

    def test_stress_missing_tokens_do_not_enter_length_distribution(self):
        rows = [{"window_id": "same", "status": "delivered", "started_at_utc": f"2026-01-01T00:{minute:02d}:00Z", "finished_at_utc": f"2026-01-01T00:{minute:02d}:01Z", "elapsed_seconds": 1, "input_tokens": None, "output_tokens": None, "attempt_count": 1} for minute in (0, 30)]
        result = stress_summary([{"windows": rows}], [], [])
        self.assertEqual(result["periods"]["front"]["input_tokens"]["count"], 0)
        self.assertEqual(result["periods"]["front"]["input_tokens_missing_windows"], 1)
        self.assertIsNone(result["periods"]["front"]["output_tokens"]["p50"])

    def test_report_separates_duration_threshold_and_stability_verdict(self):
        rendered = engineering_report({"comparisons": {}, "limitations_zh": [], "runs": [{
            "task_id": "synthetic-failed-stress", "status": "failed", "oom": False,
            "stress": {"at_least_1800_seconds": True, "stability_passed": False},
        }]})
        self.assertIn("达到 30 分钟 | 稳定性通过", rendered)
        self.assertIn("| True | False |", rendered)
        self.assertNotIn("30 分钟完成", rendered)


if __name__ == "__main__":
    unittest.main()
