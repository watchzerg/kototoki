"""Offline checks for fixed sample coordinates, edge uncertainty and identity."""

import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).parent))
SPEC = importlib.util.spec_from_file_location("round2_prepare", Path(__file__).with_name("prepare_round2.py"))
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


class Round2CorpusTests(unittest.TestCase):
    def test_fixed_sample_boundaries_and_duration(self):
        windows = prepare.fixed_windows(7200.001)
        self.assertEqual(len(windows), 6)
        self.assertEqual(windows[0]["source_start_sample"], round(7200.001 * .05 * 16000))
        self.assertTrue(all(w["source_end_sample"] - w["source_start_sample"] == 4800000 for w in windows))
        self.assertEqual(windows[-1]["source_start_seconds"], windows[-1]["source_start_sample"] / 16000)
        with self.assertRaises(ValueError):
            prepare.fixed_windows(1000)

    def test_overlap_cues_keep_unclipped_source_text_times(self):
        cues = [{"id": str(i), "start": start, "end": end, "text": "parser text",
                 "original_text": f"（A）Original {i}", "flags": [], "removed_prefix_labels": ["（A）"]}
                for i, (start, end) in enumerate([(8, 11), (11, 12), (19, 22), (1, 10), (20, 21)])]
        reference = prepare.window_reference(cues, 10, 20, "film", "window", "hash")
        self.assertEqual([s["id"] for s in reference["spans"]], ["film-0", "film-1", "film-2"])
        self.assertEqual([s["boundary_crossing"] for s in reference["spans"]], [True, False, True])
        self.assertEqual(reference["spans"][0]["start"], 8)
        self.assertEqual(reference["spans"][-1]["end"], 22)
        self.assertEqual(reference["spans"][0]["text"], "（A）Original 0")
        self.assertFalse(reference["acoustic_ground_truth"])

    def test_pcm_crop_and_manifest_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            full, cropped, descriptor = root / "full.wav", root / "crop.wav", root / "crop.json"
            pcm = struct.pack("<32000h", *(i % 32767 for i in range(32000)))
            with wave.open(str(full), "wb") as output:
                output.setparams((1, 2, 16000, 32000, "NONE", "not compressed"))
                output.writeframes(pcm)
            prepare.crop_pcm(full, cropped, 123, 30123)
            with wave.open(str(cropped), "rb") as audio:
                self.assertEqual(audio.readframes(audio.getnframes()), pcm[246:60246])
            info = prepare.describe_audio(cropped, 123 / 16000)
            prepare.write_immutable(descriptor, info)
            self.assertEqual(prepare.verify_existing_audio(cropped, descriptor, 123 / 16000), info)
            self.assertEqual(info["source_end_seconds"], 30123 / 16000)
            with self.assertRaises(ValueError):
                prepare.verify_existing_audio(cropped, descriptor, 0)
            with cropped.open("r+b") as stream:
                stream.seek(-2, 2)
                stream.write(b"\x01\x02")
            with self.assertRaises(ValueError):
                prepare.verify_existing_audio(cropped, descriptor, 123 / 16000)
            self.assertEqual(json.loads(descriptor.read_text()), info)
            with self.assertRaises(ValueError):
                prepare.crop_pcm(full, root / "invalid.wav", 0, 32001)
            self.assertFalse((root / "invalid.wav").exists())

    def test_source_hash_protection(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "reference.srt"
            source.write_bytes(b"original")
            frozen = prepare.sha256(source)
            self.assertEqual(prepare.require_hash(source, frozen), frozen)
            source.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                prepare.require_hash(source, frozen)


if __name__ == "__main__":
    unittest.main()
