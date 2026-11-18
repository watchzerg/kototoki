"""资产清单 `assets.toml` 的执行入口：安装二进制、下载模型、离线核对（docs/development/dependencies.md）。

用法（经 `just install`、`just fetch-models`、`just verify-assets` 调用）：

    python scripts/assets.py install-tools   # 装 tools 锁定分支上当前最新的构建（联网查询 GitHub）
    python scripts/assets.py fetch-models    # 按清单下载缺失或不符的模型文件（联网，几十 GB）
    python scripts/assets.py verify          # 离线核对全部 tools 与 models，不下载

tools 只锁维护分支（ADR-0033）：`install-tools` 取该分支最新的构建，压缩包 SHA256 取自 GitHub 的 asset digest，
实际版本与逐文件 SHA256 写进安装目录的 `identity.json`；`verify` 按 `identity.json` 离线核对。models 锁 revision
与逐文件 SHA256。只用标准库与仓库内同样只依赖标准库的 `kototoki.artifacts`。核对用 `verify_model` 的 size+mtime
缓存（`.local/cache/assets-verify.json`），文件未变时不重算 SHA256。门控模型（`gated = true`）从环境变量
`HF_TOKEN` 取访问令牌。
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tomllib
from typing import Any
from urllib.request import Request, urlopen
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from kototoki.artifacts import utc_now, verify_model  # noqa: E402

MANIFEST = REPO / "assets.toml"
TOOLS_ROOT = REPO / ".local" / "tools"
DOWNLOADS_ROOT = REPO / ".local" / "downloads"
MODELS_ROOT = REPO / ".local" / "models"
VERIFY_CACHE = REPO / ".local" / "cache" / "assets-verify.json"
HF_ENDPOINT = "https://huggingface.co"
GITHUB_API = "https://api.github.com/repos"
# BtbN 的维护分支构建：ffmpeg-<版本>-win64-gpl-<主>.<次>.zip，版本形如 n9.0.2-28-g669f5ab083。
BTBN_ASSET = re.compile(r"ffmpeg-(n[\d.]+-\d+-g[0-9a-f]+)-win64-gpl-(\d+\.\d+)\.zip")
IDENTITY = "identity.json"
CHUNK = 8 << 20


class AssetError(RuntimeError):
    """清单无法满足；消息给出资产名与处理办法。"""


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    with Path(path).open("rb") as stream:
        return tomllib.load(stream)


def tool_dir(name: str, tool: Mapping[str, Any], tools_root: Path = TOOLS_ROOT) -> Path:
    """安装目录按分支命名（`.local/tools/<name>/<branch>/`），分支内换构建时路径不变。"""
    return Path(tools_root) / name / tool["branch"]


def _local(base: Path, relative: str) -> Path:
    return Path(base).joinpath(*PurePosixPath(relative).parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_files(base: Path, files: Mapping[str, Mapping[str, Any]], cache: Path) -> list[str]:
    """逐文件核对大小与 SHA256（size+mtime 缓存）；返回问题清单，空表示全部一致。"""
    problems = []
    for relative, expected in files.items():
        path = _local(base, relative)
        if not path.is_file():
            problems.append(f"{relative}: missing")
        elif path.stat().st_size != expected["size"]:
            problems.append(f"{relative}: size {path.stat().st_size} != {expected['size']}")
        else:
            try:
                verify_model(path, expected["sha256"], cache)
            except ValueError as error:
                problems.append(f"{relative}: {error}")
    return problems


def download(url: str, target: Path, sha256: str, *, headers: Mapping[str, str] | None = None) -> Path:
    """下载到 `<target>.partial`，边下边算 SHA256；一致才改名为 `target`，不一致删掉临时文件并报错。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    print(f"download {url}", flush=True)
    try:
        with urlopen(Request(url, headers=dict(headers or {}))) as response, partial.open("wb") as stream:
            while chunk := response.read(CHUNK):
                digest.update(chunk)
                stream.write(chunk)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if digest.hexdigest() != sha256:
        partial.unlink()
        raise AssetError(f"SHA256 mismatch for {url}: {digest.hexdigest()} != {sha256}")
    partial.replace(target)
    return target


def _extract(archive: Path, base: Path, files: Mapping[str, Any], strip: str) -> list[str]:
    """只解出清单 `files` 列出的成员（去掉 `strip` 前缀后比对）；返回解出的相对路径。"""
    extracted = []
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = member.filename
            if member.is_dir() or not name.startswith(strip):
                continue
            relative = name[len(strip):]
            if relative not in files:
                continue
            path = _local(base, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(path.name + ".partial")
            with bundle.open(member) as source, partial.open("wb") as stream:
                shutil.copyfileobj(source, stream, CHUNK)
            partial.replace(path)
            extracted.append(relative)
    return extracted


def fetch_json(url: str) -> Any:
    with urlopen(Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "kototoki-assets"})) as r:
        return json.load(r)


def btbn_builds(releases: list[Mapping[str, Any]]) -> tuple[Mapping[str, Any], dict[str, tuple[str, Mapping[str, Any]]]]:
    """(release, {分支: (版本, asset)})：最新一个带日期 tag 的 autobuild 里各维护分支的 win64 gpl 构建。"""
    release = next((r for r in releases if r["tag_name"].startswith("autobuild-") and not r["prerelease"]), None)
    if release is None:
        raise AssetError("BtbN/FFmpeg-Builds: no dated autobuild release")
    builds = {}
    for asset in release["assets"]:
        if match := BTBN_ASSET.fullmatch(asset["name"]):
            builds[match.group(2)] = (match.group(1), asset)
    return release, builds


def asset_sha256(asset: Mapping[str, Any]) -> str:
    value = asset.get("digest") or ""
    if not value.startswith("sha256:"):
        raise AssetError(f"GitHub asset {asset['name']} has no sha256 digest; refusing to install it")
    return value.removeprefix("sha256:")


def resolve_build(name: str, tool: Mapping[str, Any], releases: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """锁定分支上当前最新的构建：{version, release, archive: {name, url, sha256, strip}}。"""
    if releases is None:
        releases = fetch_json(f"{GITHUB_API}/{tool['repo']}/releases?per_page=10")
    release, builds = btbn_builds(releases)
    if tool["branch"] not in builds:
        raise AssetError(f"tools.{name}: {tool['repo']} {release['tag_name']} has no {tool['branch']} build "
                         f"(available: {sorted(builds)}); run `just upgrade ffmpeg` to move to a current branch")
    version, asset = builds[tool["branch"]]
    return {"version": version, "release": release["tag_name"],
            "archive": {"name": asset["name"], "url": asset["browser_download_url"], "sha256": asset_sha256(asset),
                        "strip": asset["name"].removesuffix(".zip") + "/"}}


def read_identity(base: Path) -> dict[str, Any] | None:
    path = Path(base) / IDENTITY
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_identity(base: Path, name: str, tool: Mapping[str, Any], build: Mapping[str, Any],
                   files: Mapping[str, Mapping[str, Any]]) -> Path:
    """安装目录的 `identity.json`：锁定的分支、实际装上的构建（版本、release、压缩包）与逐文件大小和 SHA256。"""
    identity = {"identity": f"{name}-{build['version']}", "created_at": utc_now(), "branch": tool["branch"],
                "version": build["version"], "repo": tool["repo"], "release": build["release"],
                "archive": dict(build["archive"]), "files": {relative: dict(entry) for relative, entry in files.items()}}
    path = Path(base) / IDENTITY
    path.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def install_tool(name: str, tool: Mapping[str, Any], *, tools_root: Path = TOOLS_ROOT,
                 downloads_root: Path = DOWNLOADS_ROOT, cache: Path = VERIFY_CACHE,
                 resolve: Callable[[str, Mapping[str, Any]], Mapping[str, Any]] = resolve_build) -> str:
    """装锁定分支上最新的构建。已装的就是它、且文件与 `identity.json` 一致时不动；否则下载压缩包（缓存于
    `downloads/<name>/`）、解出 `files` 到临时目录、整目录替换安装目录并写 `identity.json`。"""
    base = tool_dir(name, tool, tools_root)
    build = resolve(name, tool)
    identity = read_identity(base)
    if identity and identity.get("version") == build["version"] and not check_files(base, identity["files"], cache):
        return f"ok ({build['version']})"
    archive = build["archive"]
    if not archive["name"].endswith(".zip"):
        raise AssetError(f"tools.{name}: archive {archive['name']} is not a zip; only zip archives are supported")
    cached = Path(downloads_root) / name / archive["name"]
    if not (cached.is_file() and _sha256(cached) == archive["sha256"]):
        download(archive["url"], cached, archive["sha256"])
    staging = base.with_name(base.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    extracted = _extract(cached, staging, set(tool["files"]), archive.get("strip", ""))
    if missing := sorted(set(tool["files"]) - set(extracted)):
        shutil.rmtree(staging, ignore_errors=True)
        raise AssetError(f"tools.{name}: {archive['name']} lacks {missing}")
    files = {relative: {"sha256": _sha256(_local(staging, relative)), "size": _local(staging, relative).stat().st_size}
             for relative in tool["files"]}
    write_identity(staging, name, tool, build, files)
    if base.exists():
        shutil.rmtree(base)
    staging.replace(base)
    old = identity.get("version") if identity else None
    return f"installed {build['version']}" if old in (None, build["version"]) else f"updated {old} -> {build['version']}"


def fetch_model(name: str, model: Mapping[str, Any], *, models_root: Path = MODELS_ROOT, cache: Path = VERIFY_CACHE,
                endpoint: str = HF_ENDPOINT, environ: Mapping[str, str] = os.environ) -> str:
    """下载缺失或不符的文件（`<endpoint>/<repo>/resolve/<revision>/<file>`）；已一致的文件不动。"""
    base = Path(models_root) / model["dir"]
    pending = [relative for relative, entry in model["files"].items() if check_files(base, {relative: entry}, cache)]
    if not pending:
        return "ok"
    if "repo" not in model:
        raise AssetError(f"models.{name}: {pending} missing or mismatched and assets.toml lists no download source "
                         f"({model.get('source', 'unknown')}); provision it manually")
    headers = {}
    if model.get("gated"):
        token = environ.get("HF_TOKEN")
        if not token:
            raise AssetError(f"models.{name}: {model['repo']} is gated; set HF_TOKEN to a token that has accepted "
                             "its conditions")
        headers["Authorization"] = f"Bearer {token}"
    for relative in pending:
        url = f"{endpoint.rstrip('/')}/{model['repo']}/resolve/{model['revision']}/{relative}"
        download(url, _local(base, relative), model["files"][relative]["sha256"], headers=headers)
    return f"fetched {len(pending)} file(s)"


def verify(manifest: Mapping[str, Any], *, tools_root: Path = TOOLS_ROOT, models_root: Path = MODELS_ROOT,
           cache: Path = VERIFY_CACHE) -> dict[str, list[str]]:
    """离线核对全部资产：{`tools.<name>`／`models.<name>`: 问题清单}；tools 按安装目录的 `identity.json` 核对。"""
    report = {}
    for name, tool in manifest.get("tools", {}).items():
        base = tool_dir(name, tool, tools_root)
        identity = read_identity(base)
        if identity is None:
            report[f"tools.{name}"] = [f"{IDENTITY}: missing"]
            continue
        problems = check_files(base, identity["files"], cache)
        problems += [f"{relative}: not recorded in {IDENTITY}" for relative in tool["files"]
                     if relative not in identity["files"]]
        if identity.get("branch") != tool["branch"]:
            problems.append(f"installed branch {identity.get('branch')} != assets.toml branch {tool['branch']}")
        report[f"tools.{name}"] = problems
    for name, model in manifest.get("models", {}).items():
        report[f"models.{name}"] = check_files(Path(models_root) / model["dir"], model["files"], cache)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("install-tools", "fetch-models", "verify"))
    command = parser.parse_args(argv).command
    manifest = load_manifest()
    if command == "verify":
        report = verify(manifest)
        for asset, problems in report.items():
            print(f"{asset}: {'ok' if not problems else 'FAIL'}")
            for problem in problems:
                print(f"  {problem}")
        return 0 if not any(report.values()) else 1
    section, action = ("tools", install_tool) if command == "install-tools" else ("models", fetch_model)
    failed = False
    for name, entry in manifest[section].items():  # 一项失败不阻断其余各项
        try:
            print(f"{section}.{name}: {action(name, entry)}", flush=True)
        except (AssetError, OSError) as error:  # OSError 含网络错误（URLError、HTTPError）
            print(f"error: {error}", file=sys.stderr, flush=True)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
