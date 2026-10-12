"""MDE derivation for decision-policy-v4 from the dev calibration (no candidate scores used).

Per-cue paired variance of the accuracy delta with S seeds per cue:
    V(S) = tau + noise / S
noise = per-cue variance of the A/A delta (control vs its replicate seeds; one seed each side),
tau   = per-cue variance of a real pair's delta (c0 vs control, one seed each side) minus noise.
Work-equal, 50:50 aggregation with n_w cues in work w (K_s series works, K_m movie works):
    Var = 0.25 * (sum_s V/n_w / K_s^2 + sum_m V/n_w / K_m^2) * deff
deff = (measured scene-bootstrap SE)^2 / analytic variance of the bridge pair on dev (scene clustering).
MDE (one-sided alpha, power 0.8) = (z_{1-alpha} + z_{0.8}) * SE.
"""

from __future__ import annotations

from statistics import NormalDist
from typing import Any

Z = NormalDist().inv_cdf


def analytic_var(per_cue_var: float, cues_by_work: dict[str, int], category_of: dict[str, str]) -> float:
    total = 0.0
    for category in ("anime_series", "animation_movie"):
        works = [w for w in cues_by_work if category_of[w] == category]
        total += sum(per_cue_var / cues_by_work[w] for w in works) / len(works) ** 2
    return 0.25 * total


def mde(se: float, alpha: float, power: float = 0.8) -> float:
    return (Z(1 - alpha) + Z(power)) * se


def design_table(tau: float, noise: float, deff: float, layouts: dict[str, tuple[dict[str, int], dict[str, str], int]],
                 alphas: dict[str, float]) -> dict[str, Any]:
    """layouts: name -> (cues_by_work, category_of, seeds per cue)."""
    rows = {}
    for name, (cues, category_of, seeds) in layouts.items():
        v = tau + noise / seeds
        se = (analytic_var(v, cues, category_of) * deff) ** 0.5
        rows[name] = {"seeds_per_cue": seeds, "per_cue_var": v, "se": se,
                      "mde80": {label: mde(se, alpha) for label, alpha in alphas.items()}}
    return rows
