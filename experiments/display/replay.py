"""Replay normalized units through a frozen minimal SRT presentation contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RULES = {"revision": "minimal-display-v1-2026-10-04", "max_gap_seconds": 0.4,
         "max_duration_seconds": 7.0, "max_characters": 42,
         "sentence_endings": ".!?。！？", "time_rounding": "nearest millisecond, half upward",
         "untimed_nonlexical_policy": "attach only punctuation/whitespace between or beside valid timed units",
         "unit_order": "original Python character positions", "time_repairs": "none"}


def finite_time(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def nonlexical(text: str) -> bool:
    return all(char.isspace() or unicodedata.category(char).startswith("P") for char in text)


def milliseconds(seconds: float) -> int:
    return math.floor(seconds * 1000 + 0.5)


def srt_time(ms: int) -> str:
    hours, remainder = divmod(ms, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, fraction = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}"


def json_safe(value: Any) -> Any:
    """Keep invalid native numeric evidence visible in standards-compliant JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite_number": repr(value)}
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def complement_ranges(text: str, covered: set[int]) -> list[dict[str, Any]]:
    ranges = []
    begin = None
    for index in range(len(text) + 1):
        missing = index < len(text) and index not in covered
        if missing and begin is None:
            begin = index
        if not missing and begin is not None:
            ranges.append({"char_start": begin, "char_end": index, "text": text[begin:index]})
            begin = None
    return ranges


def display_diagnostics(cues: list[dict[str, Any]]) -> dict[str, Any]:
    valid = []
    invalid = []
    for index, cue in enumerate(cues):
        start, end = cue.get("start"), cue.get("end")
        if not finite_time(start) or not finite_time(end) or start < 0 or end <= start:
            invalid.append(index)
        else:
            valid.append((index, start, end, str(cue.get("text", ""))))
    return {"cue_count": len(cues), "valid_duration_count": len(valid),
            "invalid_cue_indices": invalid,
            "duration_seconds": [end - start for _, start, end, _ in valid],
            "overlap_count_in_original_order": sum(right[1] < left[2] for left, right in zip(valid, valid[1:])),
            "nonmonotonic_start_count": sum(right[1] < left[1] for left, right in zip(valid, valid[1:])),
            "over_7_seconds_count": sum(end - start > RULES["max_duration_seconds"] for _, start, end, _ in valid),
            "over_42_characters_count": sum(len(text) > RULES["max_characters"] for _, _, _, text in valid),
            "gap_interpretation": "predicted unit/cue gaps only; no claim of acoustic silence"}


def replay(document: dict[str, Any], source_start: float | None = None,
           source_end: float | None = None) -> tuple[str, dict[str, Any]]:
    if document.get("schema_version") != 1 or not isinstance(document.get("text"), str):
        raise ValueError("Normalized schema_version 1 and complete original text are required")
    if (source_start is not None and (not finite_time(source_start) or source_start < 0)) or (
        source_end is not None and (not finite_time(source_end) or source_end < 0)):
        raise ValueError("Source range must be finite and nonnegative")
    if source_start is not None and source_end is not None and source_end <= source_start:
        raise ValueError("Source range must have positive duration")
    text = document["text"]
    original_units = document.get("units", [])
    if not isinstance(original_units, list):
        raise ValueError("Normalized units must be an array")
    candidates = []
    rejected = []
    for index, original in enumerate(original_units):
        unit = dict(original)
        if "id" in original:
            unit["source_id"] = original["id"]
        unit["id"] = f"unit-{index:06d}"
        unit["original_index"] = index
        left, right = unit.get("char_start"), unit.get("char_end")
        reason = None
        if not isinstance(left, int) or not isinstance(right, int) or isinstance(left, bool) or isinstance(right, bool) or not 0 <= left < right <= len(text):
            reason = "invalid_character_range"
        elif unit.get("status", "ok") != "ok":
            reason = "non_success_unit_status"
        elif not finite_time(unit.get("start")) or not finite_time(unit.get("end")):
            reason = "missing_or_nonfinite_time"
        elif unit["start"] < 0 or unit["end"] <= unit["start"]:
            reason = "nonpositive_or_negative_time"
        elif source_start is not None and unit["start"] < source_start or source_end is not None and unit["end"] > source_end:
            reason = "outside_declared_source_range"
        elif milliseconds(unit["end"]) <= milliseconds(unit["start"]):
            reason = "millisecond_rounding_zero_duration"
        if reason:
            rejected.append({"reason": reason, "unit": unit})
        else:
            candidates.append(unit)
    candidates.sort(key=lambda unit: (unit["char_start"], unit["char_end"], unit["original_index"]))
    conflicting = set()
    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            if right["char_start"] >= left["char_end"]:
                break
            conflicting.update([left_index, right_index])
    units = []
    for index, unit in enumerate(candidates):
        if index in conflicting:
            rejected.append({"reason": "overlapping_character_ranges", "unit": unit})
        else:
            units.append(unit)
    cues: list[dict[str, Any]] = []
    native_covered: set[int] = set()
    attached: list[dict[str, Any]] = []
    for unit in units:
        if unit.get("time_source", "native") in {"native", "api"}:
            native_covered.update(range(unit["char_start"], unit["char_end"]))
        if not cues:
            left = 0 if nonlexical(text[:unit["char_start"]]) else unit["char_start"]
            cue = {"char_start": left, "char_end": unit["char_end"], "start": unit["start"], "end": unit["end"],
                   "unit_ids": [unit["id"]], "time_sources": [unit.get("time_source", "native")],
                   "last_unit_start": unit["start"], "last_unit_end": unit["end"]}
            cues.append(cue)
            if left < unit["char_start"]:
                attached.append({"char_start": left, "char_end": unit["char_start"], "policy": "prefix_nonlexical"})
            continue
        previous = cues[-1]
        gap_text = text[previous["char_end"]:unit["char_start"]]
        can_attach = nonlexical(gap_text)
        punctuation_stop = (text[previous["char_start"]:unit["char_start"]].rstrip().endswith(tuple(RULES["sentence_endings"])))
        gap_seconds = unit["start"] - previous["last_unit_end"]
        can_merge = (can_attach and not punctuation_stop and gap_seconds <= RULES["max_gap_seconds"]
                     and unit["start"] >= previous["last_unit_start"] and unit["end"] >= previous["last_unit_end"]
                     and unit["end"] - previous["start"] <= RULES["max_duration_seconds"]
                     and unit["char_end"] - previous["char_start"] <= RULES["max_characters"])
        if can_attach and unit["char_start"] > previous["char_end"]:
            attached.append({"char_start": previous["char_end"], "char_end": unit["char_start"],
                             "policy": "bridge_nonlexical" if can_merge else "previous_cue_suffix_nonlexical"})
        if can_merge:
            previous["char_end"] = unit["char_end"]
            previous["end"] = unit["end"]
            previous["unit_ids"].append(unit["id"])
            previous["time_sources"].append(unit.get("time_source", "native"))
            previous["last_unit_start"], previous["last_unit_end"] = unit["start"], unit["end"]
        else:
            if can_attach:
                previous["char_end"] = unit["char_start"]
            cues.append({"char_start": unit["char_start"], "char_end": unit["char_end"],
                         "start": unit["start"], "end": unit["end"], "unit_ids": [unit["id"]],
                         "time_sources": [unit.get("time_source", "native")],
                         "last_unit_start": unit["start"], "last_unit_end": unit["end"]})
    if cues and nonlexical(text[cues[-1]["char_end"]:]):
        if cues[-1]["char_end"] < len(text):
            attached.append({"char_start": cues[-1]["char_end"], "char_end": len(text), "policy": "suffix_nonlexical"})
        cues[-1]["char_end"] = len(text)
    rendered = []
    srt_blocks = []
    rendered_covered: set[int] = set()
    for index, cue in enumerate(cues):
        cue = {key: value for key, value in cue.items() if not key.startswith("last_unit_")}
        cue["text"] = text[cue["char_start"]:cue["char_end"]]
        cue["time_sources"] = sorted(set(cue["time_sources"]))
        cue["start_ms"], cue["end_ms"] = milliseconds(cue["start"]), milliseconds(cue["end"])
        normalized_lines = cue["text"].replace("\r\n", "\n")
        if not normalized_lines.strip() or normalized_lines.startswith("\n") or re.search(r"\n\s*\n", normalized_lines):
            rejected.append({"reason": "srt_blank_line_in_original_text", "cue": cue})
            continue
        cue["id"] = f"cue-{len(rendered) + 1:06d}"
        rendered.append(cue)
        rendered_covered.update(range(cue["char_start"], cue["char_end"]))
        srt_blocks.append(f"{len(rendered)}\n{srt_time(cue['start_ms'])} --> {srt_time(cue['end_ms'])}\n{cue['text']}\n")
    unrendered = complement_ranges(text, rendered_covered)
    lexical = {index for index, char in enumerate(text) if unicodedata.category(char)[0] in "LN"}
    sidecar = {"schema_version": 1, "display_rules": dict(RULES), "original_text": text,
               "original_units": original_units, "source_bounds": [source_start, source_end],
               "unified_cues": rendered, "nonlexical_associations_without_new_times": attached,
               "unrenderable": rejected, "unrendered_ranges": unrendered,
               "native_cues_preserved": document.get("cues", []),
               "native_writer_cues_preserved": document.get("native_writer_cues", []),
               "coverage": {"full_original_characters": len(text), "rendered_characters": len(rendered_covered),
                            "rendered_character_fraction": len(rendered_covered) / len(text) if text else None,
                            "native_or_api_timed_characters": len(native_covered),
                            "original_lexical_characters": len(lexical),
                            "rendered_lexical_characters": len(lexical & rendered_covered),
                            "unrendered_characters": len(text) - len(rendered_covered)},
               "diagnostics": {"unified": display_diagnostics(rendered),
                               "native": display_diagnostics(document.get("cues", [])),
                               "native_writer": display_diagnostics(document.get("native_writer_cues", [])),
                               "predicted_unit_overlap_count": sum(right["start"] < left["end"] for left, right in zip(units, units[1:])),
                               "acoustic_silence_verified": False},
               "timing_note": "provided source-media times are preserved; rounding only affects SRT milliseconds; no acoustic truth or repair asserted"}
    return "\n".join(srt_blocks), json_safe(sidecar)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--source-start", type=float)
    parser.add_argument("--source-end", type=float)
    args = parser.parse_args()
    prefix = args.output_prefix.resolve()
    if not prefix.is_relative_to((ROOT / ".local").resolve()):
        parser.error("Private display output must remain under this project's Git-ignored .local directory")
    srt_path, sidecar_path = Path(str(prefix) + ".srt"), Path(str(prefix) + ".display.json")
    if srt_path.exists() or sidecar_path.exists():
        parser.error("Output already exists; choose a new replay identity")
    document = json.loads(args.input.read_text(encoding="utf-8-sig"))
    srt, sidecar = replay(document, args.source_start, args.source_end)
    sidecar["input_identity"] = {"path": str(args.input.resolve()), "sha256": hashlib.sha256(args.input.read_bytes()).hexdigest()}
    sidecar["writer_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with sidecar_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(sidecar, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with srt_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(srt)
    print(json.dumps({"display_rules": RULES["revision"], "srt": str(srt_path), "sidecar": str(sidecar_path),
                      "coverage": sidecar["coverage"], "unrenderable_count": len(sidecar["unrenderable"]),
                      "cue_count": len(sidecar["unified_cues"])}))


if __name__ == "__main__":
    main()
