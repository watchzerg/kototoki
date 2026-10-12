"""Offline circuit policy and bounded scheduling tests."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest

from experiments.translation_judge.scheduling import AccessCircuit, classify_access_failure, schedule_jobs


def stamp():
    return datetime.now(timezone.utc).isoformat()


def result(job, kind=None, succeeded=False, started=None, resumed=False):
    attempt = {'started_at': started or stamp(), 'status': 'succeeded' if succeeded else 'failed',
               'access_failure': {'kind': kind} if kind else None}
    return {'job_id': job['job_id'], 'window_id': job['window_id'],
            'status': 'succeeded' if succeeded else 'judge_failed', 'resumed': resumed,
            'attempts': [dict(attempt), dict(attempt)]}


class CircuitTests(unittest.TestCase):
    def setUp(self):
        self.started = stamp()
        self.jobs = [{'job_id': 'primary/A/' + str(i), 'window_id': str(i),
                      'packet': f'packets/{i}.json', 'response': f'primary/A/{i}.json'} for i in range(10)]

    def test_three_distinct_persistent_failures_and_historical_resume(self):
        circuit = AccessCircuit(self.started)
        circuit.observe(result(self.jobs[0], 'quota'))
        circuit.observe(result(self.jobs[0], 'quota'))
        self.assertEqual(circuit.consecutive, 1)
        old = (datetime.fromisoformat(self.started) - timedelta(seconds=10)).isoformat()
        circuit.observe(result(self.jobs[1], 'quota', started=old))
        circuit.observe(result(self.jobs[1], succeeded=True, resumed=True))
        self.assertEqual(circuit.consecutive, 1)
        circuit.observe(result(self.jobs[1], 'quota'))
        circuit.observe(result(self.jobs[2], 'quota'))
        self.assertTrue(circuit.tripped)

    def test_success_generic_failure_or_changed_family_breaks_streak(self):
        circuit = AccessCircuit(self.started)
        circuit.observe(result(self.jobs[0], 'quota'))
        circuit.observe(result(self.jobs[1], succeeded=True))
        self.assertEqual(circuit.consecutive, 0)
        circuit.observe(result(self.jobs[2], 'auth'))
        circuit.observe(result(self.jobs[3]))
        self.assertEqual(circuit.consecutive, 0)
        circuit.observe(result(self.jobs[4], 'quota'))
        circuit.observe(result(self.jobs[5], 'model_access'))
        self.assertEqual(circuit.consecutive, 1)
        self.assertEqual(circuit.kind, 'model_access')

    def test_unsubmitted_jobs_have_complete_denominator_and_no_attempts(self):
        calls = []
        def invoke(job):
            calls.append(job['job_id'])
            return result(job, 'auth')
        states, circuit = schedule_jobs(self.jobs, 1, invoke, started_at=self.started)
        self.assertTrue(circuit['tripped'])
        self.assertEqual(len(calls), 3)
        self.assertEqual({state['job_id'] for state in states}, {job['job_id'] for job in self.jobs})
        not_run = [state for state in states if state['status'] == 'not_run']
        self.assertEqual(len(not_run), 7)
        self.assertTrue(all(state['attempts'] == [] and not state['scheduled_this_invocation'] for state in not_run))

    def test_no_eager_queue_and_inflight_finishes_after_trip(self):
        release = threading.Event()
        calls = []
        active, peak = 0, 0
        lock = threading.Lock()
        def invoke(job):
            nonlocal active, peak
            with lock:
                calls.append(job['job_id'])
                active += 1
                peak = max(peak, active)
            if job['window_id'] == '0':
                self.assertTrue(release.wait(2))
                value = result(job, succeeded=True)
            else:
                value = result(job, 'model_access')
            with lock:
                active -= 1
            return value
        observed = []
        def on_result(state):
            observed.append(state)
            if sum(s['status'] == 'judge_failed' for s in observed) == 3:
                release.set()
        states, circuit = schedule_jobs(self.jobs, 2, invoke, on_result, self.started)
        self.assertTrue(circuit['tripped'])
        self.assertEqual(len(calls), 4)
        self.assertLessEqual(peak, 2)
        self.assertEqual(sum(s['status'] == 'succeeded' for s in states), 1)
        self.assertEqual(sum(s['status'] == 'not_run' for s in states), 6)

    def test_latched_circuit_does_not_restart_after_inflight_success(self):
        circuit = AccessCircuit(self.started)
        for job in self.jobs[:3]:
            circuit.observe(result(job, 'quota'))
        circuit.observe(result(self.jobs[3], succeeded=True))
        self.assertTrue(circuit.tripped)

    def test_explicit_classifier_ignores_assistant_content_and_transient_errors(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
            path = Path(temporary)
            record = {'status': 'failed', 'transport_status': 'completed', 'returncode': 1}
            def check(events, stderr=''):
                (path / 'stdout.jsonl').write_text('\n'.join(json.dumps(e) for e in events), encoding='utf-8')
                (path / 'stderr.txt').write_text(stderr, encoding='utf-8')
                return classify_access_failure(path, record)
            self.assertIsNone(check([{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': "You've hit your usage limit"}}]))
            self.assertIsNone(check([], 'HTTP 429: Rate limit reached'))
            self.assertIsNone(check([], 'Network timeout; reconnecting'))
            self.assertIsNone(check([], 'Access denied opening schema.json'))
            self.assertEqual(check([{'type': 'error', 'message': "You've hit your usage limit. Try again later."}])['kind'], 'quota')
            self.assertEqual(check([{'type': 'turn.failed', 'error': {'code': 'authentication_error', 'message': 'Expired'}}])['kind'], 'auth')
            self.assertEqual(check([], "The 'gpt-6.1-sol' model is not supported when using Codex with a ChatGPT account.")['kind'], 'model_access')
            record['returncode'] = 0
            self.assertEqual(check([{'type': 'error', 'code': 'insufficient_quota', 'message': 'Quota exhausted'}])['kind'], 'quota')


if __name__ == '__main__':
    unittest.main()
