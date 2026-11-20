"""`scripts/check_docs.py` 的各项检查：只用临时目录里的合成文档树；唯一例外是核对必填标题与
`research/TEMPLATE.md` 一致。"""

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
ROUND = "# 轮次\n\n" + "".join(f"## {h}\n\n内容\n\n" for h in (
    "状态", "时间", "问题", "策略", "环境与版本", "测试", "结果", "结论与去向"))
ACCEPTANCE = "# 验收\n\n" + "".join(f"## {h}\n\n内容\n\n" for h in (
    "时间", "对象", "环境与版本", "测试", "结果", "结论"))
RUN = "# 跑次\n\n" + "".join(f"## {h}\n\n内容\n\n" for h in ("运行", "版本", "输入", "结果", "问题"))
ADR_INDEX = (
    "# 决定索引\n\n## 全部 ADR\n\n| 编号 | 主题 |\n| --- | --- |\n"
    "| [0001](0001-a.md) | a |\n| [0002](0002-b.md) | b |\n\n新 ADR 编号从 0003 起。\n")


class CheckDocsTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        # 仓库现有的白名单与本测试的合成文档树无关。
        for name in ("BUDGET_WHITELIST", "KNOWN_MISSING_PATHS", "KNOWN_UNOWNED_MODULES", "ALLOWED_ABSOLUTE_PATHS"):
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
        self.write("research/INDEX.md", "# 研究\n\n[轮次](2026-01-demo/README.md) [验收](acceptance/2026-01-02-x.md)\n")
        self.write("research/2026-01-demo/README.md", ROUND)
        self.write("research/acceptance/2026-01-02-x.md", ACCEPTANCE)
        self.write("runs/INDEX.md", "# 跑次\n\n[模板](TEMPLATE.md) [首跑](2026-01-03-a.md)\n")
        self.write("runs/TEMPLATE.md", "# 模板\n")
        self.write("runs/2026-01-03-a.md", RUN)

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

    def test_links_in_research_records_and_tickets_are_checked(self) -> None:
        self.write("research/2026-01-demo/README.md", ROUND + "[无](gone.md)\n")
        self.write(".scratch/feature/spec.md", "[无](gone.md)\n")
        errors = self.errors()
        self.assertIn("research/2026-01-demo/README.md:35 链接目标不存在：gone.md", errors)
        self.assertIn(".scratch/feature/spec.md:1 链接目标不存在：gone.md", errors)

    def test_frozen_ticket_link_to_removed_document_is_allowed_only_under_scratch(self) -> None:
        dead = sorted(check_docs.FROZEN_DEAD_TARGETS)[0]
        self.write(".scratch/feature/spec.md", f"[旧](../../{dead})\n")
        self.assertEqual(self.errors(), [])
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE + f"\n[旧](../../../{dead})\n")
        self.assertEqual(len(self.errors()), 1)

    def test_document_must_be_linked_from_an_index(self) -> None:
        self.write("docs/specs/topic.md", "# 规格\n")
        self.write("docs/architecture/modules/alpha.md", MODULE_PAGE + "\n[规格](../../specs/topic.md)\n")
        self.assertEqual(self.errors(), ["docs/specs/topic.md:1 没有被任何 INDEX.md 链接"])
        self.write("docs/specs/INDEX.md", "# 规格\n\n[主题](topic.md)\n")
        self.write("docs/INDEX.md", "# 索引\n\n[架构](architecture/INDEX.md) [决定](adr/INDEX.md) [规格](specs/INDEX.md)\n")
        self.assertEqual(self.errors(), [])

    def test_research_round_and_acceptance_need_required_headings(self) -> None:
        self.write("research/2026-01-demo/README.md", ROUND.replace("## 结论与去向", "## 结论"))
        self.write("research/acceptance/2026-01-02-x.md", ACCEPTANCE.replace("## 对象", "## 范围"))
        self.assertEqual(self.errors(), [
            "research/2026-01-demo/README.md:1 缺少必填标题：## 结论与去向",
            "research/acceptance/2026-01-02-x.md:1 缺少必填标题：## 对象"])

    def test_research_round_needs_readme_and_registration(self) -> None:
        self.write("research/2026-02-other/notes.py", "")
        self.write("research/_lib/tool.py", "")
        self.assertEqual(self.errors(), ["缺少文档：research/2026-02-other/README.md"])
        self.write("research/2026-02-other/README.md", ROUND)
        self.assertEqual(self.errors(), ["research/2026-02-other/README.md:1 没有在 research/INDEX.md 登记"])
        self.write("research/INDEX.md", "# 研究\n\n[轮次](2026-01-demo/README.md) [另一轮](2026-02-other/README.md) "
                   "[验收](acceptance/2026-01-02-x.md)\n")
        self.assertEqual(self.errors(), [])

    def test_research_must_not_contain_64_hex_strings(self) -> None:
        self.write("research/2026-01-demo/README.md", ROUND + "revision `e66f3d3b`，提交 1234567890ab\n")
        self.assertEqual(self.errors(), [])
        self.write("research/2026-01-demo/run.py", "SHA = '" + "ab" * 32 + "'\n")
        self.assertEqual(self.errors(), ["research/2026-01-demo/run.py:1 研究记录里有 64 位十六进制串"])

    def test_machine_paths_are_reported_unless_allowed(self) -> None:
        home = "/" + "home"  # 拼出来，免得本测试文件自己被路径检查命中
        fictional, local = f"{home}/u/movies/ep01.mkv", "/" + "data/set"
        self.write("tests/core/test_x.py",
                   'URL = "https://example.com/data/a"\nP = "/proc/meminfo /srv/in"\n' + f'PATH = "{fictional}"\n')
        self.write("research/2026-01-demo/README.md", ROUND + f"数据在 {local} 下\n")
        self.assertEqual(self.errors(), [
            f"research/2026-01-demo/README.md:35 本机绝对路径：{local}",
            f"tests/core/test_x.py:3 本机绝对路径：{fictional}"])
        with mock.patch.dict(check_docs.ALLOWED_ABSOLUTE_PATHS, {("tests/core/test_x.py", f"{home}/u"): "虚构"}):
            self.assertEqual(self.errors(), [f"research/2026-01-demo/README.md:35 本机绝对路径：{local}"])

    def test_run_record_needs_headings_registration_and_no_media_names(self) -> None:
        self.write("runs/2026-01-04-b.md", RUN.replace("## 问题", "## 发现") + "输入集 1234567890ab，工作 id 0a1b2c3d4e5f\n")
        self.assertEqual(self.errors(), ["runs/2026-01-04-b.md:1 缺少必填标题：## 问题",
                                         "runs/2026-01-04-b.md:1 没有在 runs/INDEX.md 登记"])
        self.write("runs/2026-01-04-b.md", RUN + "失败的是 Show S01E02.MKV 与 `ep.wav`\n" + "ab" * 32 + "\n")
        self.write("runs/INDEX.md", "# 跑次\n\n[首跑](2026-01-03-a.md) [次跑](2026-01-04-b.md)\n")
        self.assertEqual(self.errors(), ["runs/2026-01-04-b.md:23 跑次记录里有媒体文件名：S01E02.MKV",
                                         "runs/2026-01-04-b.md:23 跑次记录里有媒体文件名：ep.wav",
                                         "runs/2026-01-04-b.md:24 跑次记录里有 64 位十六进制串"])

    def test_required_headings_match_run_template(self) -> None:
        template = (config.REPO_ROOT / "runs" / "TEMPLATE.md").read_text(encoding="utf-8")
        for heading in check_docs.RUN_HEADINGS:
            self.assertIn(f"\n## {heading}\n", template, heading)

    def test_required_headings_match_research_template(self) -> None:
        template = (config.REPO_ROOT / "research" / "TEMPLATE.md").read_text(encoding="utf-8")
        round_part, acceptance_part = template.split("## 验收记录模板")
        for heading in check_docs.ROUND_HEADINGS:
            self.assertIn(f"\n## {heading}\n", round_part, heading)
        for heading in check_docs.ACCEPTANCE_HEADINGS:
            self.assertIn(f"\n## {heading}\n", acceptance_part, heading)

    def test_index_budget_limits_lines_and_line_length(self) -> None:
        self.write("research/INDEX.md", "# 研究\n\n[轮次](2026-01-demo/README.md) [验收](acceptance/2026-01-02-x.md) "
                   + "长" * 400 + "\n" + "行\n" * 150)
        errors = self.errors()
        self.assertEqual(errors, [
            "research/INDEX.md:1 超出预算：行数 153 > 150",
            f"research/INDEX.md:3 超出预算：最长行 {len((self.root / 'research/INDEX.md').read_text(encoding='utf-8').splitlines()[2])} > 400"])

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
        self.assertEqual(check_docs.repo_path("research/2026-10-vad/"), "research/2026-10-vad")
        for token in ("research/20*", ".scratch/<slug>/spec.md", "python -m kototoki", ".local/work/", "kototoki.toml"):
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
            "docs/adr/INDEX.md:9 登记的 0004 没有对应的 ADR 文件",
            'docs/adr/INDEX.md:11 "编号从 0003 起"应为 0004'])

    def test_status_line_with_three_dates_is_a_warning_not_an_error(self) -> None:
        self.write("docs/architecture/modules/alpha.md",
                   MODULE_PAGE.replace("状态：current", "状态：current（2026-10-01 建，2026-10-02 改，2026-10-03 再改）"))
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.warnings(), ["docs/architecture/modules/alpha.md:3 状态行含 3 个以上日期，像变更日志"])


if __name__ == "__main__":
    unittest.main()
