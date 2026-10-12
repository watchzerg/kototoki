"""Evaluate the frozen two-window X0 flow study with the existing evaluator."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any
import wave

from kototoki_eval.schema import normalize, validate_transcript
from experiments.analysis.build_heldout import repeated_unit_observation
from experiments.components.evaluate import build as build_component_report, write_new

ROOT = Path(__file__).resolve().parents[1]
CLIP_IDS = ("hf-ii-window-01", "hf-iii-window-01")
VARIANTS = ("fixed30", "energy", "pyannote")


def digest(path: Path) -> str:
    """Hash large original assets without loading them into memory."""
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return document


def path_from(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def check_inputs(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Verify frozen audio, original subtitles, and derived references."""
    checks = []
    for clip in clips:
        for field in ("audio", "reference", "source_audio", "source_srt"):
            path = path_from(clip[field])
            actual = digest(path)
            expected = clip[f"{field}_sha256"]
            if actual != expected:
                raise ValueError(f"Frozen {field} identity changed for {clip['id']}")
            checks.append({"clip_id": clip["id"], "role": field,
                           "path": str(path), "sha256": actual})
    return checks


def text_and_units_parity(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """Compare full persisted units exactly; do not apply time tolerances."""
    def value_hash(value: Any) -> str:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    return {"complete_text_equal": new["text"] == old["text"],
            "normalized_text_equal": normalize(new["text"]).text == normalize(old["text"]).text,
            "units_exactly_equal": new.get("units", []) == old.get("units", []),
            "original_segments_exactly_equal": new.get("original_segments") == old.get("original_segments"),
            "new_text_sha256": value_hash(new["text"]), "old_text_sha256": value_hash(old["text"]),
            "new_units_sha256": value_hash(new.get("units", [])),
            "old_units_sha256": value_hash(old.get("units", [])),
            "new_unit_count": len(new.get("units", [])), "old_unit_count": len(old.get("units", []))}


def severe_transitions(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep IDs and numeric status transitions, including loss of measurability."""
    rows = {(record["scene_id"], row["id"]): row for record in right["scene_records"]
            for row in record["spans"]}
    result = []
    for record in left["scene_records"]:
        for row in record["spans"]:
            if row["status"] != "measurable" or row["error"] <= 2:
                continue
            other = rows[(record["scene_id"], row["id"])]
            result.append({"scene_id": record["scene_id"], "span_id": row["id"],
                           "baseline_error_s": row["error"], "variant_status": other["status"],
                           "variant_error_s": other.get("error"),
                           "lost_measurability": other["status"] != "measurable",
                           "measured_below_2_seconds": other["status"] == "measurable" and other["error"] < 2})
    return result


def boundary_repeat_observations(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Observe adjacent chunk suffix/prefix equality without emitting text."""
    rows = []
    for index, (left, right) in enumerate(zip(segments, segments[1:])):
        before = normalize(left["text"]).text
        after = normalize(right["text"]).text
        length = next((size for size in range(min(len(before), len(after)), 1, -1)
                       if before[-size:] == after[:size]), 0)
        if length:
            rows.append({"left_chunk_index": index, "right_chunk_index": index + 1,
                         "normalized_overlap_characters": length})
    return {"minimum_normalized_characters": 2, "adjacent_pair_count": len(rows),
            "overlap_characters_sum": sum(row["normalized_overlap_characters"] for row in rows),
            "pairs": rows,
            "scope": "Literal equal suffix/prefix in adjacent chunks, not a duplicate error label. Genuine speech may repeat; no deletion or deduplication is applied."}


def safe_costs(document: dict[str, Any], process: list[dict[str, Any]]) -> dict[str, Any]:
    stages = {key: value for key, value in document.get("stages", {}).items()
              if isinstance(value, (int, float)) and not isinstance(value, bool)}
    entries = [{key: row.get(key) for key in ("stage", "wall_s", "exit_code")} for row in process]
    times = [row["wall_s"] for row in entries]
    complete = (len(entries) == 3 and {row["stage"] for row in entries} == {"plan", "asr", "align"}
                and all(row["exit_code"] == 0 for row in entries)
                and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) and value >= 0 for value in times))
    return {"reported_stages_s": stages, "process_wall_s": entries,
            "three_process_end_to_end_s": sum(times) if complete else None,
            "scope": "Sum of sequential plan/ASR/alignment process wall times, including loads and process startup; excludes evaluation and asset provisioning"}


def execution_proof(document: dict[str, Any], result_path: Path, variant: str,
                    clip: dict[str, Any]) -> dict[str, Any]:
    """Inspect GPU tensors and the exact fresh plan/ASR dependency chain."""
    if document.get("variant") != variant:
        raise ValueError("Result variant differs from frozen slot")
    for field, filename in (("plan_sha256", "plan.json"), ("asr_stage_sha256", "asr.json")):
        if document.get(field) != digest(result_path.parent / filename):
            raise ValueError("Persisted plan/ASR stage identity changed")
    for value, expected in document.get("source_sha256", {}).items():
        if digest(path_from(value)) != expected:
            raise ValueError("Inference source identity changed")
    if document["text"] != "".join(row["text"] for row in document["original_segments"]):
        raise ValueError("Alignment lost or changed complete ASR text")
    with wave.open(str(path_from(clip["audio"])), "rb") as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 16000):
            raise ValueError("Frozen study input must be mono PCM16 at 16 kHz")
        samples = array("h", source.readframes(source.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    def cuda(value: Any) -> bool:
        return isinstance(value, str) and value.startswith("cuda:")
    traces = document.get("asr_traces", [])
    if len(traces) != len(document.get("chunks", [])) or len(traces) != len(document["original_segments"]):
        raise ValueError("ASR traces, chunks, and segments must account for the same complete windows")
    asr_ok = bool(traces) and len(traces) == len(document.get("chunks", []))
    pcm_checks = []
    for index, row in enumerate(traces):
        chunk = document["chunks"][index]
        start, end = chunk["start_sample"], chunk["end_sample"]
        pcm = array("f", (value / 32768 for value in samples[start:end]))
        if sys.byteorder != "little":
            pcm.byteswap()
        actual = hashlib.sha256(pcm.tobytes()).hexdigest()
        if (row.get("start_sample") != start or row.get("end_sample") != end
                or row.get("pcm_float32_sha256") != actual):
            raise ValueError("ASR trace PCM differs from the original planned sample window")
        segment = document["original_segments"][index]
        if segment["start"] != chunk["start"] or segment["end"] != chunk["end"]:
            raise ValueError("ASR segment changed planned source window")
        pcm_checks.append({"chunk_index": index, "start_sample": start,
                           "end_sample": end, "pcm_float32_sha256": actual})
        evidence = row.get("asr_input_evidence", {})
        parameters = evidence.get("parameter_devices", [])
        inputs = list(evidence.get("input_devices", {}).values())
        asr_ok = asr_ok and bool(parameters) and bool(inputs) and all(cuda(v) for v in parameters + inputs)
        asr_ok = asr_ok and cuda(evidence.get("output_device"))
    records = document.get("alignment_records", [])
    measured = [row for row in records if "decoder_input_device" in row]
    alignment_ok = bool(measured) and cuda(document.get("effective_parameters", {}).get("alignment", {}).get("model"))
    for row in measured:
        segment = document["original_segments"][row["segment_index"]]
        start = max(0, min(len(samples), int(segment["start"] * 16000)))
        end = max(0, min(len(samples), int(segment["end"] * 16000)))
        normalization = row.get("normalization", {})
        if normalization.get("source_sample_start") != start or normalization.get("source_sample_end") != end:
            raise ValueError("MMS normalization differs from the same ASR source window")
        alignment_ok = alignment_ok and all(cuda(value) for value in (
            row.get("model_output_device"), row.get("decoder_input_device"),
            row.get("decoder_output_device"), row.get("normalization", {}).get("actual_input_device")))
    stages = document.get("stage_execution", {})
    fresh = stages.get("asr") == "fresh_separate_process" and stages.get("alignment") == "fresh_separate_process"
    cap_clear = bool(traces) and all(row.get("token_limit_reached") is False for row in traces)
    return {"asr_gpu_observed": bool(asr_ok), "alignment_gpu_observed": bool(alignment_ok),
            "fresh_stage_execution": fresh, "token_cap_clear": cap_clear,
            "execution_verified": bool(asr_ok and alignment_ok and fresh and cap_clear),
            "planned_original_pcm_windows": pcm_checks,
            "asr_trace_count": len(traces), "alignment_gpu_record_count": len(measured),
            "alignment_failure_count": sum(bool(row.get("failure")) for row in records),
            "token_cap_chunk_count": sum(row.get("token_limit_reached") is True for row in traces)}


def summary_row(route: dict[str, Any], scope: str) -> dict[str, Any]:
    summary = route["summary"]
    text, timing = summary["text"], summary["timing"]
    return {"scope": scope, "variant": route["route_id"],
            **{key: text[key] for key in ("reference_characters", "candidate_characters", "S", "D", "I", "CER")},
            "timing_denominator": timing["denominator"], "measurable_count": timing["measurable_count"],
            "measurable_coverage": timing["measurable_coverage"],
            "recognized_character_coverage": timing["recognized_character_coverage"],
            "exact_character_coverage": timing["exact_character_coverage"],
            "boundary_complete_count": timing["boundary_complete_count"],
            "strict_half_second": timing["success"]["0.5"],
            "strict_half_second_lower_count": timing["success"]["0.5"]["success_count"],
            "conditional_P95_s": timing["error"]["p95"], "conditional_max_s": timing["error"]["max"],
            "conditional_count": timing["error"]["n"],
            "over_2_s": timing["over_threshold_counts"]["2.0"],
            "over_5_s": timing["over_threshold_counts"]["5.0"],
            "text_only_reference_spans": timing["status_counts"].get("text_only", 0),
            "status_counts": timing["status_counts"],
            "joint_completeness_timing_P95_s": timing["joint_completeness_timing"]["p95"],
            "execution_unverified_count": summary["execution_unverified_count"]}


def render_markdown(rows: list[dict[str, Any]]) -> str:
    lines = ["# X0 流程两窗评估", "", "范围：固定 II／III 两个已接触的 300 秒窗口；相对原始 SRT 显示边界，未做人工声学验证。",
             "全部参考跨度保留在分母。半秒成功要求两端严格小于 0.5 秒；条件 P95／最大值只使用该路线可测子集。",
             "插入 I 是编辑距离计数，不等同于重复或幻觉；重复另作字面诊断。两窗不执行 bootstrap，也不作产品通过判定。", "",
             "| 范围 | 路线 | CER | S/D/I | 参考字符 | 可测/N | 半秒成功/N | 条件 P95/最大（秒） | >2/>5秒 | text_only |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    def number(value: Any) -> str:
        return f"{value:.3f}" if isinstance(value, (int, float)) else "不可测"
    for row in rows:
        cer = f"{row['CER']:.2%}" if row["CER"] is not None else "未定义"
        n = row["timing_denominator"]
        lines.append(f"| {row['scope']} | {row['variant']} | {cer} | {row['S']}/{row['D']}/{row['I']} | {row['reference_characters']} | {row['measurable_count']}/{n} | {row['strict_half_second']['success_count']}/{n} | {number(row['conditional_P95_s'])}/{number(row['conditional_max_s'])} | {row['over_2_s']}/{row['over_5_s']} | {row['text_only_reference_spans']} |")
    return "\n".join(lines) + "\n"


def evaluate_study(study: Path, output: Path) -> dict[str, Any]:
    study, output = study.resolve(), output.resolve()
    if not study.is_relative_to((ROOT / ".local").resolve()):
        raise ValueError("Study must be a private .local directory")
    if not output.is_relative_to((ROOT / ".local").resolve()) or output.exists():
        raise ValueError("Output must be a new private .local directory")
    study_path = study / "study.json"
    frozen = read(study_path)
    study_sha = digest(study_path)
    round2_path = ROOT / ".local/round2/plan.json"
    round2 = read(round2_path)
    if frozen.get("source_plan_sha256") != digest(round2_path):
        raise ValueError("Study does not bind the unchanged round2 plan")
    clips = frozen["clips"]
    if tuple(clip["id"] for clip in clips) != CLIP_IDS or tuple(frozen["variants"]) != VARIANTS:
        raise ValueError("Expected exactly two frozen clips and three declared variants")
    originals = {clip["id"]: clip for clip in round2["clips"]}
    if any(clip != originals[clip["id"]] for clip in clips):
        raise ValueError("Study clips differ from frozen round2 inputs/references")
    before = check_inputs(clips)
    sources = [Path(__file__), ROOT / "experiments/components/evaluate.py",
               ROOT / "experiments/analysis/aggregate.py", ROOT / "experiments/analysis/build_round2.py",
               ROOT / "experiments/analysis/build_heldout.py", ROOT / "experiments/display/replay.py",
               *sorted((ROOT / "kototoki_eval").glob("*.py"))]
    source_before = {str(path): digest(path) for path in sources}
    process_path = study / "process-costs.json"
    process_document = json.loads(process_path.read_text(encoding="utf-8-sig")) if process_path.is_file() else []
    process_rows = process_document if isinstance(process_document, list) else process_document.get("entries", [])
    configurations, diagnostics, documents = [], [], {}
    for variant in VARIANTS:
        runs = []
        for clip in clips:
            result_path = study / clip["id"] / variant / "result.json"
            if not result_path.is_file():
                raise ValueError(f"Study is not terminal; required result is missing: {clip['id']}/{variant}")
            document = read(result_path)
            validate_transcript(document)
            if document.get("status") != "ok":
                raise ValueError(f"Noncomplete result requires explicit failure accounting: {clip['id']}/{variant}")
            documents[(clip["id"], variant)] = document
            proof = execution_proof(document, result_path, variant, clip)
            verified = proof["execution_verified"]
            runs.append({"clip_id": clip["id"], "run_id": f"{study.name}-{clip['id']}-{variant}",
                         "status": "completed" if verified else "execution_unverified",
                         "execution_verified": verified, "result_path": str(result_path), "result_sha256": digest(result_path)})
            normalized = normalize(document["text"]).text
            diagnostics.append({"clip_id": clip["id"], "variant": variant,
                                "execution_proof": proof,
                                "result": {"path": str(result_path), "sha256": digest(result_path)},
                                "timed_unit_count": sum(unit.get("status") == "ok" for unit in document["units"]),
                                "text_only_unit_count": sum(unit.get("status") == "text_only" for unit in document["units"]),
                                "text_only_characters": sum(unit["char_end"] - unit["char_start"] for unit in document["units"] if unit.get("status") == "text_only"),
                                "normalized_literal_repetition": repeated_unit_observation(normalized),
                                "chunk_boundary_literal_repetition": boundary_repeat_observations(document.get("original_segments", [])),
                                "repetition_scope": "Literal adjacent repeats only; genuine dialogue can repeat. CER insertions are not a repetition count.",
                                "costs": safe_costs(document, [row for row in process_rows if row.get("clip_id") == clip["id"] and row.get("variant") == variant])})
        configurations.append({"id": variant, "configuration_id": f"x0-flow-{variant}-v1", "runs": runs})
    # Historical controls have their own explicit identities and remain separate routes.
    historical = []
    progress_path = ROOT / ".local/round2/progress.json"
    progress = read(progress_path)["tasks"] if progress_path.is_file() else {}
    mms_plan_path = ROOT / ".local/japanese-ctc/jctc-mms-full-v2/plan.json"
    mms_plan = read(mms_plan_path) if mms_plan_path.is_file() else {}
    for label in ("historical-q0", "historical-x0-mms"):
        runs = []
        for clip in clips:
            if label == "historical-q0":
                receipt = progress.get(f"{clip['id']}-q0", {})
                value, expected = receipt.get("output"), receipt.get("output_sha256")
            else:
                task = next((task for task in mms_plan.get("tasks", []) if task["clip_id"] == clip["id"] and task["route"] == "x0" and task["candidate"] == "mms"), {})
                value = task.get("output")
                receipt_path = mms_plan_path.parent / "progress" / f"{task.get('id', 'missing')}.json"
                receipt = read(receipt_path) if receipt_path.is_file() else {}
                expected = receipt.get("artifacts", {}).get(value)
            if not value or not expected or receipt.get("status") != "completed":
                break
            result_path = path_from(value)
            if digest(result_path) != expected:
                raise ValueError(f"Historical result identity changed: {label}/{clip['id']}")
            old = read(result_path)
            historical.append({"clip_id": clip["id"], "control": label,
                               "result": {"path": str(result_path), "sha256": expected},
                               "fixed30_parity": text_and_units_parity(documents[(clip["id"], "fixed30")], old)})
            runs.append({"clip_id": clip["id"], "run_id": f"{label}-{clip['id']}", "status": "completed",
                         "execution_verified": True, "result_path": str(result_path), "result_sha256": expected})
        if len(runs) == len(clips):
            configurations.append({"id": label, "configuration_id": label, "runs": runs})
    manifest = {"schema_version": 1, "manifest_id": f"{study.name}-flow-evaluation", "frozen": True,
                "strict_hashes": True, "clips": clips, "configurations": configurations,
                "source_sha256": source_before}
    output.mkdir(parents=True, exist_ok=False)
    registry_path = output / "evaluation-registry.json"
    write_new(registry_path, manifest)
    report = build_component_report(registry_path, output / "details", bootstrap=False)
    pooled = report["pooled"]
    routes = {route["route_id"]: route for route in pooled["routes"]}
    transitions = {variant: severe_transitions(routes["fixed30"], routes[variant]) for variant in VARIANTS[1:]}
    rows = [summary_row(route, "两片汇总") for route in pooled["routes"]]
    rows += [summary_row(route, film) for film, value in report["films"].items() for route in value["routes"]]
    summary = {"schema_version": 1, "rows": rows, "diagnostics": diagnostics,
               "historical_parity": historical, "baseline_severe_transitions": transitions,
               "comparisons": pooled["comparisons"], "ranking": "not_performed",
               "P95_scope": "Conditional on each route's measurable spans; denominator and strict success remain full-reference",
               "references": "Frozen original SRT display boundaries; no independent acoustic ground truth",
               "bootstrap": "not_run_two_windows"}
    after = check_inputs(clips)
    source_after = {str(path): digest(path) for path in sources}
    if before != after or source_before != source_after or digest(study_path) != study_sha:
        raise ValueError("Source/reference/evaluator identity changed during evaluation")
    write_new(output / "integrity.json", {"study": {"path": str(study_path), "sha256": study_sha},
                                          "inputs_before": before, "inputs_after": after,
                                          "source_before": source_before, "source_after": source_after,
                                          "original_assets_unchanged": True})
    write_new(output / "summary.json", summary)
    (output / "summary.md").write_text(render_markdown(rows), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = evaluate_study(args.study, args.out)
    print(json.dumps({"output": str(args.out.resolve()), "rows": len(summary["rows"]),
                      "reference_integrity": "unchanged"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
