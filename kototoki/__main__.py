"""`python -m kototoki [kototoki.toml]`：读配置、检查工作目录位置、跑一批（规格 §1、§10）。

退出码见 `kototoki.job`：0 全部成功；1 有文件失败；2 配置或工作目录不可用；3 同一目标目录已有编排器在运行；4 GPU 锁冲突。

模块页：docs/architecture/modules/batch-orchestration.md。
"""

from __future__ import annotations

from pathlib import Path
import sys

from kototoki import job
from kototoki.config import REPO_ROOT, Config, ConfigError, load


def check_input_dir(config: Config) -> None:
    """输入目录必须存在：否则扫描到 0 个文件也会以退出码 0 结束，无人值守时像成功。双语字幕写在源文件旁，
    因此输入目录也不得位于仓库内（`.local/` 除外），转写不进 Git。"""
    input_dir = config.paths.input_dir
    if not input_dir.is_dir():
        raise ConfigError(f"[paths] input_dir is not a directory: {input_dir}")
    if input_dir.is_relative_to(REPO_ROOT) and not input_dir.is_relative_to(REPO_ROOT / ".local"):
        raise ConfigError(f"[paths] input_dir must not be inside the repository (except .local/): {input_dir}")


def check_work_dir(config: Config) -> None:
    """拒绝工作目录位于仓库内（`.local/` 除外）或位于输入目录内（含二者相同）：中间产物不进 Git、不污染目标目录。"""
    work, input_dir = config.paths.work_dir, config.paths.input_dir
    if work.is_relative_to(REPO_ROOT) and not work.is_relative_to(REPO_ROOT / ".local"):
        raise ConfigError(f"[paths] work_dir must not be inside the repository (except .local/): {work}")
    if work.is_relative_to(input_dir):
        raise ConfigError(f"[paths] work_dir must not be inside input_dir: {work}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: python -m kototoki [kototoki.toml]", file=sys.stderr)
        return job.EXIT_CONFIG
    try:
        config = load(Path(args[0] if args else "kototoki.toml"))
        check_input_dir(config)
        check_work_dir(config)
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return job.EXIT_CONFIG
    try:
        summary = job.run(config)
    except job.WorkLocked as error:
        print(f"work directory locked: {error}", file=sys.stderr)
        return job.EXIT_WORK_LOCKED
    except job.GpuLocked as error:
        print(f"GPU locked: {error}", file=sys.stderr)
        return job.EXIT_GPU_LOCKED
    return summary.exit_code


if __name__ == "__main__":
    # 文件名可能含非 UTF-8 字节（surrogateescape 解码），UTF-8 输出时会抛错；转义显示，不崩溃。
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
    sys.exit(main())
