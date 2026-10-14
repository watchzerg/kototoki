"""kototoki.schema 的离线测试：validate_transcript、validate_windows、validate_units。"""

import unittest

from kototoki.schema import validate_transcript, validate_units, validate_windows

SR = 16000


def transcript(**overrides):
    document = {"schema_version": 1, "text": "日本語",
                "units": [{"char_start": 0, "char_end": 3, "granularity": "word"}]}
    document.update(overrides)
    return document


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
    def test_accepts_minimal_and_full_documents(self):
        validate_transcript({"schema_version": 1, "text": ""})
        validate_transcript(transcript(source_start_seconds=1.0, source_end_seconds=4.0, duration_seconds=3))

    def test_rejects_wrong_schema_version_or_missing_text(self):
        for document in ({"text": "a"}, {"schema_version": 2, "text": "a"},
                         {"schema_version": 1}, {"schema_version": 1, "text": None}):
            with self.subTest(document=document), self.assertRaises(ValueError):
                validate_transcript(document)

    def test_rejects_bad_source_bounds(self):
        for overrides in ({"source_start_seconds": -1}, {"duration_seconds": float("nan")},
                          {"source_end_seconds": True}, {"source_start_seconds": "0"},
                          {"source_start_seconds": 5.0, "source_end_seconds": 4.0}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_transcript(transcript(**overrides))

    def test_unit_character_ranges_must_fit_text(self):
        bad = ({"char_start": 0, "char_end": 4}, {"char_start": -1, "char_end": 2},
               {"char_start": 2, "char_end": 2}, {"char_start": 0.0, "char_end": 2},
               {"char_start": 0})
        for unit in bad:
            with self.subTest(unit=unit), self.assertRaises(ValueError):
                validate_transcript(transcript(units=[{**unit, "granularity": "word"}]))

    def test_granularity_time_source_and_status_vocabularies(self):
        base = {"char_start": 0, "char_end": 1, "granularity": "character"}
        for granularity in ("word", "character", "segment"):
            validate_transcript(transcript(units=[{**base, "granularity": granularity}]))
        for source in ("native", "api", "fallback", "interpolated"):
            validate_transcript(transcript(units=[{**base, "time_source": source}]))
        for status in ("ok", "failed", "text_only"):
            validate_transcript(transcript(units=[{**base, "status": status}]))
        for extra in ({"granularity": "phoneme"}, {"granularity": None}, {"time_source": "guess"},
                      {"status": "done"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_transcript(transcript(units=[{**base, **extra}]))


class ValidateWindowsTests(unittest.TestCase):
    def test_accepts_exact_windows_and_empty_list(self):
        validate_windows([], 0)
        validate_windows([window(0, 480000), window(480000, 481001)], 481001)
        validate_windows([window(1000, 2000, segments=[])], 3000)
        validate_windows([window(0, 32000, segments=[[0.0, 0.5], [1.0, 2.0]])], 32000)

    def test_rejects_bool_or_float_samples(self):
        for key, value in (("start_sample", True), ("end_sample", 1600.0), ("start_sample", 0.0)):
            chunk = window(0, 1600)
            chunk[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_windows([chunk], 3200)

    def test_rejects_overlap_and_disorder(self):
        with self.assertRaises(ValueError):
            validate_windows([window(0, 2000), window(1999, 3000)], 4000)
        with self.assertRaises(ValueError):
            validate_windows([window(2000, 3000), window(0, 1000)], 4000)

    def test_adjacent_windows_are_allowed(self):
        validate_windows([window(0, 2000), window(2000, 3000)], 4000)

    def test_rejects_out_of_source_and_empty_windows(self):
        for chunk in (window(0, 4001), window(-1, 100), window(100, 100)):
            with self.subTest(chunk=chunk), self.assertRaises(ValueError):
                validate_windows([chunk], 4000)

    def test_rejects_window_over_480000_samples(self):
        with self.assertRaises(ValueError):
            validate_windows([window(0, 480001)], 600000)

    def test_rejects_seconds_not_matching_samples(self):
        for key, value in (("start", 0.5), ("end", 0.2), ("end", float("nan")), ("start", True)):
            chunk = window(0, 1600)
            chunk[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_windows([chunk], 3200)

    def test_rejects_segments_outside_window_or_unordered(self):
        bad_segments = ([[0.0, 0.2]], [[-0.01, 0.05]], [[0.05, 0.05]], [[0.06, 0.05]],
                        [[0.0, 0.05], [0.04, 0.08]], [[0.05, 0.08], [0.0, 0.04]], [[0.0]], [[0.0, float("inf")]])
        for segments in bad_segments:
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                validate_windows([window(0, 1600, segments=segments)], 3200)


class ValidateUnitsTests(unittest.TestCase):
    def test_accepts_exact_coverage_with_timed_units(self):
        validate_units(unit_doc([timed(0, 1, 10.0, 11.0), timed(1, 2, 11.0, 12.0)]))

    def test_accepts_one_unit_spanning_several_characters(self):
        validate_units(unit_doc([timed(0, 2, 10.0, 12.0)]))

    def test_text_only_units_need_no_times(self):
        validate_units(unit_doc([text_only(0, 1), timed(1, 2, 11.0, 12.0)]))
        validate_units(unit_doc([text_only(0, 1), text_only(1, 2)]))

    def test_empty_text_with_no_units_is_valid(self):
        validate_units(unit_doc([], text=""))

    def test_missing_coverage_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_units(unit_doc([timed(0, 1, 10.0, 11.0)]))
        with self.assertRaises(ValueError):
            validate_units(unit_doc([]))

    def test_duplicate_coverage_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_units(unit_doc([timed(0, 2, 10.0, 12.0), text_only(1, 2)]))
        with self.assertRaises(ValueError):
            validate_units(unit_doc([text_only(0, 1), text_only(0, 1), text_only(1, 2)]))

    def test_timed_unit_outside_source_range_is_rejected(self):
        for start, end in ((9.9, 11.0), (10.0, 15.01), (12.0, 11.0), (20.0, 21.0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                validate_units(unit_doc([timed(0, 1, start, end), text_only(1, 2)]))

    def test_end_slack_of_one_millisecond_is_allowed(self):
        validate_units(unit_doc([timed(0, 1, 10.0, 15.0), timed(1, 2, 14.0, 15.001)]))

    def test_timed_unit_without_finite_times_is_rejected(self):
        for start, end in ((None, None), (float("nan"), 11.0), (10.0, float("inf")), (True, 11.0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                validate_units(unit_doc([timed(0, 1, start, end), text_only(1, 2)]))


if __name__ == "__main__":
    unittest.main()
