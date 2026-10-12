"""Full-denominator CER and reference-span timing; no timestamp-based matching."""

import bisect
import math
import statistics
from collections import Counter
from typing import Any

from .alignment import align
from .schema import finite_time, normalize, validate_transcript

THRESHOLDS = (0.5, 2.0, 5.0)
RULE_VERSION = "nfkc-punctuation-v2-universal-complete-invariant-boundaries"
REFERENCE_KINDS = frozenset({"srt_display", "human_acoustic", "synthetic_digital_silence"})


def quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)]


def distribution(values: list[float]) -> dict[str, Any]:
    return {"n": len(values), "p50": quantile(values, 0.5), "p90": quantile(values, 0.9),
            "p95": quantile(values, 0.95), "p99": quantile(values, 0.99),
            "max": max(values) if values else None}


def _interval_error(predicted: float, interval: list[float]) -> tuple[float, float]:
    low, high = interval
    minimum = max(low - predicted, predicted - high, 0.0)
    maximum = max(abs(predicted - low), abs(predicted - high))
    return minimum, maximum


def _validate_reference(document: dict[str, Any]) -> None:
    if document.get("schema_version") != 1:
        raise ValueError("Reference schema_version must be 1")
    if document.get("reference_kind") not in REFERENCE_KINDS:
        raise ValueError("Reference kind must distinguish SRT display and human acoustic times")
    if document["reference_kind"] == "synthetic_digital_silence":
        if (document.get("spans") != [] or document.get("expected_spoken_characters") != 0
                or document.get("silence_kind") != "digital_zero_no_room_noise"
                or not isinstance(document.get("provenance"), str) or not document["provenance"].strip()
                or not finite_time(document.get("duration_seconds")) or document["duration_seconds"] <= 0):
            raise ValueError("Synthetic digital silence requires empty spans, zero expected text and explicit positive-duration digital-zero provenance")
    ids: set[str] = set()
    for span in document["spans"]:
        if span["id"] in ids:
            raise ValueError("Reference IDs must be unique")
        ids.add(span["id"])
        if not isinstance(span["text"], str):
            raise ValueError("Reference text must be a string")
        if not finite_time(span["start"]) or not finite_time(span["end"]) or not 0 <= span["start"] < span["end"]:
            raise ValueError("Reference bounds must be finite positive-duration source seconds")
        for key in ("start", "end"):
            bounds = span.get(key + "_interval", [span[key], span[key]])
            if (len(bounds) != 2 or not all(finite_time(v) for v in bounds)
                    or not bounds[0] <= span[key] <= bounds[1]):
                raise ValueError("Reference uncertainty interval must include frozen point estimate")


def evaluate(reference: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one pre-fixed scene or full film, using complete text exactly once.

    Content timing uses only exact native-unit boundaries. A segment spanning
    several reference items cannot supply internal endpoints. Character provenance
    and edit correspondence are included for reproducibility; output is private.
    """
    _validate_reference(reference)
    validate_transcript(transcript)
    spans = reference["spans"]
    raw_reference = "".join(span["text"] for span in spans)
    ref = normalize(raw_reference)
    hyp = normalize(transcript["text"])
    reference_boundaries = []
    cursor = 0
    for span in spans[:-1]:
        cursor += len(span["text"])
        reference_boundaries.append(cursor)
    for raw_start, raw_end in ref.raw_spans:
        boundary_index = bisect.bisect_right(reference_boundaries, raw_start)
        if boundary_index < len(reference_boundaries) and reference_boundaries[boundary_index] < raw_end:
            raise ValueError("Unsupported reference mapping: NFKC source cluster crosses fixed reference span boundary")
    alignment = align(ref.text, hyp.text)
    raw_starts = [a for a, _ in hyp.raw_spans]
    raw_ends = [b for _, b in hyp.raw_spans]
    covered: list[list[dict[str, Any]]] = [[] for _ in hyp.text]
    for unit in transcript.get("units", []):
        lo = bisect.bisect_left(raw_starts, unit["char_start"])
        hi = bisect.bisect_right(raw_ends, unit["char_end"])
        mapped = {**unit, "normalized_start": lo, "normalized_end": hi}
        for index in range(lo, hi):
            covered[index].append(mapped)

    def choose(index: int) -> dict[str, Any] | None:
        items = covered[index]
        if not items:
            return None
        rank = {"character": 0, "word": 1, "segment": 2}
        return min(items, key=lambda u: (rank[u["granularity"]], u["char_end"] - u["char_start"]))

    source_start = transcript.get("source_start_seconds", 0)
    source_end = transcript.get("source_end_seconds")
    if source_end is None and transcript.get("duration_seconds") is not None:
        source_end = source_start + transcript["duration_seconds"]

    def valid_unit(unit: dict[str, Any] | None) -> bool:
        return (unit is not None and unit.get("status", "ok") == "ok"
                and unit.get("time_source", "native") not in {"fallback", "interpolated"}
                and finite_time(unit.get("start")) and finite_time(unit.get("end"))
                and source_start <= unit["start"] < unit["end"]
                and (source_end is None or unit["end"] <= source_end))

    def chronological(left: int, right: int) -> bool:
        lu, ru = choose(left), choose(right)
        return valid_unit(lu) and valid_unit(ru) and lu["start"] <= ru["start"] and lu["end"] <= ru["end"]

    def invariant_timing_safe(a: int, b: int) -> bool:
        # Universal text-derived endpoints are mandatory. Neither timing values
        # nor one favorable alternative path can select the correspondence.
        if alignment.span_boundary_invariant(a, b) is None:
            return False
        if not alignment.span_has_stable_anchor(a, b, lambda r, h: ref.text[r] == hyp.text[h]):
            return False
        if not all(valid_unit(choose(index)) for index in alignment.span_candidate_positions(a, b)):
            return False
        # Every attainable adjacent reference pair must preserve unit chronology.
        # Testing pair projections is sufficient: any invalid complete path has
        # at least one invalid adjacent pair; unrelated exclusive choices do not
        # get combined into an artificial path.
        return all(chronological(left, right) for r in range(a, b - 1)
                   for left, right in alignment.possible_span_bounds(r, r + 2))

    def ambiguous_possible_thresholds(a: int, b: int, span: dict[str, Any]) -> list[float]:
        possible: set[float] = set()
        source_start = transcript.get("source_start_seconds", 0)
        source_end = transcript.get("source_end_seconds")
        if source_end is None and transcript.get("duration_seconds") is not None:
            source_end = source_start + transcript["duration_seconds"]
        allowed = set()
        for index in range(len(hyp.text)):
            unit = choose(index)
            if (unit is not None and unit.get("status", "ok") == "ok"
                    and unit.get("time_source", "native") not in {"fallback", "interpolated"}
                    and finite_time(unit.get("start")) and finite_time(unit.get("end"))
                    and source_start <= unit["start"] < unit["end"]
                    and (source_end is None or unit["end"] <= source_end)):
                allowed.add(index)
        for first_index, last_index in alignment.possible_span_bounds(
                a, b, allowed, lambda r, h: ref.text[r] == hyp.text[h], chronological):
            first, last = choose(first_index), choose(last_index)
            if (first is None or last is None or first["normalized_start"] != first_index
                    or last["normalized_end"] != last_index + 1):
                continue
            units = [first, last]
            source_start = transcript.get("source_start_seconds", 0)
            source_end = transcript.get("source_end_seconds")
            if source_end is None and transcript.get("duration_seconds") is not None:
                source_end = source_start + transcript["duration_seconds"]
            if any(unit.get("status", "ok") != "ok"
                   or unit.get("time_source", "native") in {"fallback", "interpolated"}
                   or not finite_time(unit.get("start")) or not finite_time(unit.get("end"))
                   or not source_start <= unit["start"] < unit["end"]
                   or (source_end is not None and unit["end"] > source_end) for unit in units):
                continue
            if first["start"] >= last["end"]:
                continue
            lower_s, _ = _interval_error(first["start"], span.get("start_interval", [span["start"]] * 2))
            lower_e, _ = _interval_error(last["end"], span.get("end_interval", [span["end"]] * 2))
            possible.update(t for t in THRESHOLDS if max(lower_s, lower_e) < t)
        return sorted(possible)

    rows: list[dict[str, Any]] = []
    raw_cursor = 0
    ref_raw_starts = [a for a, _ in ref.raw_spans]
    ref_raw_ends = [b for _, b in ref.raw_spans]
    for span in spans:
        raw_end = raw_cursor + len(span["text"])
        a = bisect.bisect_left(ref_raw_starts, raw_cursor)
        b = bisect.bisect_right(ref_raw_ends, raw_end)
        raw_cursor = raw_end
        if a == b:
            # Empty/nonspoken items are not speech-span timing units. Their count
            # remains explicit; silence insertion statistics are scene-level.
            rows.append({"id": span["id"], "status": "empty_reference", "characters": 0})
            continue
        positions = alignment.mapping[a:b]
        recognized = [(r, h) for r, h in enumerate(positions, a) if h is not None]
        exact = sum(ref.text[r] == hyp.text[h] for r, h in recognized)
        row: dict[str, Any] = {"id": span["id"], "characters": b - a,
                               "recognized_characters": len(recognized), "exact_characters": exact,
                               "boundary_complete": positions[0] is not None and positions[-1] is not None,
                               "normalized_reference_span": [a, b]}
        rows.append(row)
        internal_ambiguity = any(index in alignment.ambiguous for index in range(a, b))
        row["character_mapping_ambiguous"] = internal_ambiguity
        if internal_ambiguity:
            row["timing_boundary_mapping_invariant"] = alignment.span_boundary_invariant(a, b) is not None
            may_complete = alignment.complete_possible(a, b)
            row["unresolved_may_be_complete"] = may_complete
            if not may_complete:
                row["status"] = "incomplete_content" if recognized else "missing_content"
                continue
            if not invariant_timing_safe(a, b):
                row["status"] = "matching_ambiguity"
                row["unresolved_possible_thresholds"] = ambiguous_possible_thresholds(a, b, span)
                continue
            row["time_correspondence"] = "all_optimal_paths_complete_same_endpoints_valid_units"
        if not recognized:
            row["status"] = "missing_content"
            continue
        if exact == 0:
            row["status"] = "text_mismatch"
            continue
        first_index, last_index = recognized[0][1], recognized[-1][1]
        first, last = choose(first_index), choose(last_index)
        if first is None or last is None:
            row["status"] = "text_only"
            continue
        if (first["normalized_start"] != first_index
                or last["normalized_end"] != last_index + 1):
            row["status"] = "coarse_time"
            continue
        selected: list[dict[str, Any]] = []
        seen_ranges: set[tuple[int, int, str]] = set()
        for _, index in recognized:
            unit = choose(index)
            if unit is None:
                continue
            key = (unit["char_start"], unit["char_end"], unit["granularity"])
            if key not in seen_ranges:
                selected.append(unit)
                seen_ranges.add(key)
        if any(unit.get("status", "ok") == "failed" for unit in selected):
            row["status"] = "alignment_failure"
            continue
        if any(unit.get("status", "ok") == "text_only" or unit.get("start") is None
               or unit.get("end") is None for unit in selected):
            row["status"] = "text_only"
            continue
        if any(unit.get("time_source", "native") in {"fallback", "interpolated"} for unit in selected):
            row["status"] = "fallback_or_interpolated"
            continue
        source_start = transcript.get("source_start_seconds", 0)
        source_end = transcript.get("source_end_seconds")
        if source_end is None and transcript.get("duration_seconds") is not None:
            source_end = source_start + transcript["duration_seconds"]
        if (any(not finite_time(unit["start"]) or not finite_time(unit["end"])
                or not source_start <= unit["start"] < unit["end"]
                or (source_end is not None and unit["end"] > source_end) for unit in selected)
                or any(right["start"] < left["start"] or right["end"] < left["end"]
                       for left, right in zip(selected, selected[1:]))):
            row["status"] = "invalid_time"
            continue
        start, end = first["start"], last["end"]
        row["predicted_start"], row["predicted_end"] = start, end
        row["normalized_candidate_span"] = [first_index, last_index + 1]
        if len(recognized) != b - a:
            row["status"] = "incomplete_content"
            row["local_predicted_bounds"] = [start, end]
            # Local predicted bounds are preserved, but no invented partial
            # reference boundaries are used to compute an error.
            continue
        if end <= start:
            row["status"] = "invalid_time"
            continue
        ds, de = start - span["start"], end - span["end"]
        row.update(status="measurable", start_error=ds, end_error=de, error=max(abs(ds), abs(de)))
        s_range = _interval_error(start, span.get("start_interval", [span["start"]] * 2))
        e_range = _interval_error(end, span.get("end_interval", [span["end"]] * 2))
        row["error_interval"] = [max(s_range[0], e_range[0]), max(s_range[1], e_range[1])]
    measured = [row for row in rows if row["status"] == "measurable"]
    eligible = [row for row in rows if row["status"] != "empty_reference"]
    n = len(eligible)
    timing = {
        "reference_kind": reference["reference_kind"], "denominator": n,
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "measurable_count": len(measured), "measurable_coverage": len(measured) / n if n else None,
        "boundary_complete_count": sum(row.get("boundary_complete", False) for row in eligible),
        "recognized_character_coverage": sum(row.get("recognized_characters", 0) for row in rows) / len(ref.text) if ref.text else None,
        "exact_character_coverage": sum(row.get("exact_characters", 0) for row in rows) / len(ref.text) if ref.text else None,
        "start_signed_median": statistics.median(row["start_error"] for row in measured) if measured else None,
        "end_signed_median": statistics.median(row["end_error"] for row in measured) if measured else None,
        "start_absolute": distribution([abs(row["start_error"]) for row in measured]),
        "end_absolute": distribution([abs(row["end_error"]) for row in measured]),
        "error": distribution([row["error"] for row in measured]),
        "over_threshold_counts": {str(t): sum(row["error"] > t for row in measured) for t in THRESHOLDS},
        "success": {},
    }
    for threshold in THRESHOLDS:
        success = sum(row["error_interval"][1] < threshold for row in measured)
        uncertain = sum(row["error_interval"][0] < threshold <= row["error_interval"][1] for row in measured)
        uncertain += sum(row["status"] == "matching_ambiguity" and threshold in row["unresolved_possible_thresholds"] for row in eligible)
        timing["success"][str(threshold)] = {"success_count": success, "unresolved_count": uncertain,
                                              "lower": success / n if n else None,
                                              "upper": (success + uncertain) / n if n else None}
    joint = [row["error"] if row["status"] == "measurable" else math.inf for row in eligible]
    timing["joint_completeness_timing"] = distribution(joint)
    timing["joint_completeness_timing"]["nonfinite_count"] = sum(not math.isfinite(v) for v in joint)
    edits = alignment.substitutions + alignment.deletions + alignment.insertions
    result = {
        "schema_version": 1, "rule_version": RULE_VERSION,
        "reference_kind": reference["reference_kind"],
        "reference_metadata": {key: value for key, value in reference.items() if key not in {"spans", "schema_version"}},
        "text": {"reference_characters": len(ref.text), "candidate_characters": len(hyp.text),
                 "S": alignment.substitutions, "D": alignment.deletions, "I": alignment.insertions,
                 "CER": edits / len(ref.text) if ref.text else None,
                 "deletion_rate": alignment.deletions / len(ref.text) if ref.text else None,
                 "silence_hallucination_characters": len(hyp.text) if not ref.text else 0},
        "timing": timing, "spans": rows,
        "mapping": {"reference_to_candidate": list(alignment.mapping),
                    "ambiguous_reference_characters": sorted(alignment.ambiguous),
                    "reference_raw_spans": list(ref.raw_spans), "candidate_raw_spans": list(hyp.raw_spans)},
        "display": display_diagnostics(transcript),
        "limitations": [{"srt_display": "SRT display boundaries are not acoustic ground truth",
                         "human_acoustic": "Human reference uncertainty is reported separately from point-estimate quantiles",
                         "synthetic_digital_silence": "Generated digital-zero samples establish expected empty text, not room-noise robustness or human acoustic labels"}[reference["reference_kind"]],
                        "No human adjudication, speaker/number error attribution, or acoustic silence detection",
                        "Conditional quantiles use this candidate's measurable subset; small correlated samples do not establish general tail guarantees"],
    }
    return result


def display_diagnostics(transcript: dict[str, Any]) -> dict[str, Any]:
    """Structural writer observations; no acoustic silence is inferred from gaps."""
    cues = transcript.get("cues", [])
    valid = [cue for cue in cues if finite_time(cue.get("start")) and finite_time(cue.get("end"))
             and 0 <= cue["start"] < cue["end"]]
    durations = [cue["end"] - cue["start"] for cue in valid]
    text = normalize("".join(cue.get("text", "") for cue in cues)).text
    original = normalize(transcript["text"]).text
    return {"cue_count": len(cues), "invalid_cue_count": len(cues) - len(valid),
            "durations": distribution(durations),
            "overlap_count": sum(b["start"] < a["end"] for a, b in zip(valid, valid[1:])),
            "writer_text_preserved": text == original,
            "internal_acoustic_silence": "unverified_without_independent_speech_annotation"}


def micro_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate independent fixed scenes, retaining pure-silence insertions."""
    totals = {key: sum(result["text"][key] for result in results)
              for key in ("reference_characters", "candidate_characters", "S", "D", "I", "silence_hallucination_characters")}
    n = totals["reference_characters"]
    totals["CER"] = (totals["S"] + totals["D"] + totals["I"]) / n if n else None
    totals["deletion_rate"] = totals["D"] / n if n else None
    return totals
