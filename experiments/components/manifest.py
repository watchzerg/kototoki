"""Assemble an immutable paired evaluator manifest from component run evidence."""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.components.run import ROOT, LOCAL, digest, read, write_new
from experiments.qwen.run_cross import validate_ctc_evidence


def verify_gpu(route, result):
    if result.get('status', 'ok') != 'ok':
        return False
    if route in ('w0', 'w1'):
        if result.get('devices', {}).get('asr', {}).get('device') != 'cuda':
            return False
        if route == 'w1':
            vad = result.get('devices', {}).get('vad', {}).get('forward_observation', [])
            if not vad or any(not r.get('input', '').startswith('cuda') for r in vad):
                return False
            validate_ctc_evidence(result)
    else:
        validate_ctc_evidence(result)
        pipeline = result.get('pipeline', {})
        if pipeline.get('status') != 'completed' or pipeline.get('new_asr_inference') is not True:
            return False
    return True


def build(name, output):
    plan = read(LOCAL / name / 'plan.json')
    previous = read(ROOT / '.local/round2/progress.json')['tasks']
    result = {'schema_version': 1, 'manifest_id': name, 'frozen': True, 'strict_hashes': True,
              'clips': plan['clips'], 'source_sha256': plan['source_sha256'],
              'configuration_policy': 'one preprocessing component; historic baseline vs fresh downstream ASR; exposed development',
              'configurations': []}
    for route in ('w0', 'w1', 'x0'):
        for enhanced in (False, True):
            config = {'id': route + ('-vocals' if enhanced else '-baseline'),
                      'model_metadata': {'base': route, 'component': plan['component'] if enhanced else None}, 'runs': []}
            for clip in plan['clips']:
                if enhanced:
                    task = next(t for t in plan['tasks'] if t['clip'] == clip['id'] and t['stage'] == route)
                    path = Path(task['output'])
                    run_id = task['id']
                    status_path = LOCAL / name / 'progress' / (run_id + '.json')
                    status = read(status_path)['status'] if status_path.exists() else 'missing'
                    audio = task['audio']
                else:
                    entry = previous[f'{clip["id"]}-{route}']
                    path, run_id, status = Path(entry['output']), entry['id'], entry['status']
                    audio = clip['audio']
                run = {'clip_id': clip['id'], 'run_id': run_id,
                       'status': 'invocation_failed' if status in ('failed', 'blocked') else status,
                       'result_path': str(path), 'execution_verified': False,
                       'input_audio_path': str(audio), 'evidence': {'cached_baseline': not enhanced}}
                if Path(audio).exists():
                    run['input_audio_sha256'] = digest(audio)
                if path.exists():
                    run['result_sha256'] = digest(path)
                if status == 'completed':
                    data = read(path)
                    harness = read(ROOT / '.local/results' / run_id / 'manifest.json')
                    if harness['status'] != 'completed' or harness.get('reference_unchanged') is not True:
                        raise ValueError('Harness not verified complete')
                    if harness['audio_sha256'] != digest(audio):
                        raise ValueError('Harness audio mismatch')
                    if data.get('input', {}).get('file_sha256') != digest(audio):
                        raise ValueError('Backend audio identity mismatch')
                    if data.get('offset_s') != clip['offset']:
                        raise ValueError('Backend source offset mismatch')
                    if enhanced or route != 'x0':
                        run['execution_verified'] = verify_gpu(route, data)
                    else:
                        validate_ctc_evidence(data)
                        # This historical X0 reused round2 Q0 ASR; its immutable
                        # upstream harness and actual device were audited in round2.
                        upstream = previous[f'{clip["id"]}-q0']
                        qwen = read(upstream['output'])
                        devices = qwen.get('environment', {}).get('devices', {}).get('asr', {})
                        run['evidence']['upstream_asr_devices'] = devices
                        if not devices or 'cuda' not in str(devices):
                            raise ValueError('Historical Qwen CUDA evidence absent')
                        run['execution_verified'] = True
                    if not run['execution_verified']:
                        run['status'] = 'execution_unverified'
                    run['evidence']['harness_wall_seconds'] = harness.get('wall_seconds')
                    run['evidence']['harness_sha256'] = digest(ROOT / '.local/results' / run_id / 'manifest.json')
                config['runs'].append(run)
            result['configurations'].append(config)
    write_new(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.name, args.output)
