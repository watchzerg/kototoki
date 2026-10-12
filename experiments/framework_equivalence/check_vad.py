"""Compare independent postprocessing against the exact installed reference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from pyannote.core import SlidingWindow, SlidingWindowFeature

from vad import merge_scores


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output = args.output.resolve()
    if not args.output.is_relative_to((root / ".local/framework-equivalence").resolve()):
        parser.error("Output must be within .local/framework-equivalence")
    if (args.output / "vad-equivalence.json").exists():
        parser.error("Validation report already exists; use a new experimental identity")
    # Only the validation reference imports WX. The independent replica does not.
    from whisperx.vads.pyannote import Pyannote
    saved = json.loads((args.output / "wx.json").read_text(encoding="utf-8"))
    cases = []
    for item in saved["results"]:
        window = SlidingWindow(**item["scores_window"])
        scores = SlidingWindowFeature(np.load(args.output / (item["clip"]["id"] + "-vad.npy")), window)
        cases.append((item["clip"]["id"], scores))
    rng = np.random.default_rng(20261004)
    cases.extend([
        ("silent", SlidingWindowFeature(np.zeros((100, 1)), SlidingWindow(start=0, duration=.02, step=.01))),
        ("long-active-mincut", SlidingWindowFeature(np.full((7500, 1), .8), SlidingWindow(start=0, duration=.02, step=.01))),
        ("threshold-equality", SlidingWindowFeature(np.array([[.5], [.501], [.363], [.362], [.5], [.501], [.4], [.3]]), SlidingWindow(start=0, duration=.02, step=.01))),
        ("short-speech-and-gaps", SlidingWindowFeature(np.array([[0], [.8], [0], [.8], [0]], dtype=float), SlidingWindow(start=0, duration=.02, step=.01))),
    ])
    for index in range(40):
        cases.append((f"seeded-{index}", SlidingWindowFeature(rng.random((rng.integers(1, 8500), rng.integers(1, 4))), SlidingWindow(start=-.003, duration=.02, step=.01))))
    results = []
    for name, scores in cases:
        reference = Pyannote.merge_chunks(scores, 30, onset=.5, offset=.363)
        actual = merge_scores(scores)
        if actual != reference:
            raise AssertionError(name)
        results.append({"name": name, "equal": True, "chunks": len(actual),
                        "max_duration": max((c["end"]-c["start"] for c in actual), default=0)})
    report = {"cases": results, "all_equal": True, "random_seed": 20261004,
              "limitations": "Pinned default cut/merge only; checkpoint inference and future WX changes excluded"}
    (args.output / "vad-equivalence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"equal_cases": len(results)}))


if __name__ == "__main__":
    main()
