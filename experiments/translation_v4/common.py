"""v4 paths, set names and seed plans (stdlib only, no side effects)."""

from __future__ import annotations

from pathlib import Path

from experiments.translation_v3.common import REPO, safe_name

DEFAULT_ROOT = REPO / ".local/translation-evaluation/hy30-flow-v4"
SETS = ("dev", "confirm")
CONTROL = "b10-joint"
# dev: each scene is generated with ONE seed; scenes are split into three seed blocks (R1 analysis:
# with ample cues, one seed per scene spread over more scenes beats three seeds on fewer scenes).
DEV_SEEDS = (20261011, 20261012, 20261013)
# Second realization of the same dev blocks, used only for noise calibration of the control.
DEV_REPLICATE_SEEDS = (20261021, 20261022, 20261023)
# confirm: movie cues are supply-limited, so every scene is generated with all three seeds.
CONFIRM_SEEDS = (20261031, 20261032, 20261033)
POLICY_FILE = "decision-policy-v4.json"


def set_dir(root: Path, name: str) -> Path:
    if name not in SETS:
        raise ValueError(f"Unknown set {name!r}; use {SETS}")
    return root / "sets" / name


def evaluation_dir(root: Path, name: str) -> Path:
    """Reference inputs/outputs; confirm is read by reviewer sub-agents and the judge only."""
    return root / "evaluation-only" / name


def scope_name(set_name: str) -> str:
    return safe_name(set_name, "set")
