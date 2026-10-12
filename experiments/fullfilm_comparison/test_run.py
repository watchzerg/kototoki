"""Offline subprocess-boundary checks for immutable full-film batch execution."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import run


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.folder = self.root / '.local/fullfilm-comparison/test-v1'
        self.corpus = self.root / 'corpus.json'
        self.candidates = self.root / 'candidates.json'
        run.write(self.corpus, {'clips': [{'id': 'film-ii'}, {'id': 'film-iii'}]})
        run.write(self.candidates, {'candidates': {'pyannote-current': {
            'device': 'cuda:0', 'status': 'ready', 'python': 'fake-python'}}})
        self.stack.enter_context(patch.object(run, 'ROOT', self.root))
        self.stack.enter_context(patch.object(run, 'source_paths', return_value=[]))
        self.stack.enter_context(patch.object(run, 'verify_clips', return_value={'ok': True}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.calls = []
        self.asr_code = 0
        self.align_status = 'ok'
        self.segment_code = 0
        self.stack.enter_context(patch.object(run, 'execute', side_effect=self.fake_execute))

    def invoke(self, *extra):
        argv = ['fullfilm', '--study-id', 'test-v1', '--corpus', str(self.corpus),
                '--candidates', str(self.candidates), *extra]
        with patch.object(run.sys, 'argv', argv):
            run.main()

    def fake_execute(self, command, prefix, environment):
        lock = run.read(self.root / '.local/gpu.lock')
        self.assertEqual(lock['pid'], os.getpid())
        self.assertEqual(environment['KOTOTOKI_FULLFILM_PARENT_PID'], str(os.getpid()))
        job = run.read(Path(command[command.index('--job') + 1]))
        out = Path(command[command.index('--out') + 1])
        phase = 'segment' if command[2].endswith('.segment') else command[3]
        self.calls.append((phase, job, out))
        code = self.segment_code if phase == 'segment' else self.asr_code if phase == 'asr' else 0
        if phase == 'segment' and code == 0:
            run.write(out / 'plan.json', {'clip_id': job['clip']['id'], 'chunks': []})
        elif phase == 'asr' and code in (0, 2):
            run.write(out / 'asr.json', {'status': 'partial' if code else 'ok', 'records': []})
        elif phase == 'align':
            self.assertEqual(run.sha256(Path(job['asr_stage_path'])), job['asr_stage_sha256'])
            run.write(out / 'alignment.json', {'status': self.align_status})
        return {'command': command, 'pid': 1234, 'exit_code': code, 'wall_s': 0.1}

    def test_four_routes_both_films_share_one_plan_per_strategy_and_parent_lock(self):
        self.invoke()
        study = run.read(self.folder / 'study.json')
        self.assertTrue(study['terminal'])
        self.assertEqual(len([c for c in self.calls if c[0] == 'segment']), 4)
        self.assertEqual(len([c for c in self.calls if c[0] == 'asr']), 8)
        self.assertEqual(len([c for c in self.calls if c[0] == 'align']), 8)
        for strategy in run.STRATEGIES:
            routes = [r for r in study['routes'] if r['segmentation'] == strategy]
            for left, right in zip(routes[0]['runs'], routes[1]['runs']):
                self.assertEqual(left['plan_path'], right['plan_path'])
                self.assertEqual(left['plan_sha256'], right['plan_sha256'])
        for phase, job, _ in self.calls:
            self.assertNotIn('scoring_bins', job)
            self.assertNotIn('excluded_bins', job)
        self.assertFalse((self.root / '.local/gpu.lock').exists())

    def test_partial_asr_exit_two_still_aligns_and_is_retained(self):
        self.asr_code, self.align_status = 2, 'partial'
        self.invoke()
        study = run.read(self.folder / 'study.json')
        self.assertEqual(len([c for c in self.calls if c[0] == 'align']), 8)
        self.assertTrue(study['terminal'])
        self.assertEqual({s['status'] for r in study['routes'] for s in r['runs']}, {'partial'})

    def test_failed_asr_no_alignment_no_retry_and_remaining_routes_attempted(self):
        self.asr_code = 1
        self.invoke()
        self.assertEqual(len([c for c in self.calls if c[0] == 'asr']), 8)
        self.assertEqual(len([c for c in self.calls if c[0] == 'align']), 0)
        before = {p: p.read_bytes() for p in self.folder.glob('runs/*/asr-job.json')}
        self.calls.clear()
        self.invoke()
        self.assertEqual(self.calls, [])
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        study = run.read(self.folder / 'study.json')
        self.assertTrue(study['terminal'])
        self.assertEqual({s['status'] for r in study['routes'] for s in r['runs']}, {'invocation_failed'})

    def test_failed_segmentation_is_not_retried(self):
        self.segment_code = 1
        self.invoke()
        self.assertEqual(len(self.calls), 4)
        self.calls.clear()
        self.invoke()
        self.assertEqual(self.calls, [])
        study = run.read(self.folder / 'study.json')
        self.assertEqual({v['status'] for v in study['segmentation_runs'].values()}, {'failed'})

    def test_route_selection_continues_pending_routes_with_same_frozen_plan(self):
        self.invoke('--routes', 'w0-cut-merge', '--clips', 'film-ii')
        study = run.read(self.folder / 'study.json')
        self.assertFalse(study['terminal'])
        plan = study['segmentation_runs']['cut-merge-film-ii']['manifest_path']
        self.calls.clear()
        self.invoke('--routes', 'x0-cut-merge', '--clips', 'film-ii')
        self.assertEqual([c[0] for c in self.calls], ['asr', 'align'])
        self.assertEqual(self.calls[0][1]['plan_path'], plan)

    def test_interrupted_running_slot_requires_inspection_and_never_retries(self):
        self.folder.mkdir(parents=True)
        study = run.initialize(self.folder, self.corpus, self.candidates)
        study['routes'][0]['runs'][0]['status'] = 'running'
        run.write(self.folder / 'study.json', study)
        before = (self.folder / 'study.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.invoke()
        self.assertEqual(self.calls, [])
        self.assertEqual(before, (self.folder / 'study.json').read_bytes())

    def test_changed_frozen_plan_prevents_new_inference(self):
        self.invoke('--routes', 'w0-cut-merge', '--clips', 'film-ii')
        study = run.read(self.folder / 'study.json')
        Path(study['segmentation_runs']['cut-merge-film-ii']['manifest_path']).write_bytes(b'changed')
        self.calls.clear()
        with self.assertRaisesRegex(RuntimeError, 'plan changed'):
            self.invoke('--routes', 'x0-cut-merge', '--clips', 'film-ii')
        self.assertEqual(self.calls, [])

    def test_active_lock_prevents_study_registry_writes(self):
        with run.gpu_lock(self.root / '.local/gpu.lock', 'other-controller'):
            with self.assertRaises(FileExistsError):
                self.invoke()
            self.assertFalse((self.folder / 'study.json').exists())


if __name__ == '__main__':
    unittest.main()
