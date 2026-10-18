"""翻译子系统伪客户端测试：`plan` 的 run 键与 `needs_model`、正常、按批次续跑、基础设施失败重启即新 session、
缓存校验、空场景、`ja.srt` 变化换目录、显存轮询超时。批次终态失败的降级见 `test_translate_degrade.py`。
不启动 llama-server，不占 GPU。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.error import HTTPError

from kototoki.artifacts import read_json
from kototoki.srt import format_srt, parse_srt
from kototoki.translate import RECIPE_HASH, Session, TranslateError, TranslatePlan, translate_document
from kototoki.translate import plan as translate_plan
from kototoki.translate import recipes as R
from kototoki.translate.server import InfraFailure, wait_for_free_vram

SEED = 7


def document(n: int, word: str = "台詞"):
    """每条 1.5 s、相邻停顿 0.5 s，每 10 条之间留 20 s 停顿：dp10-cut 在此恰好切出 10 条一批（与 b10-joint 相同），
    续跑与降级测试只关心批次机制；批内后邻可见（<1 s）、跨 20 s 的邻文不可见。切包规则本身见 `test_translate_recipes`。"""
    def start(i: int) -> float:
        return i * 2.0 + (i // 10) * 20.0
    return parse_srt(format_srt([(start(i), start(i) + 1.5, f"{word}{i}ですね") for i in range(n)]))


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
    """token 即码点；按待译 JSON 回译文。`plan` 按本客户端的 completion 序号注入故障；
    待译 ID 含 `harness.poison` 中任一条时返回非法 JSON（解析失败，用于降级测试）。"""

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
        if self.server.harness.poison & set(target["translations"]):
            return base | {"content": "{not json"}
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
        self.poison: set[str] = set()
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

    work_dir = property(lambda self: self.root / "out/.work/abc")

    def plan(self, doc) -> TranslatePlan:
        return translate_plan(self.work_dir, doc, self.config)

    def translate(self, doc, session: Session | None = None):
        if session is not None:
            return translate_document(self.plan(doc), session)
        with self.session() as own:
            return translate_document(self.plan(doc), own)

    def run_root(self, doc) -> Path:
        return self.plan(doc).run_dir


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
        self.assertEqual(result.report["completion"]["state"], "complete")
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
        from kototoki.translate.batching import build_batches, scene_from_document
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
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 0)
        (row,) = self.batch_lines(doc)
        self.assertEqual(row["degrade"]["nodes"][0]["error_kind"], "parse")  # 按解析失败进入降级

    def test_rerun_of_a_complete_run_does_not_start_a_server(self) -> None:
        doc = document(12)
        self.assertTrue(self.h.plan(doc).needs_model)
        self.h.translate(doc)
        self.h.events.clear()
        plan = self.h.plan(doc)
        self.assertFalse(plan.needs_model)
        result = translate_document(plan, None)  # 不需要模型时编排器不建 session
        self.assertEqual(len(result.translations), 12)
        self.assertEqual(self.h.events, [])

    def test_plan_keys_run_dir_by_ja_srt_recipe_and_seed(self) -> None:
        doc = document(3)
        plan = self.h.plan(doc)
        self.assertEqual(plan.run_dir, self.h.work_dir / "translate" / f"srt-{doc.source_sha256[:12]}"
                         / f"{R.PRODUCT.name}__s{SEED}")
        self.assertEqual(plan.relative, f"translate/srt-{doc.source_sha256[:12]}/{R.PRODUCT.name}__s{SEED}")
        self.assertEqual(plan.identity, {"ja_srt_sha256": doc.source_sha256, "recipe_hash": RECIPE_HASH, "seed": SEED})
        self.assertIs(plan.document, doc)
        self.assertFalse(plan.run_dir.exists())  # 计划不写文件

    def test_plan_rejects_a_run_recorded_under_another_recipe_hash(self) -> None:
        doc = document(3)
        self.h.translate(doc)
        path = self.h.run_root(doc) / "run.json"
        run = read_json(path)
        run["recipe_hash"] = "f" * 64
        path.write_text(json.dumps(run), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Delete .* to translate"):
            self.h.plan(doc)

    def test_incomplete_batches_under_a_complete_run_json_fail_instead_of_starting_a_server(self) -> None:
        doc = document(23)
        self.h.translate(doc)
        (self.h.run_root(doc) / "batches.jsonl").unlink()
        plan = self.h.plan(doc)
        self.assertFalse(plan.needs_model)
        self.h.events.clear()
        with self.assertRaisesRegex(TranslateError, "recorded as complete"):
            translate_document(plan, None)
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
        self.assertTrue(self.h.plan(new).needs_model)
        self.h.translate(new)
        self.assertNotEqual(self.h.plan(old).run_dir, self.h.plan(new).run_dir)
        self.assertEqual(self.h.plan(new).run_dir.parent.name, f"srt-{new.source_sha256[:12]}")
        self.assertFalse(self.h.plan(old).needs_model)
        self.assertEqual(self.run_json(old)["completion"]["state"], "complete")
        self.assertEqual(self.run_json(new)["source"]["ja_srt_sha256"], new.source_sha256)

    def test_seed_change_uses_its_own_run(self) -> None:
        doc = document(5)
        self.h.translate(doc)
        first = self.h.plan(doc)
        self.h.config.translate.seed = SEED + 1
        second = self.h.plan(doc)
        self.assertTrue(second.needs_model)
        self.assertEqual(second.run_dir, first.run_dir.with_name(f"{R.PRODUCT.name}__s{SEED + 1}"))
        self.assertEqual(second.identity["seed"], SEED + 1)
        self.h.translate(doc)
        self.assertTrue((second.run_dir / "run.json").is_file())
        self.assertTrue(first.run_dir.is_dir())

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

    def test_normal_run_logs_one_progress_line_per_batch(self) -> None:
        doc = document(23)
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            self.h.translate(doc)
        batch_lines = [line for line in logs.output if "[translate] batch " in line]
        self.assertEqual(batch_lines, ["INFO:kototoki.translate.generate:[translate] batch 1/3: 10 cue(s), 12 tok, cache 0",
                                       "INFO:kototoki.translate.generate:[translate] batch 2/3: 10 cue(s), 12 tok, cache 5",
                                       "INFO:kototoki.translate.generate:[translate] batch 3/3: 3 cue(s), 12 tok, cache 5"])
        self.assertTrue(any("session 1 start" in line and "3 of 3 batch(es) pending" in line for line in logs.output))
        self.assertTrue(any("session 1 end: 3 batch(es) written" in line for line in logs.output))
        self.assertEqual({record.levelname for record in logs.records}, {"INFO"})

    def test_restart_logs_a_warning_and_giving_up_an_error(self) -> None:
        doc = document(12)
        self.h.plans = [{2: "oom"}]
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            self.h.translate(doc)
        warnings = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("[translate] server restart 1/2: oom: HTTP 500 (oom)"), warnings[0])
        self.h.plans = [{1: "oom"}, {1: "oom"}, {1: "oom"}]
        with self.assertLogs("kototoki.translate", level="INFO") as logs, self.assertRaises(TranslateError):
            self.h.translate(document(5, "別"))
        self.assertEqual([r.levelname for r in logs.records if r.levelname != "INFO"], ["WARNING", "WARNING", "ERROR"])
        (error,) = [r for r in logs.records if r.levelname == "ERROR"]
        self.assertIn("giving up after 2 server restart(s): oom", error.getMessage())

    def test_unexpected_exception_logs_an_error_without_traceback(self) -> None:
        # traceback 归编排器的 ctx.fail，这里只记一行类型，避免运行日志里出现两份。
        self.h.plans = [{1: ValueError("Expected server JSON object")}]
        with self.assertLogs("kototoki.translate", level="ERROR") as logs, self.assertRaises(ValueError):
            self.h.translate(document(5))
        (record,) = logs.records
        self.assertIn("unexpected ValueError", record.getMessage())
        self.assertIsNone(record.exc_info)

    def test_logs_never_contain_cue_text(self) -> None:
        # 覆盖正常批次、降级、回退与重启：日志里不出现任何日文 cue 文字（及其片段）。
        doc = document(23)
        self.h.poison = {doc.cues[3].id}
        self.h.plans = [{14: "oom"}]
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 1)
        text = "\n".join(logs.output)
        self.assertIn("WARNING", text)
        for cue in doc.cues:
            self.assertNotIn(cue.text, text)
        for fragment in ("台詞", "ですね", "译"):
            self.assertNotIn(fragment, text)

    def test_http_error_message_omits_the_response_body(self) -> None:
        from kototoki.translate.generate import StepFailed, run_step
        exchange = self.h.root / "exchange"
        exchange.mkdir()
        (exchange / "response.raw").write_text('{"error": "台詞0ですね exceeds the available context"}', encoding="utf-8")

        class Client:
            last_exchange = str(exchange)

            def tokenize(self, prompt: str) -> list[int]:
                return [1, 2, 3]

            def complete(self, request: dict[str, Any]) -> dict[str, Any]:
                raise HTTPError("http://127.0.0.1:8080/completion", 400, "Bad Request", {}, None)

        with self.assertRaises(StepFailed) as caught:
            run_step(Client(), "台詞0ですね", "root ::= x", SEED, lambda text: text, {}, {})
        self.assertEqual(caught.exception.kind, "context")
        self.assertNotIn("台詞", str(caught.exception))
        self.assertRegex(str(caught.exception), r"^HTTP 400 \(context\): response body \d+ char\(s\)$")

    def test_start_failure_then_success(self) -> None:
        def crash() -> None:
            raise InfraFailure("llama-server exited 1 during load (out of memory)")

        self.h.start_failures = [crash]
        result = self.h.translate(document(5))
        self.assertEqual(len(result.translations), 5)


if __name__ == "__main__":
    unittest.main()
