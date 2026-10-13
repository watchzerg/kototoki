"""kototoki.srt 的离线测试：零条目、毫秒取整、严格解析、渲染与写出。"""

import hashlib
import math
from pathlib import Path
import tempfile
import unittest

from kototoki.srt import (
    IncompleteTranslationError, format_srt, milliseconds, parse_srt, read_srt,
    render_srt, srt_time, validate_translations, write_srt,
)

EMPTY_SHA = hashlib.sha256(b"").hexdigest()
TWO_CUES = "1\n00:00:01,000 --> 00:00:02,500\nこんにちは\n\n2\n00:00:03,000 --> 00:00:04,000\nさようなら\n"


class EmptySrtTests(unittest.TestCase):
    def test_blank_inputs_yield_zero_cues(self):
        for text in ("", " \n\t\n", "﻿", "﻿\r\n\r\n"):
            with self.subTest(text=text):
                self.assertEqual(parse_srt(text).cues, ())

    def test_read_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.srt"
            path.write_bytes(b"")
            document = read_srt(path)
        self.assertEqual(document.cues, ())
        self.assertEqual(document.source_sha256, EMPTY_SHA)
        self.assertEqual(document.source_path, str(path.resolve()))

    def test_empty_format_render_and_write(self):
        self.assertEqual(format_srt([]), "")
        self.assertEqual(render_srt(parse_srt(""), {}), "")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.srt"
            write_srt("", path)
            self.assertEqual(path.read_bytes(), b"")
            self.assertEqual(read_srt(path).cues, ())


class TimeTests(unittest.TestCase):
    def test_milliseconds_rounds_half_up_not_bankers(self):
        # (秒, 期望毫秒, Python round 的结果)；半毫秒处两者不同
        for seconds, expected, banker in [
            (0.0005, 1, 0), (0.0025, 3, 2), (1.2345, 1235, 1234), (0.0015, 2, 2),
            (0, 0, 0), (7199.9995, 7200000, 7200000),
        ]:
            with self.subTest(seconds=seconds):
                self.assertEqual(milliseconds(seconds), expected)
                self.assertEqual(milliseconds(seconds), math.floor(seconds * 1000 + 0.5))
                self.assertEqual(round(seconds * 1000), banker)

    def test_srt_time_formats(self):
        self.assertEqual(srt_time(0), "00:00:00,000")
        self.assertEqual(srt_time(3_723_004), "01:02:03,004")
        self.assertEqual(srt_time(100 * 3_600_000 + 1), "100:00:00,001")

    def test_srt_time_rejects_negative_and_non_int(self):
        for bad in (-1, 1.0, "1", True, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                srt_time(bad)


class FormatTests(unittest.TestCase):
    def test_numbering_and_time_lines(self):
        text = format_srt([(0.0, 1.5, "一"), (3723.004, 3724, "二\n行")])
        self.assertEqual(
            text,
            "1\n00:00:00,000 --> 00:00:01,500\n一\n\n2\n01:02:03,004 --> 01:02:04,000\n二\n行\n",
        )
        self.assertEqual([c.index for c in parse_srt(text).cues], [1, 2])

    def test_rejects_non_positive_rounded_duration(self):
        for entry in [(1.0001, 1.0004, "a"), (2.0, 1.0, "a"), (-1.0, 1.0, "a")]:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                format_srt([entry])

    def test_rejects_empty_or_blank_line_text(self):
        for text in ("", "  \n", "a\n\nb", "a\r\n \r\nb", None):
            with self.subTest(text=text), self.assertRaises(ValueError):
                format_srt([(0.0, 1.0, text)])

    def test_crlf_text_is_normalized(self):
        text = format_srt([(0.0, 1.0, "a\r\nb\rc")])
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("a\nb\nc\n"))

    def test_output_is_utf8_without_bom_and_lf(self):
        text = format_srt([(0.0, 1.0, "日本語の字幕")])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.srt"
            write_srt(text, path)
            raw = path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        self.assertEqual(raw.decode("utf-8"), text)


class ParseStrictnessTests(unittest.TestCase):
    def test_parse_keeps_original_fields(self):
        cue = parse_srt("﻿007\r\n00:00:01,200\t-->  00:00:03,450\r\nはい\r\n").cues[0]
        self.assertEqual((cue.index, cue.index_text, cue.start_ms, cue.end_ms), (7, "007", 1200, 3450))
        self.assertEqual(cue.time_line, "00:00:01,200\t-->  00:00:03,450")

    def test_rejects_malformed_input(self):
        good = "00:00:01,000 --> 00:00:02,000"
        for name, text in {
            "duplicate index": f"1\n{good}\na\n\n1\n{good}\nb\n",
            "zero index": f"0\n{good}\na\n",
            "bad time line": "1\n00:00:01.000 --> 00:00:02,000\na\n",
            "equal times": "1\n00:00:01,000 --> 00:00:01,000\na\n",
            "end before start": "1\n00:00:02,000 --> 00:00:01,000\na\n",
            "missing text": f"1\n{good}\n",
            "blank text line": f"1\n{good}\na\n \nb\n",
            "non-numeric index": f"x\n{good}\na\n",
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_srt(text)

    def test_bad_sha_rejected(self):
        with self.assertRaises(ValueError):
            parse_srt("", source_sha256="ABC")

    def test_read_sha_is_over_raw_bytes_and_tolerates_bom(self):
        raw = b"\xef\xbb\xbf" + TWO_CUES.replace("\n", "\r\n").encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "in.srt"
            path.write_bytes(raw)
            document = read_srt(path)
        self.assertEqual(document.source_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual([c.text for c in document.cues], ["こんにちは", "さようなら"])


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.document = parse_srt(TWO_CUES)
        self.ids = [cue.id for cue in self.document.cues]

    def test_render_keeps_index_and_time_lines_and_multiline(self):
        text = render_srt(self.document, {self.ids[0]: "Hello", self.ids[1]: "Good\r\nbye"})
        self.assertEqual(
            text,
            "1\n00:00:01,000 --> 00:00:02,500\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nGood\nbye\n",
        )

    def test_incomplete_translations_raise_with_report(self):
        for name, mapping, key, expected in [
            ("missing", {self.ids[0]: "a"}, "missing_ids", [self.ids[1]]),
            ("unexpected", {self.ids[0]: "a", self.ids[1]: "b", "zzz": "c"}, "unexpected_ids", ["zzz"]),
            ("empty", {self.ids[0]: "a", self.ids[1]: "  "}, "invalid",
             [{"id": self.ids[1], "reason": "empty_or_nonstring_text"}]),
            ("blank line", {self.ids[0]: "a\n\nb", self.ids[1]: "b"}, "invalid",
             [{"id": self.ids[0], "reason": "blank_text_line_would_break_srt"}]),
        ]:
            with self.subTest(name), self.assertRaises(IncompleteTranslationError) as ctx:
                render_srt(self.document, mapping)
            self.assertEqual(ctx.exception.report[key], expected)
            self.assertEqual(ctx.exception.report["status"], "partial")

    def test_validate_complete_report(self):
        report = validate_translations(self.document, dict.fromkeys(self.ids, "x"))
        self.assertEqual(report["status"], "complete")
        self.assertEqual((report["expected_count"], report["valid_count"]), (2, 2))
        self.assertEqual(report["source_sha256"], self.document.source_sha256)

    def test_non_string_translation_is_invalid(self):
        report = validate_translations(self.document, {self.ids[0]: None, self.ids[1]: "b"})
        self.assertEqual(report["invalid"], [{"id": self.ids[0], "reason": "empty_or_nonstring_text"}])
        self.assertEqual(report["valid_count"], 1)


class WriteTests(unittest.TestCase):
    def test_refuses_to_overwrite_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "in.srt"
            path.write_text(TWO_CUES, encoding="utf-8")
            document = read_srt(path)
            with self.assertRaises(ValueError):
                write_srt("x\n", path, source=document)
            self.assertEqual(path.read_text(encoding="utf-8"), TWO_CUES)

    def test_overwrites_other_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, other = Path(tmp) / "in.srt", Path(tmp) / "out.srt"
            source.write_text(TWO_CUES, encoding="utf-8")
            other.write_text("old", encoding="utf-8")
            write_srt("新しい\n", other, source=read_srt(source))
            self.assertEqual(other.read_text(encoding="utf-8"), "新しい\n")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["in.srt", "out.srt"])


if __name__ == "__main__":
    unittest.main()
