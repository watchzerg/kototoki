"""`just test-full` 入口：依次在独立子进程中运行环境 smoke（占 GPU、加载模型，运行前须经用户批准）。

用法：`python scripts/smoke/run_all.py [名称 ...]`，省略名称时按 SMOKES 顺序全跑。
每项一个子进程，避免 PyAV 与 torchcodec 的 FFmpeg DLL 在同一进程相遇；子进程 PATH 去掉
`whisper-runtime-provisional`，并设置离线变量。结果写入 `.local/smoke/<UTC 时间>/`，
运行期间持有 `.local/gpu.lock`，已存在时拒绝启动（用 Get-Process 核实后再处理）。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GPU_LOCK = REPO / ".local/gpu.lock"
SMOKES = ("forced_align", "vad_pyannote", "ct2_after_torch", "llama_stock")
PRIVATE_DLL_DIR = "whisper-runtime-provisional"


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    path = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry and PRIVATE_DLL_DIR not in entry.lower()]
    env["PATH"] = os.pathsep.join(path)
    cache = REPO / ".local/cache/smoke"
    env.update(PYTHONUTF8="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYANNOTE_METRICS_ENABLED="0",
               HF_HOME=str(cache / "hf"), TORCH_HOME=str(cache / "torch"))
    return env


def acquire_lock() -> None:
    GPU_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with GPU_LOCK.open("x", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "job": "scripts/smoke/run_all.py",
                       "created_at_utc": datetime.now(timezone.utc).isoformat()}, stream)
    except FileExistsError:
        raise SystemExit(f"{GPU_LOCK} exists; verify the owning process with Get-Process before removing it") from None


def run_one(name: str, out: Path, env: dict[str, str]) -> tuple[int, float]:
    started = time.perf_counter()
    command = [sys.executable, "-X", "utf8", str(HERE / f"{name}.py"), "--out", str(out)]
    with (out / f"{name}.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            print(f"[{name}] {line}", end="", flush=True)
        code = process.wait()
    return code, time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", metavar="name", help=f"可选：{', '.join(SMOKES)}")
    names = parser.parse_args().names or list(SMOKES)
    if unknown := sorted(set(names) - set(SMOKES)):
        parser.error(f"unknown smoke: {', '.join(unknown)}")
    out = REPO / ".local/smoke" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True)
    acquire_lock()
    try:
        env = child_env()
        results = {name: run_one(name, out, env) for name in names}
    finally:
        GPU_LOCK.unlink(missing_ok=True)
    for name, (code, seconds) in results.items():
        print(f"{name}: {'PASS' if code == 0 else f'FAIL (exit {code})'} in {seconds:.1f}s")
    print(f"results: {out}")
    return 0 if all(code == 0 for code, _ in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
