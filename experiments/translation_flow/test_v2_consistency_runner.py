"""Handwritten synthetic contracts and native-lock fixtures; no judge CLI calls."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.translation_judge import integrity
from . import v2_consistency as c, v2_consistency_runner as r, v2_judge_dispatch as native
from . import test_v2_consistency as synthetic


class RunnerTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local" / "consistency-runner-synthetic-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = synthetic.ConsistencyTests()
        self.fixture.setUp()
        self.a = c.build_phase_a(self.fixture.frame(), self.fixture.scene["id"], c.SEEDS[0], self.fixture.deliveries())
        self.b = self.fixture.b_packet()
        self.jobs = [{"job_id": "a", "envelope": self.a}, {"job_id": "b", "envelope": self.b}]
        # This stub authenticates ONLY this in-memory synthetic fixture. Actual
        # source/native authentication belongs to the separately tested module.
        self.custody_calls = []
        self.extra_slots = []
        def validate(pointer, jobs):
            self.custody_calls.append((pointer, deepcopy(jobs)))
            value = r._read(r._pointer(pointer))
            if value != {"synthetic_fixture_only": True, "jobs_sha256": c.object_hash(jobs)}:
                raise ValueError("synthetic custody jobs mismatch")
            return {"expected_slots": [{"job_id": job["job_id"], "phase": job["envelope"]["judge_packet"]["phase"],
                                        "status": "scheduled"} for job in jobs] + self.extra_slots}
        self.stub = SimpleNamespace(__file__=c.__file__, validate_receipt=validate)
        self.addCleanup(patch.stopall)
        patch.object(r, "_custody", return_value=self.stub).start()
        self.protocol = self.write("protocol.json", {
            "version": r.PROTOCOL_VERSION, "state": "frozen_before_candidate_quality",
            "implementation": r.implementation(), "phases": r.phase_contracts(),
            "command_config": r.command_config(), "maximum_attempts": 2,
            "maximum_adjudication_attempts": 2,
            "adjudication_prompt_sha256": integrity.sha(r.ADJUDICATION_PROMPT.encode())})
        self.source_receipt = self.write("synthetic-custody.json", {
            "synthetic_fixture_only": True, "jobs_sha256": c.object_hash(self.jobs)})
        self.terminal = self.write("terminal.json", {
            "schema": "hy30-judge-core-terminal-receipt-v1", "owner": "evaluation_custodian",
            "core_pipeline_terminal": True, "native_children_drained": True, "owned_cli_batches": []})
        exe = self.root / "never-launched-fixture.exe"
        exe.write_bytes(b"synthetic executable identity; never executed")
        self.exe = {"path": str(exe), "sha256": r._sha(exe)}
        self.calls, self.outputs = [], {}

    def write(self, relative, value):
        path = self.root / relative
        r._write(path, value)
        return {"path": str(path), "sha256": r._sha(path)}

    def prepare(self):
        root = self.root / "full"
        plan = r.prepare_packets(root, self.jobs, self.protocol, self.source_receipt,
                                 expected_protocol_sha256=self.protocol["sha256"])
        return root, plan

    def kwargs(self, root, plan, probes=None):
        launch = self.write(root.name + "-launch.json", {
            "version": "hy30-consistency-launch-v1", "run_plan_sha256": r._sha(root / "run-plan.json"),
            "protocol_sha256": self.protocol["sha256"], "kind": plan["kind"],
            "reviewed_safe": True, "calls_authorized": True, "maximum_cli_workers": 6,
            "dispatch_owner": "evaluation_custodian", "native_dispatch_sha256": r.implementation()["native_dispatch"],
            "cli_version": "synthetic-test-only", "executable": self.exe,
            "terminal_receipt": self.terminal, "global_lock": str(self.root / ".judge-global-six.lock"),
            "source_custody_receipt": plan["source_custody_receipt"], "probe_receipts": probes})
        return {"launch_receipt": launch, "expected_launch_sha256": launch["sha256"],
                "custody_owner": "evaluation_custodian", "dispatch_guard": lambda workers: native.CustodyGuard(
                    self.root, workers, Path(self.terminal["path"]), self.terminal["sha256"]),
                "invoke": native.execute, "executable": self.exe["path"], "cli_version": "synthetic-test-only",
                "expected_protocol_sha256": self.protocol["sha256"], "workers": 1, "probe_receipts": probes}

    def response(self, phase, unknown=False):
        if phase == "A":
            return self.fixture.a_response(self.a, classifications=[("unknown", None)] * len(self.a["judge_packet"]["anchors"][0]["occurrences"])) if unknown else self.fixture.a_response(self.a)
        return self.fixture.b_response(self.b, all_unknown=unknown)

    def fake(self, guard, args, prompt, cwd, attempt, timeout):
        self.calls.append({"prompt": prompt, "cwd": str(cwd), "attempt": str(attempt)})
        phase = "A" if self.a["judge_packet"]["profile"] in prompt else "B"
        stage = attempt.parent.parent.name
        output = self.outputs.get((stage, phase), self.response(phase))
        if isinstance(output, list):
            output = output.pop(0)
        (attempt / "stdin.bin").write_bytes(prompt.encode())
        (attempt / "stdout.jsonl").write_bytes(b"")
        (attempt / "stderr.txt").write_bytes(b"")
        record = {"transport_status": "completed", "returncode": 0,
                  "returned_models": ["gpt-6.1-sol"], "returned_efforts": ["high"], "tool_events": [],
                  "native_dispatch_sha256": guard.implementation_sha256, "custody_token": guard.token,
                  "custody_workers_reserved": guard.workers, "native_drain_proven": True,
                  "native_active_processes_after_drain": 0, "custody_receipt": str(guard.owner_record),
                  "containment": "suspended-assign-resume-kill-on-close-job"}
        if output == "schema_failure":
            (attempt / "stdout.jsonl").write_bytes(b'{"type":"error","code":"invalid_json_schema"}\n')
            record["returncode"] = 1
        elif output == "identity_failure":
            record["returned_models"] = ["wrong-model"]
        elif output == "format_failure":
            (attempt / "last-message.txt").write_bytes(b"not JSON")
        else:
            (attempt / "last-message.txt").write_bytes(integrity.canonical_bytes(output))
        return record

    def probes(self):
        probes = {}
        for job in self.jobs:
            phase = job["envelope"]["judge_packet"]["phase"]
            root = self.root / ("probe-" + phase)
            plan = r.prepare_probe(root, job, self.protocol, synthetic_material_declared=True,
                                   source_independent_handwritten=True, expected_protocol_sha256=self.protocol["sha256"])
            probes[phase] = r.run_probe(root, **self.kwargs(root, plan))["probe_receipt"]
        return probes

    def test_original_schemas_prompts_and_private_custody_are_frozen_offline(self):
        root, plan = self.prepare()
        self.assertEqual(len(self.custody_calls), 1)
        self.assertFalse(plan["automatic_dispatch"])
        for job in plan["jobs"]:
            directory = root / job["bundle"]
            self.assertEqual((directory / "schema.json").read_bytes(), integrity.canonical_bytes(c.response_schema(job["diagnostic_phase"])))
            self.assertEqual((directory / "prompt.txt").read_bytes(), c.prompt(self.jobs[0 if job["job_id"] == "a" else 1]["envelope"]).encode())
        self.assertEqual(self.a["judge_packet"]["records"], [])
        self.assertIsNone(self.a["judge_packet"]["prepared_side"])
        self.assertEqual(self.calls, [])

    def test_explicit_synthetic_declaration_and_external_protocol_pin_required(self):
        with self.assertRaises(ValueError):
            r.prepare_probe(self.root / "bad", self.jobs[0], self.protocol,
                            synthetic_material_declared=True, source_independent_handwritten=False,
                            expected_protocol_sha256=self.protocol["sha256"])
        with self.assertRaises(ValueError):
            r.prepare_packets(self.root / "bad", self.jobs, self.protocol, self.source_receipt,
                              expected_protocol_sha256="0" * 64)
        self.assertFalse((self.root / "bad").exists())

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_both_probes_fresh_review_and_no_dispute_no_adjudication(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            kwargs = self.kwargs(root, plan, probes)
            self.assertEqual(r.run_stage(root, "primary", **kwargs)["succeeded"], 2)
            self.assertEqual(r.run_stage(root, "independent_review", **kwargs)["succeeded"], 2)
            self.assertEqual(r.run_stage(root, "adjudication", **kwargs)["selected_jobs"], 0)
            self.assertEqual(len(self.calls), 6)
            self.assertEqual(self.calls[2]["prompt"], self.calls[4]["prompt"])
            self.assertEqual(self.calls[3]["prompt"], self.calls[5]["prompt"])
            self.assertEqual(len({x["cwd"] for x in self.calls}), 6)
            self.assertEqual(r.run_stage(root, "primary", **kwargs)["succeeded"], 2)
            self.assertEqual(len(self.calls), 6)

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_unknown_accepted_without_retry_and_one_disputed_logical_adjudication(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            kwargs = self.kwargs(root, plan, probes)
            r.run_stage(root, "primary", **kwargs)
            state = r._read(root / "execution" / "primary" / "a" / "job.json")
            native_receipt = Path(state["attempts"][0]["custody_receipt"])
            native_bytes = native_receipt.read_bytes()
            changed = r._read(native_receipt)
            changed["state"] = "held"
            r._write(native_receipt, changed)
            with self.assertRaises(ValueError):
                r.run_stage(root, "primary", **kwargs)
            self.assertEqual(len(self.calls), 4)
            native_receipt.write_bytes(native_bytes)
            self.outputs[("independent_review", "A")] = self.response("A", unknown=True)
            result = r.run_stage(root, "independent_review", **kwargs)
            self.assertEqual(result["unknown_or_failed_or_not_run"], 1)
            self.assertEqual(len(self.calls), 6)
            result = r.run_stage(root, "adjudication", **kwargs)
            self.assertEqual(result["selected_jobs"], 1)
            self.assertIn("opinion_1", self.calls[-1]["prompt"])
            self.assertNotIn(c.PROFILES["B"], self.calls[-1]["prompt"])
            r.run_stage(root, "adjudication", **kwargs)
            self.assertEqual(len(self.calls), 7)

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_format_retry_bounded_identity_mismatch_terminal_schema_failure_stops_refill(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            kwargs = self.kwargs(root, plan, probes)
            self.outputs[("primary", "A")] = ["format_failure", self.response("A")]
            self.outputs[("primary", "B")] = "identity_failure"
            result = r.run_stage(root, "primary", **kwargs)
            self.assertEqual(result["succeeded"], 1)
            self.assertEqual(len(self.calls), 5)
            r.run_stage(root, "primary", **kwargs)
            self.assertEqual(len(self.calls), 5)
        # Preserve this failed pool; a new synthetic pool has its own plan.
        self.jobs = [self.jobs[0], self.jobs[1]]
        self.outputs[("primary", "A")] = "schema_failure"
        second = self.root / "full-second"
        plan = r.prepare_packets(second, self.jobs, self.protocol, self.source_receipt,
                                 expected_protocol_sha256=self.protocol["sha256"])
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            kwargs = self.kwargs(second, plan, probes)
            result = r.run_stage(second, "primary", **kwargs)
            self.assertTrue(result["global_invalid_json_schema"])
            self.assertEqual(result["not_run"], 1)
            self.assertEqual(len(self.calls), 6)
            result = r.run_stage(second, "primary", **kwargs)
            self.assertEqual(result["not_run"], 1)
            self.assertEqual(len(self.calls), 6)

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_unavailable_inventory_stays_unknown_in_full_slot_denominator(self):
        self.extra_slots = [{"job_id": "unavailable-a", "phase": "A", "status": "term_inventory_unavailable"},
                            {"job_id": "zero-a", "phase": "A", "status": "not_assessed_zero_inventory"}]
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            result = r.run_stage(root, "primary", **self.kwargs(root, plan, probes))
            self.assertEqual(result["expected_jobs"], 2)
            self.assertEqual(result["expected_slots"], 4)
            self.assertEqual(result["unknown_or_failed_or_not_run"], 2)
            self.assertIsNone(result["root_count"])

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_missing_probe_and_tampered_raw_snapshot_authority_stop_before_dispatch(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            with self.assertRaises(ValueError):
                r.run_stage(root, "primary", **self.kwargs(root, plan, {"A": probes["A"]}))
            self.assertEqual(len(self.calls), 2)
            kwargs = self.kwargs(root, plan, probes)
            r.run_stage(root, "primary", **kwargs)
            canonical = root / "responses" / "primary" / "a.json"
            observed = canonical.read_bytes()
            canonical.unlink()
            r.run_stage(root, "primary", **kwargs)
            self.assertEqual(canonical.read_bytes(), observed)
            self.assertEqual(len(self.calls), 4)
            snapshot = root / "execution" / "primary" / "a" / "attempt-1" / "accepted-canonical.json"
            snapshot.write_bytes(observed + b" ")
            with self.assertRaises(ValueError):
                r.run_stage(root, "primary", **kwargs)
            self.assertEqual(len(self.calls), 4)
            snapshot.write_bytes(observed)
            authority = Path(kwargs["launch_receipt"]["path"])
            authority_bytes = authority.read_bytes()
            authority.write_bytes(authority_bytes + b" ")
            with self.assertRaises(ValueError):
                r.run_stage(root, "primary", **kwargs)
            self.assertEqual(len(self.calls), 4)
            authority.write_bytes(authority_bytes)
            raw = root / "execution" / "primary" / "a" / "attempt-1" / "last-message.txt"
            raw.write_bytes(raw.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                r.run_stage(root, "primary", **kwargs)
            self.assertEqual(len(self.calls), 4)

    def test_schema_failure_detector_reads_only_transport_errors(self):
        attempt = self.root / "detector"
        attempt.mkdir()
        log = attempt / "stdout.jsonl"
        log.write_bytes(b'{"type":"item.completed","item":{"type":"agent_message","text":"HTTP 400 invalid_json_schema"}}\n')
        self.assertFalse(r._schema_failure(attempt, {"returncode": 1}))
        log.write_bytes(b'{"type":"turn.failed","error":{"message":"HTTP 400 invalid_json_schema"}}\n')
        self.assertTrue(r._schema_failure(attempt, {"returncode": 1}))
        self.assertFalse(r._schema_failure(attempt, {"returncode": 0}))

    def test_signature_ignores_reason_and_local_sense_labels(self):
        response = self.response("A")
        changed = deepcopy(response)
        changed["summary_zh"] = "不同合成描述。"
        for row in changed["rows"]:
            for occurrence in row["occurrences"]:
                occurrence["sense_group"] = "renamed"
                occurrence["reason_zh"] = "不同合成说明。"
            for chain in row["chains"]:
                chain["sense_group"] = "renamed"
        self.assertEqual(r.structural_signature(response, "A"), r.structural_signature(changed, "A"))

    def test_authenticated_empty_jobs_keep_unknown_denominator_without_probe_or_call(self):
        self.jobs = []
        self.extra_slots = [{"job_id": "empty-a", "phase": "A", "status": "inventory_incomplete"},
                            {"job_id": "empty-b", "phase": "B", "status": "not_assessed_zero_inventory"}]
        self.source_receipt = self.write("synthetic-custody.json", {
            "synthetic_fixture_only": True, "jobs_sha256": c.object_hash(self.jobs)})
        root, plan = self.prepare()
        self.assertEqual(plan["jobs"], [])
        summary = r.summarize(root, expected_protocol_sha256=self.protocol["sha256"])
        self.assertEqual(summary["expected_slots"], 2)
        self.assertEqual(summary["unknown_or_failed_or_not_run"], 2)
        self.assertEqual(summary["succeeded"], 0)
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_schema_failure_drains_already_submitted_worker_and_stops_new_jobs(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
        second_seed = c.build_phase_a(self.fixture.frame(), self.fixture.scene["id"], c.SEEDS[1], self.fixture.deliveries())
        self.jobs.append({"job_id": "a-second-seed", "envelope": second_seed})
        self.source_receipt = self.write("synthetic-custody.json", {
            "synthetic_fixture_only": True, "jobs_sha256": c.object_hash(self.jobs)})
        self.outputs[("primary", "A")] = "schema_failure"
        barrier = threading.Barrier(2)
        def fake(guard, args, prompt, cwd, attempt, timeout):
            barrier.wait(timeout=10)
            return self.fake(guard, args, prompt, cwd, attempt, timeout)
        root, plan = self.prepare()
        kwargs = self.kwargs(root, plan, probes)
        kwargs["workers"] = 2
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=fake):
            summary = r.run_stage(root, "primary", **kwargs)
        self.assertTrue(summary["global_invalid_json_schema"])
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["not_run"], 1)
        self.assertEqual(len(self.calls), 4)
        receipts = [r._read(path) for path in (self.root / ".judge-dispatch-receipts").glob("*.json")]
        self.assertTrue(all(value["state"] == "drained_released" and value["active_callbacks"] == 0 for value in receipts))

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_failed_primary_slot_still_receives_fresh_independent_review(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            kwargs = self.kwargs(root, plan, probes)
            self.outputs[("primary", "B")] = "identity_failure"
            r.run_stage(root, "primary", **kwargs)
            review = r.run_stage(root, "independent_review", **kwargs)
            self.assertEqual(review["succeeded"], 2)
            self.assertEqual(review["scheduled_slots_reported"], 2)
            self.assertEqual(review["not_run"], 0)
            self.assertEqual(review["primary_unknown_slots"], 1)
            self.assertEqual(review["unknown_or_failed_or_not_run"], 1)
            self.assertEqual(len(self.calls), 6)
            self.assertEqual(self.calls[3]["prompt"], self.calls[5]["prompt"])
            adjudication = r.run_stage(root, "adjudication", **kwargs)
            self.assertEqual(adjudication["scheduled_slots_reported"], 2)
            self.assertEqual(adjudication["selected_jobs"], 0)
            self.assertEqual(adjudication["unknown_or_failed_or_not_run"], 1)
            self.assertEqual(len(self.calls), 6)

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_missing_primary_does_not_suppress_fresh_reviews_or_create_consensus(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            kwargs = self.kwargs(root, plan, probes)
            summary = r.run_stage(root, "independent_review", **kwargs)
            self.assertEqual(summary["succeeded"], 2)
            self.assertEqual(summary["primary_unknown_slots"], 2)
            self.assertEqual(summary["unknown_or_failed_or_not_run"], 2)
            self.assertEqual(len(self.calls), 4)
            self.assertFalse((root / "execution" / "primary").exists())
            self.assertNotIn("opinion_1", self.calls[-1]["prompt"])
            adjudication = r.run_stage(root, "adjudication", **kwargs)
            self.assertEqual(adjudication["selected_jobs"], 0)
            self.assertEqual(adjudication["unknown_or_failed_or_not_run"], 2)
            self.assertEqual(len(self.calls), 4)

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_original_shape_exact_evidence_mismatch_is_terminal_without_retry(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            probes = self.probes()
            root, plan = self.prepare()
            kwargs = self.kwargs(root, plan, probes)
            response = self.response("A")
            response["rows"][0]["occurrences"][0]["source_evidence"][0]["quote"] = "不存在的合成引文。"
            c._shape(response, c.response_schema("A"))
            self.outputs[("primary", "A")] = response
            summary = r.run_stage(root, "primary", **kwargs)
            self.assertEqual(summary["succeeded"], 1)
            state = r._read(root / "execution" / "primary" / "a" / "job.json")
            self.assertTrue(state["terminal_evidence_failure"])
            self.assertEqual(len(state["attempts"]), 1)
            self.assertEqual(len(self.calls), 4)
            r.run_stage(root, "primary", **kwargs)
            self.assertEqual(len(self.calls), 4)

    @unittest.skipUnless(os.name == "nt", "Native Windows shared-lock fixture")
    def test_authentic_synthetic_custody_to_prepare_probe_primary_and_review(self):
        # No custody stub here: real prepare/source-preparation/worker/delivery
        # APIs produce preserved exchange files through a socket-free client.
        patch.stopall()
        from .test_v2_consistency_custody import NativeConsistencyFixture
        fixture = NativeConsistencyFixture()
        self.addCleanup(fixture.close)
        frozen = fixture.freeze()
        self.protocol = self.write("protocol.json", {
            "version": r.PROTOCOL_VERSION, "state": "frozen_before_candidate_quality",
            "implementation": r.implementation(), "phases": r.phase_contracts(),
            "command_config": r.command_config(), "maximum_attempts": 2,
            "maximum_adjudication_attempts": 2,
            "adjudication_prompt_sha256": integrity.sha(r.ADJUDICATION_PROMPT.encode())})

        def unknown_response(envelope):
            packet = envelope["judge_packet"]
            source = {row["id"]: row["text"] for row in packet["source_context"]}
            rows = []
            if packet["phase"] == "A":
                for anchor in packet["anchors"]:
                    occurrences = []
                    for occurrence in anchor["occurrences"]:
                        uid = occurrence["id"]
                        occurrences.append({"occurrence_id": occurrence["occurrence_id"], "kind": "unknown",
                            "sense_group": None, "source_evidence": [{"id": uid, "quote": source[uid],
                                "start": 0, "end": len(source[uid])}], "reason_zh": "合成未判定。"})
                    rows.append({"anchor_id": anchor["anchor_id"], "occurrences": occurrences, "chains": []})
            else:
                for record in packet["records"]:
                    rows.append({"record_id": record["record_id"], "preparation_status": "unknown",
                        "source_evidence": [], "reason_zh": "合成未判定。", "root_proposition_zh": "合成未判定。",
                        "link_type": "unknown", "observations": [{"ids": packet["expected_ids"], "source_evidence": [],
                            "sides": {side: {"state": "unknown", "candidate_evidence": [], "reason_zh": "合成未判定。"}
                                      for side in ("L", "R")}, "relation": "unknown",
                            "proposition_zh": "合成未判定。", "reason_zh": "合成未判定。"}], "pattern": "unknown"})
            return {"profile": packet["profile"], "packet_sha256": envelope["packet_sha256"],
                    "status": "unknown", "rows": rows, "summary_zh": "只验证机械集成，不作实际语义判断。"}

        def fake(guard, args, prompt, cwd, attempt, timeout):
            job_id = attempt.parent.name
            run_root = attempt.parents[3]
            envelope = r._read(run_root / "bundles" / job_id / "envelope.json")
            phase, stage = envelope["judge_packet"]["phase"], attempt.parent.parent.name
            self.outputs[(stage, phase)] = unknown_response(envelope)
            return self.fake(guard, args, prompt, cwd, attempt, timeout)

        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=fake):
            probes = self.probes()
            root = self.root / "authentic-full"
            plan = r.prepare_packets(root, frozen["jobs"], self.protocol, frozen["receipt"],
                                     expected_protocol_sha256=self.protocol["sha256"])
            kwargs = self.kwargs(root, plan, probes)
            primary = r.run_stage(root, "primary", **kwargs)
            review = r.run_stage(root, "independent_review", **kwargs)
            self.assertEqual(primary["expected_slots"], len(frozen["expected_slots"]))
            self.assertEqual(primary["succeeded"], len(frozen["jobs"]))
            self.assertEqual(primary["unknown_or_failed_or_not_run"], len(frozen["expected_slots"]))
            self.assertEqual(review["succeeded"], len(frozen["jobs"]))
            self.assertEqual(len(self.calls), 2 + 2 * len(frozen["jobs"]))
            self.assertEqual(r.run_stage(root, "adjudication", **kwargs)["selected_jobs"], 0)


if __name__ == "__main__":
    unittest.main()
