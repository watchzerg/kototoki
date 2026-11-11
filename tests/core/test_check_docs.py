"""`scripts/check_docs.py` 的各项检查：只用临时目录里的合成文档树，不读仓库文档。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kototoki import config

_SPEC = importlib.util.spec_from_file_location("check_docs_script", config.REPO_ROOT / "scripts" / "check_docs.py")
check_docs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_docs)

MODULE_PAGE = "# 模块\n\n状态：current\n\n## 代码与验证入口\n\n- `kototoki/alpha.py`、`kototoki/pkg/`\n"
ADR_INDEX = (
    "# 决定索引\n\n## 全部 ADR\n\n| 编号 | 主题 |\n| --- | --- |\n"
    "| [0002](0002-b.md) | b |\n\n跳转页：0001 → 0002。新 ADR 编号从 0003 起。\n")


class CheckDocsTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        # 仓库现有的白名单与本测试的合成文档树无关。
        for name in ("BUDGET_WHITELIST", "KNOWN_MISSING_PATHS", "KNOWN_UNOWNED_MODULES"):
            patcher = mock.patch.object(check_docs, name, type(getattr(check_docs, name))())
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in check_docs.ROOT_DOCUMENTS:
            self.write(name, f"# {name}\n")
        self.write("docs/INDEX.md", "# 索引\n\n[架构](architecture/INDEX.md) [决定](adr/INDEX.md)\n")
        self.write("docs/architecture/INDEX.md", "# 架构\n\n[模块](modules/alpha.md)\n")
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE)
        self.write("docs/adr/INDEX.md", ADR_INDEX + "\n[1](0001-a.md)\n")
        self.write("docs/adr/0001-a.md", "# a\n")
        self.write("docs/adr/0002-b.md", "# b\n")
        self.write("kototoki/__init__.py", "")
        self.write("kototoki/alpha.py", "")
        self.write("kototoki/pkg/__init__.py", "")
        self.write("experiments/INDEX.md", "# 登记\n\n| `demo` | 可复用入口 |\n")
        self.write("experiments/demo/run.py", "")

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def errors(self) -> list[str]:
        return check_docs.check_all(self.root)[0]

    def warnings(self) -> list[str]:
        return check_docs.check_all(self.root)[1]

    def test_consistent_tree_passes(self) -> None:
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.warnings(), [])

    def test_broken_link_and_missing_anchor_are_reported_with_line(self) -> None:
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE + "\n[无](missing.md) [锚](../INDEX.md#不存在)\n")
        errors = self.errors()
        self.assertIn("docs/architecture/modules/alpha.md:9 链接目标不存在：missing.md", errors)
        self.assertIn("docs/architecture/modules/alpha.md:9 章节不存在：../INDEX.md#不存在", errors)

    def test_links_in_experiment_readmes_and_tickets_are_checked(self) -> None:
        self.write("experiments/demo/README.md", "[无](gone.md)\n")
        self.write(".scratch/feature/spec.md", "[无](gone.md)\n")
        errors = self.errors()
        self.assertIn("experiments/demo/README.md:1 链接目标不存在：gone.md", errors)
        self.assertIn(".scratch/feature/spec.md:1 链接目标不存在：gone.md", errors)

    def test_frozen_ticket_link_to_removed_document_is_allowed_only_under_scratch(self) -> None:
        dead = sorted(check_docs.FROZEN_DEAD_TARGETS)[0]
        self.write(".scratch/feature/spec.md", f"[旧](../../{dead})\n")
        self.assertEqual(self.errors(), [])
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE + f"\n[旧](../../../{dead})\n")
        self.assertEqual(len(self.errors()), 1)

    def test_archive_links_are_not_checked_but_archive_files_must_be_registered(self) -> None:
        self.write("docs/archive/old.md", "[无](gone.md)\n")
        self.assertEqual(self.errors(), ["docs/archive/old.md:1 没有被任何 INDEX.md 或子索引链接"])
        self.write("docs/INDEX.md", "# 索引\n\n[架构](architecture/INDEX.md) [决定](adr/INDEX.md) [归档](archive/old.md)\n")
        self.assertEqual(self.errors(), [])

    def test_document_must_be_linked_from_an_index_or_subindex(self) -> None:
        self.write("docs/research/2026-01-01-report.md", "# 报告\n")
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE + "\n[报告](../../research/2026-01-01-report.md)\n")
        self.assertEqual(self.errors(), ["docs/research/2026-01-01-report.md:1 没有被任何 INDEX.md 或子索引链接"])
        self.write("docs/research/INDEX.md", "# 调研\n\n[子索引](topics/a.md)\n")
        self.write("docs/research/topics/a.md", "# 子索引\n\n[报告](../2026-01-01-report.md)\n")
        self.write("docs/INDEX.md", "# 索引\n\n[架构](architecture/INDEX.md) [决定](adr/INDEX.md) [调研](research/INDEX.md)\n")
        self.assertEqual(self.errors(), [])

    def test_unregistered_experiment_package_is_reported(self) -> None:
        self.write("experiments/other/run.py", "")
        self.write("experiments/notes/readme.txt", "")
        self.assertEqual(self.errors(), ["experiments/INDEX.md:1 未登记的包：experiments/other/"])

    def test_index_budget_limits_lines_and_line_length(self) -> None:
        self.write("experiments/INDEX.md", "# 登记\n\n`demo` " + "长" * 400 + "\n" + "行\n" * 150)
        self.assertEqual(self.errors(), [
            "experiments/INDEX.md:1 超出预算：行数 153 > 150",
            "experiments/INDEX.md:3 超出预算：最长行 407 > 400"])

    def test_living_document_budget_and_agents_budget(self) -> None:
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE + "字\n" * 6000)
        self.write("AGENTS.md", "字" * 4501)
        errors = self.errors()
        self.assertEqual(len(errors), 2)
        self.assertIn("AGENTS.md:1 超出预算：字符数 4501 > 4500", errors)
        self.assertTrue(errors[1].startswith("docs/architecture/modules/alpha.md:1 超出预算：字符数"))

    def test_whitelist_caps_at_recorded_size_and_warns_when_no_longer_needed(self) -> None:
        name = "docs/architecture/modules/alpha.md"
        self.write(name, MODULE_PAGE + "字" * 13000 + "\n")
        with mock.patch.dict(check_docs.BUDGET_WHITELIST, {name: (14000, None, 13000)}, clear=True):
            self.assertEqual(self.errors(), [])
            self.write(name, MODULE_PAGE + "字" * 13001 + "\n")
            self.assertEqual(self.errors(), [f"{name}:8 超出预算：最长行 13001 > 13000"])
            self.write(name, MODULE_PAGE)
            self.assertEqual(self.warnings(), [f"{name}:1 已回到预算内，请从 BUDGET_WHITELIST 删除"])

    def test_repo_path_recognises_paths_and_skips_patterns(self) -> None:
        self.assertEqual(check_docs.repo_path("kototoki/plan.py"), "kototoki/plan.py")
        self.assertEqual(check_docs.repo_path("kototoki/translate/recipes.py::name_rows"), "kototoki/translate/recipes.py")
        self.assertEqual(check_docs.repo_path("docs/adr/INDEX.md#演进链"), "docs/adr/INDEX.md")
        self.assertEqual(check_docs.repo_path("experiments/x0_demo/"), "experiments/x0_demo")
        for token in ("docs/research/20*", ".scratch/<slug>/spec.md", "python -m kototoki", ".local/work/", "kototoki.toml"):
            self.assertIsNone(check_docs.repo_path(token), token)

    def test_missing_backticked_path_is_reported_outside_code_fences(self) -> None:
        self.write("docs/architecture/modules/alpha.md",
                   MODULE_PAGE + "\n见 `kototoki/gone.py` 与 `kototoki/alpha.py`。\n\n```\n`kototoki/fenced.py`\n```\n")
        self.assertEqual(self.errors(), ["docs/architecture/modules/alpha.md:9 反引号路径不存在：kototoki/gone.py"])
        with mock.patch.dict(check_docs.REMOVED_PATHS, {"kototoki/gone.py": "历史"}):
            self.assertEqual(self.errors(), [])

    def test_product_module_without_owning_page_is_reported(self) -> None:
        self.write("kototoki/beta.py", "")
        self.write("kototoki/sub/__init__.py", "")
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE + "\n## 变更与决策来源\n\n`kototoki/beta.py`\n")
        self.assertEqual(self.errors(), [
            'docs/architecture/modules:1 没有模块页在"代码与验证入口"里列出 kototoki/beta.py',
            'docs/architecture/modules:1 没有模块页在"代码与验证入口"里列出 kototoki/sub/'])

    def test_adr_files_table_and_next_number_must_agree(self) -> None:
        self.write("docs/adr/0003-c.md", "# c\n")
        self.write("docs/adr/INDEX.md", ADR_INDEX.replace("| [0002](0002-b.md) | b |", "| [0002](0002-b.md) | b |\n| [0004](0002-b.md) | 多 |")
                   + "\n[1](0001-a.md) [3](0003-c.md)\n")
        self.assertEqual(self.errors(), [
            'docs/adr/INDEX.md:1 "全部 ADR"没有登记 0003',
            "docs/adr/INDEX.md:8 登记的 0004 没有对应的 ADR 文件",
            'docs/adr/INDEX.md:10 "编号从 0003 起"应为 0004'])

    def test_status_line_with_three_dates_is_a_warning_not_an_error(self) -> None:
        self.write("docs/architecture/modules/alpha.md",
                   MODULE_PAGE.replace("状态：current", "状态：current（2026-10-01 建，2026-10-02 改，2026-10-03 再改）"))
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.warnings(), ["docs/architecture/modules/alpha.md:3 状态行含 3 个以上日期，像变更日志"])


if __name__ == "__main__":
    unittest.main()
