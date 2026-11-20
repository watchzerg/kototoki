"""`scripts/assets.py` 的模型下载与核对逻辑：用本地 `file://` URL 顶替网络，不碰 socket。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from kototoki import config

_SPEC = importlib.util.spec_from_file_location("assets_script", config.REPO_ROOT / "scripts" / "assets.py")
assets = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(assets)


def entry(data: bytes) -> dict:
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


class AssetsCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "source"   # 伪"远端"
        self.source.mkdir()
        self.models, self.cache = self.root / "models", self.root / "cache" / "verify.json"
class FetchModelTests(AssetsCase):
    def model(self, files: dict[str, bytes], **extra) -> dict:
        return {"dir": "group/demo-model", "repo": "org/demo", "revision": "abc123",
                "files": {relative: entry(data) for relative, data in files.items()}, **extra}

    def publish(self, relative: str, data: bytes) -> None:
        path = self.source / "org" / "demo" / "resolve" / "abc123" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def fetch(self, model: dict, environ: dict | None = None) -> str:
        return assets.fetch_model("demo", model, models_root=self.models, cache=self.cache,
                                  endpoint=self.source.as_uri(), environ=environ or {})

    def test_downloads_missing_files_and_keeps_verified_ones(self) -> None:
        model = self.model({"config.json": b"{}", "sub/weights.bin": b"weights"})
        self.publish("config.json", b"{}")
        self.publish("sub/weights.bin", b"weights")
        base = self.models / "group" / "demo-model"
        base.mkdir(parents=True)
        (base / "config.json").write_bytes(b"{}")
        self.assertEqual(self.fetch(model), "fetched 1 file(s)")
        self.assertEqual((base / "sub" / "weights.bin").read_bytes(), b"weights")
        self.assertEqual(self.fetch(model), "ok")

    def test_mismatched_download_is_removed(self) -> None:
        model = self.model({"w.bin": b"expected"})
        self.publish("w.bin", b"tampered")
        with self.assertRaisesRegex(assets.AssetError, "SHA256 mismatch"):
            self.fetch(model)
        self.assertEqual(list((self.models / "group" / "demo-model").iterdir()), [])

    def test_model_without_repo_cannot_be_fetched(self) -> None:
        model = self.model({"mel.npz": b"m"}, source="package assets")
        del model["repo"]
        with self.assertRaisesRegex(assets.AssetError, "no download source"):
            self.fetch(model)

    def test_gated_model_requires_token(self) -> None:
        model = self.model({"w.bin": b"w"}, gated=True)
        self.publish("w.bin", b"w")
        with self.assertRaisesRegex(assets.AssetError, "HF_TOKEN"):
            self.fetch(model)
        self.assertEqual(self.fetch(model, {"HF_TOKEN": "t"}), "fetched 1 file(s)")


class VerifyTests(AssetsCase):
    def test_reports_ok_missing_size_and_sha(self) -> None:
        model_base = self.models / "m"
        model_base.mkdir(parents=True)
        (model_base / "ok.bin").write_bytes(b"ok")
        (model_base / "short.bin").write_bytes(b"s")
        (model_base / "bad.bin").write_bytes(b"BAD")
        manifest = {"models": {"m": {"dir": "m", "files": {"ok.bin": entry(b"ok"), "short.bin": entry(b"short"),
                                                           "bad.bin": entry(b"bad"), "gone.bin": entry(b"g")}}}}
        report = assets.verify(manifest, models_root=self.models, cache=self.cache)
        problems = report["models.m"]
        self.assertEqual(len(problems), 3)
        self.assertTrue(problems[0].startswith("short.bin: size 1 != 5"))
        self.assertIn("bad.bin: Model SHA256 mismatch", problems[1])
        self.assertEqual(problems[2], "gone.bin: missing")
        self.assertTrue(self.cache.is_file())  # size+mtime 缓存写在指定位置


if __name__ == "__main__":
    unittest.main()
