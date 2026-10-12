"""Synthetic native-byte custody; no GPU, HTTP, CLI or real corpus access."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import unittest

from experiments.translation_eval import runner as e
from . import v2_consistency as c
from . import v2_consistency_custody as custody
from . import v2_delivery as delivery
from . import v2_prepare as prepare
from . import v2_source_preparation as auxiliary
from . import v2_source_projection as projection
from . import v2_worker as worker
from . import test_v2_evaluation as eval_tests


class TracingClient:
    """Emit actual native exchange schema without opening a socket."""
    def __init__(self, trace_dir: Path, outputs: list[dict]):
        self.trace_dir, self.outputs = trace_dir, deepcopy(outputs)
        self.last_exchange = None
        self.timeout = 300
        self.counter = 0
        self.prompt = None

    def exchange(self, endpoint, body, response):
        self.counter += 1
        path = self.trace_dir / f"exchange-{self.counter:04d}"
        path.mkdir(parents=True)
        e.dump(path / "request.json", {"endpoint": endpoint, "body": body})
        e.dump(path / "response.raw", response)
        e.dump(path / "transport.json", {"status": 200})
        self.last_exchange = str(path.resolve())
        return deepcopy(response)

    def request(self, endpoint):
        return self.exchange(endpoint, None, {"model_alias": worker.CANDIDATE})

    def tokenize(self, prompt):
        self.prompt = prompt
        return self.exchange("/tokenize", {"content": prompt}, {"tokens": list(range(8))})["tokens"]

    def complete(self, request):
        content = self.outputs.pop(0)
        cache_n = content.pop("_cache_n", 0)
        response = {"content": json.dumps(content, ensure_ascii=False), "tokens_predicted": 8,
                    "tokens_evaluated": 8, "timings": {"cache_n": cache_n},
                    "generation_settings": {k: v for k, v in request.items() if k != "prompt"}}
        return self.exchange("/completion", request, response)


class NativeConsistencyFixture:
    """Reusable three-seed fixture invoking real prepare/worker/export APIs."""
    def __init__(self, *, mode="terms", zero=False, fail_aux=False, partial_aux=False, shared_source=None,
                 auxiliary_attempts_by_seed=None, card_options=None, treated_target_sizes=None,
                 treated_card_options=None, explicit_none_options=False, additional_implementation_seed=None,
                 native_card_metadata=False, native_v5_metadata=False):
        native_card_metadata = native_card_metadata or native_v5_metadata
        self.shared_source = shared_source
        if shared_source is None:
            self.base = eval_tests.SceneEvaluationTests(methodName="test_multiple_scenes_and_episodes_keep_same_work_and_fixed_scope")
            self.base.setUp()
            self.root = self.base.root
            for scene in self.base.scenes:
                scene.update(scene_id=scene["id"], source_language="ja", target_language="zh-Hans")
            e.dump_jsonl(self.base.scene_path, self.base.scenes)
            self.base.delivery("source-authority")
        else:
            self.base = shared_source.base
            self.root = shared_source.root / "background-native-fixture"
            self.root.mkdir()
        self.mode, self.zero, self.fail_aux, self.partial_aux = mode, zero, fail_aux, partial_aux
        self.scenes = [{"id": row["id"], "source_language": "ja", "target_language": "zh-Hans",
            "context": [{"id": cue["id"], "text": cue["text"]} for cue in row["context"]],
            "translate_ids": row["translate_ids"]} for row in self.base.scenes]
        self.source = {"manifest": str(self.base.manifest_path.resolve()), "manifest_sha256": e.sha(self.base.manifest_path),
                       "scenes": str(self.base.scene_path.resolve()), "scenes_sha256": e.sha(self.base.scene_path)}
        self.scope_path = self.root / "consistency-scope.json"
        e.dump(self.scope_path, {"version": "hy30-consistency-source-scope-v1", "state": "frozen_before_consistency_quality",
            "split": "screen-a", "selection": "explicit_complete_scenes", "quality_inspected": False,
            "source_manifest": custody.identity(self.base.manifest_path), "source_scenes": custody.identity(self.base.scene_path),
            "source_freeze": custody.identity(self.base.source / "freeze-manifest.json"),
            "scene_ids": [row["id"] for row in self.scenes], "window_ids": [row["id"] for row in self.base.windows],
            "selected_scene_count": 2, "full_scene_count": 2, "selected_window_count": 3, "full_window_count": 3})
        self.scope = custody.identity(self.scope_path)
        if shared_source is not None:
            self.scope_path, self.scope = shared_source.scope_path, shared_source.scope
        self.runtime = {"asset_sha256": "a" * 64, "template_sha256": "b" * 64,
                        "engine": {"build": 11429, "context_size": 8192}}
        self.authority_path = self.root / "generation-authority.json"
        self.authority = {"version": "hy30-consistency-generation-authority-v1", "state": "approved_before_generation",
            "source_scope": self.scope, "group_id": "synthetic-group", "generation_seeds": list(c.SEEDS),
            "mode": mode, "max_items": (32 if mode == "terms" else 16) if native_v5_metadata else 4,
            "runtime": self.runtime, "trials": []}
        self.cards, self.roots, self.plans = {}, {}, {}
        if native_card_metadata:
            policy_path = self.root / "native-decision-policy.json"
            e.dump(policy_path, {"version": "synthetic-policy-v1", "state": "frozen_before_generation"})
        # Freeze source-only cards and all six planned output identities first.
        for seed in c.SEEDS:
            for role in custody.ALIASES:
                root = self.root / f"{role}-{seed}"
                card_path = self.root / f"card-{role}-{seed}.json"
                settings = {"recipe_id": role, "recipe": "c0" if role == "baseline" else "base-json", "seed": seed,
                    "stage": "screening", "split": "screen-a", "selected_scene_ids": [s["id"] for s in self.scenes],
                    "target_size": 1, "context_before": 1, "context_after": 1}
                if role == "treated" and treated_target_sizes is not None:
                    settings["target_size"] = treated_target_sizes[seed]
                original_options = treated_card_options if role == "treated" and treated_card_options is not None else card_options
                if original_options is not None or explicit_none_options:
                    settings["options"] = deepcopy(original_options)
                card = {"schema": "hy30-flow-trial-card-v2", "source": self.source, "prepare": settings,
                        "implementation_identity": [custody.identity(Path(worker.__file__)), custody.identity(Path(auxiliary.__file__))]}
                if native_card_metadata:
                    parent_path = self.root / f"parent-card-{role}-{seed}.json"
                    e.dump(parent_path, {"id": f"synthetic-parent-{role}-{seed}", "seed": seed, "role": role})
                    card.update(id=f"synthetic-{role}-seed{seed}", seed=seed, recipe_id=settings["recipe_id"],
                        candidate_group=role, family="C0" if role == "baseline" else "F6" if mode == "terms" else "F7",
                        role="fresh_control" if role == "baseline" else "candidate",
                        hypothesis=f"Synthetic native-card descriptor for seed {seed}",
                        source_freeze=custody.identity(self.base.source / "freeze-manifest.json"),
                        quality_scope={"windows": 3, "representative_windows": 3, "risk_windows": 0,
                            "scored_ids": 15, "works": 1, "seeds_for_candidate_decision": list(c.SEEDS)},
                        source_estimate={"scenes": 2, "source_cues": 6}, prospective_descriptor_only=True,
                        derivation={"parent_card": custody.identity(parent_path)},
                        historical_control_relation={"parent_card": custody.identity(parent_path),
                            "no_generation_relabel": True, "no_time_identity_equivalence": True},
                        decision_policy=custody.identity(policy_path), fixed_runtime_contract=deepcopy(self.runtime))
                if role == "treated" and seed == additional_implementation_seed:
                    card["implementation_identity"].append(custody.identity(Path(custody.recipes.__file__)))
                if role == "treated":
                    plan_path = self.root / f"aux-plan-{seed}.json"
                    e.dump(plan_path, {"schema": auxiliary.SESSION_SCHEMA, "mode": mode, "stage": "screening",
                        "protocol": "eligibility-filtered-proposals-v1" if mode == "terms" else "quoted-background-with-uncertainty-v1",
                        "source": {**self.source, "freeze_sha256": self.scope_freeze_sha},
                        "scene_ids": [s["id"] for s in self.scenes],
                        "settings": {"sampling": "official", "cache_prompt": True, "n_predict": 2048 if native_v5_metadata else 4096,
                                     "seed": seed, "max_attempts": (auxiliary_attempts_by_seed or {}).get(seed, 2 if native_v5_metadata else 1),
                                     "max_items": self.authority["max_items"]},
                        "budgets": {"max_translation_calls": 8, "max_judge_calls": 0,
                                    "max_estimated_tokens": 100000, "max_wall_seconds": 120}})
                    card["source_preparation"] = {"plan": str(plan_path), "sha256": e.sha(plan_path)}
                    settings["source_preparation_projection"] = projection.TERMS if mode == "terms" else projection.SCENE_CARD
                    self.plans[seed] = plan_path
                if native_v5_metadata:
                    self.v5_metadata(card, seed, role)
                e.dump(card_path, card)
                self.cards[seed, role], self.roots[seed, role] = card_path, root
                self.authority["trials"].append({"seed": seed, "role": role,
                    "card": custody.identity(card_path), "output": str(root.resolve())})
        e.dump(self.authority_path, self.authority)
        self.authority_pointer = custody.identity(self.authority_path)
        self.pair_pointers = []
        for seed in c.SEEDS:
            for role in custody.ALIASES:
                self.execute(seed, role)
            pair_path = self.root / f"pair-{seed}.json"
            pair = {"version": "hy30-consistency-generation-pair-v1", "source_scope": self.scope,
                    "seed": seed, "group_id": self.authority["group_id"]}
            for role in custody.ALIASES:
                pair[role] = {"trial_root": str(self.roots[seed, role].resolve()), "card": custody.identity(self.cards[seed, role]),
                              "terminal": custody.identity(self.roots[seed, role] / "trial-completion.json")}
            pair["treated"]["projection"] = projection.TERMS if mode == "terms" else projection.SCENE_CARD
            e.dump(pair_path, pair)
            self.pair_pointers.append(custody.identity(pair_path))

    @property
    def scope_freeze_sha(self):
        return e.sha(self.base.source / "freeze-manifest.json")

    def v5_metadata(self, card, seed, role):
        """Mirror observed v5 metadata keys with only local synthetic artifacts."""
        def artifact(name, artifact_seed=seed):
            path = self.root / f"historical-{name}-{artifact_seed}.json"
            if not path.exists():
                e.dump(path, {"id": name, "seed": artifact_seed, "synthetic_metadata_only": True})
            return custody.identity(path)

        card.update(frozen_origin="Original registered source order.",
            decision_contract="Complete three-seed fixed source denominator; mechanical qualification is not quality.",
            baseline_connection="Historical lineage retained; original baseline pair is separately authenticated.")
        controls = []
        for historical_seed in c.SEEDS:
            controls.append({"generation_seed": historical_seed,
                "trial_completion": artifact("trial-completion", historical_seed),
                "delivery_files": [artifact("delivery", historical_seed)],
                "universal_evaluation_root": str(self.root / f"historical-evaluation-{historical_seed}"),
                "universal_finalization": artifact("finalization", historical_seed),
                "matched_control_scope": {**artifact("matched-scope", historical_seed),
                    "version": "synthetic-matched-scope-v1", "state": "frozen_before_candidate_quality_inspection",
                    "selection": "explicit_matched_windows", "expected_windows_per_seed": 3},
                "matched_validation_provenance": {**artifact("matched-validation", historical_seed),
                    "version": "synthetic-matched-validation-v1", "state": "frozen_before_any_candidate_quality_inspection"}})
        card["control_reuse"] = {"binding": {"behavior_receipt": artifact("behavior"),
            "control_kind": "synthetic-native-screen-a", "cohort": {"split": "screen-a", "scenes": 2,
                "source_cues": 6, "score_windows": 3, "score_cues": 15, "batches_per_seed": 6, "seeds": list(c.SEEDS)},
            "safe_metadata": [artifact("safe-metadata")], "controls": controls},
            "preserve_actual_historical_generation_and_judge_identity": True, "no_new_control_generation": True,
            "no_cache_history_or_walltime_equivalence_claim": True, "requires_actual_scope_packet_provenance_validation": True}
        if role == "treated":
            plan = e.read_json(self.plans[seed])
            card["source_preparation_contract"] = {"protocol": plan["protocol"],
                "projection": card["prepare"]["source_preparation_projection"],
                "aux_output_reservation_tokens": 2048, "main_output_reservation_tokens": 4096,
                "cost_attribution": "Count original preparation once per candidate/seed, including complete startup/export.",
                "fresh_server_per_phase": True}
            card["qualification_prerequisite"] = {"required": True, "status": "historical_native_mechanical_receipt_bound",
                "mechanical_receipt": artifact("mechanical"), "parent_requirement": {"required": True,
                    "status": "pending_actual_new_protocol_receipt", "qualification_card": artifact("qualification-card"),
                    "required_checks": ["Retain complete native delivery and all original failures/costs."],
                    "interpretation": "Mechanical qualification is not semantic quality."},
                "not_a_new_v5_native_generation_or_semantic_quality_pass": True,
                "fresh_trial_still_requires_capacity_delivery_injection_and_full_cost_validation": True}
            if self.mode == "terms":
                card["resource_revision"] = {"parent_card": artifact("parent-card"),
                    "parent_source_plan": artifact("parent-source-plan"), "diagnostic_audit": artifact("diagnostic-audit"),
                    "only_executed_parameter_change": {"source_preparation.settings.max_items": {"from": 16, "to": 32}},
                    "fresh_generation_required": True, "no_reuse_of_failed_original_attempts": True,
                    "original_failed_qualification_preserved": True,
                    "interpretation": "A declared resource variant never relabels original failures."}

    def close(self):
        if self.shared_source is None:
            self.base.doCleanups()

    def native_identity(self, args):
        asset = {"id": worker.CANDIDATE, "sha256": "a" * 64}
        return {"asset": asset, "engine": {"asset": asset, "model_path": "synthetic.gguf", "model_sha256": "a" * 64,
            "server_pid": 1234, "command": ["server", "-np", "1"], "build": 11429, "context_size": 8192},
            "engine_manifest_sha256": "a" * 64, "template_sha256": "b" * 64}

    def args(self, path, output):
        return argparse.Namespace(candidate=worker.CANDIDATE, session_plan=path, output_dir=output,
            server_url="http://unused.invalid", context_size=8192, engine_manifest=self.root / "unused.json",
            asset_manifest=[], stop_on_oom=True)

    def execute(self, seed, role):
        root = self.roots[seed, role]
        root.mkdir()
        card = e.read_json(self.cards[seed, role])
        terminal = {"schema": "hy30-flow-trial-v2", "card_path": str(self.cards[seed, role]),
            "card_sha256": e.sha(self.cards[seed, role]), "card": card, "status": "complete", "trial_wall_seconds": .2}
        extra = {}
        if role == "treated":
            plan_path = self.plans[seed]
            aux_root = root / "source-preparation/runtime-run/translation"
            if self.fail_aux:
                terminal.update(status="failed", failed_phase="source_preparation", source_preparation={
                    "plan_path": str(plan_path), "plan_sha256": e.sha(plan_path)})
                e.dump(root / "trial-completion.json", terminal)
                return
            outputs = []
            for number, scene in enumerate(self.scenes, 1):
                if self.mode == "terms":
                    outputs.append({"terms": [] if self.zero else [
                        {"source": f"台詞{number}", "translation": f"约定{number}", "uncertain": False},
                        {"source": f"台詞{number}-1", "translation": "拒绝项", "uncertain": True}]})
                else:
                    outputs.append({"background": [] if self.zero else [{"text": "场景描述",
                        "evidence": [{"id": scene["context"][0]["id"], "quote": scene["context"][0]["text"]}], "uncertain": True}]})
            if self.partial_aux:
                outputs[-1] = {self.mode: "malformed synthetic response"}
            code = auxiliary.execute_plan(self.args(plan_path, aux_root),
                client_factory=lambda _, trace_dir: TracingClient(trace_dir, outputs), identity_loader=self.native_identity)
            artifact = e.read_json(aux_root / "worker-completion.json")["artifact"]
            command = root / "source-preparation/command-completion.json"
            e.dump(command, {"schema": "hy30-flow-command-v2", "worker": "experiments.translation_flow.v2_source_preparation",
                "plan_sha256": e.sha(plan_path), "returncode": code, "command_seconds": .1})
            rows = e.load_jsonl(aux_root / "ledger.jsonl")
            attempts = [a for row in rows for a in row["attempts"]]
            terminal["source_preparation"] = {"plan_path": str(plan_path), "plan_sha256": e.sha(plan_path),
                "runtime_exit_code": code, "cost": {"command": custody.identity(command),
                    "ledger": custody.identity(aux_root / "ledger.jsonl"), "command_seconds": .1,
                    "scene_records": len(rows), "attempts": len(attempts),
                    "translation_calls": sum(a.get("completion_dispatched") is True for a in attempts)}}
            if code:
                terminal.update(status="failed", failed_phase="source_preparation")
                e.dump(root / "trial-completion.json", terminal)
                return
            terminal["source_preparation"]["artifact"] = artifact
            extra = {"source_preparation_path": Path(artifact["path"]), "source_preparation_sha256": artifact["sha256"],
                     "source_preparation_projection": card["prepare"]["source_preparation_projection"]}
        prepared = root / "prepared"
        settings = deepcopy(card["prepare"])
        settings.pop("split")
        settings.pop("source_preparation_projection", None)
        prepare.prepare(manifest=self.base.manifest_path, scenes=self.base.scene_path, output=prepared,
                        split="screen-a", **settings, **extra)
        windows = e.load_jsonl(prepared / "inputs.jsonl")
        outputs = [{"translations": {uid: "合成译文" for uid in row["translate_ids"]}} for row in windows]
        main_root = root / "execution/runtime-run/translation"
        with redirect_stdout(io.StringIO()):
            code = worker.execute_plan(self.args(prepared / "session-plan.json", main_root),
                client_factory=lambda _, trace_dir: TracingClient(trace_dir, outputs), identity_loader=self.native_identity)
        if code:
            raise AssertionError("Synthetic main generation did not complete")
        for name in ("packed-mapping.json", "batch-options.json"):
            if (prepared / name).exists():
                shutil.copyfile(prepared / name, main_root / name)
        delivery.deliver(self.base.manifest_path, prepared / "packed-mapping.json", main_root / role, root / "delivery")
        e.dump(root / "execution/command-completion.json", {"schema": "hy30-flow-command-v2",
            "worker": "experiments.translation_flow.v2_worker", "plan_sha256": e.sha(prepared / "session-plan.json"),
            "returncode": code, "command_seconds": .1})
        terminal["runtime_exit_code"] = code
        e.dump(root / "trial-completion.json", terminal)

    def authenticate(self):
        return [custody.authenticate_generation_pair(self.scope, pointer,
            generation_authorization_pointer=self.authority_pointer,
            registered_generation_authorization_sha256=self.authority_pointer["sha256"]) for pointer in self.pair_pointers]

    def rebind_card_metadata(self, seed, role, mutate):
        """Rebind synthetic declarations; preserve original executed native bytes."""
        path = self.cards[seed, role]
        card = e.read_json(path)
        mutate(card)
        e.dump(path, card)
        pointer = custody.identity(path)
        terminal_path = self.roots[seed, role] / "trial-completion.json"
        terminal = e.read_json(terminal_path)
        terminal.update(card=card, card_sha256=pointer["sha256"])
        e.dump(terminal_path, terminal)
        index = c.SEEDS.index(seed)
        pair_path = Path(self.pair_pointers[index]["path"])
        pair = e.read_json(pair_path)
        pair[role].update(card=pointer, terminal=custody.identity(terminal_path))
        e.dump(pair_path, pair)
        self.pair_pointers[index] = custody.identity(pair_path)
        next(row for row in self.authority["trials"] if row["seed"] == seed and row["role"] == role)["card"] = pointer
        e.dump(self.authority_path, self.authority)
        self.authority_pointer = custody.identity(self.authority_path)

    def freeze(self, *, donor=None):
        return custody.freeze_source_frames(self.scope, self.authenticate(), self.root / "custody.json", term_inventory_donor=donor)


class ConsistencyCustodyTests(unittest.TestCase):
    def fixture(self, **kwargs):
        fixture = NativeConsistencyFixture(**kwargs)
        self.addCleanup(fixture.close)
        return fixture

    def test_native_three_seed_exchange_to_source_frame_and_revalidation(self):
        f = self.fixture()
        result = f.freeze()
        self.assertEqual(len(result["jobs"]), 12)
        receipt = custody.validate_receipt(result["receipt"], result["jobs"])
        self.assertEqual(receipt["original_cost_count"], 6)
        self.assertEqual(receipt["new_generation_calls"], 0)
        self.assertIsNone(receipt["root_count"])
        self.assertEqual([row["declined_count"] for row in receipt["proposal_inventory_audit"]], [1] * 6)
        self.assertEqual({job["envelope"]["judge_packet"]["phase"] for job in result["jobs"]}, {"A", "B"})

    def test_actual_rendered_tokenize_mutation_rejected_even_rehashed_inner_claim(self):
        f = self.fixture()
        root = f.roots[c.SEEDS[0], "treated"] / "execution/runtime-run/translation"
        ledger_path = root / "treated/ledger.jsonl"
        rows = e.load_jsonl(ledger_path)
        attempt = rows[0]["attempts"][0]
        request_path = Path(attempt["tokenize_exchange"]) / "request.json"
        obj = e.read_json(request_path)
        obj["body"]["content"] += " altered"
        e.dump(request_path, obj)
        attempt["prompt_sha256"] = c.object_hash(obj["body"]["content"])
        e.dump_jsonl(ledger_path, rows)
        with self.assertRaises(ValueError):
            f.authenticate()

    def test_zero_and_failed_preparations_keep_all_fixed_seed_slots_unknown(self):
        for options in ({"zero": True}, {"fail_aux": True}):
            with self.subTest(options=options):
                f = self.fixture(**options)
                result = f.freeze()
                self.assertEqual(len(result["expected_slots"]), 12)
                expected = "inventory_incomplete" if options.get("fail_aux") else "not_assessed_zero_inventory"
                self.assertTrue(all(row["status"] == expected for row in result["expected_slots"] if row["phase"] == "A"))
                self.assertEqual(len(result["jobs"]), 6 if options.get("fail_aux") else 0)
                if options.get("fail_aux"):
                    self.assertTrue(all(pair["treated_main_not_started"] for pair in f.authenticate()))

    def test_genuine_partial_auxiliary_keeps_accepted_and_failed_scenes(self):
        f = self.fixture(partial_aux=True)
        pairs = f.authenticate()
        self.assertEqual([row["status"] for row in pairs[0]["preparations"]], ["prepared", "preparation_failed"])
        self.assertTrue(all(pair["treated_main_not_started"] for pair in pairs))
        result = f.freeze()
        self.assertEqual(len(result["expected_slots"]), 12)
        self.assertEqual(len(result["jobs"]), 9)
        self.assertEqual([row["status"] for row in result["expected_slots"] if row["phase"] == "A" and row["scene_id"] == "scene-b"], ["inventory_incomplete"] * 3)

    def test_scope_and_generation_authority_cannot_be_relabelled(self):
        f = self.fixture()
        bad = deepcopy(e.read_json(f.scope_path))
        bad["split"] = "screening"
        path = f.root / "bad-scope.json"
        e.dump(path, bad)
        with self.assertRaises(ValueError):
            custody.authenticate_generation_pair(custody.identity(path), f.pair_pointers[0],
                generation_authorization_pointer=f.authority_pointer,
                registered_generation_authorization_sha256=f.authority_pointer["sha256"])
        with self.assertRaises(ValueError):
            custody.authenticate_generation_pair(f.scope, f.pair_pointers[0],
                generation_authorization_pointer=f.authority_pointer, registered_generation_authorization_sha256="f" * 64)

    def test_background_without_same_source_term_donor_explicit_unavailable(self):
        f = self.fixture(mode="background")
        result = f.freeze()
        self.assertEqual(len(result["jobs"]), 6)
        self.assertEqual({row["status"] for row in result["expected_slots"] if row["phase"] == "A"}, {"term_inventory_unavailable"})
        custody.validate_receipt(result["receipt"])

    def test_same_source_terms_donor_revalidated_and_other_source_rejected(self):
        terms = self.fixture()
        donor = terms.freeze()["receipt"]
        background = self.fixture(mode="background", shared_source=terms)
        result = background.freeze(donor=donor)
        self.assertEqual(len(result["jobs"]), 12)
        self.assertEqual(custody.validate_receipt(result["receipt"])["term_inventory_donor"], donor)
        other = self.fixture(mode="background")
        with self.assertRaisesRegex(ValueError, "exact same registered source scope"):
            other.freeze(donor=donor)

    def test_raw_native_completion_cannot_self_claim_different_settings_or_tokens(self):
        f = self.fixture()
        root = f.roots[c.SEEDS[0], "baseline"] / "execution/runtime-run/translation"
        row = e.load_jsonl(root / "baseline/ledger.jsonl")[0]
        attempt = row["attempts"][0]
        plan = e.read_json(root / "session-plan.json")
        item = plan["workloads"][0]
        window = e.load_jsonl(root / "baseline/inputs.jsonl")[0]
        prompt = custody.recipes.render_window(item["recipe"], window, item)
        content, proof = custody._trace(attempt, root / "transport", prompt, item, ids=window["translate_ids"])
        self.assertEqual(len(proof), 6)
        self.assertTrue(content)
        request_path = Path(attempt["original_response"]) / "request.json"
        obj = e.read_json(request_path)
        obj["body"]["n_predict"] += 1
        e.dump(request_path, obj)
        attempt["request"] = obj["body"]
        attempt["request_sha256"] = c.object_hash(obj["body"])
        with self.assertRaisesRegex(ValueError, "completion settings"):
            custody._trace(attempt, root / "transport", prompt, item, ids=window["translate_ids"])

    def test_baseline_wrong_recipe_rejected_before_native_intake(self):
        f = self.fixture()
        seed = c.SEEDS[0]
        card_path = f.cards[seed, "baseline"]
        card = e.read_json(card_path)
        card["prepare"]["recipe"] = "joint-json"
        e.dump(card_path, card)
        authority = e.read_json(f.authority_path)
        authority["trials"][0]["card"] = custody.identity(card_path)
        e.dump(f.authority_path, authority)
        f.authority_pointer = custody.identity(f.authority_path)
        terminal_path = f.roots[seed, "baseline"] / "trial-completion.json"
        terminal = e.read_json(terminal_path)
        terminal.update(card=card, card_sha256=e.sha(card_path))
        e.dump(terminal_path, terminal)
        pair_path = Path(f.pair_pointers[0]["path"])
        pair = e.read_json(pair_path)
        pair["baseline"].update(card=custody.identity(card_path), terminal=custody.identity(terminal_path))
        e.dump(pair_path, pair)
        f.pair_pointers[0] = custody.identity(pair_path)
        with self.assertRaisesRegex(ValueError, "authentic C0"):
            f.authenticate()

    def test_actual_native_canonical_neutral_options_are_accepted(self):
        options = {"terms": [], "background": [], "style": "neutral", "review": False}
        f = self.fixture(card_options=options)
        result = f.freeze()
        self.assertEqual(len(result["jobs"]), 12)
        for seed in c.SEEDS:
            for role in custody.ALIASES:
                root = f.roots[seed, role] / "execution/runtime-run/translation"
                settings = e.read_json(root / role / "run.json")["settings"]
                self.assertEqual({key: settings[key] for key in options}, options)
        custody.validate_receipt(result["receipt"])

    def test_native_none_options_use_canonical_absent_semantics(self):
        f = self.fixture(explicit_none_options=True)
        result = f.freeze()
        receipt = custody.validate_receipt(result["receipt"])
        self.assertEqual(len(result["jobs"]), 12)
        self.assertEqual(receipt["main_recipes"]["baseline"]["prepare"]["options"],
                         {"terms": [], "background": [], "style": "neutral", "review": False})

    def test_native_supported_material_style_remains_outside_consistency_scope(self):
        options = {"terms": [], "background": [], "style": "neutral", "review": False}
        f = self.fixture(card_options=options, treated_card_options={**options, "style": "natural-dialogue"})
        with self.assertRaisesRegex(ValueError, "bounded native prepared"):
            f.authenticate()

    def test_noncanonical_falsey_and_manual_treatments_cannot_bypass_options_guard(self):
        canonical = {"terms": [], "background": [], "style": "neutral", "review": False}
        self.assertEqual(custody._neutral_options(None), canonical)
        self.assertEqual(custody._neutral_options({}), canonical)
        for key, value in (("terms", None), ("terms", {}), ("background", 0), ("style", None),
                           ("style", ""), ("style", "natural-dialogue"), ("review", 0), ("review", None),
                           ("review", True), ("terms", [{"source": "manual"}]), ("background", [{"text": "manual"}]),
                           ("quoted_terms", None), ("partition_grammar_limits", {})):
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    custody._neutral_options({**canonical, key: value})

    def test_authentic_treated_main_partition_drift_cannot_define_one_group(self):
        f = self.fixture(treated_target_sizes=dict(zip(c.SEEDS, (1, 2, 1))), native_card_metadata=True)
        pairs = f.authenticate()
        self.assertEqual([len(pair["treated_batches"]) for pair in pairs], [6, 4, 6])
        with self.assertRaisesRegex(ValueError, "main recipe|source partition"):
            custody.freeze_source_frames(f.scope, pairs, f.root / "mixed-main.json")

    def test_uniform_treated_packing_can_differ_from_uniform_baseline(self):
        options = {"terms": [], "background": [], "style": "neutral", "review": False}
        f = self.fixture(card_options=options, treated_target_sizes={seed: 2 for seed in c.SEEDS})
        pairs = f.authenticate()
        self.assertEqual([len(pair["baseline_batches"]) for pair in pairs], [6] * 3)
        self.assertEqual([len(pair["treated_batches"]) for pair in pairs], [4] * 3)
        result = custody.freeze_source_frames(f.scope, pairs, f.root / "different-role-packing.json")
        self.assertEqual(len(result["jobs"]), 12)
        custody.validate_receipt(result["receipt"])

    def test_authentic_declared_implementation_drift_cannot_define_one_group(self):
        f = self.fixture(additional_implementation_seed=c.SEEDS[1], native_card_metadata=True)
        pairs = f.authenticate()
        self.assertEqual([len(p["main_recipes"]["treated"]["implementation_identity"]) for p in pairs], [2, 3, 2])
        with self.assertRaisesRegex(ValueError, "treated main recipe differs"):
            custody.freeze_source_frames(f.scope, pairs, f.root / "mixed-declared-code.json")

    def test_native_card_ids_and_bound_control_lineage_are_not_execution_drift(self):
        f = self.fixture(native_card_metadata=True,
            card_options={"terms": [], "background": [], "style": "neutral", "review": False})
        pairs = f.authenticate()
        self.assertEqual(len({e.read_json(path)["id"] for path in f.cards.values()}), 6)
        result = custody.freeze_source_frames(f.scope, pairs, f.root / "native-descriptors.json")
        self.assertEqual(len(result["jobs"]), 12)
        receipt = custody.validate_receipt(result["receipt"])
        for pair in pairs:
            for role in custody.ALIASES:
                provenance = pair["card_provenance"][role]
                card = e.read_json(f.cards[pair["seed"], role])
                self.assertEqual(provenance["card"], custody.identity(f.cards[pair["seed"], role]))
                self.assertEqual(provenance["metadata"]["id"], card["id"])
                self.assertEqual(provenance["metadata"]["derivation"], card["derivation"])
                self.assertIn(card["derivation"]["parent_card"], provenance["lineage_artifacts"])
                self.assertNotIn("id", pair["main_recipes"][role])
                self.assertNotIn("derivation", pair["main_recipes"][role])
        self.assertEqual(len(receipt["pair_pointers"]), 3)

    def test_native_card_lineage_tamper_is_rejected_without_normalizing_proof(self):
        f = self.fixture(native_card_metadata=True)
        card = e.read_json(f.cards[c.SEEDS[0], "baseline"])
        parent = Path(card["derivation"]["parent_card"]["path"])
        e.dump(parent, {"id": "changed-parent", "seed": c.SEEDS[0], "role": "baseline"})
        with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
            f.authenticate()

    def test_execution_fields_are_retained_when_native_descriptors_are_excluded(self):
        card = {"schema": "hy30-flow-trial-card-v2", "source": {"manifest_sha256": "a" * 64},
            "prepare": {"seed": c.SEEDS[0], "recipe_id": "label", "recipe": "base-json", "target_size": 1,
                "context_before": 1, "context_after": 1, "n_predict": 4096, "options": None},
            "implementation_identity": [{"path": "synthetic-code", "sha256": "b" * 64}],
            "fixed_runtime_contract": {"context_size": 8192}, "id": "synthetic-card"}
        normalized = custody._main_recipe(card)
        for section, key, value in (("prepare", "target_size", 2), ("prepare", "context_before", 2),
                ("prepare", "context_after", 2), ("prepare", "n_predict", 2048),
                ("source", "manifest_sha256", "c" * 64), ("fixed_runtime_contract", "context_size", 4096)):
            with self.subTest(section=section, key=key):
                changed = deepcopy(card)
                changed[section][key] = value
                self.assertNotEqual(normalized, custody._main_recipe(changed))
        changed = deepcopy(card)
        changed["seed"] = c.SEEDS[1]
        with self.assertRaisesRegex(ValueError, "Top-level"):
            custody._main_recipe(changed)
        changed = deepcopy(card)
        changed["unrecognized_execution_setting"] = "cannot silently drop"
        with self.assertRaisesRegex(ValueError, "Unsupported card fields"):
            custody._main_recipe(changed)

    def test_observed_f6_v5_metadata_contract_freezes_authentic_native_exchange(self):
        f = self.fixture(native_v5_metadata=True)
        pairs = f.authenticate()
        result = custody.freeze_source_frames(f.scope, pairs, f.root / "f6-v5.json")
        self.assertEqual(len(result["jobs"]), 12)
        receipt = custody.validate_receipt(result["receipt"])
        self.assertEqual(receipt["preparation_recipe"]["settings"]["max_items"], 32)
        self.assertEqual(receipt["preparation_recipe"]["settings"]["n_predict"], 2048)
        for pair in pairs:
            card = e.read_json(f.cards[pair["seed"], "treated"])
            provenance = pair["card_provenance"]["treated"]
            self.assertEqual(provenance["metadata"]["qualification_prerequisite"], card["qualification_prerequisite"])
            self.assertEqual(provenance["metadata"]["resource_revision"], card["resource_revision"])
            extended = card["control_reuse"]["binding"]["controls"][0]["matched_control_scope"]
            self.assertIn({key: extended[key] for key in ("path", "sha256")}, provenance["lineage_artifacts"])
            self.assertEqual(pair["main_recipes"]["treated"]["source_preparation_contract"], card["source_preparation_contract"])
            self.assertNotIn("control_reuse", pair["main_recipes"]["treated"])

    def test_observed_f7_v5_metadata_contract_keeps_inventory_unavailable_honest(self):
        f = self.fixture(mode="background", native_v5_metadata=True)
        result = f.freeze()
        self.assertEqual(len(result["jobs"]), 6)
        self.assertEqual(len(result["expected_slots"]), 12)
        receipt = custody.validate_receipt(result["receipt"])
        self.assertEqual(receipt["term_inventory_state"], "term_inventory_unavailable")
        self.assertEqual(receipt["preparation_recipe"]["settings"]["max_items"], 16)
        self.assertEqual(receipt["main_recipes"]["treated"]["source_preparation_contract"]["projection"], projection.SCENE_CARD)
        self.assertNotIn("resource_revision", receipt["card_provenance"][str(c.SEEDS[0])]["treated"]["metadata"])

    def test_v5_execution_summary_cannot_override_actual_native_settings(self):
        f = self.fixture(native_v5_metadata=True)
        f.rebind_card_metadata(c.SEEDS[0], "treated",
            lambda card: card["source_preparation_contract"].update(aux_output_reservation_tokens=4096))
        with self.assertRaisesRegex(ValueError, "contract differs"):
            f.authenticate()

    def test_v5_extended_lineage_and_qualification_pointers_are_not_ignored(self):
        f = self.fixture(native_v5_metadata=True)
        card = e.read_json(f.cards[c.SEEDS[0], "treated"])
        pointers = [card["qualification_prerequisite"]["mechanical_receipt"],
                    card["control_reuse"]["binding"]["controls"][0]["matched_control_scope"],
                    card["resource_revision"]["diagnostic_audit"]]
        for pointer in pointers:
            with self.subTest(path=Path(pointer["path"]).name):
                path = Path(pointer["path"])
                original = path.read_bytes()
                path.write_bytes(b'{"changed_synthetic_metadata":true}\n')
                with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
                    f.authenticate()
                path.write_bytes(original)

    def test_v5_declared_summary_and_resource_changes_must_match_executed_plan(self):
        contract = {"protocol": "eligibility-filtered-proposals-v1", "projection": projection.TERMS,
            "aux_output_reservation_tokens": 2048, "main_output_reservation_tokens": 4096,
            "cost_attribution": "Once per original trial", "fresh_server_per_phase": True}
        card = {"prepare": {"source_preparation_projection": projection.TERMS}, "source_preparation_contract": contract}
        plan = {"protocol": contract["protocol"], "settings": {"n_predict": 2048, "max_items": 32}}
        main = {"missing": False, "settings": {"n_predict": 4096}, "projection": projection.TERMS}
        custody._source_preparation_contract(card, plan, main)
        for key, value in (("protocol", "different"), ("projection", projection.SCENE_CARD),
                           ("aux_output_reservation_tokens", True), ("aux_output_reservation_tokens", 4096),
                           ("main_output_reservation_tokens", 2048), ("fresh_server_per_phase", False), ("cost_attribution", "")):
            with self.subTest(key=key, value=value):
                changed = deepcopy(card)
                changed["source_preparation_contract"][key] = value
                with self.assertRaisesRegex(ValueError, "contract differs"):
                    custody._source_preparation_contract(changed, plan, main)
        changed = deepcopy(card)
        changed["resource_revision"] = {"only_executed_parameter_change": {"source_preparation.settings.max_items": {"from": 16, "to": 31}}}
        with self.assertRaisesRegex(ValueError, "resource revision differs"):
            custody._source_preparation_contract(changed, plan, main)

    def test_individually_authentic_auxiliary_plan_drift_cannot_define_one_group(self):
        f = self.fixture(auxiliary_attempts_by_seed={c.SEEDS[1]: 2})
        pairs = f.authenticate()
        self.assertEqual(len(pairs), 3)
        self.assertEqual([p["preparation_recipe"]["settings"]["max_attempts"] for p in pairs], [1, 2, 1])
        self.assertTrue(all("seed" not in p["preparation_recipe"]["settings"] for p in pairs))
        with self.assertRaisesRegex(ValueError, "differs across seeds"):
            custody.freeze_source_frames(f.scope, pairs, f.root / "drift.json")

    def test_frozen_receipt_changed_options_hash_is_not_exposure_proof(self):
        f = self.fixture()
        result = f.freeze()
        receipt = e.read_json(Path(result["receipt"]["path"]))
        receipt["jobs"][1]["envelope"]["judge_packet"]["exposures"][0]["status"] = "missing"
        receipt["jobs_sha256"] = c.object_hash(receipt["jobs"])
        altered = f.root / "altered.json"
        e.dump(altered, receipt)
        with self.assertRaises(ValueError):
            custody.validate_receipt(custody.identity(altered))


if __name__ == "__main__":
    unittest.main()
