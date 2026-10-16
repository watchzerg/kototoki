"""只判与基准 run 不同的窗口（票据 08）：候选 run 与同 seed 基准 run 只换了选择器，多数窗口译文完全相同。

窗口内任一计分 cue 的译文不同 → 用 v4 `judge(reference=子集)` 真判；其余窗口的计分 cue 与基准相同（上下文 cue
可能不同，这是近似：上下文只供裁判参考，不计分），把基准 run 对这些窗口的判分复制进候选 run 的裁判目录，写成一个合成包文件（文件名合乎 v3
`PACKET_FILE`，内容标 `copied_from`）。之后 v4 `compare` 照常读取。复制只省配额，并让相同窗口在
"候选 vs 基准"的配对差里精确为 0。

命令（仓库根目录，`.venv`）：
  python -X utf8 -m experiments.quality_v5.diff_judge --root ROOT --run mbr8s__s20261011__dev --base mbr8c [--plan]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from experiments.translation_v3 import judge as J
from experiments.translation_v3.common import atomic_write_json, read_json, sha256_bytes, utc_now
from experiments.translation_v3.data import ReferenceWindow
from experiments.translation_v4.evaluate import judge, reference_for


def translations(run_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for scene_id in read_json(run_dir / "run.json")["scene_ids"]:
        out.update(read_json(run_dir / "scenes" / f"{scene_id}.json").get("translations", {}))
    return out


def differing_windows(windows: dict[str, ReferenceWindow], scenes: set[str], cand: dict[str, str],
                      base: dict[str, str]) -> tuple[set[str], set[str]]:
    """(不同窗口, 相同窗口)：只看本 run 场景内的窗口；比较计分 cue 的译文。"""
    differ, same = set(), set()
    for key, window in windows.items():
        if window.meta.scene_id not in scenes:
            continue
        (differ if any(cand.get(u["id"]) != base.get(u["id"]) for u in window.units) else same).add(key)
    return differ, same


def copy_base(root: Path, run_dir: Path, base_dir: Path, same: set[str]) -> dict[str, Any]:
    base_judged, surfaces = J.load_judgements(base_dir)
    missing = sorted(same - set(base_judged))
    if missing:
        raise ValueError(f"{base_dir.name} lacks judgements for {len(missing)} windows")
    out_dir = run_dir / "judge" / J.profile_dir_name(0)
    packet_id = "p" + sha256_bytes(f"copied|{run_dir.name}|{base_dir.name}|{','.join(sorted(same))}".encode())[:19]
    atomic_write_json(out_dir / f"{packet_id}.json", {
        "packet_id": packet_id, "split": None, "window_ids": sorted(same), "profile": J.PROFILE_ID,
        "profile_hash": J.PROFILE_HASH, "surface": "+".join(sorted(surfaces)), "copied_from": base_dir.name,
        "copied_at_utc": utc_now(), "judgement": {key: base_judged[key] for key in sorted(same)}})
    return {"packet_id": packet_id, "windows": len(same)}


def run(root: Path, run_id: str, base: str, plan_only: bool, parallel: int = 3) -> dict[str, Any]:
    run_dir = root / "runs" / run_id
    meta = read_json(run_dir / "run.json")
    base_dir = root / "runs" / f"{base}__s{meta['seed']}__{meta['scope']}"
    windows = reference_for(root, meta["scope"])
    differ, same = differing_windows(windows, set(meta["scene_ids"]), translations(run_dir), translations(base_dir))
    report: dict[str, Any] = {"run_id": run_id, "base": base_dir.name, "differ_windows": len(differ),
                              "same_windows": len(same)}
    if plan_only:
        return report
    report["copied"] = copy_base(root, run_dir, base_dir, same)
    summary = judge(root, run_dir, ["A", "B"], parallel=parallel, reference={k: windows[k] for k in differ})
    report["judge"] = {"exit_code": summary["exit_code"],
                       "packets": sum(p.get("packets_total", 0) for p in summary["parts"]),
                       "errors": sum(len(p.get("errors", [])) for p in summary["parts"])}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="只判与基准 run 不同的窗口（票据 08）")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--plan", action="store_true", help="只统计不同／相同窗口数，不复制不裁判")
    parser.add_argument("--parallel", type=int, default=3)
    args = parser.parse_args()
    report = run(args.root, args.run, args.base, args.plan, args.parallel)
    print(json.dumps(report, ensure_ascii=False))
    return report.get("judge", {}).get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
