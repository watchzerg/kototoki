"""kototoki.schema 的离线测试：validate_transcript、validate_windows、validate_units。"""

import unittest

from kototoki.schema import validate_transcript, validate_units, validate_windows

SR = 16000


def unit_doc(units, text="日本", offset=10.0, duration=5.0):
    return {"text": text, "offset_s": offset, "duration_seconds": duration, "units": units}


def timed(char_start, char_end, start, end, status="ok"):
    return {"char_start": char_start, "char_end": char_end, "start": start, "end": end, "status": status}


def text_only(char_start, char_end):
    return {"char_start": char_start, "char_end": char_end, "start": None, "end": None, "status": "text_only"}


def window(start_sample, end_sample, segments=None):
    start, end = start_sample / SR, end_sample / SR
    return {"start": start, "end": end, "start_sample": start_sample, "end_sample": end_sample,
            "segments": [[start, end]] if segments is None else segments}


class ValidateTranscriptTests(unittest.TestCase):
    def test_rejects_wrong_schema_version_or_missing_text(self):
        for document in ({"text": "a"}, {"schema_version": 2, "text": "a"},
                         {"schema_version": 1}, {"schema_version": 1, "text": None}):
            with self.subTest(document=document), self.assertRaises(ValueError):
                validate_transcript(document)



class ValidateWindowsTests(unittest.TestCase):
    def test_accepts_exact_windows_and_empty_list(self):
        validate_windows([], 0)
        validate_windows([window(0, 480000), window(480000, 481001)], 481001)
        validate_windows([window(1000, 2000, segments=[])], 3000)
        validate_windows([window(0, 32000, segments=[[0.0, 0.5], [1.0, 2.0]])], 32000)

    def test_rejects_overlap_and_disorder(self):
        with self.assertRaises(ValueError):
            validate_windows([window(0, 2000), window(1999, 3000)], 4000)
        with self.assertRaises(ValueError):
            validate_windows([window(2000, 3000), window(0, 1000)], 4000)

    def test_rejects_window_over_480000_samples(self):
        with self.assertRaises(ValueError):
            validate_windows([window(0, 480001)], 600000)



class ValidateUnitsTests(unittest.TestCase):
    """units 是 WAV 本地秒：`unit_doc` 的 `offset_s` 为 10，范围仍是 [0, duration]。"""

    def test_accepts_exact_coverage_with_timed_units(self):
        validate_units(unit_doc([timed(0, 1, 0.0, 1.0), timed(1, 2, 1.0, 2.0)]))

    def test_text_only_units_need_no_times(self):
        validate_units(unit_doc([text_only(0, 1), timed(1, 2, 1.0, 2.0)]))
        validate_units(unit_doc([text_only(0, 1), text_only(1, 2)]))

    def test_missing_coverage_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_units(unit_doc([timed(0, 1, 0.0, 1.0)]))
        with self.assertRaises(ValueError):
            validate_units(unit_doc([]))

    def test_duplicate_coverage_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_units(unit_doc([timed(0, 2, 0.0, 2.0), text_only(1, 2)]))
        with self.assertRaises(ValueError):
            validate_units(unit_doc([text_only(0, 1), text_only(0, 1), text_only(1, 2)]))

    def test_timed_unit_outside_source_range_is_rejected(self):
        for start, end in ((-0.1, 1.0), (0.0, 5.01), (2.0, 1.0), (10.0, 11.0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                validate_units(unit_doc([timed(0, 1, start, end), text_only(1, 2)]))
