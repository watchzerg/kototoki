"""v4 statistics: every cue scored, paired by cue, work-equal, series/movie 50:50, scene bootstrap.

Unit of resampling: the tiled 5-cue window, stratified by work; works are fixed, so the inference is
about the content of these works. R1 showed the v3 work-cluster bootstrap (3-6 clusters per category)
understates the SE about 2.5x and that the cue ICC of the delta is ~0. Half-A subsets have 1-2 scenes
per work, so a scene bootstrap degenerates there; the scene-unit bootstrap is kept to measure the
scene-clustering design effect on the calibration pairs (decision-policy-v4 records it).

Per cue and run: accuracy penalty (minor 1 / major 5 / critical 10, accuracy categories), fluency
penalty, major+ indicator, critical count, any-accuracy-error indicator. A cue of a scene that failed
terminally counts as accuracy 10 / major+ / critical (undelivered), as in v3. A recipe's value for a
cue is the mean over its runs that contain the cue (dev: one seed block per scene; confirm: 3 seeds).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import random
import statistics
from typing import Any

from experiments.translation_v3 import stats as S3
from experiments.translation_v3.common import read_json
from experiments.translation_v3.data import ReferenceWindow
from experiments.translation_v3.generate import load_run_translations, scene_state
from experiments.translation_v3.judge import ACCURACY, FLUENCY, load_judgements

from .common import POLICY_FILE
from .reference import risk_cue

CATEGORIES = S3.CATEGORIES
METRICS = ("accuracy", "fluency", "major_plus", "critical", "any_error")
BOOTSTRAP_SEED = "v4-bootstrap-20261011"
# Arms that may be compared before the policy is frozen: the control itself (replicate seeds) and the
# old v3 baseline c0 (a bridge, never a v4 candidate).
CALIBRATION_ARMS = ("b10-joint", "c0")
REQUIRED_POLICY = ("noninferiority_margin", "critical_margin", "risk_major_margin", "alpha")


def cue_values(cue: dict[str, Any]) -> dict[str, float]:
    s = S3.cue_scores(cue)
    return {"accuracy": s["accuracy"], "fluency": s["fluency"], "major_plus": s["major_plus"],
            "critical": s["critical"], "any_error": float(any(e["category"] in ACCURACY for e in cue["errors"]))}


UNDELIVERED = {"accuracy": 10.0, "fluency": 0.0, "major_plus": 1.0, "critical": 1.0, "any_error": 1.0}


def run_cues(run_dir: Path, windows: dict[str, ReferenceWindow], replicate: int = 0) -> dict[str, Any]:
    """cue_id -> metric dict for every expected cue of this run's scenes in ``windows``; plus missing."""
    run = read_json(run_dir / "run.json")
    scenes = set(run["scene_ids"])
    translations, _ = load_run_translations(run_dir)
    judgements, surfaces = load_judgements(run_dir, replicate)
    values, missing, undelivered, categories = {}, [], [], {}
    for key, window in windows.items():
        if window.meta.scene_id not in scenes:
            continue
        ids = [u["id"] for u in window.units]
        if all(i in translations for i in ids):
            judged = judgements.get(key)
            if judged is None:
                missing.append(key)
                continue
            for i in ids:
                values[i] = cue_values(judged[i])
                categories[i] = [(e["category"], e["severity"]) for e in judged[i]["errors"]]
        elif scene_state(run_dir, window.meta.scene_id) == "failed":
            for i in ids:
                values[i] = dict(UNDELIVERED)
            undelivered.append(key)
        else:
            missing.append(key)
    return {"values": values, "missing": missing, "undelivered": undelivered, "surfaces": surfaces,
            "errors": categories, "failed_scenes": sorted(s for s in scenes if scene_state(run_dir, s) == "failed")}


def recipe_cues(run_dirs: list[Path], windows: dict[str, ReferenceWindow], replicate: int = 0) -> dict[str, Any]:
    per: dict[str, list[dict[str, float]]] = defaultdict(list)
    missing, surfaces, failed, errors = {}, set(), [], defaultdict(list)
    for run_dir in run_dirs:
        result = run_cues(run_dir, windows, replicate)
        if result["missing"]:
            missing[run_dir.name] = result["missing"]
        surfaces |= result["surfaces"]
        failed += [(run_dir.name, s) for s in result["failed_scenes"]]
        for cue, value in result["values"].items():
            per[cue].append(value)
        for cue, errs in result["errors"].items():
            errors[cue] += errs
    values = {cue: {m: statistics.fmean(v[m] for v in rows) for m in METRICS} for cue, rows in per.items()}
    return {"values": values, "runs_per_cue": {c: len(r) for c, r in per.items()}, "missing": missing,
            "surfaces": surfaces, "failed_scenes": failed, "errors": dict(errors)}


# --- aggregation and bootstrap ----------------------------------------------------------------

class Layout:
    """Scenes (and tiled windows) grouped by work and category, with cue lists (for fast resampling)."""

    def __init__(self, windows: dict[str, ReferenceWindow], cues: set[str]):
        self.scene_cues: dict[str, list[str]] = defaultdict(list)
        self.window_cues: dict[str, list[str]] = {}
        self.work_of: dict[str, str] = {}
        self.category_of: dict[str, str] = {}
        self.work_windows: dict[str, list[str]] = defaultdict(list)
        for key, window in sorted(windows.items(), key=lambda kw: kw[1].meta.window_id):
            ids = [u["id"] for u in window.units if u["id"] in cues]
            self.scene_cues[window.meta.scene_id] += ids
            if ids:
                self.window_cues[key] = ids
                self.work_windows[window.meta.work_id].append(key)
            self.work_of[window.meta.scene_id] = window.meta.work_id
            self.category_of[window.meta.work_id] = window.meta.category
        self.works: dict[str, list[str]] = defaultdict(list)
        for scene in sorted(self.scene_cues):
            if self.scene_cues[scene]:
                self.works[self.work_of[scene]].append(scene)


def aggregate_sums(work_sums: dict[str, tuple[float, int]], category_of: dict[str, str]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for category in CATEGORIES:
        means = [s / n for w, (s, n) in sorted(work_sums.items()) if category_of[w] == category and n]
        result[category] = statistics.fmean(means) if means else None
    result["overall"] = (statistics.fmean([result[c] for c in CATEGORIES])
                         if all(result[c] is not None for c in CATEGORIES) else None)
    return result


def aggregate(values: dict[str, float], layout: Layout, works: set[str] | None = None) -> dict[str, float | None]:
    sums = {}
    for work, scenes in layout.works.items():
        if works is not None and work not in works:
            continue
        keys = [c for s in scenes for c in layout.scene_cues[s] if c in values]
        sums[work] = (sum(values[c] for c in keys), len(keys))
    return aggregate_sums(sums, layout.category_of)


def bootstrap(values: dict[str, float], layout: Layout, *, reps: int = 10000, seed: str = BOOTSTRAP_SEED,
              unit: str = "window") -> dict[str, Any]:
    """Stratified by work (works fixed). unit "window": tiled 5-cue windows (default; R1: cue ICC of the
    delta ~ 0, and half-A subsets have 1-2 scenes per work, where a scene bootstrap degenerates);
    unit "scene": whole scenes (used to measure the design effect of scene clustering)."""
    groups = layout.scene_cues if unit == "scene" else layout.window_cues
    members = layout.works if unit == "scene" else layout.work_windows
    if unit not in ("scene", "window"):
        raise ValueError(unit)
    unit_sums = {g: (sum(values[c] for c in cues if c in values), sum(c in values for c in cues))
                 for g, cues in groups.items()}
    works = {w: [unit_sums[g] for g in gs] for w, gs in sorted(members.items())}
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {k: [] for k in (*CATEGORIES, "overall")}
    for _ in range(reps):
        sums = {}
        for work, rows in works.items():
            drawn = [rows[rng.randrange(len(rows))] for _ in rows]
            sums[work] = (sum(d[0] for d in drawn), sum(d[1] for d in drawn))
        agg = aggregate_sums(sums, layout.category_of)
        for key in samples:
            if agg[key] is not None:
                samples[key].append(agg[key])

    def summary(xs: list[float]) -> dict[str, Any] | None:
        if not xs:
            return None
        xs = sorted(xs)
        q = lambda p: xs[min(len(xs) - 1, int(p * (len(xs) - 1)))]
        return {"se": statistics.stdev(xs), "ci95": [q(0.025), q(0.975)], "ci90": [q(0.05), q(0.95)],
                "p_ge_0": sum(x >= 0 for x in xs) / len(xs), "p_le_0": sum(x <= 0 for x in xs) / len(xs)}
    return {"reps": reps, "seed": seed, "unit": f"{unit} within work", **{k: summary(v) for k, v in samples.items()}}


def holm(pvalues: dict[str, float], alpha: float) -> dict[str, dict[str, Any]]:
    return S3.holm(pvalues, alpha)


def load_policy(root: Path) -> dict[str, Any] | None:
    path = root / POLICY_FILE
    if not path.is_file():
        return None
    policy = read_json(path)
    for key in REQUIRED_POLICY:
        if not isinstance(policy.get(key), (int, float)) or policy[key] < 0:
            raise ValueError(f"{POLICY_FILE}: '{key}' must be a nonnegative number")
    return policy


# --- comparison ---------------------------------------------------------------------------------

def find_runs(root: Path, recipe: str, set_name: str, seeds: tuple[int, ...] | None = None) -> list[Path]:
    runs = sorted(p for p in (root / "runs").glob(f"{recipe}__s*__{set_name}") if (p / "run.json").is_file())
    if seeds is not None:
        runs = [p for p in runs if read_json(p / "run.json")["seed"] in seeds]
    return runs


def compare_cues(cand: dict[str, Any], ctrl: dict[str, Any], windows: dict[str, ReferenceWindow],
                 *, reps: int = 10000) -> dict[str, Any]:
    common = sorted(set(cand["values"]) & set(ctrl["values"]))
    layout = Layout(windows, set(common))
    ja = {u["id"]: u["ja"] for w in windows.values() for u in w.units}
    result: dict[str, Any] = {"cues": len(common), "scenes": sum(len(v) for v in layout.works.values()),
                              "works": {w: len(s) for w, s in sorted(layout.works.items())}}
    for metric in METRICS:
        delta = {c: cand["values"][c][metric] - ctrl["values"][c][metric] for c in common}
        row = {"candidate": aggregate({c: cand["values"][c][metric] for c in common}, layout),
               "control": aggregate({c: ctrl["values"][c][metric] for c in common}, layout),
               "delta": aggregate(delta, layout)}
        if metric in ("accuracy", "critical", "any_error", "major_plus"):
            row["bootstrap"] = bootstrap(delta, layout, reps=reps)
        if metric == "accuracy":
            row["bootstrap_scene_unit"] = bootstrap(delta, layout, reps=min(reps, 4000), unit="scene")["overall"]
            row["per_work"] = {w: {"category": layout.category_of[w],
                                   "delta": statistics.fmean(delta[c] for s in scenes for c in layout.scene_cues[s]),
                                   "cues": sum(len(layout.scene_cues[s]) for s in scenes)}
                               for w, scenes in sorted(layout.works.items())}
            row["leave_one_work_out"] = {w: aggregate(delta, layout, set(layout.works) - {w})["overall"]
                                         for w in sorted(layout.works)}
        result[metric] = row
    risk = {c for c in common if risk_cue(ja[c])}
    risk_layout = Layout(windows, risk)
    risk_delta = {c: cand["values"][c]["major_plus"] - ctrl["values"][c]["major_plus"] for c in risk}
    result["risk_major_plus"] = {"cues": len(risk), "delta": aggregate(risk_delta, risk_layout),
                                 "bootstrap": bootstrap(risk_delta, risk_layout, reps=reps)}
    result["error_categories"] = {side: _category_totals(data, common) for side, data in (("candidate", cand), ("control", ctrl))}
    return result


def _category_totals(data: dict[str, Any], cues: list[str]) -> dict[str, Any]:
    totals: dict[str, float] = defaultdict(float)
    for cue in cues:
        for category, severity in data["errors"].get(cue, []):
            totals[category] += S3.PENALTY[severity] / max(1, data["runs_per_cue"][cue])
    return {k: round(v, 2) for k, v in sorted(totals.items())}


def decide(row: dict[str, Any], policy: dict[str, Any], stage: str, delivery: dict[str, int]) -> tuple[str, dict[str, Any]]:
    acc = row["accuracy"]
    delta = acc["delta"]
    boot = acc["bootstrap"]["overall"]
    crit = row["critical"]
    crit_boot = crit["bootstrap"]["overall"]
    risk_upper = (row["risk_major_plus"]["bootstrap"]["overall"] or {}).get("ci90", [None, None])[1]
    gates = {
        "category_noninferior": all(delta[c] is not None and delta[c] <= policy["noninferiority_margin"] for c in CATEGORIES),
        "critical_not_increased": (crit["delta"]["overall"] <= policy["critical_margin"]
                                   and crit_boot["ci90"][0] <= 0),
        "risk_major_upper_within_margin": risk_upper is None or risk_upper <= policy["risk_major_margin"],
        "delivery_not_worse": delivery["candidate"] <= delivery["control"],
        "leave_one_work_out_negative": all(v is not None and v < 0 for v in acc["leave_one_work_out"].values()),
    }
    p = boot["p_ge_0"]
    alpha = policy.get("alpha_confirm", policy["alpha"]) if stage == "confirm" else policy["alpha"]
    gates["one_sided_p_below_alpha"] = p < alpha
    safety = all(gates[k] for k in ("category_noninferior", "critical_not_increased", "risk_major_upper_within_margin",
                                    "delivery_not_worse"))
    if stage == "A":
        return ("continue" if delta["overall"] is not None and delta["overall"] < 0 else "stop_at_A"), gates
    if stage == "confirm":
        return ("confirmed_before_holm" if gates["one_sided_p_below_alpha"] and safety else "not_confirmed"), gates
    if gates["one_sided_p_below_alpha"] and safety and gates["leave_one_work_out_negative"]:
        return "promising", gates
    if boot["p_le_0"] < policy["alpha"]:
        return "worse", gates
    return "no_detectable_effect" if safety else "no_detectable_effect_safety_flag", gates


def compare(root: Path, windows: dict[str, ReferenceWindow], candidate: str, control: str, set_name: str, *,
            halves: tuple[str, ...], seeds: tuple[int, ...] | None = None, control_seeds: tuple[int, ...] | None = None,
            reps: int = 10000, allow_without_policy: bool = False, calibration: bool = False) -> dict[str, Any]:
    policy = load_policy(root)
    if calibration and candidate not in CALIBRATION_ARMS:
        raise PermissionError(f"calibration comparisons are limited to {CALIBRATION_ARMS} (not v4 candidates)")
    if policy is None and not (allow_without_policy or calibration):
        raise PermissionError(f"{POLICY_FILE} is not frozen; candidate scores must not be viewed before calibration")
    splits = {f"{set_name}-{h}" for h in halves}
    windows = {k: w for k, w in windows.items() if w.meta.split in splits}
    cand_runs = find_runs(root, candidate, set_name, seeds)
    ctrl_runs = find_runs(root, control, set_name, control_seeds or seeds)
    info: dict[str, Any] = {"candidate": candidate, "control": control, "set": set_name, "halves": list(halves),
                            "runs": {"candidate": [p.name for p in cand_runs], "control": [p.name for p in ctrl_runs]}}
    cand_scenes = {s for p in cand_runs for s in read_json(p / "run.json")["scene_ids"]}
    ctrl_scenes = {s for p in ctrl_runs for s in read_json(p / "run.json")["scene_ids"]}
    expected = {w.meta.scene_id for w in windows.values()}
    if not expected <= cand_scenes or not expected <= ctrl_scenes:
        return info | {"decision": "insufficient", "reason": "runs do not cover all scenes of the compared halves",
                       "missing_scenes": sorted((expected - cand_scenes) | (expected - ctrl_scenes))[:20]}
    cand, ctrl = recipe_cues(cand_runs, windows), recipe_cues(ctrl_runs, windows)
    if len(cand["surfaces"] | ctrl["surfaces"]) > 1:
        raise ValueError(f"Mixed judge surfaces {sorted(cand['surfaces'] | ctrl['surfaces'])} in one comparison")
    if cand["missing"] or ctrl["missing"]:
        return info | {"decision": "insufficient", "reason": "windows neither judged nor undelivered",
                       "missing": {k: len(v) for k, v in {**cand["missing"], **ctrl["missing"]}.items()}}
    row = compare_cues(cand, ctrl, windows, reps=reps)
    delivery = {"candidate": len(cand["failed_scenes"]), "control": len(ctrl["failed_scenes"])}
    info.update(row, delivery_failed_scenes={"candidate": cand["failed_scenes"], "control": ctrl["failed_scenes"]},
                wall_clock_seconds={side: [read_json(p / "run.json").get("wall_clock_seconds") for p in runs]
                                    for side, runs in (("candidate", cand_runs), ("control", ctrl_runs))},
                performance_comparable={side: all(read_json(p / "run.json").get("performance_comparable", True)
                                                  for p in runs) for side, runs in (("candidate", cand_runs), ("control", ctrl_runs))})
    if policy and not calibration:
        stage = "confirm" if set_name == "confirm" else ("A" if set(halves) == {"A"} else "full")
        info["decision"], info["gates"] = decide(row, policy, stage, delivery)
    else:
        info["decision"] = "calibration_only"
    return info
