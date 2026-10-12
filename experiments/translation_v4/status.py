"""File-derived v4 state for a resuming agent (read-only; confirm contents are only counted)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.translation_v3 import status as S3
from experiments.translation_v3.common import read_json, utc_now

from .common import POLICY_FILE, SETS, evaluation_dir, set_dir


def derive_status(root: Path) -> dict[str, Any]:
    base = S3.derive_status(root)
    status: dict[str, Any] = {"root": str(root), "at_utc": utc_now(), "sets": {}}
    for name in SETS:
        manifest = set_dir(root, name) / "manifest.json"
        review_dir = evaluation_dir(root, name) / "reference-review"
        freeze = evaluation_dir(root, name) / "reference" / "freeze.json"
        info = read_json(manifest) if manifest.is_file() else None
        status["sets"][name] = {
            "built": info is not None, "scenes": info and info["scenes"], "cues": info and info["cues"],
            "reviewed_scenes": len([p for p in review_dir.glob("*.json") if not p.name.endswith(".error.json")])
            if review_dir.is_dir() else 0,
            "review_errors": len(list(review_dir.glob("*.error.json"))) if review_dir.is_dir() else 0,
            "reference_frozen": freeze.is_file(),
            "reference_counts": read_json(freeze)["counts"] if freeze.is_file() and name == "dev" else None}
    status["decision_policy_frozen"] = (root / POLICY_FILE).is_file()
    status["locked_candidates"] = base["locked_candidates"]
    for key in ("gpu_lock", "orphan_llama_servers", "judge_blocked", "queue"):
        status[key] = base[key]
    status["runs"] = [{k: r[k] for k in ("run_id", "state", "scenes_complete", "scenes_failed", "scenes_missing",
                                         "resumed", "judge")} for r in base["runs"]]
    status["next_actions"] = suggest(status, base)
    return status


def suggest(status: dict[str, Any], base: dict[str, Any]) -> list[str]:
    actions = []
    lock = status["gpu_lock"]
    gpu_busy = bool(lock and lock.get("pid_alive"))
    if lock and lock.get("pid_alive") is False:
        actions.append(f"stale gpu.lock (dead pid {lock.get('pid')}): verify with Get-Process, then run-queue --break-stale-lock")
    if status["orphan_llama_servers"]:
        actions.append("llama-server not owned by a live v3/v4 process: inspect before GPU work; never kill foreign processes")
    pending = [j for j in status["queue"] if j["state"] not in ("complete", "finished_with_failures")]
    if gpu_busy:
        actions.append(f"GPU busy (run {lock.get('run_id')}); do not start generation")
    elif pending:
        actions.append(f"run-queue in background ({len(pending)} pending job(s))")
    if status["judge_blocked"]:
        actions.append("Claude blocked (exit 75): do non-judge work or stop; rerun the same judge/review command later")
    for name, info in status["sets"].items():
        if info["built"] and info["reviewed_scenes"] < info["scenes"]:
            actions.append(f"review --set {name} ({info['reviewed_scenes']}/{info['scenes']} scenes)")
        elif info["built"] and not info["reference_frozen"]:
            actions.append(f"freeze-reference --set {name}")
    for run in status["runs"]:
        for profile, judge in run["judge"].items():
            if judge["done"] < judge["planned"] and not status["judge_blocked"]:
                actions.append(f"judge --run {run['run_id']} ({profile}: {judge['done']}/{judge['planned']})")
    if not status["decision_policy_frozen"]:
        actions.append(f"calibrate, then freeze {POLICY_FILE} before any candidate compare")
    return actions
