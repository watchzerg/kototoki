"""Backend-neutral ASR and complete-character result validation."""
from __future__ import annotations

import math
from kototoki_eval.schema import validate_transcript
from .chunks import RATE, validate_chunks


def validate_asr(saved: dict, chunks: list[dict], samples: int, *, retain_all: bool = True) -> None:
    validate_chunks(chunks, samples, retain_all=retain_all)
    segments = saved["original_segments"]
    if len(segments) != len(chunks):
        raise ValueError("ASR must return one segment per planned source window")
    for segment, chunk in zip(segments, chunks):
        if (not isinstance(segment.get("text"), str)
                or any(segment.get(k) != chunk[k] for k in ("start_sample", "end_sample", "start", "end"))):
            raise ValueError("ASR must preserve planned integer windows and original text")
    if saved["text"] != "".join(s["text"] for s in segments):
        raise ValueError("ASR complete text differs from original segments")
    traces = saved["asr_traces"]
    if len(traces) != len(chunks):
        raise ValueError("ASR trace count differs from source windows")
    for index, (trace, chunk) in enumerate(zip(traces, chunks)):
        if (trace.get("chunk_index") != index or any(trace.get(k) != chunk[k] for k in ("start_sample", "end_sample"))
                or not isinstance(trace.get("pcm_float32_sha256"), str)):
            raise ValueError("ASR traces must identify each exact source window")
        if trace.get("token_limit_reached"):
            raise ValueError("Qwen generation reached its token cap; partial ASR evidence is retained")


def build_result(plan: dict, saved: dict, aligned: dict, metadata: dict, stages: dict) -> dict:
    samples, offset = plan["input"]["samples"], plan["offset_s"]
    validate_asr(saved, plan["chunks"], samples, retain_all=plan["segmentation"] != "vad")
    if isinstance(offset, bool) or not math.isfinite(offset) or offset < 0:
        raise ValueError("Finite nonnegative source offset required")
    if aligned["text"] != saved["text"]:
        raise ValueError("Alignment must preserve complete ASR text")
    failures = [r for r in aligned["records"] if r.get("failure")]
    result = {"schema_version": 1, "recipe": plan["recipe"], "route": "X0",
        "segmentation": plan["segmentation"], "status": "partial" if failures else "ok", "text": saved["text"],
        "alignment_failure_count": len(failures),
        "alignment_failed_segment_indices": [r["segment_index"] for r in failures],
        "units": aligned["units"], "cues": [], "original_segments": saved["original_segments"],
        "chunks": plan["chunks"], "asr_traces": saved["asr_traces"],
        "alignment_records": aligned["records"], "derived_segments": aligned["derived_segments"],
        "effective_parameters": {"segmentation": plan["effective_parameters"],
                                 "asr": saved["effective_parameters"], "alignment": metadata},
        "input": plan["input"], "offset_s": offset, "source_start_seconds": offset,
        "duration_seconds": samples / RATE, "source_end_seconds": offset + samples / RATE,
        "source_sha256": plan["source_sha256"], "retained_samples": plan.get("retained_samples", samples),
        "removed_samples": plan.get("removed_samples", 0),
        "stages": stages, "cached_inference": False, "offline_requested": True,
        "stage_execution": {"planning": "fresh", "asr": "fresh_separate_process",
                            "alignment": "fresh_separate_process"}}
    if plan["segmentation"] == "vad":
        result.update(vad_id=plan["vad_id"], vad_provenance=plan["vad_provenance"])
        result["stage_execution"]["vad"] = "precomputed_external_manifest"
        if not plan["chunks"]:
            result["stage_execution"].update(asr="skipped_no_speech", alignment="skipped_no_speech")
    validate_transcript(result)
    covered = [0] * len(result["text"])
    for unit in result["units"]:
        for index in range(unit["char_start"], unit["char_end"]):
            covered[index] += 1
        if unit["status"] == "ok":
            start, end = unit.get("start"), unit.get("end")
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in (start, end)) or not offset <= start <= end <= offset + samples / RATE + .001):
                raise ValueError("Timed units must stay within original source audio")
        elif unit.get("start") is not None or unit.get("end") is not None:
            raise ValueError("Untimed characters must not fabricate lexical intervals")
    if any(n != 1 for n in covered):
        raise ValueError("Every original character must be accounted for exactly once")
    result["text_only_characters"] = sum(u["char_end"] - u["char_start"] for u in result["units"]
                                          if u["status"] == "text_only")
    return result
