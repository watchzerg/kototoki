"""Create one full-film source-window plan without resetting at scoring bins."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from experiments.w0_demo.run import read_audio, sha256, write_json
from experiments.x0_demo.chunks import RATE, cut_merge_chunks, validate_chunks

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding='utf-8'))
    lock = json.loads((ROOT / '.local/gpu.lock').read_text(encoding='utf-8'))
    if str(lock['pid']) != os.environ.get('KOTOTOKI_FULLFILM_PARENT_PID'):
        raise RuntimeError('Parent must own the shared GPU lock')
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / '.local/fullfilm-comparison'):
        raise ValueError('Private full-film output required')
    out.mkdir(parents=True, exist_ok=False)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      PYANNOTE_METRICS_ENABLED='0', HF_HOME=str(out/'cache/hf'),
                      TORCH_HOME=str(out/'cache/torch'), XDG_CACHE_HOME=str(out/'cache'),
                      MPLCONFIGDIR=str(out/'cache/matplotlib'), TOKENIZERS_PARALLELISM='false')
    started = time.perf_counter()
    detector = None
    try:
        for name, expected in job['source_sha256'].items():
            if sha256(ROOT/name) != expected:
                raise RuntimeError(f'Source changed before segmentation: {name}')
        clip = job['clip']
        audio, identity = read_audio(Path(clip['audio']))
        if identity['file_sha256'] != clip['audio_sha256'] or identity['pcm_sha256'] != clip['pcm_sha256']:
            raise ValueError('Frozen full-film input changed')
        read_s = time.perf_counter()-started
        mark = time.perf_counter()
        if job['segmentation'] == 'pyannote-current':
            from experiments.w0_demo.vad_candidates import create_vad
            candidate = job['candidate']
            detector = create_vad('pyannote-current', Path(candidate['model']),
                                  device=candidate['device'], model_revision=candidate['revision'])
            import torch
            torch.cuda.synchronize()
            load_s = time.perf_counter()-mark
            mark = time.perf_counter()
            chunks = detector.segment(audio)
            for chunk in chunks:
                chunk['start'] = chunk['start_sample'] / RATE
                chunk['end'] = chunk['end_sample'] / RATE
            torch.cuda.synchronize()
            inference_s = time.perf_counter()-mark
            metadata = dict(detector.metadata)
            detector.close()
            detector = None
        elif job['segmentation'] == 'cut-merge':
            chunks = cut_merge_chunks(audio)
            load_s, inference_s = 0.0, time.perf_counter()-mark
            metadata = {'kind': 'cut-merge', 'fresh_inference': True, 'device': 'cpu',
                        'policy': 'canonical x0_demo.chunks.cut_merge_chunks',
                        'filters_audio': False, 'candidate_region_s': 5, 'rms_grid_s': .1,
                        'max_chunk_s': 30, 'retain_all': True}
        else:
            raise ValueError('Unknown segmentation')
        validate_chunks(chunks, len(audio), retain_all=job['segmentation']=='cut-merge')
        for name, expected in job['source_sha256'].items():
            if sha256(ROOT/name) != expected:
                raise RuntimeError(f'Source changed during segmentation: {name}')
        retained = sum(c['end_sample']-c['start_sample'] for c in chunks)
        plan = {'schema_version': 1, 'status': 'ok', 'clip_id': clip['id'],
                'segmentation': job['segmentation'], 'recipe': 'fullfilm-source-windows-v1',
                'input': identity, 'offset_s': clip.get('offset', 0), 'chunks': chunks,
                'retained_samples': retained, 'removed_samples': len(audio)-retained,
                'effective_parameters': {'segmentation': metadata}, 'metadata': metadata,
                'source_sha256': job['source_sha256'], 'python': sys.version, 'executable': sys.executable,
                'stages': {'input_read_s': read_s, 'load_s': load_s, 'inference_s': inference_s,
                           'wall_s': time.perf_counter()-started}}
        write_json(out/'plan.json', plan)
        print(json.dumps({'clip': clip['id'], 'segmentation': job['segmentation'],
                          'chunks': len(chunks), 'retained_samples': retained}), flush=True)
    except Exception as error:
        write_json(out/'failure.json', {'type': type(error).__name__, 'message': str(error)})
        raise
    finally:
        if detector is not None:
            detector.close()


if __name__ == '__main__':
    main()
