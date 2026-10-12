"""Import frozen VAD evidence without running VAD or changing source audio."""
from __future__ import annotations

from pathlib import Path

from experiments.w0_demo.run import read_vad_manifest
from .chunks import RATE, make_chunk, validate_chunks
from .storage import sha256


def import_vad_plan(reference: dict, identity: dict, offset: float) -> tuple[list[dict], dict, dict]:
    """Use the same floor-and-clip source crops as W0, retaining gap samples."""
    path = Path(reference["frozen_path"])
    if sha256(path) != reference["sha256"]:
        raise ValueError("Frozen external VAD manifest changed")
    manifest = read_vad_manifest(path, identity, offset)
    chunks = []
    for window in manifest["chunks"]:
        start = window.get("start_sample", max(0, int(window["start"] * RATE)))
        end = window.get("end_sample", min(identity["samples"], int(window["end"] * RATE)))
        chunk = make_chunk(start, end)
        chunk["vad_window"] = window
        chunks.append(chunk)
    validate_chunks(chunks, identity["samples"], retain_all=False)
    provenance = {**reference, "vad_id": manifest["vad_id"], "vad_recipe": manifest["recipe"],
                  "metadata": manifest["metadata"], "precomputed_stages": manifest["stages"]}
    metadata = {"kind": "vad", "vad": True, "vad_id": manifest["vad_id"],
                "retain_all_samples": False, "max_samples": 480000, "sample_rate": RATE,
                "audio_transform": "none", "crop_rule": "explicit_integer_samples_else_floor_seconds_clip",
                "input_mode": "whole_source_window_including_internal_gaps",
                "vad_execution": "precomputed_external_manifest"}
    return chunks, metadata, provenance
