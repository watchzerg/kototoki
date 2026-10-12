"""Freeze source-only v2 flow samples and keep confirmation semantics sealed."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .prepare import digest, read_json, write_json, write_jsonl

VERSION = "hy30-flow-v2-source-v1"
SEED = "hy30-flow-v2-c-20261008"
WORKS = ("W01", "W02", "W03", "W06", "W09", "W11", "M01", "M02", "M03", "M04")
Json = dict[str, Any]


def shuffled(items: list[Any], key: str) -> list[Any]:
    result = list(items)
    random.Random(hashlib.sha256(f"{SEED}|{key}".encode()).digest()).shuffle(result)
    return result


def policy() -> Json:
    return {
        "version": VERSION, "seed": SEED, "works": list(WORKS),
        "screening": {"representative": 72, "risk": 24}, "confirmation": 48,
        "scene_cues": [80, 160], "max_windows_per_scene": 3, "scored_cues_per_window": 5,
        "history_rule": "Exclude old dev/test and historical1200 full visible event IDs from scoring. Historical overlap in unscored scene context is allowed, quantified, and never called unseen source.",
        "isolation": "Series use disjoint entire episodes; movies use disjoint full visible source partitions, including source preparation and warm-up. No source outside the frozen scene is permitted without a new audited input identity.",
        "sampling": "Series unused episodes ordered by season/episode and divided into five bands, one random episode per band; three screening bands and two confirmation bands. Movies randomly partitioned into80-160cue scenes then divided into six timeline bands, four screening and two confirmation. Five-cue score blocks partitioned before selection; representative blocks sampled FIRST by frozen random order from the full eligible frame, then risk blocks ranked by deterministic Japanese-only proxies among the remaining blocks.",
        "risk_selection": "Japanese-only regex proxies for negation/condition, ellipsis/anaphora, speaker change markers, long sentence, honorific/entity, repeated short lines and revelation. Proxy tags are not semantic verification.",
        "replacement": "Use next nonoverlapping five-cue block in same scene and role order; if scene/reference context fails, use frozen same-band scene reserve and rebuild all scene windows as a new source identity before inference. Never move confirmation into screening.",
        "representativeness": "Conditional on mechanically eligible five-cue block frame and deterministic scene allocation, not all possible subtitle windows. Report source and reference rejection rates; risk layer is diagnostic only.",
        "confirmation": "Japanese semantics stored only in evaluation-only/source-confirmation until candidate freeze. Public audit contains metadata and hashes only.",
    }


def parse_srt(path: Path) -> list[Json]:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    def milliseconds(value: str) -> int:
        h, m, s, ms = map(int, re.split(r"[:,]", value))
        return ((h * 60 + m) * 60 + s) * 1000 + ms
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise ValueError(f"Invalid Japanese SRT: {path}")
        match = re.fullmatch(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", lines[1].strip())
        if not match:
            raise ValueError(f"Invalid Japanese timestamp: {path}")
        cues.append({"ja_srt_index": int(lines[0]), "index_text": lines[0], "time_line": lines[1], "start_ms": milliseconds(match[1]), "end_ms": milliseconds(match[2]), "ja": "\n".join(lines[2:])})
    if [x["ja_srt_index"] for x in cues] != list(range(1, len(cues) + 1)):
        raise ValueError(f"Noncontiguous Japanese cue indices: {path}")
    return cues


def load_source(corpus: Path, source: Json) -> list[Json]:
    """SRT supplies semantic text; mixed mapping supplies metadata only."""
    mapping = read_json(corpus / source["source_mapping"])
    if mapping["源SHA256"] != source["source_sha256"]:
        raise ValueError("Source identity mismatch")
    # No Chinese text is accessed or serialized; drop its track after metadata projection.
    zh_by_start: dict[int, list[Json]] = defaultdict(list)
    for item in mapping["语言轨"]["zh"]:
        zh_by_start[item["开始毫秒"]].append({"zh_srt_index": item["SRT序号"], "zh_end_ms": item["结束毫秒"], "events": item["源事件"]})
    ja_track = [{"index": item["SRT序号"], "start_ms": item["开始毫秒"], "end_ms": item["结束毫秒"], "events": item["源事件"], "flags": item["标记"]} for item in mapping["语言轨"]["ja"]]
    del mapping
    ja_start_counts = Counter(x["start_ms"] for x in ja_track)
    cues = parse_srt(corpus / source["source_srt"])
    if len(cues) != len(ja_track):
        raise ValueError("Japanese mapping/SRT count mismatch")
    for cue, meta in zip(cues, ja_track, strict=True):
        if (cue["ja_srt_index"], cue["start_ms"], cue["end_ms"]) != (meta["index"], meta["start_ms"], meta["end_ms"]):
            raise ValueError("Japanese mapping/SRT provenance mismatch")
        matches = zh_by_start[cue["start_ms"]]
        pair = matches[0] if len(matches) == 1 and ja_start_counts[cue["start_ms"]] == 1 else None
        cue.update({"source_events": {"ja": meta["events"], "zh": pair["events"] if pair else []}, "flags": meta["flags"], "zh_srt_index": pair["zh_srt_index"] if pair else None})
    return cues


def event_keys(source_hash: str, cues: list[Json]) -> set[str]:
    return {f"{source_hash}|{lang}|{e['Dialogue序号']}" for cue in cues for lang, events in cue["source_events"].items() for e in events}


def risk_tags(cues: list[Json]) -> list[str]:
    text = "\n".join(x["ja"] for x in cues)
    patterns = {
        "negation_condition": r"ない|なかった|ません|なければ|なら|たら|ても|なく",
        "ellipsis_reference": r"それ|あれ|これ|彼|彼女|あいつ|こいつ|…|\.\.\.",
        "speaker_change_proxy": r"[（(].+[)）]|[―—]",
        "honorific_entity_proxy": r"さん|様|さま|殿|先生|隊長|[ァ-ヶ]{4,}",
        "information_revelation_proxy": r"実は|まさか|正体|秘密|本当|つまり|だったの",
    }
    tags = [tag for tag, pattern in patterns.items() if re.search(pattern, text)]
    if max(len(x["ja"]) for x in cues) >= 35 or len(text) >= 110:
        tags.append("long_sentence")
    short = [x["ja"].strip() for x in cues if len(x["ja"].strip()) <= 10]
    if len(short) >= 3 or len(set(short)) < len(short):
        tags.append("repeated_short_proxy")
    return sorted(tags)


def partitions(cues: list[Json], key: str) -> list[tuple[int, int]]:
    generator = random.Random(hashlib.sha256(f"{SEED}|partition|{key}".encode()).digest())
    ranges = []
    start = 0
    while len(cues) - start >= 80:
        remaining = len(cues) - start
        size = generator.randint(80, min(160, remaining))
        if 0 < remaining - size < 80 and remaining <= 160:
            size = remaining
        ranges.append((start, start + size))
        start += size
    return ranges


def score_frame(cues: list[Json], source_hash: str, forbidden: set[str], key: str) -> tuple[list[Json], list[Json]]:
    offset = random.Random(hashlib.sha256(f"{SEED}|score-offset|{key}".encode()).digest()).randrange(5)
    frame, excluded = [], []
    for start in range(offset, len(cues) - 4, 5):
        chunk = cues[start:start + 5]
        reason = None
        if event_keys(source_hash, chunk) & forbidden:
            reason = "historically_visible_scoring_events"
        elif any(x["zh_srt_index"] is None for x in chunk):
            reason = "nonunique_time_pairing"
        elif any(chunk[i + 1]["zh_srt_index"] != chunk[i]["zh_srt_index"] + 1 for i in range(4)):
            reason = "nonconsecutive_reference_indices"
        elif any(not x["ja"].strip() or x["end_ms"] <= x["start_ms"] for x in chunk):
            reason = "invalid_japanese_source"
        row = {"start": start, "ids": [x["id"] for x in chunk], "risk_tags": risk_tags(chunk)}
        if reason:
            excluded.append({"scene_id": key, "start": start, "reason": reason})
        else:
            frame.append(row)
    return frame, excluded


def select_scene(source: Json, cues: list[Json], bounds: tuple[int, int], scene_id: str, split: str, quota: int, risk_quota: int, forbidden: set[str]) -> tuple[Json, list[Json], list[Json], Json, list[Json]]:
    start, stop = bounds
    segment = [{**cue, "id": f"F2-{source['episode_id']}-J{cue['ja_srt_index']:05d}"} for cue in cues[start:stop]]
    frame, excluded = score_frame(segment, source["source_sha256"], forbidden, scene_id)
    if len(frame) < quota:
        raise ValueError(f"Insufficient eligible scoring blocks: {scene_id} ({len(frame)}/{quota})")
    rep_order = shuffled(frame, f"representative|{scene_id}")
    rep_chosen = rep_order[:quota - risk_quota]
    rep_starts = {r["start"] for r in rep_chosen}
    risk_order = sorted(shuffled([r for r in frame if r["start"] not in rep_starts], f"risk|{scene_id}"), key=lambda r: -len(r["risk_tags"]))
    risk_chosen = [r for r in risk_order if r["risk_tags"]][:risk_quota]
    if len(risk_chosen) != risk_quota:
        raise ValueError(f"Insufficient Japanese risk proxies: {scene_id}")
    roles = [(r, "risk") for r in risk_chosen] + [(r, "representative") for r in rep_chosen]
    units = [{"id": x["id"], "ja_srt_index": x["ja_srt_index"], "zh_srt_index": x["zh_srt_index"], "start": x["start_ms"] / 1000, "end": x["end_ms"] / 1000, "start_ms": x["start_ms"], "end_ms": x["end_ms"], "index_text": x.get("index_text", str(x["ja_srt_index"])), "time_line": x.get("time_line"), "source_events": x["source_events"], "flags": x["flags"]} for x in segment]
    keys = event_keys(source["source_sha256"], segment)
    base = {**source, "scene_id": scene_id, "split": split, "units": units, "visible_start_index": start + 1, "visible_end_index": stop, "source_event_keys": sorted(keys), "historically_visible_context_events": len(keys & forbidden), "position_stratum": source["band"], "selection_group": scene_id}
    def window(row: Json, role: str) -> Json:
        wid = f"{scene_id}-Q{row['start']:03d}"
        return {**base, "id": wid, "window_id": wid, "scored_ids": row["ids"], "selection_type": role, "risk_tags": row["risk_tags"], "units": [{**x, "score": x["id"] in row["ids"]} for x in units]}
    selected = [window(r, role) for r, role in roles]
    selected_starts = {r["start"] for r, _ in roles}
    reserves = []
    for role, ordered in [("representative", rep_order), ("risk", risk_order if risk_quota else [])]:
        for rank, row in enumerate(ordered):
            if row["start"] not in selected_starts and (role != "risk" or row["risk_tags"]):
                reserves.append({**window(row, role), "reserve_rank": rank})
    scene = {"id": scene_id, "scene_id": scene_id, "source_language": "ja", "target_language": "zh-Hans", "context": [{"id": x["id"], "text": x["ja"], "start": x["start_ms"] / 1000, "end": x["end_ms"] / 1000} for x in segment], "translate_ids": [x["id"] for x in segment]}
    order = {"scene_id": scene_id, "quota": quota, "risk_quota": risk_quota, "eligible_blocks": len(frame), "representative_conditional_probability": (quota - risk_quota) / len(frame), "representative_order": [r["start"] for r in rep_order], "risk_order": [r["start"] for r in risk_order if r["risk_tags"]], "initial_selected": [x["id"] for x in selected]}
    return scene, selected, reserves, order, excluded


def audit_isolation(windows: list[Json]) -> Json:
    by_scene = {row["scene_id"]: row for row in windows}
    scenes = list(by_scene.values())
    for i, a in enumerate(scenes):
        for b in scenes[i + 1:]:
            if a["source_sha256"] != b["source_sha256"]:
                continue
            if a["split"].startswith("screen") == b["split"].startswith("screen"):
                continue
            if a["category"] == "anime_series":
                raise ValueError("Screening/confirmation episode overlap")
            if max(a["visible_start_index"], b["visible_start_index"]) <= min(a["visible_end_index"], b["visible_end_index"]):
                raise ValueError("Screening/confirmation full visible interval overlap")
            if set(a["source_event_keys"]) & set(b["source_event_keys"]):
                raise ValueError("Screening/confirmation source event overlap")
    counts = Counter(x["scene_id"] for x in windows)
    if max(counts.values(), default=0) > 3:
        raise ValueError("More than three scoring windows per scene")
    scored = [x for row in windows for x in row["scored_ids"]]
    if len(scored) != len(set(scored)):
        raise ValueError("Overlapping scored IDs")
    return {"valid": True, "scenes": len(scenes), "scored_windows": len(windows), "scored_ids": len(scored), "scope": "whole episodes and full movie visible intervals including warm-up/source preparation", "historical_context_overlap_events": sum(x["historically_visible_context_events"] for x in scenes)}


def prepare(corpus: Path, history: Path, run: Path) -> Json:
    corpus, history, run = corpus.resolve(), history.resolve(), run.resolve()
    if run == corpus or corpus in run.parents or run in corpus.parents:
        raise ValueError("Output must be separate from read-only external corpus")
    source_out = run / "source"
    confirm_out = run / "evaluation-only/source-confirmation"
    if source_out.exists() or confirm_out.exists():
        raise ValueError("Source output must be new; preserve prior identities")
    # This policy is persisted BEFORE selecting any source or window.
    write_json(source_out / "sampling-policy.json", policy())
    historical = read_json(history / "source-manifest.json")["windows"]
    historical_manifest = read_json(history / "manifest.json")
    forbidden = set(read_json(history / "audit/forbidden-event-keys.json"))
    forbidden.update(key for row in historical for key in row["source_event_keys"])
    used_series = set(historical_manifest["old_series_source_hashes"])
    used_series.update(row["source_sha256"] for row in historical if row["category"] == "anime_series")
    anime = read_json(corpus / "动画v1/构建清单.json")
    movies = read_json(corpus / "电影补充/电影构建清单.json")
    windows, reserves, scenes, orders, scene_orders, exclusions, consumed = [], [], [], [], [], [], []
    def consume(source: Json) -> list[Json]:
        consumed.extend([corpus / source["source_mapping"], corpus / source["source_srt"]])
        source["source_srt_sha256"] = digest(corpus / source["source_srt"])
        source["source_mapping_sha256"] = digest(corpus / source["source_mapping"])
        return load_source(corpus, source)
    def add(source: Json, cues: list[Json], bounds: tuple[int, int], role: str, quota: int, risk: int, sid: str) -> None:
        s, w, r, o, e = select_scene(source, cues, bounds, sid, role, quota, risk, forbidden)
        scenes.append((role, s)); windows.extend(w); reserves.extend(r); orders.append(o); exclusions.extend(e)
    for work_id in WORKS:
        if work_id.startswith("W"):
            eligible = sorted([e for e in anime["集"] if e["作品ID"] == work_id and e["选用SHA256"] not in used_series], key=lambda e: (e["季"], e["集ID"]))
            # Interleave role bands to cover early, middle and late source positions.
            for band, role in enumerate(("screening", "confirmation", "screening", "confirmation", "screening")):
                members = eligible[len(eligible) * band // 5:len(eligible) * (band + 1) // 5]
                ordered = shuffled(members, f"episodes|{work_id}|{band}")
                scene_orders.append({"work_id": work_id, "band": band, "role": role, "episode_order": [e["集ID"] for e in ordered]})
                if not ordered:
                    raise ValueError(f"No unused episode: {work_id}/{band}")
                success = False
                for episode_rank, e in enumerate(ordered):
                    prefix = f"动画v1/清洗候选/{work_id}/{e['集ID']}"
                    source = {"work_id": work_id, "work": e["作品"], "category": "anime_series", "episode_id": e["集ID"], "episode": f"{e['季']}|{e['原始集标识']}", "source_sha256": e["选用SHA256"], "source_mapping": f"{prefix}/事件映射.json", "source_srt": f"{prefix}/ja.srt", "band": band}
                    cues = consume(source)
                    bounds_order = shuffled(partitions(cues, e["集ID"]), f"scene|{e['集ID']}|{band}")
                    scene_orders[-1].setdefault("scene_orders", {})[e["集ID"]] = bounds_order
                    screen_rank = (0, 2, 4).index(band) if role == "screening" else (1, 3).index(band)
                    quota = (3, 3, 2)[screen_rank] if role == "screening" else 2
                    risk = int(role == "screening" and screen_rank < 2)
                    for bounds in bounds_order:
                        sid = f"F2-{e['集ID']}-S{bounds[0] + 1:05d}"
                        try:
                            add(source, cues, bounds, role, quota, risk, sid)
                        except ValueError as err:
                            exclusions.append({"scene_id": sid, "reason": str(err), "episode_reserve_rank": episode_rank})
                            continue
                        success = True
                        break
                    if success:
                        break
                if not success:
                    raise ValueError(f"Source preparation shortage: {work_id}/{band}")
        else:
            e = next(x for x in movies["作品"] if x["作品ID"] == work_id)
            prefix = f"电影补充/{work_id}/清洗候选"
            source = {"work_id": work_id, "work": e["作品"], "category": "animation_movie", "episode_id": work_id, "episode": work_id, "source_sha256": e["源SHA256"], "source_mapping": f"{prefix}/事件映射.json", "source_srt": f"{prefix}/ja.srt", "series_cluster": "SAO" if work_id in ("M01", "M02") else work_id}
            cues = consume(source); bounds_all = partitions(cues, work_id)
            for band, role in enumerate(("screening", "confirmation", "screening", "screening", "confirmation", "screening")):
                members = bounds_all[len(bounds_all) * band // 6:len(bounds_all) * (band + 1) // 6]
                ordered = shuffled(members, f"movie-scenes|{work_id}|{band}")
                scene_orders.append({"work_id": work_id, "band": band, "role": role, "scene_order": ordered})
                screen_rank = (0, 2, 3, 5).index(band) if role == "screening" else -1
                for bounds in ordered:
                    sid = f"F2-{work_id}-S{bounds[0] + 1:05d}"
                    try:
                        add({**source, "band": band}, cues, bounds, role, 3, int(role == "screening" and screen_rank < 3), sid)
                    except ValueError as err:
                        exclusions.append({"scene_id": sid, "reason": str(err)})
                        continue
                    break
                else:
                    raise ValueError(f"Source preparation shortage: {work_id}/{band}")
    for work_id in WORKS:
        screen_rows = [r for r in windows if r["work_id"] == work_id and r["split"] == "screening"]
        movie_index = int(work_id[1:]) - 1 if work_id.startswith("M") else -1
        for role in ("representative", "risk"):
            rows = shuffled([r for r in screen_rows if r["selection_type"] == role], f"split|{work_id}|{role}")
            first = len(rows) // 2
            if work_id.startswith("M"):
                first += int((movie_index % 2 == 0) == (role == "representative"))
            for rank, row in enumerate(rows):
                row["split"] = "screen-a" if rank < first else "screen-b"
    overlap = audit_isolation(windows)
    counts = Counter((r["split"], r["selection_type"]) for r in windows)
    expected = {("screen-a", "representative"): 36, ("screen-a", "risk"): 12, ("screen-b", "representative"): 36, ("screen-b", "risk"): 12, ("confirmation", "representative"): 48}
    if dict(counts) != expected:
        raise ValueError(f"Unexpected v2 quotas: {counts}")
    screen_windows = [r for r in windows if r["split"].startswith("screen")]
    # At least one calibration window per work; the other six follow a frozen hash order.
    calibration = [shuffled([r for r in screen_windows if r["work_id"] == work], f"calibration|{work}")[0]["id"] for work in WORKS]
    calibration += [r["id"] for r in shuffled(screen_windows, "calibration-extra") if r["id"] not in calibration][:6]
    for role, out in [("screening", source_out / "screening"), ("confirmation", confirm_out)]:
        selected = [r for r in windows if (r["split"] == "confirmation") == (role == "confirmation")]
        role_scenes = [s for r, s in scenes if r == role]
        ids = {s["scene_id"] for s in role_scenes}
        write_json(out / "source-manifest.json", {"version": VERSION, "external_corpus": str(corpus), "windows": selected})
        write_jsonl(out / "audit/reserve-manifest.jsonl", [r for r in reserves if r["scene_id"] in ids])
        write_json(out / "audit/window-orders.json", [o for o in orders if o["scene_id"] in ids])
        write_json(out / "audit/scene-orders.json", [o for o in scene_orders if o["role"] == role])
        write_jsonl(out / "model-input/scenes.jsonl", role_scenes)
        source_by_scene = {s["scene_id"]: s for s in role_scenes}
        write_jsonl(out / "model-input/windows.jsonl", [{"id": r["id"], "source_language": "ja", "target_language": "zh-Hans", "context": [{"id": x["id"], "text": x["text"]} for x in source_by_scene[r["scene_id"]]["context"]], "translate_ids": r["scored_ids"]} for r in selected])
        write_jsonl(out / "audit/exclusions.jsonl", [e for e in exclusions if e.get("scene_id") in ids])
        write_json(out / "audit/selection-exclusions.json", [e for e in exclusions if e.get("scene_id") not in {o["scene_id"] for o in orders}])
        if role == "screening":
            write_json(out / "calibration-selection.json", {"version": VERSION, "window_ids": calibration, "count": 16, "semantic_repeats": 2, "sample_count_increase": 0})
        artifacts = [{"path": p.relative_to(out).as_posix(), "sha256": digest(p)} for p in sorted(out.rglob("*")) if p.is_file()]
        write_json(out / "freeze-manifest.json", {"version": VERSION, "state": "source_frozen_reference_unreviewed", "role": role, "windows": len(selected), "scenes": len(role_scenes), "scored_ids": sum(len(r["scored_ids"]) for r in selected), "policy_sha256": digest(source_out / "sampling-policy.json"), "artifacts": artifacts})
    provenance = [corpus / "freeze_manifest.json", corpus / "动画v1/构建清单.json", corpus / "电影补充/电影构建清单.json", history / "manifest.json", history / "source-manifest.json", history / "audit/forbidden-event-keys.json"] + consumed
    summary = {"version": VERSION, "state": "source_frozen_reference_unreviewed", "seed": SEED, "screening_windows": 96, "screening_representative": 72, "screening_risk": 24, "confirmation_windows": 48, "screening_scenes": sum(r == "screening" for r, _ in scenes), "confirmation_scenes": sum(r == "confirmation" for r, _ in scenes), "per_work": {work: {"screening": sum(r["work_id"] == work and r["split"].startswith("screen") for r in windows), "confirmation": sum(r["work_id"] == work and r["split"] == "confirmation" for r in windows)} for work in WORKS}, "overlap": overlap, "source_rejections": dict(Counter(e["reason"] for e in exclusions)), "confirmation_semantics_sealed": True, "source_inputs": [{"path": str(p), "sha256": digest(p)} for p in sorted(set(provenance))], "builder_sha256": digest(Path(__file__))}
    write_json(source_out / "source-audit-summary.json", summary)
    return {k: summary[k] for k in ("version", "state", "screening_windows", "confirmation_windows", "screening_scenes", "confirmation_scenes", "confirmation_semantics_sealed", "overlap", "source_rejections")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.corpus, args.history, args.run), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
