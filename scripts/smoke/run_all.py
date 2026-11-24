"""`mise run smoke` 入口：依次在独立子进程中运行真实模型验证（CT2 环境 smoke、产品翻译与产品专名 smoke；占 GPU、加载模型，
每次运行前须经用户批准；不属于任何 gate）。

用法：`python scripts/smoke/run_all.py [名称 ...]`，省略名称时按 SMOKES 顺序全跑；每项是本目录下的
`<名称>.py`，以 `--out <dir>` 启动。
每项一个子进程，避免 PyAV 与 torchcodec 各自的 FFmpeg 库在同一进程相遇；子进程设置离线变量。结果写入
`.local/smoke/<UTC 时间>/`，运行期间持有 `.local/gpu.lock`，已存在时拒绝启动（用 `ps -p <pid>` 核实后再处理）。
每项打印开始行与结束行（PASS／FAIL、耗时、该项 `.log`）；中途异常或 Ctrl+C 时先回收仍在运行的子进程再删锁，汇总照常打印。
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
SMOKES = ("ct2_after_torch", "translate_product", "names_product")


def child_env() -> dict[str, str]:
    env = dict(os.environ)
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
        raise SystemExit(f"{GPU_LOCK} exists; verify the owning process with `ps -p <pid>` before removing it") from None


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_one(index: int, total: int, name: str, out: Path, env: dict[str, str]) -> tuple[int, float]:
    """跑一项并把子进程输出逐行转发；无论以何种方式退出（含 Ctrl+C 或父进程打印失败），子进程仍在运行就先杀掉并回收。"""
    started = time.perf_counter()
    log_path = out / f"{name}.log"
    print(f"=== [{index}/{total}] {name} start {utc_now()}", flush=True)
    command = [sys.executable, "-X", "utf8", str(HERE / f"{name}.py"), "--out", str(out)]
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        try:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                print(f"[{name}] {line}", end="", flush=True)
            code = process.wait()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()
    seconds = time.perf_counter() - started
    verdict = "PASS" if code == 0 else f"FAIL (exit {code})"
    print(f"=== [{index}/{total}] {name} {verdict} in {seconds:.1f}s, log {log_path}", flush=True)
    return code, seconds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", metavar="name", help=f"可选：{', '.join(SMOKES)}")
    names = parser.parse_args().names or list(SMOKES)
    if unknown := sorted(set(names) - set(SMOKES)):
        parser.error(f"unknown smoke: {', '.join(unknown)}")
    out = REPO / ".local/smoke" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True)
    acquire_lock()
    results: dict[str, tuple[int, float]] = {}
    try:
        env = child_env()
        for index, name in enumerate(names, 1):
            results[name] = run_one(index, len(names), name, out, env)
    finally:
        GPU_LOCK.unlink(missing_ok=True)  # run_one 已回收子进程，之后才删锁
        for name in names:
            if name in results:
                code, seconds = results[name]
                print(f"{name}: {'PASS' if code == 0 else f'FAIL (exit {code})'} in {seconds:.1f}s")
            else:
                print(f"{name}: not completed")
        print(f"results: {out}", flush=True)
    return 0 if all(code == 0 for code, _ in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
