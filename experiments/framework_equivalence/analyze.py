"""CPU-only evidence aggregation, with no private text printed."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from faster_whisper.feature_extractor import FeatureExtractor
import torch


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distance(reference: str, hypothesis: str) -> dict:
    # Unit-cost Levenshtein, deterministic substitution/deletion/insertion tie order.
    rows = [[(0, 0, j) for j in range(len(hypothesis)+1)]]
    for i, a in enumerate(reference, 1):
        row = [(0, i, 0)]
        previous = rows[-1]
        for j, b in enumerate(hypothesis, 1):
            s, d, ins = previous[j-1]
            sub = (s + (a != b), d, ins)
            s, d, ins = previous[j]
            delete = (s, d+1, ins)
            s, d, ins = row[-1]
            insert = (s, d, ins+1)
            row.append(min((sub, delete, insert), key=sum))
        rows = [row]
    s, d, ins = rows[-1][-1]
    return {"substitutions": s, "deletions": d, "insertions": ins, "distance": s+d+ins,
            "reference_characters": len(reference), "hypothesis_characters": len(hypothesis)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.output
    out = out.resolve()
    if not out.is_relative_to((root / ".local/framework-equivalence").resolve()):
        parser.error("Output must be within .local/framework-equivalence")
    if (out / "analysis.json").exists():
        parser.error("Analysis report already exists; use a new experimental identity")
    wx = json.loads((out / "wx.json").read_text(encoding="utf-8"))
    fw = json.loads((out / "fw.json").read_text(encoding="utf-8"))
    with np.load(out / "mel_filters.npz") as archive:
        bank = archive["mel_128"].copy()
    extractor = FeatureExtractor(feature_size=128)
    report = {"mel_bank": {"fw_dynamic_bit_equal": bool(np.array_equal(bank, extractor.mel_filters)),
                           "max_abs_diff": float(np.max(np.abs(bank-extractor.mel_filters)))}, "windows": []}
    for original, direct in zip(wx["results"], fw["results"]):
        clip = original["clip"]
        old_path = root / f'.local/results/r2-{clip["id"]}-w1-a01/result.json'
        mms_path = root / f'.local/results/jctc-mms-full-v2-{clip["id"]}-w1-mms/result.json'
        old = json.loads(old_path.read_text(encoding="utf-8"))
        mms = json.loads(mms_path.read_text(encoding="utf-8"))
        native = original["native"]["segments"]
        fields = lambda rows: [{k: s[k] for k in ("start", "end", "text")} for s in rows]
        expected = "".join(s["text"] for s in native)
        adapted = "".join(c["adapter"]["text"] for c in direct["chunks"])
        standard = "".join(s["text"] for s in direct["standard"])
        batch = "".join(s["text"] for s in direct["batch"])
        report["windows"].append({"id": clip["id"], "chunks": len(native),
            "old_w1_hash": sha(old_path), "old_w1_full_segment_equal": native == old["original_segments"],
            "old_w1_alignment_input_equal": fields(native) == fields(old["original_segments"]),
            "mms_hash": sha(mms_path), "mms_original_asr_equal": fields(native) == fields(mms["original_asr_segments"]),
            "source_offset_equal": clip["offset"] == old["offset_s"] == mms["offset_s"],
            "adapter_difference": distance(expected, adapted), "standard_difference": distance(expected, standard),
            "batch_difference": distance(expected, batch), "token_lengths": [c["wx_token_length"] for c in direct["chunks"]],
            "ct2_cap224_reached": any(c["wx_token_length"] >= 224 for c in direct["chunks"]),
            "adapter_total_s": sum(c["adapter_s"] for c in direct["chunks"]),
            "legacy_model_pcm_sha": old["input"]["pcm_sha256"] == clip["pcm_sha256"]})
    report["validation_source_sha256"] = {p.name: sha(p) for p in Path(__file__).parent.glob("*.py")}
    (out / "analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
