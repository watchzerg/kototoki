"""Crisp official C ABI FA diagnostic with preference set inside the same DLL."""

from __future__ import annotations

import argparse
from array import array
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

from run import DEFAULT_ALIGNER, DEFAULT_EXE, PINS, ROOT, native_times, normalize, sha256
from alignment_labels import has_alignment_labels


def replay_segments(saved: dict, frame_count: int) -> list[dict]:
    """Use only pre-alignment native ASR ranges, never reference timestamps."""
    manifest = saved.get('manifest', {})
    if manifest.get('route') != 'crisp-qwen-f16-cli-asr-only' or manifest.get('status') != 'ok':
        raise ValueError('Replay requires a successful fresh CLI ASR-only result.')
    if manifest.get('pins') != PINS:
        raise ValueError('ASR model/source pins differ from the frozen FA round.')
    segments = saved.get('native', {}).get('transcription', [])
    planned = []
    for index, segment in enumerate(segments):
        start, end = native_times(segment, 0)
        if start is None or end is None or end <= start:
            raise ValueError(f'Invalid native ASR range at segment {index}.')
        # CLI coarse ranges are quantized to milliseconds in the JSON writer.
        # Exactly record this quantization rather than inventing missing precision.
        first, last = round(start * 16000), min(frame_count, round(end * 16000))
        if first < 0 or last <= first or first >= frame_count:
            raise ValueError(f'Native ASR range is outside input at segment {index}.')
        planned.append({'text': segment['text'], 'start_sample': first, 'end_sample': last,
                        'offset_cs': round(start * 100), 'native_asr_segment': segment})
    return planned


def worker(args: argparse.Namespace) -> None:
    with wave.open(str(args.audio), 'rb') as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Diagnostic requires PCM16 mono 16 kHz WAV.')
        pcm = array('h', stream.readframes(stream.getnframes()))
    if sys.byteorder != 'little':
        pcm.byteswap()
    text_path = args.text_file.resolve()
    loaded = text_path.read_text(encoding='utf-8-sig')
    saved = json.loads(loaded) if text_path.suffix.lower() == '.json' else None
    if args.asr_segments:
        if saved['manifest']['input']['sha256'] != sha256(args.audio):
            raise ValueError('ASR input SHA256 differs from replay audio.')
        if saved['manifest']['config']['source_offset_s'] != args.offset:
            raise ValueError('Source offset must equal the saved ASR source offset.')
        planned = replay_segments(saved, len(pcm))
    else:
        text = saved['text'] if saved else loaded
        if not text.strip():
            raise ValueError('Alignment diagnostic text is empty.')
        planned = [{'text': text, 'start_sample': 0, 'end_sample': len(pcm), 'offset_cs': 0}]
    with os.add_dll_directory(str(args.dll.parent.resolve())):
        library = ctypes.CDLL(str(args.dll.resolve()))
        setter = library.crispasr_set_gpu_backend
        setter.argtypes = [ctypes.c_char_p]
        setter.restype = None
        setter(args.gpu_backend.encode())
        align = library.crispasr_align_words_abi
        align.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_float),
                         ctypes.c_int32, ctypes.c_int64, ctypes.c_int32]
        align.restype = ctypes.c_void_p
        count = library.crispasr_align_result_n_words
        count.argtypes = [ctypes.c_void_p]
        count.restype = ctypes.c_int
        getters = {}
        for name, result_type in [('text', ctypes.c_char_p), ('t0', ctypes.c_int64), ('t1', ctypes.c_int64)]:
            function = getattr(library, 'crispasr_align_result_word_' + name)
            function.argtypes = [ctypes.c_void_p, ctypes.c_int]
            function.restype = result_type
            getters[name] = function
        release = library.crispasr_align_result_free
        release.argtypes = [ctypes.c_void_p]
        release.restype = None
        started = time.perf_counter()
        native = {'transcription': []}
        failures = []
        for index, segment in enumerate(planned):
            window = pcm[segment['start_sample']:segment['end_sample']]
            floats = (ctypes.c_float * len(window))(*(value / 32768.0 for value in window))
            result = align(str(args.aligner.resolve()).encode('utf-8'), segment['text'].encode('utf-8'),
                           floats, len(window), segment['offset_cs'], args.threads)
            words = []
            try:
                if result:
                    words = [{'text': getters['text'](result, item).decode('utf-8'),
                              't0': getters['t0'](result, item), 't1': getters['t1'](result, item)}
                             for item in range(count(result))]
            finally:
                if result:
                    release(result)
            if has_alignment_labels(segment['text']) and not words:
                failures.append({'stage': 'aligner', 'segment': index})
            native['transcription'].append({'text': segment['text'], 'words': words,
                'offsets': {'from': segment['start_sample'] / 16, 'to': segment['end_sample'] / 16}})
        total_words = sum(len(segment['words']) for segment in native['transcription'])
        output = {**normalize(native, args.offset), 'native': native,
                      'manifest': {'route': 'crisp-cli-asr-explicit-gpu-fa-replay' if args.asr_segments else 'crisp-cabi-explicit-gpu-fa-only', 'pins': PINS,
                                   'dll_sha256': sha256(args.dll), 'aligner_sha256': sha256(args.aligner),
                                   'input_sha256': sha256(args.audio), 'asr_text_sha256': sha256(args.text_file),
                                   'source_offset_s': args.offset, 'threads': args.threads,
                                   'gpu_backend': args.gpu_backend, 'wall_s': time.perf_counter() - started,
                                   'fa_text_segmentation': 'cjk_unicode_character_split_punctuation_filtered',
                                   'fa_timestamp_correction': 'official_fix_timestamps_port',
                                   'asr_executed': False, 'text_source': 'saved_asr_or_explicit_diagnostic_text',
                                   'words': total_words, 'cpu_fallback_allowed': False, 'failures': failures,
                                   'asr_inference_reused': bool(args.asr_segments), 'fa_inference_reused': False,
                                   'cached_inference': False, 'alignment_windows': planned,
                                   'asr_manifest': saved['manifest'] if args.asr_segments else None,
                                   'timing_scope': 'FA replay only; not new full-pipeline performance'}}
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--text-file', type=Path, required=True)
    parser.add_argument('--asr-segments', action='store_true', help='Replay CLI ASR-only native predicted ranges.')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--aligner', type=Path, default=DEFAULT_ALIGNER)
    parser.add_argument('--dll', type=Path, default=DEFAULT_EXE.with_name('crispasr.dll'))
    parser.add_argument('--gpu-backend', choices=['vulkan', 'cuda'], default='vulkan')
    parser.add_argument('--offset', type=float, default=0)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=3600)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / '.local').resolve()):
        parser.error('Private output must remain under project .local.')
    for path in (args.audio, args.text_file, args.aligner, args.dll):
        if not path.is_file():
            parser.error(f'Missing local asset: {path}')
    if args.output.exists() or (not args.worker and args.output.with_suffix('.stderr.log').exists()):
        parser.error('Output artifact already exists.')
    if args.offset < 0 or args.threads < 1:
        parser.error('Offset must be nonnegative and threads positive.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args)
        return
    if sha256(args.aligner) != PINS['aligner']['sha256']:
        parser.error('Aligner SHA256 differs from pinned artifact.')
    for key in ('CRISPASR_N_GPU_LAYERS', 'CRISPASR_KV_ON_CPU'):
        if os.environ.get(key) not in (None, '', '0'):
            parser.error(f'CPU/offload override is forbidden: {key}')
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--worker']
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, capture_output=True, timeout=args.timeout)
        code, stderr = completed.returncode, completed.stderr
    except subprocess.TimeoutExpired as error:
        code, stderr = 124, error.stderr or b''
    log = stderr.decode('utf-8', errors='replace')
    args.output.with_suffix('.stderr.log').write_text(log, encoding='utf-8')
    if not args.output.exists():
        failed = {'schema_version': 1, 'text': '', 'units': [], 'cues': [], 'native': {},
                  'manifest': {'route': 'crisp-cabi-explicit-gpu-fa-only', 'pins': PINS,
                               'status': 'failed', 'words': 0, 'failure_type': 'worker_failed_before_prediction',
                               'input_sha256': sha256(args.audio), 'dll_sha256': sha256(args.dll),
                               'asr_text_sha256': sha256(args.text_file), 'command': command,
                               'wall_s': time.perf_counter() - started,
                               'failures': [{'stage': 'worker', 'process_exit_code': code}]}}
        args.output.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.output.exists():
        result = json.loads(args.output.read_text(encoding='utf-8'))
        markers = [line for line in log.splitlines() if 'using preferred GPU backend:' in line]
        gpu_verified = any(('backend: ' + args.gpu_backend).lower() in line.lower() for line in markers)
        fallback = [line for line in log.splitlines() if any(phrase in line for phrase in
                    ('falling back to', 'layer offload:', 'keeping it on the CPU'))]
        result['manifest'].update(actual_gpu_markers=markers, fallback_warnings=fallback,
                                  actual_fa_gpu_verified=gpu_verified and not fallback,
                                  process_exit_code=code,
                                  alignment_warnings=[line for line in log.splitlines() if 'crispasr[aligner]:' in line])
        result['manifest']['status'] = 'ok' if code == 0 and gpu_verified and not fallback and not result['manifest']['failures'] else 'failed'
        if args.asr_segments and result['manifest'].get('asr_manifest'):
            asr_device = result['manifest']['asr_manifest']['device_evidence']
            result['manifest']['device_evidence'] = {
                'asr': asr_device.get('asr'),
                'aligner': markers[0] if markers else None,
                'gpu_only_contexts_verified': asr_device['gpu_only_contexts_verified'] and gpu_verified and not fallback,
                'asr_evidence_source': 'saved_fresh_cli_asr_run',
                'aligner_evidence_source': 'this_same_dll_explicit_gpu_fa_replay',
                'scope': 'separate_stage_runs_not_single_process_native_baseline'}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'words': result['manifest']['words'], 'actual_fa_gpu_verified': gpu_verified and not fallback,
                          'output': str(args.output), 'wall_s': result['manifest']['wall_s']}))
        if result['manifest']['status'] != 'ok':
            raise SystemExit(2)
    if code:
        raise SystemExit(code)


if __name__ == '__main__':
    main()
