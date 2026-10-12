"""CPU verification of byte equality and normalized text differences."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from adapter import features
from analyze import distance
from run import audio
from kototoki_eval.schema import normalize


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to((ROOT / ".local/framework-equivalence").resolve()):
        parser.error("Output must be within .local/framework-equivalence")
    target = out / "features-text-check.json"
    if target.exists():
        parser.error("Supplemental report already exists")
    wx = json.loads((out / "wx.json").read_text(encoding="utf-8"))
    fw = json.loads((out / "fw.json").read_text(encoding="utf-8"))
    with np.load(out / "mel_filters.npz") as asset:
        bank = torch.from_numpy(asset["mel_128"].copy())
    records = []
    for w, f in zip(wx["results"], fw["results"]):
        pcm = audio(Path(w["clip"]["audio"]))
        equal = []
        for index, chunk in enumerate(w["chunks"]):
            mel = features(pcm[int(chunk["start"]*16000):int(chunk["end"]*16000)], bank)
            expected = np.load(out / f'{w["clip"]["id"]}-mel-{index:02d}.npy')
            equal.append(mel.tobytes() == expected.tobytes())
        text = normalize("".join(s["text"] for s in w["native"]["segments"])).text
        standard = normalize("".join(s["text"] for s in f["standard"])).text
        batch = normalize("".join(s["text"] for s in f["batch"])).text
        records.append({"id": w["clip"]["id"], "feature_bytes_equal": equal,
                        "standard_normalized_equal_chunks": sum(normalize(a["text"]).text == normalize(b["adapter"]["text"]).text for a, b in zip(f["standard"], f["chunks"])),
                        "standard_normalized_difference": distance(text, standard),
                        "batch_normalized_difference": distance(text, batch)})
    target.write_text(json.dumps({"records": records, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2), encoding="utf-8")
    print(target.read_text())


if __name__ == "__main__":
    main()
