"""Offline acquisition behavior checks using small synthetic payloads."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import acquire_models as provision


class Response(io.BytesIO):
    def __init__(self, data: bytes, status: int, headers: dict):
        super().__init__(data)
        self.status = status
        self.headers = headers


class AcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.target = Path(self.temp.name) / "weights.bin"
        self.payload = b"synthetic-model-weight-data"
        self.entry = {"size": len(self.payload), "lfs": {"sha256": hashlib.sha256(self.payload).hexdigest()}}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_range_resume_retains_prefix_and_verifies_full_content(self) -> None:
        partial = self.target.with_suffix(".bin.partial")
        partial.write_bytes(self.payload[:7])
        with patch.object(provision, "request", return_value=Response(self.payload[7:], 206, {"Content-Range": f"bytes 7-{len(self.payload)-1}/{len(self.payload)}"})) as request:
            record = provision.download("https://example.invalid/model", self.target, self.entry)
        self.assertEqual(request.call_args.args[1], {"Range": "bytes=7-"})
        self.assertEqual(self.target.read_bytes(), self.payload)
        self.assertEqual(record["new_bytes"], len(self.payload) - 7)
        self.assertFalse(partial.exists())

    def test_ignored_range_cannot_silently_restart_or_mark_ready(self) -> None:
        partial = self.target.with_suffix(".bin.partial")
        partial.write_bytes(self.payload[:7])
        with patch.object(provision, "request", side_effect=lambda *_: Response(self.payload, 200, {})), patch.object(provision.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "refused range"):
                provision.download("https://example.invalid/model", self.target, self.entry)
        self.assertEqual(partial.read_bytes(), self.payload[:7])
        self.assertFalse(self.target.exists())

    def test_corruption_cannot_mark_asset_ready(self) -> None:
        with patch.object(provision, "request", side_effect=lambda *_: Response(b"x" * len(self.payload), 200, {})), patch.object(provision.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "integrity mismatch"):
                provision.download("https://example.invalid/model", self.target, self.entry)
        self.assertFalse(self.target.exists())

    def test_git_blob_content_identity_for_small_accessory_file(self) -> None:
        self.target.write_bytes(self.payload)
        entry = {"size": len(self.payload), "blobId": hashlib.sha1(f"blob {len(self.payload)}\0".encode() + self.payload).hexdigest()}
        self.assertTrue(provision.valid(self.target, entry))
        self.target.write_bytes(b"x" * len(self.payload))
        self.assertFalse(provision.valid(self.target, entry))

    def test_reverification_preserves_original_acquisition_provenance(self) -> None:
        root = Path(self.temp.name)
        name, repo, revision = "synthetic", "owner/synthetic", "fixed-revision"
        target = root / ".local/models" / name / "weights.bin"
        target.parent.mkdir(parents=True)
        target.write_bytes(self.payload)
        manifest = root / ".local/manifests" / f"model-{name}.json"
        provision.write_json(manifest, {"revision": revision, "files": [{"path": str(target.relative_to(root)), "sha256": self.entry["lfs"]["sha256"], "mode": "verified_local_copy", "copy_source": "original-cache"}]})
        metadata = {"sha": revision, "siblings": [{"rfilename": "weights.bin", **self.entry}]}
        with patch.object(provision, "ROOT", root), patch.object(provision, "metadata_request", return_value=metadata):
            provision.acquire((name, repo, revision, None))
        result = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertTrue(result["complete"])
        self.assertEqual(result["files"][0]["copy_source"], "original-cache")
        self.assertTrue(result["files"][0]["reverified"])


if __name__ == "__main__":
    unittest.main()
