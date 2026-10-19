"""运行一条命令并旁路记录整卡显存与按阶段墙钟（只观察，不控制被测进程）。

用法：python -m experiments.quality_v5.telemetry_run --out DIR -- <命令...>
产物：DIR/console.log（子进程合并输出）、DIR/gpu-samples.jsonl、DIR/driver-result.json。
阶段按产品日志的 `[phase] start` / `[phase] end` 行切分；不认识的行不影响结果。
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

# 产品日志自 2026-10-18 起形如 `2026-10-19 06:35:03Z [    10.0s] INFO     [vad] start: ...`；
# 旧格式 `[   10.0s] [vad] start` 仍可匹配（日期与级别均可选）。
PHASE_LINE = re.compile(r"^(?:\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z\s+)?\[\s*(?P<t>[\d.]+)s\]\s+(?:[A-Z]+\s+)?"
                        r"\[(?P<phase>[\w-]+)\]\s+(?P<event>start|end)\b")


def summarize(lines: list[str], samples: list[dict], t0: float) -> dict:
    """各阶段墙钟（日志自带相对秒）与阶段内显存峰值；样本时间换算为相对子进程启动的秒。
    产品日志的秒从编排器启动算起，与子进程启动相差解释器加载时间，峰值归属只作参考。"""
    result = []
    open_at: dict[str, float] = {}
    for line in lines:
        match = PHASE_LINE.match(line.strip())
        if not match:
            continue
        t, phase = float(match["t"]), match["phase"]
        if match["event"] == "start":
            open_at[phase] = t
        elif phase in open_at:
            start = open_at.pop(phase)
            inside = [s["memory_used_mib"] for s in samples if start <= s["t"] - t0 <= t]
            result.append({"phase": phase, "start_s": start, "end_s": t, "wall_s": round(t - start, 1),
                           "peak_memory_used_mib": max(inside) if inside else None})
    peak = max((s["memory_used_mib"] for s in samples), default=None)
    idle = samples[0]["memory_used_mib"] if samples else None
    return {"phases": result, "peak_memory_used_mib": peak, "idle_memory_used_mib": idle,
            "sample_count": len(samples)}


def sample_gpu(stop: threading.Event, samples: list[dict], sink, interval: float) -> None:
    query = ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"]
    while not stop.is_set():
        try:
            used, util = subprocess.run(query, capture_output=True, text=True, timeout=10).stdout.strip().split(",")
            sample = {"t": time.time(), "memory_used_mib": float(used), "utilization_percent": float(util)}
            samples.append(sample)
            sink.write(json.dumps(sample) + "\n")
        except (ValueError, subprocess.SubprocessError):
            pass
        stop.wait(interval)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if Path(command[0]).exists():  # Windows CreateProcess 不按 cwd 解析带 / 的相对路径
        command[0] = str(Path(command[0]).resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    samples: list[dict] = []
    stop = threading.Event()
    lines: list[str] = []
    with open(args.out / "gpu-samples.jsonl", "w", encoding="utf-8") as sink, \
            open(args.out / "console.log", "w", encoding="utf-8") as console:
        sampler = threading.Thread(target=sample_gpu, args=(stop, samples, sink, args.interval), daemon=True)
        sampler.start()
        t0 = time.time()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="backslashreplace")
        for line in process.stdout:
            lines.append(line)
            console.write(line)
            console.flush()
            sys.stdout.write(line)
            sys.stdout.flush()
        exit_code = process.wait()
        total = time.time() - t0
        stop.set()
        sampler.join(timeout=15)
    result = {"command": command, "exit_code": exit_code, "total_wall_s": round(total, 1),
              **summarize(lines, samples, t0)}
    (args.out / "driver-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("exit_code", "total_wall_s", "peak_memory_used_mib")}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
