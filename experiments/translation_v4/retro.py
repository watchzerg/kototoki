"""Retrospective variance decomposition of the v3 judged runs (read-only on v3 artifacts).

Model for one window's accuracy penalty y (mean over its scored cues):
    y[r, s, w, j] = mu_w + tau[r, w] + e_seed[r, s, w] + e_judge[r, s, w, j]
- sigma2_judge: half the variance of replicate-minus-original differences (same run, re-judged);
- sigma2_seed:  mean within-window variance across seeds (one judging) minus sigma2_judge;
- sigma2_tau:   variance across windows of the seed-mean paired delta minus its noise part.
Also reports the within-work / between-work split of tau and the cue-level intra-window
correlation of paired deltas, which decides whether more cues per window behave like more windows.
"""

from __future__ import annotations

from pathlib import Path
import statistics
from typing import Any

from experiments.translation_v3 import stats as S
from experiments.translation_v3.common import read_json
from experiments.translation_v3.data import load_reference_v3
from experiments.translation_v3.judge import load_judgements

V3_ROOT = Path(__file__).resolve().parents[2] / ".local/translation-evaluation/hy30-flow-v3"


def _runs(root: Path, recipe: str, scope: str) -> dict[int, Path]:
    return {read_json(p / "run.json")["seed"]: p for p in S.find_runs(root, recipe, scope)}


def cue_penalties(run_dir: Path, replicate: int = 0) -> dict[str, dict[str, float]]:
    judgements, _ = load_judgements(run_dir, replicate)
    return {w: {c: S.cue_scores(cue)["accuracy"] for c, cue in cues.items()} for w, cues in judgements.items()}


def window_acc(cues: dict[str, float]) -> float:
    return statistics.fmean(cues.values())


def _var(xs: list[float]) -> float:
    return statistics.variance(xs) if len(xs) > 1 else 0.0


def decompose(root: Path = V3_ROOT, scope: str = "screening") -> dict[str, Any]:
    reference = load_reference_v3(root)
    splits = ("screen-a", "screen-b") if scope == "screening" else ("confirmation",)
    meta = {k: w for k, w in reference.items() if w.meta.split in splits and w.meta.selection_type == "representative"}
    recipes = sorted({p.name.split("__")[0] for p in (root / "runs").glob(f"*__s2026*__{scope}")})
    data: dict[str, dict[int, dict[str, dict[str, float]]]] = {}
    for recipe in recipes:
        for seed, path in _runs(root, recipe, scope).items():
            cues = cue_penalties(path)
            data.setdefault(recipe, {})[seed] = {w: c for w, c in cues.items() if w in meta}
    # judge noise from replicates
    judge_diffs = []
    for path in _runs(root, "c0", scope).values():
        first, second = cue_penalties(path, 0), cue_penalties(path, 1)
        judge_diffs += [window_acc(second[w]) - window_acc(first[w]) for w in sorted(set(first) & set(second) & set(meta))]
    sigma2_judge = _var(judge_diffs) / 2 if judge_diffs else None
    # seed noise per recipe (windows judged in all 3 seeds)
    seed_var = {}
    for recipe, seeds in data.items():
        if len(seeds) < 3:
            continue
        common = set.intersection(*(set(v) for v in seeds.values()))
        if common:
            seed_var[recipe] = statistics.fmean(_var([window_acc(seeds[s][w]) for s in sorted(seeds)]) for w in sorted(common))
    pooled_seed_total = statistics.fmean(seed_var.values())
    sigma2_seed = pooled_seed_total - (sigma2_judge or 0)
    control = data["c0"]
    effects = {}
    for recipe, seeds in data.items():
        if recipe == "c0" or set(seeds) != set(control):
            continue
        common = sorted(set.intersection(*(set(v) for v in list(seeds.values()) + list(control.values()))))
        if len(common) < 20:
            continue
        n = len(seeds)
        deltas = {w: statistics.fmean(window_acc(seeds[s][w]) for s in seeds) - statistics.fmean(window_acc(control[s][w]) for s in control)
                  for w in common}
        total = _var(list(deltas.values()))
        noise = 2 * pooled_seed_total / n
        by_work: dict[str, list[float]] = {}
        for w, d in deltas.items():
            by_work.setdefault(meta[w].meta.work_id, []).append(d)
        within = statistics.fmean(_var(v) for v in by_work.values() if len(v) > 1)
        work_means = [statistics.fmean(v) for v in by_work.values()]
        # cue-level ICC of paired deltas inside a window
        cue_d = {w: [statistics.fmean(seeds[s][w][c] for s in seeds) - statistics.fmean(control[s][w][c] for s in control)
                     for c in sorted(control[min(control)][w])] for w in common}
        cue_var = statistics.fmean(_var(v) for v in cue_d.values())
        k = statistics.fmean(len(v) for v in cue_d.values())
        between = _var([statistics.fmean(v) for v in cue_d.values()]) - cue_var / k
        icc = between / (between + cue_var) if between + cue_var > 0 else None
        effects[recipe] = {"windows": len(common), "mean_delta": statistics.fmean(deltas.values()),
                           "var_delta_window": total, "noise_part": noise,
                           "sigma2_tau": total - noise, "within_work_var": within,
                           "between_work_var_of_means": _var(work_means), "cue_icc_of_delta": icc}
    tau = [e["sigma2_tau"] for e in effects.values()]
    return {"scope": scope, "representative_windows": len(meta), "recipes": len(data),
            "judge_replicate_pairs": len(judge_diffs), "sigma2_judge": sigma2_judge,
            "seed_plus_judge_var": pooled_seed_total, "sigma2_seed": sigma2_seed,
            "seed_var_by_recipe": seed_var,
            "sigma2_tau_median": statistics.median(tau) if tau else None,
            "sigma2_tau_mean": statistics.fmean(tau) if tau else None,
            "c0_mean_window_acc": statistics.fmean(window_acc(control[s][w]) for s in control for w in control[s]),
            "effects": effects}


def design_se(sigma2_tau: float, sigma2_seed: float, sigma2_judge: float, *, windows: int, seeds: int,
              judgings: int = 1, design_effect: float = 1.0) -> float:
    """Approximate SE of a work-equal, 50/50 paired delta with ``windows`` spread evenly.

    Per-window paired variance = tau + 2*(seed + judge/J)/S; equal work weighting with a
    balanced design makes the aggregate variance ~ per-window variance / windows; the
    design effect absorbs work clustering / unequal weights (measured, not assumed)."""
    per_window = sigma2_tau + 2 * (sigma2_seed + sigma2_judge / judgings) / seeds
    return (design_effect * per_window / windows) ** 0.5


if __name__ == "__main__":
    import json
    import sys
    scope = sys.argv[1] if len(sys.argv) > 1 else "screening"
    print(json.dumps(decompose(scope=scope), ensure_ascii=False, indent=1))


# --- retrospective power: honest SE and metric reliability -----------------------------------

METRIC_FUNCS = {
    "accuracy": lambda cue: S.cue_scores(cue)["accuracy"],
    "major_plus": lambda cue: S.cue_scores(cue)["major_plus"] * 1.0,
    "any_accuracy_error": lambda cue: float(any(e["category"] in S.ACCURACY for e in cue["errors"])),
    "accuracy_capped5": lambda cue: min(5.0, S.cue_scores(cue)["accuracy"]),
}


def window_values(run_dir: Path, meta: dict, metric: str) -> dict[str, float]:
    judgements, _ = load_judgements(run_dir, 0)
    f = METRIC_FUNCS[metric]
    return {w: statistics.fmean(f(cue) for cue in cues.values()) for w, cues in judgements.items() if w in meta}


def work_equal(values: dict[str, float], meta: dict) -> float:
    agg = S.aggregate(values, meta)
    return agg["overall"]


def stratified_window_bootstrap(deltas: dict[str, float], meta: dict, reps: int = 2000, seed: int = 7) -> float:
    """Resample windows with replacement inside each work (works fixed), work-equal 50/50 aggregate."""
    import random
    rng = random.Random(seed)
    by_work: dict[str, list[str]] = {}
    for key in sorted(deltas):
        by_work.setdefault(meta[key].meta.work_id, []).append(key)
    samples = []
    for _ in range(reps):
        drawn: dict[str, float] = {}
        for work, keys in by_work.items():
            for i in range(len(keys)):
                k = rng.choice(keys)
                drawn[f"{k}#{i}"] = deltas[k]
        fake = {k: meta[k.split("#")[0]] for k in drawn}
        samples.append(S.aggregate(drawn, fake)["overall"])
    return statistics.stdev(samples)


def retro_power(root: Path = V3_ROOT) -> dict[str, Any]:
    reference = load_reference_v3(root)
    out: dict[str, Any] = {}
    for scope, splits in (("screening", ("screen-a", "screen-b")), ("confirmation", ("confirmation",))):
        meta = {k: w for k, w in reference.items() if w.meta.split in splits and w.meta.selection_type == "representative"}
        recipes = sorted({p.name.split("__")[0] for p in (root / "runs").glob(f"*__s2026*__{scope}")})
        rows = {}
        for metric in METRIC_FUNCS:
            per = {}
            for recipe in recipes:
                runs = _runs(root, recipe, scope)
                if len(runs) < 3:
                    continue
                per[recipe] = {s: window_values(p, meta, metric) for s, p in runs.items()}
            control = per.pop("c0")
            for recipe, seeds in per.items():
                common = sorted(set.intersection(*(set(v) for v in list(seeds.values()) + list(control.values()))))
                if len(common) < 60:
                    continue
                cm = {w: statistics.fmean(seeds[s][w] for s in seeds) for w in common}
                km = {w: statistics.fmean(control[s][w] for s in control) for w in common}
                deltas = {w: cm[w] - km[w] for w in common}
                sub = {w: meta[w] for w in common}
                half = {}
                for split in splits:
                    keys = [w for w in common if meta[w].meta.split == split]
                    half[split] = work_equal({w: deltas[w] for w in keys}, sub) if keys else None
                rows.setdefault(recipe, {})[metric] = {
                    "delta": work_equal(deltas, sub), "control_level": work_equal(km, sub),
                    "se_window_bootstrap": stratified_window_bootstrap(deltas, sub),
                    "half": half}
        out[scope] = rows
    return out
