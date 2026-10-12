"""Acquire only pinned Japanese CTC assets, independently of offline inference."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire_models import acquire

COMMON = ["README.md", "config.json", "preprocessor_config.json",
          "special_tokens_map.json", "tokenizer_config.json", "vocab.json"]
SPECS = {
    "reazon": ("japanese-wav2vec2-large-rs35kh",
        "reazon-research/japanese-wav2vec2-large-rs35kh",
        "2162c9edb97f362f7623d6b3a2e417458e879bca",
        COMMON + ["added_tokens.json", "model.safetensors"]),
    "mms": ("mms-1b-all", "facebook/mms-1b-all",
        "3d33597edbdaaba14a8e858e2c8caa76e3cec0cd",
        COMMON + ["model.safetensors", "adapter.jpn.safetensors"]),
    "hiragana": ("wav2vec2-xls-r-300m-japanese-hiragana",
        "slplab/wav2vec2-xls-r-300m-japanese-hiragana",
        "d3a14c42fb73398697e5815e548b16994773b636",
        COMMON + ["pytorch_model.bin"]),
}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=SPECS, action="append", required=True)
    args = parser.parse_args()
    for candidate in args.candidate:
        acquire(SPECS[candidate])
