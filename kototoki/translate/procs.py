"""列出本机正在运行的 llama-server（复制自 `experiments/translation_v3/procs.py`）。

锁与 Job Object 不在此：GPU 锁归编排器；编排器启动时已把自身放进 KILL_ON_JOB_CLOSE Job Object
（`job.contain_children`），llama-server 作为其子进程自动加入。
"""

from __future__ import annotations

import subprocess
import sys


def list_llama_servers() -> list[int]:
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith("llama-server") and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids
