"""Offline public bridge-runner integration using handwritten synthetic material.

Original source/native admission seams are explicit fixture stubs. The public
bridge freeze/replay, immutable runner plans, response validation and receipt
joins are real. Fake native callbacks and a CustodyGuard-shaped fixture replace
native execution; this suite never opens the production ROOT or invokes CLI,
GPU, model, network, actual material or historical judge data.
"""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from experiments.translation_flow import v2_consistency_pair_bridge as b
from experiments.translation_flow import v2_consistency as c
from experiments.translation_flow import v2_consistency_custody as custody
from experiments.translation_flow import v2_unit_custody as unit
from experiments.translation_flow import v2_source_projection as projection
from experiments.translation_flow import v2_consistency_runner as original
from experiments.translation_flow import v2_consistency_prompt_contract as prompt_contract
from experiments.translation_flow import v2_judge_dispatch as native
from experiments.translation_flow import v2_consistency_bridge_runner as r
from experiments.translation_judge import integrity


class SyntheticCohort(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bridge-cohort-test-", dir=Path(__file__).resolve().parents[2] / ".local" / "tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scenes, self.batches = [], []
        for number in range(29):
            sid = f"handwritten-scene-{number:02d}"
            ids = [f"{sid}-j{i}" for i in range(4)]
            self.scenes.append({"id": sid, "source_language": "ja", "target_language": "zh-Hans",
                "context": [{"id": uid, "text": text} for uid, text in zip(ids,
                    ("翼がある。", "翼を広げる。", "まだです。", "行きます。"))], "translate_ids": ids})
            self.batches.extend({"id": f"{sid}-batch-{i}", "scene_id": sid,
                "target_ids": [uid], "readonly_ids": []} for i, uid in enumerate(ids))
        self.originals = {row["id"]: deepcopy(row) for row in self.scenes}
        self.scope = {"version": "hy30-consistency-source-scope-v1", "split": "screen-a",
            "state": "frozen_before_consistency_quality", "quality_inspected": False,
            "scene_ids": list(self.originals)}
        for key in ("source_manifest", "source_scenes", "source_freeze"):
            self.scope[key] = self.write(f"source/{key}.json", {"handwritten_only": True})
        self.scope_ptr = self.write("source/scope.json", self.scope)
        self.source = self.write("registration/source.json", {"schema": b.SOURCE_SCHEMA,
            "state": "source_only_scope_registered_for_consistency", "source_scope": self.scope_ptr,
            "ordered_scene_ids": list(self.originals), "generation_seeds": list(c.SEEDS)})
        self.controls, self.intakes, self.candidates, self.loaded = {}, {}, {}, {}
        self.external_control = self.write("control-authority/external.json", {"synthetic_only": True})
        control_authority = self.write("control-authority/authority.json", {"synthetic_only": True})
        self.control_seal = self.write("control-authority/seal.json", {"authority": control_authority})
        self.entries, slots = [], []
        settings = {"recipe": "c0", "n_predict": 4096, "terms": [], "background": [], "style": "neutral", "review": False}
        raw = json.dumps({"terms": [{"source": "翼", "translation": "翅膀", "uncertain": False}]}, ensure_ascii=False)
        for seed in c.SEEDS:
            control_card = self.write(f"evidence/control-{seed}/card.json", {"prepare": {"seed": seed, "recipe_id": f"control-{seed}", "recipe": "c0"}})
            control_cost = self.write(f"evidence/control-{seed}/completion.json", {"synthetic_only": True})
            proof = {key: None for key in unit.MAIN_FIELDS}
            proof.update(schema=unit.MAIN_PROOF_SCHEMA, role="control", seed=seed, card=control_card,
                original_generation_cost_identity=control_cost, cost_authority=control_cost,
                native_stage="full-flow", native_complete=True, generation_attempt_status="complete",
                trial={"completion": control_cost})
            ptr = self.write(f"evidence/control-{seed}/proof.json", proof)
            self.controls[seed] = (ptr, proof)
            results, ledger = [], []
            aggregate = {"scenes": {sid: {} for sid in self.originals}}
            for batch in self.batches:
                values = {uid: "翅膀。" for uid in batch["target_ids"]}
                results.append({"id": batch["id"], "status": "delivered", "translations": values})
                ledger.append({"window_id": batch["id"], "status": "delivered", "translations": values, "attempts": []})
                for uid, text in values.items():
                    aggregate["scenes"][batch["scene_id"]][uid] = {"status": "delivered", "text": text, "batch_id": batch["id"]}
            self.intakes[seed] = {"data": {"packed": {"scene_ids": list(self.originals), "scenes": deepcopy(self.scenes), "batches": deepcopy(self.batches)},
                "run": {"settings": {**settings, "seed": seed, "label": f"control-{seed}"}}, "results": results, "ledger": ledger, "schedule": []}}
            root = self.root / f"evidence/candidate-{seed}"
            card = {"prepare": {"seed": seed, "recipe_id": f"candidate-{seed}", "recipe": "base-json",
                "source_preparation_projection": projection.TERMS}}
            card_ptr = self.write(f"evidence/candidate-{seed}/card.json", card)
            terminal = {"status": "complete"}
            cost = self.write(f"evidence/candidate-{seed}/completion.json", terminal)
            preparations = [{"scene_id": sid, "status": "prepared", "raw_response": raw, "reason": None} for sid in self.originals]
            native_proof = {"candidate_group": "F6-terms-proposals-max32", "seed": seed, "trial_root": str(root.resolve()),
                "card": card_ptr, "original_trial_attempt_identity": cost, "scope": {"scene_ids": list(self.originals)},
                "native_complete": True, "source_preparation_slots": [{k:v for k,v in row.items() if k!="raw_response"} for row in preparations]}
            native_ptr = self.write(f"evidence/candidate-{seed}/proof.json", native_proof)
            exposures = {}
            for batch in self.batches:
                scene = self.originals[batch["scene_id"]]
                parsed = c.parse_proposals(raw, scene, 32)
                window = {**scene, "id": batch["id"], "translate_ids": batch["target_ids"],
                    "context": [q for q in scene["context"] if q["id"] in batch["target_ids"]]}
                projected = projection.project("terms", "eligibility-filtered-proposals-v1", projection.TERMS, parsed, window)
                exposures[batch["id"]] = {"status": "verified", "options_sha256": c.object_hash(projected["options"]), "visibility_sha256": c.object_hash(projected["visibility"])}
            current = {"missing": False, "settings": {**settings, "recipe": "base-json", "seed": seed, "label": f"candidate-{seed}"},
                "aggregate": aggregate, "batches": self.batches, "projection": projection.TERMS, "exposure_proofs": exposures, "native": {"synthetic_only": True}}
            self.candidates[seed] = (native_ptr, native_proof)
            self.loaded[seed] = {"proof": native_proof, "scope": self.scope, "scenes": self.scenes, "originals": self.originals,
                "card": card, "terminal": terminal, "source_preparation_slots": preparations,
                "source_preparation_plan": {"protocol": "eligibility-filtered-proposals-v1", "settings": {"seed": seed, "max_items": 32}},
                "main": current, "card_provenance": {"synthetic_only": True}}
            self.entries.append({"candidate_group": "F6-terms-proposals-max32", "seed": seed, "card": card_ptr,
                "trial_root": str(root.resolve()), "trial_completion": cost})
            slots.extend(({"seed": seed, "role": "control", "kind": "main_proof", "evidence": ptr},
                          {"seed": seed, "role": "candidate", "kind": "native_proof", "evidence": native_ptr}))
        self.auth = {"source_scope": self.scope_ptr, "entries": self.entries}
        self.candidate_authority = self.write("candidate-authority/authority.json", self.auth)
        self.pair_value = {"schema": b.PAIR_SCHEMA, "state": "retained_control_and_preregistered_candidate",
            "source_registration": self.source, "implementation": b.implementation(), "generation_seeds": list(c.SEEDS),
            "groups": {"F6-terms-proposals-max32": {"mode": "terms", "control_seal": self.control_seal,
                "control_external_registration": self.external_control, "candidate_authority": self.candidate_authority, "slots": slots}}}
        self.register_pair()

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(integrity.canonical_bytes(value))
        return custody.identity(path)

    def register_pair(self):
        self.pair = self.write("registration/pair.json", self.pair_value)
        self.external = self.write("registration/external.json", {"schema": b.EXTERNAL_SCHEMA,
            "state": "root_registered_before_actual_consistency_calls", "source_registration": self.source,
            "pair_authority": self.pair, "implementation": b.implementation()})

    def pins(self):
        return dict(source_registration=self.source, pair_authority=self.pair, external_registration=self.external,
            expected_source_sha256=self.source["sha256"], expected_pair_sha256=self.pair["sha256"], expected_external_sha256=self.external["sha256"])

    def seams(self):
        def control_validate(pointer, *, seed, role, external_registration):
            self.assertEqual(role, "control")
            self.assertEqual(pointer, self.controls[seed][0])
            self.assertEqual(external_registration, self.external_control)
            return deepcopy(b._read(pointer))
        def validate_candidate(**kwargs):
            proof = b._read(kwargs["proof"], kwargs["expected_proof_sha256"])
            return proof
        def load_candidate(**kwargs):
            proof = validate_candidate(**kwargs)
            value = deepcopy(self.loaded[proof["seed"]])
            value["proof"] = proof
            return value
        helper = SimpleNamespace(_authority=lambda *args: deepcopy(self.auth), validate_admission=validate_candidate,
                                 load_original_material=load_candidate)
        stack = ExitStack()
        stack.enter_context(patch.object(b, "_candidate_helper", return_value=helper))
        stack.enter_context(patch.object(b.main, "make_main_validator", return_value=control_validate))
        stack.enter_context(patch.object(b.main, "_authority", return_value=({"external_registration": self.external_control}, {"synthetic_only": True})))
        stack.enter_context(patch.object(b.unit, "_main", side_effect=lambda ptr, **kw: (control_validate(ptr, seed=kw["seed"], role=kw["role"], external_registration=kw["external_registration"]), deepcopy(self.intakes[kw["seed"]]))))
        stack.enter_context(patch.object(b.custody, "_source", return_value=(deepcopy(self.scope), deepcopy(self.scenes), deepcopy(self.originals))))
        return stack


def synthetic_response(envelope, *, unknown=False):
    """Produce full-coverage fixture opinions, never a semantic oracle."""
    packet = c.validate_packet(envelope)
    source = {row["id"]: row["text"] for row in packet["source_context"]}

    def quote(uid):
        text = source[uid]
        return {"id": uid, "quote": text, "start": 0, "end": len(text)}

    def evidence(side, ids, state):
        texts = {row["id"]: row for row in packet["sides"][side]}
        return {"state": state, "candidate_evidence": [] if state == "unknown" else [
            {"id": uid, "quote": texts[uid]["text"]} for uid in ids
            if texts[uid]["status"] == "delivered"], "reason_zh": "合成测试直接引文。"}

    rows = []
    if packet["phase"] == "A":
        for anchor in packet["anchors"]:
            occurrences = anchor["occurrences"]
            ids = list(dict.fromkeys(row["id"] for row in occurrences))
            rows.append({"anchor_id": anchor["anchor_id"], "occurrences": [
                {"occurrence_id": row["occurrence_id"], "kind": "unknown" if unknown else "term",
                 "sense_group": None if unknown else "synthetic-sense",
                 "source_evidence": [quote(row["id"])], "reason_zh": "合成词义检查。"}
                for row in occurrences], "chains": [] if unknown else [
                {"sense_group": "synthetic-sense", "occurrence_ids": [row["occurrence_id"] for row in occurrences],
                 "sides": {side: evidence(side, ids, "not_comparable" if len(ids) == 1
                                          else "no_supported_inconsistency") for side in ("L", "R")},
                 "relation": "same", "proposition_zh": "合成命题。", "reason_zh": "合成链检查。"}]})
    else:
        # This conservative opinion intentionally retains unknown for all
        # supplied records/cues; repeated words never manufacture a root link.
        unknown = True
        for record in packet["records"]:
            rows.append({"record_id": record["record_id"], "preparation_status": "unknown",
                "source_evidence": [], "reason_zh": "合成测试未判断语义正确性。",
                "root_proposition_zh": "合成未决命题。", "link_type": "unknown", "pattern": "unknown",
                "observations": [{"ids": [uid], "source_evidence": [],
                    "sides": {side: evidence(side, [uid], "unknown") for side in ("L", "R")},
                    "relation": "unknown", "proposition_zh": "合成未决命题。", "reason_zh": "合成未知。"}
                    for uid in packet["expected_ids"]]})
    value = {"profile": packet["profile"], "packet_sha256": envelope["packet_sha256"],
             "status": "unknown" if unknown else "assessed", "rows": rows, "summary_zh": "纯合成测试。"}
    return c.validate_response(envelope, value)


class TestCustodyGuard:
    """Explicit TEST stub; no Windows lock or native process is opened."""

    def __init__(self, root, workers, terminal_receipt, terminal_sha256, *, owner="evaluation_custodian"):
        self.root = Path(root).resolve()
        self.workers, self.owner = workers, owner
        self.terminal_receipt = Path(terminal_receipt).resolve()
        self.terminal_sha256 = terminal_sha256
        self.token = uuid.uuid4().hex
        self.implementation_sha256 = original._sha(Path(native.__file__))
        self.owner_record = self.root / ".judge-dispatch-receipts" / (self.token + ".json")
        self.entered = False
        self.closing = False
        self.active_callbacks = 0
        self.jobs = set()

    def _record(self, state):
        original._write(self.owner_record, {"schema": "hy30-native-judge-custody-v1", "owner": self.owner,
            "token": self.token, "workers_reserved": self.workers, "shared_limit": 6,
            "global_lock": str(self.root / ".judge-global-six.lock"), "state": state,
            "terminal_receipt": str(self.terminal_receipt), "terminal_sha256": self.terminal_sha256,
            "active_callbacks": 0, "owned_job_objects": 0, "module_sha256": self.implementation_sha256,
            "test_stub_only": True})

    def __enter__(self):
        native._receipt(self.terminal_receipt, self.terminal_sha256)
        self.entered = True
        self._record("held")
        TestCustodyGuard.active = self
        native._ACTIVE_GUARD = self
        return self

    def __exit__(self, *exception):
        self._record("drained_released")
        self.entered = False
        self.closing = True
        TestCustodyGuard.active = None
        native._ACTIVE_GUARD = None


class BridgeRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = SyntheticCohort()
        cls.fixture.setUp()
        cls.addClassCleanup(cls.fixture.doCleanups)
        with cls.fixture.seams():
            result = b.freeze_registered_consistency_frames(**cls.fixture.pins(),
                group_id="F6-terms-proposals-max32", output=cls.fixture.root / "derived/receipt.json")
            cls.cohort = result["receipt"]
            cls.material = b.validate_registered_bridge_receipt(cls.cohort, **cls.fixture.pins())

    def setUp(self):
        self.shared = self.fixture.root
        self.root = self.shared / ("run-" + uuid.uuid4().hex)
        self.calls, self.guard_entries, self.outputs = [], [], {}
        self.envelopes = {job["envelope"]["packet_sha256"]: job["envelope"] for job in self.material["jobs"]}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(self.fixture.seams())
        self.stack.enter_context(patch.object(r, "ROOT", self.shared))
        self.terminal = self.write("terminal.json", {"schema": "hy30-judge-core-terminal-receipt-v1",
            "owner": "evaluation_custodian", "core_pipeline_terminal": True,
            "native_children_drained": True, "owned_cli_batches": []})
        self.stack.enter_context(patch.object(r, "TERMINAL_SHA256", self.terminal["sha256"]))
        self.stack.enter_context(patch.object(native, "CustodyGuard", TestCustodyGuard))
        self.stack.enter_context(patch.object(native, "_ACTIVE_GUARD", None))
        self.stack.enter_context(patch.object(native, "execute", self.fake_execute))
        # Explicit TEST qualification stub, isolated from separately tested
        # handwritten native probe lifecycle. It does not grant production calls.
        self.stack.enter_context(patch.object(r, "_qualification", return_value=None))
        exe = self.shared / "never-executed-fixture.exe"
        exe.write_bytes(b"handwritten synthetic executable identity; never launched")
        self.exe = str(exe.resolve())

    def write(self, name, value):
        path = self.shared / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(integrity.canonical_bytes(value))
        return custody.identity(path)

    @staticmethod
    def read(pointer):
        path = Path(pointer["path"]) if isinstance(pointer, dict) else Path(pointer)
        return integrity.strict_parse(path.read_text(encoding="utf-8"))

    def fake_execute(self, args, prompt, cwd, attempt, timeout):
        guard = TestCustodyGuard.active
        stage = attempt.parents[2].name
        job = attempt.parent.name
        metadata = integrity.strict_parse(prompt.split("TRUSTED_RESPONSE_METADATA\n")[1]
                                         .split("\nUNTRUSTED_JUDGE_PACKET\n")[0])
        envelope = self.envelopes[metadata["packet_sha256"]]
        output = self.outputs.get((stage, job), self.outputs.get(stage, synthetic_response(envelope)))
        if isinstance(output, list):
            output = output.pop(0)
        self.calls.append({"stage": stage, "job": job, "prompt": prompt, "cwd": str(cwd),
                           "attempt": str(attempt), "token": guard.token})
        (attempt / "stdin.bin").write_bytes(prompt.encode("utf-8"))
        (attempt / "stdout.jsonl").write_bytes(b"")
        (attempt / "stderr.txt").write_bytes(b"")
        record = {"transport_status": "completed", "returncode": 0, "returned_models": ["gpt-6.1-sol"],
            "returned_efforts": ["high"], "tool_events": [], "native_dispatch_sha256": guard.implementation_sha256,
            "custody_token": guard.token, "custody_workers_reserved": guard.workers,
            "custody_receipt": str(guard.owner_record), "containment": "suspended-assign-resume-kill-on-close-job",
            "native_drain_proven": True, "native_active_processes_after_drain": 0}
        if output == "schema_failure":
            (attempt / "stdout.jsonl").write_bytes(b'{"type":"error","code":"invalid_json_schema"}\n')
            record["returncode"] = 1
        elif output == "identity_failure":
            record["returned_models"] = ["unregistered-model"]
        elif output == "stdin_failure":
            (attempt / "stdin.bin").write_bytes(b"changed submitted stdin")
            (attempt / "last-message.txt").write_bytes(integrity.canonical_bytes(synthetic_response(envelope)))
        elif output == "format_failure":
            (attempt / "last-message.txt").write_bytes(b"not JSON")
        elif output == "drain_failure":
            record["native_drain_proven"] = False
        else:
            (attempt / "last-message.txt").write_bytes(integrity.canonical_bytes(output))
        return record

    def guard(self, workers):
        self.guard_entries.append(workers)
        return TestCustodyGuard(self.shared, workers, Path(self.terminal["path"]), self.terminal["sha256"])

    def prepare(self, *, cohort=None, qualification=None):
        cohort = cohort or self.cohort
        proposal = r.protocol(kind="full_diagnostic", shared_root=self.shared, cohort=cohort,
            registration_pins=self.fixture.pins(), profile_qualification=qualification or {
                phase: {"plan": self.cohort, "seal": self.cohort} for phase in ("A", "B")})
        proposal["state"] = "root_registered_material_protocol"
        self.protocol = self.write(self.root.name + "-protocol.json", proposal)
        self.plan_pointer = r.prepare_run(self.root, cohort, self.fixture.pins(), self.protocol,
                                         expected_protocol_sha256=self.protocol["sha256"])
        self.plan = self.read(self.plan_pointer)
        return self.plan

    def kwargs(self, stage="primary", *, changes=None, workers=1, root=None):
        root = root or self.root
        proposal = r.launch_proposal(root, stage, expected_plan_sha256=self.plan_pointer["sha256"],
            executable=self.exe, cli_version="synthetic-test-only", terminal_receipt=self.terminal, workers=workers)
        proposal["state"] = "root_authorized_exact_stage"
        proposal.update(changes or {})
        launch = self.write(root.name + "-" + stage + "-launch.json", proposal)
        return {"launch_receipt": launch, "expected_launch_sha256": launch["sha256"],
            "expected_plan_sha256": self.plan_pointer["sha256"], "dispatch_guard": self.guard,
            "invoke": native.execute, "executable": self.exe, "cli_version": "synthetic-test-only", "workers": workers}

    def run_stage(self, stage="primary", **kwargs):
        pointer = r.run_stage(self.root, stage, **self.kwargs(stage, **kwargs))
        return pointer, r.validate_run_receipt(self.root, stage,
            expected_plan_sha256=self.plan_pointer["sha256"], expected_seal_sha256=pointer["sha256"])

    def resume(self, stage, pointer):
        return r.run_stage(self.root, stage, **self.kwargs(stage), expected_existing_seal_sha256=pointer["sha256"])

    def test_public_prepare_preserves_all174_original_slots_and_frozen_packets(self):
        with patch.object(b, "validate_registered_bridge_receipt", wraps=b.validate_registered_bridge_receipt) as authenticate:
            self.prepare()
        self.assertEqual(authenticate.call_count, 1)
        self.assertEqual(len(self.plan["expected_slots"]), 174)
        self.assertEqual(len(self.plan["jobs"]), 174)
        self.assertFalse(self.plan["automatic_dispatch"])
        self.assertEqual(self.calls, [])
        for job in self.plan["jobs"]:
            directory = self.root / job["bundle"]
            envelope = self.read(directory / "envelope.json")
            self.assertEqual((directory / "prompt.txt").read_text(encoding="utf-8"), prompt_contract.prompt(envelope))
            self.assertEqual((directory / "schema.json").read_bytes(), integrity.canonical_bytes(c.response_schema(job["phase"])))

    def test_bad_protocol_pin_refuses_before_run_directory_creation(self):
        proposal = r.protocol(kind="full_diagnostic", shared_root=self.shared, cohort=self.cohort,
            registration_pins=self.fixture.pins(), profile_qualification={})
        proposal["state"] = "root_registered_material_protocol"
        pointer = self.write(self.root.name + "-bad-protocol.json", proposal)
        with self.assertRaises(ValueError):
            r.prepare_run(self.root, self.cohort, self.fixture.pins(), pointer, expected_protocol_sha256="0" * 64)
        self.assertFalse(self.root.exists())

    def test_full174_fresh_review_agreed_unknown_and_external_pin_resume(self):
        self.prepare()
        with patch.object(b, "validate_registered_bridge_receipt", wraps=b.validate_registered_bridge_receipt) as authenticate:
            primary = r.run_stage(self.root, "primary", **self.kwargs())
        self.assertEqual(authenticate.call_count, 2)
        primary_summary = r.validate_run_receipt(self.root, "primary", expected_plan_sha256=self.plan_pointer["sha256"],
                                                expected_seal_sha256=primary["sha256"])
        self.assertEqual(primary_summary["succeeded"], 174)
        review, review_summary = self.run_stage("independent_review")
        final, final_summary = self.run_stage("adjudication")
        self.assertEqual(review_summary["succeeded"], 174)
        self.assertEqual(final_summary["selected_jobs"], 0)
        self.assertEqual(final_summary["unknown_or_failed_or_not_run"], 87)
        self.assertEqual(len(self.calls), 348)
        self.assertEqual(len({call["cwd"] for call in self.calls}), 348)
        for job in self.plan["jobs"]:
            a = next(call for call in self.calls if call["stage"] == "primary" and call["job"] == job["job_id"])
            z = next(call for call in self.calls if call["stage"] == "independent_review" and call["job"] == job["job_id"])
            self.assertEqual(a["prompt"], z["prompt"])
        for stage, pointer in (("primary", primary), ("independent_review", review), ("adjudication", final)):
            with patch.object(b, "validate_registered_bridge_receipt", wraps=b.validate_registered_bridge_receipt) as authenticate:
                self.assertEqual(self.resume(stage, pointer), pointer)
            self.assertEqual(authenticate.call_count, 1)
        self.assertEqual(len(self.calls), 348)
        self.assertEqual(self.guard_entries, [1, 1])

    def test_launch_scope_fields_refuse_before_any_guard_or_invoke(self):
        self.prepare()
        mutations = {"state": "proposal", "run_root": str(self.shared / "sibling"),
            "shared_root": str(self.root), "global_lock": str(self.root / ".judge-global-six.lock"),
            "stage": "independent_review", "maximum_workers": 6, "dispatch_owner": "other",
            "cli_version": "other-cli", "implementation": {}, "protocol": self.cohort,
            "plan": self.cohort, "terminal_receipt": self.cohort, "executable": self.cohort,
            "profile_qualification": {}, "prior_stage_seals": {"primary": self.cohort}}
        for key, value in mutations.items():
            with self.subTest(field=key), self.assertRaises((ValueError, KeyError, FileNotFoundError)):
                r.run_stage(self.root, "primary", **self.kwargs(changes={key: value}))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.guard_entries, [])

    def test_local_envelope_packet_schema_prompt_and_snapshot_tamper_refuse(self):
        self.prepare()
        kwargs = self.kwargs()
        job = self.plan["jobs"][0]
        directory = self.root / job["bundle"]
        targets = [directory / name for name in ("envelope.json", "packet.json", "schema.json", "prompt.txt")]
        targets.append(next((self.root / "implementation").glob("*.py")))
        for path in targets:
            before = path.read_bytes()
            try:
                path.write_bytes(before + b"tampered")
                with self.subTest(file=path.name), self.assertRaises((ValueError, KeyError)):
                    r.run_stage(self.root, "primary", **kwargs)
            finally:
                path.write_bytes(before)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.guard_entries, [])

    def test_copied_sibling_cannot_reuse_plan_or_launch(self):
        self.prepare()
        kwargs = self.kwargs()
        sibling = self.shared / ("sibling-" + uuid.uuid4().hex)
        shutil.copytree(self.root, sibling)
        with self.assertRaises(ValueError):
            r.run_stage(sibling, "primary", **kwargs)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.guard_entries, [])

    def test_review_launch_requires_exact_primary_stage_lineage(self):
        self.prepare()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.kwargs("independent_review")
        self.assertEqual(self.calls, [])

    def assert_durable_global_stop(self, failure):
        self.prepare()
        self.outputs["primary"] = failure
        pointer, summary = self.run_stage()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((self.root / "global-stop.json").is_file())
        self.resume("primary", pointer)
        review, review_summary = self.run_stage("independent_review")
        final, final_summary = self.run_stage("adjudication")
        self.resume("independent_review", review)
        self.resume("adjudication", final)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.guard_entries, [1])
        self.assertEqual(review_summary["not_run"], 174)
        self.assertEqual(final_summary["not_run"], 174)
        return pointer, summary

    def test_schema_failure_stops_all_stages_and_resume_without_retry(self):
        self.assert_durable_global_stop("schema_failure")

    def test_original_global_stop_cannot_be_deleted_or_replaced_for_later_dispatch(self):
        self.prepare()
        self.outputs["primary"] = "schema_failure"
        primary, _ = self.run_stage()
        kwargs = self.kwargs("independent_review")
        stop = self.root / "global-stop.json"
        original_stop = stop.read_bytes()
        for mutation in ("deleted", "different_reason", "different_job"):
            try:
                if mutation == "deleted":
                    stop.unlink()
                else:
                    changed = integrity.strict_parse(original_stop.decode())
                    changed["reason" if mutation == "different_reason" else "job_id"] = (
                        "integrity" if mutation == "different_reason" else "unrelated-positive-attempt")
                    stop.write_bytes(integrity.canonical_bytes(changed))
                for action in ("primary_resume", "new_review"):
                    with self.subTest(mutation=mutation, action=action), self.assertRaises((ValueError, FileNotFoundError)):
                        if action == "primary_resume":
                            self.resume("primary", primary)
                        else:
                            r.run_stage(self.root, "independent_review", **kwargs)
            finally:
                stop.write_bytes(original_stop)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.guard_entries, [1])

    def test_unsealed_original_schema_error_cannot_resume_with_missing_stop_marker(self):
        self.prepare()
        self.outputs["primary"] = "schema_failure"
        pointer, _ = self.run_stage()
        attempt = next((self.root / "stages/primary/execution").glob("*/attempt-1/attempt.json"))
        record = self.read(attempt)
        self.assertTrue(original._schema_failure(attempt.parent, record))
        ledger = attempt.parent.parent / "job.json"
        state = self.read(ledger)
        state.pop("global_invalid_json_schema", None)
        ledger.write_bytes(integrity.canonical_bytes(state))
        # Explicit synthetic interruption state: retain every original attempt,
        # launch, native output and drained lease, but publish no stage seal.
        Path(pointer["path"]).unlink()
        (self.root / "global-stop.json").unlink()
        with self.assertRaises(ValueError):
            r.run_stage(self.root, "primary", **self.kwargs())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.guard_entries, [1])

    def test_native_identity_failure_stops_all_stages_and_resume(self):
        self.assert_invalid_native_evidence_stops("identity_failure")

    def test_submitted_stdin_integrity_failure_stops_all_stages_and_resume(self):
        self.assert_invalid_native_evidence_stops("stdin_failure")

    def assert_invalid_native_evidence_stops(self, failure):
        self.prepare()
        self.outputs["primary"] = failure
        kwargs = self.kwargs()
        with self.assertRaises(ValueError):
            r.run_stage(self.root, "primary", **kwargs)
        self.assertTrue((self.root / "global-stop.json").exists())
        self.assertFalse((self.root / "stages/primary/seal.json").exists())
        for stage in r.STAGES:
            with self.subTest(stage=stage), self.assertRaises((ValueError, FileNotFoundError)):
                r.run_stage(self.root, stage, **self.kwargs(stage))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.guard_entries, [1])

    def test_missing_original_drained_lease_prevents_any_later_dispatch(self):
        pointer, _ = self.assert_durable_global_stop("schema_failure")
        path = next((self.root / "stages/primary/execution").glob("*/attempt-1/attempt.json"))
        value = self.read(path)
        lease = Path(value["drained_lease"]["path"])
        before = lease.read_bytes()
        try:
            lease.unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.resume("primary", pointer)
            review = custody.identity(self.root / "stages/independent_review/seal.json")
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.resume("independent_review", review)
        finally:
            lease.write_bytes(before)
        self.assertEqual(len(self.calls), 1)

    def test_all_attempts_exact_original_lease_token_and_positive_state_are_required(self):
        pointer, _ = self.assert_durable_global_stop("schema_failure")
        path = next((self.root / "stages/primary/execution").glob("*/attempt-1/attempt.json"))
        value = self.read(path)
        lease = Path(value["drained_lease"]["path"])
        before = lease.read_bytes()
        for changes in ({"token": "another-positive-lease"}, {"state": "held"},
                        {"active_callbacks": 1}, {"owned_job_objects": 1}, {"workers_reserved": 6},
                        {"terminal_sha256": "0" * 64}, {"module_sha256": "0" * 64}):
            changed = self.read(lease)
            changed.update(changes)
            try:
                lease.write_bytes(integrity.canonical_bytes(changed))
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    self.resume("primary", pointer)
            finally:
                lease.write_bytes(before)
        self.assertEqual(len(self.calls), 1)

    def test_registered_zero_inventory_keeps174_unknown_slots_without_guard(self):
        loaded = deepcopy(self.fixture.loaded)
        try:
            for seed in c.SEEDS:
                value = self.fixture.loaded[seed]
                for preparation in value["source_preparation_slots"]:
                    preparation["raw_response"] = '{"terms":[]}'
                for batch in self.fixture.batches:
                    scene = self.fixture.originals[batch["scene_id"]]
                    prepared = c.parse_proposals('{"terms":[]}', scene, 32)
                    window = {**scene, "id": batch["id"], "translate_ids": batch["target_ids"],
                              "context": [row for row in scene["context"] if row["id"] in batch["target_ids"]]}
                    projected = projection.project("terms", "eligibility-filtered-proposals-v1", projection.TERMS, prepared, window)
                    value["main"]["exposure_proofs"][batch["id"]] = {"status": "verified",
                        "options_sha256": c.object_hash(projected["options"]),
                        "visibility_sha256": c.object_hash(projected["visibility"])}
            frozen = b.freeze_registered_consistency_frames(**self.fixture.pins(),
                group_id="F6-terms-proposals-max32", output=self.shared / (self.root.name + "-zero.json"))
            self.prepare(cohort=frozen["receipt"])
            self.assertEqual(len(self.plan["expected_slots"]), 174)
            self.assertEqual(self.plan["jobs"], [])
            self.assertTrue(all(slot["status"] == "not_assessed_zero_inventory" for slot in self.plan["expected_slots"]))
            _, summary = self.run_stage()
            self.assertEqual(summary["unknown_or_failed_or_not_run"], 174)
            self.assertEqual(summary["succeeded"], 0)
            self.assertEqual(self.calls, [])
            self.assertEqual(self.guard_entries, [])
        finally:
            self.fixture.loaded = loaded

    def test_whole_source_reauthentication_at_postdrain_refuses_seal_on_mutation(self):
        self.prepare()
        original_intake = deepcopy(self.fixture.intakes[c.SEEDS[0]])
        original_execute = self.fake_execute
        def mutate_after_first(*args):
            result = original_execute(*args)
            self.fixture.intakes[c.SEEDS[0]]["data"]["packed"]["scenes"][0]["context"][0]["text"] = "合成源漂移。"
            return result
        try:
            with patch.object(native, "execute", mutate_after_first):
                with self.assertRaises(ValueError):
                    r.run_stage(self.root, "primary", **self.kwargs())
            self.assertFalse((self.root / "stages/primary/seal.json").exists())
            self.assertTrue(list((self.root / "stages/primary/execution").glob("*/attempt-1/attempt.json")))
            self.assertTrue(list((self.shared / ".judge-dispatch-receipts").glob("*.json")))
        finally:
            self.fixture.intakes[c.SEEDS[0]] = original_intake

    def test_retry_waits_for_original_positive_drain_and_uses_new_lease(self):
        self.prepare()
        job = self.plan["jobs"][0]
        envelope = self.read(self.root / job["bundle"] / "envelope.json")
        self.outputs[("primary", job["job_id"])] = ["format_failure", synthetic_response(envelope)]
        _, summary = self.run_stage()
        self.assertEqual(summary["succeeded"], 174)
        calls = [call for call in self.calls if call["job"] == job["job_id"]]
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0]["token"], calls[1]["token"])
        self.assertEqual(self.guard_entries, [1, 1])
        attempts = sorted((self.root / "stages/primary/execution" / job["job_id"]).glob("attempt-*/attempt.json"))
        self.assertEqual(len(attempts), 2)
        for path in attempts:
            record = self.read(path)
            lease = self.read(record["drained_lease"])
            self.assertEqual(lease["state"], "drained_released")
            self.assertEqual(lease["token"], record["custody_token"])

    def test_seal_inventory_is_stage_prefix_and_non_circular(self):
        self.prepare()
        self.outputs["primary"] = "schema_failure"
        pointer, _ = self.run_stage()
        value = self.read(pointer)
        inventory = value["inventory"]
        self.assertTrue(inventory)
        self.assertNotIn("seal.json", inventory)
        self.assertFalse(any("independent_review" in name or "adjudication" in name for name in inventory))
        self.assertEqual(self.resume("primary", pointer), pointer)
        with self.assertRaises(ValueError):
            r.run_stage(self.root, "primary", **self.kwargs())
        with self.assertRaises(ValueError):
            r.run_stage(self.root, "primary", **self.kwargs(), expected_existing_seal_sha256="0" * 64)
        self.assertEqual(len(self.calls), 1)

    def test_accepted_raw_and_canonical_snapshot_tamper_blocks_resume(self):
        self.prepare()
        pointer, _ = self.run_stage()
        job = self.plan["jobs"][0]
        attempt = self.root / "stages/primary/execution" / job["job_id"] / "attempt-1"
        raw = attempt / "last-message.txt"
        before = raw.read_bytes()
        try:
            raw.write_bytes(before + b" ")
            with self.assertRaises(ValueError):
                self.resume("primary", pointer)
        finally:
            raw.write_bytes(before)
        self.assertEqual(len(self.calls), 174)

    def test_review_covers_failed_primary_and_adjudication_cannot_replace_it(self):
        self.prepare()
        job = self.plan["jobs"][0]
        self.outputs[("primary", job["job_id"])] = ["format_failure", "format_failure"]
        _, primary = self.run_stage()
        self.assertEqual(primary["succeeded"], 173)
        _, review = self.run_stage("independent_review")
        self.assertEqual(review["succeeded"], 174)
        self.assertEqual(review["primary_unknown_slots"], 88)
        _, adjudication = self.run_stage("adjudication")
        self.assertEqual(adjudication["not_run"], 1)
        self.assertEqual(adjudication["selected_jobs"], 0)
        self.assertEqual(len(self.calls), 349)

    def test_adjudication_is_one_fresh_call_for_structural_dispute(self):
        self.prepare()
        job = next(job for job in self.plan["jobs"] if job["phase"] == "A")
        envelope = self.read(self.root / job["bundle"] / "envelope.json")
        self.run_stage()
        self.outputs[("independent_review", job["job_id"])] = synthetic_response(envelope, unknown=True)
        self.run_stage("independent_review")
        self.outputs[("adjudication", job["job_id"])] = "format_failure"
        pointer, summary = self.run_stage("adjudication")
        self.assertEqual(summary["selected_jobs"], 1)
        attempts = [call for call in self.calls if call["stage"] == "adjudication"]
        self.assertEqual(len(attempts), 1)
        self.assertIn(original.ADJUDICATION_PROMPT, attempts[0]["prompt"])
        self.assertNotIn(c.PROFILES["B"], attempts[0]["prompt"])
        self.resume("adjudication", pointer)
        self.assertEqual(len(self.calls), 349)

    def test_foreign_native_executor_and_nonconcrete_guard_refuse(self):
        self.prepare()
        kwargs = self.kwargs()
        kwargs["invoke"] = lambda *args: None
        with self.assertRaises(ValueError):
            r.run_stage(self.root, "primary", **kwargs)
        self.assertEqual(self.calls, [])
        kwargs = self.kwargs()
        kwargs["dispatch_guard"] = lambda workers: SimpleNamespace(__enter__=lambda: None)
        with self.assertRaises((ValueError, TypeError)):
            r.run_stage(self.root, "primary", **kwargs)
        self.assertEqual(self.calls, [])

    def test_guard_active_identity_and_closing_state_fail_before_callback(self):
        original_enter = TestCustodyGuard.__enter__
        for mode in ("inactive", "closing"):
            self.root = self.shared / ("invalid-guard-" + mode + uuid.uuid4().hex)
            self.prepare()
            def invalid_enter(guard):
                original_enter(guard)
                if mode == "inactive":
                    native._ACTIVE_GUARD = None
                else:
                    guard.closing = True
                return guard
            with self.subTest(mode=mode), patch.object(TestCustodyGuard, "__enter__", invalid_enter):
                with self.assertRaises(ValueError):
                    r.run_stage(self.root, "primary", **self.kwargs())
            self.assertEqual(self.calls, [])
        self.assertEqual(self.guard_entries, [1, 1])

    def test_guard_transition_during_inputs_fails_at_adjacent_invoke_gate(self):
        original_inputs = r._inputs
        for mode in ("inactive", "closing"):
            self.root = self.shared / ("guard-transition-" + mode + uuid.uuid4().hex)
            self.prepare()
            def transition_inside_inputs(*args):
                result = original_inputs(*args)
                guard = TestCustodyGuard.active
                if guard is not None:
                    if mode == "inactive":
                        native._ACTIVE_GUARD = None
                    else:
                        guard.closing = True
                return result
            kwargs = self.kwargs()
            with self.subTest(mode=mode), patch.object(r, "_inputs", side_effect=transition_inside_inputs):
                with self.assertRaises((ValueError, KeyError)):
                    r.run_stage(self.root, "primary", **kwargs)
            self.assertEqual(self.calls, [])
            self.assertTrue((self.root / "global-stop.json").exists())
            self.assertFalse((self.root / "stages/primary/seal.json").exists())
            records = list((self.root / "stages/primary/execution").glob("*/attempt-1/attempt.json"))
            self.assertTrue(records)
            for path in records:
                record = self.read(path)
                self.assertNotIn("custody_token", record)
                self.assertNotIn("custody_receipt", record)
            with self.assertRaises((ValueError, KeyError, FileNotFoundError)):
                r.run_stage(self.root, "primary", **kwargs)
            self.assertEqual(self.calls, [])
        self.assertEqual(self.guard_entries, [1, 1])

    def test_resume_remaining_attempt_is_cumulative_and_never_dispatches_attempt3(self):
        self.prepare()
        job = self.plan["jobs"][0]
        for stage in ("primary", "independent_review"):
            self.outputs[(stage, job["job_id"])] = "format_failure"
            original_attempts = r._attempts
            def interrupt_after_first_positive_wave(*args):
                result = original_attempts(*args)
                first = self.root / "stages" / stage / "execution" / job["job_id"] / "attempt-1/attempt.json"
                if first.exists() and self.read(first).get("drained_lease"):
                    raise RuntimeError("TEST interruption before wave2 after positive original lease binding")
                return result
            with self.subTest(stage=stage), patch.object(r, "_attempts", side_effect=interrupt_after_first_positive_wave):
                with self.assertRaisesRegex(RuntimeError, "TEST interruption"):
                    r.run_stage(self.root, stage, **self.kwargs(stage))
            directory = self.root / "stages" / stage / "execution" / job["job_id"]
            attempt1 = self.read(directory / "attempt-1/attempt.json")
            self.assertEqual(self.read(attempt1["drained_lease"])["state"], "drained_released")
            pointer, summary = self.run_stage(stage)
            self.assertEqual(summary["succeeded"], 173)
            self.assertEqual(len(list(directory.glob("attempt-*"))), 2)
            self.assertFalse((directory / "attempt-3").exists())
            self.resume(stage, pointer)
            self.assertEqual(len([call for call in self.calls if call["stage"] == stage]), 175)
    def test_new_handwritten_AB_probe_lifecycle_and_old757_cannot_qualify(self):
        from experiments.translation_flow import test_v2_consistency as synthetic
        fixture = synthetic.ConsistencyTests()
        fixture.setUp()
        a = c.build_phase_a(fixture.frame(), fixture.scene["id"], c.SEEDS[0], fixture.deliveries())
        envelopes = {"A": a, "B": fixture.b_packet()}
        material = self.write(self.root.name + "-handwritten.json", {
            "version": "hy30-consistency-handwritten-probe-material-v1",
            "source_independent_handwritten": True, "actual_source_scope": None,
            "translation_generation_seed": None, "semantic_accuracy_verified": False,
            "dispatch_authorized_by_this_material": False, "helper_sha256": original.HELPER_SHA256,
            "intended_calls": {"A": 1, "B": 1}, "frame": fixture.frame(), "envelopes": envelopes})
        # Restore the actual qualification function: prior material tests use
        # only the explicitly declared TEST qualification seam.
        self.stack.close()
        with self.fixture.seams(), patch.object(r, "ROOT", self.shared), \
                patch.object(r, "TERMINAL_SHA256", self.terminal["sha256"]), \
                patch.object(prompt_contract, "MATERIAL_SHA256", material["sha256"]), \
                patch.object(native, "CustodyGuard", TestCustodyGuard), \
                patch.object(native, "execute", self.fake_execute):
            self.envelopes.update({envelope["packet_sha256"]: envelope for envelope in envelopes.values()})
            proposed = r.protocol(kind="handwritten_native_probe", shared_root=self.shared, probe_material=material)
            proposed["state"] = "root_registered_material_protocol"
            protocol = self.write(self.root.name + "-probe-protocol.json", proposed)
            qualification = {}
            for phase in ("A", "B"):
                self.root = self.shared / ("probe-" + phase + uuid.uuid4().hex)
                self.plan_pointer = r.prepare_probe(self.root, phase, protocol, expected_protocol_sha256=protocol["sha256"])
                self.plan = self.read(self.plan_pointer)
                pointer, summary = self.run_stage()
                self.assertEqual(summary["succeeded"], 1)
                self.assertEqual(self.plan["maximum_attempts"], {"primary": 1})
                qualification[phase] = {"plan": self.plan_pointer, "seal": pointer}
                self.resume("primary", pointer)
                with self.assertRaises(ValueError):
                    self.kwargs("independent_review")
            self.assertEqual(len(self.calls), 2)
            self.root = self.shared / ("qualified-" + uuid.uuid4().hex)
            self.prepare(qualification=qualification)
            kwargs = self.kwargs()
            launch = self.read(kwargs["launch_receipt"])
            r._qualification(qualification, self.plan, launch)
            with self.assertRaises((ValueError, FileNotFoundError)):
                r._qualification({phase: {"plan": self.cohort, "seal": self.cohort} for phase in ("A", "B")}, self.plan, launch)
            old_plan = deepcopy(self.read(qualification["A"]["plan"]))
            old_plan.update(schema=prompt_contract.VERSION, kind="synthetic_probe")
            old_pointer = self.write("old757-test-stub/run-plan.json", old_plan)
            old_seal = self.write("old757-test-stub/seal.json", {"version": "hy30-consistency-prompt-probe-success-v2",
                "synthetic_test_only": True})
            with self.assertRaises(ValueError):
                r._qualification({"A": {"plan": old_pointer, "seal": old_seal}, "B": qualification["B"]}, self.plan, launch)
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()

