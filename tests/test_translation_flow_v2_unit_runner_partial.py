"""Bounded offline tests for the NEW closed partial auxiliary binding.

Authentic handwritten frame: 48 scenes, 48 scored windows, 252 source cues,
84 scheduled/selected batches per seed; no production 29/3606/734 claim.
The source-freeze root authority seam is TEST-only. Worker/parser, all present
factories, shared callback, custody and consumer preparation are real APIs.
Candidate08/10 remain explicit administrative unknown, never fabricated proofs.
No corpus/reference/retained trial/native process/GPU/network is accessed.
"""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from experiments.translation_flow import test_v2_unit_main_proof as original
from experiments.translation_flow import test_v2_unit_custody as fixtures
from experiments.translation_flow import v2_unit_runner_partial as runner
from experiments.translation_flow import v2_unit_diagnostics as diagnostics
from experiments.translation_flow import v2_unit_custody as custody
from experiments.translation_flow import v2_delivery as delivery
from experiments.translation_flow import v2_worker as worker
from experiments.translation_flow import v2_trial, v2_execute
from experiments.translation_flow.test_v2_worker import settings, result
from experiments.translation_flow.test_worker import budget
from tests import test_translation_flow_v2_unit_runner_singleton as prior

FIXED_ENGINE = original.FIXED_ENGINE


class BoundedRunnerRegressionTests(unittest.TestCase):
    def setUp(self):
        alias = patch.object(prior, "runner", runner)
        alias.start()
        self.addCleanup(alias.stop)
        prior.UnitRunnerTests.setUp(self)

    def write(self, name, value):
        value = deepcopy(value)
        if isinstance(value, dict) and isinstance(value.get("schema"), str):
            value["schema"] = value["schema"].replace("hy30-F5-unit-singleton-", "hy30-F5-unit-partial-")
        return prior.UnitRunnerTests.write(self, name, value)

    source_frame = prior.UnitRunnerTests.source_frame
    source_registration_fixture = prior.UnitRunnerTests.source_registration_fixture
    freeze_source_protocol = prior.UnitRunnerTests.freeze_source_protocol
    fixture_run = prior.UnitRunnerTests.fixture_run
    phase = prior.UnitRunnerTests.phase
    launch = prior.UnitRunnerTests.launch
    native_probe = prior.UnitRunnerTests.native_probe
    dispatch = prior.UnitRunnerTests.dispatch
    stage_completions = prior.UnitRunnerTests.stage_completions
    check_probe = prior.UnitRunnerTests.check_probe
    test_source_only_reliability_has_exact_per_seed_count_and_is_deterministic = prior.UnitRunnerTests.test_source_only_reliability_has_exact_per_seed_count_and_is_deterministic
    test_phase_retains_252_slots_but_504_and_252_view_limits = prior.UnitRunnerTests.test_phase_retains_252_slots_but_504_and_252_view_limits
    test_format_and_transport_failures_retry_with_contiguous_locked_budget = prior.UnitRunnerTests.test_format_and_transport_failures_retry_with_contiguous_locked_budget
    test_auth_failure_is_terminal_and_retains_unknown_usage = prior.UnitRunnerTests.test_auth_failure_is_terminal_and_retains_unknown_usage
    test_launch_wrong_owner_model_root_worker_budget_rejected_before_call = prior.UnitRunnerTests.test_launch_wrong_owner_model_root_worker_budget_rejected_before_call
    test_native_returned_model_tools_or_drain_drift_cannot_be_accepted = prior.UnitRunnerTests.test_native_returned_model_tools_or_drain_drift_cannot_be_accepted
    test_original_cost_unique_once_without_view_multiplication = prior.UnitRunnerTests.test_original_cost_unique_once_without_view_multiplication
    test_started_attempt_without_terminal_drain_cannot_resume_as_free_retry = prior.UnitRunnerTests.test_started_attempt_without_terminal_drain_cannot_resume_as_free_retry
    test_original_module_identities_remain_fixed = prior.UnitRunnerTests.test_original_module_identities_remain_fixed
    test_custody_uses_one_explicit_source_pinned_registry_callback = prior.UnitRunnerTests.test_custody_uses_one_explicit_source_pinned_registry_callback
    test_present_registry_receipt_cannot_be_replaced_by_unavailable = prior.UnitRunnerTests.test_present_registry_receipt_cannot_be_replaced_by_unavailable
    test_registry_slots_cannot_relabel_candidate_seed_or_role = prior.UnitRunnerTests.test_registry_slots_cannot_relabel_candidate_seed_or_role
    test_registry_external_registration_cannot_drift = prior.UnitRunnerTests.test_registry_external_registration_cannot_drift
    test_prepare_requires_independent_registry_hash = prior.UnitRunnerTests.test_prepare_requires_independent_registry_hash
    test_original_profile_probe_cannot_qualify_singleton_binding = prior.UnitRunnerTests.test_original_profile_probe_cannot_qualify_singleton_binding
    test_bounded_failed_transport_cost_and_unknown_tails_keep_fixed_denominator = prior.UnitRunnerTests.test_bounded_failed_transport_cost_and_unknown_tails_keep_fixed_denominator
    test_no_main_evidence_keeps_all_seed_slots_unavailable_with_zero_calls = prior.UnitRunnerTests.test_no_main_evidence_keeps_all_seed_slots_unavailable_with_zero_calls
    test_authenticated_native_with_failed_mapping_remains_in_fidelity_only = prior.UnitRunnerTests.test_authenticated_native_with_failed_mapping_remains_in_fidelity_only
    test_present_failed_original_generations_keep_all_84_null_slots_per_seed = prior.UnitRunnerTests.test_present_failed_original_generations_keep_all_84_null_slots_per_seed
    test_both_original_schema_probes_authenticate_native_bytes_without_cohort_calls = prior.UnitRunnerTests.test_both_original_schema_probes_authenticate_native_bytes_without_cohort_calls

    def test_singleton_probe_and_history_cannot_qualify_partial_binding(self):
        from experiments.translation_flow import v2_unit_runner_singleton as singleton
        self.fixture_run()
        probe = runner._read(self.native_probe("native_fidelity"))
        probe.update(schema="hy30-F5-unit-singleton-native-probe-v1", implementation=singleton.implementation())
        pointer = prior.UnitRunnerTests.write(self, "singleton-probe.json", probe)
        with self.assertRaisesRegex(ValueError, "original-schema"):
            runner.validate_native_probe(pointer, phase="native_fidelity", protocol=self.protocol,
                                         executable=self.executable, shared_root=self.shared)
        expected = {
            "experiments/translation_flow/v2_unit_runner_singleton.py": "80b7fdc49912044e89b762a23dead1e99fecdf6e7ff908bf242136bda86d3705",
            "tests/test_translation_flow_v2_unit_runner_singleton.py": "c6d9d93353d6f049ca6f3033bd559bdfea299639a41fb5393657825a80c1543a",
            "experiments/translation_flow/v2_unit_role_seed_validator_singleton.py": "f2747acfc1cc0d68a17f55f8dd9cc3a1887b6ddadab23e1115e8b5547a92abf2",
            "experiments/translation_flow/v2_unit_role_seed_validator_partial.py": "e3d78fed78b347fa2373fb942b93fb553385e2131aa47ac6636c7abb0ae840a4"}
        workspace = Path(__file__).resolve().parents[1]
        for file, sha in expected.items():
            self.assertEqual(runner.identity(workspace / file)["sha256"], sha)


class GenuinePartialPreparationTests(unittest.TestCase):
    write = fixtures.RegistrationTests.write
    register = fixtures.RegistrationTests.register
    put = original.MainProofTests.put

    def setUp(self):
        original.MainProofTests.setUp(self)
        self.expand_source()

    def replay_for(self, factory):
        return self.write(f"replay-{Path(factory.__file__).stem}.json", {
            "schema": factory.REPLAY_SCHEMA, "state": "root_approved_closed_parser_replay",
            "verifier": factory.identity(Path(factory.__file__)), "parsers": custody._dependencies(),
            "historical_behavior": self.historical["behavior"]})

    def expand_source(self):
        scenes, windows = [], []
        for number in range(48):
            size = 6 if number < 36 else 3
            sid = f"handwritten-scene-{number:02d}"
            ids = [f"handwritten-{number:02d}-cue-{cue}" for cue in range(size)]
            scenes.append({"id": sid, "scene_id": sid, "source_language": "ja", "target_language": "zh-Hans",
                "context": [{"id": uid, "text": "仮の台詞。", "start": i + 1, "end": i + 1.5} for i, uid in enumerate(ids)],
                "translate_ids": ids})
            scored = [ids[0], ids[-1]]
            units = []
            for i, uid in enumerate(ids, 1):
                units.append({"id": uid, "ja_srt_index": i, "index_text": str(i),
                    "time_line": f"00:00:{i:02d},000 --> 00:00:{i:02d},500", "start_ms": i * 1000,
                    "end_ms": i * 1000 + 500, "source_events": {"ja": [{"Dialogue序号": i}], "zh": []},
                    "score": uid in scored})
            windows.append({"id": f"handwritten-window-{number:02d}", "scene_id": sid,
                "source_sha256": "d" * 64, "scored_ids": scored, "units": units,
                "split": "screen-a", "selection_type": "representative" if number < 36 else "risk",
                "work": "handwritten-work", "category": "anime_series", "series_cluster": "handwritten-series"})
        self.windows = windows
        manifest = self.put(self.root / "expanded-manifest.json", {"windows": windows})
        scenes_pointer = self.put(self.root / "expanded-scenes.jsonl", scenes, lines=True)
        self.source = {"manifest": manifest["path"], "manifest_sha256": manifest["sha256"],
                       "scenes": scenes_pointer["path"], "scenes_sha256": scenes_pointer["sha256"]}
        cards = []
        for pointer in self.cards:
            card = custody._read(pointer)
            card["source"] = self.source
            card["prepare"]["selected_scene_ids"] = [scene["id"] for scene in scenes]
            cards.append(self.write(f"expanded-card-{card['prepare']['seed']}.json", card))
        self.cards = cards
        entries = [{"id": f"F5-{seed}", "seed": seed, **pointer} for seed, pointer in zip(diagnostics.SEEDS, cards, strict=True)]
        self.index = self.write("expanded-index.json", {"schema": "hy30-pending-v5-source-only-index-v1", "state": "frozen_not_executed", "cards": entries})
        self.bundle = self.write("expanded-bundle.json", {"schema": "hy30-pending-v5-source-only-freeze-v1", "state": "frozen_not_executed", "cards": entries, "index": self.index})
        gate = custody._read(self.gate)
        gate["source"] = self.source
        gate["controls"]["screen-a"]["cohort"] = {"split": "screen-a", "scenes": 48, "source_cues": 252,
            "score_windows": 48, "score_cues": 96, "batches_per_seed": 84, "seeds": list(diagnostics.SEEDS)}
        self.gate = self.write("expanded-gate.json", gate)
        self.registration = self.register(output=self.root / "expanded-registered")
        self.record = custody._read(self.registration)
        self.external = self.write("expanded-external.json", {"schema": custody.EXTERNAL_REGISTRATION_SCHEMA,
            "state": "frozen_before_generation", "registration": self.registration, "root_gate": self.gate,
            "registered_at_utc": "2020-01-01T00:00:00+00:00"})
        frame = custody._read(self.record["frame"])
        self.assertEqual((len(frame["batches"]), len(frame["expected_slots"])), (84, 252))
        selection = runner.reliability_selection(frame["expected_slots"])
        algorithm = "sha256-canonical-domain-phase-seed-batch; ascending; ceil(84/5)=17 per seed"
        proposal = self.write("reliability-proposal.json", {"registration": self.registration,
            "external_registration": self.external, "frame": self.record["frame"],
            "slot_manifest": frame["expected_slots"], "selection": selection, "algorithm": algorithm})
        reliability = self.write("reliability-registration.json", {"schema": "hy30-F5-source-reliability-root-registration-v1",
            "state": "source_selection_frozen_before_F5_generation_and_quality", "source_registration": self.registration,
            "external_registration": self.external, "source_frame": self.record["frame"], "selection": selection,
            "fixed_slot_count": 252, "source_batches_per_seed": 84, "selected_per_seed_per_phase": 17,
            "paired_control_fidelity_same_slots": True, "candidate_native_root_exists_at_registration": False,
            "native_calls_authorized": False, "registered_at_utc": "2020-01-01T00:00:00+00:00",
            "proposal": proposal, "algorithm": algorithm})
        protocol = runner.freeze_protocol(registration=self.registration, external_registration=self.external,
            expected_registration_sha256=self.registration["sha256"], expected_external_sha256=self.external["sha256"],
            reliability_registration=reliability, expected_reliability_sha256=reliability["sha256"], output=self.root / "protocol-proposal.json")
        value = custody._read(protocol)
        value["state"] = "root_approved_no_implicit_calls"
        self.protocol = self.write("TEST-approved-protocol.json", value)

    def native(self, *, factory, seed, control=False, failure=None, invalid_batch=None, invalid_cue=1, retry=False, scope=None):
        main = factory
        role = "control" if control else "candidate"
        seed_index = diagnostics.SEEDS.index(seed)
        card_ptr = self.cards[seed_index]
        card = custody._read(card_ptr)
        if control:
            card["prepare"].update(recipe="c0", recipe_id="original-C0")
            card["implementation_identity"] = self.codes[:17]
            card_ptr = self.write(f"original-control-card-{seed}.json", card)
        root = self.root / f"native-{role}-{seed}"
        session = root / "execution/runtime-run/translation"
        label = session / card["prepare"]["recipe_id"]
        packed = deepcopy(scope or custody._read(self.record["packed"][seed_index]))
        packed["recipe_id"] = card["prepare"]["recipe_id"]
        packed_ptr = self.put(root / "prepared/packed-mapping.json", packed)
        inputs = [b["producer_input"] for b in diagnostics._source(packed)["batches"]]
        inputs_ptr = self.put(label / "inputs.jsonl", inputs, lines=True)
        item = settings(card["prepare"]["recipe"], label=card["prepare"]["recipe_id"],
            inputs="inputs.jsonl", input_sha256=inputs_ptr["sha256"], packed_mapping_sha256=packed_ptr["sha256"],
            source_manifest_sha256=packed["source_manifest"]["sha256"], terms=[], background=[], style="neutral", review=False, seed=seed)
        self.put(session / "transport/00000/request.json", {"endpoint": "/props"})
        props = {"model_alias": "synthetic-model.gguf", "model_path": "synthetic-model.gguf", "total_slots": 1,
                 "default_generation_settings": {"n_ctx": 8192}}
        self.put(session / "transport/00000/response.raw", props)
        self.put(session / "transport/00000/transport.json", {"status": 200})
        cache = {"method": "fresh-managed-server", "server_pid": 99, "verified": False, "first_response_checked": False}
        rows = []
        client = fixtures.TraceClient(session, [])
        for index, window in enumerate(inputs):
            ids = window["translate_ids"]
            if control:
                outputs = [result({"translations": {key: "控制😀。" for key in ids}})]
                if retry and index == 0:
                    outputs.insert(0, result({"translations": {"wrong": "Invalid"}}))
            else:
                boundaries = {"boundaries": [{"join": True, "evidence_ids": [a, b], "uncertain": True}
                                             for a, b in zip(ids, ids[1:])]}
                cue_texts = ["甲\n\n😀。 " if index == invalid_batch and cue == invalid_cue else "甲😀。 " for cue in range(len(ids))]
                native = "".join(cue_texts)
                mapped = {"segments": [{"unit_id": "u1", "source_id": key, "text": text} for key, text in zip(ids, cue_texts, strict=True)]}
                outputs = ([result(boundaries)] if len(ids) > 1 else []) + [result({"translations": {"u1": native}})]
                if len(ids) > 1:
                    outputs.append(result(mapped))
                if failure == "mapping" and index == 0:
                    outputs[-1:] = [result({"unresolved": "Unknown boundary"})] * 2
                elif failure == "planning" and index == 0:
                    outputs = [result({"unresolved": "Unknown plan"})] * 2
                elif failure == "native" and index == 0:
                    outputs[1:] = [result({"translations": {"wrong": "Invalid"}})] * 2
                if retry and index == 0:
                    outputs.insert(0, result({"unresolved": "Unknown plan"}))
            if failure == "cache":
                outputs[0]["timings"] = {"cache_n": None}
            client.outputs = outputs
            client.tokens = 4100 if failure == "all-preflight" or failure == "preflight" and index == 0 else 7
            row = worker.run_window(client, window, item, 8192,
                                   budget(max_estimated_tokens=500000), cache)
            self.put(label / f"window-{window['id']}.json", row)
            rows.append(row)
            if row.get("error_kind") in {"budget", "oom", "cache"}:
                break
        self.put(label / "ledger.jsonl", rows, lines=True)
        self.put(label / "results.jsonl", [{"id": r["window_id"], "status": r["status"], "translations": r["translations"]} for r in rows], lines=True)
        tail = [{"window_id": w["id"], "status": "not_run", "reason": rows[-1]["stop_reason"]} for w in inputs[len(rows):]]
        self.put(label / "schedule.jsonl", tail, lines=True)
        codes = {}
        workspace = Path(main.__file__).resolve().parents[2]
        # Captured inventory is deliberately larger than the declared closure.
        for ptr in self.codes:
            rel = Path(ptr["path"]).relative_to(workspace).as_posix()
            file = session / "source" / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(Path(ptr["path"]).read_bytes())
            codes[rel] = ptr["sha256"]
        plan = {"schema": "hy30-flow-session-v2", "stage": "screening", "lane": "P-flow", "workloads": [item],
            "experiment_identity": {"source_manifest_sha256": packed["source_manifest"]["sha256"], "split": "screen-a",
                "seed": seed, "recipe_id": item["label"], "source_order_sha256": diagnostics.canonical_sha256([i["id"] for i in inputs])}}
        plan_ptr = self.put(session / "session-plan.json", plan)
        self.put(root / "prepared/session-plan.json", plan)
        asset = {"id": worker.CANDIDATE, "sha256": "a" * 64}
        engine = {**FIXED_ENGINE, "asset": asset, "model_sha256": "a" * 64, "server_pid": 99,
            "model_path": "synthetic-model.gguf",
            "command": ["native-server.exe", "-np", "1"],
            "residency": {"gpu_layers_offloaded": 49, "model_layers_total": 49, "layers_not_offloaded": 0, "partial_layer_offload": False}}
        self.put(session / "session.json", {"schema": "hy30-flow-session-v2", "plan_sha256": plan_ptr["sha256"],
            "identity": {"asset": asset, "engine": engine, "template_sha256": "b" * 64}, "code_sha256": codes,
            "server_props": props, "compatibility_sha256": "c" * 64, "resume": None, "performance_valid_for_fresh_flow": True})
        self.put(root / "execution/runtime-run/runtime/engine.json", engine)
        self.put(root / "execution/runtime-run/runtime/props.json", props)
        self.put(label / "run.json", {"schema": "hy30-flow-session-v2", "phase": "translation", "lane": "P-flow",
            "candidate": worker.CANDIDATE, "recipe": item["recipe"], "settings": item, "code_sha256": codes,
            "compatibility_sha256": "c" * 64, "session_plan_sha256": plan_ptr["sha256"],
            "source_manifest_sha256": packed["source_manifest"]["sha256"], "packed_mapping_sha256": packed_ptr["sha256"],
            "input_sha256": inputs_ptr["sha256"], "expected_window_ids": [w["id"] for w in inputs]})
        attempts = [a for r in rows for a in r["attempts"] if a["completion_dispatched"]]
        failures = sum(r["status"] != "delivered" for r in rows)
        self.put(session / "worker-completion.json", {"schema": worker.SCHEMA, "complete": not failures, "failures": failures,
            "stopped_reason": rows[-1].get("stop_reason"),
            "cache_reset": cache, "reused_windows": 0, "performance_valid_for_fresh_flow": True, "inherited_budget": None,
            "source_token_count_cost": None, "unresolved_prior_dispatch": None,
            "budget": {"translation_calls": len(attempts), "estimated_tokens": sum(a["input_tokens"] + 4096 for a in attempts)}})
        self.put(label / "completion.json", {"windows": len(rows), "expected_windows": len(inputs), "remaining_window_ids": [r["window_id"] for r in tail],
            "failures": failures, "reused_windows": 0, "stopped_reason": rows[-1].get("stop_reason")})
        launched = {"schema": "hy30-flow-command-v2",
            "worker": "experiments.translation_flow.v2_worker", "plan_sha256": plan_ptr["sha256"], "returncode": int(bool(failures)),
            "prepared": str((root / "prepared").resolve()), "code_sha256": main.identity(Path(v2_execute.__file__))["sha256"],
            "command": ["python.exe", "-m", "experiments.translation_demo_runtime", "--session-worker", "experiments.translation_flow.v2_worker",
                "--session-plan", str((root / "prepared/session-plan.json").resolve()), "--output-dir", str((root / "execution/runtime-run").resolve()),
                "--context-size", "8192", "--layers", "99"]}
        command_start = {k: v for k, v in launched.items() if k != "returncode"}
        self.put(root / "execution/command.json", command_start)
        self.put(root / "execution/command-completion.json", {**launched, "command_seconds": 1.5})
        start = {"schema": "hy30-flow-trial-v2", "card_path": card_ptr["path"], "card_sha256": card_ptr["sha256"], "card": card,
            "started_at_utc": "2026-10-08T00:00:00+00:00", "status": "started", "phases": {},
            "code_sha256": main.identity(Path(v2_trial.__file__))["sha256"]}
        self.put(root / "trial-start.json", start)
        terminal = {**start, "status": "partial" if failures or invalid_batch is not None else "complete", "finished_at_utc": "2026-10-08T00:00:02+00:00",
            "total_flow_seconds": 2.0, "phases": {"preparation": .1, "managed_command": 1.5, "export": .3}, "runtime_exit_code": int(bool(failures))}
        terminal_ptr = self.put(root / "trial-completion.json", terminal)
        delivery.deliver(Path(packed["source_manifest"]["path"]), Path(packed_ptr["path"]), label, root / "delivery")
        if control:
            self.historical["workload_archive"] = self.write(f"historical-native-archive-{seed}.json", {"fresh_output_audits": [
                {"seed": seed, "fresh_original_run": main.identity(label / "run.json"), "fresh_ledger": main.identity(label / "ledger.jsonl"),
                 "matched_batches": len(inputs)}]})
        entry = {"seed": seed, "role": role, "card": card_ptr, "trial_root": str(root.resolve()), "trial_completion": terminal_ptr,
            "runtime": self.runtime, "declared_snapshot_count": 17 if control else 21,
            "historical_authorities": deepcopy(self.historical) if control else None, "scoring_derivation": None}
        authority = self.write(f"authority-{role}-{seed}.json", {"schema": main.AUTHORITY_SCHEMA,
            "state": "root_approved_offline_original_authentication", "registration": self.registration,
            "external_registration": self.external, "verifier": main.identity(Path(main.__file__)),
            "diagnostic_replay": self.replay_for(factory), "entries": [entry]})
        return {"root": root, "label": label, "rows": rows, "entry": entry, "authority": authority, "role": role}

    def authenticate_and_prove(self, fixture, factory, seed, authority=None):
        authority = authority or fixture["authority"]
        admission = factory.authenticate_original_trial(authority=authority,
            expected_authority_sha256=authority["sha256"], role=fixture["role"], seed=seed,
            output=self.root / f"admission-{fixture['role']}-{seed}.json")
        proof = factory.build_main_proof(admission=admission, expected_admission_sha256=admission["sha256"],
            authority=authority, expected_authority_sha256=authority["sha256"],
            output=self.root / f"proof-{fixture['role']}-{seed}.json")
        return admission, proof

    def prepare_cohort(self, *, mapping_failure):
        router = runner.main_router
        controls = [self.native(factory=router.control_factory, seed=seed, control=True) for seed in diagnostics.SEEDS]
        authority_value = custody._read(controls[0]["authority"])
        authority_value["entries"] = [fixture["entry"] for fixture in controls]
        control_authority = self.write("aggregate-TEST-control-authority.json", authority_value)
        control_proofs = {}
        for seed, fixture in zip(diagnostics.SEEDS, controls, strict=True):
            control_proofs[seed] = self.authenticate_and_prove(fixture, router.control_factory, seed, control_authority)
        control_seal = self.write("aggregate-TEST-control-seal.json", {"schema": router.control_factory.SEAL_SCHEMA,
            "state": "root_reviewed_original_main_proofs", "verifier": router.identity(Path(router.control_factory.__file__)),
            "authority": control_authority, "proofs": [{"seed": seed, "role": "control", "admission": admission, "proof": proof}
                for seed, (admission, proof) in control_proofs.items()]})
        candidate = self.native(factory=router.partial_factory, seed=20261009,
            failure="mapping" if mapping_failure else None, invalid_batch=1 if mapping_failure else 0)
        admission, proof = self.authenticate_and_prove(candidate, router.partial_factory, 20261009)
        candidate_seal = self.write("single-TEST-partial-candidate-seal.json", {"schema": router.partial_factory.SEAL_SCHEMA,
            "state": "root_reviewed_original_main_proofs", "verifier": router.identity(Path(router.partial_factory.__file__)),
            "authority": candidate["authority"], "proofs": [{"seed": 20261009, "role": "candidate", "admission": admission, "proof": proof}]})
        propagation = self.put(self.root / "summaries/F5-singleton-helper-version-v1/propagation-boundary.json",
            {"handwritten_TEST_propagation": True})
        acceptance = self.put(self.root / "summaries/F5-partial-mainproof-root-offline-acceptance-v1.json",
            {"handwritten_TEST_partial_acceptance": True})
        # TEST root metadata authority only; literal executed factory hashes,
        # real router, real authentication/parser and custody remain unchanged.
        boundary = patch.multiple(router, BASE=self.root, CONTROL_SEAL_SHA=control_seal["sha256"],
            F5_EXTERNAL_SHA=self.external["sha256"], PROPAGATION_SHA=propagation["sha256"],
            PARTIAL_ACCEPTANCE_SHA=acceptance["sha256"])
        boundary.start()
        self.addCleanup(boundary.stop)
        slots = []
        for seed in diagnostics.SEEDS:
            present = seed == 20261009
            slots.append({"seed": seed, "role": "candidate", "receipt": proof if present else None,
                "seal": candidate_seal if present else None, "authority": candidate["authority"] if present else None,
                "unavailable_reason": None if present else "TEST-only candidate proof administratively unavailable"})
            slots.append({"seed": seed, "role": "control", "receipt": control_proofs[seed][1],
                "seal": control_seal, "authority": control_authority, "unavailable_reason": None})
        registry = self.write("TEST-partial-registry.json", {"schema": router.REGISTRY_SCHEMA,
            "state": "root_reviewed_fixed_role_seed_slots", "dispatcher": router.identity(Path(router.__file__)),
            "propagation": propagation, "candidate_verifiers": router.candidate_verifiers(),
            "partial_acceptance": router.partial_acceptance(), "control_verifier": router.identity(Path(router.control_factory.__file__)),
            "control_seal": control_seal, "external_registration": self.external, "slots": slots})
        callback = router.make_role_seed_main_validator(registry=registry, expected_registry_sha256=registry["sha256"])
        for row in slots:
            if row["receipt"] is not None:
                decoded = callback(row["receipt"], seed=row["seed"], role=row["role"], external_registration=self.external)
                self.assertEqual(decoded, custody._read(row["receipt"]))
        present = [{key: row[key] for key in ("seed", "role", "receipt")} for row in slots if row["receipt"] is not None]
        validator_pointer = router.identity(Path(router.__file__))
        prepared = custody.prepare_unit_auxiliary(registration=self.registration, external_registration=self.external,
            expected_registration_sha256=self.registration["sha256"], expected_external_sha256=self.external["sha256"],
            main_receipts=present, expected_main_receipts=present, main_validator=callback,
            validator_identity=validator_pointer, expected_validator_sha256=validator_pointer["sha256"],
            output=self.root / "prepared-auxiliary")
        expected_slots = [{key: row[key] for key in ("seed", "role", "receipt", "unavailable_reason")} for row in slots]
        run_plan = runner.prepare_run(custody_pointer=prepared, expected_custody_sha256=prepared["sha256"],
            registration=self.registration, external_registration=self.external, expected_main_slots=expected_slots,
            main_registry=registry, expected_main_registry_sha256=registry["sha256"], protocol=self.protocol,
            expected_protocol_sha256=self.protocol["sha256"], output=self.root / "evaluation-only/partial-run")
        phase = runner.prepare_phase(run_plan=run_plan, expected_run_plan_sha256=run_plan["sha256"], phase="native_fidelity")
        return candidate, custody._read(admission), custody._read(prepared), custody._read(phase)

    def assert_partial_scope_and_fixed_unknown(self, admission, material, phase):
        self.assertFalse(admission["native_complete"])
        self.assertEqual(admission["generation_attempt_status"], "terminal_partial")
        self.assertEqual(admission["actual_source_scope"]["source_cues"], 252)
        self.assertEqual(len(admission["actual_source_scope"]["scene_ids"]), 48)
        self.assertEqual((admission["scheduled_batches"], admission["attempted_batches"]), (84, 84))
        self.assertEqual(admission["original_cost_count"], 1)
        self.assertEqual(admission["new_generation_calls"], 0)
        self.assertFalse(admission["semantic_accuracy_verified"])
        self.assertEqual(len(material["slots"]), 252)
        self.assertEqual(len(material["original_generation_cost_authorities"]), 4)
        self.assertEqual(len({pointer["path"] for pointer in material["original_generation_cost_authorities"]}), 4)
        metadata = next(row for row in material["original_generation_metadata"] if row["role"] == "candidate")
        self.assertFalse(metadata["native_complete"])
        self.assertEqual(metadata["generation_attempt_status"], "terminal_partial")
        self.assertEqual(len(phase["slots"]), 504)
        self.assertEqual(len(phase["jobs"]), 336)
        self.assertEqual(phase["logical_slots"], 252)
        self.assertEqual(len(phase["reliability"]), 51)
        for seed in (20261008, 20261010):
            unknown = [row for row in phase["slots"] if row["arm"] == "candidate" and row["slot"]["seed"] == seed]
            self.assertEqual(len(unknown), 84)
            self.assertTrue(all(row["status"] == "unavailable" for row in unknown))
            self.assertTrue(all(row["views"]["native_packet"] is None and row["views"]["attribution_packet"] is None
                for row in material["slots"] if row["slot"]["seed"] == seed))
        self.assertTrue(all(row["views"]["c0_packet"] is not None for row in material["slots"]))

    def test_authentic_invalid_only_worker_success_delivery_fail_public_phase_preparation(self):
        candidate, admission, material, phase = self.prepare_cohort(mapping_failure=False)
        self.assert_partial_scope_and_fixed_unknown(admission, material, phase)
        completion = custody._read(runner.identity(candidate["label"].parent / "worker-completion.json"))
        command = custody._read(runner.identity(candidate["root"] / "execution/command-completion.json"))
        self.assertTrue(completion["complete"])
        self.assertEqual(command["returncode"], 0)
        self.assertEqual(admission["failed_batches"], [])
        sidecar = custody._read(runner.identity(candidate["root"] / "delivery/scenes/handwritten-scene-00/sidecar.json"))
        self.assertEqual(sidecar["coverage"]["status_counts"], {"delivered": 5, "invalid": 1})
        selected = [row for row in material["slots"] if row["slot"]["seed"] == 20261009]
        self.assertEqual(sum(row["views"]["native_packet"] is not None for row in selected), 84)
        self.assertEqual(sum(row["views"]["attribution_packet"] is not None for row in selected), 84)
        self.assertIn("\n\n", selected[0]["views"]["native_packet"]["output_groups"][0]["text"])
        # Exact mapper partition preserves invalid display bytes, not a semantic
        # or SRT-delivery pass. No judge is launched by phase preparation.
        self.assertFalse((candidate["root"] / "delivery/scenes/handwritten-scene-00/chn.srt").exists())

    def test_authentic_combined_mapping_null_and_invalid_keep_native_raw_fixed_slots(self):
        candidate, admission, material, phase = self.prepare_cohort(mapping_failure=True)
        self.assert_partial_scope_and_fixed_unknown(admission, material, phase)
        self.assertEqual(len(admission["failed_batches"]), 1)
        self.assertEqual(admission["failed_batches"][0]["status"], "mapping_unjudgeable")
        sidecar = custody._read(runner.identity(candidate["root"] / "delivery/scenes/handwritten-scene-00/sidecar.json"))
        self.assertEqual(sidecar["coverage"]["status_counts"], {"mapping_unjudgeable": 3, "invalid": 1, "delivered": 2})
        selected = [row for row in material["slots"] if row["slot"]["seed"] == 20261009]
        self.assertIsNotNone(selected[0]["views"]["native_packet"])
        self.assertIsNone(selected[0]["views"]["attribution_packet"])
        self.assertEqual(selected[0]["original_stage_proof"]["mapping"], "unavailable")
        self.assertIsNotNone(selected[1]["views"]["attribution_packet"])
        self.assertIn("\n\n", selected[1]["views"]["native_packet"]["output_groups"][0]["text"])
        self.assertEqual(sum(row["views"]["native_packet"] is not None for row in selected), 84)
        self.assertEqual(sum(row["views"]["attribution_packet"] is not None for row in selected), 83)
        raw = {pointer["path"] for pointer in material["raw_artifacts"]}
        attempts = [attempt for row in candidate["rows"] for attempt in row["attempts"] if attempt["completion_dispatched"]]
        self.assertTrue({str((Path(attempt["original_response"]) / "response.raw").resolve()) for attempt in attempts} <= raw)
        costs = custody._read(runner.identity(candidate["root"] / "delivery/costs.json"))
        self.assertEqual(costs["dispatched_completions"], 253)
        self.assertEqual(costs["input_tokens"]["measured_sum"], sum(attempt["input_tokens"] for attempt in attempts))


if __name__ == "__main__":
    unittest.main()

