"""Offline resume guards: incomplete attempts must never become skipped work."""

import json
from pathlib import Path
import tempfile
import unittest

from batch_state import EXE_HASH, REFERENCE_HASH, check
from run import PINS, ROOT, sha256


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.local/cache/crisp')
        self.root = Path(self.directory.name)
        self.audio = self.root / 'audio.wav'
        self.audio.write_bytes(b'private synthetic input identity fixture')
        self.result = self.root / 'result.json'
        self.harness = {'status': 'completed', 'returncode': 0, 'reference_unchanged': True,
                        'reference_sha256_before': REFERENCE_HASH, 'reference_sha256_after': REFERENCE_HASH,
                        'audio_sha256': sha256(self.audio)}
        self.data = {'text': 'synthetic', 'native': {'transcription': [{'text': 'synthetic'}]},
                     'manifest': {'status': 'ok', 'route': 'crisp-qwen-f16-cli-asr-only', 'pins': PINS,
                     'input': {'sha256': sha256(self.audio)}, 'binary_sha256': EXE_HASH,
                     'config': {'source_offset_s': 10, 'gpu_backend': 'vulkan', 'device': 0,
                                'language': 'ja', 'temperature': 0, 'seed': 42, 'max_new_tokens': 512,
                                'threads': 4, 'chunk_seconds': 30, 'chunk_overlap': 3.0, 'vad': True,
                                'energy_gate': True, 'native_writer_split_on_punct': False,
                                'aligner_executed': False}, 'vad_sha256': PINS['vad']['sha256'],
                     'device_evidence': {'gpu_only_contexts_verified': True},
                     'model_hashes': {'asr': PINS['asr']['sha256']}}}

    def tearDown(self):
        self.directory.cleanup()

    def write(self):
        self.result.write_text(json.dumps(self.data), encoding='utf-8')
        (self.root / 'manifest.json').write_text(json.dumps(self.harness), encoding='utf-8')

    def test_matching_completed_nonempty_identity_is_reusable(self):
        self.write()
        self.assertEqual(check(self.result, self.audio, 10, 'asr', True, None), [])

    def test_empty_failed_attempt_never_skipped(self):
        self.data['text'] = ''
        self.harness['status'] = 'failed'
        self.write()
        errors = check(self.result, self.audio, 10, 'asr', True, None)
        self.assertIn('failed_or_empty_prediction', errors)
        self.assertIn('harness_not_completed_and_reference_preserved', errors)

    def test_changed_offset_or_vad_is_not_same_configuration(self):
        self.write()
        errors = check(self.result, self.audio, 11, 'asr', False, None)
        self.assertIn('config_source_offset_s', errors)
        self.assertIn('config_vad', errors)

    def test_replaced_audio_is_not_reused(self):
        self.write()
        self.audio.write_bytes(b'different input')
        self.assertIn('asr_asset_identity', check(self.result, self.audio, 10, 'asr', True, None))

    def test_reference_identity_and_gpu_evidence_are_required(self):
        self.harness['reference_sha256_after'] = 'changed'
        self.data['manifest']['device_evidence']['gpu_only_contexts_verified'] = False
        self.write()
        errors = check(self.result, self.audio, 10, 'asr', True, None)
        self.assertIn('reference_identity', errors)
        self.assertIn('asr_gpu_proof', errors)


if __name__ == '__main__':
    unittest.main()
