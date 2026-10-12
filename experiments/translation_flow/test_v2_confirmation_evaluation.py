"""Synthetic native confirmation generations and judgments; no model/network."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from experiments.translation_eval import runner as e
from experiments.translation_eval.test_runner import judgment
from experiments.translation_judge import runner as j
from . import v2_statistics as statistics
from . import test_v2_evaluation as source_fixtures
from . import test_v2_confirmation as lock_fixtures
from . import v2_confirmation as c, v2_confirmation_dispatch as d
from . import v2_confirmation_evaluation as bridge, v2_prepare, v2_delivery, v2_recipes
from tests import test_translation_flow_v2_source_preparation as preparation_fixtures


class NativeSourcePreparationMetadataTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = preparation_fixtures.SourcePreparationVersion3Tests()
        plan, self.args = self.fixture.fixture(self.root, mode="background")
        code, _ = self.fixture.run_fake(self.args, [preparation_fixtures.result(preparation_fixtures.background_response())])
        self.assertEqual(code, 0)
        self.plan = c.pointer(self.args.session_plan)
        self.options = c.pointer(self.args.output_dir / "preparation-options.json")
        spec = plan["source"]
        self.card_source = {key: value for key, value in spec.items() if key != "freeze_sha256"}
        self.source = {"role": "screening", "split": "screen-a",
            "manifest": {"path": spec["manifest"], "sha256": spec["manifest_sha256"]},
            "scenes": {"path": spec["scenes"], "sha256": spec["scenes_sha256"]},
            "freeze": c.pointer(Path(spec["manifest"]).parent / "freeze-manifest.json")}

    def intake(self, options=None, **overrides):
        return bridge.validate_source_preparation_metadata(self.plan, self.options if options is None else options,
            self.source, **{"seed": 20261008, "stage": "qualification", **overrides})

    def test_native_v3_proof_accepts_extra_freeze_while_card_source_has_only_required_four_fields(self):
        from . import v2_timing
        requested = []
        original = v2_timing.read_metadata_fields
        def observe(path, fields):
            requested.append(set(fields))
            return original(path, fields)
        with patch.object(v2_timing, "read_metadata_fields", side_effect=observe):
            proof = self.intake()
        self.assertNotIn("freeze_sha256", self.card_source)
        self.assertEqual(proof["source"]["freeze"], self.source["freeze"])
        self.assertEqual(proof["stage"], "qualification")
        self.assertFalse(proof["formal_timing_eligible"])
        self.assertFalse(proof["preparation_semantics_validated"])
        self.assertTrue(all(not fields & {"preparations", "raw_responses", "terms", "background"} for fields in requested))

    def test_native_artifact_wrong_freeze_manifest_scene_and_seed_are_rejected(self):
        original = e.read_json(Path(self.options["path"]))
        for field in ("freeze_sha256", "manifest_sha256", "scenes_sha256"):
            changed = deepcopy(original)
            changed["source"][field] = "f" * 64
            path = self.root / "altered-options.json"
            e.dump(path, changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.intake(c.pointer(path))
        with self.assertRaisesRegex(ValueError, "plan/stage/seed"):
            self.intake(seed=20261009)

    def test_qualification_proof_cannot_be_relabelled_confirmation_or_screening(self):
        with self.assertRaises(ValueError):
            self.intake(stage="confirmation")
        with self.assertRaises(ValueError):
            self.intake(stage="screening")

    def test_metadata_guard_rejects_undeclared_auxiliary_in_native_main_run(self):
        with self.assertRaisesRegex(ValueError, "absent from its locked card"):
            bridge._native_source_preparation({}, self.source, self.root, {"source_preparation": {"artifact": self.options}}, {}, {})


class ConfirmationEvaluationTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-evaluation-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        temporary = patch.object(tempfile, "tempdir", self.temp.name)
        temporary.start()
        self.addCleanup(temporary.stop)
        self.source = source_fixtures.SceneEvaluationTests()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.lock_fixture = lock_fixtures.ConfirmationContractTests()
        self.lock_fixture.setUp()
        self.addCleanup(self.lock_fixture.doCleanups)
        self.root = self.source.root
        original_windows, original_inputs, original_refs = self.source.windows, self.source.inputs, self.source.refs
        self.source.windows, self.source.inputs, self.source.refs = [], [], []
        for index in range(48):
            window, request, ref = (deepcopy(rows[index % 3]) for rows in (original_windows, original_inputs, original_refs))
            wid = f"confirmation-Q{index + 1:02d}"
            window.update(id=wid, window_id=wid, split="confirmation", selection_type="representative")
            request["id"] = ref["id"] = wid
            self.source.windows.append(window)
            self.source.inputs.append(request)
            self.source.refs.append(ref)
        e.dump(self.source.manifest_path, {"version": "synthetic-confirmation-source", "external_corpus": str(self.source.source),
            "windows": self.source.windows})
        e.dump_jsonl(self.source.input_path, self.source.inputs)
        e.dump_jsonl(self.source.reference_path, self.source.refs)
        self.source.freeze()
        original = self.source.source / "original-source-freeze.json"
        e.dump(original, {"version": "hy30-flow-v2-source-v1", "role": "confirmation", "state": "source_frozen_reference_unreviewed"})
        self.freeze = self.source.source / "freeze-manifest.json"
        e.dump(self.freeze, {"version": "hy30-flow-v2-source-v1", "role": "confirmation", "windows": 48,
            "state": "source_frozen_reference_qualified", "original_source_freeze": c.pointer(original),
            "reference_qualification": {**c.pointer(self.source.freeze_path), "version": "hy30-flow-v2-reference-v1",
                "state": "frozen_double_fresh_reference_review", "inference_allowed": True},
            "artifacts": [{"path": path.name, "sha256": e.sha(path)} for path in (self.source.manifest_path, self.source.scene_path)]})
        fixture = self.lock_fixture
        policy = e.read_json(fixture.policy_path)
        policy["primary_endpoint"]["estimator"] = statistics.ESTIMATOR
        policy["multiplicity"] = {"bootstrap_iterations": 30, "bootstrap_seed": 20261008,
                                  "family_confidence": .95, "family_size": 9}
        fixture.write(fixture.policy_path.name, policy)
        fixture.policy_sha = e.sha(fixture.policy_path)
        fixture.manifest, fixture.scenes, fixture.freeze = self.source.manifest_path, self.source.scene_path, self.freeze
        fixture.source = {"role": "confirmation", "split": "confirmation", "expected_windows": 48,
            "selection_type": "representative", "manifest": c.pointer(fixture.manifest), "scenes": c.pointer(fixture.scenes), "freeze": c.pointer(self.freeze)}
        evaluation = fixture.read(c.pointer(fixture.evaluation))
        prompt = Path(evaluation["prompt"]["path"])
        prompt.write_text(e.PROMPT + "\n", encoding="utf-8")
        evaluation.update(prompt=c.pointer(prompt), source_scope_sha256=c.source_scope_sha256(fixture.source))
        fixture.write(fixture.evaluation.name, evaluation)
        fixture.baseline_cards = fixture.cards("C0-official-cached", "c0", 5)
        fixture.candidates = [fixture.candidate("candidate-b10", "c0", 10)]
        self.lock = fixture.lock()
        self.unseal = fixture.open(self.lock)
        self.pins = {"registered_lock_sha256": self.lock["sha256"], "registered_unseal_sha256": self.unseal["sha256"],
                     "expected_policy_sha256": fixture.policy_sha}
        self.fail_at = None
        self.calls = []

    def native_trial(self, card_path, output):
        ordinal = int(output.name.rsplit("-", 1)[1])
        if ordinal == self.fail_at:
            output.mkdir()
            return 1
        started = datetime.now(timezone.utc).isoformat()
        output.mkdir()
        card = e.read_json(card_path)
        settings = card["prepare"]
        prepare_settings = deepcopy(settings)
        output_budget = prepare_settings.pop("n_predict", 4096)
        v2_prepare.prepare(manifest=self.source.manifest_path, scenes=self.source.scene_path,
                           output=output / "prepared", **prepare_settings)
        plan_path = output / "prepared/session-plan.json"
        plan = e.read_json(plan_path)
        item = plan["workloads"][0]
        # Prospective output-budget metadata seam; no staged runtime promotion.
        if output_budget != 4096:
            item["n_predict"] = output_budget
            e.dump(plan_path, plan)
        packed_path = output / "prepared/packed-mapping.json"
        packed = e.read_json(packed_path)
        session_root = output / "execution/runtime-run/translation"
        run_dir = session_root / settings["recipe_id"]
        run_dir.mkdir(parents=True)
        (session_root / "session-plan.json").write_bytes(plan_path.read_bytes())
        (run_dir / "inputs.jsonl").write_bytes((output / "prepared/inputs.jsonl").read_bytes())
        code = self.lock_fixture.code
        relative = code.relative_to(Path(__file__).resolve().parents[2]).as_posix()
        snapshot = session_root / "source" / relative
        snapshot.parent.mkdir(parents=True)
        snapshot.write_bytes(code.read_bytes())
        code_hashes = {relative: e.sha(code)}
        asset = {"id": "hy-mt2-30b-a3b-apex-i-compact", "sha256": c.OFFICIAL_C0_RUNTIME["asset_sha256"]}
        engine = {"asset": asset, "model_sha256": asset["sha256"], "server_pid": 9000 + ordinal,
                  "context_size": 8192, "gpu_layers_requested": 99, "command": ["synthetic-server", "-np", "1"]}
        e.dump(session_root / "session.json", {"schema": "hy30-flow-session-v2", "plan_sha256": e.sha(plan_path),
            "created_at_utc": started,
            "identity": {"asset": asset, "engine": engine, "template_sha256": "d" * 64}, "compatibility_sha256": "c" * 64,
            "code_sha256": code_hashes, "resume": None, "performance_valid_for_fresh_flow": True})
        e.dump(run_dir / "run.json", {"schema": "hy30-flow-session-v2", "lane": "P-flow", "candidate": asset["id"],
            "settings": item, "session_plan_sha256": e.sha(plan_path), "source_manifest_sha256": e.sha(self.source.manifest_path),
            "recipe": item["recipe"],
            "packed_mapping_sha256": e.sha(packed_path), "input_sha256": e.sha(run_dir / "inputs.jsonl"),
            "expected_window_ids": [row["id"] for row in packed["batches"]], "compatibility_sha256": "c" * 64,
            "code_sha256": code_hashes})
        exchange = session_root / "transport/first-completion"
        exchange.mkdir(parents=True)
        request = v2_recipes.completion_request(item, [1])
        response = {"content": "Synthetic native response", "timings": {"cache_n": 0}}
        e.dump(exchange / "request.json", {"endpoint": "/completion", "body": request})
        e.dump(exchange / "response.raw", response)
        e.dump(exchange / "transport.json", {"synthetic": True})
        e.dump(session_root / "checkpoint.json", {"cache_reset": {"method": "fresh-managed-server", "verified": True,
            "first_response_checked": True, "first_response_cache_n": 0, "server_pid": engine["server_pid"], "exchange": str(exchange)}})
        results, ledger = [], []
        for index, batch in enumerate(packed["batches"]):
            values = {uid: "合成译文" for uid in batch["target_ids"]}
            results.append({"id": batch["id"], "translations": values})
            attempts = [{"completion_dispatched": True, "request": request, "response": response,
                         "original_response": str(exchange)}] if index == 0 else []
            ledger.append({"window_id": batch["id"], "status": "delivered", "translations": values, "attempts": attempts})
        e.dump_jsonl(run_dir / "results.jsonl", results)
        e.dump_jsonl(run_dir / "ledger.jsonl", ledger)
        e.dump_jsonl(run_dir / "schedule.jsonl", [])
        e.dump(output / "execution/command-completion.json", {"schema": "hy30-flow-command-v2", "returncode": 0,
            "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "worker": "experiments.translation_flow.v2_worker", "plan_sha256": e.sha(plan_path), "command_seconds": .1})
        v2_delivery.deliver(self.source.manifest_path, packed_path, run_dir, output / "delivery")
        report = {"schema": "hy30-flow-trial-v2", "card_path": str(card_path), "card_sha256": e.sha(card_path), "card": card,
            "started_at_utc": started, "finished_at_utc": datetime.now(timezone.utc).isoformat(), "total_flow_seconds": .2,
            "status": "complete", "runtime_exit_code": 0, "expected_scene_ids": packed["scene_ids"],
            "expected_scenes": len(packed["scene_ids"]), "complete_scenes": len(packed["scene_ids"]),
            "missing_scene_ids": [], "unexpected_scene_ids": [], "duplicate_scene_ids": []}
        e.dump(output / "trial-start.json", report)
        e.dump(output / "trial-completion.json", report)
        return 0

    def create_queue(self, fail_at=None):
        self.fail_at = fail_at
        self.plan = d.freeze_dispatch_plan(self.lock, self.unseal, self.root / "generation", self.root / "dispatch-plan.json", **self.pins)
        self.receipt = d.execute_dispatch_plan(self.plan, trial_runner=self.native_trial, **self.pins)
        return self.plan, self.receipt

    def prepare_seed(self, seed=c.SEEDS[0]):
        receipt = c._json(Path(self.receipt["path"]))
        paths = {job["candidate_alias"]: Path(job["output"]) / "delivery" for job in receipt["jobs"]
                 if job["seed"] == seed and job["status"] == "complete"}
        root = self.root / f"evaluation-{seed}"
        bridge.prepare(self.source.manifest_path, self.source.input_path, self.source.reference_path, paths, root,
            reference_freeze=self.source.freeze_path, seed=seed, dispatch_authority=self.plan, generation_receipt=self.receipt, **self.pins)
        return root

    def fake_judge(self, args, prompt, cwd, attempt, timeout):
        self.calls.append(attempt)
        packet = json.loads(prompt.split("\nPACKET:\n", 1)[1].split("\nADJUDICATION:\n", 1)[0])
        value = judgment(packet, 4)
        if attempt.parents[2].name == "adjudication":
            value.update(resolved=True, resolution_zh="合成裁决。")
        e.dump(attempt / "last-message.txt", value)
        return {"transport_status": "completed", "returncode": 0, "returned_models": [j.MODEL],
                "returned_efforts": [j.EFFORT], "tool_events": [], "elapsed_seconds": .01}

    def execute_jobs(self, root, filename):
        for job in e.load_jsonl(root / filename):
            self.assertEqual(j.run_job(root, job, "synthetic", "synthetic", 1, self.fake_judge)["status"], "succeeded")

    def finish(self, root):
        self.execute_jobs(root, "jobs.jsonl")
        bridge.finalize(root, **self.pins)
        self.execute_jobs(root, "jobs-review.jsonl")
        bridge.finalize(root, **self.pins)
        self.execute_jobs(root, "jobs-adjudication.jsonl")
        bridge.finalize(root, **self.pins)
        return bridge.seal_metadata(root, **self.pins)

    def test_actual_prepare_finalize_and_seal_mirror_fresh_scope_all_review(self):
        self.create_queue()
        root = self.prepare_seed()
        run = e.read_json(root / "run.json")
        self.assertNotIn("universal_review_scope", run)
        self.assertEqual(len(e.load_jsonl(root / "expected.jsonl")), 96)
        self.assertEqual(run["fresh_confirmation_scope"], c.pointer(self.lock_fixture.evaluation))
        mirrors = self.finish(root)
        self.assertEqual(mirrors["confirmation_review_coverage"], {"expected_records": 96, "judgeable_records": 96,
            "selected_records": 96, "accepted_review_records": 96, "known_scored_reviewed_records": 96, "complete": True})
        bridge.validate_metadata(root, self.plan, **self.pins)

    def test_terminal_failure_and_not_run_tail_keep_every_group_window_unknown(self):
        self.create_queue(fail_at=4)
        for seed in c.SEEDS:
            root = self.prepare_seed(seed)
            final = self.finish(root)
            rows = e.load_jsonl(root / "final.jsonl")
            failed = [row for row in rows if row["candidate_alias"] == "candidate-b10"]
            self.assertEqual(len(failed), 48)
            self.assertEqual({row["status"] for row in failed}, {"setup_failed" if seed == c.SEEDS[0] else "not_run"})
            self.assertTrue(all(row["semantic"] is None and row["naturalness"] is None for row in failed))
            self.assertEqual(final["confirmation_review_coverage"]["expected_records"], 96)
            self.assertEqual(final["confirmation_review_coverage"]["accepted_review_records"], 48)
            run = e.read_json(root / "run.json")
            self.assertIsNone(run["candidates"]["candidate-b10"]["original_generation_cost_identity"])

    def test_external_pins_wrong_seed_and_imports_rejected(self):
        self.create_queue()
        with self.assertRaises(ValueError):
            bridge.authority_metadata(self.plan, self.receipt, **{**self.pins, "registered_lock_sha256": "f" * 64})
        root = self.prepare_seed()
        run = e.read_json(root / "run.json")
        for field in ("judgment_import", "matched_control_scope", "universal_review_scope"):
            e.dump(root / "run.json", {**run, field: None})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "forbids screening"):
                bridge.validate_metadata(root, self.plan, **self.pins)
        e.dump(root / "run.json", {**run, "confirmation_generation_seed": 123})
        with self.assertRaises(ValueError):
            bridge.validate_metadata(root, self.plan, **self.pins)

    def test_measured_raw_cache_resume_and_missing_native_proof_rejected(self):
        self.create_queue()
        authority = bridge.authority_metadata(self.plan, self.receipt, **self.pins)
        job = authority["receipt"]["jobs"][0]
        checkpoint = Path(job["output"]) / "execution/runtime-run/translation/checkpoint.json"
        original = e.read_json(checkpoint)
        changed = deepcopy(original)
        changed["cache_reset"]["first_response_cache_n"] = 1
        e.dump(checkpoint, changed)
        with self.assertRaisesRegex(ValueError, "empty-cache"):
            bridge.collect_generation_evidence(authority)
        e.dump(checkpoint, original)
        session_path = checkpoint.parent / "session.json"
        session = e.read_json(session_path)
        e.dump(session_path, {**session, "resume": {"old": "screening"}})
        with self.assertRaisesRegex(ValueError, "fresh native"):
            bridge.collect_generation_evidence(authority)
        e.dump(session_path, session)
        (checkpoint.parent / "session.json").unlink()
        with self.assertRaises(FileNotFoundError):
            bridge.collect_generation_evidence(authority)

    def test_guard_rejects_mismatched_scope_stage_and_baseline_before_packet_prepare(self):
        self.create_queue()
        for changed in ("role", "state"):
            freeze = e.read_json(self.freeze)
            freeze[changed] = "screening"
            e.dump(self.freeze, freeze)
            with patch.object(bridge.v, "prepare") as core, self.assertRaises(ValueError):
                bridge.authority_metadata(self.plan, self.receipt, **self.pins)
            core.assert_not_called()
            break

    def test_root_reuse_rejected_and_native_snapshot_tamper_detected(self):
        self.create_queue()
        root = self.prepare_seed()
        with self.assertRaises(FileExistsError):
            self.prepare_seed()
        run = e.read_json(root / "run.json")
        evidence = e.read_json(Path(run["confirmation_generation_evidence"]["path"]))
        path = Path(evidence["generations"][0]["implementation_snapshots"][0]["path"])
        path.write_text("tampered executed code", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "implementation snapshot changed"):
            bridge.validate_metadata(root, self.plan, **self.pins)

    def test_native_template_and_self_consistent_runtime_settings_drift_rejected(self):
        self.create_queue()
        authority = bridge.authority_metadata(self.plan, self.receipt, **self.pins)
        second = Path(authority["receipt"]["jobs"][1]["output"]) / "execution/runtime-run/translation/session.json"
        session = e.read_json(second)
        changed = deepcopy(session)
        changed["identity"]["template_sha256"] = "e" * 64
        e.dump(second, changed)
        with self.assertRaisesRegex(ValueError, "engine/model/template"):
            bridge.collect_generation_evidence(authority)
        e.dump(second, session)
        job = authority["receipt"]["jobs"][0]
        output = Path(job["output"])
        recipe_id = e.read_json(Path(job["card"]["path"]))["prepare"]["recipe_id"]
        session_root = output / "execution/runtime-run/translation"
        plan = e.read_json(session_root / "session-plan.json")
        plan["workloads"][0]["sampling"] = "official-temperature0"
        for path in (session_root / "session-plan.json", output / "prepared/session-plan.json"):
            e.dump(path, plan)
        digest = e.sha(session_root / "session-plan.json")
        run_path = session_root / recipe_id / "run.json"
        run = e.read_json(run_path)
        run.update(settings=plan["workloads"][0], session_plan_sha256=digest)
        e.dump(run_path, run)
        session_path = session_root / "session.json"
        e.dump(session_path, {**e.read_json(session_path), "plan_sha256": digest})
        command = output / "execution/command-completion.json"
        e.dump(command, {**e.read_json(command), "plan_sha256": digest})
        with self.assertRaisesRegex(ValueError, "recipe/options/packing"):
            bridge.collect_generation_evidence(authority)

    def test_raw_empty_cache_and_omitted_c0_cannot_be_replaced_by_metadata_claims(self):
        self.create_queue()
        receipt = c._json(Path(self.receipt["path"]))
        job = receipt["jobs"][0]
        session_root = Path(job["output"]) / "execution/runtime-run/translation"
        checkpoint = e.read_json(session_root / "checkpoint.json")
        exchange = Path(checkpoint["cache_reset"]["exchange"])
        response = e.read_json(exchange / "response.raw")
        response["timings"]["cache_n"] = 1
        e.dump(exchange / "response.raw", response)
        run_dir = session_root / e.read_json(Path(job["card"]["path"]))["prepare"]["recipe_id"]
        ledger = e.load_jsonl(run_dir / "ledger.jsonl")
        ledger[0]["attempts"][0]["response"] = response
        e.dump_jsonl(run_dir / "ledger.jsonl", ledger)
        authority = bridge.authority_metadata(self.plan, self.receipt, **self.pins)
        with self.assertRaisesRegex(ValueError, "actually reused cache"):
            bridge.collect_generation_evidence(authority)
        with self.assertRaisesRegex(ValueError, "Every completed locked slot"):
            bridge.prepare(self.source.manifest_path, self.source.input_path, self.source.reference_path,
                {}, self.root / "omitted", reference_freeze=self.source.freeze_path, seed=c.SEEDS[0],
                dispatch_authority=self.plan, generation_receipt=self.receipt, **self.pins)

    def test_wrong_seed_new_per_job_lock_and_old_baseline_rejected_before_preparation(self):
        self.create_queue()
        with self.assertRaisesRegex(ValueError, "seed differs"):
            bridge.prepare(self.source.manifest_path, self.source.input_path, self.source.reference_path,
                {}, self.root / "wrong-seed", reference_freeze=self.source.freeze_path, seed=1,
                dispatch_authority=self.plan, generation_receipt=self.receipt, **self.pins)
        receipt = c._json(Path(self.receipt["path"]))
        receipt["confirmation_dispatch_authority"]["lock"] = {"path": str(self.root / "new-lock"), "sha256": "a" * 64}
        altered = self.root / "receipt-relocked.json"
        e.dump(altered, receipt)
        with self.assertRaises(ValueError):
            bridge.authority_metadata(self.plan, c.pointer(altered), **self.pins)
        card_path = self.lock_fixture.baseline_cards[0]
        card = e.read_json(card_path)
        card["prepare"]["target_size"] = 10
        e.dump(card_path, card)
        with self.assertRaises(ValueError), patch.object(bridge.v, "prepare") as core:
            bridge.authority_metadata(self.plan, self.receipt, **self.pins)
        core.assert_not_called()

    def test_seal_rejects_historical_accepted_judgment_timestamp(self):
        self.create_queue()
        root = self.prepare_seed()
        self.finish(root)
        job = e.load_jsonl(root / "jobs-review.jsonl")[0]
        ledger = root / "judge-execution" / job["job_id"] / "job.json"
        state = e.read_json(ledger)
        state["attempts"][0]["started_at"] = "2020-01-01T00:00:00+00:00"
        e.dump(ledger, state)
        with self.assertRaisesRegex(ValueError, "predates its terminal generation authority"):
            bridge.seal_metadata(root, **self.pins)

    def test_failed_first_c0_preserves_whole_denominator_without_fake_generation_or_judges(self):
        self.create_queue(fail_at=1)
        root = self.prepare_seed()
        mirrors = self.finish(root)
        self.assertEqual(len(self.calls), 0)
        self.assertEqual(mirrors["confirmation_review_coverage"]["expected_records"], 96)
        self.assertEqual(mirrors["confirmation_review_coverage"]["judgeable_records"], 0)
        self.assertTrue(mirrors["confirmation_review_coverage"]["complete"])
        self.assertTrue(all(row["semantic"] is None and row["naturalness"] is None for row in e.load_jsonl(root / "final.jsonl")))
        evidence = e.read_json(Path(mirrors["confirmation_generation_evidence"]["path"]))
        self.assertFalse(evidence["all_fresh_native_generations"])
        self.assertTrue(all(row["original_run"] is None for row in evidence["generations"]))

    def test_actual_completion_sampling_drift_rejected_despite_correct_declared_settings(self):
        self.create_queue()
        authority = bridge.authority_metadata(self.plan, self.receipt, **self.pins)
        job = authority["receipt"]["jobs"][0]
        session_root = Path(job["output"]) / "execution/runtime-run/translation"
        recipe_id = e.read_json(Path(job["card"]["path"]))["prepare"]["recipe_id"]
        ledger_path = session_root / recipe_id / "ledger.jsonl"
        rows = e.load_jsonl(ledger_path)
        rows[0]["attempts"][0]["request"]["temperature"] = 0
        e.dump_jsonl(ledger_path, rows)
        exchange = Path(e.read_json(session_root / "checkpoint.json")["cache_reset"]["exchange"])
        request = e.read_json(exchange / "request.json")
        request["body"]["temperature"] = 0
        e.dump(exchange / "request.json", request)
        with self.assertRaisesRegex(ValueError, "Actual completion settings"):
            bridge.collect_generation_evidence(authority)

    def test_locked_candidate_budget_native_queue_and_all_raw_attempts_bind(self):
        fixture = self.lock_fixture
        candidate = fixture.candidate("candidate-budget", "base-json", 10)
        for path in candidate["cards"]:
            card = e.read_json(path)
            card["prepare"]["n_predict"] = 3072
            e.dump(path, card)
        self.lock = fixture.lock(candidates=[candidate], name="budget-lock.json")
        self.unseal = c.record_unseal(self.lock, fixture.root / "budget-unseal.json", expected_policy_sha256=fixture.policy_sha)
        self.pins.update(registered_lock_sha256=self.lock["sha256"], registered_unseal_sha256=self.unseal["sha256"])
        self.create_queue()
        authority = bridge.authority_metadata(self.plan, self.receipt, **self.pins)
        evidence = bridge.collect_generation_evidence(authority)
        for row in evidence["generations"]:
            expected = 3072 if row["candidate_alias"] == "candidate-budget" else 4096
            self.assertEqual(row["locked_configuration"]["n_predict"], expected)
            self.assertEqual(row["completion_settings"]["n_predict"], expected)
        job = next(row for row in authority["receipt"]["jobs"] if row["candidate_alias"] == "candidate-budget")
        card = e.read_json(Path(job["card"]["path"]))
        ledger_path = Path(job["output"]) / "execution/runtime-run/translation" / card["prepare"]["recipe_id"] / "ledger.jsonl"
        rows = e.load_jsonl(ledger_path)
        retry = deepcopy(rows[0]["attempts"][0])
        retry["request"]["n_predict"] = 4096
        rows[0]["attempts"].append(retry)
        e.dump_jsonl(ledger_path, rows)
        with self.assertRaisesRegex(ValueError, "Actual completion settings"):
            bridge.collect_generation_evidence(authority)


class LockedWorkloadCompatibilityTests(unittest.TestCase):
    """Native packing rows with prospective metadata; no staged runtime import."""
    def fixture(self, *, block=True, budget=3072, recipe="base-json", target=20):
        scene = {"id": "synthetic-scene", "context": [{"id": f"cue-{i}", "text": f"源{i}"} for i in range(125)],
                 "translate_ids": [f"cue-{i}" for i in range(125)]}
        inputs, batches = v2_prepare.pack_scene(scene, target_size=target)
        packing = {"target_size": target, "context_before": 1, "context_after": 1, "token_target": None,
                   "common_context": False, "offset": 0}
        card = {"prepare": {**packing, "recipe_id": "candidate-seed20261008", "recipe": recipe,
                            "seed": 20261008, "n_predict": budget}}
        item = {"label": card["prepare"]["recipe_id"], "recipe": recipe, "seed": 20261008,
                "sampling": "official", "cache_prompt": True, "n_predict": budget, "max_attempts": 2}
        packed = {"packing": deepcopy(packing), "batches": batches}
        if block:
            self.assertEqual(target, 20)
            card["prepare"]["common_context_block_size"] = packed["packing"]["common_context_block_size"] = 60
            packed["source_visibility_policy"] = {"protocol": "hy30-common-source-macroblock-v1", "origin_position": 0,
                "block_size": 60, "target_size": 20, "outer_previous": 1, "outer_next": 1,
                "tail_block": "clipped-to-frozen-scene", "target_packing": "unchanged-scene-origin",
                "capacity_verification": "native-full-prompt-output-reservation-guard", "source_truncation": False}
            # Native staged v1 geometry for three batches/block, then clipped tail.
            footprints = [(0, 60, 0, 61)] * 3 + [(60, 120, 59, 121)] * 3 + [(120, 125, 119, 125)]
            for batch, request, (start, stop, left, right) in zip(batches, inputs, footprints, strict=True):
                ids = scene["translate_ids"]
                batch["readonly_ids"] = ids[left:batch["start_position"]] + ids[batch["end_position"]:right]
                request["context"] = deepcopy(scene["context"][left:right])
                batch["common_source_visibility"] = {"protocol": "hy30-common-source-macroblock-v1",
                    "block_start_position": start, "block_end_position": stop, "context_start_position": left,
                    "context_end_position": right, "visible_ids": ids[left:right], "full_scene_visible": False,
                    "visible_source_cue_count": right-left, "visible_source_text_token_count": None}
        return card, item, packed, inputs, [scene]

    def check(self, values, alias="candidate"):
        card, item, packed, inputs, scenes = values
        return bridge._locked_workload(card, alias, item, packed, inputs, scenes)

    def test_explicit_budget_macroblock_and_candidate_c0_geometry_accept(self):
        self.assertEqual(self.check(self.fixture()), {})
        self.assertEqual(self.check(self.fixture(recipe="c0", budget=4096)), {})
        self.assertEqual(self.check(self.fixture(block=False, recipe="c0", budget=4096, target=5), "C0-official-cached"), {})
        legacy = self.fixture(block=False, budget=4096)
        legacy[0]["prepare"].pop("n_predict")
        self.assertEqual(self.check(legacy), {})

    def test_budget_missing_type_undeclared_and_c0_restrictions_reject(self):
        for budget in (None, False, 0, -1, 3072.0, "3072"):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.check(self.fixture(budget=budget))
        with self.assertRaises(ValueError):
            self.check(self.fixture(recipe="c0"))
        for changed in ("missing-native", "undeclared", "native-drift", "typed-drift", "option-override", "extra-runtime-block", "baseline"):
            values = self.fixture()
            if changed == "missing-native": values[1].pop("n_predict")
            elif changed == "undeclared": values[0]["prepare"].pop("n_predict")
            elif changed == "native-drift": values[1]["n_predict"] = 4096
            elif changed == "typed-drift": values[1]["n_predict"] = 3072.0
            elif changed == "option-override": values[0]["prepare"]["options"] = {"n_predict": 3072}
            elif changed == "extra-runtime-block": values[1]["common_context_block_size"] = 60
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.check(values, "C0-official-cached" if changed == "baseline" else "candidate")

    def test_locked_block_missing_extra_geometry_source_bytes_and_policy_reject(self):
        mutations = [("absent-lock", lambda x: x[0]["prepare"].pop("common_context_block_size")),
            ("missing-packing", lambda x: x[2]["packing"].pop("common_context_block_size")),
            ("extra-packing", lambda x: x[2]["packing"].update(unknown=True)),
            ("missing-policy", lambda x: x[2].pop("source_visibility_policy")),
            ("truncation", lambda x: x[2]["source_visibility_policy"].update(source_truncation=True)),
            ("invalid-block", lambda x: x[0]["prepare"].update(common_context_block_size=61)),
            ("wrong-size", lambda x: x[0]["prepare"].update(common_context_block_size=120)),
            ("visibility", lambda x: x[2]["batches"][0]["common_source_visibility"].update(context_end_position=60)),
            ("source-text", lambda x: x[3][0]["context"][0].update(text="tampered")),
            ("readonly", lambda x: x[2]["batches"][0]["readonly_ids"].pop()),
            ("targets", lambda x: x[3][0]["translate_ids"].reverse())]
        for name, mutate in mutations:
            values = self.fixture()
            mutate(values)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(values)
        with self.assertRaises(ValueError):
            self.check(self.fixture(recipe="c0", budget=4096), "C0-official-cached")
