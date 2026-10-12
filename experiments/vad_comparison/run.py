"""Resume a fixed ten-route comparison without discovering successful subsets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from experiments.w0_demo.run import sha256

ROOT = Path(__file__).resolve().parents[2]
VADS = ('pyannote-current', 'silero', 'fsmn', 'firered')


def write(path: Path, value: object) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def verify_clips(clips: list[dict]) -> dict:
    verified = {}
    for clip in clips:
        for key in ('audio', 'reference', 'source_audio', 'source_srt'):
            path = Path(clip[key])
            if str(path) not in verified:
                verified[str(path)] = sha256(path)
            if verified[str(path)] != clip[f'{key}_sha256']:
                raise ValueError(f'Frozen input changed: {path}')
    return verified


def execute(command: list[str], log_prefix: Path) -> dict:
    log_prefix.parent.mkdir(parents=True, exist_ok=True)
    temp = log_prefix.parent / 'tmp'
    temp.mkdir(exist_ok=True)
    environment = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                       PYTHONNOUSERSITE='1', TMP=str(temp), TEMP=str(temp), TMPDIR=str(temp))
    started = time.perf_counter()
    stop = threading.Event()
    samples = []
    def sample_gpu() -> None:
        while not stop.is_set():
            try:
                measured = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu',
                    '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
                if measured.returncode == 0:
                    memory, utilization = map(float, measured.stdout.strip().splitlines()[0].split(','))
                    samples.append({'elapsed_s': time.perf_counter() - started,
                                    'gpu_total_used_mib': memory, 'gpu_utilization_percent': utilization})
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
            stop.wait(1)
    sampler = threading.Thread(target=sample_gpu, daemon=True)
    try:
        sampler.start()
        with log_prefix.with_suffix('.stdout.log').open('x', encoding='utf-8') as stdout, \
                log_prefix.with_suffix('.stderr.log').open('x', encoding='utf-8') as stderr:
            child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr)
            try:
                code = child.wait()
                elapsed = time.perf_counter() - started
            except BaseException:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                raise
    finally:
        stop.set()
        sampler.join(timeout=6)
    write(log_prefix.with_suffix('.gpu-samples.json'), samples)
    return {'command': command, 'exit_code': code, 'wall_s': elapsed,
            'pid': child.pid, 'sampled_gpu_total_used_peak_mib':
            max((row['gpu_total_used_mib'] for row in samples), default=None),
            'gpu_sample_count': len(samples),
            'memory_scope': 'whole GPU including desktop and unrelated processes; sampled once per second'}


def initialize(path: Path, study_id: str) -> dict:
    plan_path = ROOT / '.local/round2/plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    study = {'schema_version': 1, 'study_id': study_id, 'terminal': False,
             'source_plan_sha256': sha256(plan_path), 'clips': plan['clips'], 'routes': [],
             'created_utc': datetime.now(timezone.utc).isoformat(), 'vad_runs': {}}
    for family in ('w0', 'x0'):
        for vad_id in ('original', *VADS):
            route_id = f'{family}-{vad_id}'
            study['routes'].append({'id': route_id, 'configuration_id': f'vad-comparison-v1-{route_id}',
                'model_metadata': {'family': family, 'vad': vad_id},
                'runs': [{'clip_id': clip['id'], 'run_id': f'{study_id}-{route_id}-{clip["id"]}',
                          'status': 'pending'} for clip in plan['clips']]})
    study['input_checks_before'] = verify_clips(study['clips'])
    write(path, study)
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-id', default='vad-comparison-v1')
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--routes', nargs='*', help='Optional bounded execution; registry always retains ten routes')
    parser.add_argument('--clips', nargs='*', help='Optional smoke scope; registry retains twelve clips')
    args = parser.parse_args()
    if not args.study_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.study_id):
        parser.error('study-id must use lowercase ASCII letters, digits and hyphens')
    folder = ROOT / '.local/vad-comparison' / args.study_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'study.json'
    study = json.loads(path.read_text(encoding='utf-8')) if path.exists() else initialize(path, args.study_id)
    if any(slot['status'] == 'running' for route in study['routes'] for slot in route['runs']):
        raise RuntimeError('Interrupted running slot requires inspection and a new attempt identity; refusing duplicate inference')
    study['terminal'] = False
    study['controller_pid'] = os.getpid()
    study['controller_started_utc'] = datetime.now(timezone.utc).isoformat()
    study['controller_source_sha256'] = sha256(Path(__file__))
    write(path, study)
    if study['source_plan_sha256'] != sha256(ROOT / '.local/round2/plan.json'):
        raise ValueError('Source plan changed after freeze')
    config = json.loads(args.candidates.read_text(encoding='utf-8'))
    config = config.get('candidates', config)
    whisper = ROOT / '.local/envs/whisper-latest/Scripts/python.exe'
    for clip in study['clips']:
        if args.clips and clip['id'] not in args.clips:
            continue
        for route in study['routes']:
            if args.routes and route['id'] not in args.routes:
                continue
            slot = next(run for run in route['runs'] if run['clip_id'] == clip['id'])
            if slot['status'] not in ('pending', 'blocked'):
                continue
            family, vad_id = route['model_metadata']['family'], route['model_metadata']['vad']
            manifest = None
            if vad_id != 'original':
                candidate = config.get(vad_id, {})
                if not candidate.get('python') or not candidate.get('model') or candidate.get('status') not in ('ready', 'ok'):
                    slot.update(status='blocked', reason=candidate.get('reason', 'Candidate is not provisioned'))
                    write(path, study)
                    continue
                pinned = study.setdefault('candidate_configs', {})
                if vad_id in pinned and pinned[vad_id] != candidate:
                    raise ValueError(f'Candidate configuration changed: {vad_id}; use a new study')
                pinned[vad_id] = candidate
                vad_key = f'{vad_id}-{clip["id"]}'
                vad_run = study['vad_runs'].get(vad_key)
                vad_out = folder / 'vad' / vad_key
                if vad_run is None:
                    command = [str(candidate['python']), '-m', 'experiments.vad_comparison.vad_stage',
                        '--audio', clip['audio'], '--offset', str(clip['offset']), '--out', str(vad_out),
                        '--vad-id', vad_id, '--model', str(candidate['model']),
                        '--revision', candidate['revision'], '--device', candidate.get('device', 'cpu')]
                    print(f'VAD {vad_key}', flush=True)
                    study['vad_runs'][vad_key] = {'status': 'running', 'command': command}
                    write(path, study)
                    cost = execute(command, folder / 'logs' / f'vad-{vad_key}')
                    vad_run = dict(cost, manifest_path=str(vad_out / 'manifest.json'))
                    if Path(vad_run['manifest_path']).is_file():
                        vad_run['manifest_sha256'] = sha256(Path(vad_run['manifest_path']))
                    study['vad_runs'][vad_key] = vad_run
                    write(path, study)
                if 'exit_code' not in vad_run:
                    raise RuntimeError(f'Interrupted VAD stage {vad_key}; inspect before a new attempt')
                slot['vad_process_wall_s'] = vad_run['wall_s']
                if vad_run['exit_code'] or not Path(vad_run['manifest_path']).is_file():
                    slot.update(status='invocation_failed', reason='VAD stage failed', failure_path=str(vad_out / 'failure.json'))
                    write(path, study)
                    continue
                manifest = Path(vad_run['manifest_path'])
                if sha256(manifest) != vad_run['manifest_sha256']:
                    raise ValueError(f'Frozen VAD manifest changed: {manifest}')
                slot['vad_manifest_path'] = str(manifest)
                slot['vad_manifest_sha256'] = sha256(manifest)
            else:
                slot['vad_process_wall_s'] = 0.0
            out = ROOT / f'.local/{family}-demo' / slot['run_id']
            command = [str(whisper if family == 'w0' else Path(sys.executable)), '-m',
                       f'experiments.{family}_demo.run', '--audio', clip['audio'],
                       '--offset', str(clip['offset']), '--out', str(out)]
            if manifest:
                command += ['--vad-manifest', str(manifest)]
                if family == 'x0':
                    command += ['--segmentation', 'vad']
            print(f'RUN {route["id"]} {clip["id"]}', flush=True)
            slot['status'] = 'running'
            slot['started_utc'] = datetime.now(timezone.utc).isoformat()
            slot['command'] = command
            write(path, study)
            cost = execute(command, folder / 'logs' / slot['run_id'])
            slot.update(process_wall_s=cost['wall_s'], process=cost)
            result_path = out / 'result.json'
            if result_path.is_file() and cost['exit_code'] in (0, 2):
                result = json.loads(result_path.read_text(encoding='utf-8'))
                slot.update(status='partial' if result.get('status') == 'partial' or cost['exit_code'] else 'completed',
                            result_path=str(result_path), result_sha256=sha256(result_path))
            else:
                slot.update(status='invocation_failed', failure_path=str(out / 'failure.json'))
            write(path, study)
            print(f'DONE {slot["status"]} {cost["wall_s"]:.1f}s', flush=True)
    study['terminal'] = all(run['status'] in ('completed', 'partial', 'invocation_failed', 'missing', 'blocked')
                            for route in study['routes'] for run in route['runs'])
    study['input_checks_after'] = verify_clips(study['clips'])
    write(path, study)
    print(json.dumps({'study': str(path), 'terminal': study['terminal']}), flush=True)


if __name__ == '__main__':
    main()
