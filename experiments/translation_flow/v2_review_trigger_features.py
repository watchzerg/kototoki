"""Pure inference-time F8 trigger features; no quality labels or runtime calls.

The caller must authenticate native acceptance and its hash before constructing
the narrow initial view. A status/hash assertion here is not native provenance
validation. Only the current source request and its accepted initial output are
accepted; source-review output and additional fields are rejected. Returned
flags are proxies, including lawful names/repetition, never fidelity findings.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any


VERSION = "f8-review-trigger-features-v1"
SEEDS = (20261008, 20261009, 20261010)
MARKERS = ("ない", "なかった", "なく", "ず", "もし", "なら", "かもしれない")
RULE_IDS = ("source_risk_literal_v1", "initial_output_suspicion_v1", "source_OR_output_v1")
_KANA = re.compile(r"[\u3040-\u30ff]")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value: Any) -> str:
    def plain(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, list):
            return [plain(child) for child in item]
        return item

    serialized = json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def contract() -> dict[str, Any]:
    """Return a fresh immutable-in-effect specification of the three fixed rules."""
    return {
        "version": VERSION,
        "rule_ids": list(RULE_IDS),
        "source_markers": list(MARKERS),
        "source_marker_normalization": "none_literal_substring",
        "source_copy_kana_regex": r"[\u3040-\u30ff]",
        "output_comparison_normalization": "strip_leading_and_trailing_whitespace_only",
        "adjacency": "consecutive_current_target_ids_not_readonly_or_future_outputs",
        "duplicate_output_rule": "identical_target_language_outputs_and_distinct_source_after_strip",
        "empty_accepted_translation": "invalid_input_not_an_invented_success",
        "missing_initial_decisions": "all_rules_null_ineligible_unknown",
        "features_are_quality_labels": False,
    }


def contract_sha256() -> str:
    return _digest(contract())


def _source(source: Mapping[str, Any]) -> tuple[str, list[str], dict[str, str]]:
    keys = {"id", "source_language", "target_language", "context", "translate_ids"}
    if not isinstance(source, Mapping) or set(source) != keys:
        raise ValueError("source request requires exactly the native five fields")
    if not isinstance(source["id"], str) or not source["id"].strip():
        raise ValueError("source request lacks batch identity")
    if source["source_language"] != "ja" or source["target_language"] != "zh-Hans":
        raise ValueError("trigger profile requires ja to zh-Hans")
    context = source["context"]
    targets = source["translate_ids"]
    if not isinstance(context, list) or not isinstance(targets, list) or not targets:
        raise ValueError("context and nonempty ordered target IDs are required")
    if any(not isinstance(uid, str) or not uid for uid in targets) or len(set(targets)) != len(targets):
        raise ValueError("target IDs must be unique nonempty strings")
    texts: dict[str, str] = {}
    for cue in context:
        if not isinstance(cue, Mapping) or set(cue) != {"id", "text"}:
            raise ValueError("source context accepts only id and text")
        uid, text = cue["id"], cue["text"]
        if not isinstance(uid, str) or not uid or uid in texts or not isinstance(text, str):
            raise ValueError("source context IDs must be unique and text must be a string")
        texts[uid] = text
    if [uid for uid in texts if uid in targets] != targets:
        raise ValueError("target membership/order differs from current visible source")
    return source["id"], targets.copy(), texts


def _initial(initial: Mapping[str, Any] | None, targets: list[str]) -> tuple[str, dict[str, str] | None]:
    if initial is None:
        return "missing", None
    if not isinstance(initial, Mapping) or set(initial) != {"stage", "status", "translations", "acceptance_sha256"}:
        raise ValueError("initial view requires only stage/status/translations/acceptance_sha256")
    if initial["stage"] != "translation":
        raise ValueError("only the initial translation stage is eligible, never source-review")
    status = initial["status"]
    if not isinstance(status, str):
        raise ValueError("initial status must be a string")
    if status in {"failed", "not_executed"}:
        if initial["translations"] is not None or initial["acceptance_sha256"] is not None:
            raise ValueError("unsuccessful initial view cannot carry fabricated acceptance")
        return status, None
    if status != "accepted":
        raise ValueError("initial status must be accepted, failed or not_executed")
    acceptance = initial["acceptance_sha256"]
    if not isinstance(acceptance, str) or _SHA.fullmatch(acceptance) is None:
        raise ValueError("accepted initial requires its native acceptance SHA256 binding")
    values = initial["translations"]
    if not isinstance(values, Mapping) or set(values) != set(targets):
        raise ValueError("accepted initial must cover exactly the current target IDs")
    if any(not isinstance(values[uid], str) or not values[uid].strip() for uid in targets):
        raise ValueError("accepted initial translation must be a nonempty string per target")
    return status, {uid: values[uid] for uid in targets}


def extract_features(
    source_request: Mapping[str, Any],
    accepted_initial: Mapping[str, Any] | None,
    *,
    generation_seed: int,
) -> dict[str, Any]:
    """Compute all three candidate gates without selecting one or judging quality.

Native caller validation must bind this initial view to the same batch/seed/raw
acceptance before any source-review call. Hashes in the returned snapshot bind
the exact inputs, but cannot independently prove that external provenance.
Missing/failed initial output retains a batch record with null gate decisions.
No source/candidate text is returned; the fixed literal markers are method data.
"""
    if type(generation_seed) is not int or generation_seed not in SEEDS:
        raise ValueError("generation seed must be one of the three preregistered seeds")
    bid, targets, texts = _source(source_request)
    status, values = _initial(accepted_initial, targets)
    hits = []
    for uid in targets:
        for marker in MARKERS:
            start = 0
            while (offset := texts[uid].find(marker, start)) >= 0:
                hits.append({"id": uid, "marker": marker, "start": offset, "end": offset + len(marker)})
                start = offset + 1  # Preserve overlapping literal occurrences.
    copies = []
    repeats = []
    if values is not None:
        copies = [uid for uid in targets if texts[uid].strip() == values[uid].strip() and _KANA.search(texts[uid])]
        for left, right in zip(targets, targets[1:]):
            if (values[left].strip() == values[right].strip()
                    and texts[left].strip() != texts[right].strip()):
                repeats.append({"left_id": left, "right_id": right})
    eligible = values is not None
    source_flag = bool(hits)
    output_flag = bool(copies or repeats) if eligible else None
    decisions = dict(zip(RULE_IDS, (source_flag, output_flag, source_flag or output_flag))) if eligible else {
        key: None for key in RULE_IDS
    }
    snapshot = {
        "schema": VERSION, "contract_sha256": contract_sha256(), "batch_id": bid,
        "generation_seed": generation_seed, "target_ids": targets,
        "source_request_canonical_sha256": _digest(source_request),
        "initial_view_canonical_sha256": _digest(accepted_initial),
        "native_acceptance_sha256": accepted_initial["acceptance_sha256"] if eligible else None,
        "initial_status": status, "eligible": eligible,
        "decision_status": "known" if eligible else "unknown",
        "source_literal_marker_presence": source_flag,
        "source_literal_marker_hits": hits,
        "source_copy_with_kana_ids": copies if eligible else None,
        "adjacent_duplicate_output_pairs": repeats if eligible else None,
        "rules": decisions, "quality_label": None,
    }
    snapshot["snapshot_sha256"] = _digest(snapshot)
    return snapshot


def validate_snapshot(
    snapshot: Mapping[str, Any],
    source_request: Mapping[str, Any],
    accepted_initial: Mapping[str, Any] | None,
) -> None:
    """Recompute against authenticated caller-supplied inputs; reject tampering."""
    if not isinstance(snapshot, Mapping) or "generation_seed" not in snapshot:
        raise ValueError("invalid feature snapshot")
    expected = extract_features(source_request, accepted_initial, generation_seed=snapshot["generation_seed"])
    if snapshot != expected:
        raise ValueError("feature snapshot differs from exact source/initial/contract binding")
