"""Run a pinned local Crisp Qwen ASR + FA experiment without model acquisition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any
import wave

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / '.local/tools/crisp/v0.8.41-vulkan/crispasr-windows-x86_64-vulkan/crispasr.exe'
DEFAULT_MODEL = ROOT / '.local/models/crisp-qwen3-asr-1.7b-f16/qwen3-asr-1.7b-f16.gguf'
DEFAULT_ALIGNER = ROOT / '.local/models/crisp-qwen3-forced-aligner-0.6b-f16/qwen3-forced-aligner-0.6b-f16.gguf'
PINS = {
    'release': 'v0.8.41', 'source_revision': '340d7085eaa53c40a46dcb73a6d3d0448a480006',
    'asr': {'repo': 'cstr/qwen3-asr-1.7b-GGUF', 'revision': '674df5d44b50a63e7102a18895ed20e3f91de301',
            'sha256': 'ac6c58f9cb0f2bb22290319cde01b0e25a2c1f1ee69aa2f1a9265f29a8bfc9d7'},
    'aligner': {'repo': 'cstr/qwen3-forced-aligner-0.6b-GGUF', 'revision': '1ec5110602ccab18c878ddebedab0891e290a95c',
                'sha256': '35bd243939212f675652d36de061bedf09daee9a7af2a866f47e57be148a8578'},
    'vad': {'repo': 'ggml-org/whisper-vad', 'revision': '9ffd54a1e1ee413ddf265af9913beaf518d1639b',
            'sha256': '2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987'},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def native_times(item: dict[str, Any], offset: float) -> tuple[float | None, float | None]:
    """Prefer explicit milliseconds; retain missing centisecond sentinels."""
    if 'offsets' in item:
        start, end = item['offsets'].get('from'), item['offsets'].get('to')
        scale = 1000
    else:
        start, end = item.get('t0'), item.get('t1')
        scale = 100
    if start is None or end is None or start < 0 or end < start:
        return None, None
    return start / scale + offset, end / scale + offset


def normalize(native: dict[str, Any], offset: float = 0) -> dict[str, Any]:
    """Preserve original segment text and map exact word spans monotonically.

    Unmapped punctuation/text remains explicit text-only coverage. Do not invent
    character timestamps or replace original text with the aligner's tokenization.
    """
    text_parts: list[str] = []
    units: list[dict[str, Any]] = []
    cues: list[dict[str, Any]] = []
    unmatched_words: list[dict[str, Any]] = []
    base = 0
    for segment in native.get('transcription', []):
        text = segment.get('text', '')
        text_parts.append(text)
        start, end = native_times(segment, offset)
        cues.append({'text': text, 'start': start, 'end': end})
        words = segment.get('words', [])
        if not words:
            if text:
                units.append({'char_start': base, 'char_end': base + len(text), 'start': start,
                              'end': end, 'granularity': 'segment', 'time_source': 'fallback',
                              'status': 'text_only'})
            base += len(text)
            continue
        cursor = 0
        for word in words:
            word_text = word.get('text', '')
            if not word_text:
                continue
            found = text.find(word_text, cursor)
            if found < 0:
                unmatched_words.append({'segment_char_start': base, 'word': word})
                continue
            if found > cursor:
                units.append({'char_start': base + cursor, 'char_end': base + found, 'start': None,
                              'end': None, 'granularity': 'character', 'time_source': 'native',
                              'status': 'text_only'})
            word_start, word_end = native_times(word, offset)
            valid = word_start is not None and word_end is not None and word_end > word_start
            units.append({'char_start': base + found, 'char_end': base + found + len(word_text),
                          'start': word_start, 'end': word_end, 'granularity': 'word',
                          'time_source': 'api', 'status': 'ok' if valid else 'failed'})
            cursor = found + len(word_text)
        if cursor < len(text):
            units.append({'char_start': base + cursor, 'char_end': base + len(text), 'start': None,
                          'end': None, 'granularity': 'character', 'time_source': 'native',
                          'status': 'text_only'})
        base += len(text)
    return {'schema_version': 1, 'text': ''.join(text_parts), 'units': units, 'cues': cues,
            'unmapped_native_words': unmatched_words}


def device_evidence(log: str, backend: str, has_text: bool) -> dict[str, Any]:
    markers = re.findall(r'using preferred GPU backend: ([^\r\n]+)', log)
    selected = [marker for marker in markers if marker.lower().startswith(backend)]
    failures = re.findall(r'[^\r\n]*(?:falling back to auto|layer offload:|keeping it on the CPU|using the CPU backend)[^\r\n]*', log)
    # The CLI and DLL may have separate inline GPU-preference state. FA in the
    # DLL can select an unlogged default GPU, so do not infer its actual device
    # from the CLI ASR marker or successful aligner_forward alone.
    verified = len(selected) >= (2 if has_text else 1) and not failures
    return {'backend': backend, 'asr': selected[0] if selected else None,
            'aligner': selected[1] if len(selected) >= 2 else None,
            'aligner_executed': has_text and len(selected) >= 2,
            'gpu_only_contexts_verified': verified, 'fallback_warnings': failures,
            'all_gpu_init_markers': markers,
            'limit': 'Context placement plus completed graph execution; ggml scheduler includes CPU helper ops.'}


def native_srt_cues(path: Path, offset: float) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    def seconds(stamp: str) -> float:
        hours, minutes, rest = stamp.split(':')
        return int(hours) * 3600 + int(minutes) * 60 + float(rest.replace(',', '.')) + offset
    cues = []
    for block in re.split(r'\r?\n\s*\r?\n', path.read_text(encoding='utf-8-sig').strip()):
        lines = block.splitlines()
        timing = next((index for index, line in enumerate(lines) if ' --> ' in line), None)
        if timing is not None:
            start, end = lines[timing].split(' --> ')
            cues.append({'text': '\n'.join(lines[timing + 1:]), 'start': seconds(start), 'end': seconds(end)})
    return cues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path, default=DEFAULT_EXE)
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    parser.add_argument('--aligner', type=Path, default=DEFAULT_ALIGNER)
    parser.add_argument('--asr-only', action='store_true', help='Controlled stage output: no FA or display splitting.')
    parser.add_argument('--gpu-backend', choices=['vulkan', 'cuda'], default='vulkan')
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--offset', type=float, default=0, help='Source time of extracted WAV, seconds.')
    parser.add_argument('--language', default='ja')
    parser.add_argument('--chunk-seconds', type=int, help='Unset retains native 30 s default.')
    parser.add_argument('--chunk-overlap', type=float, help='Unset retains native 3 s default.')
    parser.add_argument('--max-new-tokens', type=int, default=512)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--vad-model', type=Path, help='Local Silero model enables recommended VAD flow.')
    parser.add_argument('--disable-energy-gate', action='store_true')
    parser.add_argument('--timeout', type=float, default=3600)
    parser.add_argument('--skip-model-hash', action='store_true', help='Hashes recorded by separate provisioning; report unchecked.')
    args = parser.parse_args()
    for path in (args.audio, args.exe, args.model, args.aligner):
        if not path.is_file():
            parser.error(f'Required local asset is missing: {path}')
    if args.vad_model and not args.vad_model.is_file():
        parser.error(f'VAD model is missing: {args.vad_model}')
    if args.offset < 0 or args.max_new_tokens < 1 or args.threads < 1:
        parser.error('Offset must be nonnegative; tokens and threads must be positive.')
    with wave.open(str(args.audio), 'rb') as audio:
        audio_info = {'sample_rate': audio.getframerate(), 'channels': audio.getnchannels(),
                      'sample_width': audio.getsampwidth(), 'frames': audio.getnframes(),
                      'duration_s': audio.getnframes() / audio.getframerate()}
    if (audio_info['sample_rate'], audio_info['channels'], audio_info['sample_width']) != (16000, 1, 2):
        parser.error('Prepare explicit PCM16 mono 16 kHz WAV before inference.')
    if audio_info['frames'] == 0:
        parser.error('Audio has no frames.')
    args.output = args.output.resolve()
    if not args.output.is_relative_to((ROOT / '.local').resolve()):
        parser.error('Private results must be written below the Git-ignored project .local directory.')
    if args.output == args.audio.resolve():
        parser.error('Output must not overwrite input audio.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    native_base = args.output.with_suffix('.native')
    artifact_paths = [args.output, args.output.with_suffix('.stderr.log'), args.output.with_suffix('.stdout.log'),
                      Path(str(native_base) + '.json'), Path(str(native_base) + '.srt')]
    if any(path.exists() for path in artifact_paths):
        parser.error('An output artifact already exists; choose a new output to prevent overwrite or stale/cache results.')
    environment = os.environ.copy()
    overrides = {key: value for key, value in environment.items() if key.startswith(('CRISPASR_', 'GGML_'))}
    unsafe = [key for key, value in overrides.items() if value not in ('0', '') and
              (key in ('CRISPASR_N_GPU_LAYERS', 'CRISPASR_KV_ON_CPU') or key.endswith(('_CPU', '_CPU_ONLY', '_FORCE_CPU')))]
    if unsafe:
        parser.error(f'GPU-only run refuses CPU/offload environment overrides: {unsafe}')
    environment['CRISPASR_CACHE_DIR'] = str(ROOT / '.local/cache/crisp')
    environment['CRISPASR_QWEN3_ASR_BENCH'] = '1'
    if args.disable_energy_gate:
        environment['CRISPASR_ENERGY_SILENCE_GATE'] = '0'
    command = [str(args.exe.resolve()), '--backend', 'qwen3', '-m', str(args.model.resolve()),
               '--strict-pipeline', '--gpu-backend', args.gpu_backend, '-dev', str(args.device),
               '-f', str(args.audio.resolve()), '-l', args.language, '-n', str(args.max_new_tokens),
               '-t', str(args.threads), '-tp', '0', '--seed', '42', '-ojf', '-of', str(native_base), '--verbose']
    if not args.asr_only:
        command += ['-am', str(args.aligner.resolve()), '--force-aligner', '--require-word-timestamps',
                    '-osrt', '--split-on-punct']
    if args.chunk_seconds is not None:
        command += ['--chunk-seconds', str(args.chunk_seconds)]
    if args.chunk_overlap is not None:
        command += ['--chunk-overlap', str(args.chunk_overlap)]
    if args.vad_model:
        command += ['--vad', '-vm', str(args.vad_model.resolve())]
    manifest: dict[str, Any] = {'route': 'crisp-qwen-f16-cli-asr-only' if args.asr_only else 'crisp-qwen-f16-fa-f16', 'pins': PINS, 'command': command,
        'input': {'path': str(args.audio.resolve()), 'sha256': sha256(args.audio), **audio_info},
        'config': {'source_offset_s': args.offset, 'gpu_backend': args.gpu_backend, 'device': args.device,
                   'language': args.language, 'temperature': 0, 'seed': 42,
                   'max_new_tokens': args.max_new_tokens, 'threads': args.threads,
                   'chunk_seconds': args.chunk_seconds or 30,
                   'chunk_overlap': args.chunk_overlap if args.chunk_overlap is not None else 3.0,
                   'vad': bool(args.vad_model), 'energy_gate': not args.disable_energy_gate,
                   'vad_device': 'cpu_native_preprocessing' if args.vad_model else None,
                   'native_writer_split_on_punct': not args.asr_only, 'model_precision': 'f16',
                   'aligner_executed': not args.asr_only,
                   'fa_text_segmentation': 'cjk_unicode_character_split_punctuation_filtered',
                   'fa_timestamp_correction': 'official_fix_timestamps_port',
                   'native_defaults_preserved_except_explicit_command': True},
        'environment_overrides': {key: value for key, value in environment.items() if key.startswith(('CRISPASR_', 'GGML_'))},
        'binary_sha256': sha256(args.exe),
        'model_hashes': {'asr': None, 'aligner': None},
        'vad_sha256': sha256(args.vad_model) if args.vad_model else None,
        'cached_inference': False}
    if args.vad_model and manifest['vad_sha256'] != PINS['vad']['sha256']:
        parser.error('VAD SHA256 differs from the pinned Silero artifact.')
    if not args.skip_model_hash:
        for name, path in [('asr', args.model), ('aligner', args.aligner)]:
            measured = sha256(path)
            manifest['model_hashes'][name] = measured
            if measured != PINS[name]['sha256']:
                parser.error(f'{name} hash differs from pinned f16 artifact: {measured}')
    started = time.perf_counter()
    try:
        completed = subprocess.run(command, env=environment, capture_output=True, timeout=args.timeout)
        log = completed.stderr.decode('utf-8', errors='replace')
        manifest['process_exit_code'] = completed.returncode
        manifest['wall_s'] = time.perf_counter() - started
        args.output.with_suffix('.stderr.log').write_text(log, encoding='utf-8')
        args.output.with_suffix('.stdout.log').write_bytes(completed.stdout)
        native_path = Path(str(native_base) + '.json')
        native = json.loads(native_path.read_text(encoding='utf-8-sig')) if native_path.exists() else {}
        evaluation = normalize(native, args.offset)
        evidence = device_evidence(log, args.gpu_backend, bool(evaluation['text']) and not args.asr_only)
        if args.asr_only:
            evidence['scope'] = 'asr_only_no_aligner_requested'
        manifest['device_evidence'] = evidence
        manifest['alignment_warnings'] = re.findall(r'[^\r\n]*crispasr\[aligner\]:[^\r\n]*', log)
        manifest['native_no_speech_detected'] = 'warning: no speech detected' in log
        stages: dict[str, dict[str, float | int]] = {}
        for stage, milliseconds in re.findall(r'qwen3_asr_bench:\s+(\S+)\s+(\d+(?:\.\d+)?) ms', log):
            aggregate = stages.setdefault(stage, {'calls': 0, 'total_s': 0.0})
            aggregate['calls'] += 1
            aggregate['total_s'] += float(milliseconds) / 1000
        manifest['native_stage_timings'] = stages
        manifest['status'] = 'ok' if completed.returncode == 0 and native_path.exists() and evidence['gpu_only_contexts_verified'] else 'failed'
        if completed.returncode == 0 and manifest['native_no_speech_detected'] and not native_path.exists():
            manifest['failure_type'] = 'native_vad_no_speech_no_json'
        elif completed.returncode == 0 and not evidence['gpu_only_contexts_verified']:
            manifest['failure_type'] = 'actual_fa_device_unverified'
        display_cues = native_srt_cues(Path(str(native_base) + '.srt'), args.offset)
        args.output.write_text(json.dumps({**evaluation, 'native': native, 'native_writer_cues': display_cues, 'manifest': manifest},
                                         ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'status': manifest['status'], 'wall_s': manifest['wall_s'],
                          'output': str(args.output), 'text_chars': len(evaluation['text']),
                          'units': len(evaluation['units']), 'device_evidence': evidence}, ensure_ascii=False))
        if manifest['status'] != 'ok':
            raise SystemExit(completed.returncode or 2)
    except subprocess.TimeoutExpired as exc:
        manifest.update(status='timeout', wall_s=time.perf_counter() - started)
        args.output.write_text(json.dumps({'schema_version': 1, 'text': '', 'units': [], 'cues': [],
                                          'manifest': manifest}, ensure_ascii=False, indent=2), encoding='utf-8')
        args.output.with_suffix('.stderr.log').write_bytes(exc.stderr or b'')
        raise SystemExit(124) from exc


if __name__ == '__main__':
    main()
