"""Freeze complete private HF II/III inputs without inference or reference cuts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
from typing import Any

from experiments.corpus.prepare import RATE, describe_audio, output_under, parse_srt, sha256, write_immutable
from experiments.corpus.prepare_round2 import FILMS, require_hash, verify_existing_audio
from kototoki_eval.schema import normalize

ROOT = Path(__file__).resolve().parents[2]
REVISION = "hf-ii-iii-complete-films-v1-2026-10-05"
BIN_SECONDS = 300
PREPROCESSING = "pan=mono|c0=0.5*c0+0.5*c1,aresample=16000"
SOURCE_AUDIO_HASHES = {
    "hf-ii": "8138e17de9ec10215c24a465a0fa166b65d9cce8839ef819bc6eb3676e0ccd1f",
    "hf-iii": "11d0d17746f31bd9b7c7b8d246aae915e77b6b41b0509640f48bc381991feaaf",
}
REFERENCE_CAVEAT = (
    "Current official-source SRT text and display times are preserved; not acoustic ground truth. "
    "All audio including credits and any unreferenced speech or singing is retained. "
    "Candidate insertions can include unreferenced real speech/singing, not necessarily hallucination. "
    "No listening review, new reference exclusions, tuning, or unseen-heldout claim."
)
BIN_POLICY = (
    "Fixed 300-second half-open bins cover [0, EOF) without gaps. Each full reference cue is "
    "assigned once by its display-time midpoint; cues crossing bin boundaries are flagged and "
    "never clipped or duplicated. These are evaluation strata only, not inference windows."
)


def scoring_bins(samples: int, film_id: str) -> list[dict[str, Any]]:
    """Freeze complete sample coverage independently of subtitles/candidates."""
    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        raise ValueError("Full source must have a positive integer sample count")
    step = BIN_SECONDS * RATE
    return [
        {"id": f"{film_id}-bin-{ordinal:02d}", "ordinal": ordinal,
         "source_start_sample": start, "source_end_sample": min(start + step, samples),
         "source_start_seconds": start / RATE, "source_end_seconds": min(start + step, samples) / RATE,
         "duration_seconds": (min(start + step, samples) - start) / RATE,
         "cue_ids": [], "reference_cue_count": 0, "reference_characters": 0}
        for ordinal, start in enumerate(range(0, samples, step), 1)
    ]


def full_reference(spans: list[dict[str, Any]], samples: int, film_id: str,
                   srt_hash: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reuse the corpus SRT parser, restoring current cleaned source text exactly."""
    bins = scoring_bins(samples, film_id)
    duration = samples / RATE
    selected = []
    seen = set()
    for source in spans:
        start, end = source["start"], source["end"]
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, end)):
            raise ValueError("Reference time must be finite")
        if not 0 <= start < end <= duration:
            raise ValueError("Full reference cue lies outside decoded source")
        identity = f"{film_id}-{source['id']}"
        if identity in seen:
            raise ValueError("Duplicate full reference cue identity")
        seen.add(identity)
        # prepare_round2 explicitly preserves current cleaned SRT, not new SDH exclusions.
        text = source["original_text"]
        if not text.strip():
            raise ValueError("Current cleaned SRT unexpectedly contains an empty cue")
        index = min(int(((start + end) / 2) // BIN_SECONDS), len(bins) - 1)
        bucket = bins[index]
        crossing = start < bucket["source_start_seconds"] or end > bucket["source_end_seconds"]
        span = dict(source, id=identity, text=text, removed_prefix_labels=[],
                    parser_removed_prefix_labels=source.get("removed_prefix_labels", []),
                    scene_id=bucket["id"], bin_id=bucket["id"], boundary_crossing=crossing,
                    partition="fullfilm_comparison_no_tuning", spoken_status="unreviewed",
                    acoustic_review=False, content_uncertainty="srt_not_acoustically_reviewed")
        selected.append(span)
        bucket["cue_ids"].append(identity)
        bucket["reference_cue_count"] += 1
        bucket["reference_characters"] += len(normalize(text).text)
    characters = len(normalize("".join(span["text"] for span in selected)).text)
    if characters != sum(bucket["reference_characters"] for bucket in bins):
        raise ValueError("Cross-cue normalization changes character provenance")
    return ({"schema_version": 1, "reference_kind": "srt_display", "spans": selected,
             "corpus_revision": REVISION, "source_reference_sha256": srt_hash,
             "scope": f"{film_id}-full", "time_coordinate": "source_media_seconds",
             "source_start_seconds": 0, "source_end_seconds": duration,
             "duration_seconds": duration, "acoustic_ground_truth": False,
             "reference_cue_count": len(selected), "reference_characters": characters,
             "reference_rule": "current cleaned SRT original_text; no additional exclusions",
             "reference_caveat": REFERENCE_CAVEAT, "bin_policy": BIN_POLICY}, bins)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = args.private_root.resolve()
    media_root = args.media_root.resolve()
    if root.is_relative_to(media_root) or root.is_relative_to(Path("D:/movie").resolve()):
        raise ValueError("Private output cannot be inside source media")
    if not root.is_relative_to(ROOT / ".local"):
        raise ValueError("Private corpus outputs must remain in project .local")
    plan_path = output_under(root.parent / "plan.json", root.parent)
    films, clips = [], []
    for spec in FILMS:
        base = media_root / spec["name"] / spec["name"]
        source_audio = Path(str(base) + ".jpn.flac")
        source_srt = Path(str(base) + ".jpn.srt")
        audio_hash = require_hash(source_audio, SOURCE_AUDIO_HASHES[spec["id"]])
        srt_hash = require_hash(source_srt, spec["srt_sha256"])
        probe = json.loads(subprocess.check_output(
            [str(args.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source_audio)],
            text=True, encoding="utf-8"))
        streams = [stream for stream in probe["streams"] if stream.get("codec_type") == "audio"]
        if len(streams) != 1 or streams[0].get("channels") != 2:
            raise ValueError("Frozen full-film preprocessing requires one stereo audio stream")
        stream = streams[0]
        if float(stream.get("start_time", 0)) != 0 or float(probe["format"].get("start_time", 0)) != 0:
            raise ValueError("Frozen complete film requires a zero source origin")
        clip_id = f"{spec['id']}-full"
        previous_audio = args.reuse_corpus.resolve() / "audio" / f"{clip_id}.wav"
        previous_descriptor = args.reuse_corpus.resolve() / "manifests" / f"{clip_id}-audio.json"
        if previous_audio.exists() or previous_descriptor.exists():
            info = verify_existing_audio(previous_audio, previous_descriptor, 0)
            if info is None or info.get("source_audio_sha256") != audio_hash:
                raise ValueError("Reusable full PCM lacks the frozen source identity")
            if PREPROCESSING not in info.get("command", []):
                raise ValueError("Reusable full PCM preprocessing differs")
            audio = previous_audio
            decode_kind = "verified_existing_complete_pcm"
        else:
            audio = output_under(root / "audio" / f"{clip_id}.wav", root)
            descriptor = root / "manifests" / f"{clip_id}-audio.json"
            info = verify_existing_audio(audio, descriptor, 0)
            if info is None:
                audio.parent.mkdir(parents=True, exist_ok=True)
                command = [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                           "-i", str(source_audio), "-map", "0:a:0", "-vn", "-sn", "-dn", "-af",
                           PREPROCESSING, "-c:a", "pcm_s16le", "-fflags", "+bitexact", "-flags:a", "+bitexact", str(audio)]
                subprocess.run(command, check=True)
                info = describe_audio(audio, 0)
                info.update(command=command, source_audio_sha256=audio_hash)
                write_immutable(descriptor, info)
            if info.get("source_audio_sha256") != audio_hash:
                raise ValueError("Prepared full PCM source identity differs")
            decode_kind = "private_complete_pcm"
        duration = info["duration_seconds"]
        if abs(duration - float(probe["format"]["duration"])) > 1 / RATE:
            raise ValueError("Complete PCM duration differs from source by over one output sample")
        reference, bins = full_reference(parse_srt(source_srt), info["samples"], spec["id"], srt_hash)
        reference_path = output_under(root / "references" / f"{clip_id}.json", root)
        write_immutable(reference_path, reference)
        clip = {"id": clip_id, "film": spec["id"], "audio": str(audio),
                "audio_sha256": info["wav_sha256"], "pcm_sha256": info["pcm_sha256"],
                "reference": str(reference_path), "reference_sha256": sha256(reference_path),
                "offset": 0, "source_start_seconds": 0, "source_end_seconds": duration,
                "inference_local_start_seconds": 0, "duration": duration, "samples": info["samples"],
                "source_audio": str(source_audio), "source_audio_sha256": audio_hash,
                "source_srt": str(source_srt), "source_srt_sha256": srt_hash,
                "reference_cue_count": reference["reference_cue_count"],
                "reference_characters": reference["reference_characters"]}
        film = dict(spec, clip=clip, full_pcm=info, decode_kind=decode_kind, scoring_bins=bins,
                    source_audio_bytes=source_audio.stat().st_size, source_srt_bytes=source_srt.stat().st_size,
                    source_rate=int(stream["sample_rate"]), source_channels=stream["channels"],
                    source_codec=stream["codec_name"], media_duration_seconds=float(probe["format"]["duration"]),
                    source_audio_sha256_after=require_hash(source_audio, audio_hash),
                    source_srt_sha256_after=require_hash(source_srt, srt_hash))
        write_immutable(root / "manifests" / f"{clip_id}-input.json", film)
        films.append(film)
        clips.append(clip)
    manifest = {"schema_version": 1, "corpus_revision": REVISION, "scope": "two complete films including credits",
                "sampled": False, "unseen_heldout": False, "offset": 0, "films": films, "clips": clips,
                "sample_seconds_total": sum(clip["duration"] for clip in clips),
                "preprocessing": PREPROCESSING + ", pcm_s16le; no denoising or source separation",
                "bin_seconds": BIN_SECONDS, "bin_policy": BIN_POLICY, "reference_caveat": REFERENCE_CAVEAT,
                "normalization": "kototoki_eval.schema.normalize: NFKC, remove Unicode P* punctuation and whitespace",
                "source_parser_sha256": sha256(ROOT / "experiments/corpus/prepare.py"),
                "corpus_builder_sha256": sha256(Path(__file__)),
                "ffprobe_path": str(args.ffprobe.resolve()), "ffprobe_sha256": sha256(args.ffprobe),
                "ffmpeg_path": str(args.ffmpeg.resolve()), "ffmpeg_sha256": sha256(args.ffmpeg),
                "ffmpeg_version": subprocess.check_output([str(args.ffmpeg), "-version"], text=True).splitlines()[0]}
    manifest_path = root / "manifests/corpus.json"
    write_immutable(manifest_path, manifest)
    write_immutable(root / "manifest.json", {"schema_version": 1, "corpus_revision": REVISION,
                    "clips": clips, "corpus_manifest_path": str(manifest_path), "corpus_manifest_sha256": sha256(manifest_path)})
    plan = {"schema_version": 1, "study_id": root.parent.name, "corpus_revision": REVISION,
            "comparison_scope": "complete HF II and III films; four fixed routes; no sample inference resets",
            "clips": clips, "corpus_manifest_path": str(manifest_path), "corpus_manifest_sha256": sha256(manifest_path),
            "bins_by_film": {film["id"]: film["scoring_bins"] for film in films},
            "bin_seconds": BIN_SECONDS, "bin_policy": BIN_POLICY, "reference_caveat": REFERENCE_CAVEAT,
            "sampled": False, "unseen_heldout": False, "total_audio_seconds": manifest["sample_seconds_total"]}
    write_immutable(plan_path, plan)
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, default=Path("D:/movie"))
    parser.add_argument("--private-root", type=Path, default=ROOT / ".local/fullfilm-comparison/fullfilm-v1/corpus")
    parser.add_argument("--reuse-corpus", type=Path, default=ROOT / ".local/round2/corpus")
    parser.add_argument("--ffmpeg", type=Path, default=Path("D:/bin/ffmpeg.exe"))
    parser.add_argument("--ffprobe", type=Path, default=Path("D:/bin/ffprobe.exe"))
    plan = prepare(parser.parse_args())
    print(json.dumps({"study_id": plan["study_id"], "total_audio_seconds": plan["total_audio_seconds"],
                      "films": [{"id": clip["id"], "samples": clip["samples"], "duration": clip["duration"],
                                 "reference_cue_count": clip["reference_cue_count"],
                                 "reference_characters": clip["reference_characters"]} for clip in plan["clips"]]}))


if __name__ == "__main__":
    main()
