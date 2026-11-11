"""内嵌字幕清洗（`kototoki.embedded.clean`）：输入取 ffmpeg n9.0.2 `-c:s srt -f srt` 对 ASS／SubRip 轨的实际输出形态。

用真实 ffmpeg 抽轨再清洗的测试属于 full 层，在 `tests/full/test_job_ffmpeg.py`。
"""

from __future__ import annotations

import unittest

from kototoki import embedded, srt


def block(index: int, start: str, end: str, *lines: str) -> str:
    return "\n".join((str(index), f"{start} --> {end}", *lines)) + "\n"


class CleanTests(unittest.TestCase):
    def cues(self, text: str) -> list[tuple[int, int, str]]:
        cleaned, stats = embedded.clean(text)
        document = srt.parse_srt(cleaned)  # 清洗结果必须过产品的严格解析
        self.assertEqual(stats["cues"], len(document.cues))
        self.assertEqual([cue.index for cue in document.cues], list(range(1, len(document.cues) + 1)))
        return [(cue.start_ms, cue.end_ms, cue.text) for cue in document.cues]

    def test_ass_tags_are_stripped_and_lines_joined(self) -> None:
        text = "\n".join((
            block(1, "00:00:00,500", "00:00:01,500",
                  '<font size="60">{\\an8}<font size="40">こんにちは', "世界</font></font>"),
            block(2, "00:00:01,600", "00:00:02,200",
                  '<font size="60"><i>斜体</i>と<font color="#ff0000">色</font></font><font size="60">\\hです</font>'),
        ))
        self.assertEqual(self.cues(text), [(500, 1500, "こんにちは 世界"), (1600, 2200, "斜体と色 です")])

    def test_subrip_markup_and_literal_brackets_survive_selectively(self) -> None:
        text = block(1, "00:00:00,500", "00:00:01,500", "<i>こんにちは</i>", "二行目") + "\n" + \
            block(2, "00:00:01,600", "00:00:02,400", "（ドアの音）<3 {笑}")
        # 听障说明、不是标签的尖括号与不以反斜杠开头的花括号原样保留
        self.assertEqual(self.cues(text), [(500, 1500, "こんにちは 二行目"), (1600, 2400, "（ドアの音）<3 {笑}")])

    def test_empty_drawing_invalid_and_duplicate_cues_are_dropped(self) -> None:
        text = "\n".join((
            block(1, "00:00:01,000", "00:00:02,000", "<font size=\"60\">台詞</font>"),
            block(2, "00:00:01,000", "00:00:02,000", "台詞"),                                    # 去标签后重复
            block(3, "00:00:02,300", "00:00:02,800", '<font size="40">{\\an8}m 0 0 l 100 0 100 100 0 100</font>'),
            block(4, "00:00:02,850", "00:00:02,950", '<font size="60"></font>'),
            block(5, "00:00:03,000", "00:00:03,000", "時間なし"),
            block(6, "00:00:01,000", "00:00:02,500", "台詞"),                                    # 时间不同：不是重复
        ))
        cleaned, stats = embedded.clean(text)
        self.assertEqual(stats, {"source_cues": 6, "cues": 2, "dropped_empty": 1, "dropped_drawing": 1,
                                 "dropped_invalid_time": 1, "dropped_duplicate": 1})
        self.assertEqual(self.cues(text), [(1000, 2000, "台詞"), (1000, 2500, "台詞")])

    def test_cues_are_sorted_by_time_and_renumbered(self) -> None:
        text = block(7, "00:00:05,000", "00:00:06,000", "後") + "\n" + block(3, "00:00:01,000", "00:00:02,000", "前")
        self.assertEqual(self.cues(text), [(1000, 2000, "前"), (5000, 6000, "後")])

    def test_blank_lines_inside_a_cue_and_crlf_do_not_split_it(self) -> None:
        text = "﻿1\r\n00:00:01,000 --> 00:00:02,000\r\n一行目\r\n\r\n二行目\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\n次\r\n"
        self.assertEqual(self.cues(text), [(1000, 2000, "一行目 二行目"), (3000, 4000, "次")])

    def test_a_number_line_inside_text_is_not_a_cue_head(self) -> None:
        text = block(1, "00:00:01,000", "00:00:02,000", "2", "人") + "\n" + block(2, "00:00:03,000", "00:00:04,000", "次")
        self.assertEqual(self.cues(text), [(1000, 2000, "2 人"), (3000, 4000, "次")])

    def test_nothing_usable_gives_empty_text(self) -> None:
        for text in ("", "\n\n", "not a subtitle", block(1, "00:00:01,000", "00:00:02,000", "<i></i>")):
            cleaned, stats = embedded.clean(text)
            self.assertEqual((cleaned, stats["cues"]), ("", 0))


if __name__ == "__main__":
    unittest.main()
