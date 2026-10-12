"""Summarize observed work without turning replay into fresh inference speed."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
from typing import Any
import wave


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def spread(values: list[float]) -> dict[str, Any]:
    return {'n': len(values), 'min': min(values) if values else None,
            'median': statistics.median(values) if values else None,
            'max': max(values) if values else None}


def gpu_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    devices: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    invalid = 0
    for sample in samples:
        elapsed = finite_number(sample.get('elapsed_seconds'))
        if sample.get('returncode') != 0 or elapsed is None:
            invalid += 1
            continue
        parsed = False
        for ordinal, row in enumerate(csv.reader(io.StringIO(sample.get('csv', '')), skipinitialspace=True)):
            if len(row) != 6:
                invalid += 1
                continue
            parsed = True
            devices[(ordinal, row[1].strip(), row[2].strip())].append({
                'elapsed_seconds': elapsed, 'memory_mb': finite_number(row[3]),
                'utilization_percent': finite_number(row[4]), 'power_watts': finite_number(row[5])})
        if not parsed and not sample.get('csv'):
            invalid += 1
    result = []
    for (ordinal, name, driver), readings in devices.items():
        readings.sort(key=lambda item: item['elapsed_seconds'])
        memory = [item['memory_mb'] for item in readings if item['memory_mb'] is not None]
        elapsed = [item['elapsed_seconds'] for item in readings]
        gaps = [end - start for start, end in zip(elapsed, elapsed[1:])]
        first_memory = readings[0]['memory_mb']
        result.append({'query_row_index': ordinal, 'name': name, 'driver_version': driver,
                       'sample_count': len(readings), 'first_sample_elapsed_s': elapsed[0],
                       'last_sample_elapsed_s': elapsed[-1], 'sampling_gap_s': spread(gaps),
                       'sampled_memory_mb': spread(memory), 'first_sample_memory_mb_proxy': first_memory,
                       'peak_minus_first_sample_mb_proxy': max(memory) - first_memory if memory and first_memory is not None else None,
                       'utilization_percent': spread([item['utilization_percent'] for item in readings if item['utilization_percent'] is not None]),
                       'power_watts': spread([item['power_watts'] for item in readings if item['power_watts'] is not None])})
    return {'devices': result, 'query_records': len(samples), 'invalid_query_or_row_count': invalid,
            'limitation': 'Whole-device samples include desktop/other processes; first/min are baseline proxies, not measured idle baseline. Peaks between samples may be missed; no per-process or model-only peak inference. Device identity is query row order/name/driver.'}


def cache_classification(candidate: dict[str, Any], harness: dict[str, Any], *, pipeline_verified: bool | None = None) -> dict[str, Any]:
    meta = candidate.get('manifest', candidate)
    flags = {name: container[name] for container in (candidate, meta)
             for name in ('cached_inference', 'cache_reused', 'asr_inference_reused', 'fa_inference_reused') if name in container}
    if candidate.get('effective_parameters', {}).get('asr_reused') is True:
        flags['asr_result_reused'] = True
    route = meta.get('route', candidate.get('route', candidate.get('backend', 'unknown')))
    config = meta.get('config', {})
    component = (any(part in str(route) for part in ('asr-only', 'fa-only', 'fa-replay'))
                 or bool(config.get('alignment_only')) or config.get('asr_only') is True)
    pipeline = candidate.get('pipeline', {})
    if pipeline.get('cache_classification') == 'fresh_end_to_end':
        classification = 'fresh_complete_pipeline' if pipeline_verified is True and harness.get('fresh_subprocess') is True else 'fresh_pipeline_declared_unverified'
    elif flags.get('asr_inference_reused') is True and flags.get('fa_inference_reused') is False:
        classification = 'reused_asr_fresh_fa_component'
    elif any(value is True for value in flags.values()):
        classification = 'cached_or_reused_inference'
    elif flags and all(value is False for value in flags.values()) and harness.get('fresh_subprocess') is True:
        classification = 'fresh_component' if component else 'fresh_complete_pipeline'
    else:
        classification = 'unknown_inference_freshness'
    return {'classification': classification, 'explicit_flags': flags, 'fresh_subprocess': harness.get('fresh_subprocess'),
            'limitation': 'Provisioned model/download caches do not imply inference reuse. Fresh process does not prove cold OS/model file cache. Replayed ASR is never included in fresh full-pipeline performance.'}


def pipeline_artifacts(candidate: dict[str, Any], harness: dict[str, Any]) -> dict[str, Any] | None:
    """Bind cross-family executed source and ASR input without copying its text."""
    pipeline = candidate.get('pipeline')
    if not isinstance(pipeline, dict):
        return None
    issues, verified_stages, sources = [], {}, {}
    if (pipeline.get('status') != 'completed' or pipeline.get('new_asr_inference') is not True
            or pipeline.get('new_alignment_inference') is not True
            or pipeline.get('stage_cache', {}).get('asr') != 'fresh'
            or pipeline.get('audio_sha256') != harness.get('audio_sha256')):
        issues.append('pipeline_fresh_execution_or_audio_evidence')
    for name, artifact in pipeline.get('source_files', {}).items():
        try:
            actual = file_hash(Path(artifact['path']))
            if actual != artifact['sha256']:
                issues.append('source_hash_mismatch:' + name)
            sources[name] = actual
        except (OSError, KeyError, TypeError):
            issues.append('source_unavailable:' + name)
    if not sources:
        issues.append('pipeline_source_snapshot_missing')
    for stage in pipeline.get('stages', []):
        name = stage.get('stage', 'unknown')
        try:
            actual = file_hash(Path(stage['output']))
            if actual != stage['output_sha256'] or stage.get('status') != 'completed' or stage.get('returncode') != 0:
                issues.append('stage_hash_or_execution:' + name)
            verified_stages[name] = {'path': stage['output'], 'sha256': actual}
        except (OSError, KeyError, TypeError):
            issues.append('stage_unavailable:' + name)
    if not {'asr', 'ctc'}.issubset(verified_stages):
        issues.append('required_pipeline_stages_missing')
    asr = None
    artifact = verified_stages.get('asr')
    try:
        if not artifact or str(Path(pipeline['asr_result']).resolve()) != str(Path(artifact['path']).resolve()):
            raise ValueError('ASR output is not bound to executed stage.')
        asr = json.loads(Path(artifact['path']).read_text(encoding='utf-8-sig'))
        asr_input = asr.get('input', {})
        if asr_input.get('file_sha256', asr_input.get('sha256')) != harness.get('audio_sha256'):
            issues.append('asr_stage_input_identity')
        asr_fresh = cache_classification(asr, harness)['classification']
        if asr_fresh not in ('fresh_component', 'fresh_complete_pipeline'):
            issues.append('asr_stage_not_fresh')
    except (OSError, ValueError, KeyError, TypeError):
        issues.append('hash_bound_asr_stage_unavailable')
    return {'verified_fresh_pipeline': not issues, 'issues': issues,
            'source_sha256': sources, 'stage_artifact_identity': verified_stages,
            'asr_execution_identity': execution_identity(asr, harness, {'devices': []}) if asr else None,
            'provenance': pipeline}


def orchestration_paths(value: Any, pipeline: dict[str, Any] | None) -> Any:
    """Normalize only verified per-run intermediate paths, never model/options."""
    paths = {artifact['path']: '<pipeline-stage:' + name + '>'
             for name, artifact in (pipeline or {}).get('stage_artifact_identity', {}).items()}
    if isinstance(value, str):
        return paths.get(value, value)
    if isinstance(value, dict):
        return {key: orchestration_paths(item, pipeline) for key, item in value.items()}
    if isinstance(value, list):
        return [orchestration_paths(item, pipeline) for item in value]
    return value


def execution_identity(candidate: dict[str, Any], harness: dict[str, Any], hardware: dict[str, Any]) -> dict[str, Any]:
    meta = candidate.get('manifest', candidate)
    effective = candidate.get('effective_parameters', {})
    effective_config = {key: value for key, value in effective.items() if key != 'info'}
    if 'info' in effective:
        effective_config['info'] = {key: effective['info'].get(key) for key in ('transcription_options', 'vad_options')}
    model_keys = ('pins', 'models', 'model_identity', 'checkpoint_file_sha256', 'model_hashes', 'aligner_sha256', 'dll_sha256', 'binary_sha256')
    return {'audio_sha256': harness.get('audio_sha256'), 'source_sha256': harness.get('source_sha256', {}),
            'route': meta.get('route', candidate.get('route', candidate.get('backend'))),
            'config': meta.get('config', candidate.get('config', {})), 'effective_parameters': effective_config,
            'generation_config': candidate.get('generation_config'),
            'model_identity': {key: meta.get(key, candidate.get(key)) for key in model_keys if key in meta or key in candidate},
            'environment': candidate.get('environment'), 'runtime_identity': candidate.get('runtime_identity'),
            'platform': harness.get('platform'), 'harness_python': harness.get('harness_python'),
            'source_offset_seconds': candidate.get('source_start_seconds', meta.get('source_offset_s')),
            'hardware': [{key: device[key] for key in ('query_row_index', 'name', 'driver_version')} for device in hardware['devices']],
            'scope_limit': 'Only source/model/runtime identities actually recorded by adapters/harness; missing transitive dependency snapshots are not inferred.'}


def bound_audio(harness: dict[str, Any], cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    path = Path(harness.get('audio', ''))
    key = str(path.resolve())
    if key not in cache:
        try:
            with wave.open(str(path), 'rb') as stream:
                frames, rate = stream.getnframes(), stream.getframerate()
                info = {'path': key, 'duration_seconds': frames / rate, 'frames': frames, 'sample_rate': rate,
                        'channels': stream.getnchannels(), 'sample_width': stream.getsampwidth(), 'sha256': file_hash(path)}
            cache[key] = info
        except (OSError, wave.Error, ZeroDivisionError) as error:
            cache[key] = {'path': key, 'duration_seconds': None, 'sha256': None, 'error': type(error).__name__}
    result = dict(cache[key])
    result['matches_harness_sha256'] = result['sha256'] is not None and result['sha256'] == harness.get('audio_sha256')
    return result


def summarize_run(path: Path, audio_cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record: dict[str, Any] = {'manifest_path': str(path.resolve()), 'run_id': path.parent.name,
                              'retained': True, 'issues': []}
    try:
        harness = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        return {**record, 'status': 'manifest_unreadable', 'issues': [type(error).__name__], 'eligible_fresh_pipeline': False}
    record.update(run_id=harness.get('id', path.parent.name), manifest_sha256=file_hash(path),
                  status=harness.get('status', 'missing_status'), process_exit_code=harness.get('returncode'),
                  actual_wall_seconds=finite_number(harness.get('wall_seconds')),
                  performance_context=harness.get('performance_context'), reference_unchanged=harness.get('reference_unchanged'))
    candidate_path = path.parent / 'result.json'
    try:
        candidate = json.loads(candidate_path.read_text(encoding='utf-8-sig'))
        record['candidate_sha256'] = file_hash(candidate_path)
    except (OSError, ValueError) as error:
        candidate = {}
        record['issues'].append('candidate_unreadable:' + type(error).__name__)
    meta = candidate.get('manifest', candidate)
    record['candidate_status'] = meta.get('status', 'not_recorded')
    record['gpu_sampling'] = gpu_samples(harness.get('gpu_samples', []))
    record['audio'] = bound_audio(harness, audio_cache)
    pipeline = pipeline_artifacts(candidate, harness)
    record['inference'] = cache_classification(candidate, harness, pipeline_verified=pipeline['verified_fresh_pipeline'] if pipeline else None)
    record['stage_measurements'] = {key: container[key] for container in (candidate, meta)
                                    for key in ('stages', 'timings', 'wall_s', 'asr_s', 'fa_s', 'model_load_s', 'native_stage_timings') if key in container}
    if pipeline:
        record['stage_measurements']['pipeline_stages'] = candidate['pipeline'].get('stages', [])
        record['stage_measurements']['pipeline_wall_seconds'] = candidate['pipeline'].get('wall_seconds')
        record['pipeline_provenance'] = pipeline
        record['issues'].extend(pipeline['issues'])
    record['stage_time_limit'] = 'Adapter stage timers may overlap/nest or omit initialization; retained unchanged and never summed into a new full-pipeline wall. This run harness wall is the observed process cost.'
    record['identity'] = orchestration_paths(execution_identity(candidate, harness, record['gpu_sampling']), pipeline)
    if pipeline:
        # Artifact output SHA varies with output/timers and belongs in provenance,
        # not the repeat configuration. Bound ASR model/config/source is stable.
        record['identity']['pipeline_source_sha256'] = pipeline['source_sha256']
        record['identity']['pipeline_asr_execution_identity'] = pipeline['asr_execution_identity']
    record['identity_sha256'] = canonical_hash(record['identity'])
    record['identity_missing_fields'] = [key for key in ('audio_sha256', 'source_sha256', 'route', 'model_identity', 'hardware')
                                         if not record['identity'].get(key)]
    if not record['identity']['config'] and not record['identity']['effective_parameters']:
        record['identity_missing_fields'].append('config_or_effective_parameters')
    record['candidate_device_evidence'] = meta.get('device_evidence', candidate.get('devices'))
    try:
        record['output_stability'] = {'text_sha256': hashlib.sha256(candidate['text'].encode('utf-8')).hexdigest(),
                                       'timed_units_sha256': canonical_hash(candidate['units']),
                                       'text_characters': len(candidate['text']), 'units': len(candidate['units'])}
    except (KeyError, TypeError, ValueError):
        record['output_stability'] = None
        record['issues'].append('missing_or_invalid_output_hash_contract')
    successful = (harness.get('status') == 'completed' and harness.get('returncode') == 0
                  and harness.get('reference_unchanged') is True and bool(candidate)
                  and meta.get('status', 'ok') in ('ok', 'completed'))
    record['execution_success'] = successful
    duration = record['audio']['duration_seconds']
    bound = record['audio']['matches_harness_sha256'] and duration is not None and duration > 0
    wall = record['actual_wall_seconds']
    record['attempt_wall_per_input_duration'] = wall / duration if bound and wall is not None else None
    record['eligible_fresh_pipeline'] = (successful and bound and wall is not None and wall >= 0
                                         and record['inference']['classification'] == 'fresh_complete_pipeline')
    record['fresh_complete_pipeline_rtf'] = record['attempt_wall_per_input_duration'] if record['eligible_fresh_pipeline'] else None
    return record


def build_report(paths: list[Path]) -> dict[str, Any]:
    audio_cache: dict[str, dict[str, Any]] = {}
    runs = [summarize_run(path, audio_cache) for path in paths]
    seen: dict[str, int] = {}
    for index, run in enumerate(runs):
        evidence = run.get('manifest_sha256')
        if evidence and evidence in seen:
            run['duplicate_of_requested_index'] = seen[evidence]
            run['eligible_fresh_pipeline'] = False
            run['fresh_complete_pipeline_rtf'] = None
            run['issues'].append('duplicate_manifest_evidence_not_another_actual_repeat')
        elif evidence:
            seen[evidence] = index
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run.get('identity_sha256'):
            grouped[run['identity_sha256']].append(run)
    groups = []
    for identity, records in grouped.items():
        fresh = [run for run in records if run['eligible_fresh_pipeline']]
        hashes = [run['output_stability'] for run in fresh if run['output_stability'] is not None]
        groups.append({'identity_sha256': identity, 'run_ids': [run['run_id'] for run in records],
                       'recorded_input_source_config_identity_equal': True, 'all_attempts_count': len(records),
                       'recorded_identity_complete': all(not run['identity_missing_fields'] for run in records),
                       'successful_fresh_pipeline_count': len(fresh),
                       'fresh_pipeline_wall_seconds': spread([run['actual_wall_seconds'] for run in fresh]),
                       'fresh_pipeline_rtf': spread([run['fresh_complete_pipeline_rtf'] for run in fresh]),
                       'fresh_exact_text_hash_count': len(set(item['text_sha256'] for item in hashes)),
                       'fresh_exact_timed_units_hash_count': len(set(item['timed_units_sha256'] for item in hashes)),
                       'fresh_output_hash_available_count': len(hashes),
                       'repeatability_evidence': 'observed_repeats_only' if len(hashes) >= 2 else 'insufficient_fewer_than_two_fresh_outputs'})
    return {'schema_version': 1, 'purpose': 'resources_performance_repeatability_only_no_quality_ranking',
            'runs': runs, 'repeat_groups': groups,
            'counts': {'all_requested_runs': len(runs), 'execution_success': sum(run.get('execution_success', False) for run in runs),
                       'failed_or_incomplete': sum(not run.get('execution_success', False) for run in runs),
                       'successful_fresh_pipeline': sum(run['eligible_fresh_pipeline'] for run in runs),
                       'duplicate_supplied_evidence': sum('duplicate_of_requested_index' in run for run in runs),
                       'status_counts': dict(Counter(run['status'] for run in runs)),
                       'freshness_counts': dict(Counter(run.get('inference', {}).get('classification', 'unreadable') for run in runs))},
            'limits': ['All supplied runs retained, including missing/failed/running attempts; no candidate quality ranking.',
                       'RTF is actual harness wall divided by SHA-bound WAV duration; failed/replay ratio is labeled attempt cost and excluded from fresh pipeline statistics.',
                       'Three repeats do not establish population latency tails; successful repeats and whole-film runs must share exact recorded identities to be grouped.',
                       'Output hashes disclose stability only, not transcription accuracy. No transcript content is emitted.',
                       'No GPU inference, model download, network call, or environment change is performed.']}
