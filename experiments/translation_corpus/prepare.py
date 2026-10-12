"""Build disjoint probability-sampled windows without modifying frozen sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SEED = 20261006
VERSION = "hy30-expanded-v1"
Json = dict[str, Any]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)


def unique_object(pairs: list[tuple[str, Any]]) -> Json:
    obj: Json = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON key: {key}")
        obj[key] = value
    return obj


def read_jsonl(path: Path) -> list[Json]:
    return [json.loads(line, object_pairs_hook=unique_object) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[Json]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rng(key: str) -> random.Random:
    return random.Random(hashlib.sha256(f"{SEED}|{key}".encode()).digest())


def events(source_hash: str, unit: Json) -> set[str]:
    return {f"{source_hash}|{lang}|{event['Dialogue序号']}" for lang in ("ja", "zh") for event in unit["source_events"][lang]}


def paired_units(mapping: Json) -> list[Json]:
    """Only pair unique shared start times, never SRT row numbers."""
    groups: dict[str, dict[int, list[Json]]] = {}
    for lang in ("ja", "zh"):
        groups[lang] = defaultdict(list)
        for cue in mapping["语言轨"][lang]:
            groups[lang][cue["开始毫秒"]].append(cue)
    pairs = []
    for start in sorted(set(groups["ja"]) & set(groups["zh"])):
        a, b = groups["ja"][start], groups["zh"][start]
        if len(a) != 1 or len(b) != 1:
            continue
        ja, zh = a[0], b[0]
        pairs.append({"start_ms": start, "end_ms": ja["结束毫秒"], "ja_end_ms": ja["结束毫秒"], "zh_end_ms": zh["结束毫秒"], "ja": ja["文本"], "zh": zh["文本"], "ja_srt_index": ja["SRT序号"], "zh_srt_index": zh["SRT序号"], "source_events": {"ja": ja["源事件"], "zh": zh["源事件"]}, "flags": ja["标记"] + zh["标记"]})
    return pairs


def blocks(pairs: list[Json], source: Json, forbidden: set[str]) -> tuple[list[Json], list[Json]]:
    """Partition before sampling; no sliding windows or overlapping reserves."""
    offset = rng(f"partition|{source['source_sha256']}").randrange(7)
    frame, rejected = [], []
    for start in range(offset, len(pairs) - 6, 7):
        chunk = pairs[start:start + 7]
        event_ids = set().union(*(events(source["source_sha256"], u) for u in chunk))
        reason = None
        if event_ids & forbidden:
            reason = "old_context_or_previously_quarantined_events"
        elif any(chunk[i + 1][f"{lang}_srt_index"] != chunk[i][f"{lang}_srt_index"] + 1 for lang in ("ja", "zh") for i in range(6)):
            reason = "nonconsecutive_source_cues_or_unpaired_gap"
        elif any(not u["ja"].strip() or not u["zh"].strip() for u in chunk):
            reason = "empty_source_or_candidate_reference"
        wid = f"H30-{source['episode_id']}-B{start // 7 + 1:04d}"
        if reason:
            rejected.append({"window_id": wid, "episode_id": source["episode_id"], "reason": reason, "source_events": sorted(event_ids)})
            continue
        units = [{**unit, "id": f"{wid}-{i}", "start": unit["start_ms"] / 1000, "end": unit["ja_end_ms"] / 1000, "original_zh": unit["zh"], "score": 1 <= i <= 5} for i, unit in enumerate(chunk)]
        frame.append({**source, "id": wid, "window_id": wid, "units": units, "scored_ids": [u["id"] for u in units if u["score"]], "source_event_keys": sorted(event_ids), "position_decile": min(9, 10 * (start + 3) // len(pairs)), "review_status": "pending_double_fresh_review", "partition_offset": offset})
    return frame, rejected


def audit_overlap(rows: list[Json], forbidden: set[str]) -> Json:
    seen: dict[str, str] = {}
    for row in rows:
        for event in row["source_event_keys"]:
            if event in forbidden:
                raise ValueError(f"Old-context overlap: {row['id']}")
            if event in seen and seen[event] != row["id"]:
                raise ValueError(f"New-context overlap: {seen[event]} / {row['id']}")
            seen[event] = row["id"]
    return {"valid": True, "windows": len(rows), "context_event_keys": len(seen), "old_forbidden_event_keys": len(forbidden), "scope": "all Japanese and Chinese context source events, including reserves"}


def packet(row: Json) -> Json:
    return {"window_id": row["id"], "work": row["work"], "episode_id": row["episode_id"], "scored_ids": row["scored_ids"], "context": [{"id": u["id"], "ja": u["ja"], "start": u["start"], "end": u["end"], "source_events": u["source_events"], "flags": u["flags"], **({"original_zh": u["original_zh"]} if u["score"] else {})} for u in row["units"]], "source_sha256": row["source_sha256"], "quality_status": "unverified candidate reference; exact packet context only"}


def source_manifest(rows: list[Json]) -> Json:
    return {"corpus_version": VERSION, "windows": [{"id": r["id"], "window_id": r["id"], "work": r["work"], "category": r["category"], "set": "expanded", "episode": r["episode"], "episode_id": r["episode_id"], "scored_ids": r["scored_ids"], "source_sha256": r["source_sha256"], "source_event_keys": r["source_event_keys"], "start": r["units"][0]["start"], "end": r["units"][-1]["end"], "selection_group": r["selection_group"], "position_stratum": r["position_decile"], "position_decile": r["position_decile"], "source_length_chars": sum(len(u["ja"]) for u in r["units"]), "risk_tags": r.get("diagnostic_tags", [])} for r in rows]}


def prepare(corpus: Path, out: Path) -> Json:
    corpus, out = corpus.resolve(), out.resolve()
    if out == corpus or corpus in out.parents or out in corpus.parents:
        raise ValueError("Output must be separate from the read-only corpus")
    if out.exists():
        raise ValueError("Preparation output must be new; preserve previous artifacts")
    old = read_jsonl(corpus / "固定评测集/参考答案/dev.jsonl") + read_jsonl(corpus / "固定评测集/参考答案/test.jsonl")
    old_hashes = {row["source_sha256"] for row in old if row["category"] == "anime_series"}
    forbidden = set()
    for row in old:
        for unit in row["units"]:
            if "source_events" in unit:
                forbidden.update(events(row["source_sha256"], unit))
    excluded_ids = {row["window_id"] for row in read_json(corpus / "固定评测集/电影排除记录.json")}
    sampled = read_json(corpus / "电影补充/电影抽样.json")
    # The historical sampling object is traversed structurally, not matched by text.
    def visit(obj: Any, inherited_hash: str | None = None) -> None:
        if isinstance(obj, dict):
            source_hash = obj.get("source_sha256", obj.get("sha256", inherited_hash))
            if obj.get("id", obj.get("window_id")) in excluded_ids and "units" in obj:
                if source_hash:
                    for u in obj["units"]:
                        forbidden.update(events(source_hash, u))
            for value in obj.values():
                visit(value, source_hash)
        elif isinstance(obj, list):
            for value in obj:
                visit(value, inherited_hash)
    visit(sampled)
    anime = read_json(corpus / "动画v1/构建清单.json")
    movies = read_json(corpus / "电影补充/电影构建清单.json")
    consumed = [corpus / "freeze_manifest.json", corpus / "动画v1/构建清单.json", corpus / "电影补充/电影构建清单.json", corpus / "电影补充/电影抽样.json", corpus / "固定评测集/电影排除记录.json", corpus / "固定评测集/参考答案/dev.jsonl", corpus / "固定评测集/参考答案/test.jsonl"]
    sources, excluded = [], []
    for e in anime["集"]:
        if e["选用SHA256"] in old_hashes:
            excluded.append({"episode_id": e["集ID"], "reason": "old_dev_test_entire_episode", "source_sha256": e["选用SHA256"]})
            continue
        path = corpus / "动画v1/清洗候选" / e["作品ID"] / e["集ID"] / "事件映射.json"
        consumed.append(path)
        source = {"episode_id": e["集ID"], "episode": f"{e['季']}|{e['原始集标识']}", "season": e["季"], "work_id": e["作品ID"], "work": e["作品"], "source_sha256": e["选用SHA256"], "category": "anime_series", "source_mapping": path.relative_to(corpus).as_posix()}
        mapping = read_json(path)
        if mapping["源SHA256"] != source["source_sha256"]:
            raise ValueError(f"Source hash disagreement: {path}")
        sources.append((source, paired_units(mapping)))
    for e in movies["作品"]:
        if e["作品ID"] == "M05":
            excluded.append({"episode_id": "M05", "reason": "Weathering_with_You_source_quarantine"})
            continue
        path = corpus / "电影补充" / e["作品ID"] / "清洗候选/配对候选.json"
        consumed.append(path)
        sources.append(({"episode_id": e["作品ID"], "episode": e["作品ID"], "season": None, "work_id": e["作品ID"], "work": e["作品"], "source_sha256": e["源SHA256"], "category": "animation_movie", "source_mapping": path.relative_to(corpus).as_posix()}, read_json(path)["pairs"]))
    frame = []
    for source, pairs in sources:
        windows, failures = blocks(pairs, source, forbidden)
        frame.extend(windows)
        excluded.extend(failures)
    by_work: dict[str, list[Json]] = defaultdict(list)
    for row in frame:
        by_work[row["work_id"]].append(row)
    selected, reserve, strata = [], [], []
    for work_id, rows in sorted(by_work.items()):
        groups: dict[str, list[Json]] = defaultdict(list)
        if work_id.startswith("M"):
            for row in rows:
                groups[f"{work_id}|decile-{row['position_decile']:02d}"].append(row)
            quotas = {key: 8 for key in groups}
            for row in rows:
                row["episode_inclusion_probability"] = 1.0
        else:
            episodes = sorted({r["episode_id"] for r in rows}, key=lambda eid: next((r["season"], eid) for r in rows if r["episode_id"] == eid))
            episode_groups = {eid: [r for r in rows if r["episode_id"] == eid] for eid in episodes}
            # Eight contiguous season/episode-order bands; one uniformly selected episode per band.
            for band in range(8):
                members = episodes[len(episodes) * band // 8:len(episodes) * (band + 1) // 8]
                if not members:
                    raise ValueError(f"Fewer than eight unused episodes for {work_id}")
                rng(f"episodes|{work_id}|{band}").shuffle(members)
                chosen = members[0]
                key = f"{work_id}|episode-band-{band:02d}|{chosen}"
                groups[key] = episode_groups[chosen]
                for row in groups[key]:
                    row["episode_inclusion_probability"] = 1 / len(members)
                strata.append({"type": "episode_band", "work_id": work_id, "band": band, "ordered_episode_reserves": members, "selected_episode": chosen, "episode_probability": 1 / len(members)})
                for episode_rank, eid in enumerate(members[1:], 1):
                    for row in episode_groups[eid]:
                        row["selection_group"] = key
                        row["reserve_tier"] = "extra_episode"
                        row["reserve_episode_rank"] = episode_rank
                        row["initial_inclusion_probability"] = (1 / len(members)) * min(1, 10 / len(episode_groups[eid]))
                        reserve.append(row)
            quotas = {key: 10 for key in groups}
        for key, group in sorted(groups.items()):
            ordered = sorted(group, key=lambda r: r["id"])
            rng(f"windows|{key}").shuffle(ordered)
            quota = quotas[key]
            strata.append({"type": "window_group", "group": key, "work_id": work_id, "eligible_windows": len(ordered), "target": quota, "initial_selected": min(quota, len(ordered)), "conditional_window_probability": min(1, quota / len(ordered)), "frozen_order": [r["id"] for r in ordered]})
            for rank, row in enumerate(ordered):
                row.update({"selection_group": key, "reserve_rank": rank, "reserve_tier": "same_episode_or_position", "initial_inclusion_probability": row["episode_inclusion_probability"] * min(1, quota / len(ordered))})
                (selected if rank < quota else reserve).append(row)
    selected.sort(key=lambda r: (r["work_id"], r["selection_group"], r["reserve_rank"]))
    reserve.sort(key=lambda r: (r["selection_group"], r["reserve_tier"] == "extra_episode", r.get("reserve_episode_rank", 0), r.get("reserve_rank", 0), r["id"]))
    overlap = audit_overlap(selected + reserve, forbidden)
    write_jsonl(out / "staging/selected-candidates.jsonl", selected)
    write_jsonl(out / "staging/reserve-candidates.jsonl", reserve)
    write_json(out / "source-manifest.json", source_manifest(selected))
    write_jsonl(out / "audit/frame.jsonl", frame)
    write_jsonl(out / "audit/exclusions.jsonl", excluded)
    write_json(out / "audit/strata.json", strata)
    write_json(out / "audit/forbidden-event-keys.json", sorted(forbidden))
    write_json(out / "audit/overlap.json", overlap)
    prompt = Path(__file__).with_name("reference-review-prompt.md")
    prompt_text = prompt.read_text(encoding="utf-8")
    jobs = []
    for row in selected:
        rel = f"review-packets/{row['id']}.json"
        write_json(out / rel, packet(row))
        for phase in ("primary", "review"):
            jobs.append({"job_id": f"{phase}|{row['id']}", "phase": phase, "window_id": row["id"], "packet": rel, "output": f"reviews/{phase}/{row['id']}.json", "model": "gpt-6.1-sol", "reasoning_effort": "high", "fresh": True, "candidate_outputs_allowed": False})
    rng("review-job-order").shuffle(jobs)
    write_jsonl(out / "review-jobs.jsonl", jobs)
    (out / "reference-review-prompt.md").write_text(prompt_text, encoding="utf-8")
    counts = Counter(row["work_id"] for row in selected)
    manifest = {"corpus_version": VERSION, "state": "staged_unreviewed_not_for_inference", "lane": "V2-native-adapted", "seed": SEED, "target_windows": 1200, "selected_windows": len(selected), "selected_scored_ids": sum(len(r["scored_ids"]) for r in selected), "per_work_windows": dict(counts), "shortfalls": {k: 80 - counts[k] for k in by_work if counts[k] < 80}, "reserve_windows": len(reserve), "sampling_contract": "random-offset nonoverlapping seven-unit partition; 8 ordered episode bands, one uniform episode per band and 10 uniform windows; movies 10 position deciles with 8 uniform windows; quotas conditional on mechanically eligible frame", "replacement_contract": "same group frozen rank first; extra-episode tier only after same-episode exhaustion; no candidate-informed replacement", "probability_limit": "Initial probabilities are design probabilities on the mechanically eligible partition, not all subtitle spans. Reference exclusion/replacement changes the estimand; record rejection and actual final selection. Frame offset randomness is not included in conditional probabilities.", "sources": [{"path": p.relative_to(corpus).as_posix(), "sha256": digest(p)} for p in sorted(set(consumed))], "external_corpus": str(corpus), "external_freeze_manifest_sha256": digest(corpus / "freeze_manifest.json"), "builder_sha256": digest(Path(__file__)), "prompt_sha256": digest(prompt), "old_series_source_hashes": sorted(old_hashes), "old_windows": len(old), "independence": "Both passes must use fresh Sol/high and the original packet; no prior conclusions. Same model family is not independent ground truth."}
    write_json(out / "manifest.json", manifest)
    return manifest


def validate_review(row: Json, result: Json) -> None:
    if set(result) != {"window_id", "status", "translations", "changes", "reason_zh", "diagnostic_tags"}:
        raise ValueError("Unexpected review fields")
    if result["window_id"] != row["id"] or result["status"] not in {"accept", "edit", "exclude"}:
        raise ValueError("Invalid review identity/status")
    if not isinstance(result["reason_zh"], str) or not result["reason_zh"].strip():
        raise ValueError("Missing review reason")
    tags = result["diagnostic_tags"]
    allowed_tags = {"ellipsis_reference", "negation_condition", "named_entity", "number", "colloquial", "long_sentence", "other"}
    if not isinstance(tags, list) or any(not isinstance(t, str) or t not in allowed_tags for t in tags) or len(tags) != len(set(tags)):
        raise ValueError("Invalid diagnostic tags")
    original = {u["id"]: u["original_zh"] for u in row["units"] if u["score"]}
    translations = result["translations"]
    if result["status"] == "exclude":
        if translations != {} or result["changes"] != []:
            raise ValueError("Excluded review cannot invent translations")
        return
    if not isinstance(translations, dict) or set(translations) != set(original) or any(not isinstance(s, str) or not s.strip() for s in translations.values()):
        raise ValueError("Review must cover exactly scored IDs")
    changed = {key for key in original if original[key] != translations[key]}
    changes = result["changes"]
    if not isinstance(changes, list) or len(changes) != len(changed) or {c["id"] for c in changes} != changed:
        raise ValueError("Changes must account exactly for changed IDs")
    source_texts = [u["ja"] for u in row["units"]]
    for c in changes:
        if set(c) != {"id", "original_zh", "revised_zh", "source_evidence", "reason_zh"} or any(not isinstance(v, str) for v in c.values()):
            raise ValueError("Invalid change fields")
        if c["original_zh"] != original[c["id"]] or c["revised_zh"] != translations[c["id"]] or not c["reason_zh"].strip() or not c["source_evidence"] or not any(c["source_evidence"] in text for text in source_texts):
            raise ValueError("Invalid change provenance/evidence")
    if (result["status"] == "accept") != (not changed):
        raise ValueError("Status must distinguish edits from unchanged acceptance")


def reconcile(out: Path) -> Json:
    """Audit double review, prepare bounded disputes; never silently promote references."""
    rows = read_jsonl(out / "staging/selected-candidates.jsonl")
    ledger, agreed, disputes = [], [], []
    for row in rows:
        records = []
        for phase in ("primary", "review"):
            p = out / f"reviews/{phase}/{row['id']}.json"
            if not p.is_file():
                records.append(None)
            else:
                result = read_json(p)
                validate_review(row, result)
                records.append(result)
        if any(r is None for r in records):
            status = "pending"
        elif records[0]["status"] == records[1]["status"] and records[0]["translations"] == records[1]["translations"]:
            status = "excluded" if records[0]["status"] == "exclude" else "agreed"
            if status == "agreed":
                agreed.append({"row": row, "decision": records[0]})
        else:
            status = "dispute"
            opinions = list(records)
            rng(f"adjudication|{row['id']}").shuffle(opinions)
            disputes.append({"window_id": row["id"], "packet": packet(row), "anonymized_opinions": opinions, "maximum_adjudications": 1, "instruction": "Resolve supported reference changes using only packet source. Return the reference-review schema plus resolved:boolean and resolution_zh. If unresolved, exclude; do not guess. Same model arbitration is not ground truth."})
            adjudication_path = out / f"reviews/adjudication/{row['id']}.json"
            if adjudication_path.exists():
                adjudication = read_json(adjudication_path)
                if not isinstance(adjudication.get("resolved"), bool) or not isinstance(adjudication.get("resolution_zh"), str) or not adjudication["resolution_zh"].strip():
                    raise ValueError("Invalid adjudication resolution")
                if not adjudication["resolved"] and adjudication.get("status") != "exclude":
                    raise ValueError("Unresolved adjudication must exclude")
                decision = {k: v for k, v in adjudication.items() if k not in {"resolved", "resolution_zh"}}
                validate_review(row, decision)
                if not adjudication["resolved"] or decision["status"] == "exclude":
                    status = "excluded"
                else:
                    status = "adjudicated"
                    agreed.append({"row": row, "decision": decision})
        ledger.append({"window_id": row["id"], "status": status, "selection_group": row["selection_group"]})
    write_jsonl(out / "audit/review-ledger.jsonl", ledger)
    if disputes:
        source_prompt = Path(__file__).with_name("reference-adjudication-prompt.md")
        frozen_prompt = out / "reference-adjudication-prompt.md"
        if frozen_prompt.exists() and frozen_prompt.read_bytes() != source_prompt.read_bytes():
            raise ValueError("Adjudication instructions changed; use a new reference version")
        if not frozen_prompt.exists():
            frozen_prompt.write_bytes(source_prompt.read_bytes())
    write_jsonl(out / "adjudication-jobs.jsonl", disputes)
    write_jsonl(out / "staging/resolved-references.jsonl", agreed)
    summary = {"state": "reference_review_in_progress", "counts": dict(Counter(r["status"] for r in ledger)), "disputes": len(disputes), "inference_allowed": False}
    write_json(out / "audit/review-summary.json", summary)
    return summary


def replace_excluded(out: Path) -> Json:
    """Advance only frozen same-group reserves; archive rather than overwrite decisions."""
    if (out / "freeze-manifest.json").exists() or (out / "model-input/expanded.jsonl").exists():
        raise ValueError("Frozen corpus cannot change through replacement")
    rows = read_jsonl(out / "staging/selected-candidates.jsonl")
    validate_active_selection(out, rows)
    reconcile(out)
    ledger = read_jsonl(out / "audit/review-ledger.jsonl")
    reserves = read_jsonl(out / "staging/reserve-candidates.jsonl")
    excluded = {r["window_id"] for r in ledger if r["status"] == "excluded"}
    previous = out / "audit/replacements.jsonl"
    history = read_jsonl(previous) if previous.exists() else []
    used = {r["id"] for r in rows} | {r["removed"] for r in history}
    replacements, shortfalls, new_rows = [], [], []
    for row in rows:
        if row["id"] not in excluded:
            new_rows.append(row)
            continue
        replacement = next((r for r in reserves if r["selection_group"] == row["selection_group"] and r["id"] not in used), None)
        if replacement is None:
            shortfalls.append({"window_id": row["id"], "group": row["selection_group"], "reason": "frozen_same_group_reserves_exhausted"})
            new_rows.append(row)
            continue
        used.add(replacement["id"])
        new_rows.append(replacement)
        replacements.append({"removed": row["id"], "added": replacement["id"], "selection_group": row["selection_group"], "reason": "reference_double_review_exclusion", "reserve_tier": replacement["reserve_tier"]})
        write_json(out / f"review-packets/{replacement['id']}.json", packet(replacement))
    if replacements:
        generation = len(list((out / "audit").glob("selected-before-replacement-*.jsonl")))
        write_jsonl(out / f"audit/selected-before-replacement-{generation:04d}.jsonl", rows)
        write_jsonl(out / "staging/selected-candidates.jsonl", new_rows)
        jobs = read_jsonl(out / "review-jobs.jsonl")
        write_jsonl(out / f"audit/review-jobs-before-replacement-{generation:04d}.jsonl", jobs)
        active_ids = {r["id"] for r in new_rows}
        jobs = [j for j in jobs if j["window_id"] in active_ids]
        for r in new_rows:
            if r["id"] in {j["added"] for j in replacements}:
                for phase in ("primary", "review"):
                    jobs.append({"job_id": f"{phase}|{r['id']}", "phase": phase, "window_id": r["id"], "packet": f"review-packets/{r['id']}.json", "output": f"reviews/{phase}/{r['id']}.json", "model": "gpt-6.1-sol", "reasoning_effort": "high", "fresh": True, "candidate_outputs_allowed": False})
        write_jsonl(out / "review-jobs.jsonl", jobs)
        write_jsonl(previous, history + replacements)
    result = {"replaced": len(replacements), "shortfalls": shortfalls, "inference_allowed": False}
    write_json(out / "audit/replacement-summary.json", result)
    return result


def review_prompt_identity(copied: bytes, source_snapshot: bytes, expected_source_sha256: str) -> Json:
    """Accept exact bytes or the precisely proven Windows LF-to-CRLF text copy."""
    actual = hashlib.sha256(copied).hexdigest()
    source = hashlib.sha256(source_snapshot).hexdigest()
    conversion = "none"
    if actual != expected_source_sha256:
        if (source != expected_source_sha256 or b"\r" in source_snapshot
                or b"\n" not in source_snapshot
                or copied != source_snapshot.replace(b"\n", b"\r\n")
                or hashlib.sha256(copied.replace(b"\r\n", b"\n")).hexdigest() != expected_source_sha256):
            raise ValueError("Reference review instructions changed after source sampling")
        conversion = "windows_text_copy_lf_to_crlf"
    return {"declared_sampling_source_sha256": expected_source_sha256,
            "actual_execution_prompt_sha256": actual,
            "source_snapshot_sha256": source,
            "newline_conversion": conversion}


def freeze_evidence_inventory(out: Path) -> tuple[list[Json], list[Json]]:
    """Hash evidence; exclude only the two root-level transient native lock controls."""
    control_paths = {".reference-orchestration.lock", ".judge-scheduler.lock"}
    files, excluded = [], []
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(out).as_posix()
        if relative == "freeze-manifest.json":
            continue
        if relative in control_paths:
            excluded.append({"path": relative, "reason": "transient_native_lock_control"})
            continue
        files.append({"path": relative, "sha256": digest(path)})
    return files, excluded


def freeze(out: Path) -> Json:
    """Publish Japanese-only inputs only after the entire selected reference is resolved."""
    summary = reconcile(out)
    if sum(summary["counts"].get(k, 0) for k in ("agreed", "adjudicated")) != 1200:
        raise ValueError(f"Cannot freeze incomplete 1200-window double review: {summary['counts']}")
    manifest = read_json(out / "manifest.json")
    external = Path(manifest["external_corpus"])
    for source in manifest["sources"]:
        if digest(external / source["path"]) != source["sha256"]:
            raise ValueError(f"Frozen external source changed: {source['path']}")
    prompt_identity = review_prompt_identity(
        (out / "reference-review-prompt.md").read_bytes(),
        Path(__file__).with_name("reference-review-prompt.md").read_bytes(), manifest["prompt_sha256"])
    prompt_identity["historical_sampling_manifest_sha256"] = digest(out / "manifest.json")
    resolved = read_jsonl(out / "staging/resolved-references.jsonl")
    validate_active_selection(out, read_jsonl(out / "staging/selected-candidates.jsonl"))
    for record in resolved:
        wid = record["row"]["id"]
        phases = ["primary", "review"]
        if (out / f"reviews/adjudication/{wid}.json").exists():
            phases.append("adjudication")
        for phase in phases:
            validate_execution(out, phase, wid)
    references, inputs = [], []
    for record in resolved:
        row, decision = record["row"], record["decision"]
        units = [{**u, "zh": decision["translations"].get(u["id"], u["original_zh"]), "review_status": "double_fresh_reviewed" if u["score"] else "unscored_context_reference_unreviewed"} for u in row["units"]]
        references.append({**row, "units": units, "split": "expanded", "review_status": "double_fresh_reviewed_scored_ids", "review_note": decision["reason_zh"], "diagnostic_tags": decision["diagnostic_tags"], "quality_status": "计分条目经Sol/high双轮文本复核，未验证音画；不是人工金标准"})
        inputs.append({"id": row["id"], "source_language": "ja", "target_language": "zh-Hans", "context": [{"id": u["id"], "text": u["ja"]} for u in row["units"]], "translate_ids": row["scored_ids"]})
    forbidden = set(read_json(out / "audit/forbidden-event-keys.json"))
    audit_overlap(references, forbidden)
    counts = Counter(r["work_id"] for r in references)
    if len(counts) != 15 or set(counts.values()) != {80}:
        raise ValueError("Final corpus must contain 80 windows for each of 15 works")
    if (out / "model-input/expanded.jsonl").exists():
        raise ValueError("Frozen corpus must not be overwritten")
    original_builder_snapshots = [{"path": p.relative_to(out).as_posix(), "sha256": digest(p)}
                                  for p in sorted((out / "builder-snapshot").rglob("*")) if p.is_file()]
    final_builder_snapshot = snapshot_final_sources(out)
    write_jsonl(out / "model-input/expanded.jsonl", inputs)
    write_jsonl(out / "reference/expanded.jsonl", references)
    write_json(out / "source-manifest.json", source_manifest(references))
    evidence_files, excluded_controls = freeze_evidence_inventory(out)
    frozen = {"state": "frozen_double_fresh_reference_review", "windows": len(inputs), "scored_ids": sum(len(i["translate_ids"]) for i in inputs), "per_work_windows": dict(counts), "files": evidence_files, "inference_allowed": True, "quality_limit": "model-only same-family double review; source text only, not ground truth"}
    frozen["excluded_control_artifacts"] = excluded_controls
    frozen["reference_review_prompt_identity"] = prompt_identity
    frozen["original_builder_snapshots"] = original_builder_snapshots
    frozen["final_builder_snapshot"] = final_builder_snapshot
    write_json(out / "freeze-manifest.json", frozen)
    return {k: v for k, v in frozen.items() if k != "files"}


def snapshot_final_sources(out: Path) -> Json:
    """Capture final implementation in a content-addressed immutable directory."""
    payload = {f"corpus/{p.name}": p.read_bytes() for p in sorted(Path(__file__).parent.glob("*.py"))}
    for name in ("reference-review-prompt.md", "reference-adjudication-prompt.md"):
        path = Path(__file__).with_name(name)
        if path.exists():
            payload[f"corpus/{name}"] = path.read_bytes()
    transport = Path(__file__).parents[1] / "translation_reference_judge.py"
    if transport.exists():
        payload["translation_reference_judge.py"] = transport.read_bytes()
    identities = [{"path": name, "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(payload.items())]
    code_hash = hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()
    directory = out / "final-freeze-snapshots" / code_hash
    for name, data in sorted(payload.items()):
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError(f"Final source snapshot already differs: {target}")
        else:
            with target.open("xb") as stream:
                stream.write(data)
    return {"directory": directory.relative_to(out).as_posix(), "identity_sha256": code_hash,
            "files": identities}


def validate_active_selection(out: Path, selected: list[Json]) -> None:
    """Verify the current full rows and packets against the original frozen frame."""
    frame_rows = read_jsonl(out / "audit/frame.jsonl")
    frame = {row["id"]: row for row in frame_rows}
    if len(frame) != len(frame_rows):
        raise ValueError("Duplicate original frame window IDs")
    if len({row["id"] for row in selected}) != len(selected):
        raise ValueError("Duplicate active selected window IDs")
    for row in selected:
        if row["id"] not in frame or row != frame[row["id"]]:
            raise ValueError(f"Active selected row differs from original frame: {row['id']}")
        packet_path = out / f"review-packets/{row['id']}.json"
        if not packet_path.is_file() or read_json(packet_path) != packet(row):
            raise ValueError(f"Active selected packet differs from original frame: {row['id']}")


def validate_execution(out: Path, phase: str, wid: str) -> None:
    path = out / f"reference-execution/{phase}/{wid}/job.json"
    if not path.is_file():
        raise ValueError(f"Missing exact-model fresh execution evidence: {phase}/{wid}")
    evidence = read_json(path)
    if evidence.get("status") != "succeeded" or evidence.get("requested_model") != "gpt-6.1-sol" or evidence.get("requested_effort") != "high" or evidence.get("fresh") is not True:
        raise ValueError(f"Invalid exact-model fresh execution evidence: {path}")
    response = out / f"reviews/{phase}/{wid}.json"
    if evidence.get("response_sha256") != digest(response):
        raise ValueError(f"Review response provenance hash mismatch: {response}")
    prompt_name = "reference-adjudication-prompt.md" if phase == "adjudication" else "reference-review-prompt.md"
    if evidence.get("prompt_sha256") != digest(out / prompt_name):
        raise ValueError(f"Reference instructions provenance hash mismatch: {path}")
    raw_value = evidence.get("accepted_raw_response")
    if not isinstance(raw_value, str):
        raise ValueError("Missing accepted raw response")
    raw = Path(raw_value)
    if not raw.is_absolute():
        raw = out / raw
    if not raw.is_file() or evidence.get("accepted_raw_response_sha256") != digest(raw):
        raise ValueError(f"Missing or changed accepted raw response: {path}")
    if read_json(raw) != read_json(response):
        raise ValueError(f"Canonical response differs from accepted raw JSON: {path}")
    attempts = evidence.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        raise ValueError("Expected one fresh attempt and at most one format/transport retry")
    for attempt in attempts:
        if any(m != "gpt-6.1-sol" for m in attempt.get("returned_models", [])) or any(e != "high" for e in attempt.get("returned_efforts", [])):
            raise ValueError(f"Returned execution identity differs from exact Sol/high: {path}")
        if attempt.get("tool_events"):
            raise ValueError(f"Reference worker used tools outside its packet: {path}")
    exposed_models = [m for a in attempts for m in a.get("returned_models", [])]
    exposed_efforts = [e for a in attempts for e in a.get("returned_efforts", [])]
    if (not exposed_models or not exposed_efforts) and not evidence.get("returned_identity_unavailable"):
        raise ValueError(f"Unexposed returned identity requires an explicit limitation: {path}")
    if phase != "adjudication":
        expected_packet_hash = digest(out / f"review-packets/{wid}.json")
    else:
        selected = {r["id"]: r for r in read_jsonl(out / "staging/selected-candidates.jsonl")}
        expected_packet_hash = hashlib.sha256(json.dumps(packet(selected[wid]), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if evidence.get("packet_sha256") != expected_packet_hash:
        raise ValueError(f"Review packet provenance hash mismatch: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    for command in ("reconcile", "replace-excluded", "freeze"):
        p = sub.add_parser(command)
        p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commands = {"reconcile": reconcile, "replace-excluded": replace_excluded, "freeze": freeze}
    result = prepare(args.corpus, args.output) if args.command == "prepare" else commands[args.command](args.output)
    print(json.dumps({k: v for k, v in result.items() if k not in {"sources", "old_series_source_hashes"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
