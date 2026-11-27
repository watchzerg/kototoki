"""运行日志的格式：编排器的运行日志与 GPU worker 的 stderr 共用同一行格式。

只依赖标准库，属基础层；handler 与目的地由使用方（`job.run`、`workers/gpu.main`）各自配置。

模块页：docs/architecture/modules/run-logging-and-processes.md。
"""

from __future__ import annotations

import logging
from pathlib import Path
import time

__all__ = ["FailureKind", "LOG_DATEFMT", "LOG_FORMAT", "RunFormatter", "failure_kind", "format_error", "path_label"]

LOG_FORMAT = "%(asctime)s [%(elapsed)8.1fs] %(levelname)-8s %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%SZ"

FailureKind = tuple[str, str | None, int | None]


def format_error(error: BaseException, limit: int = 200) -> str:
    """将异常压成单行 `<类型>: <首行消息>`（空消息时只保留类型名），总长截断到 `limit` 字符。"""
    name = type(error).__name__
    message = str(error).strip()
    if not message:
        return name[:limit]
    return f"{name}: {message.splitlines()[0]}"[:limit]


def path_label(path: Path) -> str:
    """用 `<parent.name>/<name>` 标识路径（无父目录名时取 `name`），避免在日志里暴露宿主绝对路径。"""
    path = Path(path)
    return f"{path.parent.name}/{path.name}" if path.parent.name else path.name


def failure_kind(cause: BaseException) -> FailureKind:
    """提取异常类别 `(完整异常类型名, 最内层抛出文件, 行号)`；无 traceback 时位置为 None。"""
    tb = cause.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    where = (tb.tb_frame.f_code.co_filename, tb.tb_lineno) if tb is not None else (None, None)
    return (f"{type(cause).__module__}.{type(cause).__qualname__}", *where)


class RunFormatter(logging.Formatter):
    """墙钟取 UTC，另带自构造起的相对秒；非 `kototoki` logger 的消息前加 `[<logger 名首段>]`。

    相对秒用单调时钟（格式化时取），系统时钟被校正时不跳变（batch-run-fixes 06.2）；墙钟时间戳照旧取 `record.created`。
    """

    converter = time.gmtime

    def __init__(self) -> None:
        super().__init__(LOG_FORMAT, LOG_DATEFMT)
        self.started = time.monotonic()

    def formatMessage(self, record: logging.LogRecord) -> str:
        # `format` 每次都会从 getMessage() 重建 record.message，这里改写不会在多个 handler 间叠加前缀。
        # handler 在 emit 时同步格式化，格式化时刻即记录时刻。
        record.elapsed = time.monotonic() - self.started
        top = record.name.split(".")[0]
        if top != "kototoki":
            record.message = f"[{top}] {record.message}"
        return super().formatMessage(record)
