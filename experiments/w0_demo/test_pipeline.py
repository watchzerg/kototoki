"""Offline contract tests with fake engines, without model imports."""
import json
from pathlib import Path
import tempfile
import unittest

from experiments.w0_demo.pipeline import run_pipeline, validate_chunks
from experiments.w0_demo.run import ROOT, frozen_chunks, gpu_lock, private_output


class FakeVad:
    metadata = {"adapter": "fake"}
    def segment(self, audio):
        return [{"start": 0., "end": 1., "segments": [(0., 1.)]}]


class PipelineTests(unittest.TestCase):
    def test_private_output_cannot_escape_ignored_root(self):
        self.assertEqual(private_output(ROOT / ".local/w0-demo/new-run"), ROOT / ".local/w0-demo/new-run")
        for path in (ROOT / "results/new-run", ROOT / ".local/w0-demo", ROOT / ".local/w0-demo/../../exposed"):
            with self.assertRaises(ValueError): private_output(path)

    def test_sequential_residency_and_complete_text(self):
        events = []
        class Asr:
            metadata = {}
            def __init__(self): events.append("asr_load")
            def transcribe(self, audio, chunks):
                events.append("asr")
                return [{"text": "あ?", "start": 0., "end": 1.}], []
            def close(self): events.append("asr_close")
        class Aligner:
            metadata = {}
            def __init__(self): events.append("mms_load")
            def align(self, audio, segments, offset):
                return {"text": "あ?", "units": [
                    {"char_start": 0, "char_end": 1, "start": offset + .1, "end": offset + .2,
                     "status": "ok", "granularity": "character", "time_source": "api"},
                    {"char_start": 1, "char_end": 2, "start": None, "end": None,
                     "status": "text_only", "granularity": "character", "time_source": "fallback"}],
                    "records": [], "derived_segments": []}
            def close(self): events.append("mms_close")
        result = run_pipeline(range(16000), FakeVad(), Asr, Aligner, offset=5)
        self.assertEqual(result["text"], "あ?")
        self.assertEqual(result["units"][0]["start"], 5.1)
        self.assertEqual(events, ["asr_load", "asr", "asr_close", "mms_load", "mms_close"])

    def test_silence_does_not_load_other_models(self):
        class Silent(FakeVad):
            def segment(self, audio): return []
        def unexpected(): self.fail("Model loaded for empty speech")
        result = run_pipeline(range(16000), Silent(), unexpected, unexpected)
        self.assertEqual((result["text"], result["units"]), ("", []))

    def test_asr_failure_releases_model_without_loading_mms(self):
        events = []
        class FailingAsr:
            metadata = {}
            def transcribe(self, audio, chunks): raise RuntimeError("ASR failed")
            def close(self): events.append("closed")
        def unexpected(): self.fail("MMS loaded after ASR failure")
        with self.assertRaisesRegex(RuntimeError, "ASR failed"):
            run_pipeline(range(16000), FakeVad(), FailingAsr, unexpected)
        self.assertEqual(events, ["closed"])

    def test_alignment_cannot_drop_original_characters(self):
        class Asr:
            metadata = {}
            def transcribe(self, audio, chunks): return [{"text": "あ", "start": 0, "end": 1}], []
            def close(self): pass
        class BadAligner:
            metadata = {}
            def align(self, audio, segments, offset):
                return {"text": "あ", "units": [], "records": [], "derived_segments": []}
            def close(self): pass
        with self.assertRaisesRegex(ValueError, "every original character"):
            run_pipeline(range(16000), FakeVad(), Asr, BadAligner)

    def test_bad_chunks_fail_before_asr(self):
        for chunks in ([{"start": 0., "end": 31.}], [{"start": float("nan"), "end": 2.}],
                       [{"start": 0., "end": 5.}, {"start": 4., "end": 6.}]):
            with self.subTest(chunks=chunks), self.assertRaises(ValueError):
                validate_chunks(chunks, 40)

    def test_frozen_identity_and_offset_required(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "result.json"
            identity = {"pcm_sha256": "pcm", "file_sha256": "file"}
            path.write_text(json.dumps({"input": identity, "offset_s": 1, "chunks": []}))
            self.assertEqual(frozen_chunks(path, identity, 1), [])
            with self.assertRaises(ValueError): frozen_chunks(path, identity, 0)
            with self.assertRaises(ValueError): frozen_chunks(path, {**identity, "pcm_sha256": "wrong"}, 1)

    def test_gpu_lock_exclusive_and_released_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gpu.lock"
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                with gpu_lock(path):
                    with self.assertRaises(FileExistsError):
                        with gpu_lock(path): pass
                    raise RuntimeError("test failure")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
