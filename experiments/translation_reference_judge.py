"""Isolated, resumable Sol/high CLI transport for double reference review."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable

from experiments.translation_corpus.prepare import packet as reference_packet, validate_review
from experiments.translation_eval.runner import dump, dump_jsonl, load_jsonl, read_json
from experiments.translation_judge.runner import (
    DISABLED_FEATURES, EFFORT, MODEL, OVERRIDES, command, execute, local_path, run_lock, utc,
)

from experiments.translation_judge.scheduling import classify_access_failure, schedule_jobs

TAGS = ('ellipsis_reference', 'negation_condition', 'named_entity', 'number', 'colloquial', 'long_sentence', 'other')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def response_schema(ids: list[str], adjudication: bool = False) -> dict[str, Any]:
    def obj(properties: dict[str, Any]) -> dict[str, Any]:
        return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
    string = {'type': 'string'}
    properties = {
        'window_id': string, 'status': {'type': 'string', 'enum': ['accept', 'edit', 'exclude']},
        'translations': {'anyOf': [obj({uid: string for uid in ids}), obj({})]},
        'changes': {'type': 'array', 'items': obj({
            'id': string, 'original_zh': string, 'revised_zh': string,
            'source_evidence': string, 'reason_zh': string,
        })},
        'reason_zh': string, 'diagnostic_tags': {'type': 'array', 'items': {'type': 'string', 'enum': list(TAGS)}},
    }
    if adjudication:
        properties.update(resolved={'type': 'boolean'}, resolution_zh={'type': 'string', 'minLength': 1})
    return obj(properties)


def validate_response(row: dict[str, Any], result: dict[str, Any], adjudication: bool = False) -> dict[str, Any]:
    base = dict(result)
    if adjudication:
        resolved = base.pop('resolved', None)
        resolution = base.pop('resolution_zh', None)
        if type(resolved) is not bool or not isinstance(resolution, str) or not resolution.strip():
            raise ValueError('Invalid adjudication resolution')
        if result['resolved'] is False and result['status'] != 'exclude':
            raise ValueError('Unresolved adjudication must exclude')
    if not isinstance(base.get('changes'), list):
        raise ValueError('Invalid changes type')
    for change in base['changes']:
        if not isinstance(change, dict) or set(change) != {'id', 'original_zh', 'revised_zh', 'source_evidence', 'reason_zh'}:
            raise ValueError('Unexpected change fields')
        if any(not isinstance(value, str) for value in change.values()):
            raise ValueError('Invalid change types')
    validate_review(row, base)
    tags = base['diagnostic_tags']
    if not isinstance(tags, list) or any(not isinstance(tag, str) or tag not in TAGS for tag in tags):
        raise ValueError('Invalid diagnostic tags')
    if len(tags) != len(set(tags)):
        raise ValueError('Duplicate diagnostic tags')
    return result


def assemble_prompt(original_prompt: str, packet: dict[str, Any],
                    job: dict[str, Any], adjudication: bool = False) -> str:
    if adjudication:
        prompt = original_prompt + '\nUse only the supplied packet and anonymous opinions. Do not use tools, files, memory, external knowledge, or other conversations.\nPACKET:\n' + json.dumps(packet, ensure_ascii=False)
        prompt += '\nANONYMIZED OPINIONS:\n' + json.dumps(job['anonymized_opinions'], ensure_ascii=False)
        return prompt + '\nADJUDICATION INSTRUCTION:\n' + job['instruction']
    # Preserve primary/review assembled prompt bytes exactly for frozen-job resume.
    return original_prompt + '\nUse only the supplied packet. Do not use tools, files, memory, external knowledge, or other conversations.\nPACKET:\n' + json.dumps(packet, ensure_ascii=False)


def run_job(root: Path, job: dict[str, Any], row: dict[str, Any], executable: str,
            version: str, timeout: float, invoke: Callable[..., dict[str, Any]] = execute) -> dict[str, Any]:
    root = root.resolve()
    phase = job.get('phase', 'adjudication')
    if phase not in {'primary', 'review', 'adjudication'}:
        raise ValueError('Unknown reference-review phase')
    window_id = job['window_id']
    if window_id != row['id'] or Path(window_id).name != window_id or window_id in {'.', '..'}:
        raise ValueError('Invalid window identity/path')
    adjudication = phase == 'adjudication'
    if adjudication:
        if job.get('maximum_adjudications') != 1:
            raise ValueError('Adjudication must be bounded to one logical job')
        packet = job['packet']
    else:
        if (job.get('model'), job.get('reasoning_effort'), job.get('fresh'), job.get('candidate_outputs_allowed')) != (MODEL, EFFORT, True, False):
            raise ValueError('Reference invocation violates frozen model/isolation contract')
        packet = read_json(local_path(root, job['packet']))
    if packet != reference_packet(row):
        raise ValueError('Packet differs from original selected source/reference')
    packet_hash = (hashlib.sha256(json.dumps(packet, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                   if adjudication else digest(local_path(root, job['packet'])))
    prompt_path = root / ('reference-adjudication-prompt.md' if adjudication else 'reference-review-prompt.md')
    original_prompt = prompt_path.read_text(encoding='utf-8-sig')
    prompt = assemble_prompt(original_prompt, packet, job, adjudication)
    schema = response_schema(packet['scored_ids'], adjudication)
    frozen = {'prompt': prompt, 'schema': schema, 'model': MODEL, 'effort': EFFORT,
              'overrides': OVERRIDES, 'disabled_features': DISABLED_FEATURES}
    fingerprint = hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    directory = local_path(root, f'reference-execution/{phase}/{window_id}')
    directory.mkdir(parents=True, exist_ok=True)
    ledger = directory / 'job.json'
    response = local_path(root, job.get('output', f'reviews/{phase}/{window_id}.json'))
    previous = read_json(ledger) if ledger.exists() else None
    if previous and previous['fingerprint'] != fingerprint:
        raise ValueError('Reference packet/prompt/schema/settings changed; use a new run')
    if previous and (previous['packet_sha256'] != packet_hash or previous['prompt_sha256'] != digest(prompt_path)):
        raise ValueError('Reference packet/prompt file bytes changed; use a new run')
    if response.exists() and (previous is None or previous['status'] != 'succeeded'):
        raise ValueError('Canonical reference response lacks successful transport evidence')
    if previous and previous['status'] == 'succeeded':
        raw = Path(previous['accepted_raw_response'])
        if digest(raw) != previous['accepted_raw_response_sha256']:
            raise ValueError('Accepted raw response changed')
        validated = validate_response(row, read_json(raw), adjudication)
        if response.exists():
            if digest(response) != previous['response_sha256']:
                raise ValueError('Accepted canonical response changed')
        else:
            dump(response, validated)
            if digest(response) != previous['response_sha256']:
                raise ValueError('Restored canonical hash differs')
        return {**previous, 'resumed': True}
    state = {'job_id': f'{phase}|{window_id}', 'phase': phase, 'window_id': window_id,
             'fingerprint': fingerprint, 'requested_model': MODEL, 'requested_effort': EFFORT,
             'fresh': True, 'cli_version': version, 'response': str(response), 'status': 'judge_failed',
             'packet_sha256': packet_hash,
             'prompt_sha256': digest(prompt_path),
             'schema_sha256': hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(), 'attempts': []}
    attempts = sorted(directory.glob('attempt-*'))
    if len(attempts) > 2:
        raise ValueError('Reference retry budget already exceeded')
    for attempt in attempts:
        record_path = attempt / 'attempt.json'
        state['attempts'].append(read_json(record_path) if record_path.exists() else {'attempt': attempt.name, 'status': 'interrupted'})
    dump(ledger, state)
    for number in range(len(attempts) + 1, 3):
        attempt = directory / f'attempt-{number}'
        attempt.mkdir(exist_ok=False)
        dump(attempt / 'packet.json', packet)
        dump(attempt / 'schema.json', schema)
        (attempt / 'prompt.txt').write_text(prompt, encoding='utf-8')
        raw = attempt / 'last-message.txt'
        record = {'attempt': number, 'started_at': utc(), 'status': 'started'}
        dump(attempt / 'attempt.json', record)
        with tempfile.TemporaryDirectory(prefix='kototoki-reference-judge-') as temporary:
            cwd = Path(temporary)
            args = command(executable, cwd, attempt / 'schema.json', raw)
            record.update(command=args, isolated_cwd=str(cwd))
            dump(attempt / 'attempt.json', record)
            record.update(invoke(args, prompt, cwd, attempt, timeout))
        record['finished_at'] = utc()
        try:
            if record['transport_status'] != 'completed' or record['returncode'] != 0:
                raise ValueError('Codex reference transport failed')
            if record['returned_models'] and record['returned_models'] != [MODEL]:
                raise ValueError('Returned model differs from requested model')
            if record['returned_efforts'] and record['returned_efforts'] != [EFFORT]:
                raise ValueError('Returned effort differs from requested effort')
            if record['tool_events']:
                raise ValueError('Reference worker invoked tools')
            validated = validate_response(row, read_json(raw), adjudication)
            raw_hash = digest(raw)
            dump(response, validated)
            record['status'] = 'succeeded'
            state.update(status='succeeded', accepted_raw_response=str(raw),
                         accepted_raw_response_sha256=raw_hash, response_sha256=digest(response),
                         returned_models=record['returned_models'], returned_efforts=record['returned_efforts'],
                         returned_identity_unavailable=(None if record['returned_models'] and record['returned_efforts']
                             else 'CLI JSON events did not expose complete model/effort identity; configured identity is not returned identity'))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            record.update(status='failed', error=str(exc))
        if record['status'] == 'failed':
            record['access_failure'] = classify_access_failure(attempt, record)
        dump(attempt / 'attempt.json', record)
        state['attempts'].append(record)
        dump(ledger, state)
        if state['status'] == 'succeeded':
            break
    return state


def run(root: Path, jobs_path: Path, executable: str = 'codex.exe', workers: int = 6,
        timeout: float = 300, phase: str = 'primary', limit: int | None = None) -> dict[str, Any]:
    if not 1 <= workers <= 6 or timeout <= 0 or (limit is not None and limit <= 0):
        raise ValueError('workers must be 1..6; timeout and limit must be positive')
    root = root.resolve()
    with run_lock(root):
        rows = {row['id']: row for row in load_jsonl(root / 'staging/selected-candidates.jsonl')}
        jobs = [job for job in load_jsonl(jobs_path) if job.get('phase', 'adjudication') == phase]
        if limit is not None:
            jobs = jobs[:limit]
        ids = [job['window_id'] for job in jobs]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate reference job identities')
        if any(uid not in rows for uid in ids):
            raise ValueError('Reference job is not in selected source manifest')
        executable = shutil.which(executable) or executable
        version_result = subprocess.run([executable, '--version'], capture_output=True, timeout=30, check=True)
        version = version_result.stdout.decode('utf-8', errors='replace').strip()
        started, states = time.perf_counter(), []
        def on_result(state: dict[str, Any]) -> None:
            print(json.dumps({key: state.get(key) for key in ('job_id', 'status', 'resumed')}, ensure_ascii=False), flush=True)
        states, circuit = schedule_jobs(jobs, workers,
            lambda job: run_job(root, job, rows[job['window_id']], executable, version, timeout), on_result)
        states.sort(key=lambda item: item['job_id'])
        summary = {'requested_model': MODEL, 'requested_effort': EFFORT, 'cli_version': version,
                   'phase': phase, 'workers': workers, 'jobs_file': str(jobs_path.resolve()),
                   'expected_jobs': len(jobs), 'succeeded': sum(state['status'] == 'succeeded' for state in states),
                   'judge_failed': sum(state['status'] == 'judge_failed' for state in states),
                   'not_run': sum(state['status'] == 'not_run' for state in states),
                   'circuit_breaker': circuit,
                   'elapsed_seconds_this_invocation': time.perf_counter() - started,
                   'all_attempt_seconds': sum(attempt.get('elapsed_seconds', 0) for state in states for attempt in state['attempts']),
                   'cost': None, 'cost_reason': 'CLI does not expose billed cost; raw usage events retained', 'jobs': states}
        summary_directory = root / 'reference-execution/schedules'
        summary_directory.mkdir(parents=True, exist_ok=True)
        name = utc().replace(':', '-').replace('+', '_')
        dump(summary_directory / f'{phase}-{name}-summary.json', summary)
        dump_jsonl(summary_directory / f'{phase}-{name}-ledger.jsonl', states)
        return summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Isolated Sol/high reference review; authenticated CLI requires escalation')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=Path, required=True)
    parser.add_argument('--phase', choices=['primary', 'review', 'adjudication'], default='primary')
    parser.add_argument('--workers', type=int, choices=range(1, 7), default=6)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--codex', default='codex.exe')
    args = parser.parse_args()
    try:
        summary = run(args.output, args.jobs, args.codex, args.workers, args.timeout, args.phase, args.limit)
        if summary['judge_failed'] or summary['not_run']:
            parser.exit(1, '部分参考审核失败；保留原始响应及重试账本。\n')
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f'参考审核传输错误：{exc}\n')


if __name__ == '__main__':
    main()
