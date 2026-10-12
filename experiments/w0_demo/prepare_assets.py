"""Copy two already-provisioned, hash-pinned assets; never download or import WhisperX."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from .run import ROOT, sha256, write_json

ASSETS = {
    "pytorch_model.bin": "0b5b3216d60a2d32fc086b47ea8c67589aaeb26b7e07fcbe620d6d0b83e209ea",
    "mel_filters.npz": "7450ae70723a5ef9d341e3cee628c7cb0177f36ce42c44b7ed2bf3325f0f6d4c",
}


def prepare(source: Path, destination: Path) -> None:
    notices = Path(__file__).with_name("THIRD_PARTY_NOTICES.txt")
    if not notices.is_file():
        raise FileNotFoundError("W0 source distribution must include THIRD_PARTY_NOTICES.txt")
    for name, digest in ASSETS.items():
        if sha256(source / name) != digest:
            raise ValueError(f"Asset differs from measured WhisperX 3.8.6 baseline: {name}")
    destination.mkdir(parents=True, exist_ok=False)
    for name in ASSETS:
        shutil.copy2(source / name, destination / name)
    shutil.copy2(notices, destination / "THIRD_PARTY_NOTICES.txt")
    write_json(destination / "manifest.json", {"source": str(source.resolve()), "sha256": ASSETS,
        "origin": "Already provisioned WhisperX 3.8.6 assets; runtime independent copy",
        "vad_license": "See docs/research/2026-10-04-runtime-inventory.md; independent checkpoint license provenance remains unverified"})


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision W0 assets from an existing local asset directory")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", type=Path, default=ROOT / ".local/models/w0-assets")
    args = parser.parse_args()
    prepare(args.source, args.destination)
    print(f"Verified local W0 assets: {args.destination}")


if __name__ == "__main__":
    main()
