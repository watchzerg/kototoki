"""Offline tests for strict delivery, immutable mapping, and failure bookkeeping."""

import unittest
import json
from pathlib import Path
import tempfile
import hashlib
from datetime import datetime
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

from experiments.translation_demo import adapters
from experiments.translation_demo.client import LlamaClient
from experiments.translation_demo.profiles import LEGACY_PROFILE, OFFICIAL_PROFILE, APEX_CANDIDATE, resolve_profile
from experiments.translation_demo.run import (CANDIDATES, HY30_ASSET_IDENTITIES, ASSET_IDENTITY_FIELDS,
    asset_manifest_paths, load_assets, select_asset, model_digest, main, parser, read_inputs, run_window, write_json)
from experiments.translation_demo_runtime import residency_evidence, validate_residency, forward_worker_events, main as runtime_main


WINDOW = {
    "id": "synthetic-1", "source_language": "ja", "target_language": "zh-Hans",
    "context": [{"id": "s0", "text": "はい。"}, {"id": "s1", "text": "渡さないで。"}, {"id": "s2", "text": "わかった。"}],
    "translate_ids": ["s1", "s2"],
}
SETTINGS = {"context_size": 4096, "n_predict": 1024, "max_attempts": 2, "input_limit": None, "stop": []}


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.last_exchange = "synthetic-transport"
        self.prompts = []
        self.requests = []

    def tokenize(self, prompt):
        self.prompts.append(prompt)
        return list(range(100))

    def complete(self, request):
        self.requests.append(request)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return dict({"prompt": self.prompts[-1], "tokens_evaluated": len(request["prompt"])}, **value)


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root = Path(__file__).resolve().parents[2] / '.local/translation-evaluation/test-tmp'
        cls.temp_root.mkdir(parents=True, exist_ok=True)

    def test_official_profile_native_request_has_no_hidden_truncation(self):
        profile = resolve_profile(OFFICIAL_PROFILE, APEX_CANDIDATE)
        client = FakeClient([{'content': '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'}])
        row = run_window(client, WINDOW, 'hy-mt2-30b', dict(SETTINGS, **profile))
        self.assertEqual(row['status'], 'delivered')
        expected = {'n_predict': 4096, 'temperature': .7, 'seed': 20261006,
                    'cache_prompt': True, 'stream': False, 'top_p': 1.0, 'top_k': 0,
                    'repeat_penalty': 1.0, 'min_p': 0.0, 'samplers': ['temperature'],
                    'dynatemp_range': 0.0, 'mirostat': 0, 'frequency_penalty': 0.0,
                    'presence_penalty': 0.0}
        self.assertEqual(client.requests, [dict(expected, prompt=list(range(100)), stop=[],
                                              grammar=adapters.id_grammar(WINDOW['translate_ids']))])
        self.assertEqual(row['attempts'][0]['generation_parameters'], expected)
        self.assertEqual(row['attempts'][0]['sampling_profile'], OFFICIAL_PROFILE)
        self.assertEqual(profile['model_recommendation']['top_k'], -1)
        self.assertEqual(profile['model_recommendation']['max_tokens'], 4096)

    def test_legacy_profile_preserves_exact_request_for_every_family(self):
        expected = {'prompt': list(range(100)), 'n_predict': 1024, 'temperature': 0.0,
                    'seed': 20261006, 'cache_prompt': False, 'stream': False, 'stop': []}
        for candidate, family in CANDIDATES.items():
            content = '合成译文。' if family == 'translategemma' else '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'
            for settings in (SETTINGS, dict(SETTINGS, **resolve_profile(LEGACY_PROFILE, candidate))):
                with self.subTest(candidate=candidate, explicit='sampling_profile' in settings):
                    client = FakeClient([{'content': content}])
                    row = run_window(client, WINDOW, family, settings)
                    self.assertIn(row['status'], ('delivered', 'native_delivered'))
                    request = dict(client.requests[0])
                    if family != 'translategemma':
                        self.assertEqual(request.pop('grammar'), adapters.id_grammar(WINDOW['translate_ids']))
                    self.assertEqual(request, expected)

    def test_official_profile_rejects_conflicting_budgets_models_and_mapping(self):
        for override in ({'n_predict': 1024}, {'context_size': 4096}, {'mapping_only': True},
                         {'n_predict': 0}, {'context_size': -1}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                resolve_profile(OFFICIAL_PROFILE, APEX_CANDIDATE, **override)
        for candidate in CANDIDATES.keys() - {APEX_CANDIDATE}:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                resolve_profile(OFFICIAL_PROFILE, candidate)
        custom = resolve_profile(LEGACY_PROFILE, 'hy-mt2-7b-q8', n_predict=500, context_size=2048)
        self.assertEqual((custom['n_predict'], custom['context_size']), (500, 2048))
        self.assertEqual(custom['generation_parameters']['n_predict'], 500)

    def test_official_context_budget_reserves_all_output_and_guard(self):
        settings = dict(SETTINGS, **resolve_profile(OFFICIAL_PROFILE, APEX_CANDIDATE))
        for tokens, accepted in ((4032, True), (4033, False)):
            with self.subTest(tokens=tokens):
                client = FakeClient([{'content': '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'}])
                def tokenize(prompt):
                    client.prompts.append(prompt)
                    return list(range(tokens))
                client.tokenize = tokenize
                row = run_window(client, WINDOW, 'hy-mt2-30b', settings)
                self.assertEqual(row['status'], 'delivered' if accepted else 'translation_failed')
                self.assertEqual(len(client.requests), int(accepted))
                self.assertEqual(len(row['attempts']), 1)
                if not accepted:
                    self.assertIn('output reserve exceeds runtime context', row['reason'])

    def test_managed_session_profile_override_is_rejected_before_loading(self):
        argv = ['runtime', '--candidate', APEX_CANDIDATE, '--output-dir', 'unused',
                '--session-worker', 'experiments.translation_flow.worker', '--session-plan', 'unused.json',
                '--sampling-profile', OFFICIAL_PROFILE]
        with patch('sys.argv', argv), patch('experiments.translation_demo_runtime.load_assets') as load, \
                patch('sys.stderr'), self.assertRaises(SystemExit) as error:
            runtime_main()
        self.assertEqual(error.exception.code, 2)
        load.assert_not_called()

    def test_runtime_official_profile_forwards_output_and_preserves_metadata(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            root = Path(temp)
            model, engine = root / 'synthetic.gguf', root / 'engine.exe'
            model.write_bytes(b'synthetic')
            engine.write_bytes(b'fake engine')
            asset = dict(id=APEX_CANDIDATE, directory=str(root), file=model.name, size=9,
                         status='verified', sha256=model_digest(model))
            write_json(root / 'assets.json', [asset])
            write_json(root / 'identity.json', {'identity': 'synthetic'})
            response = MagicMock(status=200)
            response.__enter__.return_value = response
            response.read.return_value = b'{}'
            opener = MagicMock()
            opener.open.side_effect = [OSError('port unused'), response, response]
            server = SimpleNamespace(pid=1234, returncode=None)
            server.poll = lambda: server.returncode
            server.terminate = lambda: setattr(server, 'returncode', -15)
            server.wait = lambda **kwargs: server.returncode
            child = SimpleNamespace(returncode=0, poll=lambda: 0)
            commands = []
            def launch(command, **kwargs):
                commands.append(command)
                if len(commands) == 1:
                    (root / 'out/runtime/server.log').write_text(
                        'load_tensors: offloaded 49/49 layers to GPU\nload_tensors: CUDA0 model buffer size = 100.0 MiB', encoding='utf-8')
                    return server
                return child
            monitor = SimpleNamespace(start=lambda: None, mark_phase=lambda *args: None,
                                      set_target=lambda pid: None, stop=lambda: {})
            argv = ['runtime', '--candidate', APEX_CANDIDATE, '--inputs', str(root / 'inputs.jsonl'),
                    '--output-dir', str(root / 'out'), '--engine', str(engine),
                    '--engine-identity', str(root / 'identity.json'), '--asset-manifest', str(root / 'assets.json'),
                    '--sampling-profile', OFFICIAL_PROFILE]
            with patch('sys.argv', argv), patch('experiments.translation_demo_runtime.load_assets', return_value={APEX_CANDIDATE: asset}), \
                    patch('experiments.translation_demo_runtime.ResourceMonitor', return_value=monitor), \
                    patch('experiments.translation_demo_runtime.build_opener', return_value=opener), \
                    patch('experiments.translation_demo_runtime.subprocess.Popen', side_effect=launch), \
                    patch('experiments.translation_demo_runtime.subprocess.run', return_value=SimpleNamespace(stdout='100,0', returncode=0)), \
                    patch('experiments.translation_demo_runtime.time.sleep'), patch('builtins.print'):
                self.assertEqual(runtime_main(), 0)
            self.assertEqual(commands[0][commands[0].index('-c') + 1], '8192')
            for flag, value in (('--context-size', '8192'), ('--n-predict', '4096'), ('--sampling-profile', OFFICIAL_PROFILE)):
                self.assertEqual(commands[1][commands[1].index(flag) + 1], value)
            manifest = json.loads((root / 'out/runtime/runtime-final.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['generation_profile'], resolve_profile(OFFICIAL_PROFILE, APEX_CANDIDATE))
            self.assertEqual(manifest['generation_settings_source'], 'sampling-profile')
            self.assertEqual(manifest['context_size'], 8192)
            self.assertTrue((root / 'out/runtime/profiles.py').is_file())

    def test_official_main_records_parameters_and_rejects_stale_context(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            root = Path(temp)
            model = root / 'synthetic.gguf'
            model.write_bytes(b'synthetic')
            asset = dict(id=APEX_CANDIDATE, directory=str(root), file=model.name, size=9,
                         status='verified', sha256=model_digest(model))
            write_json(root / 'assets.json', [asset])
            write_json(root / 'engine.json', dict(model_path=str(model), model_sha256=asset['sha256'], context_size=8192))
            (root / 'inputs.jsonl').write_text(json.dumps(WINDOW), encoding='utf-8')
            client = FakeClient([{'content': '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'}])
            client.request = lambda endpoint: {'model_path': str(model), 'default_generation_settings': {'n_ctx': 8192}}
            template = '<｜hy_begin▁of▁sentence｜><｜hy_User｜><｜hy_Assistant｜><｜reasoning_mode｜>no_think<eos:6124c78e>'
            argv = ['demo', '--candidate', APEX_CANDIDATE, '--inputs', str(root / 'inputs.jsonl'),
                    '--output-dir', str(root / 'out'), '--engine-manifest', str(root / 'engine.json'),
                    '--asset-manifest', str(root / 'assets.json'), '--sampling-profile', OFFICIAL_PROFILE]
            with patch('sys.argv', argv), patch('experiments.translation_demo.run.load_assets', return_value={APEX_CANDIDATE: asset}), \
                    patch('experiments.translation_demo.run.LlamaClient', return_value=client), \
                    patch('experiments.translation_demo.run.metadata', return_value={'tokenizer.chat_template': template}), patch('builtins.print'):
                self.assertEqual(main(), 0)
            settings = json.loads((root / 'out/run.json').read_text(encoding='utf-8'))['settings']
            for key, value in resolve_profile(OFFICIAL_PROFILE, APEX_CANDIDATE).items():
                self.assertEqual(settings[key], value)
            client.request = lambda endpoint: {'model_path': str(model), 'default_generation_settings': {'n_ctx': 4096}}
            argv[argv.index('--output-dir') + 1] = str(root / 'stale-server')
            with patch('sys.argv', argv), patch('experiments.translation_demo.run.load_assets', return_value={APEX_CANDIDATE: asset}), \
                    patch('experiments.translation_demo.run.LlamaClient', return_value=client), \
                    patch('experiments.translation_demo.run.metadata', return_value={'tokenizer.chat_template': template}), \
                    self.assertRaisesRegex(ValueError, 'Server context size differs'):
                main()
            (root / 'engine.json').write_text(json.dumps(dict(model_path=str(model), context_size=4096)), encoding='utf-8')
            with patch('sys.argv', argv), patch('experiments.translation_demo.run.load_assets', return_value={APEX_CANDIDATE: asset}), \
                    self.assertRaisesRegex(ValueError, 'Engine manifest must prove'):
                main()

    def test_new_hy30_candidates_share_frozen_native_prompt(self):
        for candidate in HY30_ASSET_IDENTITIES:
            with self.subTest(candidate=candidate):
                args = parser().parse_args(['--candidate', candidate, '--inputs', 'synthetic.jsonl',
                    '--output-dir', 'synthetic', '--engine-manifest', 'engine.json',
                    '--asset-manifest', 'primary.json', '--asset-manifest', 'shortlist.json'])
                self.assertEqual(args.asset_manifest, [Path('primary.json'), Path('shortlist.json')])
                client = FakeClient([{'content': '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'}])
                self.assertEqual(run_window(client, WINDOW, CANDIDATES[candidate], SETTINGS)['status'], 'delivered')
                self.assertEqual(client.prompts[0], adapters.render('hy-mt2-30b', WINDOW))

    def test_manifest_merge_rejects_duplicates_and_relabelled_candidates(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            root = Path(temp)
            paths = [root / 'primary.json', root / 'shortlist.json']
            rows = [dict(zip(ASSET_IDENTITY_FIELDS, values), id=model_id, directory=str(root / model_id), status='verified')
                    for model_id, values in HY30_ASSET_IDENTITIES.items()]
            write_json(paths[0], rows[:1])
            write_json(paths[1], rows[1:])
            self.assertEqual(set(load_assets(paths)), set(HY30_ASSET_IDENTITIES))
            for change in ({'id': 'unknown'}, {'file': 'other.gguf'}, {'repo': 'other/repo'},
                           {'sha256': '0' * 64}, {'revision': '0' * 40}, {'size': rows[1]['size'] + 1}):
                paths[1].write_text(json.dumps([dict(rows[1], **change)]), encoding='utf-8')
                with self.subTest(change=change), self.assertRaises(ValueError):
                    load_assets(paths)
            paths[1].write_text(json.dumps([rows[0]]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Duplicate asset ID'):
                load_assets(paths)

    def test_asset_file_aliases_missing_candidates_and_size_changes_fail(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            root = Path(temp)
            model = root / 'synthetic.gguf'
            model.write_bytes(b'synthetic')
            asset = dict(id='hy-mt2-7b-q8', repo='synthetic/repo', revision='0' * 40,
                         file=model.name, directory=str(root), status='verified', size=9,
                         sha256=hashlib.sha256(model.read_bytes()).hexdigest())
            path = root / 'manifest.json'
            write_json(path, [asset])
            self.assertEqual(select_asset(load_assets([path]), asset['id']), asset)
            self.assertEqual(model_digest(model), asset['sha256'])
            with self.assertRaisesRegex(ValueError, 'missing'):
                select_asset(load_assets([path]), 'tower-plus-9b-q8')
            for extra in (dict(asset, id='tower-plus-9b-q8', sha256='1' * 64),
                          dict(asset, id='tower-plus-9b-q8', directory=str(root / 'other'))):
                path.write_text(json.dumps([asset, extra]), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'Duplicate asset file identity'):
                    load_assets([path])
            model.write_bytes(b'changed-size')
            with self.assertRaisesRegex(ValueError, 'size'):
                select_asset({asset['id']: asset}, asset['id'])
            with self.assertRaisesRegex(ValueError, 'not verified'):
                select_asset({asset['id']: dict(asset, status='downloaded')}, asset['id'])

    def test_manifest_defaults_preserve_old_setup_and_explicit_selection(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            root = Path(temp)
            primary = root / '.local/manifests/translation-download-plan.json'
            shortlist = root / '.local/manifests/hy30-shortlist-downloads.json'
            self.assertEqual(asset_manifest_paths(None, root), [primary])
            shortlist.parent.mkdir(parents=True)
            shortlist.touch()
            self.assertEqual(asset_manifest_paths(None, root), [primary, shortlist])
            self.assertEqual(asset_manifest_paths([shortlist], root), [shortlist.resolve()])

    def test_oom_stops_identical_retry_and_records_absolute_timing(self):
        client = FakeClient([RuntimeError('CUDA_ERROR_OUT_OF_MEMORY')])
        row = run_window(client, WINDOW, 'hy-mt2', dict(SETTINGS, stop_on_oom=True))
        self.assertEqual(row['status'], 'translation_failed')
        self.assertEqual(row['error_kind'], 'oom')
        self.assertEqual(len(row['attempts']), 1)
        self.assertLessEqual(datetime.fromisoformat(row['started_at_utc']), datetime.fromisoformat(row['finished_at_utc']))
        response = {'content': '{"translations":{"s1":"内存不足。","s2":"明白了。"}}'}
        self.assertNotIn('error_kind', run_window(FakeClient([response]), WINDOW, 'hy-mt2', SETTINGS))

    def test_oom_checks_engine_error_fields_and_http_error_body_only(self):
        settings = dict(SETTINGS, stop_on_oom=True)
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            trace = Path(temp)
            (trace / 'response.raw').write_text('{"content":"out of memory"}', encoding='utf-8')
            invalid = {'content': 'out of memory'}
            client = FakeClient([invalid, invalid])
            client.last_exchange = str(trace)
            row = run_window(client, WINDOW, 'hy-mt2', settings)
            self.assertEqual(row['status'], 'translation_failed')
            self.assertEqual(len(row['attempts']), 2)
            self.assertNotIn('error_kind', row)
            (trace / 'response.raw').write_text('{"error":{"message":"CUDA out of memory"}}', encoding='utf-8')
            client = FakeClient([HTTPError('http://localhost', 500, 'server error', None, None)])
            client.last_exchange = str(trace)
            row = run_window(client, WINDOW, 'hy-mt2', settings)
            self.assertEqual(row['error_kind'], 'oom')
            self.assertEqual(len(row['attempts']), 1)
            client = FakeClient([{'error': {'message': 'VK_ERROR_OUT_OF_DEVICE_MEMORY'}}])
            row = run_window(client, WINDOW, 'hy-mt2', settings)
            self.assertEqual(row['error_kind'], 'oom')
            self.assertEqual(len(row['attempts']), 1)

    def test_oom_main_preserves_only_attempted_rows_and_explicit_remaining_ids(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            root = Path(temp)
            model = root / 'synthetic.gguf'
            model.write_bytes(b'synthetic')
            asset = dict(id='hy-mt2-7b-q8', repo='synthetic/repo', revision='0' * 40, file=model.name,
                         directory=str(root), status='verified', size=9, sha256=model_digest(model))
            write_json(root / 'assets.json', [asset])
            write_json(root / 'engine.json', dict(model_path=str(model), model_sha256=asset['sha256'], asset=asset))
            inputs = [WINDOW, dict(WINDOW, id='synthetic-2')]
            (root / 'inputs.jsonl').write_text('\n'.join(json.dumps(row) for row in inputs), encoding='utf-8')
            client = FakeClient([RuntimeError('CUDA out of memory')])
            client.request = lambda endpoint: {'model_path': str(model)}
            argv = ['demo', '--candidate', asset['id'], '--inputs', str(root / 'inputs.jsonl'),
                    '--output-dir', str(root / 'out'), '--engine-manifest', str(root / 'engine.json'),
                    '--asset-manifest', str(root / 'assets.json'), '--stop-on-oom']
            with patch('sys.argv', argv), patch('experiments.translation_demo.run.LlamaClient', return_value=client), \
                    patch('experiments.translation_demo.run.metadata', return_value={'tokenizer.chat_template': '<|startoftext|><|extra_0|>'}):
                self.assertEqual(main(), 1)
            completion = json.loads((root / 'out/completion.json').read_text(encoding='utf-8'))
            self.assertEqual(completion['windows'], 1)
            self.assertEqual(completion['expected_windows'], 2)
            self.assertEqual(completion['remaining_window_ids'], ['synthetic-2'])
            self.assertEqual(completion['stopped_reason'], 'oom')
            self.assertEqual(len((root / 'out/ledger.jsonl').read_text(encoding='utf-8').splitlines()), 1)
            self.assertFalse((root / 'out/window-synthetic-2.json').exists())

    def test_worker_phase_forwarding_waits_for_complete_lines(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            path = Path(temp) / 'workloads.jsonl'
            phases = []
            monitor = SimpleNamespace(mark_phase=lambda name, data: phases.append((name, data)))
            first = json.dumps({'status': 'started', 'label': 'warmup', 'at_utc': 'synthetic'})
            path.write_bytes((first + '\n{"status":').encode())
            offset = forward_worker_events(path, 0, monitor)
            self.assertEqual(offset, len((first + '\n').encode()))
            self.assertEqual(phases[0][0], 'warmup')
            with path.open('ab') as stream:
                stream.write(b'"started","label":"regression"}\n')
            final_offset = forward_worker_events(path, offset, monitor)
            self.assertEqual(final_offset, path.stat().st_size)
            self.assertEqual([phase for phase, _ in phases], ['warmup', 'regression'])
            self.assertEqual(forward_worker_events(path, final_offset, monitor), final_offset)
            self.assertEqual(len(phases), 2)

    def test_runtime_session_freezes_equivalent_flags_and_cleans_owned_server(self):
        with tempfile.TemporaryDirectory(dir=self.temp_root) as temp:
            root = Path(temp)
            model = root / 'synthetic.gguf'
            model.write_bytes(b'synthetic')
            engine = root / 'llama-server.exe'
            engine.write_bytes(b'fake engine')
            asset = dict(id='hy-mt2-7b-q8', repo='synthetic/repo', revision='0' * 40, file=model.name,
                         directory=str(root), status='verified', size=9, sha256=model_digest(model))
            write_json(root / 'assets.json', [asset])
            write_json(root / 'identity.json', {'identity': 'synthetic'})
            write_json(root / 'plan.json', {'workloads': []})
            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self): return b'{}'
            class Opener:
                calls = 0
                def open(self, *args, **kwargs):
                    self.calls += 1
                    if self.calls == 1: raise OSError('port unused')
                    return Response()
            class Process:
                pid = 1234
                returncode = None
                def poll(self): return self.returncode
                def terminate(self): self.returncode = -15
                def wait(self, **kwargs): return self.returncode
            server = Process()
            worker = Process()
            worker.returncode = 0
            calls = []
            def launch(cmd, **kwargs):
                calls.append(cmd)
                if len(calls) == 1:
                    (root / 'out/runtime/server.log').write_text(
                        'load_tensors: offloaded 49/49 layers to GPU\nload_tensors: CUDA0 model buffer size = 100.0 MiB', encoding='utf-8')
                    return server
                return worker
            phases = []
            monitor = SimpleNamespace(start=lambda: None, mark_phase=lambda name, data=None: phases.append(name),
                                      set_target=lambda pid: None, stop=lambda: {'sample_count': 0})
            argv = ['runtime', '--candidate', asset['id'], '--output-dir', str(root / 'out'),
                    '--engine', str(engine), '--engine-identity', str(root / 'identity.json'),
                    '--asset-manifest', str(root / 'assets.json'), '--session-plan', str(root / 'plan.json'),
                    '--session-worker', 'experiments.translation_four_quantization.worker']
            with patch('sys.argv', argv), patch('experiments.translation_demo_runtime.ResourceMonitor', return_value=monitor), \
                    patch('experiments.translation_demo_runtime.build_opener', return_value=Opener()), \
                    patch('experiments.translation_demo_runtime.subprocess.Popen', side_effect=launch), \
                    patch('experiments.translation_demo_runtime.subprocess.run', return_value=SimpleNamespace(stdout='100,0', returncode=0)), \
                    patch('experiments.translation_demo_runtime.time.sleep'), patch('builtins.print'):
                self.assertEqual(runtime_main(), 0)
            manifest = json.loads((root / 'out/runtime/runtime-final.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['model_sha256'], asset['sha256'])
            self.assertEqual((manifest['threads'], manifest['threads_batch']), (8, 8))
            self.assertEqual((manifest['kv_type_k'], manifest['kv_type_v']), ('f16', 'f16'))
            self.assertEqual(manifest['prompt_cache_ram_mib'], 8192)
            self.assertTrue(manifest['server_process_exited'])
            self.assertTrue(manifest['worker_process_exited'])
            self.assertEqual(manifest['server_exit_code'], -15)
            self.assertIn('--stop-on-oom', calls[1])
            self.assertIn('--asset-manifest', calls[1])
            self.assertNotIn('--sampling-profile', calls[1])
            self.assertNotIn('--n-predict', calls[1])
            self.assertIsNone(manifest['generation_profile'])
            self.assertEqual(manifest['generation_settings_source'], 'session-plan')
            self.assertEqual(phases, ['idle_baseline', 'load', 'inference', 'unload', 'released'])
            self.assertTrue((root / 'out/runtime/server-pid.json').exists())


    def test_official_q4_uses_same_native_contract_as_q3(self):
        candidate = 'hy-mt2-30b-a3b-q4-k-m-official'
        args = parser().parse_args(['--candidate', candidate, '--inputs', 'synthetic.jsonl',
                                    '--output-dir', 'synthetic', '--engine-manifest', 'engine.json'])
        self.assertEqual(args.candidate, candidate)
        self.assertEqual(CANDIDATES[candidate], CANDIDATES['hy-mt2-30b-a3b-q3-k-m'])
        client = FakeClient([{'content': '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'}])
        result = run_window(client, WINDOW, CANDIDATES[candidate], SETTINGS)
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual(client.prompts[0], adapters.render(CANDIDATES['hy-mt2-30b-a3b-q3-k-m'], WINDOW))

    def test_partial_offload_needs_explicit_opt_in_and_exact_layers(self):
        evidence = residency_evidence('''load_tensors: offloaded 36/49 layers to GPU
load_tensors: CPU_Mapped model buffer size = 4500.00 MiB
load_tensors: CUDA0 model buffer size = 12890.13 MiB''')
        self.assertEqual(evidence['layers_not_offloaded'], 13)
        self.assertEqual(evidence['cpu_model_buffers_mib'], {'CPU_Mapped': 4500.0})
        self.assertEqual(evidence['gpu_model_buffers_mib'], {'CUDA0': 12890.13})
        validate_residency(evidence, 36, True)
        with self.assertRaisesRegex(RuntimeError, 'requires explicit'):
            validate_residency(evidence, 36, False)
        with self.assertRaisesRegex(RuntimeError, 'differ'):
            validate_residency(evidence, 40, True)

    def test_full_gpu_can_still_have_cpu_mapped_embedding_buffer(self):
        evidence = residency_evidence('''load_tensors: offloaded 49/49 layers to GPU
load_tensors: CPU_Mapped model buffer size = 101.41 MiB
load_tensors: CUDA0 model buffer size = 13670.82 MiB''')
        validate_residency(evidence, 99, False)
        self.assertFalse(evidence['partial_layer_offload'])
        self.assertEqual(evidence['layers_not_offloaded'], 0)

    def test_cpu_only_and_missing_gpu_placement_evidence_fail(self):
        for log in ('', 'load_tensors: offloaded 0/49 layers to GPU',
                    'load_tensors: offloaded 36/49 layers to GPU\nload_tensors: CPU model buffer size = 17000.0 MiB',
                    'load_tensors: offloaded 36/49 layers to GPU\nload_tensors: CUDA_Host model buffer size = 500.0 MiB'):
            with self.subTest(log=log), self.assertRaises(RuntimeError):
                validate_residency(residency_evidence(log), 36, True)

    def test_tokenizer_preserves_explicit_native_special_tokens(self):
        client = LlamaClient("http://127.0.0.1:8080")
        prompt = "<bos><start_of_turn>user\n合成源文<end_of_turn>\n<start_of_turn>model\n"
        with patch.object(client, "request", return_value={"tokens": [2, 106, 500, 107]}) as request:
            self.assertEqual(client.tokenize(prompt), [2, 106, 500, 107])
            request.assert_called_once_with("/tokenize", {"content": prompt, "add_special": False, "parse_special": True})
        for invalid in ([], [True], [-1], [2.0], "tokens"):
            with self.subTest(invalid=invalid), patch.object(client, "request", return_value={"tokens": invalid}):
                with self.assertRaisesRegex(ValueError, "integer token IDs"):
                    client.tokenize(prompt)

    def test_native_transport_submits_numeric_ids_uniformly(self):
        for family in ("hy-mt2", "hy-mt2-30b", "tower-plus", "translategemma"):
            content = "未改写合成译文。" if family == "translategemma" else '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'
            client = FakeClient([{"content": content}])
            row = run_window(client, WINDOW, family, SETTINGS)
            with self.subTest(family=family):
                self.assertIn(row["status"], ("delivered", "native_delivered"))
                self.assertEqual(client.requests[0]["prompt"], list(range(100)))
                self.assertEqual(client.prompts[0], adapters.render(family, WINDOW))
                self.assertEqual(row["attempts"][0]["prompt_transport"], "token-ids-v1")
                self.assertTrue(row["attempts"][0]["effective_prompt_verified"])
                self.assertTrue(row["attempts"][0]["effective_token_count_verified"])
                self.assertEqual(len(row["attempts"][0]["input_token_ids_sha256"]), 64)

    def test_effective_prompt_or_token_count_mismatch_refuses_delivery(self):
        for field, value in (("prompt", "<bos><bos>changed"), ("tokens_evaluated", 101), ("tokens_evaluated", True)):
            response = {"content": '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}', field: value}
            row = run_window(FakeClient([response, response]), WINDOW, "tower-plus", SETTINGS)
            with self.subTest(field=field, value=value):
                self.assertEqual(row["status"], "translation_failed")
                self.assertEqual(len(row["attempts"]), 2)
                self.assertEqual(row["translations"], {})
                self.assertIn("Effective server prompt", row["reason"])

    def test_failed_group_mapping_retains_explicit_contract(self):
        settings = dict(SETTINGS, mapping_recipe="native-scored-groups-gbnf-v4")
        unresolved = {"content": '{"unresolved":true,"reason":"无法可靠分组"}'}
        row = run_window(FakeClient([unresolved, unresolved]), WINDOW, "translategemma", settings,
                         {"status": "native_delivered", "native_text": "合成译文。", "generation_seconds": 1.0})
        self.assertEqual(row["status"], "mapping_unjudgeable")
        self.assertEqual(row["delivery_contract"], "native-scored-groups-v4")
        row = run_window(FakeClient([]), WINDOW, "translategemma", settings,
                         {"status": "translation_failed", "reason": "原生调用失败", "generation_seconds": 1.0})
        self.assertEqual(row["status"], "translation_failed")
        self.assertEqual(row["delivery_contract"], "native-scored-groups-v4")

    def test_exact_ids_and_duplicate_key_rejection(self):
        for text in ['{"translations":{"s1":"不要交出去。"}}', '{"translations":{"s1":"甲","s1":"乙","s2":"丙"}}', '{"translations":{"s0":"甲","s1":"乙","s2":"丙"}}']:
            with self.assertRaises(ValueError):
                adapters.translations(text, WINDOW["translate_ids"])

    def test_native_template_preserves_full_context(self):
        text = adapters.render("translategemma", WINDOW)
        self.assertIn("Japanese (ja) to Chinese (zh-Hans)", text)
        self.assertIn("はい。\n渡さないで。\nわかった。", text)
        self.assertNotIn("translate_ids", text)
        self.assertTrue(text.startswith("<bos><start_of_turn>user\n"))
        self.assertTrue(text.endswith("<start_of_turn>model\n"))
        for family in ("hy-mt2", "hy-mt2-30b", "tower-plus"):
            prompt = adapters.render(family, WINDOW)
            self.assertIn('"s0"', prompt)
            self.assertIn('"s1"', prompt)
        large = adapters.render("hy-mt2-30b", WINDOW)
        self.assertTrue(large.startswith("<｜hy_begin▁of▁sentence｜><｜reasoning_mode｜>reasoning_effort:no_think<｜hy_User｜>"))
        self.assertTrue(large.endswith("<｜hy_Assistant｜><think></think>"))

    def test_mapping_keeps_offsets_and_refuses_rewrite(self):
        native = "是。不要交出去。明白了。"
        valid = '{"segments":[{"id":"s0","text":"是。"},{"id":"s1","text":"不要交出去。"},{"id":"s2","text":"明白了。"}]}'
        output, spans = adapters.validate_mapping(valid, WINDOW, native)
        self.assertEqual(output, {"s1": "不要交出去。", "s2": "明白了。"})
        self.assertEqual(spans[1]["target_spans"], [[2, 8]])
        with self.assertRaises(ValueError):
            adapters.validate_mapping(valid.replace("不要交出去。", "请不要交出去。"), WINDOW, native)

    def test_boundary_mapping_extracts_native_across_changed_line_layout(self):
        native = '是。\n不要交出去。 明白了。'
        # Native line layout is not an ID mapping; only semantic anchors set boundaries.
        text = json.dumps({"boundaries": {"s1": "不要交出去", "s2": "明白了。"}}, ensure_ascii=False)
        result, spans = adapters.validate_boundary_mapping(text, WINDOW, native)
        self.assertEqual(result, {"s1": "不要交出去。 ", "s2": "明白了。"})
        self.assertEqual(spans[0]["target_spans"], [[0, 3]])
        self.assertEqual(''.join(native[start:end] for span in spans for start, end in span['target_spans']), native)

    def test_boundary_mapping_rejects_ambiguity_invention_reorder_and_empty(self):
        cases = [
            ("是。是。不要交出去。明白了。", {"s1": "是。", "s2": "明白了。"}),
            ("是。不要交出去。明白了。", {"s1": "请不要交出去", "s2": "明白了。"}),
            ("是。不要交出去。明白了。", {"s1": "明白了。", "s2": "不要交出去"}),
            ("是。不要交出去。明白了。", {"s1": "是。", "s2": "明白了。"}),
            ("是。不要交出去。明白了。", {"s1": "不要交出去"}),
        ]
        for native, boundaries in cases:
            with self.subTest(boundaries=boundaries), self.assertRaises(ValueError):
                adapters.validate_boundary_mapping(json.dumps({"boundaries": boundaries}, ensure_ascii=False), WINDOW, native)

    def test_mapping_failure_is_unjudgeable(self):
        native = {"status": "native_delivered", "native_text": "合并了。", "generation_seconds": 2.0}
        response = {"content": '{"unresolved":true,"reason":"源句合并，边界无法确定"}'}
        row = run_window(FakeClient([response, response]), WINDOW, "translategemma", SETTINGS, native)
        self.assertEqual(row["status"], "mapping_unjudgeable")
        self.assertEqual(row["translations"], {})
        self.assertEqual(len(row["attempts"]), 2)
        self.assertGreaterEqual(row["elapsed_seconds"], 2.0)

    def test_mapper_choice_and_native_attempt_audit(self):
        native_attempts = [{"attempt": 1, "status": "failed"}, {"attempt": 2, "status": "accepted"}]
        native = {"status": "native_delivered", "native_text": "是。\n不要交出去。明白了。", "generation_seconds": 3.0,
                  "attempts": native_attempts, "native_window_artifact": "synthetic/window.json"}
        client = FakeClient([{"content": '{"boundaries":{"s1":"不要交出去","s2":"明白了。"}}'}])
        row = run_window(client, WINDOW, "translategemma", dict(SETTINGS, mapper_family="tower-plus", mapping_recipe="native-boundary-anchors-v2"), native)
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(row["translations"]["s1"], "不要交出去。")
        self.assertEqual(row["native_attempts"], native_attempts)
        self.assertEqual(row["native_window_artifact"], "synthetic/window.json")
        self.assertTrue(client.prompts[0].startswith("<bos><start_of_turn>user\n"))
        self.assertIn('root ::= boundaries | unresolved', client.requests[0]["grammar"])
        self.assertEqual(len(row["attempts"]), 1)
        self.assertGreaterEqual(row["elapsed_seconds"], 3.0)

    def test_unknown_native_duration_is_not_fabricated(self):
        native = {"status": "native_delivered", "native_text": "是。不要交出去。明白了。"}
        client = FakeClient([{"content": '{"boundaries":{"s1":"不要交出去","s2":"明白了。"}}'}])
        row = run_window(client, WINDOW, "translategemma", SETTINGS, native)
        self.assertEqual(row["status"], "delivered")
        self.assertIsNone(row["generation_seconds"])
        self.assertIsNone(row["elapsed_seconds"])
        self.assertIn("absent", row["generation_timing_reason"])
        self.assertGreaterEqual(row["auxiliary_seconds"], 0)

    def test_boundary_mapping_uses_unicode_codepoint_offsets(self):
        native = "是😀。不要交出去。明白了。"
        result, spans = adapters.validate_boundary_mapping('{"boundaries":{"s1":"不要交出去","s2":"明白了。"}}', WINDOW, native)
        self.assertEqual(spans[1]["target_spans"][0][0], 3)
        self.assertEqual(result["s1"], "不要交出去。")

    def test_native_anchor_vocabulary_is_unique_exact_and_handles_escapes(self):
        native = '是😀。\n不要交出去。"明白了。"\n不要交出去。结束。'
        anchors = adapters.native_boundary_anchors(native)
        self.assertNotIn("不要交出", anchors)  # This prefix occurs twice.
        self.assertTrue(anchors)
        for anchor in anchors:
            start = native.find(anchor)
            self.assertGreater(start, 0)
            self.assertEqual(native.find(anchor, start + 1), -1)
            self.assertTrue(len(anchor) in (4, 8, 12, 16) or native.endswith(anchor))
        grammar = adapters.native_boundary_mapping_grammar(WINDOW, native)
        self.assertIn("root ::= boundaries | unresolved", grammar)
        self.assertIn('ws anchor ws', grammar)
        for anchor in anchors:
            self.assertIn(json.dumps(json.dumps(anchor, ensure_ascii=False), ensure_ascii=False), grammar)

    def test_native_anchor_v3_pipeline_and_semantic_abstention(self):
        native = {"status": "native_delivered", "native_text": "是。不要交出去。明白了。", "generation_seconds": 2.0}
        settings = dict(SETTINGS, mapper_family="tower-plus", mapping_recipe="native-boundary-anchors-gbnf-v3")
        client = FakeClient([{"content": '{"boundaries":{"s1":"不要交出","s2":"明白了。"}}'}])
        row = run_window(client, WINDOW, "translategemma", settings, native)
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(row["translations"]["s1"], "不要交出去。")
        self.assertIn("restriction proves text identity, not semantic association", client.prompts[0])
        unresolved = {"content": '{"unresolved":true,"reason":"inseparable meanings"}'}
        row = run_window(FakeClient([unresolved, unresolved]), WINDOW, "translategemma", settings, native)
        self.assertEqual(row["status"], "mapping_unjudgeable")
        with self.assertRaises(ValueError):
            adapters.validate_native_boundary_mapping('{"boundaries":{"s1":"不要交","s2":"明白了。"}}', WINDOW, native["native_text"])

    def test_native_anchor_grammar_can_abstain_without_any_unique_boundary(self):
        grammar = adapters.native_boundary_mapping_grammar(WINDOW, "aaaa")
        self.assertTrue(grammar.startswith("root ::= unresolved\n"))

    def test_grouped_mapping_keeps_merged_scored_text_once(self):
        native = "是。不要交出去，明白了。"
        groups = adapters.source_mapping_groups(WINDOW)
        self.assertEqual([(g["source_ids"], g["scored"]) for g in groups], [(["s0"], False), (["s1", "s2"], True)])
        output, provenance = adapters.validate_grouped_mapping('{"boundaries":{"g1":"不要交出"}}', WINDOW, native)
        self.assertEqual(output, [{"source_ids": ["s1", "s2"], "text": "不要交出去，明白了。", "target_spans": [[2, len(native)]]}])
        self.assertEqual("".join(g["text"] for g in provenance), native)
        self.assertEqual(provenance[0]["source_ids"], ["s0"])
        self.assertFalse(provenance[0]["scored"])
        client = FakeClient([{"content": '{"boundaries":{"g1":"不要交出"}}'}])
        row = run_window(client, WINDOW, "translategemma", dict(SETTINGS, mapping_recipe="native-scored-groups-gbnf-v4"),
                         {"status": "native_delivered", "native_text": native, "generation_seconds": 2.0})
        self.assertEqual(row["status"], "delivered")
        self.assertEqual(row["translations"], {})
        self.assertEqual(row["translation_groups"], output)
        self.assertEqual(row["mapping_groups"], provenance)
        self.assertNotIn("text", row["source_span_to_target_span"][0])
        self.assertIn("Find only boundaries BETWEEN groups", client.prompts[0])

    def test_grouped_mapping_noncontiguous_scored_runs_exclude_all_context(self):
        window = dict(WINDOW, context=[{"id": f"s{i}", "text": "合成台词。"} for i in range(5)], translate_ids=["s3", "s1"])
        native = "前面。我走了。中间。我来了。后面。"
        boundaries = {"g1": "我走了。", "g2": "中间。我", "g3": "我来了。", "g4": "后面。"}
        scored, all_groups = adapters.validate_grouped_mapping(json.dumps({"boundaries": boundaries}, ensure_ascii=False), window, native)
        self.assertEqual([g["source_ids"] for g in scored], [["s1"], ["s3"]])
        self.assertEqual([g["text"] for g in scored], ["我走了。", "我来了。"])
        self.assertEqual([g["scored"] for g in all_groups], [False, True, False, True, False])
        self.assertEqual("".join(g["text"] for g in all_groups), native)
        self.assertEqual([s for g in all_groups for s in g["source_ids"]], [f"s{i}" for i in range(5)])
        with self.assertRaises(ValueError):
            adapters.validate_grouped_mapping('{"boundaries":{"g1":"我走了。"}}', window, native)

    def test_grouped_mapping_all_scored_is_single_complete_group(self):
        window = dict(WINDOW, translate_ids=["s2", "s0", "s1"])
        native = "整段合成译文。"
        result, provenance = adapters.validate_grouped_mapping('{"boundaries":{}}', window, native)
        self.assertEqual(result, [{"source_ids": ["s0", "s1", "s2"], "text": native, "target_spans": [[0, len(native)]]}])
        self.assertEqual(len(provenance), 1)

    def test_retry_does_not_drop_failed_attempt(self):
        client = FakeClient([OSError("transport failed"), {"content": '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}'}])
        row = run_window(client, WINDOW, "hy-mt2", SETTINGS)
        self.assertEqual(row["status"], "delivered")
        self.assertEqual([a["status"] for a in row["attempts"]], ["failed", "accepted"])
        self.assertEqual(client.prompts[0], client.prompts[1])

    def test_truncation_not_accepted_even_with_valid_json(self):
        response = {"content": '{"translations":{"s1":"不要交出去。","s2":"明白了。"}}', "stopped_limit": True}
        row = run_window(FakeClient([response, response]), WINDOW, "hy-mt2", SETTINGS)
        self.assertEqual(row["status"], "translation_failed")
        self.assertEqual(row["translations"], {})

    def test_native_failure_and_missing_window_stay_failed(self):
        row = run_window(FakeClient([]), WINDOW, "translategemma", SETTINGS, {"status": "translation_failed", "reason": "transport failed", "generation_seconds": 3.0})
        self.assertEqual(row["status"], "translation_failed")
        self.assertEqual(row["elapsed_seconds"], 3.0)

    def test_reference_input_and_overwrite_are_rejected(self):
        root = Path(__file__).resolve().parents[2] / ".local" / "translation-evaluation" / "test-tmp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            target = Path(temp) / "input.jsonl"
            window = dict(WINDOW, reference="SECRET REFERENCE")
            target.write_text(json.dumps(window, ensure_ascii=False) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_inputs(target)
            with self.assertRaises(FileExistsError):
                write_json(target, {})

    def test_no_external_inference(self):
        for url in ("https://127.0.0.1:8080", "http://example.com", "http://user:pass@localhost:8080"):
            with self.assertRaises(ValueError):
                LlamaClient(url)


if __name__ == "__main__":
    unittest.main()
