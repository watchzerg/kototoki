"""Offline checks for bounded chunks, preserved prefixes and final SHA verification."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import acquire_models as assets
import range_models
from test_acquire_models import Response


class RangeTests(unittest.TestCase):
    def test_chunks_stitch_exact_prefix_and_verify_full_file(self) -> None:
        for prefix_size in (0, 7):
            with self.subTest(prefix_size=prefix_size):
                self._verify_full_transfer(prefix_size)

    def _verify_full_transfer(self, prefix_size: int) -> None:
        payload = b"known-preserved-prefix-and-synthetic-weight-body"
        spec = assets.SPECS[0]
        name, _, revision, _ = spec
        entry = {"rfilename": "model.bin", "size": len(payload), "lfs": {"sha256": hashlib.sha256(payload).hexdigest()}}
        metadata = {"sha": revision, "siblings": [entry]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ".local/models" / name / "model.bin"
            prefix = target.with_suffix(".bin.partial")
            if prefix_size:
                target.parent.mkdir(parents=True)
                prefix.write_bytes(payload[:prefix_size])

            def response(_url, headers):
                start, end = [int(x) for x in headers["Range"][6:].split("-")]
                return Response(payload[start:end+1], 206, {"Content-Range": f"bytes {start}-{end}/{len(payload)}"})

            with patch.object(assets, "ROOT", root), patch.object(assets, "metadata_request", return_value=metadata), patch.object(assets, "request", side_effect=response), patch.object(sys, "argv", ["range_models", "--model", name, "--connections", "2"]):
                range_models.main()
            self.assertEqual(target.read_bytes(), payload)
            if prefix_size:
                self.assertEqual(prefix.read_bytes(), payload[:prefix_size])
            else:
                self.assertFalse(prefix.exists())
            state = json.loads((root / ".local/downloads/models" / name / "range-state.json").read_text())
            self.assertTrue(state["complete"])
            self.assertEqual(state["prefix_bytes"], prefix_size)
            manifest = json.loads((root / ".local/manifests" / f"model-{name}.json").read_text())
            self.assertEqual(manifest["files"][0]["mode"], "verified_parallel_range_download")

    def test_inexact_content_range_never_appends_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "range.partial"
            chunk = {"path": str(path), "start": 4, "end": 7, "total": 8}
            with patch.object(assets, "request", side_effect=lambda *_: Response(b"abcd", 206, {"Content-Range": "bytes 0-3/8"})), patch.object(range_models.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "mismatch"):
                    range_models.transfer("https://example.invalid", chunk)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
