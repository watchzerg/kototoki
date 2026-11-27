"""环境 smoke 的共用小工具：结果输出、进程已加载的共享库清单、仓库路径、正在运行的 llama-server 进程。

每个 smoke 脚本由 `run_all.py` 在独立子进程中以 `python scripts/smoke/<name>.py --out <dir>` 启动，
结束时调用 `finish()` 写 `<dir>/<name>.json` 并在 stdout 打印一行 `SMOKE_RESULT <json>`。
结果里只放版本、设备、耗时、计数与哈希，不放音频内容或转写全文。
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
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RESULT_PREFIX = "SMOKE_RESULT "


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--out", type=Path, required=True, help="本次 smoke 的输出目录（由 run_all.py 新建）")
    return parser.parse_args()


def loaded_modules() -> list[str]:
    """当前进程映射进来的全部共享库路径（`/proc/self/maps`）。"""
    paths = set()
    for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and fields[5].startswith("/") and ".so" in Path(fields[5]).name:
            paths.add(fields[5])
    return sorted(paths)


def modules_matching(prefixes: tuple[str, ...]) -> list[str]:
    """按共享库文件名前缀（如 `libcudnn`）筛选已加载的库。"""
    return [path for path in loaded_modules() if Path(path).name.startswith(prefixes)]


def package_versions(*names: str) -> dict[str, str | None]:
    import importlib.metadata
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


class Timer:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.marks: dict[str, float] = {}

    def mark(self, label: str) -> float:
        self.marks[label] = round(time.perf_counter() - self.started, 3)
        return self.marks[label]


def list_llama_servers() -> list[int]:
    """正在运行的 `llama-server` 的 pid。ADR-0025 起产品已不起 llama-server，只有 smoke 用它核实全程没有 llama-server。"""
    result = subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True, text=True, check=False)
    if result.returncode > 1:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"pgrep failed with exit code {result.returncode}: {detail}")
    return [int(pid) for pid in result.stdout.split()]


def finish(out: Path, name: str, result: dict[str, Any]) -> int:
    """写结果 JSON 并打印摘要行；`passed` 为假时返回 1。"""
    result = {"smoke": name, "finished_at_utc": utc_now(), "python": sys.version.split()[0],
              "path_env": os.environ.get("PATH", "").split(os.pathsep), **result}
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: result.get(key) for key in ("smoke", "passed", "versions", "device", "elapsed_s", "failures")}
    print(RESULT_PREFIX + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if result.get("passed") else 1
