"""Synthetic known-error pseudo-runs for judge sensitivity calibration (plan 4.2 step 2)."""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any, Callable

from .common import atomic_write_json, read_json, utc_now
from .data import ReferenceWindow
from .judge import ACCURACY

SYNTH_VERSION = "synthetic-perturbations-v1"
SYNTH_SEED = "v3-synth-20261010"
KINDS = ("negation_flip", "number_change", "key_info_deletion", "adjacent_swap")
_NUMERAL_SWAP = {"一": "三", "二": "五", "两": "三", "三": "五", "四": "七", "五": "八", "六": "九",
                 "七": "二", "八": "四", "九": "六", "十": "百", "百": "千", "千": "万", "万": "千"}
_NOT_NUMBER_AFTER_YI = "起下样定直点切般边些旦向会天生"


def negation_flip(text: str) -> str | None:
    for negator in ("不", "没", "别"):
        index = text.find(negator)
        if index >= 0 and len(text) > 1:
            return text[:index] + text[index + 1:]
    for verb in ("是", "要", "会", "能"):
        index = text.find(verb)
        if index >= 0:
            return text[:index] + "不" + text[index:]
    return None


def number_change(text: str) -> str | None:
    match = re.search(r"\d+", text)
    if match:
        return text[:match.start()] + str(int(match.group()) + 1) + text[match.end():]
    for index, char in enumerate(text):
        if char in _NUMERAL_SWAP:
            if char == "一" and (index + 1 < len(text) and text[index + 1] in _NOT_NUMBER_AFTER_YI
                                 or index > 0 and text[index - 1] in "统唯万第"):
                continue
            return text[:index] + _NUMERAL_SWAP[char] + text[index + 1:]
    return None


def key_info_deletion(text: str) -> str | None:
    segments = [part for part in re.split(r"[，、,\s]+", text) if part.strip()]
    if len(segments) >= 2:
        segments.remove(max(segments, key=len))
        result = "，".join(segments)
        return result if result != text else None
    if len(text) >= 6:
        return text[: len(text) // 2]
    return None


TEXT_PERTURBATIONS: dict[str, Callable[[str], str | None]] = {
    "negation_flip": negation_flip, "number_change": number_change, "key_info_deletion": key_info_deletion}


def make_synthetic(root: Path, base_run_dir: Path, reference: dict[str, ReferenceWindow], *, split: str = "screen-a",
                   target: int = 40) -> tuple[Path, dict[str, Any]]:
    """Copy the base run's complete scenes with ~``target`` perturbations, one per window."""
    base = read_json(base_run_dir / "run.json")
    if base["completion"]["missing_scene_ids"]:
        raise ValueError("Base run is unfinished")
    recipe, seed = base["recipe"]["name"], base["seed"]
    run_id = f"synth-{recipe}-s{seed}__s0__{base['scope']}"
    out = root / "runs" / run_id
    if (out / "run.json").exists():
        raise FileExistsError(f"{out} already exists; synthetic runs are immutable")
    scenes = {path.stem: read_json(path) for path in sorted((base_run_dir / "scenes").glob("*.json"))}
    translations = {key: value for row in scenes.values() if row["status"] == "complete"
                    for key, value in row["translations"].items()}
    windows = sorted(key for key, window in reference.items() if window.meta.split == split
                     and window.meta.scene_id in scenes and all(u["id"] in translations for u in window.units))
    rng = random.Random(f"{SYNTH_SEED}|{split}")
    rng.shuffle(windows)
    perturbations: list[dict[str, Any]] = []
    for number, window_id in enumerate(windows):
        if len(perturbations) >= target:
            break
        ids = [u["id"] for u in reference[window_id].units]
        start = number % len(KINDS)
        for kind in KINDS[start:] + KINDS[:start]:
            order = ids[:]
            rng.shuffle(order)
            change = None
            if kind == "adjacent_swap":
                pairs = [(a, b) for a, b in zip(ids, ids[1:]) if translations[a] != translations[b]]
                if pairs:
                    a, b = pairs[rng.randrange(len(pairs))]
                    change = {a: translations[b], b: translations[a]}
            else:
                for key in order:
                    new = TEXT_PERTURBATIONS[kind](translations[key])
                    if new and new.strip() and new != translations[key]:
                        change = {key: new}
                        break
            if change:
                perturbations.append({"window_id": window_id, "kind": kind, "cue_ids": sorted(change),
                                      "original": {k: translations[k] for k in change}, "perturbed": change})
                translations.update(change)
                break
    for name, row in scenes.items():
        if row["status"] == "complete":
            row = dict(row, translations={k: translations[k] for k in row["translations"]}, run_id=run_id)
        atomic_write_json(out / "scenes" / f"{name}.json", row)
    run = {"schema": base["schema"], "run_id": run_id, "pseudo": {"kind": "synthetic", "version": SYNTH_VERSION,
           "base_run_id": base["run_id"], "split": split}, "recipe": base["recipe"], "recipe_hash": base["recipe_hash"],
           "seed": 0, "scope": base["scope"], "sources": base["sources"], "scene_ids": base["scene_ids"],
           "created_at_utc": utc_now(), "sessions": [], "resumed": False, "completion": base["completion"]}
    atomic_write_json(out / "run.json", run)
    manifest = {"version": SYNTH_VERSION, "run_id": run_id, "base_run_id": base["run_id"], "split": split,
                "created_at_utc": utc_now(), "count": len(perturbations),
                "by_kind": {k: sum(p["kind"] == k for p in perturbations) for k in KINDS},
                "perturbations": perturbations}
    # Ground truth lives outside the run directory so no judge input can reach it.
    atomic_write_json(root / "calibration" / "synthetic" / f"{run_id}.manifest.json", manifest)
    return out, manifest


def _accuracy_errors(cue: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [e for e in (cue or {}).get("errors", []) if e["category"] in ACCURACY]


def detection_report(manifest: dict[str, Any], synthetic: dict[str, dict[str, Any]],
                     base: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Detection = an accuracy error on any perturbed cue; false positives on untouched scored cues."""
    rows = []
    for item in manifest["perturbations"]:
        judged = synthetic.get(item["window_id"])
        if judged is None:
            rows.append({**{k: item[k] for k in ("window_id", "kind", "cue_ids")}, "judged": False})
            continue
        errors = [e for key in item["cue_ids"] for e in _accuracy_errors(judged.get(key))]
        rows.append({**{k: item[k] for k in ("window_id", "kind", "cue_ids")}, "judged": True,
                     "detected": bool(errors),
                     "detected_major_plus": any(e["severity"] in ("major", "critical") for e in errors),
                     "categories": sorted({e["category"] for e in errors})})
    judged_rows = [row for row in rows if row["judged"]]
    perturbed = {(p["window_id"], key) for p in manifest["perturbations"] for key in p["cue_ids"]}
    false_positive, new_vs_base, untouched = 0, 0, 0
    for window_id in {p["window_id"] for p in manifest["perturbations"]}:
        for key, cue in synthetic.get(window_id, {}).items():
            if (window_id, key) in perturbed:
                continue
            untouched += 1
            if _accuracy_errors(cue):
                false_positive += 1
                if base is not None and not _accuracy_errors(base.get(window_id, {}).get(key)):
                    new_vs_base += 1
    by_kind = {}
    for kind in KINDS:
        subset = [row for row in judged_rows if row["kind"] == kind]
        by_kind[kind] = {"n": len(subset), "detected": sum(row["detected"] for row in subset)}
    n = len(judged_rows)
    return {"version": SYNTH_VERSION, "perturbations": len(rows), "judged": n,
            "detection_rate": sum(r["detected"] for r in judged_rows) / n if n else None,
            "detection_rate_major_plus": sum(r["detected_major_plus"] for r in judged_rows) / n if n else None,
            "by_kind": by_kind, "untouched_cues_in_perturbed_windows": untouched,
            "accuracy_errors_on_untouched": false_positive,
            "new_accuracy_errors_vs_base": new_vs_base if base is not None else None,
            "targets": {"detection_rate_goal": 0.9, "stop_below": 0.8}, "rows": rows}
