"""产品 GPU worker 的驱动：写 jobs 文件、以产品子进程环境运行 `kototoki.workers.{vad,asr,align}`、记墙钟与显存峰值。

worker 的接口（jobs 形状、`config.models`／`model_cache`、stdout 协议行）见 `docs/architecture/modules/stt-workers.md`。
研究侧不经产品编排器，但子进程环境与它相同（`kototoki.job.OFFLINE_ENV`／`QUIET_ENV`，`HF_HOME`／`TORCH_HOME` 指向
研究缓存目录）。本模块导入时不加载 torch。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from experiments.asr_robustness_v14 import common
from kototoki import artifacts, plan
from kototoki.job import OFFLINE_ENV, QUIET_ENV

PYTHON = Path(sys.executable)
STAGE_INPUTS = {"vad": ("wav",), "asr": ("wav", "vad"), "align": ("wav", "asr")}
INPUT_FILES = {"wav": artifacts.AUDIO_16K, "vad": artifacts.VAD, "asr": artifacts.ASR}


def child_env(cache_dir: Path) -> dict[str, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return {**os.environ, **OFFLINE_ENV, **QUIET_ENV, "HF_HOME": str(cache_dir), "TORCH_HOME": str(cache_dir)}


def write_jobs(stage: str, work_dirs: list[Path], path: Path, *, engine: str = "w0",
               config: dict[str, Any] | None = None) -> Path:
    """一个阶段、若干工作目录的 jobs 文件；输入文件按产品命名取自各工作目录。"""
    config = dict(config or common.product_models())
    config["engine"] = engine
    files = [{"id": work.name, "work_dir": str(work),
              "inputs": {name: str(work / INPUT_FILES[name]) for name in STAGE_INPUTS[stage]}}
             for work in work_dirs]
    payload = {"stage": stage, "recipe_hash": plan.recipe_hash(stage, engine=engine if stage == "asr" else None),
               "config": config, "files": files}
    common.write_json(path, payload)
    return path


def run_worker(stage: str, jobs_path: Path, log_dir: Path, *, python: Path = PYTHON) -> dict[str, Any]:
    """运行一个 worker 到结束；stderr 存 `<log_dir>/<stage>.stderr.log`，stdout 协议行解析成事件。返回事件、退出码、墙钟、显存峰值。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    cache = common.ROOT / "cache"
    sampler = common.VramSampler()
    sampler.start()
    started = common.timed()
    with (log_dir / f"{stage}.stderr.log").open("ab") as stderr:
        proc = subprocess.run([str(python), "-X", "utf8", "-m", f"kototoki.workers.{stage}", "--jobs", str(jobs_path)],
                              cwd=str(common.REPO), env=child_env(cache), stdout=subprocess.PIPE, stderr=stderr)
    wall = common.timed() - started
    peak = sampler.stop()
    events = []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    result = {"stage": stage, "jobs": str(jobs_path), "exit_code": proc.returncode, "wall_s": round(wall, 1),
              "vram_peak_mib": peak, "events": events, "finished_at_utc": common.utc_now()}
    common.write_json(log_dir / f"{stage}.result.json", result)
    if proc.returncode != 0 or any(e.get("event") != "done" for e in events) or not events:
        raise RuntimeError(f"{stage} worker failed: exit {proc.returncode}, events {events}")
    return result
