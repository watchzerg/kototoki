"""v11 ticket 03 (offline): how often the cross-segment truncation (``wide_context.silence_gap``) changes a pack's
read-only neighbours on the product timing (HF II / III product w0 ``ja.srt``) and on dev, for G = 5, 10, 20 s.

Only times and counts are read, never text: per gap the share of packs whose neighbours differ from ``qwen-wide``,
the mean visible neighbours before / after, the share of target cues in affected packs, and (product, G = 10 s) a
list of truncation points with the silence at the cut and the cue density on both sides.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.batching import build_batches, silence
from experiments.translation_v3.common import atomic_write_json
from experiments.translation_v3.data import Cue, Scene
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT
from experiments.translation_v4.gen import set_scenes

from . import q2, v9
from .asr10 import FILMS
from .v11 import V11_ROOT

GAPS = (5.0, 10.0, 20.0)
POINTS = 20
DENSITY_WINDOW = 30.0  # seconds on each side of a truncation point


def product_scenes() -> list[Scene]:
    from experiments.translation_flow import srt
    out = []
    for film, paths in FILMS.items():
        document = srt.read_srt(paths["ja"])
        out.append(Scene(film, tuple(Cue(c.id, c.text, c.start_ms / 1000, c.end_ms / 1000) for c in document.cues),
                         work_id=film, category="animation_movie"))
    return out


def dev_scenes() -> list[Scene]:
    return [s for seed in v9.MAIN_SEEDS for s in set_scenes(V4_ROOT, q2.SET, seed)[0]]


def seg_recipe(gap: float) -> R.Recipe:
    return R.compose(f"seg{gap:g}", "qwen-wide", wide_context={"max_visible": 35, "silence_gap": gap})


def _density(scene: Scene, time: float) -> tuple[int, int]:
    """Cues starting within DENSITY_WINDOW before / after ``time``."""
    before = sum(1 for c in scene.cues if c.start is not None and time - DENSITY_WINDOW <= c.start < time)
    after = sum(1 for c in scene.cues if c.start is not None and time <= c.start < time + DENSITY_WINDOW)
    return before, after


def scene_stats(scene: Scene, gap: float, points: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    base, cut = build_batches(scene, R.BUILTIN["qwen-wide"]), build_batches(scene, seg_recipe(gap))
    assert [b.target_ids for b in base] == [c.target_ids for c in cut]
    row = Counter(packs=len(base), cues=len(scene.cues), affected_packs=0, affected_cues=0, affected_before=0,
                  affected_after=0)
    sums = Counter()
    for b, c in zip(base, cut):
        sums["before_base"] += len(b.before_ids)
        sums["after_base"] += len(b.after_ids)
        sums["before_cut"] += len(c.before_ids)
        sums["after_cut"] += len(c.after_ids)
        lost_before, lost_after = len(b.before_ids) - len(c.before_ids), len(b.after_ids) - len(c.after_ids)
        if lost_before or lost_after:
            row["affected_packs"] += 1
            row["affected_cues"] += len(c.target_ids)
            row["affected_before"] += bool(lost_before)
            row["affected_after"] += bool(lost_after)
        if points is not None:
            if lost_before:
                left = c.start - len(c.before_ids)
                time = scene.cues[left].start
                points.append({"scene": scene.scene_id, "pack": c.index, "side": "before", "cut_time_s": round(time, 1),
                               "silence_s": round(silence(scene, left - 1), 1), "neighbours_dropped": lost_before,
                               "neighbours_kept": len(c.before_ids), "targets": len(c.target_ids),
                               "cues_30s_before_after": _density(scene, time)})
            if lost_after:
                right = c.stop + len(c.after_ids)
                time = scene.cues[right].start
                points.append({"scene": scene.scene_id, "pack": c.index, "side": "after", "cut_time_s": round(time, 1),
                               "silence_s": round(silence(scene, right - 1), 1), "neighbours_dropped": lost_after,
                               "neighbours_kept": len(c.after_ids), "targets": len(c.target_ids),
                               "cues_30s_before_after": _density(scene, time)})
    return dict(row) | dict(sums)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = Counter()
    for r in rows:
        total.update(r)
    packs = total["packs"] or 1
    return {"packs": total["packs"], "cues": total["cues"], "affected_packs": total["affected_packs"],
            "affected_pack_share": total["affected_packs"] / packs,
            "affected_before": total["affected_before"], "affected_after": total["affected_after"],
            "affected_cue_share": total["affected_cues"] / (total["cues"] or 1),
            "mean_before": [total["before_base"] / packs, total["before_cut"] / packs],
            "mean_after": [total["after_base"] / packs, total["after_cut"] / packs]}


def segment_stats(gaps: tuple[float, ...] = GAPS, *, out: Path = V11_ROOT / "A") -> dict[str, Any]:
    product, dev = product_scenes(), dev_scenes()
    report: dict[str, Any] = {"gaps": list(gaps), "product": {}, "dev": {}, "points": {}}
    for gap in gaps:
        points: list[dict[str, Any]] = []
        rows = {s.scene_id: scene_stats(s, gap, points) for s in product}
        report["product"][f"{gap:g}"] = _summary(list(rows.values())) | {"by_film": {k: _summary([v]) for k, v in rows.items()}}
        dev_rows = [(s.category, scene_stats(s, gap)) for s in dev]
        report["dev"][f"{gap:g}"] = _summary([r for _, r in dev_rows]) | {
            "by_category": {c: _summary([r for cat, r in dev_rows if cat == c]) for c in sorted({c for c, _ in dev_rows})}}
        if points:
            step = max(1, len(points) // POINTS)
            report["points"][f"{gap:g}"] = {"total": len(points), "listed": sorted(points, key=lambda p: (p["scene"], p["cut_time_s"]))[::step][:POINTS],
                                            "silence_histogram": dict(sorted(Counter(int(p["silence_s"] // 10) * 10 for p in points).items()))}
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "03-segment-stats.json", report)
    return report
