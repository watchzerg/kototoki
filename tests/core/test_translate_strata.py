"""Strata 启停的伪 CLI 测试（ADR-0019 第 2 点）：已有 launch 时拒绝且不替别人停、等 names 释放显存、
`--no-tui --model iq3_s` 启动、等唯一一个 ready、按 ADR-0017 核对身份（版本／run config／`/v1/models`／`/v1/status`），不符即停并拒绝；未就绪、
启动失败、被中断都执行 `--stop`；退出核实 `--status` 为空与显存释放，核实失败只记 ERROR、不抛出。不调用真实 `strata`。"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import unittest

from kototoki.artifacts import read_json
from kototoki.llama_server import InfraFailure
from kototoki.translate import recipes as R
from kototoki.translate import strata as S
from kototoki.translate.strata import StrataRefused, StrataServer

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
        self.model_name = R.MODEL
        self.models = [R.MODEL]
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
        self.engine_lines = "strata generate: expert arena: locked 1302 MiB\n"
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
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
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
        self.assertEqual((observed["config"]["model_name"], observed["status"]["context"]["native"]), (R.MODEL, 131072))
        resources = read_json(self.root / "resources.json")
        self.assertEqual((resources["gpu_used_mib"], resources["ram_used_gib"]), (15600, 21.5))
        self.assertGreaterEqual(resources["samples"], 2)
        final = read_json(self.root / "strata-final.json")
        self.assertEqual((final["stop"], final["status_empty"], final["free_vram_mib"], final["released"]),
                         ("ok", True, 15000, True))
        self.assertEqual({r.levelname for r in logs.records}, {"INFO"})

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
        with self.assertRaisesRegex(InfraFailure, "did not become ready within 300 s"):
            with self.server():
                self.fail("must not enter")
        self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])
        self.assertIsNone(self.fake.state)

    def test_two_launches_are_refused(self) -> None:
        self.fake.extra_launch = True
        with self.assertRaisesRegex(StrataRefused, "expected one Strata launch, got 2"):
            with self.server():
                self.fail("must not enter")
        self.assertEqual(self.verbs(), ["launch --no-tui --model iq3_s", "launch --stop"])

    def test_launch_command_failure_still_stops(self) -> None:
        self.fake.launch_error = subprocess.CalledProcessError(
            2, ["strata", "launch"], stderr="strata: `strata launch` with no choices opens screens.\n")
        with self.assertRaisesRegex(InfraFailure, "exited with 2: strata: `strata launch` with no choices"):
            with self.server():
                self.fail("must not enter")
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
        with self.assertLogs("kototoki.translate", level="ERROR") as logs:
            with self.server():
                pass
        final = read_json(self.root / "strata-final.json")
        self.assertEqual((final["stop"], final["status_empty"], final["released"]), ("ok", False, False))
        self.assertIn("free GPU memory", final["error"].replace("Free", "free"))
        self.assertIn("Strata stop not confirmed", logs.output[-1])
        self.assertEqual(self.pids, [4242, None])

    def test_vram_not_released_after_stop_is_recorded(self) -> None:
        with self.assertLogs("kototoki.translate", level="ERROR"):
            with self.server():
                self.fake.vram_stays_low = True
        final = read_json(self.root / "strata-final.json")
        self.assertEqual((final["status_empty"], final["released"], final["free_vram_mib"]), (True, False, None))
        self.assertIn("1000 MiB", final["error"])

    def test_waits_for_ram_before_launching(self) -> None:
        self.fake.ram = [41.2, 44.0, 51.0]  # 建表进程的内存还在释放
        with self.server() as server:
            self.assertEqual(server.identity["available_ram_gib_before_start"], 51.0)
        self.assertGreaterEqual(self.now[0], 2 * S.POLL_S)  # 轮询了两次才启动
        self.assertIn(S.LAUNCH_ARGS, self.fake.commands)

    def test_low_ram_after_waiting_warns_and_launches_anyway(self) -> None:
        self.fake.ram = [30.0]
        with self.assertLogs("kototoki.translate", level="WARNING") as logs:
            with self.server() as server:
                self.assertEqual(server.identity["available_ram_gib_before_start"], 30.0)
        self.assertIn("only 30.0 GiB RAM available", logs.output[0])
        self.assertIn("launch --no-tui --model iq3_s", self.verbs())

    def test_mmap_fallback_is_recorded_and_warned_not_refused(self) -> None:
        self.fake.engine_lines = ("strata generate: not enough RAM for the expert arena (2.21 GiB short)\n"
                                  "strata generate: experts via mmap\n")
        with self.assertLogs("kototoki.translate", level="WARNING") as logs:
            with self.server():
                pass
        self.assertEqual(read_json(self.root / "strata.json")["expert_arena"], "mmap")
        self.assertTrue(any("reads them from the SSD" in line for line in logs.output))

    def test_expert_arena_parsing(self) -> None:
        self.assertIsNone(S.expert_arena(""))
        self.assertEqual(S.expert_arena("strata generate: expert arena: locked\n"), "ram")
        self.assertEqual(S.expert_arena("strata generate: experts via mmap (not enough RAM)\n"), "mmap")

    def test_status_parses_only_the_json_line(self) -> None:
        self.assertEqual(S.running(lambda *a: '{"running": []}\nNo launches running.\n'), [])
        self.assertEqual(S.running(lambda *a: '{"running": [{"name": "a"}]}\n'), [{"name": "a"}])


if __name__ == "__main__":
    unittest.main()
