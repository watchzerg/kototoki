"""Privacy-free digital-silence preparation contract checks."""

from pathlib import Path
import tempfile
import unittest
import wave

from prepare_silence import prepare_silence


class SilencePreparationTests(unittest.TestCase):
    def test_zero_samples_manifest_and_reuse(self):
        private_root = Path(__file__).resolve().parents[2] / ".local"
        private_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="silence-test-", dir=private_root) as temporary:
            root = Path(temporary)
            manifest = prepare_silence(root)
            audio = root / "audio/synthetic-silence-10s.wav"
            with wave.open(str(audio), "rb") as source:
                self.assertEqual((source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()),
                                 (16000, 1, 2, 160000))
                self.assertEqual(source.readframes(160000), bytes(320000))
            self.assertEqual(manifest["input"]["duration_seconds"], 10)
            self.assertEqual(manifest["input"]["pcm_sha256"], "ac2878215ad33205d1732578c89f25ededaad1b676911c540825bcf4baa42d9b")
            self.assertEqual(prepare_silence(root), manifest)

    def test_existing_nonzero_audio_is_not_silently_replaced(self):
        private_root = Path(__file__).resolve().parents[2] / ".local"
        with tempfile.TemporaryDirectory(prefix="silence-test-", dir=private_root) as temporary:
            root = Path(temporary)
            prepare_silence(root)
            audio = root / "audio/synthetic-silence-10s.wav"
            with wave.open(str(audio), "wb") as output:
                output.setparams((1, 2, 16000, 160000, "NONE", "not compressed"))
                output.writeframes(b"\x01\x00" + bytes(319998))
            with self.assertRaisesRegex(ValueError, "nonzero"):
                prepare_silence(root)


if __name__ == "__main__":
    unittest.main()
