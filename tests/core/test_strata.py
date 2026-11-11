"""Strata 启停与共享 session 的伪 CLI 测试（ADR-0019 第 2 点、ADR-0022）：已有 launch 时拒绝且不替别人停、等上一阶段释放显存、
`--no-tui --model iq3_s` 启动、等唯一一个 ready、按 ADR-0017 核对身份（版本／run config／`/v1/models`／`/v1/status`），不符即停并拒绝；未就绪、
启动失败、被中断都执行 `--stop`；退出核实 `--status` 为空与显存释放，核实失败只记 ERROR、不抛出。共享 `Session`：首次才启动、
两阶段复用、`stop` 后再起为新 session、启动失败整批累计 `MAX_START_FAILURES` 次或被拒即 `unavailable`。不调用真实 `strata`。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest

from types import SimpleNamespace

from kototoki import artifacts
from kototoki import strata as S
from kototoki.artifacts import read_json
from kototoki.local_client import InfraFailure
from kototoki.strata import Session, StrataRefused, StrataServer, wait_for_free_vram

# 0.2.12 的默认启动真实写下的参数形状：总带 `--mtp <权重目录>`，DFlash2 不在 run config 里（2026-11-08 smoke）。
DEFAULT_ARGS = ["--pack", "p", "--spec", "4", "--spec-min-p", "0.5", "--mtp", "D:/mtp/rt", "--max-context", "131072",
                "--kv", "int8", "--kv-resident", "32768", "--vision"]
DFLASH_LINE = "[strata] drafting: DFlash2 alone (--draft dflash2, --draft-conf 0.7)\n"


class FakeStrata:
    """`strata` CLI 与 HTTP 端点的状态机。显存：服务运行时空闲 1000 MiB，停掉后 15000 MiB。"""

    def __init__(self, root: Path):
        self.root = root
        self.commands: list[tuple[str, ...]] = []
        self.version = "strata 0.2.12 (build 0.1.58)"
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
        self.launch_error: BaseException | None = None
        self.stop_ignored = False               # `--stop` 后仍显示在服务
        self.vram_stays_low = False
        self.extra_launch = False               # ready 时同时冒出第二个 launch
        self.free_before = 15000
        self.ram = [55.0]                       # 依次返回的可用内存（GiB），用完后保持最后一个值
        self.engine_lines = "strata generate: expert arena: locked 1302 MiB via working-set minimum + VirtualLock\n"
        self.engine_log = root / "launch-logs" / "k1.engine.log"
        self.engine_log.parent.mkdir(exist_ok=True)
        self.engine_log.write_text("strata generate: experts via mmap (older launch)\n", encoding="utf-8")

    def launch_row(self) -> dict[str, Any]:
        config = self.root / "launch.json"
        config.write_text(json.dumps({"model_name": self.model_name, "exe": "llama-server.exe", "args": self.args,
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
                if self.extra_launch and self.state == "ready":
                    rows.append(dict(self.launch_row(), name="k2"))
            return json.dumps({"schema_version": 1, "ok": True, "running": rows}) + "\nhuman-readable line\n"
        if args == S.LAUNCH_ARGS:
            if self.launch_error is not None:
                raise self.launch_error
            self.state = "loading"
            with self.engine_log.open("a", encoding="utf-8") as handle:
                handle.write(self.engine_lines)
            if self.drafting_line is not None:
                with self.log.open("a", encoding="utf-8") as handle:
                    handle.write("[strata] loading the model ...\n" + self.drafting_line)
            return ""
        if args == S.STOP_ARGS:
            if not self.stop_ignored:
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
        if self.state is None and not self.vram_stays_low:
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

    def server(self) -> StrataServer:
        def sleep(seconds: float) -> None:
            self.now[0] += seconds

        return StrataServer(self.root, on_pid=self.pids.append, cli=self.fake.cli, get=self.fake.get,
                            free_vram=self.fake.free_vram, available_ram=self.fake.available_ram, sleep=sleep,
                            clock=lambda: self.now[0], log_dir=self.root / "logs",
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

    def test_waits_for_names_server_to_release_vram_then_gives_up(self) -> None:
        self.fake.free_before = 9000
        with self.assertRaisesRegex(InfraFailure, "9000 MiB stayed below 14000 MiB"):
            with self.server():
                self.fail("must not enter")
        self.assertEqual(self.verbs(), [])  # 显存不够就不启动（llama-server 与 Strata 不同时驻留）

    def test_probe_mismatch_stops_the_launch_and_refuses(self) -> None:
        cases = [("drafting_line", "[strata] drafting: MTP alone (--spec 4)\n", "drafting 'mtp'"),
                 ("drafting_line", None, "drafting None"),  # 本次启动没写起草行：不拿上一次的行充数
                 ("args", ["--mtp", "D:/mtp/rt", "--max-context", "65536"], "--max-context '65536'"),
                 ("model_name", "qwen3.8-27b", "model 'qwen3.8-27b'"),
                 ("version", "strata 0.2.13 (build 0.1.60)", "version differs"),
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

    def test_not_ready_in_time_is_an_infra_failure_and_stops(self) -> None:
        self.fake.ready_after = None
        with self.assertRaisesRegex(InfraFailure, "did not become ready within 300 s") as caught:
            with self.server():
                self.fail("must not enter")
        self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])
        self.assertIsNone(self.fake.state)
        self.assertTrue(str(caught.exception).endswith(f"; see {self.fake.log}"), str(caught.exception))

    def test_two_launches_are_refused(self) -> None:
        self.fake.extra_launch = True
        with self.assertRaisesRegex(StrataRefused, "expected one Strata launch, got 2"):
            with self.server():
                self.fail("must not enter")
        self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])

    def test_launch_command_failure_still_stops(self) -> None:
        self.fake.launch_error = subprocess.CalledProcessError(
            2, ["strata", "launch"], stderr="strata: `strata launch` with no choices opens screens.\n")
        with self.assertRaisesRegex(InfraFailure, "exited with 2: strata: `strata launch` with no choices") as caught:
            with self.server():
                self.fail("must not enter")
        self.assertTrue(str(caught.exception).endswith(f"; see {self.root / 'logs'}"))  # 没有新写的日志：给目录
        self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])

    def test_interrupt_while_loading_still_stops(self) -> None:
        self.fake.ready_after = None
        server = self.server()

        def interrupt(seconds: float) -> None:
            raise KeyboardInterrupt()

        server.sleep = interrupt
        with self.assertRaises(KeyboardInterrupt):
            with server:
                self.fail("must not enter")
        self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])

    def test_interrupt_inside_the_session_stops_strata(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            with self.server():
                raise KeyboardInterrupt()
        self.assertIsNone(self.fake.state)
        self.assertEqual(self.pids, [4242, None])

    def test_unconfirmed_stop_is_logged_not_raised(self) -> None:
        self.fake.stop_ignored = True
        with self.assertLogs("kototoki.strata", level="ERROR") as logs:
            with self.server():
                pass
        final = read_json(self.root / "strata-final.json")
        self.assertEqual((final["stop"], final["status_empty"], final["released"]), ("ok", False, False))
        self.assertIn("free GPU memory", final["error"].replace("Free", "free"))
        self.assertIn("Strata stop not confirmed", logs.output[-1])
        self.assertTrue(logs.output[-1].endswith(f"; see {self.root / 'strata-final.json'}"), logs.output[-1])
        self.assertEqual(self.pids, [4242, None])

    def test_vram_not_released_after_stop_is_recorded(self) -> None:
        with self.assertLogs("kototoki.strata", level="ERROR"):
            with self.server():
                self.fake.vram_stays_low = True
        final = read_json(self.root / "strata-final.json")
        self.assertEqual((final["status_empty"], final["released"], final["free_vram_mib"]), (True, False, None))
        self.assertIn("1000 MiB", final["error"])

    def test_waits_for_ram_before_launching(self) -> None:
        self.fake.ram = [41.2, 44.0, 53.0]  # 建表进程的内存还在释放
        with self.server() as server:
            self.assertEqual(server.identity["available_ram_gib_before_start"], 53.0)
        self.assertGreaterEqual(self.now[0], 2 * S.POLL_S)  # 轮询了两次才启动
        self.assertIn(S.LAUNCH_ARGS, self.fake.commands)

    def test_low_ram_after_waiting_warns_and_launches_anyway(self) -> None:
        self.fake.ram = [30.0]
        with self.assertLogs("kototoki.strata", level="WARNING") as logs:
            with self.server() as server:
                self.assertEqual(server.identity["available_ram_gib_before_start"], 30.0)
        self.assertIn("only 30.0 GiB RAM available", logs.output[0])
        self.assertIn("launch --no-tui --model iq3_s", self.verbs())

    def test_mmap_fallback_or_unconfirmed_arena_stops_and_refuses(self) -> None:
        cases = [("strata generate: expert arena: locked 1 MiB\n"
                  "strata generate: not enough RAM for the expert arena (2.21 GiB short)\n"
                  "strata generate: experts via mmap\n", "mmap", "fell back to mmap"),
                 ("strata generate: memory guard: ...\n", None, "not confirmed")]
        for lines, arena, message in cases:
            with self.subTest(arena=arena):
                self.fake = FakeStrata(self.root)
                self.fake.engine_lines = lines
                self.pids.clear()
                with self.assertRaisesRegex(StrataRefused, message):
                    with self.server():
                        self.fail("must not enter")
                self.assertEqual(read_json(self.root / "strata.json")["expert_arena"], arena)
                self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])
                self.assertIsNone(self.fake.state)
                self.assertTrue(read_json(self.root / "strata-final.json")["released"])

    def test_expert_arena_parsing(self) -> None:
        self.assertIsNone(S.expert_arena(""))
        self.assertEqual(S.expert_arena("strata generate: expert arena: locked 3502 MiB\n"), "ram")
        self.assertIsNone(S.expert_arena("strata generate: expert arena read unbuffered\n"))
        self.assertEqual(S.expert_arena("strata generate: experts via mmap (not enough RAM)\n"), "mmap")

    def test_status_parses_only_the_json_line(self) -> None:
        self.assertEqual(S.running(lambda *a: '{"running": []}\nNo launches running.\n'), [])
        self.assertEqual(S.running(lambda *a: '{"running": [{"name": "a"}]}\n'), [{"name": "a"}])


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

    def test_long_wait_logs_one_warning(self):
        with self.assertLogs("kototoki.strata", level="INFO") as logs:
            self.assertEqual(self._wait([1000] * 20 + [14500], timeout=120.0), 14500)
        (record,) = logs.records
        self.assertEqual(record.levelname, "WARNING")
        self.assertIn("1000 MiB < 14300 MiB", record.getMessage())

    def test_warning_carries_the_stage_prefix(self):
        with self.assertLogs("kototoki.strata", level="WARNING") as logs:
            self._wait([1000] * 20 + [14500], timeout=120.0, stage="translate")
        self.assertTrue(logs.records[0].getMessage().startswith("[translate] waiting for free GPU memory: "))

    def test_short_wait_logs_nothing(self):
        with self.assertNoLogs("kototoki.strata", level="INFO"):
            self._wait([1000, 14500])

    def test_timeout_raises_with_last_reading(self):
        with self.assertRaises(InfraFailure) as caught:
            self._wait([1000, 2000, 3456])
        self.assertIn("3456", str(caught.exception))

    def test_unknown_reading_message(self):
        with self.assertRaises(InfraFailure) as caught:
            self._wait([None])
        message = str(caught.exception).lower()
        self.assertIn("unknown", message)
        self.assertIn("nvidia-smi failed", message)


class SessionTests(unittest.TestCase):
    """共享 session 的生命周期用伪服务验证；真实 `StrataServer` 的行为见上。"""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = SimpleNamespace(paths=SimpleNamespace(work_dir=self.root / "work", input_dir=self.root / "in"))
        self.events: list[str] = []
        self.pids: list[int | None] = []
        self.refuse_on: set[int] = set()   # 这些序号的启动被拒绝（StrataRefused）
        self.infra_on: set[int] = set()    # 这些序号的启动失败（InfraFailure，服务已自行停掉）
        self.servers: list[Any] = []

    def factory(self, runtime_dir: Path, on_pid: Any) -> Any:
        tests = self
        number = len(self.servers) + 1

        class FakeServer:
            url = "http://127.0.0.1:8080"
            identity = {"candidate": S.MODEL}

            def __enter__(self) -> "FakeServer":
                tests.events.append(f"start:{number}:{runtime_dir.name}")
                if number in tests.refuse_on:
                    on_pid(None)
                    raise StrataRefused(f"refused {number}")
                if number in tests.infra_on:
                    on_pid(None)
                    raise InfraFailure(f"launch {number} exploded")
                on_pid(1000 + number)
                return self

            def __exit__(self, *exc: Any) -> None:
                tests.events.append(f"stop:{number}")
                on_pid(None)

        server = FakeServer()
        self.servers.append(server)
        return server

    def session(self) -> Session:
        return Session(self.config, on_server_pid=self.pids.append, server_factory=self.factory)

    def test_starts_once_and_is_reused_across_stages(self) -> None:
        with self.session() as session:
            self.assertIsNone(session.server)
            first = session.ensure_started()   # names 阶段
            second = session.ensure_started()  # 翻译阶段
            self.assertIs(first, second)
            self.assertEqual(session.label, f"{session.runtime_root.name}/session-01")
        self.assertEqual(self.events, ["start:1:session-01", "stop:1"])
        self.assertEqual(self.pids, [1001, None])
        self.assertEqual(session.runtime_root.parent,
                         artifacts.work_root(self.root / "work", self.root / "in") / S.SESSIONS_DIR)

    def test_stop_then_restart_is_a_new_session(self) -> None:
        session = self.session()
        session.ensure_started()
        session.stop()
        session.stop()  # 幂等
        session.ensure_started()
        self.assertEqual(session.label, f"{session.runtime_root.name}/session-02")
        self.assertEqual(self.events, ["start:1:session-01", "stop:1", "start:2:session-02"])
        session.stop()
        self.assertEqual(self.pids, [1001, None, 1002, None])

    def test_successful_starts_are_not_capped(self) -> None:
        session = self.session()
        for _ in range(S.MAX_START_FAILURES + 2):
            session.ensure_started()
            session.stop()
        self.assertIsNone(session.unavailable)
        self.assertEqual(session.ordinal, S.MAX_START_FAILURES + 2)

    def test_repeated_start_failures_make_the_batch_unavailable(self) -> None:
        self.infra_on = {1, 2, 3, 4}
        session = self.session()
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
        self.assertEqual(self.events, ["start:1:session-01", "start:2:session-02", "start:3:session-03"])  # 第 4 次没有碰工厂
        self.assertIsNone(session.server)
        self.assertEqual(self.pids, [None, None, None])

    def test_refused_start_marks_the_batch_unavailable(self) -> None:
        self.refuse_on = {1}
        with self.session() as session, self.assertLogs("kototoki.strata", level="WARNING") as logs:
            with self.assertRaisesRegex(StrataRefused, "refused 1"):
                session.ensure_started()
            self.assertEqual(session.unavailable, "refused 1")
            self.assertIsNone(session.server)
            with self.assertRaisesRegex(StrataRefused, "refused 1"):
                session.ensure_started()
        self.assertEqual([(r.levelname, r.getMessage()) for r in logs.records],
                         [("ERROR", "[strata] unavailable for the rest of this batch: refused 1")])  # 只记一次
        self.assertEqual(self.events, ["start:1:session-01"])  # 被拒的服务已自行停掉，不再 stop
        self.assertEqual(self.pids, [None])

    def test_one_start_failure_then_success(self) -> None:
        self.infra_on = {1}
        session = self.session()
        with self.assertRaises(InfraFailure):
            session.ensure_started()
        self.assertIsNone(session.unavailable)
        self.assertIsNone(session.server)
        self.assertEqual((session.ordinal, session.start_failures), (1, 1))
        session.ensure_started()
        self.assertEqual(self.events, ["start:1:session-01", "start:2:session-02"])  # 失败的启动也占用一个 session 序号
        session.stop()
        self.assertEqual(self.pids, [None, 1002, None])

    def test_client_is_built_for_the_running_server_with_the_callers_trace_dir(self) -> None:
        made: list[tuple[str, float, Path]] = []

        def client_factory(url: str, *, timeout: float, trace_dir: Path) -> str:
            made.append((url, timeout, trace_dir))
            return "client"

        session = Session(self.config, on_server_pid=self.pids.append, server_factory=self.factory,
                          client_factory=client_factory)
        with self.assertRaisesRegex(RuntimeError, "ensure_started"):
            session.client(self.root / "t", timeout=1.0)  # 没有运行中的服务
        session.ensure_started()
        self.assertEqual(session.client(self.root / "t", timeout=600.0), "client")
        self.assertEqual(made, [("http://127.0.0.1:8080", 600.0, self.root / "t")])  # 目录由调用方定，不另加子目录
        session.stop()

    def test_label_follows_the_attempted_start_ordinal(self) -> None:
        self.infra_on = {1}
        session = self.session()
        self.assertRegex(session.label, r"^\d{8}T\d{6}Z-\d+/session-00$")
        with self.assertRaises(InfraFailure):
            session.ensure_started()
        session.ensure_started()
        self.assertEqual(session.label, f"{session.runtime_root.name}/session-02")  # 失败的启动也占一个序号
        session.stop()

    def test_old_translate_strata_path_is_gone(self) -> None:
        # ADR-0022：再导出模块已删除，研究侧改为直接导入 kototoki.strata
        with self.assertRaises(ImportError):
            importlib.import_module("kototoki.translate.strata")


if __name__ == "__main__":
    unittest.main()
