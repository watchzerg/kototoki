"""Five-model full-film comparison using the existing offline scoring rules."""

from __future__ import annotations

import argparse
from collections import Counter
import copy
from importlib.metadata import version
import json
import math
from pathlib import Path
from typing import Any

from experiments.fullfilm_comparison import evaluate as core
from kototoki_eval.schema import normalize

ROOT = core.ROOT
FAMILIES = ("w0", "x0", "cohere", "granite", "nemotron")
TERMINAL = {"completed", "partial", "invocation_failed", "alignment_failed", "missing", "failed", "blocked", "blocked_access", "timeout"}


def execution_observations(document: dict[str, Any], family: str) -> dict[str, Any]:
    """Separate observed devices, generation failures, and plan coverage."""
    proof = core.execution_proof(document)

    def cuda(value: Any) -> bool:
        return isinstance(value, str) and (value == "cuda" or value.startswith("cuda:"))

    successful = document.get("asr_traces", [])
    failed = [trace for chunk in document.get("failed_chunks", []) for trace in chunk.get("partial_traces", [])]
    traces = [*successful, *failed]
    asr_only = "chunks" not in document and "asr_traces" in document
    native = family != "w0" or any("asr_input_evidence" in trace for trace in traces)
    candidates = {"cohere", "granite", "nemotron"}
    if family in candidates:
        proof["asr_gpu_evidence_kind"] = "native_parameter_input_output_tensors"
    evidence_states = []
    buffer_states = []
    for trace in traces:
        if native:
            evidence = trace.get("asr_input_evidence", {})
            parameters = evidence.get("parameter_devices", [])
            inputs = list(evidence.get("input_devices", {}).values())
            buffers = evidence.get("buffer_devices", [])
            devices = [*parameters, *inputs, *buffers, evidence.get("output_device")]
            complete = bool(parameters) and bool(inputs) and all(cuda(device) for device in devices)
            non_cuda = any(isinstance(device, str) and not cuda(device) for device in devices)
            if family in candidates:
                buffer_states.append(all(cuda(device) for device in buffers) if "buffer_devices" in evidence else None)
        else:
            metadata = document.get("effective_parameters", {})
            device = metadata.get("device") if asr_only else metadata.get("asr", {}).get("device")
            complete, non_cuda = cuda(device), isinstance(device, str) and not cuda(device)
        evidence_states.append("cuda" if complete else "non_cuda" if non_cuda else "incomplete")
    state_counts = Counter(evidence_states)
    asr_ok = state_counts["cuda"] > 0 and state_counts["non_cuda"] == 0
    status = ("observed_non_cuda" if state_counts["non_cuda"] else
              "partially_observed_cuda" if asr_ok and state_counts["incomplete"] else
              "observed_cuda" if asr_ok else "incomplete_evidence" if traces else "no_trace_evidence")
    expected = document.get("total_chunks", len(document["chunks"]) if "chunks" in document else None)
    expected_known = isinstance(expected, int) and not isinstance(expected, bool) and expected >= 0

    def identified(trace: dict[str, Any]) -> bool:
        index = trace.get("chunk_index")
        return isinstance(index, int) and not isinstance(index, bool) and index >= 0 and (not expected_known or index < expected)

    def trace_indices(rows: list[dict[str, Any]]) -> set[int]:
        return {trace["chunk_index"] for trace in rows if identified(trace)}

    successful_indices, failed_indices = trace_indices(successful), trace_indices(failed)
    observed_indices = successful_indices | failed_indices
    unidentified = sum(not identified(trace) for trace in traces)
    coverage_complete = len(observed_indices) == expected and unidentified == 0 if expected_known else None
    successful_coverage = len(successful_indices) == expected and len(successful) == expected if expected_known else None
    capped = [trace for trace in traces if trace.get("token_limit_reached") is True]
    capped_count = len(trace_indices(capped)) + sum(not identified(trace) for trace in capped)
    cap_clear = ((all(trace.get("token_limit_reached") is False for trace in traces) if native else not capped)
                 and coverage_complete is True)
    proof.update(asr_gpu_observed=asr_ok, asr_gpu_observation_status=status,
        asr_successful_trace_count=len(successful), asr_failed_partial_trace_count=len(failed),
        asr_observed_trace_count=len(traces), asr_observed_chunk_count=len(observed_indices),
        asr_expected_chunk_count=expected if expected_known else None,
        asr_trace_plan_coverage_complete=coverage_complete,
        asr_successful_trace_plan_coverage_complete=successful_coverage,
        asr_unobserved_chunk_count=expected - len(observed_indices) if expected_known else None,
        asr_unobserved_chunk_indices=sorted(set(range(expected)) - observed_indices) if expected_known else None,
        asr_unidentified_trace_count=unidentified,
        asr_cuda_trace_count=state_counts["cuda"], asr_non_cuda_trace_count=state_counts["non_cuda"],
        asr_incomplete_device_trace_count=state_counts["incomplete"],
        asr_successful_cuda_trace_count=evidence_states[:len(successful)].count("cuda"),
        asr_failed_partial_cuda_trace_count=evidence_states[len(successful):].count("cuda"),
        successful_trace_token_cap_count=sum(trace.get("token_limit_reached") is True for trace in successful),
        failed_partial_trace_token_cap_count=sum(trace.get("token_limit_reached") is True for trace in failed),
        token_cap_chunk_count=capped_count, token_cap_clear=cap_clear,
        asr_evidence_scope="Persisted successful and failed partial traces. Device observations do not certify successful generation; plan coverage and unobserved windows are separate.")
    if family in candidates:
        proof["asr_buffer_devices_cuda"] = (False if False in buffer_states else
                                            None if not buffer_states or None in buffer_states else True)
    complete_observation = (state_counts["incomplete"] == 0 and successful_coverage is True
                            and (family not in candidates or proof["asr_buffer_devices_cuda"] is True))
    proof["execution_observations_pass"] = bool((proof["empty_vad_inference_skipped"] or
        asr_ok and complete_observation and proof["alignment_gpu_observed"])
        and proof["fresh_asr_alignment"] and proof["offline_requested"] and proof["complete_asr_text_preserved"]
        and not document.get("failed_chunks") and not proof["alignment_failure_count"] and cap_clear)
    if asr_only:
        proof.update(fresh_asr=proof["fresh_asr_alignment"], fresh_asr_alignment=None,
            empty_vad_inference_skipped=None, alignment_gpu_observed=False,
            alignment_observation_status="not_observed_in_asr_only_artifact", execution_observations_pass=False)
    return proof


def public_quality(row: dict[str, Any], observed_count: int, expected_count: int) -> dict[str, Any]:
    """Separate hypothetical missing-output edits from observed model quality."""
    result = copy.deepcopy(row)
    result["quality_scope"] = ("complete_corpus" if observed_count == expected_count
                               else "partial_corpus" if observed_count else "unobserved")
    if observed_count != expected_count:
        result["full_denominator_accounting"] = copy.deepcopy(result["summary"]["text"])
        result["full_denominator_accounting"]["scope"] = "Observed output plus hypothetical empty output for unobserved slots; these edit counts are completeness accounting, not a model-quality result."
        for key in ("candidate_characters", "S", "D", "I", "CER"):
            result["summary"]["text"][key] = None
        result["summary"]["text"]["quality_unavailable"] = True
    return result


def cost_summary(run: dict[str, Any]) -> dict[str, Any]:
    """Count failed attempts too; unavailable cost is unknown, never zero."""
    processes = run.get("processes") or {}
    rows = list(processes.values()) if isinstance(processes, dict) else []
    values = [row.get("wall_s") if isinstance(row, dict) else None for row in rows]
    segmentation = run.get("segmentation_process_wall_s")
    valid = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    complete = bool(rows) and all(valid(value) for value in values) and valid(segmentation)
    return {"reconstructed_serial_wall_s": sum(values) + segmentation if complete else None,
            "cost_complete": complete,
            "cost_scope": "Includes failed attempts and shared segmentation once per route. Reconstructed serial cost is not a separately measured live full-pipeline wall clock."}


def validate_registry(study: dict[str, Any]) -> None:
    """Keep all requested model slots, including unavailable candidates."""
    routes = study["routes"]
    if len(routes) != len(FAMILIES) or {row["family"] for row in routes} != set(FAMILIES):
        raise ValueError("Study requires exactly one route for each of w0/x0/cohere/granite/nemotron")
    ids = [row["id"] for row in routes]
    if len(set(ids)) != len(ids) or ids != study.get("expected_route_ids", ids):
        raise ValueError("Route registry differs from frozen expected routes")
    if any(row.get("segmentation") != "pyannote-current" for row in routes):
        raise ValueError("Every route requires current pyannote-current segmentation")


def load_run(run: dict[str, Any], clip: dict[str, Any], bins: list[dict[str, Any]],
             reference: dict[str, Any], identities: dict[str, str], family: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Retain complete ASR if alignment/export fails, and retain failed slots."""
    if run["status"] not in TERMINAL:
        raise ValueError("Every declared run must be terminal before evaluation")
    stage_failure = None
    if run.get("failure_path"):
        failure_path = core.resolve(run["failure_path"])
        if failure_path.is_file():
            actual = core.digest(failure_path)
            if actual != run.get("failure_sha256"):
                raise ValueError("Run failure_path SHA256 differs")
            identities[str(failure_path)] = actual
            stage_failure = {key: value for key, value in core.read(failure_path).items()
                             if key in {"status", "stage", "failure_kind", "exception", "message", "worker_wall_s"}}
    document, final_result_observed = None, False
    for field in ("result_path", "asr_path", "plan_path"):
        if not run.get(field):
            continue
        path = core.resolve(run[field])
        if not path.is_file():
            continue
        actual = core.digest(path)
        if actual != run.get(field.removesuffix("_path") + "_sha256"):
            raise ValueError(f"Run {field} SHA256 differs")
        identities[str(path)] = actual
        if field == "result_path" or field == "asr_path" and document is None:
            document = core.read(path)
            final_result_observed = field == "result_path"
    observed = document is not None
    if document is None:
        document = {"schema_version": 1, "text": "", "units": [], "original_segments": [],
                    "duration_seconds": clip["duration"]}
    else:
        document = copy.deepcopy(document)
        input_hash = document.get("input_sha256", document.get("input", {}).get("file_sha256"))
        if input_hash and input_hash != clip["audio_sha256"]:
            raise ValueError("Result input WAV identity differs")
        document.setdefault("units", [])
        document.setdefault("duration_seconds", clip["duration"])
    scoring_run = {**run, "status": "blocked"} if run["status"] == "blocked_access" else run
    scored = core.score_bins(reference, document, bins, scoring_run)
    if not observed:
        scored["failure"] = core.failure_bins(None, bins, run)
        for record in scored["records"]:
            record["bin_failed"] = True
    elif not final_result_observed:
        scored["failure"]["failed_bin_ids"] = [row["id"] for row in bins]
        scored["failure"]["failure_counts"]["missing_alignment_result"] = 1
        scored["failure"]["failure_spans"].append({"kind": "missing_alignment_result", "start": 0, "end": clip["duration"]})
        for record in scored["records"]:
            record["bin_failed"] = True
    partial = [segment for failed in document.get("failed_chunks", []) for segment in failed.get("partial_segments", [])]
    diagnostic = {"clip_id": clip["id"], "declared_status": run["status"],
        "reason": run.get("failure_reason") or run.get("reason") or run.get("error") or run.get("failure") or (stage_failure or {}).get("message"),
        "stage_failure": stage_failure,
        "stage_failure_kind": run.get("failure_kind") or (stage_failure or {}).get("failure_kind"),
        "failure": scored["failure"], "boundary": scored["partition"]["boundary"],
        "final_result_observed": final_result_observed, "asr_or_result_observed": observed,
        "partial_failed_asr_raw_characters": sum(len(segment.get("text", "")) for segment in partial),
        "partial_failed_asr_normalized_characters": sum(len(normalize(segment.get("text", "")).text) for segment in partial),
        "execution_proof": execution_observations(document, family) if observed else None,
        "execution_observation_scope": "Persisted run-level observations, separate from content metrics. Missing evidence does not establish CPU execution or GPU failure.",
        "processes": run.get("processes"), "segmentation_process_wall_s": run.get("segmentation_process_wall_s"),
        "parameters": document.get("effective_parameters"), "runtime_identity": document.get("runtime_identity"),
        "source_sha256": document.get("source_sha256"), "stages": document.get("stages"),
        "unit_status_counts": dict(Counter(unit.get("status", "ok") for unit in document.get("units", []))),
        "attempted_asr_chunk_count": len(document.get("chunk_records", [])),
        "successful_asr_chunk_count": sum(row.get("status") == "ok" for row in document.get("chunk_records", [])),
        "failed_asr_chunk_count": len(document.get("failed_chunks", [])),
        "failed_asr_kind_counts": dict(Counter(row.get("failure_kind", "unknown") for row in document.get("failed_chunks", []))),
        **cost_summary(run)}
    if partial:
        segments = sorted([*document.get("original_segments", []), *partial], key=core.bounds)
        diagnostic["including_failed_chunk_partial_text_diagnostic"] = core.text_score(
            "".join(span["text"] for span in reference["spans"]), "".join(segment.get("text", "") for segment in segments))
    return scored, document, diagnostic


def summary_markdown(report: dict[str, Any]) -> str:
    """Produce a compact Chinese numerical report without raw transcripts."""
    rows = report["views"]["including_failures"]
    lines = ["# 第一批 ASR 整片比较", "", f"研究：`{report['study_id']}`。完整参考分母保留失败、缺失和阻塞任务。", "",
        "CER 为原版日文 SRT 的全文参考差异；时间指标使用完整参考条目，SRT 显示时间不是人工声学真值。", "",
        "| 路线 | 电影 | 状态 | CER | S / D / I | 时间分母 | 失败评分区间 | 重构串行秒 |", "| --- | --- | --- | ---: | --- | ---: | ---: | ---: |"]
    def formatted(value: Any, percent: bool = False) -> str:
        return ("未测" if percent else "未知") if value is None else (f"{value:.2%}" if percent else f"{value:.3f}")
    for row in rows["films"]:
        text, timing = row["summary"]["text"], row["summary"]["timing"]
        edits = "未测" if text["CER"] is None else f"{text['S']} / {text['D']} / {text['I']}"
        lines.append(f"| {row['route_id']} | {row['film']} | {row['declared_status']} | {formatted(text['CER'], True)} | {edits} | {timing['denominator']} | {row['summary']['failed_bin_count']} | {formatted(row['reconstructed_serial_wall_s'])} |")
    lines.extend(["", "两片加权合并：", "", "| 路线 | CER | S / D / I | 时间分母 | 终态计数 |", "| --- | ---: | --- | ---: | --- |"])
    for row in rows["pooled"]:
        text = row["summary"]["text"]
        statuses = ", ".join(f"{key}={value}" for key, value in row["declared_status_counts"].items())
        edits = "未测" if text["CER"] is None else f"{text['S']} / {text['D']} / {text['I']}"
        quality = "部分覆盖" if row["quality_scope"] == "partial_corpus" else formatted(text["CER"], True)
        lines.append(f"| {row['route_id']} | {quality} | {edits} | {row['summary']['timing']['denominator']} | {statuses} |")
    lines.extend(["", "两片时间指标（完整参考分母）：", "",
                  "| 路线 | 可测覆盖 | 严格 <0.5 秒下界／上界 | 条件 P95 秒 | 最大偏移秒 | >5 秒条目 |", "| --- | ---: | --- | ---: | ---: | ---: |"])
    for row in rows["pooled"]:
        timing = row["summary"]["timing"]
        if row["quality_scope"] != "complete_corpus":
            lines.append(f"| {row['route_id']} | 未测 | 未测 | 未测 | 未测 | 未测 |")
            continue
        strict = timing["success"]["0.5"]
        lines.append(f"| {row['route_id']} | {formatted(timing['measurable_coverage'], True)} | {formatted(strict['lower'], True)} / {formatted(strict['upper'], True)} | {formatted(timing['error']['p95'])} | {formatted(timing['error']['max'])} | {timing['over_threshold_counts']['5.0']} |")
    incomplete = [row for row in rows["films"] if row["declared_status"] != "completed" or not row["final_result_observed"]]
    if incomplete:
        lines.extend(["", "未完整完成的任务：", ""])
        for row in incomplete:
            reason = str(row.get("reason") or "详情见 diagnostics.json").replace("\n", " ")
            lines.append(f"- {row['route_id']} / {row['film']}：{row['declared_status']}；{reason}")
    lines.extend(["", "完整数值、时间覆盖／偏移、跨界诊断及执行证据分别见 report.json、bin-scores.json、diagnostics.json。",
                  "重构成本包含失败工作，每条路线计入共享分段成本；不能直接相加作为研究实际墙钟。",
                  "缺失／阻塞路线标为未测，全文质量字段为空；假定空输出的完整分母编辑记账另存 full_denominator_accounting，不作为模型质量成绩。", ""])
    return "\n".join(lines)


def evaluate_study(study_path: Path, output: Path) -> dict[str, Any]:
    """Score all five families over the exact full corpus with no exclusion."""
    study_path, output = study_path.resolve(), output.resolve()
    if study_path.is_dir():
        study_path /= "study.json"
    private = (ROOT / ".local").resolve()
    if not output.is_relative_to(private) or output == private or output.exists():
        raise ValueError("Analysis requires a new private .local output directory")
    study = core.read(study_path)
    if study.get("schema_version") != 1 or not study.get("study_id") or study.get("terminal") is not True:
        raise ValueError("Study requires schema_version=1, study_id and terminal=true")
    validate_registry(study)
    plan_path = core.resolve(study["corpus_plan_path"])
    if core.digest(plan_path) != study.get("corpus_plan_sha256"):
        raise ValueError("Corpus plan SHA256 differs")
    plan = core.read(plan_path)
    if study["clips"] != plan["clips"]:
        raise ValueError("Study must preserve exact full corpus clip registry")
    clip_ids = {clip["id"] for clip in study["clips"]}
    if not clip_ids or len(clip_ids) != len(study["clips"]):
        raise ValueError("Corpus requires unique nonempty clip IDs")
    identities = {str(study_path): core.digest(study_path), str(plan_path): core.digest(plan_path)}
    films, pooled, diagnostics, bin_scores = [], [], [], []
    for route in study["routes"]:
        runs = route.get("runs", [])
        if len({run["clip_id"] for run in runs}) != len(runs) or any(run["clip_id"] not in clip_ids for run in runs):
            raise ValueError("Duplicate or unknown run clip IDs")
        by_clip = {run["clip_id"]: run for run in runs}
        route_films = []
        for clip in study["clips"]:
            for field in ("audio", "reference", "source_audio", "source_srt"):
                if field not in clip:
                    continue
                path = core.resolve(clip[field])
                actual = identities.get(str(path)) or core.digest(path)
                if actual != clip.get(field + "_sha256"):
                    raise ValueError(f"Frozen {field} SHA256 differs: {clip['id']}")
                identities[str(path)] = actual
            reference = core.read(core.resolve(clip["reference"]))
            bins = clip.get("scoring_bins") or plan.get("bins_by_film", {}).get(clip["film"]) or plan.get("bins_by_film", {}).get(clip["id"])
            if not bins or len({row["id"] for row in bins}) != len(bins):
                raise ValueError("Every film requires unique complete scoring bins")
            cursor = 0.0
            for row in bins:
                lo, hi = core.bin_bounds(row)
                if not math.isclose(cursor, lo, abs_tol=1 / 16000) or hi <= lo:
                    raise ValueError("Scoring bins must cover complete film without gaps/overlap")
                cursor = hi
            if not math.isclose(cursor, clip["duration"], abs_tol=1 / 16000):
                raise ValueError("Scoring bins must include source EOF")
            run = by_clip.get(clip["id"], {"clip_id": clip["id"], "status": "missing"})
            scored, document, diagnostic = load_run(run, clip, bins, reference, identities, route["family"])
            diagnostic["route_id"] = route["id"]
            diagnostics.append(diagnostic)
            bin_scores.append({"route_id": route["id"], "clip_id": clip["id"],
                "records": [{key: value for key, value in record.items() if key not in {"execution_status", "execution_verified"}} for record in scored["records"]],
                "execution_verification": copy.deepcopy(core.EXECUTION_SCOPE)})
            row = {"route_id": route["id"], "family": route["family"], "clip_id": clip["id"], "film": clip["film"],
                   "declared_status": run["status"], "reason": diagnostic["reason"],
                   "stage_failure_kind": diagnostic["stage_failure_kind"],
                   "asr_or_result_observed": diagnostic["asr_or_result_observed"],
                   "final_result_observed": diagnostic["final_result_observed"],
                   "summary": core.summarize(scored, reference, document, bins, set()),
                   "failure_counts": scored["failure"]["failure_counts"], "records": scored["records"],
                   **cost_summary(run)}
            route_films.append(row)
            films.append(public_quality({key: value for key, value in row.items() if key != "records"}, int(diagnostic["asr_or_result_observed"]), 1))
            print(json.dumps({"scored": route["id"], "clip_id": clip["id"], "bins": len(scored["records"]),
                              "declared_status": run["status"]}), flush=True)
        costs = [row["reconstructed_serial_wall_s"] for row in route_films]
        observed_count = sum(row["asr_or_result_observed"] for row in route_films)
        pooled.append(public_quality({"route_id": route["id"], "family": route["family"], "summary": core.pool(route_films),
                       "declared_status_counts": dict(Counter(row["declared_status"] for row in route_films)),
                       "final_result_count": sum(row["final_result_observed"] for row in route_films),
                       "asr_or_result_count": observed_count,
                       "expected_film_count": len(study["clips"]),
                       "reconstructed_serial_wall_s": sum(costs) if all(value is not None for value in costs) else None,
                       "failure_counts": dict(sum((Counter(row["failure_counts"]) for row in route_films), Counter()))}, observed_count, len(study["clips"])))
    report = {"schema_version": 1, "study_id": study["study_id"], "rule_version": core.RULE_VERSION,
        "text_edit_rule": core.TEXT_RULE, "rapidfuzz_version": version("rapidfuzz"),
        "views": {"including_failures": {"films": films, "pooled": pooled}},
        "policy": {"primary_text": "Exact full-film global reference-difference CER, pooled by summing film edit counts; no forced-alignment time selects text.",
            "primary_timing": "Existing universal all-optimal-path evaluator on complete predetermined source bins; intact reference cues and ASR chunks owned once by source midpoint.",
            "failure": "All requested model/film slots and full reference denominators retained, including missing/blocked/invocation failures. Unobserved quality fields are null; hypothetical empty-output edits are separate completeness accounting. Complete ASR preserved if alignment fails; partial failed-chunk text diagnostic only.",
            "exclusion": "None. Five distinct ASR families share current pyannote-current segmentation; no paired segmentation strategies are assumed.",
            "reference": "Full original SRT-derived reference including credits/end tail; display times are not human acoustic truth; unreferenced speech is not classified as hallucination or song.",
            "boundary": "Whole-film global CER is primary; bin-local timing/CER can differ near boundaries. Crossing cue/chunk metadata and interior timing remain visible.",
            "independence": "Two previously encountered films; correlated bins are descriptive units, not independent samples or a new blind holdout."}}
    for path, expected in identities.items():
        if core.digest(Path(path)) != expected:
            raise ValueError("Frozen artifact changed during evaluation")
    output.mkdir(parents=True)
    core.write(output / "report.json", report)
    core.write(output / "diagnostics.json", {"runs": diagnostics})
    core.write(output / "bin-scores.json", {"runs": bin_scores, "scope": "Numeric timing and local text counts; no raw transcripts or character maps."})
    core.write(output / "identities.json", {"files": identities, "analysis_source_sha256": core.digest(Path(__file__)),
        "fullfilm_evaluator_sha256": core.digest(Path(core.__file__)),
        "core_sources": {str(path.relative_to(ROOT)): core.digest(path) for path in (ROOT / "kototoki_eval").glob("*.py")}})
    with (output / "summary.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(summary_markdown(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate_study(args.study, args.output)


if __name__ == "__main__":
    main()
