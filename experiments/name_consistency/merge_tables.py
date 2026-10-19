"""合并两张 name-table-v2。--mode intersection（默认，票据 05）取交集；--mode zh-agree（票据 07）按实体的中文是否一致取并集。

intersection：只留两张表都有、且映到同一中文的写法。

规则：
- 写法 form 的日文先规范化（NFKC：全角半角统一；去掉全部空白；片假名长音 ー 保留原样），
  规范化后相同、且 zh 完全相同，才算两表都有。
- 实体以 A 表为准，按保留下来的 form 聚合；实体的 zh 必须与 B 表里对应实体（含同一保留 form 的实体）的 zh 一致，
  否则整个实体丢弃并记录。entity_ja 若不是保留的 form，改用第一个保留 form 的日文（apply_table 会为缺失的 entity_ja 补 form）。
- zh_variants 取两表并集（A 在前）；confidence 取较低者；evidence 取并集。
- 输出 name-table-v2，meta 记 source: intersection、两张来源表路径、统计与丢弃清单。

zh-agree：
- 实体配对：A 的实体与 B 的实体，entity_ja 规范化后相同，或任一写法的日文规范化后相同，就是同一实体；
  一个 A 实体对上多个 B 实体时取写法重合最多的（并列取靠前的）。对不上的实体（A、B 两边都算）丢弃，记 meta.dropped_unmatched。
- 配对实体的 zh 必须完全相同，否则整对丢弃，记 meta.dropped_zh_disagree（带两边 zh）。
- 保留实体的写法取并集（按规范化日文去重，输出保留 A 的写法）；同一日文两边 zh 不同则只丢该写法，记 meta.dropped_form_disagree。
  entity_ja 取 A 的；其写法被丢弃时改用第一个保留写法的日文。写法全被丢弃的实体不输出，记 meta.dropped_no_form。
- zh_variants 并集（A 在前）、evidence 并集、confidence 取低、kind 取 A；meta 记 source: zh-agree、两张来源表路径与统计。
- --forms-fallback：配对实体 zh 不一致时不整对丢弃，改为只留两边日文规范化相同且 zh 相同的写法（像 intersection）；
  实体 zh、zh_variants 取 A 的（B 的变体对应的是 B 的实体 zh），记 meta.kept_forms_only（带 a_zh／b_zh）。
  A 的实体 zh 若不等于任何保留写法的 zh，apply_table 的隐含写法（entity_ja→实体 zh）会拼出错误映射，
  所以实体就只是两表一致认可的内容：entity_ja 与 zh 取第一个保留写法的，zh_variants 清空。
  一条写法都对不上仍记 dropped_zh_disagree。

命令（仓库根目录）：
  python -X utf8 -m experiments.name_consistency.merge_tables --a A.json --b B.json --out OUT.json [--mode zh-agree]
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


def entity_keys(entity: dict) -> set[str]:
    """实体配对用的日文键：entity_ja 与各写法的规范化日文。"""
    return {norm_ja(form["ja"]) for form in entity_forms(entity)}


def common_forms(a_entity: dict, b_entity: dict) -> list[dict]:
    """两边日文规范化相同且 zh 相同的写法（取 A 的写法）。"""
    b_keys = {form_key(form) for form in entity_forms(b_entity)}
    kept, seen = [], set()
    for form in entity_forms(a_entity):
        key = form_key(form)
        if key in b_keys and key not in seen:
            seen.add(key)
            kept.append(form)
    return kept


def agree_tables(a: dict, b: dict, a_path: str = "", b_path: str = "", forms_fallback: bool = False) -> dict:
    """zh-agree：日文配对实体，zh 一致才保留，写法取并集；forms_fallback 时 zh 不一致的配对退而只留共同写法。"""
    b_keys = [entity_keys(entity) for entity in b["entries"]]
    entries, used_b = [], set()
    unmatched, zh_disagree, form_disagree, no_form, forms_only = [], [], [], [], []
    for entity in a["entries"]:
        keys = entity_keys(entity)
        overlaps = [len(keys & other) for other in b_keys]
        best = max(range(len(overlaps)), key=lambda i: (overlaps[i], -i), default=None)
        if best is None or overlaps[best] == 0:
            unmatched.append({"table": "a", "entity_ja": entity["entity_ja"], "zh": entity["zh"]})
            continue
        used_b.add(best)
        other = b["entries"][best]
        if entity["zh"] != other["zh"] and forms_fallback and (shared := common_forms(entity, other)):
            entity_ja, zh, variants = entity["entity_ja"], entity["zh"], list(entity.get("zh_variants", []))
            if zh not in {form["zh"] for form in shared}:
                entity_ja, zh, variants = shared[0]["ja"], shared[0]["zh"], []
            elif norm_ja(entity_ja) not in {norm_ja(form["ja"]) for form in shared}:
                entity_ja = shared[0]["ja"]
            forms_only.append({"entity_ja": entity["entity_ja"], "a_zh": entity["zh"], "b_zh": other["zh"],
                               "forms_kept": [{"ja": form["ja"], "zh": form["zh"]} for form in shared]})
            entries.append({"entity_ja": entity_ja, "kind": entity.get("kind"),
                            "confidence": lower_confidence(entity.get("confidence"), other.get("confidence")),
                            "zh": zh, "forms": [{"ja": form["ja"], "zh": form["zh"]} for form in shared],
                            "zh_variants": variants,
                            "evidence": sorted({*entity.get("evidence", []), *other.get("evidence", [])})})
            continue
        if entity["zh"] != other["zh"]:
            zh_disagree.append({"entity_ja": entity["entity_ja"], "a_zh": entity["zh"],
                                "b_entity_ja": other["entity_ja"], "b_zh": other["zh"]})
            continue
        merged: dict[str, dict] = {}
        for form in entity_forms(entity):
            merged.setdefault(norm_ja(form["ja"]), form)
        dropped_keys = set()
        for form in entity_forms(other):
            key = norm_ja(form["ja"])
            if key not in merged:
                merged[key] = form
            elif merged[key]["zh"] != form["zh"] and key not in dropped_keys:
                dropped_keys.add(key)
                form_disagree.append({"entity_ja": entity["entity_ja"], "form_ja": merged[key]["ja"],
                                      "a_zh": merged[key]["zh"], "b_zh": form["zh"]})
        kept = [form for key, form in merged.items() if key not in dropped_keys]
        if not kept:
            no_form.append({"entity_ja": entity["entity_ja"], "zh": entity["zh"]})
            continue
        entity_ja = entity["entity_ja"]
        if norm_ja(entity_ja) in dropped_keys:
            entity_ja = kept[0]["ja"]  # 否则 apply_table 会用 entity_ja＋实体 zh 补出一条已被丢弃的写法
        entries.append({"entity_ja": entity_ja, "kind": entity.get("kind"),
                        "confidence": lower_confidence(entity.get("confidence"), other.get("confidence")),
                        "zh": entity["zh"], "forms": [{"ja": form["ja"], "zh": form["zh"]} for form in kept],
                        "zh_variants": list(dict.fromkeys([*entity.get("zh_variants", []), *other.get("zh_variants", [])])),
                        "evidence": sorted({*entity.get("evidence", []), *other.get("evidence", [])})})
    for index, entity in enumerate(b["entries"]):
        if index not in used_b:
            unmatched.append({"table": "b", "entity_ja": entity["entity_ja"], "zh": entity["zh"]})
    stats = {"entities_a": len(a["entries"]), "entities_b": len(b["entries"]), "entities_kept": len(entries),
             "dropped_unmatched": len(unmatched), "dropped_zh_disagree": len(zh_disagree),
             "dropped_form_disagree": len(form_disagree), "dropped_no_form": len(no_form),
             "kept_forms_only": len(forms_only), "forms_kept": sum(len(entry["forms"]) for entry in entries)}
    return {"schema": SCHEMA, "work": a.get("work"),
            "meta": {"source": "zh-agree", "a": a_path, "b": b_path, "stats": stats,
                     "dropped_unmatched": unmatched, "dropped_zh_disagree": zh_disagree,
                     "dropped_form_disagree": form_disagree, "dropped_no_form": no_form,
                     "kept_forms_only": forms_only},
            "entries": entries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="两张 name-table-v2 取交集")
    parser.add_argument("--a", type=Path, required=True)
    parser.add_argument("--b", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=["intersection", "zh-agree"], default="intersection",
                        help="intersection：写法取交集（默认）；zh-agree：实体 zh 一致才保留，写法取并集")
    parser.add_argument("--forms-fallback", action="store_true",
                        help="只对 zh-agree：配对实体 zh 不一致时不整对丢弃，改为只留两边相同的写法（实体 zh 取 A）")
    args = parser.parse_args(argv)
    if args.forms_fallback and args.mode != "zh-agree":
        parser.error("--forms-fallback requires --mode zh-agree")
    tables = []
    for path in (args.a, args.b):
        table = json.loads(path.read_text(encoding="utf-8"))
        if table.get("schema") != SCHEMA:
            raise SystemExit(f"{path}: unexpected table schema {table.get('schema')!r} (expected {SCHEMA})")
        tables.append(table)
    merged = (agree_tables(tables[0], tables[1], str(args.a), str(args.b), args.forms_fallback)
              if args.mode == "zh-agree" else merge_tables(tables[0], tables[1], str(args.a), str(args.b)))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    stats = merged["meta"]["stats"]
    print(json.dumps(stats))
    if args.mode == "zh-agree":
        return 0
    reasons: dict[str, int] = {}
    for item in merged["meta"]["dropped"]:
        label = f"{item['table']}:{item['reason']}"
        reasons[label] = reasons.get(label, 0) + 1
    print(json.dumps(reasons, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
