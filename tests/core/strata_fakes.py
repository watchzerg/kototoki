"""伪 Strata 服务与 `Session` 装配的唯一一份：翻译、names session、strata session 三个测试套件共用。

只提供服务一侧：启动失败按预设队列、`start:N`／`stop:N` 事件、pid 回调。HTTP 客户端的行为在三个套件里各不相同，
由各套件自己提供，经 `session(client_factory=…)` 接入。不起 Strata、不加载模型。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kototoki.strata import MODEL, Session


class FakeServer:
    """伪 Strata 服务。启动按 harness 的 `start_failures` 队列成功或抛出（`StrataRefused`／`InfraFailure`）；
    每次启动尝试都记 `start:N`；失败时服务已自行停掉：回调 `on_pid(None)` 并抛出，不记 `stop`。"""

    def __init__(self, harness: "StrataHarness", runtime_dir: Path, number: int, on_pid) -> None:
        self.harness, self.runtime_dir, self.number, self.on_pid = harness, runtime_dir, number, on_pid
        self.pid = 1000 + number
        self.url = f"http://127.0.0.1:8080/#{number}"
        self.identity = {"candidate": MODEL, "strata": {"drafting": "dflash2"}, "cold_load_seconds": 1.0}
        self.completions = 0

    def __enter__(self) -> "FakeServer":
        self.harness.events.append(f"start:{self.number}")
        failure = self.harness.start_failures.pop(0) if self.harness.start_failures else None
        if failure is not None:
            self.on_pid(None)
            raise failure
        self.on_pid(self.pid)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.on_pid(None)
        self.harness.events.append(f"stop:{self.number}")


class StrataHarness:
    """持有 `events`、`pids`、`servers` 与 `start_failures`，并按测试配置构造真实的 `Session`。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.events: list[str] = []
        self.pids: list[int | None] = []
        self.start_failures: list[Exception | None] = []  # 依次用于每次服务启动；None 表示正常
        self.servers: list[FakeServer] = []
        self.client_factory: Any = None
        self.config = SimpleNamespace(paths=SimpleNamespace(work_dir=root / "work", input_dir=root / "in"))

    def server_at(self, url: str) -> FakeServer:
        return next(server for server in self.servers if server.url == url)

    def session(self, client_factory: Any = None) -> Session:
        def server_factory(runtime_dir: Path, on_pid) -> FakeServer:
            server = FakeServer(self, runtime_dir, len(self.servers) + 1, on_pid)
            self.servers.append(server)
            return server

        return Session(self.config, on_server_pid=self.pids.append, server_factory=server_factory,
                       client_factory=client_factory)
