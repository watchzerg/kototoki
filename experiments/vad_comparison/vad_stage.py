"""Run one provisioned offline detector and persist source-window evidence."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import math
import os
from pathlib import Path
import shutil
import sys
import time

from experiments.w0_demo.run import gpu_lock, read_audio, sha256, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--offset', type=float, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--vad-id', required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--device', default='cpu')
    args = parser.parse_args()
    if not math.isfinite(args.offset) or args.offset < 0:
        parser.error('offset must be finite and nonnegative')
    root = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    if not out.is_relative_to(root / '.local/vad-comparison'):
        raise ValueError('VAD outputs must remain under .local/vad-comparison')
    out.mkdir(parents=True, exist_ok=False)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', PYANNOTE_METRICS_ENABLED='0',
                      HF_HOME=str(out / 'cache/hf'), TORCH_HOME=str(out / 'cache/torch'),
                      XDG_CACHE_HOME=str(out / 'cache'), TOKENIZERS_PARALLELISM='false')
    source_files = [Path(__file__), root / 'kototoki_eval/schema.py',
                    *(root / 'experiments/w0_demo' / name for name in
                      ('vad_candidates.py', 'run.py', 'vad.py', 'pipeline.py', 'alignment.py', '__init__.py'))]
    sources = {}
    for path in source_files:
        target = out / 'source' / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        sources[path.relative_to(root).as_posix()] = sha256(path)
    started = time.perf_counter()
    vad = None
    try:
        audio, identity = read_audio(args.audio)
        read_s = time.perf_counter() - started
        from experiments.w0_demo.vad_candidates import create_vad
        with gpu_lock(root / '.local/gpu.lock', args.vad_id) if args.device.startswith('cuda') else nullcontext():
            mark = time.perf_counter()
            vad = create_vad(args.vad_id, args.model, device=args.device, model_revision=args.revision)
            load_s = time.perf_counter() - mark
            mark = time.perf_counter()
            chunks = vad.segment(audio)
            inference_s = time.perf_counter() - mark
            metadata = dict(vad.metadata)
            vad.close()
            vad = None
        if any(sha256(root / name) != digest for name, digest in sources.items()):
            raise RuntimeError('VAD source changed during inference')
        write_json(out / 'manifest.json', {
            'schema_version': 1, 'status': 'ok', 'vad_id': args.vad_id,
            'recipe': f'{args.vad_id}-source-span-merge-v1',
            'input': identity, 'offset_s': args.offset, 'chunks': chunks,
            'metadata': metadata, 'source_sha256': sources,
            'python': sys.version, 'executable': sys.executable,
            'stages': {'input_read_s': read_s, 'vad_load_s': load_s, 'vad_inference_s': inference_s,
                       'worker_wall_s': time.perf_counter() - started},
        })
        print(f'{args.vad_id}: {len(chunks)} source windows', flush=True)
    except Exception as error:
        write_json(out / 'failure.json', {'status': 'failed', 'type': type(error).__name__,
                                         'message': str(error)})
        raise
    finally:
        if vad is not None:
            vad.close()


if __name__ == '__main__':
    main()
