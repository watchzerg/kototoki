"""Q2: generate gap-split variants on the v4 dev set, judge only the affected subset, compare paired.

Layout under ``<v6 root>``:
  recipes/<name>.json                       variant recipes (v3 compose format)
  runs/<variant>__s<seed>__dev/             v3 runs (generation + judge/) on the v4 dev seed block
  runs/b10-joint-ctl__s<seed>__dev/         copy of the v4 b10-joint run (run.json + scenes/), judged
                                            on the same subset with the same packet layout
  subsets/<variant>__s<seed>.json           affected cues/windows for that pair
  summaries/q2-<variant>[-rep].json         paired comparison

A batch is "changed" when its (targets, before, after, pause marks) differs from the control batch holding the same
targets; its targets are the affected cues. Judge windows are the v4 5-cue tiles containing at least
one affected cue; all cues of these windows are judged in both arms, the endpoint uses affected cues.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import shutil
import statistics
from typing import Any

from experiments.translation_v3.common import atomic_write_json, read_json
from experiments.translation_v3.data import ReferenceWindow
from experiments.translation_v3.generate import load_run_translations, managed_session_factory, run_generation, run_id_for
from experiments.translation_v3.recipes import load_recipe
from experiments.translation_v4 import evaluate as E
from experiments.translation_v4 import stats4 as S4
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT
from experiments.translation_v4.gen import set_scenes

from .common import V6_ROOT
from .stats6 import METRICS, run_metrics

CONTROL = "b10-joint"
CONTROL_COPY = "b10-joint-ctl"
SET = "dev"


def run_dir(root: Path, recipe: str, seed: int) -> Path:
    return root / "runs" / f"{recipe}__s{seed}__{SET}"


def generate(recipe_name: str, seed: int, *, root: Path = V6_ROOT, port: int = 8080,
             break_stale_lock: bool = False) -> dict[str, Any]:
    recipe = load_recipe(recipe_name, root)
    scenes, sources = set_scenes(V4_ROOT, SET, seed)
    run_id = run_id_for(recipe, seed, SET)
    factory = managed_session_factory(root, run_id, port=port, break_stale_lock=break_stale_lock)
    run = run_generation(root / "runs" / run_id, recipe, seed, scenes, scope=SET, sources=sources,
                         session_factory=factory)
    return {"run_id": run_id, "completion": run["completion"], "resumed": run["resumed"],
            "wall_clock_seconds": run.get("wall_clock_seconds")}


def copy_control(seed: int, *, root: Path = V6_ROOT, v4_root: Path = V4_ROOT) -> Path:
    """Copy run.json (run_id renamed, provenance added) and scenes/ of the v4 control run."""
    source = run_dir(v4_root, CONTROL, seed)
    target = run_dir(root, CONTROL_COPY, seed)
    if (target / "run.json").is_file():
        return target
    (target / "scenes").mkdir(parents=True, exist_ok=True)
    for path in sorted((source / "scenes").glob("*.json")):
        shutil.copy2(path, target / "scenes" / path.name)
    run = read_json(source / "run.json")
    run.update(run_id=target.name, copied_from=str(source.relative_to(v4_root.parent)),
               copy_note="translations of the v4 control run, re-judged on the v6 subset")
    atomic_write_json(target / "run.json", run)
    return target


def _batch_map(run_path: Path) -> dict[str, dict[str, tuple]]:
    out = {}
    for path in sorted((run_path / "scenes").glob("*.json")):
        row = read_json(path)
        out[row["scene_id"]] = {k: (tuple(b["target_ids"]), tuple(b["before_ids"]), tuple(b["after_ids"]),
                                    tuple(tuple(p) for p in b.get("pauses", ())))
                                for b in row["batches"] for k in b["target_ids"]}
    return out


def affected_cues(cand: dict[str, dict[str, tuple]], ctrl: dict[str, dict[str, tuple]]) -> list[str]:
    """Targets of candidate batches whose (targets, before, after) differs from the control batch
    holding the same cue."""
    if set(cand) != set(ctrl):
        raise ValueError("candidate and control cover different scenes")
    return sorted(k for scene in cand for k, b in cand[scene].items() if ctrl[scene][k] != b)


def build_subset(variant: str, seed: int, *, root: Path = V6_ROOT, control_seed: int | None = None,
                 full: bool = False) -> dict[str, Any]:
    """Affected cues and windows of one candidate run against the control run of ``control_seed``;
    ``full`` (v7) keeps every window of the covered scenes."""
    cand_dir = run_dir(root, variant, seed)
    ctrl_dir = run_dir(root, CONTROL_COPY, control_seed or seed)
    cand, ctrl = _batch_map(cand_dir), _batch_map(ctrl_dir)
    affected = affected_cues(cand, ctrl)
    windows = E.reference_for(V4_ROOT, SET)
    scenes = set(cand)
    chosen = sorted(key for key, w in windows.items() if w.meta.scene_id in scenes
                    and (full or any(u["id"] in set(affected) for u in w.units)))
    cand_tr, _ = load_run_translations(cand_dir)
    ctrl_tr, _ = load_run_translations(ctrl_dir)
    unaffected = [k for scene in cand for k in cand[scene] if k not in set(affected)]
    identical = sum(cand_tr.get(k) == ctrl_tr.get(k) for k in unaffected)
    changed_batches = len({b for scene in cand for k, b in cand[scene].items() if k in set(affected)})
    subset = {"variant": variant, "seed": seed, "control_seed": control_seed or seed, "full": full,
              "affected_cues": affected, "windows": chosen, "scene_count": len(scenes),
              "cue_count": sum(len(v) for v in cand.values()), "changed_batches": changed_batches,
              "unaffected_cues": len(unaffected), "unaffected_identical_translation": identical,
              "affected_identical_translation": sum(cand_tr.get(k) == ctrl_tr.get(k) for k in affected)}
    atomic_write_json(root / "subsets" / f"{variant}__s{seed}.json", subset)
    return subset


def subset_reference(root: Path, variant: str, seed: int) -> dict[str, ReferenceWindow]:
    keys = set(read_json(root / "subsets" / f"{variant}__s{seed}.json")["windows"])
    return E.reference_for(V4_ROOT, SET, keys)


def judge(variant: str, seed: int, *, root: Path = V6_ROOT, parallel: int = 3, control_seed: int | None = None,
          candidate_only: bool = False, log=print) -> dict[str, Any]:
    """Judge the subset windows in the candidate run and in the control copy (same packet layout)."""
    reference = subset_reference(root, variant, seed)
    results = []
    paths = [run_dir(root, variant, seed)] + ([] if candidate_only else [run_dir(root, CONTROL_COPY, control_seed or seed)])
    for path in paths:
        result = E.judge(root, path, ["A", "B"], parallel=parallel, reference=reference, log=log)
        results.append(result)
        if result["exit_code"]:
            break
    return {"parts": results, "exit_code": max(r["exit_code"] for r in results)}


# --- comparison --------------------------------------------------------------------------------

def _work_equal(diffs: dict[str, float], layout: S4.Layout) -> dict[str, float | None]:
    return S4.aggregate(diffs, layout)


def compare(variant: str, seeds: list[int], *, root: Path = V6_ROOT, control_seeds: list[int] | None = None,
            v4_root: Path = V4_ROOT, label: str = "") -> dict[str, Any]:
    """Paired candidate - control on affected cues (primary) and the full-set guard (unaffected cues
    contribute 0, valid when their translations are identical, which the subset files record)."""
    control_seeds = control_seeds or seeds
    all_windows = E.reference_for(v4_root, SET)
    cand_vals, ctrl_vals, orig_vals, affected, scenes = {}, {}, {}, set(), set()
    missing, subsets = {}, []
    for seed, cseed in zip(seeds, control_seeds):
        subset = read_json(root / "subsets" / f"{variant}__s{seed}.json")
        subsets.append({k: subset[k] for k in subset if k not in ("affected_cues", "windows")})
        ref = {k: all_windows[k] for k in subset["windows"]}
        for target, path in ((cand_vals, run_dir(root, variant, seed)), (ctrl_vals, run_dir(root, CONTROL_COPY, cseed)),
                             (orig_vals, run_dir(v4_root, CONTROL, cseed))):
            result = run_metrics(path, ref)
            if result["missing"]:
                missing[path.name] = len(result["missing"])
            target.update(result["values"])
        affected |= set(subset["affected_cues"])
        scenes |= set(read_json(run_dir(root, variant, seed) / "run.json")["scene_ids"])
    if missing:
        return {"state": "insufficient", "missing_windows": missing}
    keys = sorted(k for k in affected if k in cand_vals and k in ctrl_vals)
    layout = S4.Layout(all_windows, set(keys))
    report: dict[str, Any] = {"variant": variant, "seeds": seeds, "control_seeds": control_seeds, "subsets": subsets,
                              "affected_cues": len(keys), "by_category_counts": _counts(layout, keys)}
    for metric in METRICS:
        diffs = {k: cand_vals[k][metric] - ctrl_vals[k][metric] for k in keys}
        report.setdefault("affected", {})[metric] = {
            "candidate": _work_equal({k: cand_vals[k][metric] for k in keys}, layout),
            "control": _work_equal({k: ctrl_vals[k][metric] for k in keys}, layout),
            "delta": _work_equal(diffs, layout), "bootstrap": S4.bootstrap(diffs, layout, reps=10000)}
    # safety metrics on affected cues (v4 definitions: critical count, major+ indicator)
    safety: dict[str, dict[str, float]] = {"candidate": {}, "control": {}}
    for seed, cseed in zip(seeds, control_seeds):
        ref = {k: all_windows[k] for k in read_json(root / "subsets" / f"{variant}__s{seed}.json")["windows"]}
        for arm, path in (("candidate", run_dir(root, variant, seed)), ("control", run_dir(root, CONTROL_COPY, cseed))):
            for cue, row in S4.run_cues(path, ref)["values"].items():
                safety[arm][cue] = row
    for metric in ("critical", "major_plus"):
        diffs = {k: safety["candidate"][k][metric] - safety["control"][k][metric] for k in keys}
        report.setdefault("safety", {})[metric] = {"delta": _work_equal(diffs, layout),
                                                   "bootstrap": S4.bootstrap(diffs, layout, reps=2000)}
    # judge noise on the subset: control re-judge minus original v4 judgement (same translations)
    rejudge = {k: ctrl_vals[k]["accuracy"] - orig_vals[k]["accuracy"] for k in keys if k in orig_vals}
    report["control_rejudge_minus_original"] = {"delta": _work_equal(rejudge, layout),
                                                "bootstrap": S4.bootstrap(rejudge, layout, reps=2000)}
    # full-set guard: every dev cue of the covered scenes, unaffected cues contribute 0
    full_windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in scenes}
    full_cues = {u["id"] for w in full_windows.values() for u in w.units}
    full_layout = S4.Layout(full_windows, full_cues)
    full = {k: (cand_vals[k]["accuracy"] - ctrl_vals[k]["accuracy"]) if k in set(keys) else 0.0 for k in full_cues}
    report["full_set_guard"] = {"cues": len(full_cues), "delta": _work_equal(full, full_layout),
                                "bootstrap": S4.bootstrap(full, full_layout, reps=10000)}
    report["delivery"] = {name: _failed(run_dir(root, name, s)) for name, ss in ((variant, seeds), (CONTROL_COPY, control_seeds))
                          for s in ss}
    report["cost"] = {path.name: _cost(path) for s in seeds for path in (run_dir(root, variant, s), run_dir(v4_root, CONTROL, s))}
    name = f"q2-{variant}{('-' + label) if label else ''}.json"
    atomic_write_json(root / "summaries" / name, report)
    return report


def _counts(layout: S4.Layout, keys: list[str]) -> dict[str, int]:
    scene_of = {c: s for s, cs in layout.scene_cues.items() for c in cs}
    out: dict[str, int] = defaultdict(int)
    for k in keys:
        out[layout.category_of[layout.work_of[scene_of[k]]]] += 1
    return dict(out)


def _failed(path: Path) -> list[str]:
    return sorted(p.stem for p in (path / "scenes").glob("*.json") if read_json(p).get("status") == "failed")


def _cost(path: Path) -> dict[str, Any]:
    run = read_json(path / "run.json")
    rows = [read_json(p) for p in sorted((path / "scenes").glob("*.json"))]
    sizes = [len(b["before_ids"]) + len(b["target_ids"]) + len(b["after_ids"]) for r in rows for b in r["batches"]]
    peaks = [read_json(p).get("peak_device_memory_mib") for p in sorted(path.glob("runtime/session-*/engine-final.json"))]
    return {"wall_clock_seconds": run.get("wall_clock_seconds"), "resumed": run.get("resumed"),
            "requests": sum(r["totals"]["requests"] for r in rows),
            "output_tokens": sum(r["totals"]["output_tokens"] for r in rows),
            "scene_seconds": sum(r.get("elapsed_seconds") or 0 for r in rows),
            "visible_max": max(sizes) if sizes else None,
            "visible_mean": statistics.fmean(sizes) if sizes else None, "peak_device_memory_mib": peaks}


def pooled(variant: str, seed_sets: list[list[int]], *, root: Path = V6_ROOT, label: str = "pooled") -> dict[str, Any]:
    """Mean of the paired differences over independent realizations (each set pairs candidate and
    control with the same seeds); affected cues must be the same in every set (batching is seed-free)."""
    all_windows = E.reference_for(V4_ROOT, SET)
    per_set: list[dict[str, dict[str, float]]] = []
    affected: set[str] | None = None
    scenes: set[str] = set()
    for seeds in seed_sets:
        diffs: dict[str, dict[str, float]] = {}
        keys: set[str] = set()
        for seed in seeds:
            subset = read_json(root / "subsets" / f"{variant}__s{seed}.json")
            ref = {k: all_windows[k] for k in subset["windows"]}
            cand = run_metrics(run_dir(root, variant, seed), ref)["values"]
            ctrl = run_metrics(run_dir(root, CONTROL_COPY, seed), ref)["values"]
            for k in subset["affected_cues"]:
                diffs[k] = {m: cand[k][m] - ctrl[k][m] for m in METRICS}
            keys |= set(subset["affected_cues"])
            scenes |= set(read_json(run_dir(root, variant, seed) / "run.json")["scene_ids"])
        if affected is not None and keys != affected:
            raise ValueError("affected cues differ between seed sets")
        affected = keys
        per_set.append(diffs)
    keys = sorted(affected or ())
    layout = S4.Layout(all_windows, set(keys))
    report: dict[str, Any] = {"variant": variant, "seed_sets": seed_sets, "affected_cues": len(keys), "affected": {}}
    for metric in METRICS:
        mean = {k: statistics.fmean(d[k][metric] for d in per_set) for k in keys}
        report["affected"][metric] = {"delta": _work_equal(mean, layout), "bootstrap": S4.bootstrap(mean, layout, reps=10000)}
    full_windows = {k: w for k, w in all_windows.items() if w.meta.scene_id in scenes}
    full_cues = {u["id"] for w in full_windows.values() for u in w.units}
    full_layout = S4.Layout(full_windows, full_cues)
    full = {k: (statistics.fmean(d[k]["accuracy"] for d in per_set) if k in affected else 0.0) for k in full_cues}
    report["full_set_guard"] = {"cues": len(full_cues), "delta": _work_equal(full, full_layout),
                                "bootstrap": S4.bootstrap(full, full_layout, reps=10000)}
    atomic_write_json(root / "summaries" / f"q2-{variant}-{label}.json", report)
    return report
