"""Offline public-contract checks with synthetic reference and PCM only."""

import argparse
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

SPEC = importlib.util.spec_from_file_location("corpus_prepare", Path(__file__).with_name("prepare.py"))
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


class CorpusPreparationTests(unittest.TestCase):
    def test_reference_labels_keep_dialogue_and_ambiguous_internals(self):
        spoken, removed, flags = prepare.strip_reference_labels("（Speaker）Hello (spoken aside)\n（Door noise）")
        self.assertEqual(spoken, "Hello (spoken aside)")
        self.assertEqual(removed, ["（Speaker）", "（Door noise）"])
        self.assertEqual(flags, ["internal_parenthetical_unreviewed"])

    def test_immutable_output_cannot_replace_previous_revision(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            prepare.write_immutable(path, {"revision": 1})
            prepare.write_immutable(path, {"revision": 1})
            with self.assertRaises(ValueError):
                prepare.write_immutable(path, {"revision": 2})
            self.assertEqual(json.loads(path.read_text()), {"revision": 1})

    def test_crop_sample_identity_and_source_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "audio").mkdir()
            full = root / "audio/fatestay-full.wav"
            samples = [i % 32767 for i in range(64000)]
            with wave.open(str(full), "wb") as output:
                output.setparams((1, 2, 16000, len(samples), "NONE", "not compressed"))
                output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
            args = argparse.Namespace(private_root=root)
            descriptor = prepare.crop(args, "synthetic", 12345, 54321)
            self.assertEqual(descriptor["samples"], 54321 - 12345)
            self.assertEqual(descriptor["source_start_seconds"], 12345 / 16000)
            self.assertEqual(descriptor["source_end_seconds"], 54321 / 16000)
            with wave.open(str(root / "audio/synthetic.wav"), "rb") as audio:
                self.assertEqual(audio.readframes(audio.getnframes()), struct.pack("<41976h", *samples[12345:54321]))
            self.assertEqual(prepare.crop(args, "synthetic", 12345, 54321), descriptor)
            with self.assertRaises(ValueError):
                prepare.crop(args, "synthetic", 0, 54321)
            with self.assertRaises(ValueError):
                prepare.crop(args, "beyond-source", 0, 64001)
            self.assertFalse((root / "audio/beyond-source.wav").exists())

    def test_source_coordinate_srt_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.srt"
            path.write_text("1\n01:02:03,456 --> 01:02:05,001\n（A）Hello\n", encoding="utf-8")
            span = prepare.parse_srt(path)[0]
            self.assertEqual((span["start"], span["end"]), (3723.456, 3725.001))
            self.assertEqual(span["text"], "Hello")
            self.assertFalse(span["acoustic_review"])


if __name__ == "__main__":
    unittest.main()
