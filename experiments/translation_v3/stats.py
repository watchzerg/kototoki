"""MQM penalties, work-equal aggregation, cluster bootstrap and the v3 decision rules (plan 7.1).

Every expected window of the compared split must be accounted for in every seed: judged, or
undelivered (its scene failed terminally: each scored cue counts as an accuracy critical, 10).
Anything else (unjudged, generation unfinished) makes the decision ``insufficient``.
"""

from __future__ import annotations

from pathlib import Path
import random
import statistics
from typing import Any

from .common import read_json
from .data import ReferenceWindow
from .generate import load_run_translations, scene_state
from .judge import ACCURACY, PROFILE_ID, load_judgements

PENALTY = {"minor": 1, "major": 5, "critical": 10}
UNDELIVERED_CUE_PENALTY = PENALTY["critical"]
CATEGORIES = ("anime_series", "animation_movie")
BOOTSTRAP_SEED = "v3-bootstrap-20261010"
BOOTSTRAP_REPS = 10000
POLICY_FILE = "decision-policy-v3.json"
METRICS = ("accuracy", "fluency", "major_plus_rate", "critical")
REQUIRED_POLICY = ("mde", "noninferiority_margin", "risk_major_margin")


def cue_scores(cue: dict[str, Any]) -> dict[str, float]:
    accuracy = sum(PENALTY[e["severity"]] for e in cue["errors"] if e["category"] in ACCURACY)
    fluency = sum(PENALTY[e["severity"]] for e in cue["errors"] if e["category"] not in ACCURACY)
    return {"accuracy": accuracy, "fluency": fluency,
            "major_plus": float(any(e["severity"] != "minor" for e in cue["errors"])),
            "critical": float(sum(e["severity"] == "critical" for e in cue["errors"]))}


def window_metrics(cues: dict[str, dict[str, Any]]) -> dict[str, float]:
    scores = [cue_scores(cues[key]) for key in sorted(cues)]
    return {"accuracy": statistics.fmean(s["accuracy"] for s in scores),
            "fluency": statistics.fmean(s["fluency"] for s in scores),
            "major_plus_rate": statistics.fmean(s["major_plus"] for s in scores),
            "critical": sum(s["critical"] for s in scores)}


def undelivered_metrics(n_cues: int) -> dict[str, float]:
    return {"accuracy": float(UNDELIVERED_CUE_PENALTY), "fluency": 0.0, "major_plus_rate": 1.0, "critical": float(n_cues)}


def run_window_metrics(run_dir: Path, meta: dict[str, ReferenceWindow], replicate: int = 0) -> dict[str, Any]:
    """Metrics for every expected window: judged, undelivered (terminal scene failure) or missing."""
    translations, _ = load_run_translations(run_dir)
    judgements, surfaces = load_judgements(run_dir, replicate)
    metrics, missing, undelivered = {}, [], []
    for key in sorted(meta):
        window = meta[key]
        if all(u["id"] in translations for u in window.units):
            if key in judgements:
                metrics[key] = window_metrics(judgements[key])
            else:
                missing.append(key)
        elif scene_state(run_dir, window.meta.scene_id) == "failed":
            metrics[key] = undelivered_metrics(len(window.units))
            undelivered.append(key)
        else:
            missing.append(key)
    return {"metrics": metrics, "missing": missing, "undelivered": undelivered, "surfaces": surfaces}


def _work_means(values: dict[str, float], meta: dict[str, ReferenceWindow], keys: list[str]) -> dict[str, float]:
    groups: dict[str, list[float]] = {}
    for key in sorted(keys):
        groups.setdefault(meta[key].meta.work_id, []).append(values[key])
    return {work: statistics.fmean(groups[work]) for work in sorted(groups)}


def aggregate(values: dict[str, float], meta: dict[str, ReferenceWindow]) -> dict[str, float | None]:
    """Mean per work -> equal-weight mean per category -> 50/50 overall; plus a pooled work-equal mean."""
    result: dict[str, float | None] = {}
    for category in CATEGORIES:
        works = _work_means(values, meta, [k for k in values if meta[k].meta.category == category])
        result[category] = statistics.fmean(works.values()) if works else None
    present = [result[c] for c in CATEGORIES if result[c] is not None]
    result["overall"] = statistics.fmean(present) if len(present) == len(CATEGORIES) else None
    pooled = _work_means(values, meta, list(values))
    result["pooled"] = statistics.fmean(pooled.values()) if pooled else None
    return result


def cluster_bootstrap(deltas: dict[str, float], meta: dict[str, ReferenceWindow], *, reps: int = BOOTSTRAP_REPS,
                      seed: str = BOOTSTRAP_SEED, clusters: dict[str, str] | None = None) -> dict[str, Any]:
    """Paired bootstrap: resample clusters (work, or series via ``clusters``) with replacement within
    each category; works stay equally weighted inside drawn clusters. Keys are sorted, so results do
    not depend on hash randomization."""
    cluster_of = lambda work: (clusters or {}).get(work, work)
    work_means = _work_means(deltas, meta, list(deltas))
    category_of = {meta[k].meta.work_id: meta[k].meta.category for k in deltas}
    strata: dict[str, dict[str, list[float]]] = {name: {} for name in (*CATEGORIES, "pooled")}
    for work in sorted(work_means):
        for stratum in (category_of[work], "pooled"):
            strata[stratum].setdefault(cluster_of(work), []).append(work_means[work])
    ordered = {name: [groups[c] for c in sorted(groups)] for name, groups in strata.items()}
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {"overall": [], **{name: [] for name in ordered}}
    for _ in range(reps):
        values = {}
        for name, groups in ordered.items():
            if groups:
                drawn = [mean for _ in groups for mean in rng.choice(groups)]
                values[name] = statistics.fmean(drawn)
                samples[name].append(values[name])
        if all(c in values for c in CATEGORIES):
            samples["overall"].append(statistics.fmean(values[c] for c in CATEGORIES))

    def summary(xs: list[float]) -> dict[str, Any] | None:
        if not xs:
            return None
        ordered_xs = sorted(xs)
        return {"ci95": [ordered_xs[int(0.025 * (len(xs) - 1))], ordered_xs[int(0.975 * (len(xs) - 1))]],
                "sd": statistics.stdev(xs) if len(xs) > 1 else 0.0,
                "p_delta_ge_0": sum(x >= 0 for x in xs) / len(xs)}
    return {"reps": reps, "seed": seed, "clusters": "series-map" if clusters else "work",
            **{key: summary(value) for key, value in samples.items()}}


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict[str, Any]]:
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    result, previous, stop = {}, 0.0, False
    for rank, (name, p) in enumerate(ordered):
        adjusted = max(previous, min(1.0, p * (len(ordered) - rank)))
        previous = adjusted
        stop = stop or adjusted >= alpha
        result[name] = {"p": p, "p_holm": adjusted, "reject": not stop}
    return result


def load_policy(root: Path) -> dict[str, Any] | None:
    path = root / POLICY_FILE
    if not path.is_file():
        return None
    policy = read_json(path)
    for key in REQUIRED_POLICY:
        if not isinstance(policy.get(key), (int, float)) or policy[key] < 0:
            raise ValueError(f"{POLICY_FILE}: '{key}' must be a nonnegative number")
    if policy.get("critical_rule", "no_increase") != "no_increase":
        raise ValueError(f"{POLICY_FILE}: only critical_rule 'no_increase' is implemented")
    return policy


def find_runs(root: Path, prefix: str, scope: str) -> list[Path]:
    return sorted(p for p in (root / "runs").glob(f"{prefix}__s*__{scope}") if (p / "run.json").is_file())


def split_meta(reference: dict[str, ReferenceWindow], split: str) -> dict[str, ReferenceWindow]:
    splits = ("screen-a", "screen-b") if split == "screening" else (split,)
    return {k: w for k, w in sorted(reference.items()) if w.meta.split in splits}


def compare(root: Path, reference: dict[str, ReferenceWindow], candidates: list[str], control: str, split: str,
            *, reps: int = BOOTSTRAP_REPS, allow_without_policy: bool = False) -> dict[str, Any]:
    policy = load_policy(root)
    if policy is None and not allow_without_policy and any(c != control for c in candidates):
        raise PermissionError(f"{POLICY_FILE} is not frozen; candidate scores must not be viewed before calibration")
    scope = "confirmation" if split == "confirmation" else "screening"
    meta = split_meta(reference, split)
    reports = {name: _compare_one(root, meta, name, control, scope, policy, reps, split) for name in candidates}
    if split == "confirmation" and policy:
        pvalues = {n: r["primary"]["bootstrap"]["overall"]["p_delta_ge_0"] for n, r in reports.items()
                   if (r.get("primary", {}).get("bootstrap") or {}).get("overall")}
        for name, row in holm(pvalues, policy.get("holm_alpha", 0.05)).items():
            reports[name]["holm"] = row
            if reports[name]["decision"] == "confirmed" and not row["reject"]:
                reports[name]["decision"] = "not_confirmed_after_holm"
    return {"split": split, "control": control, "policy": policy, "profile": PROFILE_ID,
            "expected_windows": len(meta), "candidates": reports}


def _seed_mean(per_seed: dict[int, dict[str, dict[str, float]]], metric: str, keys: list[str]) -> dict[str, float]:
    return {k: statistics.fmean(per_seed[s][k][metric] for s in sorted(per_seed)) for k in sorted(keys)}


def _compare_one(root: Path, meta: dict[str, ReferenceWindow], name: str, control: str, scope: str,
                 policy: dict[str, Any] | None, reps: int, split: str) -> dict[str, Any]:
    runs = {"candidate": find_runs(root, name, scope), "control": find_runs(root, control, scope)}
    info: dict[str, Any] = {"runs": {k: [p.name for p in v] for k, v in runs.items()}}
    required = (policy or {}).get("required_seeds", 3)
    seeds = {side: {read_json(p / "run.json")["seed"]: p for p in paths} for side, paths in runs.items()}
    if set(seeds["candidate"]) != set(seeds["control"]) or len(seeds["candidate"]) < required:
        return info | {"decision": "insufficient",
                       "reason": f"need the same >= {required} seeds on both sides: {sorted(seeds['candidate'])} vs {sorted(seeds['control'])}"}
    per_seed: dict[str, dict[int, dict[str, dict[str, float]]]] = {"candidate": {}, "control": {}}
    surfaces: set[str] = set()
    missing: dict[str, list[str]] = {}
    delivery: dict[str, float] = {}
    for side in per_seed:
        rates = []
        for seed in sorted(seeds[side]):
            path = seeds[side][seed]
            result = run_window_metrics(path, meta)
            surfaces |= result["surfaces"]
            if result["missing"]:
                missing[path.name] = result["missing"]
            per_seed[side][seed] = result["metrics"]
            rates.append(len(result["undelivered"]) / len(meta))
        delivery[side] = statistics.fmean(rates)
    if len(surfaces) > 1:
        raise ValueError(f"Mixed judge surfaces {sorted(surfaces)} in one comparison; rejudge with one surface")
    info.update(surface=sorted(surfaces), delivery_failure_rate=delivery, seeds=sorted(seeds["candidate"]),
                wall_clock_seconds={side: [read_json(p / "run.json").get("wall_clock_seconds") for p in paths
                                           if read_json(p / "run.json").get("performance_comparable")]
                                    for side, paths in runs.items()})
    if missing:
        return info | {"decision": "insufficient", "reason": "expected windows neither judged nor undelivered",
                       "missing_windows": missing}
    clusters = (policy or {}).get("series_clusters") or None
    groups = {"representative": sorted(k for k, w in meta.items() if w.meta.selection_type == "representative"),
              "risk": sorted(k for k, w in meta.items() if w.meta.selection_type == "risk")}
    for group, keys in groups.items():
        row = {}
        for metric in METRICS:
            cand = _seed_mean(per_seed["candidate"], metric, keys)
            ctrl = _seed_mean(per_seed["control"], metric, keys)
            deltas = {k: cand[k] - ctrl[k] for k in keys}
            row[metric] = {"candidate": aggregate(cand, meta), "control": aggregate(ctrl, meta),
                           "delta": aggregate(deltas, meta), "windows": len(keys)}
            if deltas and (metric == "accuracy" or (group == "risk" and metric == "major_plus_rate")):
                row[metric]["bootstrap"] = cluster_bootstrap(deltas, meta, reps=reps, clusters=clusters)
            if metric == "accuracy" and group == "representative":
                info["per_work_delta"] = {work: {"category": next(meta[k].meta.category for k in keys if meta[k].meta.work_id == work),
                                                 "delta": value}
                                          for work, value in _work_means(deltas, meta, keys).items()}
                info["leave_one_work_out"] = _leave_one_out(deltas, meta, policy)
        info[group] = row
    info["primary"] = info["representative"]["accuracy"]
    info["per_seed_category_delta"] = {
        seed: aggregate({k: per_seed["candidate"][seed][k]["accuracy"] - per_seed["control"][seed][k]["accuracy"]
                         for k in groups["representative"]}, meta) for seed in sorted(seeds["candidate"])}
    info["decision"], info["reason"], info["gates"] = decide(info, policy, split, len(seeds["candidate"]))
    return info


def _passes_core(delta: dict[str, float | None], policy: dict[str, Any]) -> bool:
    return (delta["overall"] is not None and delta["overall"] <= -policy["mde"]
            and all(delta[c] is not None and delta[c] <= policy["noninferiority_margin"] for c in CATEGORIES))


def _leave_one_out(deltas: dict[str, float], meta: dict[str, ReferenceWindow], policy: dict[str, Any] | None) -> dict[str, Any]:
    works = sorted({meta[k].meta.work_id for k in deltas})
    result = {}
    for work in works:
        kept = {k: v for k, v in deltas.items() if meta[k].meta.work_id != work}
        delta = aggregate(kept, meta)
        result[work] = {"delta": delta, "passes": _passes_core(delta, policy) if policy else None}
    return result


def decide(info: dict[str, Any], policy: dict[str, Any] | None, split: str, n_seeds: int) -> tuple[str, str, dict[str, Any]]:
    if policy is None:
        return "no_policy", "decision-policy-v3.json not frozen", {}
    delta = info["primary"]["delta"]
    if delta["overall"] is None:
        return "insufficient", "a category has no windows", {}
    margin = policy["noninferiority_margin"]
    rep_crit, risk_crit = info["representative"]["critical"], info["risk"]["critical"]
    risk_major = info["risk"]["major_plus_rate"]
    risk_upper = ((risk_major.get("bootstrap") or {}).get("pooled") or {}).get("ci95", [None, None])[1]
    gates = {
        "category_noninferior": all(delta[c] <= margin for c in CATEGORIES),
        "critical_representative": (rep_crit["candidate"]["overall"] or 0) <= (rep_crit["control"]["overall"] or 0),
        "critical_risk": risk_crit["windows"] == 0 or (risk_crit["candidate"]["pooled"] or 0) <= (risk_crit["control"]["pooled"] or 0),
        "risk_major_upper_within_margin": risk_upper is None or risk_upper <= policy["risk_major_margin"],
        "delivery_noninferior": info["delivery_failure_rate"]["candidate"]
                                <= info["delivery_failure_rate"]["control"] + policy.get("delivery_margin", 0.0),
        "leave_one_work_out": all(row["passes"] for row in info.get("leave_one_work_out", {}).values()),
    }
    safety = all(gates[k] for k in ("category_noninferior", "critical_representative", "critical_risk", "delivery_noninferior"))
    if split == "confirmation":
        upper = info["primary"]["bootstrap"]["overall"]["ci95"][1]
        gates["ci_upper_below_zero"] = upper < 0
        if gates["ci_upper_below_zero"] and safety:
            return "confirmed", "CI upper < 0, categories within margin, critical and delivery not worse", gates
        return "not_confirmed", "confirmation rule not met", gates
    if split == "screening":
        consistent = [c for c in CATEGORIES if delta[c] > margin and n_seeds >= 3
                      and all((row[c] or 0) > 0 for row in info["per_seed_category_delta"].values())]
        if delta["overall"] >= 0 or consistent:
            return "eliminated", f"overall delta >= 0 or category worse than margin with consistent seeds {consistent}", gates
    gates["overall_at_most_minus_mde"] = delta["overall"] <= -policy["mde"]
    if gates["overall_at_most_minus_mde"] and safety and gates["risk_major_upper_within_margin"] and gates["leave_one_work_out"]:
        return "promising", "all promising gates pass (incl. risk, critical, delivery, leave-one-work-out)", gates
    return "insufficient", "failed gates: " + ", ".join(k for k, v in gates.items() if not v), gates


# --- calibration -----------------------------------------------------------------------------

def reference_self_check(run_dir: Path, meta: dict[str, ReferenceWindow]) -> dict[str, Any]:
    judgements, surfaces = load_judgements(run_dir)
    metrics = {k: window_metrics(v) for k, v in sorted(judgements.items()) if k in meta}
    flagged = [{"window_id": w, "cue_id": c, "errors": [{"category": e["category"], "severity": e["severity"]}
                                                          for e in cue["errors"] if e["severity"] != "minor"]}
               for w, cues in sorted(judgements.items()) for c, cue in sorted(cues.items())
               if any(e["severity"] != "minor" for e in cue["errors"])]
    return {"windows_judged": len(metrics), "windows_expected": len(meta), "surfaces": sorted(surfaces),
            "accuracy": aggregate({k: v["accuracy"] for k, v in metrics.items()}, meta),
            "fluency": aggregate({k: v["fluency"] for k, v in metrics.items()}, meta),
            "major_or_critical_cues": flagged,
            "note": "review every major/critical cue: reference error or judge too strict"}


def repeat_noise(run_dirs: list[Path], meta: dict[str, ReferenceWindow], replicate: int = 1, *,
                 reps: int = BOOTSTRAP_REPS) -> dict[str, Any]:
    """Judge-repeat noise on the decision scale: per-window replicate differences averaged over the
    runs (seeds) that have both judgements, aggregated work-equal/50-50 on representative windows,
    with SE from the clustered bootstrap; MDE = 2 * SE."""
    diffs: dict[str, list[float]] = {}
    flips: list[bool] = []
    used = []
    for run_dir in run_dirs:
        first, _ = load_judgements(run_dir, 0)
        second, _ = load_judgements(run_dir, replicate)
        common = sorted(set(first) & set(second) & set(meta))
        if common:
            used.append(run_dir.name)
        for key in common:
            diffs.setdefault(key, []).append(window_metrics(second[key])["accuracy"] - window_metrics(first[key])["accuracy"])
            flips += [cue_scores(first[key][c])["major_plus"] != cue_scores(second[key][c])["major_plus"]
                      for c in sorted(first[key]) if c in second[key]]
    representative = {k: statistics.fmean(v) for k, v in sorted(diffs.items()) if meta[k].meta.selection_type == "representative"}
    report: dict[str, Any] = {"runs": used, "paired_windows": len(diffs), "representative_windows": len(representative),
                              "expected_windows": len(meta),
                              "major_flip_rate": statistics.fmean(flips) if flips else None,
                              "formula": "MDE = 2 * SE, SE = sd of the clustered-bootstrap aggregate of replicate differences"}
    if not representative:
        return report
    aggregated = aggregate(representative, meta)
    boot = cluster_bootstrap(representative, meta, reps=reps)
    se = (boot.get("overall") or {}).get("sd")
    report.update(aggregate_diff=aggregated, se=se, suggested_mde=2 * se if se is not None else None,
                  per_window_sd=statistics.stdev(representative.values()) if len(representative) > 1 else None)
    return report
