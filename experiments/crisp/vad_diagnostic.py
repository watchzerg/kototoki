"""Inspect CPU native Silero probability distributions and optional carry recipe."""

from __future__ import annotations

import argparse
from array import array
import ctypes as C
import json
import os
from pathlib import Path
import time
import wave

from run import DEFAULT_EXE, PINS, ROOT, sha256
from run_session import bind


class ContextParams(C.Structure):
    _fields_ = [('n_threads', C.c_int), ('use_gpu', C.c_bool), ('gpu_device', C.c_int)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vad-model', type=Path, default=ROOT / '.local/models/crisp-silero-v6.2.0/ggml-silero-v6.2.0.bin')
    parser.add_argument('--dll', type=Path, default=DEFAULT_EXE.with_name('crispasr.dll'))
    parser.add_argument('--source-context', action='store_true', help='Opt-in upstream internal 64-sample carry recipe; separate diagnostic arm.')
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / '.local').resolve()) or args.output.exists():
        parser.error('Use a new private .local output.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if sha256(args.vad_model) != PINS['vad']['sha256']:
        parser.error('VAD SHA256 differs from pinned artifact.')
    with wave.open(str(args.audio), 'rb') as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            parser.error('Expected PCM16 mono 16 kHz WAV.')
        samples = array('h', stream.readframes(stream.getnframes()))
    if not samples:
        parser.error('Empty audio.')
    pcm = (C.c_float * len(samples))(*(sample / 32768.0 for sample in samples))
    with os.add_dll_directory(str(args.dll.parent.resolve())):
        library = C.CDLL(str(args.dll.resolve()))
        defaults = bind(library, 'whisper_vad_default_context_params', [], ContextParams)()
        defaults.use_gpu = False
        ctx = bind(library, 'whisper_vad_init_from_file_with_params', [C.c_char_p, ContextParams], C.c_void_p)(
            str(args.vad_model.resolve()).encode(), defaults)
        if not ctx:
            raise RuntimeError('Native Silero context failed to load.')
        try:
            if args.source_context:
                if not bind(library, 'crispasr_silero_enable_context', [C.c_void_p], C.c_bool)(ctx):
                    raise RuntimeError('Source-context recipe is incompatible with this model.')
            started = time.perf_counter()
            success = bind(library, 'whisper_vad_detect_speech', [C.c_void_p, C.POINTER(C.c_float), C.c_int], C.c_bool)(ctx, pcm, len(pcm))
            elapsed = time.perf_counter() - started
            count = bind(library, 'whisper_vad_n_probs', [C.c_void_p], C.c_int)(ctx)
            raw = bind(library, 'whisper_vad_probs', [C.c_void_p], C.POINTER(C.c_float))(ctx)
            probabilities = [raw[index] for index in range(count)]
            sorted_probs = sorted(probabilities)
            quantiles = {str(q): sorted_probs[min(len(sorted_probs) - 1, int(q * (len(sorted_probs) - 1)))]
                         for q in (0, 0.5, 0.9, 0.95, 0.99, 1)} if sorted_probs else {}
            output = {'status': 'ok' if success else 'failed', 'device': 'cpu_native_preprocessing',
                      'source_context_64_samples': args.source_context, 'audio_sha256': sha256(args.audio),
                      'model_sha256': sha256(args.vad_model), 'dll_sha256': sha256(args.dll),
                      'duration_s': len(samples) / 16000, 'wall_s': elapsed, 'probability_frames': count,
                      'threshold_coverage': {str(q): sum(p >= q for p in probabilities) / count if count else 0
                                             for q in (0.1, 0.3, 0.5)},
                      'probability_quantiles': quantiles, 'probabilities': probabilities}
            args.output.write_text(json.dumps(output, indent=2), encoding='utf-8')
            print(json.dumps({key: value for key, value in output.items() if key != 'probabilities'}))
        finally:
            bind(library, 'whisper_vad_free', [C.c_void_p], None)(ctx)


if __name__ == '__main__':
    main()
