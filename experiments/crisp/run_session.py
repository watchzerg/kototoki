"""Controlled continuous-window Crisp C ABI ASR + FA in one explicit GPU DLL."""

from __future__ import annotations

import argparse
from array import array
import ctypes as C
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import wave

from run import DEFAULT_ALIGNER, DEFAULT_EXE, DEFAULT_MODEL, PINS, ROOT, device_evidence, normalize, sha256


def bind(library: C.CDLL, name: str, arguments: list, result: object):
    function = getattr(library, name)
    function.argtypes, function.restype = arguments, result
    return function


def configure_decoding(setter_temp, setter_tokens, setter_beam, session, max_new_tokens: int) -> dict[str, int]:
    results = {'temperature': setter_temp(session, 0, 42),
               'max_new_tokens': setter_tokens(session, max_new_tokens), 'beam_size': setter_beam(session, 1)}
    # v0.8.41's temperature setter writes s->temperature and s->seed FIRST.
    # Its -2 return means no backend-specific setter was touched; the Qwen
    # decoder directly reads those shared fields at lines 6859..6860.
    # Accept only this source-verified Qwen sticky-field case, recording -2.
    for name, code in results.items():
        if code not in ((0, -2) if name == 'temperature' else (0,)):
            raise RuntimeError(f'C ABI decoding setter {name} failed: {code}')
    return results


def decode_native_segments(parts: list[bytes]) -> tuple[str | None, dict]:
    """Join API byte segments before strict decoding; preserve malformed output.

    A UTF-8 codepoint may span two API segments. Never decode with replacement,
    because invented characters must not enter quality measurements or alignment.
    """
    raw = b''.join(parts)
    try:
        return raw.decode('utf-8'), {}
    except UnicodeDecodeError as error:
        return None, {'failure_type': 'native_asr_invalid_utf8',
                      'raw_segment_bytes_hex': [part.hex() for part in parts],
                      'utf8_error': {'start': error.start, 'end': error.end, 'reason': error.reason},
                      'quality_valid': False, 'replacement_used': False}


def worker(args: argparse.Namespace) -> None:
    with wave.open(str(args.audio), 'rb') as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Prepare PCM16 mono 16 kHz WAV before inference.')
        samples = array('h', stream.readframes(stream.getnframes()))
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        raise ValueError('Empty audio.')
    os.environ['CRISPASR_QWEN3_ASR_BENCH'] = '1'
    with os.add_dll_directory(str(args.dll.parent.resolve())):
        library = C.CDLL(str(args.dll.resolve()))
        bind(library, 'crispasr_set_gpu_backend', [C.c_char_p], None)(args.gpu_backend.encode())
        open_session = bind(library, 'crispasr_session_open_explicit', [C.c_char_p, C.c_char_p, C.c_int], C.c_void_p)
        close = bind(library, 'crispasr_session_close', [C.c_void_p], None)
        transcribe = bind(library, 'crispasr_session_transcribe_lang',
                          [C.c_void_p, C.POINTER(C.c_float), C.c_int, C.c_char_p], C.c_void_p)
        free_result = bind(library, 'crispasr_session_result_free', [C.c_void_p], None)
        count_segments = bind(library, 'crispasr_session_result_n_segments', [C.c_void_p], C.c_int)
        segment_text = bind(library, 'crispasr_session_result_segment_text', [C.c_void_p, C.c_int], C.c_char_p)
        align = bind(library, 'crispasr_align_words_abi',
                     [C.c_char_p, C.c_char_p, C.POINTER(C.c_float), C.c_int32, C.c_int64, C.c_int32], C.c_void_p)
        count_words = bind(library, 'crispasr_align_result_n_words', [C.c_void_p], C.c_int)
        word_getters = {name: bind(library, 'crispasr_align_result_word_' + name,
                                 [C.c_void_p, C.c_int], result_type)
                        for name, result_type in [('text', C.c_char_p), ('t0', C.c_int64), ('t1', C.c_int64)]}
        free_aligned = bind(library, 'crispasr_align_result_free', [C.c_void_p], None)
        started = time.perf_counter()
        session = open_session(str(args.model.resolve()).encode(), b'qwen3', args.threads)
        load_seconds = time.perf_counter() - started
        if not session:
            raise RuntimeError('Crisp C ABI GPU ASR session failed to open.')
        setter_temp = bind(library, 'crispasr_session_set_temperature', [C.c_void_p, C.c_float, C.c_uint64], C.c_int)
        setter_tokens = bind(library, 'crispasr_session_set_max_new_tokens', [C.c_void_p, C.c_int], C.c_int)
        setter_beam = bind(library, 'crispasr_session_set_beam_size', [C.c_void_p, C.c_int], C.c_int)
        try:
            setter_results = configure_decoding(setter_temp, setter_tokens, setter_beam, session, args.max_new_tokens)
        except BaseException:
            close(session)
            raise
        native_segments, windows, failures = [], [], []
        window_frames = int(args.chunk_seconds * 16000)
        try:
            for start_sample in range(0, len(samples), window_frames):
                end_sample = min(len(samples), start_sample + window_frames)
                window_pcm = samples[start_sample:end_sample]
                pcm = (C.c_float * len(window_pcm))(*(sample / 32768.0 for sample in window_pcm))
                window_start = start_sample / 16000
                metadata = {'start_sample': start_sample, 'end_sample': end_sample,
                            'source_start_s': args.offset + window_start,
                            'source_end_s': args.offset + end_sample / 16000}
                step_started = time.perf_counter()
                result = transcribe(session, pcm, len(pcm), args.language.encode())
                metadata['asr_s'] = time.perf_counter() - step_started
                if not result:
                    failures.append({'stage': 'asr', 'window': metadata})
                    windows.append(metadata)
                    continue
                try:
                    # ctypes c_char_p copies bytes while the owning result is
                    # alive. Preserve exact API bytes before freeing the result.
                    raw_texts = [segment_text(result, index) or b''
                                 for index in range(count_segments(result))]
                finally:
                    free_result(result)
                text, decoding_error = decode_native_segments(raw_texts)
                if text is None:
                    metadata.update(decoding_error)
                    failures.append({'stage': 'asr_utf8', 'window': metadata})
                    text = ''
                segment = {'text': text, 'offsets': {'from': window_start * 1000, 'to': end_sample / 16},
                           'words': []}
                if text.strip():
                    step_started = time.perf_counter()
                    aligned = align(str(args.aligner.resolve()).encode(), text.encode('utf-8'), pcm,
                                    len(pcm), int(round(window_start * 100)), args.threads)
                    metadata['fa_s'] = time.perf_counter() - step_started
                    if aligned:
                        try:
                            segment['words'] = [
                                {'text': (word_getters['text'](aligned, index) or b'').decode('utf-8'),
                                 't0': word_getters['t0'](aligned, index), 't1': word_getters['t1'](aligned, index)}
                                for index in range(count_words(aligned))]
                        finally:
                            free_aligned(aligned)
                    if not segment['words']:
                        failures.append({'stage': 'aligner', 'window': metadata})
                metadata.update(text_chars=len(text), words=len(segment['words']))
                windows.append(metadata)
                native_segments.append(segment)
                current = {'transcription': native_segments}
                args.output.write_text(json.dumps({**normalize(current, args.offset), 'native': current,
                    'manifest': {'status': 'running', 'windows': windows, 'failures': failures}},
                    ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            close(session)
        native = {'transcription': native_segments}
        manifest = {'route': 'crisp-cabi-explicit-gpu-continuous-windows', 'pins': PINS,
                    'status': 'completed' if not failures else 'failed', 'windows': windows, 'failures': failures,
                    'input_sha256': sha256(args.audio), 'dll_sha256': sha256(args.dll),
                    'config': {'gpu_backend': args.gpu_backend, 'device': 0, 'language': args.language,
                               'chunk_seconds': args.chunk_seconds, 'overlap_seconds': 0,
                               'max_new_tokens': args.max_new_tokens, 'temperature': 0, 'beam_size': 1,
                               'seed': 42, 'threads': args.threads, 'vad': False, 'energy_gate': False,
                               'asr_precision': 'f16', 'aligner_precision': 'f16',
                               'fa_text_segmentation': 'cjk_unicode_character_split_punctuation_filtered',
                               'fa_timestamp_correction': 'official_fix_timestamps_port',
                               'native_cli_equivalent': False, 'source_offset_s': args.offset},
                    'model_load_s': load_seconds, 'wall_s': time.perf_counter() - started,
                    'decoding_setter_return_codes': setter_results,
                    'temperature_minus2_interpretation': 'shared_fields_written_and_read_directly_by_qwen_decoder',
                    'asr_s': sum(window.get('asr_s', 0) for window in windows),
                    'fa_s': sum(window.get('fa_s', 0) for window in windows), 'cached_inference': False}
        args.output.write_text(json.dumps({**normalize(native, args.offset), 'native': native, 'manifest': manifest},
                                         ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--aligner', type=Path, default=DEFAULT_ALIGNER)
    parser.add_argument('--dll', type=Path, default=DEFAULT_EXE.with_name('crispasr.dll'))
    parser.add_argument('--gpu-backend', choices=['vulkan', 'cuda'], default='vulkan')
    parser.add_argument('--offset', type=float, default=0)
    parser.add_argument('--language', default='ja')
    parser.add_argument('--chunk-seconds', type=float, default=30)
    parser.add_argument('--max-new-tokens', type=int, default=512)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=7200)
    parser.add_argument('--skip-model-hash', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / '.local').resolve()):
        parser.error('Private output must remain under project .local.')
    if args.output.exists() or (not args.worker and args.output.with_suffix('.stderr.log').exists()):
        parser.error('An output artifact already exists.')
    if args.offset < 0 or not 1 <= args.chunk_seconds <= 120 or args.threads < 1 or args.max_new_tokens < 1:
        parser.error('Invalid offset, 1..120 s window, threads or token limit.')
    for path in (args.audio, args.model, args.aligner, args.dll):
        if not path.is_file():
            parser.error(f'Missing local asset: {path}')
    for key, value in os.environ.items():
        if key.startswith('CRISPASR_') and value not in ('0', '') and (
            key in ('CRISPASR_N_GPU_LAYERS', 'CRISPASR_KV_ON_CPU') or key.endswith(('_CPU', '_CPU_ONLY', '_FORCE_CPU'))):
            parser.error(f'CPU/offload override is forbidden: {key}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        worker(args)
        return
    if not args.skip_model_hash:
        for name, path in [('asr', args.model), ('aligner', args.aligner)]:
            if sha256(path) != PINS[name]['sha256']:
                parser.error(f'{name} SHA256 differs from pinned artifact.')
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
        # Every executed attempt retains a machine-readable empty prediction,
        # so model-load/setup failures cannot disappear from evaluation counts.
        failed = {'schema_version': 1, 'text': '', 'units': [], 'cues': [], 'native': {},
                  'manifest': {'route': 'crisp-cabi-explicit-gpu-continuous-windows', 'pins': PINS,
                               'status': 'failed', 'failure_type': 'worker_failed_before_prediction',
                               'process_exit_code': code, 'command': command,
                               'input_sha256': sha256(args.audio), 'dll_sha256': sha256(args.dll),
                               'wall_s': time.perf_counter() - started, 'windows': [],
                               'failures': [{'stage': 'setup_or_worker', 'process_exit_code': code}],
                               'requested_config': {'gpu_backend': args.gpu_backend, 'offset': args.offset,
                                                    'chunk_seconds': args.chunk_seconds,
                                                    'max_new_tokens': args.max_new_tokens,
                                                    'language': args.language, 'threads': args.threads},
                               'effective_config': None}}
        args.output.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.output.exists():
        result = json.loads(args.output.read_text(encoding='utf-8'))
        evidence = device_evidence(log, args.gpu_backend, bool(result['text']))
        result['manifest'].update(device_evidence=evidence, process_exit_code=code,
                                  alignment_warnings=re.findall(r'[^\r\n]*crispasr\[aligner\]:[^\r\n]*', log),
                                  model_hashes_rechecked=not args.skip_model_hash)
        success = code == 0 and evidence['gpu_only_contexts_verified'] and not result['manifest']['failures']
        result['manifest']['status'] = 'ok' if success else 'failed'
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': result['manifest']['status'], 'text_chars': len(result['text']),
                          'windows': len(result['manifest']['windows']), 'device_evidence': evidence}))
        if not success:
            raise SystemExit(code or 2)
    elif code == 0:
        raise SystemExit(2)
    if code:
        raise SystemExit(code)


if __name__ == '__main__':
    main()
