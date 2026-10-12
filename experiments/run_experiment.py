"""Serialize GPU experiments and retain private reproducibility evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_HASH = "2d31b51406dd33cfc3af300c9346280a31aac7b6c199208e87f1f92ce79ae583"


def reference_sha256(value: str) -> str:
    if re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise argparse.ArgumentTypeError("reference SHA256 must contain exactly 64 hexadecimal characters")
    return value.lower()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=Path("D:/movie/FateStay/FateStay-original-1.srt"))
    parser.add_argument("--reference-sha256", type=reference_sha256, default=REFERENCE_HASH)
    parser.add_argument("--timeout", type=float, default=7200)
    parser.add_argument("--performance-context", default="exploratory; CPU/network preparation may run concurrently; GPU experiments serialized")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("backend command required after --")
    if args.id in {"", ".", ".."} or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in args.id):
        parser.error("id must be a simple filename")
    run_dir = ROOT / ".local" / "results" / args.id
    run_dir.mkdir(parents=True, exist_ok=False)
    before = sha256(args.reference)
    if before != args.reference_sha256:
        raise RuntimeError("Reference SHA256 mismatch; source was not modified by this tool")
    manifest = {
        "id": args.id, "started_utc": datetime.now(timezone.utc).isoformat(),
        "command": command, "audio": str(args.audio.resolve()),
        "audio_sha256": sha256(args.audio), "reference_sha256_before": before,
        "reference_sha256_expected": args.reference_sha256,
        "platform": platform.platform(), "harness_python": sys.version,
        "performance_context": args.performance_context,
        "cache_reuse": "adapter_reported_per_stage", "fresh_subprocess": True,
        "input_identity_note": "Compare this SHA256 with backend input manifest before interpreting results",
        "status": "running", "gpu_samples": [],
        "measurement": "nvidia-smi whole-device memory/utilization sampled ~1s; includes desktop baseline, not per-process peak",
    }
    source_files = {Path(__file__).resolve()}
    for argument in command:
        candidate = (ROOT / argument).resolve()
        if candidate.suffix == ".py" and candidate.is_file() and candidate.is_relative_to(ROOT):
            source_files.add(candidate)
            if candidate.is_relative_to(ROOT / "experiments"):
                source_files.update(candidate.parent.glob("*.py"))
    manifest["source_sha256"] = {}
    for source in sorted(source_files):
        relative = source.relative_to(ROOT)
        snapshot = run_dir / "source" / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, snapshot)
        manifest["source_sha256"][str(relative)] = sha256(snapshot)
    env = os.environ.copy()
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "PYTHONUTF8": "1"})
    lock = ROOT / ".local" / "gpu.lock"
    lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "run": args.id}, stream)
    except BaseException:
        lock.unlink(missing_ok=True)
        raise
    started = time.perf_counter()
    process = None
    try:
        with (run_dir / "stdout.log").open("wb") as stdout, (run_dir / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
            while process.poll() is None:
                elapsed = time.perf_counter() - started
                if elapsed > args.timeout:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    process.wait(timeout=30)
                    manifest["status"] = "timeout"
                    break
                sample = subprocess.run(["nvidia-smi", "--query-gpu=timestamp,name,driver_version,memory.used,utilization.gpu,power.draw", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
                manifest["gpu_samples"].append({"elapsed_seconds": elapsed, "csv": sample.stdout.strip(), "returncode": sample.returncode})
                (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                time.sleep(1)
            manifest["returncode"] = process.returncode
            if manifest["status"] == "running":
                manifest["status"] = "completed" if process.returncode == 0 else "failed"
    except BaseException as exc:
        manifest["status"] = "harness_error"
        manifest["error"] = str(exc)
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            process.wait(timeout=30)
        raise
    finally:
        manifest["wall_seconds"] = time.perf_counter() - started
        try:
            try:
                manifest["reference_sha256_after"] = sha256(args.reference)
                manifest["reference_unchanged"] = manifest["reference_sha256_after"] == before
            except OSError as exc:
                manifest["reference_unchanged"] = False
                manifest["reference_check_error"] = str(exc)
            (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        finally:
            lock.unlink()
    print(json.dumps({"id": args.id, "status": manifest["status"], "seconds": manifest["wall_seconds"], "reference_unchanged": manifest["reference_unchanged"]}))
    return 0 if manifest["status"] == "completed" and manifest["reference_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
