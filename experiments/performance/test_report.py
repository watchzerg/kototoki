"""Offline observable guards for failed runs, cache reuse and repeat identity."""
import json
from pathlib import Path
import tempfile
import unittest
import wave

from experiments.performance.report import build_report, cache_classification, file_hash, gpu_samples

ROOT = Path(__file__).resolve().parents[2]


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        private = ROOT / '.local/analysis/performance-dev'
        private.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=private)
        self.root = Path(self.temporary.name)
        self.audio = self.root / 'synthetic.wav'
        with wave.open(str(self.audio), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b'\0' * 64000)

    def tearDown(self):
        self.temporary.cleanup()

    def run_fixture(self, name, *, status='completed', cached=False, text='私有合成文字', units=None, beam=5):
        directory = self.root / name
        directory.mkdir()
        manifest = {'id': name, 'audio': str(self.audio), 'audio_sha256': file_hash(self.audio),
                    'status': status, 'returncode': 0 if status == 'completed' else 1,
                    'reference_unchanged': True, 'fresh_subprocess': True, 'wall_seconds': 4,
                    'source_sha256': {'adapter.py': 'fixedsource'}, 'platform': 'Windows', 'harness_python': '3.12',
                    'gpu_samples': [
                        {'elapsed_seconds': 0.1, 'returncode': 0, 'csv': '2026/10/04 01:00:00, NVIDIA RTX 5080, 616.92, 2100, 0, 30'},
                        {'elapsed_seconds': 1.2, 'returncode': 0, 'csv': '2026/10/04 01:00:01, NVIDIA RTX 5080, 616.92, 8000, 90, 220'}]}
        candidate = {'text': text, 'units': units if units is not None else [
                     {'char_start': 0, 'char_end': 2, 'start': 0.1, 'end': 0.4, 'granularity': 'word',
                      'time_source': 'native', 'status': 'ok'}],
                     'route': 'test-complete', 'config': {'beam': beam}, 'models': {'revision': 'fixedmodel'},
                     'cached_inference': cached, 'stages': {'asr_s': 2, 'nested_decoder_s': 1, 'total_s': 3}}
        path = directory / 'manifest.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        (directory / 'result.json').write_text(json.dumps(candidate), encoding='utf-8')
        return path

    def test_six_field_nvidia_query_and_proxy_baseline(self):
        report = build_report([self.run_fixture('fresh')])
        run = report['runs'][0]
        device = run['gpu_sampling']['devices'][0]
        self.assertEqual(device['first_sample_memory_mb_proxy'], 2100)
        self.assertEqual(device['sampled_memory_mb']['max'], 8000)
        self.assertEqual(device['peak_minus_first_sample_mb_proxy'], 5900)
        self.assertAlmostEqual(device['sampling_gap_s']['max'], 1.1)
        self.assertEqual(run['fresh_complete_pipeline_rtf'], 2)
        self.assertEqual(run['stage_measurements']['stages']['total_s'], 3)

    def test_missing_failed_and_unavailable_samples_are_not_zero_measurements(self):
        result = gpu_samples([{'elapsed_seconds': 0, 'returncode': 1, 'csv': ''},
                              {'elapsed_seconds': 1, 'returncode': 0,
                               'csv': 'date, "GPU, quoted", 616.92, N/A, N/A, N/A'}])
        self.assertEqual(result['invalid_query_or_row_count'], 1)
        self.assertEqual(result['devices'][0]['name'], 'GPU, quoted')
        self.assertIsNone(result['devices'][0]['sampled_memory_mb']['max'])

    def test_failed_attempt_retained_without_fresh_rtf(self):
        report = build_report([self.run_fixture('failed', status='failed')])
        self.assertEqual(report['counts']['failed_or_incomplete'], 1)
        self.assertEqual(report['runs'][0]['attempt_wall_per_input_duration'], 2)
        self.assertIsNone(report['runs'][0]['fresh_complete_pipeline_rtf'])

    def test_cached_run_excluded_from_fresh_repeat_statistics(self):
        paths = [self.run_fixture('fresh1'), self.run_fixture('fresh2'), self.run_fixture('cached', cached=True)]
        report = build_report(paths)
        self.assertEqual(report['counts']['all_requested_runs'], 3)
        group = report['repeat_groups'][0]
        self.assertEqual(group['successful_fresh_pipeline_count'], 2)
        self.assertEqual(group['fresh_pipeline_wall_seconds']['n'], 2)
        self.assertEqual(group['fresh_exact_text_hash_count'], 1)
        self.assertEqual(group['fresh_exact_timed_units_hash_count'], 1)

    def test_fa_replay_never_promoted_by_cached_inference_false(self):
        classification = cache_classification({'manifest': {'route': 'crisp-fa-replay', 'cached_inference': False,
                                               'asr_inference_reused': True, 'fa_inference_reused': False}},
                                              {'fresh_subprocess': True})
        self.assertEqual(classification['classification'], 'reused_asr_fresh_fa_component')

    def test_missing_cache_metadata_is_unknown_even_with_new_process(self):
        result = cache_classification({'route': 'test-complete'}, {'fresh_subprocess': True})
        self.assertEqual(result['classification'], 'unknown_inference_freshness')

    def test_changed_audio_sha_excludes_rtf(self):
        path = self.run_fixture('mismatch')
        manifest = json.loads(path.read_text())
        manifest['audio_sha256'] = 'wrong'
        path.write_text(json.dumps(manifest))
        report = build_report([path])
        self.assertFalse(report['runs'][0]['audio']['matches_harness_sha256'])
        self.assertIsNone(report['runs'][0]['attempt_wall_per_input_duration'])

    def test_config_and_source_changes_separate_repeats(self):
        first = self.run_fixture('first')
        second = self.run_fixture('config-changed', beam=1)
        third = self.run_fixture('source-changed')
        manifest = json.loads(third.read_text())
        manifest['source_sha256']['adapter.py'] = 'different'
        third.write_text(json.dumps(manifest))
        report = build_report([first, second, third])
        self.assertEqual(len(report['repeat_groups']), 3)
        self.assertTrue(all(group['repeatability_evidence'] == 'insufficient_fewer_than_two_fresh_outputs'
                            for group in report['repeat_groups']))

    def test_timed_unit_changes_detected_without_transcript_output(self):
        first = self.run_fixture('first')
        second = self.run_fixture('second', units=[{'char_start': 0, 'char_end': 2, 'start': 0.2, 'end': 0.4,
                                                  'granularity': 'word', 'time_source': 'native', 'status': 'ok'}])
        report = build_report([first, second])
        self.assertEqual(report['repeat_groups'][0]['fresh_exact_text_hash_count'], 1)
        self.assertEqual(report['repeat_groups'][0]['fresh_exact_timed_units_hash_count'], 2)
        self.assertNotIn('私有合成文字', json.dumps(report, ensure_ascii=False))

    def test_missing_manifest_and_result_are_retained(self):
        first = self.run_fixture('missing-result')
        (first.parent / 'result.json').unlink()
        report = build_report([first, self.root / 'nonexistent' / 'manifest.json'])
        self.assertEqual(report['counts']['all_requested_runs'], 2)
        self.assertEqual(report['counts']['failed_or_incomplete'], 2)
        self.assertEqual(report['counts']['successful_fresh_pipeline'], 0)

    def test_duplicate_manifest_is_not_another_fresh_repeat(self):
        path = self.run_fixture('single-run')
        report = build_report([path, path, path])
        self.assertEqual(report['counts']['all_requested_runs'], 3)
        self.assertEqual(report['counts']['duplicate_supplied_evidence'], 2)
        group = report['repeat_groups'][0]
        self.assertEqual(group['successful_fresh_pipeline_count'], 1)
        self.assertEqual(group['repeatability_evidence'], 'insufficient_fewer_than_two_fresh_outputs')

    def test_qwen_asr_only_config_is_component_even_with_full_route_name(self):
        result = cache_classification({'backend': 'Q0', 'cache_reused': False, 'config': {'asr_only': True}},
                                      {'fresh_subprocess': True})
        self.assertEqual(result['classification'], 'fresh_component')

    def cross_fixture(self, name, *, asr_beam=5):
        manifest = self.run_fixture(name)
        candidate_path = manifest.parent / 'result.json'
        candidate = json.loads(candidate_path.read_text())
        stage_path = manifest.parent / 'asr.json'
        source_path = manifest.parent / 'snapshot.py'
        source_path.write_text('# fixed executed source\n')
        asr = {'text': 'private stage text', 'units': [], 'backend': 'Q0', 'cache_reused': False,
               'input': {'file_sha256': file_hash(self.audio)}, 'models': {'revision': 'ASR-fixed'},
               'config': {'asr_only': True, 'beam': asr_beam}}
        stage_path.write_text(json.dumps(asr))
        ctc_path = manifest.parent / 'ctc.json'
        ctc_path.write_text(json.dumps({'text': 'private ctc output', 'units': []}))
        candidate.update(route='X0', model_identity={'aligner': 'CTC-fixed'},
                         effective_parameters={'asr_reused': True, 'asr_result': str(stage_path), 'padding': 0},
                         pipeline={'status': 'completed', 'cache_classification': 'fresh_end_to_end',
                                   'new_asr_inference': True, 'new_alignment_inference': True,
                                   'stage_cache': {'asr': 'fresh'}, 'audio_sha256': file_hash(self.audio),
                                   'asr_result': str(stage_path), 'source_files': {
                                       'snapshot.py': {'path': str(source_path), 'sha256': file_hash(source_path)}},
                                   'stages': [{'stage': label, 'status': 'completed', 'returncode': 0,
                                               'output': str(path), 'output_sha256': file_hash(path), 'wall_seconds': 1}
                                              for label, path in [('asr', stage_path), ('ctc', ctc_path)]]})
        candidate_path.write_text(json.dumps(candidate))
        return manifest

    def test_fresh_cross_pipeline_binds_asr_config_normalizes_run_paths(self):
        first, second, changed = self.cross_fixture('cross1'), self.cross_fixture('cross2'), self.cross_fixture('cross3', asr_beam=1)
        report = build_report([first, second, changed])
        self.assertEqual(report['counts']['successful_fresh_pipeline'], 3)
        self.assertEqual(len(report['repeat_groups']), 2)
        self.assertEqual(report['repeat_groups'][0]['successful_fresh_pipeline_count'], 2)
        self.assertIn('pipeline_stages', report['runs'][0]['stage_measurements'])
        self.assertNotIn('private stage text', json.dumps(report))

    def test_changed_cross_asr_artifact_hash_is_not_verified_full_pipeline(self):
        manifest = self.cross_fixture('tampered')
        (manifest.parent / 'asr.json').write_text('{}')
        report = build_report([manifest])
        self.assertEqual(report['runs'][0]['inference']['classification'], 'fresh_pipeline_declared_unverified')
        self.assertIsNone(report['runs'][0]['fresh_complete_pipeline_rtf'])
        self.assertIn('stage_hash_or_execution:asr', report['runs'][0]['issues'])


if __name__ == '__main__':
    unittest.main()
