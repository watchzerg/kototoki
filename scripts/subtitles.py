"""`mise run subtitles <目录>`：用默认配置为一个目标目录生成双语字幕（占 GPU、加载模型，运行前须先问）。

产品入口仍是配置文件驱动的 `python -m kototoki [kototoki.toml]`（ADR-0007）。本脚本只写一份仅含
`[paths] input_dir` 的配置到 `.local/run-configs/<末段名>-<sha12>.toml`（同一目录每次覆写同一文件，
运行日志里的 `config=` 指向它），其余键取默认值，然后以该文件调用 `kototoki.__main__.main`；退出码原样返回。
需要改引擎、工作目录等其他键时，直接写 `kototoki.toml` 并用产品入口。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from kototoki import __main__ as cli  # noqa: E402

CONFIG_DIR = REPO / ".local" / "run-configs"


def write_config(input_dir: Path, config_dir: Path | None = None) -> Path:
    """写只含 `input_dir` 的配置；路径用正斜杠写入 TOML 基本字符串（Windows 路径不含双引号）。"""
    config_dir = CONFIG_DIR if config_dir is None else config_dir
    target = input_dir.resolve()
    digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:12]
    path = config_dir / f"{target.name or 'root'}-{digest}.toml"
    config_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(f'[paths]\ninput_dir = "{target.as_posix()}"\n', encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: mise run subtitles <input_dir>", file=sys.stderr)
        return 2
    return cli.main([str(write_config(Path(argv[0])))])


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
    sys.exit(main(sys.argv[1:]))
