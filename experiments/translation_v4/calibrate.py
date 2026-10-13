"""v4 calibration of the measurement on the new dev references (before the policy is frozen).

- reference: the frozen reference itself as a pseudo-candidate on one half-A scene per work
  (expect near-zero accuracy penalty; every major/critical is listed for inspection);
- synthetic: v3 perturbations (negation flip, number change, key-info deletion, adjacent swap) on a
  control run, judging only the perturbed windows (detection goal >= 0.90);
- repeat: the control re-judged with reshuffled packets (replicate 1): judge-only noise;
- aa: control vs the control's replicate seeds (A/A, same scenes, different seed): the full noise
  of a null comparison, compared with its bootstrap SE.
"""

from __future__ import annotations

from pathlib import Path
import statistics
from typing import Any

from experiments.translation_v3 import synth
from experiments.translation_v3.common import atomic_write_json, read_json, utc_now
from experiments.translation_v3.judge import load_judgements

from .reference import load_reference_cues, load_scenes
from .stats4 import Layout, aggregate, bootstrap, recipe_cues, run_cues

REFERENCE_RUN = "reference-v4-self__s0__dev"


def reference_run(root: Path) -> Path:
    """One half-A dev scene per work (lowest scene id), translations = frozen reference zh."""
    run_dir = root / "runs" / REFERENCE_RUN
    if (run_dir / "run.json").is_file():
        return run_dir
    reference = load_reference_cues(root, "dev")
    chosen: dict[str, dict[str, Any]] = {}
    for scene in sorted(load_scenes(root, "dev"), key=lambda s: s["scene_id"]):
        if scene["half"] == "A" and scene["work_id"] not in chosen:
            chosen[scene["work_id"]] = scene
    for scene in chosen.values():
        atomic_write_json(run_dir / "scenes" / f"{scene['scene_id']}.json",
                          {"scene_id": scene["scene_id"], "status": "complete", "cue_ids": [c["id"] for c in scene["cues"]],
                           "translations": {c["id"]: reference[c["id"]]["zh"] for c in scene["cues"]}, "run_id": REFERENCE_RUN})
    atomic_write_json(run_dir / "run.json", {
        "schema": "hy30-flow-v3-run-v1", "run_id": REFERENCE_RUN, "pseudo": {"kind": "reference-self-check"},
        "recipe": {"name": "reference-v4-self"}, "recipe_hash": None, "seed": 0, "scope": "dev", "sources": {},
        "scene_ids": sorted(s["scene_id"] for s in chosen.values()), "created_at_utc": utc_now(), "sessions": [],
        "resumed": False, "completion": {"state": "complete", "missing_scene_ids": [], "failed_scene_ids": []}})
    return run_dir


def level(run_dir: Path, windows: dict) -> dict[str, Any]:
    result = run_cues(run_dir, windows)
    values = result["values"]
    layout = Layout(windows, set(values))
    flagged = [{"cue": c, "errors": e} for c, e in sorted(result["errors"].items()) if any(s != "minor" for _, s in e)]
    return {"cues": len(values), "missing_windows": len(result["missing"]),
            "accuracy": aggregate({c: v["accuracy"] for c, v in values.items()}, layout),
            "major_plus_rate": aggregate({c: v["major_plus"] for c, v in values.items()}, layout),
            "major_or_critical_cues": flagged}


def synthetic_run(root: Path, base_run: Path, windows: dict, target: int = 40) -> tuple[Path, dict[str, Any]]:
    subset = {k: w for k, w in windows.items() if w.meta.split == "dev-A"}
    return synth.make_synthetic(root, base_run, subset, split="dev-A", target=target)


def synthetic_report(root: Path, synth_run: Path, base_run: Path) -> dict[str, Any]:
    manifest = read_json(root / "calibration" / "synthetic" / f"{synth_run.name}.manifest.json")
    return synth.detection_report(manifest, load_judgements(synth_run)[0], load_judgements(base_run)[0])


def repeat_noise(run_dir: Path, windows: dict, replicate: int = 1, reps: int = 10000) -> dict[str, Any]:
    first, second = run_cues(run_dir, windows, 0), run_cues(run_dir, windows, replicate)
    common = sorted(set(first["values"]) & set(second["values"]))
    layout = Layout(windows, set(common))
    diff = {c: second["values"][c]["accuracy"] - first["values"][c]["accuracy"] for c in common}
    flips = [first["values"][c]["major_plus"] != second["values"][c]["major_plus"] for c in common]
    boot = bootstrap(diff, layout, reps=reps)
    per_cue_var = statistics.variance(diff.values()) if len(diff) > 1 else None
    scene = bootstrap(diff, layout, reps=min(reps, 4000), unit="scene")
    return {"cues": len(common), "aggregate_diff": aggregate(diff, layout), "se": boot["overall"]["se"],
            "se_scene_unit": scene["overall"]["se"], "scenes_per_work": {w: len(s) for w, s in layout.works.items()},
            "per_cue_var_of_diff": per_cue_var, "sigma2_judge_per_cue": per_cue_var / 2 if per_cue_var else None,
            "major_flip_rate": statistics.fmean(flips) if flips else None}


def pair_components(cand: dict[str, Any], ctrl: dict[str, Any], windows: dict) -> dict[str, Any]:
    """Per-cue variance of the paired accuracy delta and the clustered SE for this pair."""
    common = sorted(set(cand["values"]) & set(ctrl["values"]))
    layout = Layout(windows, set(common))
    delta = {c: cand["values"][c]["accuracy"] - ctrl["values"][c]["accuracy"] for c in common}
    boot = bootstrap(delta, layout, reps=4000)
    scene = bootstrap(delta, layout, reps=4000, unit="scene")
    return {"cues": len(common), "delta": aggregate(delta, layout), "se": boot["overall"]["se"],
            "se_scene_unit": scene["overall"]["se"], "windows": len(layout.window_cues),
            "per_cue_var": statistics.variance(delta.values()),
            "control_level": aggregate({c: ctrl["values"][c]["accuracy"] for c in common}, layout)}


def save(root: Path, name: str, report: dict[str, Any]) -> Path:
    path = root / "calibration" / f"{name}.json"
    atomic_write_json(path, report | {"written_at_utc": utc_now()})
    return path


__all__ = ["reference_run", "level", "synthetic_run", "synthetic_report", "repeat_noise", "pair_components",
           "recipe_cues", "save"]
