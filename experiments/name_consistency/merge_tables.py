"""两张 name-table-v2 取交集（票据 05）：只留两张表都有、且映到同一中文的写法。

规则：
- 写法 form 的日文先规范化（NFKC：全角半角统一；去掉全部空白；片假名长音 ー 保留原样），
  规范化后相同、且 zh 完全相同，才算两表都有。
- 实体以 A 表为准，按保留下来的 form 聚合；实体的 zh 必须与 B 表里对应实体（含同一保留 form 的实体）的 zh 一致，
  否则整个实体丢弃并记录。entity_ja 若不是保留的 form，改用第一个保留 form 的日文（apply_table 会为缺失的 entity_ja 补 form）。
- zh_variants 取两表并集（A 在前）；confidence 取较低者；evidence 取并集。
- 输出 name-table-v2，meta 记 source: intersection、两张来源表路径、统计与丢弃清单。

命令（仓库根目录）：
  python -X utf8 -m experiments.name_consistency.merge_tables --a A.json --b B.json --out OUT.json
"""

import argparse
import json
import unicodedata
from pathlib import Path

from experiments.name_consistency.apply_table import CONFIDENCE_LEVELS, SCHEMA, entity_forms


def norm_ja(text: str) -> str:
    """日文写法的比较键：NFKC 统一全角半角，去掉所有空白；长音 ー 保持原样。"""
    return "".join(unicodedata.normalize("NFKC", text).split())


def form_key(form: dict) -> tuple[str, str]:
    return norm_ja(form["ja"]), form["zh"].strip()


def lower_confidence(*values: str | None) -> str:
    """取较低的置信度；缺失按 high 处理。"""
    return min((v or "high" for v in values), key=lambda v: CONFIDENCE_LEVELS.get(v, 2))


def merge_tables(a: dict, b: dict, a_path: str = "", b_path: str = "") -> dict:
    b_index: dict[tuple[str, str], list[int]] = {}
    b_norms: set[str] = set()
    for index, entity in enumerate(b["entries"]):
        for form in entity_forms(entity):
            b_index.setdefault(form_key(form), []).append(index)
            b_norms.add(norm_ja(form["ja"]))
    a_keys: set[tuple[str, str]] = set()
    a_norms: set[str] = set()

    entries, dropped = [], []
    forms_total = {"a": 0, "b": 0}
    forms_kept = 0
    for entity in a["entries"]:
        forms = entity_forms(entity)
        forms_total["a"] += len(forms)
        kept, seen = [], set()
        for form in forms:
            key = form_key(form)
            a_keys.add(key)
            a_norms.add(key[0])
            if key in b_index:
                if key not in seen:
                    seen.add(key)
                    kept.append(form)
            else:
                dropped.append({"table": "a", "entity_ja": entity["entity_ja"], "form_ja": form["ja"], "zh": form["zh"],
                                "reason": "zh_mismatch" if key[0] in b_norms else "not_in_other"})
        if not kept:
            dropped.append({"table": "a", "entity_ja": entity["entity_ja"], "zh": entity["zh"], "reason": "entity_no_common_form"})
            continue
        counterparts = {index for form in kept for index in b_index[form_key(form)]}
        matched = [b["entries"][index] for index in sorted(counterparts) if b["entries"][index]["zh"] == entity["zh"]]
        if not matched:
            dropped.append({"table": "a", "entity_ja": entity["entity_ja"], "zh": entity["zh"], "reason": "entity_zh_mismatch",
                            "other_zh": sorted({b["entries"][index]["zh"] for index in counterparts})})
            continue
        entity_ja = entity["entity_ja"]
        if norm_ja(entity_ja) not in {form_key(form)[0] for form in kept}:
            entity_ja = kept[0]["ja"]  # 否则 apply_table 会用 entity_ja＋实体 zh 补出一条已被交集去掉的 form
        variants = list(dict.fromkeys(v for e in [entity, *matched] for v in e.get("zh_variants", [])))
        evidence = sorted({n for e in [entity, *matched] for n in e.get("evidence", [])})
        forms_kept += len(kept)
        entries.append({"entity_ja": entity_ja, "kind": entity.get("kind"),
                        "confidence": lower_confidence(entity.get("confidence"), *(e.get("confidence") for e in matched)),
                        "zh": entity["zh"], "forms": [{"ja": form["ja"], "zh": form["zh"]} for form in kept],
                        "zh_variants": variants, "evidence": evidence})
    for entity in b["entries"]:  # B 里有而 A 里没有（或 zh 不同）的写法，只记录不输出
        for form in entity_forms(entity):
            forms_total["b"] += 1
            key = form_key(form)
            if key not in a_keys:
                dropped.append({"table": "b", "entity_ja": entity["entity_ja"], "form_ja": form["ja"], "zh": form["zh"],
                                "reason": "zh_mismatch" if key[0] in a_norms else "not_in_other"})
    stats = {"forms_a": forms_total["a"], "forms_b": forms_total["b"], "forms_kept": forms_kept,
             "entities_a": len(a["entries"]), "entities_b": len(b["entries"]), "entities_kept": len(entries),
             "entities_dropped": sum(1 for item in dropped if item["table"] == "a" and item["reason"].startswith("entity_"))}
    return {"schema": SCHEMA, "work": a.get("work"),
            "meta": {"source": "intersection", "a": a_path, "b": b_path, "stats": stats, "dropped": dropped},
            "entries": entries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="两张 name-table-v2 取交集")
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    tables = []
    for path in (args.a, args.b):
        table = json.loads(path.read_text(encoding="utf-8"))
        if table.get("schema") != SCHEMA:
            raise SystemExit(f"{path}: unexpected table schema {table.get('schema')!r} (expected {SCHEMA})")
        tables.append(table)
    merged = merge_tables(tables[0], tables[1], str(args.a), str(args.b))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    stats = merged["meta"]["stats"]
    print(json.dumps(stats))
    reasons: dict[str, int] = {}
    for item in merged["meta"]["dropped"]:
        label = f"{item['table']}:{item['reason']}"
        reasons[label] = reasons.get(label, 0) + 1
    print(json.dumps(reasons, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
