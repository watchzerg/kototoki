"""翻译子系统伪客户端测试：`plan` 的 run 键、身份与 `needs_model`、正常、按批次续跑、基础设施失败（OOM、中途断开、
起不来）重启即新 session、Strata 拒绝、空场景、`ja.srt`／seed／注入行变化换目录。按条追问、拆分与未翻译见
`test_translate_resolve.py`，Strata 启停与共享 session 本身见 `test_strata.py`。不启动 Strata，不占 GPU。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from urllib.error import HTTPError

from kototoki.artifacts import read_json
from kototoki.srt import format_srt_ms, milliseconds, parse_srt
from kototoki.strata import Session
from kototoki.translate import RECIPE_HASH, TranslateError, TranslatePlan, translate_document
from kototoki.translate import plan as translate_plan
from kototoki.translate import recipes as R
from tests.core.strata_fakes import FakeServer, StrataHarness

SEED = 7
EMPTY_TABLE: dict[str, Any] = {"entries": []}
REL = "S1/ep01.mkv"  # 输入目录内的相对路径：只进 session start 日志行


def closed_http_error(code: int, msg: str) -> HTTPError:
    """伪造的 HTTP 错误：产品的 LocalClient 读完正文即关，这里同样先关；code 与 str 不受影响。"""
    error = HTTPError("http://127.0.0.1:8080/v1/chat/completions", code, msg, {}, None)
    error.close()
    return error


def document(n: int, word: str = "台詞"):
    """每条 1.5 s、相邻停顿 0.5 s，每 10 条之间留 20 s 停顿：dp10-cut 在此恰好切出 10 条一批，续跑与降级测试只关心
    批次机制。切包与邻文规则本身见 `test_translate_recipes`。"""
    def start(i: int) -> float:
        return i * 2.0 + (i // 10) * 20.0
    return parse_srt(format_srt_ms([(milliseconds(start(i)), milliseconds(start(i) + 1.5), f"{word}{i}ですね") for i in range(n)]))


def table(*rows: tuple[str, str, str]) -> dict[str, Any]:
    """(confidence, ja, zh) → 最小的 `name-table.json` 内容（每行一个实体、一个写法）。"""
    return {"entries": [{"entity_ja": ja, "kind": "person", "confidence": c, "zh": zh, "forms": [{"ja": ja, "zh": zh}],
                         "zh_variants": [], "evidence": []} for c, ja, zh in rows]}


class FakeClient:
    """按待译 JSON 回译文（OpenAI chat completions 形状）。`plan` 按本客户端的请求序号注入故障；
    待译 ID 含 `harness.poison` 中任一条时返回非法 JSON（结构失败，用于拆分测试）；`harness.empty`／`harness.drop`
    里的 ID 在剩余次数内回空串／不回（按条未解决，用于追问测试）；待译条数超过 `harness.max_targets` 时按服务报
    超出 context 回 HTTP 400。"""

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
            raise closed_http_error(500, "CUDA error: out of memory")
        if behaviour == "http_other":
            raise closed_http_error(500, "boom")
        if behaviour == "error_field":  # 200 响应里带 error 字段
            return {"error": {"message": "boom"}}
        if behaviour == "oom_and_context":  # 同时命中 OOM 与超出 context 的文本：先判 oom
            raise closed_http_error(500, "CUDA error: out of memory; the request exceeds the available context size")
        user = body["messages"][1]["content"]
        cache_n = 0 if self.server.completions == 1 and not self.server.harness.warm_cache else 5
        base = {"usage": {"prompt_tokens": len(user), "completion_tokens": 12}, "timings": {"cache_n": cache_n}}

        def reply(content: str, finish: str = "stop") -> dict[str, Any]:
            return base | {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}]}
        if behaviour == "bad_json":
            return reply("{not json")
        if behaviour == "dup_key":  # 重复的键来自模型回复，不得进日志
            return reply('{"translations": {"秘密キー": "甲", "秘密キー": "乙"}}')
        if behaviour == "length":
            return reply('{"translations": {', "length")
        target, _ = json.JSONDecoder().raw_decode(user.split("【待译 JSON】\n", 1)[1])
        limit = self.server.harness.max_targets
        if limit is not None and len(target["translations"]) > limit:
            raise closed_http_error(400, "the request exceeds the available context size")
        if self.server.harness.poison & set(target["translations"]):
            return reply("{not json")
        texts = {k: "译" + k + ("\n\n续" if behaviour == "blank_line" else "") for k in target["translations"]}
        for key in list(texts):
            for remaining, value in ((self.server.harness.empty, ""), (self.server.harness.drop, None)):
                if remaining.get(key, 0) > 0:
                    remaining[key] -= 1
                    if value is None:
                        del texts[key]
                    else:
                        texts[key] = value
        if behaviour == "extra":
            texts["unknown-cue"] = "多"
        return reply(json.dumps({"translations": texts}, ensure_ascii=False))


class Harness(StrataHarness):
    def __init__(self, root: Path):
        super().__init__(root)
        self.requests: list[dict[str, Any]] = []
        self.plans: list[dict[int, Any]] = []  # 依次分给每个新客户端
        self.poison: set[str] = set()
        self.empty: dict[str, int] = {}        # cue id → 还要回空串的次数
        self.drop: dict[str, int] = {}         # cue id → 还要漏掉的次数
        self.max_targets: int | None = None
        self.warm_cache = False                # True：服务的首个请求也报 cache_n 5（前缀缓存未清空）
        self.trace_dirs: list[Path] = []       # 依次给每个新客户端的 trace 目录
        self.table: dict[str, Any] = EMPTY_TABLE
        self.config.translate = SimpleNamespace(seed=SEED)

    def session(self) -> Session:
        def client_factory(url: str, *, timeout: float, trace_dir: Path) -> FakeClient:
            self.trace_dirs.append(trace_dir)
            return FakeClient(self.server_at(url), self.plans.pop(0) if self.plans else {})

        return super().session(client_factory)

    work_dir = property(lambda self: self.root / "work/abc")

    def plan(self, doc) -> TranslatePlan:
        return translate_plan(self.work_dir, doc, self.table, self.config)

    def translate(self, doc, session: Session | None = None):
        if session is not None:
            return translate_document(self.plan(doc), session, relative=REL)
        with self.session() as own:
            return translate_document(self.plan(doc), own, relative=REL)

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
        self.assertEqual(result.untranslated_count, 0)
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
        self.assertEqual(result.untranslated_count, 0)
        self.assertEqual([body["seed"] for body in self.h.requests], [SEED, SEED + 1])
        self.assertEqual(self.h.requests[0]["messages"], self.h.requests[1]["messages"])
        (row,) = self.batch_lines(doc)
        self.assertEqual([a["status"] for a in row["request"]["attempts"]], ["failed", "accepted"])

    def test_injected_rows_reach_the_system_message_of_matching_packs_only(self) -> None:
        doc = parse_srt(format_srt_ms([(0, 1000, "セイバー、行くぞ"), (1500, 2500, "はい"), (30000, 31000, "士郎！"),
                                       *[(40000 + i * 2000, 41000 + i * 2000, f"台詞{i}") for i in range(12)]]))
        self.h.table = table(("high", "セイバー", "Saber"), ("medium", "士郎", "士郎"), ("high", "凛", "凛"))
        result = self.h.translate(doc)
        self.assertEqual(len(result.translations), len(doc.cues))
        systems = [body["messages"][0]["content"] for body in self.h.requests]
        self.assertTrue(systems[0].endswith(R.NAMES_HEADER + "セイバー → Saber"))
        self.assertTrue(all("士郎 →" not in text and "凛 →" not in text for text in systems))  # medium 与未出现的不注入
        self.assertEqual(self.batch_lines(doc)[0]["request"]["names_injected"], 1)

    def test_one_strata_session_serves_the_whole_batch(self) -> None:
        a, b = document(12), document(5, "別")
        with self.h.session() as session:
            self.h.translate(a, session)
            self.h.translate(b, session)
        self.assertEqual(self.h.events, ["start:1", "stop:1"])
        self.assertEqual(self.run_json(b)["sessions"][0]["server_session"], self.run_json(a)["sessions"][0]["server_session"])
        self.assertEqual(self.run_json(b)["completion"]["state"], "complete")

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
        with self.assertLogs("kototoki.translate", level="WARNING") as logs:
            result = self.h.translate(doc)
        self.assertTrue(any("truncated 29 byte(s)" in r.getMessage() and "unterminated final line" in r.getMessage()
                            for r in logs.records))
        self.assertEqual(len(result.translations), 23)
        self.assertEqual(len(self.h.requests), 2)
        self.assertEqual([row["index"] for row in self.batch_lines(doc)], [0, 1, 2])
        run = self.run_json(doc)
        self.assertEqual(len(run["sessions"]), 2)
        self.assertTrue(run["resumed"])
        self.assertFalse((self.h.run_root(doc) / "scene.json").read_text(encoding="utf-8").count("tor"))

    def test_rerun_of_a_complete_run_does_not_start_strata(self) -> None:
        doc = document(12)
        self.assertTrue(self.h.plan(doc).needs_model)
        self.h.translate(doc)
        self.h.events.clear()
        plan = self.h.plan(doc)
        self.assertFalse(plan.needs_model)
        result = translate_document(plan, None, relative=REL)
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

    def test_oom_restarts_strata_as_a_new_session(self) -> None:
        doc = document(23)
        self.h.plans = [{2: "oom"}]
        with self.assertLogs("kototoki.translate", level="WARNING") as logs:
            result = self.h.translate(doc)
        self.assertTrue(any(REL in r.getMessage() and "Strata restart 1/2" in r.getMessage() for r in logs.records))
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

    def test_failure_text_is_classified_in_translate_call_sites(self) -> None:
        for behaviour, kind in (("http_other", "server_error"), ("error_field", "server_error"), ("oom_and_context", "oom")):
            with self.subTest(behaviour=behaviour):
                self.setUp()
                doc = document(3)
                self.h.plans = [{1: behaviour}]
                self.h.translate(doc)
                if kind == "oom":  # oom 停 Strata 并重启，失败类别记在 session 里
                    first = self.run_json(doc)["sessions"][0]
                    self.assertEqual((first["stop_reason"], first["infra_failure"]["kind"]), ("oom", "oom"))
                else:  # server_error 换 seed 重试，类别记在尝试记录里
                    first = self.batch_lines(doc)[0]["request"]["attempts"][0]
                    self.assertEqual((first["status"], first["error_kind"]), ("failed", "server_error"))

    def test_context_overflow_is_classified_context_in_attempt_records(self) -> None:
        doc = document(4)
        self.h.max_targets = 2
        self.h.translate(doc)
        nodes = [n for row in self.batch_lines(doc) for n in (row["resolution"]["nodes"] if "resolution" in row else [row])]
        kinds = [a.get("error_kind") for node in nodes for a in node["request"]["attempts"]]
        self.assertIn("context", kinds)

    def test_infra_failure_gives_up_after_two_restarts(self) -> None:
        doc = document(12)
        self.h.plans = [{1: "oom"}, {1: "oom"}, {1: "oom"}]
        with self.assertNoLogs("kototoki.translate", level="ERROR"), \
                self.assertRaisesRegex(TranslateError, "after 2 Strata restarts"):
            self.h.translate(doc)
        self.assertEqual(self.h.events, ["start:1", "stop:1", "start:2", "stop:2", "start:3", "stop:3"])
        run = self.run_json(doc)
        self.assertEqual(len(run["sessions"]), 3)
        self.assertEqual(run["completion"]["state"], "partial")
        self.assertFalse((self.h.run_root(doc) / "batches.jsonl").exists())

    def test_changed_ja_srt_uses_a_new_directory_and_keeps_the_old(self) -> None:
        old, new = document(5), document(5, "変")
        self.h.translate(old)
        self.assertTrue(self.h.plan(new).needs_model)
        self.h.translate(new)
        self.assertNotEqual(self.h.plan(old).run_dir, self.h.plan(new).run_dir)
        self.assertEqual(self.h.plan(new).run_dir.parent.name, f"srt-{new.source_sha256[:12]}")
        self.assertFalse(self.h.plan(old).needs_model)

    def test_replay_skips_duplicate_split_warnings_and_corrupt_jsonl_truncates_with_warning(self) -> None:
        doc = document(10)
        self.h.poison = {doc.cues[3].id}
        self.h.plans = [{5: KeyboardInterrupt()}]
        with self.assertRaises(KeyboardInterrupt):
            self.h.translate(doc)
        with (self.h.run_root(doc) / "nodes.jsonl").open("ab") as stream:
            stream.write(b"{corrupt\n")
        with self.assertLogs("kototoki.translate", level="WARNING") as logs:
            self.h.translate(doc)
        msgs = [r.getMessage() for r in logs.records]
        self.assertTrue(any("truncated 9 byte(s)" in m and "corrupt final JSON line" in m for m in msgs))
        splits = [m for m in msgs if "splitting into" in m]
        # 原批次与 .a 已在首轮记录并回放，不再重复记 splitting；只新拆 .a.b
        self.assertEqual(len(splits), 1)
        self.assertIn(".a.b failed", splits[0])


if __name__ == "__main__":
    unittest.main()
