"""翻译子系统伪客户端测试：`plan` 的 run 键、身份与 `needs_model`、正常、按批次续跑、基础设施失败（OOM、中途断开、
起不来）重启即新 session、Strata 拒绝、空场景、`ja.srt`／seed／注入行变化换目录。批次终态失败的降级见
`test_translate_degrade.py`，Strata 启停与共享 session 本身见 `test_strata.py`。不启动 Strata，不占 GPU。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.error import HTTPError, URLError

from kototoki import artifacts
from kototoki.artifacts import read_json
from kototoki.local_client import InfraFailure
from kototoki.srt import format_srt, parse_srt
from kototoki.strata import Session, StrataRefused, wait_for_free_vram
from kototoki.translate import RECIPE_HASH, TranslateError, TranslatePlan, translate_document
from kototoki.translate import plan as translate_plan
from kototoki.translate import recipes as R

SEED = 7
EMPTY_TABLE: dict[str, Any] = {"entries": []}


def document(n: int, word: str = "台詞"):
    """每条 1.5 s、相邻停顿 0.5 s，每 10 条之间留 20 s 停顿：dp10-cut 在此恰好切出 10 条一批，续跑与降级测试只关心
    批次机制。切包与邻文规则本身见 `test_translate_recipes`。"""
    def start(i: int) -> float:
        return i * 2.0 + (i // 10) * 20.0
    return parse_srt(format_srt([(start(i), start(i) + 1.5, f"{word}{i}ですね") for i in range(n)]))


def table(*rows: tuple[str, str, str]) -> dict[str, Any]:
    """(confidence, ja, zh) → 最小的 `name-table.json` 内容（每行一个实体、一个写法）。"""
    return {"entries": [{"entity_ja": ja, "kind": "person", "confidence": c, "zh": zh, "forms": [{"ja": ja, "zh": zh}],
                         "zh_variants": [], "evidence": []} for c, ja, zh in rows]}


class FakeServer:
    def __init__(self, harness: "Harness", runtime_dir: Path, number: int, on_pid):
        self.harness, self.runtime_dir, self.number, self.on_pid = harness, runtime_dir, number, on_pid
        self.pid = 1000 + number
        self.url = f"http://127.0.0.1:8080/#{number}"
        self.identity = {"candidate": R.MODEL, "strata": {"drafting": "dflash2"}, "cold_load_seconds": 1.0}
        self.completions = 0

    def __enter__(self) -> "FakeServer":
        failure = self.harness.start_failures.pop(0) if self.harness.start_failures else None
        if failure is not None:
            failure()
        self.on_pid(self.pid)
        self.harness.events.append(f"start:{self.number}")
        return self

    def __exit__(self, *exc: Any) -> None:
        self.on_pid(None)
        self.harness.events.append(f"stop:{self.number}")


class FakeClient:
    """按待译 JSON 回译文（OpenAI chat completions 形状）。`plan` 按本客户端的请求序号注入故障；
    待译 ID 含 `harness.poison` 中任一条时返回非法 JSON（解析失败，用于降级测试）；待译条数超过
    `harness.max_targets` 时按服务报超出 context 回 HTTP 400。"""

    def __init__(self, server: FakeServer, plan: dict[int, Any]):
        self.server, self.plan = server, plan
        self.completions = 0
        self.last_exchange = None

    def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
        self.completions += 1
        self.server.completions += 1
        self.server.harness.requests.append(body)
        behaviour = self.plan.get(self.completions)
        if isinstance(behaviour, BaseException):
            raise behaviour
        if callable(behaviour):
            behaviour()
        if behaviour == "oom":
            raise HTTPError("http://127.0.0.1:8080/v1/chat/completions", 500, "CUDA error: out of memory", {}, None)
        user = body["messages"][1]["content"]
        cache_n = 0 if self.server.completions == 1 and not self.server.harness.warm_cache else 5
        base = {"usage": {"prompt_tokens": len(user), "completion_tokens": 12}, "timings": {"cache_n": cache_n}}

        def reply(content: str, finish: str = "stop") -> dict[str, Any]:
            return base | {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}
        if behaviour == "bad_json":
            return reply("{not json")
        if behaviour == "length":
            return reply('{"translations": {', "length")
        target, _ = json.JSONDecoder().raw_decode(user.split("【待译 JSON】\n", 1)[1])
        limit = self.server.harness.max_targets
        if limit is not None and len(target["translations"]) > limit:
            raise HTTPError("http://127.0.0.1:8080/v1/chat/completions", 400,
                            "the request exceeds the available context size", {}, None)
        if self.server.harness.poison & set(target["translations"]):
            return reply("{not json")
        texts = {k: "译" + k + ("\n\n续" if behaviour == "blank_line" else "") for k in target["translations"]}
        return reply(json.dumps({"translations": texts}, ensure_ascii=False))


class Harness:
    def __init__(self, root: Path):
        self.root = root
        self.events: list[str] = []
        self.pids: list[int | None] = []
        self.requests: list[dict[str, Any]] = []
        self.plans: list[dict[int, Any]] = []  # 依次分给每个新客户端
        self.start_failures: list[Any] = []    # 依次用于每次服务启动；None 表示正常
        self.poison: set[str] = set()
        self.max_targets: int | None = None
        self.warm_cache = False                # True：服务的首个请求也报 cache_n 5（前缀缓存未清空）
        self.trace_dirs: list[Path] = []       # 依次给每个新客户端的 trace 目录
        self.table: dict[str, Any] = EMPTY_TABLE
        self.servers: dict[str, FakeServer] = {}
        self.config = SimpleNamespace(paths=SimpleNamespace(work_dir=root / "work", input_dir=root / "in"),
                                      translate=SimpleNamespace(seed=SEED))

    def session(self) -> Session:
        def server_factory(runtime_dir: Path, on_pid) -> FakeServer:
            server = FakeServer(self, runtime_dir, len(self.servers) + 1, on_pid)
            self.servers[server.url] = server
            return server

        def client_factory(url: str, *, timeout: float, trace_dir: Path) -> FakeClient:
            self.trace_dirs.append(trace_dir)
            return FakeClient(self.servers[url], self.plans.pop(0) if self.plans else {})

        return Session(self.config, on_server_pid=self.pids.append, server_factory=server_factory,
                       client_factory=client_factory)

    work_dir = property(lambda self: self.root / "work/abc")

    def plan(self, doc) -> TranslatePlan:
        return translate_plan(self.work_dir, doc, self.table, self.config)

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
        self.assertEqual(run["names"], {"sha256": R.names_sha256([]), "rows": 0})
        self.assertEqual(run["source"]["ja_srt_sha256"], doc.source_sha256)
        self.assertEqual(len(run["sessions"]), 1)
        self.assertFalse(run["resumed"])
        self.assertEqual(run["sessions"][0]["engine"]["candidate"], R.MODEL)
        self.assertEqual([row["index"] for row in self.batch_lines(doc)], [0, 1, 2])
        scene = read_json(self.h.run_root(doc) / "scene.json")
        self.assertEqual(scene["status"], "complete")
        self.assertEqual(scene["translations"], result.translations)
        self.assertEqual(self.h.pids, [1001, None])
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        # 首个请求即第 0 批按产品配方构造的完整请求体（与研究侧 Q2 的逐字节对照在 test_translate_recipes）。
        from kototoki.translate.batching import build_batches, scene_from_document
        scene = scene_from_document(doc)
        window = build_batches(scene)[0].to_window(scene)
        expected = R.request_body(R.messages(window, []), SEED)
        self.assertEqual(json.dumps(self.h.requests[0], ensure_ascii=False), json.dumps(expected, ensure_ascii=False))
        self.assertNotIn("grammar", self.h.requests[0])

    def test_second_attempt_uses_seed_plus_one(self) -> None:
        doc = document(5)
        self.h.plans = [{1: "bad_json"}]
        result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 0)
        self.assertEqual([body["seed"] for body in self.h.requests], [SEED, SEED + 1])
        self.assertEqual(self.h.requests[0]["messages"], self.h.requests[1]["messages"])
        (row,) = self.batch_lines(doc)
        self.assertEqual([a["status"] for a in row["request"]["attempts"]], ["failed", "accepted"])

    def test_injected_rows_reach_the_system_message_of_matching_packs_only(self) -> None:
        doc = parse_srt(format_srt([(0.0, 1.0, "セイバー、行くぞ"), (1.5, 2.5, "はい"), (30.0, 31.0, "士郎！"),
                                    *[(40.0 + i * 2, 41.0 + i * 2, f"台詞{i}") for i in range(12)]]))
        self.h.table = table(("high", "セイバー", "Saber"), ("medium", "士郎", "士郎"), ("high", "凛", "凛"))
        result = self.h.translate(doc)
        self.assertEqual(len(result.translations), len(doc.cues))
        systems = [body["messages"][0]["content"] for body in self.h.requests]
        self.assertTrue(systems[0].endswith(R.NAMES_HEADER + "セイバー → Saber"))
        self.assertTrue(all("士郎 →" not in text and "凛 →" not in text for text in systems))  # medium 与未出现的不注入
        self.assertEqual(self.batch_lines(doc)[0]["request"]["names_injected"], 1)

    def test_session_directory_is_a_utc_stamp_with_pid(self) -> None:
        session = self.h.session()
        self.assertRegex(session.runtime_root.name, r"^\d{8}T\d{6}Z-\d+$")
        self.assertEqual(session.runtime_root.parent, artifacts.work_root(self.h.root / "work", self.h.root / "in") / "strata-sessions")

    def test_one_strata_session_serves_the_whole_batch(self) -> None:
        a, b = document(12), document(5, "別")
        with self.h.session() as session:
            self.h.translate(a, session)
            self.h.translate(b, session)
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        self.assertEqual(self.run_json(b)["sessions"][0]["server_session"], self.run_json(a)["sessions"][0]["server_session"])
        self.assertEqual(self.run_json(b)["completion"]["state"], "complete")

    def test_first_cache_reuse_is_recorded_not_failed(self) -> None:
        doc = document(5)
        self.h.warm_cache = True  # 新 session 的首个请求就看到 cache_n 5
        self.h.translate(doc)
        cache = self.run_json(doc)["sessions"][0]["cache_reset"]
        self.assertEqual((cache["first_cache_n"], cache["verified"], cache["recorded_only"]), (5, False, True))
        self.assertEqual(self.run_json(doc)["completion"]["state"], "complete")

    def test_cache_reset_is_checked_once_per_strata_session(self) -> None:
        a, b = document(12), document(5, "別")
        with self.h.session() as session:
            self.h.translate(a, session)
            self.h.translate(b, session)  # 同一 Strata session：沿用 a 记下的首个请求
            self.h.plans = [{1: "oom"}]
            c = document(5, "変")
            self.h.translate(c, session)  # OOM 后重启即新 session：重新记一次
        first = {"checked": True, "first_cache_n": 0, "verified": True, "recorded_only": True, "exchange": None}
        self.assertEqual(self.run_json(a)["sessions"][0]["cache_reset"], first)
        self.assertEqual(self.run_json(b)["sessions"][0]["cache_reset"], first)
        broken, fresh = self.run_json(c)["sessions"]
        self.assertEqual(broken["cache_reset"], first)  # 仍是 session-01 的记录
        self.assertEqual(fresh["cache_reset"], first)    # session-02 的首个请求 cache_n 0
        self.assertEqual([broken["server_session"][-10:], fresh["server_session"][-10:]], ["session-01", "session-02"])
        # 另一个 Session 对象（哪怕同一秒构造、session 名相同）从头记录
        self.h.warm_cache = True
        d = document(5, "又")
        self.h.translate(d)
        self.assertEqual(self.run_json(d)["sessions"][0]["cache_reset"]["first_cache_n"], 5)

    def test_trace_dirs_and_server_session_layout_are_unchanged(self) -> None:
        doc = document(23)
        self.h.plans = [{2: "oom"}]
        with self.h.session() as session:
            self.h.translate(doc, session)
        root = self.h.run_root(doc)
        self.assertEqual(self.h.trace_dirs, [root / "transport" / "session-01", root / "transport" / "session-02"])
        self.assertEqual([entry["server_session"] for entry in self.run_json(doc)["sessions"]],
                         [f"{session.runtime_root.name}/session-01", f"{session.runtime_root.name}/session-02"])

    def test_resume_continues_from_the_first_unwritten_batch(self) -> None:
        doc = document(23)
        self.h.plans = [{2: KeyboardInterrupt()}]
        with self.assertRaises(KeyboardInterrupt):
            self.h.translate(doc)
        self.assertEqual(self.h.events, ["start:1", "stop:1"])  # 中断也停掉 Strata
        self.assertEqual(len(self.batch_lines(doc)), 1)
        self.assertEqual(self.run_json(doc)["completion"]["state"], "partial")
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

    def test_unexpected_exception_is_recorded_and_stops_strata(self) -> None:
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
        self.assertEqual(row["degrade"]["nodes"][0]["error_kind"], "parse")

    def test_format_error_then_success_logs_the_failed_attempt(self) -> None:
        doc = document(5)
        self.h.plans = [{1: "bad_json"}]
        with self.assertLogs("kototoki.translate", level="WARNING") as logs:
            result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 0)
        (row,) = self.batch_lines(doc)
        (line,) = [r.getMessage() for r in logs.records]
        self.assertEqual(line, f"[translate] batch {row['batch_id']} attempt 1/2 failed (parse): validation: "
                               f"Expecting property name enclosed in double quotes: line 1 column 2 (char 1); "
                               f"seed {SEED}, finish stop, 12 tok, reply 9 char(s)")
        self.assertNotIn("{not json", line)  # 回复正文不进日志

    def test_length_stop_is_a_limit_failure(self) -> None:
        doc = document(5)
        self.h.plans = [{1: "length", 2: "length"}]
        self.h.translate(doc)
        (row,) = self.batch_lines(doc)
        self.assertEqual(row["degrade"]["nodes"][0]["error_kind"], "limit")

    def test_rerun_of_a_complete_run_does_not_start_strata(self) -> None:
        doc = document(12)
        self.assertTrue(self.h.plan(doc).needs_model)
        self.h.translate(doc)
        self.h.events.clear()
        plan = self.h.plan(doc)
        self.assertFalse(plan.needs_model)
        result = translate_document(plan, None)
        self.assertEqual(len(result.translations), 12)
        self.assertEqual(self.h.events, [])

    def test_plan_keys_run_dir_by_ja_srt_recipe_seed_and_names(self) -> None:
        doc = document(3)
        self.h.table = table(("high", "台詞", "台词"))
        plan = self.h.plan(doc)
        names = R.names_sha256([{"source": "台詞", "translation": "台词"}])
        leaf = f"{R.RECIPE_NAME}__s{SEED}__n{names[:12]}"
        self.assertEqual(plan.run_dir, self.h.work_dir / "translate" / f"srt-{doc.source_sha256[:12]}" / leaf)
        self.assertEqual(plan.relative, f"translate/srt-{doc.source_sha256[:12]}/{leaf}")
        self.assertEqual(plan.identity, {"ja_srt_sha256": doc.source_sha256, "recipe_hash": RECIPE_HASH, "seed": SEED,
                                         "names_sha256": names})
        self.assertIs(plan.document, doc)
        self.assertFalse(plan.run_dir.exists())

    def test_editing_the_injected_rows_retranslates_but_other_entries_do_not(self) -> None:
        doc = document(5)
        self.h.table = table(("high", "台詞", "台词"), ("low", "ですね", "呢"))
        self.h.translate(doc)
        before = self.h.plan(doc)
        self.assertFalse(before.needs_model)
        self.h.table = table(("high", "台詞", "台词"), ("low", "ですね", "啊"))  # 只改 low：注入行不变
        self.assertEqual(self.h.plan(doc).run_dir, before.run_dir)
        self.h.table = table(("high", "台詞", "台本"))  # 手改 high 条目
        after = self.h.plan(doc)
        self.assertTrue(after.needs_model)
        self.assertNotEqual(after.identity["names_sha256"], before.identity["names_sha256"])
        self.assertEqual(after.run_dir.parent, before.run_dir.parent)
        self.h.requests.clear()
        self.h.translate(doc)
        self.assertTrue(self.h.requests[0]["messages"][0]["content"].endswith("台詞 → 台本"))
        self.assertTrue(before.run_dir.is_dir())

    def test_only_high_confidence_rows_enter_the_translate_identity(self) -> None:
        # 注入规则只在翻译子系统（ADR-0019）：编排测试的伪计划把整张表当不透明身份，这里对真实的 `translate.plan` 断言。
        doc = document(3)
        self.h.table = table(("high", "山田", "山田"), ("medium", "東京", "东京"), ("low", "大阪", "大阪"))
        base = self.h.plan(doc)
        self.assertEqual(base.identity["names_sha256"], R.names_sha256([{"source": "山田", "translation": "山田"}]))
        for edited in (table(("high", "山田", "山田"), ("medium", "東京", "东京都"), ("low", "大阪", "大阪")),
                       table(("high", "山田", "山田"), ("medium", "東京", "东京"), ("low", "大阪", "大坂")),
                       table(("high", "山田", "山田"))):  # 改或删 medium／low 条目
            with self.subTest(entries=edited["entries"]):
                self.h.table = edited
                self.assertEqual((self.h.plan(doc).identity, self.h.plan(doc).run_dir), (base.identity, base.run_dir))
        for edited in (table(("high", "山田", "山田君"), ("medium", "東京", "东京"), ("low", "大阪", "大阪")),
                       table(("high", "山田", "山田"), ("high", "東京", "东京"), ("low", "大阪", "大阪"))):  # 改 high、升为 high
            with self.subTest(entries=edited["entries"]):
                self.h.table = edited
                self.assertNotEqual(self.h.plan(doc).identity["names_sha256"], base.identity["names_sha256"])

    def test_plan_rejects_a_run_recorded_under_another_recipe_hash(self) -> None:
        doc = document(3)
        self.h.translate(doc)
        path = self.h.run_root(doc) / "run.json"
        run = read_json(path)
        run["recipe_hash"] = "f" * 64
        path.write_text(json.dumps(run), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Delete .* to translate"):
            self.h.plan(doc)

    def test_incomplete_batches_under_a_complete_run_json_fail_instead_of_starting_strata(self) -> None:
        doc = document(23)
        self.h.translate(doc)
        (self.h.run_root(doc) / "batches.jsonl").unlink()
        plan = self.h.plan(doc)
        self.assertFalse(plan.needs_model)
        self.h.events.clear()
        with self.assertRaisesRegex(TranslateError, "recorded as complete"):
            translate_document(plan, None)
        self.assertEqual(self.h.events, [])

    def test_oom_restarts_strata_as_a_new_session(self) -> None:
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
        self.assertTrue(run["resumed"])
        self.assertEqual(run["completion"]["restarts_last_call"], 1)

    def test_disconnect_mid_run_restarts_and_continues(self) -> None:
        doc = document(23)
        self.h.plans = [{2: URLError(ConnectionResetError(10054, "connection reset"))}]
        result = self.h.translate(doc)
        self.assertEqual((len(result.translations), result.fallback_count), (23, 0))
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2"])
        first, second = self.run_json(doc)["sessions"]
        self.assertEqual((first["stop_reason"], first["batches_written"], second["batches_written"]), ("server", 1, 2))
        # 断开的那一批只试了一次（传输失败不换 seed 重试），新 session 从它重做。
        evidence = read_json(self.h.run_root(doc) / first["infra_failure"]["evidence"])
        self.assertEqual(len(evidence["request"]["attempts"]), 1)

    def test_infra_failure_gives_up_after_two_restarts(self) -> None:
        doc = document(12)
        self.h.plans = [{1: "oom"}, {1: "oom"}, {1: "oom"}]
        with self.assertRaisesRegex(TranslateError, "after 2 Strata restarts"):
            self.h.translate(doc)
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2", "start:3", "stop:3"])
        run = self.run_json(doc)
        self.assertEqual(len(run["sessions"]), 3)
        self.assertEqual(run["completion"]["state"], "partial")
        self.assertFalse((self.h.run_root(doc) / "batches.jsonl").exists())

    def test_refused_strata_fails_the_rest_of_the_batch_without_retrying(self) -> None:
        def mismatch() -> None:
            raise StrataRefused("Strata run config differs from ADR-0017: drafting 'mtp'")

        a, b = document(5), document(5, "別")
        self.h.start_failures = [mismatch, None, None]
        with self.h.session() as session:
            with self.assertRaisesRegex(TranslateError, "Strata refused.*drafting 'mtp'"):
                self.h.translate(a, session)
            with self.assertRaisesRegex(TranslateError, "unavailable for the rest of this batch: .*drafting 'mtp'"):
                self.h.translate(b, session)
        self.assertEqual(self.h.start_failures, [None, None])  # 没有重试，第二部也没有再启动
        self.assertEqual(self.h.events, [])
        self.assertEqual(self.run_json(a)["sessions"], [])

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

    def test_seed_change_uses_its_own_run(self) -> None:
        doc = document(5)
        self.h.translate(doc)
        first = self.h.plan(doc)
        self.h.config.translate.seed = SEED + 1
        second = self.h.plan(doc)
        self.assertTrue(second.needs_model)
        self.assertEqual(second.run_dir.parent, first.run_dir.parent)
        self.assertTrue(second.run_dir.name.startswith(f"{R.RECIPE_NAME}__s{SEED + 1}__n"))
        self.h.translate(doc)
        self.assertTrue((second.run_dir / "run.json").is_file())
        self.assertTrue(first.run_dir.is_dir())

    def test_vram_poll_timeout_is_an_infrastructure_failure(self) -> None:
        doc = document(5)
        clock = [0.0]

        def low_vram() -> None:
            wait_for_free_vram(14000, 10.0, query=lambda: 9000, sleep=lambda s: clock.__setitem__(0, clock[0] + s),
                               clock=lambda: clock[0])

        self.h.start_failures = [low_vram, low_vram, low_vram]
        with self.assertRaisesRegex(TranslateError, "9000 MiB"):
            self.h.translate(doc)
        run = self.run_json(doc)
        self.assertEqual(run["sessions"], [])
        self.assertEqual(len(run["server_start_failures"]), 3)
        self.assertEqual(self.h.pids, [])

    def test_unstartable_strata_fails_the_rest_of_the_batch_without_waiting(self) -> None:
        def crash() -> None:
            raise InfraFailure("Strata did not become ready within 300 s")

        a, b = document(5), document(5, "別")
        self.h.start_failures = [crash] * 3
        with self.h.session() as session:
            with self.assertRaises(TranslateError):
                self.h.translate(a, session)
            self.assertIn("failed to start 3 times in this batch (start budget exhausted): Strata did not become ready",
                          session.unavailable)  # 由 Session 写，翻译不覆盖
            with self.assertRaisesRegex(TranslateError, "unavailable for the rest of this batch: .*start budget "
                                                        "exhausted.*ready") as caught:
                self.h.translate(b, session)
            self.assertNotIn("refused", str(caught.exception))
        self.assertEqual(self.h.start_failures, [])
        self.assertEqual(self.run_json(b)["server_start_failures"], [])

    def test_start_budget_used_by_an_earlier_film_is_reported_as_exhausted(self) -> None:
        def crash() -> None:
            raise InfraFailure("strata launch exited with 1")

        a, b = document(5), document(5, "別")
        self.h.start_failures = [crash, None, crash, crash]  # a 用掉 1 次额度；b 再失败 2 次即耗尽（整批 3 次）
        with self.h.session() as session:
            self.assertEqual(len(self.h.translate(a, session).translations), 5)
            session.stop()  # 例如 a 之后的影片遇到 OOM 停掉了 Strata
            with self.assertRaises(TranslateError) as caught:
                self.h.translate(b, session)
        message = str(caught.exception)
        self.assertIn("start budget exhausted", message)
        self.assertIn("failed to start 3 times", message)
        self.assertNotIn("refused", message)
        self.assertEqual(len(self.run_json(b)["server_start_failures"]), 2)
        self.assertEqual(self.h.start_failures, [])

    def test_mixed_failures_do_not_mark_strata_unavailable(self) -> None:
        def crash() -> None:
            raise InfraFailure("strata launch exited with 1")

        a, b = document(5), document(5, "別")
        self.h.start_failures = [crash, None, None]
        self.h.plans = [{1: "oom"}, {1: "oom"}]
        with self.h.session() as session:
            with self.assertRaises(TranslateError):
                self.h.translate(a, session)
            self.assertEqual(len(self.h.translate(b, session).translations), 5)

    def test_start_failure_then_success(self) -> None:
        def crash() -> None:
            raise InfraFailure("strata launch exited with 1")

        self.h.start_failures = [crash]
        self.assertEqual(len(self.h.translate(document(5)).translations), 5)

    def test_normal_run_logs_one_progress_line_per_batch(self) -> None:
        doc = document(23)
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            self.h.translate(doc)
        batch_lines = [line for line in logs.output if "[translate] batch " in line]
        self.assertEqual(batch_lines, ["INFO:kototoki.translate.generate:[translate] batch 1/3: 10 cue(s), 12 tok, cache 0",
                                       "INFO:kototoki.translate.generate:[translate] batch 2/3: 10 cue(s), 12 tok, cache 5",
                                       "INFO:kototoki.translate.generate:[translate] batch 3/3: 3 cue(s), 12 tok, cache 5"])
        self.assertTrue(any("session 1 start" in line and "3 of 3 batch(es) pending" in line for line in logs.output))
        self.assertEqual({record.levelname for record in logs.records}, {"INFO"})

    def test_restart_logs_a_warning_and_giving_up_an_error(self) -> None:
        doc = document(12)
        self.h.plans = [{2: "oom"}]
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            self.h.translate(doc)
        warnings = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(len(warnings), 2)
        self.assertTrue(warnings[0].startswith("[translate] batch ") and " attempt 1/2 failed (oom): HTTP 500" in warnings[0],
                        warnings[0])
        self.assertTrue(warnings[1].startswith("[translate] Strata restart 1/2: oom: HTTP 500 (oom)"), warnings[1])
        self.h.plans = [{1: "oom"}, {1: "oom"}, {1: "oom"}]
        with self.assertLogs("kototoki.translate", level="INFO") as logs, self.assertRaises(TranslateError):
            self.h.translate(document(5, "別"))
        self.assertEqual([r.levelname for r in logs.records if r.levelname != "INFO" and " attempt " not in r.getMessage()],
                         ["WARNING", "WARNING", "ERROR"])

    def test_logs_never_contain_cue_text(self) -> None:
        doc = document(23)
        self.h.poison = {doc.cues[3].id}
        self.h.plans = [{14: "oom"}]
        self.h.table = table(("high", "台詞1", "台词一"))
        with self.assertLogs("kototoki.translate", level="INFO") as logs:
            result = self.h.translate(doc)
        self.assertEqual(result.fallback_count, 1)
        text = "\n".join(logs.output)
        self.assertIn("WARNING", text)
        for fragment in ("台詞", "ですね", "译", "台词一"):
            self.assertNotIn(fragment, text)

    def test_http_error_message_omits_the_response_body(self) -> None:
        from kototoki.translate.generate import StepFailed, run_step
        exchange = self.h.root / "exchange"
        exchange.mkdir()
        (exchange / "response.raw").write_text('{"error": "台詞0ですね exceeds the available context"}', encoding="utf-8")

        class Client:
            last_exchange = str(exchange)

            def chat_completion(self, body: dict[str, Any]) -> dict[str, Any]:
                raise HTTPError("http://127.0.0.1:8080/v1/chat/completions", 400, "Bad Request", {}, None)

        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "台詞0ですね"}]
        record: dict[str, Any] = {}
        with self.assertRaises(StepFailed) as caught:
            run_step(Client(), messages, SEED, ["x"], {}, record)
        self.assertEqual(caught.exception.kind, "context")
        self.assertEqual(len(record["attempts"]), 1)  # context 不换 seed 重试
        self.assertNotIn("台詞", str(caught.exception))
        self.assertRegex(str(caught.exception), r"^HTTP 400 \(context\): response body \d+ char\(s\)$")


if __name__ == "__main__":
    unittest.main()
