"""Offline F5 adapter tests using handwritten text and fake native custody.

No corpus, retained candidate, reference, native process, GPU or network is used.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from experiments.translation_flow import v2_unit_diagnostics as helper
from experiments.translation_flow import v2_unit_runner_singleton as runner
from experiments.translation_flow import v2_judge_dispatch as native
from experiments.translation_judge import integrity


def handwritten_packet(phase="native_fidelity", *, control=False):
    groups = [{"group_id": "private-unit-SECRET", "source_ids": ["s1", "s2"],
               "text": " 甲😀\n乙。乙。 ", "evidence_ids": ["s1", "s2"], "uncertain": False}]
    if control:
        groups = [{"group_id": "private-cue-s1", "source_ids": ["s1"],
                   "text": " 甲😀\n", "evidence_ids": ["s1"], "uncertain": None},
                  {"group_id": "private-cue-s2", "source_ids": ["s2"],
                   "text": "乙。乙。 ", "evidence_ids": ["s2"], "uncertain": None}]
    packet = {"schema": helper.PACKET_SCHEMA, "phase": phase,
              "batch_id": "private-batch-SECRET", "seed": helper.SEEDS[0],
              "target_source_ids": ["s1", "s2"],
              "source_context": [{"id": "s1", "text": "  まだです。\n😀"},
                                 {"id": "s2", "text": "もう一度。もう一度。"}],
              "output_groups": groups, "scope": "full_fixed_source_batch_auxiliary_only"}
    if phase == "cue_attribution":
        packet["mapped_cues"] = [
            {"group_id": groups[0]["group_id"], "source_id": "s1", "target_span": [0, 4],
             "text": groups[0]["text"][:4], "ja_srt_index": 1, "start_ms": 100, "end_ms": 900},
            {"group_id": groups[0]["group_id"], "source_id": "s2", "target_span": [4, 9],
             "text": groups[0]["text"][4:9], "ja_srt_index": 2, "start_ms": 901, "end_ms": 1900}]
    return packet


def handwritten_response(packet, *, unresolved=False, error=False):
    value = {"packet_sha256": helper.canonical_sha256(packet),
             "assessment": "unresolved" if unresolved else
             ("assessable" if packet["phase"] == "native_fidelity" else "supported"),
             "reason": "Handwritten unresolved evidence" if unresolved else "Handwritten fixture",
             "errors": []}
    if packet["phase"] == "native_fidelity":
        value["native_semantic"] = None if unresolved else 3
    if error:
        source_id = packet["output_groups"][0]["source_ids"][0]
        value["errors"] = [{"root_id": "root-1", "group_id": packet["output_groups"][0]["group_id"],
                            "source_ids": [source_id], "severity": "major",
                            "source_evidence": [{"source_id": source_id, "quote": "まだです。"}],
                            "target_evidence": [{"start": 2, "end": 3, "quote": "😀"}],
                            "explanation": "Handwritten scope claim"}]
    return value


class FakeNative:
    """Retain native-shaped evidence without creating any operating-system process."""

    def __init__(self, testcase):
        self.case = testcase
        self.calls = []
        self.guards = []
        self.outcomes = []
        self.record_changes = {}
        self.receipt_changes = {}
        self.active = None

    def guard(self, root, workers, terminal_receipt, terminal_sha256, *, owner="evaluation_custodian"):
        fake = self

        class Guard:
            def __init__(self):
                self.root = Path(root).resolve()
                self.workers = workers
                self.owner = owner
                self.terminal_receipt = Path(terminal_receipt).resolve()
                self.terminal_sha256 = terminal_sha256
                self.token = "handwritten-custody-" + uuid.uuid4().hex
                self.implementation_sha256 = integrity.sha(Path(native.__file__).read_bytes())
                self.owner_record = self.root / ".judge-dispatch-receipts" / (self.token + ".json")
                self.entered = False

            def __enter__(self):
                fake.case.assertEqual(self.owner, "evaluation_custodian")
                fake.case.assertTrue(1 <= self.workers <= 6)
                native._receipt(self.terminal_receipt, self.terminal_sha256)
                fake.guards.append(self)
                fake.active = self
                self.entered = True
                self._record("held")
                return self

            def _record(self, state):
                value = {"schema": "hy30-native-judge-custody-v1", "owner": self.owner,
                         "token": self.token, "workers_reserved": self.workers, "shared_limit": 6,
                         "global_lock": str(self.root / ".judge-global-six.lock"), "state": state,
                         "terminal_receipt": str(self.terminal_receipt),
                         "terminal_sha256": self.terminal_sha256, "active_callbacks": 0,
                         "owned_job_objects": 0, "module_sha256": self.implementation_sha256}
                value.update(fake.receipt_changes)
                self.owner_record.parent.mkdir(parents=True, exist_ok=True)
                self.owner_record.write_bytes(integrity.canonical_bytes(value))

            def __exit__(self, *exception):
                self._record("drained_released")
                self.entered = False
                fake.active = None

        return Guard()

    def execute(self, args, prompt, cwd, attempt, timeout):
        self.case.assertIsNotNone(self.active, "execute requires the shared custody guard")
        self.case.assertTrue(Path(cwd).is_dir(), "fresh isolated cwd must exist while native execute runs")
        self.calls.append({"args": list(args), "prompt": prompt, "attempt": Path(attempt)})
        attempt = Path(attempt)
        packet = integrity.strict_parse((attempt / "packet.json").read_text(encoding="utf-8")) if (attempt / "packet.json").exists() else None
        if packet is None:
            schema_path = Path(args[args.index("--output-schema") + 1])
            schema = integrity.strict_parse(schema_path.read_text(encoding="utf-8"))
            digest = schema["properties"]["packet_sha256"]["const"]
            phase = "native_fidelity" if "native_semantic" in schema["properties"] else "cue_attribution"
            value = {"packet_sha256": digest, "assessment": "assessable" if phase == "native_fidelity" else "supported",
                     "reason": "Handwritten fake invocation", "errors": []}
            if phase == "native_fidelity":
                value["native_semantic"] = 3
        else:
            value = handwritten_response(packet)
        outcome = self.outcomes.pop(0) if self.outcomes else {}
        value = outcome.get("response", value)
        stdout = outcome.get("stdout", {"type": "turn.completed", "model": "gpt-6.1-sol", "reasoning_effort": "high"})
        (attempt / "stdin.bin").write_bytes(prompt.encode("utf-8"))
        (attempt / "stdout.jsonl").write_text(json.dumps(stdout) + "\n", encoding="utf-8")
        (attempt / "stderr.txt").write_text(outcome.get("stderr", ""), encoding="utf-8")
        last_message = Path(args[args.index("--output-last-message") + 1])
        last_message.write_bytes(value if isinstance(value, bytes) else integrity.canonical_bytes(value))
        guard = self.active
        record = {"transport_status": "completed", "returncode": 0, "returned_models": ["gpt-6.1-sol"],
                  "returned_efforts": ["high"], "tool_events": [], "usage_events": [], "elapsed_seconds": 0.01,
                  "native_dispatch_sha256": guard.implementation_sha256, "custody_token": guard.token,
                  "custody_workers_reserved": guard.workers, "custody_receipt": str(guard.owner_record),
                  "containment": "suspended-assign-resume-kill-on-close-job", "native_drain_proven": True,
                  "native_active_processes_after_drain": 0, "native_root_pid": 424242}
        record.update(runner.transport.event_evidence(json.dumps(stdout) + "\n"))
        record.update(self.record_changes)
        record.update(outcome.get("record", {}))
        if outcome.get("after"):
            outcome["after"]()
        return record

    def patches(self):
        fake = self

        class FakeGuard:
            def __init__(self, *args, **kwargs):
                self.delegate = fake.guard(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.delegate, name)

            def __enter__(self):
                self.delegate.__enter__()
                return self

            def __exit__(self, *exception):
                return self.delegate.__exit__(*exception)

        return patch.multiple(native, CustodyGuard=FakeGuard, execute=self.execute)


class UnitRunnerTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local" / "unit-runner-singleton-synthetic-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = FakeNative(self)
        self.launch_pins = {}
        self.probe_pins = {}

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(integrity.canonical_bytes(value))
        return {"path": str(path.resolve()), "sha256": integrity.sha(path.read_bytes())}

    def source_frame(self):
        batches = [{"batch_id": f"handwritten-batch-{number:03d}", "scene_id": "handwritten-scene",
                    "source_ids": [f"source-{number:03d}-a", f"source-{number:03d}-b"]} for number in range(84)]
        return {"schema": helper.FRAME_SCHEMA,
                "generation_seeds": list(helper.SEEDS), "batches": batches,
                "expected_slots": [{"seed": seed, "batch_id": batch["batch_id"],
                                    "scene_id": batch["scene_id"], "expected_source_ids": batch["source_ids"]}
                                   for seed in helper.SEEDS for batch in batches],
                "source_geometry": {"scenes": {"handwritten-scene": {
                    "context": [{"id": source_id, "text": "  まだです。\n😀" if i == 0 else "もう一度。もう一度。"}
                                for batch in batches for i, source_id in enumerate(batch["source_ids"])]}}},
                "selection_basis": "source_batch_intersection_before_outputs_units_or_grades",
                "primary_endpoint_changed": False, "new_independent_samples": False}

    def source_registration_fixture(self):
        frame = self.source_frame()
        self.frame_pointer = self.write("frame.json", frame)
        self.registration = self.write("registration.json", {"frame": self.frame_pointer})
        self.external = self.write("external.json", {"handwritten_registration": self.registration})
        algorithm = "sha256-canonical-domain-phase-seed-batch; ascending; ceil(84/5)=17 per seed"
        selection = runner.reliability_selection(frame["expected_slots"])
        self.reliability_proposal = self.write("source-reliability-proposal.json", {
            "registration": self.registration, "external_registration": self.external,
            "frame": self.frame_pointer, "slot_manifest": frame["expected_slots"],
            "selection": selection, "algorithm": algorithm})
        self.reliability_registration = self.write("source-reliability-root-registration.json", {
            "schema": "hy30-F5-source-reliability-root-registration-v1",
            "state": "source_selection_frozen_before_F5_generation_and_quality",
            "source_registration": self.registration, "external_registration": self.external,
            "source_frame": self.frame_pointer, "selection": selection,
            "fixed_slot_count": 252, "source_batches_per_seed": 84,
            "selected_per_seed_per_phase": 17, "paired_control_fidelity_same_slots": True,
            "candidate_native_root_exists_at_registration": False, "native_calls_authorized": False,
            "registered_at_utc": "2026-10-08T00:00:00+00:00",
            "proposal": self.reliability_proposal, "algorithm": algorithm})
        return frame

    def freeze_source_protocol(self, frame, *, reliability=None, expected=None, name="proposal.json"):
        reliability = self.reliability_registration if reliability is None else reliability
        expected = reliability["sha256"] if expected is None else expected
        with patch.object(runner.custody, "validate_registered_frame", return_value={"frame": frame}):
            return runner.freeze_protocol(registration=self.registration, external_registration=self.external,
                expected_registration_sha256=self.registration["sha256"], expected_external_sha256=self.external["sha256"],
                reliability_registration=reliability, expected_reliability_sha256=expected,
                output=self.root / name)

    def fixture_run(self, *, available=1, control=True, mapping=True, main_present=None):
        self.shared = self.root / "evaluation-only"
        self.shared.mkdir(exist_ok=True)
        frame = self.source_registration_fixture()
        proposal = self.freeze_source_protocol(frame)
        policy = runner._read(proposal)
        policy["state"] = "root_approved_no_implicit_calls"
        self.protocol = self.write("protocol.json", policy)
        main_present = bool(available) if main_present is None else main_present
        self.main_slots, self.costs, self.main_metadata = [], [], {}
        for seed in helper.SEEDS:
            for role in ("candidate", "control"):
                receipt = None
                if main_present:
                    cost = self.write(f"original-cost-{seed}-{role}.json", {"seed": seed, "role": role,
                                      "original_cost_count": 1})
                    self.costs.append(cost)
                    proof = {field: None for field in runner.custody.MAIN_FIELDS}
                    proof.update(schema=runner.custody.MAIN_PROOF_SCHEMA, seed=seed, role=role,
                                 cost_authority=cost, original_generation_cost_identity=cost)
                    self.main_metadata[(seed, role)] = proof
                    receipt = self.write(f"handwritten-main-{seed}-{role}.json", proof)
                self.main_slots.append({"seed": seed, "role": role, "receipt": receipt,
                                        "unavailable_reason": None if receipt else "Handwritten main not generated"})
        present = [{k: slot[k] for k in ("seed", "role", "receipt")} for slot in self.main_slots if slot["receipt"] is not None]
        self.material = {"main_receipts": present, "original_generation_cost_authorities": self.costs, "slots": []}
        for index, slot in enumerate(frame["expected_slots"]):
            views = {"native_packet": None, "c0_packet": None, "attribution_packet": None,
                     "native_state": "native_unavailable", "c0_state": "control_unavailable",
                     "attribution_state": "mapping_unavailable", "reason": "Handwritten missing main evidence"}
            if main_present and not available:
                views.update(reason="Handwritten original native generation failed", native_state="native_translation_failed",
                             status="translation_failed")
            if index < available:
                views["reason"] = None
                for key, phase, is_control in (("native_packet", "native_fidelity", False),
                        ("c0_packet", "native_fidelity", True), ("attribution_packet", "cue_attribution", False)):
                    if is_control and not control:
                        continue
                    if phase == "cue_attribution" and not mapping:
                        continue
                    packet = handwritten_packet(phase, control=is_control)
                    packet["batch_id"], packet["seed"] = slot["batch_id"], slot["seed"]
                    ids = dict(zip(("s1", "s2"), slot["expected_source_ids"], strict=True))
                    packet["target_source_ids"] = list(slot["expected_source_ids"])
                    packet["source_context"] = deepcopy(frame["source_geometry"]["scenes"]["handwritten-scene"]["context"])
                    for group in packet["output_groups"]:
                        group["source_ids"] = [ids[source_id] for source_id in group["source_ids"]]
                        group["evidence_ids"] = [ids[source_id] for source_id in group["evidence_ids"]]
                    for cue in packet.get("mapped_cues", []):
                        cue["source_id"] = ids[cue["source_id"]]
                    views[key] = packet
            self.material["slots"].append({"slot": slot, "views": views})
        self.custody = self.write("custody.json", self.material)
        self.control_seal = self.write("control-seal.json", {"handwritten_control_seal": True})
        self.candidate_seals = {seed: self.write(f"candidate-seal-{seed}.json",
            {"handwritten_candidate_seal": True, "seed": seed}) if main_present else None for seed in helper.SEEDS}
        self.registry_value = {"external_registration": self.external, "slots": [
            {**entry, "seal": self.control_seal if entry["role"] == "control" else self.candidate_seals[entry["seed"]],
             "authority": None} for entry in self.main_slots]}
        self.main_registry = self.write("main-registry.json", self.registry_value)
        self.addCleanup(patch.stopall)
        self.inventory_mock = patch.object(runner.custody, "validate_prepared_unit_auxiliary",
                                          side_effect=lambda *args, **kwargs: deepcopy(self.material)).start()
        self.registry_patch = patch.object(runner.main_router, "validate_registry", side_effect=lambda registry, expected_sha256:
                                          (runner._read(registry, expected_sha256), {}))
        self.factory_patch = patch.object(runner.main_router, "make_role_seed_main_validator",
            return_value=lambda receipt, *, seed, role, external_registration: deepcopy(self.main_metadata[(seed, role)]))
        self.registry_patch.start()
        self.factory_patch.start()
        self.run_plan = runner.prepare_run(custody_pointer=self.custody, expected_custody_sha256=self.custody["sha256"],
            registration=self.registration, external_registration=self.external, expected_main_slots=self.main_slots,
            main_registry=self.main_registry, expected_main_registry_sha256=self.main_registry["sha256"], protocol=self.protocol,
            expected_protocol_sha256=self.protocol["sha256"], output=self.shared / "aux-run")
        self.terminal = self.write("terminal.json", {"schema": "hy30-judge-core-terminal-receipt-v1",
            "owner": "evaluation_custodian", "core_pipeline_terminal": True,
            "native_children_drained": True, "owned_cli_batches": []})
        executable = self.root / "never-executed.exe"
        executable.write_bytes(b"handwritten executable identity, never launched")
        self.executable = runner.identity(executable)

    def phase(self, phase="native_fidelity", fidelity_seal=None):
        return runner.prepare_phase(run_plan=self.run_plan, expected_run_plan_sha256=self.run_plan["sha256"],
                                    phase=phase, fidelity_seal=fidelity_seal)

    def launch(self, phase, *, stage="primary", changes=None):
        probes = {name: self.native_probe(name) for name in runner.PHASES}
        value = {"schema": "hy30-F5-unit-singleton-launch-v1", "phase_plan": phase, "stage": stage,
                 "calls_authorized": True, "owner": "evaluation_custodian",
                 "implementation": runner.implementation(), "model": "gpt-6.1-sol", "effort": "high",
                 "maximum_workers": 6, "root": str(self.shared.resolve()),
                 "global_lock": str(self.shared / ".judge-global-six.lock"), "executable": self.executable,
                 "terminal_receipt": self.terminal, "probe_receipts": probes,
                 "reliability_registration": self.reliability_registration}
        value.update(changes or {})
        pointer = self.write(f"launch-{stage}-{len(list(self.root.glob('launch-*')))}.json", value)
        self.launch_pins[stage] = pointer
        return pointer

    def native_probe(self, phase):
        if phase in self.probe_pins:
            return self.probe_pins[phase]
        directory = self.shared / "handwritten-probes" / phase / "attempt-1"
        directory.mkdir(parents=True)
        packet, _ = runner._blind(handwritten_packet(phase), "handwritten-probe")
        packet_ptr = runner._write(directory / "packet.json", packet)
        schema_ptr = runner._write(directory / "schema.json", helper.response_schema(packet))
        prompt = runner._prompt(packet, "primary")
        (directory / "prompt.txt").write_bytes(prompt.encode("utf-8"))
        prompt_ptr = runner.identity(directory / "prompt.txt")
        launch_ptr = self.write(f"probe-launch-{phase}.json", {
            "schema": "hy30-F5-unit-singleton-probe-launch-v1", "phase": phase,
            "profile": runner.PROFILES[phase], "protocol": self.protocol,
            "implementation": runner.implementation(), "calls_authorized": True,
            "owner": "evaluation_custodian", "maximum_workers": 1, "model": "gpt-6.1-sol", "effort": "high",
            "executable": self.executable, "root": str(self.shared.resolve()),
            "terminal_receipt": self.terminal, "source_independent_handwritten": True})
        cwd = directory.parent / "isolated-empty-cwd"
        cwd.mkdir()
        args = runner.transport.command(self.executable["path"], cwd, directory / "schema.json", directory / "last-message.txt")
        probe_fake = FakeNative(self)
        with probe_fake.guard(self.shared, 1, self.terminal["path"], self.terminal["sha256"]):
            record = probe_fake.execute(args, prompt, cwd, directory, 1)
        accepted = integrity.accept_response(directory / "last-message.txt", directory / "response.json",
            lambda value: helper.parse_response(json.dumps(value, ensure_ascii=False), packet))
        accepted["response"] = str(directory / "response.json")
        record.update(attempt=1, status="succeeded", finished_at=runner.transport.utc(),
                      profile=runner.PROFILES[phase], packet_sha256=helper.canonical_sha256(packet),
                      command=args, isolated_cwd=str(cwd))
        attempt_ptr = runner._write(directory / "attempt.json", record)
        pointer = self.write(f"native-probe-{phase}.json", {
            "schema": "hy30-F5-unit-singleton-native-probe-v1", "state": "root_reviewed_native_probe", "phase": phase,
            "profile": runner.PROFILES[phase], "implementation": runner.implementation(), "protocol": self.protocol,
            "probe_launch": launch_ptr, "packet": packet_ptr, "schema_artifact": schema_ptr, "prompt": prompt_ptr,
            "attempt_record": attempt_ptr, "accepted": accepted,
            "attempt_inventory": [runner.identity(path) for path in sorted(directory.iterdir()) if path.is_file()],
            "exactly_one_fresh_attempt": True, "synthetic_material_declared": True,
            "source_independent_handwritten": True, "drained": True})
        self.probe_pins[phase] = pointer
        return pointer

    def dispatch(self, phase, launch, *, stage="primary", workers=1):
        with self.fake.patches():
            return runner.run_phase(phase_plan=phase, expected_phase_plan_sha256=phase["sha256"],
                launch=launch, expected_launch_sha256=launch["sha256"], workers=workers, stage=stage)

    def test_source_only_reliability_has_exact_per_seed_count_and_is_deterministic(self):
        slots = self.source_frame()["expected_slots"]
        chosen = runner.reliability_selection(slots)
        self.assertEqual(chosen, runner.reliability_selection(deepcopy(slots)))
        self.assertEqual(chosen, runner.reliability_selection(list(reversed(slots))))
        for phase in runner.PHASES:
            self.assertEqual(len(chosen[phase]), 51)
            self.assertEqual(len(set(chosen[phase])), 51)
            for seed in helper.SEEDS:
                self.assertEqual(sum(key.startswith(str(seed) + ":") for key in chosen[phase]), 17)
        for damaged in (slots[:-1], slots + [slots[0]], [slots[0]] * 252):
            with self.subTest(size=len(damaged)), self.assertRaises(ValueError):
                runner.reliability_selection(damaged)

    def test_protocol_requires_independent_source_reliability_pin_before_outputs(self):
        frame = self.source_registration_fixture()
        with patch.object(runner.custody, "validate_registered_frame", return_value={"frame": frame}):
            with self.assertRaises(TypeError):
                runner.freeze_protocol(registration=self.registration, external_registration=self.external,
                    expected_registration_sha256=self.registration["sha256"],
                    expected_external_sha256=self.external["sha256"], output=self.root / "missing.json")
        self.assertFalse((self.root / "missing.json").exists())
        with self.assertRaises(ValueError):
            self.freeze_source_protocol(frame, reliability={"path": self.reliability_registration["path"],
                                                          "sha256": "0" * 64})
        with self.assertRaises(ValueError):
            self.freeze_source_protocol(frame, expected="0" * 64)
        proposal = runner._read(self.freeze_source_protocol(frame))
        self.assertEqual(proposal["reliability_registration"], self.reliability_registration)
        self.assertEqual(proposal["reliability"], runner._read(self.reliability_registration)["selection"])
        self.assertEqual(proposal["generation_calls"], 0)
        self.assertEqual(self.fake.calls, [])

    def test_source_reliability_rejects_original_proposal_selection_drift(self):
        frame = self.source_registration_fixture()
        proposal = runner._read(self.reliability_proposal)
        proposal["selection"]["native_fidelity"][0] = "20261008:unregistered-batch"
        root = runner._read(self.reliability_registration)
        root["proposal"] = self.write("changed-reliability-proposal.json", proposal)
        changed = self.write("changed-reliability-root.json", root)
        with self.assertRaises(ValueError):
            self.freeze_source_protocol(frame, reliability=changed)
        self.assertFalse((self.root / "proposal.json").exists())

    def test_source_reliability_rejects_source_frame_or_expected_slots_mismatch(self):
        frame = self.source_registration_fixture()
        alternate = deepcopy(frame)
        alternate["expected_slots"][0]["expected_source_ids"] = ["other-source-a", "other-source-b"]
        alternate_pointer = self.write("other-frame.json", alternate)
        root = runner._read(self.reliability_registration)
        root["source_frame"] = alternate_pointer
        changed = self.write("other-frame-root.json", root)
        with self.assertRaises(ValueError):
            self.freeze_source_protocol(frame, reliability=changed)
        with self.assertRaises(ValueError):
            self.freeze_source_protocol(alternate)

    def test_source_reliability_rejects_chronology_without_explicit_timezone(self):
        frame = self.source_registration_fixture()
        root = runner._read(self.reliability_registration)
        root["registered_at_utc"] = "2026-10-08T00:00:00"
        changed = self.write("naive-time-root.json", root)
        with self.assertRaises(ValueError):
            self.freeze_source_protocol(frame, reliability=changed)

    def test_source_reliability_rejects_native_exists_or_calls_authorized(self):
        frame = self.source_registration_fixture()
        for field in ("candidate_native_root_exists_at_registration", "native_calls_authorized"):
            with self.subTest(field=field):
                root = runner._read(self.reliability_registration)
                root[field] = True
                changed = self.write(f"invalid-{field}-root.json", root)
                with self.assertRaises(ValueError):
                    self.freeze_source_protocol(frame, reliability=changed)

    def test_launch_requires_literal_approved_reliability_registration_pin(self):
        self.fixture_run()
        phase = self.phase()
        other = self.write("other-source-root.json", runner._read(self.reliability_registration))
        for pin in (None, other):
            with self.subTest(pin=pin):
                launch = self.launch(phase, changes={"reliability_registration": pin})
                with self.assertRaises(ValueError):
                    self.dispatch(phase, launch)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.fake.guards, [])

    def test_blinding_preserves_unicode_groups_map_and_times_without_private_labels(self):
        for phase in runner.PHASES:
            original = handwritten_packet(phase)
            original["reference"] = "MUST NOT COPY"
            original["fidelity_score"] = 4
            public, private = runner._blind(original, "opaque-batch")
            self.assertEqual(public["source_context"], original["source_context"])
            self.assertEqual(public["output_groups"][0]["text"], " 甲😀\n乙。乙。 ")
            self.assertEqual(private["original_packet_sha256"], helper.canonical_sha256(original))
            self.assertEqual(private["group_ids"], {"private-unit-SECRET": "g0000"})
            serialized = json.dumps(public, ensure_ascii=False)
            for hidden in ("SECRET", "seed", "reference", "fidelity_score", "MUST NOT COPY"):
                self.assertNotIn(hidden, serialized)
            if phase == "cue_attribution":
                self.assertEqual(public["mapped_cues"][0]["target_span"], [0, 4])
                self.assertEqual(public["mapped_cues"][1]["text"], "乙。乙。 ")
                self.assertEqual(public["mapped_cues"][1]["end_ms"], 1900)
                self.assertEqual(public["mapped_cues"][1]["group_id"], "g0000")
            else:
                self.assertNotIn("mapped_cues", public)

    def test_control_keeps_discrete_cue_groups_and_whole_batch_schema(self):
        original = handwritten_packet(control=True)
        public, private = runner._blind(original, "opaque-control")
        self.assertEqual(len(public["output_groups"]), 2)
        self.assertEqual([g["source_ids"] for g in public["output_groups"]], [["s1"], ["s2"]])
        self.assertEqual(len(private["group_ids"]), 2)
        self.assertEqual(helper.response_schema(public)["properties"]["native_semantic"]["maximum"], 4)

    def test_prompt_has_literal_profile_and_submitted_packet_sha(self):
        for phase in runner.PHASES:
            packet, _ = runner._blind(handwritten_packet(phase), "opaque")
            text = runner._prompt(packet, "review")
            contract = integrity.strict_parse(text.split("TRUSTED RESPONSE CONTRACT\n")[1].split("\nIndependently")[0])
            self.assertEqual(contract["packet_sha256"], helper.canonical_sha256(packet))
            self.assertEqual(contract["profile"], runner.PROFILES[phase])
            self.assertIn("do not compute a hash", contract["instruction"])
            self.assertEqual(integrity.strict_parse(text.split("ORIGINAL BLIND PACKET\n")[1]), packet)
            self.assertNotIn("SECRET", text)

    def test_known_missing_main_allowed_but_expected_present_missing_rejected(self):
        expected = [{"seed": seed, "role": role, "receipt": None, "unavailable_reason": "Not generated"}
                    for seed in helper.SEEDS for role in ("candidate", "control")]
        runner._main_slots(expected, [])
        expected[0].update(receipt={"path": "synthetic-present.json", "sha256": "a" * 64}, unavailable_reason=None)
        with self.assertRaisesRegex(ValueError, "missing"):
            runner._main_slots(expected, [])
        with self.assertRaises(ValueError):
            runner._main_slots(expected[:-1], [])

    def test_phase_retains_252_slots_but_504_and_252_view_limits(self):
        self.fixture_run(available=252)
        phase = self.phase()
        value = runner._read(phase)
        self.assertEqual(len(value["slots"]), 504)
        self.assertEqual(len(value["jobs"]), 504)
        self.assertEqual(value["logical_slots"], 252)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(runner._read(self.protocol)["maximum_primary_jobs"],
                         {"native_fidelity": 504, "cue_attribution": 252})

    def test_attribution_requires_fidelity_barrier_and_preserves_unavailable_tail(self):
        self.fixture_run(available=1)
        with self.assertRaises((ValueError, TypeError)):
            self.phase("cue_attribution")
        seal = self.write("undrained-fidelity.json", {"schema": "hy30-F5-unit-singleton-phase-seal-v1",
            "phase": "native_fidelity", "run_plan": self.run_plan, "drained": False, "logical_slots": 252})
        with self.assertRaisesRegex(ValueError, "seal"):
            self.phase("cue_attribution", seal)
        fidelity = runner._read(self.phase())
        self.assertEqual(len(fidelity["slots"]), 504)
        self.assertEqual(sum(s["status"] == "unavailable" for s in fidelity["slots"]), 502)
        self.assertTrue(all(s["reason"] for s in fidelity["slots"] if s["status"] == "unavailable"))

    def test_real_native_command_fake_execution_and_accepted_resume_zero_calls(self):
        self.fixture_run(available=1)
        phase = self.phase()
        launch = self.launch(phase)
        self.inventory_mock.reset_mock()
        completion = runner._read(self.dispatch(phase, launch))
        self.assertEqual(completion["actual_attempts"], 2)
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(self.inventory_mock.call_count, 2, "full custody inventory only at phase entry and exit")
        for call in self.fake.calls:
            self.assertIn("--ephemeral", call["args"])
            self.assertIn("--ignore-user-config", call["args"])
            self.assertEqual(call["args"][call["args"].index("--model") + 1], "gpt-6.1-sol")
            self.assertIn('model_reasoning_effort="high"', call["args"])
            self.assertEqual(call["args"][-1], "-")
        self.assertTrue(all(state["status"] == "succeeded" for state in completion["states"]))
        resumed = runner._read(self.dispatch(phase, launch))
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(resumed["actual_attempts"], 2)
        self.assertEqual(resumed["new_attempts"], 0)
        self.assertEqual(resumed["new_native_callbacks"], 0)
        self.assertEqual(self.fake.guards[0].root, self.shared.resolve())

    def test_format_and_transport_failures_retry_with_contiguous_locked_budget(self):
        self.fixture_run(control=False)
        phase = self.phase()
        launch = self.launch(phase)
        self.fake.outcomes = [{"response": b"{"}]
        completion = runner._read(self.dispatch(phase, launch))
        state = completion["states"][0]
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual([a["attempt"] for a in state["attempts"]], [1, 2])
        self.assertEqual([a["status"] for a in state["attempts"]], ["failed", "succeeded"])
        self.assertEqual(len(self.fake.calls), 2)

    def test_packet_hash_evidence_failure_is_terminal_without_retry(self):
        self.fixture_run(control=False)
        phase = self.phase()
        packet = runner._read(runner._read(phase)["jobs"][0]["packet"])
        response = handwritten_response(packet)
        response["packet_sha256"] = "0" * 64
        self.fake.outcomes = [{"response": response}]
        completion = runner._read(self.dispatch(phase, self.launch(phase)))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(completion["states"][0]["status"], "judge_failed")
        self.assertTrue(completion["states"][0]["terminal_failure"])

    def test_global_invalid_schema_stops_and_inherited_resume_does_not_dispatch(self):
        self.fixture_run(available=2, control=False)
        phase = self.phase()
        launch = self.launch(phase)
        self.fake.outcomes = [{"stdout": {"type": "turn.failed", "error": {"code": "invalid_json_schema"}},
                               "record": {"returncode": 1}}]
        completion = runner._read(self.dispatch(phase, launch))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(runner._read(completion["stop"])["reason"], "invalid_json_schema")
        self.dispatch(phase, launch)
        self.assertEqual(len(self.fake.calls), 1)

    def test_auth_failure_is_terminal_and_retains_unknown_usage(self):
        self.fixture_run(control=False)
        phase = self.phase()
        self.fake.outcomes = [{"stdout": {"type": "error", "code": "authentication_error"},
                               "record": {"returncode": 1}}]
        completion = runner._read(self.dispatch(phase, self.launch(phase)))
        self.assertEqual(len(self.fake.calls), 1)
        state = completion["states"][0]
        self.assertEqual(state["terminal_failure"], "access_failure")
        self.assertEqual(state["attempts"][0]["usage_events"], [])

    def test_launch_wrong_owner_model_root_worker_budget_rejected_before_call(self):
        self.fixture_run(control=False)
        phase = self.phase()
        for changes in ({"owner": "other"}, {"model": "other"}, {"maximum_workers": 7},
                        {"global_lock": str(self.shared / "private.lock")}, {"calls_authorized": False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.dispatch(phase, self.launch(phase, changes=changes))
        self.assertEqual(self.fake.calls, [])

    def test_native_returned_model_tools_or_drain_drift_cannot_be_accepted(self):
        self.fixture_run(control=False)
        phase = self.phase()
        self.fake.record_changes = {"returned_models": ["wrong-model"]}
        with self.assertRaisesRegex(ValueError, "Native CLI identity"):
            self.dispatch(phase, self.launch(phase))
        job = runner._read(phase)["jobs"][0]
        ledger = Path(phase["path"]).parent / "execution" / "primary" / job["job_id"] / "job.json"
        state = integrity.strict_parse(ledger.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "judge_failed")
        self.assertNotIn("accepted_response", state)
        self.assertEqual(len(self.fake.calls), 1)

    def test_original_cost_unique_once_without_view_multiplication(self):
        self.fixture_run(available=2)
        plan = runner._read(self.run_plan)
        self.assertEqual(plan["original_generation_cost_authorities"], self.costs)
        self.assertEqual(len(self.costs), 6)
        self.assertEqual(plan["generation_calls"], 0)
        self.assertFalse(plan["new_independent_samples"])
        self.assertFalse(plan["primary_scores_changed"])

    def test_accepted_raw_canonical_stdin_and_snapshot_tamper_never_redispatches(self):
        self.fixture_run(control=False)
        phase = self.phase()
        launch = self.launch(phase)
        completion = runner._read(self.dispatch(phase, launch))
        state = completion["states"][0]
        files = [Path(state["accepted_raw_response"]), Path(state["response"]),
                 Path(state["accepted_canonical_snapshot"]), Path(state["accepted_raw_response"]).parent / "stdin.bin"]
        for path in files:
            original = path.read_bytes()
            with self.subTest(file=path.name):
                path.write_bytes(original + b"tampered")
                try:
                    with self.assertRaises(ValueError):
                        self.dispatch(phase, launch)
                finally:
                    path.write_bytes(original)
                self.assertEqual(len(self.fake.calls), 1)

    def test_strict_source_quote_failure_is_terminal_not_format_retry(self):
        self.fixture_run(control=False)
        phase = self.phase()
        packet = runner._read(runner._read(phase)["jobs"][0]["packet"])
        response = handwritten_response(packet, error=True)
        response["errors"][0]["source_evidence"][0]["quote"] = "invisible invented quote"
        self.fake.outcomes = [{"response": response}]
        completion = runner._read(self.dispatch(phase, self.launch(phase)))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertTrue(completion["states"][0]["terminal_failure"])
        self.assertNotIn("accepted_response", completion["states"][0])

    def test_strict_group_scope_and_codepoint_quote_bindings_are_terminal(self):
        packet, _ = runner._blind(handwritten_packet(), "opaque")
        for change in ("membership", "codepoint", "packet", "duplicate"):
            response = handwritten_response(packet, error=True)
            if change == "membership":
                response["errors"][0]["source_ids"] = ["not-a-member"]
            elif change == "codepoint":
                response["errors"][0]["target_evidence"][0]["start"] = 3
            elif change == "packet":
                response["packet_sha256"] = "f" * 64
            else:
                response["errors"].append(deepcopy(response["errors"][0]))
            with self.subTest(change=change), self.assertRaises(ValueError):
                helper.parse_response(json.dumps(response), packet)

    def test_local_material_mutation_after_failed_transport_blocks_retry(self):
        self.fixture_run(control=False)
        phase = self.phase()
        prompt = Path(runner._read(phase)["jobs"][0]["prompt"]["path"])
        self.fake.outcomes = [{"record": {"returncode": 1},
                               "after": lambda: prompt.write_bytes(prompt.read_bytes() + b"drift")}]
        with self.assertRaises(ValueError):
            self.dispatch(phase, self.launch(phase))
        self.assertEqual(len(self.fake.calls), 1)

    def test_native_receipt_rejects_owner_root_terminal_worker_tool_and_drain_drift(self):
        self.fixture_run(control=False)
        phase = self.phase()
        launch = runner._read(self.launch(phase))
        guard = self.fake.guard(self.shared, 1, self.terminal["path"], self.terminal["sha256"])
        with guard:
            pass
        record = {"native_dispatch_sha256": runner.implementation()["native"]["sha256"],
                  "returned_models": ["gpt-6.1-sol"], "returned_efforts": ["high"], "tool_events": [],
                  "containment": "suspended-assign-resume-kill-on-close-job", "native_drain_proven": True,
                  "native_active_processes_after_drain": 0, "native_root_pid": 424242, "custody_workers_reserved": 1,
                  "custody_receipt": str(guard.owner_record), "custody_token": guard.token}
        runner._native_evidence(record, launch, drained=True)
        for changes in ({"returned_models": ["other"]}, {"returned_efforts": ["low"]},
                        {"tool_events": ["shell_command"]}, {"native_drain_proven": False},
                        {"native_active_processes_after_drain": 1}, {"custody_workers_reserved": 7},
                        {"custody_token": "donor"}, {"containment": "unmanaged"}):
            with self.subTest(record=changes), self.assertRaises(ValueError):
                runner._native_evidence({**record, **changes}, launch, drained=True)
        original = guard.owner_record.read_bytes()
        for changes in ({"owner": "other"}, {"shared_limit": 7}, {"state": "held"},
                        {"global_lock": str(self.root / "private.lock")}, {"terminal_sha256": "0" * 64},
                        {"active_callbacks": 1}, {"owned_job_objects": 1}):
            receipt = integrity.strict_parse(original.decode())
            receipt.update(changes)
            guard.owner_record.write_bytes(integrity.canonical_bytes(receipt))
            with self.subTest(receipt=changes), self.assertRaises(ValueError):
                runner._native_evidence(record, launch, drained=True)
        guard.owner_record.write_bytes(original)

    def test_score_or_anonymous_root_label_differences_do_not_create_disputes(self):
        packet, _ = runner._blind(handwritten_packet(), "opaque")
        first = handwritten_response(packet, error=True)
        second = deepcopy(first)
        second["native_semantic"] = 0
        second["errors"][0]["root_id"] = "other-local-root-label"
        second["errors"][0]["explanation"] = "Different wording of the same claim"
        self.assertFalse(runner._dispute(first, second))
        second["errors"][0]["severity"] = "critical"
        self.assertFalse(runner._dispute(first, second), "severity alone is not contradictory source fact")

    def test_fidelity_risk_review_selects_paired_control_with_no_primary_opinion_leak(self):
        self.fixture_run()
        phase = self.phase()
        packet = runner._read(runner._read(phase)["jobs"][0]["packet"])
        self.fake.outcomes = [{"response": handwritten_response(packet, error=True)}]
        self.dispatch(phase, self.launch(phase))
        self.fake.calls.clear()
        completion = runner._read(self.dispatch(phase, self.launch(phase, stage="review"), stage="review"))
        self.assertEqual(len(self.fake.calls), 2, "risk selects both native candidate and same-slot control")
        self.assertTrue(all(s["status"] == "succeeded" for s in completion["states"]))
        for call in self.fake.calls:
            self.assertNotIn("Handwritten scope claim", call["prompt"])
            self.assertNotIn("root-1", call["prompt"])

    def stage_completions(self, phase):
        return {stage: self.dispatch(phase, self.launch(phase, stage=stage), stage=stage)
                for stage in runner.STAGES}

    def test_phase_seal_rejects_forged_completion_state_despite_job_id_coverage(self):
        self.fixture_run(control=False)
        phase = self.phase()
        completions = self.stage_completions(phase)
        forged = runner._read(completions["primary"])
        forged["states"][0]["status"] = "started"
        completions["primary"] = self.write("forged-completion.json", forged)
        with self.assertRaises(ValueError):
            runner.seal_phase(phase_plan=phase, expected_phase_plan_sha256=phase["sha256"], completions=completions,
                              external_launch_pins=self.launch_pins)

    def test_phase_seal_rejects_extra_artifact_outside_frozen_phase_material(self):
        self.fixture_run(control=False)
        phase = self.phase()
        completions = self.stage_completions(phase)
        extra = Path(phase["path"]).parent / "undeclared-original.txt"
        extra.write_text("unregistered synthetic bytes", encoding="utf-8")
        with self.assertRaises(ValueError):
            runner.seal_phase(phase_plan=phase, expected_phase_plan_sha256=phase["sha256"], completions=completions,
                              external_launch_pins=self.launch_pins)

    def test_started_attempt_without_terminal_drain_cannot_resume_as_free_retry(self):
        self.fixture_run(control=False)
        phase = self.phase()
        launch = self.launch(phase)
        job = runner._read(phase)["jobs"][0]
        _, schema, prompt, fingerprint = runner._inputs(job, "primary")
        directory = Path(phase["path"]).parent / "execution" / "primary" / job["job_id"]
        attempt = directory / "attempt-1"
        attempt.mkdir(parents=True)
        (attempt / "prompt.txt").write_bytes(prompt)
        (attempt / "schema.json").write_bytes(schema)
        record = {"attempt": 1, "status": "started", "started_at": "2026-10-08T00:00:00+00:00"}
        (attempt / "attempt.json").write_bytes(integrity.canonical_bytes(record))
        state = {"job_id": job["job_id"], "stage": "primary", "fingerprint": fingerprint,
                 "status": "judge_failed", "attempts": [record], "launch": launch,
                 "response": str(Path(phase["path"]).parent / "responses" / "primary" / (job["job_id"] + ".json"))}
        (directory / "job.json").write_bytes(integrity.canonical_bytes(state))
        with self.assertRaises(ValueError):
            self.dispatch(phase, launch)
        self.assertEqual(self.fake.calls, [])
        self.assertFalse((directory / "attempt-2").exists())

    def test_original_module_identities_remain_fixed(self):
        from experiments.translation_flow import v2_unit_runner as original
        pins = runner.implementation()
        self.assertEqual(runner.identity(Path(original.__file__))["sha256"],
                         "13ca80a94954254122b0dea7c5fe50f36cd6dd6de2e0c573f44290165995acde")
        self.assertEqual(pins["custody"]["sha256"], "66c9c6415ab8e28122823011225427c60f4e72bba45d1f99c6c1dce4e748d8c6")
        self.assertEqual(pins["helper"]["sha256"], "7142126ef94575550ba1d835690e3e085bd758db532cd3e5b96372b10a4f42bf")
        self.assertEqual(runner.PROFILES, original.PROFILES)
        self.assertEqual(runner.PROMPTS, original.PROMPTS)
        for phase in runner.PHASES:
            packet = handwritten_packet(phase)
            self.assertEqual(runner._prompt(packet, "primary"), original._prompt(packet, "primary"))

    def test_custody_uses_one_explicit_source_pinned_registry_callback(self):
        self.fixture_run()
        callback = runner.main_router.make_role_seed_main_validator
        callback.reset_mock()
        runner._custody(runner._read(self.run_plan))
        callback.assert_called_once_with(registry=self.main_registry,
                                        expected_registry_sha256=self.main_registry["sha256"])
        self.assertEqual(self.inventory_mock.call_args.kwargs["expected_validator"],
                         runner.identity(Path(runner.main_router.__file__)))
        self.assertEqual(len(self.main_metadata), 6)
        self.assertEqual(len({seal["path"] for seal in self.candidate_seals.values()}), 3)

    def real_synthetic_registry(self):
        """Use both real metadata factories; only root authority pins are TEST fixtures.

        These handwritten sealed admissions are not whole-trial authentication.
        The existing prepared auxiliary view parser remains an explicit stub.
        No factory, registry parser, router or callback implementation is mocked.
        """
        self.registry_patch.stop()
        self.factory_patch.stop()
        router = runner.main_router
        leaf = self.write("router-fixture/leaf.json", {"handwritten_metadata_only": True})
        source = {name: leaf for name in ("manifest", "scenes", "freeze")}
        registration = self.write("router-fixture/registration.json", {
            "frame": leaf, "packed": [leaf], "cards": [leaf], "source_authority": source})
        propagation = self.write("summaries/F5-singleton-helper-version-v1/propagation-boundary.json",
                                 {"handwritten_TEST_propagation": True})
        authorities, admissions, receipts, costs = {}, {}, {}, []
        control_rows = []
        for seed in helper.SEEDS:
            trial = self.root / "router-fixture" / f"empty-original-control-{seed}"
            trial.mkdir(parents=True)
            control_rows.append({"seed": seed, "role": "control", "card": leaf, "trial_root": str(trial),
                "trial_completion": leaf, "runtime": leaf, "declared_snapshot_count": 17,
                "historical_authorities": {field: leaf for field in router.control_factory.HISTORICAL_FIELDS},
                "scoring_derivation": None})
        for role in ("control", "candidate"):
            factory = router.control_factory if role == "control" else router.candidate_factory
            replay = self.write(f"router-fixture/{role}-replay.json", {"schema": factory.REPLAY_SCHEMA,
                "state": "root_approved_closed_parser_replay", "verifier": router.identity(Path(factory.__file__)),
                "parsers": runner.custody._dependencies(), "historical_behavior": leaf})
            for seed in helper.SEEDS:
                trial = self.root / "router-fixture" / f"empty-original-{role}-{seed}"
                trial.mkdir(parents=True, exist_ok=True)
                entries = control_rows if role == "control" else [{"seed": seed, "role": role,
                    "card": leaf, "trial_root": str(trial), "trial_completion": leaf, "runtime": leaf,
                    "declared_snapshot_count": 21, "historical_authorities": None, "scoring_derivation": None}]
                authority = authorities["control", helper.SEEDS[0]] if role == "control" and seed != helper.SEEDS[0] else self.write(
                    f"router-fixture/{role}-{seed}-authority.json", {
                        "schema": factory.AUTHORITY_SCHEMA, "state": "root_approved_offline_original_authentication",
                        "registration": registration, "external_registration": self.external,
                        "verifier": router.identity(Path(factory.__file__)), "diagnostic_replay": replay, "entries": entries})
                authorities[role, seed] = authority
                metadata = {"role": role, "seed": seed, "card": leaf, "source_authority": source,
                    "retained": {field: leaf for field in runner.custody.RETAINED_FIELDS},
                    "session_root": str(trial), "trial": {"start": leaf, "completion": leaf},
                    "actual_source_scope": {"split": "screen-a", "scene_ids": ["handwritten"],
                                           "source_cues": 0, "scored_windows": 0},
                    "original_source_authority": source, "scoring_derivation": None, "native_complete": False,
                    "generation_attempt_status": "terminal_partial" if role == "candidate" else "not_run",
                    "native_stage": "full-flow" if role == "control" else "screening",
                    "approved_parser_snapshots": runner.custody._dependencies()}
                admission = self.write(f"router-fixture/{role}-{seed}-admission.json", {**metadata,
                    "schema": factory.ADMISSION_SCHEMA, "authority": authority, "session_provenance": [leaf],
                    "original_generation_run_identity": leaf, "inventory": []})
                admissions[role, seed] = admission
                cost = self.write(f"router-fixture/{role}-{seed}-cost.json", {
                    "schema": "hy30-F5-original-cost-authority-v1", "admission": admission,
                    "trial": metadata["trial"], "original_generation_run_identity": leaf, "original_cost_count": 1,
                    "new_generation_calls": 0, "new_samples": 0, "new_timing_measurements": 0})
                costs.append(cost)
                receipts[role, seed] = self.write(f"router-fixture/{role}-{seed}-proof.json", {**metadata,
                    "schema": runner.custody.MAIN_PROOF_SCHEMA, "session_provenance": [leaf, admission],
                    "cost_authority": cost, "original_generation_cost_identity": cost, "terminal_authority": admission,
                    "external_registration": self.external if role == "candidate" else None})
        # One historical control seal owns all three original control proofs.
        control_authority = authorities["control", helper.SEEDS[0]]
        control_seal = self.write("router-fixture/control-seal.json", {
            "schema": router.control_factory.SEAL_SCHEMA, "state": "root_reviewed_original_main_proofs",
            "verifier": router.identity(Path(router.control_factory.__file__)), "authority": control_authority,
            "proofs": [{"role": "control", "seed": seed, "proof": receipts["control", seed],
                        "admission": admissions["control", seed]} for seed in helper.SEEDS]})
        slots = []
        for seed in helper.SEEDS:
            candidate_seal = self.write(f"router-fixture/candidate-{seed}-seal.json", {
                "schema": router.candidate_factory.SEAL_SCHEMA, "state": "root_reviewed_original_main_proofs",
                "verifier": router.identity(Path(router.candidate_factory.__file__)), "authority": authorities["candidate", seed],
                "proofs": [{"role": "candidate", "seed": seed, "proof": receipts["candidate", seed],
                            "admission": admissions["candidate", seed]}]})
            for role in ("candidate", "control"):
                slots.append({"seed": seed, "role": role, "receipt": receipts[role, seed],
                    "seal": candidate_seal if role == "candidate" else control_seal,
                    "authority": authorities[role, seed] if role == "candidate" else control_authority,
                    "unavailable_reason": None})
        self.addCleanup(patch.stopall)
        patch.multiple(router, BASE=self.root, CONTROL_SEAL_SHA=control_seal["sha256"],
                       F5_EXTERNAL_SHA=self.external["sha256"], PROPAGATION_SHA=propagation["sha256"]).start()
        registry = self.write("router-fixture/registry.json", {"schema": router.REGISTRY_SCHEMA,
            "state": "root_reviewed_fixed_role_seed_slots", "dispatcher": router.identity(Path(router.__file__)),
            "propagation": propagation, "candidate_verifier": router.identity(Path(router.candidate_factory.__file__)),
            "control_verifier": router.identity(Path(router.control_factory.__file__)),
            "control_seal": control_seal, "external_registration": self.external, "slots": slots})
        self.material["main_receipts"] = [{k: row[k] for k in ("seed", "role", "receipt")} for row in slots]
        self.material["original_generation_cost_authorities"] = [
            runner._read(row["receipt"])["cost_authority"] for row in slots]
        self.custody = self.write("router-fixture/prepared-custody.json", self.material)
        return registry, slots

    def test_public_prepare_run_authenticates_all_six_routes_with_real_metadata_factories(self):
        self.fixture_run()
        registry, slots = self.real_synthetic_registry()
        callback = runner.main_router.make_role_seed_main_validator(
            registry=registry, expected_registry_sha256=registry["sha256"])
        router_pointer = runner.identity(Path(runner.main_router.__file__))
        runner.custody._validator_pin(callback, router_pointer, router_pointer["sha256"])
        with self.assertRaises(ValueError):
            runner.custody._validator_pin(callback, runner.identity(Path(runner.__file__)), router_pointer["sha256"])
        for row in slots:
            proof = callback(row["receipt"], seed=row["seed"], role=row["role"], external_registration=self.external)
            self.assertEqual(proof, runner._read(row["receipt"]))
            self.assertEqual(set(proof), runner.custody.MAIN_FIELDS)
            self.assertEqual(proof["external_registration"], self.external if row["role"] == "candidate" else None)
            if row["role"] == "candidate":
                self.assertFalse(proof["native_complete"])
                self.assertEqual(proof["generation_attempt_status"], "terminal_partial")
        plan = runner.prepare_run(custody_pointer=self.custody, expected_custody_sha256=self.custody["sha256"],
            registration=self.registration, external_registration=self.external,
            expected_main_slots=[{k: row[k] for k in ("seed", "role", "receipt", "unavailable_reason")} for row in slots],
            main_registry=registry, expected_main_registry_sha256=registry["sha256"], protocol=self.protocol,
            expected_protocol_sha256=self.protocol["sha256"], output=self.shared / "real-router-prepare")
        self.assertEqual(runner._read(plan)["logical_slots"], 252)
        self.assertEqual(len(runner._read(plan)["original_generation_cost_authorities"]), 6)
        fidelity = runner.prepare_phase(run_plan=plan, expected_run_plan_sha256=plan["sha256"], phase="native_fidelity")
        self.assertEqual(len([s for s in runner._read(fidelity)["slots"] if s["arm"] == "candidate"]), 252)
        for seed in helper.SEEDS:
            self.assertEqual(len([s for s in runner._read(fidelity)["slots"]
                                  if s["arm"] == "candidate" and s["slot"]["seed"] == seed]), 84)
        self.assertEqual(sum(s["status"] == "unavailable" for s in runner._read(fidelity)["slots"]), 502)
        for changed_seed, changed_role in ((helper.SEEDS[1], "candidate"), (helper.SEEDS[0], "control")):
            with self.assertRaises(ValueError):
                callback(slots[0]["receipt"], seed=changed_seed, role=changed_role, external_registration=self.external)
        unavailable = runner._read(registry)
        unavailable["slots"][0].update(receipt=None, seal=None, authority=None,
                                       unavailable_reason="Handwritten candidate not generated")
        absent_registry = self.write("router-fixture/unavailable-registry.json", unavailable)
        absent_callback = runner.main_router.make_role_seed_main_validator(
            registry=absent_registry, expected_registry_sha256=absent_registry["sha256"])
        with self.assertRaises(ValueError):
            absent_callback(slots[0]["receipt"], seed=helper.SEEDS[0], role="candidate", external_registration=self.external)
        self.assertEqual(absent_callback(slots[1]["receipt"], seed=helper.SEEDS[0], role="control",
                                        external_registration=self.external), runner._read(slots[1]["receipt"]))
        self.assertEqual(self.fake.calls, [])

    def test_public_registry_rejects_aggregate_candidate_authority_behind_single_seed_seal(self):
        self.fixture_run()
        registry, slots = self.real_synthetic_registry()
        value = runner._read(registry)
        authority = runner._read(slots[0]["authority"])
        authority["entries"] = [runner._read(row["authority"])["entries"][0]
                                for row in slots if row["role"] == "candidate"]
        aggregate = self.write("router-fixture/aggregate-candidate-authority.json", authority)
        seal = runner._read(slots[0]["seal"])
        seal["authority"] = aggregate
        value["slots"][0].update(authority=aggregate,
            seal=self.write("router-fixture/single-proof-with-aggregate-authority-seal.json", seal))
        damaged = self.write("router-fixture/aggregate-authority-registry.json", value)
        with self.assertRaises(ValueError):
            runner.main_router.validate_registry(damaged, damaged["sha256"])
        self.assertEqual(self.fake.calls, [])

    def test_present_registry_receipt_cannot_be_replaced_by_unavailable(self):
        self.fixture_run()
        plan = runner._read(self.run_plan)
        plan["expected_main_slots"][0].update(receipt=None, unavailable_reason="fabricated missing")
        with self.assertRaises(ValueError):
            runner._custody(plan)

    def test_registry_slots_cannot_relabel_candidate_seed_or_role(self):
        self.fixture_run()
        plan = runner._read(self.run_plan)
        altered = deepcopy(self.registry_value)
        altered["slots"][0]["seed"] = helper.SEEDS[1]
        plan["main_registry"] = self.write("relabeled-registry.json", altered)
        with self.assertRaisesRegex(ValueError, "roles/seeds"):
            runner._custody(plan)

    def test_registry_external_registration_cannot_drift(self):
        self.fixture_run()
        plan = runner._read(self.run_plan)
        altered = deepcopy(self.registry_value)
        altered["external_registration"] = self.write("other-external.json", {"handwritten": "other"})
        plan["main_registry"] = self.write("other-registry.json", altered)
        with self.assertRaisesRegex(ValueError, "roles/seeds"):
            runner._custody(plan)

    def test_prepare_requires_independent_registry_hash(self):
        self.fixture_run()
        with self.assertRaisesRegex(ValueError, "pin changed"):
            runner.prepare_run(custody_pointer=self.custody, expected_custody_sha256=self.custody["sha256"],
                registration=self.registration, external_registration=self.external, expected_main_slots=self.main_slots,
                main_registry=self.main_registry, expected_main_registry_sha256="0" * 64, protocol=self.protocol,
                expected_protocol_sha256=self.protocol["sha256"], output=self.shared / "wrong-registry-pin")

    def test_original_profile_probe_cannot_qualify_singleton_binding(self):
        from experiments.translation_flow import v2_unit_runner as original
        self.fixture_run()
        probe = runner._read(self.native_probe("native_fidelity"))
        probe.update(schema="hy30-F5-unit-native-probe-v1", implementation=original.implementation())
        old_probe = self.write("handwritten-historical-probe.json", probe)
        with self.assertRaisesRegex(ValueError, "original-schema"):
            runner.validate_native_probe(old_probe, phase="native_fidelity", protocol=self.protocol,
                                         executable=self.executable, shared_root=self.shared)

    def test_duplicate_original_cost_authority_cannot_prepare_new_run(self):
        self.fixture_run(control=False)
        self.material["original_generation_cost_authorities"].append(deepcopy(self.costs[0]))
        output = self.shared / "duplicated-cost-run"
        with self.assertRaisesRegex(ValueError, "duplicated"):
            runner.prepare_run(custody_pointer=self.custody, expected_custody_sha256=self.custody["sha256"],
                registration=self.registration, external_registration=self.external, expected_main_slots=self.main_slots,
                main_registry=self.main_registry, expected_main_registry_sha256=self.main_registry["sha256"], protocol=self.protocol,
                expected_protocol_sha256=self.protocol["sha256"], output=output)
        self.assertFalse(output.exists())

    def test_accepted_response_cannot_use_cross_job_raw_donor(self):
        self.fixture_run(control=False)
        phase = self.phase()
        launch = self.launch(phase)
        completion = runner._read(self.dispatch(phase, launch))
        state = completion["states"][0]
        original = Path(state["accepted_raw_response"])
        donor = original.parents[1].parent / "another-job" / "last-message.txt"
        donor.parent.mkdir()
        donor.write_bytes(original.read_bytes())
        state["accepted_raw_response"] = str(donor)
        ledger = original.parents[1] / "job.json"
        ledger.write_bytes(integrity.canonical_bytes(state))
        with self.assertRaises(ValueError):
            self.dispatch(phase, launch)
        self.assertEqual(len(self.fake.calls), 1)

    def test_bounded_failed_transport_cost_and_unknown_tails_keep_fixed_denominator(self):
        self.fixture_run(available=2, control=False)
        phase = self.phase()
        self.fake.outcomes = [{"record": {"transport_status": "timeout", "returncode": None}} for _ in range(4)]
        completion = runner._read(self.dispatch(phase, self.launch(phase)))
        self.assertEqual(completion["logical_slots"], 252)
        self.assertEqual(completion["actual_attempts"], 4)
        self.assertEqual(len(self.fake.calls), 4)
        self.assertEqual(completion["unavailable_views"], 502)
        self.assertTrue(all(s["status"] == "judge_failed" for s in completion["states"]))
        self.assertTrue(all(len(s["attempts"]) == 2 for s in completion["states"]))
        self.assertTrue(all(a["usage_events"] == [] for s in completion["states"] for a in s["attempts"]))

    def test_no_main_evidence_keeps_all_seed_slots_unavailable_with_zero_calls(self):
        self.fixture_run(available=0)
        phase = self.phase()
        value = runner._read(phase)
        for seed in helper.SEEDS:
            self.assertEqual(sum(s["slot"]["seed"] == seed and s["arm"] == "candidate"
                                 and s["status"] == "unavailable" for s in value["slots"]), 84)
        completion = runner._read(self.dispatch(phase, self.launch(phase)))
        self.assertEqual(completion["actual_attempts"], 0)
        self.assertEqual(completion["unavailable_views"], 504)
        self.assertEqual(completion["logical_slots"], 252)
        self.assertEqual(self.fake.calls, [])

    def test_attribution_after_real_unresolved_fidelity_seal_does_not_filter_score(self):
        self.fixture_run(control=False)
        fidelity = self.phase()
        packet = runner._read(runner._read(fidelity)["jobs"][0]["packet"])
        self.fake.outcomes = [{"response": handwritten_response(packet, unresolved=True)}]
        completions = self.stage_completions(fidelity)
        seal = runner.seal_phase(phase_plan=fidelity, expected_phase_plan_sha256=fidelity["sha256"],
                                 completions=completions, external_launch_pins=self.launch_pins)
        attribution = self.phase("cue_attribution", seal)
        phase = runner._read(attribution)
        self.assertEqual(len(phase["slots"]), 252)
        self.assertEqual(len(phase["jobs"]), 1, "unresolved fidelity does not remove authenticated mapping")
        blind = runner._read(phase["jobs"][0]["packet"])
        self.assertEqual(blind["phase"], "cue_attribution")
        self.assertNotIn("native_semantic", blind)
        self.assertNotIn("Handwritten unresolved evidence", runner._prompt(blind, "primary"))

    def check_probe(self, pointer, phase="native_fidelity"):
        return runner.validate_native_probe(pointer, phase=phase, protocol=self.protocol,
                                            executable=self.executable, shared_root=self.shared)

    def test_both_original_schema_probes_authenticate_native_bytes_without_cohort_calls(self):
        self.fixture_run(control=False)
        for phase in runner.PHASES:
            pointer = self.native_probe(phase)
            probe = self.check_probe(pointer, phase)
            record = runner._read(probe["attempt_record"])
            self.assertEqual(record["custody_workers_reserved"], 1)
            self.assertEqual(record["returned_models"], ["gpt-6.1-sol"])
            self.assertEqual(record["returned_efforts"], ["high"])
            self.assertEqual(record["tool_events"], [])
            schema = runner._read(probe["schema_artifact"])
            self.assertEqual(schema, helper.response_schema(runner._read(probe["packet"])))
        self.assertEqual(self.fake.calls, [])

    def test_boolean_only_or_wrong_phase_probe_cannot_authorize_native_launch(self):
        self.fixture_run(control=False)
        forged = self.write("boolean-probe.json", {
            "schema": "hy30-F5-unit-singleton-native-probe-v1", "phase": "native_fidelity",
            "implementation": runner.implementation(), "exactly_one_fresh_attempt": True,
            "synthetic_material_declared": True, "drained": True})
        with self.assertRaises(ValueError):
            self.check_probe(forged)
        valid = self.native_probe("native_fidelity")
        with self.assertRaises(ValueError):
            self.check_probe(valid, "cue_attribution")
        self.assertEqual(self.fake.calls, [])

    def test_probe_stdin_raw_canonical_snapshot_and_schema_tamper_all_refused(self):
        self.fixture_run(control=False)
        pointer = self.native_probe("native_fidelity")
        probe = runner._read(pointer)
        accepted = probe["accepted"]
        paths = [Path(probe["schema_artifact"]["path"]), Path(probe["prompt"]["path"]),
                 Path(accepted["accepted_raw_response"]), Path(accepted["response"]),
                 Path(accepted["accepted_canonical_snapshot"]), Path(probe["attempt_record"]["path"]).parent / "stdin.bin"]
        for path in paths:
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(original + b"changed")
                try:
                    with self.assertRaises(ValueError):
                        self.check_probe(pointer)
                finally:
                    path.write_bytes(original)
        self.assertEqual(self.fake.calls, [])

    def test_probe_extra_file_and_wrong_executable_rejected(self):
        self.fixture_run(control=False)
        pointer = self.native_probe("native_fidelity")
        probe = runner._read(pointer)
        directory = Path(probe["attempt_record"]["path"]).parent
        (directory / "unregistered-response.txt").write_bytes(b"another original")
        with self.assertRaises(ValueError):
            self.check_probe(pointer)
        executable = self.root / "another-never-executed.exe"
        executable.write_bytes(b"other executable")
        with self.assertRaises(ValueError):
            runner.validate_native_probe(pointer, phase="native_fidelity", protocol=self.protocol,
                                         executable=runner.identity(executable), shared_root=self.shared)

    def test_probe_second_attempt_cannot_hide_behind_exactly_one_flag(self):
        self.fixture_run(control=False)
        pointer = self.native_probe("native_fidelity")
        probe = runner._read(pointer)
        second = Path(probe["attempt_record"]["path"]).parent.parent / "attempt-2"
        second.mkdir()
        (second / "attempt.json").write_bytes(integrity.canonical_bytes({"attempt": 2, "status": "failed"}))
        with self.assertRaises(ValueError):
            self.check_probe(pointer)

    def test_accepted_resume_requires_original_immutable_launch(self):
        self.fixture_run(control=False)
        phase = self.phase()
        first_launch = self.launch(phase)
        self.dispatch(phase, first_launch)
        second_launch = self.launch(phase)
        self.assertNotEqual(first_launch, second_launch)
        with self.assertRaises(ValueError):
            self.dispatch(phase, second_launch)
        self.assertEqual(len(self.fake.calls), 1)

    def test_final_diagnostic_seal_preserves_252_slots_and_six_original_costs_once(self):
        self.fixture_run(control=False)
        fidelity = self.phase()
        completions = self.stage_completions(fidelity)
        fidelity_seal = runner.seal_phase(phase_plan=fidelity, expected_phase_plan_sha256=fidelity["sha256"],
                                         completions=completions, external_launch_pins=deepcopy(self.launch_pins))
        attribution = self.phase("cue_attribution", fidelity_seal)
        completions = self.stage_completions(attribution)
        attribution_seal = runner.seal_phase(phase_plan=attribution, expected_phase_plan_sha256=attribution["sha256"],
                                            completions=completions, external_launch_pins=deepcopy(self.launch_pins))
        seal = runner.seal_diagnostic(run_plan=self.run_plan, expected_run_plan_sha256=self.run_plan["sha256"],
                                     fidelity_seal=fidelity_seal, attribution_seal=attribution_seal)
        value = runner._read(seal)
        self.assertEqual(value["logical_slots"], 252)
        self.assertEqual(len(value["source_slots"]), 252)
        self.assertEqual(value["original_generation_cost_authorities"], self.costs)
        self.assertEqual(len(value["original_generation_cost_authorities"]), 6)
        self.assertTrue(value["original_generation_cost_counted_once"])
        self.assertFalse(value["primary_scores_changed"])
        self.assertFalse(value["semantic_accuracy_verified"])
        self.assertFalse(value["new_independent_samples"])
        self.assertEqual(value["generation_calls"], 0)

    def test_sealed_fidelity_private_join_mutation_blocks_attribution_entry(self):
        self.fixture_run(control=False)
        fidelity = self.phase()
        completions = self.stage_completions(fidelity)
        seal = runner.seal_phase(phase_plan=fidelity, expected_phase_plan_sha256=fidelity["sha256"],
                                 completions=completions, external_launch_pins=self.launch_pins)
        join = Path(runner._read(fidelity)["jobs"][0]["join"]["path"])
        value = integrity.strict_parse(join.read_text(encoding="utf-8"))
        value["arm"] = "donor"
        join.write_bytes(integrity.canonical_bytes(value))
        calls_before = len(self.fake.calls)
        with self.assertRaises(ValueError):
            self.phase("cue_attribution", seal)
        self.assertEqual(len(self.fake.calls), calls_before)

    def test_known_missing_main_cannot_expose_an_available_native_packet(self):
        self.fixture_run(available=0)
        self.material["slots"][0]["views"]["native_packet"] = handwritten_packet()
        forged_custody = self.write("available-without-main-custody.json", self.material)
        output = self.shared / "missing-main-forgery"
        with self.assertRaisesRegex(ValueError, "Missing candidate main proof"):
            runner.prepare_run(custody_pointer=forged_custody, expected_custody_sha256=forged_custody["sha256"],
                registration=self.registration, external_registration=self.external, expected_main_slots=self.main_slots,
                main_registry=self.main_registry, expected_main_registry_sha256=self.main_registry["sha256"], protocol=self.protocol,
                expected_protocol_sha256=self.protocol["sha256"], output=output)
        self.assertFalse(output.exists())
        self.assertEqual(self.fake.calls, [])

    def test_native_invalid_schema_error_event_variants_stop_but_assistant_text_does_not(self):
        directory = self.root / "handwritten-native-events"
        directory.mkdir()
        events = [{"type": "error", "code": "invalid_json_schema"},
                  {"type": "turn.failed", "error": {"code": "invalid_json_schema"}},
                  {"type": "item.completed", "item": {"type": "error", "code": "invalid_json_schema"}}]
        for event in events:
            (directory / "stdout.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
            with self.subTest(event=event):
                self.assertTrue(runner._schema_failure(directory))
        (directory / "stdout.jsonl").write_text(json.dumps({"type": "item.completed", "item": {
            "type": "agent_message", "text": "This handwritten text mentions invalid_json_schema"}}), encoding="utf-8")
        self.assertFalse(runner._schema_failure(directory))

    def test_authenticated_native_with_failed_mapping_remains_in_fidelity_only(self):
        self.fixture_run(control=False, mapping=False)
        fidelity = self.phase()
        self.assertEqual(len(runner._read(fidelity)["jobs"]), 1)
        completions = self.stage_completions(fidelity)
        seal = runner.seal_phase(phase_plan=fidelity, expected_phase_plan_sha256=fidelity["sha256"],
                                 completions=completions, external_launch_pins=self.launch_pins)
        attribution = self.phase("cue_attribution", seal)
        value = runner._read(attribution)
        self.assertEqual(value["jobs"], [])
        self.assertEqual(len(value["slots"]), 252)
        self.assertEqual(value["slots"][0]["status"], "unavailable")
        self.assertEqual(value["slots"][0]["reason"], "mapping_unavailable")

    def test_present_failed_original_generations_keep_all_84_null_slots_per_seed(self):
        self.fixture_run(available=0, main_present=True)
        fidelity = self.phase()
        value = runner._read(fidelity)
        self.assertEqual(value["jobs"], [])
        for seed in helper.SEEDS:
            self.assertEqual(sum(s["slot"]["seed"] == seed and s["arm"] == "candidate"
                                 and s["status"] == "unavailable" for s in value["slots"]), 84)
        self.assertEqual(len(runner._read(self.run_plan)["original_generation_cost_authorities"]), 6)
        self.assertEqual(self.fake.calls, [])

    def forged_empty_completion(self, phase, stage, launch, state, *, stop=None):
        root = Path(phase["path"]).parent
        return runner._write(root / "completions" / (stage + "-handwritten-forged.json"), {
            "schema": "hy30-F5-unit-singleton-stage-completion-v1", "phase_plan": phase, "stage": stage,
            "launch": launch, "states": [state], "logical_slots": 252, "stop": stop,
            "actual_attempts": 0, "unavailable_views": 503, "generation_calls": 0,
            "primary_scores_changed": False})

    def test_forged_empty_review_ledger_cannot_hide_eligible_risk_review(self):
        self.fixture_run(control=False)
        phase = self.phase()
        job = runner._read(phase)["jobs"][0]
        packet = runner._read(job["packet"])
        self.fake.outcomes = [{"response": handwritten_response(packet, error=True)}]
        primary = self.dispatch(phase, self.launch(phase))
        review_launch = self.launch(phase, stage="review")
        root = Path(phase["path"]).parent
        state = {"job_id": job["job_id"], "stage": "review", "fingerprint": runner._inputs(job, "review")[3],
                 "status": "not_required", "attempts": [], "launch": review_launch,
                 "reason": "not_selected_source_reliability_or_risk",
                 "response": str(root / "responses" / "review" / (job["job_id"] + ".json"))}
        ledger = root / "execution" / "review" / job["job_id"] / "job.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_bytes(integrity.canonical_bytes(state))
        review = self.forged_empty_completion(phase, "review", review_launch, state)
        adjudication = self.forged_empty_completion(phase, "adjudication", self.launch(phase, stage="adjudication"),
            {"job_id": job["job_id"], "status": "unknown", "reason": "review_unknown", "attempts": []})
        with self.assertRaises(ValueError):
            runner.seal_phase(phase_plan=phase, expected_phase_plan_sha256=phase["sha256"],
                              completions={"primary": primary, "review": review, "adjudication": adjudication},
                              external_launch_pins=self.launch_pins)

    def test_arbitrary_stop_pointer_cannot_justify_unattempted_review_tail(self):
        self.fixture_run(control=False)
        phase = self.phase()
        job = runner._read(phase)["jobs"][0]
        self.fake.outcomes = [{"response": handwritten_response(runner._read(job["packet"]), error=True)}]
        primary = self.dispatch(phase, self.launch(phase))
        review_launch = self.launch(phase, stage="review")
        stop = self.write("arbitrary-stop.json", {"schema": "hy30-F5-unit-singleton-global-stop-v1", "reason": "invalid_json_schema",
                    "phase_plan": phase, "launch": review_launch, "stage": "review", "owner": "evaluation_custodian"})
        state = {"job_id": job["job_id"], "status": "not_run", "reason": "global_stop", "attempts": []}
        review = self.forged_empty_completion(phase, "review", review_launch, state, stop=stop)
        adjudication = self.dispatch(phase, self.launch(phase, stage="adjudication"), stage="adjudication")
        with self.assertRaises(ValueError):
            runner.seal_phase(phase_plan=phase, expected_phase_plan_sha256=phase["sha256"],
                              completions={"primary": primary, "review": review, "adjudication": adjudication},
                              external_launch_pins=self.launch_pins)

    def test_deleted_inherited_global_schema_stop_cannot_restart_sibling_dispatch(self):
        self.fixture_run(available=2, control=False)
        phase = self.phase()
        launch = self.launch(phase)
        self.fake.outcomes = [{"stdout": {"type": "turn.failed", "error": {"code": "invalid_json_schema"}},
                               "record": {"returncode": 1}}]
        completion = runner._read(self.dispatch(phase, launch))
        stop = Path(completion["stop"]["path"])
        self.assertEqual(stop.parent, Path(self.run_plan["path"]).parent)
        stop.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.dispatch(phase, launch)
        self.assertEqual(len(self.fake.calls), 1)

    def assert_failed_attempt_material_mutation_blocks_retry(self, filename):
        self.fixture_run(control=False)
        phase = self.phase()
        def mutate():
            path = self.fake.calls[-1]["attempt"] / filename
            path.write_bytes(path.read_bytes() + b"mutation-after-failed-native-callback")
        self.fake.outcomes = [{"record": {"transport_status": "timeout", "returncode": None}, "after": mutate}]
        try:
            self.dispatch(phase, self.launch(phase))
        except ValueError:
            pass
        self.assertEqual(len(self.fake.calls), 1)
        self.assertFalse((self.fake.calls[0]["attempt"].parent / "attempt-2").exists())

    def test_failed_timeout_stdin_mutation_blocks_second_attempt(self):
        self.assert_failed_attempt_material_mutation_blocks_retry("stdin.bin")

    def test_failed_timeout_schema_mutation_blocks_second_attempt(self):
        self.assert_failed_attempt_material_mutation_blocks_retry("schema.json")

    def test_failed_timeout_prompt_mutation_blocks_second_attempt(self):
        self.assert_failed_attempt_material_mutation_blocks_retry("prompt.txt")

    def test_mutated_original_job_launch_cannot_be_sealed_under_independent_launch_pin(self):
        self.fixture_run(control=False)
        phase = self.phase()
        completions = self.stage_completions(phase)
        primary = runner._read(completions["primary"])
        state = primary["states"][0]
        original_launch = runner._read(state["launch"])
        forged_launch = self.write("unapproved-minimal-launch.json", {key: original_launch[key]
                                    for key in ("executable", "root", "terminal_receipt")})
        state["launch"] = forged_launch
        ledger = Path(state["accepted_raw_response"]).parents[1] / "job.json"
        ledger.write_bytes(integrity.canonical_bytes(state))
        forged_completion = self.write("matching-forged-launch-completion.json", primary)
        completions["primary"] = forged_completion
        with self.assertRaises(ValueError):
            runner.seal_phase(phase_plan=phase, expected_phase_plan_sha256=phase["sha256"],
                              completions=completions, external_launch_pins=self.launch_pins)

    def test_forged_succeeded_completion_with_attempts_and_no_ledger_cannot_seal(self):
        self.fixture_run(control=False)
        phase = self.phase()
        job = runner._read(phase)["jobs"][0]
        completions = self.stage_completions(phase)
        primary = runner._read(completions["primary"])
        original = primary["states"][0]
        ledger = Path(original["accepted_raw_response"]).parents[1] / "job.json"
        self.assertTrue(ledger.exists())
        ledger.unlink()
        self.assertTrue(original["attempts"])
        self.assertEqual(original["status"], "succeeded")
        with self.assertRaises(ValueError):
            runner.seal_phase(phase_plan=phase, expected_phase_plan_sha256=phase["sha256"],
                              completions=completions, external_launch_pins=self.launch_pins)

    def test_sealed_phase_resume_refuses_without_calls_or_mutation_and_barrier_stays_valid(self):
        self.fixture_run(control=False)
        fidelity = self.phase()
        completions = self.stage_completions(fidelity)
        launches = deepcopy(self.launch_pins)
        seal = runner.seal_phase(phase_plan=fidelity, expected_phase_plan_sha256=fidelity["sha256"],
                                 completions=completions, external_launch_pins=launches)
        root = Path(fidelity["path"]).parent
        before = [runner.identity(path) for path in sorted(root.rglob("*")) if path.is_file()]
        calls_before = len(self.fake.calls)
        with self.assertRaisesRegex(ValueError, "sealed|immutable|Sealed"):
            self.dispatch(fidelity, launches["primary"])
        after = [runner.identity(path) for path in sorted(root.rglob("*")) if path.is_file()]
        self.assertEqual(before, after)
        self.assertEqual(len(self.fake.calls), calls_before)
        attribution = self.phase("cue_attribution", seal)
        self.assertEqual(runner._read(attribution)["fidelity_seal"], seal)


if __name__ == "__main__":
    unittest.main()
