"""Synthetic native-format timing trials; no inference or confirmation data."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, read_json, sha
from .v2_delivery import deliver
from .v2_reproject import identity
from .v2_prepare import identity as object_hash
from .v2_statistics import student_t_critical
from .v2_timing import (CONFIDENCE, audit_native_metadata, read_metadata_fields, create_exploratory_plan, execute_plan, fixed_n,
                        freeze_confirmation_plan, summarize_timing, _native_leg, load_policy)


class TimingTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[2] / ".local/translation-v2-timing-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.manifest, self.scenes = self.root / "source-manifest.json", self.root / "scenes.jsonl"
        self.scene_rows, self.windows = [], []
        for number in range(34):
            sid = f"scene-{number:02d}"
            count = 126 if number < 33 else 139
            ids = [f"{sid}-{cue:03d}" for cue in range(count)]
            context = [{"id": uid, "text": f"源{cue}", "start": cue * 2., "end": cue * 2. + 1.}
                       for cue, uid in enumerate(ids)]
            units = [{"id": uid, "ja_srt_index": cue + 1, "index_text": str(cue + 1),
                      "time_line": f"00:{cue * 2 // 60:02d}:{cue * 2 % 60:02d},000 --> 00:{(cue * 2 + 1) // 60:02d}:{(cue * 2 + 1) % 60:02d},000",
                      "start_ms": cue * 2000, "end_ms": cue * 2000 + 1000, "score": cue < 5}
                     for cue, uid in enumerate(ids)]
            self.scene_rows.append({"id": sid, "scene_id": sid, "source_language": "ja", "target_language": "zh-Hans",
                                    "context": context, "translate_ids": ids})
            self.windows.append({"id": f"score-{number}", "scene_id": sid, "work": "synthetic",
                                 "scored_ids": ids[:5], "source_sha256": "a" * 64, "units": units})
        dump(self.manifest, {"windows": self.windows})
        dump_jsonl(self.scenes, self.scene_rows)
        dump(self.root / "freeze-manifest.json", {"role": "screening", "state": "source_frozen_reference_qualified",
             "artifacts": [{"path": p.name, "sha256": sha(p)} for p in (self.manifest, self.scenes)]})
        self.policy, self.interpretation = self.root / "policy.json", self.root / "interpretation.json"
        dump(self.policy, {"schema_version": "hy30-flow-v2-decision-policy-v2",
             "multiplicity": {"family_size": 9, "individual_two_sided_confidence": CONFIDENCE},
             "baseline": {"model_sha256": "b" * 64, "seeds": [20261008, 20261009, 20261010]},
             "freeze_provenance": {"source_workload": {"scenes": 34, "source_cues": 4297,
                                     "manifest_sha256": sha(self.manifest), "scenes_sha256": sha(self.scenes)}},
             "timing": {"interval_confidence": CONFIDENCE, "target_half_width_seconds": 15,
                        "practically_meaningful_savings_seconds": 60, "exploratory_minimum_completed_pairs": 4,
                        "independent_confirmation_minimum_pairs": 4, "exploratory_initial_order": ["AB", "BA", "AB", "BA"],
                        "starting_cache_state": "identical_empty_new_session", "reused_outputs_or_same_prompt_replay_eligible_for_timing": False}})
        dump(self.interpretation, {"schema_version": "hy30-flow-v2-timing-interpretation-v1", "policy_sha256": sha(self.policy),
                                  "unchanged_decision_rules": {"direction_based_early_stopping": False}})
        code = self.root / "frozen-code.py"
        code.write_text("# Synthetic frozen implementation\n", encoding="utf-8")
        self.code = identity(code)
        self.cards = {}
        for side, recipe in (("A", "c0"), ("B", "joint-json")):
            path = self.root / f"card-{side}.json"
            dump(path, {"schema": "hy30-flow-trial-card-v2", "source": {
                "manifest": str(self.manifest), "manifest_sha256": sha(self.manifest),
                "scenes": str(self.scenes), "scenes_sha256": sha(self.scenes)},
                "prepare": {"stage": "screening", "split": "screening", "recipe_id": f"recipe-{side}",
                            "recipe": recipe, "seed": 20261008},
                "decision_policy": identity(self.policy), "implementation_identity": [self.code]})
            self.cards[side] = {"20261008": identity(path)}
        self.plan = self.root / "pilot-plan.json"
        create_exploratory_plan(self.policy, self.interpretation, self.cards, [20261008] * 4,
                                {"sampler": "synthetic-fixed", "quiet": "prefrozen"}, self.plan, prefix="pilot")
        plan = read_json(self.plan)
        plan["created_at_utc"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        dump(self.plan, plan)

    def native_leg(self, directory, card_path, seconds, started, *, retry=False, auxiliary_mutation=None):
        card = read_json(card_path)
        label = card["prepare"]["recipe_id"]
        auxiliary_report = None
        if 'source_preparation' in card:
            aux_root = directory / 'source-preparation'
            aux_translation = aux_root / 'runtime-run/translation'
            auxiliary_plan = read_json(Path(card['source_preparation']['plan']))
            cache = {'method': 'fresh-managed-server', 'server_pid': 4321, 'verified': True,
                     'first_response_checked': True, 'first_response_cache_n': 0}
            identity_fields = {'engine': {'server_pid': 4321, 'model_sha256': 'b' * 64}}
            options_path = aux_translation / 'preparation-options.json'
            aux_rows = []
            for number, scene in enumerate(self.scene_rows):
                trace = aux_translation / 'transport' / str(number)
                request = {'prompt': [number], 'seed': 20261008}
                response = {'timings': {'cache_n': 0 if number == 0 else 5}}
                dump(trace / 'request.json', {'endpoint': '/completion', 'body': request})
                dump(trace / 'response.raw', response)
                aux_rows.append({'scene_id': scene['id'], 'status': 'prepared', 'attempts': [{'completion_dispatched': True,
                                 'status': 'accepted', 'stage': 'source-background',
                                 'original_response': str(trace), 'request': request, 'response': response}]})
            dump_jsonl(aux_translation / 'ledger.jsonl', aux_rows)
            dump(options_path, {'schema': 'hy30-source-preparation-options-v3', 'complete': True,
                'source': auxiliary_plan['source'], 'scene_ids': auxiliary_plan['scene_ids'],
                'settings': auxiliary_plan['settings'], 'mode': auxiliary_plan['mode'], 'stage': auxiliary_plan['stage'],
                'protocol': auxiliary_plan['protocol'], 'session_plan_sha256': card['source_preparation']['sha256'],
                'cache_reset': cache, 'identity': identity_fields, 'code_sha256': {'fixture': self.code['sha256']},
                'cost_artifacts': {'ledger.jsonl': sha(aux_translation / 'ledger.jsonl')},
                'preparations': [{'scene_id': row['id'], 'text': 'Synthetic auxiliary value'} for row in self.scene_rows],
                'raw_responses': [{'scene_id': row['id'], 'content': 'Synthetic parser input'} for row in self.scene_rows]})
            dump(aux_translation / 'worker-completion.json', {'complete': True, 'failures': 0,
                 'artifact': identity(options_path), 'cache_reset': cache})
            dump(aux_translation / 'session.json', {'plan_sha256': card['source_preparation']['sha256'],
                'expected_scene_ids': auxiliary_plan['scene_ids'], 'identity': identity_fields,
                'code_sha256': {'fixture': self.code['sha256']}})
            dump(aux_root / 'runtime-run/runtime/runtime-final.json', {'session_plan_sha256': card['source_preparation']['sha256'],
                'server_pid': 4321, 'server_process_exited': True, 'worker_process_exited': True, 'translation_exit_code': 0})
            dump(aux_root / 'command-completion.json', {'returncode': 0, 'command_seconds': 20,
                 'plan_sha256': card['source_preparation']['sha256'], 'code_sha256': self.code['sha256']})
            auxiliary_report = {'runtime_exit_code': 0, 'plan_sha256': card['source_preparation']['sha256'],
                                'artifact': identity(options_path), 'cost': {'command': identity(aux_root / 'command-completion.json'),
                                'ledger': identity(aux_translation / 'ledger.jsonl'), 'command_seconds': 20,
                                'scene_records': 34, 'attempts': 34, 'translation_calls': 34}}
            if auxiliary_mutation is not None:
                auxiliary_mutation(aux_root)
                auxiliary_report['artifact'] = identity(options_path)
                worker = read_json(aux_translation / 'worker-completion.json')
                worker['artifact'] = auxiliary_report['artifact']
                dump(aux_translation / 'worker-completion.json', worker)
        prepared = directory / "prepared"
        run = directory / "execution/runtime-run/translation" / label
        batches = [{"id": f"batch-{n}", "scene_id": scene["id"], "target_ids": scene["translate_ids"], "readonly_ids": []}
                   for n, scene in enumerate(self.scene_rows)]
        packed = {"schema": "hy30-flow-packed-v2", "scene_ids": [row["id"] for row in self.scene_rows],
                  "scenes": self.scene_rows, "windows": self.windows, "batches": batches,
                  "source_manifest": identity(self.manifest), "source_scenes": identity(self.scenes),
                  "recipe_id": label, "seed": 20261008}
        mapping = prepared / "packed-mapping.json"
        dump(mapping, packed)
        inputs = [{"id": batch["id"], "source_language": "ja", "target_language": "zh-Hans",
                   "context": [{"id": cue["id"], "text": cue["text"]} for cue in scene["context"]],
                   "translate_ids": batch["target_ids"]} for batch, scene in zip(batches, self.scene_rows)]
        dump_jsonl(run / "inputs.jsonl", inputs)
        item = {"label": label, "recipe": card["prepare"]["recipe"], "seed": 20261008,
                "input_sha256": sha(run / "inputs.jsonl"), "sampling": "official", "cache_prompt": True, "n_predict": 4096}
        if auxiliary_report:
            item['source_preparation'] = {'artifact': auxiliary_report['artifact']}
        session_plan = prepared / "session-plan.json"
        dump(session_plan, {"stage": "screening", "experiment_identity": {"split": "screening", "seed": 20261008,
             "source_manifest_sha256": sha(self.manifest), "source_order_sha256": object_hash([batch['id'] for batch in batches])}, "workloads": [item]})
        dump(run / "run.json", {"lane": "P-flow", "candidate": "apex", "settings": item,
             **({'source_preparation': item['source_preparation']} if auxiliary_report else {}),
             "expected_window_ids": [b["id"] for b in batches], "input_sha256": item["input_sha256"],
             "source_manifest_sha256": sha(self.manifest), "packed_mapping_sha256": sha(mapping),
             "session_plan_sha256": sha(session_plan), "code_sha256": {"fixture": self.code["sha256"]}})
        results, ledger = [], []
        for number, batch in enumerate(batches):
            values = {uid: f"译{uid}" for uid in batch["target_ids"]}
            attempts = []
            for index in range(2 if retry and number == 0 else 1):
                request = {"prompt": [number, 2, 3], "seed": 20261008}
                response = {"content": json.dumps({"translations": values}, ensure_ascii=False),
                            "timings": {"cache_n": 0 if number == 0 and index == 0 else 5}, "tokens_predicted": 5}
                trace = run / "transport" / f"{number}-{index}"
                dump(trace / "request.json", {"endpoint": "/completion", "body": request})
                dump(trace / "response.raw", response)
                dump(trace / "transport.json", {"status": 200})
                attempts.append({"stage": "translation", "status": "failed" if index == 0 and retry and number == 0 else "accepted",
                                 "completion_dispatched": True, "request": request, "response": response, "original_response": str(trace),
                                 "input_tokens": 10, "elapsed_seconds": 1})
            results.append({"id": batch["id"], "translations": values, "status": "delivered", "elapsed_seconds": 3})
            ledger.append({"window_id": batch["id"], "translations": values, "status": "delivered", "elapsed_seconds": 3,
                           "generation_seconds": 2, "auxiliary_seconds": 1, "attempts": attempts})
        dump_jsonl(run / "results.jsonl", results)
        dump_jsonl(run / "ledger.jsonl", ledger)
        cache = {"method": "fresh-managed-server", "server_pid": 1234, "verified": True,
                 "first_response_checked": True, "first_response_cache_n": 0}
        dump(run / "completion.json", {"reused_windows": 0, "remaining_window_ids": [], "failures": 0, "cache_reset": cache})
        dump(run.parent / "session.json", {"plan_sha256": sha(session_plan), "performance_valid_for_fresh_flow": True,
             "identity": {"engine": {"server_pid": 1234, "model_sha256": "b" * 64}}, "code_sha256": {"fixture": self.code["sha256"]}})
        dump(run.parent / "worker-completion.json", {"performance_valid_for_fresh_flow": True, "complete": True, "reused_windows": 0})
        dump(directory / "execution/command-completion.json", {"returncode": 0, "plan_sha256": sha(session_plan),
                 "command_seconds": seconds - (70 if auxiliary_report else 30), "code_sha256": self.code["sha256"]})
        dump(directory / "execution/runtime-run/runtime/runtime-final.json", {"server_pid": 1234,
             "translation_exit_code": 0, "server_process_exited": True, "worker_process_exited": True, "session_plan_sha256": sha(session_plan)})
        deliver(self.manifest, mapping, run, directory / "delivery")
        dump(directory / "trial-completion.json", {"schema": "hy30-flow-trial-v2", "card": card,
             "card_path": str(card_path), "card_sha256": sha(card_path), "code_sha256": self.code["sha256"],
             "started_at_utc": started.isoformat(), "finished_at_utc": (started + timedelta(seconds=seconds)).isoformat(),
             "status": "complete", "total_flow_seconds": seconds,
             **({'source_preparation': auxiliary_report} if auxiliary_report else {}),
             "phases": {"preparation": 10, "managed_command": seconds - (60 if auxiliary_report else 20), "export": 10,
                         **({'source_preparation': 40} if auxiliary_report else {})},
             "runtime_exit_code": 0, "expected_scene_ids": packed["scene_ids"], "expected_scenes": 34, "complete_scenes": 34,
             "missing_scene_ids": [], "unexpected_scene_ids": [], "duplicate_scene_ids": []})
        return identity(directory / "trial-completion.json")

    def receipt(self, plan_path, *, savings=(100, 100, 100, 100), retry=False):
        plan = read_json(plan_path)
        phase = plan["phase"]
        started = datetime.now(timezone.utc) + timedelta(days=1 if phase == "confirmation" else -5)
        rows = []
        for number, pair in enumerate(plan["pairs"]):
            actual = {"pair_id": pair["pair_id"], "legs": {}}
            for side in pair["order"]:
                spec = pair["legs"][side]
                pointer = self.native_leg(self.root / phase / spec["measurement_id"], Path(spec["card"]["path"]),
                                          1000 if side == "A" else 1000 - savings[number], started, retry=retry)
                started += timedelta(hours=1)
                native = _native_leg(pointer, self.root, spec, pair, plan, load_policy(self.policy, self.interpretation))
                actual["legs"][side] = {"measurement_id": spec["measurement_id"], "trial": pointer,
                                         "returncode": 0,
                                         "native_artifacts": native["artifacts"],
                                         "conditions": {"policy_sha256": plan["conditions_sha256"], "state": "verified"}}
            rows.append(actual)
        path = self.root / f"{phase}-receipt.json"
        dump(path, {"schema": "hy30-flow-policy-timing-v1", "plan": identity(plan_path), "pairs": rows,
                    "started_at_utc": (started - timedelta(hours=8)).isoformat(), "finished_at_utc": started.isoformat()})
        return path

    def test_exact_even_n_minimality_and_zero_variance(self):
        self.assertEqual(fixed_n(0), 4)
        for sd in (5, 10, 25, 80):
            n = fixed_n(sd)
            self.assertEqual(n % 2, 0)
            self.assertGreaterEqual(n, 4)
            self.assertLessEqual(student_t_critical(CONFIDENCE, n - 1) * sd / n ** .5, 15)
            if n > 4:
                self.assertGreater(student_t_critical(CONFIDENCE, n - 3) * sd / (n - 2) ** .5, 15)

    def test_native_v4_crossseed_card_labels_lineage_and_complete_execution(self):
        cards = {side: {} for side in ('A', 'B')}
        for side in cards:
            template = read_json(Path(self.cards[side]['20261008']['path']))
            for seed in (20261008, 20261009, 20261010):
                card = deepcopy(template)
                label = f'{side}-full96-seed{seed}'
                card.update(id=label, family='C0' if side == 'A' else 'F1', role='baseline' if side == 'A' else 'candidate',
                            candidate_group=side, hypothesis=f'Synthetic prose for {seed}',
                            source_freeze=identity(self.root / 'freeze-manifest.json'),
                            fixed_runtime_contract={'context_tokens': 8192, 'output_reservation_tokens': 4096,
                                'temperature': .7, 'sampling': 'official', 'cache_prompt': True,
                                'fresh_server_per_trial': True, 'max_attempts_per_step': 2},
                            quality_scope={'windows': 96, 'seeds_for_candidate_decision': [20261008, 20261009, 20261010]},
                            source_estimate={'scenes': 34, 'source_cues': 4297},
                            decision_contract={'fixed_family': 9}, baseline_connection={'identity': 'synthetic-C0'},
                            frozen_origin={'bundle': 'synthetic-v4'}, preregistered_next_question='Synthetic question',
                            scope_expansion={'from': 29, 'to': 34},
                            derivation={'parent_card': {'path': f'historical-{seed}.json', 'sha256': str(seed) * 8}},
                            control_reuse={'baseline_universal_evaluation_root': f'historical-quality-{seed}',
                                           'no_new_control_generation': True})
                card['prepare'].update(seed=seed, recipe_id=label, split='screening', stage='screening',
                    target_size=5 if side == 'A' else 10, context_before=1, context_after=1, token_target=None,
                    token_counts_path=None, measure_source_tokens=None, common_context=False, offset=0,
                    selected_scene_ids=[row['id'] for row in self.scene_rows],
                    options={'terms': [], 'background': [], 'style': 'neutral', 'review': False})
                if seed == 20261010:
                    card['prepare']['selected_scene_ids'] = None
                path = self.root / f'{label}.json'
                dump(path, card)
                cards[side][str(seed)] = identity(path)
        seeds = [20261008, 20261009, 20261010, 20261008]
        plan = create_exploratory_plan(self.policy, self.interpretation, cards, seeds, {'quiet': 'locked'},
                                      self.root / 'v4-plan.json', prefix='v4')
        self.assertEqual([pair['seed'] for pair in plan['pairs']], seeds)
        self.assertEqual(plan['pairs'][1]['legs']['B']['card'], cards['B']['20261009'])
        original = read_json(Path(cards['B']['20261009']['path']))
        mutations = [('context', lambda c: c['prepare'].update(context_after=2)),
                     ('options', lambda c: c['prepare']['options'].update(style='formal')),
                     ('sampling', lambda c: c['fixed_runtime_contract'].update(temperature=.8)),
                     ('budget', lambda c: c.update(dispatch_budget={'calls': 1})),
                     ('source-setting', lambda c: c['source'].update(input_protocol='changed')),
                     ('subset', lambda c: c['prepare'].update(selected_scene_ids=plan['source_order'][:-1])),
                     ('reorder', lambda c: c['prepare'].update(selected_scene_ids=list(reversed(plan['source_order'])))),
                     ('identifier', lambda c: c.update(seed=20261008)),
                     ('code', lambda c: c['implementation_identity'].append(identity(self.policy)))]
        for name, mutate in mutations:
            with self.subTest(name=name):
                altered = deepcopy(original)
                mutate(altered)
                path = self.root / f'changed-{name}.json'
                dump(path, altered)
                changed = deepcopy(cards)
                changed['B']['20261009'] = identity(path)
                with self.assertRaises(ValueError):
                    create_exploratory_plan(self.policy, self.interpretation, changed, seeds, {'quiet': 'locked'},
                                            self.root / f'rejected-{name}.json', prefix=name)

    def test_metadata_audit_historical_layout_never_reads_outputs_or_grants_eligibility(self):
        root = self.root / 'historical'
        prepared = self.root / 'historical-prepared'
        translation = root / 'runtime-run/translation'
        run = translation / 'native-C0'
        dump(prepared / 'session-plan.json', {'workloads': [{'label': 'native-C0'}]})
        dump(root / 'command-completion.json', {'schema': 'hy30-flow-command-v2', 'returncode': 0,
             'command_seconds': 500, 'plan_sha256': 'a' * 64, 'code_sha256': self.code['sha256']})
        code = {'fixture.py': self.code['sha256'], 'undeclared.py': 'f' * 64}
        dump(translation / 'session.json', {'plan_sha256': 'a' * 64, 'performance_valid_for_fresh_flow': True,
             'identity': {}, 'code_sha256': code})
        dump(translation / 'worker-completion.json', {'complete': True, 'reused_windows': 0,
                                                     'performance_valid_for_fresh_flow': True})
        dump(run / 'run.json', {'expected_window_ids': ['b1', 'b2'], 'settings': {},
                               'session_plan_sha256': 'a' * 64, 'code_sha256': code})
        dump(run / 'completion.json', {'remaining_window_ids': [], 'failures': 0, 'reused_windows': 0,
                                      'cache_reset': {'verified': True, 'first_response_cache_n': 0}})
        dump(root / 'runtime-run/runtime/runtime-final.json', {'session_plan_sha256': 'a' * 64,
             'translation_exit_code': 0, 'server_process_exited': True, 'worker_process_exited': True})
        for name in ('results.jsonl', 'ledger.jsonl'):
            (run / name).write_text('Deliberately invalid: must never be opened', encoding='utf-8')
        report = audit_native_metadata(root, prepared, implementation_card=Path(self.cards['A']['20261008']['path']))
        self.assertTrue(report['diagnostic_only'])
        self.assertFalse(report['formal_eligible'])
        self.assertIn('total_flow_seconds', report['missing_formal_fields']['trial'])
        self.assertEqual(report['observed_metadata']['expected_batches'], 2)
        self.assertEqual(report['code_identity_coverage']['run']['undeclared_files'], ['undeclared.py'])
        self.assertEqual(report['field_types']['completion']['cache_reset'], 'dict')
        self.assertEqual(report['additional_generation_calls'], 0)

    def test_pilot_fresh_confirmation_bound_confidence_and_retry_cost(self):
        receipt = self.receipt(self.plan, retry=True)
        pilot = summarize_timing(self.plan, receipt)
        self.assertEqual(pilot['status'], 'pilot_ready')
        self.assertEqual(pilot['required_fixed_n'], 4)
        self.assertEqual(pilot['measurements'][0]['legs']['A']['dispatched_calls'], 35)
        self.assertEqual(pilot['statistics']['exploratory']['interval']['confidence'], CONFIDENCE)
        confirm = self.root / 'confirmation-plan.json'
        freeze_confirmation_plan(self.plan, receipt, confirm, [20261008] * 4, prefix='confirm')
        measured = self.receipt(confirm)
        unresolved = summarize_timing(confirm, measured)
        self.assertEqual(unresolved['status'], 'evidence_insufficient')
        diagnostics = self.root / 'diagnostics.json'
        dump(diagnostics, {'plan_sha256': sha(confirm), 'receipt_sha256': sha(measured),
                           'independence': 'resolved', 'normal_approximation': 'resolved', 'order_and_drift': 'resolved'})
        result = summarize_timing(confirm, measured, diagnostics=identity(diagnostics))
        self.assertEqual(result['status'], 'timing_thresholds_met')
        self.assertEqual(result['statistics']['confirmation']['mean_savings_seconds'], 100)
        self.assertEqual(result['statistics']['exploratory']['completed_pair_count'], 0)
        self.assertEqual(result['additional_quality_seeds'], 0)
        # Complete but practically small savings do not pass the prospective gate.
        receipt_data = read_json(measured)
        for pair in receipt_data['pairs']:
            leg = pair['legs']['B']
            report_path = Path(leg['trial']['path'])
            report = read_json(report_path)
            report['total_flow_seconds'] = 960
            report['phases']['managed_command'] = 940
            dump(report_path, report)
            leg['trial'] = identity(report_path)
        dump(measured, receipt_data)
        record = read_json(diagnostics)
        record['receipt_sha256'] = sha(measured)
        dump(diagnostics, record)
        small = summarize_timing(confirm, measured, diagnostics=identity(diagnostics))
        self.assertEqual(small['statistics']['confirmation']['interval']['lower'], 40)
        self.assertEqual(small['status'], 'evidence_insufficient')
        for number, pair in enumerate(receipt_data['pairs']):
            leg = pair['legs']['A']
            report_path = Path(leg['trial']['path'])
            report = read_json(report_path)
            report['total_flow_seconds'] = 1400 if number % 2 == 0 else 1600
            report['phases']['managed_command'] = report['total_flow_seconds'] - 20
            dump(report_path, report)
            leg['trial'] = identity(report_path)
        dump(measured, receipt_data)
        record['receipt_sha256'] = sha(measured)
        dump(diagnostics, record)
        imprecise = summarize_timing(confirm, measured, diagnostics=identity(diagnostics))
        final = imprecise['statistics']['confirmation']
        self.assertGreaterEqual(final['interval']['lower'], 60)
        self.assertGreater(final['half_width_seconds'], 15)
        self.assertEqual(imprecise['status'], 'evidence_insufficient')

    def test_unknown_conditions_and_failure_pairs_not_dropped(self):
        receipt = self.receipt(self.plan)
        data = read_json(receipt)
        data['pairs'][0]['legs']['A']['conditions']['state'] = 'unknown'
        leg = data['pairs'][1]['legs']['B']
        report_path = Path(leg['trial']['path'])
        report = read_json(report_path)
        report['status'] = 'failed'
        dump(report_path, report)
        leg['trial'] = identity(report_path)
        data['pairs'][2]['legs']['A'].pop('returncode')
        dump(receipt, data)
        result = summarize_timing(self.plan, receipt)
        self.assertEqual(result['expected_pairs'], 4)
        self.assertEqual(len(result['failed_or_unknown_pairs']), 3)
        self.assertIsNone(result['required_fixed_n'])
        self.assertEqual(result['status'], 'evidence_insufficient')

    def test_policy_confidence_stage_and_workload_scope_cannot_drift(self):
        for field, value in (('stage', 'confirmation'), ('split', 'screen-a'), ('selected_scene_ids', ['scene-00'])):
            cards = deepcopy(self.cards)
            path = self.root / f'bad-{field}.json'
            card = read_json(Path(cards['B']['20261008']['path']))
            card['prepare'][field] = value
            dump(path, card)
            cards['B']['20261008'] = identity(path)
            with self.assertRaisesRegex(ValueError, 'workload'):
                create_exploratory_plan(self.policy, self.interpretation, cards, [20261008] * 4, {'sampler': 'x'},
                                        self.root / 'bad-plan.json', prefix='bad')
        rule = read_json(self.policy)
        rule['timing']['interval_confidence'] = .95
        dump(self.policy, rule)
        with self.assertRaisesRegex(ValueError, 'frozen decision rule'):
            create_exploratory_plan(self.policy, self.interpretation, self.cards, [20261008] * 4, {'sampler': 'x'},
                                    self.root / 'bad-policy-plan.json', prefix='bad')

    def test_unbalanced_schedule_and_renamed_same_trial_rejected(self):
        receipt = self.receipt(self.plan)
        data = read_json(receipt)
        data['pairs'][1]['legs']['B']['trial'] = data['pairs'][0]['legs']['B']['trial']
        dump(receipt, data)
        with self.assertRaisesRegex(ValueError, 'artifact reused'):
            summarize_timing(self.plan, receipt)
        plan = read_json(self.plan)
        plan['pairs'][1]['order'] = 'AB'
        dump(self.plan, plan)
        with self.assertRaisesRegex(ValueError, 'locked balanced plan'):
            summarize_timing(self.plan, receipt)

    def test_cache_reuse_or_command_time_substitution_rejected(self):
        receipt = self.receipt(self.plan)
        data = read_json(receipt)
        leg = data['pairs'][0]['legs']['A']
        report_path = Path(leg['trial']['path'])
        report = read_json(report_path)
        report['total_flow_seconds'] = 5
        dump(report_path, report)
        leg['trial'] = identity(report_path)
        dump(receipt, data)
        with self.assertRaisesRegex(ValueError, 'full-flow wall time'):
            summarize_timing(self.plan, receipt)

    def test_early_stop_and_fixed_n_changes_do_not_pass(self):
        receipt = self.receipt(self.plan)
        confirm = self.root / 'confirmation-plan.json'
        freeze_confirmation_plan(self.plan, receipt, confirm, [20261008] * 4, prefix='confirm')
        measured = self.receipt(confirm)
        data = read_json(measured)
        data['pairs'] = data['pairs'][:2]
        dump(measured, data)
        result = summarize_timing(confirm, measured)
        self.assertEqual(result['status'], 'evidence_insufficient')
        self.assertEqual(len(result['missing_pair_ids']), 2)
        plan = read_json(confirm)
        plan['fixed_n'] = 2
        dump(confirm, plan)
        with self.assertRaisesRegex(ValueError, 'locked balanced plan'):
            summarize_timing(confirm, measured)

    def test_executor_attempts_all_legs_after_failure_and_new_output_required(self):
        calls = []
        def failing_runner(card, output):
            calls.append((card, output))
            raise RuntimeError('Synthetic failed trial')
        output = self.root / 'execute'
        receipt = execute_plan(self.plan, output, observe_conditions=lambda: {'state': 'unknown'}, trial_runner=failing_runner)
        self.assertEqual(len(calls), 8)
        self.assertEqual(len(receipt['pairs']), 4)
        self.assertTrue(all(leg['trial'] is None for pair in receipt['pairs'] for leg in pair['legs'].values()))
        with self.assertRaises(FileExistsError):
            execute_plan(self.plan, output, observe_conditions=lambda: {}, trial_runner=failing_runner)

    def test_explicit_interruption_retains_all_unrun_legs_and_unknown_state(self):
        calls = []
        def interrupted_runner(card, output):
            calls.append(output)
            raise KeyboardInterrupt('Synthetic explicit interruption')
        output = self.root / 'interrupted'
        receipt = execute_plan(self.plan, output, observe_conditions=lambda: {'state': 'unknown'}, trial_runner=interrupted_runner)
        self.assertTrue(receipt['interrupted'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(receipt['pairs']), 4)
        result = summarize_timing(self.plan, output / 'timing-receipt.json')
        self.assertEqual(result['status'], 'evidence_insufficient')
        self.assertEqual(result['expected_pairs'], 4)
        self.assertEqual(len(result['failed_or_unknown_pairs']), 4)

    def test_native_cache_resume_partial_and_missing_artifact_guards(self):
        receipt = self.receipt(self.plan)
        data = read_json(receipt)
        leg = data['pairs'][0]['legs']['A']
        directory = Path(leg['trial']['path']).parent
        run = directory / 'execution/runtime-run/translation/recipe-A'
        for path, field, value, message in (
                (run / 'completion.json', 'reused_windows', 1, 'fresh and complete'),
                (run / 'completion.json', 'cache_reset', {'verified': False}, 'empty fresh cache'),
                (run.parent / 'session.json', 'resume', {'checkpoint': 'old'}, 'fresh and complete'),
                (directory / 'trial-completion.json', 'complete_scenes', 33, 'complete frozen')):
            original = read_json(path)
            changed = deepcopy(original)
            changed[field] = value
            dump(path, changed)
            leg['trial'] = identity(directory / 'trial-completion.json')
            dump(receipt, data)
            with self.assertRaisesRegex(ValueError, message):
                summarize_timing(self.plan, receipt)
            dump(path, original)
        leg['trial'] = identity(directory / 'trial-completion.json')
        leg.pop('native_artifacts')
        dump(receipt, data)
        with self.assertRaisesRegex(ValueError, 'collection-time artifact hashes'):
            summarize_timing(self.plan, receipt)

    def test_too_small_or_odd_pilot_plan_rejected(self):
        for n in (2, 3, 5):
            with self.assertRaisesRegex(ValueError, 'even >=4'):
                create_exploratory_plan(self.policy, self.interpretation, self.cards, [20261008] * n,
                                        {'sampler': 'x'}, self.root / f'bad-{n}.json', prefix='bad')
        with self.assertRaisesRegex(ValueError, 'unsafe artifact ID'):
            create_exploratory_plan(self.policy, self.interpretation, self.cards, [20261008] * 4,
                                    {'sampler': 'x'}, self.root / 'unsafe.json', prefix='../escape')

    def test_auxiliary_preparation_fresh_cost_is_charged_once_not_per_batch(self):
        cards = deepcopy(self.cards)
        card_path = self.root / 'aux-card.json'
        card = read_json(Path(cards['B']['20261008']['path']))
        aux_plan = self.root / 'aux-plan.json'
        dump(aux_plan, {'schema': 'hy30-source-preparation-session-v3',
            'source': {**card['source'], 'freeze_sha256': sha(self.root / 'freeze-manifest.json')},
            'stage': 'screening', 'settings': {'seed': 20261008, 'sampling': 'official', 'cache_prompt': True,
                'n_predict': 2048, 'max_attempts': 2, 'max_items': 16},
            'scene_ids': [row['id'] for row in self.scene_rows], 'mode': 'background',
            'protocol': 'quoted-background-with-uncertainty-v1'})
        card['source_preparation'] = {'plan': str(aux_plan), 'sha256': sha(aux_plan)}
        dump(card_path, card)
        cards['B']['20261008'] = identity(card_path)
        plan_path = self.root / 'aux-pilot.json'
        plan = create_exploratory_plan(self.policy, self.interpretation, cards, [20261008] * 4,
                                       {'sampler': 'synthetic'}, plan_path, prefix='aux')
        pair = plan['pairs'][0]
        directory = self.root / 'aux-leg'
        pointer = self.native_leg(directory, card_path, 900, datetime.now(timezone.utc) + timedelta(days=1))
        measured = _native_leg(pointer, self.root, pair['legs']['B'], pair, plan, load_policy(self.policy, self.interpretation))
        self.assertEqual(measured['source_preparation_cost']['attempts'], 34)
        self.assertEqual(measured['dispatched_calls'], 34)
        self.assertEqual(measured['seconds'], 900)
        mutations = [('freeze', 'translation/preparation-options.json', lambda d: d['source'].update(freeze_sha256='e' * 64)),
                     ('settings', 'translation/preparation-options.json', lambda d: d['settings'].update(n_predict=1024)),
                     ('code', 'translation/preparation-options.json', lambda d: d['code_sha256'].update(fixture='e' * 64)),
                     ('cost-link', 'translation/preparation-options.json', lambda d: d['cost_artifacts'].update({'ledger.jsonl': 'e' * 64})),
                     ('cache', 'translation/preparation-options.json', lambda d: d['cache_reset'].update(first_response_checked=False)),
                     ('pid', 'runtime/runtime-final.json', lambda d: d.update(server_pid=9876)),
                     ('worker-exit', 'runtime/runtime-final.json', lambda d: d.update(worker_process_exited=False))]
        for name, suffix, mutate in mutations:
            def alter(aux_root, suffix=suffix, mutate=mutate):
                path = aux_root / 'runtime-run' / suffix
                value = read_json(path)
                mutate(value)
                dump(path, value)
            with self.subTest(name=name):
                path = self.root / ('bad-aux-' + name)
                ptr = self.native_leg(path, card_path, 900, datetime.now(timezone.utc) + timedelta(days=1), auxiliary_mutation=alter)
                with self.assertRaises(ValueError):
                    _native_leg(ptr, self.root, pair['legs']['B'], pair, plan, load_policy(self.policy, self.interpretation))
        report_path = directory / 'trial-completion.json'
        report = read_json(report_path)
        report['source_preparation']['cost']['attempts'] *= 34
        dump(report_path, report)
        with self.assertRaisesRegex(ValueError, 'costs are incomplete'):
            _native_leg(identity(report_path), self.root, pair['legs']['B'], pair, plan, load_policy(self.policy, self.interpretation))

    def test_metadata_reader_skips_deep_semantic_values_and_rejects_semantic_selection(self):
        path = self.root / 'metadata-only.json'
        path.write_text('{"preparations":' + '[' * 1500 + '"opaque"' + ']' * 1500
                        + ',"source":{"freeze_sha256":"bound"},"raw_responses":[{"content":"opaque"}]}', encoding='utf-8')
        self.assertEqual(read_metadata_fields(path, {'source'}), {'source': {'freeze_sha256': 'bound'}})
        for field in ('preparations', 'raw_responses'):
            with self.assertRaisesRegex(ValueError, 'semantic fields'):
                read_metadata_fields(path, {field})
        for value in ('{"source":{},"source":{}}', '{"source":{},}', '{"source":[}]}'):
            path.write_text(value, encoding='utf-8')
            with self.assertRaises(ValueError):
                read_metadata_fields(path, {'source'})


if __name__ == '__main__':
    unittest.main()
