"""本机回环 HTTP 客户端 `LlamaClient`、基础设施失败 `InfraFailure` 与 OOM 文本识别 `explicit_oom`。

中间层，不属基础层（它发 HTTP）：`strata`（建客户端、启动失败）、翻译子系统与专名建表（`InfraFailure`、`explicit_oom`）
单向依赖本模块；本模块只依赖标准库。不导入 torch、`experiments.*`。

来源：2026-11-11 架构整理票据 05（ADR-0025）从 `kototoki/llama_server.py` 拆出产品实际使用的部分，行为不变。
`LlamaClient` 源头是 `experiments/translation_demo/client.py`（产品新增 `chat_completion`），`explicit_oom` 复制自
`translation_demo/run.py`。llama-server 的进程生命周期与 `LlamaClient.tokenize`／`.complete` 随唯一使用者搬到研究侧
`experiments/translation_v3/llama_server.py`。

模块页：docs/architecture/modules/strata-session.md。
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

_OOM = re.compile(r"out of memory|cuda_error_out_of_memory|cudaerrormemoryallocation|vk_error_out_of_device_memory|std::bad_alloc",
                  re.IGNORECASE)


class InfraFailure(RuntimeError):
    """可通过重启 server 重试的基础设施失败（加载期退出／超时、显存不足）。"""


def explicit_oom(message: str) -> bool:
    return bool(_OOM.search(message))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local inference requests may not redirect")


class LlamaClient:
    """只连本机回环的 HTTP 客户端；不走系统代理、不跟随重定向。

    `trace_dir` 给出时每个请求写一个交换目录（`request.json`、`response.raw`、`transport.json`）：
    不带 `trace_label` 的请求目录名是 5 位序号，带的是 `<label>-NN`（`chat_completion` 为 `chat-NN`，同一序号计数）。
    内部接缝：测试用伪客户端替换本类（`Session(client_factory=...)`，只经 `Session.client()` 生效）。
    """

    def __init__(self, url: str, timeout: float = 180.0, trace_dir: Path | None = None):
        parsed = urlparse(url)
        if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password:
            raise ValueError("Only an unauthenticated local loopback HTTP server is allowed")
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.trace_dir = trace_dir
        self.sequence = 0
        self.last_exchange: str | None = None

    def request(self, endpoint: str, data: dict[str, Any] | None = None, *,
                trace_label: str | None = None) -> dict[str, Any]:
        payload = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.sequence += 1
        trace = None
        if self.trace_dir is not None:
            name = f"{self.sequence:05d}" if trace_label is None else f"{trace_label}-{self.sequence:02d}"
            trace = self.trace_dir / name
            trace.mkdir(parents=True, exist_ok=False)
            (trace / "request.json").write_bytes(json.dumps({"endpoint": endpoint, "body": data}, ensure_ascii=False).encode("utf-8"))
            self.last_exchange = str(trace)
        request = Request(self.url + endpoint, data=payload, headers={"Content-Type": "application/json"})
        start = time.perf_counter()
        raw_bytes = b""
        error = None
        status = None
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                status = response.status
                raw_bytes = response.read()
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, HTTPError):
                status = exc.code
                with exc:  # 读完即关，不让错误响应挂到垃圾回收；code 与 str(exc) 不受影响
                    raw_bytes = exc.read()
            raise
        finally:
            if trace is not None:
                (trace / "response.raw").write_bytes(raw_bytes)
                (trace / "transport.json").write_text(json.dumps({"status": status, "elapsed_seconds": time.perf_counter() - start, "error": error}, ensure_ascii=False), encoding="utf-8")
        raw = raw_bytes.decode("utf-8")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected server JSON object")
        return result

    def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("/v1/chat/completions", body, trace_label="chat")
