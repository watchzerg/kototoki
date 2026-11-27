"""资产清单 `assets.toml` 的执行入口：下载模型、离线核对（docs/development/dependencies.md）。

用法（经 `mise run fetch-models`、`mise run verify-assets` 调用）：

    python scripts/assets.py fetch-models    # 按清单下载缺失或不符的模型文件（联网，约 11 GB）
    python scripts/assets.py verify          # 离线核对全部 models，不下载

清单只列模型，锁 revision 与逐文件 SHA256；ffmpeg 等外部前置由用户安装（ADR-0034）。只用标准库与仓库内同样只依赖标准库的 `kototoki.artifacts`。核对用 `verify_model` 的 size+mtime
缓存（`.local/cache/assets-verify.json`），文件未变时不重算 SHA256。门控模型（`gated = true`）从环境变量
`HF_TOKEN` 取访问令牌。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import os
from pathlib import Path, PurePosixPath
import sys
import tomllib
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from kototoki.artifacts import verify_model  # noqa: E402

MANIFEST = REPO / "assets.toml"
MODELS_ROOT = REPO / ".local" / "models"
VERIFY_CACHE = REPO / ".local" / "cache" / "assets-verify.json"
HF_ENDPOINT = "https://huggingface.co"
CHUNK = 8 << 20


class AssetError(RuntimeError):
    """清单无法满足；消息给出资产名与处理办法。"""


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    with Path(path).open("rb") as stream:
        return tomllib.load(stream)


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


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    return scheme, (parts.hostname or "").lower(), parts.port or default_port


class _SafeRedirectHandler(HTTPRedirectHandler):
    """跨主机或换协议重定向时剥离 Authorization，避免把 HF_TOKEN 交给第三方 CDN 或被预签名 URL 拒收。"""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and _origin(req.full_url) != _origin(redirected.full_url):
            redirected.remove_header("Authorization")
        return redirected


def download(url: str, target: Path, sha256: str, *, headers: Mapping[str, str] | None = None) -> Path:
    """下载到 `<target>.partial`，边下边算 SHA256；一致才改名为 `target`，不一致删掉临时文件并报错。"""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    opener = build_opener(_SafeRedirectHandler())
    print(f"download {url}", flush=True)
    try:
        with opener.open(Request(url, headers=dict(headers or {}))) as response, partial.open("wb") as stream:
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


def fetch_model(name: str, model: Mapping[str, Any], *, models_root: Path = MODELS_ROOT, cache: Path = VERIFY_CACHE,
                endpoint: str = HF_ENDPOINT, environ: Mapping[str, str] = os.environ) -> str:
    """下载缺失或不符的文件（`<endpoint>/<repo>/resolve/<revision>/<file>`）；已一致的文件不动。"""
    base = Path(models_root) / model["dir"]
    pending = [relative for relative, entry in model["files"].items() if check_files(base, {relative: entry}, cache)]
    if not pending:
        return "ok"
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


def verify(manifest: Mapping[str, Any], *, models_root: Path = MODELS_ROOT,
           cache: Path = VERIFY_CACHE) -> dict[str, list[str]]:
    """离线核对全部模型：{`models.<name>`: 问题清单}。"""
    report = {}
    for name, model in manifest.get("models", {}).items():
        report[f"models.{name}"] = check_files(Path(models_root) / model["dir"], model["files"], cache)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("fetch-models", "verify"))
    command = parser.parse_args(argv).command
    manifest = load_manifest()
    if command == "verify":
        report = verify(manifest)
        for asset, problems in report.items():
            print(f"{asset}: {'ok' if not problems else 'FAIL'}")
            for problem in problems:
                print(f"  {problem}")
        return 0 if not any(report.values()) else 1
    failed = False
    for name, entry in manifest["models"].items():  # 一项失败不阻断其余各项
        try:
            print(f"models.{name}: {fetch_model(name, entry)}", flush=True)
        except (AssetError, OSError) as error:  # OSError 含网络错误（URLError、HTTPError）
            print(f"error: {error}", file=sys.stderr, flush=True)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
