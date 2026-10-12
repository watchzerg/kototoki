"""Compare a new private W0 result to the measured WX/MMS regression artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def compare(result: dict, wx: dict, mms: dict, features: list[str], vad_hash: str) -> dict:
    traces = result["asr_traces"]
    calls = wx["calls"]
    old_records = mms["experimental_alignment"]["records"]
    new_records = result["alignment_records"]
    identity = result["input"]
    checks = {
        "input_identity": all(identity.get(key) == mms["input"].get(key) for key in ("pcm_sha256", "file_sha256")),
        "source_offset": result["offset_s"] == mms["offset_s"],
        "chunks": result["chunks"] == wx["chunks"],
        "vad_scores": result["effective_parameters"]["vad"].get("scores_sha256") == vad_hash,
        "vad_frame_coordinates": result["effective_parameters"]["vad"].get("scores_window") == wx["scores_window"],
        "full_asr_segments": result["original_segments"] == wx["native"]["segments"],
        "mms_search_segments": result["original_segments"] == mms["native"]["align_search_segments"],
        "text": result["text"] == mms["text"],
        "full_units": result["units"] == mms["units"],
        "whisperx_not_imported": result["runtime_identity"]["whisperx_imported"] is False,
        "features": len(traces) == len(features) and all(t["feature_sha256"] == f for t, f in zip(traces, features)),
        "tokens": len(traces) == len(calls) and all(t["tokens"] == c["results"][0]["tokens"] for t, c in zip(traces, calls)),
        "prompts": len(traces) == len(calls) and all(t["prompt"] == c["prompts"][0] for t, c in zip(traces, calls)),
        "generation_kwargs": len(traces) == len(calls) and all(t["kwargs"] == c["kwargs"] for t, c in zip(traces, calls)),
    }
    for key in ("emission_sha256", "path_sha256", "tokens", "failure"):
        checks[f"ctc_{key}"] = (len(old_records) == len(new_records)
                                and all(a.get(key) == b.get(key) for a, b in zip(new_records, old_records)))
    preprocessing = mms["experimental_preprocessing"]["records"]
    checks["ctc_normalization"] = (len(new_records) == len(preprocessing) and all(
        all(new["normalization"].get(key) == old.get(key) for key in (
            "source_sample_start", "source_sample_end", "valid_samples", "padded_samples",
            "raw_float32_sha256", "normalized_float32_sha256"))
        for new, old in zip(new_records, preprocessing)))
    return {"all_equal": all(checks.values()), "checks": checks,
            "segments": len(traces), "characters": len(result["text"]),
            "timed_characters": sum(u["char_end"] - u["char_start"] for u in result["units"] if u["status"] == "ok"),
            "text_only_characters": sum(u["char_end"] - u["char_start"] for u in result["units"] if u["status"] != "ok"),
            "alignment_failures": sum(bool(r.get("failure")) for r in new_records),
            "stages": result["stages"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--mms-result", type=Path, required=True)
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    import numpy as np
    wx = next(r for r in load(args.reference_dir / "wx.json")["results"] if r["clip"]["id"] == args.clip_id)
    features = [hashlib.sha256(np.load(args.reference_dir / f"{args.clip_id}-mel-{i:02d}.npy").tobytes()).hexdigest()
                for i in range(len(wx["chunks"]))]
    vad_hash = hashlib.sha256(np.load(args.reference_dir / f"{args.clip_id}-vad.npy").tobytes()).hexdigest()
    report = compare(load(args.result), wx, load(args.mms_result), features, vad_hash)
    report["references"] = {"result": str(args.result.resolve()), "wx": str(args.reference_dir.resolve()),
                            "mms": str(args.mms_result.resolve())}
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    if not report["all_equal"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
