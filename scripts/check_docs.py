"""检查仓库文档的本地链接、章节锚点与模块可达性；只依赖标准库，不联网。

检查范围：根目录 README、AGENTS、GLOSSARY、CODING_STANDARDS 与 docs/ 下全部 Markdown。
模块页（docs/architecture/modules/*.md）必须能从 docs/architecture/INDEX.md 沿链接到达。
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


def check_documents(root: Path) -> tuple[list[str], int, int]:
    root = root.resolve()
    files = {root / name for name in ROOT_DOCUMENTS} | set((root / "docs").rglob("*.md"))
    errors = []
    documents = {}
    for path in sorted(files):
        if not path.is_file():
            errors.append(f"缺少文档：{path.relative_to(root)}")
        else:
            documents[path] = body_lines(path.read_text(encoding="utf-8"))
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
    pending = [root / ARCHITECTURE_INDEX]
    while pending:
        current = pending.pop()
        if current not in visited:
            visited.add(current)
            pending.extend(graph.get(current, set()) - visited)
    for module in sorted(set((root / MODULES).rglob("*.md")) - visited):
        errors.append(f"架构入口不可达：{module.relative_to(root)}")
    return errors, len(documents), links


def main() -> int:
    parser = argparse.ArgumentParser(description="检查文档的本地链接、锚点与模块可达性。")
    parser.add_argument(
        "root",
        nargs="?",
        help="项目根目录；默认是本脚本所在 scripts/ 的上级，从别处调用时传目标项目根",
    )
    args = parser.parse_args()
    # 错误信息含中文与文档里的任意字符；控制台代码页不是 UTF-8（本机默认 cp1252）时转义而不崩溃。
    sys.stdout.reconfigure(errors="backslashreplace")
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    errors, documents, links = check_documents(root)
    if errors:
        print("\n".join(errors))
        return 1
    print(f"文档检查通过：{documents} 篇，{links} 个本地链接；模块页均可从架构入口到达。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
