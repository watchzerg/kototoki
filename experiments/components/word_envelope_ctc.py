"""Build a CTC input bridge whose search bounds enclose unchanged native W0 words."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from experiments.components.align_raw_w0 import validate_cached_asr
from experiments.components.separate import read_pcm, sha256


def finite_bound(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Nonfinite or nonnumeric {label}")
    return value


def envelope(segments: list[dict[str, Any]], duration: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Change only parent bounds, using its own words, without padding or reference input."""
    finite_bound(duration, "audio duration")
    if duration <= 0:
        raise ValueError("Audio duration must be positive")
    if not isinstance(segments, list):
        raise ValueError("Original segments must be a complete list")
    repaired, mapping = deepcopy(segments), []
    previous_end = 0
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError("Malformed native segment")
        start, end = finite_bound(segment.get("start"), "parent onset"), finite_bound(segment.get("end"), "parent offset")
        if end < start or not isinstance(segment.get("text"), str):
            raise ValueError("Parent bounds are reversed or complete segment text is absent")
        words = segment.get("words", [])
        if not isinstance(words, list):
            raise ValueError("Native words must be a list")
        word_bounds = []
        previous_word_end = 0
        for word in words:
            if not isinstance(word, dict):
                raise ValueError("Malformed native word")
            begin = finite_bound(word.get("start"), "word onset")
            finish = finite_bound(word.get("end"), "word offset")
            if not 0 <= begin <= finish <= duration or begin < previous_word_end:
                raise ValueError("Native words are outside audio, reversed, overlapping, or unordered")
            previous_word_end = finish
            word_bounds.append((begin, finish))
        search_start = max(0, min([start] + [bounds[0] for bounds in word_bounds]))
        search_end = min(duration, max([end] + [bounds[1] for bounds in word_bounds]))
        if not 0 <= previous_end <= search_start < search_end <= duration:
            raise ValueError("Repaired search windows overlap, are unordered, empty, or outside audio")
        previous_end = search_end
        repaired[index]["start"], repaired[index]["end"] = search_start, search_end
        mapping.append({"segment_index": index, "original_start": start, "original_end": end,
                        "search_start": search_start, "search_end": search_end,
                        "source_sample_start": int(search_start * 16000),
                        "source_sample_end_exclusive": int(search_end * 16000),
                        "word_count": len(words), "changed": start != search_start or end != search_end,
                        "word_envelope_start": min([bounds[0] for bounds in word_bounds], default=None),
                        "word_envelope_end": max([bounds[1] for bounds in word_bounds], default=None),
                        "parent_clamped": start < 0 or end > duration,
                        "text_sha256": hashlib.sha256(segment["text"].encode()).hexdigest()})
    return repaired, mapping


def mapping_hash(mapping: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_bridge(source_asr: Path, audio: Path, offset: float) -> dict[str, Any]:
    source_hash = sha256(source_asr)
    original = json.loads(source_asr.read_text(encoding="utf-8"))
    _, identity = read_pcm(audio)
    validate_cached_asr(original, {"audio_sha256": identity["file_sha256"], "pcm_sha256": identity["pcm_sha256"], "offset": offset})
    repaired, mapping = envelope(original["original_segments"], identity["duration_s"])
    if "".join(segment["text"] for segment in repaired) != original["text"]:
        raise RuntimeError("Window repair changed the complete ASR text")
    if sha256(source_asr) != source_hash:
        raise RuntimeError("Source ASR changed during bridge creation")
    return {"schema_version": 1, "status": "ok", "text": original["text"], "input": identity,
            "offset_s": offset, "source_start_seconds": offset, "duration_seconds": identity["duration_s"],
            "original_segments": repaired,
            "original_asr": {"source_result": str(source_asr.resolve()), "source_result_sha256": source_hash,
                             "text": original["text"], "original_segments": original["original_segments"]},
            "window_repair": {"method": "parent-and-own-native-word-envelope-v1", "mapping": mapping,
                              "mapping_sha256": mapping_hash(mapping), "changed_segments": sum(row["changed"] for row in mapping),
                              "source_sha256": sha256(Path(__file__)), "reference_text_used": False,
                              "ctc_scores_used": False, "padding_s": 0,
                              "overlap_policy": "reject overlapping repaired windows or native words",
                              "out_of_audio_policy": "reject words outside input; clamp parent envelope to input duration",
                              "asr_metadata_unchanged": True},
            "cached_inference": True, "new_asr_inference": False,
            "stage_cache": {"asr": "complete historical raw W0", "alignment": "not_yet_executed"}}


def verify_bridge(bridge: dict[str, Any], saved: dict[str, Any], offset: float) -> None:
    repaired, mapping = envelope(saved["original_segments"], saved["input"]["duration_s"])
    if (bridge.get("text") != saved["text"] or bridge.get("offset_s") != offset
            or bridge.get("original_segments") != repaired
            or bridge.get("original_asr", {}).get("original_segments") != saved["original_segments"]
            or bridge.get("original_asr", {}).get("text") != saved["text"]
            or bridge.get("input", {}).get("pcm_sha256") != saved["input"]["pcm_sha256"]
            or bridge.get("input", {}).get("file_sha256") != saved["input"]["file_sha256"]
            or bridge.get("input", {}).get("duration_s") != saved["input"]["duration_s"]
            or bridge.get("source_start_seconds") != offset
            or bridge.get("duration_seconds") != saved["input"]["duration_s"]
            or bridge.get("window_repair", {}).get("mapping") != mapping
            or bridge.get("window_repair", {}).get("mapping_sha256") != mapping_hash(mapping)):
        raise ValueError("Bridge differs from the deterministic native-word window repair")
