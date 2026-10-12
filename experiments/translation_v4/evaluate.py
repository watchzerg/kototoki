"""v4 judging on tiled windows with the unchanged v3 judge profile ``claude-opus-5-5-mqm-v1``.

A run is judged per half (``dev-A`` / ``dev-B`` / ``confirm-A`` / ``confirm-B``) so the dev screening
can stop after half A. Packets are planned by the v3 fixed-seed shuffle inside each split, so every
run shares co-packing. Confirm runs require the locked recipe (v4 ``locked-candidates.json``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from experiments.translation_v3 import judge as J
from experiments.translation_v3.common import check_locked_candidate, read_json
from experiments.translation_v3.data import ReferenceWindow

from .reference import windows as tiled_windows


def run_set(run_dir: Path) -> str:
    return read_json(run_dir / "run.json")["scope"]


def reference_for(root: Path, set_name: str, only: set[str] | None = None) -> dict[str, ReferenceWindow]:
    windows = tiled_windows(root, set_name)
    return {k: w for k, w in windows.items() if only is None or k in only}


def contexts(root: Path, run_dir: Path, halves: list[str], replicate: int = 0,
             reference: dict[str, ReferenceWindow] | None = None) -> list[J.RunJudgeContext]:
    run = read_json(run_dir / "run.json")
    set_name = run["scope"]
    if set_name == "confirm" and not run.get("pseudo"):
        check_locked_candidate(root, run["recipe"]["name"], run.get("recipe_hash"))
    reference = reference if reference is not None else reference_for(root, set_name)
    result = []
    for half in halves:
        split = f"{set_name}-{half}"
        if any(w.meta.split == split and w.meta.scene_id in set(run["scene_ids"]) for w in reference.values()):
            result.append(J.prepare_run(run_dir, reference, split, replicate, root=root))
    if not result:
        raise ValueError(f"{run['run_id']}: no windows for halves {halves}")
    return result


def judge(root: Path, run_dir: Path, halves: list[str], *, replicate: int = 0, parallel: int = 3,
          max_packets: int | None = None, backend: Callable | None = None,
          reference: dict[str, ReferenceWindow] | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    backend = backend or J.CliBackend()
    summaries = []
    for ctx in contexts(root, run_dir, halves, replicate, reference):
        summary = J.judge_run(root, ctx, backend, max_packets=max_packets, parallel=parallel, log=log)
        summaries.append(summary)
        if summary["exit_code"] in (J.EXIT_BLOCKED, J.EXIT_LOCKED):
            break
    codes = [s["exit_code"] for s in summaries]
    exit_code = J.EXIT_BLOCKED if J.EXIT_BLOCKED in codes else J.EXIT_LOCKED if J.EXIT_LOCKED in codes else max(codes)
    return {"run_id": run_dir.name, "halves": halves, "parts": summaries, "exit_code": exit_code}
