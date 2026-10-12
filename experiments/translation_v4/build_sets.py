"""Build the v4 dev set and the sealed v4 confirmation set (selection is content-blind).

dev     = the 34 v3 screening scenes (opened; development material only) + new contiguous
          segments from the five series works v3 never used (W04 W05 W07 W08 W10).
confirm = new contiguous segments only: 3 untouched episodes per series work (11 works) and every
          movie cue range not within 8 cues of a v2/v3 scene and outside the historical movie windows.

Every cue of every scene is scored (no window sampling). Segments are chosen by a fixed-seed RNG
from catalog metadata and cue counts only; texts are read only to write model input (ja) and the
reviewer inputs (ja + fansub zh). The confirm reviewer inputs live under evaluation-only/confirm and
are not printed. Writing is refused if a set already exists with different content.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import random
from typing import Any

from experiments.translation_v3 import data as v3data
from experiments.translation_v3.common import (V2_ROOT, atomic_write_json, atomic_write_jsonl, read_json,
                                               sha256_file, utc_now)

from . import inventory as inv
from .common import DEFAULT_ROOT, evaluation_dir, set_dir

SET_SCHEMA = "hy30-flow-v4-set-v1"
DEV_NEW_WORKS = ("W04", "W05", "W07", "W08", "W10")
DEV_NEW_EPISODES = 2
DEV_NEW_LENGTH = 110
CONFIRM_EPISODES = 3
CONFIRM_LENGTH = 120
MOVIE_MARGIN = 8
MOVIE_MIN_RUN = 30
MOVIE_MAX_SEGMENT = 200
EDGE_FRACTION = 0.05
ALIGN_TOLERANCE = 0.5
SHARD_CUES = 350
SELECTION_SEED = {"dev": "v4-dev-selection-20261011", "confirm": "v4-confirm-selection-20261011"}


MIN_MATCHED = 0.95


def zh_index_map(ja: list[inv.SrtCue], zh: list[inv.SrtCue]) -> dict[int, int]:
    """ja index -> zh index by start time (two pointers, tolerance ALIGN_TOLERANCE); robust to a
    missing or duplicated cue on one side, which shifts plain index pairing (M03)."""
    result, j = {}, 0
    for i, cue in enumerate(ja):
        while j < len(zh) and zh[j].start < cue.start - ALIGN_TOLERANCE:
            j += 1
        if j < len(zh) and abs(zh[j].start - cue.start) <= ALIGN_TOLERANCE:
            result[i] = j
            j += 1
    return result


def _aligned(ja: list[inv.SrtCue], zh: list[inv.SrtCue], start: int, stop: int) -> bool:
    mapping = zh_index_map(ja, zh)
    matched = sum(i in mapping for i in range(start, stop))
    return all(ja[i].text.strip() for i in range(start, stop)) and matched >= MIN_MATCHED * (stop - start)


def _segment_scene(prefix: str, source: inv.Source, ja: list[inv.SrtCue], start: int, stop: int) -> dict[str, Any]:
    sid = source.source_id
    return {"scene_id": f"{prefix}-{sid}-S{start + 1:05d}", "work_id": source.work_id, "work": source.work,
            "category": source.category, "source_id": sid, "source_ja_srt": str(source.ja_srt),
            "source_ja_sha256": sha256_file(source.ja_srt), "source_zh_sha256": sha256_file(source.zh_srt),
            "first_srt_number": start + 1, "last_srt_number": stop,
            "cues": [{"id": f"{prefix}-{sid}-J{i + 1:05d}", "srt_number": i + 1, "text": ja[i].text,
                      "start": ja[i].start, "end": ja[i].end} for i in range(start, stop)]}


def _pick_episode_segments(rng: random.Random, prefix: str, candidates: list[inv.Source], count: int,
                           length: int, used: dict[str, list]) -> list[dict[str, Any]]:
    order = sorted(candidates, key=lambda s: s.source_id)
    rng.shuffle(order)
    scenes = []
    for source in order:
        if len(scenes) == count:
            break
        if used.get(inv._key(source.ja_srt)):
            continue  # only untouched episodes
        ja, zh = inv.read_srt(source.ja_srt), inv.read_srt(source.zh_srt)
        low = int(len(ja) * EDGE_FRACTION)
        high = len(ja) - int(len(ja) * EDGE_FRACTION) - length
        if high < low:
            continue
        start = rng.randint(low, high)
        if not _aligned(ja, zh, start, start + length):
            continue
        scenes.append(_segment_scene(prefix, source, ja, start, start + length))
    if len(scenes) < count:
        raise ValueError(f"Only {len(scenes)} aligned untouched episodes for {candidates[0].work_id}")
    return scenes


def _movie_segments(prefix: str, source: inv.Source, used: dict[str, list]) -> list[dict[str, Any]]:
    ja, zh = inv.read_srt(source.ja_srt), inv.read_srt(source.zh_srt)
    scenes = []
    for start, stop in inv.free_runs(len(ja), used.get(inv._key(source.ja_srt), []), MOVIE_MARGIN, 0):
        if stop - start < MOVIE_MIN_RUN:
            continue
        parts = -(-(stop - start) // MOVIE_MAX_SEGMENT)
        bounds = [start + round(k * (stop - start) / parts) for k in range(parts + 1)]
        for a, b in zip(bounds, bounds[1:]):
            if _aligned(ja, zh, a, b):
                scenes.append(_segment_scene(prefix, source, ja, a, b))
    return scenes


def _v3_dev_scenes() -> list[dict[str, Any]]:
    scenes, _, hashes = v3data.load_screening()
    manifest = {r["scene_id"]: r for r in read_json(V2_ROOT / "source/screening-qualified-v1/source-manifest.json")["windows"]}
    by_source = {inv._key(s.ja_srt): s for s in inv.sources()}
    rows = []
    for scene in scenes:
        meta = manifest[scene.scene_id]
        path = Path(meta["source_srt"])
        path = path if path.is_absolute() else inv.LIBRARY / path
        source = by_source[inv._key(path)]
        rows.append({"scene_id": scene.scene_id, "work_id": source.work_id, "work": source.work,
                     "category": source.category, "source_id": source.source_id, "source_ja_srt": str(source.ja_srt),
                     "source_ja_sha256": sha256_file(source.ja_srt), "source_zh_sha256": sha256_file(source.zh_srt),
                     "first_srt_number": meta["visible_start_index"], "last_srt_number": meta["visible_end_index"],
                     "origin": "v3-screening",
                     "cues": [{"id": c.id, "srt_number": int(c.id.rsplit("-J", 1)[1]), "text": c.text,
                               "start": c.start, "end": c.end} for c in scene.cues]})
    return rows


def _assign_blocks(scenes: list[dict[str, Any]]) -> None:
    by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scene in scenes:
        by_work[scene["work_id"]].append(scene)
    for offset, work in enumerate(sorted(by_work)):
        for i, scene in enumerate(sorted(by_work[work], key=lambda s: s["scene_id"])):
            scene["seed_block"] = (i + offset) % 3
            scene["half"] = "A" if (i + offset) % 2 == 0 else "B"


def build(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    used = inv.used_ranges()
    sources = inv.sources()
    by_work: dict[str, list[inv.Source]] = defaultdict(list)
    for source in sources:
        by_work[source.work_id].append(source)
    dev_rng, confirm_rng = random.Random(SELECTION_SEED["dev"]), random.Random(SELECTION_SEED["confirm"])
    dev = _v3_dev_scenes()
    for work in DEV_NEW_WORKS:
        dev += [s | {"origin": "v4-new"} for s in
                _pick_episode_segments(dev_rng, "V4D", by_work[work], DEV_NEW_EPISODES, DEV_NEW_LENGTH, used)]
    dev_sources = {s["source_id"] for s in dev}
    confirm = []
    for work in sorted(w for w in by_work if w.startswith("W")):
        pool = [s for s in by_work[work] if s.source_id not in dev_sources]
        confirm += [s | {"origin": "v4-new"} for s in
                    _pick_episode_segments(confirm_rng, "V4C", pool, CONFIRM_EPISODES, CONFIRM_LENGTH, used)]
    for work in sorted(w for w in by_work if w.startswith("M")):
        confirm += [s | {"origin": "v4-new"} for s in _movie_segments("V4C", by_work[work][0], used)]
    _check_isolation(dev, confirm, used)
    result = {}
    for name, scenes in (("dev", dev), ("confirm", confirm)):
        _assign_blocks(scenes)
        result[name] = _write_set(root, name, scenes)
    return result


def _check_isolation(dev: list[dict[str, Any]], confirm: list[dict[str, Any]], used: dict[str, list]) -> None:
    taken: dict[str, set[int]] = defaultdict(set)
    for scene in dev:
        taken[inv._key(scene["source_ja_srt"])].update(c["srt_number"] for c in scene["cues"])
    for scene in confirm:
        key = inv._key(scene["source_ja_srt"])
        numbers = {c["srt_number"] for c in scene["cues"]}
        near = {n + d for n in taken[key] for d in range(-MOVIE_MARGIN, MOVIE_MARGIN + 1)}
        if numbers & near:
            raise ValueError(f"confirm scene {scene['scene_id']} is within {MOVIE_MARGIN} cues of a dev scene")
        for low, high, why in used.get(key, []):
            pad = 0 if why.startswith("historical") else MOVIE_MARGIN
            if any(low - pad <= n - 1 <= high + pad for n in numbers):
                raise ValueError(f"confirm scene {scene['scene_id']} overlaps used range {why}")


def _write_set(root: Path, name: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    folder, evaluation = set_dir(root, name), evaluation_dir(root, name)
    model_rows = [{k: v for k, v in s.items()} | {"cues": [{k: c[k] for k in ("id", "text", "start", "end")}
                                                         for c in s["cues"]]} for s in scenes]
    review_rows = []
    zh_cache: dict[str, list[inv.SrtCue]] = {}
    maps: dict[str, dict[int, int]] = {}
    for scene in scenes:
        path = Path(scene["source_ja_srt"]).with_name("zh.srt")
        if str(path) not in zh_cache:
            zh_cache[str(path)] = inv.read_srt(path)
            maps[str(path)] = zh_index_map(inv.read_srt(Path(scene["source_ja_srt"])), zh_cache[str(path)])
        zh, mapping = zh_cache[str(path)], maps[str(path)]
        review_rows.append({"scene_id": scene["scene_id"], "work": scene["work"], "category": scene["category"],
                            "cues": [{"id": c["id"], "ja": c["text"],
                                      "fansub_zh": zh[mapping[c["srt_number"] - 1]].text
                                      if c["srt_number"] - 1 in mapping else None}
                                     for c in scene["cues"]]})
    scenes_path = folder / "scenes.jsonl"
    if scenes_path.is_file():
        existing = scenes_path.read_text(encoding="utf-8")
        import json
        fresh = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in model_rows)
        if existing != fresh:
            raise ValueError(f"{scenes_path} exists with different content; sets are frozen once written")
    atomic_write_jsonl(scenes_path, model_rows)
    shards, current, size = [], [], 0
    for row in review_rows:
        current.append(row)
        size += len(row["cues"])
        if size >= SHARD_CUES:
            shards.append(current)
            current, size = [], 0
    if current:
        shards.append(current)
    shard_files = []
    for index, rows in enumerate(shards, 1):
        path = evaluation / "review-input" / f"shard-{index:02d}.jsonl"
        atomic_write_jsonl(path, rows)
        shard_files.append({"path": str(path.relative_to(root)), "sha256": sha256_file(path), "scenes": len(rows),
                            "cues": sum(len(r["cues"]) for r in rows)})
    counts: dict[str, Any] = defaultdict(lambda: {"scenes": 0, "cues": 0})
    for scene in scenes:
        for key in (scene["category"], scene["work_id"]):
            counts[key]["scenes"] += 1
            counts[key]["cues"] += len(scene["cues"])
    manifest = {"schema": SET_SCHEMA, "set": name, "built_at_utc": utc_now(),
                "selection": {"seed": SELECTION_SEED[name], "dev_new_works": DEV_NEW_WORKS,
                              "dev_new_episodes": DEV_NEW_EPISODES, "dev_new_length": DEV_NEW_LENGTH,
                              "confirm_episodes": CONFIRM_EPISODES, "confirm_length": CONFIRM_LENGTH,
                              "movie_margin": MOVIE_MARGIN, "movie_min_run": MOVIE_MIN_RUN,
                              "movie_max_segment": MOVIE_MAX_SEGMENT, "edge_fraction": EDGE_FRACTION,
                              "rule": __doc__},
                "scenes_sha256": sha256_file(scenes_path), "scenes": len(scenes),
                "cues": sum(len(s["cues"]) for s in scenes), "counts": dict(sorted(counts.items())),
                "seed_blocks": {b: sum(len(s["cues"]) for s in scenes if s["seed_block"] == b) for b in range(3)},
                "halves": {h: sum(len(s["cues"]) for s in scenes if s["half"] == h) for h in "AB"},
                "review_shards": shard_files}
    atomic_write_json(folder / "manifest.json", manifest)
    return {k: manifest[k] for k in ("scenes", "cues", "counts", "seed_blocks", "halves")} | {"shards": len(shard_files)}


if __name__ == "__main__":
    import json
    print(json.dumps(build(), ensure_ascii=False, indent=1))
