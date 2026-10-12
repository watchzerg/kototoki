"""Whole-source segmentation and parent-lock checks without inference assets."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from . import segment
from experiments.w0_demo.vad_candidates import chunk_intervals
from experiments.x0_demo.chunks import RATE, make_chunk


class SizedAudio:
    def __len__(self):
        return 605 * RATE + 1


class SegmentationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.out = self.root / '.local/fullfilm-comparison/test-v1/segmentation/film'
        self.job_path = self.root / 'job.json'
        self.audio = SizedAudio()
        self.identity = {'file_sha256': 'file-hash', 'pcm_sha256': 'pcm-hash', 'samples': len(self.audio)}
        self.job = {'clip': {'id': 'film', 'audio': 'fake.wav', 'audio_sha256': 'file-hash',
                            'pcm_sha256': 'pcm-hash', 'offset': 0,
                            'scoring_bins': [{'start': 0, 'end': 300}]},
                    'segmentation': 'cut-merge', 'source_sha256': {},
                    'candidate': {'model': 'fake-model', 'device': 'cuda:0', 'revision': 'frozen'}}
        lock = self.root / '.local/gpu.lock'
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({'pid': 1234}), encoding='utf-8')
        self.stack.enter_context(patch.object(segment, 'ROOT', self.root))
        self.stack.enter_context(patch.dict(os.environ, {'KOTOTOKI_FULLFILM_PARENT_PID': '1234'}))
        self.reader = self.stack.enter_context(patch.object(segment, 'read_audio', return_value=(self.audio, self.identity)))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.chunks = [make_chunk(0, 5 * RATE)]
        self.chunks.extend(make_chunk(start, min(start + 30 * RATE, len(self.audio)))
                           for start in range(5 * RATE, len(self.audio), 30 * RATE))

    def invoke(self):
        self.job_path.write_text(json.dumps(self.job), encoding='utf-8')
        with patch.object(segment.sys, 'argv', ['segment', '--job', str(self.job_path), '--out', str(self.out)]):
            segment.main()

    def test_cut_merge_receives_entire_film_once_and_crosses_scoring_bin(self):
        with patch.object(segment, 'cut_merge_chunks', return_value=self.chunks) as cut:
            self.invoke()
        cut.assert_called_once_with(self.audio)
        plan = json.loads((self.out / 'plan.json').read_text(encoding='utf-8'))
        self.assertEqual(plan['chunks'], self.chunks)
        self.assertEqual(plan['retained_samples'], len(self.audio))
        self.assertEqual(plan['removed_samples'], 0)
        self.assertTrue(any(c['start_sample'] < 300 * RATE < c['end_sample'] for c in plan['chunks']))
        self.assertEqual(plan['chunks'][-1]['end_sample'], len(self.audio))
        self.assertNotIn('scoring_bins', plan)

    def test_pyannote_receives_entire_film_once_and_keeps_source_gap(self):
        self.job['segmentation'] = 'pyannote-current'
        chunks = [make_chunk(299 * RATE, 301 * RATE), make_chunk(600 * RATE, len(self.audio))]
        detector = Mock(metadata={'device': 'cuda:0'})
        detector.segment.return_value = chunks
        torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=Mock()))
        with patch('experiments.w0_demo.vad_candidates.create_vad', return_value=detector) as create, \
                patch.dict(segment.sys.modules, {'torch': torch}):
            self.invoke()
        detector.segment.assert_called_once_with(self.audio)
        detector.close.assert_called_once()
        self.assertEqual(create.call_args.kwargs['device'], 'cuda:0')
        plan = json.loads((self.out / 'plan.json').read_text(encoding='utf-8'))
        self.assertEqual(plan['chunks'], chunks)
        self.assertEqual(plan['removed_samples'], len(self.audio) - sum(c['end_sample'] - c['start_sample'] for c in chunks))

    def test_pyannote_nextafter_seconds_are_canonicalized_from_integer_bounds(self):
        self.job['segmentation'] = 'pyannote-current'
        chunks, metadata = chunk_intervals([[1001, 112001]], len(self.audio), unit='samples')
        self.assertNotEqual(chunks[0]['start'], 1001 / RATE)
        expected = [{**chunk, 'start': chunk['start_sample'] / RATE,
                     'end': chunk['end_sample'] / RATE} for chunk in chunks]
        detector = Mock(metadata=metadata)
        detector.segment.return_value = chunks
        torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=Mock()))
        with patch('experiments.w0_demo.vad_candidates.create_vad', return_value=detector), \
                patch.dict(segment.sys.modules, {'torch': torch}):
            self.invoke()
        detector.segment.assert_called_once_with(self.audio)
        detector.close.assert_called_once()
        plan = json.loads((self.out / 'plan.json').read_text(encoding='utf-8'))
        self.assertEqual(plan['chunks'], expected)
        self.assertEqual(plan['chunks'][0]['start_sample'], 1001)
        self.assertEqual(plan['chunks'][0]['end_sample'], 112001)
        self.assertEqual(plan['chunks'][0]['segments'], chunks[0]['segments'])
        self.assertEqual(plan['metadata'], metadata)
        self.assertEqual(plan['retained_samples'], 111000)
        self.assertEqual(plan['removed_samples'], len(self.audio) - 111000)

    def test_wrong_parent_lock_stops_before_audio_or_output(self):
        with patch.dict(os.environ, {'KOTOTOKI_FULLFILM_PARENT_PID': '9999'}):
            with self.assertRaisesRegex(RuntimeError, 'Parent must own'):
                self.invoke()
        self.reader.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_existing_failed_output_is_not_overwritten(self):
        self.out.mkdir(parents=True)
        failure = self.out / 'failure.json'
        failure.write_bytes(b'original failure evidence')
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(failure.read_bytes(), b'original failure evidence')
        self.reader.assert_not_called()

    def test_changed_pcm_records_failure_and_never_segments(self):
        self.job['clip']['pcm_sha256'] = 'changed'
        with patch.object(segment, 'cut_merge_chunks') as cut:
            with self.assertRaisesRegex(ValueError, 'input changed'):
                self.invoke()
        cut.assert_not_called()
        self.assertFalse((self.out / 'plan.json').exists())
        failure = json.loads((self.out / 'failure.json').read_text(encoding='utf-8'))
        self.assertEqual(failure['type'], 'ValueError')

    def test_invalid_or_missing_tail_chunk_plan_is_rejected(self):
        with patch.object(segment, 'cut_merge_chunks', return_value=self.chunks[:-1]):
            with self.assertRaisesRegex(ValueError, 'source tail'):
                self.invoke()
        self.assertFalse((self.out / 'plan.json').exists())

    def test_detector_is_closed_on_failure(self):
        self.job['segmentation'] = 'pyannote-current'
        detector = Mock(metadata={'device': 'cuda:0'})
        detector.segment.side_effect = RuntimeError('fake detector error')
        torch = SimpleNamespace(cuda=SimpleNamespace(synchronize=Mock()))
        with patch('experiments.w0_demo.vad_candidates.create_vad', return_value=detector), \
                patch.dict(segment.sys.modules, {'torch': torch}):
            with self.assertRaisesRegex(RuntimeError, 'fake detector error'):
                self.invoke()
        detector.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
