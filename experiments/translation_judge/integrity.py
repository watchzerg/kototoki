"""Accepted-byte integrity and explicitly retrospective legacy resume baselines."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any, Callable

VERSION = 'accepted-byte-sha256-v1'
LEGACY_VERSION = 'legacy-current-pair-baseline-v1'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def strict_parse(text: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def _windows_path(value: Path | PureWindowsPath | str) -> PureWindowsPath:
    """Normalize only equivalent DOS-drive/UNC namespaces, without filesystem I/O."""
    text = str(value).replace('/', '\\')
    lowered = text.lower()
    if lowered.startswith('\\\\?\\'):
        if lowered.startswith('\\\\?\\unc\\'):
            text = '\\\\' + text[8:]
        elif (len(text) >= 7 and text[4].lower() in 'abcdefghijklmnopqrstuvwxyz'
              and text[5:7] == ':\\'):
            text = text[4:]
        else:
            raise ValueError('Unsupported Windows evidence path namespace')
    elif lowered.startswith(('\\\\.\\', '\\??\\', '\\\\??\\')):
        raise ValueError('Unsupported Windows evidence path namespace')
    result = PureWindowsPath(text)
    if text.startswith('\\\\'):
        parts = result.drive[2:].split('\\')
        if (not result.drive.startswith('\\\\') or len(parts) != 2
                or any(part in {'', '.', '..'} or ':' in part for part in parts)):
            raise ValueError('Malformed Windows evidence UNC path')
    return result


def _resolved_path(path: Path) -> Path:
    if os.name != 'nt':
        return path.resolve()
    # Normalize before resolve so an extended input cannot keep a distinct
    # anchor; resolve still detects real parent/reparse escapes. Normalize its
    # output too because Windows may expose an extended final path.
    return Path(_windows_path(Path(_windows_path(path)).resolve()))


def inside(directory: Path, path: Path) -> Path:
    resolved = _resolved_path(path)
    if not resolved.is_relative_to(_resolved_path(directory)):
        raise ValueError('Accepted evidence path escapes job directory')
    return resolved


def accept_response(raw: Path, response: Path, validate: Callable[[Any], dict[str, Any]],
                    parse: Callable[[str], Any] = strict_parse) -> dict[str, Any]:
    observed = raw.read_bytes()
    validated = validate(parse(observed.decode('utf-8-sig')))
    canonical = canonical_bytes(validated)
    if raw.read_bytes() != observed:
        raise ValueError('Raw response changed during validation')
    snapshot = raw.with_name('accepted-canonical.json')
    response.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive writes preserve any unexpected earlier evidence and stop races.
    with snapshot.open('xb') as handle:
        handle.write(canonical)
    with response.open('xb') as handle:
        handle.write(canonical)
    return {'accepted_raw_response': str(raw), 'accepted_raw_response_sha256': sha(observed),
            'response_sha256': sha(canonical), 'accepted_canonical_snapshot': str(snapshot),
            'resume_integrity_version': VERSION,
            'hash_provenance': 'captured immediately after first successful validation'}


def capture_legacy_baseline(ledger: Path) -> dict[str, Any]:
    """Offline opt-in: prove only the current agreeing pair, not historical bytes."""
    previous_bytes = ledger.read_bytes()
    previous = strict_parse(previous_bytes.decode('utf-8-sig'))
    if previous.get('status') != 'succeeded':
        raise ValueError('Legacy baseline requires a successful original ledger')
    if any(key in previous for key in ('accepted_raw_response_sha256', 'response_sha256')):
        raise ValueError('Original hash metadata exists; do not reinterpret it as legacy')
    directory = ledger.parent
    raw = inside(directory, Path(previous['accepted_raw_response']))
    response = _resolved_path(Path(previous['response']))
    raw_bytes, response_bytes = raw.read_bytes(), response.read_bytes()
    if strict_parse(raw_bytes.decode('utf-8-sig')) != strict_parse(response_bytes.decode('utf-8-sig')):
        raise ValueError('Legacy raw/canonical pair disagrees; preserve original evidence')
    # A missing member cannot be filled from another member without an earlier baseline.
    baseline = directory / 'legacy-resume-baseline'
    if baseline.exists():
        raise ValueError('Legacy baseline already exists; never overwrite it')
    if ledger.read_bytes() != previous_bytes or raw.read_bytes() != raw_bytes or response.read_bytes() != response_bytes:
        raise ValueError('Legacy evidence changed during observation')
    baseline.mkdir()
    (baseline / 'observed-raw.bin').write_bytes(raw_bytes)
    (baseline / 'observed-canonical.json').write_bytes(response_bytes)
    record = {'version': LEGACY_VERSION, 'job_id': previous['job_id'], 'fingerprint': previous['fingerprint'],
              'captured_at': datetime.now(timezone.utc).isoformat(), 'ledger_sha256': sha(previous_bytes),
              'accepted_raw_response': str(raw), 'response': str(response),
              'observed_raw_response_sha256': sha(raw_bytes), 'observed_canonical_response_sha256': sha(response_bytes),
              'raw_snapshot': str(baseline / 'observed-raw.bin'),
              'canonical_snapshot': str(baseline / 'observed-canonical.json'),
              'original_acceptance_hashes_available': False,
              'provenance_limit_zh': '只记录迁移时一致的当前文件字节；原首次接受响应没有保存哈希，历史原始字节身份仍未知，不能追溯补造。'}
    (baseline / 'baseline.json').write_bytes(canonical_bytes(record))
    return record


def resume_success(previous: dict[str, Any], ledger: Path, response: Path,
                   validate: Callable[[Any], dict[str, Any]],
                   parse: Callable[[str], Any] = strict_parse) -> dict[str, Any]:
    """Verify/restore success locally; every refusal must precede any new dispatch."""
    raw = inside(ledger.parent, Path(previous['accepted_raw_response']))
    if _resolved_path(Path(previous['response'])) != _resolved_path(response):
        raise ValueError('Accepted canonical response identity changed')
    present = [key in previous for key in ('accepted_raw_response_sha256', 'response_sha256')]
    if all(present):
        evidence = previous
        provenance = {'version': previous.get('resume_integrity_version', VERSION),
                      'hash_provenance': previous.get('hash_provenance', 'hashes previously recorded in job ledger')}
        snapshot_path = previous.get('accepted_canonical_snapshot')
    elif any(present):
        raise ValueError('Incomplete accepted hash metadata; do not invent missing identity')
    else:
        baseline_path = ledger.parent / 'legacy-resume-baseline/baseline.json'
        if not baseline_path.exists():
            raise ValueError('Legacy success lacks original hashes; explicitly capture an offline current-pair baseline before resume')
        baseline = strict_parse(baseline_path.read_text(encoding='utf-8-sig'))
        if (baseline.get('version'), baseline.get('job_id'), baseline.get('fingerprint'), baseline.get('ledger_sha256')) != (
                LEGACY_VERSION, previous['job_id'], previous['fingerprint'], sha(ledger.read_bytes())):
            raise ValueError('Legacy baseline ledger/fingerprint identity changed')
        if (_resolved_path(Path(baseline['accepted_raw_response'])) != raw
                or _resolved_path(Path(baseline['response'])) != _resolved_path(response)):
            raise ValueError('Legacy baseline response identity changed')
        snapshot_path = baseline['canonical_snapshot']
        evidence = {'accepted_raw_response_sha256': baseline['observed_raw_response_sha256'],
                    'response_sha256': baseline['observed_canonical_response_sha256']}
        provenance = {'version': LEGACY_VERSION, 'baseline': str(baseline_path),
                      'captured_at': baseline['captured_at'], 'original_acceptance_hashes_available': False,
                      'provenance_limit_zh': baseline['provenance_limit_zh']}
        observed_raw_snapshot = inside(ledger.parent, Path(baseline['raw_snapshot']))
        if sha(observed_raw_snapshot.read_bytes()) != evidence['accepted_raw_response_sha256']:
            raise ValueError('Legacy observed raw snapshot changed')
    observed_raw = raw.read_bytes()
    if sha(observed_raw) != evidence['accepted_raw_response_sha256']:
        raise ValueError('Accepted raw response changed; refuse without re-dispatch')
    validated = validate(parse(observed_raw.decode('utf-8-sig')))
    if response.exists():
        canonical = response.read_bytes()
        if sha(canonical) != evidence['response_sha256']:
            raise ValueError('Accepted canonical response changed; refuse without overwrite')
        if parse(canonical.decode('utf-8-sig')) != validated:
            raise ValueError('Accepted raw/canonical content disagrees')
        restored = False
    else:
        if not snapshot_path:
            raise ValueError('No accepted canonical byte snapshot; exact restoration unavailable')
        snapshot = inside(ledger.parent, Path(snapshot_path))
        canonical = snapshot.read_bytes()
        if sha(canonical) != evidence['response_sha256'] or parse(canonical.decode('utf-8-sig')) != validated:
            raise ValueError('Accepted canonical snapshot changed or disagrees')
        if raw.read_bytes() != observed_raw:
            raise ValueError('Raw response changed during restoration')
        response.parent.mkdir(parents=True, exist_ok=True)
        with response.open('xb') as handle:
            handle.write(canonical)
        restored = True
    return {**previous, 'resumed': True, 'canonical_restored': restored,
            'resume_integrity_evidence': provenance}


def main() -> None:
    parser = argparse.ArgumentParser(description='Offline retrospective legacy-current-pair baseline; no model dispatch')
    parser.add_argument('--ledger', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(capture_legacy_baseline(args.ledger), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f'旧响应证据基线失败：{exc}\n')


if __name__ == '__main__':
    main()
