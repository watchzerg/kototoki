"""`python -m kototoki [kototoki.toml]`：读配置、检查输出目录位置、跑一批（规格 §1、§10）。

退出码见 `kototoki.job`：0 全部成功；1 有文件失败；2 配置或输出目录不可用；3 输出目录锁冲突；4 GPU 锁冲突。
"""

from __future__ import annotations

from pathlib import Path
import sys

from kototoki import job
from kototoki.config import REPO_ROOT, Config, ConfigError, load


def check_input_dir(config: Config) -> None:
    """输入目录必须存在：否则扫描到 0 个视频也会以退出码 0 结束，无人值守时像成功。"""
    if not config.paths.input_dir.is_dir():
        raise ConfigError(f"[paths] input_dir is not a directory: {config.paths.input_dir}")


def check_output_dir(config: Config) -> None:
    """拒绝输出目录位于仓库内（`.local/` 除外）或位于输入目录内（含二者相同）。"""
    output, input_dir = config.paths.output_dir, config.paths.input_dir
    if output.is_relative_to(REPO_ROOT) and not output.is_relative_to(REPO_ROOT / ".local"):
        raise ConfigError(f"[paths] output_dir must not be inside the repository (except .local/): {output}")
    if output.is_relative_to(input_dir):
        raise ConfigError(f"[paths] output_dir must not be inside input_dir: {output}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: python -m kototoki [kototoki.toml]", file=sys.stderr)
        return job.EXIT_CONFIG
    try:
        config = load(Path(args[0] if args else "kototoki.toml"))
        check_input_dir(config)
        check_output_dir(config)
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return job.EXIT_CONFIG
    try:
        summary = job.run(config)
    except job.OutputLocked as error:
        print(f"output directory locked: {error}", file=sys.stderr)
        return job.EXIT_OUTPUT_LOCKED
    except job.GpuLocked as error:
        print(f"GPU locked: {error}", file=sys.stderr)
        return job.EXIT_GPU_LOCKED
    return summary.exit_code


if __name__ == "__main__":
    # 控制台代码页可能不是 UTF-8（本机根环境默认 cp1252）；文件名无法显示时转义，不崩溃。
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
    sys.exit(main())
