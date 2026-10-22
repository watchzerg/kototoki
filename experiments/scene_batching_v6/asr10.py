"""v10 stage D: Q0 arms on the product ASR source of HF II / III (docs/research/2026-10-21-q0-exploration-v10.md §4.4).

Translations: ``translation_v3 translate-srt`` on the product w0 ``ja.srt`` of quality_v5 step 01 (the source of
the v5 step 02 units and of the product name tables), seeds 20261051-53, root ``<v10>/D/root`` (arm recipes in
``recipes/``), outputs ``<v10>/D/zh/<arm>/<film>.s<seed>.zh.srt``. Replacement arms (``<arm>+rep``) are the
product chain: ``name_consistency.apply_table`` with its default parameters and the product ``name-table.json``.

Evaluation reuses quality_v5 step 02 unchanged: its units (reference / product cue overlap components with the
Japanese CER bucket), the ``v5-asr-pairwise-v1`` judge (``asr_source.judge``, reference Japanese + context, two
blind Chinese candidates) and ``asr_source.collect``. Here both candidates come from the ASR source: x = the
control arm, y = the candidate arm, same seed per item (seed index rotates over the sampled units). The unit
sample of a bucket is the same for every comparison (seeded by bucket only); the A/B sides are drawn per
comparison. Δ = mean(py − px) per bucket (candidate − control), item bootstrap CI90.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from experiments.quality_v5 import asr_source as A
from experiments.translation_v3.common import REPO, atomic_write_json

from .v10 import V10_ROOT

D_ROOT = V10_ROOT / "D"
SEEDS = (20261051, 20261052, 20261053)
V5 = REPO / ".local/quality-exploration-v5"
FILMS = {
    "HF-II": {"units": V5 / "02/units/hf-ii.jsonl",
              "ja": V5 / "01/out-w0/FateStay Night Heaven’s Feel II.ja.srt",
              "table": REPO / ".local/name-consistency-product/after/HF-II/name-table.json"},
    "HF-III": {"units": V5 / "02/units/hf-iii.jsonl",
               "ja": V5 / "01/out-w0/FateStay Night Heaven's Feel III.ja.srt",
               "table": REPO / ".local/name-consistency-product/after/HF-III/name-table.json"},
}
UNIT_FILM = {"hf-ii": "HF-II", "hf-iii": "HF-III"}
JUDGED = ("exact", "light", "heavy")
NAME_ERROR = re.compile(r"人名|名字|姓名|称呼|译名|专名|角色名|昵称|音译")


def zh_path(arm: str, film: str, seed: int, root: Path = D_ROOT) -> Path:
    return root / "zh" / arm / f"{film}.s{seed}.zh.srt"


def name_tables() -> dict[str, list[dict[str, str]]]:
    """Product tables as {work: [{source: form.ja, translation: form.zh}]} (every form of every entity)."""
    out = {}
    for film, paths in FILMS.items():
        table = json.loads(paths["table"].read_text(encoding="utf-8"))
        rows, seen = [], set()
        for entity in table["entries"]:
            for form in entity["forms"]:
                if form["ja"] not in seen and form["ja"].strip() and form["zh"].strip():
                    seen.add(form["ja"])
                    rows.append({"source": form["ja"], "translation": form["zh"]})
        out[film] = rows
    return out


def load_units() -> dict[str, list[dict]]:
    """quality_v5 units keyed by their own film id (hf-ii / hf-iii), as ``asr_source.judge`` expects."""
    return {u[0]["film"]: u for u in (A.read_units(p["units"]) for p in FILMS.values())}


def arm_texts(arm: str, root: Path = D_ROOT) -> dict[str, list[list[str]]]:
    """unit film id -> per unit, per seed: the arm's Chinese of the unit's product cues (joined like v5)."""
    out = {}
    for unit_film, units in load_units().items():
        film = UNIT_FILM[unit_film]
        docs = [A.read_srt(zh_path(arm, film, s, root)) for s in SEEDS]
        n = len(A.read_srt(FILMS[film]["ja"]))
        if any(len(d) != n for d in docs):
            raise ValueError(f"{arm} {film}: cue count differs from the product ja.srt ({n})")
        out[unit_film] = [[" ".join(d[j]["text"] for j in u["asr_ids"]) for d in docs] for u in units]
    return out


def sample_units(units: dict[str, list[dict]], quotas: dict[str, int]) -> list[tuple[str, int, str]]:
    """(unit film, unit index, bucket); the same draw for every comparison (seeded by bucket)."""
    pool = [(f, i, u["bucket"]) for f, us in sorted(units.items()) for i, u in enumerate(us)]
    chosen = []
    for bucket in JUDGED:
        rows = [p for p in pool if p[2] == bucket]
        random.Random(f"v10-D-{bucket}").shuffle(rows)
        chosen += rows if quotas.get(bucket) == "all" else rows[:quotas.get(bucket, 0)]
    return chosen


def plan(x_arm: str, y_arm: str, quotas: dict[str, Any], *, root: Path = D_ROOT) -> Path:
    """Write the judge plan for y (candidate) vs x (control); plans are written once."""
    name = f"{y_arm}-vs-{x_arm}"
    path = root / "judge" / name / "plan.json"
    if path.exists():
        raise SystemExit(f"{path} exists; plans are written once")
    units = load_units()
    tx, ty = arm_texts(x_arm, root), arm_texts(y_arm, root)
    rng = random.Random(f"v10-D-sides-{name}")
    items = []
    for n, (film, i, bucket) in enumerate(sample_units(units, quotas)):
        k = n % len(SEEDS)
        x, y = tx[film][i][k], ty[film][i][k]
        flip = rng.random() < 0.5
        items.append({"id": f"q{n + 1:04d}", "arm": "main", "bucket": bucket, "film": film, "unit": i,
                      "seed_index": k, "x": x, "y": y, "y_label": y_arm, "x_label": x_arm,
                      "a": y if flip else x, "b": x if flip else y, "x_side": "B" if flip else "A"})
    rng.shuffle(items)
    atomic_write_json(path, {"profile": A.PROFILE, "x_arm": x_arm, "y_arm": y_arm, "quota": quotas,
                             "seeds": list(SEEDS), "items": items})
    return path


def judge(name: str, *, root: Path = D_ROOT) -> int:
    folder = root / "judge" / name
    return A.judge(folder / "plan.json", load_units(), folder / "packets")


def _boot(rows: list[dict], value=lambda r: r["py"] - r["px"], draws: int = 4000,
          seed: str = "v10-D-boot") -> list[float] | None:
    if not rows:
        return None
    rng = random.Random(seed)
    stats = sorted(sum(value(r) for r in (rng.choice(rows) for _ in rows)) / len(rows) for _ in range(draws))
    return [stats[int(0.05 * draws)], stats[int(0.95 * draws) - 1]]


def _names(errors: list[dict]) -> int:
    return sum(e["category"] == "terminology" or bool(NAME_ERROR.search(e.get("note") or "")) for e in errors)


def estimate(name: str, *, root: Path = D_ROOT) -> dict[str, Any]:
    folder = root / "judge" / name
    rows = A.collect(folder / "plan.json", folder / "packets")
    report: dict[str, Any] = {"comparison": name, "judged": len(rows), "delta": "py - px (candidate - control)",
                              "buckets": {}}
    for bucket in (*JUDGED, "light+heavy", "all"):
        rs = [r for r in rows if bucket == "all" or r["bucket"] == bucket
              or (bucket == "light+heavy" and r["bucket"] in ("light", "heavy"))]
        if not rs:
            continue
        cat = lambda side, c: sum(e["category"] == c for r in rs for e in r[side])  # noqa: E731
        sev = lambda side, s: sum(e["severity"] == s for r in rs for e in r[side])  # noqa: E731
        report["buckets"][bucket] = {
            "n": len(rs), "mean_px": A.mean([r["px"] for r in rs]), "mean_py": A.mean([r["py"] for r in rs]),
            "delta": A.mean([r["py"] - r["px"] for r in rs]), "ci90": _boot(rs, seed=f"v10-D-boot-{bucket}"),
            "pref_control": A.mean([r["winner"] == "x" for r in rs]),
            "pref_candidate": A.mean([r["winner"] == "y" for r in rs]),
            "tie": A.mean([r["winner"] == "tie" for r in rs]),
            "critical": [sev("x_errors", "critical"), sev("y_errors", "critical")],
            "addition": [cat("x_errors", "addition"), cat("y_errors", "addition")],
            "name_errors": [sum(_names(r["x_errors"]) for r in rs), sum(_names(r["y_errors"]) for r in rs)],
            "name_error_delta_ci90": _boot(rs, lambda r: _names(r["y_errors"]) - _names(r["x_errors"]),
                                           seed=f"v10-D-names-{bucket}"),
            "by_film_delta": {f: A.mean([r["py"] - r["px"] for r in rs if r["film"] == f])
                              for f in sorted({r["film"] for r in rs})}}
    atomic_write_json(folder / "estimate.json", report)
    return report


def inconsistency(arms: list[str], *, root: Path = D_ROOT) -> dict[str, Any]:
    """``apply_table measure``口径 (quality_v5 consistency on the whole film), per arm: film x seed and mean."""
    from experiments.quality_v5 import consistency
    out: dict[str, Any] = {}
    for arm in arms:
        rows = {}
        for film, paths in FILMS.items():
            ja = consistency.read_srt_texts(paths["ja"])
            for seed in SEEDS:
                zh = consistency.read_srt_texts(zh_path(arm, film, seed, root))
                rows[f"{film}.s{seed}"] = consistency.work_summary(consistency.analyze_work(list(zip(ja, zh))))
        out[arm] = {"runs": rows, "mean_inconsistency": A.mean([r["inconsistency"] for r in rows.values() if r["inconsistency"] is not None])}
    atomic_write_json(root / "inconsistency.json", out)
    return out


def product_timing(recipes: tuple[str, ...] = ("dp10-cut", "qwen-wide"), *, root: Path = D_ROOT) -> dict[str, Any]:
    """v9 §8 item 6 (offline): pack sizes and visible neighbours of each recipe on the product ja.srt timing."""
    from collections import Counter
    from experiments.translation_flow import srt
    from experiments.translation_v3.batching import build_batches
    from experiments.translation_v3.data import Cue, Scene
    from experiments.translation_v3.recipes import load_recipe
    out: dict[str, Any] = {}
    for film, paths in FILMS.items():
        document = srt.read_srt(paths["ja"])
        scene = Scene(film, tuple(Cue(c.id, c.text, c.start_ms / 1000, c.end_ms / 1000) for c in document.cues))
        for name in recipes:
            batches = build_batches(scene, load_recipe(name, root))
            targets = [len(b.target_ids) for b in batches]
            before = [len(b.before_ids) for b in batches]
            after = [len(b.after_ids) for b in batches]
            out.setdefault(name, {})[film] = {
                "cues": len(scene.cues), "packs": len(batches), "mean_targets": A.mean(targets),
                "targets_histogram": dict(sorted(Counter(targets).items())),
                "mean_before": A.mean(before), "mean_after": A.mean(after),
                "mean_visible": A.mean([t + b + a for t, b, a in zip(targets, before, after)])}
    atomic_write_json(root / "product-timing.json", out)
    return out
