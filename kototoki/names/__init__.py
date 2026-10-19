"""专名一致性：对编排器只暴露 `Session`、`build_document`、`apply`、`NamesError` 与两个配方 hash
`BUILD_RECIPE_HASH`／`APPLY_RECIPE_HASH`。

- 建表（`table`）：整份 `ja.srt` 一次送入 Qwen llama-server（no-think），取回 `name-table-v2` 表并归一；终态失败
  （超预算 `too_long`、两次尝试都失败 `failed`）返回空表，由编排器照常写出并发布。
- 替换（`apply`）：发布时的纯函数，按日文锚定 cue，把译文里专名的各种写法整段换成表里的中文。包属性
  `kototoki.names.apply` 是这个函数（遮住同名子模块）；子模块里的其他名字用 `from kototoki.names.apply import …` 取。
- 配方（`recipes`）：两份配方字典与 hash；`NAMES_SPEC` 是本模块用 `recipes.NAMES_SERVER` 与模型资产拼成的
  llama-server 配置。

`Session` 整批共用一个 server：首次需要时才启动，server 退出后下一部影片再启动，整批最多启动 `MAX_STARTS` 次；
启动失败即 `unavailable`，本批其余需要模型的影片直接失败。每部只有一个请求，不做同调用内重启。server 运行日志在
`<output_dir>/.work/names-sessions/<UTC戳>-<pid>/session-NN/`，每部影片的原始交换在
`<work_dir>/names/transport/<UTC戳>-<pid>/session-NN/`。

依赖方向：只依赖基础层（`artifacts`、`config`、`srt`、`recipes`）与 `kototoki.llama_server`；不导入 torch、
`experiments.*`。不取 GPU 锁、不写产物（`name-table.json`／`names-apply.json` 由编排器写）、不打含条目文字的日志。
见 docs/architecture/modules/name-consistency.md。
"""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError

from kototoki import artifacts
from kototoki.config import Config
from kototoki.llama_server import LlamaClient, ManagedServer, ServerSpec, explicit_oom
from kototoki.srt import SourceDocument

from .apply import ApplyResult, apply
from .recipes import APPLY_RECIPE_HASH, BUILD, BUILD_RECIPE_HASH, NAMES_SERVER
from .table import BuildResult, build_table

__all__ = ["APPLY_RECIPE_HASH", "BUILD_RECIPE_HASH", "ApplyResult", "BuildResult", "NamesError", "Session", "apply",
           "build_document"]

SESSIONS_DIR = "names-sessions"   # `.work/` 下 server 运行日志的根
TRANSPORT_DIR = "names/transport"  # 工作目录内原始交换的根
MAX_STARTS = 3                     # 整批最多启动 server 的次数（即重启 2 次）
CLIENT_TIMEOUT_SECONDS = 1800.0

NAMES_SPEC = ServerSpec(
    stage="names", candidate=NAMES_SERVER["candidate"],
    model_asset={"repo": NAMES_SERVER["repo"], "revision": NAMES_SERVER["revision"], **BUILD["model_asset"]},
    layers=NAMES_SERVER["layers"], context=NAMES_SERVER["context"], extra_args=NAMES_SERVER["extra_args"],
    min_free_mib=NAMES_SERVER["min_free_mib"], load_timeout_s=NAMES_SERVER["load_timeout_s"])


class NamesError(RuntimeError):
    """该影片建表失败（server 起不来、传输失败、HTTP 错误或 OOM）；编排器记为 names 阶段文件级失败。"""


class Session:
    """整批建表共用的 server 生命周期。`on_server_pid(pid)` 在 server 启动后以 pid、停止后以 None 回调。

    `server_factory`／`client_factory` 是只供测试的内部接缝。
    """

    def __init__(self, config: Config, *, on_server_pid: Callable[[int | None], None] | None = None,
                 server_factory: Callable[[Path, Callable[[int | None], None]], Any] | None = None,
                 client_factory: Callable[..., Any] = LlamaClient):
        self.config = config
        self.on_server_pid = on_server_pid or (lambda pid: None)
        self.server_factory = server_factory or self._managed_server
        self.client_factory = client_factory
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())  # UTC，与运行日志 `run-<戳>.log` 同一时间基准
        self.runtime_root = artifacts.work_root(config.paths.output_dir) / SESSIONS_DIR / f"{stamp}-{os.getpid()}"
        self.server: Any = None
        self.starts = 0
        self.unavailable: str | None = None

    def _managed_server(self, runtime_dir: Path, on_pid: Callable[[int | None], None]) -> ManagedServer:
        return ManagedServer(runtime_dir, NAMES_SPEC, engine=self.config.paths.llama_server,
                             model=self.config.models.names, port=self.config.names.port,
                             model_cache=artifacts.model_cache_path(self.config.paths.output_dir), on_pid=on_pid)

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def ensure_started(self) -> Any:
        """返回运行中的 server；未启动或已退出时启动新的。启动失败或启动次数用尽即 `unavailable` 并抛 `NamesError`。"""
        if self.unavailable is not None:
            raise NamesError(f"llama-server could not start earlier in this batch: {self.unavailable}")
        if self.server is not None and self.server.process.poll() is None:
            return self.server
        self.stop()  # server 已自行退出：收尾（记 engine-final.json、以 None 回调）后重启
        if self.starts >= MAX_STARTS:
            self.unavailable = f"llama-server already started {MAX_STARTS} times in this batch"
            raise NamesError(self.unavailable)
        self.starts += 1
        server = self.server_factory(self.runtime_root / f"session-{self.starts:02d}", self.on_server_pid)
        try:
            server.__enter__()  # 进程一启动即以 pid 回调；加载失败时自行清理并以 None 回调
        except Exception as exc:
            self.unavailable = f"{type(exc).__name__}: {exc}"
            raise NamesError(f"llama-server failed to start: {self.unavailable}") from exc
        self.server = server
        return server

    def stop(self) -> None:
        server, self.server = self.server, None
        if server is not None:
            server.__exit__(None, None, None)


def _no_server(*args: Any) -> Any:
    raise AssertionError("a zero-cue document must not reach the server")


def build_document(work_dir: Path, document: SourceDocument, session: Session | None, seed: int) -> BuildResult:
    """为一部影片建表，返回 `BuildResult`（payload 即 `name-table.json` 的内容，不含身份块）。

    零条目文档不起 server（`session` 可为 None），直接得到空表。传输失败、HTTP 错误或 OOM 时停掉 server（下一部
    影片 `ensure_started` 再启动）并抛 `NamesError`，消息只带状态码与分类，回复正文留在交换目录里。
    """
    if not document.cues:
        return build_table(document, _no_server, _no_server, seed)
    assert session is not None
    server = session.ensure_started()
    trace_dir = Path(work_dir) / TRANSPORT_DIR / session.runtime_root.name / f"session-{session.starts:02d}"
    client = session.client_factory(server.url, timeout=CLIENT_TIMEOUT_SECONDS, trace_dir=trace_dir)
    try:
        return build_table(document, client.chat_completion, lambda text: len(client.tokenize(text)), seed)
    except HTTPError as exc:
        body = _response_body(client) + str(exc)
        kind = "oom" if explicit_oom(body) else "server_error"
        session.stop()
        raise NamesError(f"HTTP {exc.code} ({kind}): response body {len(body)} char(s); see {trace_dir}") from exc
    except (URLError, ConnectionError, TimeoutError) as exc:
        session.stop()
        raise NamesError(f"transport failure: {type(exc).__name__}: {exc}") from exc


def _response_body(client: Any) -> str:
    exchange = getattr(client, "last_exchange", None)
    raw = Path(exchange) / "response.raw" if isinstance(exchange, str) else None
    return raw.read_text(encoding="utf-8", errors="replace") if raw is not None and raw.is_file() else ""
