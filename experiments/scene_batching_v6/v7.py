"""v7: full-set judging and paired comparison of the gap-aware variants (dp6, mark5, dp6-grp).

Same layout as q2 under ``<v7 root>`` (``.local/gap-aware-batching-v7``); generation, the control
copy and judging reuse q2 with that root. The subset file of a variant lists the affected cues (batch
targets/neighbours/pause marks differ from the control) but every window of the covered scenes, so
the candidate and the b10-joint control copy are judged on the full set with one packet layout; the
control copy of a seed is judged once and serves all variants.

``compare`` pairs a variant with the control copy (or with another variant, ``against``) on every
judged cue: full-set Δ per metric by category, the affected and unaffected parts (unaffected cues
with identical translations give the judge noise floor), safety, delivery, cost and the batch-size
distribution. ``pooled`` averages the paired differences over independent seed sets.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import statistics
from typing import Any

from experiments.translation_v3.common import atomic_write_json, read_json
from experiments.translation_v3.generate import load_run_translations
from experiments.translation_v4 import evaluate as E
from experiments.translation_v4 import stats4 as S4
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT

from . import q2
from .common import V7_ROOT
from .stats6 import METRICS, run_metrics

NONINFERIORITY_MARGIN = 0.05  # v4 margin, per category, on the CI90 upper bound
CRITICAL_MARGIN = 0.002       # v6: critical count per cue must not rise above this (point estimate)


def subset(variant: str, seed: int, *, root: Path = V7_ROOT) -> dict[str, Any]:
    return q2.build_subset(variant, seed, root=root, full=True)


def _arm(root: Path, name: str, seed: int, windows: dict) -> dict[str, Any]:
    path = q2.run_dir(root, name, seed)
    metrics = run_metrics(path, windows)
    safety = S4.run_cues(path, windows)["values"] if not metrics["missing"] else {}
    return {"path": path, "metrics": metrics, "safety": safety}


def _delta_block(diffs: dict[str, float], layout: S4.Layout, reps: int) -> dict[str, Any]:
    return {"delta": S4.aggregate(diffs, layout), "bootstrap": S4.bootstrap(diffs, layout, reps=reps)}


def compare(variant: str, seeds: list[int], *, against: str = q2.CONTROL_COPY, against_seeds: list[int] | None = None,
            root: Path = V7_ROOT, v4_root: Path = V4_ROOT, label: str = "") -> dict[str, Any]:
    against_seeds = against_seeds or seeds
    all_windows = E.reference_for(v4_root, q2.SET)
    cand: dict[str, dict[str, float]] = {}
    ctrl: dict[str, dict[str, float]] = {}
    safety: dict[str, dict[str, dict[str, float]]] = {"candidate": {}, "against": {}}
    affected: set[str] = set()
    identical: set[str] = set()
    scenes: set[str] = set()
    missing: dict[str, int] = {}
    for seed, aseed in zip(seeds, against_seeds):
        run = read_json(q2.run_dir(root, variant, seed) / "run.json")
        scenes |= set(run["scene_ids"])
        windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in set(run["scene_ids"])}
        a, b = _arm(root, variant, seed, windows), _arm(root, against, aseed, windows)
        for arm in (a, b):
            if arm["metrics"]["missing"]:
                missing[arm["path"].name] = len(arm["metrics"]["missing"])
        cand.update(a["metrics"]["values"])
        ctrl.update(b["metrics"]["values"])
        safety["candidate"].update(a["safety"])
        safety["against"].update(b["safety"])
        cmap, amap = q2._batch_map(a["path"]), q2._batch_map(b["path"])
        affected |= set(q2.affected_cues(cmap, amap))
        ctr, _ = load_run_translations(a["path"])
        atr, _ = load_run_translations(b["path"])
        identical |= {k for k in ctr if ctr.get(k) == atr.get(k)}
    if missing:
        return {"state": "insufficient", "missing_windows": missing}
    windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in scenes}
    keys = sorted({u["id"] for w in windows.values() for u in w.units} & set(cand) & set(ctrl))
    full_layout = S4.Layout(windows, set(keys))
    report: dict[str, Any] = {"variant": variant, "against": against, "seeds": seeds, "against_seeds": against_seeds,
                              "cues": len(keys), "affected_cues": len(affected & set(keys)),
                              "affected_share": len(affected & set(keys)) / len(keys), "full": {}, "parts": {}}
    for metric in METRICS:
        diffs = {k: cand[k][metric] - ctrl[k][metric] for k in keys}
        report["full"][metric] = {"candidate": S4.aggregate({k: cand[k][metric] for k in keys}, full_layout),
                                  "against": S4.aggregate({k: ctrl[k][metric] for k in keys}, full_layout),
                                  **_delta_block(diffs, full_layout, 10000)}
    parts = {"affected": [k for k in keys if k in affected],
             "affected_changed_translation": [k for k in keys if k in affected and k not in identical],
             "unaffected_identical_translation": [k for k in keys if k not in affected and k in identical],
             "unaffected_changed_translation": [k for k in keys if k not in affected and k not in identical]}
    for name, part in parts.items():
        if not part:
            report["parts"][name] = {"cues": 0}
            continue
        layout = S4.Layout(windows, set(part))
        report["parts"][name] = {"cues": len(part), **_delta_block(
            {k: cand[k]["accuracy"] - ctrl[k]["accuracy"] for k in part}, layout, 2000)}
    report["safety"] = {m: _delta_block({k: safety["candidate"][k][m] - safety["against"][k][m] for k in keys},
                                        full_layout, 2000) for m in ("critical", "major_plus")}
    if against == q2.CONTROL_COPY:  # judge noise: control re-judge minus the original v4 judgement
        orig: dict[str, dict[str, float]] = {}
        for aseed in against_seeds:
            run_scenes = set(read_json(q2.run_dir(root, against, aseed) / "run.json")["scene_ids"])
            orig.update(run_metrics(q2.run_dir(v4_root, q2.CONTROL, aseed),
                                    {k: w for k, w in windows.items() if w.meta.scene_id in run_scenes})["values"])
        rejudge = {k: ctrl[k]["accuracy"] - orig[k]["accuracy"] for k in keys if k in orig}
        report["control_rejudge_minus_original"] = _delta_block(rejudge, full_layout, 2000)
    report["decision"] = decision(report)
    report["delivery"] = {f"{n}__s{s}": q2._failed(q2.run_dir(root, n, s))
                          for n, ss in ((variant, seeds), (against, against_seeds)) for s in ss}
    report["cost"] = {f"{n}__s{s}": cost(q2.run_dir(root, n, s) if n == variant else _original(root, v4_root, n, s))
                      for n, ss in ((variant, seeds), (against, against_seeds)) for s in ss}
    name = f"v7-{variant}-vs-{against}{('-' + label) if label else ''}.json"
    atomic_write_json(root / "summaries" / name, report)
    return report


def _original(root: Path, v4_root: Path, name: str, seed: int) -> Path:
    """Cost of the control comes from the original v4 run (the copy has no runtime directory)."""
    return q2.run_dir(v4_root, q2.CONTROL, seed) if name == q2.CONTROL_COPY else q2.run_dir(root, name, seed)


def decision(report: dict[str, Any]) -> dict[str, Any]:
    """Non-inferiority per category (CI90 upper bound < margin), critical not up, significance flags."""
    acc = report["full"]["accuracy"]
    out: dict[str, Any] = {}
    for category in ("anime_series", "animation_movie", "overall"):
        ci = acc["bootstrap"][category]["ci90"]
        out[category] = {"delta": acc["delta"][category], "ci90": ci,
                         "noninferior": ci[1] < NONINFERIORITY_MARGIN,
                         "significantly_worse": ci[0] > 0, "significantly_better": ci[1] < 0}
    crit = report["safety"]["critical"]["delta"]["overall"]
    out["critical_not_up"] = crit is not None and crit <= CRITICAL_MARGIN
    out["noninferior_both"] = out["anime_series"]["noninferior"] and out["animation_movie"]["noninferior"]
    return out


def cost(path: Path) -> dict[str, Any]:
    base = q2._cost(path)
    rows = [read_json(p) for p in sorted((path / "scenes").glob("*.json"))]
    sizes = [len(b["target_ids"]) for r in rows for b in r["batches"]]
    visible = [len(b["before_ids"]) + len(b["target_ids"]) + len(b["after_ids"]) for r in rows for b in r["batches"]]
    base["target_size_histogram"] = dict(sorted(Counter(sizes).items()))
    base["visible_histogram"] = dict(sorted(Counter(visible).items()))
    base["pause_marks"] = sum(len(b.get("pauses", ())) for r in rows for b in r["batches"])
    base["input_tokens"] = sum(r["totals"].get("input_tokens", 0) for r in rows)
    return base


def pooled(variant: str, seed_sets: list[list[int]], *, against: str = q2.CONTROL_COPY,
           root: Path = V7_ROOT, v4_root: Path = V4_ROOT, label: str = "pooled") -> dict[str, Any]:
    """Mean of the per-cue paired differences over independent seed sets (each set pairs the variant
    and ``against`` on the same seeds)."""
    all_windows = E.reference_for(v4_root, q2.SET)
    per_set: list[dict[str, dict[str, float]]] = []
    scenes: set[str] = set()
    for seeds in seed_sets:
        diffs: dict[str, dict[str, float]] = {}
        for seed in seeds:
            run_scenes = set(read_json(q2.run_dir(root, variant, seed) / "run.json")["scene_ids"])
            scenes |= run_scenes
            windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in run_scenes}
            a = run_metrics(q2.run_dir(root, variant, seed), windows)
            b = run_metrics(q2.run_dir(root, against, seed), windows)
            if a["missing"] or b["missing"]:
                return {"state": "insufficient", "seed": seed}
            for k in a["values"].keys() & b["values"].keys():
                diffs[k] = {m: a["values"][k][m] - b["values"][k][m] for m in METRICS}
        per_set.append(diffs)
    keys = sorted(set.intersection(*(set(d) for d in per_set)))
    windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in scenes}
    layout = S4.Layout(windows, set(keys))
    report: dict[str, Any] = {"variant": variant, "against": against, "seed_sets": seed_sets, "cues": len(keys),
                              "full": {}}
    for metric in METRICS:
        mean = {k: statistics.fmean(d[k][metric] for d in per_set) for k in keys}
        report["full"][metric] = _delta_block(mean, layout, 10000)
    atomic_write_json(root / "summaries" / f"v7-{variant}-vs-{against}-{label}.json", report)
    return report
