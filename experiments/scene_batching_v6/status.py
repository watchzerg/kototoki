"""Offline status of the v6 root (files only; never starts or stops anything)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from experiments.translation_v3.common import GPU_LOCK, read_json
from experiments.translation_v3.judge import PACKET_FILE, profile_dir_name


def status(root: Path) -> dict[str, Any]:
    runs = {}
    for path in sorted((root / "runs").glob("*__s*__*")) if (root / "runs").is_dir() else []:
        if not (path / "run.json").is_file():
            continue
        run = read_json(path / "run.json")
        judge_dir = path / "judge" / profile_dir_name(0)
        plan = read_json(judge_dir / "packets.json") if (judge_dir / "packets.json").is_file() else {"packets": []}
        done = {p.stem for p in judge_dir.glob("p*.json") if PACKET_FILE.fullmatch(p.name)} if judge_dir.is_dir() else set()
        runs[path.name] = {"completion": run["completion"].get("state"), "copied": "copied_from" in run,
                           "wall_clock_seconds": run.get("wall_clock_seconds"),
                           "judge_packets_planned": len(plan["packets"]),
                           "judge_packets_done": len(done & {p["packet_id"] for p in plan["packets"]}),
                           "judge_errors": len(list(judge_dir.glob("*.error.json"))) if judge_dir.is_dir() else 0}
    subsets = sorted(p.stem for p in (root / "subsets").glob("*.json")) if (root / "subsets").is_dir() else []
    blocked = root / "judge-blocked.json"
    return {"root": str(root), "runs": runs, "subsets": subsets,
            "judge_blocked": read_json(blocked) if blocked.is_file() else None,
            "gpu_lock": read_json(GPU_LOCK) if GPU_LOCK.is_file() else None}
