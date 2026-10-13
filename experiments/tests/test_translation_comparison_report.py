"""Synthetic accounting checks; no private corpus, model or network access."""

from pathlib import Path
import tempfile
import unittest

from experiments.translation_comparison_report import (
    CANDIDATES, build_metrics, judge_inventory, reconcile, report, runtime_record,
)
from experiments.translation_eval.runner import aggregate, dump, dump_jsonl


class ComparisonReportTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local" / "translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evaluation = self.root / "test-eval"
        self.evaluation.mkdir()
        self.aliases = {chr(65 + i): candidate for i, candidate in enumerate(sorted(CANDIDATES))}
        dump(self.root / "aliases.json", self.aliases)
        self.rows = []
        for alias in self.aliases:
            for window, work, category, score, status in (
                ("s1", "series-a", "anime_series", 4, "scored"),
                ("s2", "series-a", "anime_series", None, "review_failed"),
                ("s3", "series-b", "anime_series", 0, "delivery_zero"),
                ("m1", "movie-a", "movie", 2, "scored"),
            ):
                self.rows.append({"candidate_alias": alias, "window_id": window,
                    "work": work, "category": category, "scored_ids": [window + "-1"],
                    "semantic": score, "naturalness": 2 if status == "scored" else None,
                    "status": status, "errors": [], "structural_status": "valid", "missing_ids": [],
                    "reviewed": status == "scored", "initial_disagreement": False,
                    "generation_seconds": None if window == "s2" else 2.0,
                    "auxiliary_seconds": 0.0, "translation_attempts": [{}]})
        self.save_evaluation()

    def save_evaluation(self) -> None:
        dump_jsonl(self.evaluation / "expected.jsonl", [{key: row[key] for key in
            ("candidate_alias", "window_id", "work", "category", "scored_ids")} for row in self.rows])
        dump_jsonl(self.evaluation / "final.jsonl", self.rows)
        dump(self.evaluation / "summary.json", {**aggregate(self.rows), "profile": "sol-high-auto-v1",
            "lane": "V2-native-adapted", "split": "test"})

    def test_complete_denominator_equal_work_bounds_and_unknown_cost(self) -> None:
        metrics = build_metrics(self.evaluation, self.root, self.root / "aliases.json")
        self.assertEqual(metrics["denominators"]["windows_per_candidate"], 4)
        self.assertEqual(metrics["denominators"]["scored_ids_per_candidate"], 4)
        self.assertEqual(len(metrics["formal_runtime_records"]), 7)
        candidate = metrics["quality"]["candidates"]["A"]
        # series-a bounds [2, 4], series-b [0, 0]; equal-work bounds [1, 2].
        self.assertEqual(candidate["categories"]["anime_series"]["semantic_lower"], 1)
        self.assertEqual(candidate["categories"]["anime_series"]["semantic_upper"], 2)
        self.assertEqual(candidate["generation_timing_unknown_windows"], 1)
        self.assertIsNone(metrics["formal_judge"]["billing_cost"])
        self.assertIsNone(metrics["development_history"]["known_runtime_seconds"])
        text = report(metrics)
        for name in CANDIDATES:
            self.assertIn(name, text)
        self.assertIn("不自动宣布优胜者", text)
        self.assertEqual(metrics, build_metrics(self.evaluation, self.root, self.root / "aliases.json"))

    def test_rejects_missing_final_duplicate_and_stale_summary(self) -> None:
        dump_jsonl(self.evaluation / "final.jsonl", self.rows[:-1])
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            reconcile(self.evaluation)
        dump_jsonl(self.evaluation / "final.jsonl", self.rows + self.rows[:1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            reconcile(self.evaluation)
        self.rows[0]["semantic"] = 3
        dump_jsonl(self.evaluation / "final.jsonl", self.rows)
        with self.assertRaisesRegex(ValueError, "summary mismatch"):
            reconcile(self.evaluation)

    def test_judge_attempts_preferred_to_overlapping_summaries(self) -> None:
        for number, elapsed, status in ((1, 5.0, "judge_failed"), (2, 7.0, "succeeded")):
            directory = self.evaluation / "subagent-execution" / "primary" / "A" / "s1" / f"attempt-{number}"
            directory.mkdir(parents=True)
            dump(directory / "invocation.json", {"elapsed_seconds": elapsed, "agent_id": str(number)})
            dump(directory / "validation.json", {"status": status})
        dump(self.evaluation / "judge-execution-summary.json", {"total_attempt_seconds": 12, "total_jobs": 1})
        dump(self.evaluation / "execution-summary.json", {"total_attempt_wall_seconds": 12, "attempt_count": 2})
        judge = judge_inventory(self.evaluation)
        self.assertEqual(judge["all_known_attempt_seconds"], 12)
        self.assertEqual(judge["attempt_count"], 2)
        self.assertEqual(judge["known_failed_attempts"], 1)
        self.assertEqual(len(judge["execution_summaries"]), 1)

    def test_mapping_cost_does_not_recount_native_generation(self) -> None:
        directory = self.root / "dev-map" / "candidate"
        (directory / "runtime").mkdir(parents=True)
        (directory / "translation").mkdir()
        dump(directory / "runtime" / "runtime-final.json", {"cold_load_seconds": 1,
            "total_runtime_seconds": 9, "peak_device_memory_mib": 12000, "translation_exit_code": 1})
        dump(directory / "translation" / "run.json", {"phase": "pure-mapping"})
        dump_jsonl(directory / "translation" / "ledger.jsonl", [{"status": "mapping_unjudgeable",
            "generation_seconds": 100, "auxiliary_seconds": 3, "attempts": [{}, {}]}])
        row = runtime_record(directory, self.root)
        self.assertEqual(row["phase_seconds_measured"], 3)
        self.assertEqual(row["attempts_measured"], 2)
        self.assertEqual(row["retries_measured"], 1)
        metrics = build_metrics(self.evaluation, self.root, self.root / "aliases.json")
        self.assertEqual(metrics["development_history"]["known_runtime_seconds"], 9)
        self.assertEqual(metrics["development_history"]["runtime_records"][0]["ledger_status_counts"],
            {"mapping_unjudgeable": 1})

    def test_prepared_but_never_dispatched_is_not_a_call_or_timing(self) -> None:
        execution = self.evaluation / "subagent-execution" / "primary" / "A"
        for window in ("s1", "s2"):
            directory = execution / window / "attempt-1"
            directory.mkdir(parents=True)
            dump(directory / "invocation.json", {"agent_id": None,
                "dispatch_status": "interrupted_before_spawn", "elapsed_seconds": 0})
        # A coordinator total must not turn undispatched preparations into calls.
        dump(self.evaluation / "execution-summary.json", {"attempt_count": 2, "total_attempt_seconds": 0})
        prepared_only = judge_inventory(self.evaluation)
        self.assertEqual(prepared_only["attempt_count"], 0)
        self.assertEqual(prepared_only["known_failed_attempts"], 0)
        self.assertIsNone(prepared_only["all_known_attempt_seconds"])
        self.assertEqual(prepared_only["prepared_not_dispatched_count"], 2)
        self.assertTrue(all(item["elapsed_seconds"] is None for item in prepared_only["prepared_not_dispatched"]))
        directory = execution / "s3" / "attempt-1"
        directory.mkdir(parents=True)
        dump(directory / "invocation.json", {"agent_id": "actual-worker",
            "dispatch_status": "completed", "elapsed_seconds": 7})
        dump(directory / "validation.json", {"status": "succeeded"})
        mixed = judge_inventory(self.evaluation)
        self.assertEqual(mixed["attempt_count"], 1)
        self.assertEqual(mixed["all_known_attempt_seconds"], 7)
        self.assertEqual(mixed["attempt_status_counts"], {"succeeded": 1})
        self.assertEqual(mixed["timing_known_attempts"], 1)
        self.assertEqual(mixed["prepared_not_dispatched_count"], 2)

    def test_manual_failures_are_inventoried_without_recounting_runtime_or_originals(self) -> None:
        candidate = self.aliases["A"]
        for relative in ("manual-dev", "dev-wrapper/translation", "dev-eval/originals/A"):
            directory = self.root / relative
            directory.mkdir(parents=True)
            dump(directory / "run.json", {"phase": "translation", "candidate": candidate})
            dump_jsonl(directory / "ledger.jsonl", [{"status": "translation_failed",
                "generation_seconds": 3, "attempts": [{}, {}]}])
        runtime = self.root / "dev-wrapper/runtime"
        runtime.mkdir()
        dump(runtime / "runtime-final.json", {"total_runtime_seconds": 9})
        metrics = build_metrics(self.evaluation, self.root, self.root / "aliases.json")
        history = metrics["development_history"]
        self.assertEqual(len(history["runtime_records"]), 1)
        self.assertEqual(len(history["manual_stage_records"]), 1)
        self.assertEqual(history["known_runtime_seconds"], 9)
        self.assertEqual(history["known_manual_phase_seconds"], 3)
        manual = history["manual_stage_records"][0]
        self.assertEqual(manual["directory"], "manual-dev")
        self.assertEqual(manual["ledger_status_counts"], {"translation_failed": 1})
        self.assertEqual(manual["attempts_measured"], 2)
        self.assertEqual(manual["retries_measured"], 1)
        self.assertIsNone(manual["cold_load_seconds"])
        self.assertIsNone(manual["total_runtime_seconds"])
        self.assertIn("完整运行墙钟", report(metrics))


if __name__ == "__main__":
    unittest.main()
