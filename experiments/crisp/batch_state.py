"""Read-only strict resume checks for private Crisp development batches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run import PINS, sha256

DLL_HASH = 'd346663c39948cef204db12768eb340003115af9e904e25979a00c44113878a2'
EXE_HASH = '07dbe65c4adbea6e977bc0253d0991175cbd92ee871e5a5cf33ac4eda5303658'
REFERENCE_HASH = '2d31b51406dd33cfc3af300c9346280a31aac7b6c199208e87f1f92ce79ae583'


def check(path: Path, audio: Path, offset: float, stage: str, vad: bool, asr: Path | None) -> list[str]:
    reasons = []
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        harness = json.loads((path.parent / 'manifest.json').read_text(encoding='utf-8-sig'))
        manifest = data['manifest']
        if harness['status'] != 'completed' or harness['returncode'] != 0 or not harness['reference_unchanged']:
            reasons.append('harness_not_completed_and_reference_preserved')
        if harness.get('reference_sha256_before') != REFERENCE_HASH or harness.get('reference_sha256_after') != REFERENCE_HASH:
            reasons.append('reference_identity')
        if harness['audio_sha256'] != sha256(audio):
            reasons.append('harness_input_hash')
        if manifest['status'] != 'ok' or not data.get('text') or not data.get('native', {}).get('transcription'):
            reasons.append('failed_or_empty_prediction')
        if manifest['pins'] != PINS:
            reasons.append('frozen_pins')
        if stage == 'asr':
            if manifest['route'] != 'crisp-qwen-f16-cli-asr-only':
                reasons.append('asr_route')
            if manifest['input']['sha256'] != sha256(audio) or manifest['binary_sha256'] != EXE_HASH:
                reasons.append('asr_asset_identity')
            expected = {'source_offset_s': offset, 'gpu_backend': 'vulkan', 'device': 0,
                        'language': 'ja', 'temperature': 0, 'seed': 42, 'max_new_tokens': 512,
                        'threads': 4, 'chunk_seconds': 30, 'chunk_overlap': 3.0, 'vad': vad,
                        'energy_gate': True, 'native_writer_split_on_punct': False, 'aligner_executed': False}
            for name, value in expected.items():
                if manifest['config'].get(name) != value:
                    reasons.append('config_' + name)
            if vad and manifest.get('vad_sha256') != PINS['vad']['sha256']:
                reasons.append('vad_asset')
            if not manifest['device_evidence']['gpu_only_contexts_verified']:
                reasons.append('asr_gpu_proof')
            if manifest['model_hashes']['asr'] != PINS['asr']['sha256']:
                reasons.append('asr_model_hash_not_checked')
        else:
            if manifest['route'] != 'crisp-cli-asr-explicit-gpu-fa-replay':
                reasons.append('fa_route')
            if manifest.get('input_sha256') != sha256(audio) or manifest.get('asr_text_sha256') != sha256(asr):
                reasons.append('fa_input_identity')
            if manifest.get('dll_sha256') != DLL_HASH or manifest.get('aligner_sha256') != PINS['aligner']['sha256']:
                reasons.append('fa_asset_identity')
            if manifest.get('source_offset_s') != offset or manifest.get('gpu_backend') != 'vulkan' or manifest.get('threads') != 4:
                reasons.append('fa_config')
            if not manifest.get('actual_fa_gpu_verified') or manifest.get('failures'):
                reasons.append('fa_gpu_or_execution_failure')
            reasons.extend('saved_asr_' + reason for reason in check(asr, audio, offset, 'asr', vad, None))
    except (OSError, ValueError, KeyError, TypeError) as error:
        reasons.append('unreadable_or_incomplete:' + type(error).__name__)
    return reasons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--offset', type=float, required=True)
    parser.add_argument('--stage', choices=['asr', 'fa'], required=True)
    parser.add_argument('--vad', action='store_true')
    parser.add_argument('--asr', type=Path)
    args = parser.parse_args()
    if args.stage == 'fa' and args.asr is None:
        parser.error('FA resume check requires saved ASR result.')
    reasons = check(args.result, args.audio, args.offset, args.stage, args.vad, args.asr)
    print(json.dumps({'valid': not reasons, 'reasons': reasons, 'path': str(args.result.resolve())}))


if __name__ == '__main__':
    main()
