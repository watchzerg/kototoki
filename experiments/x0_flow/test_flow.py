"""Offline source sample and cross-stage full-text contracts."""
import unittest

from experiments.w0_demo.pipeline import run_pipeline
from .chunks import MAX_SAMPLES, energy_chunks, fixed_chunks, validate_sample_coverage
from .run import ROOT, ReplayAsr, private_output

try:
    import numpy as np
except ImportError:
    np = None


class ChunkTests(unittest.TestCase):
    def test_fixed_windows_cover_every_sample_once(self):
        for samples in (1, 16000, MAX_SAMPLES, MAX_SAMPLES + 1, MAX_SAMPLES * 10 + 123):
            with self.subTest(samples=samples):
                chunks = fixed_chunks(samples)
                self.assertEqual(chunks[0]["start_sample"], 0)
                self.assertEqual(chunks[-1]["end_sample"], samples)
                self.assertEqual(sum(c["end_sample"] - c["start_sample"] for c in chunks), samples)
                self.assertTrue(all(c["end_sample"] - c["start_sample"] <= MAX_SAMPLES for c in chunks))

    def test_invalid_samples_and_corrupt_plan_rejected(self):
        for samples in (0, -1, True, 1.5):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                fixed_chunks(samples)
        chunks = fixed_chunks(16000)
        chunks[0]["start_sample"] = 1
        with self.assertRaises(ValueError):
            validate_sample_coverage(chunks, 16000, retain_all=True)

    def test_inherited_unrepresentable_tail_fails_instead_of_sample_loss(self):
        with self.assertRaises(ValueError):
            fixed_chunks(1001)

    @unittest.skipIf(np is None, "NumPy is only provisioned in backend environment")
    def test_energy_minimum_and_latest_tie_preserve_complete_source(self):
        audio = np.ones(65 * 16000, dtype=np.float32)
        audio[27 * 16000:27 * 16000 + 1600] = 0
        chunks = energy_chunks(audio)
        self.assertEqual(chunks[0]["end_sample"], 27 * 16000 + 1600)
        validate_sample_coverage(chunks, len(audio), retain_all=True)
        for chunk in chunks[:-1]:
            self.assertGreaterEqual(chunk["end_sample"] - chunk["start_sample"], 25 * 16000)
            self.assertLessEqual(chunk["end_sample"] - chunk["start_sample"], 30 * 16000)
        silent = energy_chunks(np.zeros(61 * 16000, dtype=np.float32))
        self.assertEqual([c["end_sample"] for c in silent], [30 * 16000, 60 * 16000, 61 * 16000])

    @unittest.skipIf(np is None, "NumPy is only provisioned in backend environment")
    def test_short_tail_never_searches_or_removes_samples(self):
        for seconds in (1, 25, 30):
            audio = np.zeros(seconds * 16000, dtype=np.float32)
            self.assertEqual(energy_chunks(audio), fixed_chunks(len(audio)))
        with self.assertRaises(ValueError):
            energy_chunks(np.zeros(0, dtype=np.float32))


class StageContractTests(unittest.TestCase):
    def test_private_output_rejects_escape(self):
        self.assertEqual(private_output(ROOT / ".local/x0-flow/new"), ROOT / ".local/x0-flow/new")
        for path in (ROOT / "result", ROOT / ".local/x0-flow", ROOT / ".local/x0-flow/../../result"):
            with self.assertRaises(ValueError):
                private_output(path)

    def test_replay_checks_text_and_exact_frozen_bounds(self):
        chunks = fixed_chunks(16000)
        saved = {"text": "あ?", "original_segments": [{"start": 0., "end": 1., "text": "あ?"}],
                 "asr_traces": [], "effective_parameters": {}}
        replay = ReplayAsr(saved, chunks)
        self.assertEqual(replay.transcribe(None, chunks)[0][0]["text"], "あ?")
        with self.assertRaises(ValueError):
            replay.transcribe(None, [])
        saved["text"] = "あ"
        with self.assertRaises(ValueError):
            replay.transcribe(None, chunks)

    @unittest.skipIf(np is None, "NumPy is only provisioned in backend environment")
    def test_shared_pipeline_preserves_full_text_and_source_offset(self):
        from experiments.w0_demo.vad import FrozenVad
        from experiments.w0_demo.alignment import map_records

        chunks = fixed_chunks(16000)
        saved = {"text": "あ?", "original_segments": [{"start": 0., "end": 1., "text": "あ?"}],
                 "asr_traces": [], "effective_parameters": {}}
        class FakeMms:
            metadata = {"fake": True}
            def align(self, audio, segments, offset):
                return map_records(segments, [{"segment_index": 0, "frame_count": 10,
                    "window_start": 0., "window_end": 1., "tokens": [{"original_position": 0,
                        "lexical_interval_accepted": True, "start_frame": 1, "end_frame": 2,
                        "evidence_kind": "vocabulary_token"}]}], offset)
            def close(self):
                pass
        result = run_pipeline(np.zeros(16000, dtype=np.float32), FrozenVad(chunks),
                              lambda: ReplayAsr(saved, chunks), FakeMms, offset=123)
        self.assertEqual(result["text"], "あ?")
        self.assertEqual(result["units"][0]["start"], 123.1)
        self.assertEqual(result["units"][1]["status"], "text_only")
        self.assertEqual(result["original_segments"][0]["end"], chunks[0]["end"])


if __name__ == "__main__":
    unittest.main()
