"""Generate an immutable, redistributable digital-silence preflight input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import wave

from prepare import describe_audio, write_immutable

RATE = 16000
SAMPLES = 160000
REVISION = "synthetic-digital-silence-v1-2026-10-04"


def prepare_silence(root: Path) -> dict:
    root = root.resolve()
    if not root.is_relative_to((Path(__file__).resolve().parents[2] / ".local").resolve()):
        raise ValueError("Synthetic private experiment output must remain under the project .local directory")
    audio = root / "audio/synthetic-silence-10s.wav"
    manifest_path = root / "manifests/corpus-synthetic-silence-10s.json"
    audio.parent.mkdir(parents=True, exist_ok=True)
    if audio.exists():
        if not manifest_path.exists():
            raise ValueError("Unmanifested synthetic audio exists; inspect before reuse")
        with wave.open(str(audio), "rb") as source:
            if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()) != (RATE, 1, 2, SAMPLES):
                raise ValueError("Existing synthetic silence has a different audio identity")
            if source.readframes(SAMPLES) != bytes(SAMPLES * 2):
                raise ValueError("Existing synthetic silence contains nonzero samples")
    else:
        with audio.open("xb") as stream:
            with wave.open(stream, "wb") as output:
                output.setparams((1, 2, RATE, SAMPLES, "NONE", "not compressed"))
                output.writeframes(bytes(SAMPLES * 2))
    reference = {"schema_version": 1, "reference_kind": "synthetic_digital_silence",
                 "reference_revision": REVISION, "duration_seconds": 10.0,
                 "time_coordinate": "source_media_seconds", "source_start_seconds": 0.0,
                 "spans": [], "provenance": "160000 generated zero-valued PCM16 samples; no private source media",
                 "expected_spoken_characters": 0, "silence_kind": "digital_zero_no_room_noise"}
    write_immutable(root / "references/synthetic-silence-10s.json", reference)
    manifest = {"schema_version": 1, "corpus_revision": REVISION,
                "input": describe_audio(audio, 0.0), "all_samples_zero": True,
                "provenance": "Python standard-library wave; 320000 zero-valued PCM bytes",
                "license": "Generated privacy-free synthetic data; redistributable",
                "expected_spoken_characters": 0,
                "aligner_policy": "No text input is intentional; skip normal forced alignment, do not supply invented text",
                "evaluation_policy": "CER undefined for reference N=0; preserve insertion counts and hallucination events/duration; no timing-success denominator",
                "limitation": "digital silence preflight does not establish background-music, real silence, room-noise, or full-film hallucination performance"}
    write_immutable(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, default=Path(".local"))
    args = parser.parse_args()
    print(json.dumps(prepare_silence(args.private_root)))


if __name__ == "__main__":
    main()
