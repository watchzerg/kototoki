"""共用运行日志格式与诊断辅助（`kototoki.logs`）的离线单元测试。"""

from __future__ import annotations

from pathlib import Path
import unittest

from kototoki.logs import failure_kind, format_error, path_label


def _inner_raise(message: str) -> None:
    raise RuntimeError(message)


def _outer_raise(message: str) -> None:
    _inner_raise(message)


class LogsHelperTests(unittest.TestCase):
    def test_format_error_handles_empty_multiline_and_limit(self) -> None:
        self.assertEqual(format_error(ValueError()), "ValueError")
        self.assertEqual(format_error(ValueError("   \nignored")), "ValueError: ignored")
        self.assertEqual(format_error(RuntimeError("first line\nsecond line")), "RuntimeError: first line")
        summary = format_error(ValueError("x" * 250), limit=200)
        self.assertEqual(len(summary), 200)
        self.assertTrue(summary.startswith("ValueError: "))

    def test_path_label_returns_parent_and_name_or_name_only(self) -> None:
        self.assertEqual(path_label(Path("/host/work/0123456789ab/vad.json")), "0123456789ab/vad.json")
        self.assertEqual(path_label(Path("ja.srt")), "ja.srt")
        self.assertEqual(path_label(Path("/ja.srt")), "ja.srt")

    def test_failure_kind_extracts_innermost_frame_and_handles_no_traceback(self) -> None:
        self.assertEqual(failure_kind(ValueError("plain")), ("builtins.ValueError", None, None))
        try:
            _outer_raise("boom")
        except RuntimeError as exc:
            qualname, filename, lineno = failure_kind(exc)
        self.assertEqual(qualname, "builtins.RuntimeError")
        self.assertEqual(filename, __file__)
        self.assertIsInstance(lineno, int)


if __name__ == "__main__":
    unittest.main()
