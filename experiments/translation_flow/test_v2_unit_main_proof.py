"""Offline native-shaped main admission, original C0 replay and metadata seals."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from urllib.error import HTTPError
import unittest
from unittest.mock import patch

from . import v2_unit_main_proof as main
from . import v2_unit_custody as custody
from . import v2_unit_diagnostics as diagnostics
from . import v2_delivery as delivery
from . import v2_worker as worker
from . import v2_prepare as packing
from . import v2_trial, v2_execute
from . import test_v2_unit_custody as fixtures
from .test_v2_worker import settings, result
from .test_worker import budget

FIXED_ENGINE = {"engine": "llama.cpp", "release": "v0.6.0", "build": 11429, "commit": "d81235049",
    "cuda": "13.4", "context_size": 8192, "gpu_layers_requested": 99, "cpu_offload_allowed": False,
    "threads": 8, "threads_batch": 8, "kv_type_k": "f16", "kv_type_v": "f16", "prompt_cache_ram_mib": 8192}


class TransportFailureClient(fixtures.TraceClient):
    failed = False
    endpoint = "/completion"
    raw = b""
    http_status = None

    def fail(self, endpoint, body):
        if type(self).failed or endpoint != type(self).endpoint:
            return
        type(self).failed = True
        self.ordinal += 1
        path = self.root / "transport" / f"{self.ordinal:05d}"
        path.mkdir(parents=True)
        (path / "request.json").write_text(json.dumps({"endpoint": endpoint, "body": body}), encoding="utf-8")
        (path / "response.raw").write_bytes(type(self).raw)
        exc = (HTTPError("http://localhost", type(self).http_status, "Synthetic transport failure", None, None)
               if type(self).http_status is not None else TimeoutError("Synthetic transport failure"))
        (path / "transport.json").write_text(json.dumps({"status": type(self).http_status,
            "error": f"{type(exc).__name__}: {exc}"}), encoding="utf-8")
        self.last_exchange = str(path.resolve())
        raise exc

    def tokenize(self, prompt):
        self.fail("/tokenize", {"content": prompt, "add_special": False, "parse_special": True})
        return super().tokenize(prompt)

    def complete(self, request):
        self.fail("/completion", request)
        return super().complete(request)


class EmptyTokenizerClient(fixtures.TraceClient):
    failed = False

    def tokenize(self, prompt):
        if not type(self).failed:
            type(self).failed = True
            self.exchange("/tokenize", {"content": prompt, "add_special": False, "parse_special": True}, {"tokens": []})
            raise ValueError("Tokenizer must return nonempty integer token IDs")
        return super().tokenize(prompt)


class MainProofTests(unittest.TestCase):
    write = fixtures.RegistrationTests.write
    register = fixtures.RegistrationTests.register

    def setUp(self):
        fixtures.RegistrationTests.setUp(self)
        for window in self.windows:
            window["source_sha256"] = "d" * 64
            for index, unit in enumerate(window["units"], 1):
                start, end = unit["start_ms"], unit["end_ms"]
                def stamp(value):
                    return f"{value // 3600000:02d}:{value // 60000 % 60:02d}:{value // 1000 % 60:02d},{value % 1000:03d}"
                unit.update(index_text=str(index), time_line=f"{stamp(start)} --> {stamp(end)}", start_ms=start, end_ms=end)
        self.put(self.root / "source-manifest.json", {"windows": self.windows})
        manifest = main.identity(self.root / "source-manifest.json")
        self.source.update(manifest_sha256=manifest["sha256"])
        gate = custody._read(self.gate)
        gate["source"] = self.source
        self.gate = self.write("source-time-gate.json", gate)
        for ptr in self.cards:
            value = custody._read(ptr)
            value["source"] = self.source
            self.put(Path(ptr["path"]), value)
        self.cards = [main.identity(Path(p["path"])) for p in self.cards]
        workspace = Path(main.__file__).resolve().parents[2]
        files = [Path(v2_trial.__file__), Path(v2_execute.__file__), *[Path(p["path"]) for p in custody._dependencies()]]
        files += [workspace / "experiments/translation_flow" / name for name in (
            "v2_prepare.py", "recipes.py", "srt.py", "cli.py", "v2_source_preparation.py", "v2_scene_card.py",
            "v2_source_proposals.py", "v2_source_projection.py", "v2_id_text.py", "v2_semantic_anchors.py")]
        self.codes = [main.identity(p) for p in dict.fromkeys(files)]
        self.assertEqual(len(self.codes), 21)
        self.runtime = {"asset_sha256": "a" * 64, "template_sha256": "b" * 64, "engine": FIXED_ENGINE}
        self.fixed = {"asset_sha256": "a" * 64, "engine": "original compatible b11429 CUDA13.4",
            "context_tokens": 8192, "output_reservation_tokens": 4096, "input_margin_tokens": 64,
            "sampling": "official", "cache_prompt": True, "fresh_server_per_trial": True,
            "temperature": .7, "top_p": 1., "top_k": 0, "repeat_penalty": 1., "samplers": ["temperature"],
            "gpu_required": True, "cpu_fallback": False, "max_attempts_per_step": 2}
        cards = []
        for ptr in self.cards:
            card = custody._read(ptr)
            card.update(implementation_identity=self.codes, fixed_runtime_contract=self.fixed)
            cards.append(self.write(f"native-{card['prepare']['seed']}.json", card))
        self.cards = cards
        self.entries = [{"id": f"F5-{seed}", "seed": seed, **ptr} for seed, ptr in zip(diagnostics.SEEDS, cards, strict=True)]
        self.index = self.write("native-index.json", {"schema": "hy30-pending-v5-source-only-index-v1", "state": "frozen_not_executed", "cards": self.entries})
        self.bundle = self.write("native-bundle.json", {"schema": "hy30-pending-v5-source-only-freeze-v1", "state": "frozen_not_executed", "cards": self.entries, "index": self.index})
        gate = custody._read(self.gate)
        gate["implementation_identity"] = self.codes
        self.gate = self.write("native-gate.json", gate)
        self.registration = self.register()
        self.record = custody._read(self.registration)
        self.external = self.write("external-main.json", {"schema": custody.EXTERNAL_REGISTRATION_SCHEMA,
            "state": "frozen_before_generation", "registration": self.registration, "root_gate": self.gate,
            "registered_at_utc": "2020-01-01T00:00:00+00:00"})
        self.historical = {key: self.write(f"historical-{key}.json", {"root_approved_original_control": key})
                           for key in main.HISTORICAL_FIELDS}
        self.replay = self.write("replay.json", {"schema": main.REPLAY_SCHEMA, "state": "root_approved_closed_parser_replay",
            "verifier": main.identity(Path(main.__file__)), "parsers": custody._dependencies(),
            "historical_behavior": self.historical["behavior"]})

    def put(self, path, value, *, lines=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in value) if lines else
                        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return main.identity(path)

    def native(self, *, control=False, failure=None, retry=False, scope=None):
        role, seed = "control" if control else "candidate", 20261008
        card_ptr = self.cards[0]
        card = custody._read(card_ptr)
        if control:
            card["prepare"].update(recipe="c0", recipe_id="original-C0")
            card["implementation_identity"] = self.codes[:17]
            card_ptr = self.write("original-control-card.json", card)
        root = self.root / f"native-{role}"
        session = root / "execution/runtime-run/translation"
        label = session / card["prepare"]["recipe_id"]
        packed = deepcopy(scope or custody._read(self.record["packed"][0]))
        packed["recipe_id"] = card["prepare"]["recipe_id"]
        packed_ptr = self.put(root / "prepared/packed-mapping.json", packed)
        inputs = [b["producer_input"] for b in diagnostics._source(packed)["batches"]]
        inputs_ptr = self.put(label / "inputs.jsonl", inputs, lines=True)
        item = settings(card["prepare"]["recipe"], label=card["prepare"]["recipe_id"],
            inputs="inputs.jsonl", input_sha256=inputs_ptr["sha256"], packed_mapping_sha256=packed_ptr["sha256"],
            source_manifest_sha256=packed["source_manifest"]["sha256"], terms=[], background=[], style="neutral", review=False)
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
                native = "甲😀。 " * len(ids)
                mapped = {"segments": [{"unit_id": "u1", "source_id": key, "text": "甲😀。 "} for key in ids]}
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
        terminal = {**start, "status": "partial" if failures else "complete", "finished_at_utc": "2026-10-08T00:00:02+00:00",
            "total_flow_seconds": 2.0, "phases": {"preparation": .1, "managed_command": 1.5, "export": .3}, "runtime_exit_code": int(bool(failures))}
        terminal_ptr = self.put(root / "trial-completion.json", terminal)
        delivery.deliver(Path(packed["source_manifest"]["path"]), Path(packed_ptr["path"]), label, root / "delivery")
        if control:
            self.historical["workload_archive"] = self.write("historical-native-archive.json", {"fresh_output_audits": [
                {"seed": seed, "fresh_original_run": main.identity(label / "run.json"), "fresh_ledger": main.identity(label / "ledger.jsonl"),
                 "matched_batches": len(inputs)}]})
        entry = {"seed": seed, "role": role, "card": card_ptr, "trial_root": str(root.resolve()), "trial_completion": terminal_ptr,
            "runtime": self.runtime, "declared_snapshot_count": 17 if control else 21,
            "historical_authorities": self.historical if control else None, "scoring_derivation": None}
        authority = self.write(f"authority-{role}.json", {"schema": main.AUTHORITY_SCHEMA,
            "state": "root_approved_offline_original_authentication", "registration": self.registration,
            "external_registration": self.external, "verifier": main.identity(Path(main.__file__)),
            "diagnostic_replay": self.replay, "entries": [entry]})
        return {"root": root, "label": label, "rows": rows, "entry": entry, "authority": authority, "role": role}

    def authenticate(self, fixture, name="admission.json"):
        return main.authenticate_original_trial(authority=fixture["authority"], expected_authority_sha256=fixture["authority"]["sha256"],
            role=fixture["role"], seed=20261008, output=self.root / name)

    def modify(self, path, mutate, *, lines=False):
        value = custody._read(main.identity(path), lines=lines)
        mutate(value)
        return self.put(path, value, lines=lines)

    def test_genuine_all_stage_retries_whole_scope_and_exact20_metadata_only_callback(self):
        fixture = self.native(retry=True)
        admission = self.authenticate(fixture)
        value = custody._read(admission)
        self.assertEqual(value["scheduled_batches"], 3)
        self.assertEqual(value["attempted_batches"], 3)
        self.assertTrue(value["native_complete"])
        self.assertEqual(len(value["declared_executed_snapshots"]), 21)
        proof = main.build_main_proof(admission=admission, expected_admission_sha256=admission["sha256"],
            authority=fixture["authority"], expected_authority_sha256=fixture["authority"]["sha256"], output=self.root / "main.json")
        decoded = custody._read(proof)
        self.assertEqual(set(decoded), custody.MAIN_FIELDS)
        seal = self.write("seal.json", {"schema": main.SEAL_SCHEMA, "state": "root_reviewed_original_main_proofs",
            "verifier": main.identity(Path(main.__file__)), "authority": fixture["authority"],
            "proofs": [{"seed": 20261008, "role": "candidate", "proof": proof, "admission": admission}]})
        validator = main.make_main_validator(seal=seal, expected_seal_sha256=seal["sha256"])
        decoded_paths = []
        original_read = main._read
        def metadata_read(ptr, **kwargs):
            decoded_paths.append(ptr["path"])
            return original_read(ptr, **kwargs)
        with patch.object(custody, "validate_registered_frame", side_effect=AssertionError("No semantic decode")), \
                patch.object(custody, "_stage_material", side_effect=AssertionError("No native replay")), \
                patch.object(diagnostics, "_intake", side_effect=AssertionError("No native intake")), \
                patch.object(main, "_read", side_effect=metadata_read):
            self.assertEqual(validator(proof, seed=20261008, role="candidate", external_registration=self.external), decoded)
        forbidden = {ptr["path"] for ptr in decoded["retained"].values()} | {ptr["path"] for ptr in decoded["source_authority"].values()}
        self.assertFalse(forbidden & set(decoded_paths))
        redirected = self.write("redirected-seal.json", {"schema": main.SEAL_SCHEMA, "state": "unaccepted_replacement", "proofs": []})
        seal.update(redirected)
        self.assertEqual(validator(proof, seed=20261008, role="candidate", external_registration=self.external), decoded)
        # The existing frozen66c callback accepts the genuine factory proof.
        registered = custody.validate_registered_frame(self.registration, self.external,
            expected_registration_sha256=self.registration["sha256"], expected_external_sha256=self.external["sha256"])
        custody._main(proof, seed=20261008, role="candidate", registered=registered,
                      external_registration=self.external, validator=validator)
        raw = Path(fixture["rows"][0]["attempts"][0]["original_response"]) / "response.raw"
        raw.write_bytes(raw.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            validator(proof, seed=20261008, role="candidate", external_registration=self.external)

    def test_old_control_declared17_captured21_diagnostic9_not_historical_execution(self):
        value = custody._read(self.authenticate(self.native(control=True, retry=True)))
        self.assertEqual(len(value["declared_executed_snapshots"]), 17)
        self.assertEqual(len(value["captured_executed_snapshots"]), 21)
        self.assertEqual(len(value["approved_parser_snapshots"]), 9)
        self.assertEqual(value["historical_authorities"], self.historical)
        self.assertEqual(value["original_cost_count"], 1)
        self.assertEqual(value["new_timing_measurements"], 0)

    def test_mapping_failed_native_kept_original_partial_and_costs_not_zeroed(self):
        fixture = self.native(failure="mapping")
        value = custody._read(self.authenticate(fixture))
        self.assertFalse(value["native_complete"])
        self.assertEqual(value["generation_attempt_status"], "terminal_partial")
        self.assertEqual(value["failed_batches"][0]["status"], "mapping_unjudgeable")
        self.assertTrue(fixture["rows"][0]["native_unit_translations"])
        self.assertFalse((fixture["root"] / "delivery/scenes/scene/chn.srt").exists())

    def test_runtime_cache_source_snapshot_and_terminal_cost_tamper_rejected(self):
        cases = {
            "cache": ("execution/runtime-run/translation/worker-completion.json", lambda d: d["cache_reset"].update(first_response_cache_n=1)),
            "cost": ("execution/runtime-run/translation/worker-completion.json", lambda d: d["budget"].update(translation_calls=0)),
            "residency": ("execution/runtime-run/translation/session.json", lambda d: d["identity"]["engine"]["residency"].update(layers_not_offloaded=1)),
            "trial": ("trial-completion.json", lambda d: d.update(status="started")),
            "stage": ("execution/runtime-run/translation/session-plan.json", lambda d: d.update(stage="confirmation"))}
        fixture = self.native()
        for name, (relative, mutate) in cases.items():
            path = fixture["root"] / relative
            old = path.read_bytes()
            self.modify(path, mutate)
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.authenticate(fixture, f"reject-{name}.json")
            path.write_bytes(old)
        file = next((fixture["root"] / "execution/runtime-run/translation/source").rglob("*.py"))
        old = file.read_bytes()
        file.write_bytes(old + b"\n")
        with self.assertRaisesRegex(ValueError, "captured"):
            self.authenticate(fixture)

    def test_actual_retry_request_grammar_and_accepted_native_span_tamper_rejected(self):
        fixture = self.native(retry=True)
        for index in (0, len(fixture["rows"][0]["attempts"]) - 1):
            request = Path(fixture["rows"][0]["attempts"][index]["original_response"]) / "request.json"
            old = request.read_bytes()
            self.modify(request, lambda d: d["body"].update(n_predict=3072))
            with self.assertRaises(ValueError):
                self.authenticate(fixture)
            request.write_bytes(old)
        srt = fixture["root"] / "delivery/scenes/scene/chn.srt"
        srt.write_bytes(srt.read_bytes().replace(b" --> ", b" ---> ", 1))
        with self.assertRaisesRegex(ValueError, "SRT"):
            self.authenticate(fixture)

    def test_extra_transport_missing_context_batch_no_complete_promotion(self):
        fixture = self.native()
        first = Path(fixture["rows"][0]["attempts"][0]["original_response"])
        shutil.copytree(first, first.parent / "extra-call")
        with self.assertRaisesRegex(ValueError, "transport"):
            self.authenticate(fixture)

    def test_external_pins_wrong_seed_source_frame_chronology_and_unknown_not_zero(self):
        fixture = self.native()
        with self.assertRaisesRegex(ValueError, "independent"):
            main.authenticate_original_trial(authority=fixture["authority"], expected_authority_sha256="0" * 64,
                role="candidate", seed=20261008, output=self.root / "wrong.json")
        with self.assertRaisesRegex(ValueError, "absent"):
            main.authenticate_original_trial(authority=fixture["authority"], expected_authority_sha256=fixture["authority"]["sha256"],
                role="candidate", seed=20261009, output=self.root / "wrong.json")
        path = fixture["root"] / "execution/runtime-run/translation/worker-completion.json"
        self.modify(path, lambda d: d["cache_reset"].update(verified=None))
        with self.assertRaisesRegex(ValueError, "cache"):
            self.authenticate(fixture)

    def test_planning_and_native_failure_cannot_manufacture_intact_native_or_complete(self):
        fixture = self.native(failure="planning")
        value = custody._read(self.authenticate(fixture))
        self.assertFalse(value["native_complete"])
        self.assertEqual(value["failed_batches"][0]["failure_stage"], "source-planning")
        self.assertNotIn("native_unit_translations", fixture["rows"][0])

    def test_preflight_setup_zero_dispatch_tokens_do_not_duplicate_completion_cost(self):
        fixture = self.native(failure="preflight")
        admitted = custody._read(self.authenticate(fixture))
        self.assertFalse(admitted["native_complete"])
        self.assertEqual(len(admitted["scheduled_tail"]), 2)
        first = fixture["rows"][0]
        self.assertEqual(first["status"], "setup_failed")
        self.assertFalse(first["attempts"][0]["completion_dispatched"])
        costs = custody._read(main.identity(fixture["root"] / "delivery/costs.json"))
        dispatched = [a for r in fixture["rows"] for a in r["attempts"] if a["completion_dispatched"]]
        self.assertEqual(costs["dispatched_completions"], len(dispatched))
        self.assertEqual(costs["input_tokens"]["measured_sum"], sum(a["input_tokens"] for a in dispatched))

    def test_whole_undispatched_original_setup_is_not_relabelled_terminal_partial(self):
        fixture = self.native(failure="all-preflight")
        admitted = custody._read(self.authenticate(fixture))
        self.assertEqual(admitted["generation_attempt_status"], "setup_failed")
        self.assertFalse(admitted["native_complete"])
        self.assertFalse(any(a["completion_dispatched"] for r in fixture["rows"] for a in r["attempts"]))

    def test_factory_rejects_original_tree_destination_before_any_write(self):
        fixture = self.native()
        admitted = self.authenticate(fixture)
        destination = fixture["root"] / "forbidden-main.json"
        with self.assertRaisesRegex(ValueError, "immutable"):
            main.build_main_proof(admission=admitted, expected_admission_sha256=admitted["sha256"], authority=fixture["authority"],
                expected_authority_sha256=fixture["authority"]["sha256"], output=destination)
        self.assertFalse(destination.exists())
        self.assertFalse(destination.with_name("forbidden-main-cost-authority.json").exists())

    def test_real_empty_timeout_and_nonjson_http_retry_shapes_preserve_unknown_cost(self):
        for index, (endpoint, raw, status) in enumerate((("/tokenize", b"", None), ("/completion", b"upstream unavailable", 503))):
            with self.subTest(endpoint=endpoint):
                TransportFailureClient.failed = False
                TransportFailureClient.endpoint = endpoint
                TransportFailureClient.raw = raw
                TransportFailureClient.http_status = status
                with patch.object(fixtures, "TraceClient", TransportFailureClient):
                    fixture = self.native(control=index == 1)
                admitted = custody._read(self.authenticate(fixture, f"transport-{index}.json"))
                self.assertTrue(admitted["native_complete"])
                self.assertEqual(fixture["rows"][0]["attempts"][0]["status"], "failed")
                if endpoint == "/completion":
                    costs = custody._read(main.identity(fixture["root"] / "delivery/costs.json"))
                    self.assertEqual(costs["output_tokens"]["unknown_records"], 1)
                    self.assertFalse(costs["output_tokens"]["complete"])

    def test_original_cache_unknown_failure_is_authentic_partial_never_empty_cache_success(self):
        fixture = self.native(failure="cache")
        value = custody._read(self.authenticate(fixture))
        self.assertFalse(value["native_complete"])
        self.assertEqual(value["generation_attempt_status"], "terminal_partial")
        self.assertEqual(fixture["rows"][0]["error_kind"], "cache")

    def test_original_inventory_rejects_linked_root_without_traversal(self):
        fixture = self.native()
        original = main._inventory
        with patch.object(Path, "is_junction", return_value=True):
            with self.assertRaisesRegex(ValueError, "linked"):
                original(fixture["root"])

    def test_actual_engine_props_and_command_artifacts_are_required_and_bound(self):
        fixture = self.native()
        for relative, mutate in (("execution/runtime-run/runtime/engine.json", lambda d: d.update(server_pid=1)),
                                 ("execution/runtime-run/runtime/props.json", lambda d: d.update(total_slots=2)),
                                 ("execution/command.json", lambda d: d["command"].__setitem__(-1, "0"))):
            path = fixture["root"] / relative
            previous = path.read_bytes()
            self.modify(path, mutate)
            with self.assertRaises(ValueError):
                self.authenticate(fixture)
            path.write_bytes(previous)

    def test_genuine_empty_tokenizer_json_failure_retries_without_dispatched_cost(self):
        EmptyTokenizerClient.failed = False
        with patch.object(fixtures, "TraceClient", EmptyTokenizerClient):
            fixture = self.native()
        value = custody._read(self.authenticate(fixture))
        self.assertTrue(value["native_complete"])
        self.assertFalse(fixture["rows"][0]["attempts"][0]["completion_dispatched"])
        self.assertNotIn("input_tokens", fixture["rows"][0]["attempts"][0])

    def test_accepted_response_missing_actual_effective_settings_is_not_complete_admission(self):
        fixture = self.native()
        for field in (None, "temperature"):
            first = fixture["rows"][0]["attempts"][0]
            raw = Path(first["original_response"]) / "response.raw"
            old = raw.read_bytes()
            response = custody._read(main.identity(raw))
            if field is None:
                response.pop("generation_settings")
            else:
                response["generation_settings"].pop(field)
            first["response"] = response
            first["effective_settings"] = main.effective_settings(response, first["request"])
            self.put(raw, response)
            self.put(fixture["label"] / "ledger.jsonl", fixture["rows"], lines=True)
            self.put(fixture["label"] / f"window-{fixture['rows'][0]['window_id']}.json", fixture["rows"][0])
            with self.assertRaisesRegex(ValueError, "effective"):
                main._all_attempts(fixture["rows"][0], diagnostics._source(custody._read(self.record["packed"][0]))["batches"][0]["producer_input"],
                                   custody._read(main.identity(fixture["label"] / "run.json"))["settings"], fixture["label"].parent)
            raw.write_bytes(old)

    def test_duplicate_retry_tokenizer_and_completion_exchanges_rejected_before_cost_counting(self):
        fixture = self.native(failure="mapping")
        attempted = [a for row in fixture["rows"] for a in row["attempts"]]
        selected = [a for a in fixture["rows"][0]["attempts"] if a["stage"] == "semantic-remapping"]
        for key in ("tokenize_exchange", "original_response"):
            previous = selected[1][key]
            removed = Path(previous).resolve()
            backup = (self.root / f"unused-{key}").resolve()
            if not removed.is_relative_to(self.root.resolve()) or not backup.is_relative_to(self.root.resolve()):
                raise ValueError("Synthetic move must remain in its explicit temporary root")
            removed.rename(backup)
            selected[1][key] = selected[0][key]
            with self.assertRaisesRegex(ValueError, "more than once"):
                main._transport_inventory(fixture["label"].parent, attempted)
            selected[1][key] = previous
            backup.rename(removed)

    def test_full29_3606_734_main_not_selected84_and_all3_frame_unavailable_slots(self):
        scenes, windows = [], []
        sizes = [127] * 6 + [128] * 3 + [123] * 20
        for ordinal, size in enumerate(sizes):
            sid = f"synthetic-scene-{ordinal:02d}"
            ids = [f"{sid}-J{i:05d}" for i in range(size)]
            scene = {"id": sid, "scene_id": sid, "source_language": "ja", "target_language": "zh-Hans",
                "translate_ids": ids, "context": [{"id": key, "text": f"合成{i}。", "start": i, "end": i + .5} for i, key in enumerate(ids)]}
            scenes.append(scene)
            positions = [5 if ordinal < 12 else 7] + ([57] if ordinal < 19 else [])
            units = [{"id": key, "ja_srt_index": i + 1, "index_text": str(i + 1), "start_ms": i * 1000,
                "end_ms": i * 1000 + 500, "time_line": f"00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},500",
                "source_events": {"ja": [{"Dialogue序号": i + 1}], "zh": []}} for i, key in enumerate(ids)]
            for position in positions:
                scored = ids[position:position + 5]
                windows.append({**deepcopy(self.windows[0]), "id": f"window-{len(windows):03d}", "scene_id": sid,
                    "scored_ids": scored, "units": [{**u, "score": u["id"] in scored} for u in units]})
        self.put(self.root / "full-scenes.jsonl", scenes, lines=True)
        manifest = self.write("full-source-manifest.json", {"windows": windows})
        source = {"manifest": manifest["path"], "manifest_sha256": manifest["sha256"],
            "scenes": str((self.root / "full-scenes.jsonl").resolve()), "scenes_sha256": main.identity(self.root / "full-scenes.jsonl")["sha256"]}
        cards = []
        for ptr in self.cards:
            card = custody._read(ptr)
            card["source"] = source
            card["prepare"].update(target_size=5, selected_scene_ids=[s["id"] for s in scenes])
            cards.append(self.write(f"full-card-{card['prepare']['seed']}.json", card))
        self.cards = cards
        entries = [{"id": f"F5-{seed}", "seed": seed, **ptr} for seed, ptr in zip(diagnostics.SEEDS, cards, strict=True)]
        self.index = self.write("full-index.json", {"schema": "hy30-pending-v5-source-only-index-v1", "state": "frozen_not_executed", "cards": entries})
        self.bundle = self.write("full-bundle.json", {"schema": "hy30-pending-v5-source-only-freeze-v1", "state": "frozen_not_executed", "cards": entries, "index": self.index})
        gate = custody._read(self.gate)
        gate["source"] = source
        gate["controls"]["screen-a"]["cohort"].update(scenes=29, source_cues=3606, score_windows=48, score_cues=240, batches_per_seed=734)
        self.gate = self.write("full-gate.json", gate)
        self.registration = self.register(output=self.root / "full-registered")
        self.record = custody._read(self.registration)
        self.external = self.write("full-external.json", {"schema": custody.EXTERNAL_REGISTRATION_SCHEMA,
            "state": "frozen_before_generation", "registration": self.registration, "root_gate": self.gate,
            "registered_at_utc": "2020-01-01T00:00:00+00:00"})
        self.assertEqual(self.record["scope"]["selected_batches_per_seed"], 84)
        self.assertEqual(self.record["scope"]["expected_slots"], 252)
        fixture = self.native()
        admitted = custody._read(self.authenticate(fixture))
        self.assertEqual(admitted["scheduled_batches"], 734)
        self.assertEqual(admitted["attempted_batches"], 734)
        self.assertEqual(admitted["actual_source_scope"]["source_cues"], 3606)
        self.assertEqual(len(admitted["actual_source_scope"]["scene_ids"]), 29)
        self.assertTrue(admitted["native_complete"])
        # Removing a nonselected/context-only producer cannot pass main intake.
        frame = custody._read(self.record["frame"])
        selected = {b["batch_id"] for b in frame["batches"]}
        missing = next(r["window_id"] for r in fixture["rows"] if r["window_id"] not in selected)
        self.modify(fixture["label"] / "ledger.jsonl", lambda rows: rows.__setitem__(slice(None), [r for r in rows if r["window_id"] != missing]), lines=True)
        with self.assertRaisesRegex(ValueError, "Full ordered"):
            self.authenticate(fixture, "partial84-is-not-main.json")


if __name__ == "__main__":
    unittest.main()
