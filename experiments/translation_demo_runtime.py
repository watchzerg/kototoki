"""Run one isolated local llama.cpp model and preserve runtime evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler

from experiments.translation_demo.run import CANDIDATES, asset_manifest_paths, load_assets, select_asset
from experiments.translation_demo.run import explicit_oom
from experiments.translation_demo.profiles import LEGACY_PROFILE, PROFILE_NAMES, resolve_profile
from experiments.translation_monitor import ResourceMonitor


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def residency_evidence(log: str) -> dict:
    """Extract explicit loader placement, without equating mmap to CPU residency."""
    offloads = re.findall(r'offloaded (\d+)/(\d+) layers to GPU', log)
    buffers = re.findall(r'load_tensors:\s+(\S+) model buffer size\s*=\s*([\d.]+) MiB', log)
    gpu_buffers = {device: float(size) for device, size in buffers
                   if re.fullmatch(r'(?:CUDA\d+|Vulkan\d+|SYCL\d+|Metal)', device)}
    cpu_buffers = {device: float(size) for device, size in buffers if device.startswith('CPU')}
    loaded, total = map(int, offloads[-1]) if offloads else (None, None)
    return {'gpu_layers_offloaded': loaded, 'model_layers_total': total,
            'layers_not_offloaded': total - loaded if total is not None else None,
            'partial_layer_offload': loaded < total if total is not None else None,
            'gpu_model_buffers_mib': gpu_buffers, 'cpu_model_buffers_mib': cpu_buffers,
            'evidence_source': 'loader-log',
            'buffer_measurement_scope': 'loader allocations/mappings; not process working set or physical CPU residency'}


def validate_residency(evidence: dict, requested_layers: int, allow_cpu_offload: bool) -> None:
    """Reject missing GPU evidence and unrequested partial layer placement."""
    loaded, total = evidence['gpu_layers_offloaded'], evidence['model_layers_total']
    if loaded is None or total is None or not 0 < loaded <= total:
        raise RuntimeError('Loader did not prove positive GPU layer offload; inspect runtime logs')
    if not any(size > 0 for size in evidence['gpu_model_buffers_mib'].values()):
        raise RuntimeError('Loader did not prove a GPU model buffer; inspect runtime logs')
    if loaded < total and not allow_cpu_offload:
        raise RuntimeError('Partial GPU offload requires explicit --allow-cpu-offload')
    if loaded != min(requested_layers, total):
        raise RuntimeError('Actual GPU layers differ from explicit request; no silent placement fallback is allowed')


def loader_logs(runtime: Path) -> str:
    return '\n'.join(path.read_text(encoding='utf-8', errors='replace')
                     for name in ('server.log', 'stderr.log', 'stdout.log')
                     if (path := runtime / name).exists())


def forward_worker_events(path: Path, offset: int, monitor: ResourceMonitor) -> int:
    """Forward only durable complete worker lines; retain original event timestamps."""
    if not path.exists():
        return offset
    with path.open('rb') as stream:
        stream.seek(offset)
        while True:
            line = stream.readline()
            if not line or not line.endswith(b'\n'):
                return offset
            offset = stream.tell()
            event = json.loads(line)
            if event.get('status') == 'started':
                monitor.mark_phase(event['label'], {'worker_event': event})
            elif event.get('status') in ('interrupted', 'phase_finished', 'not_run'):
                monitor.mark_phase(event['label'], {'worker_event': event})


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', choices=CANDIDATES, required=True)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--mapping-only', type=Path)
    parser.add_argument('--mapper', choices=['hy-mt2-7b-q8', 'tower-plus-9b-q8'], default='hy-mt2-7b-q8')
    parser.add_argument('--mapping-recipe', default='native-boundary-anchors-v2')
    parser.add_argument('--layers', type=int, default=99)
    parser.add_argument('--allow-cpu-offload', action='store_true',
                        help='显式允许部分模型层留在 CPU；必须仍有 GPU 加载证据，不自动回退')
    parser.add_argument('--sampling-profile', choices=PROFILE_NAMES, default=LEGACY_PROFILE,
                        help='版本化采样配置；默认保留历史 greedy 请求')
    parser.add_argument('--n-predict', type=int, help='最大输出 tokens；历史默认 1024，新基线固定 4096')
    parser.add_argument('--context-size', type=int, help='总 context tokens；历史默认 4096，新基线默认 8192')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--engine', type=Path)
    parser.add_argument('--engine-identity', type=Path)
    parser.add_argument('--asset-manifest', type=Path, action='append')
    parser.add_argument('--session-plan', type=Path)
    parser.add_argument('--session-worker', choices=['experiments.translation_four_quantization.worker',
                                                    'experiments.translation_flow.worker',
                                                    'experiments.translation_flow.dispatch',
                                                    'experiments.translation_flow.v2_worker',
                                                    'experiments.translation_flow.v2_source_preparation'])
    parser.add_argument('--stop-on-oom', action='store_true')
    parser.add_argument('--monitor-interval', type=float, default=.25)
    parser.add_argument('--idle-baseline-seconds', type=float, default=30.0)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--threads-batch', type=int, default=8)
    return parser


def main() -> int:
    argument_parser = parser()
    args = argument_parser.parse_args()
    # Managed workers resolve generation from their frozen session plans.
    if args.session_worker and (args.sampling_profile != LEGACY_PROFILE or args.n_predict is not None):
        argument_parser.error('Managed sessions require sampling/output settings in their session plan')
    try:
        profile = resolve_profile(args.sampling_profile, args.candidate, n_predict=args.n_predict,
                                  context_size=args.context_size, mapping_only=bool(args.mapping_only))
    except ValueError as exc:
        argument_parser.error(str(exc))
    args.n_predict, args.context_size = profile['n_predict'], profile['context_size']
    if args.layers <= 0 or args.context_size <= 0:
        argument_parser.error('--layers and --context-size must be positive; CPU-only inference is unsupported')
    if bool(args.session_plan) != bool(args.session_worker):
        argument_parser.error('--session-plan and --session-worker must be supplied together')
    if not args.session_worker and args.inputs is None:
        argument_parser.error('--inputs is required outside a managed session')
    if args.monitor_interval <= 0 or args.idle_baseline_seconds < 30:
        argument_parser.error('Monitor interval must be positive and idle baseline must be at least 30 seconds')
    if args.threads <= 0 or args.threads_batch <= 0:
        argument_parser.error('CPU thread counts must be explicitly positive')
    if args.session_worker and args.mapping_only:
        argument_parser.error('Managed comparison sessions do not support the separate mapping phase')
    root = Path(__file__).resolve().parents[1]
    engine = args.engine.resolve() if args.engine else root / '.local/tools/llama-b11429-cuda13.4/llama-server.exe'
    if args.engine and not args.engine_identity:
        raise ValueError('Custom engine requires explicit identity record')
    manifest_paths = asset_manifest_paths(args.asset_manifest, root)
    assets = load_assets(manifest_paths)
    model_id = args.mapper if args.mapping_only else args.candidate
    asset = select_asset(assets, model_id)
    model = Path(asset['directory']) / asset['file']
    model_sha256 = file_hash(model)
    if model_sha256 != asset['sha256']:
        raise ValueError('Model SHA256 no longer matches verified asset manifest')
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    runtime = out / 'runtime'
    runtime.mkdir()
    url = f'http://127.0.0.1:{args.port}'
    opener = build_opener(ProxyHandler({}))
    try:
        opener.open(url + '/health', timeout=1)
    except OSError:
        pass
    else:
        raise RuntimeError('Port already occupied; do not share another run model')
    cmd = [str(engine), '-m', str(model), '--host', '127.0.0.1', '--port', str(args.port),
           '-c', str(args.context_size), '-np', '1', '-ngl', str(args.layers), '-b', '256', '-ub', '128',
           '-t', str(args.threads), '-tb', str(args.threads_batch), '-ctk', 'f16', '-ctv', 'f16', '--cache-ram', '8192',
           '-fa', 'on', '--fit', 'off', '--no-webui', '--log-file', str(runtime / 'server.log'), '-lv', '4']
    if model_id.startswith('translategemma'):
        # Only the unused chat endpoint needs this fallback parser. /completion
        # receives the exact, metadata-validated native translation prompt.
        cmd.extend(['--no-jinja', '--chat-template', 'chatml'])
    manifest = {'engine': 'llama.cpp', 'release': 'v0.6.0', 'build': 11429, 'commit': 'd81235049',
                'cuda': '13.4', 'model_path': str(model), 'asset': asset, 'command': cmd,
                'executable_sha256': hashlib.sha256(engine.read_bytes()).hexdigest(),
                'context_size': args.context_size, 'gpu_layers_requested': args.layers,
                'generation_settings_source': 'session-plan' if args.session_worker else 'sampling-profile',
                'generation_profile': None if args.session_worker else profile,
                'cpu_offload_allowed': args.allow_cpu_offload,
                'threads': args.threads, 'threads_batch': args.threads_batch,
                'kv_type_k': 'f16', 'kv_type_v': 'f16', 'prompt_cache_ram_mib': 8192,
                'model_sha256': model_sha256,
                'asset_manifests': [{'path': str(path), 'sha256': file_hash(path)} for path in manifest_paths],
                'cold_load_seconds': None, 'peak_device_memory_mib': None}
    manifest['runtime_source_sha256'] = file_hash(Path(__file__))
    (runtime / 'translation_demo_runtime.py').write_bytes(Path(__file__).read_bytes())
    profile_source = Path(__file__).parent / 'translation_demo/profiles.py'
    manifest['profile_source_sha256'] = file_hash(profile_source)
    (runtime / 'profiles.py').write_bytes(profile_source.read_bytes())
    monitor_source = Path(__file__).with_name('translation_monitor.py')
    manifest['monitor_source_sha256'] = file_hash(monitor_source)
    (runtime / monitor_source.name).write_bytes(monitor_source.read_bytes())
    manifest['runtime_dll_sha256'] = {p.name: file_hash(p) for p in engine.parent.glob('*.dll')}
    if args.engine_identity:
        manifest['custom_runtime_identity'] = json.loads(args.engine_identity.read_text(encoding='utf-8-sig'))
        manifest['custom_runtime_identity_sha256'] = hashlib.sha256(args.engine_identity.read_bytes()).hexdigest()
    samples = []
    def sample() -> None:
        result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True)
        samples.append({'elapsed_seconds': time.perf_counter()-start, 'reading': result.stdout.strip(), 'returncode': result.returncode})
    start = time.perf_counter()
    process = None
    child = None
    monitor = ResourceMonitor(runtime, interval_seconds=args.monitor_interval)
    try:
        monitor.start()
        monitor.mark_phase('idle_baseline')
        time.sleep(args.idle_baseline_seconds)
        monitor.mark_phase('load')
        load_start = time.perf_counter()
        with (runtime / 'stdout.log').open('wb') as stdout, (runtime / 'stderr.log').open('wb') as stderr:
            process = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
            manifest['server_pid'] = process.pid
            (runtime / 'server-pid.json').write_text(json.dumps({'pid': process.pid}), encoding='utf-8')
            monitor.set_target(process.pid)
            while time.perf_counter()-load_start < 180:
                if process.poll() is not None:
                    raise RuntimeError(f'Engine exited {process.returncode}; inspect logs')
                try:
                    with opener.open(url + '/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.5)
            else:
                raise TimeoutError('Model load exceeded 180 seconds')
            manifest['cold_load_seconds'] = time.perf_counter()-load_start
            with opener.open(url + '/props', timeout=10) as response:
                (runtime / 'props.json').write_bytes(response.read())
            manifest['residency'] = residency_evidence(loader_logs(runtime))
            validate_residency(manifest['residency'], args.layers, args.allow_cpu_offload)
            manifest_path = runtime / 'engine.json'
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            sample()
            run_cmd = [] if args.session_worker else [sys.executable, '-X', 'utf8', '-m', 'experiments.translation_demo.run',
                       '--candidate', args.candidate, '--inputs', str(args.inputs.resolve()),
                       '--output-dir', str(out / 'translation'), '--server-url', url,
                       '--engine-manifest', str(manifest_path), '--context-size', str(args.context_size),
                       '--sampling-profile', args.sampling_profile, '--n-predict', str(args.n_predict)]
            if args.session_worker:
                run_cmd = [sys.executable, '-X', 'utf8', '-m', args.session_worker,
                           '--candidate', args.candidate, '--session-plan', str(args.session_plan.resolve()),
                           '--output-dir', str(out / 'translation'), '--server-url', url,
                           '--engine-manifest', str(manifest_path), '--context-size', str(args.context_size),
                           '--stop-on-oom']
                manifest['session_worker'] = args.session_worker
                manifest['session_plan_sha256'] = file_hash(args.session_plan)
                (runtime / 'session-plan.json').write_bytes(args.session_plan.read_bytes())
            elif args.stop_on_oom:
                run_cmd.append('--stop-on-oom')
            for path in manifest_paths:
                run_cmd.extend(['--asset-manifest', str(path)])
            if args.mapping_only:
                run_cmd.extend(['--mapping-only', str(args.mapping_only.resolve()), '--mapper', args.mapper,
                                '--mapping-recipe', args.mapping_recipe])
            with (runtime / 'translation.stdout.log').open('wb') as log, (runtime / 'translation.stderr.log').open('wb') as errors:
                monitor.mark_phase('inference')
                child = subprocess.Popen(run_cmd, cwd=root, stdout=log, stderr=errors)
                event_offset = 0
                event_path = out / 'translation/workload-ledger.jsonl'
                while child.poll() is None:
                    if args.session_worker:
                        event_offset = forward_worker_events(event_path, event_offset, monitor)
                    sample()
                    time.sleep(1)
                manifest['translation_exit_code'] = child.returncode
                if args.session_worker:
                    forward_worker_events(event_path, event_offset, monitor)
            sample()
    except Exception as exc:
        manifest['runtime_error'] = repr(exc)
        manifest['runtime_error_kind'] = 'oom' if explicit_oom(str(exc) + '\n' + loader_logs(runtime)) else 'runtime_error'
        monitor.mark_phase('failure', {'reason': manifest['runtime_error_kind']})
        raise
    finally:
        monitor.mark_phase('unload')
        manifest['cleanup_started_at_utc'] = datetime.now(timezone.utc).isoformat()
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        manifest['server_exit_code'] = process.poll() if process is not None else None
        manifest['server_process_exited'] = process is None or process.poll() is not None
        manifest['worker_process_exited'] = child is None or child.poll() is not None
        manifest['cleanup_finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        monitor.set_target(None)
        monitor.mark_phase('released')
        time.sleep(2)
        manifest['resource_summary'] = monitor.stop()
        manifest['total_runtime_seconds'] = time.perf_counter()-start
        manifest['residency'] = residency_evidence(loader_logs(runtime))
        manifest['potential_driver_error_log_lines'] = [line for line in loader_logs(runtime).splitlines()
            if re.search(r'device lost|device reset|driver reset|CUDA_ERROR_CONTEXT_IS_DESTROYED|CUDA_ERROR_UNKNOWN|cudaErrorUnknown', line, re.IGNORECASE)]
        readings = [int(s['reading'].split(',')[0]) for s in samples if s['returncode'] == 0 and s['reading']]
        manifest['peak_device_memory_mib'] = max(readings, default=None)
        (runtime / 'runtime-final.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        (runtime / 'gpu-samples.json').write_text(json.dumps(samples, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False))
    return manifest.get('translation_exit_code', 1)


if __name__ == '__main__':
    sys.exit(main())
