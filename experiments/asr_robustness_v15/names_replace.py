"""票据 04 C3：只按专名表替换（日文转写侧，ADR-0014 研究线按 §8 第 6 项局部重开）。

- **表**：HF II 用 Q3 产品表（`.local/q3-product-fullfilm/.../name-table.json`，high 20）；HF III 在本轮 Strata session 里用产品配方
  `q3-names-v1`（`kototoki.names.build_document`，最多 5 次请求取第一张合格表）新建，建不出来退回 27B 旧表并记下。旧表只作对照附录
  （`c3a-oldtable`）。
- **分组**：每个 `confidence: high` 条目的 `entity_ja` 与 `forms[].ja` 按各自的 `zh` 分组——同一 `zh` 的几种日文写法视为同一指称
  （遠坂／トウサカ／父坂 → 远坂）；`zh` 不同的写法不互换。出现在两个 `zh` 组里的写法视为歧义，整个不用（也不计入"表内写法"）；
  单字写法不参与替换（既不作来源也不作规范写法）。组内以**对照转写里出现最多的写法**为规范写法（并列取条目的 `entity_ja`，再并列取先列出的）。
- **C3a 纯规则**：在每条 cue 文字上找全部表内写法的出现位置，按"最长优先、再靠左优先"选不重叠的命中；命中是非规范写法时整串换成本组
  规范写法。较短写法落在更长表内写法内部的命中因此自然被丢弃（ADR-0014 规则一的纪律）。
- **C3b Flash-Next 判定**：提示 `ja-names-v1`：system 给出按组的全部 high 写法（行首为规范写法），要求只把听错的专名片段换成规范写法、
  别的字一个不动；包（20 待校正／前 10／后 5 只读邻文）、采样、seed 20261109、`max_tokens` 2048、思考关闭、编辑比 ≤0.5 守卫与
  解析失败换 seed＋1 重试一次均同 v14 §4.3。**表内 diff 守卫**（`table_guard`）：对 before→after 做字符级 diff，相邻改动区段之间
  等同片段 ≤2 字的合并为一个区段；每个区段允许向两侧等同的上下文对称扩展，直到 after 侧片段正好是一个表内写法；任一区段扩不出表内写法、
  或是纯删除，整条回退并计 `rejected_not_table`。
- **评估**（离线）：单元口径 CER（对照分母）、改动 cue 数、改好／改坏／无影响（v14 `classify_changes`）、有害率＝改坏／改动、
  **人名命中率**＝"参考单元文字含某个规范写法"的每次提及里，候选单元文字也含该写法的比例（规范化文本上数，改前／改后各一份）。
  与 v14 C2 v2 在 HF II 同一张表下并列。05 的触发条件：某臂两部单元 CER 都不升且有害率 ≤10%。

转写、表与改动文字只写 `.local/`；报告与日志只含计数。
"""

from __future__ import annotations

import difflib
import random
from pathlib import Path
from typing import Any

from experiments.asr_robustness_v14 import correct
from experiments.asr_robustness_v15 import common
from experiments.quality_v5 import asr_source
from kototoki.srt import format_srt
from kototoki_eval.schema import normalize

TICKET = "04"
RECIPE_LABEL = "ja-names-replace-v1"
PROMPT_NAME = "ja-names-v1"
PROMPT = (
    "你是日语语音识别（ASR）转写字幕的专名校对员。下面给出本作品专名的日文写法表：每行是一个人物或事物，同一行的几种写法指同一指称，"
    "行首第一个是规范写法。任务：只把待校正条目里**听错或写错的专名片段**——与表内写法同音／近音、明显指同一人物或事物的片段——"
    "改成该行的规范写法；表内其他写法也统一改成规范写法。除此之外**一个字都不动**：不改措辞、助词、语序、敬体，不改标点，不补漏，"
    "不删句，不修正专名以外的任何错误；只读邻文只用来理解上下文，不要输出它们。没有把握就保持原文。"
    "输出一个 JSON 对象：键是待校正条目的 id，值是修正后的整条文字；只列有改动的条目，没有改动就输出 {}。不输出解释或代码围栏。")
NAMES_HEADER = "【专名写法表（每行一个指称，第一个为规范写法）】\n"
ARMS = ("c3a", "c3b", "c3a-oldtable", "c3a-entity", "c3a-entity-oldtable")
CANONICAL_RULES = ("frequency", "entity")
OLD_TABLE_HF_III = common.v14.FILMS["hf-iii"]["name_table"]
V14_C2_EVAL = common.LOCAL / "asr-robustness-v14" / "04" / "ja-correct-v2" / "eval.json"
MERGE_GAP = 2


def out_dir() -> Path:
    return common.ticket_dir(TICKET)


# --- 表与分组 -------------------------------------------------------------------------------------

def high_pairs(table: dict[str, Any]) -> list[tuple[str, str, str]]:
    """high 条目的 (ja, zh, entity_ja) 三元组，按出现顺序去重。"""
    pairs: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in table["entries"]:
        if entry.get("confidence") != "high":
            continue
        entity = (entry.get("entity_ja") or "").strip()
        for form in [{"ja": entity, "zh": entry.get("zh")}, *entry.get("forms", [])]:
            ja, zh = (form.get("ja") or "").strip(), (form.get("zh") or "").strip()
            if ja and zh and (ja, zh) not in seen:
                seen.add((ja, zh))
                pairs.append((ja, zh, entity))
    return pairs


def count_occurrences(form: str, texts: list[str]) -> int:
    return sum(t.count(form) for t in texts)


def build_groups(table: dict[str, Any], texts: list[str], canonical_rule: str = "frequency") -> dict[str, Any]:
    """按 `zh` 分组、选规范写法、给出替换映射与"全部表内写法"（用于保护更长写法）。

    `canonical_rule`：`frequency`＝§4.3 的规则（转写里出现最多，并列取条目 `entity_ja`）；`entity`＝附录变体，取与本组 `zh`
    同名条目的 `entity_ja`（表的"头写法"），没有就取先列出的，不看转写频次。
    """
    pairs = high_pairs(table)
    zh_of: dict[str, set[str]] = {}
    for ja, zh, _ in pairs:
        zh_of.setdefault(ja, set()).add(zh)
    ambiguous = sorted(ja for ja, zhs in zh_of.items() if len(zhs) > 1)
    single_char = sorted({ja for ja, _, _ in pairs if len(ja) == 1})
    by_zh: dict[str, list[tuple[str, str]]] = {}
    for ja, zh, entity in pairs:
        if ja in ambiguous or len(ja) == 1:
            continue
        by_zh.setdefault(zh, []).append((ja, entity))
    groups = []
    mapping: dict[str, str] = {}
    for zh, members in by_zh.items():
        forms = []
        for ja, _ in members:
            if ja not in forms:
                forms.append(ja)
        counts = {ja: count_occurrences(ja, texts) for ja in forms}
        if len(forms) < 2:
            groups.append({"zh": zh, "forms": forms, "canonical": forms[0], "counts": counts, "replace": []})
            continue
        entity_names = [entity for ja, entity in members if ja == entity]
        if canonical_rule == "entity":
            heads = [ja for ja in forms if ja in entity_names and any(e.get("entity_ja", "").strip() == ja and (e.get("zh") or "").strip() == zh
                                                                      for e in table["entries"])]
            canonical, tie = (heads or [ja for ja in forms if ja in entity_names] or forms)[0], False
        else:
            top = max(counts.values())
            candidates = [ja for ja in forms if counts[ja] == top]
            canonical, tie = next((ja for ja in candidates if ja in entity_names), candidates[0]), len(candidates) > 1
        groups.append({"zh": zh, "forms": forms, "canonical": canonical, "counts": counts,
                       "replace": [ja for ja in forms if ja != canonical], "tie": tie})
        for ja in forms:
            if ja != canonical:
                mapping[ja] = canonical
    all_forms = sorted({ja for ja, _, _ in pairs if len(ja) > 1 and ja not in ambiguous}, key=lambda s: (-len(s), s))
    return {"groups": groups, "mapping": mapping, "all_forms": all_forms, "ambiguous": ambiguous, "canonical_rule": canonical_rule,
            "single_char": single_char, "canonicals": sorted({g["canonical"] for g in groups if g["replace"]})}


def name_lines(grouping: dict[str, Any]) -> list[str]:
    return ["／".join([g["canonical"], *[f for f in g["forms"] if f != g["canonical"]]]) for g in grouping["groups"]]


# --- C3a：规则替换 ---------------------------------------------------------------------------------

def replace_text(text: str, mapping: dict[str, str], all_forms: list[str]) -> tuple[str, list[dict[str, Any]]]:
    """最长优先、再靠左优先的不重叠命中；非规范写法整串换成规范写法。"""
    spans = []
    for form in all_forms:
        start = text.find(form)
        while start >= 0:
            spans.append((start, start + len(form), form))
            start = text.find(form, start + 1)
    spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
    taken = [False] * len(text)
    chosen = []
    for s, e, form in spans:
        if any(taken[s:e]):
            continue
        for i in range(s, e):
            taken[i] = True
        chosen.append((s, e, form))
    chosen.sort()
    out, pos, replacements = [], 0, []
    for s, e, form in chosen:
        if form in mapping:
            out.append(text[pos:s])
            out.append(mapping[form])
            replacements.append({"from": form, "to": mapping[form], "at": s})
            pos = e
    out.append(text[pos:])
    return "".join(out), replacements


def table_for(film: str, *, old_table: bool = False) -> tuple[Path, dict[str, Any], bool]:
    """(路径, 表, 是否退回 27B 旧表)。HF III 只有本轮建出合格 Q3 表时才算"有 Q3 表"。"""
    if film == "hf-ii":
        path, fallback = common.v14.FILMS["hf-ii"]["name_table"], False
    elif old_table:
        path, fallback = OLD_TABLE_HF_III, True
    else:
        built = out_dir() / "names" / "hf-iii" / "name-table.json"
        result = out_dir() / "names" / "hf-iii" / "build-result.json"
        ok = built.is_file() and result.is_file() and common.read_json(result).get("status") == "ok"
        path, fallback = (built, False) if ok else (OLD_TABLE_HF_III, True)
    return path, common.read_json(path), fallback


def table_summary(path: Path, table: dict[str, Any]) -> dict[str, Any]:
    return {"path": str(path), "entries": len(table["entries"]),
            "high": sum(1 for e in table["entries"] if e.get("confidence") == "high")}


def run_rules(films: tuple[str, ...] = ("hf-ii", "hf-iii")) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for arm, old, rule in (("c3a", False, "frequency"), ("c3a-oldtable", True, "frequency"),
                           ("c3a-entity", False, "entity"), ("c3a-entity-oldtable", True, "entity")):
        for film in films:
            if old and film != "hf-iii":
                continue
            path, table, fallback = table_for(film, old_table=old)
            if fallback and not old:
                report.setdefault(arm, {})[film] = {"skipped": "no Q3 table for HF III this round (Strata not run); see *-oldtable"}
                continue
            cues = correct.control_cues(film)
            grouping = build_groups(table, [c["text"] for c in cues], rule)
            new_cues, changes, total = [], [], 0
            for cue in cues:
                text, reps = replace_text(cue["text"], grouping["mapping"], grouping["all_forms"])
                new_cues.append({**cue, "text": text})
                if reps:
                    total += len(reps)
                    changes.append({"id": correct.cue_id(cue), "index": cue["index"], "start": cue["start"], "end": cue["end"],
                                    "before": cue["text"], "after": text, "replacements": reps})
            out = out_dir() / arm / film
            common.write_text(out / "ja.srt", format_srt([(c["start"], c["end"], c["text"]) for c in new_cues]))
            common.write_json(out / "changes.json", changes)
            common.write_json(out / "groups.json", grouping)
            summary = {"recipe": RECIPE_LABEL, "canonical_rule": rule, "table": table_summary(path, table), "cues": len(cues),
                       "changed_cues": len(changes),
                       "replacements": total, "groups": len(grouping["groups"]),
                       "groups_with_replacement": sum(1 for g in grouping["groups"] if g["replace"]),
                       "forms_replaced": len(grouping["mapping"]), "ties": sum(1 for g in grouping["groups"] if g.get("tie")),
                       "ambiguous_forms": len(grouping["ambiguous"]), "single_char_forms": len(grouping["single_char"])}
            common.write_json(out / "summary.json", summary)
            report.setdefault(arm, {})[film] = summary
    common.write_json(out_dir() / "rules.json", report)
    return report


# --- C3b：Flash-Next 表内替换 ---------------------------------------------------------------------

def messages(pack: dict[str, Any], names: list[str]) -> list[dict[str, str]]:
    import json

    system = PROMPT + "\n\n" + NAMES_HEADER + "\n".join(names)
    lines = lambda cues: "\n".join(f"{correct.cue_id(c)}: {c['text']}" for c in cues) or "（无）"  # noqa: E731
    target = json.dumps({correct.cue_id(c): c["text"] for c in pack["targets"]}, ensure_ascii=False)
    user = (correct.CONTEXT_BEFORE + lines(pack["before"]) + correct.TARGET_HEADER + target + correct.CONTEXT_AFTER
            + lines(pack["after"]))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def table_guard(before: str, after: str, forms: list[str]) -> dict[str, Any]:
    """before→after 的每个改动区段（≤MERGE_GAP 字等同片段合并）在 after 侧扩成表内写法才采纳。"""
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    ops = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if not ops:
        return {"ok": False, "reason": "unchanged"}
    regions: list[list[int]] = []
    for _tag, i1, i2, j1, j2 in ops:
        if regions and i1 - regions[-1][1] <= MERGE_GAP:
            regions[-1][1], regions[-1][3] = i2, j2
        else:
            regions.append([i1, i2, j1, j2])
    form_set = set(forms)
    max_len = max((len(f) for f in forms), default=0)
    replacements = []
    for i1, i2, j1, j2 in regions:
        if j2 == j1:
            return {"ok": False, "reason": "deletion"}
        found = None
        for left in range(0, max_len):
            for right in range(0, max_len):
                a1, a2, b1, b2 = j1 - left, j2 + right, i1 - left, i2 + right
                if a1 < 0 or b1 < 0 or a2 > len(after) or b2 > len(before):
                    continue
                if before[b1:i1] != after[a1:j1] or before[i2:b2] != after[j2:a2]:
                    continue
                if after[a1:a2] in form_set:
                    found = {"from": before[b1:b2], "to": after[a1:a2]}
                    break
            if found:
                break
        if found is None:
            return {"ok": False, "reason": "not_table"}
        replacements.append(found)
    return {"ok": True, "replacements": replacements}


def apply_reply(pack: dict[str, Any], content: str, forms: list[str]) -> tuple[dict[str, Any], dict[str, int]]:
    """v14 的解析与编辑比守卫 → 再过表内 diff 守卫。返回 ({id: {text, replacements}}, 计数)。"""
    accepted, counts = correct.apply_reply(pack, content)
    counts.update({"rejected_not_table": 0, "rejected_deletion": 0, "table_accepted": 0})
    targets = {correct.cue_id(c): c["text"] for c in pack["targets"]}
    kept: dict[str, Any] = {}
    for key, text in accepted.items():
        guard = table_guard(targets[key], text, forms)
        if guard["ok"]:
            counts["table_accepted"] += 1
            kept[key] = {"text": text, "replacements": guard["replacements"]}
        elif guard["reason"] == "deletion":
            counts["rejected_deletion"] += 1
        else:
            counts["rejected_not_table"] += 1
    counts["accepted"] = counts["table_accepted"]
    return kept, counts


def correct_film(cues: list[dict[str, Any]], client: Any, names: list[str], forms: list[str],
                 *, seed: int = correct.SEED) -> dict[str, Any]:
    corrected = [dict(c) for c in cues]
    by_id = {correct.cue_id(c): i for i, c in enumerate(cues)}
    changes, packets = [], []
    for pack in correct.packs(cues):
        body_messages = messages(pack, names)
        outcome: dict[str, Any] = {"pack": pack["number"], "targets": len(pack["targets"]), "attempts": []}
        kept: dict[str, Any] = {}
        for attempt in range(2):
            reply = client.chat(correct.request_body(body_messages, seed + attempt))
            record = {"seed": seed + attempt, **reply["record"]}
            if reply["content"] is None or record.get("finish_reason") == "length":
                record["failure"] = "length" if record.get("finish_reason") == "length" else "no_content"
                outcome["attempts"].append(record)
                continue
            try:
                kept, counts = apply_reply(pack, reply["content"], forms)
            except ValueError as exc:
                record["failure"] = f"parse: {type(exc).__name__}"
                outcome["attempts"].append(record)
                continue
            record.update(counts)
            outcome["attempts"].append(record)
            break
        else:
            outcome["pack_failed"] = True
        for key, item in kept.items():
            i = by_id[key]
            changes.append({"id": key, "index": cues[i]["index"], "start": cues[i]["start"], "end": cues[i]["end"],
                            "before": cues[i]["text"], "after": item["text"], "replacements": item["replacements"],
                            "pack": pack["number"]})
            corrected[i]["text"] = item["text"]
        packets.append(outcome)
    attempts = [a for p in packets for a in p["attempts"]]
    summary = {
        "cues": len(cues), "packs": len(packets), "requests": len(attempts),
        "pack_failed": sum(1 for p in packets if p.get("pack_failed")),
        "retried": sum(1 for p in packets if len(p["attempts"]) > 1),
        "length_failures": sum(1 for a in attempts if a.get("failure") == "length"),
        "parse_failures": sum(1 for a in attempts if str(a.get("failure", "")).startswith("parse")),
        "http_errors": sum(1 for a in attempts if a.get("finish_reason") == "http_error"),
        "reasoning_nonempty": sum(1 for a in attempts if a.get("reasoning_chars")),
        "think_tags": sum(1 for a in attempts if a.get("think_tag")),
        "proposed": sum(a.get("proposed", 0) for a in attempts), "accepted": len(changes),
        "ratio_rejected": sum(a.get("ratio_rejected", 0) for a in attempts),
        "rejected_not_table": sum(a.get("rejected_not_table", 0) for a in attempts),
        "rejected_deletion": sum(a.get("rejected_deletion", 0) for a in attempts),
        "unknown_id": sum(a.get("unknown_id", 0) for a in attempts),
        "unchanged": sum(a.get("unchanged", 0) for a in attempts), "empty": sum(a.get("empty", 0) for a in attempts),
        "replacements": sum(len(c["replacements"]) for c in changes),
        "seconds": round(sum(a["seconds"] for a in attempts), 1),
        "seconds_per_pack": round(sum(a["seconds"] for a in attempts) / max(1, len(packets)), 2),
        "prompt_tokens": sum(a.get("prompt_tokens") or 0 for a in attempts),
        "completion_tokens": sum(a.get("completion_tokens") or 0 for a in attempts),
        "cache_n_first": attempts[0].get("cache_n") if attempts else None,
    }
    return {"cues": corrected, "changes": changes, "packets": packets, "summary": summary}


# --- Strata session：HF III 建表 ＋ C3b -------------------------------------------------------------

CONFIG_TOML = "[paths]\ninput_dir = \"input\"\nwork_dir = \"work\"\n"


def load_config() -> Any:
    from kototoki import config as config_module

    root = out_dir() / "strata"
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "work").mkdir(parents=True, exist_ok=True)
    path = root / "kototoki.toml"
    common.write_text(path, CONFIG_TOML)
    return config_module.load(path)


def build_hf_iii_table(session: Any, seed: int) -> dict[str, Any]:
    from kototoki import names as names_module
    from kototoki import srt

    document = srt.read_srt(common.v14.FILMS["hf-iii"]["work"] / "ja.srt")
    work = out_dir() / "names" / "hf-iii"
    started = common.timed()
    try:
        result = names_module.build_document(work, document, session, seed)
    except names_module.NamesError as exc:
        record = {"status": "error", "error": str(exc)[:300], "seconds": round(common.timed() - started, 1), "seed": seed}
        common.write_json(work / "build-result.json", record)
        return record
    common.write_json(work / "name-table.json", result.payload)
    record = {"status": result.status, "attempts": result.attempts, "seconds": round(result.seconds, 1), "seed": seed,
              "entries": len(result.payload["entries"]),
              "high": sum(1 for e in result.payload["entries"] if e.get("confidence") == "high"),
              "build": result.payload.get("build"), "meta": {k: v for k, v in result.payload.get("meta", {}).items()
                                                            if k in ("attempt", "prompt_tokens", "completion_tokens", "seconds")}}
    common.write_json(work / "build-result.json", record)
    return record


def run_strata(films: tuple[str, ...] = ("hf-ii", "hf-iii"), *, skip_build: bool = False) -> dict[str, Any]:
    """GPU 1 run（一个 Strata session）：先为 HF III 建 Q3 表，再在同一 session 上跑两部 C3b。"""
    from kototoki.strata import Session

    root = out_dir() / "strata"
    index = len(list(root.glob("session-*"))) + 1 if root.is_dir() else 1
    session_dir = root / f"session-{index:02d}"
    session_dir.mkdir(parents=True, exist_ok=True)
    preflight = correct.preflight(session_dir)
    config = load_config()
    started = common.timed()
    report: dict[str, Any] = {"recipe": RECIPE_LABEL, "prompt": PROMPT_NAME, "films": films, "preflight": preflight,
                              "build": None, "results": {}, "sessions": 0}
    with common.gpu_lock("v15-04 C3 names-build + ja-names-v1 on Strata"):
        session = Session(config)
        try:
            if "hf-iii" in films and not skip_build:
                report["build"] = build_hf_iii_table(session, config.names.seed)
                common.write_json(root / "progress.json", report)
            server = session.ensure_started()
            report["sessions"] = session.ordinal
            client = correct.Client(base=server.url)
            for film in films:
                path, table, fallback = table_for(film)
                cues = correct.control_cues(film)
                grouping = build_groups(table, [c["text"] for c in cues])
                names = name_lines(grouping)
                result = correct_film(cues, client, names, grouping["all_forms"])
                out = out_dir() / "c3b" / film
                common.write_text(out / "ja.srt", format_srt([(c["start"], c["end"], c["text"]) for c in result["cues"]]))
                common.write_json(out / "changes.json", result["changes"])
                common.write_json(out / "packets.json", result["packets"])
                common.write_json(out / "groups.json", grouping)
                summary = {**result["summary"], "recipe": RECIPE_LABEL, "table": {**table_summary(path, table), "old_table": fallback},
                           "name_rows": len(names)}
                common.write_json(out / "summary.json", summary)
                report["results"][film] = summary
                common.write_json(root / "progress.json", report)
            identity = server.identity
            report["session"] = {k: v for k, v in identity.items() if k != "strata"}
            report["session"]["strata"] = {k: identity["strata"].get(k) for k in ("version", "drafting", "expert_arena", "kv")}
        finally:
            session.stop()
    report["wall_s"] = round(common.timed() - started, 1)
    report["vram_used_after_stop_mib"] = common.v14.vram_used_mib()
    report["gpu_run"] = 1
    common.write_json(root / f"run-{index:02d}.json", report)
    return report


# --- 评估 -----------------------------------------------------------------------------------------

def name_hit_rate(reference: list[dict[str, Any]], cues: list[dict[str, Any]], canonicals: list[str]) -> dict[str, Any]:
    """参考单元文字含规范写法的每次提及里，候选单元文字也含该写法的比例（规范化文本）。"""
    units = asr_source.overlap_units(reference, cues)
    norm_forms = [(normalize(c).text, c) for c in canonicals]
    mentions = hits = units_with = 0
    for refs, prods in units:
        ref_text = normalize("".join(reference[i]["text"] for i in refs)).text
        hyp_text = normalize("".join(cues[k]["text"] for k in prods)).text
        found = False
        for form, _ in norm_forms:
            n = ref_text.count(form) if form else 0
            if n:
                found = True
                mentions += n
                hits += min(n, hyp_text.count(form))
        units_with += found
    return {"units_with_names": units_with, "mentions": mentions, "hits": hits,
            "rate": round(hits / mentions, 4) if mentions else None}


def evaluate(films: tuple[str, ...] = ("hf-ii", "hf-iii")) -> dict[str, Any]:
    report: dict[str, Any] = {"arms": {}}
    for arm in ARMS:
        for film in films:
            out = out_dir() / arm / film
            if not (out / "ja.srt").is_file():
                continue
            reference = common.v14.reference_cues(film)  # noqa: E501
            control = correct.control_cues(film)
            corrected = asr_source.read_srt(out / "ja.srt")
            changes = common.read_json(out / "changes.json")
            grouping = common.read_json(out / "groups.json")
            before, after = common.v14.unit_cer(reference, control), common.v14.unit_cer(reference, corrected)
            rows, summary = correct.classify_changes(reference, control, changes)
            common.write_json(out / "changes-classified.json", rows)
            harm = round(summary["worsened"] / summary["changes"], 4) if summary["changes"] else None
            report["arms"].setdefault(arm, {})[film] = {
                "control": {k: before[k] for k in ("CER", "edits", "reference_characters", "units")},
                "corrected": {k: after[k] for k in ("CER", "edits", "reference_characters", "units")},
                "delta_edits": after["edits"] - before["edits"],
                "delta_cer_pp": round(after["CER"] - before["CER"], 4) if after["CER"] is not None else None,
                "changes": summary, "harm_rate": harm,
                "name_hit": {"before": name_hit_rate(reference, control, grouping["canonicals"]),
                             "after": name_hit_rate(reference, corrected, grouping["canonicals"])},
                "summary": common.read_json(out / "summary.json")}
    # 05 触发：某臂两部单元 CER 都不升且有害率 ≤10%；多臂满足取 Δ编辑合计更低的
    eligible = []
    for arm in ("c3a", "c3b"):
        rows = report["arms"].get(arm, {})
        if len(rows) == 2 and all(r["delta_edits"] <= 0 and (r["harm_rate"] or 0) <= 0.10 for r in rows.values()):
            eligible.append((sum(r["delta_edits"] for r in rows.values()), arm))
    report["trigger_05"] = {"eligible": [a for _, a in sorted(eligible)], "selected": min(eligible)[1] if eligible else None}
    if V14_C2_EVAL.is_file():
        c2 = common.read_json(V14_C2_EVAL)["arms"].get("c2", {}).get("hf-ii")
        if c2:
            report["v14_c2_v2_hf_ii"] = {k: c2[k] for k in ("control", "corrected", "delta_edits", "delta_cer_pp")}
            report["v14_c2_v2_hf_ii"]["changes"] = {k: c2["changes"][k] for k in ("changes", "improved", "worsened", "neutral")}
    common.write_json(out_dir() / "eval.json", report)
    return report


def sample_changes(n: int = 30, seed: int = correct.SEED) -> dict[str, Any]:
    pool: dict[str, list[dict[str, Any]]] = {"improved": [], "worsened": []}
    for arm in ("c3a", "c3b"):
        for path in sorted((out_dir() / arm).glob("*/changes-classified.json")):
            film = path.parent.name
            for row in common.read_json(path):
                if row["verdict"] in pool:
                    pool[row["verdict"]].append({**row, "arm": arm, "film": film})
    rng = random.Random(seed)
    picked = []
    for rows in pool.values():
        rng.shuffle(rows)
        picked.extend(rows[:n // 2])
    rng.shuffle(picked)
    references = {film: common.v14.reference_cues(film) for film in ("hf-ii", "hf-iii")}
    items = []
    for k, row in enumerate(picked, 1):
        control = correct.control_cues(row["film"])
        units, owner = correct.unit_index(references[row["film"]], control)
        j = next(i for i, c in enumerate(control) if c["index"] == row["index"])
        refs, _ = units[owner[j]]
        items.append({"n": k, "arm": row["arm"], "film": row["film"], "id": row["id"], "verdict": row["verdict"],
                      "before": row["before"], "after": row["after"], "replacements": row.get("replacements"),
                      "reference": "".join(references[row["film"]][i]["text"] for i in refs)})
    common.write_json(out_dir() / "sample.json", {"items": items, "pool": {k: len(v) for k, v in pool.items()}})
    return {"sampled": len(items), "pool": {k: len(v) for k, v in pool.items()}, "path": str(out_dir() / "sample.json")}


__all__ = ["ARMS", "PROMPT", "PROMPT_NAME", "RECIPE_LABEL", "apply_reply", "build_groups", "correct_film", "evaluate",
           "high_pairs", "messages", "name_hit_rate", "name_lines", "replace_text", "run_rules", "run_strata",
           "sample_changes", "table_guard"]
