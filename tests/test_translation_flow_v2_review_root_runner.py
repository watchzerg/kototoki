"""Offline synthetic byte chains; callbacks never launch CLI/native/model processes."""
from copy import deepcopy
import ast
import json
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from experiments.translation_judge import integrity
from experiments.translation_flow import v2_review_root_evidence as helper
from experiments.translation_flow import v2_review_root_runner as runner
from tests.test_translation_flow_v2_review_root_evidence import response, root_record
from tests.test_translation_flow_v2_review_root_evidence import NativeFixture


class RootRunnerCallbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="f8-root-offline-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = self.directory / "runner"
        self.root.mkdir()
        self.packet = {
            "schema": helper.PACKET_VERSION, "profile": helper.PROFILE, "task_stage": "evidence",
            "pair_alias": "anon-" + "a" * 32,
            "context": [{"id": "synthetic-cue", "text": "彼は来ない。\r\n合成例。"}],
            "scored_ids": ["synthetic-cue"],
            "phases": {"phase_A": {"synthetic-cue": "他会来。"},
                       "phase_B": {"synthetic-cue": "他不会来。"}},
            "accepted_evidence": [], "hypotheses": [],
        }
        self.protocol = {
            "model": "gpt-6.1-sol", "effort": "high", "adapter_sha256": runner.ADAPTER_SHA256,
            "frame_sha256": "1" * 64,
            "transport_settings": {"model": "gpt-6.1-sol", "effort": "high", "cli_version": "synthetic-no-cli",
                                   "executable": "synthetic-never-executed.exe", "surface": "codex-cli",
                                   "tool_policy": "disabled", "fresh_session": True},
        }
        self.protocol_pointer = runner._new(self.directory / "protocol.json", self.protocol)
        registration = runner._new(self.directory / "registration.json", {"synthetic_material_declared": True})
        self.source = self.directory / "synthetic-source.bin"
        self.source.write_bytes(b"handwritten synthetic dependency; no corpus content")
        self.code_copy = self.directory / "synthetic-code-snapshot.py"
        self.code_copy.write_bytes(Path(runner.__file__).read_bytes())
        self.context = {"protocol": self.protocol_pointer, "registration": registration,
                        "command_config": runner._command_config(), "launch_dependencies": [registration],
                        "implementation": {"runner_snapshot": runner._identity(self.code_copy)}}
        private = {"pair_key": "synthetic-pair", "phase_order": ["before", "after"],
                   "upstream_complete": True, "frame_sha256": "1" * 64,
                   "packet_sha256": helper.object_hash(self.packet)}
        self.job = runner._bundle(self.root, self.packet, private, self.protocol_pointer, self.protocol,
                                  [runner._identity(self.source)])
        self.launch = runner._new(self.directory / "external-launch.json", {"synthetic_fake_callback_only": True})
        self.stop = threading.Event()
        self.calls = []

    def callback(self, values, *, returncode=0, stdout=None, mutation=None, stdin_transform=None):
        """Write retained fake transport bytes and assert actual submitted inputs."""
        def execute(args, prompt, cwd, attempt, timeout):
            self.calls.append(attempt)
            self.assertEqual(timeout, 2)
            self.assertEqual(prompt.encode("utf-8"), helper.prompt(self.packet).encode("utf-8"))
            self.assertEqual((attempt / "prompt.txt").read_bytes(), prompt.encode("utf-8"))
            self.assertEqual((attempt / "schema.json").read_bytes(),
                             integrity.canonical_bytes(helper.response_schema(self.packet["task_stage"])))
            schema_path = Path(args[args.index("--output-schema") + 1])
            self.assertTrue(schema_path.is_relative_to(cwd))
            self.assertEqual(schema_path.read_bytes(), (attempt / "schema.json").read_bytes())
            self.assertNotIn("private.json", " ".join(args))
            stdin = prompt.encode("utf-8")
            (attempt / "stdin.bin").write_bytes(stdin_transform(stdin) if stdin_transform else stdin)
            (attempt / "stdout.jsonl").write_bytes(stdout if stdout is not None else b'{"type":"synthetic-transport"}\n')
            (attempt / "stderr.txt").write_bytes(b"")
            value = values[min(len(self.calls) - 1, len(values) - 1)]
            (attempt / "last-message.txt").write_bytes(value if isinstance(value, bytes) else integrity.canonical_bytes(value))
            if mutation:
                mutation(attempt)
            return {"transport_status": "completed", "returncode": returncode, "native_root_pid": 123,
                    "native_drain_proven": True, "native_active_processes_after_drain": 0,
                    "containment": "suspended-assign-resume-kill-on-close-job",
                    "returned_models": ["gpt-6.1-sol"], "returned_efforts": ["high"],
                    "tool_events": [], "usage_events": []}
        return execute

    def run_job(self, execute, **kwargs):
        return runner._run_job(self.root, self.job, self.context, self.protocol, execute=execute,
                               timeout=2, launch=self.launch, stop=self.stop, **kwargs)

    def test_actual_rendered_response_binding_is_copied_not_computed(self):
        submitted = runner._inputs(self.root, self.job, self.context, self.protocol)[2].decode("utf-8")
        binding = json.loads(submitted.split("\nRESPONSE_BINDING:\n", 1)[1].split("\nPACKET:\n", 1)[0])
        self.assertEqual(binding, {"profile": helper.PROFILE, "task_stage": "evidence",
                                  "pair_alias": self.packet["pair_alias"],
                                  "packet_sha256": helper.object_hash(self.packet)})
        self.assertEqual(json.loads(submitted.split("\nPACKET:\n", 1)[1]), self.packet)
        self.assertIn("copy", submitted.lower())

    def test_valid_unknown_accepts_once_and_resume_dispatches_zero(self):
        value = response(self.packet)
        value.update(status="unknown", uncertainties=[{"ids": self.packet["scored_ids"],
                                                       "reason_zh": "合成合法未知，用于传输测试。"}])
        state = self.run_job(self.callback([value]))
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(len(self.calls), 1)
        accepted, _ = runner._accepted(self.root, self.job, self.context, self.protocol)
        self.assertEqual(accepted, value)
        def forbidden(*args):
            self.fail("accepted resume must not execute any callback")
        resumed = self.run_job(forbidden)
        self.assertTrue(resumed["resumed"])
        self.assertEqual(len(self.calls), 1)

    def test_format_failure_retries_same_input_then_accepts(self):
        state = self.run_job(self.callback([b'{"incomplete":', response(self.packet)]))
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual([a["attempt"] for a in state["attempts"]], [1, 2])
        self.assertEqual(state["attempts"][0]["failure_class"], "format")
        self.assertEqual(self.calls[0].joinpath("stdin.bin").read_bytes(), self.calls[1].joinpath("stdin.bin").read_bytes())

    def test_format_failure_stops_at_two_and_resume_does_not_add_budget(self):
        state = self.run_job(self.callback([b"not-json"]))
        self.assertEqual(state["status"], "judge_failed")
        self.assertEqual(len(self.calls), 2)
        resumed = self.run_job(lambda *args: self.fail("two-attempt job must not run again"))
        self.assertTrue(resumed["resumed"])
        self.assertEqual(len(self.calls), 2)

    def test_well_shaped_wrong_quote_is_terminal_without_retry(self):
        value = response(self.packet)
        value["roots"] = [root_record(self.packet)]
        value["roots"][0]["source_anchors"][0]["quote"] = "合成不存在的引用"
        state = self.run_job(self.callback([value]))
        self.assertEqual(state["status"], "judge_failed")
        self.assertTrue(state["terminal_no_retry"])
        self.assertEqual(len(self.calls), 1)

    def test_well_shaped_wrong_machine_identity_is_terminal(self):
        value = response(self.packet)
        value["packet_sha256"] = "0" * 64
        state = self.run_job(self.callback([value]))
        self.assertEqual(state["attempts"][0]["failure_class"], "source_quote_coverage_or_identity")
        self.assertTrue(state["terminal_no_retry"])
        self.assertEqual(len(self.calls), 1)

    def test_schema_transport_error_stops_even_with_returncode_zero(self):
        event = (json.dumps({"type": "error", "error": {"code": "invalid_json_schema", "status": 400}}) + "\n").encode()
        state = self.run_job(self.callback([response(self.packet)], stdout=event))
        self.assertEqual(state["global_stop"], "invalid_json_schema")
        self.assertEqual(state["status"], "judge_failed")
        self.assertTrue(self.stop.is_set())
        self.assertEqual(len(self.calls), 1)

    def test_assistant_schema_error_words_do_not_trip_transport_circuit(self):
        value = response(self.packet)
        value.update(status="unknown", uncertainties=[{"ids": self.packet["scored_ids"],
                                                       "reason_zh": "合成文本包含 invalid_json_schema 400。"}])
        stdout = (json.dumps({"type": "item.completed", "item": {"type": "agent_message",
                            "text": "synthetic invalid_json_schema 400"}}) + "\n").encode()
        state = self.run_job(self.callback([value], stdout=stdout))
        self.assertEqual(state["status"], "succeeded")
        self.assertFalse(self.stop.is_set())
        self.assertEqual(len(self.calls), 1)

    def test_integrity_drift_is_checked_before_retry_on_returncode_one(self):
        def drift(_):
            self.source.write_bytes(b"changed direct dependency")
        with self.assertRaises(runner.IntegrityDrift):
            self.run_job(self.callback([b"not-json"], returncode=1, mutation=drift))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.stop.is_set())
        ledger = runner._read(self.root / "execution" / self.job["job_id"] / "job.json")
        self.assertEqual(ledger["attempts"][0]["failure_class"], "integrity_drift")

    def test_crlf_reencoding_actual_stdin_is_rejected(self):
        with self.assertRaises(runner.IntegrityDrift):
            self.run_job(self.callback([response(self.packet)], stdin_transform=lambda b: b.replace(b"\n", b"\r\n")))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.stop.is_set())

    def test_raw_and_canonical_tampering_rejects_resume(self):
        state = self.run_job(self.callback([response(self.packet)]))
        for field in ("accepted_raw_response", "response", "accepted_canonical_snapshot"):
            with self.subTest(field=field):
                path = Path(state[field])
                original = path.read_bytes()
                try:
                    path.write_bytes(b"{}")
                    with self.assertRaises(ValueError):
                        self.run_job(lambda *args: self.fail("tampered acceptance must not dispatch"))
                finally:
                    path.write_bytes(original)
        self.assertEqual(len(self.calls), 1)

    def test_dependency_source_code_and_hash_tampering_blocks_callback(self):
        for path in (self.source, self.code_copy):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                try:
                    path.write_bytes(b"changed synthetic dependency")
                    with self.assertRaises(ValueError):
                        self.run_job(lambda *args: self.fail("drifted dependency must not dispatch"))
                finally:
                    path.write_bytes(original)
        context = deepcopy(self.context)
        self.context["protocol"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            self.run_job(lambda *args: self.fail("bad external hash must not dispatch"))
        self.context = context
        self.assertEqual(self.calls, [])

    def test_launch_command_config_drift_blocks_callback(self):
        self.context["command_config"]["effort"] = "xhigh"
        with self.assertRaises(ValueError):
            self.run_job(lambda *args: self.fail("changed launch command must not dispatch"))
        self.assertEqual(self.calls, [])

    def test_stage_inventory_allows_disjoint_review_additions_but_rejects_evidence_extra(self):
        runner._new(self.root / "receipts/evidence/preparation.json", {"synthetic": True})
        files = runner._inventory(self.root, runner.PREFIXES["evidence"])
        pointer = runner._new(self.root / "stage-seals/evidence.json", {
            "schema": "f8-root-stage-terminal-inventory-v1", "stage": "evidence", "files": files})
        runner._new(self.root / "bundles/hypothesis_review/synthetic/packet.json", {"synthetic": True})
        runner._seal(self.root, "evidence", pointer, pointer["sha256"])
        runner._new(self.root / "execution/evidence/unregistered/extra.json", {"synthetic": True})
        with self.assertRaises(runner.IntegrityDrift):
            runner._seal(self.root, "evidence", pointer, pointer["sha256"])

    def test_inherited_schema_stop_blocks_future_stage_without_erasing_fixed_slots(self):
        runner._new(self.root / "receipts/evidence/preparation.json", {"jobs": [self.job]})
        state = runner._state(self.root, self.job, self.protocol)
        state["global_stop"] = "invalid_json_schema"
        runner._live(self.root / "execution" / self.job["job_id"] / "job.json", state)
        with self.assertRaises(runner.AdmissionBlocked):
            runner._inherited_stop(self.root)
        self.assertEqual(runner._read(self.root / "execution" / self.job["job_id"] / "job.json")["status"], "not_run")

    def test_native_drain_must_match_each_actual_lease_not_an_unrelated_receipt(self):
        custody = self.directory / "evaluation-only"
        common = {"schema": "hy30-native-judge-custody-v1", "owner": "evaluation_custodian", "state": "drained_released",
                  "active_callbacks": 0, "owned_job_objects": 0, "workers_reserved": 1,
                  "global_lock": str(custody / ".judge-global-six.lock"),
                  "module_sha256": runner.implementation()["native_dispatch"]["sha256"]}
        good = runner._new(custody / "native-drain-good.json", {**common, "token": "1" * 32})
        unrelated = runner._new(custody / "native-drain-unrelated.json", {**common, "token": "2" * 32})
        state = {"attempts": [{"custody_token": "1" * 32, "custody_receipt": good["path"],
                              "native_dispatch_sha256": common["module_sha256"], "custody_workers_reserved": 1}]}
        registration = {"custody_root": str(custody), "kind": "actual"}
        self.assertEqual(runner._drain_lineage([good], registration, [state]), [good])
        with self.assertRaises(runner.AdmissionBlocked):
            runner._drain_lineage([unrelated], registration, [state])
        bad = deepcopy(state)
        bad["attempts"][0]["custody_receipt"] = unrelated["path"]
        with self.assertRaises(runner.IntegrityDrift):
            runner._drain_lineage([good], registration, [bad])

    def test_probe_one_attempt_format_failure_never_uses_two_attempt_budget(self):
        state = self.run_job(self.callback([b"not-json"]), maximum_attempts=1)
        self.assertEqual(state["status"], "judge_failed")
        self.assertEqual(len(self.calls), 1)
        self.run_job(lambda *args: self.fail("probe bound cannot reset"), maximum_attempts=1)


class RootRunnerUpstreamDrainTests(unittest.TestCase):
    """Only metadata seams are stubbed; original V8 equality body is executed."""
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="f8-three-drains-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.custody = self.base / "evaluation-only"
        self.custody.mkdir()
        self.roots, self.drains, self.executions = {}, {}, {}
        for index, seed in enumerate(helper.SEEDS):
            root = self.base / str(seed)
            root.mkdir()
            self.roots[str(seed)] = root
            rows = [{"candidate_alias": "synthetic", "window_id": str(i)} for i in range(96)]
            for name in ("expected.jsonl", "final.jsonl"):
                (root / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            self.drains[str(seed)] = runner._new(self.base / f"drain-{seed}.json", {
                "schema": "hy30-native-judge-custody-v1", "owner": "evaluation_custodian",
                "state": "drained_released", "active_callbacks": 0, "owned_job_objects": 0,
                "module_sha256": runner.implementation()["native_dispatch"]["sha256"],
                "workers_reserved": 1, "global_lock": str(self.custody / ".judge-global-six.lock"),
                "token": f"{index + 1:032x}"})
            self.executions[str(seed)] = runner._new(self.base / f"execution-{seed}.json", {
                "state": "required_fresh_judgments_completed", "native_drain_receipt": self.drains[str(seed)],
                "inventory": [], "launch_receipt": {"synthetic": True}})
        self.registration = {"custody_root": str(self.custody),
            "phase_roots": {seed: str(root) for seed, root in self.roots.items()},
            "phase_code": {}, "native_frame": {"path": str(self.base / "synthetic-frame.json"), "sha256": "0" * 64}}

    def seal(self, drains):
        with patch.object(runner, "_registration", return_value=self.registration), \
                patch.object(runner, "_native_proofs", return_value=[]), \
                patch.object(helper, "_code_pins", return_value={}), \
                patch.object(helper.evaluation, "validate_prepared", side_effect=lambda root, **kw: {"seed": int(root.name)}), \
                patch.object(helper, "_accepted_phases", return_value=({}, None)), \
                patch.object(helper, "_used_evidence", return_value=None):
            return runner.seal_upstream_phases({}, registered_sha256="synthetic",
                                               drained_receipts_by_seed=drains)

    def test_exact_three_distinct_original_leases_are_preserved(self):
        sealed = self.seal(self.drains)
        for seed in helper.SEEDS:
            phase = runner._read(runner._pointer(sealed["seals"][str(seed)]))
            self.assertEqual(phase["native_drain_receipt"], self.drains[str(seed)])
        self.assertEqual(sealed["root_calls"], 0)
        self.assertFalse(sealed["automatic_dispatch"])

    def test_missing_extra_or_integer_seed_keys_write_no_seals(self):
        for drains in ({str(helper.SEEDS[0]): self.drains[str(helper.SEEDS[0])]},
                       self.drains | {"extra": next(iter(self.drains.values()))},
                       {int(seed): value for seed, value in self.drains.items()}):
            with self.subTest(keys=list(drains)), self.assertRaises(runner.AdmissionBlocked):
                self.seal(drains)
            self.assertTrue(all(not (root / "root-phase-inventory.json").exists() for root in self.roots.values()))

    def test_invalid_last_seed_drain_rejects_before_any_output(self):
        bad = runner._new(self.base / "active-drain.json", {
            **runner._read(runner._pointer(self.drains[str(helper.SEEDS[-1])])), "active_callbacks": 1})
        drains = self.drains | {str(helper.SEEDS[-1]): bad}
        with self.assertRaises(runner.AdmissionBlocked):
            self.seal(drains)
        self.assertTrue(all(not (root / "root-phase-inventory.json").exists() for root in self.roots.values()))

    def test_actual_v8_cohort_body_accepts_original_leases_and_rejects_substitution(self):
        controller = Path(__file__).resolve().parents[1] / (
            ".local/translation-evaluation/hy30-flow-v2-20261008/evaluation-only/methods/run_registered_screening_v8.py")
        if not controller.exists():
            self.skipTest("private V8 controller unavailable; public per-seed mechanics tested separately")
        self.assertEqual(runner._sha(controller), "91a59cc3aeb696a15e2a3f0676d942a3b23919c00f73b21136dd003fdc4c2335")
        sealed = self.seal(self.drains)
        pins = SimpleNamespace(synthetic_metadata_only=True, f8_phase_frame=self.registration["native_frame"])
        phase_registration = runner._new(self.base / "phase-registration.json", {
            "version": "registered-screening-v8-side-phase-seals-v1",
            "state": "root_reviewed_all_three_side_phase_seals", "controller": runner._identity(controller),
            "pins": vars(pins), "seals": sealed["seals"], "execution_terminals": self.executions})
        verified = []
        namespace = {"__file__": str(controller), "Path": Path, "SEEDS": helper.SEEDS,
            "e": helper.e, "bound": runner._pointer, "pointer": runner._identity,
            "verify_authority": lambda pins: {}, "verify_f8_frame": lambda authority: None,
            "f8_side_target": lambda seed: self.roots[str(seed)],
            "side_terminal_path": lambda seed: Path(self.executions[str(seed)]["path"]),
            "root_evidence": SimpleNamespace(_code_pins=lambda pins: {}, _phase_inventory=lambda *args: None),
            "ROOT": self.custody, "exact_inventory": lambda *args, **kw: None,
            "_private_side_seal": lambda target, **kw: verified.append((target, kw)) or {"synthetic_seal": True}}
        tree = ast.parse(controller.read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "seal_f8_side_cohort")
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(controller), "exec"), namespace)
        result = namespace["seal_f8_side_cohort"](pins=pins, phase_registration=phase_registration)
        self.assertEqual(result["new_calls"], 0)
        self.assertEqual(len(verified), 3)
        self.assertEqual([kw["custody_receipt"] for _, kw in verified], [self.drains[str(s)] for s in helper.SEEDS])
        # The real cohort's original-execution equality remains independent authority.
        path = runner._pointer(sealed["seals"][str(helper.SEEDS[0])])
        value = runner._read(path)
        value["native_drain_receipt"] = self.drains[str(helper.SEEDS[-1])]
        path.write_bytes(integrity.canonical_bytes(value))
        changed = deepcopy(runner._read(runner._pointer(phase_registration)))
        changed["seals"][str(helper.SEEDS[0])] = runner._identity(path)
        changed_registration = runner._new(self.base / "substituted-registration.json", changed)
        verified.clear()
        with self.assertRaisesRegex(ValueError, "cannot substitute the original side native drain"):
            namespace["seal_f8_side_cohort"](pins=pins, phase_registration=changed_registration)
        self.assertEqual(verified, [])


class RootRunnerPredispatchResumeTests(unittest.TestCase):
    """Run the real stage scheduler with explicit authority/guard test doubles."""
    def setUp(self):
        self.fixture = RootRunnerCallbackTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.custody = f.directory / "evaluation-only"
        self.terminal = runner._new(f.directory / "terminal.json", {"synthetic_terminal": True})
        self.registration = {"kind": "actual", "custody_root": str(self.custody), "terminal_receipt": self.terminal}
        self.pins = runner.implementation()
        f.context["implementation"]["native_dispatch"] = self.pins["native_dispatch"]
        self.manifest = {"jobs": [f.job], "synthetic_incomplete_frame": True}
        self.preparation = runner._new(f.root / "receipts/evidence/preparation.json", self.manifest)
        runner._new(f.root / "common/seal.json", {"synthetic_barrier": True})
        self.drains = {}
        for label, token in (("A", "1" * 32), ("B", "2" * 32), ("C", "3" * 32)):
            self.drains[label] = runner._new(f.directory / f"lease-{label}.json", {
                "schema": "hy30-native-judge-custody-v1", "owner": "evaluation_custodian",
                "state": "drained_released", "active_callbacks": 0, "owned_job_objects": 0,
                "module_sha256": self.pins["native_dispatch"]["sha256"], "workers_reserved": 1,
                "global_lock": str(self.custody / ".judge-global-six.lock"), "token": token})
        self.lease = {"custody_token": "1" * 32, "custody_receipt": self.drains["A"]["path"],
                      "native_dispatch_sha256": self.pins["native_dispatch"]["sha256"], "custody_workers_reserved": 1}
        f.run_job(f.callback([b"synthetic-format-failure"]), maximum_attempts=1, lease=self.lease)
        f.calls.clear()
        # No __enter__, lock, native child, or Windows JobObject is invoked.
        self.guard = object.__new__(runner.native.CustodyGuard)
        for name, value in {"entered": True, "closing": False, "root": self.custody.resolve(),
            "owner": "evaluation_custodian", "workers": 1, "implementation_sha256": self.pins["native_dispatch"]["sha256"],
            "terminal_receipt": runner._pointer(self.terminal), "terminal_sha256": self.terminal["sha256"],
            "token": "2" * 32, "owner_record": Path(self.drains["B"]["path"])}.items():
            setattr(self.guard, name, value)

    def admission(self, receipts, *, version=2):
        f = self.fixture
        inventory = runner._new(f.directory / f"resume-{version}-{len(receipts)}.json", {
            "schema": "f8-root-unsealed-stage-resume-inventory-v1", "stage": "evidence",
            "files": runner._inventory(f.root, runner.PREFIXES["evidence"])})
        value = {"schema": f"f8-root-stage-external-admission-v{version}", "stage": "evidence", "root": str(f.root),
            "common": runner._identity(f.root / "common/seal.json"), "preparation": self.preparation,
            "implementation": f.context["implementation"], "registration": f.context["registration"],
            "protocol": f.context["protocol"], "custody_root": str(self.custody), "terminal_receipt": self.terminal,
            "workers": 1, "timeout_seconds": 2, "maximum_attempts": 2, "resume_inventory": inventory,
            "compatibility_probe": {"synthetic_custom_probe": True, "sha256": "0" * 64}}
        value["resume_drain_receipt" if version == 1 else "resume_drain_receipts"] = receipts[0] if version == 1 else receipts
        return runner._new(f.directory / f"admission-{version}-{len(receipts)}.json", value)

    def run_stage(self, admission):
        f = self.fixture
        probe = {"schema": "f8-root-synthetic-compatibility-probe-v1", "compatible": True,
                 "implementation": self.pins, "actual_corpus_used": False, "jobs": 1, "maximum_attempts": 1,
                 "profile": helper.PROFILE}
        with patch.object(runner, "_barrier", return_value=(f.context, self.registration, None, None, f.protocol)), \
                patch.object(runner, "_manifest", return_value=self.manifest), \
                patch.object(runner, "validate_compatibility_probe", return_value=probe), \
                patch.object(runner.native, "_ACTIVE_GUARD", self.guard), \
                patch.object(runner.native, "execute", f.callback([response(f.packet)])):
            return runner.run_stage(f.root, "evidence", admission_pointer=admission,
                                    registered_admission_sha256=admission["sha256"], custody_guard=self.guard)

    def test_unrelated_positive_drain_blocks_before_real_stage_callback(self):
        admission = self.admission([self.drains["C"]])
        with self.assertRaises(runner.AdmissionBlocked):
            self.run_stage(admission)
        self.assertEqual(self.fixture.calls, [])
        self.assertFalse((self.fixture.root / "execution/evidence" / self.fixture.packet["pair_alias"] / "attempt-2").exists())

    def test_original_lease_allows_exact_one_remaining_attempt_v1(self):
        admission = self.admission([self.drains["A"]], version=1)
        result = self.run_stage(admission)
        self.assertFalse(result["global_stop"])
        self.assertEqual(len(self.fixture.calls), 1)
        ledger = runner._read(self.fixture.root / "execution" / self.fixture.job["job_id"] / "job.json")
        self.assertEqual(len(ledger["attempts"]), 2)
        self.assertEqual([a["custody_token"] for a in ledger["attempts"]], ["1" * 32, "2" * 32])
        # Offline sealing must authenticate the retained pre-resume A ledger,
        # while the separate final seal lineage also covers the new B attempt.
        runner._admission(self.fixture.root, "evidence", admission, admission["sha256"],
                          self.fixture.context, self.registration, self.manifest, dispatch=False)

    def test_existing_attempt_without_resume_authority_blocks_entire_stage(self):
        f = self.fixture
        value = runner._read(runner._pointer(self.admission([self.drains["A"]])))
        value.update(resume_drain_receipts=[], resume_inventory=None)
        admission = runner._new(f.directory / "no-resume-authority.json", value)
        with self.assertRaises(runner.AdmissionBlocked):
            self.run_stage(admission)
        self.assertEqual(f.calls, [])

    def test_cumulative_v2_requires_every_previous_lease_before_retry(self):
        f = self.fixture
        ledger = f.root / "execution" / f.job["job_id"] / "job.json"
        state = runner._read(ledger)
        # A second prior job adds another lease without resetting this job's budget.
        second = deepcopy(state)
        second["job_id"] = "evidence/second-synthetic"
        second["attempts"][0].update(custody_token="2" * 32, custody_receipt=self.drains["B"]["path"])
        runner._new(f.root / "execution/evidence/second-synthetic/job.json", second)
        missing = self.admission([self.drains["A"]])
        with self.assertRaises(runner.AdmissionBlocked):
            self.run_stage(missing)
        self.assertEqual(f.calls, [])
        complete = self.admission([self.drains["A"], self.drains["B"]])
        self.run_stage(complete)
        self.assertEqual(len(f.calls), 1)


class RootRunnerProjectionTests(unittest.TestCase):
    def setUp(self):
        self.pair = {"pair_key": "synthetic-projection", "mechanically_eligible": True,
            "upstream_complete": True,
            "source": {"context": [{"id": "cue", "text": "彼は来ない。"}], "scored_ids": ["cue"]},
            "views": {"before": {"translations": {"cue": "他会来。"}},
                      "after": {"translations": {"cue": "他不会来。"}}},
            "obligations": [{"native_phase": "before", "ids": ["cue"], "type": "mistranslation",
                             "severity": "major", "source_evidence": "彼は来ない。", "candidate_evidence": "他会来。"}]}

    def test_pure_projection_keeps_orientations_and_does_not_alias_authenticated_data(self):
        for order in (("before", "after"), ("after", "before")):
            with self.subTest(order=order):
                packet, private = helper._packet(self.pair, "1" * 64, "anon-" + "b" * 32, order)
                self.assertEqual(packet["phases"]["phase_A"], self.pair["views"][order[0]]["translations"])
                self.assertEqual(private["phase_order"], list(order))
                self.assertEqual(packet["accepted_evidence"][0]["phase"], "phase_A" if order[0] == "before" else "phase_B")
                original = deepcopy(self.pair)
                packet["phases"]["phase_A"]["cue"] = "调用者修改的合成副本"
                packet["accepted_evidence"][0]["severity"] = "minor"
                self.assertEqual(self.pair, original)

    def test_mechanical_null_projection_is_not_a_callable_semantic_pair(self):
        pair = deepcopy(self.pair)
        pair["views"]["after"]["translations"][pair["source"]["scored_ids"][0]] = None
        pair["mechanically_eligible"] = False
        with self.assertRaises(ValueError):
            helper._packet(pair, "1" * 64, "anon-" + "c" * 32, ("before", "after"))


class RootRunnerLifecycleTests(unittest.TestCase):
    """Full fixed frame, synthetic registered proof, fake terminal ledgers only."""
    @classmethod
    def setUpClass(cls):
        cls.native = NativeFixture()
        cls.frame, args = cls.native.authenticate("root-runner-lifecycle")
        cls.native_args = args
        cls.base, cls.root = cls.native.root, cls.native.root / "root-runner-complete"
        cls.executable = cls.base / "never-executed-synthetic.exe"
        cls.executable.write_bytes(b"synthetic CLI identity only; not a runnable executable")
        # A code-pinned fixture adapter exercises the integration ABI. It does
        # not claim to implement/replay the actual 734-batch native admission.
        cls.proof_code = cls.base / "synthetic-proof-adapter.py"
        cls.proof_code.write_text(
            'from pathlib import Path\nimport json, hashlib\n'
            'VERSION="hy30-native-review-main-admission-v1"\n'
            'PROFILE="hy30-main-source-review-private-v1"\n'
            'def validate_receipt(pointer, *, registered_receipt_sha256):\n'
            '    raw=Path(pointer["path"]).read_bytes()\n'
            '    if hashlib.sha256(raw).hexdigest()!=registered_receipt_sha256: raise ValueError("fixture receipt hash")\n'
            '    value=json.loads(raw)\n'
            '    if value["synthetic_not_native_qualification"] is not True: raise ValueError("fixture scope")\n'
            '    for p in value["inventory"]:\n'
            '        if hashlib.sha256(Path(p["path"]).read_bytes()).hexdigest()!=p["sha256"]: raise ValueError("fixture inventory")\n'
            '    return value\n', encoding="utf-8")
        proofs = {}
        native_frame = runner._read(runner._pointer(args[0]))
        for seed, scope_ptr in zip(helper.SEEDS, native_frame["scopes"]):
            scope = runner._read(runner._pointer(scope_ptr))
            run = runner._pointer(scope["original_generation_cost_identity"])
            delivered = runner._pointer(scope["original_delivery"])
            metadata = runner._read(delivered)
            packed = metadata["packed_mapping"]
            trial = runner._new(cls.base / f"synthetic-trial-{seed}.json", {"seed": seed, "no_actual_generation": True})
            proof = {"synthetic_not_native_qualification": True,
                     "root_binding": {"seed": seed, "source_manifest": scope["source_manifest"],
                        "original_run": scope["original_generation_cost_identity"], "original_delivery": scope["original_delivery"],
                        "original_cost_identity": runner._identity(delivered.parent / "costs.json")},
                     "retained": {"packed": packed, "run": runner._identity(run),
                                  **{k: runner._identity(run.parent / f"{k}.jsonl") for k in ("inputs", "ledger", "results", "schedule")}},
                     "trial": {"start": trial, "completion": trial}, "source_inputs": runner._identity(cls.native.fixture.scene_path),
                     "source_qualification": runner._identity(cls.native.fixture.source / "freeze-manifest.json"),
                     "generation_attempt_status": "delivered",
                     "inventory": [runner._identity(p) for p in sorted(run.parent.rglob("*")) if p.is_file()]}
            proofs[str(seed)] = runner._new(cls.base / f"synthetic-proof-{seed}.json", proof)
        cls.protocol = {"schema": "f8-root-hypothesis-review-protocol-v1", "profile": helper.PROFILE,
            "frame_sha256": cls.frame._hash, "split_registration_sha256": cls.native.registration["sha256"],
            "adapter_sha256": runner.ADAPTER_SHA256, "model": "gpt-6.1-sol", "effort": "high", "attempts_per_job_max": 2,
            "classification_adjudication_jobs": 0, "expected_pairs": 144, "custody_root": str(cls.native.custody_root),
            "transport_settings": {"cli_version": "synthetic-no-cli", "executable": str(cls.executable), "surface": "codex-cli",
                "model": "gpt-6.1-sol", "effort": "high", "tool_policy": "disabled", "fresh_session": True}}
        protocol = runner._new(cls.base / "synthetic-root-protocol.json", cls.protocol)
        cls.registration = runner._new(cls.base / "synthetic-native-registration.json", {
            "schema": "f8-root-native-registration-v1", "kind": "synthetic", "synthetic_material_declared": True,
            "custody_root": str(cls.native.custody_root), "native_frame": args[0], "split_registration": cls.native.registration,
            "phase_roots": {str(k): str(v) for k, v in args[1].items()}, "phase_seals": {str(k): v for k, v in args[2].items()},
            "phase_code": cls.native.code, "native_proof_code": runner._identity(cls.proof_code), "native_review_proofs": proofs,
            "root_protocol": protocol, "terminal_receipt": cls.native.drain, "cli_executable": runner._identity(cls.executable)})
        cls.aliases = {p["pair_key"]: f"anon-{i:032x}" for i, p in enumerate(cls.frame._data["pairs"], 1)}
        cls.orders = {p["pair_key"]: ["after", "before"] if i % 2 else ["before", "after"]
                      for i, p in enumerate(cls.frame._data["pairs"])}

    @classmethod
    def tearDownClass(cls):
        cls.native.close()

    def admission(self, root, stage, preparation):
        context = runner._read(root / "common/context.json")
        return runner._new(self.base / f"synthetic-{root.name}-{stage}-admission.json", {
            "schema": "f8-root-stage-external-admission-v1", "stage": stage, "root": str(root),
            "common": runner._identity(root / "common/seal.json"), "preparation": preparation,
            "implementation": context["implementation"], "registration": self.registration,
            "protocol": context["protocol"], "custody_root": str(self.native.custody_root),
            "terminal_receipt": self.native.drain, "workers": 1, "timeout_seconds": 2,
            "maximum_attempts": 2, "resume_drain_receipt": None, "resume_inventory": None, "compatibility_probe": None})

    def test_a_full144_stage_barriers_and_dev90_withheld54_release(self):
        prepared = runner.prepare_packets(self.root, self.registration, registered_sha256=self.registration["sha256"],
                                          aliases=self.aliases, phase_orders=self.orders)
        self.assertEqual(prepared["expected_pairs"], 144)
        self.assertEqual(prepared["expected_root_job_slots"], 288)
        first = runner._read(runner._pointer(prepared["preparation"]))
        self.assertEqual(len(first["jobs"]), 144)
        context = runner._read(self.root / "common/context.json")
        calls = []
        def fake(args, prompt, cwd, attempt, timeout):
            calls.append(attempt)
            packet = json.loads(prompt.split("\nPACKET:\n", 1)[1])
            value = response(packet)
            value.update(status="unknown", uncertainties=[{"ids": packet["scored_ids"], "reason_zh": "完整合成 fixture 的合法未知；不是模型准确性。"}])
            for name, data in (("stdin.bin", prompt.encode()), ("stdout.jsonl", b""), ("stderr.txt", b""),
                               ("last-message.txt", integrity.canonical_bytes(value))):
                (attempt / name).write_bytes(data)
            return {"transport_status": "completed", "returncode": 0, "native_root_pid": 123,
                    "native_drain_proven": True, "native_active_processes_after_drain": 0,
                    "containment": "suspended-assign-resume-kill-on-close-job",
                    "returned_models": [], "returned_efforts": [], "tool_events": []}
        seals = {}
        for stage in helper.STAGES:
            if stage == "hypothesis_review":
                prepared = runner.prepare_hypothesis_review(self.root, evidence_seal=seals["evidence"],
                    registered_evidence_seal_sha256=seals["evidence"]["sha256"])
            manifest = runner._read(runner._pointer(prepared["preparation"]))
            self.assertEqual(len(manifest["expected_slots"]), 144)
            admission = self.admission(self.root, stage, prepared["preparation"])
            # One executed fake accepted-unknown chain; every other slot remains
            # genuine root not_run. The predefined second slot is still present.
            for i, job in enumerate(manifest["jobs"]):
                if i == 0:
                    runner._run_job(self.root, job, context, self.protocol, execute=fake, timeout=2,
                                    launch=admission, stop=threading.Event())
                else:
                    runner._live(self.root / "execution" / job["job_id"] / "job.json", runner._state(self.root, job, self.protocol))
            sealed = runner.seal_stage(self.root, stage, admission_pointer=admission,
                    registered_admission_sha256=admission["sha256"], drained_receipt=self.native.drain)
            seals[stage] = sealed["seal"]
            # External seal admission gives a public read-only resume. No guard
            # and no callback are needed because all original bytes are sealed.
            resumed = runner.run_stage(self.root, stage, admission_pointer=admission,
                registered_admission_sha256=admission["sha256"], custody_guard=None, registered_stage_seal=sealed["seal"])
            self.assertEqual(resumed["root_calls"], 0)
        self.assertEqual(len(calls), 2)
        finished = runner.finish(self.root, stage_seals=seals,
            registered_stage_seal_sha256={k: v["sha256"] for k, v in seals.items()})
        resumed_finish = runner.finish(self.root, stage_seals=seals,
            registered_stage_seal_sha256={k: v["sha256"] for k, v in seals.items()},
            registered_terminal_inventory=finished["terminal_inventory"])
        self.assertEqual(resumed_finish["root_calls"], 0)
        self.assertEqual(resumed_finish["cost"], finished["cost"])
        # A interrupted final sealing command retains immutable cost bytes.
        # External registration is required; the second duration cannot replace it.
        (self.root / "root-terminal-inventory.json").unlink()
        (self.root / "private/closure.json").unlink()
        recovered = runner.finish(self.root, stage_seals=seals,
            registered_stage_seal_sha256={k: v["sha256"] for k, v in seals.items()}, registered_existing_cost=finished["cost"])
        self.assertEqual(recovered["cost"], finished["cost"])
        self.assertEqual(recovered["terminal_inventory"], finished["terminal_inventory"])
        snapshot = runner._read(runner._pointer(finished["snapshot"]))
        self.assertEqual(len(snapshot["records"]), 144)
        self.assertTrue(all(not r["complete"] for r in snapshot["records"]))
        self.assertTrue(all(r["net_presence_bounds"] == [-1, 1] for r in snapshot["records"]))
        cost = runner._read(runner._pointer(finished["cost"]))
        self.assertEqual(len(cost["original_trials_count_once"]), 3)
        self.assertTrue(all(p["full_cost_count_once"]["path"].endswith("costs.json") for p in cost["original_trials_count_once"]))
        released = runner.release_development(self.root, self.base / "dev-only-release.json",
            terminal_inventory=finished["terminal_inventory"], registered_terminal_sha256=finished["terminal_inventory"]["sha256"],
            registered_snapshot_object_sha256=snapshot["snapshot_sha256"])
        value = runner._read(runner._pointer(released["development_release"]))
        self.assertEqual(value["expected_pairs"], 90)
        self.assertEqual(value["expected_root_job_slots"], 180)
        self.assertEqual(len(value["records"]), 90)
        self.assertFalse(value["heldout_quality_released"])
        self.assertNotIn("original_trials_count_once", value)
        self.assertNotIn("private", value)
        with self.assertRaises(runner.AdmissionBlocked):
            runner.release_development(self.root, self.root / "leaking-release.json", terminal_inventory=finished["terminal_inventory"],
                registered_terminal_sha256=finished["terminal_inventory"]["sha256"], registered_snapshot_object_sha256=snapshot["snapshot_sha256"])
        runner._new(self.root / "private/extra.json", {"synthetic_extra": True})
        with self.assertRaises(runner.IntegrityDrift):
            runner.release_development(self.root, self.base / "must-not-release.json", terminal_inventory=finished["terminal_inventory"],
                registered_terminal_sha256=finished["terminal_inventory"]["sha256"], registered_snapshot_object_sha256=snapshot["snapshot_sha256"])
        (self.root / "private/extra.json").unlink()

    def test_b_public_projection_parity_and_mutation_rejection(self):
        pair = self.frame._data["pairs"][0]
        for order in (("before", "after"), ("after", "before")):
            self.assertEqual(helper._packet(pair, self.frame._hash, self.aliases[pair["pair_key"]], order),
                helper.build_evidence_packet(self.frame, pair["pair_key"], anonymous_alias=self.aliases[pair["pair_key"]], phase_order=order))
        original = deepcopy(pair)
        pair["views"]["before"]["translations"][pair["source"]["scored_ids"][0]] = "调用者修改认证输入"
        try:
            with self.assertRaises(ValueError):
                helper.build_evidence_packet(self.frame, pair["pair_key"], anonymous_alias=self.aliases[pair["pair_key"]], phase_order=("before", "after"))
        finally:
            pair.clear()
            pair.update(original)

    def test_c_upstream_not_run_is_administrative_unknown_without_relabeling(self):
        phase_root = self.native_args[1][helper.SEEDS[0]]
        ledger = next((phase_root / "judge-execution/primary").rglob("job.json"))
        original = ledger.read_bytes()
        seal_ptr = self.native_args[2][helper.SEEDS[0]]
        seal_path = runner._pointer(seal_ptr)
        old_seal = seal_path.read_bytes()
        try:
            value = runner._read(ledger)
            value["status"] = "not_run"
            ledger.write_bytes(integrity.canonical_bytes(value))
            seal = runner._read(seal_path)
            for row in seal["files"]:
                if phase_root / row["path"] == ledger:
                    row["sha256"] = runner._sha(ledger)
            seal_path.write_bytes(integrity.canonical_bytes(seal))
            reg = runner._read(runner._pointer(self.registration))
            reg["phase_seals"][str(helper.SEEDS[0])] = runner._identity(seal_path)
            with self.assertRaises(runner.AdmissionBlocked) as failed:
                runner._load_frame(reg)
            self.assertEqual(failed.exception.expected_pairs, 144)
            self.assertEqual(failed.exception.root_calls, 0)
            self.assertEqual(runner._read(ledger)["status"], "not_run")
        finally:
            ledger.write_bytes(original)
            seal_path.write_bytes(old_seal)

    def test_d_public_dispatch_cannot_accept_fake_guard_or_synthetic_full_pool(self):
        root = self.base / "root-runner-no-dispatch"
        prepared = runner.prepare_packets(root, self.registration, registered_sha256=self.registration["sha256"],
                                          aliases=self.aliases, phase_orders=self.orders)
        admission = self.admission(root, "evidence", prepared["preparation"])
        with self.assertRaises(runner.AdmissionBlocked):
            runner.run_stage(root, "evidence", admission_pointer=admission, registered_admission_sha256=admission["sha256"],
                             custody_guard=object())
        self.assertFalse((root / "execution/evidence").exists())


if __name__ == "__main__":
    unittest.main()
