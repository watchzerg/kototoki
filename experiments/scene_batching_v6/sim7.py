"""v7 offline simulation: batch-size and gap-crossing distributions of the v7 variants (no GPU).

Scenes are the v4 dev set (research timing, all seed blocks) and the product ``ja.srt`` files of
quality_v5 step 01 (own VAD/ASR timing, one scene per film, like ``translate-srt``). Recipes come
from ``<v7 root>/recipes`` (or builtins). Writes ``<v7 root>/sim/sim.json``.
"""

from __future__ import annotations

from pathlib import Path
import statistics
from typing import Any, Iterable

from experiments.translation_v3.batching import Batch, build_batches, silence
from experiments.translation_v3.common import REPO, atomic_write_json
from experiments.translation_v3.data import Cue, Scene
from experiments.translation_v3.recipes import Recipe, load_recipe
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT
from experiments.translation_v4.reference import load_scenes

from .common import V7_ROOT

PRODUCT_SRT = REPO / ".local/quality-exploration-v5/01/out-w0"
RECIPES = ("b10-joint", "dp6", "mark5", "dp6-grp")
CROSS = (2.0, 5.0, 10.0)


def dev_scenes(v4_root: Path = V4_ROOT) -> list[Scene]:
    return [Scene(r["scene_id"], tuple(Cue(c["id"], c["text"], c.get("start"), c.get("end")) for c in r["cues"]),
                  r["work_id"], r["category"]) for r in load_scenes(v4_root, "dev")]


def product_scenes(folder: Path = PRODUCT_SRT) -> list[Scene]:
    from experiments.translation_flow import srt
    scenes = []
    for path in sorted(folder.glob("*.ja.srt")):
        doc = srt.read_srt(path)
        scenes.append(Scene(f"srt-{doc.source_sha256[:12]}",
                            tuple(Cue(c.id, c.text, c.start_ms / 1000, c.end_ms / 1000) for c in doc.cues),
                            category="animation_movie"))
    return scenes


def batch_key(batch: Batch) -> tuple:
    return batch.target_ids, batch.before_ids, batch.after_ids, batch.pauses


def max_inner_gap(scene: Scene, batch: Batch) -> float:
    gaps = [silence(scene, i) for i in range(batch.start, batch.stop - 1)]
    return max((g for g in gaps if g is not None), default=0.0)


def neighbour_gap(scene: Scene, batch: Batch) -> float:
    """Largest silence between a visible neighbour and the targets (0 without neighbours)."""
    gaps = []
    if batch.before_ids:
        gaps.append(silence(scene, batch.start - 1))
    if batch.after_ids:
        gaps.append(silence(scene, batch.stop - 1))
    return max((g for g in gaps if g is not None), default=0.0)


def gap_distribution(scenes: Iterable[Scene]) -> dict[str, Any]:
    gaps = [g for s in scenes for i in range(len(s.cues) - 1) if (g := silence(s, i)) is not None]
    if not gaps:
        return {"gaps": 0}
    q = statistics.quantiles(gaps, n=100)
    return {"gaps": len(gaps), "median": statistics.median(gaps), "p75": q[74], "p90": q[89], "p99": q[98],
            **{f"share_ge_{t:g}s": sum(g >= t for g in gaps) / len(gaps) for t in (1.0, 2.0, 5.0, 10.0)}}


def summarize(scenes: list[Scene], recipe: Recipe, control: Recipe) -> dict[str, Any]:
    rows, affected, cues = [], 0, 0
    for scene in scenes:
        own = build_batches(scene, recipe)
        ctl = {k: batch_key(b) for b in build_batches(scene, control) for k in b.target_ids}
        for b in own:
            rows.append((b, max_inner_gap(scene, b), neighbour_gap(scene, b)))
            if batch_key(b) != ctl[b.target_ids[0]] or any(batch_key(b) != ctl[k] for k in b.target_ids):
                affected += len(b.target_ids)
        cues += len(scene.cues)
    sizes = [len(b.target_ids) for b, _, _ in rows]
    visible = [len(b.before_ids) + len(b.target_ids) + len(b.after_ids) for b, _, _ in rows]
    n = len(rows)
    return {"cues": cues, "requests": n, "mean_size": cues / n,
            "share_lt6": sum(s < 6 for s in sizes) / n, "share_lt8": sum(s < 8 for s in sizes) / n,
            "share_eq12": sum(s == 12 for s in sizes) / n,
            **{f"cross_ge_{t:g}s": sum(g >= t for _, g, _ in rows) / n for t in CROSS},
            "neighbour_cross_ge_5s": sum(g >= 5.0 for _, _, g in rows) / n,
            "visible_max": max(visible), "visible_mean": statistics.fmean(visible),
            "batches_with_pause_marks": sum(bool(b.pauses) for b, _, _ in rows) / n,
            "pause_marks": sum(len(b.pauses) for b, _, _ in rows),
            "affected_cue_share": affected / cues,
            "size_histogram": {str(k): sizes.count(k) for k in sorted(set(sizes))}}


def simulate(root: Path = V7_ROOT, recipes: Iterable[str] = RECIPES, v4_root: Path = V4_ROOT,
             product_folder: Path = PRODUCT_SRT, write: bool = True) -> dict[str, Any]:
    control = load_recipe("b10-joint", root)
    dev = dev_scenes(v4_root)
    sets = {"dev": dev,
            "dev_series": [s for s in dev if s.category == "anime_series"],
            "dev_movie": [s for s in dev if s.category == "animation_movie"],
            "product": product_scenes(product_folder)}
    report: dict[str, Any] = {"gaps": {name: gap_distribution(scenes) for name, scenes in sets.items()}, "recipes": {}}
    for name in recipes:
        recipe = load_recipe(name, root)
        report["recipes"][name] = {"recipe_hash": recipe.recipe_hash,
                                   **{s: summarize(scenes, recipe, control) for s, scenes in sets.items() if scenes}}
        base = report["recipes"]["b10-joint"] if "b10-joint" in report["recipes"] else None
        if base:
            for s in sets:
                if s in report["recipes"][name]:
                    report["recipes"][name][s]["requests_vs_b10"] = (report["recipes"][name][s]["requests"]
                                                                     / base[s]["requests"])
    if write:
        atomic_write_json(root / "sim" / "sim.json", report)
    return report
