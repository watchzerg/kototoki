import argparse
import unittest

from experiments.run_experiment import REFERENCE_HASH, reference_sha256


class ReferenceHashTests(unittest.TestCase):
    def test_historical_default_remains_valid(self):
        self.assertEqual(reference_sha256(REFERENCE_HASH), REFERENCE_HASH)

    def test_new_reference_hash_accepts_uppercase_hex(self):
        self.assertEqual(reference_sha256("AB" * 32), "ab" * 32)

    def test_malformed_hash_is_rejected(self):
        for value in ("", "a" * 63, "a" * 65, "g" * 64, " " + "a" * 64, "a" * 64 + "\n"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                reference_sha256(value)
