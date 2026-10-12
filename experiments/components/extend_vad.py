"""Freeze the unchanged W0+VAD pilot configuration on all twelve development clips."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from experiments.components.run_vad import (
    ROOT, LOCAL, make_tasks, verify_clip, verify_sources, validate_name,
)
from experiments.components.run import read, digest, write_new


def prepare(name: str) -> dict:
    validate_name(name)
    parent_path = LOCAL / 'comp-vad-pilot-v1/plan.json'
    parent = read(parent_path)
    verify_sources(parent, models=True)
    if (LOCAL / name).exists():
        raise FileExistsError('Use a new experiment identity')
    corpus_path = ROOT / '.local/round2/corpus/manifest.json'
    corpus = read(corpus_path)
    clips = corpus['clips']
    if len(clips) != 12:
        raise ValueError('Expected all twelve original comparison clips')
    for clip in clips:
        verify_clip(clip)
    tasks = [task for task in make_tasks(name, clips) if task['stage'] in ('vad', 'w0')]
    for task in tasks:
        if (ROOT / '.local/results' / task['id']).exists() or Path(task['output']).exists():
            raise FileExistsError('Existing task artifacts cannot be reused under a fresh identity')
    plan = copy.deepcopy(parent)
    plan.update(id=name, clips=clips, tasks=tasks,
                scope='all twelve exposed development windows; unchanged W0+VAD configuration',
                selection_policy='W0 pilot improves CER, D, I and half-second successes on both films; extend alone before considering CTC',
                promotion_from={'path': str(parent_path), 'sha256': digest(parent_path)},
                input_registry={'path': str(corpus_path), 'sha256': digest(corpus_path)},
                comparison_routes=['w0-baseline', 'w1-baseline', 'x0-baseline', 'w0-vad'],
                cost_policy='Fresh VAD and W0 per clip; sum both harness walls; pilot overlap is repeated execution, not independent samples')
    plan['source_sha256'][str(Path(__file__).resolve())] = digest(Path(__file__))
    write_new(LOCAL / name / 'plan.json', plan)
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    prepare(args.name)
