"""Check host tool versions against mise.toml and .python-version without syncing or downloading.

Run via `just check-toolchain` (uv --no-project --no-python-downloads); standard library only.
"""

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tool_version(command: str) -> str | None:
    try:
        result = subprocess.run([command, "--version"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    match = re.search(r"\d+\.\d+\.\d+", result.stdout)
    return match.group(0) if match else None


def main() -> int:
    errors: list[str] = []
    pins = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tools"]
    for tool, expected in pins.items():
        actual = tool_version(tool)
        if actual != str(expected):
            errors.append(f"{tool}: mise.toml pins {expected}, found {actual or 'not on PATH'}")
    expected_python = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    actual_python = ".".join(map(str, sys.version_info[:3]))
    if actual_python != expected_python:
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
