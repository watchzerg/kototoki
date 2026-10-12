"""Synthetic display-contract tests independent of candidate model outputs."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("display_replay", Path(__file__).with_name("replay.py"))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)


def unit(left, right, start, end, **extra):
    return {"char_start": left, "char_end": right, "start": start, "end": end,
            "status": "ok", "time_source": "native", **extra}


def document(text, units, cues=None):
    return {"schema_version": 1, "text": text, "units": units, "cues": cues or []}


class DisplayContractTests(unittest.TestCase):
    def test_native_cue_split_merge_does_not_change_unified_cues(self):
        units = [unit(0, 5, 1, 1.3), unit(6, 11, 1.4, 1.8)]
        left = document("Hello world", units, [{"text": "Hello world", "start": 1, "end": 1.8}])
        right = document("Hello world", units, [{"text": "Hello", "start": 1, "end": 1.3},
                                                  {"text": "world", "start": 1.4, "end": 1.8}])
        srt_left, report_left = display.replay(left)
        srt_right, report_right = display.replay(right)
        self.assertEqual(srt_left, srt_right)
        self.assertEqual(report_left["unified_cues"], report_right["unified_cues"])
        self.assertEqual(report_left["coverage"]["rendered_character_fraction"], 1)

    def test_text_only_lexical_text_remains_visible_without_invented_time(self):
        text = "Hello lost world."
        data = document(text, [unit(0, 5, 1, 2), unit(6, 10, None, None, status="text_only"), unit(11, 16, 3, 4)])
        srt, report = display.replay(data)
        self.assertNotIn("lost", srt)
        self.assertEqual(report["original_text"], text)
        self.assertEqual("".join(r["text"] for r in report["unrendered_ranges"]), " lost ")
        self.assertEqual(report["unrenderable"][0]["reason"], "non_success_unit_status")
        self.assertEqual(sum(c["char_end"] - c["char_start"] for c in report["unified_cues"]) + report["coverage"]["unrendered_characters"], len(text))

    def test_no_hidden_time_clipping_or_repair(self):
        data = document("ABCDE", [unit(0, 1, -1, 1), unit(1, 2, 1, 1), unit(2, 3, 2, 20),
                                  unit(3, 4, 2.0001, 2.0002), unit(4, 5, 4, float("nan"))])
        srt, report = display.replay(data, source_start=0, source_end=10)
        self.assertEqual(srt, "")
        reasons = [item["reason"] for item in report["unrenderable"]]
        self.assertEqual(reasons, ["nonpositive_or_negative_time", "nonpositive_or_negative_time",
                                   "outside_declared_source_range", "millisecond_rounding_zero_duration", "missing_or_nonfinite_time"])
        self.assertEqual(report["original_units"][0]["start"], -1)
        self.assertEqual(report["original_units"][2]["end"], 20)
        self.assertEqual(report["original_units"][4]["end"], {"nonfinite_number": "nan"})
        json.dumps(report, allow_nan=False)

    def test_gap_and_punctuation_split_without_claiming_acoustic_silence(self):
        data = document("A.BC", [unit(0, 1, 1, 2), unit(2, 3, 2.1, 3), unit(3, 4, 3.5, 4)])
        _, report = display.replay(data)
        self.assertEqual([cue["text"] for cue in report["unified_cues"]], ["A.", "B", "C"])
        self.assertFalse(report["diagnostics"]["acoustic_silence_verified"])
        self.assertEqual(report["coverage"]["rendered_characters"], 4)

    def test_long_native_unit_is_flagged_without_truncation(self):
        text = "x" * 50
        _, report = display.replay(document(text, [unit(0, 50, 2, 12)]))
        cue = report["unified_cues"][0]
        self.assertEqual((cue["text"], cue["start"], cue["end"]), (text, 2, 12))
        self.assertEqual(report["diagnostics"]["unified"]["over_7_seconds_count"], 1)
        self.assertEqual(report["diagnostics"]["unified"]["over_42_characters_count"], 1)

    def test_overlapping_character_mapping_is_not_double_rendered(self):
        _, report = display.replay(document("ABC", [unit(0, 2, 1, 2), unit(1, 3, 2, 3)]))
        self.assertEqual(report["unified_cues"], [])
        self.assertEqual(report["coverage"]["unrendered_characters"], 3)
        self.assertEqual([item["reason"] for item in report["unrenderable"]], ["overlapping_character_ranges"] * 2)

    def test_native_time_overlap_is_preserved_and_reported(self):
        _, report = display.replay(document("A.B", [unit(0, 1, 1, 3), unit(2, 3, 2, 4)]))
        self.assertEqual([(cue["start"], cue["end"]) for cue in report["unified_cues"]], [(1, 3), (2, 4)])
        self.assertEqual(report["diagnostics"]["unified"]["overlap_count_in_original_order"], 1)
        self.assertEqual(report["diagnostics"]["predicted_unit_overlap_count"], 1)

    def test_empty_units_do_not_hide_the_full_transcript(self):
        srt, report = display.replay(document("Untimed words", []))
        self.assertEqual(srt, "")
        self.assertEqual(report["unrendered_ranges"], [{"char_start": 0, "char_end": 13, "text": "Untimed words"}])

    def test_original_blank_lines_are_not_silently_rewritten_into_valid_srt(self):
        text = "A\n\nB"
        srt, report = display.replay(document(text, [unit(0, 1, 1, 2), unit(3, 4, 2.1, 3)]))
        self.assertEqual(srt, "")
        self.assertEqual(report["original_text"], text)
        self.assertEqual(report["unrenderable"][0]["reason"], "srt_blank_line_in_original_text")

    def test_cli_replay_writes_private_srt_sidecar_and_refuses_overwrite(self):
        private_root = display.ROOT / ".local"
        private_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="display-synthetic-", dir=private_root) as temporary:
            root = Path(temporary)
            source = root / "input.json"
            source.write_text(json.dumps(document("Hello", [unit(0, 5, 10, 11)])), encoding="utf-8")
            prefix = root / "replay"
            command = [sys.executable, str(Path(__file__).with_name("replay.py")), "--input", str(source),
                       "--output-prefix", str(prefix), "--source-start", "10", "--source-end", "11"]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("00:00:10,000 --> 00:00:11,000", Path(str(prefix) + ".srt").read_text(encoding="utf-8"))
            report = json.loads(Path(str(prefix) + ".display.json").read_text(encoding="utf-8"))
            self.assertEqual(report["original_text"], "Hello")
            self.assertEqual(report["coverage"]["rendered_character_fraction"], 1)
            self.assertEqual(len(report["writer_source_sha256"]), 64)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertIn("Output already exists", second.stderr)


if __name__ == "__main__":
    unittest.main()
