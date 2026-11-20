"""把 Python 依赖升到最新稳定版（docs/development/dependencies.md#升级）。

用法（经 `just upgrade` 调用；联网、改环境，须先问）：

    python scripts/upgrade.py [--check]

- CUDA 12 锚点（`ANCHORS`）保持原钉版；其余直接依赖取 uv 解析出的最新稳定版并重新钉版；
  传递依赖一起升，但跳过主版本升级（日历版本号除外），跳过项列入报告。
- ffmpeg 是系统包，由 apt 升级，不归本脚本（ADR-0034）。
- `--check` 只报告可升级项，不改任何文件。

只用标准库与仓库内同样只依赖标准库的模块。报告写 `.local/upgrade/<UTC>/report.json`；文档同步与 smoke 不在本脚本内，结束时列出待办。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from kototoki.artifacts import utc_now  # noqa: E402

PYPROJECT = REPO / "pyproject.toml"
LOCK = REPO / "uv.lock"
REPORT_ROOT = REPO / ".local" / "upgrade"
# CUDA 12 锚点：torch 系取 cu128 索引、CTranslate2 只有 CUDA 12 wheel；升级须人工决定（docs/development/technology-stack.md 选版规则）。
ANCHORS = frozenset({"torch", "torchaudio", "torchcodec", "ctranslate2"})


class UpgradeError(RuntimeError):
    """一个组件无法升级；消息说明原因，文件已还原。"""


# --- 通用 -------------------------------------------------------------------------------------

def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _release(version: str) -> list[int]:
    return [int(part) for part in re.findall(r"\d+", version.split("+")[0])[:2]]


def is_major_bump(old: str, new: str) -> bool:
    """首个数字段变化即主版本升级；0.x 看次版本；首段 ≥1900 视为日历版本号，不算。"""
    a, b = _release(old), _release(new)
    if not a or not b or a[0] >= 1900:
        return False
    if a[0] == 0 and b[0] == 0:
        return a[:2] != b[:2]
    return a[0] != b[0]


def run_uv(*args: str) -> str:
    result = subprocess.run([shutil.which("uv") or "uv", *args], cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8")
    if result.returncode != 0:
        raise UpgradeError(f"uv {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()[-2000:]}")
    return result.stderr + result.stdout


def pinned_dependencies(pyproject_text: str) -> dict[str, tuple[str, str]]:
    """{规范名: (原依赖串, 钉住的版本)}：`[project].dependencies` 里用 `==` 钉住的非锚点依赖。"""
    pins = {}
    for spec in tomllib.loads(pyproject_text)["project"]["dependencies"]:
        if match := re.fullmatch(r"([A-Za-z0-9_.\-]+)==([^\s;,]+)", spec.strip()):
            name = normalize(match.group(1))
            if name not in ANCHORS:
                pins[name] = (spec, match.group(2))
    return pins


def direct_names(pyproject_text: str) -> set[str]:
    return {normalize(re.match(r"[A-Za-z0-9_.\-]+", spec.strip()).group(0))
            for spec in tomllib.loads(pyproject_text)["project"]["dependencies"]}


def parse_updates(uv_output: str) -> dict[str, tuple[str, str]]:
    """`uv lock` 输出里的 `Update(d) <name> v<old> -> v<new>` 行。"""
    return {normalize(m.group(1)): (m.group(2), m.group(3))
            for m in re.finditer(r"^Updated? (\S+) v(\S+) -> v(\S+)$", uv_output, re.MULTILINE)}


def locked_versions(lock_text: str) -> dict[str, str]:
    return {normalize(p["name"]): p["version"] for p in tomllib.loads(lock_text)["package"] if "version" in p}


def plan_python(updates: Mapping[str, tuple[str, str]], direct: set[str]) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """(允许升级的包, 跳过的传递依赖主版本升级)。"""
    allowed, skipped = [], {}
    for name, (old, new) in sorted(updates.items()):
        if name in ANCHORS:
            continue
        if name not in direct and is_major_bump(old, new):
            skipped[name] = (old, new)
        else:
            allowed.append(name)
    return allowed, skipped


def upgrade_python(check: bool) -> dict[str, Any]:
    original_pyproject, original_lock = PYPROJECT.read_text(encoding="utf-8"), LOCK.read_text(encoding="utf-8")
    pins = pinned_dependencies(original_pyproject)
    unpinned = original_pyproject
    for spec, _ in pins.values():
        unpinned = unpinned.replace(f'"{spec}"', f'"{spec.split("==")[0]}"')
    try:
        PYPROJECT.write_text(unpinned, encoding="utf-8", newline="\n")
        allowed, skipped = plan_python(parse_updates(run_uv("lock", "--dry-run", "--upgrade")),
                                       direct_names(original_pyproject))
        if check or not allowed:
            PYPROJECT.write_text(original_pyproject, encoding="utf-8", newline="\n")
            return {"status": "available" if allowed else "up to date", "upgrades": allowed, "skipped_major": skipped}
        changes = parse_updates(run_uv("lock", *[arg for name in allowed for arg in ("-P", name)]))
        versions = locked_versions(LOCK.read_text(encoding="utf-8"))
        repinned = unpinned
        for name, (spec, _) in pins.items():
            repinned = repinned.replace(f'"{spec.split("==")[0]}"', f'"{spec.split("==")[0]}=={versions[name]}"')
        PYPROJECT.write_text(repinned, encoding="utf-8", newline="\n")
        run_uv("lock")
        run_uv("sync", "--locked")
    except BaseException:
        PYPROJECT.write_text(original_pyproject, encoding="utf-8", newline="\n")
        LOCK.write_text(original_lock, encoding="utf-8", newline="\n")
        raise
    return {"status": "upgraded", "changes": changes, "skipped_major": skipped,
            "pending": "just smoke ct2_after_torch 与小批量 just subtitles（占 GPU，须用户批准）"}


# --- 入口 -------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="只报告可升级项，不改文件")
    args = parser.parse_args(argv)
    out = REPORT_ROOT / utc_now().replace(":", "").replace("-", "")
    report: dict[str, Any] = {"created_at": utc_now(), "check": args.check}
    failed = False
    try:
        report["python"] = upgrade_python(args.check)
    except (UpgradeError, OSError) as error:
        report["python"] = {"status": "failed", "error": str(error)}
        failed = True
    print(f"python: {json.dumps(report['python'], ensure_ascii=False)}", flush=True)
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if report["python"].get("status") == "upgraded":
            print(f"report: {out / 'report.json'}\n待办：同步 docs/development/technology-stack.md 与 dependencies.md；"
                  "按报告的 pending 申请真实模型验证（smoke）。", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
