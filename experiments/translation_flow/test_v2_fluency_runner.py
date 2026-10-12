"""Fake fresh CLI tests; no real subtitle files, CLI/network or GPU calls."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from . import v2_fluency as fluency, v2_fluency_runner as driver
from experiments.translation_judge import runner as transport


class FakeCLI:
    def __init__(self, actions=None, delay=0):
        self.actions = list(actions or ["valid"])
        self.calls = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.delay = delay

    def __call__(self, args, prompt, cwd, attempt, timeout):
        with self.lock:
            number = len(self.calls)
            self.calls.append((list(args), prompt, cwd))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.assert_empty(cwd)
            if self.delay:
                time.sleep(self.delay)
            action = self.actions[min(number, len(self.actions) - 1)]
            packet = json.loads(prompt.split("\nPACKET:\n", 1)[1])
            response = {"profile": fluency.PROFILE, "window_id": packet["window_id"],
                        "candidate_alias": packet["candidate_alias"], "status": "assessed",
                        "defects": [], "preferences": [], "uncertainties": [], "summary_zh": "合成传输验证。"}
            raw = Path(args[args.index("--output-last-message") + 1])
            stderr = ""
            events = [{"type": "turn.completed", "model": "gpt-6.1-sol", "reasoning_effort": "high",
                       "usage": {"output_tokens": 5}}]
            returncode = 0
            status = "completed"
            if action == "unknown":
                response.update(status="unknown", uncertainties=[{"ids": packet["scored_ids"], "reason_zh": "合成源歧义，保留未知。"}])
            elif action == "wrong_identity":
                response["candidate_alias"] = "anon-ffffffffffffffff"
            elif action == "wrong_schema":
                response["semantic"] = 4
            elif action == "bad_quote":
                response["defects"] = [{"ids": ["a"], "type": "grammar",
                    "source_evidence": [{"id": "a", "quote": "not a supplied source"}],
                    "candidate_evidence": [{"id": "a", "quote": "快点"}],
                    "reason_zh": "合成错误引文。", "observable_effect_zh": "合成描述。"}]
            elif action == "wrong_model":
                events[0]["model"] = "different"
            elif action == "tools":
                events.append({"type": "item.completed", "item": {"type": "command_execution"}})
            elif action == "quota":
                returncode = 1
                events = [{"type": "error", "code": "insufficient_quota", "message": "insufficient quota"}]
            elif action == "timeout":
                status, returncode = "timeout", None
            elif action == "spawn_failure":
                raise OSError("Synthetic spawn failure")
            elif action == "null":
                response = None
            raw.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
            stdout = "\n".join(json.dumps(event) for event in events)
            (attempt / "stdout.jsonl").write_text(stdout, encoding="utf-8")
            (attempt / "stderr.txt").write_text(stderr, encoding="utf-8")
            return {"transport_status": status, "returncode": returncode, "elapsed_seconds": 0.01,
                    **transport.event_evidence(stdout)}
        finally:
            with self.lock:
                self.active -= 1

    @staticmethod
    def assert_empty(cwd):
        if list(cwd.iterdir()):
            raise AssertionError("Fresh CLI cwd is not empty")


class FluencyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "独立 侧轨"
        source = {"id": "scene", "source_language": "ja", "target_language": "zh-Hans",
                  "context": [{"id": "a", "text": "早く。"}], "translate_ids": ["a"]}
        metadata = {"id": "synthetic-window", "window_id": "synthetic-window", "scene_id": "scene",
                    "scored_ids": ["a"], "units": [{"id": "a", "score": True}]}
        self.packet = fluency.build_packet(source, metadata, {"status": "delivered", "translations": {"a": "快点。"}},
                                          anonymous_alias="anon-0123456789abcdef", source_manifest_sha256="1" * 64)
        self.protocol = self.base / "synthetic-protocol.json"
        value = {"profile": fluency.PROFILE, "primary_policy_sha256": fluency.PRIMARY_POLICY_SHA256,
                 "implementation_sha256": driver._sha(Path(fluency.__file__)),
                 "prompt_sha256": hashlib.sha256(fluency.PROMPT.encode()).hexdigest(),
                 "response_schema_sha256": fluency.object_hash(fluency.response_schema()), "exploration_only": True}
        self.protocol.write_text(json.dumps(value), encoding="utf-8")
        self.protocol_sha = driver._sha(self.protocol)
        self.guard_entered = False
        self.guard_workers = []

    @contextmanager
    def guard(self, workers):
        self.guard_workers.append(workers)
        self.guard_entered = True
        try:
            yield
        finally:
            self.guard_entered = False

    def prepare(self, count=1):
        jobs = []
        for number in range(count):
            packet = deepcopy(self.packet)
            packet["window_id"] = f"synthetic-{number}"
            jobs.append({"job_id": f"job-{number}", "phase": "primary", "generation_seed": fluency.SEEDS[0],
                         "judge_pass": 1, "packet": packet})
        return driver.prepare_packets(self.root, jobs, self.protocol, expected_protocol_sha256=self.protocol_sha)

    def run_fake(self, fake, workers=1):
        def invoke(*args):
            self.assertTrue(self.guard_entered)
            return fake(*args)
        return driver.run(self.root, executable="synthetic-codex.cmd", cli_version="synthetic-offline",
                          workers=workers, custody_owner="evaluation_custodian", reviewed_protocol_sha256=self.protocol_sha,
                          dispatch_guard=self.guard, invoke=invoke, expected_protocol_sha256=self.protocol_sha)

    def state(self):
        return driver._read(self.root / "execution/job-0/job.json")

    def test_offline_plan_custom_schema_no_dispatch_and_immutable(self):
        plan = self.prepare()
        self.assertFalse(plan["automatic_dispatch"])
        self.assertEqual(plan["maximum_attempts"], 2)
        self.assertEqual(plan["maximum_cli_workers"], 6)
        schema = driver._read(self.root / "bundles/job-0/schema.json")
        self.assertNotIn("semantic", schema["properties"])
        self.assertFalse((self.root / "execution").exists())
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_accepted_raw_canonical_snapshots_and_resume_never_redispatch(self):
        self.prepare()
        fake = FakeCLI()
        summary = self.run_fake(fake)
        self.assertEqual(summary["succeeded"], 1)
        state = self.state()
        self.assertEqual(driver._sha(Path(state["accepted_raw_response"])), state["accepted_raw_response_sha256"])
        self.assertEqual(driver._sha(Path(state["response"])), state["response_sha256"])
        self.assertEqual(driver._sha(Path(state["accepted_canonical_snapshot"])), state["response_sha256"])
        resumed = self.run_fake(fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(resumed["jobs"][0]["resumed"])
        self.assertFalse(resumed["finalized_quality"])
        self.assertIsNone(resumed["billed_cost"])
        self.assertIn("--ephemeral", fake.calls[0][0])
        self.assertIn("--ignore-user-config", fake.calls[0][0])
        self.assertNotIn("semantic", json.loads(fake.calls[0][1].split("\nPACKET:\n")[1]))

    def test_missing_canonical_restored_only_from_exact_accepted_snapshot(self):
        self.prepare()
        fake = FakeCLI()
        self.run_fake(fake)
        state = self.state()
        Path(state["response"]).unlink()
        summary = self.run_fake(fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(summary["jobs"][0]["canonical_restored"])
        self.assertEqual(driver._sha(Path(state["response"])), state["response_sha256"])

    def test_unknown_is_successful_transport_and_never_retried_as_disagreement(self):
        self.prepare()
        fake = FakeCLI(["unknown"])
        summary = self.run_fake(fake)
        self.assertEqual(summary["accepted_unknown"], 1)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.state()["diagnostic_status"], "unknown")
        response = driver._read(Path(self.state()["response"]))
        self.assertEqual(response["uncertainties"][0]["ids"], ["a"])

    def test_schema_identity_and_quote_failures_have_one_fresh_format_retry(self):
        for index, action in enumerate(("wrong_schema", "wrong_identity", "bad_quote", "wrong_model", "tools")):
            with self.subTest(action=action):
                self.root = self.base / f"run-{index}"
                self.prepare()
                fake = FakeCLI([action, "valid"])
                summary = self.run_fake(fake)
                self.assertEqual(summary["succeeded"], 1)
                self.assertEqual(len(fake.calls), 2)
                self.assertNotEqual(fake.calls[0][2], fake.calls[1][2])
                self.assertEqual(len(self.state()["attempts"]), 2)

    def test_persistent_transport_failures_preserve_unknown_and_exhausted_budget(self):
        for index, action in enumerate(("timeout", "spawn_failure", "wrong_schema", "null")):
            with self.subTest(action=action):
                self.root = self.base / f"failure-{index}"
                self.prepare()
                fake = FakeCLI([action])
                summary = self.run_fake(fake)
                self.assertEqual(summary["judge_failed"], 1)
                self.assertEqual(self.state()["diagnostic_status"], "unknown")
                self.assertFalse((self.root / "responses/job-0.json").exists())
                self.run_fake(fake)
                self.assertEqual(len(fake.calls), 2)

    def test_preflight_raw_canonical_snapshot_and_fingerprint_tamper_refuse_without_call(self):
        for index, kind in enumerate(("raw", "canonical", "snapshot", "fingerprint")):
            with self.subTest(kind=kind):
                self.root = self.base / f"tamper-{index}"
                self.prepare()
                fake = FakeCLI()
                self.run_fake(fake)
                state = self.state()
                if kind == "fingerprint":
                    state["fingerprint"] = "changed"
                    driver._write(self.root / "execution/job-0/job.json", state)
                else:
                    key = {"raw": "accepted_raw_response", "canonical": "response", "snapshot": "accepted_canonical_snapshot"}[kind]
                    Path(state[key]).write_bytes(b"tampered")
                with self.assertRaises(ValueError):
                    self.run_fake(fake)
                self.assertEqual(len(fake.calls), 1)

    def test_late_bad_bundle_stops_all_jobs_before_dispatch(self):
        self.prepare(2)
        (self.root / "bundles/job-1/prompt.txt").write_text("changed", encoding="utf-8")
        fake = FakeCLI()
        with self.assertRaises(ValueError):
            self.run_fake(fake)
        self.assertEqual(len(fake.calls), 0)

    def test_plan_protocol_or_schema_fingerprint_change_refuses_before_dispatch(self):
        self.prepare()
        fake = FakeCLI()
        plan = self.root / "run-plan.json"
        plan.write_bytes(plan.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            self.run_fake(fake)
        self.assertEqual(len(fake.calls), 0)

    def test_protocol_and_custom_schema_tamper_refuse_without_dispatch(self):
        original_protocol = self.protocol.read_bytes()
        for index, artifact in enumerate(("protocol", "schema")):
            with self.subTest(artifact=artifact):
                self.protocol.write_bytes(original_protocol)
                self.root = self.base / f"identity-{index}"
                self.prepare()
                path = self.protocol if artifact == "protocol" else self.root / "bundles/job-0/schema.json"
                path.write_bytes(path.read_bytes() + b" ")
                fake = FakeCLI()
                with self.assertRaises(ValueError):
                    self.run_fake(fake)
                self.assertEqual(fake.calls, [])

    def test_access_breaker_stops_after_three_distinct_failures_not_calls(self):
        self.prepare(7)
        fake = FakeCLI(["quota"])
        summary = self.run_fake(fake)
        self.assertEqual(len(fake.calls), 6)
        self.assertEqual(summary["judge_failed"], 3)
        self.assertEqual(summary["not_run"], 4)
        self.assertEqual(summary["expected_jobs"], 7)
        self.assertTrue(summary["circuit_breaker"]["tripped"])
        self.assertEqual(summary["circuit_breaker"]["kind"], "quota")
        self.assertTrue(all(s["diagnostic_status"] == "unknown" for s in summary["jobs"]))

    def test_bounded_submission_and_guard_drain(self):
        self.prepare(12)
        fake = FakeCLI(delay=0.01)
        summary = self.run_fake(fake, workers=3)
        self.assertLessEqual(fake.max_active, 3)
        self.assertEqual(summary["succeeded"], 12)
        self.assertEqual(fake.active, 0)
        self.assertFalse(self.guard_entered)
        self.assertEqual(self.guard_workers, [3])

    def test_custodian_review_guard_and_workers_are_required(self):
        self.prepare()
        fake = FakeCLI()
        base = {"executable": "fake", "cli_version": "synthetic", "custody_owner": "evaluation_custodian",
                "reviewed_protocol_sha256": self.protocol_sha, "dispatch_guard": self.guard,
                "invoke": fake, "expected_protocol_sha256": self.protocol_sha}
        for update in ({"custody_owner": "other"}, {"reviewed_protocol_sha256": "0" * 64},
                       {"dispatch_guard": None}, {"workers": 7}, {"workers": True}, {"timeout": float("nan")}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                driver.run(self.root, **dict(base, **update))
        self.assertEqual(len(fake.calls), 0)

    def test_duplicate_jobs_invalid_seed_path_and_calibration_seed_rejected(self):
        job = {"job_id": "calib", "phase": "calibration", "generation_seed": fluency.SEEDS[0],
               "judge_pass": 1, "packet": self.packet}
        for jobs in ([job, job], [dict(job, job_id="../escape")], [dict(job, generation_seed=fluency.SEEDS[1])],
                     [dict(job, judge_pass=4)], [dict(job, phase="adjudication")]):
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                driver.prepare_packets(self.root, jobs, self.protocol, expected_protocol_sha256=self.protocol_sha)
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
