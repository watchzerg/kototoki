"""`scripts/upgrade.py` 的选版、清单改写与默认路径切换逻辑：只用内置样例与临时文件，不碰网络与 uv。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest
import zipfile

from kototoki import config

_SPEC = importlib.util.spec_from_file_location("upgrade_script", config.REPO_ROOT / "scripts" / "upgrade.py")
upgrade = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(upgrade)

PYPROJECT = """[project]
name = "x"
dependencies = [
    "torch==2.11.0",
    "ctranslate2==4.8.3",
    "transformers==5.20.1",
    "pyannote.audio==4.0.7",
    "numpy",
]
"""


def asset(name: str, digest: str | None = "sha256:" + "0" * 64) -> dict:
    return {"name": name, "browser_download_url": f"https://example.invalid/{name}", "digest": digest}


class VersionRuleTests(unittest.TestCase):
    def test_major_bump_detection(self) -> None:
        self.assertTrue(upgrade.is_major_bump("12.3.0", "13.0.0"))
        self.assertFalse(upgrade.is_major_bump("4.66.1", "4.67.0"))
        self.assertTrue(upgrade.is_major_bump("0.15.3", "0.16.0"))   # 0.x 看次版本
        self.assertFalse(upgrade.is_major_bump("0.15.3", "0.15.4"))
        self.assertFalse(upgrade.is_major_bump("2026.7.22", "2027.1.5"))   # 日历版本号
        self.assertFalse(upgrade.is_major_bump("2.11.0+cu128", "2.12.0+cu128"))

    def test_pins_exclude_anchors_and_unpinned(self) -> None:
        pins = upgrade.pinned_dependencies(PYPROJECT)
        self.assertEqual(pins, {"transformers": ("transformers==5.20.1", "5.20.1"),
                                "pyannote-audio": ("pyannote.audio==4.0.7", "4.0.7")})
        self.assertEqual(upgrade.direct_names(PYPROJECT),
                         {"torch", "ctranslate2", "transformers", "pyannote-audio", "numpy"})

    def test_parse_updates_reads_dry_run_and_real_lock_lines(self) -> None:
        output = ("Resolved 108 packages in 2ms\nUpdate pillow v12.3.0 -> v13.0.0\n"
                  "Updated certifi v2026.7.22 -> v2026.10.18\nAdded scipy v1.0.0\n")
        self.assertEqual(upgrade.parse_updates(output),
                         {"pillow": ("12.3.0", "13.0.0"), "certifi": ("2026.7.22", "2026.10.18")})

    def test_plan_skips_anchors_and_transitive_majors_only(self) -> None:
        updates = {"torch": ("2.11.0", "2.12.0"), "pillow": ("12.3.0", "13.0.0"),
                   "transformers": ("5.20.1", "6.0.0"), "certifi": ("2026.7.22", "2026.10.18")}
        allowed, skipped = upgrade.plan_python(updates, {"torch", "transformers"})
        self.assertEqual(allowed, ["certifi", "transformers"])
        self.assertEqual(skipped, {"pillow": ("12.3.0", "13.0.0")})


class ManifestTests(unittest.TestCase):
    def test_rendering_current_tools_round_trips(self) -> None:
        text = upgrade.assets.MANIFEST.read_text(encoding="utf-8")
        manifest = tomllib.loads(text)
        for name, tool in manifest["tools"].items():
            replaced = upgrade.replace_tool_block(text, name, upgrade.render_tool(name, tool))
            self.assertEqual(tomllib.loads(replaced), manifest)

    def test_replacing_one_tool_keeps_neighbours(self) -> None:
        text = upgrade.assets.MANIFEST.read_text(encoding="utf-8")
        manifest = tomllib.loads(text)
        new = {"version": "b2-cuda13.5", "source": "s", "note": "说明",
               "archives": [{"name": "a.zip", "url": "u", "sha256": "f" * 64}],
               "files": {"llama-server.exe": {"sha256": "e" * 64, "size": 3}}}
        replaced = tomllib.loads(upgrade.replace_tool_block(text, "llama.cpp", upgrade.render_tool("llama.cpp", new)))
        self.assertEqual(replaced["tools"]["llama.cpp"], new)
        self.assertEqual(replaced["tools"]["ffmpeg"], manifest["tools"]["ffmpeg"])
        self.assertEqual(replaced["models"], manifest["models"])

    def test_switch_default_paths_only_touches_matching_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text('p = ".local/tools/ffmpeg/old/bin/ffmpeg.exe"\n', encoding="utf-8")
            (root / "b.toml").write_text('x = ".local/tools/llama.cpp/old/llama-server.exe"\n', encoding="utf-8")
            changed = upgrade.switch_default_paths("ffmpeg", "old", "new", ("a.py", "b.toml"), root)
            self.assertEqual(changed, ["a.py"])
            self.assertIn(".local/tools/ffmpeg/new/bin/", (root / "a.py").read_text(encoding="utf-8"))
            self.assertIn("llama.cpp/old/", (root / "b.toml").read_text(encoding="utf-8"))

    def test_zip_entries_strip_and_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.zip"
            with zipfile.ZipFile(path, "w") as bundle:
                bundle.writestr("top/bin/ffmpeg.exe", b"ff")
                bundle.writestr("top/bin/ffplay.exe", b"pl")
                bundle.writestr("top/doc/x.html", b"d")
            entries = upgrade.zip_entries(path, "top/", {"bin/ffmpeg.exe"})
            self.assertEqual(entries, {"bin/ffmpeg.exe": {"sha256": hashlib.sha256(b"ff").hexdigest(), "size": 2}})

    def test_missing_digest_is_refused(self) -> None:
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.digest(asset("a.zip", None))
        self.assertEqual(upgrade.digest(asset("a.zip", "sha256:" + "a" * 64)), "a" * 64)


class ReleasePickTests(unittest.TestCase):
    def test_llama_picks_highest_build_within_cuda_major(self) -> None:
        release = {"assets": [asset(n) for n in (
            "llama-b9-bin-win-cuda-12.4-x64.zip", "llama-b9-bin-win-cuda-13.4-x64.zip",
            "llama-b9-bin-win-cuda-13.6-x64.zip", "llama-b9-bin-win-cuda-14.0-x64.zip",
            "llama-b9-bin-win-cuda-13.6-arm64.zip", "cudart-llama-bin-win-cuda-13.6-x64.zip",
            "cudart-llama-bin-win-cuda-13.4-x64.zip")]}
        cuda, main, cudart = upgrade.pick_llama(release, "b9", "13")
        self.assertEqual((cuda, main["name"], cudart["name"]),
                         ("13.6", "llama-b9-bin-win-cuda-13.6-x64.zip", "cudart-llama-bin-win-cuda-13.6-x64.zip"))

    def test_llama_without_matching_cudart_fails(self) -> None:
        release = {"assets": [asset("llama-b9-bin-win-cuda-13.6-x64.zip")]}
        with self.assertRaises(upgrade.UpgradeError):
            upgrade.pick_llama(release, "b9", "13")

    def test_ffmpeg_picks_highest_branch_of_dated_autobuild(self) -> None:
        releases = [
            {"tag_name": "latest", "prerelease": False, "assets": [asset("ffmpeg-n9.9-latest-win64-gpl-9.9.zip")]},
            {"tag_name": "autobuild-2026-10-18-13-01", "prerelease": False, "assets": [asset(n) for n in (
                "ffmpeg-N-127650-geceaa54a38-win64-gpl.zip", "ffmpeg-n8.1.3-18-g46d899d7a0-win64-gpl-8.1.zip",
                "ffmpeg-n9.0.2-28-g669f5ab083-win64-gpl-9.0.zip", "ffmpeg-n9.0.2-28-g669f5ab083-win64-lgpl-9.0.zip",
                "ffmpeg-n9.0.2-28-g669f5ab083-win64-gpl-shared-9.0.zip")]},
        ]
        release, chosen, version, branch = upgrade.pick_ffmpeg(releases)
        self.assertEqual((release["tag_name"], chosen["name"], version, branch),
                         ("autobuild-2026-10-18-13-01", "ffmpeg-n9.0.2-28-g669f5ab083-win64-gpl-9.0.zip",
                          "n9.0.2-28-g669f5ab083", "9.0"))

    def test_wav_check_without_films_does_not_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = upgrade.compare_derived_wav(Path(tmp), Path(tmp) / "out", Path(tmp), Path(tmp))
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
