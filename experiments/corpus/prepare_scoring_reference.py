"""Derive a versioned, source-only fansub-metadata exclusion overlay."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from prepare import REFERENCE_SHA, sha256, write_immutable

REVISION = "fatestay-srt-scoring-v2-2026-10-04"
EXCLUSIONS = {
    "cue-0001": "Chinese fansub joint-production notice",
    "cue-0002": "Chinese learning-only and commercial-use disclaimer",
    "cue-0003": "Chinese translation/proofreading credits",
    "cue-0006": "Chinese translation/postproduction credits",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, default=Path(".local"))
    parser.add_argument("--srt", type=Path, default=Path("D:/movie/FateStay/FateStay-original-1.srt"))
    args = parser.parse_args()
    if sha256(args.srt) != REFERENCE_SHA:
        raise ValueError("Source reference differs from the accepted baseline")
    root = args.private_root.resolve()
    if root.is_relative_to(Path("D:/movie").resolve()):
        raise ValueError("Derived reference must remain outside source media")
    annotations = json.loads((root / "references/annotations.json").read_text(encoding="utf-8"))
    spans = annotations["spans"]
    metadata_candidates = []
    for span in spans:
        text = span["original_text"]
        has_kana = bool(re.search(r"[\u3040-\u30ff]", text))
        terms = [term for term in ["本字幕", "翻译", "校对", "商业", "学习", "后期"] if term in text]
        if not has_kana and terms:
            metadata_candidates.append({"id": span["id"], "known_exclusion": span["id"] in EXCLUSIONS,
                                        "term_count": len(terms), "acoustic_review": False})
    by_id = {span["id"]: span for span in spans}
    for cue_id in EXCLUSIONS:
        if cue_id not in by_id or re.search(r"[\u3040-\u30ff]", by_id[cue_id]["original_text"]):
            raise ValueError("Source-only metadata exclusion no longer matches reference identity")
    audit = {"schema_version": 1, "reference_revision": REVISION,
             "source_reference_sha256": REFERENCE_SHA,
             "source_inspection_basis": "explicit fansub production/disclaimer/personnel credits identified from source before final screening-rule freeze",
             "exclusions": [{"id": cue_id, "reason": reason,
                             "start": by_id[cue_id]["start"], "end": by_id[cue_id]["end"],
                             "text_characters": len(by_id[cue_id]["text"])} for cue_id, reason in EXCLUSIONS.items()],
             "structural_metadata_candidates": metadata_candidates,
             "full_source_cue_count": len(spans), "derived_spoken_cue_count": len(spans) - len(EXCLUSIONS),
             "no_acoustic_ground_truth": True,
             "raw_v1_preserved": True, "input_partitions_unchanged": True,
             "early_scores_status": "superseded: v1 included clearly nonspoken metadata",
             "additional_unknown_candidates": [item["id"] for item in metadata_candidates if not item["known_exclusion"]]}
    write_immutable(root / "manifests/corpus-reference-scoring-v2.json", audit)
    source_files = [root / "references/full.json", root / "references/dev-smoke.json"]
    source_files.extend(sorted((root / "references").glob("chapter-*.json")))
    for source in source_files:
        document = json.loads(source.read_text(encoding="utf-8"))
        document["reference_revision"] = REVISION
        document["supersedes_scoring_revision"] = "raw-v1"
        document["excluded_source_cue_ids"] = [span["id"] for span in document["spans"] if span["id"] in EXCLUSIONS]
        document["spans"] = [span for span in document["spans"] if span["id"] not in EXCLUSIONS]
        write_immutable(root / "references/scoring-v2" / source.name, document)
    if sha256(args.srt) != REFERENCE_SHA:
        raise ValueError("Source reference changed while deriving scoring overlay")
    print(json.dumps({"reference_revision": REVISION, "excluded_ids": list(EXCLUSIONS),
                      "structural_metadata_candidate_count": len(metadata_candidates),
                      "additional_unknown_ids": audit["additional_unknown_candidates"],
                      "scored_full_cues": audit["derived_spoken_cue_count"]}))


if __name__ == "__main__":
    main()
