"""运行日志的格式：编排器的运行日志与 GPU worker 的 stderr 共用同一行格式。

只依赖标准库，属基础层；handler 与目的地由使用方（`job.run`、`workers/gpu.main`）各自配置。
"""

from __future__ import annotations

import logging
import time

LOG_FORMAT = "%(asctime)s [%(elapsed)8.1fs] %(levelname)-8s %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%SZ"


class RunFormatter(logging.Formatter):
    """墙钟取 UTC，另带自 `started` 起的相对秒；非 `kototoki` logger 的消息前加 `[<logger 名首段>]`。"""

    converter = time.gmtime

    def __init__(self, started: float):
        super().__init__(LOG_FORMAT, LOG_DATEFMT)
        self.started = started

    def formatMessage(self, record: logging.LogRecord) -> str:
        # `format` 每次都会从 getMessage() 重建 record.message，这里改写不会在多个 handler 间叠加前缀。
        record.elapsed = record.created - self.started
        top = record.name.split(".")[0]
        if top != "kototoki":
            record.message = f"[{top}] {record.message}"
        return super().formatMessage(record)
