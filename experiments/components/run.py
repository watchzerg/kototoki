"""Run frozen single-component experiments without changing historical adapters."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/components'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def replace(command, option, value):
    if command.count(option) != 1:
        raise ValueError(f'Expected one {option}')
    command[command.index(option) + 1] = str(value)


def verify_separation(task, clip, output):
    manifest = read(output)
    if manifest.get('status') != 'ok' or manifest['input']['file_sha256'] != clip['audio_sha256']:
        raise ValueError('Separation source/status mismatch')
    if manifest['output']['file_sha256'] != digest(task['audio']):
        raise ValueError('Separation WAV changed')
    if manifest['timeline']['source_origin_s'] != clip['offset']:
        raise ValueError('Separation source origin mismatch')
    with wave.open(task['audio'], 'rb') as audio:
        if (audio.getnframes(), audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (
                round(clip['duration'] * 16000), 16000, 1, 2):
            raise ValueError('Separation timeline/PCM mismatch')
    device = manifest['device']
    if device['actual'] != 'cuda:0' or device['forward_evidence']['count'] < 1:
        raise ValueError('Separation GPU execution unverified')


def prepare(name, all_clips=False):
    corpus = read(ROOT / '.local/round2/corpus/manifest.json')
    historical = read(ROOT / '.local/round2/progress.json')['tasks']
    clips = [c for c in corpus['clips'] if all_clips or c['id'].endswith(('01', '04'))]
    plan = {'schema_version': 1, 'id': name, 'scope': 'exposed development single-component ablation',
            'clips': clips, 'component': 'Demucs 4.1.0 htdemucs single model vocals; shifts0 overlap0.25',
            'input_policy': 'same prepared mono16k input -> vocals mono16k exact length; every downstream stage uses vocals',
            'tasks': [], 'source_sha256': {}, 'model_sha256': {}}
    for filename in ('run.py', 'separate.py', 'manifest.py', 'evaluate.py'):
        p = ROOT / 'experiments/components' / filename
        plan['source_sha256'][str(p)] = digest(p)
    for folder in ('experiments/whisper', 'experiments/qwen'):
        for p in sorted((ROOT / folder).glob('*.py')):
            if not p.name.startswith('test_'):
                plan['source_sha256'][str(p)] = digest(p)
    for relative in ('experiments/run_experiment.py', 'experiments/whisper/requirements-whisperx.lock',
                     'experiments/whisper/requirements-w0.lock', 'experiments/qwen/requirements.lock'):
        p = ROOT / relative
        plan['source_sha256'][str(p)] = digest(p)
    for folder in ('htdemucs', 'faster-whisper-large-v3', 'wav2vec2-large-xlsr-53-japanese', 'qwen3-asr-1.7b-hf'):
        for p in sorted((ROOT / '.local/models' / folder).rglob('*')):
            if p.is_file():
                plan['model_sha256'][str(p)] = digest(p)
    vad = ROOT / '.local/envs/whisper-latest/Lib/site-packages/whisperx/assets/pytorch_model.bin'
    plan['model_sha256'][str(vad)] = digest(vad)
    for clip in clips:
        sep_dir = LOCAL / name / 'audio' / clip['id']
        sep_id = f'{name}-{clip["id"]}-sep'
        sep_command = [str(ROOT / '.local/envs/demucs/Scripts/python.exe'),
                       str(ROOT / 'experiments/components/separate.py'), '--audio', clip['audio'],
                       '--repo', str(ROOT / '.local/models/htdemucs'), '--out', str(sep_dir),
                       '--offset', str(clip['offset'])]
        plan['tasks'].append({'id': sep_id, 'stage': 'separation', 'clip': clip['id'],
                              'audio': clip['audio'], 'output': str(sep_dir / 'manifest.json'),
                              'command': sep_command})
        for route in ('w0', 'w1', 'x0'):
            run_id = f'{name}-{clip["id"]}-{route}'
            output = ROOT / '.local/results' / run_id / 'result.json'
            audio = sep_dir / 'vocals.wav'
            if route != 'x0':
                command = list(historical[f'{clip["id"]}-{route}']['command'])
                replace(command, '--audio', audio)
                replace(command, '--output', output)
            else:
                command = [sys.executable, str(ROOT / 'experiments/qwen/run_cross.py'),
                           '--audio', str(audio), '--output', str(output), '--offset', str(clip['offset']),
                           '--dll-dir', str(ROOT / '.local/tools/whisper-runtime-provisional')]
            plan['tasks'].append({'id': run_id, 'stage': route, 'clip': clip['id'],
                                 'audio': str(audio), 'output': str(output), 'command': command,
                                 'depends_on': sep_id})
    write_new(LOCAL / name / 'plan.json', plan)
    return plan


def run(name):
    plan_path = LOCAL / name / 'plan.json'
    plan = read(plan_path)
    for key in ('source_sha256', 'model_sha256'):
        for p, expected in plan[key].items():
            if digest(p) != expected:
                raise ValueError(f'Frozen identity changed: {p}')
    clips = {c['id']: c for c in plan['clips']}
    for task in plan['tasks']:
        record = LOCAL / name / 'progress' / (task['id'] + '.json')
        if record.exists():
            prior = read(record)
            if prior.get('plan_sha256') != digest(plan_path):
                raise ValueError('Progress belongs to another frozen plan')
            if prior['status'] == 'completed' and digest(task['output']) != prior['output_sha256']:
                raise ValueError('Completed output changed')
            if prior.get('harness_sha256') and digest(ROOT / '.local/results' / task['id'] / 'manifest.json') != prior['harness_sha256']:
                raise ValueError('Completed harness changed')
            continue
        clip = clips[task['clip']]
        if digest(clip['audio']) != clip['audio_sha256'] or digest(clip['reference']) != clip['reference_sha256']:
            raise ValueError('Original clip/reference identity changed')
        if task.get('depends_on'):
            parent = read(LOCAL / name / 'progress' / (task['depends_on'] + '.json'))
            if parent['status'] != 'completed':
                write_new(record, {'status': 'blocked', 'reason': 'separation_failed', 'plan_sha256': digest(plan_path)})
                continue
            separation = next(t for t in plan['tasks'] if t['id'] == task['depends_on'])
            if digest(separation['output']) != parent['output_sha256']:
                raise ValueError('Parent separation manifest changed')
            verify_separation(task, clip, separation['output'])
        command = [sys.executable, str(ROOT / 'experiments/run_experiment.py'), '--id', task['id'],
                   '--audio', task['audio'], '--reference', clip['source_srt'],
                   '--reference-sha256', clip['source_srt_sha256'], '--timeout', '3600', '--', *task['command']]
        harness_path = ROOT / '.local/results' / task['id'] / 'manifest.json'
        if harness_path.parent.exists():
            if harness_path.exists():
                old = read(harness_path)
                if (old.get('status') == 'completed' and old.get('command') == task['command']
                        and old.get('audio_sha256') == digest(task['audio'])
                        and old.get('reference_unchanged') is True and Path(task['output']).exists()):
                    write_new(record, {'status': 'completed', 'returncode': 0,
                              'plan_sha256': digest(plan_path), 'command': command,
                              'harness_sha256': digest(harness_path), 'output_sha256': digest(task['output']),
                              'recovered_completed_harness': True})
                    continue
            raise RuntimeError(f'Interrupted evidence retained at {harness_path.parent}; use a new experiment identity')
        print(json.dumps({'starting': task['id']}), flush=True)
        done = subprocess.run(command, cwd=ROOT, check=False)
        result = {'status': 'completed' if done.returncode == 0 else 'failed', 'returncode': done.returncode,
                  'plan_sha256': digest(plan_path), 'command': command}
        if Path(task['output']).exists():
            result['output_sha256'] = digest(task['output'])
        if harness_path.exists():
            result['harness_sha256'] = digest(harness_path)
        if result['status'] == 'completed' and 'output_sha256' not in result:
            result['status'] = 'failed'
        write_new(record, result)
        print(json.dumps({'finished': task['id'], 'status': result['status']}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--name', required=True)
    parser.add_argument('--all-clips', action='store_true')
    args = parser.parse_args()
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.name):
        raise ValueError('Use a lowercase simple experiment name')
    if args.action == 'prepare':
        prepare(args.name, args.all_clips)
    else:
        run(args.name)


if __name__ == '__main__':
    main()
