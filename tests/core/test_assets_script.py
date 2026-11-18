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

    def tool(self, files: list[str], branch: str = "1.0") -> dict:
        return {"branch": branch, "repo": "o/r", "files": files}

    def build(self, version: str, archive: dict) -> dict:
        return {"version": version, "release": f"autobuild-{version}", "archive": archive}

    def install(self, tool: dict, build: dict) -> str:
        return assets.install_tool("demo", tool, tools_root=self.tools, downloads_root=self.downloads, cache=self.cache,
                                   resolve=lambda name, t: build)


def btbn_asset(name: str, digest: str | None = "sha256:" + "0" * 64) -> dict:
    return {"name": name, "browser_download_url": f"https://example.invalid/{name}", "digest": digest}


RELEASES = [
    {"tag_name": "latest", "prerelease": False, "assets": [btbn_asset("ffmpeg-n9.9-latest-win64-gpl-9.9.zip")]},
    {"tag_name": "autobuild-2026-11-17-12-40", "prerelease": False, "assets": [btbn_asset(n) for n in (
        "ffmpeg-N-127650-geceaa54a38-win64-gpl.zip", "ffmpeg-n8.1.3-18-g46d899d7a0-win64-gpl-8.1.zip",
        "ffmpeg-n9.0.2-31-gaaaaaaaaaa-win64-gpl-9.0.zip", "ffmpeg-n9.0.2-31-gaaaaaaaaaa-win64-lgpl-9.0.zip",
        "ffmpeg-n9.0.2-31-gaaaaaaaaaa-win64-gpl-shared-9.0.zip")]},
]


class ResolveBuildTests(unittest.TestCase):
    def test_btbn_builds_reads_branch_gpl_assets_of_dated_autobuild(self) -> None:
        release, builds = assets.btbn_builds(RELEASES)
        self.assertEqual(release["tag_name"], "autobuild-2026-11-17-12-40")
        self.assertEqual({branch: version for branch, (version, _) in builds.items()},
                         {"8.1": "n8.1.3-18-g46d899d7a0", "9.0": "n9.0.2-31-gaaaaaaaaaa"})

    def test_resolve_build_picks_locked_branch(self) -> None:
        build = assets.resolve_build("ffmpeg", {"branch": "9.0", "repo": "BtbN/FFmpeg-Builds"}, RELEASES)
        self.assertEqual(build["version"], "n9.0.2-31-gaaaaaaaaaa")
        self.assertEqual(build["release"], "autobuild-2026-11-17-12-40")
        self.assertEqual(build["archive"]["strip"], "ffmpeg-n9.0.2-31-gaaaaaaaaaa-win64-gpl-9.0/")
        self.assertEqual(build["archive"]["sha256"], "0" * 64)

    def test_missing_branch_points_to_upgrade(self) -> None:
        with self.assertRaisesRegex(assets.AssetError, "just upgrade ffmpeg"):
            assets.resolve_build("ffmpeg", {"branch": "7.1", "repo": "BtbN/FFmpeg-Builds"}, RELEASES)

    def test_missing_digest_is_refused(self) -> None:
        with self.assertRaisesRegex(assets.AssetError, "no sha256"):
            assets.asset_sha256(btbn_asset("a.zip", None))


class InstallToolTests(AssetsCase):
    def test_installs_only_listed_files_with_strip_and_writes_identity(self) -> None:
        exe, dll = b"exe bytes", b"dll bytes"
        archive = self.make_zip("demo.zip", {"demo-v1/bin/demo.exe": exe, "demo-v1/bin/extra.txt": b"x",
                                             "demo-v1/lib.dll": dll, "outside.txt": b"y"})
        archive["strip"] = "demo-v1/"
        self.assertEqual(self.install(self.tool(["bin/demo.exe", "lib.dll"]), self.build("v1", archive)), "installed v1")
        base = self.tools / "demo" / "1.0"
        self.assertEqual((base / "bin" / "demo.exe").read_bytes(), exe)
        self.assertEqual(sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()),
                         ["bin/demo.exe", "identity.json", "lib.dll"])
        self.assertTrue((self.downloads / "demo" / "demo.zip").is_file())  # 原始压缩包缓存
        identity = json.loads((base / "identity.json").read_text(encoding="utf-8"))
        self.assertEqual((identity["identity"], identity["branch"], identity["version"], identity["release"]),
                         ("demo-v1", "1.0", "v1", "autobuild-v1"))
        self.assertEqual(identity["archive"]["sha256"], archive["sha256"])
        self.assertEqual(identity["files"], {"bin/demo.exe": entry(exe), "lib.dll": entry(dll)})
        self.assertNotIn(b"\r\n", (base / "identity.json").read_bytes())

    def test_second_run_is_a_noop_and_cached_archive_is_reused(self) -> None:
        build = self.build("v1", self.make_zip("demo.zip", {"a.exe": b"a"}))
        self.install(self.tool(["a.exe"]), build)
        (self.source / "demo.zip").unlink()  # 远端不可达也不影响
        self.assertEqual(self.install(self.tool(["a.exe"]), build), "ok (v1)")
        (self.tools / "demo" / "1.0" / "a.exe").unlink()
        self.assertEqual(self.install(self.tool(["a.exe"]), build), "installed v1")  # 从 downloads 缓存重装

    def test_newer_build_on_branch_replaces_install(self) -> None:
        self.install(self.tool(["a.exe"]), self.build("v1", self.make_zip("v1.zip", {"a.exe": b"old"})))
        self.assertEqual(self.install(self.tool(["a.exe"]), self.build("v2", self.make_zip("v2.zip", {"a.exe": b"new"}))),
                         "updated v1 -> v2")
        base = self.tools / "demo" / "1.0"
        self.assertEqual((base / "a.exe").read_bytes(), b"new")
        self.assertEqual(json.loads((base / "identity.json").read_text(encoding="utf-8"))["version"], "v2")

    def test_archive_missing_a_listed_file_fails(self) -> None:
        with self.assertRaisesRegex(assets.AssetError, "lacks"):
            self.install(self.tool(["a.exe", "b.exe"]), self.build("v1", self.make_zip("demo.zip", {"a.exe": b"a"})))
        self.assertFalse((self.tools / "demo" / "1.0").exists())

    def test_non_zip_archive_is_refused(self) -> None:
        with self.assertRaisesRegex(assets.AssetError, "not a zip"):
            self.install(self.tool(["a.exe"]),
                         self.build("v1", {"name": "a.7z", "url": "file:///nowhere", "sha256": "0" * 64}))

    def test_archive_sha_mismatch_leaves_nothing_behind(self) -> None:
        archive = self.make_zip("demo.zip", {"a.exe": b"a"})
        archive["sha256"] = "0" * 64
        with self.assertRaisesRegex(assets.AssetError, "SHA256 mismatch"):
            self.install(self.tool(["a.exe"]), self.build("v1", archive))
        self.assertEqual(list((self.downloads / "demo").iterdir()), [])
        self.assertFalse((self.tools / "demo" / "1.0").exists())


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
        model_base = self.models / "m"
        model_base.mkdir(parents=True)
        (model_base / "ok.bin").write_bytes(b"ok")
        (model_base / "short.bin").write_bytes(b"s")
        (model_base / "bad.bin").write_bytes(b"BAD")
        manifest = {"tools": {"demo": self.tool(["a.exe"])},
                    "models": {"m": {"dir": "m", "files": {"ok.bin": entry(b"ok"), "short.bin": entry(b"short"),
                                                           "bad.bin": entry(b"bad"), "gone.bin": entry(b"g")}}}}
        report = assets.verify(manifest, tools_root=self.tools, models_root=self.models, cache=self.cache)
        self.assertEqual(report["tools.demo"], ["identity.json: missing"])
        problems = report["models.m"]
        self.assertEqual(len(problems), 3)
        self.assertTrue(problems[0].startswith("short.bin: size 1 != 5"))
        self.assertIn("bad.bin: Model SHA256 mismatch", problems[1])
        self.assertEqual(problems[2], "gone.bin: missing")
        self.install(manifest["tools"]["demo"], self.build("v1", self.make_zip("demo.zip", {"a.exe": b"a"})))
        report = assets.verify(manifest, tools_root=self.tools, models_root=self.models, cache=self.cache)
        self.assertEqual(report["tools.demo"], [])
        self.assertTrue(self.cache.is_file())  # size+mtime 缓存写在指定位置
        (self.tools / "demo" / "1.0" / "a.exe").write_bytes(b"tampered")
        report = assets.verify(manifest, tools_root=self.tools, models_root=self.models, cache=self.cache)
        self.assertEqual(len(report["tools.demo"]), 1)
        manifest["tools"]["demo"]["branch"] = "2.0"
        (self.tools / "demo" / "1.0").rename(self.tools / "demo" / "2.0")
        report = assets.verify(manifest, tools_root=self.tools, models_root=self.models, cache=self.cache)
        self.assertIn("installed branch 1.0 != assets.toml branch 2.0", report["tools.demo"])


if __name__ == "__main__":
    unittest.main()
