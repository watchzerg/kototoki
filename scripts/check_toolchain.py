"""Check host tool versions against mise.toml and .python-version without syncing or downloading.

Run via `mise run check-toolchain` (uv --no-project --no-python-downloads); standard library only.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def probe_tool(command: str) -> tuple[str | None, str]:
    """返回 `(版本号, 失败说明)`；找到并解析出版本时失败说明为空串。"""
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return None, "not on PATH"
    except OSError as error:
        return None, f"{type(error).__name__}: {error}"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        suffix = f" ({detail})" if detail else ""
        return None, f"exit {result.returncode}{suffix}"
    match = re.search(r"\d+\.\d+\.\d+", result.stdout)
    if not match:
        preview = result.stdout.strip().splitlines()[0][:120] if result.stdout.strip() else "<empty>"
        return None, f"unparseable version output: {preview!r}"
    return match.group(0), ""


def main() -> int:
    errors: list[str] = []
    pins = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tools"]
    for tool, expected in pins.items():
        actual, detail = probe_tool(tool)
        # mise.toml 可只写到次版本（如 0.13），按版本段前缀匹配。
        if actual is None:
            errors.append(f"{tool}: mise.toml pins {expected}, {detail}")
        elif not f"{actual}.".startswith(f"{expected}."):
            errors.append(f"{tool}: mise.toml pins {expected}, found {actual}")
    expected_python = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    actual_python = ".".join(map(str, sys.version_info[:3]))
    # `.python-version` 写到次版本（如 3.13），补丁版本由 uv 决定。
    if not f"{actual_python}.".startswith(f"{expected_python}."):
        errors.append(f"python: .python-version pins {expected_python}, found {actual_python}")
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print("Activate the mise tool versions (or run `mise install`) before running gates.", file=sys.stderr)
        return 1
    print(f"toolchain ok: {', '.join(f'{t} {v}' for t, v in pins.items())}, python {actual_python}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
