"""检查仓库文档的结构约束；只依赖标准库，不联网。每条错误带文件与行号。

链接与锚点：根目录 README、AGENTS、GLOSSARY、CODING_STANDARDS，docs/ 下全部 Markdown，
experiments/INDEX.md 与 experiments/**/README*.md，.scratch/**/*.md。
模块页（docs/architecture/modules/*.md）必须能从 docs/architecture/INDEX.md 沿链接到达。
不检查的两类：docs/archive/ 下的归档件（原样保存的外部文件，其相对链接按原位置写，在本仓库里必然断开）；
指向仓库之外的相对链接（相邻仓库，本机未必存在），只计数。

登记：docs/ 下每篇 Markdown 至少被一个 INDEX.md 或子索引（docs/research/topics/）链接；
experiments/ 的每个包目录出现在 experiments/INDEX.md；kototoki/ 的每个模块与子包出现在某篇模块页的
"代码与验证入口"一节；ADR 文件、决定索引"全部 ADR"表与"编号从 N 起"三者一致。

预算：AGENTS.md、各 INDEX.md、活正文的字符数、行数与行长（数值见下方常量）。
活文档里反引号包住的仓库路径必须存在。状态行含 3 个以上日期只告警。

冻结文件是否被改动不在这里检查（需要比较基线）；靠 AGENTS.md 的规则与各目录索引的标注。
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT_DOCUMENTS = ("README.md", "AGENTS.md", "GLOSSARY.md", "CODING_STANDARDS.md")
ARCHITECTURE_INDEX = Path("docs/architecture/INDEX.md")
MODULES = Path("docs/architecture/modules")
ARCHIVE = Path("docs/archive")
SUBINDEX = Path("docs/research/topics")
EXPERIMENTS_INDEX = Path("experiments/INDEX.md")
ADR_INDEX = Path("docs/adr/INDEX.md")
PRODUCT = Path("kototoki")

# 预算：(最多字符, 最多行, 最长行)，None 表示不限。
Budget = tuple[int | None, int | None, int | None]
AGENTS_BUDGET: Budget = (4500, None, None)
INDEX_BUDGET: Budget = (None, 150, 400)
LIVING_BUDGET: Budget = (12000, None, 800)
# 活正文：按目录或单个文件列出；其中的 INDEX.md 走 INDEX_BUDGET。
LIVING_DIRECTORIES = ("docs/architecture", "docs/development", "docs/agents")
LIVING_FILES = ("docs/adr/CURRENT.md", "docs/pending-decisions.md")
# 技术设计只含跨模块契约，单独的上限。
SPECIAL_BUDGETS: dict[str, Budget] = {"docs/specs/bilingual-subtitle-pipeline.md": (15000, None, 800)}
# 字节被代码按 sha256 校验、不能修改的活目录文件：超标时长期留在白名单里，不提示删除。
BYTE_VERIFIED = ("docs/agents/subtitle-translation-evaluation.md", "docs/development/inference-selection.md")
# 现有超标文件：记当前数值，只许降不许升；回到预算内后删掉对应行（脚本会告警提醒）。
BUDGET_WHITELIST: dict[str, Budget] = {
    "docs/agents/subtitle-translation-evaluation.md": (25975, None, 1230),
    "docs/architecture/INDEX.md": (None, 150, 1321),
    "docs/architecture/module-boundaries.md": (19491, None, 1664),
    "docs/architecture/modules/artifact-contract.md": (12000, None, 887),
    "docs/architecture/modules/batch-orchestration.md": (20637, None, 1253),
    "docs/architecture/modules/config-and-media.md": (13301, None, 895),
    "docs/architecture/modules/name-consistency.md": (13318, None, 1150),
    "docs/architecture/modules/stage-plan.md": (12000, None, 832),
    "docs/architecture/modules/stt-workers.md": (22892, None, 1967),
    "docs/architecture/modules/translation-subsystem.md": (21389, None, 2261),
    "docs/development/dependencies.md": (12000, None, 903),
    "docs/development/workflow.md": (12000, None, 1313),
    "docs/specs/bilingual-subtitle-pipeline.md": (51461, None, 820),
}

# 路径检查认的顶层目录；.local/ 等未跟踪目录不查。
PATH_ROOTS = ("kototoki/", "kototoki_eval/", "experiments/", "scripts/", "tests/", "docs/", ".scratch/", ".claude/")
# 活文档里作为历史或规则提到、并不存在的路径：路径 -> 原因。
REMOVED_PATHS: dict[str, str] = {
    "kototoki/llama_server.py": "ADR-0025 拆掉；决定索引演进链按历史提到",
    "docs/architecture/collaborations.md": "文档维护规则里按需创建的落点，尚未创建",
    "docs/operations": "文档维护规则里按需创建的落点，尚未创建",
}
# 待修的失效路径：(文档, 路径)。
KNOWN_MISSING_PATHS: set[tuple[str, str]] = {
    ("docs/architecture/modules/batch-orchestration.md", "docs/changes/local-dependencies-and-test-layers.md"),
    ("docs/architecture/modules/config-and-media.md", "docs/changes/local-dependencies-and-test-layers.md"),
    ("docs/architecture/modules/corpus-and-assets.md", "docs/changes/local-dependencies-and-test-layers.md"),
    ("docs/architecture/modules/name-consistency.md", "docs/changes/name-consistency-product.md"),
    ("docs/architecture/modules/stt-workers.md", "docs/changes/local-dependencies-and-test-layers.md"),
    ("docs/architecture/modules/translation-subsystem.md", "docs/changes/local-dependencies-and-test-layers.md"),
    ("docs/specs/bilingual-subtitle-pipeline.md", "tests/test_translate.py"),
}
# 还没有模块页归属的产品模块。
KNOWN_UNOWNED_MODULES: set[str] = {
}
# 已结题（冻结）的 .scratch/ 票据里指向已删除文档的链接：冻结后不能修，只对 .scratch/ 下的来源放行。
FROZEN_DEAD_TARGETS = {
    "docs/architecture/bilingual-pipeline-architecture.md",
    "docs/changes/cross-asr-judge.md",
    "docs/changes/name-consistency-product.md",
}

OWNERSHIP_SECTION = "代码与验证入口"
STATUS_LINE = re.compile(r"^\s*(?:状态|Status)\s*[：:]")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
LINK_TITLE = r"""(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^)\n]*\)))?"""
LINK = re.compile(
    r"!?\[(?P<text>[^\]\n]*)\]\(\s*(?P<dest><[^>\n]+>|[^\s)]+)" + LINK_TITLE + r"\s*\)"
)
REFERENCE = re.compile(
    r"^ {0,3}\[(?P<label>[^\]\n]+)\]:\s*(?P<dest><[^>\n]+>|\S+)" + LINK_TITLE + r"\s*$"
)
INLINE_CODE = re.compile(r"`[^`\n]*`")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def body_lines(text: str) -> list[tuple[int, str]]:
    """围栏代码块之外的原始行；围栏标记允许任意缩进，覆盖列表项内的代码块。"""
    lines = []
    fence = ""
    for number, line in enumerate(text.splitlines(), 1):
        marker = FENCE.match(line)
        if marker:
            value, rest = marker.groups()
            if not fence:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence) and not rest.strip():
                fence = ""
            continue
        if not fence:
            lines.append((number, line))
    return lines


def link_targets(lines: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """返回 (行号, 链接目标)：行内链接与引用式链接定义；行内代码中的内容不算链接。"""
    targets = []
    for number, line in lines:
        prose = INLINE_CODE.sub("", line)
        targets.extend((number, match.group("dest")) for match in LINK.finditer(prose))
        reference = REFERENCE.match(prose)
        if reference and not reference.group("label").startswith("^"):
            targets.append((number, reference.group("dest")))
    return targets


def heading_title(raw: str) -> str:
    """标题的可见文字：行内代码只去掉反引号保留内容，其余部分去掉 HTML 标签并把链接换成链接文字。"""
    parts = re.split(r"(`[^`\n]*`)", raw)
    visible = []
    for index, part in enumerate(parts):
        if index % 2:
            visible.append(part.strip("`"))
        else:
            part = re.sub(r"<[^>]+>", "", part)
            visible.append(LINK.sub(lambda match: match.group("text"), part))
    return "".join(visible)


def anchors(lines: list[tuple[int, str]]) -> set[str]:
    """按 GitHub 规则生成章节锚点，重名标题依次加 -1、-2 后缀；另收集 HTML 的 id/name。"""
    result: set[str] = set()
    for _, line in lines:
        prose = INLINE_CODE.sub("", line)
        result.update(re.findall(r'<(?:a|h[1-6])\b[^>]*(?:id|name)="([^"]+)"', prose))
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if not heading:
            continue
        title = heading_title(heading.group(1)).lower()
        slug = "".join(
            char for char in title if char in "-_ " or unicodedata.category(char)[0] in "LNM"
        ).replace(" ", "-")
        candidate = slug
        suffix = 0
        while candidate in result:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        result.add(candidate)
    return result


def link_scope(root: Path) -> set[Path]:
    """做链接与锚点检查的文件。"""
    files = {root / name for name in ROOT_DOCUMENTS} | {
        path for path in (root / "docs").rglob("*.md") if not path.is_relative_to(root / ARCHIVE)}
    experiments = root / "experiments"
    if experiments.is_dir():
        files |= set(experiments.rglob("README*.md"))
        if (root / EXPERIMENTS_INDEX).is_file():
            files.add(root / EXPERIMENTS_INDEX)
    if (root / ".scratch").is_dir():
        files |= set((root / ".scratch").rglob("*.md"))
    return files


def living_documents(root: Path) -> dict[Path, Budget]:
    """受预算、路径与状态行检查约束的活文档及其预算。"""
    result: dict[Path, Budget] = {}
    for directory in LIVING_DIRECTORIES:
        for path in (root / directory).rglob("*.md"):
            result[path] = LIVING_BUDGET
    for name in LIVING_FILES:
        result[root / name] = LIVING_BUDGET
    for name, budget in SPECIAL_BUDGETS.items():
        result[root / name] = budget
    for path in (root / "docs").rglob("INDEX.md"):
        result[path] = INDEX_BUDGET
    result[root / EXPERIMENTS_INDEX] = INDEX_BUDGET
    result[root / "AGENTS.md"] = AGENTS_BUDGET
    return {path: budget for path, budget in result.items()
            if path.is_file() and not path.is_relative_to(root / ARCHIVE)}


def check_budgets(root: Path) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    labels = ("字符数", "行数", "最长行")
    for path, budget in sorted(living_documents(root).items()):
        name = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        longest = max(range(len(lines)), key=lambda index: len(lines[index]), default=0)
        actual = (len(text), len(lines), len(lines[longest]) if lines else 0)
        allowed = BUDGET_WHITELIST.get(name, budget)
        for label, value, limit in zip(labels, actual, allowed):
            if limit is not None and value > limit:
                line = longest + 1 if label == "最长行" else 1
                errors.append(f"{name}:{line} 超出预算：{label} {value} > {limit}")
        if name in BUDGET_WHITELIST and name not in BYTE_VERIFIED and all(
                limit is None or value <= limit for value, limit in zip(actual, budget)):
            warnings.append(f"{name}:1 已回到预算内，请从 BUDGET_WHITELIST 删除")
    return errors, warnings


def repo_path(token: str) -> str | None:
    """反引号里的内容是仓库路径时返回路径部分；通配、占位符与带空格的命令不算。"""
    token = token.strip()
    if not token.startswith(PATH_ROOTS) or re.search(r"[\s*<>{}|…$=,]", token):
        return None
    path = re.split(r"::|#|:(?=\d)", token, maxsplit=1)[0]
    return path.rstrip("/.;:，。；、）)") or None


def check_paths(root: Path) -> list[str]:
    errors = []
    for path in sorted(living_documents(root)):
        name = path.relative_to(root).as_posix()
        for number, line in body_lines(path.read_text(encoding="utf-8")):
            for token in CODE_SPAN.findall(line):
                target = repo_path(token)
                if target is None or target in REMOVED_PATHS or (name, target) in KNOWN_MISSING_PATHS:
                    continue
                if not (root / target).exists():
                    errors.append(f"{name}:{number} 反引号路径不存在：{target}")
    return errors


def check_status_lines(root: Path) -> list[str]:
    warnings = []
    for path in sorted(living_documents(root)):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines()[:15], 1):
            if STATUS_LINE.match(line):
                if len(DATE.findall(line)) >= 3:
                    warnings.append(
                        f"{path.relative_to(root).as_posix()}:{number} 状态行含 3 个以上日期，像变更日志")
                break
    return warnings


def check_experiments(root: Path) -> list[str]:
    index = root / EXPERIMENTS_INDEX
    experiments = root / "experiments"
    if not experiments.is_dir():
        return []
    if not index.is_file():
        return [f"缺少文档：{EXPERIMENTS_INDEX.as_posix()}"]
    text = index.read_text(encoding="utf-8")
    return [
        f"{EXPERIMENTS_INDEX.as_posix()}:1 未登记的包：experiments/{package.name}/"
        for package in sorted(experiments.iterdir())
        if package.is_dir() and package.name != "__pycache__" and any(package.glob("*.py"))
        and f"`{package.name}`" not in text]


def check_product_ownership(root: Path) -> list[str]:
    """kototoki/ 的每个模块与子包都要出现在某篇模块页的"代码与验证入口"一节。"""
    product = root / PRODUCT
    if not product.is_dir():
        return []
    owned = ""
    for page in (root / MODULES).rglob("*.md"):
        section = False
        for _, line in body_lines(page.read_text(encoding="utf-8")):
            heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if heading:
                section = OWNERSHIP_SECTION in heading.group(1)
            elif section:
                owned += line + "\n"
    units = [f"{PRODUCT.as_posix()}/{path.name}" for path in product.glob("*.py")
             if path.name not in ("__init__.py", "__main__.py")]
    units += [f"{PRODUCT.as_posix()}/{path.name}/" for path in product.iterdir()
              if path.is_dir() and (path / "__init__.py").is_file()]
    return [f"{MODULES.as_posix()}:1 没有模块页在\"{OWNERSHIP_SECTION}\"里列出 {unit}"
            for unit in sorted(units) if unit not in owned and unit not in KNOWN_UNOWNED_MODULES]


def check_adr_index(root: Path) -> list[str]:
    """ADR 文件、决定索引"全部 ADR"表（含跳转页一行）与"编号从 N 起"三者一致。"""
    index = root / ADR_INDEX
    if not index.is_file():
        return []
    name = ADR_INDEX.as_posix()
    files = {path.name[:4] for path in index.parent.glob("[0-9][0-9][0-9][0-9]-*.md")}
    listed: dict[str, int] = {}
    following = None
    section = False
    for number, line in enumerate(index.read_text(encoding="utf-8").splitlines(), 1):
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            section = heading.group(1) == "全部 ADR"
            continue
        if not section:
            continue
        row = re.match(r"^\|\s*\[(\d{4})\]\(", line)
        if row:
            listed[row.group(1)] = number
        if line.startswith("跳转页"):
            first = re.search(r"编号从\s*(\d{4})\s*起", line)
            if first:
                following = (first.group(1), number)
            for group in re.split(r"[；。]", line.split("新 ADR")[0]):
                if "→" in group:
                    for jump in re.findall(r"\d{4}", group.split("→")[0]):
                        listed[jump] = number
    errors = [f"{name}:1 \"全部 ADR\"没有登记 {number}" for number in sorted(files - set(listed))]
    errors += [f"{name}:{listed[number]} 登记的 {number} 没有对应的 ADR 文件"
               for number in sorted(set(listed) - files)]
    if files:
        expected = f"{int(max(files)) + 1:04d}"
        if following is None:
            errors.append(f"{name}:1 缺少\"新 ADR 编号从 N 起\"")
        elif following[0] != expected:
            errors.append(f"{name}:{following[1]} \"编号从 {following[0]} 起\"应为 {expected}")
    return errors


def check_registration(root: Path, documents: dict, graph: dict[Path, set[Path]]) -> list[str]:
    """docs/ 下每篇（含归档件）至少被一个 INDEX.md 或子索引（docs/research/topics/）链接。"""
    registered: set[Path] = set()
    for source, targets in graph.items():
        if source.name == "INDEX.md" or source.is_relative_to(root / SUBINDEX):
            registered |= targets
    archived = set((root / ARCHIVE).rglob("*.md")) if (root / ARCHIVE).is_dir() else set()
    for source, lines in documents.items():
        if source.name == "INDEX.md":
            for _, raw in link_targets(lines):
                path = urlsplit(raw.strip("<>")).path
                if path and (source.parent / unquote(path)).resolve() in archived:
                    registered.add((source.parent / unquote(path)).resolve())
    return [
        f"{path.relative_to(root).as_posix()}:1 没有被任何 INDEX.md 或子索引链接"
        for path in sorted(set(documents) | archived)
        if path.is_relative_to(root / "docs") and path.name != "INDEX.md" and path not in registered]


def check_documents(root: Path) -> tuple[list[str], int, int, int]:
    root = root.resolve()
    files = link_scope(root)
    errors = []
    documents = {}
    for path in sorted(files):
        if not path.is_file():
            errors.append(f"缺少文档：{path.relative_to(root).as_posix()}")
        else:
            documents[path] = body_lines(path.read_text(encoding="utf-8"))
    sections = {path: anchors(lines) for path, lines in documents.items()}
    graph: dict[Path, set[Path]] = {path: set() for path in documents}
    links = 0
    external = 0
    for source, lines in documents.items():
        for number, raw in link_targets(lines):
            destination = raw.strip("<>")
            url = urlsplit(destination)
            if url.scheme or url.netloc:
                continue
            links += 1
            target = (source.parent / unquote(url.path)).resolve() if url.path else source
            location = f"{source.relative_to(root).as_posix()}:{number}"
            if not target.is_relative_to(root):
                external += 1
                continue
            if (source.is_relative_to(root / ".scratch")
                    and target.relative_to(root).as_posix() in FROZEN_DEAD_TARGETS):
                continue
            if not target.exists():
                errors.append(f"{location} 链接目标不存在：{destination}")
                continue
            if target in documents:
                graph[source].add(target)
            if url.fragment and target.suffix == ".md":
                if target not in sections:
                    sections[target] = anchors(body_lines(target.read_text(encoding="utf-8")))
                if unquote(url.fragment) not in sections[target]:
                    errors.append(f"{location} 章节不存在：{destination}")
    visited: set[Path] = set()
    pending = [root / ARCHITECTURE_INDEX]
    while pending:
        current = pending.pop()
        if current not in visited:
            visited.add(current)
            pending.extend(graph.get(current, set()) - visited)
    for module in sorted(set((root / MODULES).rglob("*.md")) - visited):
        errors.append(f"架构入口不可达：{module.relative_to(root).as_posix()}")
    errors += check_registration(root, documents, graph)
    return errors, len(documents), links - external, external


def check_all(root: Path) -> tuple[list[str], list[str], int, int, int]:
    """全部检查：返回 (错误, 告警, 文档数, 本地链接数, 仓库外链接数)。"""
    root = root.resolve()
    errors, documents, links, external = check_documents(root)
    budget_errors, warnings = check_budgets(root)
    errors += budget_errors
    errors += check_paths(root)
    errors += check_experiments(root)
    errors += check_product_ownership(root)
    errors += check_adr_index(root)
    warnings += check_status_lines(root)
    return errors, warnings, documents, links, external


def main() -> int:
    parser = argparse.ArgumentParser(description="检查文档的链接、登记、预算、路径与模块归属。")
    parser.add_argument(
        "root",
        nargs="?",
        help="项目根目录；默认是本脚本所在 scripts/ 的上级，从别处调用时传目标项目根",
    )
    args = parser.parse_args()
    # 错误信息含中文与文档里的任意字符；控制台代码页不是 UTF-8（本机默认 cp1252）时转义而不崩溃。
    sys.stdout.reconfigure(errors="backslashreplace")
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    errors, warnings, documents, links, external = check_all(root)
    for warning in warnings:
        print(f"告警：{warning}")
    if errors:
        print("\n".join(errors))
        print(f"文档检查未通过：{len(errors)} 处错误。")
        return 1
    print(f"文档检查通过：{documents} 篇，{links} 个本地链接；登记、预算、路径、模块归属与 ADR 编号一致。"
          f"未检查 {external} 个指向仓库之外的链接；{len(warnings)} 条告警。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
