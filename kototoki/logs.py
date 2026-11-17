"""运行日志的格式：编排器的运行日志与 GPU worker 的 stderr 共用同一行格式。

只依赖标准库，属基础层；handler 与目的地由使用方（`job.run`、`workers/gpu.main`）各自配置。

模块页：docs/architecture/modules/run-logging-and-processes.md。
"""

from __future__ import annotations

import logging
import time

LOG_FORMAT = "%(asctime)s [%(elapsed)8.1fs] %(levelname)-8s %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%SZ"


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
