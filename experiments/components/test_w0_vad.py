"""Offline clip provenance, empty input semantics, and output coordinate checks."""
from __future__ import annotations

from copy import deepcopy
import unittest

from experiments.components.w0_vad import transcribe_intervals, validate_vad
from experiments.whisper.run import evaluation


class W0VadTests(unittest.TestCase):
    def fixture(self):
        identity = {"file_sha256": "a" * 64, "pcm_sha256": "b" * 64, "samples": 160000,
                    "sample_rate": 16000, "channels": 1}
        manifest = {"status": "ok", "component": "pyannote-vad-speech-crops", "input": identity.copy(),
                    "source_origin_s": 120, "source_origin_sample": 1920000,
                    "device": {"actual": "cuda:0", "forward_evidence": {"count": 1,
                        "input_devices": ["cuda:0"], "output_devices": ["cuda:0"]}},
                    "config": {"onset": 0.5, "offset": 0.363, "chunk_size_s": 30,
                        "binarize_min_duration_on_s": 0, "binarize_min_duration_off_s": 0,
                        "native_padding_s": 0, "requested_crop_context_s": 0.2,
                        "concatenated_audio": False, "masking": False},
                    "chunks": [], "empty_speech": True}
        return manifest, identity

    def chunk(self, start=16000, end=32000):
        return {"start_sample": start, "end_sample_exclusive": end,
                "source_start_sample": 1920000 + start, "source_end_sample_exclusive": 1920000 + end,
                "source_offset_s": (1920000 + start) / 16000}

    def test_clips_preserve_original_coordinates_and_document_frame_rounding(self):
        manifest, identity = self.fixture()
        manifest.update(chunks=[self.chunk(16016, 32032), self.chunk(80000, 96000)], empty_speech=False)
        result = validate_vad(manifest, identity, 120)
        self.assertEqual(result["clip_timestamps"], [1.001, 2.002, 5, 6])
        self.assertEqual(result["intervals"][0]["source_start_sample"], 1936016)
        self.assertEqual(result["intervals"][0]["effective_seek_start_s"], 1)
        self.assertEqual(result["intervals"][0]["effective_seek_end_s"], 2)

    def test_wrong_audio_offset_and_cpu_evidence_are_rejected(self):
        manifest, identity = self.fixture()
        variants = []
        changed = deepcopy(manifest)
        changed["input"]["pcm_sha256"] = "c" * 64
        variants.append(changed)
        changed = deepcopy(manifest)
        changed["source_origin_s"] = 121
        variants.append(changed)
        changed = deepcopy(manifest)
        changed["device"]["actual"] = "cpu"
        variants.append(changed)
        changed = deepcopy(manifest)
        changed["device"]["forward_evidence"]["count"] = 0
        variants.append(changed)
        changed = deepcopy(manifest)
        changed["config"]["onset"] = 0.6
        variants.append(changed)
        for candidate in variants:
            with self.assertRaises(ValueError):
                validate_vad(candidate, identity, 120)

    def test_unsorted_overlapping_or_inconsistent_chunks_are_rejected(self):
        manifest, identity = self.fixture()
        for chunks in ([self.chunk(32000, 48000), self.chunk(16000, 32000)],
                       [self.chunk(), self.chunk(30000, 64000)], [self.chunk(3, 4)]):
            manifest.update(chunks=chunks, empty_speech=False)
            with self.assertRaises(ValueError):
                validate_vad(manifest, identity, 120)
        manifest.update(chunks=[self.chunk()], empty_speech=False)
        manifest["chunks"][0]["source_start_sample"] += 1
        with self.assertRaises(ValueError):
            validate_vad(manifest, identity, 120)

    def test_empty_vad_bypasses_asr_instead_of_transcribing_full_audio(self):
        class ForbiddenASR:
            def transcribe(self, *args, **kwargs):
                raise AssertionError("Empty clips must never call transcribe")
        original, info = transcribe_intervals(ForbiddenASR(), object(), [])
        self.assertEqual(original, [])
        self.assertIsNone(info)
        self.assertEqual(evaluation(original, original, 120),
                         {"schema_version": 1, "text": "", "units": [], "cues": []})

    def test_generator_is_consumed_and_native_times_are_offset_only_once(self):
        class FakeASR:
            def transcribe(self, waveform, **kwargs):
                self.options = kwargs
                yield_segment = {"text": "日本", "start": 5, "end": 6,
                                 "words": [{"word": "日本", "start": 5, "end": 6}]}
                return iter([yield_segment]), {"duration": 10}
        asr = FakeASR()
        original, info = transcribe_intervals(asr, object(), [5, 6])
        self.assertEqual(evaluation(original, original, 120)["units"][0]["start"], 125)
        self.assertNotIn("temperature", asr.options)
        self.assertFalse(asr.options["vad_filter"])
        self.assertFalse(asr.options["condition_on_previous_text"])
        self.assertEqual(info["duration"], 10)
        with self.assertRaises(ValueError):
            transcribe_intervals(asr, object(), [5])


if __name__ == "__main__":
    unittest.main()
