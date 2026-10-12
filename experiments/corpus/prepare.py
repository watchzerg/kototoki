"""Freeze private chapter partitions and decode sample-exact evaluation inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import wave
from pathlib import Path
from typing import Any

REFERENCE_SHA = "2d31b51406dd33cfc3af300c9346280a31aac7b6c199208e87f1f92ce79ae583"
RATE = 16000
DEV_CHAPTERS = {1, 2, 5, 7, 17}
VALIDATION_CHAPTERS = {3, 14, 23}
BUFFER_SECONDS = 10
RULE_REVISION = "fatestay-chapters-v1-2026-10-04"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_immutable(path: Path, value: Any) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"Frozen artifact differs; use a new corpus revision: {path}")
        return
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def time_seconds(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 3)


def strip_reference_labels(text: str) -> tuple[str, list[str], list[str]]:
    """Remove only short leading SDH parentheses; retain ambiguous internals."""
    labels: list[str] = []
    flags: list[str] = []
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        while True:
            match = re.match(r"^[（(]([^()（）\n]{1,25})[）)]", stripped)
            if not match:
                break
            labels.append(match.group(0))
            stripped = stripped[match.end() :].lstrip()
        if re.search(r"[（(].+[）)]", stripped):
            flags.append("internal_parenthetical_unreviewed")
        if "♪" in stripped or "♬" in stripped:
            flags.append("song_marker_unreviewed")
        lines.append(stripped)
    return "\n".join(lines).strip(), labels, sorted(set(flags))


def parse_srt(path: Path) -> list[dict[str, Any]]:
    spans = []
    source = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    for block in re.split(r"\n\s*\n", source.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            raise ValueError("Unsupported SRT block structure")
        start, end = lines[1].split(" --> ")
        original = "\n".join(lines[2:])
        spoken, labels, flags = strip_reference_labels(original)
        spans.append({"id": f"cue-{int(lines[0]):04d}", "cue_id": int(lines[0]),
                      "start": time_seconds(start), "end": time_seconds(end),
                      "text": spoken, "original_text": original,
                      "removed_prefix_labels": labels, "flags": flags,
                      "spoken_status": "unreviewed" if spoken else "label_only_rule_excluded",
                      "acoustic_review": False})
    return spans


def output_under(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Output must remain under the explicit private root: {path}")
    return resolved


def reference_document(spans: list[dict[str, Any]], scope: str) -> dict[str, Any]:
    return {"schema_version": 1, "reference_kind": "srt_display",
            "reference_sha256": REFERENCE_SHA, "corpus_revision": RULE_REVISION,
            "scope": scope, "time_coordinate": "source_media_seconds",
            "acoustic_ground_truth": False, "uncertainty": "not acoustically reviewed",
            "spans": [span for span in spans if span["text"]]}


def freeze(args: argparse.Namespace) -> dict[str, Any]:
    root = args.private_root.resolve()
    if root.is_relative_to(Path("D:/movie").resolve()) or root.is_relative_to(args.media.parent.resolve()):
        raise ValueError("Private output root must not be inside the source media directory")
    if sha256(args.srt) != REFERENCE_SHA:
        raise ValueError("Source SRT does not match the accepted immutable baseline")
    probe = json.loads(args.probe.read_text(encoding="utf-8-sig"))
    streams = [s for s in probe["streams"] if s.get("codec_type") == "audio"
               and s.get("tags", {}).get("language") == "jpn"]
    if len(streams) != 1:
        raise ValueError("Exactly one explicitly Japanese audio stream is required")
    stream = streams[0]
    if float(stream.get("start_time", 0)) != 0 or float(probe["format"]["start_time"]) != 0:
        raise ValueError("Nonzero source origins require an explicit new time mapping")
    spans = parse_srt(args.srt)
    scenes = []
    for number, chapter in enumerate(probe["chapters"], 1):
        partition = "dev" if number in DEV_CHAPTERS else "validation" if number in VALIDATION_CHAPTERS else "heldout"
        begin = float(chapter["start_time"]) + BUFFER_SECONDS
        end = float(chapter["end_time"]) - BUFFER_SECONDS
        selected = [s for s in spans if s["start"] >= begin and s["end"] <= end]
        scene_id = f"chapter-{number:02d}"
        for span in selected:
            span["scene_id"] = scene_id
            span["partition"] = partition
        scenes.append({"id": scene_id, "chapter": number, "partition": partition,
                       "chapter_start": float(chapter["start_time"]),
                       "chapter_end": float(chapter["end_time"]),
                       "start": begin, "end": end,
                       "start_sample": round(begin * RATE), "end_sample": round(end * RATE),
                       "selected_cue_ids": [s["id"] for s in selected],
                       "cue_count": len(selected),
                       "scored_cue_count": sum(bool(s["text"]) for s in selected),
                       "reference_path": f"references/{scene_id}.json",
                       "audio_path": f"audio/{scene_id}.wav",
                       "scene_boundary_confidence": "container_chapter_proxy_unreviewed"})
    unassigned = [s for s in spans if "partition" not in s]
    for span in unassigned:
        span["partition"] = "boundary_buffer"
    ffmpeg_version = subprocess.check_output([str(args.ffmpeg), "-version"], text=True).splitlines()[0]
    manifest = {"schema_version": 1, "corpus_revision": RULE_REVISION,
                "frozen_before_candidate_results": True,
                "selection_basis": "container chapters and cue counts only; no candidate output or audio listening",
                "media_path": str(args.media.resolve()), "media_bytes": args.media.stat().st_size,
                "media_sha256": sha256(args.media),
                "reference_path": str(args.srt.resolve()), "reference_sha256": REFERENCE_SHA,
                "probe_sha256": sha256(args.probe), "audio_stream_index": stream["index"],
                "audio_codec": stream["codec_name"], "audio_language_tag": "jpn",
                "source_rate": int(stream["sample_rate"]), "source_channels": stream["channels"],
                "media_duration": float(probe["format"]["duration"]),
                "source_origin_seconds": 0.0, "stream_origin_seconds": 0.0,
                "output_rate": RATE, "output_channels": 1, "output_sample_format": "signed_16bit_little_endian",
                "preprocessing": "pan=mono|c0=0.5*c0+0.5*c1,aresample=16000",
                "ffmpeg_version": ffmpeg_version, "chapter_buffer_seconds": BUFFER_SECONDS,
                "reference_annotation_rule": "remove short leading parenthetical SDH labels per line; retain internal parentheses/song text; no listening",
                "boundary_policy": "cues wholly inside chapter interior are scored; all others stay in full-film diagnostic reference, never reassigned",
                "scene_warning": "chapters are independent container structure, not verified semantic scene boundaries; recurrence may cross chapters",
                "reference_count": len(spans), "buffer_cue_count": len(unassigned), "scenes": scenes}
    write_immutable(output_under(root / "manifests/corpus-freeze.json", root), manifest)
    for scene in scenes:
        selected = [s for s in spans if s.get("scene_id") == scene["id"]]
        write_immutable(output_under(root / scene["reference_path"], root), reference_document(selected, scene["id"]))
    write_immutable(output_under(root / "references/full.json", root), reference_document(spans, "full_film_diagnostic"))
    write_immutable(output_under(root / "references/annotations.json", root), {"corpus_revision": RULE_REVISION, "spans": spans})
    dev_spans = [span for span in spans if span["partition"] == "dev"]
    audit_spans = [dev_spans[round(i * (len(dev_spans) - 1) / 39)] for i in range(40)]
    audit = {"corpus_revision": RULE_REVISION, "selection": "40 evenly spaced development cue ordinals",
             "audit_kind": "automated structure only; no human listening or text correctness verification",
             "manual_acoustic_review": "pending", "independent_text_correctness": "unverified",
             "checks": [{"id": span["id"], "positive_duration": span["end"] > span["start"],
                         "within_media": 0 <= span["start"] < span["end"] <= manifest["media_duration"],
                         "has_spoken_text_after_rule": bool(span["text"]),
                         "prefix_labels_removed": len(span["removed_prefix_labels"]),
                         "flags": span["flags"]} for span in audit_spans]}
    write_immutable(output_under(root / "references/dev-text-audit.json", root), audit)
    reference_audit = {"corpus_revision": RULE_REVISION, "reference_count": len(spans),
                       "prefix_label_count": sum(len(s["removed_prefix_labels"]) for s in spans),
                       "label_only_count": sum(not s["text"] for s in spans),
                       "acoustic_ground_truth": False,
                       "chapter_edge_crossings": {scene["id"]: [s["id"] for s in spans
                           if s["start"] < scene["start"] < s["end"] or s["start"] < scene["end"] < s["end"]]
                           for scene in scenes},
                       "boundary_limitation": "chapter audio may contain truncated edge-cue speech omitted from wholly-contained SRT scoring; use full-film totals and flag chapter quality as approximate"}
    write_immutable(output_under(root / "manifests/corpus-reference-audit.json", root), reference_audit)
    smoke = [s for s in spans if s["start"] >= 10 and s["end"] <= 70]
    write_immutable(output_under(root / "references/dev-smoke.json", root), reference_document(smoke, "dev-smoke-10-70"))
    if sha256(args.srt) != REFERENCE_SHA:
        raise ValueError("Source SRT changed during corpus preparation")
    return manifest


def describe_audio(path: Path, source_start: float) -> dict[str, Any]:
    pcm_digest = hashlib.sha256()
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Decoded audio contract mismatch")
        frames = source.getnframes()
        while block := source.readframes(RATE * 60):
            pcm_digest.update(block)
    return {"path": str(path.resolve()), "wav_sha256": sha256(path),
            "pcm_sha256": pcm_digest.hexdigest(), "sample_rate": RATE, "channels": 1,
            "samples": frames, "duration_seconds": frames / RATE,
            "source_start_seconds": source_start,
            "source_end_seconds": source_start + frames / RATE,
            "time_mapping": "source_time = local_sample_index / 16000 + source_start_seconds"}


def decode_full(args: argparse.Namespace, manifest: dict[str, Any]) -> dict[str, Any]:
    target = output_under(args.private_root / "audio/fatestay-full.wav", args.private_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = args.private_root / "manifests/corpus-audio-full.json"
    if descriptor.exists():
        previous = json.loads(descriptor.read_text(encoding="utf-8"))
        if not target.exists() or sha256(target) != previous["wav_sha256"]:
            raise ValueError("Existing decoded audio differs from its manifest")
        return previous
    if target.exists():
        raise ValueError("Unmanifested full audio exists; inspect before removing or reusing")
    command = [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
               "-i", str(args.media), "-map", f"0:{manifest['audio_stream_index']}",
               "-vn", "-sn", "-dn", "-af", manifest["preprocessing"], "-c:a", "pcm_s16le",
               "-fflags", "+bitexact", "-flags:a", "+bitexact", str(target)]
    subprocess.run(command, check=True)
    result = describe_audio(target, 0)
    if abs(result["duration_seconds"] - manifest["media_duration"]) > 0.05:
        raise ValueError("Decoded duration differs from media by more than 50 ms; inspect origins")
    result["command"] = command
    result["corpus_revision"] = RULE_REVISION
    write_immutable(descriptor, result)
    return result


def crop(args: argparse.Namespace, name: str, start_sample: int, end_sample: int) -> dict[str, Any]:
    if not 0 <= start_sample < end_sample:
        raise ValueError("Crop must have a nonnegative start and positive sample length")
    target = output_under(args.private_root / f"audio/{name}.wav", args.private_root)
    descriptor = output_under(args.private_root / f"manifests/corpus-audio-{name}.json", args.private_root)
    if descriptor.exists():
        previous = json.loads(descriptor.read_text(encoding="utf-8"))
        if (previous["source_start_sample"], previous["source_end_sample"]) != (start_sample, end_sample):
            raise ValueError("Existing crop uses a different sample range; use a new identity")
        if sha256(target) != previous["wav_sha256"]:
            raise ValueError("Existing crop audio differs from its manifest")
        return previous
    if target.exists():
        raise ValueError("Unmanifested crop exists; inspect before removing or reusing")
    with wave.open(str(args.private_root / "audio/fatestay-full.wav"), "rb") as source:
        if end_sample > source.getnframes():
            raise ValueError("Crop lies beyond decoded full PCM")
        source.setpos(start_sample)
        with wave.open(str(target), "wb") as output:
            output.setparams((1, 2, RATE, end_sample - start_sample, "NONE", "not compressed"))
            remaining = end_sample - start_sample
            while remaining:
                count = min(remaining, RATE * 60)
                block = source.readframes(count)
                if len(block) != count * 2:
                    raise ValueError("Crop lies beyond decoded full PCM")
                output.writeframesraw(block)
                remaining -= count
    result = describe_audio(target, start_sample / RATE)
    result["source_pcm_path"] = str((args.private_root / "audio/fatestay-full.wav").resolve())
    result["source_start_sample"] = start_sample
    result["source_end_sample"] = end_sample
    result["corpus_revision"] = RULE_REVISION
    write_immutable(descriptor, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", type=Path, default=Path("D:/movie/FateStay/FateStay.mkv"))
    parser.add_argument("--srt", type=Path, default=Path("D:/movie/FateStay/FateStay-original-1.srt"))
    parser.add_argument("--probe", type=Path, default=Path(".local/manifests/media-probe.json"))
    parser.add_argument("--ffmpeg", type=Path, default=Path("D:/bin/ffmpeg.exe"))
    parser.add_argument("--private-root", type=Path, default=Path(".local"))
    parser.add_argument("--decode", action="store_true")
    parser.add_argument("--partition", choices=["dev", "validation", "heldout"], default="dev")
    args = parser.parse_args()
    manifest = freeze(args)
    print(json.dumps({"corpus_revision": RULE_REVISION, "reference_count": manifest["reference_count"],
                      "counts": {p: sum(s["cue_count"] for s in manifest["scenes"] if s["partition"] == p)
                                 for p in ["dev", "validation", "heldout"]},
                      "buffer_count": manifest["buffer_cue_count"]}))
    if args.decode:
        print(json.dumps({"decoded_full": decode_full(args, manifest)}))
        print(json.dumps({"smoke": crop(args, "fatestay-dev-smoke", 10 * RATE, 70 * RATE)}))
        for scene in manifest["scenes"]:
            if scene["partition"] == args.partition:
                print(json.dumps({"scene": scene["id"], "audio": crop(args, scene["id"], scene["start_sample"], scene["end_sample"])}))
    if sha256(args.srt) != REFERENCE_SHA:
        raise ValueError("Source SRT changed during audio preparation")


if __name__ == "__main__":
    main()
