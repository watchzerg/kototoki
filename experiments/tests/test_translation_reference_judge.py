"""Offline reference transport integrity, independent review, and retry tests."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.translation_corpus.prepare import packet
from experiments.translation_eval.runner import dump, read_json
from experiments.translation_reference_judge import MODEL, assemble_prompt, digest, response_schema, run_job, validate_response


class ReferenceJudgeTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[2] / '.local/testing-reference-judge'
        base.mkdir(parents=True, exist_ok=True)
        self.previous_tempdir = tempfile.tempdir
        tempfile.tempdir = str(base)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.row = {'id': 'synthetic-reference', 'work': 'synthetic', 'episode_id': 'e1',
                    'scored_ids': ['u1'], 'source_sha256': 'synthetic',
                    'units': [{'id': 'u1', 'ja': '三人です。', 'original_zh': '三个人。',
                               'score': True, 'start': 0, 'end': 1, 'source_events': [1], 'flags': []}]}
        dump(self.root / 'packets/synthetic.json', packet(self.row))
        (self.root / 'reference-review-prompt.md').write_text('Review only original packet.', encoding='utf-8')
        self.job = {'job_id': 'primary|synthetic-reference', 'phase': 'primary', 'window_id': self.row['id'],
                    'packet': 'packets/synthetic.json', 'output': 'reviews/primary/synthetic-reference.json',
                    'model': MODEL, 'reasoning_effort': 'high', 'fresh': True, 'candidate_outputs_allowed': False}
        self.result = {'window_id': self.row['id'], 'status': 'accept', 'translations': {'u1': '三个人。'},
                       'changes': [], 'reason_zh': '原译保留人数。', 'diagnostic_tags': ['number']}
        self.calls = 0
        self.prompts = []

    def tearDown(self):
        self.temp.cleanup()
        tempfile.tempdir = self.previous_tempdir

    def fake(self, args, prompt, cwd, attempt, timeout):
        self.calls += 1
        self.prompts.append(prompt)
        self.assertTrue(cwd.exists())
        self.assertFalse((cwd / 'AGENTS.md').exists())
        self.assertIn('--ephemeral', args)
        self.assertIn('--ignore-user-config', args)
        self.assertIn('model_reasoning_effort="high"', args)
        dump(attempt / 'last-message.txt', self.result)
        return {'returncode': 0, 'transport_status': 'completed', 'elapsed_seconds': .1,
                'returned_models': [], 'returned_efforts': [], 'tool_events': [], 'usage_events': []}

    def invoke(self, job=None, fake=None):
        return run_job(self.root, job or self.job, self.row, 'fake', 'test', 1, fake or self.fake)

    def test_success_resume_restore_and_evidence(self):
        first = self.invoke()
        self.assertEqual(first['status'], 'succeeded')
        self.assertEqual(first['packet_sha256'], digest(self.root / self.job['packet']))
        self.assertTrue(first['returned_identity_unavailable'])
        response = Path(first['response'])
        before = response.read_bytes()
        self.invoke()
        self.assertEqual(self.calls, 1)
        self.assertEqual(before, response.read_bytes())
        response.unlink()
        self.assertTrue(self.invoke()['resumed'])
        self.assertEqual(before, response.read_bytes())

    def test_raw_and_canonical_tampering_refused(self):
        first = self.invoke()
        raw = Path(first['accepted_raw_response'])
        original = raw.read_bytes()
        raw.write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'raw response changed'):
            self.invoke()
        raw.write_bytes(original)
        response = Path(first['response'])
        response.write_bytes(response.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'canonical response changed'):
            self.invoke()

    def test_retry_limit_survives_resume(self):
        def invalid(*args):
            metadata = self.fake(*args)
            dump(args[3] / 'last-message.txt', {'window_id': 'wrong'})
            return metadata
        self.assertEqual(self.invoke(fake=invalid)['status'], 'judge_failed')
        self.assertEqual(self.calls, 2)
        self.assertEqual(self.invoke(fake=invalid)['status'], 'judge_failed')
        self.assertEqual(self.calls, 2)

    def test_review_independent_identical_original_prompt(self):
        self.invoke()
        review = {**self.job, 'phase': 'review', 'job_id': 'review|synthetic-reference',
                  'output': 'reviews/review/synthetic-reference.json'}
        self.invoke(review)
        self.assertEqual(self.prompts[0], self.prompts[1])
        self.assertNotIn(self.result['reason_zh'], self.prompts[1])
        self.assertEqual(self.calls, 2)

    def test_frozen_prompt_or_packet_change_refused(self):
        self.invoke()
        (self.root / 'reference-review-prompt.md').write_text('Changed.', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.invoke()

    def test_wrong_identity_or_tool_events_rejected(self):
        def wrong(*args):
            metadata = self.fake(*args)
            metadata['returned_models'] = ['wrong']
            return metadata
        self.assertEqual(self.invoke(fake=wrong)['status'], 'judge_failed')
        self.assertFalse((self.root / self.job['output']).exists())

    def test_primary_review_prompt_assembly_byte_identical_to_original(self):
        original = (self.root / 'reference-review-prompt.md').read_text(encoding='utf-8')
        data = packet(self.row)
        legacy = original + '\nUse only the supplied packet. Do not use tools, files, memory, external knowledge, or other conversations.\nPACKET:\n' + json.dumps(data, ensure_ascii=False)
        self.assertEqual(assemble_prompt(original, data, self.job), legacy)
        self.assertEqual(assemble_prompt(original, data, {**self.job, 'phase': 'review'}), legacy)

    def test_adjudication_prompt_allows_opinions_and_uses_own_provenance(self):
        source = Path(__file__).resolve().parents[2] / 'experiments/translation_corpus/reference-adjudication-prompt.md'
        frozen = self.root / 'reference-adjudication-prompt.md'
        frozen.write_bytes(source.read_bytes())
        self.result.update(resolved=True, resolution_zh='日文人数明确，原参考正确。')
        job = {'window_id': self.row['id'], 'phase': 'adjudication',
               'packet': packet(self.row), 'maximum_adjudications': 1,
               'anonymized_opinions': [dict(self.result), dict(self.result)],
               'instruction': 'Resolve only from supplied source.'}
        state = self.invoke(job)
        self.assertEqual(state['status'], 'succeeded')
        self.assertEqual(state['prompt_sha256'], digest(frozen))
        self.assertIn('ANONYMIZED OPINIONS', self.prompts[0])
        self.assertIn('intentionally visible for arbitration', self.prompts[0])
        self.assertNotIn('Never inspect candidate inference outputs, identities, scores, or another review.', self.prompts[0])
        self.assertEqual(self.calls, 1)

    def test_adjudication_resolution_must_be_nonempty(self):
        for resolution in ('', '  '):
            with self.assertRaisesRegex(ValueError, 'Invalid adjudication resolution'):
                validate_response(self.row, {**self.result, 'resolved': True, 'resolution_zh': resolution}, True)
        self.assertEqual(response_schema(['u1'], True)['properties']['resolution_zh']['minLength'], 1)

    def test_exclude_and_diagnostic_contract(self):
        excluded = {**self.result, 'status': 'exclude', 'translations': {}, 'reason_zh': '缺少上下文。'}
        validate_response(self.row, excluded)
        with self.assertRaisesRegex(ValueError, 'diagnostic'):
            validate_response(self.row, {**self.result, 'diagnostic_tags': ['invalid']})
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            validate_response(self.row, {**self.result, 'resolved': False, 'resolution_zh': '无法确定。'}, True)


if __name__ == '__main__':
    unittest.main()
