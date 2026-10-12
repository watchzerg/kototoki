"""Supplemental isolated VAD-only costs; run only after the main GPU batch."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
VADS = ('original', 'silero', 'fsmn', 'firered', 'pyannote-current')


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def chunks_digest(chunks: list[dict]) -> str:
    return hashlib.sha256(json.dumps(chunks, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def verify_input(identity: dict, clip: dict) -> None:
    """The frozen plan and read_audio hash raw PCM16 bytes, not float32 arrays."""
    if (identity['file_sha256'] != clip['audio_sha256'] or
            identity['pcm_sha256'] != clip['pcm_sha256'] or
            identity['duration_s'] != clip['duration'] or
            identity['sample_rate'] != 16000 or identity['channels'] != 1):
        raise ValueError('Frozen clip changed')


def memory_sample(pid: int | None = None, handle=None) -> dict:
    """Query only self or a Popen child handle; no arbitrary native process opens.

    Native field definitions: https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters
    """
    try:
        import psutil
    except ImportError:
        if os.name != 'nt':
            raise RuntimeError('Memory measurement requires psutil or native Windows')
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        *[(name, ctypes.c_size_t) for name in (
                            'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                            'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        query = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        query.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if pid is not None and handle is None:
            raise ValueError('Native queries require the owned child handle')
        owned = kernel.GetCurrentProcess() if handle is None else int(handle)
        if not query(owned, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'rss_bytes': counters.WorkingSetSize, 'peak_working_set_bytes': counters.PeakWorkingSetSize,
                'provider': 'Windows GetProcessMemoryInfo'}
    info = psutil.Process(pid).memory_info()
    return {'rss_bytes': info.rss,
            'peak_working_set_bytes': getattr(info, 'peak_wset', getattr(info, 'peak_rss', None)),
            'provider': f'psutil {psutil.__version__}'}


def compare_chunks(result: dict, path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {'status': 'unavailable'}
    saved = read(path)
    if (saved.get('input', {}).get('file_sha256') != result['input']['file_sha256']
            or saved.get('input', {}).get('pcm_sha256') != result['input']['pcm_sha256']
            or saved.get('offset_s') != result['offset_s']):
        raise ValueError('Comparison input identity or offset differs')
    return {'status': 'compared', 'path': str(path), 'file_sha256': digest(path),
            'chunks_equal': chunks_digest(saved['chunks']) == result['chunks_sha256']}


def worker(job_path: Path) -> None:
    started = time.perf_counter()
    job = read(job_path)
    out = job_path.parent
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', PYANNOTE_METRICS_ENABLED='0',
                      HF_HOME=str(out / 'cache/hf'), TORCH_HOME=str(out / 'cache/torch'),
                      XDG_CACHE_HOME=str(out / 'cache'), TOKENIZERS_PARALLELISM='false')
    vad = None
    handles = []
    samples, errors = [], []
    stop = threading.Event()
    def sample_self() -> None:
        while not stop.is_set():
            try:
                samples.append(dict(memory_sample(), elapsed_s=time.perf_counter() - started))
            except Exception as error:
                errors.append(type(error).__name__)
            stop.wait(.05)
    sampler = threading.Thread(target=sample_self, daemon=True)
    sampler.start()
    try:
        mark = time.perf_counter()
        from experiments.w0_demo.run import gpu_lock, read_audio, setup_runtime
        from experiments.w0_demo.vad import PyannoteVad
        from experiments.w0_demo.vad_candidates import create_vad
        module_import_s = time.perf_counter() - mark
        mark = time.perf_counter()
        audio, identity = read_audio(Path(job['clip']['audio']))
        input_read_s = time.perf_counter() - mark
        verify_input(identity, job['clip'])
        candidate = job['candidate']
        gpu = candidate['device'].startswith('cuda')
        cuda = None
        with gpu_lock(ROOT / '.local/gpu.lock', 'vad-resource-v1') if gpu else nullcontext():
            mark = time.perf_counter()
            if gpu:
                handles = setup_runtime(out, ROOT / '.local/tools/whisper-runtime-provisional')
            import torch
            backend_import_s = time.perf_counter() - mark
            if gpu:
                torch.cuda.init()
                torch.cuda.reset_peak_memory_stats(0)
            mark = time.perf_counter()
            vad = (PyannoteVad(Path(candidate['model'])) if job['vad_id'] == 'original'
                   else create_vad(job['vad_id'], Path(candidate['model']), device=candidate['device'],
                                   model_revision=candidate['revision']))
            if gpu:
                torch.cuda.synchronize()
            load_s = time.perf_counter() - mark
            mark = time.perf_counter()
            chunks = vad.segment(audio)
            if gpu:
                torch.cuda.synchronize()
                cuda = {'peak_allocated_bytes': torch.cuda.max_memory_allocated(0),
                        'peak_reserved_bytes': torch.cuda.max_memory_reserved(0),
                        'scope': 'Torch allocator after CUDA init and before model load through inference; excludes CUDA context and other libraries'}
            inference_s = time.perf_counter() - mark
            metadata = dict(vad.metadata)
            vad.close()
            vad = None
        if any(digest(ROOT / name) != value for name, value in job['source_sha256'].items()):
            raise RuntimeError('Source changed during measurement')
        if model_hashes(Path(candidate['model'])) != job['model_files_sha256']:
            raise RuntimeError('Model changed during measurement')
        result = {'schema_version': 1, 'status': 'ok', 'scope': 'isolated VAD only; excludes ASR and MMS',
                  'fresh_inference': True, 'vad_id': job['vad_id'], 'input': identity,
                  'offset_s': job['clip']['offset'], 'chunks': chunks,
                  'chunks_sha256': chunks_digest(chunks), 'chunk_count': len(chunks),
                  'retained_samples': sum(c.get('end_sample', int(c['end'] * 16000)) -
                                          c.get('start_sample', int(c['start'] * 16000)) for c in chunks),
                  'metadata': metadata, 'candidate': candidate,
                  'model_files_sha256': job['model_files_sha256'], 'source_sha256': job['source_sha256'],
                  'python': sys.version, 'executable': sys.executable, 'cuda_allocator': cuda,
                  'stages': {'module_import_s': module_import_s, 'input_read_s': input_read_s,
                             'torch_runtime_import_s': backend_import_s, 'vad_load_s': load_s,
                             'vad_inference_s': inference_s},
                  'memory_near_completion': memory_sample()}
        result['comparison'] = compare_chunks(result, Path(job['comparison']) if job.get('comparison') else None)
        stop.set()
        sampler.join(timeout=1)
        result['worker_memory'] = {
            'pid': os.getpid(), 'sample_count': len(samples), 'sample_interval_s': .05,
            'sampled_rss_peak_bytes': max((s['rss_bytes'] for s in samples), default=None),
            'lifetime_peak_working_set_bytes': result['memory_near_completion']['peak_working_set_bytes'],
            'scope': 'actual inference interpreter lifetime peak through teardown and identity checks; RSS sampled from worker entry, excludes launcher, controller and descendant processes',
            'samples': samples, 'sampling_errors': errors}
        result['stages']['worker_wall_s'] = time.perf_counter() - started
        write(out / 'result.json', result)
    except Exception as error:
        write(out / 'failure.json', {'status': 'failed', 'type': type(error).__name__, 'message': str(error)})
        raise
    finally:
        stop.set()
        sampler.join(timeout=1)
        if vad is not None:
            vad.close()
        for handle in handles:
            handle.close()


def model_hashes(path: Path) -> dict:
    files = [path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file())
    if not files:
        raise FileNotFoundError(f'No provisioned model files: {path}')
    return {str(p.resolve()): digest(p) for p in files}


def execute(command: list[str], out: Path) -> dict:
    memory_sample()  # Fail before launching inference if no measurement provider exists.
    started = time.perf_counter()
    samples, errors = [], []
    temp = out / 'tmp'
    temp.mkdir()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONUTF8='1',
               TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
    with (out / 'stdout.log').open('x', encoding='utf-8') as stdout, \
            (out / 'stderr.log').open('x', encoding='utf-8') as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        try:
            while child.poll() is None:
                try:
                    sample = memory_sample(child.pid, getattr(child, '_handle', None))
                    samples.append(dict(sample, elapsed_s=time.perf_counter() - started))
                except Exception as error:
                    errors.append(type(error).__name__)
                time.sleep(.05)
            # The Windows Popen handle remains owned after exit, allowing the final lifetime peak query.
            if os.name == 'nt':
                try:
                    samples.append(dict(memory_sample(child.pid, child._handle),
                                        elapsed_s=time.perf_counter() - started))
                except Exception as error:
                    errors.append(type(error).__name__)
        except BaseException:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            raise
    cost = {'exit_code': child.returncode, 'full_process_wall_s': time.perf_counter() - started,
            'command': command, 'pid': child.pid, 'memory_sample_count': len(samples),
            'sample_interval_s': .05, 'sampled_rss_peak_bytes': max((s['rss_bytes'] for s in samples), default=None),
            'observed_lifetime_peak_working_set_bytes': max((s['peak_working_set_bytes'] or 0 for s in samples), default=None),
            'scope': 'Popen process only; Windows venv launcher may spawn actual interpreter. Use result.worker_memory for inference interpreter memory.',
            'memory_samples': samples, 'sampling_errors': errors}
    write(out / 'process-cost.json', cost)
    return cost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--candidates', type=Path, default=ROOT / '.local/vad-comparison/provision/candidates.json')
    parser.add_argument('--study', type=Path, default=ROOT / '.local/vad-comparison/vad-comparison-v1/study.json')
    parser.add_argument('--out', type=Path, default=ROOT / '.local/vad-comparison/resource-v1')
    parser.add_argument('--vads', nargs='+', choices=VADS, default=list(VADS))
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / '.local/vad-comparison'):
        raise ValueError('Output must remain under .local/vad-comparison')
    out.mkdir(parents=True, exist_ok=False)
    plan_path = ROOT / '.local/round2/plan.json'
    clip = next(c for c in read(plan_path)['clips'] if c['id'] == 'hf-ii-window-01')
    config = read(args.candidates)
    candidates = config.get('candidates', config)
    candidates['original'] = {'python': str(ROOT / '.local/envs/whisper-latest/Scripts/python.exe'),
                              'model': str(ROOT / '.local/models/w0-assets/pytorch_model.bin'),
                              'revision': 'w0-pyannote-mms-v1', 'device': 'cuda:0', 'status': 'ready'}
    shutil.copy2(args.candidates, out / 'candidates.json')
    sources = [Path(__file__), *sorted((ROOT / 'experiments/w0_demo').glob('*.py')),
               ROOT / 'kototoki_eval/schema.py']
    source_hashes = {}
    for source in sources:
        name = source.relative_to(ROOT).as_posix()
        target = out / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        source_hashes[name] = digest(source)
    study = read(args.study) if args.study.is_file() else {}
    summary = {'schema_version': 1, 'scope': 'supplemental isolated VAD only; not end-to-end ASR/MMS',
               'plan_sha256': digest(plan_path), 'candidates_sha256': digest(args.candidates), 'clip': clip, 'runs': {}}
    for vad_id in args.vads:
        candidate = candidates[vad_id]
        if candidate.get('status') not in ('ready', 'ok'):
            summary['runs'][vad_id] = {'status': 'blocked', 'reason': candidate.get('reason', 'not provisioned')}
            continue
        folder = out / vad_id
        folder.mkdir()
        comparison = study.get('vad_runs', {}).get(f"{vad_id}-{clip['id']}", {}).get('manifest_path')
        if vad_id == 'original':
            route = next((r for r in study.get('routes', []) if r['id'] == 'w0-original'), {})
            slot = next((s for s in route.get('runs', []) if s['clip_id'] == clip['id']), {})
            comparison = slot.get('result_path')
        job = {'vad_id': vad_id, 'candidate': candidate, 'clip': clip, 'comparison': comparison,
               'model_files_sha256': model_hashes(Path(candidate['model'])), 'source_sha256': source_hashes}
        write(folder / 'job.json', job)
        cost = execute([candidate['python'], '-m', 'experiments.vad_comparison.resources',
                        '--worker', str(folder / 'job.json')], folder)
        summary['runs'][vad_id] = {'status': 'ok' if cost['exit_code'] == 0 else 'failed',
                                   'process_cost_path': str(folder / 'process-cost.json')}
        write(out / 'summary.json', summary)
    write(out / 'summary.json', summary)
    print(f"VAD-only resource runs: {len(summary['runs'])}; output: {out}")


if __name__ == '__main__':
    main()
