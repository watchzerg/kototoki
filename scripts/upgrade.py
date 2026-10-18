"""把可升级的组件升到最新稳定版（docs/development/dependencies.md#升级）。

用法（经 `just upgrade` 调用；联网、改环境与 `assets.toml`，须先问）：

    python scripts/upgrade.py [--check] [--films DIR] [python] [llama.cpp] [ffmpeg]   # 省略组件即全部

- python：CUDA 12 锚点（`ANCHORS`）保持原钉版；其余直接依赖取 uv 解析出的最新稳定版并重新钉版；
  传递依赖一起升，但跳过主版本升级（日历版本号除外），跳过项列入报告。
- llama.cpp：GitHub 最新稳定版（`releases/latest`）的 `nightly-tag.txt` 指向的构建，CUDA 主版本与清单现有记录相同、
  取其中最高的 `win-cuda-*-x64`；默认路径直接切换，真实模型验证（`just smoke translate_product`）另行批准后跑。
- ffmpeg：BtbN 最新带日期 tag 的 autobuild 中最高维护分支的 win64 gpl 构建；用产品 extract 代码在 `--films`
  的每部 `.mkv` 上与当前默认构建对照派生 WAV，PCM、样本数、补偿记录与告警全部相同才切换默认路径，否则清单还原。
- `--check` 只报告可升级项，不改任何文件。

压缩包 SHA256 取自 GitHub 的 asset digest（缺失则拒绝），清单写法同 `scripts/assets.py`。只用标准库与仓库内同样只依赖
标准库的模块。报告写 `.local/upgrade/<UTC>/report.json`；文档同步与 smoke 不在本脚本内，结束时列出待办。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from types import SimpleNamespace
from typing import Any
from urllib.request import Request, urlopen
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import assets  # noqa: E402
from kototoki import config, media  # noqa: E402
from kototoki.artifacts import utc_now  # noqa: E402

PYPROJECT = REPO / "pyproject.toml"
LOCK = REPO / "uv.lock"
REPORT_ROOT = REPO / ".local" / "upgrade"
DEFAULT_FILMS = REPO / ".local" / "bilingual-fullfilm-08" / "input"
# 默认路径里带工具版本号的文件；版本号由 tests/core/test_assets_manifest.py 钉住与清单一致。
DEFAULT_PATH_FILES = ("kototoki/config.py", "kototoki.toml.example")
# CUDA 12 锚点：torch 系取 cu128 索引、CTranslate2 只有 CUDA 12 wheel；升级须人工决定（规格 §7.2 选版规则）。
ANCHORS = frozenset({"torch", "torchaudio", "torchcodec", "ctranslate2"})
GITHUB_API = "https://api.github.com/repos"
COMPONENTS = ("python", "llama.cpp", "ffmpeg")


class UpgradeError(RuntimeError):
    """一个组件无法升级；消息说明原因，文件已还原。"""


# --- 通用 -------------------------------------------------------------------------------------

def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _release(version: str) -> list[int]:
    return [int(part) for part in re.findall(r"\d+", version.split("+")[0])[:2]]


def is_major_bump(old: str, new: str) -> bool:
    """首个数字段变化即主版本升级；0.x 看次版本；首段 ≥1900 视为日历版本号，不算。"""
    a, b = _release(old), _release(new)
    if not a or not b or a[0] >= 1900:
        return False
    if a[0] == 0 and b[0] == 0:
        return a[:2] != b[:2]
    return a[0] != b[0]


def run_uv(*args: str) -> str:
    result = subprocess.run([shutil.which("uv") or "uv", *args], cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8")
    if result.returncode != 0:
        raise UpgradeError(f"uv {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()[-2000:]}")
    return result.stderr + result.stdout


def fetch_json(url: str) -> Any:
    with urlopen(Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "kototoki-upgrade"})) as r:
        return json.load(r)


def fetch_text(url: str) -> str:
    with urlopen(Request(url, headers={"User-Agent": "kototoki-upgrade"})) as response:
        return response.read().decode("utf-8")


# --- python -----------------------------------------------------------------------------------

def pinned_dependencies(pyproject_text: str) -> dict[str, tuple[str, str]]:
    """{规范名: (原依赖串, 钉住的版本)}：`[project].dependencies` 里用 `==` 钉住的非锚点依赖。"""
    pins = {}
    for spec in tomllib.loads(pyproject_text)["project"]["dependencies"]:
        if match := re.fullmatch(r"([A-Za-z0-9_.\-]+)==([^\s;,]+)", spec.strip()):
            name = normalize(match.group(1))
            if name not in ANCHORS:
                pins[name] = (spec, match.group(2))
    return pins


def direct_names(pyproject_text: str) -> set[str]:
    return {normalize(re.match(r"[A-Za-z0-9_.\-]+", spec.strip()).group(0))
            for spec in tomllib.loads(pyproject_text)["project"]["dependencies"]}


def parse_updates(uv_output: str) -> dict[str, tuple[str, str]]:
    """`uv lock` 输出里的 `Update(d) <name> v<old> -> v<new>` 行。"""
    return {normalize(m.group(1)): (m.group(2), m.group(3))
            for m in re.finditer(r"^Updated? (\S+) v(\S+) -> v(\S+)$", uv_output, re.MULTILINE)}


def locked_versions(lock_text: str) -> dict[str, str]:
    return {normalize(p["name"]): p["version"] for p in tomllib.loads(lock_text)["package"] if "version" in p}


def plan_python(updates: Mapping[str, tuple[str, str]], direct: set[str]) -> tuple[list[str], dict[str, tuple[str, str]]]:
    """(允许升级的包, 跳过的传递依赖主版本升级)。"""
    allowed, skipped = [], {}
    for name, (old, new) in sorted(updates.items()):
        if name in ANCHORS:
            continue
        if name not in direct and is_major_bump(old, new):
            skipped[name] = (old, new)
        else:
            allowed.append(name)
    return allowed, skipped


def upgrade_python(check: bool) -> dict[str, Any]:
    original_pyproject, original_lock = PYPROJECT.read_text(encoding="utf-8"), LOCK.read_text(encoding="utf-8")
    pins = pinned_dependencies(original_pyproject)
    unpinned = original_pyproject
    for spec, _ in pins.values():
        unpinned = unpinned.replace(f'"{spec}"', f'"{spec.split("==")[0]}"')
    try:
        PYPROJECT.write_text(unpinned, encoding="utf-8", newline="\n")
        allowed, skipped = plan_python(parse_updates(run_uv("lock", "--dry-run", "--upgrade")),
                                       direct_names(original_pyproject))
        if check or not allowed:
            PYPROJECT.write_text(original_pyproject, encoding="utf-8", newline="\n")
            return {"status": "available" if allowed else "up to date", "upgrades": allowed, "skipped_major": skipped}
        changes = parse_updates(run_uv("lock", *[arg for name in allowed for arg in ("-P", name)]))
        versions = locked_versions(LOCK.read_text(encoding="utf-8"))
        repinned = unpinned
        for name, (spec, _) in pins.items():
            repinned = repinned.replace(f'"{spec.split("==")[0]}"', f'"{spec.split("==")[0]}=={versions[name]}"')
        PYPROJECT.write_text(repinned, encoding="utf-8", newline="\n")
        run_uv("lock")
        run_uv("sync", "--locked")
    except BaseException:
        PYPROJECT.write_text(original_pyproject, encoding="utf-8", newline="\n")
        LOCK.write_text(original_lock, encoding="utf-8", newline="\n")
        raise
    return {"status": "upgraded", "changes": changes, "skipped_major": skipped,
            "pending": "just smoke vad_pyannote forced_align stt_frozen_window x0_frozen_window（占 GPU，须用户批准）"}


# --- 清单与默认路径 ---------------------------------------------------------------------------

def _key(name: str) -> str:
    return f'"{name}"' if "." in name else name


def render_tool(name: str, tool: Mapping[str, Any]) -> str:
    key, value = _key(name), lambda v: json.dumps(v, ensure_ascii=False)
    lines = [f"[tools.{key}]"]
    lines += [f"{field} = {value(tool[field])}" for field in
              ("version", "source", "upstream_tag", "upstream_commit", "published_at", "note") if field in tool]
    for archive in tool["archives"]:
        lines += ["", f"[[tools.{key}.archives]]"]
        lines += [f"{field} = {value(archive[field])}" for field in ("name", "url", "sha256", "strip") if field in archive]
    lines += ["", f"[tools.{key}.files]"]
    lines += [f'{value(path)} = {{ sha256 = "{e["sha256"]}", size = {e["size"]} }}' for path, e in sorted(tool["files"].items())]
    return "\n".join(lines) + "\n"


def replace_tool_block(text: str, name: str, rendered: str) -> str:
    """替换 `[tools.<name>]` 起、到下一个不属于它的表头或 `# ---` 分节注释为止的整块（含块尾空行）。"""
    key = _key(name)
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.strip() == f"[tools.{key}]")
    end = start + 1
    own = (f"[tools.{key}.", f"[[tools.{key}.")
    while end < len(lines):
        line = lines[end].lstrip()
        if line.startswith("# ---") or (line.startswith("[") and not line.startswith(own)):
            break
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    tail = "".join(lines[end:]).lstrip("\n")
    return "".join(lines[:start]) + rendered + ("\n" + tail if tail else "")


def switch_default_paths(name: str, old: str, new: str, files: Sequence[str] = DEFAULT_PATH_FILES,
                         root: Path = REPO) -> list[str]:
    changed = []
    for relative in files:
        path = Path(root) / relative
        text = path.read_text(encoding="utf-8")
        updated = text.replace(f".local/tools/{name}/{old}/", f".local/tools/{name}/{new}/")
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")
            changed.append(relative)
    return changed


def zip_entries(archive: Path, strip: str = "", only: set[str] | None = None) -> dict[str, dict[str, Any]]:
    entries = {}
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.is_dir() or not member.filename.startswith(strip):
                continue
            relative = member.filename[len(strip):]
            if only is None or relative in only:
                entries[relative] = {"sha256": hashlib.sha256(bundle.read(member)).hexdigest(), "size": member.file_size}
    return entries


def digest(asset: Mapping[str, Any]) -> str:
    value = asset.get("digest") or ""
    if not value.startswith("sha256:"):
        raise UpgradeError(f"GitHub asset {asset['name']} has no sha256 digest; cannot pin it")
    return value.removeprefix("sha256:")


def install_new_tool(name: str, tool: dict[str, Any], *, fetch_files: Callable[[list[Path]], dict[str, Any]],
                     verify: Callable[[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """下载压缩包、写清单、安装；`verify(old, new)` 返回 {"passed": bool, ...}，不通过则清单还原、默认路径不切换。"""
    current = assets.load_manifest()["tools"][name]
    paths = []
    for archive in tool["archives"]:
        cached = assets.DOWNLOADS_ROOT / name / archive["name"]
        if not (cached.is_file() and assets._sha256(cached) == archive["sha256"]):
            assets.download(archive["url"], cached, archive["sha256"])
        paths.append(cached)
    tool["files"] = fetch_files(paths)
    original = assets.MANIFEST.read_text(encoding="utf-8")
    assets.MANIFEST.write_text(replace_tool_block(original, name, render_tool(name, tool)), encoding="utf-8", newline="\n")
    result: dict[str, Any] = {"old": current["version"], "new": tool["version"]}
    try:
        print(f"tools.{name}: {assets.install_tool(name, assets.load_manifest()['tools'][name])}", flush=True)
        if verify is not None:
            result["verify"] = verify(current["version"], tool["version"])
            if not result["verify"]["passed"]:
                raise UpgradeError(f"{name} {tool['version']} failed verification; see report")
    except BaseException:
        assets.MANIFEST.write_text(original, encoding="utf-8", newline="\n")
        raise
    result["default_paths_changed"] = switch_default_paths(name, current["version"], tool["version"])
    result["status"] = "upgraded"
    return result


# --- llama.cpp --------------------------------------------------------------------------------

def pick_llama(release: Mapping[str, Any], tag: str, cuda_major: str) -> tuple[str, dict, dict]:
    """(cuda 版本, 主程序 asset, cudart asset)：同 CUDA 主版本里最高的 win x64 构建。"""
    builds = {}
    for asset in release["assets"]:
        if m := re.fullmatch(rf"llama-{re.escape(tag)}-bin-win-cuda-({cuda_major}\.\d+)-x64\.zip", asset["name"]):
            builds[m.group(1)] = asset
    if not builds:
        raise UpgradeError(f"llama.cpp {tag}: no win-cuda-{cuda_major}.x x64 build")
    cuda = max(builds, key=lambda v: tuple(map(int, v.split("."))))
    cudart = next((a for a in release["assets"] if a["name"] == f"cudart-llama-bin-win-cuda-{cuda}-x64.zip"), None)
    if cudart is None:
        raise UpgradeError(f"llama.cpp {tag}: missing cudart-llama-bin-win-cuda-{cuda}-x64.zip")
    return cuda, builds[cuda], cudart


def upgrade_llama(check: bool) -> dict[str, Any]:
    current = assets.load_manifest()["tools"]["llama.cpp"]
    stable = fetch_json(f"{GITHUB_API}/ggml-org/llama.cpp/releases/latest")
    pointer = next((a for a in stable["assets"] if a["name"] == "nightly-tag.txt"), None)
    if pointer is None:
        raise UpgradeError(f"llama.cpp {stable['tag_name']}: no nightly-tag.txt asset")
    tag = fetch_text(pointer["browser_download_url"]).strip()
    if tag == current.get("upstream_tag"):
        return {"status": "up to date", "version": current["version"], "stable": stable["tag_name"]}
    release = fetch_json(f"{GITHUB_API}/ggml-org/llama.cpp/releases/tags/{tag}")
    cuda_major = re.search(r"cuda(\d+)\.", current["version"]).group(1)
    cuda, main_asset, cudart = pick_llama(release, tag, cuda_major)
    version = f"{tag}-cuda{cuda}"
    if check:
        return {"status": "available", "old": current["version"], "new": version, "stable": stable["tag_name"]}
    commit = fetch_json(f"{GITHUB_API}/ggml-org/llama.cpp/git/ref/tags/{tag}")["object"]["sha"]
    tool = {"version": version, "source": release["html_url"], "upstream_tag": tag, "upstream_commit": commit,
            "published_at": release["published_at"],
            "note": f"稳定版 {stable['tag_name']}（{stable['published_at'][:10]}）的 nightly-tag.txt 指向 {tag}",
            "archives": [{"name": a["name"], "url": a["browser_download_url"], "sha256": digest(a)}
                         for a in (main_asset, cudart)]}
    result = install_new_tool("llama.cpp", tool,
                              fetch_files=lambda paths: {k: v for p in paths for k, v in zip_entries(p).items()})
    result["pending"] = "just smoke translate_product（占 GPU，须用户批准）"
    return result


# --- ffmpeg -----------------------------------------------------------------------------------

FFMPEG_ASSET = re.compile(r"ffmpeg-(n[\d.]+-\d+-g[0-9a-f]+)-win64-gpl-(\d+)\.(\d+)\.zip")


def pick_ffmpeg(releases: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], Mapping[str, Any], str, str]:
    """(release, asset, 版本, 分支)：最新带日期 tag 的 autobuild 里最高维护分支的 win64 gpl 构建。"""
    release = next((r for r in releases if r["tag_name"].startswith("autobuild-") and not r["prerelease"]), None)
    if release is None:
        raise UpgradeError("BtbN/FFmpeg-Builds: no dated autobuild release")
    builds = [(int(m.group(2)), int(m.group(3)), m.group(1), a) for a in release["assets"]
              if (m := FFMPEG_ASSET.fullmatch(a["name"]))]
    if not builds:
        raise UpgradeError(f"BtbN {release['tag_name']}: no release-branch win64 gpl build")
    major, minor, version, asset = max(builds, key=lambda b: (b[0], b[1]))
    return release, asset, version, f"{major}.{minor}"


def compare_derived_wav(films_dir: Path, out: Path, old_bin: Path, new_bin: Path) -> dict[str, Any]:
    """两个构建各用产品 extract 代码派生每部影片的 16 kHz WAV，比较样本数、PCM SHA256、补偿与告警。"""
    films = sorted(Path(films_dir).glob("*.mkv"))
    if not films:
        return {"passed": False, "reason": f"no .mkv under {films_dir}"}
    language = config.DEFAULTS["input"]["audio_language"]
    rows, passed = [], True
    for index, film in enumerate(films):
        row = {"film": film.name}
        for tag, bindir in (("old", old_bin), ("new", new_bin)):
            settings = SimpleNamespace(paths=SimpleNamespace(ffprobe=bindir / "ffprobe.exe"),
                                       input=SimpleNamespace(audio_language=language))
            work = out / f"{tag}-{index}"
            work.mkdir(parents=True, exist_ok=True)
            extract = media.derive_pcm16k(film, work, media.probe(film, settings), bindir / "ffmpeg.exe", audio_copy=None)
            extract.wav.unlink()  # 只留日志与哈希，WAV 每部数百 MB
            row[tag] = {"samples": extract.samples, "pcm_sha256": extract.pcm_sha256,
                        "compensation": extract.compensation, "warnings": list(extract.warnings)}
            print(f"ffmpeg {tag} {film.name}: {extract.samples} {extract.pcm_sha256}", flush=True)
        row["identical"] = row["old"] == row["new"]
        passed &= row["identical"]
        rows.append(row)
    return {"passed": passed, "films": rows}


def upgrade_ffmpeg(check: bool, films: Path, out: Path) -> dict[str, Any]:
    current = assets.load_manifest()["tools"]["ffmpeg"]
    release, asset, version, branch = pick_ffmpeg(fetch_json(f"{GITHUB_API}/BtbN/FFmpeg-Builds/releases?per_page=10"))
    if version == current["version"]:
        return {"status": "up to date", "version": version}
    if check:
        return {"status": "available", "old": current["version"], "new": version}
    strip = asset["name"].removesuffix(".zip") + "/"
    tool = {"version": version, "source": release["html_url"],
            "note": f"BtbN win64 gpl 构建，{branch} 维护分支；取自 {release['tag_name']}",
            "archives": [{"name": asset["name"], "url": asset["browser_download_url"], "sha256": digest(asset),
                          "strip": strip}]}
    tools_root = assets.TOOLS_ROOT / "ffmpeg"
    return install_new_tool(
        "ffmpeg", tool,
        fetch_files=lambda paths: zip_entries(paths[0], strip, {"bin/ffmpeg.exe", "bin/ffprobe.exe"}),
        verify=lambda old, new: compare_derived_wav(films, out / "ffmpeg", tools_root / old / "bin", tools_root / new / "bin"))


# --- 入口 -------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("components", nargs="*", choices=COMPONENTS, metavar="component")
    parser.add_argument("--check", action="store_true", help="只报告可升级项，不改文件")
    parser.add_argument("--films", type=Path, default=DEFAULT_FILMS, help="ffmpeg 派生 WAV 核对用的 .mkv 目录")
    args = parser.parse_args(argv)
    out = REPORT_ROOT / utc_now().replace(":", "").replace("-", "")
    report: dict[str, Any] = {"created_at": utc_now(), "check": args.check}
    actions = {"python": lambda: upgrade_python(args.check), "llama.cpp": lambda: upgrade_llama(args.check),
               "ffmpeg": lambda: upgrade_ffmpeg(args.check, args.films, out)}
    failed = False
    for name in args.components or COMPONENTS:  # 一项失败不阻断其余各项
        try:
            report[name] = actions[name]()
        except (UpgradeError, assets.AssetError, OSError) as error:
            report[name] = {"status": "failed", "error": str(error)}
            failed = True
        print(f"{name}: {json.dumps(report[name], ensure_ascii=False)}", flush=True)
    if not args.check:
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if any(report.get(n, {}).get("status") == "upgraded" for n in COMPONENTS):
            print(f"report: {out / 'report.json'}\n待办：同步 docs/development/technology-stack.md、dependencies.md 与规格 §7.2 的"
                  "配置示例；ffmpeg 升级补验收记录；按报告的 pending 申请真实模型验证（smoke）。", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
