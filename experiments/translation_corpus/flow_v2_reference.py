"""Versioned configurable reference review for source-frozen flow windows.

Reference artifacts remain evaluation-only. This module never performs candidate
translation, term extraction, scene preparation, or candidate repair.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from . import prepare as legacy

Json = dict[str, Any]
VERSION = "hy30-flow-v2-reference-v1"


def identity(path: Path) -> Json:
    return {"path": str(path.resolve()), "sha256": legacy.digest(path)}


def check_id(value: str) -> None:
    if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."} or any(c in value for c in '/\\:'):
        raise ValueError("Unsafe window ID")


def hydrate(meta: Json, corpus: Path | None = None) -> Json:
    """Recover references only through explicit language-track provenance."""
    meta = dict(meta)
    for name in ("source_mapping", "source_srt"):
        path = Path(meta[name])
        meta[name] = str((path if path.is_absolute() else (corpus or Path.cwd()) / path).resolve())
        if meta.get(f"{name}_sha256") and legacy.digest(Path(meta[name])) != meta[f"{name}_sha256"]:
            raise ValueError("Declared source artifact hash mismatch")
    mapping = legacy.read_json(Path(meta["source_mapping"]))
    tracks = {lang: {u["SRT序号"]: u for u in mapping["语言轨"][lang]} for lang in ("ja", "zh")}
    if any(len(tracks[lang]) != len(mapping["语言轨"][lang]) for lang in tracks):
        raise ValueError("Duplicate source track index")
    check_id(meta["id"])
    scored = meta["scored_ids"]
    if not scored or len(scored) != len(set(scored)):
        raise ValueError("Invalid scored IDs")
    units = []
    previous = 0
    for item in meta["units"]:
        ja = tracks["ja"][item["ja_srt_index"]]
        score = item["id"] in scored
        if item["ja_srt_index"] <= previous or bool(item["score"]) != score:
            raise ValueError("Source order/scored provenance mismatch")
        previous = item["ja_srt_index"]
        if item["source_events"]["ja"] != ja["源事件"] or item["start"] != ja["开始毫秒"] / 1000 or item["end"] != ja["结束毫秒"] / 1000:
            raise ValueError("Japanese event/time provenance mismatch")
        original = ""
        if score:
            zh = tracks["zh"][item["zh_srt_index"]]
            if (ja["开始毫秒"] != zh["开始毫秒"] or item["source_events"]["zh"] != zh["源事件"]
                    or sum(u["开始毫秒"] == ja["开始毫秒"] for u in tracks["ja"].values()) != 1
                    or sum(u["开始毫秒"] == ja["开始毫秒"] for u in tracks["zh"].values()) != 1):
                raise ValueError("Scored reference lacks unique paired source provenance")
            original = zh["文本"]
            if not original.strip():
                raise ValueError("Empty scored reference")
        units.append({**item, "ja": ja["文本"], "original_zh": original,
                      "score": score, "flags": ja.get("标记", [])})
    if {u["id"] for u in units if u["score"]} != set(scored) or len({u["id"] for u in units}) != len(units):
        raise ValueError("Scored IDs missing or duplicate context IDs")
    paired = [u["zh_srt_index"] for u in units if u["score"]]
    if any(b != a + 1 for a, b in zip(paired, paired[1:])):
        raise ValueError("Nonconsecutive scored Chinese source indices")
    return {**meta, "units": units}


def quota_group(row: Json) -> str:
    return "|".join((row["selection_group"], row["split"], row["selection_type"]))


def quotas(rows: list[Json]) -> Json:
    return dict(Counter(quota_group(r) for r in rows))


def check_scope(rows: list[Json]) -> None:
    """Same scene may host different scored ranges; split scopes never overlap."""
    seen: dict[str, tuple[str, str]] = {}
    scored: set[tuple[str, str]] = set()
    for row in rows:
        scope = ("screening" if row["split"].startswith("screen") else row["split"], row["scene_id"])
        for event in row["source_event_keys"]:
            if event in seen and seen[event] != scope:
                raise ValueError("Cross-scene or screening/confirmation source overlap")
            seen[event] = scope
        for unit in row["units"]:
            if unit["score"]:
                key = (row["source_sha256"], str(unit["ja_srt_index"]))
                if key in scored:
                    raise ValueError("Duplicate active scored source cue")
                scored.add(key)


def prepare(manifests: list[Path], out: Path, expected_quotas: Json | None = None) -> Json:
    """Freeze source selection before exposing any reference review jobs."""
    if out.exists():
        raise ValueError("Reference output must be a new directory")
    selected, reserve, source_files = [], [], {}
    external_corpora = set()
    for path in manifests:
        manifest = legacy.read_json(path)
        corpus = Path(manifest["external_corpus"]) if manifest.get("external_corpus") else None
        if corpus is not None:
            external_corpora.add(str(corpus.resolve()))
        selected.extend(hydrate(r, corpus) for r in manifest["windows"])
        reserve_path = path.parent / "audit/reserve-manifest.jsonl"
        reserve_rows = manifest.get("reserve_windows", [])
        if reserve_path.exists():
            reserve_rows = legacy.read_jsonl(reserve_path)
            source_files[str(reserve_path.resolve())] = identity(reserve_path)
        reserve.extend(hydrate(r, corpus) for r in reserve_rows)
        source_files[str(path.resolve())] = identity(path)
        source_freeze = path.parent / "freeze-manifest.json"
        artifacts = manifest.get("files", [])
        if source_freeze.exists():
            artifacts += legacy.read_json(source_freeze).get("artifacts", [])
            source_files[str(source_freeze.resolve())] = identity(source_freeze)
        for record in artifacts:
            artifact = Path(record["path"])
            artifact = artifact if artifact.is_absolute() else path.parent / artifact
            if legacy.digest(artifact) != record["sha256"]:
                raise ValueError("Source manifest artifact hash mismatch")
            source_files[str(artifact.resolve())] = identity(artifact)
    all_rows = selected + reserve
    if len(external_corpora) > 1:
        raise ValueError("Source selections must share one external corpus identity")
    if len({r["id"] for r in selected}) != len(selected):
        raise ValueError("Duplicate selected window IDs")
    for row in all_rows:
        for name in ("source_mapping", "source_srt"):
            artifact = Path(row[name])
            source_files[str(artifact.resolve())] = identity(artifact)
    actual = quotas(selected)
    expected = actual if expected_quotas is None else expected_quotas
    if actual != expected or any(type(n) is not int or n < 1 for n in expected.values()):
        raise ValueError("Initial selection does not satisfy configured quotas")
    check_scope(selected)
    out.mkdir(parents=True)
    legacy.write_jsonl(out / "audit/frame.jsonl", all_rows)
    legacy.write_jsonl(out / "staging/selected-candidates.jsonl", selected)
    legacy.write_jsonl(out / "staging/reserve-candidates.jsonl", reserve)
    prompt_hashes = {}
    for name in ("reference-review-prompt.md", "reference-adjudication-prompt.md"):
        source = Path(legacy.__file__).with_name(name)
        text = source.read_text(encoding="utf-8-sig").replace("The seven supplied Japanese\nunits", "The supplied Japanese\nunits").replace("Evaluate the five scored IDs", "Evaluate exactly the packet scored IDs")
        (out / name).write_text(text, encoding="utf-8")
        prompt_hashes[name] = legacy.digest(out / name)
    for row in selected:
        legacy.write_json(out / f"review-packets/{row['id']}.json", legacy.packet(row))
    legacy.write_jsonl(out / "review-jobs.jsonl", jobs(selected))
    snapshot = out / "builder-snapshot"
    snapshot.mkdir()
    for source in (Path(__file__), Path(legacy.__file__), Path(__file__).parents[1] / "translation_reference_judge.py"):
        shutil.copyfile(source, snapshot / source.name)
    manifest = {"corpus_version": VERSION, "state": "staged_unreviewed_not_for_inference",
                "external_corpus": next(iter(external_corpora), str(manifests[0].parent.resolve())),
                "target_windows": len(selected), "quotas": expected,
                "split_counts": dict(Counter(r["split"] for r in selected)),
                "selection_type_counts": dict(Counter(r["selection_type"] for r in selected)),
                "sources": list(source_files.values()), "prompts": prompt_hashes,
                "initial_selected_sha256": legacy.digest(out / "staging/selected-candidates.jsonl"),
                "frame_sha256": legacy.digest(out / "audit/frame.jsonl"),
                "reserve_sha256": legacy.digest(out / "staging/reserve-candidates.jsonl"),
                "builder_snapshots": [{"path": p.relative_to(out).as_posix(), "sha256": legacy.digest(p)} for p in sorted(snapshot.iterdir())],
                "sampling_limit_zh": "配额仅针对冻结机械合格框；参考排除和替补改变可用范围，拒绝率另报。",
                "confirmation_sealed": True, "inference_allowed": False}
    legacy.write_json(out / "manifest.json", manifest)
    (out / "manifest.sha256").write_text(legacy.digest(out / "manifest.json"), encoding="ascii")
    return {k: v for k, v in manifest.items() if k not in {"sources", "prompts"}}


def jobs(rows: list[Json]) -> list[Json]:
    return [{"job_id": f"{phase}|{row['id']}", "phase": phase, "window_id": row["id"],
             "packet": f"review-packets/{row['id']}.json", "output": f"reviews/{phase}/{row['id']}.json",
             "model": "gpt-6.1-sol", "reasoning_effort": "high", "fresh": True,
             "candidate_outputs_allowed": False} for row in rows for phase in ("primary", "review")]


def validate(out: Path) -> tuple[Json, list[Json]]:
    manifest = legacy.read_json(out / "manifest.json")
    if legacy.digest(out / "manifest.json") != (out / "manifest.sha256").read_text(encoding="ascii"):
        raise ValueError("Reference manifest changed")
    for name, key in (("audit/frame.jsonl", "frame_sha256"), ("staging/reserve-candidates.jsonl", "reserve_sha256")):
        if legacy.digest(out / name) != manifest[key]:
            raise ValueError("Frozen reference frame/reserve changed")
    for artifact in manifest["sources"]:
        if legacy.digest(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError("Frozen external source changed")
    for name, expected in manifest["prompts"].items():
        if legacy.digest(out / name) != expected:
            raise ValueError("Frozen reference prompt changed")
    for artifact in manifest["builder_snapshots"]:
        if legacy.digest(out / artifact["path"]) != artifact["sha256"]:
            raise ValueError("Initial builder snapshot changed")
    rows = legacy.read_jsonl(out / "staging/selected-candidates.jsonl")
    frame_rows = legacy.read_jsonl(out / "audit/frame.jsonl")
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate active window IDs")
    for row in rows:
        matches = [r for r in frame_rows if r["id"] == row["id"]]
        if not any(row == r or row == {**r, "split": row["split"]} and r["split"] == "screening" and row["split"].startswith("screen") for r in matches):
            raise ValueError("Active row differs from frozen source frame")
        if legacy.read_json(out / f"review-packets/{row['id']}.json") != legacy.packet(row):
            raise ValueError("Active packet differs from frozen source frame")
    if quotas(rows) != manifest["quotas"]:
        raise ValueError("Active selection does not satisfy frozen quotas")
    check_scope(rows)
    history_path = out / "audit/replacements.jsonl"
    initial_path = out / "audit/selected-before-replacement-0000.jsonl" if history_path.exists() else out / "staging/selected-candidates.jsonl"
    if legacy.digest(initial_path) != manifest["initial_selected_sha256"]:
        raise ValueError("Initial selected source identity changed")
    initial = legacy.read_jsonl(initial_path)
    reserves = legacy.read_jsonl(out / "staging/reserve-candidates.jsonl")
    current = [r["id"] for r in initial]
    slots = {r["id"]: r for r in initial}
    used = set(current)
    if history_path.exists():
        for replacement in legacy.read_jsonl(history_path):
            removed, added = replacement["removed"], replacement["added"]
            slot = slots.get(removed)
            if removed not in current or added in used or slot is None:
                raise ValueError("Invalid replacement provenance")
            expected = next((r["id"] for r in reserves if r["selection_group"] == slot["selection_group"] and r["selection_type"] == slot["selection_type"] and r["id"] not in used), None)
            if added != expected:
                raise ValueError("Replacement violates frozen same-group reserve order")
            proof = out / f"audit/excluded-reference-decisions/{removed}.json"
            if replacement.get("exclusion_proof_sha256") != legacy.digest(proof):
                raise ValueError("Replacement exclusion proof changed")
            excluded = legacy.read_json(proof)
            if excluded.get("status") != "excluded" or excluded.get("row") != slot:
                raise ValueError("Replacement lacks excluded source provenance")
            records = []
            for phase in ("primary", "review"):
                validate_execution(out, phase, slot)
                records.append(legacy.read_json(out / f"reviews/{phase}/{removed}.json"))
            if not (records[0]["status"] == records[1]["status"] == "exclude"):
                validate_execution(out, "adjudication", slot)
                adjudication = legacy.read_json(out / f"reviews/adjudication/{removed}.json")
                if adjudication["status"] != "exclude":
                    raise ValueError("Replacement lacks double-round or adjudicated exclusion")
            current[current.index(removed)] = added
            slots[added] = {**next(r for r in reserves if r["id"] == added and r["selection_type"] == slot["selection_type"]), "split": slot["split"]}
            used.add(added)
    if current != [r["id"] for r in rows]:
        raise ValueError("Active selection differs from initial selection/replacement history")
    return manifest, rows


def validate_execution(out: Path, phase: str, row: Json) -> None:
    """Validate archived adjudications whose rows are no longer active."""
    if phase != "adjudication":
        legacy.validate_execution(out, phase, row["id"])
        return
    from experiments.translation_reference_judge import validate_response
    wid = row["id"]
    evidence = legacy.read_json(out / f"reference-execution/{phase}/{wid}/job.json")
    response = out / f"reviews/{phase}/{wid}.json"
    if (evidence.get("status"), evidence.get("requested_model"), evidence.get("requested_effort"), evidence.get("fresh")) != ("succeeded", "gpt-6.1-sol", "high", True):
        raise ValueError("Invalid archived adjudication execution identity")
    expected_packet = hashlib.sha256(json.dumps(legacy.packet(row), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if evidence.get("packet_sha256") != expected_packet or evidence.get("prompt_sha256") != legacy.digest(out / "reference-adjudication-prompt.md") or evidence.get("response_sha256") != legacy.digest(response):
        raise ValueError("Archived adjudication packet/prompt/response hash mismatch")
    raw = Path(evidence["accepted_raw_response"])
    raw = raw if raw.is_absolute() else out / raw
    if legacy.digest(raw) != evidence.get("accepted_raw_response_sha256") or legacy.read_json(raw) != legacy.read_json(response):
        raise ValueError("Archived adjudication raw response mismatch")
    validate_response(row, legacy.read_json(response), True)
    attempts = evidence.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        raise ValueError("Invalid adjudication retry budget")
    for attempt in attempts:
        if any(m != "gpt-6.1-sol" for m in attempt.get("returned_models", [])) or any(e != "high" for e in attempt.get("returned_efforts", [])) or attempt.get("tool_events"):
            raise ValueError("Invalid archived adjudication execution evidence")
    if (not any(a.get("returned_models") for a in attempts) or not any(a.get("returned_efforts") for a in attempts)) and not evidence.get("returned_identity_unavailable"):
        raise ValueError("Unexposed returned identity needs explicit limitation")


def reconcile(out: Path) -> Json:
    if (out / "freeze-manifest.json").exists():
        raise ValueError("Frozen references cannot be reconciled in place")
    validate(out)
    # Preserve the historical algorithm while accepting the frozen variable-scope
    # prompt. Never change the seven-unit historical recipe or its resume bytes.
    rows = legacy.read_jsonl(out / "staging/selected-candidates.jsonl")
    from experiments.translation_reference_judge import validate_response
    ledger, accepted, disputes = [], [], []
    for row in rows:
        records = []
        for phase in ("primary", "review"):
            path = out / f"reviews/{phase}/{row['id']}.json"
            record = legacy.read_json(path) if path.exists() else None
            if record is not None:
                validate_response(row, record)
                validate_execution(out, phase, row)
            records.append(record)
        status, decision = "pending", None
        if all(record is not None for record in records):
            first, second = records
            if first["status"] == second["status"] and first["translations"] == second["translations"]:
                status = "excluded" if first["status"] == "exclude" else "agreed"
                decision = first if status == "agreed" else None
            else:
                status = "dispute"
                opinions = list(records)
                legacy.rng(f"flow-v2-adjudication|{row['id']}").shuffle(opinions)
                disputes.append({"window_id": row["id"], "packet": legacy.packet(row),
                    "anonymized_opinions": opinions, "maximum_adjudications": 1,
                    "instruction": "Resolve only from supplied source. If unresolved exclude; never guess. Return resolved and nonempty resolution_zh."})
                path = out / f"reviews/adjudication/{row['id']}.json"
                if path.exists():
                    adjudication = legacy.read_json(path)
                    validate_response(row, adjudication, True)
                    validate_execution(out, "adjudication", row)
                    status = "adjudicated" if adjudication["resolved"] and adjudication["status"] != "exclude" else "excluded"
                    decision = {k: v for k, v in adjudication.items() if k not in {"resolved", "resolution_zh"}} if status == "adjudicated" else None
        ledger.append({"window_id": row["id"], "status": status, "selection_group": row["selection_group"]})
        if decision is not None:
            accepted.append({"row": row, "decision": decision})
    legacy.write_jsonl(out / "audit/review-ledger.jsonl", ledger)
    legacy.write_jsonl(out / "adjudication-jobs.jsonl", disputes)
    legacy.write_jsonl(out / "staging/resolved-references.jsonl", accepted)
    summary = {"counts": dict(Counter(r["status"] for r in ledger)), "disputes": len(disputes), "inference_allowed": False}
    legacy.write_json(out / "audit/review-summary.json", summary)
    return summary


def replace_excluded(out: Path) -> Json:
    reconcile(out)
    _, rows = validate(out)
    excluded = {r["window_id"] for r in legacy.read_jsonl(out / "audit/review-ledger.jsonl") if r["status"] == "excluded"}
    reserves = legacy.read_jsonl(out / "staging/reserve-candidates.jsonl")
    history_path = out / "audit/replacements.jsonl"
    history = legacy.read_jsonl(history_path) if history_path.exists() else []
    used = {r["id"] for r in rows} | {r["removed"] for r in history}
    replacements, shortfalls, updated = [], [], []
    for row in rows:
        replacement = next((r for r in reserves if r["selection_group"] == row["selection_group"] and r["selection_type"] == row["selection_type"] and r["id"] not in used), None) if row["id"] in excluded else None
        if replacement is not None:
            replacement = {**replacement, "split": row["split"]}
        if row["id"] in excluded and replacement is None:
            shortfalls.append({"window_id": row["id"], "selection_group": row["selection_group"], "reason": "frozen_same_group_reserves_exhausted"})
        if replacement is not None:
            used.add(replacement["id"])
            proof = out / f"audit/excluded-reference-decisions/{row['id']}.json"
            legacy.write_json(proof, {"status": "excluded", "row": row})
            replacements.append({"removed": row["id"], "added": replacement["id"], "selection_group": row["selection_group"], "quota_group": quota_group(row), "reason": "double_fresh_reference_excluded", "exclusion_proof_sha256": legacy.digest(proof)})
            legacy.write_json(out / f"review-packets/{replacement['id']}.json", legacy.packet(replacement))
        updated.append(replacement or row)
    check_scope(updated)
    if replacements:
        generation = len(list((out / "audit").glob("selected-before-replacement-*.jsonl")))
        legacy.write_jsonl(out / f"audit/selected-before-replacement-{generation:04d}.jsonl", rows)
        legacy.write_jsonl(out / f"audit/review-jobs-before-replacement-{generation:04d}.jsonl", legacy.read_jsonl(out / "review-jobs.jsonl"))
        legacy.write_jsonl(out / "staging/selected-candidates.jsonl", updated)
        legacy.write_jsonl(history_path, history + replacements)
        legacy.write_jsonl(out / "review-jobs.jsonl", jobs(updated))
    result = {"replaced": len(replacements), "shortfalls": shortfalls, "inference_allowed": False}
    legacy.write_json(out / "audit/replacement-summary.json", result)
    return result


def freeze(out: Path) -> Json:
    if (out / "freeze-manifest.json").exists() or (out / "reference/windows.jsonl").exists():
        raise ValueError("Frozen or partially exported reference corpus cannot be overwritten")
    manifest, rows = validate(out)
    summary = reconcile(out)
    if sum(summary["counts"].get(k, 0) for k in ("agreed", "adjudicated")) != manifest["target_windows"]:
        raise ValueError("Cannot freeze incomplete double-fresh reference review")
    references, inputs = [], []
    for record in legacy.read_jsonl(out / "staging/resolved-references.jsonl"):
        row, decision = record["row"], record["decision"]
        units = [{**u, **({"zh": decision["translations"][u["id"]]} if u["score"] else {})} for u in row["units"]]
        references.append({**row, "units": units, "review_status": "double_fresh_reviewed_scored_ids", "review_note": decision["reason_zh"]})
        inputs.append({"id": row["id"], "source_language": "ja", "target_language": "zh-Hans", "context": [{"id": u["id"], "text": u["ja"]} for u in row["units"]], "translate_ids": row["scored_ids"]})
    legacy.write_jsonl(out / "reference/windows.jsonl", references)
    legacy.write_jsonl(out / "model-input/windows.jsonl", inputs)
    source_rows = [{**{k: v for k, v in row.items() if k != "units"}, "units": [{k: v for k, v in unit.items() if k not in {"ja", "zh", "original_zh"}} for unit in row["units"]]} for row in rows]
    # Older staged v1 runs already bind absolute source paths in every row.
    # Their original source-manifest bytes are immutable; recover corpus metadata
    # from those bound manifests instead of rewriting the staging identity.
    external_corpus = manifest.get("external_corpus")
    if external_corpus is None:
        external_corpus = next((legacy.read_json(Path(a["path"])).get("external_corpus") for a in manifest["sources"] if Path(a["path"]).name == "source-manifest.json" and legacy.read_json(Path(a["path"])).get("external_corpus")), str(out))
    metadata = {"corpus_version": VERSION, "external_corpus": external_corpus}
    # Source-only publication compares literal provenance with the immutable
    # original selection. Hydration uses absolute paths internally; exports
    # restore their corpus-relative representation without changing references.
    corpus_root = Path(external_corpus).resolve()
    for row in source_rows:
        for key in ("source_mapping", "source_srt"):
            source_path = Path(row[key])
            row[key] = (source_path.resolve().relative_to(corpus_root).as_posix()
                        if source_path.is_absolute() else source_path.as_posix())
    legacy.write_json(out / "source-manifest.json", {**metadata, "windows": source_rows})
    for split in ("screening", "confirmation"):
        selected_ids = {r["id"] for r in rows if (r["split"] == "confirmation") == (split == "confirmation")}
        legacy.write_json(out / f"source-manifest-{split}.json", {**metadata, "windows": [r for r in source_rows if r["id"] in selected_ids]})
        legacy.write_jsonl(out / f"model-input/{split}.jsonl", [r for r in inputs if r["id"] in selected_ids])
    ledger = legacy.read_jsonl(out / "audit/review-ledger.jsonl")
    history_path = out / "audit/replacements.jsonl"
    history = legacy.read_jsonl(history_path) if history_path.exists() else []
    rejected = Counter(record["quota_group"] for record in history)
    rejection = {group: {"accepted": count, "rejected": rejected[group], "reviewed_terminal": count + rejected[group], "rejection_rate": rejected[group] / (count + rejected[group])} for group, count in manifest["quotas"].items()}
    snapshot = legacy.snapshot_final_sources(out)
    files, controls = legacy.freeze_evidence_inventory(out)
    frozen = {"corpus_version": VERSION, "state": "frozen_double_fresh_reference_review", "windows": len(rows), "scored_ids": sum(len(r["scored_ids"]) for r in rows), "quotas": manifest["quotas"], "split_counts": manifest["split_counts"], "selection_type_counts": manifest["selection_type_counts"], "rejection_by_group": rejection, "review_counts": dict(Counter(r["status"] for r in ledger)), "files": files, "excluded_control_artifacts": controls, "final_builder_snapshot": snapshot, "inference_allowed": True, "confirmation_sealed": True, "quality_limit_zh": "Sol/high同模型双轮文本复核；未验证音画，不是人工金标准。"}
    legacy.write_json(out / "freeze-manifest.json", frozen)
    return {k: v for k, v in frozen.items() if k not in {"files", "final_builder_snapshot"}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated configurable flow-v2 reference preparation")
    parser.add_argument("command", choices=("prepare", "reconcile", "replace-excluded", "freeze"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, action="append", default=[])
    parser.add_argument("--quotas", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        if not args.source_manifest:
            parser.error("prepare requires --source-manifest")
        result = prepare(args.source_manifest, args.output, legacy.read_json(args.quotas) if args.quotas else None)
    else:
        result = {"reconcile": reconcile, "replace-excluded": replace_excluded, "freeze": freeze}[args.command](args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
