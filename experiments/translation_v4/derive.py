"""Derive selection pseudo-runs from a multi-sample run (direction 3), without new generation.

From ``<base>__s<seed>__<set>`` whose batches stored N samples (sample k used seed sample_seed(seed, k)),
the derived run ``<name>__s<seed>__<set>`` selects among samples 0..n-1 with ``selector``. It is the
same computation the real recipe ``compose(name, base_parent, candidates=n, selector=...)`` performs,
so the pseudo-run carries that recipe's hash (a locked derived recipe is generated for real on
confirm). n = 1 means "sample 0 only" (a control replicate with the run seed).
Wall clock: per scene, the summed elapsed seconds of the requests of samples < n.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.translation_v3 import recipes as R
from experiments.translation_v3.common import atomic_write_json, read_json, utc_now
from experiments.translation_v3.mbr import select


def derived_recipe(base: R.Recipe, name: str, n: int, selector: str | None) -> R.Recipe:
    parent = R.compose(f"{name}-parent", base, candidates=1, selector=None)
    if n == 1:
        return R.compose(name, parent)
    return R.compose(name, parent, candidates=n, selector=selector)


def derive(root: Path, base_run: Path, name: str, n: int, selector: str | None) -> Path:
    run = read_json(base_run / "run.json")
    base = R.load_recipe(run["recipe"]["name"], root)
    if base.candidates < n:
        raise ValueError(f"{base_run.name} has {base.candidates} samples, cannot derive n={n}")
    recipe = derived_recipe(base, name, n, selector)
    run_id = f"{name}__s{run['seed']}__{run['scope']}"
    out = root / "runs" / run_id
    if (out / "run.json").is_file():
        return out
    if run["completion"]["missing_scene_ids"]:
        raise ValueError(f"{base_run.name} is unfinished")
    total_seconds = 0.0
    for scene_id in run["scene_ids"]:
        row = read_json(base_run / "scenes" / f"{scene_id}.json")
        if row["status"] == "complete":
            translations: dict[str, str] = {}
            for batch in row["batches"]:
                ids = batch["target_ids"]
                failed = {f["sample"] for f in batch.get("failed_samples", [])}
                succeeded = [k for k in range(base.candidates) if k not in failed]  # candidates[i] <-> succeeded[i]
                samples = [batch["candidates"][i] for i, k in enumerate(succeeded) if k < n]
                if not samples:
                    raise ValueError(f"{scene_id}: no successful sample among the first {n}")
                chosen, _ = select(selector, samples, ids) if n > 1 else (dict(samples[0]), None)
                translations.update(chosen)
            seconds = sum(a.get("elapsed_seconds") or 0 for r in row["requests"] if r.get("sample", 0) < n
                          for a in r.get("attempts", []))
            out_row = {"scene_id": scene_id, "status": "complete", "cue_ids": row["cue_ids"],
                       "translations": translations, "run_id": run_id, "derived_seconds": seconds}
        else:
            seconds = 0.0
            out_row = {"scene_id": scene_id, "status": "failed", "cue_ids": row["cue_ids"], "translations": {},
                       "failure": row.get("failure"), "run_id": run_id}
        total_seconds += seconds
        atomic_write_json(out / "scenes" / f"{scene_id}.json", out_row)
    atomic_write_json(out / "run.json", {
        "schema": run["schema"], "run_id": run_id, "recipe": recipe.to_json(), "recipe_hash": recipe.recipe_hash,
        "pseudo": {"kind": "derived-selection", "base_run_id": run["run_id"], "n": n, "selector": selector},
        "seed": run["seed"], "scope": run["scope"], "sources": run["sources"], "scene_ids": run["scene_ids"],
        "created_at_utc": utc_now(), "sessions": [], "resumed": False, "performance_comparable": False,
        "wall_clock_seconds": total_seconds, "completion": run["completion"]})
    return out


__all__ = ["derive", "derived_recipe"]
