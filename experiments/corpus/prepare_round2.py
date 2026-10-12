"""Freeze deterministic II/III windows and sample-exact private PCM inputs."""

from __future__ import annotations

import argparse
import json
import subprocess
import wave
from pathlib import Path
from typing import Any

try:
    from .prepare import RATE, describe_audio, output_under, parse_srt, sha256, write_immutable
except ImportError:
    from prepare import RATE, describe_audio, output_under, parse_srt, sha256, write_immutable

REVISION = "hf-ii-iii-fixed-fractions-round2-2026-10-04"
FRACTIONS = (0.05, 0.20, 0.35, 0.50, 0.65, 0.80)
WINDOW_SECONDS = 300
FILMS = (
    {"id": "hf-ii", "name": "FateStay Night Heaven’s Feel II",
     "srt_sha256": "8366d17a2f0523fd1a82973736c18094d985abb95c3693b57e2a27517badf57d",
     "prior_exposure": "II evaluated in the previous round; not unseen heldout"},
    {"id": "hf-iii", "name": "FateStay Night Heaven's Feel III",
     "srt_sha256": "7c778cbd405e362fc659b237f870c5687ad5ea739e09509747575bd697a4ccbf",
     "prior_exposure": "III previously machine spotchecked for media matching; not unseen heldout"},
)
EDGE_CAVEAT = (
    "Every SRT cue overlapping the fixed audio window retains its original full text and source times, "
    "including boundary-straddling cues. Their partially unavailable speech can bias full-content CER "
    "and timing failure counts; these spans are flagged uncertain. No reference-driven audio cuts, "
    "reference text clipping, candidate timestamp filtering, or removal of candidate insertions. "
    "Display times are not acoustic ground truth; no tuning or independent heldout claim."
)


def fixed_windows(duration_seconds: float) -> list[dict[str, Any]]:
    """Determine windows solely from total duration, before reading reference text."""
    result = []
    for ordinal, fraction in enumerate(FRACTIONS, 1):
        start = round(duration_seconds * fraction * RATE)
        end = start + WINDOW_SECONDS * RATE
        if end > round(duration_seconds * RATE):
            raise ValueError("Source too short for predeclared window design")
        if result and start < result[-1]["source_end_sample"]:
            raise ValueError("Predeclared windows overlap; this source does not meet sampling design")
        result.append({"ordinal": ordinal, "fraction": fraction,
                       "source_start_sample": start, "source_end_sample": end,
                       "source_start_seconds": start / RATE, "source_end_seconds": end / RATE,
                       "duration_seconds": WINDOW_SECONDS})
    return result


def window_reference(spans: list[dict[str, Any]], start: float, end: float,
                     film_id: str, window_id: str, srt_hash: str) -> dict[str, Any]:
    selected = []
    for source in spans:
        if source["end"] <= start or source["start"] >= end:
            continue
        span = dict(source)
        # Preserve the already-cleaned current SRT exactly; no new SDH exclusions.
        span["text"] = source["original_text"]
        span["id"] = f"{film_id}-{source['id']}"
        span["removed_prefix_labels"] = []
        span["scene_id"] = window_id
        span["partition"] = "frozen_comparison_no_tuning"
        span["boundary_crossing"] = source["start"] < start or source["end"] > end
        span["content_uncertainty"] = "partial_audio_at_window_edge" if span["boundary_crossing"] else "srt_not_acoustically_reviewed"
        span["acoustic_review"] = False
        if span["text"].strip():
            selected.append(span)
    return {"schema_version": 1, "reference_kind": "srt_display", "spans": selected,
            "corpus_revision": REVISION, "source_reference_sha256": srt_hash,
            "scope": window_id, "time_coordinate": "source_media_seconds",
            "source_start_seconds": start, "source_end_seconds": end,
            "acoustic_ground_truth": False, "boundary_policy": EDGE_CAVEAT}


def require_hash(path: Path, expected: str) -> str:
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"Frozen input hash mismatch: {path}")
    return actual


def verify_existing_audio(path: Path, descriptor: Path, start: float) -> dict[str, Any] | None:
    if not descriptor.exists():
        if path.exists():
            raise ValueError(f"Unmanifested PCM output exists: {path}")
        return None
    previous = json.loads(descriptor.read_text(encoding="utf-8"))
    current = describe_audio(path, start)
    for key in current:
        if current[key] != previous[key]:
            raise ValueError(f"Frozen PCM descriptor mismatch ({key}): {path}")
    return previous


def crop_pcm(full: Path, target: Path, start_sample: int, end_sample: int) -> None:
    """Read one exact half-open sample range; never seek compressed media."""
    with wave.open(str(full), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Full PCM contract mismatch")
        if not 0 <= start_sample < end_sample <= source.getnframes():
            raise ValueError("Sample range outside decoded source")
        if target.exists():
            raise ValueError("Refusing to replace existing crop")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.setpos(start_sample)
        with wave.open(str(target), "wb") as output:
            output.setparams((1, 2, RATE, end_sample - start_sample, "NONE", "not compressed"))
            remaining = end_sample - start_sample
            while remaining:
                count = min(remaining, RATE * 60)
                block = source.readframes(count)
                if len(block) != count * 2:
                    raise ValueError("Decoded source ended inside requested crop")
                output.writeframesraw(block)
                remaining -= count


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = args.private_root.resolve()
    if root.is_relative_to(args.media_root.resolve()) or root.is_relative_to(Path("D:/movie").resolve()):
        raise ValueError("Output cannot be inside source media directory")
    ffmpeg_version = subprocess.check_output([str(args.ffmpeg), "-version"], text=True).splitlines()[0]
    films = []
    for spec in FILMS:
        base = args.media_root / spec["name"] / spec["name"]
        audio = Path(str(base) + ".jpn.flac")
        srt = Path(str(base) + ".jpn.srt")
        srt_hash = require_hash(srt, spec["srt_sha256"])
        audio_hash = sha256(audio)
        probe = json.loads(subprocess.check_output(
            [str(args.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(audio)],
            text=True, encoding="utf-8"))
        streams = [s for s in probe["streams"] if s["codec_type"] == "audio"]
        if len(streams) != 1:
            raise ValueError("Expected exactly one external audio stream")
        stream = streams[0]
        if stream["channels"] != 2:
            raise ValueError("Round2 frozen preprocessing requires stereo external audio")
        if float(probe["format"].get("start_time", 0)) != 0 or float(stream.get("start_time", 0)) != 0:
            raise ValueError("Nonzero source origin requires explicit mapping")
        duration = float(probe["format"]["duration"])
        windows = fixed_windows(duration)
        spans = parse_srt(srt)
        film = {**spec, "source_audio_path": str(audio.resolve()), "source_srt_path": str(srt.resolve()),
                "source_audio_sha256": audio_hash, "source_srt_sha256": srt_hash,
                "source_audio_bytes": audio.stat().st_size, "source_srt_bytes": srt.stat().st_size,
                "source_origin_seconds": 0, "media_duration_seconds": duration,
                "source_rate": int(stream["sample_rate"]), "source_channels": stream["channels"],
                "source_codec": stream["codec_name"], "source_reference_cue_count": len(spans),
                "full_audio_path": str(root / "audio" / f"{spec['id']}-full.wav"), "windows": []}
        for window in windows:
            identity = f"{spec['id']}-window-{window['ordinal']:02d}"
            reference_path = output_under(root / "references" / f"{identity}.json", root)
            reference = window_reference(spans, window["source_start_seconds"], window["source_end_seconds"],
                                         spec["id"], identity, srt_hash)
            write_immutable(reference_path, reference)
            film["windows"].append({**window, "id": identity, "film_id": spec["id"],
                                    "audio_path": str(root / "audio" / f"{identity}.wav"),
                                    "audio_manifest_path": str(root / "manifests" / f"{identity}-audio.json"),
                                    "reference_path": str(reference_path), "reference_sha256": sha256(reference_path),
                                    "reference_cue_count": len(reference["spans"]),
                                    "edge_cue_ids": [s["id"] for s in reference["spans"] if s["boundary_crossing"]]})
        films.append(film)
    selection = {"schema_version": 1, "corpus_revision": REVISION,
                 "frozen_before_round2_candidate_results": True,
                 "selection_kind": "stratified deterministic duration fractions; not fullfilm or independent random sample",
                 "fractions": list(FRACTIONS), "window_seconds": WINDOW_SECONDS,
                 "sample_seconds_total": len(FILMS) * len(FRACTIONS) * WINDOW_SECONDS,
                 "partition": "frozen_comparison_no_tuning", "unseen_heldout": False,
                 "boundary_policy": EDGE_CAVEAT, "reference_rule": "all overlapping current SRT cues; original text and source times unchanged",
                 "preprocessing": "decode from beginning; pan=mono|c0=0.5*c0+0.5*c1,aresample=16000, pcm_s16le; no denoising",
                 "time_mapping": "source_seconds = local_sample_index / 16000 + source_start_seconds",
                 "ffmpeg_path": str(args.ffmpeg.resolve()), "ffmpeg_sha256": sha256(args.ffmpeg),
                 "ffmpeg_version": ffmpeg_version, "films": films}
    write_immutable(output_under(root / "manifests/selection-freeze.json", root), selection)
    for film in films:
        full = Path(film["full_audio_path"])
        descriptor = root / "manifests" / f"{film['id']}-full-audio.json"
        full_info = verify_existing_audio(full, descriptor, 0)
        if full_info is None:
            full.parent.mkdir(parents=True, exist_ok=True)
            command = [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                       "-i", film["source_audio_path"], "-map", "0:a:0", "-vn", "-sn", "-dn",
                       "-af", "pan=mono|c0=0.5*c0+0.5*c1,aresample=16000", "-c:a", "pcm_s16le",
                       "-fflags", "+bitexact", "-flags:a", "+bitexact", str(full)]
            subprocess.run(command, check=True)
            full_info = describe_audio(full, 0)
            full_info["command"] = command
            full_info["source_audio_sha256"] = film["source_audio_sha256"]
            write_immutable(descriptor, full_info)
        if abs(full_info["duration_seconds"] - film["media_duration_seconds"]) > 1 / RATE:
            raise ValueError("Decoded duration does not match source duration within one output sample")
        film["full_pcm"] = full_info
        if film["id"] == "hf-ii":
            film["historical_pcm_comparison"] = {
                "historical_pcm_sha256": "ee4e2da3e0b335f3d3f9d0b0a0b5bb301562846195e5419716b3ed83d76d604f",
                "historical_samples": 112448683,
                "same_pcm_as_previous_round": full_info["pcm_sha256"] == "ee4e2da3e0b335f3d3f9d0b0a0b5bb301562846195e5419716b3ed83d76d604f",
                "same_samples_as_previous_round": full_info["samples"] == 112448683}
        for window in film["windows"]:
            target, metadata = Path(window["audio_path"]), Path(window["audio_manifest_path"])
            info = verify_existing_audio(target, metadata, window["source_start_seconds"])
            if info is None:
                crop_pcm(full, target, window["source_start_sample"], window["source_end_sample"])
                info = describe_audio(target, window["source_start_seconds"])
                info.update({"source_start_sample": window["source_start_sample"],
                             "source_end_sample": window["source_end_sample"], "source_pcm_sha256": full_info["pcm_sha256"]})
                write_immutable(metadata, info)
            if info["samples"] != WINDOW_SECONDS * RATE:
                raise ValueError("Crop sample count differs from predeclared design")
            window["audio"] = info
        require_hash(Path(film["source_srt_path"]), film["source_srt_sha256"])
        require_hash(Path(film["source_audio_path"]), film["source_audio_sha256"])
        film["source_srt_sha256_after"] = film["source_srt_sha256"]
        film["source_audio_sha256_after"] = film["source_audio_sha256"]
    write_immutable(output_under(root / "manifests/corpus.json", root), selection)
    runner_manifest = {"schema_version": 1, "corpus_revision": REVISION,
                       "corpus_manifest_path": str(root / "manifests/corpus.json"),
                       "corpus_manifest_sha256": sha256(root / "manifests/corpus.json"),
                       "boundary_policy": EDGE_CAVEAT, "clips": [
        {"id": w["id"], "film": f["id"], "audio": w["audio_path"], "reference": w["reference_path"],
         "reference_sha256": w["reference_sha256"], "offset": w["source_start_seconds"],
         "inference_local_start_seconds": 0, "duration": w["duration_seconds"],
         "source_start_seconds": w["source_start_seconds"], "source_end_seconds": w["source_end_seconds"],
         "source_audio": f["source_audio_path"], "source_audio_sha256": f["source_audio_sha256"],
         "source_srt": f["source_srt_path"], "source_srt_sha256": f["source_srt_sha256"],
         "audio_sha256": w["audio"]["wav_sha256"], "pcm_sha256": w["audio"]["pcm_sha256"],
         "edge_cue_ids": w["edge_cue_ids"]} for f in films for w in f["windows"]]}
    write_immutable(output_under(root / "manifest.json", root), runner_manifest)
    return selection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-root", type=Path, default=Path("D:/movie"))
    parser.add_argument("--private-root", type=Path, default=Path(".local/round2/corpus"))
    parser.add_argument("--ffmpeg", type=Path, default=Path("D:/bin/ffmpeg.exe"))
    parser.add_argument("--ffprobe", type=Path, default=Path("D:/bin/ffprobe.exe"))
    result = prepare(parser.parse_args())
    print(json.dumps({"corpus_revision": REVISION, "sample_seconds_total": result["sample_seconds_total"],
                      "films": [{"id": f["id"], "windows": len(f["windows"]),
                                 "cue_count": sum(w["reference_cue_count"] for w in f["windows"]),
                                 "edge_cue_count": sum(len(w["edge_cue_ids"]) for w in f["windows"])} for f in result["films"]]}))


if __name__ == "__main__":
    main()
