"""Synthetic native-card queue guards and real trial delegation; no GPU/judges."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from . import v2_confirmation as contract
from . import v2_confirmation_dispatch as dispatch
from . import test_v2_confirmation as confirmation_fixtures


class ConfirmationDispatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = confirmation_fixtures.ConfirmationContractTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.native_metadata()
        self.root = self.fixture.root
        self.lock = self.fixture.lock()
        self.unseal = self.fixture.open(self.lock)
        self.pins = {"registered_lock_sha256": self.lock["sha256"],
                     "registered_unseal_sha256": self.unseal["sha256"],
                     "expected_policy_sha256": self.fixture.policy_sha}

    def freeze(self, name="queue", **overrides):
        return dispatch.freeze_dispatch_plan(self.lock, self.unseal, self.root / name,
            self.root / f"{name}-plan.json", **{**self.pins, **overrides})

    def execute(self, plan, runner, **overrides):
        return dispatch.execute_dispatch_plan(plan, trial_runner=runner, **{**self.pins, **overrides})

    def validate(self, receipt):
        return dispatch.validate_dispatch_receipt(receipt, **self.pins)

    def runner(self, card_path, output):
        card = contract._json(card_path)
        output.mkdir()
        start = datetime.now(timezone.utc).isoformat()
        value = {"schema": "hy30-flow-trial-v2", "card_path": str(card_path),
            "card_sha256": contract.pointer(card_path)["sha256"], "card": card,
            "status": "complete", "runtime_exit_code": 0, "expected_scene_ids": ["synthetic-scene"],
            "expected_scenes": 1, "complete_scenes": 1,
            "missing_scene_ids": [], "unexpected_scene_ids": [], "duplicate_scene_ids": [],
            "total_flow_seconds": 12.5, "started_at_utc": start,
            "finished_at_utc": datetime.now(timezone.utc).isoformat()}
        (output / "trial-completion.json").write_text(json.dumps(value), encoding="utf-8")
        return 0

    def read(self, pointer):
        return contract._json(Path(pointer["path"]))

    def changed(self, name, value):
        return contract.pointer(self.fixture.write(name, value))

    def test_freezes_full_order_and_one_authority_and_no_quality_seed_reset(self):
        plan = self.freeze()
        value = dispatch.validate_dispatch_plan(plan, **self.pins)
        self.assertEqual(len(value["jobs"]), 6)
        self.assertEqual([job["seed"] for job in value["jobs"]], list(contract.SEEDS) * 2)
        self.assertEqual([job["candidate_alias"] for job in value["jobs"]],
            ["C0-official-cached"] * 3 + ["F1-b10"] * 3)
        self.assertFalse(value["new_quality_seeds"])
        self.assertFalse(value["formal_ABBA_timing"])
        self.assertEqual(value["confirmation_scope"]["windows_per_group_seed"], 48)
        self.assertTrue(all(job["expected_quality_windows"] == 48 for job in value["jobs"]))

    def test_complete_queue_records_native_receipts_and_actual_cost_separately(self):
        runner = Mock(side_effect=self.runner)
        receipt = self.execute(self.freeze(), runner)
        value = self.validate(receipt)
        self.assertEqual(runner.call_count, 6)
        self.assertEqual(value["state"], "complete")
        self.assertEqual(value["known_native_total_flow_seconds_sum"], 75)
        self.assertEqual(value["missing_native_cost_job_ids"], [])
        self.assertFalse(value["native_runtime_freshness_verified"])
        self.assertTrue(value["native_runtime_collector_required"])
        self.assertTrue(all(job["runner_seconds"] >= 0 for job in value["jobs"]))

    def test_separately_registered_pins_required_before_runner(self):
        for key in ("registered_lock_sha256", "registered_unseal_sha256"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "registered custody pins"):
                self.freeze(**{key: "0" * 64})
        plan = self.freeze()
        runner = Mock(side_effect=self.runner)
        with self.assertRaises(ValueError):
            self.execute(plan, runner, registered_lock_sha256="0" * 64)
        runner.assert_not_called()
        self.assertFalse((self.root / "queue").exists())

    def test_changed_whole_queue_or_new_per_job_authority_rejected_before_runner(self):
        original = self.read(self.freeze())
        for key in ("reorder", "omit", "authority", "output", "card"):
            value = deepcopy(original)
            if key == "reorder":
                value["jobs"].reverse()
            elif key == "omit":
                value["jobs"].pop()
            elif key == "authority":
                value["jobs"][0]["lock"] = self.lock
            elif key == "output":
                value["jobs"][0]["output"] = str(self.root / "escaped")
            else:
                value["jobs"][0]["card"] = value["jobs"][-1]["card"]
            runner = Mock(side_effect=self.runner)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.execute(self.changed(f"changed-{key}.json", value), runner)
            runner.assert_not_called()

    def test_stage_role_and_card_byte_guard_precedes_any_native_phase(self):
        plan = self.freeze()
        path = self.fixture.candidates[0]["cards"][0]
        card = contract._json(path)
        card["prepare"]["stage"] = "screening"
        self.fixture.write(path.name, card)
        runner = Mock(side_effect=self.runner)
        with self.assertRaises(ValueError):
            self.execute(plan, runner)
        runner.assert_not_called()
        self.assertFalse((self.root / "queue").exists())

    def test_preexisting_output_and_plan_inside_output_rejected_without_resume(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            dispatch.freeze_dispatch_plan(self.lock, self.unseal, self.root / "same-root",
                self.root / "same-root/plan.json", **self.pins)
        occupied = self.root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("Prior results remain unchanged", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.freeze("occupied")
        plan = self.freeze()
        self.execute(plan, self.runner)
        runner = Mock(side_effect=self.runner)
        with self.assertRaises(FileExistsError):
            self.execute(plan, runner)
        runner.assert_not_called()

    def test_partial_failure_stops_with_original_denominator_and_no_favorable_retry(self):
        calls = 0
        def partial(card, output):
            nonlocal calls
            calls += 1
            result = self.runner(card, output)
            if calls == 2:
                path = output / "trial-completion.json"
                value = contract._json(path)
                value.update(status="partial", complete_scenes=0)
                path.write_text(json.dumps(value), encoding="utf-8")
                return 1
            return result
        value = self.validate(self.execute(self.freeze(), partial))
        self.assertEqual(calls, 2)
        self.assertEqual([job["status"] for job in value["jobs"]], ["complete", "failed"] + ["not_run"] * 4)
        self.assertEqual(value["expected_jobs"], 6)
        self.assertEqual(value["attempted_jobs"], 2)
        self.assertEqual(value["known_native_total_flow_seconds_sum"], 25)
        self.assertTrue(value["full_expected_quality_denominator_preserved"])

    def test_exception_or_missing_native_receipt_keeps_cost_unknown_not_zero(self):
        for mode in ("exception", "missing"):
            runner = Mock(side_effect=RuntimeError("Synthetic native failure")) if mode == "exception" else Mock(return_value=0)
            value = self.validate(self.execute(self.freeze(mode), runner))
            self.assertEqual(runner.call_count, 1)
            self.assertEqual(value["state"], "incomplete")
            self.assertEqual(value["jobs"][0]["status"], "failed")
            self.assertIsNone(value["jobs"][0]["native_total_flow_seconds"])
            self.assertEqual(value["missing_native_cost_job_ids"], ["trial-001"])

    def test_interruption_preserves_failed_slot_and_remaining_queue(self):
        plan = self.freeze()
        runner = Mock(side_effect=KeyboardInterrupt("Synthetic stop"))
        with self.assertRaises(KeyboardInterrupt):
            self.execute(plan, runner)
        receipt = contract.pointer(self.root / "queue/dispatch-receipt.json")
        value = self.validate(receipt)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual([job["status"] for job in value["jobs"]], ["failed"] + ["not_run"] * 5)
        self.assertEqual(value["expected_jobs"], 6)

    def test_collector_rejects_reordered_missing_or_false_success_slots(self):
        receipt = self.execute(self.freeze(), self.runner)
        original = self.read(receipt)
        for key in ("reorder", "omit", "false-attempt", "new-seed", "missing-cost", "denominator"):
            value = deepcopy(original)
            if key == "reorder":
                value["jobs"].reverse()
            elif key == "omit":
                value["jobs"].pop()
            elif key == "false-attempt":
                value["jobs"][0]["attempted"] = False
            elif key == "new-seed":
                value["new_quality_seeds"] = True
            elif key == "missing-cost":
                value["jobs"][0]["native_trial"] = None
            else:
                value["full_expected_quality_denominator_preserved"] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(self.changed(f"altered-receipt-{key}.json", value))

    def test_midqueue_plan_mutation_is_journaled_and_stops_before_next_launch(self):
        plan = self.freeze()
        calls = 0
        def mutate(card, output):
            nonlocal calls
            calls += 1
            result = self.runner(card, output)
            path = Path(plan["path"])
            path.write_bytes(path.read_bytes() + b" ")
            return result
        receipt = self.execute(plan, mutate)
        value = self.read(receipt)
        self.assertEqual(calls, 1)
        self.assertEqual([job["status"] for job in value["jobs"]], ["complete", "blocked_before_launch"] + ["not_run"] * 4)
        self.assertEqual(value["plan"], plan)
        with self.assertRaises(ValueError):
            self.validate(receipt)

    def test_midqueue_output_reuse_attempt_is_blocked_and_preserved(self):
        plan = self.freeze()
        calls = 0
        def occupy(card, output):
            nonlocal calls
            calls += 1
            result = self.runner(card, output)
            prior = output.parent / "trial-002"
            prior.mkdir()
            (prior / "keep.txt").write_text("Prior synthetic output", encoding="utf-8")
            return result
        value = self.validate(self.execute(plan, occupy))
        self.assertEqual(calls, 1)
        self.assertEqual(value["jobs"][1]["status"], "blocked_before_launch")
        self.assertEqual((self.root / "queue/trial-002/keep.txt").read_text(), "Prior synthetic output")

    def test_replayed_native_receipt_or_changed_journal_never_enters_collector(self):
        def replay(card, output):
            result = self.runner(card, output)
            path = output / "trial-completion.json"
            value = contract._json(path)
            value["started_at_utc"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            path.write_text(json.dumps(value), encoding="utf-8")
            return result
        value = self.validate(self.execute(self.freeze("replay"), replay))
        self.assertEqual(value["jobs"][0]["status"], "failed")
        self.assertIsNone(value["jobs"][0]["native_trial"])
        receipt = self.execute(self.freeze("valid"), self.runner)
        changed = self.read(receipt)
        journal = Path(changed["journal"]["path"])
        journal.write_text(journal.read_text(encoding="utf-8") + '{"event":"job_accepted","job_id":"trial-001"}\n', encoding="utf-8")
        changed["journal"] = contract.pointer(journal)
        with self.assertRaisesRegex(ValueError, "journal"):
            self.validate(self.changed("changed-receipt.json", changed))

    def test_existing_native_trial_is_delegated_only_after_whole_queue_guard(self):
        from .v2_trial import trial
        def prep(**settings):
            settings["output"].mkdir()
            (settings["output"] / "packed-mapping.json").write_text(json.dumps({"scene_ids": ["synthetic-scene"]}), encoding="utf-8")
        with patch("experiments.translation_flow.v2_trial.prepare", side_effect=prep) as preparation, \
             patch("experiments.translation_flow.v2_trial.execute", return_value=0) as model, \
             patch("experiments.translation_flow.v2_trial.deliver", return_value={"scenes": [{"scene_id": "synthetic-scene", "status": "complete"}]}):
            value = self.validate(self.execute(self.freeze(), trial))
        self.assertEqual(preparation.call_count, 6)
        self.assertEqual(model.call_count, 6)
        self.assertEqual(value["state"], "complete")
        self.assertTrue(all(call.kwargs["stage"] == "confirmation" for call in preparation.call_args_list))
        self.assertTrue(all(job["native_total_flow_seconds"] >= 0 for job in value["jobs"]))


if __name__ == "__main__":
    unittest.main()
