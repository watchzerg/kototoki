"""v11 ticket 02 (offline): why name-table injection reversed on dev, and the N* injection tables.

Inputs are v10's (read only): the ``qwen-names-dev`` and ``qwen-wide`` runs of seed 20261011 with their same-period
judgements, and ``E/dev-name-tables.json``. ``diagnosis`` lists every cue whose name-related errors (``v9.NAME_ERROR``
on the judge evidence) or wrong-referent errors differ between the arms, with the table entries involved, and gives a
rule-based pre-class of §4.1 ((a) table entry wrong, (b) table right but differs from the reference's convention,
(c) entry right but misused: a pronoun / form of address / omitted subject rendered as a name, or applied to the
wrong person, (d) unrelated); the final class is set by reading the records (``A/02-classes.json``). Records carry
transcript text and stay under ``.local``; only counts are printed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from pathlib import Path
from typing import Any

from experiments.translation_v3.common import atomic_write_json, read_json
from experiments.translation_v3.generate import load_run_translations
from experiments.translation_v4 import evaluate as E
from experiments.translation_v4.common import DEFAULT_ROOT as V4_ROOT

from . import q2, v9, v10
from .names10 import injection_tables
from .v11 import V11_ROOT

DIAG_SEED = 20261011
CANDIDATE, CONTROL = "qwen-names-dev", v10.Q0
KATAKANA = re.compile(r"^[ァ-ヶー・゠]+$")
WRONG_REFERENT = "wrong-referent"


def dev_tables(source: Path = v10.V10_ROOT) -> dict[str, list[dict[str, Any]]]:
    return {w: t.get("entries", []) for w, t in read_json(source / "E" / "dev-name-tables.json")["tables"].items()}


def _cue_index(windows) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    ref = {u["id"]: u for w in windows.values() for u in w.units}
    work = {u["id"]: w.meta.work_id for w in windows.values() for u in w.units}
    category = {u["id"]: w.meta.category for w in windows.values() for u in w.units}
    return ref, work, category


def _injected(run_dir: Path) -> dict[str, int]:
    """cue id -> number of entries injected into the pack that translated it."""
    out = {}
    for path in sorted((run_dir / "scenes").glob("*.json")):
        for b in read_json(path)["batches"]:
            for t in b["target_ids"]:
                out[t] = b.get("names_injected", 0)
    return out


def _entries_hit(entries: list[dict], text: str) -> list[dict[str, Any]]:
    """Entries with a Japanese form occurring in ``text``."""
    return [{"entity_ja": e["entity_ja"], "zh": e["zh"], "kind": e["kind"], "confidence": e["confidence"],
             "forms": [f for f in e["forms"] if f["ja"] and f["ja"] in text]}
            for e in entries if any(f["ja"] and f["ja"] in text for f in e["forms"])]


def _zh_present(entries: list[dict], text: str) -> list[dict[str, Any]]:
    """Entries whose table Chinese (entry zh or any form zh) occurs in ``text``."""
    out = []
    for e in entries:
        zhs = {e["zh"], *(f["zh"] for f in e["forms"])} - {""}
        found = sorted(z for z in zhs if z in text)
        if found:
            out.append({"entity_ja": e["entity_ja"], "found": found})
    return out


def pre_class(record: dict[str, Any]) -> str:
    """Rule-based pre-class; '?' marks the cases the executor reads: ab? (table Chinese used where the reference
    renders it differently: (a) or (b)), c? (a table name appears in the candidate without its Japanese form in the
    cue and without that name in the reference), m? (table involved, no rule fits)."""
    if record["cand_name_without_ja_form"]:
        return "c?"
    if record["table_vs_reference"]:
        return "ab?"
    if not record["entries_in_ja"] and not record["table_zh_in_cand"]:
        return "d"
    return "m?"


def diagnosis(*, seed: int = DIAG_SEED, source: Path = v10.V10_ROOT, out: Path = V11_ROOT / "A") -> dict[str, Any]:
    windows = E.reference_for(V4_ROOT, q2.SET)
    cand_dir, ctrl_dir = q2.run_dir(source, CANDIDATE, seed), q2.run_dir(source, CONTROL, seed)
    scenes = set(read_json(cand_dir / "run.json")["scene_ids"])
    windows = {k: w for k, w in windows.items() if w.meta.scene_id in scenes}
    ref, work_of, category = _cue_index(windows)
    tc, tk = load_run_translations(cand_dir)[0], load_run_translations(ctrl_dir)[0]
    ec, ek = v9._errors(cand_dir, windows), v9._errors(ctrl_dir, windows)
    tables = dev_tables(source)
    injected = _injected(cand_dir)
    records, totals = [], Counter()
    for cue in sorted(ref):
        if cue not in tc or cue not in tk:
            continue
        work = work_of[cue]
        nc = [e for e in ec.get(cue, []) if v9.NAME_ERROR.search(e["evidence_zh"])]
        nk = [e for e in ek.get(cue, []) if v9.NAME_ERROR.search(e["evidence_zh"])]
        wc = [e for e in ec.get(cue, []) if e["category"] == WRONG_REFERENT]
        wk = [e for e in ek.get(cue, []) if e["category"] == WRONG_REFERENT]
        totals[f"{category[cue]}:name:cand"] += len(nc)
        totals[f"{category[cue]}:name:ctrl"] += len(nk)
        totals[f"{category[cue]}:wr:cand"] += len(wc)
        totals[f"{category[cue]}:wr:ctrl"] += len(wk)
        kinds = []
        if len(nc) > len(nk):
            kinds.append("name:new")
        if len(nc) < len(nk):
            kinds.append("name:fixed")
        if len(wc) > len(wk):
            kinds.append("wr:new")
        if len(wc) < len(wk):
            kinds.append("wr:fixed")
        if not kinds:
            continue
        entries = tables.get(work, [])
        ja, zh_ref, zh_c, zh_k = ref[cue]["ja"], ref[cue]["zh"], tc[cue], tk[cue]
        hit = _entries_hit(entries, ja)
        in_cand, in_ctrl, in_ref = _zh_present(entries, zh_c), _zh_present(entries, zh_k), _zh_present(entries, zh_ref)
        hit_entities = {h["entity_ja"] for h in hit}
        ref_entities = {h["entity_ja"] for h in in_ref}
        ctrl_entities = {h["entity_ja"] for h in in_ctrl}
        record = {
            "cue": cue, "work": work, "category": category[cue], "kinds": kinds, "names_injected": injected.get(cue),
            "ja": ja, "zh_ref": zh_ref, "zh_control": zh_k, "zh_candidate": zh_c, "identical": zh_c == zh_k,
            "cand_errors": ec.get(cue, []), "ctrl_errors": ek.get(cue, []),
            "entries_in_ja": hit, "table_zh_in_cand": in_cand, "table_zh_in_ctrl": in_ctrl, "table_zh_in_ref": in_ref,
            # a table name in the candidate with no Japanese form of it in the cue, not in the reference either
            "cand_name_without_ja_form": [h for h in in_cand if h["entity_ja"] not in hit_entities
                                          and h["entity_ja"] not in ref_entities],
            # a form of the cue is rendered with the table Chinese while the reference renders it otherwise
            "table_vs_reference": [h for h in hit if h["entity_ja"] in {x["entity_ja"] for x in in_cand}
                                   and h["entity_ja"] not in ref_entities],
            "control_used_table_zh": sorted(ctrl_entities)}
        record["pre_class"] = pre_class(record)
        records.append(record)
    summary: dict[str, Any] = {"seed": seed, "candidate": CANDIDATE, "control": CONTROL, "cues": len(ref),
                               "totals": dict(sorted(totals.items())), "records": len(records),
                               "by_kind": dict(Counter(k for r in records for k in r["kinds"])),
                               "pre_class_by_kind": {}}
    for kind in ("name:new", "name:fixed", "wr:new", "wr:fixed"):
        rs = [r for r in records if kind in r["kinds"]]
        summary["pre_class_by_kind"][kind] = {
            "cues": len(rs), "identical_text": sum(r["identical"] for r in rs),
            "pre_class": dict(Counter(r["pre_class"] for r in rs)),
            "by_category": dict(Counter(r["category"] for r in rs))}
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "02-diagnosis.json", {"summary": summary, "records": records})
    return summary


def table_reference_agreement(*, source: Path = v10.V10_ROOT, out: Path = V11_ROOT / "A") -> dict[str, Any]:
    """Per dev table entry: cues of the work whose Japanese contains a form, and how many of them have the table
    Chinese (entry zh / form zh / zh_variants) in the reference Chinese; entry nature (kind, confidence, katakana
    forms) for the dev and the product tables."""
    windows = E.reference_for(V4_ROOT, q2.SET)
    cues_by_work: dict[str, list[dict]] = defaultdict(list)
    for w in windows.values():
        cues_by_work[w.meta.work_id] += list(w.units)
    report: dict[str, Any] = {"works": {}, "entries": []}
    for work, entries in sorted(dev_tables(source).items()):
        rows = []
        for e in entries:
            forms = [f["ja"] for f in e["forms"] if f["ja"]]
            zhs = {e["zh"], *(f["zh"] for f in e["forms"]), *e.get("zh_variants", [])} - {""}
            occ = [u for u in cues_by_work[work] if any(f in u["ja"] for f in forms)]
            agree = sum(any(z in u["zh"] for z in zhs) for u in occ)
            rows.append({"work": work, "entity_ja": e["entity_ja"], "zh": e["zh"], "kind": e["kind"],
                         "confidence": e["confidence"], "forms": len(forms),
                         "katakana_forms": sum(bool(KATAKANA.match(f)) for f in forms),
                         "occurrences": len(occ), "reference_agrees": agree,
                         "agreement": agree / len(occ) if occ else None})
        report["entries"] += rows
        seen = [r for r in rows if r["occurrences"]]
        report["works"][work] = {
            "entries": len(rows), "with_occurrences": len(seen),
            "majority_agree": sum(r["agreement"] >= 0.5 for r in seen),
            "majority_disagree": sum(r["agreement"] < 0.5 for r in seen),
            "occurrence_weighted_agreement": (sum(r["reference_agrees"] for r in seen)
                                              / sum(r["occurrences"] for r in seen)) if seen else None,
            "kinds": dict(Counter(r["kind"] for r in rows)),
            "confidence": dict(Counter(r["confidence"] for r in rows)),
            "katakana_form_share": sum(r["katakana_forms"] for r in rows) / max(1, sum(r["forms"] for r in rows))}
    seen = [r for r in report["entries"] if r["occurrences"]]
    report["dev_total"] = {
        "entries": len(report["entries"]), "with_occurrences": len(seen),
        "majority_agree": sum(r["agreement"] >= 0.5 for r in seen),
        "majority_disagree": sum(r["agreement"] < 0.5 for r in seen),
        "occurrence_weighted_agreement": sum(r["reference_agrees"] for r in seen) / sum(r["occurrences"] for r in seen),
        "by_confidence": {c: {"entries": sum(r["confidence"] == c for r in seen),
                              "majority_disagree": sum(r["confidence"] == c and r["agreement"] < 0.5 for r in seen)}
                          for c in ("high", "medium", "low")},
        "by_kind": {k: {"entries": sum(r["kind"] == k for r in seen),
                        "majority_disagree": sum(r["kind"] == k and r["agreement"] < 0.5 for r in seen)}
                    for k in sorted({r["kind"] for r in seen})},
        "katakana_form_share": sum(r["katakana_forms"] for r in report["entries"]) / sum(r["forms"] for r in report["entries"])}
    from .asr10 import FILMS
    product = {}
    for film, paths in FILMS.items():
        entries = read_json(paths["table"])["entries"]
        forms = [f["ja"] for e in entries for f in e["forms"] if f["ja"]]
        product[film] = {"entries": len(entries), "kinds": dict(Counter(e["kind"] for e in entries)),
                         "confidence": dict(Counter(e["confidence"] for e in entries)), "forms": len(forms),
                         "katakana_form_share": sum(bool(KATAKANA.match(f)) for f in forms) / max(1, len(forms))}
    report["product"] = product
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "02-table-agreement.json", report)
    return {"dev_total": report["dev_total"], "product": product,
            "works": {w: {k: r[k] for k in ("entries", "with_occurrences", "majority_disagree",
                                            "occurrence_weighted_agreement")} for w, r in report["works"].items()}}


def class_summary(*, root: Path = V11_ROOT / "A") -> dict[str, Any]:
    """Join the executor's classes (``02-classes.json``) with the diagnosis records: counts per class by kind and
    category, and for the (a) cues whether a ``confidence: high`` filter would have dropped the entry involved."""
    diag = read_json(root / "02-diagnosis.json")
    classes = read_json(root / "02-classes.json")["classes"]
    records = {r["cue"]: r for r in diag["records"]}
    new = [r for r in diag["records"] if "name:new" in r["kinds"] or "wr:new" in r["kinds"]]
    missing = sorted(r["cue"] for r in new if r["cue"] not in classes)
    by_class: Counter = Counter()
    by_kind: dict[str, Counter] = defaultdict(Counter)
    by_category: dict[str, Counter] = defaultdict(Counter)
    for r in new:
        cls = classes.get(r["cue"], ["?"])[0]
        by_class[cls] += 1
        for kind in r["kinds"]:
            if kind.endswith(":new"):
                by_kind[kind][cls] += 1
        by_category[r["category"]][cls] += 1
    out: dict[str, Any] = {"new_cues": len(new), "unclassified": missing, "by_class": dict(by_class),
                           "by_kind": {k: dict(v) for k, v in by_kind.items()},
                           "by_category": {k: dict(v) for k, v in by_category.items()},
                           "majority": max(by_class, key=by_class.get)}
    a_cues = [r for r in new if classes.get(r["cue"], ["?"])[0] == "a"]
    conf = Counter()
    for r in a_cues:
        used = {h["entity_ja"] for h in r["table_zh_in_cand"]}
        hit = [h for h in r["entries_in_ja"] if h["entity_ja"] in used] or r["entries_in_ja"]
        conf[max((h["confidence"] for h in hit), key=("low", "medium", "high").index) if hit else "none"] += 1
    out["a_cues_by_entry_confidence"] = dict(conf)
    out["a_cues_dropped_by_high_filter"] = conf.get("medium", 0) + conf.get("low", 0)
    out["fixed"] = {k: diag["summary"]["pre_class_by_kind"][k] for k in ("name:fixed", "wr:fixed")}
    atomic_write_json(root / "02-class-summary.json", out)
    return out


def product_tables(min_confidence: str = "low") -> dict[str, list[dict[str, str]]]:
    """``asr10.name_tables`` restricted to entries at or above ``min_confidence`` (N* rule (a): ``high``)."""
    from .asr10 import FILMS
    order = ("low", "medium", "high")
    out = {}
    for film, paths in FILMS.items():
        rows, seen = [], set()
        for entity in read_json(paths["table"])["entries"]:
            if order.index(entity["confidence"]) < order.index(min_confidence):
                continue
            for form in entity["forms"]:
                if form["ja"] not in seen and form["ja"].strip() and form["zh"].strip():
                    seen.add(form["ja"])
                    rows.append({"source": form["ja"], "translation": form["zh"]})
        out[film] = rows
    return out


def write_nstar_recipes(revision: str | None) -> dict[str, Any]:
    """N* recipes: dev ``recipes/<name>.json`` and product ``C/root/recipes/<name>.json`` (hashes returned)."""
    from experiments.translation_v3.recipes import load_recipe
    from .v11 import C_ROOT
    suffix = "" if revision is None else f"-{revision}"
    comment = ("v11 N*: " + ("v1 injection" if revision is None else f"v1 injection, {revision}-confidence entries only"))
    dev_name, prod_name = f"qwen-names-dev{suffix}", f"q0-names{suffix}"
    v10.write_recipe(dev_name, "qwen-wide", root=V11_ROOT, comment=comment + " (dev tables)",
                     qwen_options={"names": {"filter": "window", "tables": nstar_tables(revision)}})
    v10.write_recipe(prod_name, "qwen-wide", root=C_ROOT / "root", comment=comment + " (product tables)",
                     qwen_options={"names": {"filter": "window", "tables": product_tables(revision or "low")}})
    dev, prod = load_recipe(dev_name, V11_ROOT), load_recipe(prod_name, C_ROOT / "root")
    return {"dev": {"name": dev_name, "hash": dev.recipe_hash,
                    "entries": {w: len(t) for w, t in dev.qwen_options["names"]["tables"].items()}},
            "product": {"name": prod_name, "hash": prod.recipe_hash,
                        "entries": {w: len(t) for w, t in prod.qwen_options["names"]["tables"].items()}}}


def nstar_tables(revision: str | None, *, source: Path = v10.V10_ROOT) -> dict[str, list[dict[str, str]]]:
    """Injection tables of N*: ``None`` = v1 (every form of every entity); ``"high"`` = §4.1 rule (a), only
    ``confidence: high`` entries. Rule (c) changes the filter / header (``names.filter: targets``), not the tables."""
    if revision is None:
        return injection_tables(source)
    if revision != "high":
        raise ValueError(revision)
    out = {}
    for work, table in read_json(source / "E" / "dev-name-tables.json")["tables"].items():
        rows, seen = [], set()
        for entity in table.get("entries", []):
            if entity["confidence"] != "high":
                continue
            for form in entity["forms"]:
                if form["ja"] not in seen and form["ja"].strip() and form["zh"].strip():
                    seen.add(form["ja"])
                    rows.append({"source": form["ja"], "translation": form["zh"]})
        if rows:
            out[work] = rows
    return out
