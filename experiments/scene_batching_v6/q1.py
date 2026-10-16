"""Q1 (offline): are b10-joint errors concentrated where a batch mixes cues across a silence gap?

Reads the v4 b10-joint (and c0, dev only) runs and their judgements read-only; writes
``<v6 root>/q1/q1.json``. Two analyses per set, recipe and threshold:

1. classes: minority / majority side of a batch crossing a gap vs clean batches, per error category,
   and the wrong-referent share of the accuracy penalty;
2. boundary natural experiment: the cues directly next to a gap, when the gap falls inside a batch
   vs exactly on a batch boundary. Batch boundaries sit at fixed multiples of the batch size from
   cue 0, independent of content, so both groups are equally "scene-edge" cues;
3. position check for 2: in clean batches (no gap >= threshold), batch-edge cues (first/last) vs
   interior cues, since the "boundary" group of 2 always sits at a batch edge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.translation_v3.common import atomic_write_json, read_json
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT
from experiments.translation_v4.reference import load_scenes, windows as tiled_windows

from . import gaps as G
from .common import V6_ROOT
from .stats6 import METRICS, SceneTable, contrast, mean_diff, mean_over_runs, run_metrics, share_diff

THRESHOLDS = (5.0, 10.0, 20.0)
ARMS = (("dev", "b10-joint"), ("confirm", "b10-joint"), ("dev", "c0"))


def run_dirs(root: Path, recipe: str, set_name: str) -> list[Path]:
    return sorted(p for p in (root / "runs").glob(f"{recipe}__s*__{set_name}") if (p / "run.json").is_file())


def batch_spans(run_dir: Path, scene_id: str) -> list[tuple[int, int]]:
    return [(b["start"], b["stop"]) for b in read_json(run_dir / "scenes" / f"{scene_id}.json")["batches"]]


def labels_for(scenes: list[dict[str, Any]], spans: dict[str, list[tuple[int, int]]], threshold: float,
               kind: str) -> dict[str, str]:
    out = {}
    for scene in scenes:
        if scene["scene_id"] not in spans:
            continue
        gaps = G.cue_gaps(scene["cues"])
        fn = {"class": G.classify, "adjacent": G.gap_adjacent, "position": G.clean_position}[kind]
        for index, label in fn(spans[scene["scene_id"]], gaps, threshold).items():
            out[scene["cues"][index]["id"]] = label
    return out


def analyse(v4_root: Path = V4_ROOT, reps: int = 2000) -> dict[str, Any]:
    report: dict[str, Any] = {"schema": "scene-batching-v6-q1-v1", "thresholds": THRESHOLDS, "metrics": METRICS,
                              "arms": {}}
    for set_name, recipe in ARMS:
        windows = tiled_windows(v4_root, set_name)
        scenes = load_scenes(v4_root, set_name)
        scene_of = {c["id"]: s["scene_id"] for s in scenes for c in s["cues"]}
        work_of = {s["scene_id"]: s["work_id"] for s in scenes}
        category_of = {s["work_id"]: s["category"] for s in scenes}
        dirs = run_dirs(v4_root, recipe, set_name)
        per_run, spans, missing = [], {}, {}
        for run_dir in dirs:
            result = run_metrics(run_dir, windows)
            if result["missing"]:
                missing[run_dir.name] = len(result["missing"])
            per_run.append(result["values"])
            for scene_id in read_json(run_dir / "run.json")["scene_ids"]:
                spans.setdefault(scene_id, batch_spans(run_dir, scene_id))
        values = mean_over_runs(per_run)
        arm: dict[str, Any] = {"runs": [d.name for d in dirs], "missing_windows": missing, "cues": len(values),
                               "by_threshold": {}}
        for threshold in THRESHOLDS:
            row: dict[str, Any] = {}
            table = SceneTable(labels_for(scenes, spans, threshold, "class"), values, scene_of, work_of, category_of)
            row["class_counts"] = table.counts()
            for side in ("minority", "majority"):
                row[f"{side}_minus_clean"] = {m: contrast(table, side, "clean", mean_diff(m), reps=reps)
                                              for m in METRICS}
            row["minority_minus_clean_share"] = {m: contrast(table, "minority", "clean", share_diff(m), reps=reps)
                                                 for m in METRICS[1:]}
            adj = SceneTable(labels_for(scenes, spans, threshold, "adjacent"), values, scene_of, work_of, category_of)
            row["adjacent_counts"] = adj.counts()
            row["in_batch_minus_boundary"] = {m: contrast(adj, "in_batch", "boundary", mean_diff(m), reps=reps)
                                              for m in METRICS}
            pos = SceneTable(labels_for(scenes, spans, threshold, "position"), values, scene_of, work_of, category_of)
            row["clean_position_counts"] = pos.counts()
            row["clean_edge_minus_interior"] = {m: contrast(pos, "edge", "interior", mean_diff(m), reps=reps)
                                                for m in METRICS}
            arm["by_threshold"][str(threshold)] = row
        report["arms"][f"{set_name}/{recipe}"] = arm
    return report


def main(v6_root: Path = V6_ROOT) -> Path:
    report = analyse()
    path = v6_root / "q1" / "q1.json"
    atomic_write_json(path, report)
    return path
