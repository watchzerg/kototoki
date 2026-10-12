"""Execute one preregistered flow trial with end-to-end elapsed evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import time

from .cli import digest, read_json, read_rows, write_json
from .v2_prepare import prepare
from .v2_execute import execute, execute_source_preparation
from .v2_delivery import deliver


def _source_preparation_plan(card: dict, card_path: Path, manifest: Path,
                             scenes: Path, settings: dict) -> tuple[Path, dict] | None:
    """Bind the auxiliary plan to exactly the main frozen source selection."""
    spec = card.get("source_preparation")
    if spec is None:
        return None
    if (not isinstance(spec, dict) or set(spec) != {"plan", "sha256"}
            or not isinstance(spec["plan"], str) or not spec["plan"]
            or not isinstance(spec["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]) is None):
        raise ValueError("source_preparation requires exactly a frozen plan path and SHA256")
    path = Path(spec["plan"])
    path = path.resolve() if path.is_absolute() else (card_path.parent / path).resolve()
    if digest(path) != spec["sha256"]:
        raise ValueError("source preparation plan differs from preregistration")
    from .v2_source_preparation import load_plan, SESSION_SCHEMA
    plan, _ = load_plan(path)
    projection = settings.get("source_preparation_projection")
    if plan["schema"] == SESSION_SCHEMA:
        supported = ({"eligible-quoted-local-terms-v1"} if plan["mode"] == "terms" else
                     {"background-supported-scene-context-v1", "background-supported-source-only-control-v1"})
        if not isinstance(projection, str) or projection not in supported:
            raise ValueError("Versioned source preparation requires a compatible preregistered projection")
    elif projection is not None:
        raise ValueError("Legacy source preparation does not accept a new projection protocol")
    source = plan["source"]
    for key, expected in (("manifest", manifest), ("scenes", scenes)):
        artifact = Path(source[key])
        artifact = artifact.resolve() if artifact.is_absolute() else (path.parent / artifact).resolve()
        if artifact != expected.resolve() or source[key + "_sha256"] != card["source"][key + "_sha256"]:
            raise ValueError("source preparation source differs from trial source")
    if (plan["stage"] != settings.get("stage", "screening")
            or plan["settings"]["seed"] != settings.get("seed", 20261008)):
        raise ValueError("source preparation stage/seed differs from trial")
    split = settings["split"]
    windows = read_json(manifest)["windows"]
    selected = {w["scene_id"] for w in windows if w["split"] == split or (
        split == "screening" and w["split"] in ("screen-a", "screen-b"))}
    requested = settings.get("selected_scene_ids")
    if requested is not None:
        if not set(requested) <= selected:
            raise ValueError("requested scene absent from selected split")
        selected &= set(requested)
    ordered = [row.get("scene_id", row["id"]) for row in read_rows(scenes)
               if row.get("scene_id", row["id"]) in selected]
    if not ordered or len(ordered) != len(selected) or plan["scene_ids"] != ordered:
        raise ValueError("source preparation ordered scenes differ from trial selection")
    return path, plan


def _preparation_cost(output: Path) -> dict:
    """Sum scene dispatches once, independent of batches and scoring windows."""
    command = output / "command-completion.json"
    ledger = output / "runtime-run/translation/ledger.jsonl"
    rows = read_rows(ledger) if ledger.exists() else []
    attempts = [attempt for row in rows for attempt in row.get("attempts", [])]
    dispatched = [attempt for attempt in attempts if attempt.get("completion_dispatched") is True]
    result = {"command": {"path": str(command.resolve()), "sha256": digest(command)} if command.exists() else None,
              "ledger": {"path": str(ledger.resolve()), "sha256": digest(ledger)} if ledger.exists() else None,
              "scene_records": len(rows), "attempts": len(attempts), "translation_calls": len(dispatched),
              "estimated_tokens": sum(a["input_tokens"] + a["request"]["n_predict"] for a in dispatched),
              "cost_scope": "one auxiliary scene ledger per candidate/seed; command startup/hash/load/unload counted once; no batch/window duplication"}
    if command.exists():
        result["command_seconds"] = read_json(command)["command_seconds"]
    from .v2_source_preparation import TERMS_PROTOCOL
    proposals = [row["preparation"] for row in rows if row.get("status") == "prepared"
                 and row.get("protocol") == TERMS_PROTOCOL and isinstance(row.get("preparation"), dict)]
    counts = ("returned_count", "accepted_count", "declined_count")
    if proposals and all(type(p.get(key)) is int for p in proposals for key in counts):
        result["proposal_scene_records"] = len(proposals)
        result.update({key: sum(p[key] for p in proposals) for key in counts})
        if all(type(p.get("zero_eligible_glossary")) is bool for p in proposals):
            result["zero_effect_scene_records"] = sum(p["zero_eligible_glossary"] for p in proposals)
    return result


def trial(card_path: Path, output: Path) -> int:
    started = time.perf_counter()
    card = read_json(card_path)
    if card.get("schema") != "hy30-flow-trial-card-v2":
        raise ValueError("Expected a frozen v2 trial card")
    if "implementation_identity" in card:
        identities = card["implementation_identity"]
        if not isinstance(identities, list) or not identities:
            raise ValueError("implementation_identity requires a nonempty frozen artifact list")
        seen = set()
        for spec in identities:
            if (not isinstance(spec, dict) or set(spec) != {"path", "sha256"}
                    or not isinstance(spec["path"], str) or not spec["path"]
                    or not isinstance(spec["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]) is None):
                raise ValueError("implementation identity requires exact paths and SHA256 values")
            artifact = Path(spec["path"])
            artifact = artifact.resolve() if artifact.is_absolute() else (card_path.parent / artifact).resolve()
            if artifact in seen or digest(artifact) != spec["sha256"]:
                raise ValueError("implementation identity changed or repeats a path")
            seen.add(artifact)
    source = card["source"]
    manifest, scenes = Path(source["manifest"]), Path(source["scenes"])
    if digest(manifest) != source["manifest_sha256"] or digest(scenes) != source["scenes_sha256"]:
        raise ValueError("trial source differs from preregistration")
    settings = dict(card["prepare"])
    if any(key in settings for key in ("source_preparation_path", "source_preparation_sha256",
                                      "source_preparation_protocol", "source_preparation_schema", "protocol")):
        raise ValueError("trial preparation options must be produced by its frozen source preparation plan")
    if settings.get("stage", "screening") != "qualification":
        policy = card.get("decision_policy", {})
        if not policy or digest(Path(policy["path"])) != policy["sha256"]:
            raise ValueError("candidate screening needs the frozen pre-result decision policy")
    for name in ("token_counts_path", "measure_source_tokens"):
        if settings.get(name) is not None:
            settings[name] = Path(settings[name])
            artifacts = card.get("artifacts", {})
            expected = artifacts.get(name) if isinstance(artifacts, dict) else None
            if (not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None
                    or digest(settings[name]) != expected):
                raise ValueError(f"trial {name} lacks unchanged preregistered artifact SHA256")
    auxiliary = _source_preparation_plan(card, card_path, manifest, scenes, settings)
    if auxiliary is None and settings.get("source_preparation_projection") is not None:
        raise ValueError("Source preparation projection requires a frozen source preparation plan")
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "hy30-flow-trial-v2", "card_path": str(card_path.resolve()),
              "card_sha256": digest(card_path), "card": card,
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "code_sha256": digest(Path(__file__)), "status": "started", "phases": {},
              "timing_scope": "card validation, source preparation, managed command including full weight hash/load/inference/unload, complete export and mechanical checks; judge excluded"}
    write_json(output / "trial-start.json", report)
    phase = "source_preparation" if auxiliary else "preparation"
    phase_start = time.perf_counter()
    try:
        if auxiliary:
            plan_path, plan = auxiliary
            source_output = output / "source-preparation"
            report["source_preparation"] = {"mode": plan["mode"], "plan_path": str(plan_path),
                                             "plan_sha256": card["source_preparation"]["sha256"],
                                             "budgets": plan["budgets"], "scene_ids": plan["scene_ids"]}
            if "protocol" in plan:
                report["source_preparation"]["protocol"] = plan["protocol"]
                report["source_preparation"]["projection"] = settings["source_preparation_projection"]
            try:
                # Recheck registration immediately before the managed dispatch.
                _source_preparation_plan(card, card_path, manifest, scenes, settings)
                source_code = execute_source_preparation(plan_path, source_output)
                report["source_preparation"]["runtime_exit_code"] = source_code
            finally:
                report["source_preparation"]["cost"] = _preparation_cost(source_output)
            if source_code != 0:
                raise ValueError("source preparation failed; partial preparation cannot enter translation")
            artifact = source_output / "runtime-run/translation/preparation-options.json"
            artifact_sha256 = digest(artifact)
            from .v2_source_preparation import load_options
            options = load_options(artifact, artifact_sha256)
            if (options["session_plan_sha256"] != card["source_preparation"]["sha256"]
                    or options["mode"] != plan["mode"] or options["source"] != plan["source"]
                    or options["scene_ids"] != plan["scene_ids"] or options["settings"] != plan["settings"]
                    or options.get("stage") != plan["stage"]
                    or options.get("protocol") != plan.get("protocol")):
                raise ValueError("source preparation artifact differs from frozen trial plan")
            report["source_preparation"]["artifact"] = {"path": str(artifact.resolve()), "sha256": artifact_sha256}
            settings.update(source_preparation_path=artifact, source_preparation_sha256=artifact_sha256)
            report["phases"][phase] = time.perf_counter() - phase_start
            phase, phase_start = "preparation", time.perf_counter()
        prepare(manifest=manifest, scenes=scenes, output=output / "prepared", **settings)
        packed = read_json(output / "prepared/packed-mapping.json")
        expected_ids = packed.get("scene_ids")
        if (not isinstance(expected_ids, list) or not expected_ids
                or any(not isinstance(sid, str) or not sid for sid in expected_ids)
                or len(set(expected_ids)) != len(expected_ids)):
            raise ValueError("prepared mapping requires unique nonempty expected scene IDs")
        report["expected_scene_ids"] = expected_ids
        if auxiliary and expected_ids != auxiliary[1]["scene_ids"]:
            raise ValueError("packed scene selection differs from frozen source preparation")
        report["expected_scenes"] = len(expected_ids)
        report["phases"][phase] = time.perf_counter() - phase_start
        phase, phase_start = "managed_command", time.perf_counter()
        code = execute(output / "prepared", output / "execution")
        report["phases"][phase] = time.perf_counter() - phase_start
        report["runtime_exit_code"] = code
        phase, phase_start = "export", time.perf_counter()
        result = deliver(manifest, output / "prepared/packed-mapping.json",
                         output / "execution/runtime-run/translation" / settings["recipe_id"],
                         output / "delivery")
        exported = result.get("scenes")
        if (not isinstance(exported, list)
                or any(not isinstance(row, dict) or not isinstance(row.get("scene_id"), str)
                       or not isinstance(row.get("status"), str) for row in exported)):
            raise ValueError("export requires explicit scene IDs and completion statuses")
        actual_ids = [row["scene_id"] for row in exported]
        report["exported_scene_records"] = len(exported)
        report["missing_scene_ids"] = sorted(set(expected_ids) - set(actual_ids))
        report["unexpected_scene_ids"] = sorted(set(actual_ids) - set(expected_ids))
        report["duplicate_scene_ids"] = sorted({sid for sid in actual_ids if actual_ids.count(sid) > 1})
        report["complete_scenes"] = len({row["scene_id"] for row in exported
                                         if row["status"] == "complete" and row["scene_id"] in expected_ids})
        exact = not any(report[name] for name in ("missing_scene_ids", "unexpected_scene_ids", "duplicate_scene_ids"))
        report["status"] = "complete" if code == 0 and exact and report["complete_scenes"] == report["expected_scenes"] else "partial"
        report["phases"][phase] = time.perf_counter() - phase_start
        return 0 if report["status"] == "complete" else 1
    except BaseException as exc:
        report.update(status="failed", failed_phase=phase, error=f"{type(exc).__name__}: {exc}")
        report["phases"][phase] = time.perf_counter() - phase_start
        raise
    finally:
        report.update(total_flow_seconds=time.perf_counter() - started,
                      finished_at_utc=datetime.now(timezone.utc).isoformat())
        write_json(output / "trial-completion.json", report)


def main() -> int:
    parser = argparse.ArgumentParser(description="执行已登记的单配方，测量准备到SRT导出的完整耗时")
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return trial(args.card, args.output)


if __name__ == "__main__":
    sys.exit(main())
