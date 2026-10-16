"""v6 cue-level metrics by error category and within-work contrasts with a scene bootstrap.

Per cue and run: accuracy penalty (minor 1 / major 5 / critical 10) split into the categories this
round tracks (wrong-referent, mistranslation, negation-number-condition, other accuracy). A cue of a
terminally failed scene counts as accuracy 10 in "other" (undelivered), as in v3/v4. A recipe's value
for a cue is the mean over its runs that contain the cue.

Contrast of two cue classes (e.g. minority vs clean): inside each work, mean(class A) - mean(class B)
over its cues; works with both classes present are averaged with equal weight inside each category
(series / movie); overall = 50:50 when both categories exist. The interval resamples scenes inside
each work (works fixed), as the v6 pre-registration check did.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import random
import statistics
from typing import Any, Callable, Iterable

from experiments.translation_v3.data import ReferenceWindow
from experiments.translation_v3.judge import ACCURACY
from experiments.translation_v3.stats import CATEGORIES, PENALTY, UNDELIVERED_CUE_PENALTY
from experiments.translation_v4.stats4 import run_cues

TRACKED = ("wrong-referent", "mistranslation", "negation-number-condition")
METRICS = ("accuracy", *TRACKED, "other")
BOOTSTRAP_SEED = "v6-scene-bootstrap-20261016"


def cue_metrics(errors: Iterable[tuple[str, str]], undelivered: bool = False) -> dict[str, float]:
    """errors: (category, severity) of one cue in one run, accuracy and fluency mixed."""
    row = dict.fromkeys(METRICS, 0.0)
    if undelivered:
        row["accuracy"] = row["other"] = float(UNDELIVERED_CUE_PENALTY)
        return row
    for category, severity in errors:
        if category not in ACCURACY:
            continue
        points = float(PENALTY[severity])
        row["accuracy"] += points
        row[category if category in TRACKED else "other"] += points
    return row


def run_metrics(run_dir: Path, windows: dict[str, ReferenceWindow], replicate: int = 0) -> dict[str, Any]:
    result = run_cues(run_dir, windows, replicate)
    values = {}
    for cue in result["values"]:
        # run_cues lists judge errors for every judged cue; only undelivered cues have no entry.
        values[cue] = cue_metrics(result["errors"].get(cue, ()), undelivered=cue not in result["errors"])
    return {"values": values, "missing": result["missing"], "undelivered": result["undelivered"],
            "failed_scenes": result["failed_scenes"]}


def mean_over_runs(per_run: list[dict[str, dict[str, float]]]) -> dict[str, dict[str, float]]:
    rows: dict[str, list[dict[str, float]]] = defaultdict(list)
    for values in per_run:
        for cue, row in values.items():
            rows[cue].append(row)
    return {cue: {m: statistics.fmean(r[m] for r in rs) for m in METRICS} for cue, rs in rows.items()}


# --- class contrasts ----------------------------------------------------------------------------

class SceneTable:
    """Per scene: class -> (count, metric sums); plus work and category of each scene."""

    def __init__(self, labels: dict[str, str], values: dict[str, dict[str, float]],
                 scene_of: dict[str, str], work_of: dict[str, str], category_of: dict[str, str]):
        self.cells: dict[str, dict[str, list[float]]] = defaultdict(dict)
        for cue, label in labels.items():
            if cue not in values:
                continue
            cell = self.cells[scene_of[cue]].setdefault(label, [0.0] + [0.0] * len(METRICS))
            cell[0] += 1
            for k, m in enumerate(METRICS, 1):
                cell[k] += values[cue][m]
        self.works: dict[str, list[str]] = defaultdict(list)
        for scene in sorted(self.cells):
            self.works[work_of[scene]].append(scene)
        self.category_of = category_of

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for work, scenes in self.works.items():
            for scene in scenes:
                for label, cell in self.cells[scene].items():
                    out[self.category_of[work]][label] += int(cell[0])
        return {c: dict(v) for c, v in out.items()}


def _contrast(table: SceneTable, draw: dict[str, list[str]], a: str, b: str,
              stat: Callable[[list[float], list[float]], float | None]) -> dict[str, float | None]:
    per_category: dict[str, list[float]] = defaultdict(list)
    for work, scenes in draw.items():
        sums = {a: [0.0] * (len(METRICS) + 1), b: [0.0] * (len(METRICS) + 1)}
        for scene in scenes:
            for label in (a, b):
                cell = table.cells[scene].get(label)
                if cell:
                    sums[label] = [x + y for x, y in zip(sums[label], cell)]
        if sums[a][0] and sums[b][0]:
            value = stat(sums[a], sums[b])
            if value is not None:
                per_category[table.category_of[work]].append(value)
    result = {c: (statistics.fmean(per_category[c]) if per_category[c] else None) for c in CATEGORIES}
    result["overall"] = (statistics.fmean([result[c] for c in CATEGORIES])
                         if all(result[c] is not None for c in CATEGORIES) else None)
    return result


def mean_diff(metric: str) -> Callable[[list[float], list[float]], float]:
    k = METRICS.index(metric) + 1
    return lambda sa, sb: sa[k] / sa[0] - sb[k] / sb[0]


def share_diff(metric: str) -> Callable[[list[float], list[float]], float | None]:
    """Difference of metric's share of the accuracy penalty (None when a side has no penalty)."""
    k, acc = METRICS.index(metric) + 1, METRICS.index("accuracy") + 1
    return lambda sa, sb: (sa[k] / sa[acc] - sb[k] / sb[acc]) if sa[acc] and sb[acc] else None


def contrast(table: SceneTable, a: str, b: str, stat: Callable[[list[float], list[float]], float | None], *,
             reps: int = 2000, seed: str = BOOTSTRAP_SEED) -> dict[str, Any]:
    point = _contrast(table, table.works, a, b, stat)
    rng = random.Random(f"{seed}|{a}|{b}")
    samples: dict[str, list[float]] = {k: [] for k in (*CATEGORIES, "overall")}
    for _ in range(reps):
        draw = {w: [s[rng.randrange(len(s))] for _ in s] for w, s in table.works.items()}
        value = _contrast(table, draw, a, b, stat)
        for key in samples:
            if value[key] is not None:
                samples[key].append(value[key])
    out = {}
    for key in samples:
        xs = sorted(samples[key])
        if point[key] is None or not xs:
            out[key] = {"point": point[key]}
            continue
        q = lambda p: xs[min(len(xs) - 1, int(p * (len(xs) - 1)))]
        out[key] = {"point": point[key], "ci90": [q(0.05), q(0.95)], "p_le_0": sum(x <= 0 for x in xs) / len(xs)}
    return out
