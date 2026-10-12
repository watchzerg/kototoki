"""File-derived state for a resuming agent: no in-progress flags to clean up."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .common import GPU_LOCK, atomic_write_json, read_json, utc_now
from .generate import scene_state
from .judge import PACKET_FILE

QUEUE_FILE = "queue.json"


def read_queue(root: Path) -> list[dict[str, Any]]:
    path = root / QUEUE_FILE
    return read_json(path)["jobs"] if path.is_file() else []


def add_job(root: Path, recipe: str, seed: int, scope: str) -> dict[str, Any]:
    jobs = read_queue(root)
    job = {"recipe": recipe, "seed": seed, "scope": scope}
    if job not in [{k: j[k] for k in ("recipe", "seed", "scope")} for j in jobs]:
        jobs.append(job | {"added_at_utc": utc_now()})
        atomic_write_json(root / QUEUE_FILE, {"jobs": jobs})
    return job


def run_state(run_dir: Path) -> dict[str, Any]:
    run = read_json(run_dir / "run.json")
    completion = run.get("completion", {})
    expected = run["scene_ids"]
    scenes = {s: scene_state(run_dir, s) for s in expected}
    sessions = run.get("sessions", [])
    state = {"run_id": run["run_id"], "pseudo": run.get("pseudo", {}).get("kind") if run.get("pseudo") else None,
             "scenes_total": len(expected), "scenes_complete": sum(v == "complete" for v in scenes.values()),
             "scenes_failed": sum(v == "failed" for v in scenes.values()),
             "scenes_missing": sum(v in (None, "infra_failed") for v in scenes.values()),
             "sessions": len(sessions), "resumed": run.get("resumed", False), "state": completion.get("state"),
             "last_infra_failure": next((s["infra_failure"] for s in reversed(sessions) if s.get("infra_failure")), None),
             "judge": {}}
    if state["scenes_missing"] == 0 and state["scenes_failed"] == 0:
        state["state"] = "complete"
    elif state["scenes_missing"] == 0:
        state["state"] = "finished_with_failures"
    elif state["scenes_complete"] or state["scenes_failed"]:
        state["state"] = "partial"
    for profile_dir in sorted((run_dir / "judge").glob("*")) if (run_dir / "judge").is_dir() else []:
        plan_path = profile_dir / "packets.json"
        if not plan_path.is_file():
            continue
        plan = read_json(plan_path)
        planned = {p["packet_id"] for p in plan["packets"]}
        done = {p.stem for p in profile_dir.glob("p*.json") if PACKET_FILE.fullmatch(p.name)}
        errors = {p.name.split(".")[0] for p in profile_dir.glob("*.error.json")}
        state["judge"][profile_dir.name] = {"planned": len(planned), "done": len(planned & done),
                                            "errors_pending": len(errors - done),
                                            "splits": sorted({p["split"] for p in plan["packets"]}),
                                            "undeliverable_windows": len(plan.get("undeliverable_window_ids", [])),
                                            "judge_lock": (profile_dir / ".lock").is_file()}
    return state


def _count(folder: Path, pattern: str) -> int:
    return len(list(folder.glob(pattern))) if folder.is_dir() else 0


def derive_status(root: Path, *, lock_path: Path = GPU_LOCK, alive: Callable[[Any, Any], bool] | None = None,
                  list_servers: Callable[[], list[int]] | None = None) -> dict[str, Any]:
    from .procs import list_llama_servers, process_created, process_matches
    alive = alive or process_matches
    list_servers = list_servers or list_llama_servers
    status: dict[str, Any] = {"root": str(root), "at_utc": utc_now()}
    freeze = root / "reference-v3/freeze.json"
    status["reference_v3"] = read_json(freeze)["counts"] if freeze.is_file() else None
    status["decision_policy_frozen"] = (root / "decision-policy-v3.json").is_file()
    locked = root / "locked-candidates.json"
    status["locked_candidates"] = [e.get("name") if isinstance(e, dict) else e
                                   for e in read_json(locked).get("recipes", [])] if locked.is_file() else None
    lock = None
    if lock_path.is_file():
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
            lock["pid_alive"] = alive(lock.get("pid"), lock.get("pid_created")) if isinstance(lock.get("pid"), int) else None
            if isinstance(lock.get("server_pid"), int):
                lock["server_alive"] = alive(lock["server_pid"], lock.get("server_created"))
        except ValueError:
            lock = {"unparseable": True}
    status["gpu_lock"] = lock
    owned = lock.get("server_pid") if lock and lock.get("pid_alive") else None
    status["orphan_llama_servers"] = [{"pid": pid, "created": process_created(pid)} for pid in list_servers() if pid != owned]
    blocked = root / "judge-blocked.json"
    status["judge_blocked"] = read_json(blocked) if blocked.is_file() else None
    status["judge_queue_files"] = _count(root / "judge-queue", "*.md")
    status["judge_inbox_files"] = _count(root / "judge-inbox", "p*.json")
    # Confirmation packets are counted only; their contents are never printed.
    status["confirmation_judge_queue_files"] = _count(root / "judge-queue-confirmation", "*.md")
    status["confirmation_judge_inbox_files"] = _count(root / "judge-inbox-confirmation", "p*.json")
    runs = [run_state(p) for p in sorted((root / "runs").glob("*")) if (p / "run.json").is_file()] if (root / "runs").is_dir() else []
    status["runs"] = runs
    by_id = {r["run_id"]: r for r in runs}
    queue = []
    for job in read_queue(root):
        run_id = f"{job['recipe']}__s{job['seed']}__{job['scope']}"
        queue.append(job | {"run_id": run_id, "state": by_id.get(run_id, {}).get("state", "not_started")})
    status["queue"] = queue
    status["next_actions"] = suggest(status)
    return status


def suggest(status: dict[str, Any]) -> list[str]:
    actions = []
    if status["reference_v3"] is None:
        actions.append("freeze-reference (reference-v3 not frozen)")
    lock = status["gpu_lock"]
    gpu_busy = bool(lock and lock.get("pid_alive"))
    if lock and lock.get("pid_alive") is False:
        actions.append(f"stale gpu.lock from dead pid {lock.get('pid')}: verify with Get-Process, then run-queue --break-stale-lock")
    if status.get("orphan_llama_servers"):
        pids = [o["pid"] for o in status["orphan_llama_servers"]]
        actions.append(f"llama-server pid(s) {pids} not owned by a live v3 process: inspect (Get-Process) before any "
                       "GPU work; do not kill processes you did not start")
    pending_jobs = [j for j in status["queue"] if j["state"] not in ("complete", "finished_with_failures")]
    if pending_jobs and not gpu_busy:
        actions.append(f"run-queue in background ({len(pending_jobs)} pending job(s))")
    elif gpu_busy:
        actions.append(f"GPU busy (pid {lock.get('pid')}, run {lock.get('run_id')}); do not start generation")
    if status["judge_blocked"]:
        actions.append("judge blocked (quota/login): do non-judge work or wait; rerun the same judge command later")
    if status["judge_inbox_files"]:
        actions.append("judge --backend ingest (inbox has results)")
    for run in status["runs"]:
        if run["state"] in ("complete", "finished_with_failures"):
            for profile, judge in run["judge"].items():
                if judge["done"] < judge["planned"] and not status["judge_blocked"]:
                    actions.append(f"judge --run {run['run_id']} (profile {profile}: {judge['done']}/{judge['planned']})")
            if not run["judge"] and not run["run_id"].endswith("__confirmation"):
                actions.append(f"judge --run {run['run_id']} --split screen-a (not yet judged)")
        elif run["state"] == "partial" and not gpu_busy:
            actions.append(f"resume generation of {run['run_id']} (run-queue or generate)")
    if not status["decision_policy_frozen"]:
        actions.append("calibrate (reference / synthetic / repeat), then write decision-policy-v3.json before any candidate compare")
    return actions
