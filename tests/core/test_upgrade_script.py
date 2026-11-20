"""`scripts/upgrade.py` 的选版逻辑：只用内置样例，不碰网络与 uv。"""

from __future__ import annotations

import importlib.util
import unittest

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


if __name__ == "__main__":
    unittest.main()
