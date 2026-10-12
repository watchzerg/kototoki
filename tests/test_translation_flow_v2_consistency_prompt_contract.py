"""Portable handwritten fixtures; native callbacks are fakes, never CLI calls."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_flow import test_v2_consistency as synthetic
from experiments.translation_flow import v2_consistency as helper
from experiments.translation_flow import v2_consistency_prompt_contract as adapter
from experiments.translation_flow import v2_consistency_runner as original
from experiments.translation_flow import v2_judge_dispatch as native
from experiments.translation_judge import integrity


class PromptContractTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[1] / ".local" / "consistency-contract-synthetic-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.shared = Path(self.temp.name)
        self.fixture = synthetic.ConsistencyTests()
        self.fixture.setUp()
        self.a = helper.build_phase_a(self.fixture.frame(), self.fixture.scene["id"],
                                     helper.SEEDS[0], self.fixture.deliveries())
        self.b = self.fixture.b_packet()
        self.material = self.write("handwritten-material.json", {
            "version": "hy30-consistency-handwritten-probe-material-v1",
            "source_independent_handwritten": True, "actual_source_scope": None,
            "translation_generation_seed": None, "semantic_accuracy_verified": False,
            "dispatch_authorized_by_this_material": False, "helper_sha256": original.HELPER_SHA256,
            "intended_calls": {"A": 1, "B": 1}, "frame": self.fixture.frame(),
            "envelopes": {"A": self.a, "B": self.b}})
        # Only this NEW adapter's external fixture pins are replaced in tests.
        # No original helper/runner/custody function or real material is patched.
        self.addCleanup(patch.stopall)
        patch.object(adapter, "MATERIAL_SHA256", self.material["sha256"]).start()
        self.terminal = self.write("terminal.json", {
            "schema": "hy30-judge-core-terminal-receipt-v1", "owner": "evaluation_custodian",
            "core_pipeline_terminal": True, "native_children_drained": True, "owned_cli_batches": []})
        patch.object(adapter, "TERMINAL_SHA256", self.terminal["sha256"]).start()
        self.protocol = self.write("protocol.json", adapter.protocol(self.material))
        exe = self.shared / "never-executed-fixture.exe"
        exe.write_bytes(b"synthetic identity only")
        self.exe = {"path": str(exe), "sha256": original._sha(exe)}
        self.calls = []
        self.output = None
        self.record_change = {}

    def write(self, name, value):
        path = self.shared / name
        original._write(path, value)
        return {"path": str(path), "sha256": original._sha(path)}

    def prepare(self, phase="A"):
        root = self.shared / ("new-probe-" + phase)
        plan = adapter.prepare_probe(root, phase, self.protocol,
                                     expected_protocol_sha256=self.protocol["sha256"])
        return root, plan

    def kwargs(self, root, plan, changes=None, guard_root=None):
        launch = {"version": adapter.LAUNCH_VERSION, "kind": "synthetic_probe", "phase": plan["phase"],
                  "probe_root": str(root.resolve()),
                  "run_plan_sha256": original._sha(root / "run-plan.json"), "protocol": self.protocol,
                  "material": self.material, "implementation": adapter.implementation(),
                  "phase_contract": adapter.phase_contracts()[plan["phase"]], "artifacts": plan["artifacts"],
                  "command_config": original.command_config(), "reviewed_safe": True, "calls_authorized": True,
                  "maximum_attempts": 1, "maximum_cli_workers": 1, "shared_cli_limit": 6,
                  "dispatch_owner": "evaluation_custodian", "global_lock": str(self.shared / ".judge-global-six.lock"),
                  "native_dispatch_sha256": adapter.implementation()["native_dispatch"],
                  "cli_version": "synthetic-test-only", "actual_source_access": False,
                  "source_custody_receipt": None, "probe_receipts": None,
                  "executable": self.exe, "terminal_receipt": self.terminal}
        launch.update(changes or {})
        pointer = self.write(root.name + "-launch.json", launch)
        return {"launch_receipt": pointer, "expected_launch_sha256": pointer["sha256"],
                "expected_protocol_sha256": self.protocol["sha256"], "executable": self.exe["path"],
                "cli_version": "synthetic-test-only", "invoke": native.execute,
                "dispatch_guard": lambda workers: native.CustodyGuard(
                    guard_root or self.shared, workers, Path(self.terminal["path"]), self.terminal["sha256"])}

    def fake(self, guard, args, prompt, cwd, attempt, timeout):
        self.calls.append({"args": args, "prompt": prompt, "cwd": str(cwd)})
        phase = "B" if self.b["judge_packet"]["profile"] in prompt else "A"
        value = self.output or (self.fixture.a_response(self.a) if phase == "A"
                                else self.fixture.b_response(self.b, all_unknown=True))
        (attempt / "stdin.bin").write_bytes(prompt.encode("utf-8"))
        (attempt / "stdout.jsonl").write_bytes(b"")
        (attempt / "stderr.txt").write_bytes(b"")
        (attempt / "last-message.txt").write_bytes(integrity.canonical_bytes(value))
        return {"transport_status": "completed", "returncode": 0, "returned_models": ["gpt-6.1-sol"],
                "returned_efforts": ["high"], "tool_events": [],
                "native_dispatch_sha256": guard.implementation_sha256, "custody_token": guard.token,
                "custody_workers_reserved": guard.workers, "custody_receipt": str(guard.owner_record),
                "containment": "suspended-assign-resume-kill-on-close-job", "native_drain_proven": True,
                "native_active_processes_after_drain": 0, **self.record_change}

    def test_trusted_packet_digest_and_profile_are_visible_verbatim(self):
        for envelope in (self.a, self.b):
            text = adapter.prompt(envelope)
            self.assertIn(envelope["packet_sha256"], text)
            metadata = integrity.strict_parse(text.split("TRUSTED_RESPONSE_METADATA\n")[1]
                                              .split("\nUNTRUSTED_JUDGE_PACKET\n")[0])
            self.assertEqual(metadata["packet_sha256"], envelope["packet_sha256"])
            self.assertEqual(metadata["profile"], envelope["judge_packet"]["profile"])
            self.assertIn("Copy its packet_sha256", text)

    def test_A_still_hides_custody_and_preparation(self):
        text = adapter.prompt(self.a)
        for secret in (*self.fixture.aliases, '"custody"', '"generation_seed"', "root_proposition_zh"):
            self.assertNotIn(secret, text)
        packet = integrity.strict_parse(text.split("\nUNTRUSTED_JUDGE_PACKET\n")[1])
        self.assertEqual(packet, self.a["judge_packet"])

    def test_B_explains_exact_labels_and_unproven_roots_without_semantic_oracle(self):
        text = adapter.prompt(self.b)
        for phrase in ("MUST copy root_proposition_zh exactly", "never proof of the same root",
                       "link_type=unknown", "top-level status=unknown", "every expected cue ID exactly once"):
            self.assertIn(phrase, text)
        self.assertNotIn("将翅膀误译为脚", text)

    def test_original_schema_and_frozen_implementation_pins_are_preserved(self):
        identity = adapter.implementation()
        self.assertEqual(identity["helper"], original.HELPER_SHA256)
        self.assertEqual(identity["driver"], adapter.FROZEN_RUNNER_SHA256)
        self.assertEqual(identity["custody"], adapter.FROZEN_CUSTODY_SHA256)
        for phase, contract in adapter.phase_contracts().items():
            digest = integrity.sha(integrity.canonical_bytes(helper.response_schema(phase)))
            self.assertEqual(contract["original_schema_sha256"], digest)
            self.assertEqual(contract["submitted_schema_sha256"], digest)

    def test_original_validator_rejects_digest_mismatch_without_repair(self):
        value = self.fixture.a_response(self.a)
        value["packet_sha256"] = "f" * 64
        before = deepcopy(value)
        with self.assertRaisesRegex(ValueError, "packet identity"):
            helper.validate_response(self.a, value)
        self.assertEqual(value, before)

    def test_original_B_validator_retains_exact_root_label_requirement(self):
        value = self.fixture.b_response(self.b)
        value["rows"][0]["observations"][0]["proposition_zh"] += "另一命题"
        with self.assertRaisesRegex(ValueError, "different propositions"):
            helper.validate_response(self.b, value)

    def test_honest_unknown_retains_full_B_scope(self):
        value = self.fixture.b_response(self.b, all_unknown=True)
        self.assertEqual(helper.validate_response(self.b, value)["status"], "unknown")
        value["rows"][0]["observations"].pop()
        with self.assertRaisesRegex(ValueError, "covered once"):
            helper.validate_response(self.b, value)

    def test_known_absence_still_requires_direct_output_evidence(self):
        value = self.fixture.b_response(self.b)
        row = value["rows"][0]["observations"][0]
        side = next(key for key, item in row["sides"].items() if item["state"] == "absent")
        row["sides"][side]["candidate_evidence"] = []
        with self.assertRaisesRegex(ValueError, "direct output evidence"):
            helper.validate_response(self.b, value)

    def test_prepare_is_offline_fresh_and_uses_pinned_original_envelope(self):
        root, plan = self.prepare()
        self.assertFalse(plan["automatic_dispatch"])
        self.assertEqual(self.calls, [])
        self.assertEqual(original._read(root / "envelope.json"), self.a)
        self.assertEqual((root / "schema.json").read_bytes(), integrity.canonical_bytes(helper.response_schema("A")))
        self.assertEqual((root / "prompt.txt").read_text(encoding="utf-8"), adapter.prompt(self.a))
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_bad_protocol_pin_fails_before_directory_creation(self):
        root = self.shared / "bad"
        with self.assertRaises(ValueError):
            adapter.prepare_probe(root, "A", self.protocol, expected_protocol_sha256="0" * 64)
        self.assertFalse(root.exists())

    def test_new_root_cannot_use_another_shared_lock(self):
        with self.assertRaisesRegex(ValueError, "shared custody root"):
            adapter.prepare_probe(self.shared / "other" / "probe", "A", self.protocol,
                                  expected_protocol_sha256=self.protocol["sha256"])

    def test_snapshot_tampering_blocks_before_native_guard(self):
        root, plan = self.prepare()
        kwargs = self.kwargs(root, plan)
        (root / "implementation" / "prompt_contract_adapter.py").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            adapter.run_probe(root, **kwargs)
        self.assertFalse((root / "execution").exists())

    def test_same_phase_sibling_cannot_reuse_plan_or_exact_launch(self):
        import shutil
        root, plan = self.prepare()
        kwargs = self.kwargs(root, plan)
        sibling = self.shared / "same-phase-sibling"
        shutil.copytree(root, sibling)
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            with self.assertRaisesRegex(ValueError, "plan identity changed"):
                adapter.run_probe(sibling, **kwargs)
        self.assertEqual(self.calls, [])
        self.assertFalse((sibling / "execution").exists())
        shutil.rmtree(sibling)
        sibling_plan = adapter.prepare_probe(sibling, "A", self.protocol,
                                            expected_protocol_sha256=self.protocol["sha256"])
        self.assertEqual(sibling_plan["probe_root"], str(sibling.resolve()))
        self.assertNotEqual(original._sha(root / "run-plan.json"), original._sha(sibling / "run-plan.json"))
        # Even a separately prepared same-phase sibling has no authority from
        # the original launch, and fails before opening the native guard.
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            with self.assertRaisesRegex(ValueError, "launch authority"):
                adapter.run_probe(sibling, **kwargs)
        self.assertEqual(self.calls, [])
        self.assertFalse((sibling / "execution").exists())

    def test_launch_probe_root_is_checked_independently_of_plan_hash(self):
        root, plan = self.prepare()
        kwargs = self.kwargs(root, plan, {"probe_root": str(self.shared / "other-probe")})
        with self.assertRaisesRegex(ValueError, "launch authority"):
            adapter.run_probe(root, **kwargs)
        self.assertEqual(self.calls, [])
        self.assertFalse((root / "execution").exists())

    def test_foreign_invoke_is_rejected_without_execution(self):
        root, plan = self.prepare()
        kwargs = self.kwargs(root, plan)
        kwargs["invoke"] = lambda *args: None
        with self.assertRaisesRegex(ValueError, "Unchanged native"):
            adapter.run_probe(root, **kwargs)

    @unittest.skipUnless(os.name == "nt", "Native Windows custody fixture")
    def test_two_phases_fresh_drained_and_never_reused(self):
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            for phase in ("A", "B"):
                root, plan = self.prepare(phase)
                kwargs = self.kwargs(root, plan)
                state = adapter.run_probe(root, **kwargs)
                self.assertEqual(state["status"], "succeeded", state.get("error"))
                self.assertEqual(state["attempts"], 1)
                receipt = original._read(Path(state["native_record"]["custody_receipt"]))
                self.assertEqual(receipt["state"], "drained_released")
                self.assertEqual(receipt["active_callbacks"], 0)
                raw = Path(state["accepted_raw_response"]).read_bytes()
                self.assertEqual(integrity.sha(raw), state["accepted_raw_response_sha256"])
                self.assertEqual(helper.validate_response(self.a if phase == "A" else self.b,
                                 original._read(root / "response.json"))["status"],
                                 "assessed" if phase == "A" else "unknown")
                with self.assertRaisesRegex(ValueError, "reuse is prohibited"):
                    adapter.run_probe(root, **kwargs)
        self.assertEqual(len(self.calls), 2)

    @unittest.skipUnless(os.name == "nt", "Native Windows custody fixture")
    def test_schema_valid_bad_digest_is_saved_failure_without_repair_or_retry(self):
        root, plan = self.prepare()
        self.output = self.fixture.a_response(self.a)
        self.output["packet_sha256"] = "0" * 64
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            state = adapter.run_probe(root, **self.kwargs(root, plan))
        self.assertEqual(state["status"], "judge_failed")
        self.assertIn("packet identity", state["error"])
        self.assertEqual(original._read(root / "execution/attempt-1/last-message.txt"), self.output)
        self.assertFalse((root / "response.json").exists())
        self.assertEqual(len(self.calls), 1)

    @unittest.skipUnless(os.name == "nt", "Native Windows custody fixture")
    def test_unproven_drain_prevents_acceptance(self):
        root, plan = self.prepare()
        self.record_change = {"native_drain_proven": False}
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            state = adapter.run_probe(root, **self.kwargs(root, plan))
        self.assertEqual(state["status"], "judge_failed")
        self.assertFalse((root / "response.json").exists())

    @unittest.skipUnless(os.name == "nt", "Native Windows custody fixture")
    def test_guard_at_new_private_root_cannot_dispatch(self):
        root, plan = self.prepare()
        other = self.shared / "private-custody"
        other.mkdir()
        with patch.object(native.CustodyGuard, "_execute", autospec=True, side_effect=self.fake):
            state = adapter.run_probe(root, **self.kwargs(root, plan, guard_root=other))
        self.assertEqual(state["status"], "judge_failed")
        self.assertEqual(self.calls, [])

    def test_wrong_launch_settings_fail_before_attempt(self):
        for changes in ({"maximum_attempts": 2}, {"maximum_cli_workers": 6}, {"calls_authorized": False},
                        {"actual_source_access": True}, {"reviewed_safe": 1},
                        {"command_config": {"model": "other", "effort": "high"}}):
            with self.subTest(changes=changes):
                root, plan = self.prepare()
                with self.assertRaisesRegex(ValueError, "launch authority"):
                    adapter.run_probe(root, **self.kwargs(root, plan, changes))
                self.assertFalse((root / "execution").exists())
                # Delete only a verified disposable synthetic temporary child.
                import shutil
                shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
