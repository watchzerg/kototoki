"""Synthetic accounting checks; no model, transport, or real subtitle content."""

from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl
from .costs import audit_budget, metric, summarize


class CostsTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-flow-cost-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def translation(self, attempts: list[dict], status: str = "delivered") -> None:
        target = self.root / "p0/session/control"
        dump(target / "run.json", {"phase": "translation"})
        row = {"window_id": "w", "status": status, "attempts": attempts}
        dump_jsonl(target / "ledger.jsonl", [row] if status != "setup_failed" else [])
        dump(target / "window-w.json", row)

    def attempt(self, dispatched: bool = True, status: str = "accepted", elapsed: int = 5) -> dict:
        return {"completion_dispatched": dispatched, "status": status, "input_tokens": 10,
                "request": {"n_predict": 20}, "elapsed_seconds": elapsed,
                "tokenize_seconds": 1, "completion_seconds": elapsed - 1 if dispatched else None,
                "response": {"tokens_evaluated": 10, "tokens_predicted": 7} if status == "accepted" else None}

    def judge(self, name: str, attempts: list[dict], stdout: list[list[dict]] | None = None) -> Path:
        directory = self.root / f"judge-probe/judge-execution/primary/c1/{name}"
        dump(directory / "job.json", {"status": "succeeded", "attempts": attempts})
        for number, events in enumerate(stdout or [], 1):
            dump_jsonl(directory / f"attempt-{number}/stdout.jsonl", events)
        return directory

    def test_failures_retries_and_probe_usage_count_once(self) -> None:
        self.translation([self.attempt(status="failed", elapsed=4), self.attempt(elapsed=6)])
        dump(self.root / "p0/session/worker-completion.json", {
            "budget": {"translation_calls": 2, "estimated_tokens": 60, "wall_seconds": 15}})
        attempts = [{"attempt": 1, "status": "judge_failed", "elapsed_seconds": 2},
                    {"attempt": 2, "status": "succeeded", "elapsed_seconds": 3,
                     "usage_events": [{"input_tokens": 99}]}]
        self.judge("probe", attempts, [[], [
            {"type": "agent_message", "text": "PRIVATE TEXT MUST NOT LEAK"},
            {"type": "progress", "usage": {"input_tokens": 12, "output_tokens": 2}},
            {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 4,
                                                    "cached_input_tokens": 3}}]])
        result = summarize(self.root)
        trans, judge = result["translation"], result["judge"]
        self.assertEqual(trans["completion_calls_accounted"], 2)
        self.assertEqual(trans["estimated_tokens_accounted"], 60)
        self.assertEqual(trans["retries"], 1)
        self.assertEqual(trans["elapsed_seconds"]["measured_sum"], 10)
        self.assertEqual(trans["generation_seconds"]["measured_sum"], 8)
        self.assertEqual(trans["tokenization_seconds"]["measured_sum"], 2)
        self.assertEqual(trans["retry_elapsed_seconds"]["measured_sum"], 6)
        self.assertEqual(trans["actual_server_output_tokens"]["measured_sum"], 7)
        self.assertEqual(trans["actual_server_output_tokens"]["unknown_records"], 1)
        self.assertEqual(judge["attempts"], 2)
        self.assertEqual(judge["retries"], 1)
        self.assertEqual(judge["usage"]["input_tokens"]["measured_sum"], 12)
        self.assertEqual(judge["usage"]["input_tokens"]["unknown_records"], 1)
        self.assertEqual(judge["elapsed_seconds"]["measured_sum"], 5)
        self.assertEqual(result["worker_wall_seconds_sum"]["measured_sum"], 15)
        self.assertNotIn("PRIVATE TEXT", str(result))
        self.assertIsNone(result["billed_cost"])
        # Archived projection/runner copies never add calls a second time.
        dump(self.root / "originals/control/run.json", {"phase": "translation"})
        dump_jsonl(self.root / "originals/control/ledger.jsonl", [{"window_id": "w", "attempts": [self.attempt()]}])
        self.assertEqual(summarize(self.root)["translation"]["completion_calls_accounted"], 2)

    def test_tokenize_only_attempt_is_not_a_translation_call(self) -> None:
        self.translation([self.attempt(False, "failed", 1)], "setup_failed")
        result = summarize(self.root)
        self.assertEqual(result["translation"]["tokenization_attempts"], 1)
        self.assertEqual(result["translation"]["completion_calls_accounted"], 0)
        self.assertEqual(result["translation"]["estimated_tokens_accounted"], 0)

    def test_snapshot_counter_preserves_untraced_calls_and_missing_cost(self) -> None:
        dump(self.root / "worker-completion.json", {"budget": {"translation_calls": 3, "estimated_tokens": 100}})
        self.judge("missing", [{"attempt": 1, "status": "interrupted"}])
        result = summarize(self.root)
        self.assertEqual(result["translation"]["completion_calls_accounted"], 3)
        self.assertEqual(result["translation"]["estimated_tokens_accounted"], 100)
        self.assertFalse(result["accounting_complete"])
        self.assertIsNone(result["judge"]["elapsed_seconds"]["measured_sum"])
        self.assertIsNone(result["judge"]["usage"]["input_tokens"]["measured_sum"])

    def test_multiple_turn_usage_is_explicitly_unresolved(self) -> None:
        self.judge("multiple", [{"attempt": 1}], [[
            {"type": "turn.completed", "usage": {"input_tokens": 10}},
            {"type": "turn.completed", "usage": {"input_tokens": 20}}]])
        result = summarize(self.root)
        self.assertIsNone(result["judge"]["usage"]["input_tokens"]["measured_sum"])
        self.assertIn("multiple completed turns", str(result["judge"]["usage_reasons"]))

    def test_interrupted_attempt_before_job_ledger_is_not_omitted(self) -> None:
        directory = self.root / "judge-probe/judge-execution/primary/c1/interrupted/attempt-1"
        dump(directory / "attempt.json", {"attempt": 1, "status": "started"})
        result = summarize(self.root)
        self.assertEqual(result["judge"]["attempts"], 1)
        self.assertFalse(result["accounting_complete"])
        self.assertIsNone(result["judge"]["elapsed_seconds"]["measured_sum"])

    def test_missing_attempts_cannot_claim_exact_remaining_budget(self) -> None:
        self.translation([])
        dump(self.root / "judge-probe/judge-execution/primary/c1/x/job.json", {"status": "judge_failed"})
        card = {"budgets": {"max_translation_calls": 5, "max_judge_calls": 6,
                            "max_estimated_tokens": 100, "max_wall_seconds": 30}}
        dump(self.root / "card.json", card)
        result = summarize(self.root, self.root / "card.json")
        self.assertFalse(result["accounting_complete"])
        dimensions = result["budget_audit"]["dimensions"]
        self.assertEqual(dimensions["max_judge_calls"]["remaining_upper_bound"], 6)
        self.assertFalse(dimensions["max_judge_calls"]["remaining_is_exact"])
        self.assertIsNone(dimensions["max_wall_seconds"]["remaining_upper_bound"])

    def test_budget_overruns_wall_and_token_scope(self) -> None:
        card = {"budgets": {"max_translation_calls": 2, "max_judge_calls": 3,
                            "max_estimated_tokens": 40, "max_wall_seconds": 20},
                "started_at_utc": "2026-10-07T00:00:00+00:00", "finished_at_utc": "2026-10-07T00:00:25+00:00"}
        result = audit_budget(card, 4, 3, 60, True)["dimensions"]
        self.assertTrue(result["max_translation_calls"]["exceeded"])
        self.assertEqual(result["max_translation_calls"]["remaining_upper_bound"], 0)
        self.assertEqual(result["max_wall_seconds"]["used_accounted"], 25)
        self.assertTrue(result["max_wall_seconds"]["remaining_is_exact"])
        self.assertFalse(result["max_estimated_tokens"]["remaining_is_exact"])
        card["budgets"]["max_judge_calls"] = True
        with self.assertRaisesRegex(ValueError, "numeric"):
            audit_budget(card, 1, 1, 1, True)

    def test_unknown_metric_never_becomes_measured_zero(self) -> None:
        self.assertIsNone(metric([None])["measured_sum"])
        self.assertEqual(metric([0])["measured_sum"], 0)


if __name__ == "__main__":
    unittest.main()
