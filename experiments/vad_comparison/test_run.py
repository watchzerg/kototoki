"""Registry tests independent of inference libraries and private audio."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import run


class RegistryTests(unittest.TestCase):
    def test_initialization_keeps_all_ten_routes_and_all_clips(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = root / '.local/round2/plan.json'
            plan.parent.mkdir(parents=True)
            clips = [{'id': f'clip-{index}'} for index in range(12)]
            plan.write_text(json.dumps({'clips': clips}), encoding='utf-8')
            target = root / 'study.json'
            with patch.object(run, 'ROOT', root), patch.object(run, 'verify_clips', return_value={}):
                study = run.initialize(target, 'test-v1')
            self.assertEqual(len(study['routes']), 10)
            self.assertEqual(sum(len(route['runs']) for route in study['routes']), 120)
            self.assertEqual({slot['status'] for route in study['routes'] for slot in route['runs']}, {'pending'})
            self.assertFalse(study['terminal'])
            self.assertEqual(json.loads(target.read_text(encoding='utf-8')), study)

    def test_input_identity_rejects_changed_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fixture'
            path.write_bytes(b'synthetic')
            clip = {}
            for name in ('audio', 'reference', 'source_audio', 'source_srt'):
                clip[name] = str(path)
                clip[f'{name}_sha256'] = run.sha256(path)
            run.verify_clips([clip])
            clip['reference_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'Frozen input changed'):
                run.verify_clips([clip])


if __name__ == '__main__':
    unittest.main()
