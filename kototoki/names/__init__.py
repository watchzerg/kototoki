"""专名一致性：对编排器只暴露 `build_document`、`NamesError`、`BuildResult` 与建表配方 hash `BUILD_RECIPE_HASH`。

- 建表（`table`）：整份 `ja.srt` 一次送入与翻译共用的 Strata（Qwen3.8-Flash-Next，思考关闭，ADR-0022），取回
  `name-table-v2` 表并归一；终态失败（超预算 `too_long`、5 次尝试都失败 `failed`）返回空表，由编排器照常写出，
  翻译照常进行（只是没有注入行）。
- 表的使用者是翻译子系统（ADR-0019：Q2 规则只注入 `confidence: high` 的写法，没有发布时替换）；本模块不知道注入规则。
- 配方（`recipes`）：建表配方 `q3-names-v1` 的字典与 hash，与基线 Q3 的 `names-strata-v4` 同一建表块。

Strata 的生命周期归中间层 `kototoki.strata`：编排器持有共享 `Session` 传进来，本模块只 `ensure_started()`／`stop()`，
不启停、不核对身份。每部影片一个客户端（`session.client()`），原始交换在
`<work_dir>/names/transport/<session.label>/`，即 `<UTC戳>-<pid>/session-NN/`（`count-NN` 计数、`chat-NN` 建表）。预算检查用
`/v1/messages/count_tokens`（Strata 没有 `/tokenize`），端点不可用时该影片不再预检、计数按 0（v13 的退路）。
不做同调用内重启：传输失败、HTTP 错误、OOM 停掉 Strata（下一部需要模型的影片再启动）并抛 `NamesError`。

依赖方向：只依赖基础层（`artifacts`、`srt`、`recipes`）、中间层 `kototoki.strata` 与 `kototoki.local_client`
（`InfraFailure`、`explicit_oom`）；不导入 torch、`experiments.*`。不取 GPU 锁、不写产物（`name-table.json` 由编排器写）、
不打含条目文字的日志。见 docs/architecture/modules/name-consistency.md。

模块页：docs/architecture/modules/name-consistency.md。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

from kototoki.local_client import InfraFailure, explicit_oom
from kototoki.srt import SourceDocument
from kototoki.strata import MODEL, Session, StrataRefused

from .recipes import BUILD, BUILD_RECIPE_HASH
from .table import PROMPT_BUDGET, BuildResult, build_table

__all__ = ["BUILD_RECIPE_HASH", "BuildResult", "NamesError", "build_document"]

TRANSPORT_DIR = "names/transport"  # 工作目录内原始交换的根
CLIENT_TIMEOUT_SECONDS = 1800.0
COUNT_TOKENS = "/v1/messages/count_tokens"

log = logging.getLogger(__name__)


class NamesError(RuntimeError):
    """该影片建表失败（Strata 起不来或被拒绝、传输失败、HTTP 错误或 OOM）；编排器记为 names 阶段文件级失败。"""


class _TokenCounter:
    """`build_table` 的 `tokenize` 回调：一段提示作一条 user 消息经 `/v1/messages/count_tokens` 计数。

    端点返回 HTTP／传输错误或响应形状不符（没有整数 `input_tokens`）时，该影片内不再预检、计数按 0，运行日志一行
    WARNING；与研究侧 v13 `NamesClient.tokenize` 的退路相同（复制，不导入）。
    """

    def __init__(self, client: Any):
        self.client = client
        self.ok: bool | None = None
        self.error: str | None = None

    def __call__(self, text: str) -> int:
        if self.ok is False:
            return 0
        try:
            n = self.client.request(COUNT_TOKENS, {"model": MODEL, "messages": [{"role": "user", "content": text}]},
                                    trace_label="count")["input_tokens"]
            if type(n) is not int:
                raise ValueError(f"input_tokens is {type(n).__name__}")
        except (HTTPError, URLError, KeyError, ValueError, TypeError) as exc:
            self.ok, self.error = False, f"{type(exc).__name__}: {exc}"[:300]
            log.warning("[names] count_tokens unavailable (%s): no prompt budget precheck for this document",
                        self.error)
            return 0
        self.ok = True
        return n


def _no_server(*args: Any) -> Any:
    raise AssertionError("a zero-cue document must not reach the server")


def build_document(work_dir: Path, document: SourceDocument, session: Session | None, seed: int) -> BuildResult:
    """为一部影片建表，返回 `BuildResult`（payload 即 `name-table.json` 的内容，不含身份块）。

    零条目文档不碰 session（可为 None），直接得到空表。`session.ensure_started()` 被拒绝（`StrataRefused`，含本批已不可用）
    或启动失败（`InfraFailure`）时抛 `NamesError`；传输失败、HTTP 错误或 OOM 时停掉 Strata（下一部需要模型的影片
    `ensure_started` 再启动）并抛 `NamesError`，消息只带状态码与分类，回复正文留在交换目录里。
    """
    if not document.cues:
        return build_table(document, _no_server, _no_server, seed)
    assert session is not None
    try:
        session.ensure_started()
    except StrataRefused as exc:
        raise NamesError(f"Strata unavailable: {exc}") from exc
    except InfraFailure as exc:
        raise NamesError(f"Strata failed to start: {exc}") from exc
    trace_dir = Path(work_dir) / TRANSPORT_DIR / session.label
    client = session.client(trace_dir, timeout=CLIENT_TIMEOUT_SECONDS)
    counter = _TokenCounter(client)
    try:
        result = build_table(document, client.chat_completion, counter, seed)
    except HTTPError as exc:
        body = _response_body(client) + str(exc)
        kind = "oom" if explicit_oom(body) else "server_error"
        session.stop()
        raise NamesError(f"HTTP {exc.code} ({kind}): response body {len(body)} char(s); see {trace_dir}") from exc
    except (URLError, ConnectionError, TimeoutError) as exc:
        session.stop()
        raise NamesError(f"transport failure: {type(exc).__name__}: {exc}") from exc
    # 预算检查的方式与"按 usage 看是否超预算"记进 build 块（计数不可用时提示仍照常发送，只记录、不失败）。
    prompt_tokens = result.payload["meta"].get("prompt_tokens")
    result.payload["build"].update(
        prompt_check="count_tokens" if counter.ok else f"skipped ({counter.error})" if counter.ok is False else None,
        over_budget_by_usage=type(prompt_tokens) is int and prompt_tokens > PROMPT_BUDGET)
    return result


def _response_body(client: Any) -> str:
    exchange = getattr(client, "last_exchange", None)
    raw = Path(exchange) / "response.raw" if isinstance(exchange, str) else None
    return raw.read_text(encoding="utf-8", errors="replace") if raw is not None and raw.is_file() else ""
