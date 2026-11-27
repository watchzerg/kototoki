"""Strata 启停与共享 session 的伪 CLI 测试（ADR-0029「Strata session」）：已有 launch 时拒绝且不替别人停、等上一阶段释放显存、
`--no-tui --model iq3_s` 启动、等唯一一个 ready、按 ADR-0021「Q3 服务与运行顺序」核对身份（版本／run config／`/v1/models`／`/v1/status`），不符即停并拒绝；未就绪、
启动失败、被中断都执行 `--stop`；退出核实 `--status` 为空与显存释放，核实失败只记 ERROR、不抛出。共享 `Session`：首次才启动、
两阶段复用、`stop` 后再起为新 session、启动失败整批累计 `MAX_START_FAILURES` 次或被拒即 `unavailable`。不调用真实 `strata`。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any
import unittest

from kototoki import artifacts
from kototoki import strata as S
from kototoki.artifacts import read_json
from kototoki.local_client import InfraFailure
from kototoki.strata import ResourceSampler, StrataRefused, StrataServer, wait_for_free_vram
from tests.core.strata_fakes import StrataHarness

# Strata 默认启动真实写下的参数形状（0.2.12 Windows 与 0.2.13.1 Linux 相同）：总带 `--mtp <权重目录>`，DFlash2 不在 run config 里（2026-11-08 smoke）。
DEFAULT_ARGS = ["--pack", "p", "--spec", "4", "--spec-min-p", "0.5", "--mtp", "/opt/strata/mtp/rt", "--max-context", "131072",
                "--kv", "int8", "--kv-resident", "32768", "--vision"]
DFLASH_LINE = "[strata] drafting: DFlash2 alone (--draft dflash2, --draft-conf 0.7)\n"


class FakeStrata:
    """`strata` CLI 与 HTTP 端点的状态机。显存：服务运行时空闲 1000 MiB，停掉后 15000 MiB。"""

    def __init__(self, root: Path):
        self.root = root
        self.commands: list[tuple[str, ...]] = []
        self.version = "strata 0.2.13.1 (build 0.1.59.1; python 3.12.15 at /opt/strata/python3.12)"
        self.args = list(DEFAULT_ARGS)
        self.drafting_line: str | None = DFLASH_LINE
        self.log = root / "logs" / "launch-k1.server.log"
        self.log.parent.mkdir(exist_ok=True)
        self.log.write_text("[strata] drafting: MTP (older launch)\n", encoding="utf-8")  # 上一次启动留下的
        self.model_name = S.MODEL
        self.models = [S.MODEL]
        self.native = 131072
        self.others: list[dict[str, Any]] = []  # 别人的 launch
        self.state: str | None = None           # None：没在服务；"loading"／"ready"
        self.ready_after = 2                    # 启动后第几次 `--status` 才 ready（None：永不）
        self.polls = 0
        self.free_before = 15000
        self.ram = [55.0]                       # 依次返回的可用内存（GiB），用完后保持最后一个值
        self.engine_lines = "strata generate: expert arena: cudaHostRegister PORTABLE ok; MAP_HUGETLB unavailable\n"
        self.engine_log = root / "launch-logs" / "k1.engine.log"
        self.engine_log.parent.mkdir(exist_ok=True)
        self.engine_log.write_text("strata generate: experts via mmap (older launch)\n", encoding="utf-8")

    def launch_row(self) -> dict[str, Any]:
        config = self.root / "launch.json"
        config.write_text(json.dumps({"model_name": self.model_name, "exe": "component:strata-engine", "args": self.args,
                                      "host": "127.0.0.1", "log": "x.log"}), encoding="utf-8")
        return {"name": "k1", "profile": "p", "state": self.state, "port": 8080, "host": "127.0.0.1", "pid": 4242,
                "config": str(config)}

    def cli(self, *args: str, timeout: float = 120.0) -> str:
        self.commands.append(args)
        if args == ("--version",):
            return self.version + "\n"
        if args == S.STATUS_ARGS:
            rows = list(self.others)
            if self.state is not None:
                self.polls += 1
                if self.state == "loading" and self.ready_after is not None and self.polls >= self.ready_after:
                    self.state = "ready"
                rows.append(self.launch_row())
            return json.dumps({"schema_version": 1, "ok": True, "running": rows}) + "\nhuman-readable line\n"
        if args == S.LAUNCH_ARGS:
            self.state = "loading"
            with self.engine_log.open("a", encoding="utf-8") as handle:
                handle.write(self.engine_lines)
            if self.drafting_line is not None:
                with self.log.open("a", encoding="utf-8") as handle:
                    handle.write("[strata] loading the model ...\n" + self.drafting_line)
            return ""
        if args == S.STOP_ARGS:
            self.state = None
            return ""
        raise AssertionError(f"unexpected strata command {args!r}")

    def get(self, url: str) -> dict[str, Any]:
        if url.endswith("/v1/models"):
            return {"data": [{"id": m} for m in self.models]}
        if url.endswith("/v1/status"):
            return {"model": self.model_name, "context": {"native": self.native}, "concurrency": 1,
                    "machine": {"gpu": {"used_mib": 15600}, "ram": {"used_gib": 21.5}}}
        raise AssertionError(url)

    def available_ram(self) -> float:
        return self.ram.pop(0) if len(self.ram) > 1 else self.ram[0]

    def free_vram(self) -> int:
        if self.state is None:
            return self.free_before
        return 1000


class StrataServerTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = FakeStrata(self.root)
        self.now = [0.0]
        self.pids: list[int | None] = []

    def server(self, *, cli: Any = None, get: Any = None, sleep: Any = None) -> StrataServer:
        def advance(seconds: float) -> None:
            self.now[0] += seconds

        return StrataServer(self.root, on_pid=self.pids.append, cli=cli or self.fake.cli, get=get or self.fake.get,
                            free_vram=self.fake.free_vram, available_ram=self.fake.available_ram,
                            sleep=sleep or advance, clock=lambda: self.now[0], log_dir=self.root / "logs",
                            engine_log_dir=self.root / "launch-logs")

    def verbs(self) -> list[str]:
        return [" ".join(c) for c in self.fake.commands if c not in (S.STATUS_ARGS, ("--version",))]

    def test_normal_session_launches_probes_and_stops(self) -> None:
        with self.assertLogs("kototoki.strata", level="INFO") as logs:
            with self.server() as server:
                self.assertEqual(self.fake.state, "ready")
                self.assertEqual(self.pids, [4242])
                self.assertEqual(server.identity["strata"]["drafting"], "dflash2")
                self.assertEqual(server.identity["free_vram_mib_before_start"], 15000)
                self.assertEqual(server.url, "http://127.0.0.1:8080")
        self.assertIsNone(self.fake.state)
        self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])
        self.assertEqual(self.fake.commands[0], S.STATUS_ARGS)  # 先确认没人在服务
        self.assertEqual(self.pids, [4242, None])
        observed = read_json(self.root / "strata.json")
        self.assertEqual(observed["expert_arena"], "ram")  # 上一次启动留下的 mmap 记录不算
        self.assertEqual(server.identity["available_ram_gib_before_start"], 55.0)
        self.assertEqual(observed["drafting_line"], DFLASH_LINE.strip())
        self.assertEqual((observed["config"]["model_name"], observed["status"]["context"]["native"]), (S.MODEL, 131072))
        resources = read_json(self.root / "resources.json")
        self.assertEqual((resources["gpu_used_mib"], resources["ram_used_gib"]), (15600, 21.5))
        self.assertGreaterEqual(resources["samples"], 2)
        final = read_json(self.root / "strata-final.json")
        self.assertEqual((final["stop"], final["status_empty"], final["free_vram_mib"], final["released"]),
                         ("ok", True, 15000, True))
        self.assertEqual({r.levelname for r in logs.records}, {"INFO"})
        messages = [r.getMessage() for r in logs.records]
        self.assertEqual(messages[0], "[strata] launching (free VRAM 15000 MiB, available RAM 55.0 GiB)")
        self.assertLess(messages.index("[strata] stopping"), len(messages) - 1)  # 停止核实行在其后

    def test_another_launch_serving_is_refused_and_left_alone(self) -> None:
        self.fake.others = [{"name": "someone", "state": "ready", "port": 8080, "host": "127.0.0.1"}]
        with self.assertRaisesRegex(StrataRefused, "another Strata launch is serving"):
            with self.server():
                self.fail("must not enter")
        self.assertEqual(self.verbs(), [])  # 没启动，也没替别人停
        self.assertEqual(self.pids, [])
        self.assertFalse((self.root / "strata-final.json").exists())

    def test_probe_mismatch_stops_the_launch_and_refuses(self) -> None:
        cases = [("drafting_line", "[strata] drafting: MTP alone (--spec 4)\n", "drafting 'mtp'"),
                 ("drafting_line", None, "drafting None"),  # 本次启动没写起草行：不拿上一次的行充数
                 ("args", ["--mtp", "/opt/strata/mtp/rt", "--max-context", "65536"], "--max-context '65536'"),
                 ("model_name", "qwen3.8-27b", "model 'qwen3.8-27b'"),
                 ("version", "strata 0.3.0 (build 0.2.0)", "must be on the 0.2 line"),
                 ("version", "strata 0.20.1 (build 0.1.59)", "must be on the 0.2 line"),
                 ("models", ["other"], "/v1/models"),
                 ("native", 65536, "native context")]
        for field, value, message in cases:
            with self.subTest(field=field, value=value):
                self.fake = FakeStrata(self.root)
                setattr(self.fake, field, value)
                self.pids.clear()
                with self.assertRaisesRegex(StrataRefused, message):
                    with self.server():
                        self.fail("must not enter")
                self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])
                self.assertIsNone(self.fake.state)
                self.assertTrue(read_json(self.root / "strata-final.json")["released"])
                self.assertEqual(self.pids, [None])

    def test_interrupt_inside_the_session_stops_strata(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            with self.server():
                raise KeyboardInterrupt()
        self.assertIsNone(self.fake.state)
        self.assertEqual(self.pids, [4242, None])

    def test_empty_status_output_raises_infra_failure(self) -> None:
        def empty_cli(*args: str, timeout: float = 120.0) -> str:
            self.fake.commands.append(args)
            if args == S.STATUS_ARGS:
                return "   \n"
            return self.fake.cli(*args, timeout=timeout)

        server = StrataServer(self.root, on_pid=self.pids.append, cli=empty_cli, get=self.fake.get,
                              free_vram=self.fake.free_vram, available_ram=self.fake.available_ram,
                              sleep=lambda s: None, clock=lambda: self.now[0], log_dir=self.root / "logs",
                              engine_log_dir=self.root / "launch-logs")
        with self.assertRaisesRegex(InfraFailure, "strata launch --status failed"):
            with server:
                self.fail("must not enter")
        self.assertEqual(self.verbs(), [])
        self.assertEqual(self.pids, [])

    def test_exit_emits_single_warning_when_sampler_had_errors(self) -> None:
        status_calls = 0

        def flaky_get(url: str) -> dict[str, Any]:
            nonlocal status_calls
            if url.endswith("/v1/status"):
                status_calls += 1
                if status_calls >= 2:
                    raise TimeoutError("status poll timed out")
            return self.fake.get(url)

        server = self.server(get=flaky_get, sleep=lambda s: None)
        with self.assertLogs("kototoki.strata", level="WARNING") as logs:
            with server:
                pass
        resources = read_json(self.root / "resources.json")
        self.assertEqual(resources["errors"], 2)
        self.assertEqual(resources["last_error"], "TimeoutError: status poll timed out")
        warnings = [r for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("2", warnings[0].getMessage())
        self.assertIn("TimeoutError: status poll timed out", warnings[0].getMessage())

    def test_final_write_error_logs_error_and_omits_missing_path(self) -> None:
        final_path = self.root / "strata-final.json"
        final_path.mkdir()
        (final_path / "keep").write_text("x", encoding="utf-8")

        def stop_fails(*args: str, timeout: float = 120.0) -> str:
            if args == S.STOP_ARGS:
                self.fake.commands.append(args)
                raise OSError("cannot stop")
            return self.fake.cli(*args, timeout=timeout)

        with self.assertLogs("kototoki.strata", level="ERROR") as logs:
            with self.server(cli=stop_fails):
                pass
        self.assertEqual(self.pids, [4242, None])
        errors = [r.getMessage() for r in logs.records if r.levelname == "ERROR"]
        self.assertTrue(any("IsADirectoryError" in msg and str(final_path) in msg for msg in errors), errors)
        unconfirmed = [msg for msg in errors if "Strata stop not confirmed" in msg]
        self.assertEqual(len(unconfirmed), 1)
        self.assertNotIn("strata-final.json", unconfirmed[0])

    def test_called_process_error_preserves_stderr_and_exit_status_error(self) -> None:
        def pre_status_fails(*args: str, timeout: float = 120.0) -> str:
            if args == S.STATUS_ARGS:
                raise subprocess.CalledProcessError(2, ["strata", *args], stderr="pre-launch status stderr")
            return self.fake.cli(*args, timeout=timeout)

        with self.assertRaisesRegex(InfraFailure, "pre-launch status stderr"):
            with self.server(cli=pre_status_fails):
                self.fail("must not enter")

        # 就绪轮询遇到 --status 失败时保留 stderr；退出时 --stop 与 --status 轮询失败分别记入 stop 与 status_error。
        self.fake = FakeStrata(self.root)
        self.now = [0.0]
        launched = False

        def lifecycle_fails(*args: str, timeout: float = 120.0) -> str:
            nonlocal launched
            if args == S.LAUNCH_ARGS:
                launched = True
                return self.fake.cli(*args, timeout=timeout)
            if args == S.STATUS_ARGS and launched:
                raise subprocess.CalledProcessError(4, ["strata", *args], stderr="status poll stderr")
            if args == S.STOP_ARGS:
                raise subprocess.CalledProcessError(3, ["strata", *args], stderr="stop cmd stderr")
            return self.fake.cli(*args, timeout=timeout)

        with self.assertLogs("kototoki.strata", level="ERROR"):
            with self.assertRaisesRegex(InfraFailure, "status poll stderr"):
                with self.server(cli=lifecycle_fails):
                    self.fail("must not enter")
        final = read_json(self.root / "strata-final.json")
        self.assertIn("stop cmd stderr", str(final["stop"]))
        self.assertIn("status poll stderr", str(final.get("status_error")))
        self.assertIsNone(final["status_empty"])


class WaitForFreeVramTests(unittest.TestCase):
    """空闲显存轮询（ADR-0025 起从 `llama_server.py` 并入本模块；测试随之从 `test_llama_server.py` 搬来）。"""

    def setUp(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def _sleep(self, seconds: float) -> None:
        # 假睡眠只推进假时钟，不真正等待
        self.sleeps.append(seconds)
        self.now += seconds

    def _wait(self, readings, timeout=10.0, **kwargs):
        iterator = iter(readings)
        last = [None]

        def query():
            last[0] = next(iterator, last[0])
            return last[0]

        return wait_for_free_vram(14300, timeout, query=query, sleep=self._sleep, clock=lambda: self.now, **kwargs)

    def test_returns_reading_once_threshold_reached(self):
        self.assertEqual(self._wait([1000, 5000, 14500, 16000]), 14500)
        self.assertEqual(len(self.sleeps), 2)

    def test_timeout_raises_with_last_reading(self):
        with self.assertRaises(InfraFailure) as caught:
            self._wait([1000, 2000, 3456])
        self.assertIn("3456", str(caught.exception))


class SessionTests(unittest.TestCase):
    """共享 session 的生命周期用伪服务验证；真实 `StrataServer` 的行为见上。"""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.h = StrataHarness(self.root)

    def runtime_names(self) -> list[str]:
        return [server.runtime_dir.name for server in self.h.servers]

    def test_starts_once_and_is_reused_across_stages(self) -> None:
        with self.h.session() as session:
            self.assertIsNone(session.server)
            first = session.ensure_started()   # names 阶段
            second = session.ensure_started()  # 翻译阶段
            self.assertIs(first, second)
            self.assertEqual(session.label, f"{session.runtime_root.name}/session-01")
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        self.assertEqual(self.runtime_names(), ["session-01"])
        self.assertEqual(self.h.pids, [1001, None])
        self.assertEqual(session.runtime_root.parent,
                         artifacts.work_root(self.root / "work", self.root / "in") / S.SESSIONS_DIR)

    def test_stop_then_restart_is_a_new_session(self) -> None:
        session = self.h.session()
        session.ensure_started()
        session.stop()
        session.stop()  # 幂等
        session.ensure_started()
        self.assertEqual(session.label, f"{session.runtime_root.name}/session-02")
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2"])
        self.assertEqual(self.runtime_names(), ["session-01", "session-02"])
        session.stop()
        self.assertEqual(self.h.pids, [1001, None, 1002, None])

    def test_repeated_start_failures_make_the_batch_unavailable(self) -> None:
        self.h.start_failures = [InfraFailure(f"launch {n} exploded") for n in range(1, 5)]
        session = self.h.session()
        with self.assertLogs("kototoki.strata", level="WARNING") as logs:
            for _ in range(S.MAX_START_FAILURES - 1):
                with self.assertRaises(InfraFailure):
                    session.ensure_started()
                self.assertIsNone(session.unavailable)
            with self.assertRaises(InfraFailure):
                session.ensure_started()
            with self.assertRaises(StrataRefused):
                session.ensure_started()
        self.assertEqual([(r.levelname, r.getMessage()) for r in logs.records], [
            ("WARNING", "[strata] start failed 1/3: launch 1 exploded"),
            ("WARNING", "[strata] start failed 2/3: launch 2 exploded"),
            ("WARNING", "[strata] start failed 3/3: launch 3 exploded"),
            ("ERROR", "[strata] unavailable for the rest of this batch: Strata failed to start 3 times in this batch "
                      "(start budget exhausted): launch 3 exploded")])
        self.assertIn(f"failed to start {S.MAX_START_FAILURES} times in this batch (start budget exhausted): "
                      f"launch {S.MAX_START_FAILURES} exploded", session.unavailable)
        with self.assertRaisesRegex(StrataRefused, "unavailable for the rest of this batch"):
            session.ensure_started()
        self.assertEqual(self.h.events, ["start:1", "start:2", "start:3"])  # 第 4 次没有碰工厂
        self.assertEqual(self.runtime_names(), ["session-01", "session-02", "session-03"])
        self.assertIsNone(session.server)
        self.assertEqual(self.h.pids, [None, None, None])

    def test_refused_start_marks_the_batch_unavailable(self) -> None:
        self.h.start_failures = [StrataRefused("refused 1")]
        with self.h.session() as session, self.assertLogs("kototoki.strata", level="WARNING") as logs:
            with self.assertRaisesRegex(StrataRefused, "refused 1"):
                session.ensure_started()
            self.assertEqual(session.unavailable, "refused 1")
            self.assertIsNone(session.server)
            with self.assertRaisesRegex(StrataRefused, "refused 1"):
                session.ensure_started()
        self.assertEqual([(r.levelname, r.getMessage()) for r in logs.records],
                         [("ERROR", "[strata] unavailable for the rest of this batch: refused 1")])  # 只记一次
        self.assertEqual(self.h.events, ["start:1"])  # 被拒的服务已自行停掉，不再 stop
        self.assertEqual(self.h.pids, [None])


class ResourceSamplerTests(unittest.TestCase):
    def test_background_uncaught_exception_is_rate_limited_and_recorded(self) -> None:
        calls = 0

        def bad_get(url: str) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"machine": {"gpu": {"used_mib": 15600}, "ram": {"used_gib": 21.5}}}
            raise RuntimeError("unexpected probe boom")

        sampler = ResourceSampler("http://127.0.0.1:8080", bad_get, every=0.005)
        with self.assertLogs("kototoki.strata", level="WARNING") as logs:
            sampler.start()
            try:
                deadline = time.monotonic() + 2.0
                while sampler.peak["errors"] < 3 and time.monotonic() < deadline:
                    time.sleep(0.005)
            finally:
                sampler.stop()
        self.assertGreaterEqual(sampler.peak["errors"], 3)
        self.assertIn("RuntimeError: unexpected probe boom", str(sampler.peak.get("last_error")))
        self.assertEqual(len(logs.records), 1)
        self.assertIn(logs.records[0].levelname, {"WARNING", "ERROR"})
        self.assertIn("RuntimeError", logs.records[0].getMessage())
        self.assertIn("unexpected probe boom", logs.records[0].getMessage())


if __name__ == "__main__":
    unittest.main()
