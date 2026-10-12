"""Offline failure accounting, integer windows, and canonical crop parity."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from experiments.fullfilm_comparison import worker
from experiments.x0_demo.chunks import make_chunk


class Audio:
    def __init__(self, values):
        self.values = list(values)

    def __len__(self):
        return len(self.values)

    def __getitem__(self, selection):
        return Audio(self.values[selection])

    def tobytes(self):
        return struct.pack(f"<{len(self.values)}f", *self.values)


class FakeAsr:
    def __init__(self, *, route="X0", failure_index=None, fatal=False):
        self.route, self.failure_index, self.fatal = route, failure_index, fatal
        self.metadata = {"device": "cuda", "model_files_sha256": {"model": "fake"}}
        self.calls = []
        self.closed = False

    def transcribe(self, audio, chunks, progress=None, *, retain_all=True):
        self.calls.append((len(audio), copy.deepcopy(chunks), audio.tobytes(), retain_all))
        index = len(self.calls) - 1
        self.assert_local(audio, chunks)
        segment = {**chunks[0], "text": f"字{index}"}
        trace = {"chunk_index": 0, "start_sample": 0, "end_sample": len(audio),
                 "token_ids": [index], "token_limit_reached": False}
        if index == self.failure_index:
            if self.fatal:
                raise RuntimeError("CUDA error: device-side assert triggered")
            if progress:
                trace.update(token_ids=list(range(4096)), generated_tokens=4096, token_limit_reached=True)
                progress([segment], [trace], self.metadata)
            raise ValueError("Qwen generation reached 4096-token cap; partial output retained")
        return [segment], [trace]

    @staticmethod
    def assert_local(audio, chunks):
        if chunks != [make_chunk(0, len(audio))]:
            raise AssertionError("Worker must pass one exact local crop")

    def close(self):
        self.closed = True


class FakeAligner:
    def __init__(self, *, failure_index=None, fatal=False):
        self.calls = []
        self.failure_index, self.fatal = failure_index, fatal
        self.metadata = {"model": "cuda:0", "dtype": "torch.float32"}
        self.closed = False

    def align(self, audio, segments, offset=0):
        from experiments.w0_demo.alignment import map_records
        self.calls.append((len(audio), copy.deepcopy(segments), audio.tobytes(), offset))
        segment = segments[0]
        count = len(segment["text"])
        record = {"segment_index": 0, "window_start": 0, "window_end": len(audio) / 16000,
            "window_start_sample": 0, "window_end_sample": len(audio), "frame_count": count * 4,
            "normalization": {"source_sample_start": 0, "source_sample_end": len(audio)},
            "tokens": [{"original_position": i, "start_frame": i * 4, "end_frame": i * 4 + 3,
                "lexical_interval_accepted": True, "evidence_kind": "vocabulary_token", "token_probability": .9}
                for i in range(count)], "failure": None}
        if len(self.calls) - 1 == self.failure_index:
            record.update(tokens=[], failure="CUDA illegal memory access" if self.fatal else "RuntimeError: CTC failure")
        return map_records(segments, [record], offset)

    def close(self):
        self.closed = True


class WorkerTest(unittest.TestCase):
    def setUp(self):
        root = worker.ROOT / ".local/tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.out = Path(self.temporary.name)
        (self.out / "chunks").mkdir()
        self.audio = Audio(range(80))
        self.chunks = [make_chunk(1, 11), make_chunk(20, 33), make_chunk(60, 80)]
        self.plan = {"chunks": self.chunks, "offset_s": 351.402125, "segmentation": "pyannote-current",
            "recipe": "fullfilm-test", "input": {"samples": 80}, "effective_parameters": {"frozen": True}}

    def tearDown(self):
        self.temporary.cleanup()

    def asr_result(self, model=None, route="X0"):
        return worker.run_asr(self.audio, self.plan, route, self.out, lambda: model or FakeAsr())

    def alignment_out(self):
        out = self.out / "alignment"
        out.mkdir()
        (out / "chunks").mkdir()
        return out

    def test_cap_preserves_partial_and_continues_exactly_once(self):
        model = FakeAsr(failure_index=1)
        created = []
        def factory():
            created.append(model)
            return model
        result = worker.run_asr(self.audio, self.plan, "X0", self.out, factory)
        self.assertEqual(len(created), 1)
        self.assertEqual(len(model.calls), 3)
        self.assertTrue(model.closed)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["all_chunks_attempted"])
        self.assertEqual(result["text"], "字0字2")
        self.assertEqual([s["chunk_index"] for s in result["original_segments"]], [0, 2])
        failure = result["failed_chunks"][0]
        self.assertEqual(failure["start_sample"], 20)
        self.assertEqual(failure["end_sample"], 33)
        self.assertEqual(failure["partial_segments"][0]["text"], "字1")
        self.assertEqual(len(failure["partial_traces"][0]["token_ids"]), 4096)
        self.assertEqual(failure["partial_traces"][0]["chunk_index"], 1)
        self.assertFalse(failure["partial_output_is_complete"])
        self.assertEqual(worker.read_json(self.out / "chunks/000001.json"), failure)
        worker.validate_asr(result, self.plan, self.audio)

    def test_w0_failure_continues_without_invented_partial_text(self):
        model = FakeAsr(route="W0", failure_index=1)
        result = self.asr_result(model, route="W0")
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(result["failed_chunks"][0]["partial_segments"], [])
        self.assertEqual(result["failed_chunks"][0]["partial_traces"], [])

    def test_model_initialization_failure_attempts_no_chunks(self):
        def failure():
            raise RuntimeError("model could not load")
        with self.assertRaises(worker.ModelInitializationError):
            worker.run_asr(self.audio, self.plan, "X0", self.out, failure)
        self.assertEqual(list((self.out / "chunks").iterdir()), [])

    def test_fatal_cuda_stops_context_but_retains_checkpoint(self):
        model = FakeAsr(failure_index=1, fatal=True)
        with self.assertRaises(worker.FatalCudaError):
            self.asr_result(model)
        self.assertEqual(len(model.calls), 2)
        self.assertTrue(model.closed)
        self.assertTrue((self.out / "chunks/000001.json").is_file())
        self.assertFalse((self.out / "chunks/000002.json").exists())

    def test_mms_aligns_remaining_complete_chunks_and_preserves_text_only(self):
        saved = self.asr_result(FakeAsr(failure_index=1))
        aligner = FakeAligner(failure_index=1)
        result = worker.run_alignment(self.audio, self.plan, saved, "X0", self.alignment_out(), lambda: aligner)
        self.assertEqual(result["text"], "字0字2")
        self.assertEqual(len(aligner.calls), 2)
        self.assertTrue(aligner.closed)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["asr_failed_chunk_indices"], [1])
        self.assertEqual(result["alignment_failed_chunk_indices"], [2])
        self.assertEqual(result["text_only_characters"], 2)
        self.assertEqual(result["alignment_records"][1]["normalization"]["source_sample_start"], 60)
        self.assertEqual(result["alignment_records"][1]["normalization"]["source_sample_end"], 80)
        self.assertGreaterEqual(result["units"][0]["start"], self.plan["offset_s"])
        self.assertEqual(result["effective_parameters"]["segmentation"], {"frozen": True})
        worker.validate_result(result)

    def test_mms_fatal_cuda_checkpoints_and_stops(self):
        saved = self.asr_result()
        aligner = FakeAligner(failure_index=1, fatal=True)
        out = self.alignment_out()
        with self.assertRaises(worker.FatalCudaError):
            worker.run_alignment(self.audio, self.plan, saved, "X0", out, lambda: aligner)
        self.assertEqual(len(aligner.calls), 2)
        self.assertTrue((out / "chunks/000001.json").exists())
        self.assertFalse((out / "chunks/000002.json").exists())

    def test_success_tokens_cannot_be_reclassified_from_capped_partial(self):
        saved = self.asr_result()
        saved["asr_traces"][1]["token_limit_reached"] = True
        with self.assertRaises(ValueError):
            worker.validate_asr(saved, self.plan, self.audio)

    def test_input_pcm_mismatch_is_rejected_before_alignment(self):
        saved = self.asr_result()
        saved["asr_traces"][0]["pcm_float32_sha256"] = "bad"
        with self.assertRaises(ValueError):
            worker.validate_asr(saved, self.plan, self.audio)

    def test_empty_vad_skips_both_model_factories(self):
        self.plan["chunks"] = []
        def forbidden():
            raise AssertionError("Empty VAD should not initialize a model")
        saved = worker.run_asr(self.audio, self.plan, "X0", self.out, forbidden)
        result = worker.run_alignment(self.audio, self.plan, saved, "X0", self.alignment_out(), forbidden)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["removed_samples"], 80)

    def test_atomic_checkpoint_rejects_overwrite_and_progress_replaces(self):
        path = self.out / "evidence.json"
        worker.atomic_json(path, {"a": 1})
        with self.assertRaises(FileExistsError):
            worker.atomic_json(path, {"a": 2})
        self.assertEqual(worker.read_json(path), {"a": 1})
        progress = self.out / "progress.json"
        worker.atomic_json(progress, {"a": 1}, replace=True)
        worker.atomic_json(progress, {"a": 2}, replace=True)
        self.assertEqual(worker.read_json(progress), {"a": 2})
        self.assertEqual(list(self.out.glob("*.writing")), [])

    def test_plan_input_source_identity_and_integer_boundaries_are_bound(self):
        audio_path = self.out / "audio.wav"
        audio_path.write_bytes(b"private synthetic identity")
        identity = {"path": str(audio_path.resolve()), "file_sha256": worker.sha256(audio_path),
            "pcm_sha256": "pcm", "sample_rate": 16000, "channels": 1, "samples": 80, "duration_s": 80 / 16000}
        plan = {**self.plan, "input": identity, "source_sha256": {}}
        path = self.out / "plan.json"
        worker.atomic_json(path, plan)
        job = {"schema_version": 1, "route": "X0", "plan_path": str(path), "plan_sha256": worker.sha256(path)}
        loaded, _, _ = worker.load_plan(job, lambda _: (self.audio, identity))
        self.assertEqual(loaded, plan)
        with self.assertRaises(ValueError):
            worker.load_plan(job, lambda _: (self.audio, {**identity, "pcm_sha256": "changed"}))
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            worker.load_plan(job, lambda _: (self.audio, identity))

    def test_frozen_source_change_is_rejected(self):
        path = self.out / "source.py"
        path.write_text("frozen", encoding="utf-8")
        source = {path.relative_to(worker.ROOT).as_posix(): worker.sha256(path)}
        worker.check_sources(source)
        path.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            worker.check_sources(source)

    def test_private_output_restriction(self):
        with self.assertRaises(ValueError):
            worker.private_output(worker.ROOT / ".local/fullfilm-comparison")
        with self.assertRaises(ValueError):
            worker.private_output(worker.ROOT / "experiments/fullfilm_comparison")


class CanonicalParityTest(unittest.TestCase):
    def setUp(self):
        try:
            import numpy as np
            import torch
        except ImportError:
            self.skipTest("Canonical numeric parity requires the provisioned NumPy/Torch environment")
        self.np, self.torch = np, torch
        root = worker.ROOT / ".local/tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=root)
        self.out = Path(self.temporary.name)
        (self.out / "chunks").mkdir()
        self.audio = np.sin(np.arange(50003, dtype=np.float32) * np.float32(.071))
        self.chunks = [make_chunk(1001, 18002), make_chunk(22003, 49004)]
        self.plan = {"chunks": self.chunks, "offset_s": 351.402125, "segmentation": "pyannote-current",
                     "input": {"samples": len(self.audio)}, "effective_parameters": {}}

    def tearDown(self):
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def test_whisper_crop_matches_canonical_global_pcm_features_tokens(self):
        from experiments.w0_demo.asr import WhisperAsr
        asr = WhisperAsr.__new__(WhisperAsr)
        asr._closed = False
        asr._model = object()
        asr._filters = self.torch.linspace(.01, .2, 128 * 201).reshape(128, 201)
        asr.options = {}
        asr.metadata = {"device": "cuda", "compute_type": "float16"}
        asr.close = lambda: None
        def generate(_model, _mel, _options):
            return {"text": "原文", "tokens": [1, 2], "prompt": [3], "kwargs": {"beam_size": 5}, "avg_logprob": -.2}
        with patch("experiments.w0_demo.asr.generate", generate):
            expected_segments, expected_traces = asr.transcribe(self.audio, self.chunks)
            result = worker.run_asr(self.audio, self.plan, "W0", self.out, lambda: asr)
        for index, (actual, expected) in enumerate(zip(result["original_segments"], expected_segments)):
            self.assertEqual({k: v for k, v in actual.items() if k != "chunk_index"}, expected)
            actual_trace, expected_trace = result["asr_traces"][index], expected_traces[index]
            for key in expected_trace:
                self.assertEqual(actual_trace[key], expected_trace[key])
            chunk = self.chunks[index]
            self.assertEqual(actual_trace["pcm_float32_sha256"], hashlib.sha256(
                self.audio[chunk["start_sample"]:chunk["end_sample"]].tobytes()).hexdigest())

    def test_mms_crop_matches_canonical_global_rounding_source_offset_and_records(self):
        from experiments.w0_demo.alignment import MmsAligner
        aligner = MmsAligner.__new__(MmsAligner)
        aligner.model = object()
        aligner.blank_id = 0
        aligner.metadata = {"model": "cuda:0"}
        aligner.close = lambda: None
        def fake_forward(audio, start, end, text, record):
            f1, f2 = record["window_start_sample"], record["window_end_sample"]
            data = audio[f1:f2]
            record.update(frame_count=17, pcm_sha256=hashlib.sha256(data.tobytes()).hexdigest(),
                normalization={"source_sample_start": f1, "source_sample_end": f2},
                tokens=[{"original_position": i, "start_frame": i * 4 + 1, "end_frame": i * 4 + 3,
                    "lexical_interval_accepted": i == 0, "evidence_kind": "vocabulary_token" if i == 0 else "wildcard",
                    "token_probability": .9} for i in range(len(text))])
        aligner._align_segment = fake_forward
        saved = worker.run_asr(self.audio, self.plan, "X0", self.out, lambda: FakeAsr())
        expected = aligner.align(self.audio, saved["original_segments"], self.plan["offset_s"])
        out = self.out / "align"
        out.mkdir()
        (out / "chunks").mkdir()
        actual = worker.run_alignment(self.audio, self.plan, saved, "X0", out, lambda: aligner)
        self.assertEqual(actual["text"], expected["text"])
        self.assertEqual(actual["units"], expected["units"])
        self.assertEqual(actual["derived_segments"], expected["derived_segments"])
        for actual_record, expected_record in zip(actual["alignment_records"], expected["records"]):
            self.assertEqual({k: v for k, v in actual_record.items() if k not in {"chunk_index", "attempt_wall_s"}}, expected_record)


if __name__ == "__main__":
    unittest.main()
