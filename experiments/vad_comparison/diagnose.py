"""Describe invariant new deletions relative to baseline CTC window support.

This optional post-study diagnostic never labels acoustic speech truth or claims
that VAD caused an omission. It consumes complete verified pairs only, retains
unavailable pair slots, and never changes the primary evaluation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from kototoki_eval.alignment import align
from kototoki_eval.schema import finite_time, normalize, validate_transcript
from experiments.analysis.build_round2 import input_identity
from experiments.components.evaluate import write_new
from .evaluate import EXPECTED_ROUTE_IDS, ROOT, digest, execution_proof, read, resolve

BUCKETS = ("outside", "crossing_boundary", "inside", "baseline_untimed")
REVISION = "invariant-reference-deletion-baseline-ctc-window-support-v1"


def source_windows(document: dict[str, Any]) -> list[tuple[float, float]]:
    """Retain original source coordinates; never concatenate speech samples."""
    offset, duration = document["source_start_seconds"], document["duration_seconds"]
    windows = []
    previous = offset
    for chunk in document.get("chunks", []):
        if "start_sample" in chunk and "end_sample" in chunk:
            bounds = (offset + chunk["start_sample"] / 16000, offset + chunk["end_sample"] / 16000)
        else:
            bounds = (offset + chunk["start"], offset + chunk["end"])
        start, end = bounds
        if (not finite_time(start) or not finite_time(end) or not previous <= start < end
                or end > offset + duration + 1e-7):
            raise ValueError("Candidate chunks must be ordered nonoverlapping source windows")
        previous = end
        windows.append(bounds)
    return windows


def support(interval: tuple[float, float], windows: list[tuple[float, float]]) -> tuple[str, bool]:
    """Classify interval support separately from full retained-union coverage."""
    start, end = interval
    if any(left <= start and end <= right for left, right in windows):
        return "inside", True
    overlaps = [(max(start, left), min(end, right)) for left, right in windows
                if max(start, left) < min(end, right)]
    if not overlaps:
        return "outside", False
    cursor = start
    for left, right in overlaps:
        if left > cursor:
            return "crossing_boundary", False
        cursor = max(cursor, right)
    return "crossing_boundary", cursor >= end


def baseline_char_interval(document: dict[str, Any], raw_span: tuple[int, int]) -> tuple[float, float] | None:
    """Accept an exact native character unit; do not interpolate coarse units."""
    a, b = raw_span
    eligible = [unit for unit in document.get("units", [])
                if unit["char_start"] == a and unit["char_end"] == b and unit["granularity"] == "character"]
    if len(eligible) != 1:
        return None
    unit = eligible[0]
    start, end = unit.get("start"), unit.get("end")
    if (unit.get("status", "ok") != "ok" or unit.get("time_source", "native") in {"fallback", "interpolated"}
            or not finite_time(start) or not finite_time(end)
            or not document["source_start_seconds"] <= start < end
            or end > document["source_start_seconds"] + document["duration_seconds"]):
        return None
    return start, end


def baseline_untimed_reason(document: dict[str, Any], raw_span: tuple[int, int]) -> str:
    a, b = raw_span
    units = [unit for unit in document.get("units", []) if unit["char_start"] == a and unit["char_end"] == b
             and unit["granularity"] == "character"]
    if len(units) != 1:
        return "no_unique_exact_character_unit"
    unit = units[0]
    if unit.get("status", "ok") != "ok":
        return "status_" + unit["status"]
    if unit.get("time_source", "native") in {"fallback", "interpolated"}:
        return "non_native_time"
    start, end = unit.get("start"), unit.get("end")
    if finite_time(start) and finite_time(end) and start == end:
        return "zero_duration"
    return "invalid_nonfinite_reversed_or_out_of_source_time"


def diagnose_pair(reference: dict[str, Any], baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Assign only unambiguous exact-baseline/new-deletion character identities."""
    validate_transcript(baseline)
    validate_transcript(candidate)
    reference_text = normalize("".join(span["text"] for span in reference["spans"])).text
    baseline_text, candidate_text = normalize(baseline["text"]), normalize(candidate["text"])
    original = align(reference_text, baseline_text.text)
    changed = align(reference_text, candidate_text.text)
    windows = source_windows(candidate)
    statuses: Counter[str] = Counter()
    buckets: Counter[str] = Counter({key: 0 for key in BUCKETS})
    untimed: Counter[str] = Counter()
    deleted = []
    union_supported = 0
    for index, char in enumerate(reference_text):
        before, after = original.mapping[index], changed.mapping[index]
        if index in original.ambiguous:
            statuses["baseline_matching_ambiguous"] += 1
        elif before is None:
            statuses["baseline_deleted"] += 1
        elif baseline_text.text[before] != char:
            statuses["baseline_substituted"] += 1
        elif index in changed.ambiguous:
            statuses["baseline_correct_candidate_matching_ambiguous"] += 1
        elif after is not None:
            statuses["baseline_correct_candidate_retained" if candidate_text.text[after] == char
                     else "baseline_correct_candidate_substituted"] += 1
        else:
            statuses["baseline_correct_candidate_newly_deleted"] += 1
            interval = baseline_char_interval(baseline, baseline_text.raw_spans[before])
            bucket, retained_union = support(interval, windows) if interval else ("baseline_untimed", None)
            buckets[bucket] += 1
            if interval is None:
                untimed[baseline_untimed_reason(baseline, baseline_text.raw_spans[before])] += 1
            union_supported += bucket == "crossing_boundary" and retained_union is True
            deleted.append({"normalized_reference_index": index,
                            "baseline_normalized_character_index": before,
                            "baseline_raw_character_span": list(baseline_text.raw_spans[before]),
                            "baseline_ctc_interval": list(interval) if interval else None,
                            "bucket": bucket, "fully_retained_by_window_union": retained_union})
    return {"reference_characters": len(reference_text), "reference_character_status_counts": dict(statuses),
            "baseline_correct_invariant_characters": sum(value for key, value in statuses.items() if key.startswith("baseline_correct_")),
            "newly_deleted_invariant_characters": len(deleted), "deletion_support_buckets": dict(buckets),
            "baseline_untimed_reason_counts": dict(untimed),
            "crossing_boundary_fully_retained_by_window_union": union_supported,
            "candidate_retained_source_duration_s": sum(end - start for start, end in windows),
            "deleted_character_observations": deleted,
            "text_alignment_scope": "All equally optimal Levenshtein paths participate in ambiguity; only invariant exact baseline correspondence and invariant candidate deletion are bucketed."}


def eligible(run: dict[str, Any] | None, document: dict[str, Any] | None) -> tuple[bool, str]:
    if not run:
        return False, "missing_run_slot"
    if run.get("status") != "completed":
        return False, "run_status_" + str(run.get("status"))
    if document is None:
        return False, "missing_result"
    if document.get("status") != "ok":
        return False, "result_not_complete"
    if run.get("execution_verified") is False:
        return False, "execution_declared_unverified"
    if not execution_proof(document)["execution_observations_pass"]:
        return False, "execution_observations_unverified"
    return True, "verified_complete"


def build(study_path: Path, output: Path) -> dict[str, Any]:
    sources = [Path(__file__), Path(__file__).with_name("evaluate.py"), ROOT / "kototoki_eval/alignment.py",
               ROOT / "kototoki_eval/schema.py", ROOT / "experiments/analysis/build_round2.py"]
    source_identity = {str(path): digest(path) for path in sources}
    study_path, output = study_path.resolve(), output.resolve()
    if study_path.is_dir():
        study_path /= "study.json"
    private = (ROOT / ".local").resolve()
    if not study_path.is_relative_to(private) or not output.is_relative_to(private) or output == private or output.exists():
        raise ValueError("Diagnostic requires a private study and new .local output directory")
    study = read(study_path)
    study_sha = digest(study_path)
    if study.get("schema_version") != 1 or study.get("terminal") is not True or not study.get("study_id"):
        raise ValueError("Diagnostic requires a terminal identified study")
    plan_path = resolve(study.get("source_plan_path", ".local/round2/plan.json"))
    if digest(plan_path) != study.get("source_plan_sha256") or read(plan_path)["clips"] != study.get("clips"):
        raise ValueError("Diagnostic must retain the exact full frozen source-plan clip registry")
    routes = study["routes"]
    if [route["id"] for route in routes] != study.get("expected_route_ids", list(EXPECTED_ROUTE_IDS)):
        raise ValueError("Diagnostic route registry differs from frozen expected routes")
    identities = {str(study_path): study_sha, str(plan_path): study["source_plan_sha256"]}
    references, documents, slots = {}, {}, {}
    clip_ids = {clip["id"] for clip in study["clips"]}
    for clip in study["clips"]:
        for field in ("audio", "reference", "source_audio", "source_srt"):
            if field not in clip:
                continue
            path = resolve(clip[field])
            if str(path) not in identities:
                identities[str(path)] = digest(path)
            if identities[str(path)] != clip.get(field + "_sha256"):
                raise ValueError("Diagnostic input/source identity differs")
        references[clip["id"]] = read(resolve(clip["reference"]))
    for route in routes:
        runs = route.get("runs", [])
        if (len({run["clip_id"] for run in runs}) != len(runs)
                or any(run["clip_id"] not in clip_ids for run in runs)):
            raise ValueError("Diagnostic run slots are duplicate or outside the frozen registry")
        for run in runs:
            slot = route["id"], run["clip_id"]
            slots[slot] = run
            path = resolve(run["result_path"]) if run.get("result_path") else None
            if path is None or not path.is_file():
                continue
            actual = digest(path)
            if not run.get("result_sha256") or actual != run["result_sha256"]:
                raise ValueError("Diagnostic result identity differs")
            identities[str(path)] = actual
            document = read(path)
            validate_transcript(document)
            clip = next(clip for clip in study["clips"] if clip["id"] == run["clip_id"])
            input_identity(document, {"audio_sha256": clip["audio_sha256"], "reference_unchanged": True}, clip)
            documents[slot] = document
            if not route["id"].endswith("-original") and run.get("status") == "completed":
                if not run.get("vad_manifest_path") or not run.get("vad_manifest_sha256"):
                    raise ValueError("Complete candidate requires a frozen VAD manifest")
                vad_path = resolve(run["vad_manifest_path"])
                vad_sha = digest(vad_path)
                if vad_sha != run["vad_manifest_sha256"]:
                    raise ValueError("Diagnostic VAD manifest identity differs")
                identities[str(vad_path)] = vad_sha
                vad = read(vad_path)
                provenance = document.get("vad_manifest_source", document.get("vad_provenance", {}))
                if (provenance.get("sha256") != vad_sha
                        or vad.get("input", {}).get("file_sha256") != clip["audio_sha256"]
                        or vad.get("offset_s") != clip["offset"]):
                    raise ValueError("Diagnostic VAD manifest does not bind same result/input/offset")
    pairs, summaries = [], []
    for route in routes:
        if route["id"].endswith("-original"):
            continue
        family = route["id"].split("-", 1)[0]
        baseline_id = family + "-original"
        selected = []
        for clip in study["clips"]:
            left, right = (baseline_id, clip["id"]), (route["id"], clip["id"])
            before_ok, before_reason = eligible(slots.get(left), documents.get(left))
            after_ok, after_reason = eligible(slots.get(right), documents.get(right))
            reference = references[clip["id"]]
            row = {"baseline_route_id": baseline_id, "candidate_route_id": route["id"],
                   "clip_id": clip["id"], "film": clip["film"],
                   "reference_characters": len(normalize("".join(span["text"] for span in reference["spans"])).text),
                   "status": "diagnosed" if before_ok and after_ok else "unavailable_pair",
                   "baseline_eligibility": before_reason, "candidate_eligibility": after_reason}
            if before_ok and after_ok:
                row["diagnostic"] = diagnose_pair(reference, documents[left], documents[right])
            else:
                row["diagnostic"] = None
            pairs.append(row)
            selected.append(row)
        valid = [row for row in selected if row["diagnostic"] is not None]
        bucket_counts = {key: sum(row["diagnostic"]["deletion_support_buckets"][key] for row in valid) for key in BUCKETS}
        summaries.append({"candidate_route_id": route["id"], "baseline_route_id": baseline_id,
            "registry_pair_count": len(selected), "eligible_complete_pair_count": len(valid),
            "unavailable_pair_count": len(selected) - len(valid),
            "full_registry_reference_characters": sum(row["reference_characters"] for row in selected),
            "eligible_pair_reference_characters": sum(row["reference_characters"] for row in valid),
            "unavailable_pair_reference_characters": sum(row["reference_characters"] for row in selected if row["diagnostic"] is None),
            "known_newly_deleted_invariant_characters": sum(row["diagnostic"]["newly_deleted_invariant_characters"] for row in valid),
            "known_deletion_support_buckets": bucket_counts,
            "crossing_boundary_fully_retained_by_window_union": sum(row["diagnostic"]["crossing_boundary_fully_retained_by_window_union"] for row in valid),
            "scope": "Known counts are conditional on eligible complete pairs; unavailable pairs stay explicit and are not zero-omission observations."})
    report = {"schema_version": 1, "revision": REVISION, "study_id": study["study_id"],
              "summary_rows": summaries, "pairs": pairs,
              "limitations": ["Reference-matched characters are SRT text proxies, not independently verified spoken characters.",
                              "Baseline CTC intervals are estimated token spans, not acoustic truth. Outside/inside/crossing associations do not establish why text changed.",
                              "Singing may be absent from subtitle references. This diagnostic cannot classify retained singing as a false positive or unreferenced text as a hallucination.",
                              "Only invariant exact baseline matches and invariant candidate deletions across all optimal text paths are bucketed; ambiguous mappings remain separate.",
                              "Word/segment units, invalid/text_only/fallback/interpolated timing and non-exact raw clusters are baseline_untimed; character times are not invented.",
                              "Crossing one chunk boundary can be fully retained by adjacent window union. It does not necessarily imply discarded source audio.",
                              "Candidate relative sample/second windows receive the frozen source offset before comparison with absolute baseline times. Window validation tolerance is 1e-7 seconds for arithmetic only; baseline character intervals require strict finite positive in-source duration.",
                              "Only verified complete pairs are diagnosed; missing, partial or unverified pairs preserve their full registry denominator and explicit unavailable status.",
                              "This optional explanation neither changes primary full-denominator scores nor attributes a causal effect to VAD."]}
    for path, expected in {**identities, **source_identity}.items():
        if digest(Path(path)) != expected:
            raise ValueError("Diagnostic evidence changed during analysis")
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "report.json", report)
    write_new(output / "identity.json", {"schema_version": 1, "input_result_sha256": identities,
                                         "diagnostic_source_sha256": source_identity})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.study, args.out)
    print(json.dumps({"revision": REVISION, "output": str(args.out.resolve()),
                      "summary_rows": report["summary_rows"]}, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
