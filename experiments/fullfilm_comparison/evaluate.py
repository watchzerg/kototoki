"""Exact full-text CER and paired source-bin failure sensitivity, offline only."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from kototoki_eval import evaluate
from kototoki_eval.__main__ import json_safe
from kototoki_eval.schema import normalize, validate_transcript
from kototoki_eval.scoring import RULE_VERSION
from experiments.analysis.aggregate import _numeric_summary
from experiments.vad_comparison.evaluate import execution_proof

ROOT = Path(__file__).resolve().parents[2]
TEXT_RULE = "rapidfuzz-levenshtein-editops-unit-cost-v1"
EXECUTION_SCOPE = {"status": "not_evaluated_by_bin_scorer", "evidence_location": "diagnostics.json",
                   "scope": "Content scores do not certify or reject GPU execution. Persisted run-level stage observations are reported separately; scoring bins are not inference invocations."}


def edit_counts(reference: str, candidate: str) -> tuple[int, int, int]:
    """Count one exact global minimum path, independent of all timestamps.

    RapidFuzz chooses an optimal edit path. S/D/I tie attribution can differ from
    the original evaluator, while total unit-cost distance and CER are exact.
    """
    from rapidfuzz.distance import Levenshtein

    counts = Counter(operation.tag for operation in Levenshtein.editops(reference, candidate))
    return counts["replace"], counts["delete"], counts["insert"]


def text_score(reference: str, candidate: str) -> dict[str, Any]:
    ref, hyp = normalize(reference).text, normalize(candidate).text
    substitutions, deletions, insertions = edit_counts(ref, hyp)
    return {"reference_characters": len(ref), "candidate_characters": len(hyp),
            "S": substitutions, "D": deletions, "I": insertions,
            "CER": (substitutions + deletions + insertions) / len(ref) if ref else None,
            "unreferenced_candidate_characters": len(hyp) if not ref else 0,
            "edit_path_rule": TEXT_RULE}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write(path: Path, document: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(json_safe(document), stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def bounds(row: dict[str, Any]) -> tuple[float, float]:
    if "start_sample" in row and "end_sample" in row:
        return row["start_sample"] / 16000, row["end_sample"] / 16000
    return float(row["start"]), float(row["end"])


def bin_bounds(row: dict[str, Any]) -> tuple[float, float]:
    return float(row["source_start_seconds"]), float(row["source_end_seconds"])


def owner(start: float, end: float, bins: list[dict[str, Any]]) -> str:
    midpoint = (start + end) / 2
    for row in bins:
        lo, hi = bin_bounds(row)
        if lo <= midpoint < hi:
            return row["id"]
    raise ValueError("Source midpoint outside complete fixed scoring bins")


def partition(reference: dict[str, Any], document: dict[str, Any], bins: list[dict[str, Any]]) -> dict[str, Any]:
    """Assign intact cues/chunks exactly once using source windows, never FA time."""
    validate_transcript(document)
    segments = document.get("original_segments", [])
    if document["text"] != "".join(row["text"] for row in segments):
        raise ValueError("Complete-success ASR text must equal original segment concatenation")
    selected: dict[str, Any] = {row["id"]: {"reference": [], "ranges": [], "text": "", "units": []} for row in bins}
    crossing_cues, crossing_chunks = [], []
    for span in reference["spans"]:
        key = owner(span["start"], span["end"], bins)
        if span.get("bin_id", span.get("scene_id", key)) != key:
            raise ValueError("Frozen reference cue owner differs from source midpoint")
        selected[key]["reference"].append(span)
        lo, hi = bin_bounds(next(row for row in bins if row["id"] == key))
        if span["start"] < lo or span["end"] > hi:
            crossing_cues.append(span["id"])
    cursor = 0
    for index, segment in enumerate(segments):
        start, end = bounds(segment)
        key = owner(start, end, bins)
        length = len(segment["text"])
        selected[key]["ranges"].append((cursor, cursor + length, len(selected[key]["text"])))
        selected[key]["text"] += segment["text"]
        cursor += length
        lo, hi = bin_bounds(next(row for row in bins if row["id"] == key))
        if start < lo or end > hi:
            crossing_chunks.append(index)
    for key, item in selected.items():
        for unit in document.get("units", []):
            for start, end, destination in item["ranges"]:
                if start <= unit["char_start"] and unit["char_end"] <= end:
                    item["units"].append({**unit, "char_start": destination + unit["char_start"] - start,
                                          "char_end": destination + unit["char_end"] - start})
                    break
                if max(start, unit["char_start"]) < min(end, unit["char_end"]):
                    raise ValueError("Timing unit crosses complete ASR segment; cannot invent clipped timing")
    if sum(len(item["text"]) for item in selected.values()) != len(document["text"]):
        raise ValueError("Candidate characters lost or duplicated in fixed-bin partition")
    return {"bins": selected, "boundary": {"crossing_reference_cue_ids": crossing_cues,
            "crossing_asr_segment_indices": crossing_chunks, "scope":
            "Whole cues and complete ASR source chunks belong once by midpoint. Local timing correspondence may differ near boundaries; no lexical timing interpolation or CTC-based text selection."}}


def failure_bins(document: dict[str, Any] | None, bins: list[dict[str, Any]], run: dict[str, Any]) -> dict[str, Any]:
    """Mark every half-open bin touching a failed ASR or alignment source span."""
    failures = []
    if document is None:
        failures = [{"kind": "missing" if run.get("status") == "missing" else "invocation_failure",
                     "start": bin_bounds(bins[0])[0], "end": bin_bounds(bins[-1])[1]}]
    else:
        for row in document.get("failed_chunks", []):
            start, end = bounds(row)
            failures.append({"kind": "asr_failure", "start": start, "end": end,
                             "chunk_index": row.get("chunk_index")})
        segments = document.get("original_segments", [])
        for row in document.get("alignment_records", []):
            if not row.get("failure"):
                continue
            index = row["segment_index"]
            start, end = bounds(segments[index])
            failures.append({"kind": "alignment_failure", "start": start, "end": end,
                             "segment_index": index})
        if run.get("status") in {"failed", "blocked", "timeout", "invocation_failed", "missing"}:
            failures.append({"kind": "invocation_failure", "start": bin_bounds(bins[0])[0],
                             "end": bin_bounds(bins[-1])[1]})
    failed = sorted({row["id"] for row in bins for failure in failures
                     if max(bin_bounds(row)[0], failure["start"]) < min(bin_bounds(row)[1], failure["end"])})
    return {"failed_bin_ids": failed, "failure_counts": dict(Counter(row["kind"] for row in failures)),
            "failure_spans": failures}


def score_bins(reference: dict[str, Any], document: dict[str, Any], bins: list[dict[str, Any]],
               run: dict[str, Any]) -> dict[str, Any]:
    assigned = partition(reference, document, bins)
    failed = failure_bins(document, bins, run)
    records = []
    for row in bins:
        item = assigned["bins"][row["id"]]
        ref = {**reference, "spans": item["reference"]}
        hyp = {"schema_version": 1, "text": item["text"], "units": item["units"], "cues": [],
               "source_start_seconds": 0, "duration_seconds": document["duration_seconds"]}
        score = evaluate(ref, hyp)
        # The shared numeric helper requires these placeholders. They are not
        # observations and are discarded from all serialized content reports.
        records.append({"scene_id": row["id"], "run_id": run.get("run_id"),
                        "execution_status": "not_evaluated_by_bin_scorer", "execution_verified": None,
                        "text": score["text"], "spans": [{key: value for key, value in span.items() if key in {
                            "id", "status", "characters", "recognized_characters", "exact_characters",
                            "boundary_complete", "start_error", "end_error", "error", "error_interval",
                            "unresolved_possible_thresholds", "unresolved_may_be_complete"}}
                            for span in score["spans"]],
                        "bin_failed": row["id"] in failed["failed_bin_ids"]})
    return {"records": records, "partition": assigned, "failure": failed}


def content_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Reuse numeric content aggregation without artificial execution flags."""
    numeric = _numeric_summary(records)
    return {"text": numeric["text"], "timing": numeric["timing"],
            "execution_verification": copy.deepcopy(EXECUTION_SCOPE)}


def summarize(score: dict[str, Any], reference: dict[str, Any], document: dict[str, Any],
              bins: list[dict[str, Any]], removed: set[str]) -> dict[str, Any]:
    records = [row for row in score["records"] if row["scene_id"] not in removed]
    summary = content_summary(records)
    summary["bin_local_text"] = summary.pop("text")
    # Restore original lexical sequence rather than concatenating bins in time order.
    ref_text = "".join(span["text"] for span in reference["spans"]
                       if owner(span["start"], span["end"], bins) not in removed)
    hyp_text = "".join(segment["text"] for segment in document.get("original_segments", [])
                       if owner(*bounds(segment), bins) not in removed)
    summary["text"] = text_score(ref_text, hyp_text)
    empty = [row for row in records if row["text"]["reference_characters"] == 0]
    summary["reference_empty_bins"] = {"bin_count": len(empty), "bin_ids": [row["scene_id"] for row in empty],
        "candidate_characters": sum(row["text"]["candidate_characters"] for row in empty),
        "scope": "Unreferenced output is not classified as hallucination or song; original SRT can omit audible content."}
    crossing = set(score["partition"]["boundary"]["crossing_reference_cue_ids"])
    interior_records = copy.deepcopy(records)
    for row in interior_records:
        row["spans"] = [span for span in row["spans"] if span["id"] not in crossing]
    summary["interior_timing_only"] = _numeric_summary(interior_records)["timing"]
    summary["interior_timing_only"].pop("recognized_character_coverage", None)
    summary["interior_timing_only"].pop("exact_character_coverage", None)
    summary["interior_timing_only"]["scope"] = (
        "Excludes only reference cues whose display bounds cross a fixed-bin boundary. "
        "Candidate chunks crossing boundaries are retained by midpoint ownership; "
        "their effects on local text correspondence are not removed or certified absent.")
    summary["bin_count"] = len(records)
    summary["failed_bin_count"] = sum(row["bin_failed"] for row in records)
    return summary


def removed_accounting(reference: dict[str, Any], bins: list[dict[str, Any]], removed: set[str]) -> dict[str, Any]:
    spans = [span for span in reference["spans"] if owner(span["start"], span["end"], bins) in removed]
    return {"removed_bin_ids": sorted(removed), "removed_bin_count": len(removed),
            "removed_duration_seconds": sum(row["duration_seconds"] for row in bins if row["id"] in removed),
            "removed_reference_cue_count": len(spans),
            "removed_nonempty_reference_cue_count": sum(bool(normalize(span["text"]).text) for span in spans),
            "removed_reference_characters": len(normalize("".join(span["text"] for span in spans)).text)}


def pool(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pool edits by film without matching characters across different films."""
    keys = ("reference_characters", "candidate_characters", "S", "D", "I")
    text = {key: sum(row["summary"]["text"][key] for row in rows) for key in keys}
    text["CER"] = (text["S"] + text["D"] + text["I"]) / text["reference_characters"] if text["reference_characters"] else None
    records = [record for row in rows for record in row["records"]]
    numeric = _numeric_summary(records)
    return {"text": {**text, "edit_path_rule": TEXT_RULE}, "timing": numeric["timing"],
            "execution_verification": copy.deepcopy(EXECUTION_SCOPE),
            "bin_local_text": numeric["text"], "bin_count": len(records),
            "failed_bin_count": sum(row["bin_failed"] for row in records),
            "reference_empty_bin_count": sum(row["summary"]["reference_empty_bins"]["bin_count"] for row in rows),
            "unreferenced_candidate_characters": sum(row["summary"]["reference_empty_bins"]["candidate_characters"] for row in rows)}


def evaluate_study(study_path: Path, output: Path) -> dict[str, Any]:
    """Read every frozen film/route slot and write a new private CPU snapshot."""
    from importlib.metadata import version

    study_path, output = study_path.resolve(), output.resolve()
    if study_path.is_dir():
        study_path /= "study.json"
    private = (ROOT / ".local").resolve()
    if not output.is_relative_to(private) or output == private or output.exists():
        raise ValueError("Analysis requires a new private .local output directory")
    study = read(study_path)
    if study.get("schema_version") != 1 or not study.get("study_id") or study.get("terminal") is not True:
        raise ValueError("Study requires schema_version=1, study_id and terminal=true")
    plan_path = resolve(study["corpus_plan_path"])
    if digest(plan_path) != study.get("corpus_plan_sha256"):
        raise ValueError("Corpus plan SHA256 differs")
    plan = read(plan_path)
    if study["clips"] != plan["clips"]:
        raise ValueError("Study must preserve exact full corpus clip registry")
    routes = study["routes"]
    expected = [f"{family}-{strategy}" for family in ("w0", "x0") for strategy in ("pyannote-current", "cut-merge")]
    if [route["id"] for route in routes] != study.get("expected_route_ids", expected):
        raise ValueError("Route registry differs from frozen expected routes")
    if len({route["id"] for route in routes}) != len(routes):
        raise ValueError("Route IDs must be unique")
    references, all_bins, identities = {}, {}, {str(study_path): digest(study_path), str(plan_path): digest(plan_path)}
    for clip in study["clips"]:
        for field in ("audio", "reference", "source_audio", "source_srt"):
            if field not in clip:
                continue
            path = resolve(clip[field])
            actual = identities.get(str(path)) or digest(path)
            if actual != clip.get(field + "_sha256"):
                raise ValueError(f"Frozen {field} SHA256 differs: {clip['id']}")
            identities[str(path)] = actual
        references[clip["id"]] = read(resolve(clip["reference"]))
        bins = clip.get("scoring_bins") or plan.get("bins_by_film", {}).get(clip["film"])
        if not bins:
            bins = plan.get("bins_by_film", {}).get(clip["id"])
        if not bins or len({row["id"] for row in bins}) != len(bins):
            raise ValueError("Every film requires unique complete scoring bins")
        cursor = 0.0
        for row in bins:
            lo, hi = bin_bounds(row)
            if not math.isclose(cursor, lo, abs_tol=1 / 16000) or hi <= lo:
                raise ValueError("Scoring bins must cover complete film without gaps/overlap")
            cursor = hi
        if not math.isclose(cursor, clip["duration"], abs_tol=1 / 16000):
            raise ValueError("Scoring bins must include source EOF")
        all_bins[clip["id"]] = bins
    output.mkdir(parents=True)
    loaded, diagnostics, bin_scores = {}, [], []
    terminal = {"completed", "partial", "invocation_failed", "alignment_failed", "missing", "failed", "blocked", "timeout"}
    clip_ids = {clip["id"] for clip in study["clips"]}
    for route in routes:
        runs = route.get("runs", [])
        if len({run["clip_id"] for run in runs}) != len(runs) or any(run["clip_id"] not in clip_ids for run in runs):
            raise ValueError("Duplicate or unknown run clip IDs")
        by_clip = {run["clip_id"]: run for run in runs}
        for clip in study["clips"]:
            run = by_clip.get(clip["id"], {"clip_id": clip["id"], "status": "missing"})
            if run["status"] not in terminal:
                raise ValueError("Every declared run must be terminal before evaluation")
            document, final_result_observed = None, False
            for field in ("result_path", "asr_path", "plan_path"):
                if not run.get(field):
                    continue
                path = resolve(run[field])
                if not path.is_file():
                    continue
                expected_hash = run.get(field.removesuffix("_path") + "_sha256")
                actual = digest(path)
                if not expected_hash or actual != expected_hash:
                    raise ValueError(f"Run {field} SHA256 differs")
                identities[str(path)] = actual
                if field == "result_path" or field == "asr_path" and document is None:
                    document = read(path)
                    if field == "result_path":
                        final_result_observed = True
            original = document
            if document is None:
                document = {"schema_version": 1, "text": "", "units": [], "original_segments": [],
                            "duration_seconds": clip["duration"]}
            else:
                document = copy.deepcopy(document)
                actual_input = document.get("input_sha256", document.get("input", {}).get("file_sha256"))
                if actual_input and actual_input != clip["audio_sha256"]:
                    raise ValueError("Result input WAV identity differs")
                document.setdefault("units", [])
                document.setdefault("duration_seconds", clip["duration"])
            scored = score_bins(references[clip["id"]], document, all_bins[clip["id"]], run)
            if original is None:
                scored["failure"] = failure_bins(None, all_bins[clip["id"]], run)
                for record in scored["records"]:
                    record["bin_failed"] = True
            elif not final_result_observed:
                # Independently saved complete ASR stays scored if final FA/export is absent.
                scored["failure"]["failed_bin_ids"] = [row["id"] for row in all_bins[clip["id"]]]
                scored["failure"]["failure_counts"]["missing_alignment_result"] = 1
                scored["failure"]["failure_spans"].append({"kind": "missing_alignment_result", "start": 0,
                                                           "end": clip["duration"]})
                for record in scored["records"]:
                    record["bin_failed"] = True
            loaded[(route["id"], clip["id"])] = (scored, document, run)
            public_records = [{key: value for key, value in record.items()
                               if key not in {"execution_status", "execution_verified"}}
                              for record in scored["records"]]
            bin_scores.append({"route_id": route["id"], "clip_id": clip["id"], "records": public_records,
                               "execution_verification": copy.deepcopy(EXECUTION_SCOPE)})
            partial = [segment for failed in document.get("failed_chunks", []) for segment in failed.get("partial_segments", [])]
            diagnostic = {"route_id": route["id"], "clip_id": clip["id"], "declared_status": run["status"],
                "failure": scored["failure"], "boundary": scored["partition"]["boundary"],
                "partial_failed_asr_raw_characters": sum(len(segment.get("text", "")) for segment in partial),
                "partial_failed_asr_normalized_characters": sum(len(normalize(segment.get("text", "")).text) for segment in partial),
                "execution_proof": execution_proof(document) if original else None,
                "execution_observation_scope": "Persisted run-level observations, separate from bin content metrics. Missing evidence or incomplete trace coverage does not establish CPU execution or GPU failure.",
                "processes": run.get("processes"), "segmentation_process_wall_s": run.get("segmentation_process_wall_s"),
                "parameters": document.get("effective_parameters"), "runtime_identity": document.get("runtime_identity"),
                "source_sha256": document.get("source_sha256"), "stages": document.get("stages"),
                "unit_status_counts": dict(Counter(unit.get("status", "ok") for unit in document.get("units", [])))}
            if partial:
                diagnostic_segments = sorted([*document.get("original_segments", []), *partial], key=bounds)
                diagnostic["including_failed_chunk_partial_text_diagnostic"] = text_score(
                    "".join(span["text"] for span in references[clip["id"]]["spans"]),
                    "".join(segment.get("text", "") for segment in diagnostic_segments))
            process_rows = [row for row in run.get("processes", {}).values() if isinstance(row, dict)]
            valid_costs = [row["wall_s"] for row in process_rows if isinstance(row.get("wall_s"), (int, float))
                           and not isinstance(row["wall_s"], bool) and math.isfinite(row["wall_s"]) and row["wall_s"] >= 0]
            segmentation_cost = run.get("segmentation_process_wall_s")
            cost_complete = (bool(valid_costs) and len(valid_costs) == len(process_rows)
                             and isinstance(segmentation_cost, (int, float)) and not isinstance(segmentation_cost, bool)
                             and math.isfinite(segmentation_cost) and segmentation_cost >= 0)
            diagnostic["reconstructed_serial_wall_s"] = sum(valid_costs) + segmentation_cost if cost_complete else None
            diagnostic["attempted_asr_chunk_count"] = len(document.get("chunk_records", []))
            diagnostic["successful_asr_chunk_count"] = sum(row.get("status") == "ok" for row in document.get("chunk_records", []))
            diagnostic["failed_asr_chunk_count"] = len(document.get("failed_chunks", []))
            diagnostic["failed_asr_kind_counts"] = dict(Counter(row.get("failure_kind", "unknown") for row in document.get("failed_chunks", [])))
            diagnostic["cost_scope"] = "Includes failed stage attempts. Shared segmentation is counted once per reconstructed route; inference processes are fresh. This is not a separately measured live full-pipeline wall clock."
            diagnostics.append(diagnostic)
            print(json.dumps({"scored": route["id"], "clip_id": clip["id"], "bins": len(scored["records"])}), flush=True)
    views: dict[str, Any] = {}
    for view in ("including_failures", "excluding_paired_failure_union"):
        film_rows, pooled_rows = [], []
        for route in routes:
            route_films = []
            for clip in study["clips"]:
                scored, document, run = loaded[(route["id"], clip["id"])]
                peers = [peer for peer in routes if peer["family"] == route["family"]]
                removed = (set().union(*(set(loaded[(peer["id"], clip["id"])][0]["failure"]["failed_bin_ids"])
                                         for peer in peers)) if view != "including_failures" else set())
                summary = summarize(scored, references[clip["id"]], document, all_bins[clip["id"]], removed)
                row = {"route_id": route["id"], "family": route["family"], "clip_id": clip["id"], "film": clip["film"],
                       "summary": summary, "removed": removed_accounting(references[clip["id"]], all_bins[clip["id"]], removed),
                       "failure_counts": scored["failure"]["failure_counts"],
                       "records": [record for record in scored["records"] if record["scene_id"] not in removed]}
                route_films.append(row)
                film_rows.append({key: value for key, value in row.items() if key != "records"})
            pooled_rows.append({"route_id": route["id"], "family": route["family"], "summary": pool(route_films),
                "removed": {key: sum(row["removed"][key] for row in route_films) for key in (
                    "removed_bin_count", "removed_duration_seconds", "removed_reference_cue_count",
                    "removed_nonempty_reference_cue_count", "removed_reference_characters")},
                "failure_counts": dict(sum((Counter(row["failure_counts"]) for row in route_films), Counter()))})
        views[view] = {"films": film_rows, "pooled": pooled_rows}
    report = {"schema_version": 1, "study_id": study["study_id"], "rule_version": RULE_VERSION,
        "text_edit_rule": TEXT_RULE, "rapidfuzz_version": version("rapidfuzz"), "views": views,
        "policy": {"primary_text": "Exact full-film global reference-difference CER; no forced-alignment time selects text.",
            "primary_timing": "Existing universal all-optimal-path evaluator on predetermined 300-second source bins; intact reference cues and ASR chunks owned once by source midpoint.",
            "exclusion": "For each ASR family and film remove UNION of failed ASR/alignment/invocation bins for both strategies; identical remaining reference. All complete ASR output remains in full analysis, including success output inside failed bins. Failed-chunk partial text is diagnostic only.",
            "costs": "Whole-run costs include failed work and are not reduced when failure bins are excluded.",
            "reference": "Full original SRT-derived reference including credits/end tail; SRT display times are not human acoustic truth; songs/unreferenced speech are not classified as false positives.",
            "boundary": "Bin-local timing and CER can differ from unbounded full-film matching. Whole-film global CER is primary; crossing cue/chunk metadata and interior timing expose boundary uncertainty.",
            "independence": "Two previously encountered films; bins are correlated descriptive units, not independent samples or a new blind holdout."}}
    # Recheck protected inputs after reading; never repair changed frozen evidence.
    for path, expected_hash in identities.items():
        if digest(Path(path)) != expected_hash:
            raise ValueError("Frozen artifact changed during evaluation")
    write(output / "report.json", report)
    write(output / "diagnostics.json", {"runs": diagnostics})
    write(output / "bin-scores.json", {"runs": bin_scores, "scope": "Sanitized numeric per-bin/cue timing and supplemental local text counts; no raw text or character maps."})
    write(output / "identities.json", {"files": identities, "analysis_source_sha256": digest(Path(__file__)),
                                      "core_sources": {str(path.relative_to(ROOT)): digest(path) for path in (ROOT / "kototoki_eval").glob("*.py")}})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate_study(args.study, args.output)


if __name__ == "__main__":
    main()
