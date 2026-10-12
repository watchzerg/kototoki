"""Bounded scheduling with explicit account/model-access failure detection."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable

POLICY_VERSION = 'explicit-access-breaker-v1'
FAILURE_THRESHOLD = 3


def classify_access_failure(attempt: Path, record: dict[str, Any]) -> dict[str, Any] | None:
    """Inspect transport error records only, never assistant text or packet content."""
    if record.get('status') != 'failed' or record.get('transport_status') != 'completed':
        return None
    messages: list[str] = []
    codes: list[str] = []
    stdout = attempt / 'stdout.jsonl'
    if stdout.exists():
        for line in stdout.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get('type') == 'error':
                payload = event
            elif isinstance(event.get('item'), dict) and event['item'].get('type') == 'error':
                payload = event['item']
            elif event.get('type') == 'turn.failed' and isinstance(event.get('error'), dict):
                payload = event['error']
            else:
                continue
            for value in (payload, payload.get('error')):
                if not isinstance(value, dict):
                    continue
                if isinstance(value.get('code'), str):
                    codes.append(value['code'].lower())
                if isinstance(value.get('message'), str):
                    messages.append(value['message'])
    stderr = attempt / 'stderr.txt'
    if stderr.exists():
        messages.extend(stderr.read_text(encoding='utf-8', errors='replace').splitlines())
    text = '\n'.join(messages).lower()
    if (set(codes) & {'insufficient_quota', 'usage_limit_reached', 'quota_exceeded'} or
            re.search(r'(?:you(?: have|\'ve)? (?:hit|reached)|account has (?:hit|reached)).{0,40}usage limit|usage limit (?:has been )?(?:reached|exceeded)|insufficient quota|exceeded (?:your|the account).{0,30}quota', text)):
        kind = 'quota'
    elif (set(codes) & {'invalid_api_key', 'authentication_error', 'invalid_authentication', 'unauthorized', 'not_authenticated'} or
            re.search(r'authentication (?:failed|error|required)|invalid (?:api key|authentication token)|(?:please|must) (?:log|sign) in|not (?:logged|signed) in|(?:http|status(?: code)?)\s*:?\s*401\b|401 unauthorized', text)):
        kind = 'auth'
    elif (set(codes) & {'model_not_found', 'model_not_supported', 'model_access_denied'} or
            re.search(r"model.{0,120}(?:is not supported|not supported when using|does not exist|do not have access|access denied|not available (?:for|with).{0,50}(?:account|plan))|(?:do not|does not) have access to.{0,60}model", text)):
        kind = 'model_access'
    else:
        return None
    # Retain exact raw logs separately. Scheduling metadata carries hashes/paths elsewhere,
    # and a short category rather than copying account messages into reports.
    return {'kind': kind, 'source': 'transport error events/stderr', 'raw_stdout': str(stdout),
            'raw_stderr': str(stderr), 'recognized_codes': sorted(set(codes))}


@dataclass
class AccessCircuit:
    started_at: str
    threshold: int = FAILURE_THRESHOLD
    kind: str | None = None
    consecutive: int = 0
    last_job_ids: list[str] = field(default_factory=list)
    tripped: bool = False
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def observe(self, state: dict[str, Any]) -> None:
        if self.tripped or state.get('resumed'):
            return
        fresh = [attempt for attempt in state.get('attempts', [])
                 if isinstance(attempt.get('started_at'), str) and
                 datetime.fromisoformat(attempt['started_at']) >= datetime.fromisoformat(self.started_at)]
        if not fresh:
            # Historical successes/failures neither trip nor clear a new-run circuit.
            return
        failure = fresh[-1].get('access_failure') if state.get('status') == 'judge_failed' else None
        if not failure:
            self.kind, self.consecutive, self.last_job_ids = None, 0, []
            return
        if failure['kind'] != self.kind:
            self.kind, self.consecutive, self.last_job_ids = failure['kind'], 0, []
        if state['job_id'] not in self.last_job_ids:
            self.last_job_ids.append(state['job_id'])
            self.consecutive += 1
            self.evidence.append({'job_id': state['job_id'], 'access_failure': failure})
        if self.consecutive >= self.threshold:
            self.tripped = True

    def metadata(self) -> dict[str, Any]:
        return {'policy_version': POLICY_VERSION, 'threshold_distinct_jobs': self.threshold,
                'tripped': self.tripped, 'kind': self.kind, 'consecutive': self.consecutive,
                'evidence': self.evidence, 'started_at': self.started_at,
                'drain_policy': 'Do not cancel submitted jobs or their existing bounded retries.'}


def schedule_jobs(jobs: list[dict[str, Any]], workers: int,
                  invoke: Callable[[dict[str, Any]], dict[str, Any]],
                  on_result: Callable[[dict[str, Any]], None] | None = None,
                  started_at: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep at most workers submitted; stop refill after persistent explicit failures."""
    if not 1 <= workers <= 6:
        raise ValueError('workers must be 1..6')
    circuit = AccessCircuit(started_at or datetime.now(timezone.utc).isoformat())
    states: list[dict[str, Any]] = []
    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending: dict[Any, int] = {}
        def refill() -> None:
            nonlocal next_index
            while not circuit.tripped and len(pending) < workers and next_index < len(jobs):
                index = next_index
                next_index += 1
                pending[pool.submit(invoke, jobs[index])] = index
        refill()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            # Consume a completed batch before any refill; stable order breaks ties.
            for future in sorted(done, key=lambda value: pending[value]):
                pending.pop(future)
                state = future.result()
                states.append(state)
                circuit.observe(state)
                if on_result:
                    on_result(state)
            refill()
    for job in jobs[next_index:]:
        states.append({'job_id': job.get('job_id', 'adjudication|' + job['window_id']),
                       'window_id': job['window_id'], 'status': 'not_run', 'attempts': [],
                       'scheduled_this_invocation': False, 'reason': 'explicit access circuit breaker',
                       'packet': job.get('packet'), 'response': job.get('response', job.get('output'))})
    return states, circuit.metadata()
