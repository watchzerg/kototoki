"""v10: Q0 (qwen-wide) exploration (docs/research/2026-10-21-q0-exploration-v10.md).

Same layout and commands as v9 (``v9.py`` with ``root=V10_ROOT``): ``runs/<recipe>__s<seed>__dev``,
``smoke/``, ``checks/``, ``summaries/``; v10 artefacts go to stage subdirectories (``A2/``, ``D/`` ...).

* A1 replicates v9 on the repeat seeds: ``qwen-wide`` and ``dp10-cut`` are generated fresh at 20261021-23.
* Later arms compare against Q0 on the main seeds: ``copy_control`` copies the v9 ``qwen-wide`` translations
  (``run.json`` + ``scenes/``, no judgements) so the control is re-judged in the same period (v7 §2.1).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from experiments.translation_v3.common import REPO, atomic_write_json, read_json

from . import q2, v9

V10_ROOT = REPO / ".local/q0-exploration-v10"
Q0 = "qwen-wide"
H0 = "dp10-cut"
MAIN_SEEDS = v9.MAIN_SEEDS
REPEAT_SEEDS = (20261021, 20261022, 20261023)


def copy_control(seed: int, *, root: Path = V10_ROOT, source: Path = v9.V9_ROOT, recipe: str = Q0) -> Path:
    """Copy a v9 run's translations (not its judgements) for same-period re-judging."""
    src, dst = q2.run_dir(source, recipe, seed), q2.run_dir(root, recipe, seed)
    if (dst / "run.json").is_file():
        return dst
    run = read_json(src / "run.json")
    shutil.copytree(src / "scenes", dst / "scenes")
    atomic_write_json(dst / "run.json", run | {"copied_from": str(src.relative_to(REPO))})
    return dst


def summary(report: dict[str, Any]) -> dict[str, Any]:
    """Compact view of a ``v9.compare`` report: Δ and CI90 per category for the metrics the v10 gates read."""
    out: dict[str, Any] = {"variant": report.get("variant"), "against": report.get("against"),
                           "seeds": report.get("seeds"), "cues": report.get("cues")}
    for metric in ("accuracy", "unnatural", "wrong-referent", "mistranslation", "addition", "omission", "register",
                   "grammar", "major_plus", "critical"):
        block = report["full"].get(metric)
        if not block:
            continue
        out[metric] = {c: [round(block["delta"][c], 4) if block["delta"].get(c) is not None else None,
                           [round(x, 4) for x in (block["bootstrap"].get(c) or {}).get("ci90") or []]]
                       for c in ("anime_series", "animation_movie")}
    return out


def write_recipe(name: str, base: str, *, root: Path = V10_ROOT, comment: str = "", **fields: Any) -> Path:
    """``<root>/recipes/<name>.json`` ({"name", "base", ...fields}); refuses to change an existing file."""
    import json
    from experiments.translation_v3.recipes import load_recipe
    path = root / "recipes" / f"{name}.json"
    data = {"name": name, "base": base, **({"comment": comment} if comment else {}), **fields}
    if path.is_file():
        if read_json(path) != data:
            raise ValueError(f"{path} exists with different content")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    load_recipe(name, root)  # validates
    return path
