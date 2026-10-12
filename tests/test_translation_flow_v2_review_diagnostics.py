"""Same-run F8 diagnostic provenance; synthetic source, no judges/references."""

import json
import unittest

from experiments.translation_eval.runner import dump, dump_jsonl, load_jsonl, read_json, sha
from experiments.translation_flow import test_v2_delivery
from experiments.translation_flow.v2_delivery import deliver
from experiments.translation_flow.v2_review_diagnostics import export_review_views, validate_review_view


class ReviewViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_v2_delivery.DeliveryTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.original = self.root / 'original-f8'
        self.output = self.root / 'review-views'
        run = read_json(self.fixture.run / 'run.json')
        run.update(recipe='c0', settings={'recipe': 'c0', 'review': True})
        dump(self.fixture.run / 'run.json', run)
        for index, row in enumerate(self.fixture.ledger):
            before = {uid: f'初译{uid}。' for uid in row['translations']}
            row['before_review'] = before
            row['attempts'] = []
            for phase, values in (('translation', before), ('source-review', row['translations'])):
                request = {'prompt': [1, 2, 3], 'n_predict': 4096}
                response = {'content': json.dumps({'translations': values}, ensure_ascii=False), 'tokens_predicted': 5}
                pointer = self.fixture.run / 'transport' / f'{index}-{phase}'
                dump(pointer / 'request.json', {'endpoint': '/completion', 'body': request})
                dump(pointer / 'response.raw', response)
                dump(pointer / 'transport.json', {'status': 200})
                row['attempts'].append({'stage': phase, 'status': 'accepted', 'completion_dispatched': True,
                                        'request': request, 'response': response, 'original_response': str(pointer),
                                        'input_tokens': 10, 'elapsed_seconds': 1})
        self.fixture.write_run()
        self.make_original()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def make_original(self) -> None:
        deliver(self.fixture.manifest, self.fixture.mapping, self.fixture.run, self.original)

    def execute(self) -> dict:
        return export_review_views(self.original, self.output)

    def test_exact_same_run_initial_and_final_views_add_no_samples_or_timing(self) -> None:
        original_hashes = {path: sha(path) for path in self.original.rglob('*') if path.is_file()}
        summary = self.execute()
        before = load_jsonl(self.output / 'before/results.jsonl')[0]
        after = load_jsonl(self.output / 'after/results.jsonl')[0]
        self.assertEqual(before['translations']['source-1'], '初译source-1。')
        self.assertEqual(after['translations']['source-1'], '中文source-1。')
        self.assertIsNone(before['elapsed_seconds'])
        self.assertIsNone(after['elapsed_seconds'])
        self.assertEqual(summary['new_inference_calls'], 0)
        self.assertEqual(summary['new_generated_samples'], 0)
        self.assertEqual((self.output / 'before/inputs.jsonl').read_bytes(), (self.output / 'after/inputs.jsonl').read_bytes())
        for phase in ('before', 'after'):
            metadata = read_json(self.output / phase / 'delivery.json')
            self.assertFalse(metadata['review_diagnostic']['standalone_flow_timing'])
            self.assertEqual(metadata['review_diagnostic']['original_cost_identity']['sha256'], sha(self.fixture.run / 'run.json'))
            self.assertIsNone(metadata['costs']['elapsed_seconds'])
            validate_review_view(metadata, self.output / phase)
        self.assertEqual({path: sha(path) for path in original_hashes}, original_hashes)

    def test_native_pre_post_provenance_is_preserved_without_quality_claims(self) -> None:
        self.execute()
        native = load_jsonl(self.output / 'before/native-review-provenance.jsonl')[0]
        self.assertEqual(native['before_review'], self.fixture.ledger[0]['before_review'])
        self.assertEqual(native['after_review'], self.fixture.ledger[0]['translations'])
        self.assertEqual(native['initial_attempt_index'], 0)
        self.assertEqual(len(native['review_raw_responses']), 1)
        self.assertNotIn('corrected', native)
        self.assertNotIn('harmed', native)

    def test_before_field_must_match_accepted_initial_native_attempt(self) -> None:
        row = self.fixture.ledger[0]
        row['before_review']['source-0'] = 'Different saved initial text'
        self.fixture.write_run()
        self.original = self.root / 'inconsistent-f8'
        self.make_original()
        with self.assertRaisesRegex(ValueError, 'before_review differs'):
            self.execute()

    def test_final_field_must_match_accepted_review_native_attempt(self) -> None:
        self.fixture.results[0]['translations']['source-0'] = 'Different saved final text'
        self.fixture.ledger[0]['translations'] = self.fixture.results[0]['translations']
        self.fixture.write_run()
        self.original = self.root / 'inconsistent-final-f8'
        self.make_original()
        with self.assertRaisesRegex(ValueError, 'after_review differs'):
            self.execute()

    def test_failed_review_retains_available_initial_delivery_and_failed_final(self) -> None:
        row = self.fixture.ledger[0]
        row.update(status='translation_failed', translations={}, reason='Review could not produce a valid delivery',
                   failure_stage='source-review')
        row['attempts'][-1]['status'] = 'failed'
        self.fixture.results[0].update(status='translation_failed', translations={})
        self.fixture.write_run()
        self.original = self.root / 'failed-review-f8'
        self.make_original()
        self.execute()
        before = read_json(self.output / 'before/delivery.json')
        after = read_json(self.output / 'after/delivery.json')
        self.assertEqual(before['scenes'][0]['status'], 'complete')
        self.assertEqual(after['scenes'][0]['status'], 'incomplete')
        self.assertTrue((self.output / 'before/scenes/scene1/chn.srt').is_file())
        self.assertFalse((self.output / 'after/scenes/scene1/chn.srt').exists())
        self.assertEqual(load_jsonl(self.output / 'after/ledger.jsonl')[0]['status'], 'translation_failed')

    def test_non_review_run_is_rejected(self) -> None:
        run = read_json(self.fixture.run / 'run.json')
        run['settings']['review'] = False
        dump(self.fixture.run / 'run.json', run)
        self.original = self.root / 'not-review-f8'
        self.make_original()
        with self.assertRaisesRegex(ValueError, 'review workload'):
            self.execute()

    def test_projection_tampering_and_cross_seed_claims_are_rejected(self) -> None:
        self.execute()
        view = self.output / 'before'
        metadata = read_json(view / 'delivery.json')
        metadata['seed'] += 1
        with self.assertRaisesRegex(ValueError, 'seed identity'):
            validate_review_view(metadata, view)
        metadata = read_json(view / 'delivery.json')
        results = load_jsonl(view / 'results.jsonl')
        results[0]['translations']['source-1'] = 'Changed diagnostic text'
        dump_jsonl(view / 'results.jsonl', results)
        with self.assertRaisesRegex(ValueError, 'immutable same-run'):
            validate_review_view(metadata, view)

    def test_original_raw_mutation_is_rejected(self) -> None:
        native = self.fixture.run / 'transport/0-translation/response.raw'
        dump(native, {'content': 'Changed raw initial response'})
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            self.execute()

    def test_same_ids_in_changed_request_order_are_rejected(self) -> None:
        inputs = load_jsonl(self.fixture.run / 'inputs.jsonl')
        dump_jsonl(self.fixture.run / 'inputs.jsonl', list(reversed(inputs)))
        run = read_json(self.fixture.run / 'run.json')
        run['input_sha256'] = sha(self.fixture.run / 'inputs.jsonl')
        dump(self.fixture.run / 'run.json', run)
        self.original = self.root / 'reordered-f8'
        self.make_original()
        with self.assertRaisesRegex(ValueError, 'request sequence'):
            self.execute()

    def test_standalone_cost_and_source_timing_claims_are_rejected(self) -> None:
        self.execute()
        view = self.output / 'before'
        metadata = read_json(view / 'delivery.json')
        metadata['costs']['elapsed_seconds'] = 1.5
        with self.assertRaisesRegex(ValueError, 'standalone timing'):
            validate_review_view(metadata, view)
        metadata = read_json(view / 'delivery.json')
        cost = read_json(view / 'costs.json')
        cost['new_generated_samples'] = 1
        dump(view / 'costs.json', cost)
        with self.assertRaisesRegex(ValueError, 'standalone timing'):
            validate_review_view(metadata, view)
        dump(view / 'costs.json', metadata['costs'])
        srt = view / 'scenes/scene1/chn.srt'
        srt.write_text(srt.read_text(encoding='utf-8').replace('00:00:00,000', '00:00:00,001'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'exact source timing'):
            validate_review_view(metadata, view)


if __name__ == '__main__':
    unittest.main()
