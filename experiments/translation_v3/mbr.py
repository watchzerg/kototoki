"""Local candidate selection for multi-sample recipes (no network, no judge): chrF-based MBR.

chrF here: character n-grams (n = 1..4, whitespace removed), precision and recall averaged over n,
F1 (symmetric). MBR picks the candidate with the highest mean chrF against the other candidates.
Ties go to the lowest sample index, so selection is deterministic.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

MBR_VERSION = "chrf1-n4-mbr-v1"
SELECTORS = ("mbr-chrf-batch", "mbr-chrf-cue")
MAX_N = 4


def _ngrams(text: str) -> list[Counter]:
    chars = "".join(text.split())
    return [Counter(chars[i:i + n] for i in range(len(chars) - n + 1)) for n in range(1, MAX_N + 1)]


def chrf(hypothesis: str, reference: str) -> float:
    hyp, ref = _ngrams(hypothesis), _ngrams(reference)
    precisions, recalls = [], []
    for h, r in zip(hyp, ref):
        if not h and not r:
            continue
        overlap = sum((h & r).values())
        precisions.append(overlap / sum(h.values()) if h else 0.0)
        recalls.append(overlap / sum(r.values()) if r else 0.0)
    if not precisions:
        return 1.0 if hypothesis.strip() == reference.strip() else 0.0
    p, r = sum(precisions) / len(precisions), sum(recalls) / len(recalls)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def mbr_index(texts: list[str]) -> int:
    if len(texts) == 1:
        return 0
    scores = [sum(chrf(t, u) for j, u in enumerate(texts) if j != i) / (len(texts) - 1) for i, t in enumerate(texts)]
    best = max(scores)
    return scores.index(best)


def select(selector: str, samples: list[dict[str, str]], ids: list[str]) -> tuple[dict[str, str], Any]:
    """Return the selected translations for ``ids`` and a record of the choice."""
    if not samples:
        raise ValueError("No candidate samples to select from")
    if selector == "mbr-chrf-batch":
        index = mbr_index(["\n".join(sample[key] for key in ids) for sample in samples])
        return dict(samples[index]), {"batch": index}
    if selector == "mbr-chrf-cue":
        chosen = {key: mbr_index([sample[key] for sample in samples]) for key in ids}
        return {key: samples[chosen[key]][key] for key in ids}, {"cue": chosen}
    raise ValueError(f"Unknown selector {selector!r}; use {SELECTORS}")
