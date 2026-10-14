"""翻译子系统伪客户端测试：正常、按批次续跑、基础设施失败重启即新 session、缓存校验、空场景、
`ja.srt` 变化换目录、显存轮询超时、批次终态失败。不启动 llama-server，不占 GPU。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.error import HTTPError

from kototoki import artifacts
from kototoki.artifacts import read_json
from kototoki.srt import format_srt, parse_srt
from kototoki.translate import RECIPE_HASH, Session, TranslateError, translate_document
from kototoki.translate import recipes as R
from kototoki.translate.server import InfraFailure, wait_for_free_vram

SEED = 7


def document(n: int, word: str = "台詞"):
    return parse_srt(format_srt([(i * 2.0, i * 2.0 + 1.5, f"{word}{i}ですね") for i in range(n)]))


class FakeServer:
    def __init__(self, harness: "Harness", runtime_dir: Path, number: int, on_pid):
        self.harness, self.runtime_dir, self.number, self.on_pid = harness, runtime_dir, number, on_pid
        self.pid = 1000 + number
        self.url = f"http://127.0.0.1:8080/#{number}"
        self.identity = {"server_pid": self.pid, "command": ["fake"]}
        self.completions = 0
        self.stopped = False

    def __enter__(self) -> "FakeServer":
        failure = self.harness.start_failures.pop(0) if self.harness.start_failures else None
        if failure is not None:
            failure()
        self.on_pid(self.pid)
        self.harness.events.append(f"start:{self.number}")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stopped = True
        self.on_pid(None)
        self.harness.events.append(f"stop:{self.number}")


class FakeClient:
    """token 即码点；按待译 JSON 回译文。`plan` 按本客户端的 completion 序号注入故障。"""

    def __init__(self, server: FakeServer, plan: dict[int, Any]):
        self.server, self.plan = server, plan
        self.completions = 0
        self.last_exchange = None

    def tokenize(self, prompt: str) -> list[int]:
        return [ord(ch) for ch in prompt]

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        self.completions += 1
        self.server.completions += 1
        self.server.harness.requests.append(request)
        behaviour = self.plan.get(self.completions)
        if isinstance(behaviour, BaseException):
            raise behaviour
        if callable(behaviour):
            behaviour()
        if behaviour == "oom":
            raise HTTPError("http://127.0.0.1:8080/completion", 500, "CUDA error: out of memory", {}, None)
        first = self.server.completions == 1
        cache_n = self.server.harness.first_cache_n if first else 5
        base = {"tokens_predicted": 12, "tokens_evaluated": len(request["prompt"]), "stop_type": "eos",
                "timings": {"cache_n": cache_n, "prompt_n": len(request["prompt"])}}
        if behaviour == "bad_json":
            return base | {"content": "{not json"}
        prompt = "".join(chr(t) for t in request["prompt"])
        target, _ = json.JSONDecoder().raw_decode(prompt.split("【待译 JSON】\n", 1)[1])
        texts = {k: "译" + k + ("\n\n续" if behaviour == "blank_line" else "") for k in target["translations"]}
        return base | {"content": json.dumps({"translations": texts}, ensure_ascii=False)}


class Harness:
    def __init__(self, root: Path):
        self.root = root
        self.events: list[str] = []
        self.pids: list[int | None] = []
        self.requests: list[dict[str, Any]] = []
        self.plans: list[dict[int, Any]] = []  # 依次分给每个新客户端
        self.start_failures: list[Any] = []    # 依次用于每次 server 启动；None 表示正常
        self.first_cache_n = 0
        self.servers: dict[str, FakeServer] = {}
        self.config = SimpleNamespace(paths=SimpleNamespace(output_dir=root / "out", llama_server=root / "x.exe"),
                                      models=SimpleNamespace(translate=root / "m.gguf"),
                                      translate=SimpleNamespace(seed=SEED, port=8080))

    def session(self) -> Session:
        def server_factory(runtime_dir: Path, on_pid) -> FakeServer:
            server = FakeServer(self, runtime_dir, len(self.servers) + 1, on_pid)
            self.servers[server.url] = server
            return server

        def client_factory(url: str, *, timeout: float, trace_dir: Path) -> FakeClient:
            return FakeClient(self.servers[url], self.plans.pop(0) if self.plans else {})

        return Session(self.config, on_server_pid=self.pids.append, server_factory=server_factory,
                       client_factory=client_factory)

    def run_dir(self, doc) -> Path:
        return artifacts.translate_run_dir(self.root / "out/.work/abc", doc.source_sha256)

    def translate(self, doc, session: Session | None = None):
        if session is not None:
            return translate_document(doc, self.run_dir(doc), session, self.config)
        with self.session() as own:
            return translate_document(doc, self.run_dir(doc), own, self.config)

    def run_root(self, doc) -> Path:
        return self.run_dir(doc) / f"{R.PRODUCT.name}__s{SEED}"


class TranslateDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.h = Harness(Path(tmp.name))

    def run_json(self, doc) -> dict[str, Any]:
        return read_json(self.h.run_root(doc) / "run.json")

    def batch_lines(self, doc) -> list[dict[str, Any]]:
        text = (self.h.run_root(doc) / "batches.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def test_normal_run_translates_every_cue(self) -> None:
        doc = document(23)
        result = self.h.translate(doc)
        self.assertEqual(result.translations, {cue.id: "译" + cue.id for cue in doc.cues})
        self.assertEqual(result.fallback_count, 0)
        self.assertEqual(result.report["state"], "complete")
        run = self.run_json(doc)
        self.assertEqual((run["recipe_hash"], run["seed"]), (RECIPE_HASH, SEED))
        self.assertEqual(run["source"]["ja_srt_sha256"], doc.source_sha256)
        self.assertEqual(len(run["sessions"]), 1)
        self.assertFalse(run["resumed"])
        self.assertTrue(run["sessions"][0]["cache_reset"]["verified"])
        self.assertEqual([row["index"] for row in self.batch_lines(doc)], [0, 1, 2])
        scene = read_json(self.h.run_root(doc) / "scene.json")
        self.assertEqual(scene["status"], "complete")
        self.assertEqual(scene["translations"], result.translations)
        self.assertEqual(self.h.pids, [1001, None])
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        # 首个请求即第 0 批按冻结配方构造的完整 completion 请求。
        from kototoki.translate.batching import build_batches
        from kototoki.translate.data import scene_from_document
        scene = scene_from_document(doc)
        window = build_batches(scene, R.PRODUCT)[0].to_window(scene)
        prompt = R.render_translation(window)
        expected = R.completion_request([ord(ch) for ch in prompt], SEED, R.translation_grammar(window["translate_ids"]))
        self.assertEqual(json.dumps(self.h.requests[0], ensure_ascii=False), json.dumps(expected, ensure_ascii=False))

    def test_one_server_session_serves_the_whole_batch(self) -> None:
        a, b = document(12), document(5, "別")
        with self.h.session() as session:
            self.h.translate(a, session)
            self.h.translate(b, session)  # 第二部影片首个请求 cache_n 非 0，但校验每个 session 只做一次
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        self.assertEqual(self.run_json(b)["sessions"][0]["server_session"], self.run_json(a)["sessions"][0]["server_session"])
        self.assertEqual(self.run_json(b)["completion"]["state"], "complete")

    def test_resume_continues_from_the_first_unwritten_batch(self) -> None:
        doc = document(23)
        self.h.plans = [{2: KeyboardInterrupt()}]
        with self.assertRaises(KeyboardInterrupt):
            self.h.translate(doc)
        self.assertEqual(len(self.batch_lines(doc)), 1)
        self.assertEqual(self.run_json(doc)["completion"]["state"], "partial")
        # 中断时写了一半的一行：不算完成，续跑前截掉。
        with (self.h.run_root(doc) / "batches.jsonl").open("ab") as stream:
            stream.write(b'{"index": 1, "batch_id": "tor')
        self.h.requests.clear()
        result = self.h.translate(doc)
        self.assertEqual(len(result.translations), 23)
        self.assertEqual(len(self.h.requests), 2)
        self.assertEqual([row["index"] for row in self.batch_lines(doc)], [0, 1, 2])
        run = self.run_json(doc)
        self.assertEqual(len(run["sessions"]), 2)
        self.assertTrue(run["resumed"])
        self.assertFalse((self.h.run_root(doc) / "scene.json").read_text(encoding="utf-8").count("tor"))

    def test_corrupt_middle_line_is_rejected(self) -> None:
        doc = document(23)
        self.h.translate(doc)
        path = self.h.run_root(doc) / "batches.jsonl"
        lines = path.read_bytes().splitlines(keepends=True)
        path.write_bytes(lines[0] + b"garbage\n" + lines[2])
        with self.assertRaisesRegex(ValueError, "corrupt line 2"):
            self.h.translate(doc)

    def test_sessions_record_written_batches_before_the_call_ends(self) -> None:
        # 强杀时 finally 不会运行：每批落盘后 run.json 已记下本 session 写入的批次数。
        doc = document(23)
        seen = []

        class Probe(BaseException):
            pass

        def check() -> None:
            seen.append(read_json(self.h.run_root(doc) / "run.json")["sessions"][0]["batches_written"])
            raise Probe()

        self.h.plans = [{3: check}]
        with self.assertRaises(Probe):
            self.h.translate(doc)
        self.assertEqual(seen, [2])

    def test_unexpected_exception_is_recorded_and_stops_the_server(self) -> None:
        doc = document(12)
        self.h.plans = [{2: ValueError("Expected server JSON object")}]
        with self.assertRaises(ValueError):
            self.h.translate(doc)
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        reason = self.run_json(doc)["sessions"][0]["stop_reason"]
        self.assertTrue(reason.startswith("session_error: ValueError"), reason)

    def test_blank_line_in_translation_is_a_parse_failure(self) -> None:
        doc = document(5)
        self.h.plans = [{1: "blank_line", 2: "blank_line"}]
        with self.assertRaisesRegex(TranslateError, "parse"):
            self.h.translate(doc)
        self.assertFalse((self.h.run_root(doc) / "batches.jsonl").exists())

    def test_rerun_of_a_complete_run_does_not_start_a_server(self) -> None:
        doc = document(12)
        self.h.translate(doc)
        self.h.events.clear()
        result = self.h.translate(doc)
        self.assertEqual(len(result.translations), 12)
        self.assertEqual(self.h.events, [])

    def test_oom_restarts_the_server_as_a_new_session(self) -> None:
        doc = document(23)
        self.h.plans = [{2: "oom"}]
        result = self.h.translate(doc)
        self.assertEqual(len(result.translations), 23)
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2"])
        self.assertEqual(self.h.pids, [1001, None, 1002, None])
        run = self.run_json(doc)
        first, second = run["sessions"]
        self.assertEqual((first["stop_reason"], first["infra_failure"]["kind"], first["batches_written"]), ("oom", "oom", 1))
        self.assertTrue((self.h.run_root(doc) / first["infra_failure"]["evidence"]).is_file())
        self.assertEqual(second["batches_written"], 2)
        self.assertEqual(second["cache_reset"]["first_cache_n"], 0)  # 新 session 重做缓存校验
        self.assertTrue(run["resumed"])
        self.assertEqual(run["completion"]["restarts_last_call"], 1)

    def test_infra_failure_gives_up_after_two_restarts(self) -> None:
        doc = document(12)
        self.h.plans = [{1: "oom"}, {1: "oom"}, {1: "oom"}]
        with self.assertRaisesRegex(TranslateError, "after 2 server restarts"):
            self.h.translate(doc)
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2", "start:3", "stop:3"])
        run = self.run_json(doc)
        self.assertEqual(len(run["sessions"]), 3)
        self.assertEqual(run["completion"]["state"], "partial")
        self.assertFalse((self.h.run_root(doc) / "batches.jsonl").exists())

    def test_cache_check_failure_is_an_infrastructure_failure(self) -> None:
        doc = document(5)
        self.h.first_cache_n = 9  # server 自称复用了缓存：首个请求即判 cache 失败
        with self.assertRaises(TranslateError):
            self.h.translate(doc)
        run = self.run_json(doc)
        self.assertEqual([s["stop_reason"] for s in run["sessions"]], ["cache"] * 3)
        self.assertEqual(run["sessions"][0]["cache_reset"]["first_cache_n"], 9)
        self.h.first_cache_n = 0
        self.assertEqual(len(self.h.translate(doc).translations), 5)

    def test_empty_scene_writes_nothing_and_requests_nothing(self) -> None:
        doc = parse_srt("")
        result = self.h.translate(doc)
        self.assertEqual((result.translations, result.fallback_count), ({}, 0))
        self.assertEqual(self.h.events, [])
        self.assertEqual(self.run_json(doc)["completion"]["state"], "complete")

    def test_changed_ja_srt_uses_a_new_directory_and_keeps_the_old(self) -> None:
        old, new = document(5), document(5, "変")
        self.h.translate(old)
        self.h.translate(new)
        self.assertNotEqual(self.h.run_dir(old), self.h.run_dir(new))
        self.assertTrue(self.h.run_dir(new).name.startswith("srt-"))
        self.assertEqual(self.run_json(old)["completion"]["state"], "complete")
        self.assertEqual(self.run_json(new)["source"]["ja_srt_sha256"], new.source_sha256)

    def test_seed_change_uses_its_own_run(self) -> None:
        doc = document(5)
        self.h.translate(doc)
        self.h.config.translate.seed = SEED + 1
        self.h.translate(doc)
        self.assertTrue((self.h.run_dir(doc) / f"{R.PRODUCT.name}__s{SEED + 1}" / "run.json").is_file())
        self.assertTrue(self.h.run_root(doc).is_dir())

    def test_vram_poll_timeout_is_an_infrastructure_failure(self) -> None:
        doc = document(5)
        clock = [0.0]

        def low_vram() -> None:
            wait_for_free_vram(14300, 10.0, query=lambda: 9000, sleep=lambda s: clock.__setitem__(0, clock[0] + s),
                               clock=lambda: clock[0])

        self.h.start_failures = [low_vram, low_vram, low_vram]
        with self.assertRaisesRegex(TranslateError, "9000 MiB"):
            self.h.translate(doc)
        run = self.run_json(doc)
        self.assertEqual(run["sessions"], [])
        self.assertEqual(len(run["server_start_failures"]), 3)
        self.assertIn("9000 MiB", run["server_start_failures"][0]["error"])
        self.assertEqual(self.h.pids, [])

    def test_unstartable_server_fails_the_rest_of_the_batch_without_waiting(self) -> None:
        def crash() -> None:
            raise InfraFailure("Free GPU memory 9000 MiB stayed below 14300 MiB for 120 s")

        a, b = document(5), document(5, "別")
        self.h.start_failures = [crash] * 3
        with self.h.session() as session:
            with self.assertRaises(TranslateError):
                self.h.translate(a, session)
            with self.assertRaisesRegex(TranslateError, "earlier in this batch.*9000 MiB"):
                self.h.translate(b, session)
        self.assertEqual(self.h.start_failures, [])  # 第二部影片没有再尝试启动
        self.assertEqual(self.run_json(b)["server_start_failures"], [])

    def test_mixed_failures_do_not_mark_the_server_unavailable(self) -> None:
        def crash() -> None:
            raise InfraFailure("llama-server exited 1 during load")

        a, b = document(5), document(5, "別")
        self.h.start_failures = [crash, None, None]
        self.h.plans = [{1: "oom"}, {1: "oom"}]
        with self.h.session() as session:
            with self.assertRaises(TranslateError):
                self.h.translate(a, session)
            self.assertEqual(len(self.h.translate(b, session).translations), 5)

    def test_start_failure_then_success(self) -> None:
        def crash() -> None:
            raise InfraFailure("llama-server exited 1 during load (out of memory)")

        self.h.start_failures = [crash]
        result = self.h.translate(document(5))
        self.assertEqual(len(result.translations), 5)

    def test_terminal_batch_failure_fails_the_file_without_writing_the_batch(self) -> None:
        doc = document(12)
        self.h.plans = [{2: "bad_json", 3: "bad_json"}]
        with self.assertRaisesRegex(TranslateError, "failed terminally"):
            self.h.translate(doc)
        self.assertEqual([row["index"] for row in self.batch_lines(doc)], [0])
        evidence = list((self.h.run_root(doc) / "terminal-failures").glob("*.json"))
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(read_json(evidence[0])["request"]["attempts"]), 2)
        self.assertEqual(self.h.events, ["start:1", "stop:1"])  # 终态失败不重启 server
        self.assertEqual(len(self.h.translate(doc).translations), 12)  # 本票内重跑会再试


if __name__ == "__main__":
    unittest.main()
