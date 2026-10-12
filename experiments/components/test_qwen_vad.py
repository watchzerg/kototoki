"""Offline exact-sample, full-text, CUDA-evidence and no-overwrite bridge contracts."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from experiments.components.qwen_vad import (
    ASR_CONFIG_SHA256, ASR_ID, ASR_REVISION, ASR_SHA256, LOCAL,
    ctc_bridge, output_paths, transcribe_windows, validate_vad,
)
from experiments.components.separate import read_pcm

try:
    import numpy as np
except ModuleNotFoundError:
    np = None


class QwenVadFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / "元音声.wav"
        self.pcm = struct.pack("<100000h", *(index % 32767 for index in range(100000)))
        with wave.open(str(self.audio), "wb") as stream:
            stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            stream.writeframes(self.pcm)
        self.pcm, self.identity = read_pcm(self.audio)
        self.manifest = {"schema_version": 1, "status": "ok", "component": "pyannote-vad-speech-crops",
            "input": self.identity.copy(), "source_origin_s": 120, "source_origin_sample": 1920000,
            "device": {"actual": "cuda:0", "forward_evidence": {"count": 2,
                "input_devices": ["cuda:0"], "output_devices": ["cuda:0"]}},
            "chunks": [self.chunk(16001, 32002), self.chunk(80000, 96000)], "empty_speech": False,
            "config": {}, "model": {}, "timing": {}}

    def tearDown(self):
        self.temp.cleanup()

    def chunk(self, start, end):
        return {"start_sample": start, "end_sample_exclusive": end,
            "source_start_sample": 1920000 + start, "source_end_sample_exclusive": 1920000 + end,
            "source_offset_s": (1920000 + start) / 16000,
            "audio": {"pcm_sha256": hashlib.sha256(self.pcm[start * 2:end * 2]).hexdigest(),
                      "samples": end - start, "sample_rate": 16000, "channels": 1, "representation": "PCM16"}}

    def contract(self):
        return validate_vad(self.manifest, self.identity, self.pcm, 120)


class QwenVadTests(QwenVadFixture, unittest.TestCase):
    def test_exact_noncontiguous_samples_preserve_source_origin(self):
        intervals = self.contract()
        self.assertEqual(intervals[0]["start_sample"], 16001)
        self.assertEqual(intervals[0]["offset"], 121.0000625)
        self.assertEqual(intervals[1]["offset"], 125)
        self.assertNotEqual(intervals[0]["end_sample"], intervals[1]["start_sample"])

    def test_one_sample_interval_has_no_whisper_frame_grid_requirement(self):
        self.manifest["chunks"] = [self.chunk(3, 4)]
        self.assertEqual(self.contract()[0]["end_sample"], 4)

    def test_identity_cuda_and_origin_errors_are_rejected(self):
        mutations = [
            lambda m: m["input"].update(pcm_sha256="wrong"),
            lambda m: m["input"].update(file_sha256="wrong"),
            lambda m: m.update(source_origin_s=121),
            lambda m: m.update(source_origin_sample=1920001),
            lambda m: m["device"].update(actual="cpu"),
            lambda m: m["device"]["forward_evidence"].update(count=0),
            lambda m: m["device"]["forward_evidence"].update(input_devices=["cpu"]),
            lambda m: m["device"]["forward_evidence"].update(output_devices=["cpu"]),
            lambda m: m.update(status="failed"),
            lambda m: m.update(empty_speech=True),
            lambda m: m["chunks"][0]["audio"].update(pcm_sha256="wrong"),
            lambda m: m["chunks"][0].update(source_start_sample=1920000),
            lambda m: m["chunks"][0].update(source_offset_s=121),
        ]
        for mutation in mutations:
            changed = deepcopy(self.manifest)
            mutation(changed)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    validate_vad(changed, self.identity, self.pcm, 120)
        with self.assertRaises(ValueError):
            validate_vad(self.manifest, self.identity, self.pcm, 120.00001)

    def test_overlap_unsorted_and_invalid_bounds_rejected(self):
        for chunks in ([self.chunk(1, 20000), self.chunk(16000, 32000)],
                       [self.chunk(80000, 96000), self.chunk(1, 20000)],
                       [self.chunk(-1, 20000)], [self.chunk(99999, 100001)],
                       [self.chunk(1, 1)]):
            changed = deepcopy(self.manifest)
            changed["chunks"] = chunks
            with self.assertRaises(ValueError):
                validate_vad(changed, self.identity, self.pcm, 120)
        changed = deepcopy(self.manifest)
        changed["chunks"][0]["start_sample"] = True
        with self.assertRaises(ValueError):
            validate_vad(changed, self.identity, self.pcm, 120)

    def test_empty_vad_does_not_call_inference(self):
        self.manifest.update(chunks=[], empty_speech=True)
        intervals = self.contract()
        def forbidden(audio):
            raise AssertionError("An empty VAD must not run full-input ASR")
        self.assertEqual(transcribe_windows(object(), intervals, forbidden), [])

    def test_fake_inference_slices_same_original_and_preserves_full_text_and_partial(self):
        class Audio:
            def __init__(self, content):
                self.content = content
            def __getitem__(self, bounds):
                return Audio(self.content[bounds])
            def tobytes(self):
                return self.content
        audio = Audio(bytes(index % 256 for index in range(100000)))
        calls, checkpoints = [], []
        texts = [" 前、\n", "後! "]
        def infer(crop):
            calls.append(crop.tobytes())
            return {"text": texts[len(calls) - 1], "raw_asr": "unchanged", "token_limit_reached": False}
        windows = transcribe_windows(audio, self.contract(), infer,
                                     lambda current: checkpoints.append("".join(w["text"] for w in current)))
        self.assertEqual(calls, [audio.content[16001:32002], audio.content[80000:96000]])
        self.assertEqual("".join(w["text"] for w in windows), " 前、\n後! ")
        self.assertEqual(checkpoints, [" 前、\n", " 前、\n後! "])
        self.assertEqual(windows[1]["offset"], 125)

    def test_outputs_distinct_private_and_never_overwritten(self):
        raw, bridge = LOCAL / "qwen-vad-contract/raw.json", LOCAL / "qwen-vad-contract/bridge.json"
        self.assertEqual(output_paths(raw, bridge, self.audio, self.root / "manifest.json"),
                         (raw.resolve(), bridge.resolve()))
        with self.assertRaises(ValueError):
            output_paths(raw, raw, self.audio, self.root / "manifest.json")
        with self.assertRaises(ValueError):
            output_paths(self.root / "raw.json", bridge, self.audio, self.root / "manifest.json")
        with self.assertRaises(ValueError):
            output_paths(raw.with_suffix(".wav"), bridge, self.audio, self.root / "manifest.json")
        with patch("experiments.components.qwen_vad.LOCAL", self.root):
            existing = self.root / "raw.json"
            existing.write_text("unchanged", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                output_paths(existing, self.root / "bridge.json", self.audio, self.root / "manifest.json")
            self.assertEqual(existing.read_text(encoding="utf-8"), "unchanged")


@unittest.skipUnless(np is not None, "Bridge integration requires numpy in the isolated Qwen environment")
class QwenVadBridgeTests(QwenVadFixture, unittest.TestCase):
    def source(self):
        waveform = np.frombuffer(self.pcm, dtype="<i2").astype(np.float32) / 32768
        evidence = {"parameter_devices": ["cuda:0"], "input_devices": {"input_ids": "cuda:0"},
                    "output_device": "cuda:0"}
        windows = [{**interval, "text": text, "raw_asr": text, "token_limit_reached": False,
                    "asr_input_evidence": deepcopy(evidence),
                    "pcm_sha256": hashlib.sha256(waveform[interval["start_sample"]:interval["end_sample"]].tobytes()).hexdigest()}
                   for interval, text in zip(self.contract(), [" 前、\n", "後! "])]
        self.source_path = self.root / "raw.json"
        return {"backend": "official-qwen-native-hf-vad", "status": "ok", "text": " 前、\n後! ",
                "source_start_seconds": 120, "cache_reused": False,
                "models": {"asr": {"id": ASR_ID, "revision": ASR_REVISION}},
                "checkpoint_file_sha256": {"asr": {"model.safetensors": ASR_SHA256, "config.json": ASR_CONFIG_SHA256}},
                "config": {"language": "ja", "dtype": "bfloat16", "attention": "sdpa", "max_new_tokens": 4096,
                           "do_sample": False, "batch_size": 1, "offset": 120, "asr_only": True,
                           "offline": True, "alignment_only": None},
                "input": {"sha256": self.identity["file_sha256"], "samples": self.identity["samples"],
                          "pcm_sha256": hashlib.sha256(waveform.tobytes()).hexdigest()},
                "windows": windows, "adapter_sha256": "synthetic", "generation_config": {}, "experimental_vad": {}}

    def bridge(self, source):
        self.source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
        return ctc_bridge(source, self.source_path, self.audio, self.pcm, self.identity, self.manifest, 120)

    def test_bridge_preserves_full_original_pcm_hash_noncontiguous_local_times_and_text(self):
        source = self.source()
        bridge = self.bridge(source)
        self.assertEqual(bridge["text"], source["text"])
        self.assertEqual(bridge["original_segments"], [
            {"start": 1.0000625, "end": 2.000125, "text": " 前、\n"},
            {"start": 5, "end": 6, "text": "後! "}])
        self.assertEqual(bridge["input"]["pcm_sha256"], self.identity["pcm_sha256"])
        self.assertEqual(bridge["input"]["samples"], 100000)
        self.assertEqual(bridge["offset_s"], 120)
        self.assertEqual(bridge["input"]["float32_pcm_sha256"], source["input"]["pcm_sha256"])
        self.assertFalse(bridge["provenance"]["reference_text_used"])
        self.assertTrue(bridge["provenance"]["new_asr_inference"])

    def test_generation_cap_keeps_text_but_cannot_export(self):
        source = self.source()
        source["windows"][0]["token_limit_reached"] = True
        text = source["text"]
        with self.assertRaisesRegex(ValueError, "Generation cap"):
            self.bridge(source)
        self.assertEqual(source["text"], text)
        self.assertEqual(json.loads(self.source_path.read_text(encoding="utf-8"))["text"], text)

    def test_bridge_rejects_identity_coordinate_text_or_device_mutation(self):
        mutations = [
            lambda s: s["input"].update(pcm_sha256="wrong"),
            lambda s: s["input"].update(sha256="wrong"),
            lambda s: s["windows"][0].update(pcm_sha256="wrong"),
            lambda s: s["windows"][0].update(offset=121),
            lambda s: s["windows"][0].update(start_sample=16000),
            lambda s: s["windows"][0]["asr_input_evidence"].update(output_device="cpu"),
            lambda s: s.update(text="lost text"),
            lambda s: s.update(source_start_seconds=121),
            lambda s: s["models"]["asr"].update(revision="wrong"),
            lambda s: s["config"].update(max_new_tokens=2048),
            lambda s: s.update(cache_reused=True),
            lambda s: s["windows"].pop(),
        ]
        for mutation in mutations:
            source = self.source()
            mutation(source)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    self.bridge(source)


if __name__ == "__main__":
    unittest.main()
