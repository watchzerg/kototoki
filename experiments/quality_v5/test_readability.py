import tempfile
import unittest
from pathlib import Path

from experiments.quality_v5 import readability as r


class ReadabilityTest(unittest.TestCase):
    def write(self, folder: Path, name: str, body: str) -> Path:
        path = folder / name
        path.write_bytes(body.encode("utf-8"))  # write_text 在 Windows 会把 \r\n 写成 \r\r\n
        return path

    def test_read_srt_keeps_lines_and_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write(Path(tmp), "a.srt", "1\r\n00:00:01,000 --> 00:00:03,500\r\n第一行\r\n第二行\r\n\r\n"
                                                  "2\r\n00:01:00,250 --> 00:01:01,000\r\n下一条\r\n")
            cues = r.read_srt(path)
        self.assertEqual(cues[0], {"start": 1.0, "end": 3.5, "lines": ["第一行", "第二行"]})
        self.assertAlmostEqual(cues[1]["start"], 60.25)

    def test_lengths(self):
        self.assertEqual(r.visible_len("你好， 世界！"), 6)
        self.assertEqual(r.lexical_len("你好， 世界！A1"), 6)

    def test_percentile_and_histogram(self):
        self.assertEqual(r.percentile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertAlmostEqual(r.percentile([0, 10], 0.95), 9.5)
        self.assertEqual(r.histogram([1, 3, 9, 30], [3, 9]), [1, 1, 2])

    def test_zh_metrics_counts_thresholds(self):
        cues = [{"start": 0.0, "end": 1.0, "lines": ["一二三四五六七八九十"]},  # 10 cps
                {"start": 1.0, "end": 9.0, "lines": ["短"]},  # 8 s，超长
                {"start": 9.0, "end": 9.5, "lines": ["一二三四五六七八九十一二三四五六七"]}]  # 34 cps，0.5 s，17 字
        m = r.zh_metrics(cues)
        self.assertEqual(m["cps_over"]["9"]["count"], 2)
        self.assertEqual(m["cps_over"]["15"]["count"], 1)
        self.assertEqual(m["line_over"]["16"]["count"], 1)
        self.assertEqual(m["duration_over_max"]["count"], 1)
        self.assertEqual(m["duration_under_min"]["count"], 1)

    def test_film_report_pairs_ja_zh(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ja = self.write(folder, "ja.srt", "1\n00:00:00,000 --> 00:00:02,000\nこんにちは\n")
            zh = self.write(folder, "zh.srt", "1\n00:00:00,000 --> 00:00:02,000\n你好\n")
            bi = self.write(folder, "bi.srt", "1\n00:00:00,000 --> 00:00:02,000\nこんにちは\n你好\n")
            report = r.film_report(ja, zh, bi)
        self.assertAlmostEqual(report["zh_ja_lexical_ratio"]["p50"], 2 / 5)
        self.assertEqual(report["bilingual_lines_per_cue"]["max"], 2)
        self.assertEqual(report["bilingual_cues_over_2_lines"], 0)


if __name__ == "__main__":
    unittest.main()
