"""Exact synthetic matched-generation audit/import; no network/GPU/real corpus."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_eval import runner as e
from experiments.translation_eval.test_runner import judgment
from experiments.translation_judge import runner as j
from . import v2_delivery, v2_evaluation as v, v2_matched_evaluation as m, v2_universal_review as u
from . import test_v2_evaluation as scene_fixtures


class ProtocolArchiveTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.base = self.root / "evaluation"
        self.protocol = self.base / "summaries/matched-validation.json"
        self.protocol.parent.mkdir(parents=True)
        self.stage = self.base / "implementation-staging/next-protocols-v1"
        self.backup = self.base / "implementation-staging/pre-promotion-r2-backup"
        self.relative = "experiments/translation_flow/v2_prepare.py"
        self.live = self.workspace / self.relative
        self.live.parent.mkdir(parents=True)
        self.original_bytes = b"MARKER = 'original'\ndef verify_source_freeze(*args, **kwargs):\n    raise ValueError('original source gate executed')\n"
        self.live.write_bytes(self.original_bytes)
        self.pointer = u.identity(self.live)
        self.archive = self.backup / self.relative
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(self.original_bytes)
        self.live.write_bytes(b"MARKER = 'promoted'\n")
        self.stage.mkdir(parents=True)
        self.staging = self.stage / "staging-manifest.json"
        e.dump(self.staging, {"schema": "source-only-implementation-staging-v1",
            "original_root": str(self.workspace), "stage_root": str(self.stage),
            "files": [{"path": self.relative, "sha256": self.pointer["sha256"]}]})
        self.row = {"path": self.relative, "change_type": "modified",
            "original_baseline_sha256": self.pointer["sha256"], "current_original_sha256": self.pointer["sha256"],
            "original_matches_baseline": True, "staged_sha256": e.sha(self.live)}
        self.manifest = self.stage / "promotion-manifest-r2.json"
        e.dump(self.manifest, {"schema": "source-only-promotion-review-v1",
            "original_root": str(self.workspace), "stage_root": str(self.stage),
            "staging_manifest_sha256": e.sha(self.staging), "files": [self.row]})
        self.receipt = self.protocol.parent / "runtime-promotion-r2.json"
        e.dump(self.receipt, {"schema": "root-runtime-promotion-v1", "promotion_manifest": u.identity(self.manifest),
            "files": [self.row], "backup": str(self.backup)})
        pin = patch.object(m, "PROMOTION_RECEIPT_SHA256", e.sha(self.receipt))
        pin.start()
        self.addCleanup(pin.stop)

    def test_exact_archive_binding_and_original_module_execution(self):
        before = self.live.read_bytes()
        resolution = m.resolve_protocol_dependency(self.pointer, self.protocol)
        self.assertEqual(resolution["resolved_pointer"], u.identity(self.archive))
        self.assertEqual(resolution["archive_authority"], u.identity(self.receipt))
        module, checked = m.load_protocol_module(self.pointer, self.protocol)
        self.assertEqual(checked, resolution)
        self.assertEqual(module.MARKER, "original")
        with self.assertRaisesRegex(ValueError, "original source gate executed"):
            module.verify_source_freeze(None, None)
        self.assertEqual(self.live.read_bytes(), before)

    def test_altered_archive_rejected_and_future_live_changes_stay_separate(self):
        self.archive.write_bytes(self.original_bytes + b"# tamper\n")
        with self.assertRaisesRegex(ValueError, "archived original bytes changed"):
            m.resolve_protocol_dependency(self.pointer, self.protocol)
        self.archive.write_bytes(self.original_bytes)
        self.live.write_bytes(b"unrecorded promotion")
        resolution = m.resolve_protocol_dependency(self.pointer, self.protocol)
        self.assertEqual(resolution["live_pointer"], u.identity(self.live))
        self.assertFalse(resolution["live_matches_promoted"])
        self.assertEqual(resolution["resolved_pointer"], u.identity(self.archive))

    def test_unbound_same_hash_neighbor_and_mutated_authorities_are_rejected(self):
        (self.protocol.parent / "v2_prepare.py").write_bytes(self.original_bytes)
        self.receipt.unlink()
        with self.assertRaisesRegex(ValueError, "archive authority"):
            m.resolve_protocol_dependency(self.pointer, self.protocol)

    def test_manifest_and_staging_bindings_are_checked(self):
        self.staging.write_bytes(self.staging.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "staging authority changed"):
            m.resolve_protocol_dependency(self.pointer, self.protocol)
        self.manifest.write_bytes(self.manifest.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            m.resolve_protocol_dependency(self.pointer, self.protocol)

    def test_original_live_bytes_need_no_archive_and_unsupported_files_never_fallback(self):
        self.live.write_bytes(self.original_bytes)
        self.receipt.unlink()
        self.assertEqual(m.resolve_protocol_dependency(self.pointer, self.protocol)["binding"], "original_live_bytes")
        self.live.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            m.resolve_protocol_dependency(self.pointer, self.protocol)

    def test_protocol_keeps_frozen_bytes_and_exports_additive_resolution(self):
        e.dump(self.protocol, {"version": m.VALIDATION_VERSION,
            "state": "frozen_before_any_candidate_quality_inspection", "window_ids": ["w"],
            "generation_seeds": [1], "matched_workload": {"windows": 1},
            "timing_declaration": {"candidate_quality_results_inspected": False},
            "offline_audit_implementation": [self.pointer]})
        before = self.protocol.read_bytes()
        identity, value = m._protocol(self.protocol)
        self.assertEqual(identity["sha256"], m._hash(before))
        self.assertEqual(value["offline_audit_implementation"], [self.pointer])
        self.assertEqual(value["_protocol_dependency_resolution"]["source_gate_authority"]["resolved_pointer"], u.identity(self.archive))
        self.assertEqual(self.protocol.read_bytes(), before)


class MatchedEvaluationTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        tempdir = patch.object(tempfile, "tempdir", self.temp.name)
        tempdir.start()
        self.addCleanup(tempdir.stop)
        self.fixture = scene_fixtures.SceneEvaluationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.donor = self.root / "donor"
        self.target = self.root / "target"
        self.calls = []
        self.review_score = 4
        self.old_delivery = self.fixture.delivery("old")
        v.prepare(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path,
                  {"A": self.old_delivery}, self.donor, reference_freeze_path=self.fixture.freeze_path)
        self.selected = [row["id"] for row in self.fixture.windows if row["scene_id"] == "scene-a"]
        self.policy_path = self.root / "policy.json"
        e.dump(self.policy_path, {"version": "synthetic-policy"})
        self.universal_path = self.root / "universal-scope.json"
        pointers = {"decision_policy": u.identity(self.policy_path),
                    "source_manifest": u.identity(self.fixture.manifest_path),
                    "source_freeze": u.identity(self.fixture.source / "freeze-manifest.json"),
                    "reference_freeze": u.identity(self.fixture.freeze_path)}
        e.dump(self.universal_path, {"version": u.VERSION, "state": "frozen_before_candidate_quality",
            "selection": "all_expected_windows", "candidate_quality_judgments_started": False,
            "no_judge_statuses": sorted(e.NO_JUDGE_STATUSES), "baseline_windows_per_seed": 3, **pointers})
        u.apply_universal_scope(self.donor, self.universal_path)
        self.protocol_path = self.root / "matched-validation.json"
        old = e.read_json(self.donor / "run.json")["candidates"]["A"]
        self.card_path = self.root / "matched-card.json"
        e.dump(self.card_path, {"version": "synthetic-matched-card"})
        e.dump(self.protocol_path, {"version": m.VALIDATION_VERSION,
            "state": "frozen_before_any_candidate_quality_inspection", "window_ids": self.selected,
            "generation_seeds": [old["seed"]], "matched_workload": {"windows": 2, "scenes": 1},
            "source_scenes": u.identity(self.fixture.scene_path),
            "timing_declaration": {"candidate_quality_results_inspected": False},
            "seed_controls": [{"seed": old["seed"], "matched_card": u.identity(self.card_path),
                                "old_original_run": old["original_generation_cost_identity"]}],
            **pointers})
        self.scope_path = self.root / "matched-scope.json"
        e.dump(self.scope_path, {"version": m.SCOPE_VERSION, "state": "frozen_before_candidate_quality_inspection",
            "selection": "explicit_matched_windows", "window_ids": self.selected, "expected_windows_per_seed": 2,
            "generation_seeds": [old["seed"]], "validation_protocol": u.identity(self.protocol_path),
            "timing_declaration": {"candidate_quality_results_inspected": False},
            "universal_review_policy": u.identity(self.universal_path), **pointers})

    def fake(self, args, prompt, cwd, attempt, timeout):
        packet = json.loads(prompt.split("\nPACKET:\n", 1)[1].split("\nADJUDICATION:\n", 1)[0])
        phase = attempt.parents[2].name
        self.calls.append((phase, packet["window_id"], prompt.encode("utf-8")))
        record = judgment(packet, self.review_score if phase == "review" else 4)
        if phase == "adjudication":
            record.update(resolved=True, resolution_zh="合成裁决。")
        e.dump(attempt / "last-message.txt", record)
        return {"transport_status": "completed", "returncode": 0, "returned_models": [j.MODEL],
                "returned_efforts": [j.EFFORT], "tool_events": [], "elapsed_seconds": .25}

    def execute(self, root, filename):
        for descriptor in e.load_jsonl(root / filename):
            self.assertEqual(j.run_job(root, descriptor, "fake", "fake-1", 1, self.fake)["status"], "succeeded")

    def seal(self):
        e.dump(self.donor / "finalization-manifest.json", {"version": u.SEAL_VERSION,
            "state": "required_fresh_judgments_completed", "accepted_raw_canonical_integrity_verified": True,
            "files": [{"path": p.relative_to(self.donor).as_posix(), "sha256": e.sha(p)}
                      for p in sorted(self.donor.rglob("*")) if p.is_file()
                      and p.name not in {"finalization-manifest.json", ".judge-scheduler.lock"}],
            **{name: u.identity(self.donor / filename) for name, filename in (
                ("run", "run.json"), ("expected", "expected.jsonl"), ("final", "final.jsonl"))}})

    def complete_donor(self):
        self.execute(self.donor, "jobs.jsonl")
        e.finalize(self.donor)
        self.execute(self.donor, "jobs-review.jsonl")
        e.finalize(self.donor)
        self.execute(self.donor, "jobs-adjudication.jsonl")
        e.finalize(self.donor)
        self.seal()

    def fresh_delivery(self, changed=False, states=None):
        delivery = self.fixture.delivery("new", states=states, scene_ids=["scene-a"])
        if changed:
            raw = self.root / "new-run"
            uid = "scene-a-J2"
            for name in ("results", "ledger"):
                rows = e.load_jsonl(raw / (name + ".jsonl"))
                for row in rows:
                    if uid in row["translations"]:
                        row["translations"][uid] += "新输出"
                e.dump_jsonl(raw / (name + ".jsonl"), rows)
            delivery = self.root / "changed-delivery"
            v2_delivery.deliver(self.fixture.manifest_path, self.root / "new-prepared/packed-mapping.json", raw, delivery)
        return delivery

    def prepare_target(self, changed=False):
        delivery = self.fresh_delivery(changed)
        v.prepare(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path,
                  {"A": delivery}, self.target, reference_freeze_path=self.fixture.freeze_path,
                  window_ids=self.selected)
        return delivery

    def import_target(self):
        return m.import_prepared(self.target, self.donor, validation_protocol_path=self.protocol_path,
                                 matched_scope_path=self.scope_path, universal_scope_path=self.universal_path)

    def test_qualification_executes_validated_original_gate_instead_of_promoted_gate(self):
        self.prepare_target()
        archive = ProtocolArchiveTests()
        archive.setUp()
        self.addCleanup(archive.doCleanups)
        e.dump(archive.protocol, {**e.read_json(self.protocol_path),
            "offline_audit_implementation": [archive.pointer]})
        _, protocol = m._protocol(archive.protocol)
        with patch.object(m.p, "verify_source_freeze", side_effect=AssertionError("live gate used")) as live:
            with self.assertRaisesRegex(ValueError, "original source gate executed"):
                m._qualification(e.read_json(self.target / "run.json"), self.target, protocol)
            live.assert_not_called()

    def hashes(self, root):
        return {p.relative_to(root).as_posix(): e.sha(p) for p in root.rglob("*") if p.is_file()}

    def legacy_qualification_metadata(self, *, bound=True):
        run = e.read_json(self.donor / "run.json")
        run["p_flow_contract"].pop("source_qualification_freeze")
        run["frozen_artifact_sha256"].pop("source-qualification-freeze.json")
        if bound:
            run["p_flow_contract"]["candidate_artifacts"]["A"]["artifacts"].append(
                u.identity(self.fixture.source / "freeze-manifest.json"))
        e.dump(self.donor / "p-flow-scene-contract.json", run["p_flow_contract"])
        run["frozen_artifact_sha256"]["p-flow-scene-contract.json"] = e.sha(self.donor / "p-flow-scene-contract.json")
        e.dump(self.donor / "run.json", run)

    def test_legacy_donor_qualification_is_recovered_only_from_bound_candidate_artifact(self):
        self.legacy_qualification_metadata()
        self.complete_donor()
        self.prepare_target()
        original = self.hashes(self.donor)
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        proof = self.import_target()
        qualification = proof["source_qualification_bindings"]["donor"]
        self.assertEqual(qualification["canonical_source_qualification_freeze"],
                         u.identity(self.fixture.source / "freeze-manifest.json"))
        self.assertEqual(qualification["evidence"][0]["binding"], "legacy_recorded_candidate_artifact")
        self.assertTrue(audit["all_complete_inputs_identical"])
        self.assertEqual(self.hashes(self.donor), original)
        self.assertNotIn("source_qualification_freeze", e.read_json(self.donor / "run.json")["p_flow_contract"])

    def test_legacy_unbound_adjacent_qualification_is_not_inferred(self):
        self.legacy_qualification_metadata(bound=False)
        self.complete_donor()
        self.prepare_target()
        with self.assertRaisesRegex(ValueError, "hash-bound donor preparation evidence"):
            self.import_target()
        self.assertFalse((self.target / "judge-execution").exists())

    def test_legacy_qualification_cannot_bind_an_alternate_accepted_reference(self):
        self.legacy_qualification_metadata()
        self.complete_donor()
        self.prepare_target()
        donor_run = e.read_json(self.donor / "run.json")
        protocol = e.read_json(self.protocol_path)
        alternate = self.root / "alternate-reference-freeze.json"
        e.dump(alternate, e.read_json(self.fixture.freeze_path))
        donor_run["p_flow_contract"]["reference_freeze"] = {**u.identity(alternate),
            "corpus_version": v.REFERENCE_VERSION, "state": "frozen_double_fresh_reference_review"}
        with self.assertRaisesRegex(ValueError, "reference identity differs"):
            m._qualification(donor_run, self.donor, protocol, allow_legacy=True)

    def test_legacy_recorded_qualification_evidence_must_keep_its_original_hash(self):
        self.legacy_qualification_metadata()
        run = e.read_json(self.donor / "run.json")
        run["p_flow_contract"]["candidate_artifacts"]["A"]["artifacts"][-1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "provenance pointer changed"):
            m._qualification(run, self.donor, e.read_json(self.protocol_path), allow_legacy=True)

    def test_legacy_preparation_frozen_metadata_copy_proves_same_canonical_qualification(self):
        self.legacy_qualification_metadata(bound=False)
        run = e.read_json(self.donor / "run.json")
        run["frozen_artifact_sha256"]["source-qualification-freeze.json"] = e.sha(self.donor / "source-qualification-freeze.json")
        e.dump(self.donor / "run.json", run)
        self.complete_donor()
        self.prepare_target()
        original = self.hashes(self.donor)
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        evidence = audit["source_qualification_bindings"]["donor"]["evidence"]
        self.assertEqual(evidence[0]["binding"], "legacy_frozen_metadata_artifact")
        self.assertEqual(self.hashes(self.donor), original)

    def test_pure_rendered_transport_bytes_match_actual_run_job_fingerprint_and_prompt(self):
        descriptor = e.load_jsonl(self.donor / "jobs.jsonl")[0]
        material = m._material(self.donor, descriptor)
        state = j.run_job(self.donor, descriptor, "fake", "fake-1", 1, self.fake)
        self.assertEqual(material["fingerprint"], state["fingerprint"])
        self.assertEqual(material["rendered_prompt"], self.calls[-1][2])
        raw = Path(state["accepted_raw_response"])
        self.assertEqual(material["schema_bytes"], (raw.parent / "schema.json").read_bytes())
        self.assertEqual(material["prompt_file_bytes"], (raw.parent / "prompt.txt").read_bytes())
        self.assertEqual(material["transport_contract"], material["task_bytes"])
        self.assertIsNone(material["dispute_fingerprint"])

    def test_audit_exact_subset_identity_is_complete_without_import_or_quality_writes(self):
        self.complete_donor()
        self.prepare_target()
        original, target_original = self.hashes(self.donor), self.hashes(self.target)
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        self.assertTrue(audit["all_primary_review_inputs_identical"])
        self.assertTrue(audit["all_complete_inputs_identical"])
        self.assertEqual(audit["complete_input_status"], "complete")
        self.assertEqual(len(audit["records"]), 6)
        self.assertEqual(audit["expected_records"], 2)
        self.assertNotEqual(audit["target_generation"], audit["donor_generation"])
        self.assertEqual(self.hashes(self.target), target_original)
        self.assertEqual(self.hashes(self.donor), original)
        self.assertNotIn("合成译文", json.dumps(audit, ensure_ascii=False))

    def test_exact_inputs_import_all_primary_review_without_repeating_and_keep_separate_generation(self):
        self.complete_donor()
        original = self.hashes(self.donor)
        self.prepare_target()
        count = len(self.calls)
        proof = self.import_target()
        self.assertEqual(proof["imported_phase_counts"], {"primary": 2, "review": 2, "adjudication": 0})
        self.assertEqual(proof["fresh_required_phase_counts"], {"primary": 0, "review": 0, "adjudication": 0})
        self.execute(self.target, "jobs.jsonl")
        self.execute(self.target, "jobs-review.jsonl")
        self.assertEqual(len(self.calls), count)
        e.finalize(self.target)
        self.assertEqual(len(e.load_jsonl(self.target / "final.jsonl")), 2)
        self.assertTrue(e.read_json(self.target / "summary.json")["universal_review_coverage"]["complete"])
        run = e.read_json(self.target / "run.json")
        self.assertEqual(run["matched_control_scope"]["expected_windows_per_seed"], 2)
        self.assertEqual(run["matched_judgment_import"]["manifest"]["sha256"], e.sha(self.target / "matched-judgment-import.json"))
        self.assertNotEqual(run["candidates"]["A"]["original_generation_cost_identity"],
                            e.read_json(self.donor / "run.json")["candidates"]["A"]["original_generation_cost_identity"])
        self.assertEqual(self.hashes(self.donor), original)

    def test_changed_complete_packet_requires_fresh_both_phases_only_for_changed_window(self):
        self.complete_donor()
        self.prepare_target(changed=True)
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        self.assertFalse(audit["all_complete_inputs_identical"])
        proof = self.import_target()
        self.assertEqual(proof["imported_phase_counts"], {"primary": 1, "review": 1, "adjudication": 0})
        self.assertEqual(proof["fresh_required_phase_counts"], {"primary": 1, "review": 1, "adjudication": 0})
        count = len(self.calls)
        self.execute(self.target, "jobs.jsonl")
        e.finalize(self.target)
        self.execute(self.target, "jobs-review.jsonl")
        e.finalize(self.target)
        self.assertEqual(len(self.calls), count + 2)
        self.assertEqual({item[1] for item in self.calls[count:]}, {"scene-a-Q2"})

    def test_pending_adjudication_is_unknown_then_actual_same_dispute_imports_without_repeat(self):
        self.review_score = 3
        self.complete_donor()
        self.prepare_target()
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        self.assertTrue(audit["all_primary_review_inputs_identical"])
        self.assertIsNone(audit["all_complete_inputs_identical"])
        self.assertEqual(audit["complete_input_status"], "incomplete_adjudication_material")
        self.import_target()
        e.finalize(self.target)
        proof = m.import_adjudication(self.target, self.donor)
        self.assertEqual(proof["imported_phase_counts"]["adjudication"], 2)
        count = len(self.calls)
        self.execute(self.target, "jobs-adjudication.jsonl")
        self.assertEqual(len(self.calls), count)
        proof2 = m.import_adjudication(self.target, self.donor)
        self.assertEqual(len(proof2["imported_jobs"]), len(proof["imported_jobs"]))
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        self.assertTrue(audit["all_complete_inputs_identical"])
        for descriptor in e.load_jsonl(self.target / "jobs-adjudication.jsonl"):
            material = m._material(self.target, descriptor)
            self.assertEqual(material["dispute_fingerprint"], material["fingerprint"].encode("ascii"))

    def test_different_actual_dispute_stays_fresh_even_with_same_packet(self):
        self.review_score = 3
        self.complete_donor()
        self.prepare_target()
        self.import_target()
        e.finalize(self.target)
        descriptor = e.load_jsonl(self.target / "jobs-adjudication.jsonl")[0]
        dispute = self.target / descriptor["dispute"]
        dispute.write_bytes(dispute.read_bytes() + b" ")
        proof = m.import_adjudication(self.target, self.donor)
        self.assertEqual(proof["imported_phase_counts"]["adjudication"], 1)
        self.assertEqual(proof["fresh_required_phase_counts"]["adjudication"], 1)
        self.assertFalse((self.target / "judge-execution" / descriptor["job_id"]).exists())

    def test_raw_packet_format_schema_and_settings_bytes_are_not_semantically_normalized(self):
        packet = (self.donor / e.load_jsonl(self.donor / "jobs.jsonl")[0]["packet"]).read_bytes()
        prompt = (self.donor / "judge-prompt.txt").read_bytes()
        original = m.render_material(packet, prompt)
        changed = m.render_material(packet + b" ", prompt)
        self.assertEqual(original["fingerprint"], changed["fingerprint"])
        self.assertNotEqual(original["packet_bytes"], changed["packet_bytes"])
        settings = {"model": j.MODEL, "effort": "medium", "overrides": j.OVERRIDES,
                    "disabled_features": j.DISABLED_FEATURES}
        self.assertNotEqual(original["settings_bytes"], m.render_material(packet, prompt, settings=settings)["settings_bytes"])
        self.complete_donor()
        schema = next((self.donor / "judge-execution/review").rglob("schema.json"))
        schema.write_bytes(schema.read_bytes() + b" ")
        self.seal()
        self.prepare_target()
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        self.assertFalse(audit["all_complete_inputs_identical"])
        failed = [row for row in audit["records"] if row["decision"] == "fresh_required"]
        self.assertEqual(len(failed), 1)
        self.assertFalse(failed[0]["equal_components"]["schema_bytes"])

    def test_donor_tamper_replayed_fingerprint_and_extra_inventory_refuse_before_import(self):
        self.complete_donor()
        self.prepare_target()
        ledger = next((self.donor / "judge-execution").rglob("job.json"))
        state = e.read_json(ledger)
        raw = Path(state["accepted_raw_response"])
        original = raw.read_bytes()
        raw.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            self.import_target()
        raw.write_bytes(original)
        state["fingerprint"] = "0" * 64
        e.dump(ledger, state)
        self.seal()
        with self.assertRaisesRegex(ValueError, "packet/settings changed"):
            self.import_target()
        self.assertFalse((self.target / "judge-execution").exists())

    @unittest.skipUnless(os.name == "nt", "native Windows extended drive relocation")
    def test_extended_paths_and_original_ledger_are_preserved_without_escape_weakening(self):
        self.complete_donor()
        for ledger in (self.donor / "judge-execution").rglob("job.json"):
            state = e.read_json(ledger)
            for name in u.RELOCATED_FIELDS:
                state[name] = "\\\\?\\" + state[name]
            e.dump(ledger, state)
        self.seal()
        original = self.hashes(self.donor)
        self.prepare_target()
        proof = self.import_target()
        for item in proof["imported_jobs"]:
            state = e.read_json(Path(item["new_ledger"]["path"]))
            donor = e.read_json(Path(item["original_ledger_copy"]["path"]))
            self.assertEqual(state["attempts"], donor["attempts"])
            for name in u.RELOCATED_FIELDS:
                self.assertTrue(Path(state[name]).is_relative_to(self.target))
            self.assertEqual(state["fingerprint"], donor["fingerprint"])
        self.assertEqual(self.hashes(self.donor), original)

    def test_validation_protocol_cannot_be_used_as_scope_and_exact_order_is_frozen(self):
        with self.assertRaises((ValueError, KeyError)):
            m.scope_metadata(self.protocol_path, self.protocol_path)
        with self.assertRaisesRegex(ValueError, "declaration differs"):
            m.scope_metadata(self.scope_path, {**u.identity(self.protocol_path), "version": "incorrect-version"})
        scope = e.read_json(self.scope_path)
        e.dump(self.scope_path, {**scope, "window_ids": list(reversed(scope["window_ids"]))})
        with self.assertRaisesRegex(ValueError, "distinct prior-inspection"):
            m.scope_metadata(self.scope_path, self.protocol_path)
        e.dump(self.scope_path, scope)
        protocol = e.read_json(self.protocol_path)
        e.dump(self.protocol_path, {**protocol, "timing_declaration": {"candidate_quality_results_inspected": True}})
        with self.assertRaisesRegex(ValueError, "frozen explicit workload"):
            m.scope_metadata(self.scope_path, self.protocol_path)

    def test_format_only_packet_change_requires_fresh_even_when_task_fingerprint_matches(self):
        self.complete_donor()
        self.prepare_target()
        run = e.read_json(self.target / "run.json")
        name = next(iter(run["packet_sha256"]))
        packet = self.target / name
        packet.write_bytes(packet.read_bytes() + b" ")
        run["packet_sha256"][name] = e.sha(packet)
        e.dump(self.target / "run.json", run)
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        fresh = [row for row in audit["records"] if row["decision"] == "fresh_required"]
        self.assertEqual(len(fresh), 2)
        self.assertTrue(all(row["equal_components"]["fingerprint"] for row in fresh))
        self.assertTrue(all(not row["equal_components"]["packet_bytes"] for row in fresh))

    def test_changed_no_judge_delivery_cannot_pass_old_projection_equivalence(self):
        self.complete_donor()
        delivery = self.fresh_delivery(states={"scene-a-J2": "translation_failed"})
        v.prepare(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path,
                  {"A": delivery}, self.target, reference_freeze_path=self.fixture.freeze_path, window_ids=self.selected)
        audit = m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        self.assertFalse(audit["all_complete_inputs_identical"])
        self.assertFalse(audit["mechanical_no_judge_inputs_identical"])
        proof = self.import_target()
        self.assertEqual(proof["imported_phase_counts"], {"primary": 1, "review": 1, "adjudication": 0})
        e.finalize(self.target)
        final = {row["window_id"]: row for row in e.load_jsonl(self.target / "final.jsonl")}
        self.assertEqual(final["scene-a-Q2"]["status"], "delivery_zero")
        self.assertEqual(final["scene-a-Q2"]["semantic"], 0)

    def test_donor_true_job_escape_and_missing_canonical_never_restore_or_import(self):
        self.complete_donor()
        self.prepare_target()
        ledger = next((self.donor / "judge-execution").rglob("job.json"))
        state = e.read_json(ledger)
        outside = self.root / "outside-job-raw.txt"
        outside.write_bytes(Path(state["accepted_raw_response"]).read_bytes())
        escaped = {**state, "accepted_raw_response": str(outside)}
        e.dump(ledger, escaped)
        self.seal()
        with self.assertRaisesRegex(ValueError, "escapes job directory"):
            self.import_target()
        e.dump(ledger, state)
        canonical = Path(state["response"])
        canonical.unlink()
        self.seal()
        with self.assertRaises(OSError):
            self.import_target()
        self.assertFalse(canonical.exists())
        self.assertFalse((self.target / "judge-execution").exists())

    def test_adjudication_complete_requires_accepted_pairs_and_matches_actual_job_set(self):
        self.complete_donor()
        self.prepare_target(changed=True)
        self.import_target()
        e.dump_jsonl(self.target / "jobs-adjudication.jsonl", [])
        with self.assertRaises(OSError):
            m.import_adjudication(self.target, self.donor)
        self.assertFalse(e.read_json(self.target / "matched-judgment-import.json")["adjudication_material_complete"])
        self.execute(self.target, "jobs.jsonl")
        e.finalize(self.target)
        self.execute(self.target, "jobs-review.jsonl")
        e.finalize(self.target)
        proof = m.import_adjudication(self.target, self.donor)
        self.assertTrue(proof["adjudication_material_complete"])
        self.assertEqual({row["job_id"] for row in proof["adjudication_audits"]},
                         {row["job_id"] for row in e.load_jsonl(self.target / "jobs-adjudication.jsonl")})
        run = e.read_json(self.target / "run.json")
        run["matched_judgment_import"]["donor_root"] = str(self.root / "another-donor")
        e.dump(self.target / "run.json", run)
        with self.assertRaisesRegex(ValueError, "envelope differs"):
            m.import_adjudication(self.target, self.donor)

    def test_mixed_full_delivery_generation_is_rejected_and_prepare_matched_calls_adapter(self):
        self.complete_donor()
        delivery = self.fixture.delivery("new-full")
        v.prepare(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path, {"A": delivery},
                  self.target, reference_freeze_path=self.fixture.freeze_path, window_ids=self.selected)
        with self.assertRaisesRegex(ValueError, "exact selected workload"):
            m.audit_complete_inputs(self.target, self.donor, self.protocol_path)
        new_target = self.root / "actual-api-target"
        exact = self.fixture.delivery("new-exact", scene_ids=["scene-a"])
        proof = m.prepare_matched(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path,
            {"A": exact}, new_target, reference_freeze_path=self.fixture.freeze_path, window_ids=self.selected,
            donor_root=self.donor, validation_protocol_path=self.protocol_path, matched_scope_path=self.scope_path,
            universal_scope_path=self.universal_path)
        self.assertEqual(proof["expected_records"], 2)
        original = self.hashes(self.donor)
        with self.assertRaisesRegex(ValueError, "disjoint"):
            m.prepare_matched(self.fixture.manifest_path, self.fixture.input_path, self.fixture.reference_path,
                {"A": exact}, self.donor / "unsafe-child", reference_freeze_path=self.fixture.freeze_path,
                window_ids=self.selected, donor_root=self.donor, validation_protocol_path=self.protocol_path,
                matched_scope_path=self.scope_path, universal_scope_path=self.universal_path)
        self.assertEqual(self.hashes(self.donor), original)


if __name__ == "__main__":
    unittest.main()
