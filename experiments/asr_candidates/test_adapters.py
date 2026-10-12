"""Offline candidate identities, generation completion, and shared failure accounting."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.fullfilm_comparison.test_worker import Audio, FakeAligner, FakeAsr
from experiments.fullfilm_comparison import worker as shared
from experiments.x0_demo.chunks import make_chunk
from .adapters import MODEL_IDS, NativeAsr, generated_suffix, rnnt_completion, validate_job
from .worker import run_asr


class CandidateContractTests(unittest.TestCase):
    def test_exact_base_checkpoints_and_full_revisions(self):
        for candidate, model in MODEL_IDS.items():
            job = {"candidate_id": candidate, "model_id": model, "route": candidate,
                   "schema_version": 1, "model_revision": "a" * 40}
            validate_job(job)
            with self.assertRaises(ValueError):
                validate_job({**job, "model_revision": "main"})
            with self.assertRaises(ValueError):
                validate_job({**job, "model_id": model + "-plus"})
            with self.assertRaises(ValueError):
                validate_job({**job, "route": "X0"})

    def test_rnnt_does_not_inherit_a_text_token_cap(self):
        job = {"candidate_id": "nemotron", "model_id": MODEL_IDS["nemotron"],
               "route": "nemotron", "schema_version": 1, "model_revision": "a" * 40}
        with self.assertRaises(ValueError):
            validate_job({**job, "max_new_tokens": 1024})

    def test_decoder_prefix_is_verified_for_cohere_and_granite(self):
        self.assertEqual(generated_suffix([8, 9, 10, 3], [8, 9], None), [10, 3])
        self.assertEqual(generated_suffix([4, 8, 9, 10, 3], [8, 9], 4), [10, 3])
        with self.assertRaises(ValueError):
            generated_suffix([4, 8, 7, 10], [8, 9], 4)

    def test_rnnt_encoder_exhaustion_and_forced_advance(self):
        evidence = rnnt_completion([0, 2, 9, 2, 9], [0, 0, 1, 1, 1], 3, 9)
        self.assertTrue(evidence["encoder_exhausted"])
        self.assertEqual(evidence["forced_frame_advances"], 1)
        self.assertFalse(rnnt_completion([0, 9], [0, 1], 3, 9)["encoder_exhausted"])
        with self.assertRaises(ValueError):
            rnnt_completion([0, 9], [1, 1], 2, 9)

    def test_failed_capped_window_retains_partial_evidence_and_continues(self):
        root = shared.ROOT / ".local/tmp"
        root.mkdir(parents=True, exist_ok=True)
        audio = Audio(range(60))
        plan = {"chunks": [make_chunk(0, 20), make_chunk(20, 40), make_chunk(40, 60)],
                "offset_s": 0, "input": {}, "segmentation": "pyannote-current"}
        with tempfile.TemporaryDirectory(dir=root) as temp:
            out = Path(temp)
            (out / "chunks").mkdir()
            backend = FakeAsr(failure_index=1)
            saved = run_asr(audio, plan, "cohere", out, lambda: backend)
            self.assertEqual(saved["route"], "cohere")
            self.assertEqual(saved["candidate_id"], "cohere")
            self.assertTrue(saved["all_chunks_attempted"])
            self.assertEqual(saved["attempted_chunks"], 3)
            self.assertEqual(saved["asr_failed_chunk_indices"], [1])
            self.assertEqual(saved["failed_chunks"][0]["partial_segments"][0]["start_sample"], 20)
            self.assertEqual(saved["text"], "字0字2")
            self.assertTrue(backend.closed)
            shared.validate_asr(saved, plan, audio)
            align_out = out / "alignment"
            align_out.mkdir()
            (align_out / "chunks").mkdir()
            aligned = shared.run_alignment(audio, plan, saved, "cohere", align_out, FakeAligner)
            self.assertEqual(aligned["route"], "cohere")
            self.assertEqual(aligned["asr_failed_chunk_indices"], [1])
            self.assertEqual(aligned["text"], saved["text"])
            self.assertEqual(aligned["total_chunks"], 3)

    @unittest.skipUnless(importlib.util.find_spec("torch") and importlib.util.find_spec("numpy"), "optional native backend dependencies")
    def test_native_rnnt_keeps_repeated_tokens_and_uses_japanese_full_crop(self):
        import numpy as np
        import torch

        class Tensor:
            device = torch.device("cuda:0")
            ndim = 2

            def __init__(self, values):
                self.values = values
                self.shape = (1, len(values))

            def __getitem__(self, index):
                return self

            def detach(self):
                return self

            def cpu(self):
                return self

            def tolist(self):
                return self.values

        class Inputs(dict):
            def to(self, *_args):
                return self

        class Processor:
            def __init__(self):
                self.calls = []
                self.decode_calls = []
                self.tokenizer = SimpleNamespace(decode=lambda *_a, **_k: "incorrect collapsed text")

            def __call__(self, **kwargs):
                self.calls.append(kwargs)
                return Inputs(input_features=Tensor([0] * 8), attention_mask=torch.ones(1, 8))

            def decode(self, values, **kwargs):
                self.decode_calls.append((values, kwargs))
                return "ああ"

        processor = Processor()
        output = SimpleNamespace(sequences=Tensor([0, 5, 5, 9, 9]), durations=Tensor([0, 0, 0, 1, 1]))
        native = NativeAsr.__new__(NativeAsr)
        native.candidate, native.cap, native.dtype = "nemotron", None, torch.bfloat16
        native.metadata = {"language": "ja-JP"}
        native.processor = processor
        calls = []

        def generate(**kwargs):
            calls.append(kwargs)
            return output

        native.model = SimpleNamespace(generate=generate, config=SimpleNamespace(blank_token_id=9),
            encoder=SimpleNamespace(_get_subsampling_output_length=lambda _x: torch.tensor([2])))
        audio = np.linspace(-1, 1, 40, dtype=np.float32)
        audio.flags.writeable = False
        with patch("experiments.asr_candidates.adapters.gpu_evidence", return_value={}), \
                patch.object(torch.cuda, "synchronize"):
            segments, traces = native.transcribe(audio, [make_chunk(0, len(audio))])
        self.assertEqual(segments[0]["text"], "ああ")
        self.assertEqual(processor.calls[0]["language"], "ja-JP")
        np.testing.assert_array_equal(processor.calls[0]["audio"], audio)
        self.assertFalse(np.shares_memory(processor.calls[0]["audio"], audio))
        self.assertNotIn("max_new_tokens", calls[0])
        self.assertEqual(traces[0]["token_ids"], [5, 5, 9, 9])
        self.assertTrue(traces[0]["encoder_exhausted"])


if __name__ == "__main__":
    unittest.main()
