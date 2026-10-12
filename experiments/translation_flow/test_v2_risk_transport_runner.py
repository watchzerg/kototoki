"""Synthetic transport-v2 fixtures only; no real source, opinions, CLI or network."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
import unittest

from . import v2_risk_reconciliation as risk, v2_risk_runner as legacy
from . import v2_risk_transport_runner as runner
from . import test_v2_risk_reconciliation as fixtures
from .test_v2_risk_runner import FakeNative


class SchemaAwareNative(FakeNative):
    """Emulate the CLI schema boundary and its actual structured HTTP 400 error."""
    def __call__(self, args, prompt, cwd, attempt, timeout):
        schema = json.loads(Path(args[args.index("--output-schema") + 1]).read_text(encoding="utf-8"))
        if "uniqueItems" in json.dumps(schema):
            raise AssertionError("unsupported uniqueItems reached model-consumed schema")
        action = self.actions[min(len(self.calls), len(self.actions) - 1)]
        if action == "invalid_json_schema":
            with self.lock:
                self.calls.append((args, prompt, str(cwd)))
            event = {"type": "error", "message": 'HTTP 400: {"error":{"code":"invalid_json_schema","message":"uniqueItems unsupported"}}'}
            (attempt / "stdout.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
            return {"transport_status": "completed", "returncode": 1}
        return super().__call__(args, prompt, cwd, attempt, timeout)


class TransportV2Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RiskReconciliationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base = self.fixture.root
        self.root = self.base / "new"
        self.active = False
        self.reservations = []
        self.original = {module.__name__: runner._sha(Path(module.__file__)) for module in (risk, legacy)}

    @contextmanager
    def guard(self, workers):
        self.reservations.append(workers)
        self.active = True
        try:
            yield
        finally:
            self.active = False

    def bundles(self, count=1, label="scene"):
        result = []
        for index in range(count):
            envelope = deepcopy(self.fixture.packet)
            for pair in envelope["judge_packet"]["pairs"]:
                pair["scene_id"] += f"-{label}-{index}"
            envelope["packet_sha256"] = risk._hash(envelope["judge_packet"])
            result.append({"job_id": f"{label}-{index}", "envelope": envelope})
        return result

    def receipt(self, root):
        plan = runner._read(root / "run-plan.json")
        return self.fixture.write(f"launch-{root.name}.json", {
            "version": "risk-reconciliation-launch-v1", "protocol_sha256": self.fixture.protocol["sha256"],
            "run_plan_sha256": runner._sha(root / "run-plan.json"),
            "final_seal_sha256": plan["final_seal_sha256"], "root_protocol_reviewed_safe": True,
            "candidate_risk_calls_authorized": True, "shared_core_complete": True,
            "maximum_cli_workers": 6, "dispatch_owner": "evaluation_custodian"})

    def options(self, root, fake, **kwargs):
        def callback(*args):
            self.assertTrue(self.active)
            return fake(*args)
        result = {"launch_receipt": self.receipt(root), "custody_owner": "evaluation_custodian",
                  "dispatch_guard": self.guard, "invoke": callback, "executable": "fake-codex.cmd",
                  "cli_version": "synthetic", "workers": 1,
                  "expected_protocol_sha256": self.fixture.protocol["sha256"]}
        result.update(kwargs)
        return result

    def probe(self, action="valid"):
        root = self.base / "probe"
        runner.prepare_probe(root, self.bundles(label="probe")[0], self.fixture.protocol,
                             synthetic_material_declared=True,
                             expected_protocol_sha256=self.fixture.protocol["sha256"])
        fake = SchemaAwareNative(self.fixture, [action])
        result = runner.run_probe(root, **self.options(root, fake))
        return result, fake

    def failed_root(self, bundles):
        """Seal synthetic failed history without dispatching the legacy CLI."""
        root = self.base / "failed"
        plan = legacy.prepare(root, bundles, self.fixture.protocol,
                              expected_protocol_sha256=self.fixture.protocol["sha256"])
        for job in plan["jobs"]:
            _, _, fingerprint = legacy._inputs(root, plan, job, "identity_match")
            directory = root / "execution/identity_match" / job["job_id"]
            records = []
            for number in (1, 2):
                attempt = directory / f"attempt-{number}"
                attempt.mkdir(parents=True)
                record = {"attempt": number, "returncode": 1, "transport_status": "completed", "status": "failed"}
                runner._write(attempt / "attempt.json", record)
                (attempt / "stdout.jsonl").write_text(json.dumps(
                    {"type": "error", "code": "invalid_json_schema"}) + "\n", encoding="utf-8")
                records.append(record)
            runner._write(directory / "job.json", {"job_id": job["job_id"], "phase": "identity_match",
                "status": "judge_failed", "fingerprint": fingerprint, "attempts": records})
        terminal = self.fixture.write("native-terminal.json", {"synthetic_fixture_only": True})
        custody = self.fixture.write("native-drained.json", {"state": "drained_released", "active_callbacks": 0,
            "owned_job_objects": 0, "terminal_receipt": terminal["path"], "terminal_sha256": terminal["sha256"]})
        manifest = {"version": "risk-transport-terminal-failure-v1", "state": "sealed_global_schema_rejection",
            "failure_class": "invalid_json_schema_uniqueItems", "accepted_opinions": 0, "semantic_acceptance": False,
            "primary_scores_modified": False, "unknown_denominator_retained": True,
            "expected_scene_jobs": len(bundles), "transport_attempts": len(bundles) * 2,
            "native_drained_attempts": len(bundles) * 2, "custody_receipts": {custody["path"]: custody["sha256"]},
            "files": [{"path": path.relative_to(root).as_posix(), "sha256": runner._sha(path)}
                      for path in sorted(root.rglob("*")) if path.is_file()]}
        runner._write(root / "terminal-failure-manifest.json", manifest)
        return root, {"path": str(root / "terminal-failure-manifest.json"),
                      "sha256": runner._sha(root / "terminal-failure-manifest.json")}

    def prepare(self, count=1):
        probe, _ = self.probe()
        bundles = self.bundles(count)
        old, seal = self.failed_root(bundles)
        self.old_bytes = {path: path.read_bytes() for path in old.rglob("*") if path.is_file()}
        plan = runner.prepare(self.root, bundles, self.fixture.protocol, failed_root=old, failed_root_seal=seal,
            probe_receipt=probe["probe_receipt"], expected_protocol_sha256=self.fixture.protocol["sha256"])
        return plan

    def run_fake(self, phase, fake, **kwargs):
        return runner.run_stage(self.root, phase, **self.options(self.root, fake, **kwargs))

    def state(self, phase="identity_match", job="scene-0"):
        return runner._read(self.root / "execution" / phase / job / "job.json")

    def test_projection_strips_only_keyword_recursively_runtime_uniqueness_unchanged(self):
        original = risk.response_schema()
        submitted = runner.projected_schema()
        self.assertIn("uniqueItems", json.dumps(original))
        self.assertNotIn("uniqueItems", json.dumps(submitted))
        def compare(a, b):
            if isinstance(a, dict):
                self.assertEqual(set(a) - {"uniqueItems"}, set(b))
                for key in b:
                    compare(a[key], b[key])
            elif isinstance(a, list):
                self.assertEqual(len(a), len(b))
                for x, y in zip(a, b): compare(x, y)
            else: self.assertEqual(a, b)
        compare(original, submitted)
        response = self.fixture.response()
        response["roots"][0]["occurrences"][0]["source_event_ids"] *= 2
        with self.assertRaises(ValueError): risk.validate_response(response, self.fixture.packet)
        for module in (risk, legacy):
            self.assertEqual(self.original[module.__name__], runner._sha(Path(module.__file__)))

    def test_one_probe_full_two_blind_phases_frozen_hash_and_preserved_failure_bytes(self):
        plan = self.prepare()
        self.assertEqual(plan["version"], "risk-reconciliation-run-transport-v2")
        self.assertEqual(plan["failed_root_lineage"]["accepted_opinions"], 0)
        fake = SchemaAwareNative(self.fixture)
        for phase in ("identity_match", "independent_review"):
            self.assertEqual(self.run_fake(phase, fake)["succeeded"], 1)
        self.assertEqual(fake.calls[0][1], fake.calls[1][1])
        self.assertNotIn("ANONYMOUS_PRIOR_RESPONSES", fake.calls[1][1])
        self.assertNotEqual(fake.calls[0][2], fake.calls[1][2])
        schema_path = Path(fake.calls[0][0][fake.calls[0][0].index("--output-schema") + 1])
        self.assertEqual(runner._sha(schema_path), plan["schema_projection"]["submitted_schema_sha256"])
        self.assertNotEqual(plan["schema_projection"]["original_schema_sha256"], runner._sha(schema_path))
        _, _, fingerprint = runner._inputs(self.root, plan, plan["jobs"][0], "identity_match")
        self.assertEqual(self.state()["fingerprint"], fingerprint)
        self.assertNotEqual(fingerprint, plan["failed_root_lineage"]["original_job_fingerprints"]["scene-0"])
        for path, content in self.old_bytes.items(): self.assertEqual(path.read_bytes(), content)
        summary = runner.complete(self.root, expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.assertEqual(summary["frozen_scenes"], 1)
        self.assertNotIn("行かない", json.dumps(summary, ensure_ascii=False))

    def test_global_schema_400_one_attempt_stops_unscheduled_tail_and_resume(self):
        self.prepare(4)
        fake = SchemaAwareNative(self.fixture, ["invalid_json_schema"])
        result = self.run_fake("identity_match", fake)
        self.assertTrue(result["global_invalid_json_schema"])
        self.assertEqual(result["not_run"], 3)
        self.assertEqual(result["expected_scene_jobs"], 4)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(len(self.state()["attempts"]), 1)
        self.run_fake("identity_match", fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse((self.root / "execution/identity_match/scene-1").exists())

    def test_scheduler_drains_pending_without_refilling_after_global_rejection(self):
        event, entered = threading.Event(), threading.Event()
        calls = []
        def invoke(job):
            calls.append(job["job_id"])
            if job["job_id"] == "j0":
                self.assertTrue(entered.wait(2))
                event.set()
                return {"status": "judge_failed", "attempts": []}
            entered.set()
            time.sleep(0.02)
            return {"status": "succeeded", "attempts": []}
        states, meta = runner._schedule([{"job_id": f"j{i}"} for i in range(5)], 2, invoke, event)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(states), 5)
        self.assertEqual(sum(s["status"] == "not_run" for s in states), 3)
        self.assertTrue(meta["global_invalid_json_schema"])

    def test_ordinary_format_transport_two_attempts_but_valid_unknown_one(self):
        self.prepare()
        fake = SchemaAwareNative(self.fixture, ["bad_quote", "unknown"])
        result = self.run_fake("identity_match", fake)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["accepted_unknown_occurrences"], 3)
        self.assertFalse(result["global_invalid_json_schema"])
        self.assertEqual(len(fake.calls), 2)
        self.run_fake("identity_match", fake)
        self.assertEqual(len(fake.calls), 2)

    def test_probe_unknown_is_accepted_no_semantic_expected_gate_single_attempt(self):
        result, fake = self.probe("unknown")
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("probe_receipt", result)
        receipt = runner._read(Path(result["probe_receipt"]["path"]))
        self.assertFalse(receipt["quality_accuracy_verified"])
        runner._probe_verified(result["probe_receipt"], self.fixture.protocol["sha256"])
        with self.assertRaises(ValueError):
            runner.complete(self.base / "probe", expected_protocol_sha256=self.fixture.protocol["sha256"])

    def test_failed_probe_never_retries_or_opens_full_pool(self):
        result, fake = self.probe("invalid_json_schema")
        self.assertNotIn("probe_receipt", result)
        runner.run_probe(self.base / "probe", **self.options(self.base / "probe", fake))
        self.assertEqual(len(fake.calls), 1)
        bundles = self.bundles()
        old, seal = self.failed_root(bundles)
        with self.assertRaises(ValueError):
            runner.prepare(self.root, bundles, self.fixture.protocol, failed_root=old, failed_root_seal=seal,
                           expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.assertFalse(self.root.exists())

    def test_accepted_resume_restores_exact_snapshot_and_raw_tamper_blocks_new_calls(self):
        self.prepare()
        fake = SchemaAwareNative(self.fixture)
        self.run_fake("identity_match", fake)
        state = self.state()
        original = Path(state["response"]).read_bytes()
        Path(state["response"]).unlink()
        self.run_fake("identity_match", fake)
        self.assertEqual(Path(state["response"]).read_bytes(), original)
        self.assertEqual(len(fake.calls), 1)
        Path(state["accepted_raw_response"]).write_text("tamper", encoding="utf-8")
        with self.assertRaises(ValueError): self.run_fake("independent_review", fake)
        self.assertEqual(len(fake.calls), 1)

    def test_schema_tamper_or_unreviewed_launch_blocks_before_guard(self):
        self.prepare()
        fake = SchemaAwareNative(self.fixture)
        value = runner._read(Path(self.receipt(self.root)["path"]))
        value["root_protocol_reviewed_safe"] = False
        pointer = self.fixture.write("not-reviewed.json", value)
        before = len(self.reservations)
        with self.assertRaises(ValueError): self.run_fake("identity_match", fake, launch_receipt=pointer)
        self.assertEqual(len(self.reservations), before)
        (self.root / "bundles/scene-0/schema.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError): self.run_fake("identity_match", fake)
        self.assertEqual(len(fake.calls), 0)

    def test_failed_derivative_rejects_changed_original_packet_and_missing_failure_seal(self):
        probe, _ = self.probe()
        bundles = self.bundles()
        old, seal = self.failed_root(bundles)
        changed = deepcopy(bundles)
        changed[0]["envelope"]["judge_packet"]["pairs"][0]["context"][0]["text"] += "変更"
        changed[0]["envelope"]["packet_sha256"] = risk._hash(changed[0]["envelope"]["judge_packet"])
        for options in ({"failed_root": old}, {"failed_root": old, "failed_root_seal": seal}):
            with self.assertRaises(ValueError):
                runner.prepare(self.root, changed, self.fixture.protocol, probe_receipt=probe["probe_receipt"],
                    expected_protocol_sha256=self.fixture.protocol["sha256"], **options)
        self.assertFalse(self.root.exists())

    def test_fresh_group_shares_failure_authority_without_packet_or_opinion_donation(self):
        probe, _ = self.probe()
        _, seal = self.failed_root(self.bundles(label="old-group"))
        bundles = self.bundles(label="fresh-group")
        joined = self.fixture.write("source-join.json", {"synthetic_fixture_only": True})
        custody_value = {"version": "risk-fresh-packet-custody-v2", "state": "frozen_before_first_risk_call",
            "original_model_calls": 0, "accepted_opinions": 0,
            "bundle_sha256": {item["job_id"]: risk._hash(item["envelope"]) for item in bundles},
            "source_join_custody": joined}
        bad = dict(custody_value, original_model_calls=1)
        with self.assertRaises(ValueError):
            runner.prepare(self.root, bundles, self.fixture.protocol, global_transport_failure_history=seal,
                fresh_packet_custody=self.fixture.write("bad-fresh-custody.json", bad), probe_receipt=probe["probe_receipt"],
                expected_protocol_sha256=self.fixture.protocol["sha256"])
        plan = runner.prepare(self.root, bundles, self.fixture.protocol, global_transport_failure_history=seal,
            fresh_packet_custody=self.fixture.write("fresh-custody.json", custody_value), probe_receipt=probe["probe_receipt"],
            expected_protocol_sha256=self.fixture.protocol["sha256"])
        self.assertIsNone(plan["failed_root_lineage"])
        fake = SchemaAwareNative(self.fixture)
        for phase in ("identity_match", "independent_review"):
            self.assertEqual(self.run_fake(phase, fake)["succeeded"], 1)
        self.assertEqual(len(fake.calls), 2)


if __name__ == "__main__":
    unittest.main()
