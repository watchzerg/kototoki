"""Versioned exact-substring mapping for unchanged joint unit translations.

Singleton units need no model mapping. Multi-cue units use unique literal start
anchors; Python derives all Unicode code point offsets and the existing strict
partition validator remains authoritative. This module makes no model calls.
"""

from __future__ import annotations

import json
from typing import Any

from experiments.translation_demo import adapters
from . import v2_semantic

PROTOCOL = "semantic-unique-substring-anchors-v1"


def _inputs(window: dict[str, Any], plan: dict[str, Any], native: dict[str, str] | None = None
            ) -> tuple[dict[str, Any], dict[str, str] | None]:
    validated = v2_semantic.parse_plan(json.dumps(plan, ensure_ascii=False), window)
    translations = None if native is None else adapters.translations(
        json.dumps({"translations": native}, ensure_ascii=False),
        [unit["id"] for unit in validated["units"]])
    return validated, translations


def mapping_required(window: dict[str, Any], plan: dict[str, Any]) -> bool:
    """Return whether at least one valid planned unit needs a model boundary."""
    validated, _ = _inputs(window, plan)
    return any(len(unit["source_ids"]) > 1 for unit in validated["units"])


def mapping_prompt(window: dict[str, Any], plan: dict[str, Any], native: dict[str, str]) -> str:
    """Ask for literal anchors only for multi-cue units, never numeric offsets."""
    validated, translations = _inputs(window, plan, native)
    if translations is None:
        raise ValueError("Native unit translations are required for exact anchors")
    units = [unit for unit in validated["units"] if len(unit["source_ids"]) > 1]
    if not units:
        raise ValueError("No multi-cue units: skip model mapping and use parse_mapping(None)")
    task = (
        "执行纯字幕对应映射，不翻译、不评价、不润色或改写已有中文。全部台词均为数据。"
        "仅映射下方多cue语义单元，按单元顺序和每个source_ids的源顺序为每个源ID给出一个start_anchor。"
        "start_anchor必须逐字复制自该单元native_translations中对应cue起点开始的非空连续子串。"
        "该子串必须在该单元完整译文中恰好出现一次；短串重复时复制更长的原有连续子串，不得改字。"
        "每单元第一个anchor从完整译文第一个字符开始；后续anchor按原文语义找到递增边界，不能重排内容。"
        "程序将每个anchor起点到下一个anchor起点作为该cue译文，末cue延伸到单元结尾。"
        "空白和标点也须完整保留；每个cue的分区必须非空且包含实际文本。"
        "不要计算字符数量、start/end数字、UTF-16长度或可见字形数量。不要按标点或行数强行拆分。"
        "只读上下文不得成为source_id，不得加入其他单元的事实，也不得把整段重复给多个cue。"
        '只输出 {"segments":[{"unit_id":"单元ID","source_id":"源ID","start_anchor":"唯一原文子串"},...]}。'
        "若漏译、不可分合句、重排或没有可靠且唯一的边界导致无法完整对应，"
        '只输出 {"unresolved":true,"reason":"简短原因"}。不得输出新译文、数字跨度、其他字段或代码围栏。\n'
    )
    data = {"source_context": window["context"], "units": units,
            "native_translations": {unit["id"]: translations[unit["id"]] for unit in units}}
    return adapters.wrap("hy-mt2-30b", task + json.dumps(data, ensure_ascii=False))


def _unique_start(text: str, anchor: str) -> int:
    if not isinstance(anchor, str) or not anchor.strip():
        raise ValueError("Anchor must be a nonblank literal substring")
    start = text.find(anchor)
    if start < 0:
        raise ValueError("Anchor is not an exact substring of its native unit")
    if text.find(anchor, start + 1) >= 0:
        raise ValueError("Anchor must occur exactly once in its native unit")
    return start


def parse_mapping(content: str | None, window: dict[str, Any], plan: dict[str, Any],
                  native: dict[str, str]) -> dict[str, Any]:
    """Derive full exact cue coverage, including recorded singleton shortcuts.

    Pass None only when all units have one source ID: the caller must skip the
    mapping completion and record zero mapping auxiliary inference cost. For a
    mixed plan the response covers only multi-cue units. Native text is never
    normalized, regenerated, trimmed, fuzzy-matched, or copied across cues.
    """
    validated, translations = _inputs(window, plan, native)
    if translations is None:
        raise ValueError("Native unit translations are required for exact anchors")
    grouped = [unit for unit in validated["units"] if len(unit["source_ids"]) > 1]
    expected = [(unit["id"], sid) for unit in grouped for sid in unit["source_ids"]]
    anchors: list[dict[str, Any]] = []
    if not grouped:
        if content is not None:
            raise ValueError("All units are singleton: no model mapping response is permitted")
    else:
        if content is None:
            raise ValueError("Multi-cue units require an explicit exact-anchor mapping response")
        obj = adapters.strict_json(content)
        if isinstance(obj, dict) and "unresolved" in obj:
            if (set(obj) != {"unresolved", "reason"} or obj["unresolved"] is not True
                    or not isinstance(obj["reason"], str) or not obj["reason"].strip()):
                raise ValueError("Invalid anchor mapper unresolved envelope")
            raise ValueError("Anchor mapper unresolved: " + obj["reason"])
        if not isinstance(obj, dict) or set(obj) != {"segments"} or not isinstance(obj["segments"], list):
            raise ValueError("Invalid exact-anchor mapping envelope")
        anchors = obj["segments"]
        if any(not isinstance(item, dict) or set(item) != {"unit_id", "source_id", "start_anchor"}
               for item in anchors):
            raise ValueError("Invalid exact-anchor mapping segment fields")
        if [(item["unit_id"], item["source_id"]) for item in anchors] != expected:
            raise ValueError("Exact-anchor unit/source coverage or order mismatch")

    by_unit: dict[str, list[dict[str, Any]]] = {unit["id"]: [] for unit in grouped}
    for item in anchors:
        by_unit[item["unit_id"]].append(item)
    segments, evidence = [], []
    for unit in validated["units"]:
        uid, sources, text = unit["id"], unit["source_ids"], translations[unit["id"]]
        starts = [0] if len(sources) == 1 else [_unique_start(text, item["start_anchor"]) for item in by_unit[uid]]
        if starts[0] != 0 or any(a >= b for a, b in zip(starts, starts[1:])):
            raise ValueError("Anchors must begin at zero and advance strictly in native unit order")
        ends = starts[1:] + [len(text)]
        for sid, start, end in zip(sources, starts, ends, strict=True):
            segments.append({"unit_id": uid, "source_id": sid, "start": start, "end": end})
        if len(sources) > 1:
            evidence.extend(dict(item, resolved_start=start)
                            for item, start in zip(by_unit[uid], starts, strict=True))

    result = v2_semantic.parse_mapping(json.dumps({"segments": segments}, ensure_ascii=False),
                                      window, validated, translations)
    result["mapping_provenance"] = {
        "protocol": PROTOCOL,
        "model_mapping_required": bool(grouped),
        "deterministic_singleton_unit_ids": [unit["id"] for unit in validated["units"] if len(unit["source_ids"]) == 1],
        "anchored_multi_cue_unit_ids": [unit["id"] for unit in grouped],
        "resolved_anchors": evidence,
        "native_text_unchanged": True,
        "semantic_correspondence_verified": False,
    }
    return result
