"""Freeze six new III intervals from verified existing PCM, without inference."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from experiments.corpus import prepare as original
from experiments.corpus import prepare_round2 as round2

ROOT = Path(__file__).resolve().parents[2]
REVISION = "hf-iii-new-intervals-components-confirmation-2026-10-04"
FRACTIONS = (0.10, 0.275, 0.45, 0.575, 0.725, 0.90)
GUARD_SECONDS = 60
SPOTCHECKS = ((636.11, 660.11), (3172.06, 3196.06), (6371.38, 6395.38))
EXPOSURE = {
    "film_previously_exposed": True,
    "intervals_previously_candidate_scored": False,
    "unseen_film_heldout": False,
    "scope": "New nonoverlapping intervals of the already exposed III film; locked-configuration confirmation only, not independent cross-film validation",
    "reference_kind": "srt_display",
    "acoustic_ground_truth": False,
    "bootstrap": "Disabled: six intervals are below the existing ten-scene minimum and remain correlated within one film",
}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fixed_windows(duration: float, samples: int) -> list[dict[str, Any]]:
    """Select sample-exact intervals solely from the predeclared fractions."""
    if not math.isfinite(duration) or duration <= 0 or samples <= 0:
        raise ValueError("Invalid source duration or sample count")
    windows = []
    for index, fraction in enumerate(FRACTIONS, 1):
        start = round(duration * fraction * original.RATE)
        end = start + round2.WINDOW_SECONDS * original.RATE
        if not 0 <= start < end <= samples:
            raise ValueError("Predeclared confirmation interval exceeds source PCM")
        windows.append({"id": f"hf-iii-confirmation-{index:02d}", "fraction": fraction,
                        "source_start_sample": start, "source_end_sample": end,
                        "source_start_seconds": start / original.RATE,
                        "source_end_seconds": end / original.RATE,
                        "duration_seconds": round2.WINDOW_SECONDS})
    return windows


def validate_intervals(windows: list[dict[str, Any]], exposed: list[dict[str, Any]],
                       guard_seconds: float = GUARD_SECONDS) -> float:
    """Reject overlaps and insufficient guard before creating any outputs."""
    if not math.isfinite(guard_seconds) or guard_seconds < 0:
        raise ValueError("Invalid interval guard")
    guard = round(guard_seconds * original.RATE)
    all_ranges = []
    minimum = math.inf
    for window in windows:
        start, end = window["source_start_sample"], window["source_end_sample"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("Invalid sample interval")
        for other in exposed + all_ranges:
            left, right = other["source_start_sample"], other["source_end_sample"]
            gap = max(start - right, left - end)
            if gap < guard:
                raise ValueError("Confirmation interval overlaps or violates exposure guard")
            minimum = min(minimum, gap / original.RATE)
        all_ranges.append(window)
    return minimum


def prepare(output: Path, *, round2_root: Path | None = None,
            media_manifest: Path | None = None) -> dict[str, Any]:
    output = output.resolve()
    if not output.is_relative_to(ROOT / ".local/components"):
        raise ValueError("Confirmation corpus must remain inside project .local/components")
    if output.exists():
        raise FileExistsError("Use a fresh confirmation corpus; existing evidence is immutable")
    round2_root = round2_root or ROOT / ".local/round2/corpus"
    media_manifest = media_manifest or ROOT / ".local/media-validation/samples/manifest.json"
    flat_path = round2_root / "manifest.json"
    detailed_path = round2_root / "manifests/corpus.json"
    descriptor = round2_root / "manifests/hf-iii-full-audio.json"
    flat, detailed = read(flat_path), read(detailed_path)
    film = next(f for f in detailed["films"] if f["id"] == "hf-iii")
    old = [c for c in flat["clips"] if c["film"] == "hf-iii"]
    if len(old) != 6 or original.sha256(detailed_path) != flat["corpus_manifest_sha256"]:
        raise ValueError("Existing round2 corpus identity or III interval count differs")
    source_audio, source_srt = Path(film["source_audio_path"]), Path(film["source_srt_path"])
    full = Path(film["full_audio_path"])
    protected = {str(source_audio): film["source_audio_sha256"],
                 str(source_srt): film["source_srt_sha256"],
                 str(full): film["full_pcm"]["wav_sha256"]}
    for path, expected in protected.items():
        round2.require_hash(Path(path), expected)
    full_info = round2.verify_existing_audio(full, descriptor, 0)
    if full_info is None:
        raise ValueError("Confirmation requires already provisioned full PCM")
    if any(full_info.get(key) != film["full_pcm"].get(key) for key in
           ("samples", "sample_rate", "channels", "wav_sha256", "pcm_sha256", "source_audio_sha256")):
        raise ValueError("Existing full PCM descriptor differs from frozen corpus")
    if abs(full_info["duration_seconds"] - film["media_duration_seconds"]) > 1 / original.RATE:
        raise ValueError("Source duration differs by more than one PCM sample")
    if any(c["source_audio_sha256"] != film["source_audio_sha256"] or
           c["source_srt_sha256"] != film["source_srt_sha256"] for c in old):
        raise ValueError("Flat and detailed III source identities differ")
    actual_spots = sorted((s["source_start"], s["source_start"] + s["duration"])
                          for s in read(media_manifest)["samples"] if s["id"].startswith("3-"))
    if len(actual_spots) != len(SPOTCHECKS) or any(abs(a - b) > 1e-6
            for pair, expected in zip(actual_spots, SPOTCHECKS) for a, b in zip(pair, expected)):
        raise ValueError("III media spotcheck exposure differs from predeclared exclusions")
    exposed = [{"id": c["id"], "source_start_sample": round(c["source_start_seconds"] * original.RATE),
                "source_end_sample": round(c["source_end_seconds"] * original.RATE)} for c in old]
    exposed += [{"id": f"media-spotcheck-{i}", "source_start_sample": round(start * original.RATE),
                 "source_end_sample": round(end * original.RATE)} for i, (start, end) in enumerate(SPOTCHECKS, 1)]
    windows = fixed_windows(film["media_duration_seconds"], full_info["samples"])
    minimum_gap = validate_intervals(windows, exposed)
    inputs = {str(path.resolve()): original.sha256(path) for path in
              (flat_path, detailed_path, descriptor, media_manifest)}
    sources = {str(path.resolve()): original.sha256(path) for path in
               (Path(__file__), Path(original.__file__), Path(round2.__file__))}
    freeze = {"schema_version": 1, "corpus_revision": REVISION,
              "frozen_utc": datetime.now(timezone.utc).isoformat(),
              "frozen_before_new_interval_component_scores": True,
              "selection_basis": "Predeclared duration fractions and existing exposure intervals only; no candidate results read",
              "exposure": EXPOSURE, "fractions": list(FRACTIONS), "window_seconds": round2.WINDOW_SECONDS,
              "sample_seconds_total": 6 * round2.WINDOW_SECONDS, "windows": windows,
              "excluded_exposed_intervals": exposed, "guard_seconds": GUARD_SECONDS,
              "minimum_interval_gap_seconds": minimum_gap,
              "source_media_duration_seconds": film["media_duration_seconds"],
              "full_pcm": full_info, "protected_asset_sha256": protected,
              "input_manifest_sha256": inputs, "source_sha256": sources,
              "boundary_policy": round2.EDGE_CAVEAT,
              "preprocessing": "Sample crop of verified round2 mono16k PCM16; no decoding, denoising, VAD, separation or model inference",
              "time_mapping": "source_seconds = local_sample_index / 16000 + source_start_seconds"}
    original.write_immutable(output / "manifests/selection-freeze.json", freeze)
    spans = original.parse_srt(source_srt)
    clips = []
    for window in windows:
        reference = round2.window_reference(spans, window["source_start_seconds"],
                    window["source_end_seconds"], "hf-iii", window["id"], film["source_srt_sha256"])
        reference["corpus_revision"] = REVISION
        reference["exposure"] = EXPOSURE
        for span in reference["spans"]:
            span["partition"] = "locked_configuration_confirmation_new_intervals_same_exposed_film"
        reference_path = output / "references" / f"{window['id']}.json"
        original.write_immutable(reference_path, reference)
        audio_path = output / "audio" / f"{window['id']}.wav"
        round2.crop_pcm(full, audio_path, window["source_start_sample"], window["source_end_sample"])
        info = original.describe_audio(audio_path, window["source_start_seconds"])
        if info["samples"] != round2.WINDOW_SECONDS * original.RATE:
            raise ValueError("Confirmation crop has incorrect sample count")
        info.update({"source_start_sample": window["source_start_sample"],
                     "source_end_sample": window["source_end_sample"], "source_pcm_sha256": full_info["pcm_sha256"]})
        original.write_immutable(output / "manifests" / f"{window['id']}-audio.json", info)
        clips.append({"id": window["id"], "film": "hf-iii", "audio": str(audio_path),
                      "audio_sha256": info["wav_sha256"], "pcm_sha256": info["pcm_sha256"],
                      "reference": str(reference_path), "reference_sha256": original.sha256(reference_path),
                      "offset": window["source_start_seconds"], "inference_local_start_seconds": 0,
                      "duration": round2.WINDOW_SECONDS, "source_start_seconds": window["source_start_seconds"],
                      "source_end_seconds": window["source_end_seconds"],
                      "source_audio": str(source_audio), "source_audio_sha256": film["source_audio_sha256"],
                      "source_srt": str(source_srt), "source_srt_sha256": film["source_srt_sha256"],
                      "edge_cue_ids": [s["id"] for s in reference["spans"] if s["boundary_crossing"]]})
    for path, expected in {**protected, **inputs, **sources}.items():
        round2.require_hash(Path(path), expected)
    completion = {**freeze, "status": "all_six_ready", "clips": clips,
                  "protected_asset_sha256_after": protected, "input_manifests_unchanged": True,
                  "sample_count_per_clip": round2.WINDOW_SECONDS * original.RATE}
    corpus_path = output / "manifests/corpus.json"
    original.write_immutable(corpus_path, completion)
    manifest = {"schema_version": 1, "corpus_revision": REVISION,
                "corpus_manifest_path": str(corpus_path), "corpus_manifest_sha256": original.sha256(corpus_path),
                "boundary_policy": round2.EDGE_CAVEAT, "exposure": EXPOSURE,
                "selection_freeze_path": str(output / "manifests/selection-freeze.json"),
                "selection_freeze_sha256": original.sha256(output / "manifests/selection-freeze.json"),
                "clips": clips}
    original.write_immutable(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".local/components/confirmation-corpus")
    result = prepare(parser.parse_args().output)
    print(json.dumps({"status": "all_six_ready", "manifest": result["corpus_manifest_path"],
                      "windows": len(result["clips"]), "duration_seconds": sum(c["duration"] for c in result["clips"])}))


if __name__ == "__main__":
    main()
