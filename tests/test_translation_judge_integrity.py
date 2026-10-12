"""Offline accepted-byte integrity and honest legacy baseline tests."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from experiments.translation_judge.integrity import (
    _windows_path, accept_response, canonical_bytes, capture_legacy_baseline,
    inside, resume_success, sha, strict_parse,
)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)
        self.directory = self.root / 'judge-execution/primary/A/synthetic'
        self.attempt = self.directory / 'attempt-1'
        self.attempt.mkdir(parents=True)
        self.raw = self.attempt / 'last-message.txt'
        self.response = self.root / 'primary/A/synthetic.json'
        self.ledger = self.directory / 'job.json'
        self.value = {'window_id': 'synthetic', 'candidate_alias': 'A', 'semantic': 4,
                      'naturalness': 2, 'status': 'scored', 'errors': [],
                      'uncertainties': [], 'summary_zh': '合成测试。'}
        self.raw.write_text(json.dumps(self.value, ensure_ascii=False), encoding='utf-8')
        self.validator_calls = 0

    def tearDown(self):
        self.temp.cleanup()

    def validate(self, value):
        self.validator_calls += 1
        if value['window_id'] != 'synthetic' or value['candidate_alias'] != 'A' or type(value['semantic']) is not int or not 0 <= value['semantic'] <= 4:
            raise ValueError('Invalid synthetic judgment')
        return value

    def save_state(self, legacy=False):
        fields = accept_response(self.raw, self.response, self.validate)
        state = {'job_id': 'primary/A/synthetic', 'fingerprint': 'unchanged-fingerprint',
                 'response': str(self.response), 'status': 'succeeded',
                 'requested_model': 'gpt-6.1-sol', 'requested_effort': 'high', 'attempts': [{'attempt': 1}], **fields}
        if legacy:
            for key in ('accepted_raw_response_sha256', 'response_sha256', 'accepted_canonical_snapshot', 'resume_integrity_version', 'hash_provenance'):
                state.pop(key)
        self.ledger.write_bytes(canonical_bytes(state))
        return state

    def resume(self, state):
        return resume_success(state, self.ledger, self.response, self.validate)

    def test_new_acceptance_and_resume_do_not_rewrite_evidence(self):
        state = self.save_state()
        raw_bytes, canonical, ledger = self.raw.read_bytes(), self.response.read_bytes(), self.ledger.read_bytes()
        result = self.resume(state)
        self.assertTrue(result['resumed'])
        self.assertFalse(result['canonical_restored'])
        self.assertEqual(state['accepted_raw_response_sha256'], sha(raw_bytes))
        self.assertEqual(state['response_sha256'], sha(canonical))
        self.assertEqual((raw_bytes, canonical, ledger), (self.raw.read_bytes(), self.response.read_bytes(), self.ledger.read_bytes()))

    def test_exact_restore_without_new_attempt(self):
        state = self.save_state()
        original = self.response.read_bytes()
        self.response.unlink()
        self.assertTrue(self.resume(state)['canonical_restored'])
        self.assertEqual(self.response.read_bytes(), original)
        self.assertEqual([path.name for path in self.directory.glob('attempt-*')], ['attempt-1'])

    def test_valid_schema_raw_tamper_refuses_without_overwrite(self):
        state = self.save_state()
        canonical = self.response.read_bytes()
        self.raw.write_bytes(canonical_bytes({**self.value, 'semantic': 3}))
        with self.assertRaisesRegex(ValueError, 'raw response changed'):
            self.resume(state)
        self.assertEqual(self.response.read_bytes(), canonical)

    def test_canonical_whitespace_tamper_refuses_without_overwrite(self):
        state = self.save_state()
        self.response.write_bytes(self.response.read_bytes() + b' ')
        tampered = self.response.read_bytes()
        with self.assertRaisesRegex(ValueError, 'canonical response changed'):
            self.resume(state)
        self.assertEqual(self.response.read_bytes(), tampered)

    def test_missing_raw_or_changed_restore_snapshot_refuses(self):
        state = self.save_state()
        saved_raw = self.raw.read_bytes()
        self.raw.unlink()
        with self.assertRaises(OSError):
            self.resume(state)
        self.raw.write_bytes(saved_raw)
        self.response.unlink()
        Path(state['accepted_canonical_snapshot']).write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            self.resume(state)
        self.assertFalse(self.response.exists())

    def test_legacy_default_refuses_and_explicit_baseline_does_not_forge_ledger(self):
        state = self.save_state(legacy=True)
        original_ledger = self.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Legacy success lacks original hashes'):
            self.resume(state)
        baseline = capture_legacy_baseline(self.ledger)
        self.assertFalse(baseline['original_acceptance_hashes_available'])
        self.assertIn('observed_raw_response_sha256', baseline)
        self.assertNotIn('accepted_raw_response_sha256', baseline)
        self.assertEqual(self.ledger.read_bytes(), original_ledger)
        result = self.resume(state)
        self.assertTrue(result['resumed'])
        self.assertFalse(result['resume_integrity_evidence']['original_acceptance_hashes_available'])
        self.assertEqual(self.ledger.read_bytes(), original_ledger)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            capture_legacy_baseline(self.ledger)

    def test_legacy_missing_pair_never_invents_restore_before_baseline(self):
        state = self.save_state(legacy=True)
        self.response.unlink()
        with self.assertRaises(OSError):
            capture_legacy_baseline(self.ledger)
        self.assertFalse((self.directory / 'legacy-resume-baseline').exists())

    def test_legacy_disagreeing_pair_refuses_migration(self):
        self.save_state(legacy=True)
        self.response.write_bytes(canonical_bytes({**self.value, 'semantic': 3}))
        with self.assertRaisesRegex(ValueError, 'pair disagrees'):
            capture_legacy_baseline(self.ledger)

    def test_legacy_ledger_change_and_pair_tamper_refuse(self):
        state = self.save_state(legacy=True)
        original_ledger = self.ledger.read_bytes()
        capture_legacy_baseline(self.ledger)
        self.ledger.write_bytes(original_ledger + b' ')
        with self.assertRaisesRegex(ValueError, 'ledger/fingerprint identity changed'):
            self.resume(state)
        self.ledger.write_bytes(original_ledger)
        self.raw.write_bytes(self.raw.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'raw response changed'):
            self.resume(state)

    def test_legacy_exact_observed_byte_restore_remains_retrospective(self):
        state = self.save_state(legacy=True)
        # Legacy observed canonical formatting may differ from today's serializer.
        self.response.write_text(json.dumps(self.value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        observed = self.response.read_bytes()
        capture_legacy_baseline(self.ledger)
        self.response.unlink()
        result = self.resume(state)
        self.assertTrue(result['canonical_restored'])
        self.assertEqual(self.response.read_bytes(), observed)
        self.assertFalse(result['resume_integrity_evidence']['original_acceptance_hashes_available'])

    def test_partial_hash_metadata_is_not_legacy_and_preserves_original(self):
        state = self.save_state()
        state.pop('response_sha256')
        self.ledger.write_bytes(canonical_bytes(state))
        with self.assertRaisesRegex(ValueError, 'Incomplete accepted hash'):
            self.resume(state)
        with self.assertRaisesRegex(ValueError, 'Original hash metadata exists'):
            capture_legacy_baseline(self.ledger)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows path namespace regression')
    def test_extended_drive_accepted_raw_and_snapshot_resume_without_evidence_rewrite(self):
        state = self.save_state()
        state.update(accepted_raw_response='\\\\?\\' + str(self.raw.resolve()),
                     accepted_canonical_snapshot='\\\\?\\' + str(Path(state['accepted_canonical_snapshot']).resolve()),
                     response='\\\\?\\' + str(self.response.resolve()))
        self.ledger.write_bytes(canonical_bytes(state))
        ledger, raw, canonical = self.ledger.read_bytes(), self.raw.read_bytes(), self.response.read_bytes()
        result = self.resume(state)
        self.assertTrue(result['resumed'])
        self.assertEqual(result['accepted_raw_response'], state['accepted_raw_response'])
        self.assertEqual((self.ledger.read_bytes(), self.raw.read_bytes(), self.response.read_bytes()), (ledger, raw, canonical))
        self.response.unlink()
        self.assertTrue(self.resume(state)['canonical_restored'])
        self.assertEqual(self.response.read_bytes(), canonical)
        self.assertEqual(self.ledger.read_bytes(), ledger)

    def test_windows_drive_and_unc_namespace_equivalence_without_unc_io(self):
        for plain, extended in ((r'D:\scope\job\attempt\raw.txt', r'\\?\d:\scope\job\attempt\raw.txt'),
                                (r'\\server\share\scope\job\attempt\raw.txt', r'\\?\UNC\SERVER\share\scope\job\attempt\raw.txt')):
            with self.subTest(plain=plain):
                self.assertEqual(_windows_path(plain), _windows_path(extended))
        root = _windows_path(r'\\?\UNC\server\share\scope\job')
        self.assertTrue(_windows_path(r'\\server\share\scope\job\attempt\raw.txt').is_relative_to(root))
        self.assertTrue(_windows_path(r'\\?\UNC\server\share\scope\job\attempt\raw.txt').is_relative_to(root))
        for value in (r'\\other\share\scope\job\raw.txt', r'\\server\other\scope\job\raw.txt',
                      r'\\?\UNC\server\share\scope\job-sibling\raw.txt', r'D:\scope\job\raw.txt'):
            with self.subTest(value=value):
                self.assertFalse(_windows_path(value).is_relative_to(root))

    def test_windows_device_globalroot_and_relative_namespace_prefixes_are_refused(self):
        for value in (r'\\.\PhysicalDrive0', r'\\.\pipe\judge', r'\\?\GLOBALROOT\Device\HarddiskVolume1\job',
                      r'\\?\Volume{123}\job', r'\\?\D:relative\raw.txt', r'\\?\relative\raw.txt',
                      r'\??\D:\scope\job', r'\\??\D:\scope\job', r'\\?\UNC\server',
                      '\\\\?\\UNC\\server\\', r'\\?\UNC\..\share\job', r'\\server'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _windows_path(value)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows containment regression')
    def test_extended_namespace_preserves_true_parent_and_sibling_escape_rejection(self):
        for path in (self.directory / '..' / 'outside.txt', self.directory.with_name('synthetic-sibling') / 'raw.txt'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'escapes job directory'):
                inside(self.directory, Path('\\\\?\\' + str(path)))
        self.assertEqual(inside(Path('\\\\?\\' + str(self.directory.resolve())), self.raw), self.raw.resolve())
        state = self.save_state()
        state['accepted_raw_response'] = '\\\\?\\' + str(self.directory / '..' / 'outside.txt')
        with self.assertRaisesRegex(ValueError, 'escapes job directory'):
            self.resume(state)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows long-path regression')
    def test_long_review_namespace_resume_and_snapshot_restore(self):
        deep = self.directory / ('review-' + 'x' * 64) / ('scope-' + 'y' * 64) / ('job-' + 'z' * 64)
        self.directory = deep
        self.attempt = deep / 'attempt-1'
        self.attempt.mkdir(parents=True)
        self.raw = self.attempt / 'last-message.txt'
        self.ledger = deep / 'job.json'
        self.raw.write_bytes(canonical_bytes(self.value))
        self.assertGreater(len(str(self.raw)), 260)
        state = self.save_state()
        state['accepted_raw_response'] = '\\\\?\\' + str(self.raw)
        state['accepted_canonical_snapshot'] = '\\\\?\\' + str(Path(state['accepted_canonical_snapshot']))
        self.ledger.write_bytes(canonical_bytes(state))
        before = self.ledger.read_bytes()
        self.assertTrue(self.resume(state)['resumed'])
        self.response.unlink()
        self.assertTrue(self.resume(state)['canonical_restored'])
        self.assertEqual(self.ledger.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
