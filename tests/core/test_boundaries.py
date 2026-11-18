"""全仓库导入边界（ADR-0031 R5、ADR-0025 决定 4）：产品包 `kototoki/` 与 `tests/core/` 都不导入 `research`
（研究可以导入产品，反向不行）。AST 扫描，覆盖 `import`、`from ... import`，以及首参为字符串
字面量的 `importlib.import_module` 与 `__import__`。"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[2]
RESEARCH = ("research",)


def imported_roots(tree: ast.AST) -> set[str]:
    """文件里被导入的顶层包名（相对导入不计）。"""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            first = node.args[0]
            if name in ("import_module", "__import__") and isinstance(first, ast.Constant) \
                    and isinstance(first.value, str):
                roots.add(first.value.split(".")[0])
    return roots


def violations(directory: str, banned: tuple[str, ...]) -> list[str]:
    found = []
    for path in sorted((REPO / directory).rglob("*.py")):
        roots = imported_roots(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        found.extend(f"{path.relative_to(REPO).as_posix()}: {root}" for root in sorted(roots & set(banned)))
    return found


class ScannerTests(unittest.TestCase):
    def test_every_import_form_is_detected(self) -> None:
        source = ("import research.x\nimport os, toolz\nfrom research import y\nfrom research.a.b import c\n"
                  "import importlib\nimportlib.import_module('research.z')\n__import__('toolz.s')\n"
                  "from . import research\nname = 'research'\nimportlib.import_module(name)\n")
        self.assertEqual(imported_roots(ast.parse(source)), {"research", "toolz", "os", "importlib"})
        self.assertEqual(imported_roots(ast.parse("from .research import a\nimport kototoki.guard\n")), {"kototoki"})

    def test_violations_reports_banned_roots(self) -> None:
        self.assertIn("tests/core/test_boundaries.py: unittest", violations("tests/core", ("unittest",)))


class RepoBoundaryTests(unittest.TestCase):
    def test_product_package_does_not_import_research(self) -> None:
        self.assertEqual(violations("kototoki", RESEARCH), [])

    def test_core_tests_do_not_import_research(self) -> None:
        self.assertEqual(violations("tests/core", RESEARCH), [])


if __name__ == "__main__":
    unittest.main()
