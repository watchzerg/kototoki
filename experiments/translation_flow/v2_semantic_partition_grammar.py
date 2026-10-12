"""Model-chosen semantic cuts through immutable native Unicode text.

The grammar graph tracks cue index, native codepoint position and whether the
current cue has nonblank text. It has O(cues * native codepoints) states, never
enumerates substrings, and cannot delete, rewrite or duplicate native text.
This module performs no inference. Engine grammar acceptance and actual semantic
correspondence require independent qualification; strict parsing is authoritative.
"""

from __future__ import annotations

import json
from typing import Any

from . import v2_semantic_structured as structured

PROTOCOL = "semantic-immutable-partition-state-grammar-v1"
PLANNING_PROTOCOL = "semantic-ordered-boundary-finite-whitespace-v1"
DEFAULT_MAX_STATES = 100_000
DEFAULT_MAX_GRAMMAR_BYTES = 16 * 1024 * 1024

# Syntax whitespace is bounded; whitespace inside native JSON strings is data.
_JSON_RULES = structured._JSON_RULES.replace(
    r"ws ::= [ \t\n\r]*", r"ws ::= [ \t\n\r]?")


class GrammarComplexityError(ValueError):
    """An explicit protective build limit was exceeded without truncating text."""

    def __init__(self, message: str, diagnostics: dict[str, Any]):
        super().__init__(message)
        self.diagnostics = diagnostics


def planning_required(window: dict[str, Any]) -> bool:
    return structured.planning_required(window)


def planning_prompt(window: dict[str, Any]) -> str:
    return structured.planning_prompt(window)


def planning_grammar(window: dict[str, Any]) -> str:
    """Retain semantic/evidence choices while removing syntax whitespace loops."""
    return structured.planning_grammar(window).replace(
        r"ws ::= [ \t\n\r]*", r"ws ::= [ \t\n\r]?")


def parse_planning(content: str | None, window: dict[str, Any]) -> dict[str, Any]:
    result = structured.parse_planning(content, window)
    provenance = result["planning_provenance"]
    provenance["base_protocol"] = provenance["protocol"]
    provenance["protocol"] = PLANNING_PROTOCOL
    provenance["planning_grammar_variant"] = "syntax-whitespace-zero-or-one-v1"
    return result


def parse_plan(content: str | None, window: dict[str, Any]) -> dict[str, Any]:
    return parse_planning(content, window)["semantic_plan"]


def native_prompt(window: dict[str, Any], plan: dict[str, Any]) -> str:
    return structured.native_prompt(window, plan)


def mapping_required(window: dict[str, Any], plan: dict[str, Any]) -> bool:
    return structured.mapping_required(window, plan)


def mapping_prompt(window: dict[str, Any], plan: dict[str, Any], native: dict[str, str]) -> str:
    return structured.mapping_prompt(window, plan, native)


def _terminal(value: str) -> str:
    """Encode a literal GBNF terminal, not a JSON value for model output."""
    return json.dumps(value, ensure_ascii=False)


def _positive_limit(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def build_mapping_grammar(window: dict[str, Any], plan: dict[str, Any], native: dict[str, str], *,
                          max_states: int = DEFAULT_MAX_STATES,
                          max_grammar_bytes: int = DEFAULT_MAX_GRAMMAR_BYTES) -> dict[str, Any]:
    """Return exact-partition GBNF plus measured build metadata.

    The positive configurable limits protect grammar construction, not evaluation
    sample size or a model token budget. Exceeding one raises explicitly, without
    text truncation, independent-cue fallback or a fake successful mapping.
    Impossible nonblank partitions allow only the explicit unresolved envelope.
    """
    _positive_limit(max_states, "max_states")
    _positive_limit(max_grammar_bytes, "max_grammar_bytes")
    validated, translations = structured._inputs(window, plan, native)
    if translations is None:
        raise ValueError("Native unit translations are required")
    units = [unit for unit in validated["units"] if len(unit["source_ids"]) > 1]
    if not units:
        raise ValueError("No multi-cue units: mapping grammar is unnecessary")
    for unit in units:
        if any(0xD800 <= ord(char) <= 0xDFFF for char in translations[unit["id"]]):
            raise ValueError("Native grammar text must contain only Unicode scalar values")
    infeasible = [unit["id"] for unit in units
                  if sum(bool(char.strip()) for char in translations[unit["id"]]) < len(unit["source_ids"])]
    diagnostics: dict[str, Any] = {
        "protocol": PROTOCOL, "state_count": 0, "multi_cue_unit_count": len(units),
        "native_codepoint_count": sum(len(translations[unit["id"]]) for unit in units),
        "mapping_feasible": not infeasible, "infeasible_unit_ids": infeasible,
        "json_syntax_whitespace": "zero-or-one-character-per-separator",
        "native_text_truncated": False, "unit_diagnostics": [],
        "max_states": max_states, "max_grammar_bytes": max_grammar_bytes,
        "real_engine_qualification_verified": False}
    lines: list[str] = []
    if infeasible:
        lines.append("root ::= unresolved")
    else:
        lines.append("root ::= mapping | unresolved")
        names = [f"unit{index}" for index in range(len(units))]
        lines.append('mapping ::= "{" ws ' + structured._terminal_json("segments")
                     + ' ws ":" ws "[" ws ' + ' ws "," ws '.join(names) + ' ws "]" ws "}" ws')
        lines.append('close ::= "\\\"" ws "}"')
        for unit_index, unit in enumerate(units):
            uid = unit["id"]
            text = translations[uid]
            count, length = len(unit["source_ids"]), len(text)
            suffix = [0] * (length + 1)
            for position in range(length - 1, -1, -1):
                suffix[position] = suffix[position + 1] + bool(text[position].strip())

            def viable(state: tuple[int, int, bool]) -> bool:
                cue, position, nonblank = state
                return suffix[position] >= count - cue - int(nonblank)

            def state_name(state: tuple[int, int, bool]) -> str:
                cue, position, nonblank = state
                return f"u{unit_index}-c{cue}-p{position}-b{int(nonblank)}"

            initial = (0, 0, False)
            pending = [initial]
            transitions: dict[tuple[int, int, bool], list[str]] = {}
            discovered = {initial}
            while pending:
                state = pending.pop()
                cue, position, nonblank = state
                alternatives = []
                next_states = []
                if position < length:
                    following = (cue, position + 1, nonblank or bool(text[position].strip()))
                    if viable(following):
                        alternatives.append(f"u{unit_index}-char{position} {state_name(following)}")
                        next_states.append(following)
                if nonblank and cue < count - 1:
                    following = (cue + 1, position, False)
                    if viable(following):
                        alternatives.append(f'close ws "," ws u{unit_index}-prefix{cue + 1} {state_name(following)}')
                        next_states.append(following)
                if cue == count - 1 and position == length and nonblank:
                    alternatives.append("close")
                if not alternatives:
                    raise AssertionError("Reachable partition grammar state has no valid continuation")
                transitions[state] = alternatives
                for following in next_states:
                    if following not in discovered:
                        discovered.add(following)
                        pending.append(following)
                if diagnostics["state_count"] + len(discovered) > max_states:
                    raise GrammarComplexityError(
                        f"Partition grammar exceeds max_states={max_states}; "
                        f"at least {diagnostics['state_count'] + len(discovered)} states; native text was not truncated",
                        {**diagnostics, "state_count": diagnostics["state_count"] + len(discovered),
                         "state_count_scope": "completed-units-plus-current-discovered-states",
                         "grammar_bytes": None, "exceeded_limit": "max_states"})
            diagnostics["state_count"] += len(transitions)
            diagnostics["unit_diagnostics"].append({"unit_id": uid, "cue_count": count,
                "native_codepoint_count": length, "state_count": len(transitions),
                "state_upper_bound": 2 * count * (length + 1)})
            lines.append(f"unit{unit_index} ::= u{unit_index}-prefix0 {state_name(initial)}")
            for cue, sid in enumerate(unit["source_ids"]):
                lines.append(f'u{unit_index}-prefix{cue} ::= "{{" ws '
                             + structured._terminal_json("unit_id") + ' ws ":" ws '
                             + structured._terminal_json(uid) + ' ws "," ws '
                             + structured._terminal_json("source_id") + ' ws ":" ws '
                             + structured._terminal_json(sid) + ' ws "," ws '
                             + structured._terminal_json("text") + ' ws ":" ws "\\\""')
            for position, char in enumerate(text):
                # JSON string content spelling, then GBNF string literal escaping.
                spelling = json.dumps(char, ensure_ascii=False)[1:-1]
                lines.append(f"u{unit_index}-char{position} ::= {_terminal(spelling)}")
            for state in sorted(transitions):
                lines.append(state_name(state) + " ::= " + " | ".join(transitions[state]))
    grammar = '\n'.join(lines) + '\n' + _JSON_RULES
    diagnostics["grammar_bytes"] = len(grammar.encode("utf-8"))
    diagnostics["production_count"] = sum("::=" in line for line in grammar.split('\n'))
    if diagnostics["grammar_bytes"] > max_grammar_bytes:
        raise GrammarComplexityError(
            f"Partition grammar has {diagnostics['grammar_bytes']} bytes, exceeds "
            f"max_grammar_bytes={max_grammar_bytes}; native text was not truncated",
            {**diagnostics, "exceeded_limit": "max_grammar_bytes"})
    return {"grammar": grammar, "diagnostics": diagnostics}


def mapping_grammar(window: dict[str, Any], plan: dict[str, Any], native: dict[str, str], *,
                    max_states: int = DEFAULT_MAX_STATES,
                    max_grammar_bytes: int = DEFAULT_MAX_GRAMMAR_BYTES) -> str:
    return build_mapping_grammar(window, plan, native, max_states=max_states,
                                 max_grammar_bytes=max_grammar_bytes)["grammar"]


def parse_mapping(content: str | None, window: dict[str, Any], plan: dict[str, Any],
                  native: dict[str, str]) -> dict[str, Any]:
    """Retain strict complete-unit validation and codepoint-derived offsets."""
    result = structured.parse_mapping(content, window, plan, native)
    result["mapping_provenance"]["base_protocol"] = structured.MAPPING_PROTOCOL
    result["mapping_provenance"]["protocol"] = PROTOCOL
    result["mapping_provenance"]["mapping_grammar_variant"] = "immutable-codepoint-state-graph-v1"
    result["mapping_provenance"]["json_syntax_whitespace"] = "zero-or-one-character-per-separator"
    return result
