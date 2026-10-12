"""Extract held-out chapter assets from frozen PCM without reading reference text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import wave

from prepare import REFERENCE_SHA, crop, sha256, write_immutable

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, default=ROOT / ".local")
    args = parser.parse_args()
    root = args.private_root.resolve()
    if not root.is_relative_to((ROOT / ".local").resolve()):
        parser.error("Output must remain below the project .local directory")
    frozen_path = root / "manifests/corpus-freeze.json"
    frozen_hash = sha256(frozen_path)
    frozen = load(frozen_path)
    full_manifest_path = root / "manifests/corpus-audio-full.json"
    full_manifest_hash = sha256(full_manifest_path)
    full = load(full_manifest_path)
    source_media = Path(frozen["media_path"])
    source_reference = Path(frozen["reference_path"])
    full_audio = Path(full["path"])
    before = {"media": sha256(source_media), "reference": sha256(source_reference), "full_wav": sha256(full_audio)}
    if before["media"] != frozen["media_sha256"] or before["reference"] != REFERENCE_SHA or before["full_wav"] != full["wav_sha256"]:
        raise ValueError("Source/frozen PCM identity mismatch before held-out preparation")
    scenes = sorted([scene for scene in frozen["scenes"] if scene["partition"] == "heldout"], key=lambda scene: scene["chapter"])
    rows = []
    with wave.open(str(full_audio), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()) != (16000, 1, 2, full["samples"]):
            raise ValueError("Full PCM audio contract changed")
        for scene in scenes:
            descriptor = crop(args, scene["id"], scene["start_sample"], scene["end_sample"])
            source.setpos(scene["start_sample"])
            pcm = source.readframes(scene["end_sample"] - scene["start_sample"])
            if hashlib.sha256(pcm).hexdigest() != descriptor["pcm_sha256"]:
                raise ValueError("Extracted held-out PCM does not match the exact full-WAV sample slice")
            if len(pcm) // 2 != descriptor["samples"]:
                raise ValueError("Extracted held-out sample count differs from frozen range")
            rows.append({"scene_id": scene["id"], "chapter": scene["chapter"],
                         "partition": "heldout", "start_seconds": scene["start_sample"] / 16000,
                         "end_seconds": scene["end_sample"] / 16000,
                         "duration_seconds": descriptor["samples"] / 16000,
                         "start_sample": scene["start_sample"], "end_sample": scene["end_sample"],
                         "samples": descriptor["samples"], "cue_count_from_frozen_manifest": scene["cue_count"],
                         "audio_path": descriptor["path"], "wav_sha256": descriptor["wav_sha256"],
                         "pcm_sha256": descriptor["pcm_sha256"], "exact_full_pcm_slice_verified": True,
                         "audio_manifest_path": str((root / f"manifests/corpus-audio-{scene['id']}.json").resolve()),
                         "audio_manifest_sha256": sha256(root / f"manifests/corpus-audio-{scene['id']}.json")})
    after = {"media": sha256(source_media), "reference": sha256(source_reference), "full_wav": sha256(full_audio)}
    if before != after or sha256(frozen_path) != frozen_hash or sha256(full_manifest_path) != full_manifest_hash:
        raise ValueError("Source or frozen manifests changed during held-out preparation")
    manifest = {"schema_version": 1, "corpus_revision": frozen["corpus_revision"],
                "preparation_only": True, "gpu_used": False, "model_inference_executed": False,
                "audio_listening_performed": False, "reference_text_read_or_analyzed": False,
                "split_and_buffers_unchanged": True, "source_hashes_before": before, "source_hashes_after": after,
                "frozen_manifest_sha256": frozen_hash, "full_audio_manifest_sha256": full_manifest_hash,
                "source_time_mapping": "source_time = local_sample_index / 16000 + chapter.start_seconds",
                "full_continuous_audio": {"path": str(full_audio), "source_start_seconds": full["source_start_seconds"],
                                          "duration_seconds": full["duration_seconds"], "samples": full["samples"],
                                          "wav_sha256": full["wav_sha256"], "pcm_sha256": full["pcm_sha256"]},
                "chapters": rows, "total_chapter_duration_seconds": sum(row["samples"] for row in rows) / 16000,
                "total_chapter_samples": sum(row["samples"] for row in rows),
                "cue_count_from_frozen_manifest": sum(row["cue_count_from_frozen_manifest"] for row in rows)}
    write_immutable(root / "manifests/corpus-heldout-preparation.json", manifest)
    print(json.dumps({"manifest": str((root / "manifests/corpus-heldout-preparation.json").resolve()),
                      "source_hashes_unchanged": True, "count": len(rows),
                      "total_seconds": manifest["total_chapter_duration_seconds"],
                      "ordered_chapters": [{key: row[key] for key in ["scene_id", "start_seconds", "duration_seconds", "samples"]}
                                           for row in rows]}))


if __name__ == "__main__":
    main()
