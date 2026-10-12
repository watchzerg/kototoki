"""Load frozen v2 source scenes/windows and freeze/load reference-v3."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .common import (REFERENCE_V1_DIR, SOURCE_DIR, atomic_write_json, atomic_write_jsonl,
                     read_json, read_jsonl, sha256_bytes, sha256_file, utc_now)

JUDGE_CONTEXT_CUES = 8
CONFIDENCE = ("high", "medium", "low")
REFERENCE_V3_SCHEMA = "hy30-flow-v3-reference-v1"


@dataclass(frozen=True)
class Cue:
    id: str
    text: str
    start: float | None = None
    end: float | None = None


@dataclass(frozen=True)
class Scene:
    scene_id: str
    cues: tuple[Cue, ...]
    work_id: str | None = None
    category: str | None = None

    @property
    def ids(self) -> list[str]:
        return [cue.id for cue in self.cues]


@dataclass(frozen=True)
class WindowMeta:
    window_id: str
    scene_id: str
    split: str
    work_id: str
    work: str
    category: str
    selection_type: str
    risk_tags: tuple[str, ...]
    scored_ids: tuple[str, ...]


def _window_meta(row: dict[str, Any], scored: list[str]) -> WindowMeta:
    return WindowMeta(row["window_id"], row["scene_id"], row["split"], row["work_id"], row["work"],
                      row["category"], row["selection_type"], tuple(row.get("risk_tags", [])), tuple(scored))


def load_screening(source_dir: Path = SOURCE_DIR) -> tuple[list[Scene], list[WindowMeta], dict[str, str]]:
    """34 screening scenes in source order, 96 windows with split/work/category/risk."""
    scenes_path = source_dir / "model-input/scenes.jsonl"
    windows_path = source_dir / "model-input/windows.jsonl"
    manifest_path = source_dir / "source-manifest.json"
    manifest = {row["window_id"]: row for row in read_json(manifest_path)["windows"]}
    windows = []
    for row in read_jsonl(windows_path):
        meta = manifest.get(row["id"])
        if meta is None:
            raise ValueError(f"Window missing from source manifest: {row['id']}")
        windows.append(_window_meta(meta, row["translate_ids"]))
    by_scene = {window.scene_id: window for window in windows}
    scenes = []
    for row in read_jsonl(scenes_path):
        if row["translate_ids"] != [cue["id"] for cue in row["context"]]:
            raise ValueError(f"Scene must translate all cues in order: {row['scene_id']}")
        meta = by_scene.get(row["scene_id"])
        scenes.append(Scene(row["scene_id"], tuple(Cue(c["id"], c["text"], c.get("start"), c.get("end"))
                                                   for c in row["context"]),
                            meta.work_id if meta else None, meta.category if meta else None))
    _check_windows_in_scenes(scenes, windows)
    hashes = {str(path.name): sha256_file(path) for path in (scenes_path, windows_path, manifest_path)}
    return scenes, windows, hashes


def load_confirmation(reference_dir: Path = REFERENCE_V1_DIR) -> tuple[list[Scene], list[WindowMeta], dict[str, str]]:
    """Each confirmation scene is the shared visible context of its windows (20 scenes, 48 windows).

    Only model-input text and window metadata are read; no reference text is returned.
    """
    inputs_path = reference_dir / "model-input/confirmation.jsonl"
    manifest_path = reference_dir / "source-manifest-confirmation.json"
    manifest = {row["window_id"]: row for row in read_json(manifest_path)["windows"]}
    scenes: dict[str, Scene] = {}
    windows = []
    for row in read_jsonl(inputs_path):
        meta = manifest[row["id"]]
        windows.append(_window_meta(meta, row["translate_ids"]))
        cues = tuple(Cue(c["id"], c["text"]) for c in row["context"])
        previous = scenes.get(meta["scene_id"])
        if previous is not None and previous.cues != cues:
            raise ValueError(f"Confirmation windows of one scene disagree on context: {meta['scene_id']}")
        scenes[meta["scene_id"]] = Scene(meta["scene_id"], cues, meta["work_id"], meta["category"])
    _check_windows_in_scenes(list(scenes.values()), windows)
    hashes = {path.name: sha256_file(path) for path in (inputs_path, manifest_path)}
    return list(scenes.values()), windows, hashes


def _check_windows_in_scenes(scenes: list[Scene], windows: list[WindowMeta]) -> None:
    ids = {scene.scene_id: set(scene.ids) for scene in scenes}
    for window in windows:
        if window.scene_id not in ids or not set(window.scored_ids) <= ids[window.scene_id]:
            raise ValueError(f"Window scored IDs are not inside its scene: {window.window_id}")


# --- reference-v3 -----------------------------------------------------------------

def freeze_reference(root: Path, reference_dir: Path = REFERENCE_V1_DIR, *, force: bool = False) -> dict[str, Any]:
    """Merge Opus review shards with reference-v1 metadata; every scored unit is required."""
    shard_paths = sorted((root / "reference-review").glob("shard-*.jsonl"))
    if not shard_paths:
        raise FileNotFoundError(f"No review shards under {root / 'reference-review'}")
    reviews: dict[tuple[str, str], dict[str, Any]] = {}
    for path in shard_paths:
        for row in read_jsonl(path):
            key = (row["window_id"], row["unit_id"])
            if key in reviews:
                raise ValueError(f"Duplicate review row: {key}")
            if row.get("confidence") not in CONFIDENCE:
                raise ValueError(f"Invalid confidence for {key}: {row.get('confidence')!r}")
            if not isinstance(row.get("zh_v3"), str) or not row["zh_v3"].strip():
                raise ValueError(f"Empty zh_v3 for {key}")
            reviews[key] = row
    v1_path = reference_dir / "reference/windows.jsonl"
    output_rows = []
    missing = []
    used = set()
    for window in read_jsonl(v1_path):
        units = window["units"]
        positions = [index for index, unit in enumerate(units) if unit.get("score")]
        if [units[index]["id"] for index in positions] != window["scored_ids"]:
            raise ValueError(f"reference-v1 score flags differ from scored_ids: {window['window_id']}")
        scored = []
        for index in positions:
            unit = units[index]
            key = (window["window_id"], unit["id"])
            review = reviews.get(key)
            if review is None:
                missing.append(key)
                continue
            if review["ja"] != unit["ja"] or review["zh_v1"] != unit["zh"] or review["split"] != window["split"]:
                raise ValueError(f"Review row differs from reference-v1 source/zh/split: {key}")
            used.add(key)
            scored.append({"id": unit["id"], "ja": unit["ja"], "zh": review["zh_v3"], "zh_v1": unit["zh"],
                           "original_zh": unit["original_zh"], "changed": bool(review["changed"]),
                           "change_type": review.get("change_type"), "confidence": review["confidence"],
                           "confidence_reason_zh": review.get("confidence_reason_zh"),
                           "ambiguity_zh": review.get("ambiguity_zh") or None,
                           "start": unit.get("start"), "end": unit.get("end")})
        low = max(0, positions[0] - JUDGE_CONTEXT_CUES)
        high = min(len(units), positions[-1] + JUDGE_CONTEXT_CUES + 1)
        context = [{"id": unit["id"], "ja": unit["ja"], "scored": bool(unit.get("score"))} for unit in units[low:high]]
        output_rows.append({key: window[key] for key in ("window_id", "scene_id", "work_id", "work", "category",
                                                         "split", "selection_type", "risk_tags", "scored_ids")}
                           | {"schema": REFERENCE_V3_SCHEMA, "units": scored, "context": context})
    if missing:
        raise ValueError(f"{len(missing)} scored units lack a review row, e.g. {missing[:3]}")
    extra = set(reviews) - used
    if extra:
        raise ValueError(f"{len(extra)} review rows match no reference-v1 scored unit, e.g. {sorted(extra)[:3]}")
    target = root / "reference-v3"
    windows_path = target / "windows.jsonl"
    freeze_path = target / "freeze.json"
    if freeze_path.exists() and not force:
        previous = read_json(freeze_path)
        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output_rows)
        if previous["output"]["sha256"] == sha256_bytes(text.encode("utf-8")):
            return previous | {"already_frozen": True}
        raise ValueError("reference-v3 is already frozen with different content; use --force only for a deliberate re-freeze")
    atomic_write_jsonl(windows_path, output_rows)
    units = [unit for row in output_rows for unit in row["units"]]
    summary = {
        "schema": REFERENCE_V3_SCHEMA, "frozen_at_utc": utc_now(),
        "inputs": {"shards": [{"path": str(path), "sha256": sha256_file(path)} for path in shard_paths],
                   "reference_v1": {"path": str(v1_path), "sha256": sha256_file(v1_path)}},
        "output": {"path": str(windows_path), "sha256": sha256_file(windows_path)},
        "counts": {"windows": len(output_rows), "units": len(units),
                   "windows_by_split": dict(Counter(row["split"] for row in output_rows)),
                   "changed": sum(unit["changed"] for unit in units),
                   "confidence": dict(Counter(unit["confidence"] for unit in units)),
                   "with_ambiguity": sum(bool(unit["ambiguity_zh"]) for unit in units)},
        "judge_context_cues_each_side": JUDGE_CONTEXT_CUES,
    }
    atomic_write_json(freeze_path, summary)
    return summary


@dataclass(frozen=True)
class ReferenceWindow:
    meta: WindowMeta
    units: tuple[dict[str, Any], ...]
    context: tuple[dict[str, Any], ...]


def load_reference_v3(root: Path) -> dict[str, ReferenceWindow]:
    freeze = read_json(root / "reference-v3/freeze.json")
    path = root / "reference-v3/windows.jsonl"
    if sha256_file(path) != freeze["output"]["sha256"]:
        raise ValueError("reference-v3/windows.jsonl differs from its freeze record")
    result = {}
    for row in read_jsonl(path):
        result[row["window_id"]] = ReferenceWindow(_window_meta(row, row["scored_ids"]),
                                                   tuple(row["units"]), tuple(row["context"]))
    return result


def windows_for_split(windows: list[WindowMeta], split: str) -> list[WindowMeta]:
    if split == "screening":
        return [w for w in windows if w.split in ("screen-a", "screen-b")]
    return [w for w in windows if w.split == split]
