"""Calculate the parent's frozen development Pareto and role policy."""

import argparse
import math
from pathlib import Path
from typing import Any

from .build_development import ROOT, digest, read, write

GROUPS = {
    "W0": ("W0-native", "W0-no-context", "W0-no-context-temp0"),
    "W1": ("W1-native", "W1-W0-no-context", "W1-normalized-forced"),
    "Q0": ("Q0-native", "Q0-window30", "Q0-window120"),
    "Q1": ("Q1-native", "Q1-no-vad"),
    "X0": ("X0-Q0-window30-CTC", "X0-Q0-window30-normalized-forced"),
}


def axes(route: dict[str, Any]) -> tuple[float, ...]:
    summary = route["summary"]
    text, timing = summary["text"], summary["timing"]
    return (text["CER"], text["deletion_rate"], text["I"] / text["reference_characters"],
            -timing["boundary_complete_count"] / timing["denominator"], -timing["measurable_coverage"],
            *(-timing["success"][key]["lower"] for key in ("0.5", "2.0", "5.0")))


def dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a, b = axes(left), axes(right)
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def role_key(route: dict[str, Any], role: str) -> tuple[Any, ...]:
    text, timing = route["summary"]["text"], route["summary"]["timing"]
    success = timing["success"]
    component_count = 1 if route["route_id"].startswith("W0-") else 2
    if role == "timing":
        key = (-success["0.5"]["lower"], -success["2.0"]["lower"], text["deletion_rate"], text["CER"])
    else:
        key = (text["deletion_rate"], text["CER"], text["I"] / text["reference_characters"], -success["0.5"]["lower"])
    return (*key, component_count, route["configuration_id"])


def calculate(report: dict[str, Any]) -> dict[str, Any]:
    routes = {route["route_id"]: route for route in report["routes"]}
    if set(routes) != {name for group in GROUPS.values() for name in group}:
        raise ValueError("Role selection requires exactly the thirteen frozen development configurations")
    groups = {}
    for group, names in GROUPS.items():
        excluded = {}
        eligible = []
        for name in names:
            route = routes[name]
            if not route["summary"]["all_execution_verified"]:
                excluded[name] = "incomplete_or_unverified_execution"
            elif report["generation_stability_observation"][name]["stability_eligibility"] is False:
                excluded[name] = report["generation_stability_observation"][name]["reason"]
            else:
                eligible.append(route)
        pareto = [route for route in eligible if not any(dominates(other, route) for other in eligible)]
        choices = {}
        for role in (("timing",) if group == "X0" else ("timing", "content_preservation")):
            if not pareto:
                continue
            selected = min(pareto, key=lambda route: role_key(route, role))
            lower = selected["summary"]["timing"]["success"]["0.5"]["lower"]
            choices[role] = {"route_id": selected["route_id"], "configuration_id": selected["configuration_id"],
                             "timing_upper_can_overlap_selection": [route["route_id"] for route in pareto
                                if route != selected and route["summary"]["timing"]["success"]["0.5"]["upper"] >= lower]}
        groups[group] = {"excluded": excluded, "eligible": [route["route_id"] for route in eligible],
                         "pareto": [route["route_id"] for route in pareto], "role_choices": choices,
                         "validation_candidates": sorted({choice["route_id"] for choice in choices.values()})}
    strict = {name: {"observational_srt_timing_pass": route["summary"]["timing"]["success"]["0.5"]["success_count"] >= math.ceil(.95 * 195)
                    and route["summary"]["timing"]["success"]["2.0"]["success_count"] >= math.ceil(.99 * 195),
                    "acoustic_qualification": "unverified"} for name, route in routes.items()}
    return {"schema_version": 1, "status": "policy_calculation_for_parent_review_not_final_candidate_freeze",
            "groups": groups, "qualification": strict,
            "tie_break": "No independent repeated cost exists; component count then configuration_id used only after complete role-key ties",
            "limitation": "Role selection exposes tradeoffs and ambiguity; it does not establish acoustic qualification or production acceptance"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    if not snapshot.is_relative_to((ROOT / ".local/analysis/dev-comparison").resolve()):
        raise ValueError("Selection artifacts must remain inside private development analysis")
    report_path = snapshot / "main-report.json"
    policy = ROOT / "docs/testing/evaluation-config-v1.md"
    result = calculate(read(report_path))
    result.update(report_sha256=digest(report_path), policy_path=str(policy), policy_sha256=digest(policy))
    write(snapshot / "policy-role-calculation.json", result)
    print({key: value["role_choices"] for key, value in result["groups"].items()})


if __name__ == "__main__":
    main()
