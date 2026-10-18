"""`scripts/assets.py` 的下载、解压、身份文件与核对逻辑：用本地 `file://` URL 顶替网络，不碰 socket。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

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
        self.tools, self.downloads = self.root / "tools", self.root / "downloads"
        self.models, self.cache = self.root / "models", self.root / "cache" / "verify.json"

    def make_zip(self, name: str, members: dict[str, bytes]) -> dict:
        path = self.source / name
        with zipfile.ZipFile(path, "w") as bundle:
            for member, data in members.items():
                bundle.writestr(member, data)
        return {"name": name, "url": path.as_uri(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def tool(self, archives: list[dict], files: dict[str, bytes]) -> dict:
        return {"version": "v1", "source": "https://example.invalid/release", "archives": archives,
                "files": {relative: entry(data) for relative, data in files.items()}}

    def install(self, tool: dict) -> str:
        return assets.install_tool("demo", tool, tools_root=self.tools, downloads_root=self.downloads, cache=self.cache)


class InstallToolTests(AssetsCase):
    def test_installs_only_listed_files_with_strip_and_writes_identity(self) -> None:
        exe, dll = b"exe bytes", b"dll bytes"
        archive = self.make_zip("demo.zip", {"demo-v1/bin/demo.exe": exe, "demo-v1/bin/extra.txt": b"x",
                                             "demo-v1/lib.dll": dll, "outside.txt": b"y"})
        archive["strip"] = "demo-v1/"
        tool = self.tool([archive], {"bin/demo.exe": exe, "lib.dll": dll})
        self.assertEqual(self.install(tool), "installed")
        base = self.tools / "demo" / "v1"
        self.assertEqual((base / "bin" / "demo.exe").read_bytes(), exe)
        self.assertEqual(sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()),
                         ["bin/demo.exe", "identity.json", "lib.dll"])
        self.assertTrue((self.downloads / "demo" / "demo.zip").is_file())  # 原始压缩包缓存
        identity = json.loads((base / "identity.json").read_text(encoding="utf-8"))
        self.assertEqual(identity["identity"], "demo-v1")
        self.assertEqual(identity["source"], "https://example.invalid/release")
        self.assertEqual(identity["archives"], [{"name": "demo.zip", "url": archive["url"], "sha256": archive["sha256"]}])
        self.assertEqual(identity["runtime_file_sha256"], {"bin/demo.exe": entry(exe)["sha256"],
                                                           "lib.dll": entry(dll)["sha256"]})
        self.assertNotIn(b"\r\n", (base / "identity.json").read_bytes())

    def test_second_run_is_a_noop_and_cached_archive_is_reused(self) -> None:
        archive = self.make_zip("demo.zip", {"a.exe": b"a"})
        tool = self.tool([archive], {"a.exe": b"a"})
        self.install(tool)
        (self.source / "demo.zip").unlink()  # 远端不可达也不影响
        self.assertEqual(self.install(tool), "ok")
        (self.tools / "demo" / "v1" / "a.exe").unlink()
        self.assertEqual(self.install(tool), "installed")  # 从 downloads 缓存重装

    def test_existing_files_without_identity_get_identity_without_download(self) -> None:
        base = self.tools / "demo" / "v1" / "bin"
        base.mkdir(parents=True)
        (base / "a.exe").write_bytes(b"a")
        tool = self.tool([{"name": "gone.7z", "url": (self.source / "gone.7z").as_uri()}], {"bin/a.exe": b"a"})
        self.assertEqual(self.install(tool), "identity written")
        identity = json.loads((base.parent / "identity.json").read_text(encoding="utf-8"))
        self.assertIsNone(identity["archives"][0]["sha256"])

    def test_archive_without_sha256_is_refused(self) -> None:
        archive = self.make_zip("demo.zip", {"a.exe": b"a"})
        del archive["sha256"]
        with self.assertRaisesRegex(assets.AssetError, "no sha256"):
            self.install(self.tool([archive], {"a.exe": b"a"}))
        self.assertFalse(self.downloads.exists())

    def test_non_zip_archive_is_refused(self) -> None:
        with self.assertRaisesRegex(assets.AssetError, "not a zip"):
            self.install(self.tool([{"name": "a.7z", "url": "file:///nowhere", "sha256": "0" * 64}], {"a.exe": b"a"}))

    def test_archive_sha_mismatch_leaves_nothing_behind(self) -> None:
        archive = self.make_zip("demo.zip", {"a.exe": b"a"})
        archive["sha256"] = "0" * 64
        with self.assertRaisesRegex(assets.AssetError, "SHA256 mismatch"):
            self.install(self.tool([archive], {"a.exe": b"a"}))
        self.assertEqual(list((self.downloads / "demo").iterdir()), [])
        self.assertFalse((self.tools / "demo" / "v1" / "a.exe").exists())

    def test_extracted_file_not_matching_manifest_fails(self) -> None:
        archive = self.make_zip("demo.zip", {"a.exe": b"different"})
        with self.assertRaisesRegex(assets.AssetError, "do not match"):
            self.install(self.tool([archive], {"a.exe": b"a"}))
        self.assertFalse((self.tools / "demo" / "v1" / "identity.json").exists())


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
    def test_reports_ok_missing_size_sha_and_identity(self) -> None:
        tool_base = self.tools / "demo" / "v1"
        tool_base.mkdir(parents=True)
        (tool_base / "a.exe").write_bytes(b"a")
        model_base = self.models / "m"
        model_base.mkdir(parents=True)
        (model_base / "ok.bin").write_bytes(b"ok")
        (model_base / "short.bin").write_bytes(b"s")
        (model_base / "bad.bin").write_bytes(b"BAD")
        manifest = {"tools": {"demo": self.tool([], {"a.exe": b"a"})},
                    "models": {"m": {"dir": "m", "files": {"ok.bin": entry(b"ok"), "short.bin": entry(b"short"),
                                                           "bad.bin": entry(b"bad"), "gone.bin": entry(b"g")}}}}
        report = assets.verify(manifest, tools_root=self.tools, models_root=self.models, cache=self.cache)
        self.assertEqual(report["tools.demo"], ["identity.json: missing"])
        problems = report["models.m"]
        self.assertEqual(len(problems), 3)
        self.assertTrue(problems[0].startswith("short.bin: size 1 != 5"))
        self.assertIn("bad.bin: Model SHA256 mismatch", problems[1])
        self.assertEqual(problems[2], "gone.bin: missing")
        assets.write_identity(tool_base, "demo", manifest["tools"]["demo"])
        report = assets.verify(manifest, tools_root=self.tools, models_root=self.models, cache=self.cache)
        self.assertEqual(report["tools.demo"], [])
        self.assertTrue(self.cache.is_file())  # size+mtime 缓存写在指定位置


if __name__ == "__main__":
    unittest.main()
