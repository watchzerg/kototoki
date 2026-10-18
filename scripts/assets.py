"""资产清单 `assets.toml` 的执行入口：安装二进制、下载模型、离线核对（docs/development/dependencies.md）。

用法（经 `just install`、`just fetch-models`、`just verify-assets` 调用）：

    python scripts/assets.py install-tools   # 按清单安装 tools；缺失或不符时下载压缩包（联网）
    python scripts/assets.py fetch-models    # 按清单下载缺失或不符的模型文件（联网，几十 GB）
    python scripts/assets.py verify          # 离线核对全部 tools 与 models，不下载

只用标准库与仓库内同样只依赖标准库的 `kototoki.artifacts`。核对用 `verify_model` 的 size+mtime 缓存
（`.local/cache/assets-verify.json`），文件未变时不重算 SHA256。压缩包只支持 zip；清单里没有 `sha256` 的
压缩包视为身份未知，拒绝从它安装。门控模型（`gated = true`）从环境变量 `HF_TOKEN` 取访问令牌。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
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
IDENTITY = "identity.json"
CHUNK = 8 << 20


class AssetError(RuntimeError):
    """清单无法满足；消息给出资产名与处理办法。"""


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    with Path(path).open("rb") as stream:
        return tomllib.load(stream)


def tool_dir(name: str, tool: Mapping[str, Any], tools_root: Path = TOOLS_ROOT) -> Path:
    return Path(tools_root) / name / tool["version"]


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


def write_identity(base: Path, name: str, tool: Mapping[str, Any]) -> Path:
    """安装目录的 `identity.json`，格式沿用 llama.cpp：来源、压缩包（SHA256 未知记 null）、逐文件 SHA256。"""
    extra = {key: value for key, value in tool.items() if key not in ("version", "archives", "files")}
    identity = {"identity": f"{name}-{tool['version']}", "created_at": utc_now(), "version": tool["version"], **extra,
                "archives": [{"name": a["name"], "url": a["url"], "sha256": a.get("sha256")} for a in tool["archives"]],
                "runtime_file_sha256": {relative: entry["sha256"] for relative, entry in tool["files"].items()}}
    path = Path(base) / IDENTITY
    path.write_text(json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def install_tool(name: str, tool: Mapping[str, Any], *, tools_root: Path = TOOLS_ROOT,
                 downloads_root: Path = DOWNLOADS_ROOT, cache: Path = VERIFY_CACHE) -> str:
    """已装且一致时只补缺失的 `identity.json`；否则下载压缩包（缓存于 `downloads/<name>/`）、解出清单文件并核对。"""
    base = tool_dir(name, tool, tools_root)
    files = tool["files"]
    if not check_files(base, files, cache):
        if (base / IDENTITY).is_file():
            return "ok"
        write_identity(base, name, tool)
        return "identity written"
    for archive in tool["archives"]:
        if "sha256" not in archive:
            raise AssetError(f"tools.{name}: archive {archive['name']} has no sha256 in assets.toml, so it cannot be "
                             "installed reproducibly; register a new version (docs/development/dependencies.md)")
        if not archive["name"].endswith(".zip"):
            raise AssetError(f"tools.{name}: archive {archive['name']} is not a zip; only zip archives are supported")
    for archive in tool["archives"]:
        cached = Path(downloads_root) / name / archive["name"]
        if not (cached.is_file() and _sha256(cached) == archive["sha256"]):
            download(archive["url"], cached, archive["sha256"])
        _extract(cached, base, files, archive.get("strip", ""))
    if problems := check_files(base, files, cache):
        raise AssetError(f"tools.{name}: installed files do not match assets.toml: {problems}")
    write_identity(base, name, tool)
    return "installed"


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
    """离线核对全部资产：{`tools.<name>`／`models.<name>`: 问题清单}；tools 还要求有 `identity.json`。"""
    report = {}
    for name, tool in manifest.get("tools", {}).items():
        base = tool_dir(name, tool, tools_root)
        problems = check_files(base, tool["files"], cache)
        if not (base / IDENTITY).is_file():
            problems.append(f"{IDENTITY}: missing")
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
        except AssetError as error:
            print(f"error: {error}", file=sys.stderr, flush=True)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
