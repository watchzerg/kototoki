"""`kototoki.logs.RunFormatter` 的行格式与相对秒。"""

from __future__ import annotations

import logging
import time
import unittest

from kototoki.logs import RunFormatter


def record(name: str = "kototoki.job", created: float | None = None) -> logging.LogRecord:
    rec = logging.LogRecord(name, logging.INFO, __file__, 1, "[scan] hello", None, None)
    if created is not None:
        rec.created = created
    return rec


class RunFormatterTests(unittest.TestCase):
    def test_elapsed_ignores_wall_clock_jumps(self) -> None:
        """回归（batch-run-fixes 06.2）：系统时钟被校正 +8 h 后相对秒不跳；时间戳照旧跟墙钟走。"""
        formatter = RunFormatter()
        jumped = time.time() + 8 * 3600
        line = formatter.format(record(created=jumped))
        self.assertTrue(line.startswith(time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(jumped))), line)
        elapsed = float(line.split("[", 1)[1].split("s]", 1)[0])
        self.assertLess(elapsed, 60.0)

    def test_foreign_logger_gets_prefix(self) -> None:
        formatter = RunFormatter()
        self.assertTrue(formatter.format(record("transformers.utils")).endswith("INFO     [transformers] [scan] hello"))
        self.assertTrue(formatter.format(record()).endswith("INFO     [scan] hello"))


if __name__ == "__main__":
    unittest.main()
