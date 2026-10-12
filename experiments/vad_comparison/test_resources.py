"""Offline resource boundary checks; no model imports or inference."""
from __future__ import annotations

import os
import json
import hashlib
import struct
from pathlib import Path
import sys
import tempfile
import unittest

from .resources import chunks_digest, compare_chunks, execute, memory_sample, verify_input, write

TEST_TEMP = Path(__file__).resolve().parents[2] / '.local/vad-comparison/resource-tests'


class ResourceTests(unittest.TestCase):
    def test_frozen_identity_uses_pcm16_not_normalized_float32(self):
        pcm16 = struct.pack('<hhh', -32768, 0, 32767)
        floats = struct.pack('<fff', -1, 0, 32767/32768)
        raw_hash = hashlib.sha256(pcm16).hexdigest()
        float_hash = hashlib.sha256(floats).hexdigest()
        identity = {'file_sha256': 'wav', 'pcm_sha256': raw_hash,
                    'duration_s': 3/16000, 'sample_rate': 16000, 'channels': 1}
        clip = {'audio_sha256': 'wav', 'pcm_sha256': raw_hash, 'duration': 3/16000}
        self.assertNotEqual(raw_hash, float_hash)
        verify_input(identity, clip)
        with self.assertRaisesRegex(ValueError, 'Frozen clip changed'):
            verify_input(dict(identity, pcm_sha256=float_hash), clip)
        with self.assertRaisesRegex(ValueError, 'Frozen clip changed'):
            verify_input(dict(identity, file_sha256='modified'), clip)

    def test_comparison_requires_same_source_identity(self):
        chunks = [{'start': 0, 'end': 1, 'segments': [[0, 1]]}]
        result = {'input': {'file_sha256': 'wav', 'pcm_sha256': 'pcm'},
                  'offset_s': 3.5, 'chunks_sha256': chunks_digest(chunks)}
        TEST_TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            path = Path(directory) / 'manifest.json'
            write(path, dict(result, chunks=chunks))
            self.assertTrue(compare_chunks(result, path)['chunks_equal'])
            write(path, dict(result, chunks=chunks, offset_s=0))
            with self.assertRaisesRegex(ValueError, 'identity or offset'):
                compare_chunks(result, path)

    def test_chunk_comparison_preserves_integer_boundaries(self):
        first = [{'start': 0., 'end': 1., 'start_sample': 0, 'end_sample': 16000}]
        second = [dict(first[0], end_sample=15999)]
        self.assertNotEqual(chunks_digest(first), chunks_digest(second))

    @unittest.skipUnless(os.name == 'nt', 'native Windows measurement boundary')
    def test_owned_process_measurement(self):
        self.assertGreater(memory_sample()['peak_working_set_bytes'], 0)
        TEST_TEMP.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TEST_TEMP) as directory:
            cost = execute([sys.executable, '-c',
                            'import time,json; from experiments.vad_comparison.resources import memory_sample; '
                            'data=bytearray(b"x"*(8*1024*1024)); time.sleep(.2); '
                            'print(json.dumps(memory_sample()))'], Path(directory))
            self.assertEqual(cost['exit_code'], 0)
            self.assertGreater(cost['memory_sample_count'], 0)
            self.assertGreater(cost['observed_lifetime_peak_working_set_bytes'], 0)
            actual = json.loads((Path(directory) / 'stdout.log').read_text(encoding='utf-8'))
            self.assertGreater(actual['peak_working_set_bytes'], 8*1024*1024)
            self.assertGreater(cost['full_process_wall_s'], .2)
            self.assertTrue((Path(directory) / 'process-cost.json').is_file())


if __name__ == '__main__':
    unittest.main()
