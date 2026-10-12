"""Time the complete managed command, including initial asset hashing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from .cli import digest, read_json, write_json


def execute(prepared: Path, output: Path, *, port: int = 8080) -> int:
    plan = prepared / "session-plan.json"
    frozen = read_json(prepared / "preparation.json")
    if digest(plan) != frozen["session_plan_sha256"] or digest(prepared / "packed-mapping.json") != frozen["mapping_sha256"]:
        raise ValueError("prepared identities changed")
    return _managed_command(plan, output, worker="experiments.translation_flow.v2_worker",
                            port=port, prepared=prepared)


def execute_source_preparation(plan: Path, output: Path, *, port: int = 8080) -> int:
    """Run preparation in its own fresh managed model session, charging startup once."""
    from .v2_source_preparation import load_plan
    load_plan(plan)
    return _managed_command(plan, output, worker="experiments.translation_flow.v2_source_preparation",
                            port=port)


def _managed_command(plan: Path, output: Path, *, worker: str, port: int,
                     prepared: Path | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-B", "-X", "utf8", "-m", "experiments.translation_demo_runtime",
               "--candidate", "hy-mt2-30b-a3b-apex-i-compact", "--engine",
               str(root / ".local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe"),
               "--engine-identity", str(root / ".local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json"),
               "--layers", "99", "--context-size", "8192", "--threads", "8", "--threads-batch", "8",
               "--session-worker", worker, "--session-plan", str(plan.resolve()),
               "--output-dir", str((output / "runtime-run").resolve()), "--port", str(port)]
    start = time.perf_counter()
    evidence = {"schema": "hy30-flow-command-v2", "command": command,
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "plan_sha256": digest(plan), "prepared": str(prepared.resolve()) if prepared else None,
                "worker": worker,
                "measurement_scope": "complete runtime subprocess including pre-load model SHA256; preparation/export separate",
                "code_sha256": digest(Path(__file__))}
    write_json(output / "command.json", evidence)
    completed = None
    try:
        with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
            completed = subprocess.run(command, cwd=root, stdout=stdout, stderr=stderr, check=False)
    except BaseException as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        evidence.update(returncode=completed.returncode if completed else None,
                        command_seconds=time.perf_counter() - start,
                        finished_at_utc=datetime.now(timezone.utc).isoformat())
        write_json(output / "command-completion.json", evidence)
    print(json.dumps({k: evidence[k] for k in ("returncode", "command_seconds", "finished_at_utc")}))
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="执行并记录完整Hy30命令耗时")
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    return execute(**vars(args))


if __name__ == "__main__":
    sys.exit(main())
