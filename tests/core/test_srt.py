"""kototoki.srt 的离线测试：毫秒取整、格式化、严格解析、按译文渲染。"""

import math
import unittest

from kototoki.srt import IncompleteTranslationError, format_srt, milliseconds, parse_srt, render_srt

TWO_CUES = "1\n00:00:01,000 --> 00:00:02,500\nこんにちは\n\n2\n00:00:03,000 --> 00:00:04,000\nさようなら\n"


class TimeTests(unittest.TestCase):
    def test_milliseconds_rounds_half_up_not_bankers(self):
        # (秒, 期望毫秒, Python round 的结果)；半毫秒处两者不同
        for seconds, expected, banker in [
            (0.0005, 1, 0), (0.0025, 3, 2), (1.2345, 1235, 1234),
        ]:
            with self.subTest(seconds=seconds):
                self.assertEqual(milliseconds(seconds), expected)
                self.assertEqual(milliseconds(seconds), math.floor(seconds * 1000 + 0.5))
                self.assertEqual(round(seconds * 1000), banker)


class FormatTests(unittest.TestCase):
    def test_numbering_and_time_lines(self):
        text = format_srt([(0.0, 1.5, "一"), (3723.004, 3724, "二\n行")])
        self.assertEqual(
            text,
            "1\n00:00:00,000 --> 00:00:01,500\n一\n\n2\n01:02:03,004 --> 01:02:04,000\n二\n行\n",
        )
        self.assertEqual([c.index for c in parse_srt(text).cues], [1, 2])


class ParseStrictnessTests(unittest.TestCase):
    def test_rejects_malformed_input(self):
        good = "00:00:01,000 --> 00:00:02,000"
        for name, text in {
            "duplicate index": f"1\n{good}\na\n\n1\n{good}\nb\n",
            "end before start": "1\n00:00:02,000 --> 00:00:01,000\na\n",
        }.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_srt(text)


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
        ]:
            with self.subTest(name), self.assertRaises(IncompleteTranslationError) as ctx:
                render_srt(self.document, mapping)
            self.assertEqual(ctx.exception.report[key], expected)
            self.assertEqual(ctx.exception.report["status"], "partial")

if __name__ == "__main__":
    unittest.main()
