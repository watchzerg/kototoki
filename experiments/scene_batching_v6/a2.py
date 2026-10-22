"""v10 A2: non-LLM corroboration of the Q0 − H0 judge Δ and the blind reading sheet (§4.1).

* ``similarity``: per cue chrF (``translation_v3.mbr.chrf``) and bge-m3 cosine (CLS, L2-normalised, the v5
  ``mbr_semantic`` encoder) of each arm's Chinese against the reference Chinese; paired Δ = Q0 − H0 (positive =
  Q0 closer to the reference), work-equal by category with the window bootstrap, per seed set (A1 repeat seeds
  on the v10 root, v9 main seeds on the v9 root, read-only) and the mean of the two sets. Agreement: among cues
  whose judge accuracy Δ is non-zero, the share whose similarity Δ has the opposite sign (judge penalty down =
  similarity up). The encoder runs on CPU (A2 is an offline ticket).
* ``blind_sheet``: main seeds (v9 judgements only pick the windows): per category the 15 judge windows with the
  largest |Σ accuracy Δ| and 15 random others; the two translations appear as X / Y in a random order, no
  source; the key goes to a separate JSON. Both files stay under ``.local`` (transcript content).
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Callable

from experiments.translation_v3.common import atomic_write_json, read_json
from experiments.translation_v3.generate import load_run_translations
from experiments.translation_v3.mbr import chrf
from experiments.translation_v4 import evaluate as E
from experiments.translation_v4 import stats4 as S4
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT

from . import q2, v9
from .v10 import H0, MAIN_SEEDS, Q0, REPEAT_SEEDS, V10_ROOT

MODEL_DIR = Path(".local/models/embedding-v5/bge-m3")
SHEET_SEED = "v10-a2-blind-20261022"
PER_CATEGORY = 15


def cpu_encoder(model_dir: Path = MODEL_DIR) -> Callable[[list[str]], list[list[float]]]:
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModel.from_pretrained(model_dir, torch_dtype=torch.float32).eval()

    def encode(texts: list[str]) -> list[list[float]]:
        out = []
        with torch.inference_mode():
            for start in range(0, len(texts), 64):
                batch = tokenizer(texts[start:start + 64], padding=True, truncation=True, max_length=128,
                                  return_tensors="pt")
                cls = model(**batch).last_hidden_state[:, 0]
                out += torch.nn.functional.normalize(cls, dim=-1).tolist()
        return out
    return encode


def seed_sets() -> list[tuple[str, Path, tuple[int, ...]]]:
    return [("a1-repeat", V10_ROOT, REPEAT_SEEDS), ("v9-main", v9.V9_ROOT, MAIN_SEEDS)]


def judge_rows(root: Path, arm: str, seed: int, windows: dict) -> dict[str, float]:
    return {k: r["accuracy"] for k, r in v9.arm_rows(q2.run_dir(root, arm, seed), windows)["values"].items()}


def collect(windows: dict, only: str | None = None) -> dict[str, dict[str, Any]]:
    """set -> {"tr": {arm: {cue: zh}}, "judge": {arm: {cue: accuracy}}}"""
    out = {}
    for name, root, seeds in seed_sets():
        if only and name != only:
            continue
        tr: dict[str, dict[str, str]] = {Q0: {}, H0: {}}
        judge: dict[str, dict[str, float]] = {Q0: {}, H0: {}}
        for seed in seeds:
            scenes = set(read_json(q2.run_dir(root, Q0, seed) / "run.json")["scene_ids"])
            sw = {k: w for k, w in windows.items() if w.meta.scene_id in scenes}
            for arm in (Q0, H0):
                tr[arm].update(load_run_translations(q2.run_dir(root, arm, seed))[0])
                judge[arm].update(judge_rows(root, arm, seed, sw))
        out[name] = {"tr": tr, "judge": judge}
    return out


def similarity(encode: Callable[[list[str]], list[list[float]]] | None = None, *, out_root: Path = V10_ROOT) -> dict[str, Any]:
    windows = E.reference_for(V4_ROOT, q2.SET)
    ref = {u["id"]: u["zh"] for w in windows.values() for u in w.units}
    data = collect(windows)
    encode = encode or cpu_encoder()
    texts = sorted({ref[k] for k in ref} | {t for d in data.values() for arm in d["tr"].values() for t in arm.values()})
    vectors = dict(zip(texts, encode(texts)))

    def cos(a: str, b: str) -> float:
        return sum(x * y for x, y in zip(vectors[a], vectors[b]))
    report: dict[str, Any] = {"encoder": "bge-m3 cls l2 cpu fp32 max_length 128", "chrf": "chrf1-n4 (mbr.chrf)",
                              "delta": "Q0 - H0 similarity (positive = Q0 closer to the reference)", "sets": {}}
    per_set: dict[str, dict[str, dict[str, float]]] = {}
    for name, d in data.items():
        keys = sorted(set(ref) & d["tr"][Q0].keys() & d["tr"][H0].keys() & d["judge"][Q0].keys() & d["judge"][H0].keys())
        layout = S4.Layout(windows, set(keys))
        deltas = {"chrf": {k: chrf(d["tr"][Q0][k], ref[k]) - chrf(d["tr"][H0][k], ref[k]) for k in keys},
                  "bge_m3": {k: cos(d["tr"][Q0][k], ref[k]) - cos(d["tr"][H0][k], ref[k]) for k in keys}}
        judge = {k: d["judge"][Q0][k] - d["judge"][H0][k] for k in keys}
        per_set[name] = deltas | {"judge": judge}
        row: dict[str, Any] = {"cues": len(keys)}
        for metric, values in deltas.items():
            row[metric] = {"Q0": S4.aggregate({k: (chrf if metric == "chrf" else cos)(d["tr"][Q0][k], ref[k]) for k in keys}, layout),
                           "H0": S4.aggregate({k: (chrf if metric == "chrf" else cos)(d["tr"][H0][k], ref[k]) for k in keys}, layout),
                           "delta": S4.aggregate(values, layout), "bootstrap": S4.bootstrap(values, layout, reps=2000),
                           "agreement": agreement(values, judge)}
        row["judge_accuracy_delta"] = S4.aggregate(judge, layout)
        report["sets"][name] = row
    common = sorted(set.intersection(*(set(v["judge"]) for v in per_set.values())))
    layout = S4.Layout(windows, set(common))
    report["pooled"] = {"cues": len(common)}
    for metric in ("chrf", "bge_m3"):
        values = {k: sum(v[metric][k] for v in per_set.values()) / len(per_set) for k in common}
        report["pooled"][metric] = {"delta": S4.aggregate(values, layout), "bootstrap": S4.bootstrap(values, layout, reps=2000)}
    report["verdict"] = verdict(report)
    atomic_write_json(out_root / "A2" / "similarity.json", report)
    return report


def agreement(sim: dict[str, float], judge: dict[str, float]) -> dict[str, Any]:
    judged = [k for k in sim if judge[k] != 0]
    decided = [k for k in judged if sim[k] != 0]
    agree = sum((sim[k] > 0) == (judge[k] < 0) for k in decided)
    return {"judge_nonzero": len(judged), "sim_nonzero": len(decided), "agree": agree,
            "rate": agree / len(decided) if decided else None}


def verdict(report: dict[str, Any]) -> dict[str, Any]:
    """§4.1 A2 gate: 'opposite' when a similarity Δ is significantly negative (Q0 further from the reference)."""
    out = {}
    for metric in ("chrf", "bge_m3"):
        for category in S4.CATEGORIES:
            ci = (report["pooled"][metric]["bootstrap"].get(category) or {}).get("ci90")
            out[f"{metric}:{category}"] = ("opposite" if ci and ci[1] < 0 else "agrees" if ci and ci[0] > 0 else "no-difference")
    out["gate"] = "flag-judge-preference" if "opposite" in out.values() else "pass"
    return out


def blind_sheet(*, out_root: Path = V10_ROOT) -> dict[str, Any]:
    windows = E.reference_for(V4_ROOT, q2.SET)
    data = collect(windows, "v9-main")["v9-main"]
    rng = random.Random(SHEET_SEED)
    by_cat: dict[str, list[tuple[float, str]]] = {c: [] for c in S4.CATEGORIES}
    for key, w in sorted(windows.items()):
        ids = [u["id"] for u in w.units]
        if not all(i in data["tr"][Q0] and i in data["tr"][H0] and i in data["judge"][Q0] for i in ids):
            continue
        by_cat[w.meta.category].append((sum(data["judge"][Q0][i] - data["judge"][H0][i] for i in ids), key))
    chosen: list[tuple[str, str, float]] = []
    for category, rows in by_cat.items():
        top = sorted(rows, key=lambda r: (-abs(r[0]), r[1]))[:PER_CATEGORY]
        rest = [r for r in rows if r not in top]
        chosen += [("largest", k, d) for d, k in top] + [("random", k, d) for d, k in rng.sample(rest, PER_CATEGORY)]
    rng.shuffle(chosen)
    lines = ["# v10 A2 盲读表", "",
             "每节是一个 5 条的裁判窗口：日文原文、中文参考，以及两份译文 X、Y（来源与顺序随机，不标注）。",
             "请对每节写下 `X`、`Y` 或 `平`（哪份作为中文字幕整体更好），可附一句理由。答案键在同目录 `blind-key.json`，读完前不要打开。",
             ""]
    key_rows = []
    for n, (kind, key, delta) in enumerate(chosen, 1):
        w = windows[key]
        x_is_q0 = rng.random() < 0.5
        x, y = (Q0, H0) if x_is_q0 else (H0, Q0)
        lines += [f"## {n:02d}", "", "| # | 日文 | 参考 | X | Y |", "| --- | --- | --- | --- | --- |"]
        for i, u in enumerate(w.units, 1):
            cells = [u["ja"], u["zh"], data["tr"][x][u["id"]], data["tr"][y][u["id"]]]
            lines.append(f"| {i} | " + " | ".join(c.replace("|", "｜").replace("\n", " ") for c in cells) + " |")
        lines += ["", "判断：", ""]
        key_rows.append({"n": n, "window": key, "category": w.meta.category, "kind": kind, "X": x, "Y": y,
                         "judge_accuracy_delta_q0_minus_h0": delta})
    path = out_root / "A2" / "blind-sheet.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    atomic_write_json(out_root / "A2" / "blind-key.json", {"seed": SHEET_SEED, "rows": key_rows})
    return {"sheet": str(path), "windows": len(chosen)}
