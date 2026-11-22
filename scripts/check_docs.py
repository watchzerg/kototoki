"""检查仓库文档的链接、可达性、索引、体量与标题骨架；只依赖标准库，不联网。

规则正文在 docs/agents/documentation.md，本脚本只负责实现。
检查范围：根目录 README、AGENTS、GLOSSARY、CODING_STANDARDS 与 docs/ 下全部 Markdown。
- 本地链接目标与章节锚点必须存在；
- 每篇文档都能从 AGENTS.md 沿文档间链接到达；
- docs/adr、docs/research 下的文档（含子目录）由所在目录的 INDEX.md 直接链接；
- 除 docs/research、docs/adr 外，单页不超过 16 KiB，围栏代码外每段与每个表格单元格不超过 400 字符；
- 模块页与行为规格页的二级标题依次符合固定骨架；
- 页首 frontmatter 的 covers 每条至少匹配一个现存文件。
--affected [BASE] 改为只提示：列出相对 BASE（默认 HEAD）的改动与未跟踪文件命中 covers 的页面，
并标出本次没有修改的页面；退出码恒为 0，不属于门禁。
"""

import argparse
import re
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT_DOCUMENTS = ("README.md", "AGENTS.md", "GLOSSARY.md", "CODING_STANDARDS.md")
ENTRY = Path("AGENTS.md")
INDEXED_DIRECTORIES = (Path("docs/adr"), Path("docs/research"))
PAGE_BYTES = 16 * 1024
LINE_CHARS = 400
BUDGET_EXEMPT = (Path("docs/research"), Path("docs/adr"))
MODULES = Path("docs/architecture/modules")
BEHAVIORS = Path("docs/behaviors")
MODULE_HEADINGS = (
    "定位与阅读",
    "当前行为规格",
    "实现设计",
    "接口与依赖",
    "代码与验证入口",
    "变更与决策来源",
)
BEHAVIOR_HEADINGS = ("场景与前提", "操作与可观察结果", "边界与错误情况", "相关模块")
LINK_TITLE = r"""(?:\s+(?:"[^"\n]*"|'[^'\n]*'|\([^)\n]*\)))?"""
LINK = re.compile(
    r"!?\[(?P<text>[^\]\n]*)\]\(\s*(?P<dest><[^>\n]+>|[^\s)]+)" + LINK_TITLE + r"\s*\)"
)
REFERENCE = re.compile(
    r"^ {0,3}\[(?P<label>[^\]\n]+)\]:\s*(?P<dest><[^>\n]+>|\S+)" + LINK_TITLE + r"\s*$"
)
INLINE_CODE = re.compile(r"`[^`\n]*`")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
H2 = re.compile(r"^\s{0,3}##\s+(.+?)(?:\s+#+)?\s*$")
LIST_ITEM = re.compile(r"^\s*-\s+(.+?)\s*$")


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


def table_cells(line: str) -> list[str]:
    """按未转义且不在行内代码中的 | 切分表格行。"""
    cells = []
    cell = ""
    code = False
    for index, char in enumerate(line):
        if char == "`":
            code = not code
        if char == "|" and not code and (index == 0 or line[index - 1] != "\\"):
            cells.append(cell)
            cell = ""
        else:
            cell += char
    cells.append(cell)
    return [cell.strip() for cell in cells]


def budget_errors(relative: Path, text: str, lines: list[tuple[int, str]]) -> list[str]:
    """单页字节数、段落字符数与表格单元格字符数；围栏代码不计。"""
    errors = []
    size = len(text.encode("utf-8"))
    if size > PAGE_BYTES:
        errors.append(f"{relative} 超出单页预算：{size} 字节 > {PAGE_BYTES}")
    for number, line in lines:
        if line.strip().startswith("|"):
            for cell in table_cells(line.strip()):
                if len(cell) > LINE_CHARS:
                    errors.append(
                        f"{relative}:{number} 表格单元格超出预算：{len(cell)} 字符 > {LINE_CHARS}"
                    )
        elif len(line.rstrip()) > LINE_CHARS:
            errors.append(
                f"{relative}:{number} 段落超出预算：{len(line.rstrip())} 字符 > {LINE_CHARS}"
            )
    return errors


def document_paths(root: Path) -> set[Path]:
    return {root / name for name in ROOT_DOCUMENTS} | set((root / "docs").rglob("*.md"))


def covers(text: str) -> list[tuple[int, str]]:
    """页首 `---` 之间 `covers:` 下的 `- glob` 列表，带行号；没有 frontmatter 或未声明时为空。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    result = []
    inside = False
    for number, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            return result
        item = LIST_ITEM.match(line)
        if item and inside:
            result.append((number, item.group(1)))
        elif not item:
            inside = line.strip() == "covers:"
    return []


def covers_errors(root: Path, relative: Path, text: str) -> list[str]:
    """每条 covers 是仓库根相对的 glob，且至少匹配一个现存文件；匹配到目录时算其下全部文件。"""
    errors = []
    for number, pattern in covers(text):
        location = f"{relative}:{number}"
        if pattern.startswith("/") or ".." in PurePosixPath(pattern).parts:
            errors.append(f"{location} covers 须为仓库根相对路径：{pattern}")
        elif not any(
            path.is_file() or any(file.is_file() for file in path.rglob("*"))
            for path in root.glob(pattern)
        ):
            errors.append(f"{location} covers 没有匹配的文件：{pattern}")
    return errors


def check_documents(root: Path) -> tuple[list[str], int, int]:
    root = root.resolve()
    files = document_paths(root)
    errors = []
    texts = {}
    for path in sorted(files):
        if not path.is_file():
            errors.append(f"缺少文档：{path.relative_to(root)}")
        else:
            texts[path] = path.read_text(encoding="utf-8")
    documents = {path: body_lines(text) for path, text in texts.items()}
    sections = {path: anchors(lines) for path, lines in documents.items()}
    graph: dict[Path, set[Path]] = {path: set() for path in documents}
    links = 0
    for source, lines in documents.items():
        for number, raw in link_targets(lines):
            destination = raw.strip("<>")
            url = urlsplit(destination)
            if url.scheme or url.netloc:
                continue
            links += 1
            target = (source.parent / unquote(url.path)).resolve() if url.path else source
            location = f"{source.relative_to(root)}:{number}"
            if not target.is_relative_to(root):
                errors.append(f"{location} 链接越出仓库：{destination}")
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
    pending = [root / ENTRY]
    while pending:
        current = pending.pop()
        if current not in visited:
            visited.add(current)
            pending.extend(graph.get(current, set()) - visited)
    for path in sorted(set(documents) - visited):
        errors.append(f"入口不可达：{path.relative_to(root)}（从 AGENTS.md 沿链接到不了）")
    for directory in INDEXED_DIRECTORIES:
        index = root / directory / "INDEX.md"
        entries = sorted(set((root / directory).rglob("*.md")) - {index})
        if not entries:
            continue
        if index not in documents:
            errors.append(f"缺少索引：{directory / 'INDEX.md'}")
            continue
        for entry in entries:
            if entry not in graph[index]:
                errors.append(
                    f"索引未登记：{entry.relative_to(root)}"
                    f"（应由 {directory / 'INDEX.md'} 直接链接）"
                )
    for path in sorted(documents):
        relative = path.relative_to(root)
        if not any(relative.is_relative_to(exempt) for exempt in BUDGET_EXEMPT):
            errors.extend(budget_errors(relative, texts[path], documents[path]))
        errors.extend(covers_errors(root, relative, texts[path]))
    skeletons: list[tuple[Path, tuple[str, ...]]] = [
        (path, MODULE_HEADINGS) for path in (root / MODULES).glob("*.md")
    ]
    skeletons += [
        (path, BEHAVIOR_HEADINGS)
        for path in (root / BEHAVIORS).glob("*.md")
        if path.name != "INDEX.md"
    ]
    for path, expected in sorted(skeletons):
        actual = tuple(
            heading_title(match.group(1)).strip()
            for _, line in documents[path]
            if (match := H2.match(line))
        )
        if actual != expected:
            errors.append(
                f"{path.relative_to(root)} 二级标题应依次为：{'、'.join(expected)}；"
                f"实际：{'、'.join(actual) or '无'}"
            )
    return errors, len(documents), links


def git_lines(root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def claims(path: str, pattern: str) -> bool:
    """改动路径是否落在一条 covers 内；与 covers_errors 一致，glob 指向目录时算其下全部文件。"""
    candidate = PurePosixPath(path)
    return candidate.full_match(pattern) or candidate.full_match(pattern.rstrip("/") + "/**")


def report_affected(root: Path, base: str) -> int:
    """改动包括相对 base 的已提交、已暂存与未暂存差异和未跟踪文件；删除的文件按原路径匹配。"""
    try:
        changed = set(
            git_lines(root, "diff", "--name-only", "--no-renames", "--relative", base)
        ) | set(git_lines(root, "ls-files", "--others", "--exclude-standard"))
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or error
        print(f"无法读取相对 {base} 的改动：{str(detail).strip()}")
        return 0
    pages = []
    for path in sorted(file for file in document_paths(root) if file.is_file()):
        patterns = [pattern for _, pattern in covers(path.read_text(encoding="utf-8"))]
        if any(claims(change, pattern) for change in changed for pattern in patterns):
            pages.append(path.relative_to(root).as_posix())
    if not pages:
        print(f"相对 {base} 的改动没有命中任何页面的 covers。")
        return 0
    print(f"相对 {base} 的改动命中以下页面的 covers：")
    for page in pages:
        print(f"- {page}" + ("" if page in changed else "（本次未修改）"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查文档的本地链接、锚点、可达性、目录索引、体量、标题骨架与 covers。"
    )
    parser.add_argument(
        "root",
        nargs="?",
        help="项目根目录；默认是本脚本所在 scripts/ 的上级，从别处调用时传目标项目根",
    )
    parser.add_argument(
        "--affected",
        nargs="?",
        const="HEAD",
        metavar="BASE",
        help="只提示：列出相对 BASE（默认 HEAD）的改动命中 covers 的页面，退出码恒为 0",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    if args.affected:
        return report_affected(root, args.affected)
    errors, documents, links = check_documents(root)
    if errors:
        print("\n".join(errors))
        return 1
    print(
        f"文档检查通过：{documents} 篇，{links} 个本地链接；"
        "全部可从 AGENTS.md 到达，索引、体量、标题骨架与 covers 符合规则。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
