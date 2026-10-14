"""只连本机回环的 llama.cpp HTTP 客户端（复制自 `experiments/translation_demo/client.py`）。

内部接缝：测试用伪客户端替换本类（`Session(client_factory=...)`），编排器看不到它。
"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local inference requests may not redirect")


class LlamaClient:
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

    def request(self, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.sequence += 1
        trace = None
        if self.trace_dir is not None:
            trace = self.trace_dir / f"{self.sequence:05d}"
            trace.mkdir(parents=True, exist_ok=False)
            (trace / "request.json").write_bytes(json.dumps({"endpoint": endpoint, "body": data}, ensure_ascii=False).encode("utf-8"))
            self.last_exchange = str(trace)
        request = Request(self.url + endpoint, data=payload, headers={"Content-Type": "application/json"})
        start = perf_counter()
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
                raw_bytes = exc.read()
            raise
        finally:
            if trace is not None:
                (trace / "response.raw").write_bytes(raw_bytes)
                (trace / "transport.json").write_text(json.dumps({"status": status, "elapsed_seconds": perf_counter() - start, "error": error}, ensure_ascii=False), encoding="utf-8")
        raw = raw_bytes.decode("utf-8")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Expected server JSON object")
        return result

    def tokenize(self, prompt: str) -> list[int]:
        # 原生提示已含显式 BOS。
        response = self.request("/tokenize", {"content": prompt, "add_special": False, "parse_special": True})
        tokens = response.get("tokens")
        if (not isinstance(tokens, list) or not tokens
                or any(type(token) is not int or token < 0 for token in tokens)):
            raise ValueError("Tokenizer must return nonempty integer token IDs")
        return tokens

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.request("/completion", request)
