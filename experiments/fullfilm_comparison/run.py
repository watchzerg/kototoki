"""Serial, resident-stage comparison covering both full films and all four routes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from experiments.w0_demo.run import gpu_lock, sha256
from experiments.vad_comparison.run import verify_clips

ROOT = Path(__file__).resolve().parents[2]
STRATEGIES = ('pyannote-current', 'cut-merge')


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def source_paths() -> list[Path]:
    paths = [ROOT/'experiments/fullfilm_comparison'/name for name in ('__init__.py', 'run.py', 'segment.py', 'worker.py')]
    for folder in ('w0_demo', 'x0_demo', 'qwen'):
        paths.extend(p for p in (ROOT/'experiments'/folder).glob('*.py') if not p.name.startswith('test_'))
    paths.extend((ROOT/'kototoki_eval').glob('*.py'))
    return sorted(set(paths))


def check_sources(sources: dict) -> None:
    for name, digest in sources.items():
        if sha256(ROOT/name) != digest:
            raise RuntimeError(f'Frozen inference source changed: {name}')


def execute(command: list[str], prefix: Path, environment: dict) -> dict:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with prefix.with_suffix('.stdout.log').open('x', encoding='utf-8') as stdout, \
            prefix.with_suffix('.stderr.log').open('x', encoding='utf-8') as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr)
        try:
            code = child.wait()
        except BaseException:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            raise
    return {'command': command, 'pid': child.pid, 'exit_code': code,
            'wall_s': time.perf_counter()-started}


def initialize(folder: Path, corpus_path: Path, candidate_path: Path) -> dict:
    corpus = read(corpus_path)
    candidates = read(candidate_path)
    candidate = candidates.get('candidates', candidates)['pyannote-current']
    if candidate['device'] != 'cuda:0' or candidate['status'] != 'ready':
        raise ValueError('Frozen ready CUDA Pyannote candidate required')
    sources = {}
    for path in source_paths():
        name = path.relative_to(ROOT).as_posix()
        target = folder/'source'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        sources[name] = sha256(path)
    study = {'schema_version': 1, 'study_id': folder.name, 'terminal': False,
             'created_utc': datetime.now(timezone.utc).isoformat(),
             'corpus_plan_path': str(corpus_path.resolve()), 'corpus_plan_sha256': sha256(corpus_path),
             'candidate_path': str(candidate_path.resolve()), 'candidate_sha256': sha256(candidate_path),
             'candidate': candidate, 'clips': corpus['clips'], 'source_sha256': sources,
             'input_checks_before': verify_clips(corpus['clips']), 'segmentation_runs': {},
             'protocol': {'full_audio': True, 'inference_plan_scope': 'whole film; no scoring-bin reset',
                          'failure_policy': 'record failed source chunk, continue remaining chunks without retry',
                          'scoring_bins_s': 300, 'exclude_policy': 'paired union of failed scoring bins'},
             'routes': []}
    for family in ('w0', 'x0'):
        for strategy in STRATEGIES:
            route = f'{family}-{strategy}'
            study['routes'].append({'id': route, 'family': family, 'segmentation': strategy,
                'runs': [{'clip_id': c['id'], 'status': 'pending'} for c in corpus['clips']]})
    return study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study-id', default='fullfilm-v1')
    parser.add_argument('--corpus', type=Path, default=ROOT/'.local/fullfilm-comparison/fullfilm-v1/plan.json')
    parser.add_argument('--candidates', type=Path, default=ROOT/'.local/vad-comparison/provision-pyannote-gpu-v1/candidates.json')
    parser.add_argument('--routes', nargs='*')
    parser.add_argument('--clips', nargs='*')
    args = parser.parse_args()
    if not args.study_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.study_id):
        parser.error('study-id must be lowercase ASCII letters, digits and hyphens')
    folder = ROOT/'.local/fullfilm-comparison'/args.study_id
    with gpu_lock(ROOT/'.local/gpu.lock', 'fullfilm-comparison-v1'):
        run_study(folder, args)


def run_study(folder: Path, args: argparse.Namespace) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/'study.json'
    study = read(path) if path.exists() else initialize(folder, args.corpus, args.candidates)
    if any(s['status']=='running' for r in study['routes'] for s in r['runs']) or any(
            v.get('status')=='running' for v in study['segmentation_runs'].values()):
        raise RuntimeError('Inspect interrupted running work; refusing duplicate inference')
    if sha256(Path(study['corpus_plan_path'])) != study['corpus_plan_sha256'] or sha256(
            Path(study['candidate_path'])) != study['candidate_sha256']:
        raise RuntimeError('Frozen corpus or candidate changed')
    check_sources(study['source_sha256'])
    study.update(terminal=False, controller_pid=os.getpid(), controller_started_utc=datetime.now(timezone.utc).isoformat())
    write(path, study)
    temp = folder/'tmp'
    temp.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               KOTOTOKI_FULLFILM_PARENT_PID=str(os.getpid()), TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
    whisper = ROOT/'.local/envs/whisper-latest/Scripts/python.exe'
    qwen = ROOT/'.local/envs/qwen-hf-final/Scripts/python.exe'
    for clip in study['clips']:
        if args.clips and clip['id'] not in args.clips:
            continue
        for strategy in STRATEGIES:
            selected = [r for r in study['routes'] if r['segmentation']==strategy and (not args.routes or r['id'] in args.routes)]
            if not selected:
                continue
            key = f'{strategy}-{clip["id"]}'
            seg = study['segmentation_runs'].get(key)
            if seg is None:
                job_path = folder/'jobs'/f'{key}-segment.json'
                write(job_path, {'clip': clip, 'segmentation': strategy, 'candidate': study['candidate'],
                                 'source_sha256': study['source_sha256']})
                out = folder/'segmentation'/key
                study['segmentation_runs'][key] = {'status': 'running'}
                write(path, study)
                print(f'SEGMENT {key}', flush=True)
                cost = execute([study['candidate']['python'], '-m', 'experiments.fullfilm_comparison.segment',
                                '--job', str(job_path), '--out', str(out)], folder/'logs'/key, env)
                manifest = out/'plan.json'
                seg = {**cost, 'status': 'completed' if cost['exit_code']==0 and manifest.exists() else 'failed',
                       'manifest_path': str(manifest)}
                if manifest.exists():
                    seg['manifest_sha256'] = sha256(manifest)
                study['segmentation_runs'][key] = seg
                write(path, study)
            for route in selected:
                slot = next(s for s in route['runs'] if s['clip_id']==clip['id'])
                if slot['status'] != 'pending':
                    continue
                if seg['status'] != 'completed':
                    slot.update(status='invocation_failed', failure_reason='Segmentation process failed')
                    write(path, study)
                    continue
                plan_path = Path(seg['manifest_path'])
                if sha256(plan_path) != seg['manifest_sha256']:
                    raise RuntimeError('Segmentation plan changed')
                family = route['family']
                out = folder/'runs'/f'{route["id"]}-{clip["id"]}'
                out.mkdir(parents=True, exist_ok=False)
                job = {'schema_version': 1, 'route': family.upper(),
                       'plan_path': str(plan_path), 'plan_sha256': seg['manifest_sha256'],
                       'source_sha256': study['source_sha256'],
                       'asr_model': str(ROOT/'.local/models'/('faster-whisper-large-v3' if family=='w0' else 'qwen3-asr-1.7b-hf')),
                       'mms_model': str(ROOT/'.local/models/mms-1b-all'),
                       'mel_path': str(ROOT/'.local/models/w0-assets/mel_filters.npz'),
                       'dll_dir': str(ROOT/'.local/tools/whisper-runtime-provisional')}
                job_path = out/'asr-job.json'
                write(job_path, job)
                slot.update(status='running', plan_path=str(plan_path), plan_sha256=seg['manifest_sha256'],
                            segmentation_process_wall_s=seg['wall_s'], processes={})
                write(path, study)
                print(f'ASR {route["id"]} {clip["id"]}', flush=True)
                cost = execute([str(whisper if family=='w0' else qwen), '-m', 'experiments.fullfilm_comparison.worker',
                                'asr', '--job', str(job_path), '--out', str(out/'asr')], out/'asr', env)
                slot['processes']['asr'] = cost
                asr_path = out/'asr/asr.json'
                if cost['exit_code'] not in (0,2) or not asr_path.exists():
                    slot.update(status='invocation_failed', failure_path=str(out/'asr/failure.json'))
                    write(path, study)
                    print(f'FAILED ASR {route["id"]} {clip["id"]}', flush=True)
                    continue
                slot.update(asr_path=str(asr_path), asr_sha256=sha256(asr_path))
                write(path, study)
                job.update(asr_stage_path=str(asr_path), asr_stage_sha256=sha256(asr_path))
                job_path = out/'align-job.json'
                write(job_path, job)
                print(f'ALIGN {route["id"]} {clip["id"]}', flush=True)
                cost = execute([str(whisper), '-m', 'experiments.fullfilm_comparison.worker', 'align',
                                '--job', str(job_path), '--out', str(out/'align')], out/'align', env)
                slot['processes']['align'] = cost
                result_path = out/'align/alignment.json'
                if cost['exit_code'] in (0,2) and result_path.exists():
                    result = read(result_path)
                    slot.update(status='partial' if result.get('status')=='partial' else 'completed',
                                result_path=str(result_path), result_sha256=sha256(result_path))
                else:
                    slot.update(status='invocation_failed', failure_path=str(out/'align/failure.json'))
                write(path, study)
                print(f'DONE {route["id"]} {clip["id"]} {slot["status"]}', flush=True)
    check_sources(study['source_sha256'])
    study['input_checks_after'] = verify_clips(study['clips'])
    study['terminal'] = all(s['status'] in ('completed','partial','invocation_failed') for r in study['routes'] for s in r['runs'])
    write(path, study)
    print(json.dumps({'study': str(path), 'terminal': study['terminal']}), flush=True)


if __name__ == '__main__':
    main()
