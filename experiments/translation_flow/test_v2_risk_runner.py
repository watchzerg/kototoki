"""Fake fresh native callbacks; no real candidate/source/judge material or calls."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import unittest

from . import v2_risk_reconciliation as risk, v2_risk_runner as runner
from . import test_v2_risk_reconciliation as fixtures
from experiments.translation_judge import runner as transport


class FakeNative:
    def __init__(self, fixture, actions=None, delay=0):
        self.fixture, self.actions = fixture, list(actions or ["valid"])
        self.calls, self.active, self.max_active = [], 0, 0
        self.lock, self.delay = threading.Lock(), delay

    def __call__(self, args, prompt, cwd, attempt, timeout):
        with self.lock:
            index = len(self.calls)
            self.calls.append((args, prompt, str(cwd)))
            self.active += 1
            self.max_active = max(self.active, self.max_active)
        try:
            if list(cwd.iterdir()): raise AssertionError("fresh cwd must be empty")
            if self.delay: time.sleep(self.delay)
            view = json.loads(prompt.split("\nPACKET:\n", 1)[1].split("\nANONYMOUS_PRIOR_RESPONSES:\n", 1)[0])
            response = self.fixture.response({"judge_packet": view, "packet_sha256": risk._hash(view)})
            action = self.actions[min(index, len(self.actions) - 1)]
            record = {"transport_status": "completed", "returncode": 0,
                      "returned_models": [transport.MODEL], "returned_efforts": [transport.EFFORT],
                      "tool_events": [], "elapsed_seconds": 0.001}
            if action == "unknown":
                for occurrence in response["roots"][0]["occurrences"]:
                    for evidence in occurrence["side_evidence"].values():
                        evidence.update(state="unknown", severity="unknown", quotes=[])
            elif action == "disagreement": response["roots"][0]["cause_zh"] = "不同的合成根因。"
            elif action == "bad_schema": response["semantic"] = 4
            elif action == "bad_quote": response["roots"][0]["occurrences"][0]["source_quotes"][0]["quote"] = "bad quote"
            elif action == "wrong_model": record["returned_models"] = ["wrong"]
            elif action == "tools": record["tool_events"] = ["forbidden"]
            elif action == "timeout": record.update(transport_status="timeout", returncode=None)
            elif action == "spawn": raise OSError("synthetic spawn failure")
            raw = Path(args[args.index("--output-last-message") + 1])
            raw.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            return record
        finally:
            with self.lock: self.active -= 1


class RiskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RiskReconciliationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root / "driver"
        self.guard_active = False
        self.reservations = []

    @contextmanager
    def guard(self, workers):
        self.reservations.append(workers)
        self.guard_active = True
        try: yield
        finally: self.guard_active = False

    def prepare(self, count=1):
        bundles = []
        for index in range(count):
            envelope = deepcopy(self.fixture.packet)
            for pair in envelope["judge_packet"]["pairs"]: pair["scene_id"] += str(index)
            envelope["packet_sha256"] = risk._hash(envelope["judge_packet"])
            bundles.append({"job_id": f"scene-{index}", "envelope": envelope})
        plan = runner.prepare(self.root, bundles, self.fixture.protocol,
                              expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.receipt = self.fixture.write("launch.json", {
            "version": "risk-reconciliation-launch-v1", "protocol_sha256": self.fixture.protocol["sha256"],
            "run_plan_sha256": runner._sha(self.root / "run-plan.json"),
            "final_seal_sha256": plan["final_seal_sha256"], "root_protocol_reviewed_safe": True,
            "candidate_risk_calls_authorized": True, "shared_core_complete": True,
            "maximum_cli_workers": 6, "dispatch_owner": "evaluation_custodian"})
        return plan

    def run_fake(self, phase, fake, **kwargs):
        def callback(*args):
            self.assertTrue(self.guard_active)
            return fake(*args)
        options = {"launch_receipt": self.receipt, "custody_owner": "evaluation_custodian",
                   "dispatch_guard": self.guard, "invoke": callback, "executable": "synthetic-codex.cmd",
                   "cli_version": "synthetic-only", "workers": 1,
                   "expected_protocol_sha256": self.fixture.protocol["sha256"]}
        options.update(kwargs)
        return runner.run_stage(self.root, phase, **options)

    def state(self, phase="identity_match", job="scene-0"):
        return runner._read(self.root / "execution" / phase / job / "job.json")

    def test_offline_prepare_custom_schema_hash_frozen_no_dispatch(self):
        plan = self.prepare()
        self.assertFalse(plan["automatic_dispatch"])
        self.assertEqual(plan["maximum_attempts"], 2)
        self.assertFalse((self.root / "execution").exists())
        schema = runner._read(self.root / "bundles/scene-0/schema.json")
        self.assertNotIn("semantic", schema["properties"])
        with self.assertRaises(FileExistsError): self.prepare()

    def test_identical_fresh_match_review_no_prior_and_no_unnecessary_adjudication(self):
        self.prepare(); fake = FakeNative(self.fixture)
        self.run_fake("identity_match", fake); self.run_fake("independent_review", fake)
        self.assertEqual(fake.calls[0][1], fake.calls[1][1])
        self.assertNotEqual(fake.calls[0][2], fake.calls[1][2])
        self.assertNotIn("ANONYMOUS_PRIOR_RESPONSES", fake.calls[1][1])
        self.assertIn("--ephemeral", fake.calls[0][0])
        adjud = self.run_fake("adjudication", fake)
        self.assertEqual(adjud["selected_jobs"], 0)
        self.assertEqual(len(fake.calls), 2)
        summary = runner.complete(self.root, expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.assertEqual(summary["frozen_scenes"], 1)
        self.assertEqual(summary["scenes"][0]["transitions"]["new"]["root_count"], 1)
        self.assertNotIn("行かない", json.dumps(summary, ensure_ascii=False))
        with self.assertRaises(ValueError): runner.complete(self.root, expected_protocol_sha256=self.fixture.protocol["sha256"])

    def test_valid_unknown_no_semantic_retry_then_bounded_fresh_adjudication(self):
        self.prepare(); fake = FakeNative(self.fixture, ["valid", "unknown", "valid"])
        self.run_fake("identity_match", fake)
        review = self.run_fake("independent_review", fake)
        self.assertEqual(review["accepted_unknown_occurrences"], 3)
        self.assertEqual(len(fake.calls), 2)
        self.run_fake("adjudication", fake)
        self.assertIn("ANONYMOUS_PRIOR_RESPONSES", fake.calls[2][1])
        self.run_fake("adjudication", fake)
        self.assertEqual(len(fake.calls), 3)
        summary = runner.complete(self.root, expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.assertEqual(summary["scenes"][0]["transitions"]["new"]["root_count"], 1)

    def test_two_unknown_fresh_passes_keep_unknown_in_registry(self):
        self.prepare(); fake = FakeNative(self.fixture, ["unknown"])
        self.run_fake("identity_match", fake); self.run_fake("independent_review", fake)
        self.run_fake("adjudication", fake)
        self.assertEqual(len(fake.calls), 2)
        summary = runner.complete(self.root, expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.assertEqual(summary["scenes"][0]["transitions"]["unresolved"]["root_count"], 1)

    def test_format_and_transport_failures_use_at_most_two_attempts(self):
        for index, action in enumerate(("bad_schema", "bad_quote", "wrong_model", "tools", "timeout", "spawn")):
            with self.subTest(action=action):
                self.root = self.fixture.root / f"retry-{index}"
                self.prepare(); fake = FakeNative(self.fixture, [action, "valid"])
                summary = self.run_fake("identity_match", fake)
                self.assertEqual(summary["succeeded"], 1)
                self.assertEqual(len(fake.calls), 2)
                self.assertEqual(len(self.state()["attempts"]), 2)
        self.root = self.fixture.root / "exhausted"
        self.prepare(); fake = FakeNative(self.fixture, ["timeout"])
        self.assertEqual(self.run_fake("identity_match", fake)["failed_or_not_run"], 1)
        self.run_fake("identity_match", fake)
        self.assertEqual(len(fake.calls), 2)
        with self.assertRaises(ValueError): self.run_fake("independent_review", fake)

    def test_raw_canonical_snapshot_fingerprint_preflight_blocks_all_new_calls(self):
        for index, member in enumerate(("accepted_raw_response", "response", "accepted_canonical_snapshot", "fingerprint")):
            with self.subTest(member=member):
                self.root = self.fixture.root / f"tamper-{index}"
                self.prepare(); fake = FakeNative(self.fixture)
                self.run_fake("identity_match", fake)
                state = self.state()
                if member == "fingerprint":
                    state[member] = "changed"
                    runner._write(self.root / "execution/identity_match/scene-0/job.json", state)
                else: Path(state[member]).write_text("changed", encoding="utf-8")
                with self.assertRaises(ValueError): self.run_fake("independent_review", fake)
                self.assertEqual(len(fake.calls), 1)

    def test_missing_canonical_restored_from_exact_snapshot_without_redispatch(self):
        self.prepare(); fake = FakeNative(self.fixture)
        self.run_fake("identity_match", fake); state = self.state()
        original = Path(state["response"]).read_bytes()
        Path(state["response"]).unlink()
        self.run_fake("identity_match", fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(Path(state["response"]).read_bytes(), original)

    def test_launch_gate_and_six_seals_checked_before_guard_or_callback(self):
        self.prepare(); fake = FakeNative(self.fixture)
        for field in ("root_protocol_reviewed_safe", "candidate_risk_calls_authorized", "shared_core_complete"):
            value = runner._read(Path(self.receipt["path"]))
            value[field] = False
            pointer = self.fixture.write(f"bad-{field}.json", value)
            with self.assertRaises(ValueError): self.run_fake("identity_match", fake, launch_receipt=pointer)
        self.assertEqual(self.reservations, [])
        self.assertEqual(len(fake.calls), 0)
        Path(self.fixture.seals[0]["path"]).with_name("final.json").write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError): self.run_fake("identity_match", fake)
        self.assertEqual(len(fake.calls), 0)

    def test_phase_prerequisites_and_global_guard_worker_cap(self):
        self.prepare(count=7); fake = FakeNative(self.fixture, delay=0.01)
        with self.assertRaises(ValueError): self.run_fake("independent_review", fake)
        with self.assertRaises(ValueError): self.run_fake("identity_match", fake, workers=7)
        summary = self.run_fake("identity_match", fake, workers=6)
        self.assertEqual(summary["succeeded"], 7)
        self.assertLessEqual(fake.max_active, 6)
        self.assertGreater(fake.max_active, 1)
        self.assertEqual(self.reservations, [6])

    def test_implementation_bundle_tamper_blocks_dispatch(self):
        self.prepare(); fake = FakeNative(self.fixture)
        (self.root / "implementation-bundle/judge-prompt.txt").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError): self.run_fake("identity_match", fake)
        self.assertEqual(len(fake.calls), 0)

    def test_complete_checks_all_scenes_before_freezing_any_registry(self):
        self.prepare(count=2); fake = FakeNative(self.fixture, ["valid", "valid", "valid", "timeout"])
        self.run_fake("identity_match", fake)
        self.run_fake("independent_review", fake)
        with self.assertRaises(ValueError): runner.complete(self.root, expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.assertFalse((self.root / "registries").exists())


if __name__ == "__main__":
    unittest.main()
