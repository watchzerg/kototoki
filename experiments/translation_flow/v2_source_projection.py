"""Explicit v3 source-preparation projections shared by packing and dispatch."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from experiments.translation_demo import adapters
from .v2_scene_card import project_scene_card
from .v2_source_proposals import project_terms


TERMS = "eligible-quoted-local-terms-v1"
SCENE_CARD = "background-supported-scene-context-v1"
SOURCE_CONTROL = "background-supported-source-only-control-v1"
PROJECTIONS = (TERMS, SCENE_CARD, SOURCE_CONTROL)


def validate_projection_mode(mode: str, protocol: str, projection: str) -> None:
    expected = {"terms": ("eligibility-filtered-proposals-v1", (TERMS,)),
                "background": ("quoted-background-with-uncertainty-v1", (SCENE_CARD, SOURCE_CONTROL))}
    if mode not in expected or protocol != expected[mode][0] or projection not in expected[mode][1]:
        raise ValueError("Explicit source preparation protocol/projection/mode mismatch")


def project(mode: str, protocol: str, projection: str, preparation: dict[str, Any],
            original_window: dict[str, Any]) -> dict[str, Any]:
    """Return actual input, quoted options and complete injection/visibility audit."""
    validate_projection_mode(mode, protocol, projection)
    adapters.validate_window(original_window)
    if projection == TERMS:
        card = project_terms(preparation, original_window)
        context_ids = [cue["id"] for cue in original_window["context"]]
        options = {"quoted_terms": card}
        visibility = {"projection": projection, "original_local_context_ids": context_ids,
                      "actual_context_ids": context_ids, "new_readonly_ids": [],
                      "injected_items": card["injected_count"],
                      "uncertain_injected_items": sum(row["uncertain"] for row in card["terms"]),
                      "zero_effective_injection": card["zero_effective_injection"],
                      "proposal_counts": {name: card[name + "_proposal_count"] for name in ("returned", "accepted", "declined")},
                      "preparation_record_sha256": card["preparation_record_sha256"],
                      "source_scene_sha256": card["source_scene_sha256"],
                      "cost_attribution": card["cost_attribution"]}
        window = deepcopy(original_window)
    else:
        result = project_scene_card(preparation, original_window)
        window, card = result["window"], result["scene_card"]
        options = {"scene_card": card} if projection == SCENE_CARD else {}
        count = len(card["background"]) if projection == SCENE_CARD else 0
        visibility = {"projection": projection,
                      **{name: deepcopy(card[name]) for name in (
                          "original_local_context_ids", "actual_context_ids", "new_readonly_ids",
                          "broader_before_ids", "broader_after_ids", "full_scene_source_hash",
                          "source_preparation_record_sha256", "cost_attribution", "full_scene_cue_count", "full_scene_visible")},
                      "prepared_background_items": len(card["background"]),
                      "injected_items": count,
                      "uncertain_injected_items": sum(row["uncertain"] for row in card["background"]) if count else 0,
                      "zero_effective_injection": count == 0,
                      "summary_rendered": projection == SCENE_CARD,
                      "information_scope": "whole-scene preparation; local source plus selected exact supporting source cues",
                      "control_scope": "whole card effect including repeated quotes and instructions, not pure summary effect"}
    visibility["actual_source_cue_count"] = len(window["context"])
    visibility["source_text_token_scope"] = "exact main prompt token count is measured by main runtime; no estimate or silent truncation"
    return {"window": window, "options": options, "visibility": visibility}
