"""环境 smoke 的共用小工具：结果输出、进程已加载模块清单、仓库路径。

每个 smoke 脚本由 `run_all.py` 在独立子进程中以 `python scripts/smoke/<name>.py --out <dir>` 启动，
结束时调用 `finish()` 写 `<dir>/<name>.json` 并在 stdout 打印一行 `SMOKE_RESULT <json>`。
结果里只放版本、设备、耗时、计数与哈希，不放音频内容或转写全文。
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
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
    """当前进程实际加载的全部 DLL 路径（Windows psapi）。"""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    process = kernel32.GetCurrentProcess()
    needed = wintypes.DWORD()
    size = 1024
    while True:
        modules = (wintypes.HMODULE * size)()
        if not psapi.EnumProcessModulesEx(process, modules, ctypes.sizeof(modules), ctypes.byref(needed), 0x03):
            raise ctypes.WinError(ctypes.get_last_error())
        count = needed.value // ctypes.sizeof(wintypes.HMODULE)
        if count <= size:
            break
        size = count
    buffer = ctypes.create_unicode_buffer(32768)
    paths = []
    for handle in modules[:count]:
        if psapi.GetModuleFileNameExW(process, handle, buffer, len(buffer)):
            paths.append(buffer.value)
    return sorted(paths, key=str.lower)


def modules_matching(prefixes: tuple[str, ...]) -> list[str]:
    """按 DLL 基名前缀（不区分大小写）筛选已加载模块。"""
    return [path for path in loaded_modules() if Path(path).name.lower().startswith(prefixes)]


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


def finish(out: Path, name: str, result: dict[str, Any]) -> int:
    """写结果 JSON 并打印摘要行；`passed` 为假时返回 1。"""
    result = {"smoke": name, "finished_at_utc": utc_now(), "python": sys.version.split()[0],
              "path_env": os.environ.get("PATH", "").split(os.pathsep), **result}
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: result.get(key) for key in ("smoke", "passed", "versions", "device", "elapsed_s", "failures")}
    print(RESULT_PREFIX + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if result.get("passed") else 1
