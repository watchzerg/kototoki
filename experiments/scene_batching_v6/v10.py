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
