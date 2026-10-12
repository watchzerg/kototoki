"""GPU-free checks for faithful timing/text mapping."""
import unittest
import contextlib
import io
from pathlib import Path
import tempfile
from unittest.mock import patch
from run_qwen import ASR_SHA256, evaluation_schema, main, parser, verified_checkpoints


class MappingTests(unittest.TestCase):
    def test_asr_only_preserves_default_asr_parameters(self):
        flags = ["--audio", "a.wav", "--output", "o.json", "--asr-model", "asr", "--aligner-model", "unused"]
        default = parser().parse_args(flags)
        asr_only = parser().parse_args(flags + ["--asr-only"])
        self.assertFalse(default.asr_only)
        self.assertTrue(asr_only.asr_only)
        for name in ["language", "dtype", "attention", "max_new_tokens", "window_seconds", "offset"]:
            self.assertEqual(getattr(asr_only, name), getattr(default, name))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(flags + ["--asr-only", "--alignment-only", "text.txt"])

    def test_asr_only_never_verifies_unused_aligner(self):
        with tempfile.TemporaryDirectory() as temp:
            asr = Path(temp)
            with patch("run_qwen.checkpoint_identity", return_value={"verified": "asr"}) as verify:
                result = verified_checkpoints(asr, asr / "absent-aligner", True)
            verify.assert_called_once_with(asr, ASR_SHA256)
            self.assertEqual(result, {"asr": {"verified": "asr"}})
            with self.assertRaises(ValueError):
                verified_checkpoints(asr, asr / "absent-aligner", False)

    def test_asr_only_text_does_not_invent_alignment(self):
        result = evaluation_schema("前、後。", [], 10., time_source="native")
        self.assertEqual(result["text"], "前、後。")
        self.assertEqual([(u["char_start"], u["char_end"]) for u in result["units"]], [(0, 1), (2, 3)])
        for unit in result["units"]:
            self.assertEqual(unit["status"], "text_only")
            self.assertEqual(unit["time_source"], "native")
            self.assertIsNone(unit["start"])
            self.assertIsNone(unit["end"])

    def test_punctuation_and_offset(self):
        result = evaluation_schema("今日は、晴れ。", [
            {"text": "今日", "start_time": 0.1, "end_time": 0.5},
            {"text": "は", "start_time": 0.5, "end_time": 0.7},
            {"text": "晴れ", "start_time": 0.9, "end_time": 1.2}], 10)
        self.assertEqual(result["text"], "今日は、晴れ。")
        self.assertEqual([(x["char_start"], x["char_end"]) for x in result["units"]], [(0, 2), (2, 3), (4, 6)])
        self.assertEqual(result["units"][2]["start"], 10.9)

    def test_unmapped_text_preserved(self):
        result = evaluation_schema("前後", [{"text": "後", "start_time": 1., "end_time": 2.}], 0)
        self.assertEqual(result["units"][0]["status"], "text_only")
        self.assertIsNone(result["units"][0]["start"])

    def test_invalid_time_not_repaired(self):
        result = evaluation_schema("音", [{"text": "音", "start_time": 2., "end_time": 1.}], 0)
        self.assertEqual(result["units"][0]["status"], "failed")
        self.assertIsNone(result["units"][0]["end"])

    def test_repetition_is_mapped_in_order(self):
        result = evaluation_schema("はいはい", [{"text": "はい", "start_time": s, "end_time": s + 0.5}
                                               for s in (0., 1.)], 0)
        self.assertEqual([x["char_start"] for x in result["units"]], [0, 2])

    def test_existing_result_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            result = Path(temp) / "result.json"
            result.write_text("prior evidence", encoding="utf-8")
            argv = ["run_qwen.py", "--audio", str(Path(temp) / "audio.wav"),
                    "--output", str(result), "--asr-model", temp, "--aligner-model", temp]
            with patch("sys.argv", argv), self.assertRaises(FileExistsError):
                main()
            self.assertEqual(result.read_text(encoding="utf-8"), "prior evidence")


if __name__ == "__main__":
    unittest.main()
