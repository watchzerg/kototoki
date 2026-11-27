"""批次编排器离线测试：媒体、cue 构建、专名建表、翻译与 Strata session 为假实现（属性 patch），合并用真的，
GPU 阶段由 `fake_worker.py` 子进程顶替。

`JobCase` 也是 full 层端到端测试（`tests/full/test_job_ffmpeg.py`）的接缝：`FAKE_MEDIA = False` 时媒体阶段用真实 ffmpeg。
主流程（单文件发布、内嵌字幕采用）的端到端证明在 full 层；这里只留编排的核心规则：阶段 × 整批、扫描与跳过、
文件级失败隔离、按身份续跑、GPU 锁冲突退出码、内嵌字幕路径选择与回退、不进日志与不导入推理栈。
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import wave

from kototoki import __main__ as cli
from kototoki import artifacts, job, media
from kototoki.config import ConfigError, load
from kototoki.merge import merge as real_merge
from kototoki.procs import ProcessLock
from tests.fake_worker import FAKE_MODELS

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_WORKER = Path(__file__).resolve().parents[1] / "fake_worker.py"
SRT_JA = "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n"
MERGED = "1\n00:00:01,000 --> 00:00:02,000\n你好\nこんにちは\n"  # 伪翻译经真实合并给出的双语字幕
FAKE_SERVER_PID = 12345   # 伪 Strata 的 pid（names 与翻译共用同一个 session）
# 运行日志一行：UTC 墙钟、相对秒、级别、消息。traceback 的续行不匹配。
LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z \[ *\d+\.\ds\] (\w+) +(.*)$")


def fake_cue_payload(cues: int) -> dict:
    """伪 `cues.build_cues` 的 payload：编排只读条数与回填、回退计数。"""
    return {"cues": [{"index": k + 1} for k in range(cues)],
            "time_sources": {"native": 5, "interpolated": 0, "fallback": 0},
            "backfilled_units": [], "fallback_windows": [], "unrendered_chars": 0}


def fake_worker_command(stage: str, jobs_path: Path) -> list[str]:
    return [sys.executable, str(FAKE_WORKER), stage, "--jobs", str(jobs_path)]


class JobCase(unittest.TestCase):
    FAKE_MEDIA = True  # False 时媒体阶段走真实 `media.probe`／`extract`（full 层的端到端测试）

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.input, self.work = self.root / "in", self.root / "work"
        self.input.mkdir()
        self.work_root = artifacts.work_root(self.work, self.input)  # 本目标目录的工作根
        self.toml = self.root / "kototoki.toml"
        self.toml.write_text('[paths]\ninput_dir = "in"\nwork_dir = "work"\n'
                             '[run]\nstable_check_s = 0\nextract_workers = 2\n', encoding="utf-8")
        # 绝不触碰仓库的 `.local/gpu.lock`。
        self.config = replace(load(self.toml), gpu_lock=self.root / "gpu.lock", break_stale_lock=False)
        self.plan_path, self.log_path = self.root / "plan.json", self.root / "fake.log"
        self.plan({})
        self.enterContext(mock.patch.dict(os.environ, {
            "KOTOTOKI_FAKE_PLAN": str(self.plan_path), "KOTOTOKI_FAKE_LOG": str(self.log_path)}))

        # 媒体、cue 构建：假实现，并记录调用。
        self.probed: list[str] = []
        self.extracted: list[str] = []
        self.subtitles: dict[str, tuple[dict, ...]] = {}   # rel → 伪 probe 给出的字幕流清单
        self.subtitle_text: dict[str, object] = {}         # rel → 伪抽轨给出的 SRT 文本，或要抛的异常
        self.subtitle_extracted: list[str] = []
        if self.FAKE_MEDIA:
            self.enterContext(mock.patch("kototoki.job.media.probe", side_effect=self._probe))
            self.enterContext(mock.patch("kototoki.job.media.ffmpeg_version", return_value="n0.0-fake"))
            self.enterContext(mock.patch("kototoki.job.media.extract", side_effect=self._extract))
            self.enterContext(mock.patch("kototoki.job.media.extract_subtitle", side_effect=self._extract_subtitle))
        self.enterContext(mock.patch("kototoki.job.cues.build_cues", side_effect=self._build_cues))
        self.enterContext(mock.patch("kototoki.job.gpu.verify_models", return_value=FAKE_MODELS))

        # 假 Strata 共享 session（属性 patch `kototoki.strata.Session`）：构造不启动，第一次
        # `ensure_started` 才"启动"（记 session_enter、回调 pid），`stop`／退出上下文记 session_exit。
        self.calls: list[str] = []
        case = self

        class StrataSession:
            def __init__(self, config, on_server_pid):
                self.on_server_pid = on_server_pid
                self.server = None
                self.unavailable: str | None = None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.stop()
                return False

            def ensure_started(self):
                if self.server is None:
                    case.calls.append("session_enter")
                    self.on_server_pid(FAKE_SERVER_PID)
                    self.server = types.SimpleNamespace(url="http://127.0.0.1:8080")
                return self.server

            def stop(self):
                if self.server is not None:
                    self.server = None
                    case.calls.append("session_exit")
                    self.on_server_pid(None)

        self.enterContext(mock.patch("kototoki.strata.Session", StrataSession))

        # 伪翻译：属性 patch `translate.plan` 与 `translate.translate_document`（阶段计划经延迟导入取同一模块对象）。
        # 合并用真的 `merge.merge`，只包一层记调用。
        self.translate_snapshots: list[dict] = []
        # (work id, 表 SHA)：伪 run 已完成，再计划即 needs_model=False；表一变即另起 run
        self.translate_done: set[tuple[str, str]] = set()
        self.enterContext(mock.patch("kototoki.translate.plan", self._translate_plan))
        self.enterContext(mock.patch("kototoki.translate.translate_document", self._translate_document))
        self.enterContext(mock.patch("kototoki.merge.merge", self._merge))

        # 伪建表：属性 patch `names.build_document`，按 `name_entries` 给表，在共享 session 上"请求模型"；没有发布期替换
        # （ADR-0029「专名注入」）。建表配方 hash 钉成固定值，names 身份的断言不随真实配方变化。
        self.name_entries: list[dict] = []          # 伪建表给出的条目；默认空表
        self.names_snapshots: list[dict] = []
        self.enterContext(mock.patch("kototoki.names.build_document", self._build_document))
        self.enterContext(mock.patch("kototoki.names.recipes.BUILD_RECIPE_HASH", "d" * 64))

    # --- 假实现 -------------------------------------------------------------------------------

    def _rel(self, path: Path) -> str:
        return Path(path).relative_to(self.input).as_posix()

    def _probe(self, path: Path, config) -> media.Probe:
        self.probed.append(self._rel(path))
        track = media.AudioTrack(index=0, codec_name="aac", channels=2, channel_layout="stereo", sample_rate=48000,
                                 language="jpn", default=True, comment=False, start_time=0.0, duration=10.0)
        return media.Probe(
            ffprobe={"streams": [{"index": 0, "codec_name": "aac"}], "format": {"duration": "10"}},
            audio=track, audio_tracks=(track,), has_video=True, duration_s=10.0, duration_source="stream.duration",
            container_start_time=0.0, subtitles=self.subtitles.get(self._rel(path), ()), warnings=())

    def _extract_subtitle(self, path: Path, index: int, ffmpeg: Path) -> str:
        rel = self._rel(path)
        self.subtitle_extracted.append(rel)
        text = self.subtitle_text.get(rel, SRT_JA)
        if isinstance(text, Exception):
            raise text
        return text

    def _extract(self, path: Path, work_dir: Path, probe: media.Probe, config) -> media.Extract:
        rel = self._rel(path)
        self.extracted.append(rel)
        wav = Path(work_dir) / artifacts.AUDIO_16K
        pcm = hashlib.sha256(rel.encode()).digest()  # 每个文件不同的 16 个样本；伪 worker 从 WAV 重算同一 SHA
        with wave.open(str(wav), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(pcm)
        return media.Extract(
            wav=wav, log=Path(work_dir) / artifacts.EXTRACT_LOG, sample_rate=16000, samples=len(pcm) // 2,
            pcm_sha256=hashlib.sha256(pcm).hexdigest(), decoded_duration_s=10.0, duration_s=10.0, offset_s=0.0,
            pan="", compensation={}, warnings=())

    def _build_cues(self, align, options):
        return fake_cue_payload(1), SRT_JA

    def _build_document(self, work_dir, document, session, seed):
        identifier = Path(work_dir).name
        if document.cues:  # 同真实模块：有 cue 才向共享 session 要模型（可能就在这里启动 Strata）
            if session is None:
                raise AssertionError("a document with cues was built without a session")
            session.ensure_started()
        self.calls.append(f"names:{identifier}")
        self.names_snapshots.append({"session": session is not None, "seed": seed})
        entries = [dict(entry) for entry in self.name_entries] if document.cues else []
        payload = {"schema": "name-table-v2", "prompt_version": "fake", "work_guess": None, "entries": entries,
                   "meta": {"seed": seed, "attempt": 1, "dropped_shape": [], "dropped_honorific": [{"ja": "x"}],
                            "dropped_ja_shape": [], "prompt_tokens": 100, "completion_tokens": 20, "seconds": 1.5},
                   "build": {"status": "ok", "reason": None}}
        return types.SimpleNamespace(payload=payload, attempts=1 if document.cues else 0, seconds=1.5, status="ok")

    @staticmethod
    def table_sha256(table: dict) -> str:
        """伪表身份：整张 `name-table.json` 内容的不透明 hash。哪些条目进翻译身份（只取 `confidence: high`）是翻译子系统的
        规则，由 `tests/core/test_translate.py` 对真实的 `translate.plan` 断言，这里不重写。"""
        return hashlib.sha256(json.dumps(table, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _translate_plan(self, work_dir, document, name_table, config):
        """伪计划：目录键与真实子系统同形；同一张表已翻译过（`translate_done`）或零条目即不需要模型。"""
        name_table["entries"]  # 同真实子系统：表缺 entries 即抛
        table_sha = self.table_sha256(name_table)
        run_dir = (Path(work_dir) / "translate" / f"srt-{document.source_sha256[:12]}"
                   / f"fake__s{config.translate.seed}__n{table_sha[:12]}")
        return types.SimpleNamespace(
            work_dir=Path(work_dir), run_dir=run_dir, document=document, names_sha256=table_sha,
            needs_model=bool(document.cues) and (Path(work_dir).name, table_sha) not in self.translate_done,
            identity={"ja_srt_sha256": document.source_sha256, "recipe_hash": "a" * 64, "seed": config.translate.seed,
                      "names_sha256": table_sha},
            relative=run_dir.relative_to(work_dir).as_posix())

    def _translate_document(self, plan, session, *, relative):
        identifier = plan.work_dir.name
        if plan.needs_model:  # 同真实子系统：要模型才向共享 session 要服务（names 没启动时在这里启动）
            if session is None:
                raise AssertionError("a plan that needs the model was translated without a session")
            session.ensure_started()
        self.calls.append(f"translate:{identifier}")
        gpu_lock = self.config.gpu_lock
        self.translate_snapshots.append({
            "processed": [(e["stage"], e["id"]) for e in self.entries("file")],
            "lock": json.loads(gpu_lock.read_text(encoding="utf-8")) if gpu_lock.is_file() else None,
            "finals": list(self.input.rglob("*.srt")),
            "session": session is not None})
        self.translate_done.add((identifier, plan.names_sha256))
        return types.SimpleNamespace(translations={cue.id: "你好" for cue in plan.document.cues},
                                     untranslated_count=0)

    def _merge(self, document, translations) -> str:
        self.calls.append("merge")
        return real_merge(document, translations)

    # --- 辅助 ---------------------------------------------------------------------------------

    def plan(self, plan: dict) -> None:
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")

    def make_inputs(self, *relatives: str) -> None:
        for rel in relatives:
            path = self.input / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"video {rel}".encode())

    def run_job(self, config=None, *, sleep=None, console=None) -> job.Summary:
        return job.run(config or self.config, worker_command=fake_worker_command,
                       sleep=sleep or (lambda seconds: None), console=console or io.StringIO())

    def entries(self, kind: str | None = None) -> list[dict]:
        if not self.log_path.is_file():
            return []
        found = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        return [e for e in found if kind is None or e["kind"] == kind]

    def launches(self, stage: str | None = None) -> list[dict]:
        return [e for e in self.entries("launch") if stage is None or e["stage"] == stage]

    def work_dir(self, rel: str) -> Path:
        return self.work_root / artifacts.work_id(rel)

    def final(self, rel: str) -> Path:
        return artifacts.final_srt_path(self.input, rel)

    def published(self, rel: str) -> dict:
        return artifacts.read_json(self.work_dir(rel) / artifacts.PUBLISHED)

    @staticmethod
    def ids(*relatives: str) -> list[str]:
        return [artifacts.work_id(rel) for rel in relatives]

    def failure(self, rel: str) -> dict:
        return artifacts.read_json(self.work_dir(rel) / artifacts.FAILURE)


FOUR = ("f1.mkv", "f2.mkv", "f3.mkv", "f4.mkv")


class ScanTests(JobCase):
    def test_scan_filters_sorts_and_publishes_next_to_source(self) -> None:
        rels = ["b.mkv", "A.MP4", "S1/ep01.mkv", "S1/ep02.flac"]  # 音频扩展名同样是输入
        others = ["notes.txt", "S1/readme.md"]
        self.make_inputs(*rels, *others)
        summary = self.run_job()
        self.assertEqual(summary.total, 4)
        self.assertEqual(summary.published, ["A.MP4", "S1/ep01.mkv", "S1/ep02.flac", "b.mkv"])
        self.assertEqual(summary.exit_code, 0)
        self.assertEqual(self.launches("vad")[0]["ids"], self.ids("A.MP4", "S1/ep01.mkv", "S1/ep02.flac", "b.mkv"))
        self.assertEqual(self.final("S1/ep01.mkv"), self.input / "S1" / "ep01.ja-zh.srt")
        self.assertEqual(self.final("S1/ep01.mkv").read_text(encoding="utf-8"), MERGED)
        # 目标目录里只多出每个输入旁的双语字幕：没有 ja／zh 单语字幕、没有工作目录
        written = {p.relative_to(self.input).as_posix() for p in self.input.rglob("*")} - set(rels) - set(others)
        self.assertEqual(written, {"S1", "A.ja-zh.srt", "S1/ep01.ja-zh.srt", "S1/ep02.ja-zh.srt", "b.ja-zh.srt"})
        index = artifacts.read_json(self.work_root / artifacts.INDEX)
        self.assertEqual(index, {artifacts.work_id(r): r for r in rels})
        for rel in rels:
            self.assertTrue(self.work_dir(rel).is_dir())
            self.assertEqual((self.work_dir(rel) / "ja.srt").read_text(encoding="utf-8"), SRT_JA)  # 日文字幕留在工作目录

    def test_same_stem_in_one_directory_fails_the_later_file(self) -> None:
        # a.mkv 与 a.mp4 会写到同一份双语字幕；不同目录的同名文件互不影响
        self.make_inputs("a.mkv", "a.mp4", "S1/a.mkv")
        summary = self.run_job()
        self.assertEqual(summary.failed, {"a.mp4": "scan"})
        self.assertEqual((summary.published, summary.exit_code), (["S1/a.mkv", "a.mkv"], 1))
        self.assertNotIn("a.mp4", self.probed)
        failure = self.failure("a.mp4")
        self.assertEqual((failure["stage"], failure["error_type"]), ("scan", "FinalPathCollision"))
        self.assertIn("'a.mkv'", failure["message"])
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"), MERGED)

    def test_size_sampling_decides_stability_not_mtime(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        config = replace(self.config, run=replace(self.config.run, stable_check_s=5.0))
        slept: list[float] = []

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            with (self.input / "b.mkv").open("ab") as stream:
                stream.write(b"more")                                   # 大小变了：写入中
            os.utime(self.input / "c.mkv", (1_000_000, 1_000_000))      # 只有 mtime 变：仍稳定

        summary = self.run_job(config, sleep=sleep)
        self.assertEqual(slept, [5.0])
        self.assertEqual((summary.total, summary.unstable), (3, ["b.mkv"]))
        self.assertEqual(summary.published, ["a.mkv", "c.mkv"])
        self.assertNotIn("b.mkv", self.probed)
        self.assertNotIn(self.ids("b.mkv")[0], artifacts.read_json(self.work_root / artifacts.INDEX))

    def test_existing_subtitle_skips_the_file_before_any_work(self) -> None:
        # 源文件旁已有同名双语字幕（不论来源）：扫描即跳过，不登记工作目录、不 probe、不覆盖
        self.make_inputs("a.mkv", "b.mkv")
        user = self.final("a.mkv")
        user.write_text("user subtitle\n", encoding="utf-8")
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.existing, summary.published, summary.exit_code), (["a.mkv"], ["b.mkv"], 0))
        self.assertEqual(self.probed, ["b.mkv"])
        self.assertEqual(self.launches("vad")[0]["ids"], self.ids("b.mkv"))
        self.assertEqual(user.read_text(encoding="utf-8"), "user subtitle\n")
        self.assertFalse(self.work_dir("a.mkv").exists())
        self.assertEqual(artifacts.read_json(self.work_root / artifacts.INDEX), dict(zip(self.ids("b.mkv"), ["b.mkv"])))
        self.assertIn("[scan] a.mkv: a.ja-zh.srt exists, skipped", console.getvalue())


class StageTests(JobCase):
    def test_stages_run_whole_batch_in_order_then_translate_then_publish(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        summary = self.run_job()
        self.assertEqual(len(summary.published), 3)
        self.assertEqual([(e["stage"], e["ids"]) for e in self.launches()],
                         [(stage, self.ids("a.mkv", "b.mkv", "c.mkv")) for stage in ("vad", "asr", "align")])
        stages = [e["stage"] for e in self.entries("file")]
        self.assertEqual(stages, ["vad"] * 3 + ["asr"] * 3 + ["align"] * 3)
        ids = self.ids("a.mkv", "b.mkv", "c.mkv")
        # 共享 Strata session：names 第一部启动，两阶段之间不停，翻译完才停
        self.assertEqual(self.calls, ["session_enter", *[f"names:{i}" for i in ids], *[f"translate:{i}" for i in ids],
                                      "session_exit"] + ["merge"] * 3)
        for snapshot in self.translate_snapshots:  # 翻译开始时 9 个 GPU 步骤已完成、尚无最终文件
            self.assertEqual(len(snapshot["processed"]), 9)
            self.assertEqual(snapshot["finals"], [])


class IsolationTests(JobCase):
    def test_crash_isolated_and_worker_restarts_for_later_files(self) -> None:
        self.make_inputs(*FOUR)
        self.plan({"asr": {"f2.mkv": "crash"}})
        summary = self.run_job()
        self.assertEqual(summary.failed, {"f2.mkv": "asr"})
        self.assertEqual(summary.exit_code, 1)
        self.assertEqual(summary.published, ["f1.mkv", "f3.mkv", "f4.mkv"])
        self.assertEqual([e["ids"] for e in self.launches("asr")],
                         [self.ids(*FOUR), self.ids("f3.mkv", "f4.mkv")])
        first, second = self.launches("asr")
        self.assertNotEqual(first["pid"], second["pid"])
        self.assertEqual(self.launches("align")[0]["ids"], self.ids("f1.mkv", "f3.mkv", "f4.mkv"))
        failure = self.failure("f2.mkv")
        self.assertEqual((failure["stage"], failure["error_type"]), ("asr", "WorkerCrashed"))
        self.assertFalse(self.final("f2.mkv").exists())

    def test_startup_crash_fails_batch_without_restart(self) -> None:
        self.make_inputs(*FOUR)
        self.plan({"asr": {"__startup__": "crash"}})
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual(summary.failed, dict.fromkeys(FOUR, "asr"))
        self.assertEqual((summary.published, summary.exit_code), ([], 1))
        self.assertEqual([e["ids"] for e in self.launches("asr")], [self.ids(*FOUR)])
        self.assertEqual(self.launches("align"), [])
        self.assertNotIn("[vad] started", console.getvalue())
        for rel in FOUR:
            failure = self.failure(rel)
            self.assertEqual((failure["stage"], failure["error_type"]), ("asr", "WorkerCrashed"))
            self.assertIn("exited with code 3", failure["message"])
            self.assertFalse(self.final(rel).exists())

    def test_no_speech_publishes_empty_subtitle_and_skips_later_stages(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.plan({"vad": {"b.mkv": "empty"}})
        summary = self.run_job()
        self.assertEqual(summary.no_speech, ["b.mkv"])
        self.assertEqual(summary.published, ["a.mkv", "b.mkv", "c.mkv"])
        for stage in ("asr", "align"):
            self.assertEqual(self.launches(stage)[0]["ids"], self.ids("a.mkv", "c.mkv"))
        self.assertNotIn(f"translate:{self.ids('b.mkv')[0]}", self.calls)
        self.assertEqual(len([c for c in self.calls if c.startswith("translate:")]), 2)
        self.assertEqual(self.final("b.mkv").stat().st_size, 0)
        self.assertEqual(self.published("b.mkv")["sha256"], hashlib.sha256(b"").hexdigest())

        launches = len(self.launches())  # 重跑：无语音文件的空字幕同样算已存在
        again = self.run_job()
        self.assertEqual((again.existing, again.published), (["a.mkv", "b.mkv", "c.mkv"], []))
        self.assertEqual(len(self.launches()), launches)

    def test_non_json_stdout_forwarded_to_stderr(self) -> None:
        # stdout 的非 JSON／非 dict 行与无换行尾行按 `[stdout] ` 转发到 stderr 日志，空行忽略，后续事件仍解析且不误计告警。
        self.make_inputs("a.mkv")
        self.plan({"vad": {"a.mkv": "empty"}})
        script = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import fake_worker\n"
            "out = sys.stdout.buffer\n"
            "out.write(b'2026-10-18 12:00:00Z [    1.0s] WARNING  from stdout\\n   \\n\\n[1, 2]\\n\\xff bad utf8\\n')\n"
            "out.flush()\n"
            "code = fake_worker.main(['fake_worker.py', sys.argv[2], '--jobs', sys.argv[3]])\n"
            "out.write(b'trailing no newline')\n"
            "out.flush()\n"
            "sys.exit(code)\n"
        )
        console = io.StringIO()
        summary = job.run(
            self.config,
            worker_command=lambda stage, jobs: [sys.executable, "-c", script, str(FAKE_WORKER.parent), stage, str(jobs)],
            sleep=lambda _: None,
            console=console,
        )
        self.assertEqual((summary.published, summary.failed), (["a.mkv"], {}))
        self.assertIn("[vad] done a.mkv: windows=1", console.getvalue())
        self.assertNotIn("warning/error line(s)", console.getvalue())
        (stderr_log,) = self.work_root.glob("run-*-vad.stderr.log")
        raw = stderr_log.read_bytes()
        header, rest = raw.split(b"\n", 1)
        self.assertRegex(header.decode("utf-8"),
                         r"^--- \[vad\] launch pid=\d+ utc=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z files=1 ---$")
        self.assertEqual(
            rest,
            b"[stdout] 2026-10-18 12:00:00Z [    1.0s] WARNING  from stdout\n"
            b"[stdout] [1, 2]\n"
            b"[stdout] \xff bad utf8\n"
            b"[stdout] trailing no newline\n",
        )
        self.assertEqual(job._count_stderr_problems(raw), 0)


class ResumeTests(JobCase):
    def test_resume_after_interruption_only_reruns_missing_stage(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.plan({"align": {"a.mkv": "crash"}})
        first = self.run_job()
        self.assertEqual((first.failed, first.published), ({"a.mkv": "align"}, ["b.mkv"]))
        self.assertTrue((self.work_dir("a.mkv") / artifacts.FAILURE).is_file())
        self.assertFalse((self.work_dir("a.mkv") / artifacts.ALIGN).exists())
        seen = len(self.launches())

        self.plan({})
        second = self.run_job()
        self.assertEqual((second.failed, second.published, second.existing), ({}, ["a.mkv"], ["b.mkv"]))
        later = self.launches()[seen:]
        self.assertEqual([(e["stage"], e["ids"]) for e in later], [("align", self.ids("a.mkv"))])
        self.assertFalse((self.work_dir("a.mkv") / artifacts.FAILURE).exists())
        self.assertTrue(self.final("a.mkv").is_file())

    def test_deleted_subtitle_republishes_from_completed_run_without_gpu(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        self.assertEqual(self.translate_snapshots[-1]["session"], True)
        for rel in ("a.mkv", "b.mkv"):
            self.final(rel).unlink()  # 用户删掉字幕：产物全当前，翻译只读回已完成的 run 再发布
        self.calls.clear()
        self.translate_snapshots.clear()
        extracted, launches = len(self.extracted), len(self.launches())
        self.config.gpu_lock.unlink(missing_ok=True)

        summary = self.run_job()
        self.assertEqual((summary.published, summary.existing, summary.failed), (["a.mkv", "b.mkv"], [], {}))
        self.assertEqual((len(self.extracted), len(self.launches())), (extracted, launches))
        self.assertEqual(self.calls, [f"translate:{i}" for i in self.ids("a.mkv", "b.mkv")] + ["merge"] * 2)
        self.assertNotIn("session_enter", self.calls)  # 两阶段都不需要模型：Strata 不启动
        for snapshot in self.translate_snapshots:
            self.assertIsNone(snapshot["lock"])  # 未取 GPU 锁
            self.assertFalse(snapshot["session"])
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"), MERGED)


class LockTests(JobCase):
    def test_gpu_lock_conflict_keeps_cpu_artifacts(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        text = json.dumps({"pid": os.getpid(), "pid_created": None})  # 持有者存活的 GPU 锁
        self.config.gpu_lock.write_text(text, encoding="utf-8")
        with self.assertRaises(job.GpuLocked):
            self.run_job()
        err = io.StringIO()
        with mock.patch("kototoki.__main__.load", return_value=self.config), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = cli.main([str(self.toml)])
        self.assertEqual(code, job.EXIT_GPU_LOCKED)
        self.assertIn("GPU locked", err.getvalue())
        for rel in ("a.mkv", "b.mkv"):
            self.assertTrue((self.work_dir(rel) / artifacts.PROBE).is_file())
            self.assertTrue((self.work_dir(rel) / artifacts.AUDIO_16K).is_file())
        self.assertEqual(list(self.work.rglob(artifacts.FAILURE)), [])  # 不写逐文件 failure.json
        self.assertEqual(self.launches(), [])
        self.assertEqual(self.config.gpu_lock.read_text(encoding="utf-8"), text)
        self.assertFalse((self.work_root / artifacts.LOCK).exists())  # 工作根锁已释放


GREETING = {"entity_ja": "こんにちは", "kind": "other", "confidence": "high", "zh": "您好",
            "forms": [{"ja": "こんにちは", "zh": "您好"}], "zh_variants": ["你好"], "evidence": [1]}
TOKYO = {"entity_ja": "東京", "kind": "place", "confidence": "medium", "zh": "东京",
         "forms": [{"ja": "東京", "zh": "东京"}], "zh_variants": [], "evidence": [1]}


class NamesTests(JobCase):
    def test_changed_table_identity_retranslates_on_the_session_without_rebuilding(self) -> None:
        # 哪些条目改动会改变翻译身份（只有 `confidence: high`）见 test_translate.py；这里只看编排：翻译计划说表身份变了
        # → 需要模型 → 用共享 session 重译，表仍当前、不重建。
        self.make_inputs("a.mkv", "b.mkv")
        self.name_entries = [GREETING, TOKYO]
        self.run_job()
        path = self.work_dir("a.mkv") / artifacts.NAME_TABLE
        table = artifacts.read_json(path)
        table["entries"] = [dict(GREETING, forms=[{"ja": "こんにちは", "zh": "嗨"}]), TOKYO]  # 用户校对条目
        artifacts.atomic_write_json(path, table)
        self.final("a.mkv").unlink()  # 要重做就删掉字幕（ADR-0007「发布」）
        self.calls.clear()
        self.names_snapshots.clear()
        self.translate_snapshots.clear()
        launches = len(self.launches())
        self.config.gpu_lock.unlink(missing_ok=True)

        summary = self.run_job()
        self.assertEqual((summary.published, summary.existing), (["a.mkv"], ["b.mkv"]))
        self.assertEqual(len(self.launches()), launches)
        # 表仍当前：不建表；表身份变了：翻译需要模型，起 Strata 重译 a。
        self.assertEqual(self.calls, ["session_enter", f"translate:{self.ids('a.mkv')[0]}", "session_exit", "merge"])
        self.assertEqual(self.names_snapshots, [])
        (snapshot,) = self.translate_snapshots
        self.assertEqual((snapshot["session"], snapshot["lock"]["server_pid"]), (True, FAKE_SERVER_PID))
        sources = self.published("a.mkv")["sources"]
        self.assertEqual(sources["translate"]["names_sha256"], self.table_sha256(table))
        self.assertEqual(artifacts.read_json(path)["entries"], table["entries"])  # 手改的表不被重建覆盖


JPN_SRT_TRACK = ({"index": 2, "codec_name": "subrip", "language": "jpn", "default": True, "forced": False},)


class EmbeddedSubtitleTests(JobCase):
    """内嵌日文字幕路径的选择（ADR-0024）：开关关掉走 STT；字幕轨不可用回退 STT。采用路径的端到端见 full 层。"""

    def with_track(self, rel: str, text: object) -> None:
        self.subtitles[rel] = JPN_SRT_TRACK
        self.subtitle_text[rel] = text

    def test_switch_off_goes_through_speech_recognition(self) -> None:
        self.make_inputs("a.mkv")
        self.with_track("a.mkv", SRT_JA)
        config = replace(self.config, input=replace(self.config.input, use_embedded_subtitles=False))
        summary = self.run_job(config)
        self.assertEqual((summary.published, summary.embedded), (["a.mkv"], []))
        self.assertEqual((self.extracted, self.subtitle_extracted), (["a.mkv"], []))
        self.assertEqual(len(self.launches()), 3)
        self.assertFalse((self.work_dir("a.mkv") / artifacts.JA_EMBEDDED).exists())

    def test_unusable_track_falls_back_to_speech_recognition_with_a_warning(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.with_track("a.mkv", media.MediaError("ffmpeg subtitle extraction failed (1): boom\nmore"))
        self.with_track("b.mkv", "1\n00:00:01,000 --> 00:00:02,000\n<i></i>\n")  # 清洗后零条目
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.embedded, summary.failed), (["a.mkv", "b.mkv"], [], {}))
        self.assertEqual(sorted(self.extracted), ["a.mkv", "b.mkv"])
        self.assertEqual(self.launches("vad")[0]["ids"], self.ids("a.mkv", "b.mkv"))
        warnings = sorted(m[2] for m in map(LOG_LINE.match, console.getvalue().splitlines()) if m and m[1] == "WARNING")
        self.assertEqual(warnings, [
            "[extract] a.mkv: Embedded subtitle stream 2 is unusable (MediaError: ffmpeg subtitle extraction failed "
            "(1): boom); falling back to speech recognition",
            "[extract] b.mkv: Embedded subtitle stream 2 is unusable (no usable cue among 1); "
            "falling back to speech recognition"])
        for rel in ("a.mkv", "b.mkv"):
            self.assertFalse((self.work_dir(rel) / artifacts.JA_EMBEDDED).exists())
            self.assertEqual(self.final(rel).read_text(encoding="utf-8"), MERGED)


class InvariantTests(JobCase):
    def test_transcript_translation_and_name_text_never_reach_logs(self) -> None:
        self.make_inputs("a.mkv")
        self.name_entries = [GREETING, TOKYO]
        self.run_job()
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"), MERGED)  # 文本确实走完了整条流水线
        (run_log,) = self.work_root.glob("run-*[0-9]Z.log")
        stderr_logs = sorted(self.work_root.glob("run-*-*.stderr.log"))
        self.assertEqual({path.name.rsplit("-", 1)[1] for path in stderr_logs},
                         {"vad.stderr.log", "asr.stderr.log", "align.stderr.log"})
        texts = [path.read_text(encoding="utf-8") for path in (run_log, *stderr_logs)]
        for secret in ("こんにちは", "你好", "您好", "東京", "东京"):
            for text in texts:
                self.assertNotIn(secret, text)

    def test_job_and_main_import_no_inference_stack(self) -> None:
        # 编排器以普通导入使用的 Strata、专名、翻译与合并模块同样不得带进推理栈或研究代码。
        code = (
            "import sys, kototoki.job, kototoki.__main__, kototoki.names, kototoki.translate\n"
            "banned = {'torch', 'ctranslate2', 'faster_whisper', 'transformers', 'pyannote', 'torchaudio',\n"
            "          'torchcodec', 'research'}\n"
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in banned)\n"
            "print(bad)\n"
            "sys.exit(1 if bad else 0)\n")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def with_paths(self, *, work_dir: Path | None = None, input_dir: Path | None = None):
        paths = replace(self.config.paths, work_dir=work_dir or self.config.paths.work_dir,
                        input_dir=input_dir or self.config.paths.input_dir)
        return replace(self.config, paths=paths)

    def test_check_input_dir_rejects_the_repository_except_local(self) -> None:
        # 双语字幕写在源文件旁：输入目录在仓库内（`.local/` 除外）会让转写进 Git
        (REPO_ROOT / ".local").mkdir(exist_ok=True)
        local = self.enterContext(tempfile.TemporaryDirectory(dir=REPO_ROOT / ".local"))
        cli.check_input_dir(self.with_paths(input_dir=Path(local)))
        for bad in (REPO_ROOT, REPO_ROOT / "tests"):
            with self.subTest(input_dir=bad), self.assertRaisesRegex(ConfigError, "inside the repository"):
                cli.check_input_dir(self.with_paths(input_dir=bad))

    def test_check_work_dir(self) -> None:
        cli.check_work_dir(self.config)
        cli.check_work_dir(self.with_paths(work_dir=REPO_ROOT / ".local" / "work"))
        for bad in (REPO_ROOT / "work", REPO_ROOT, self.input / "work", self.input):
            with self.subTest(work_dir=bad), self.assertRaises(ConfigError):
                cli.check_work_dir(self.with_paths(work_dir=bad))


class RunLogTests(JobCase):
    """编排统一日志出口（`job.run`）：L4 启动/收尾异常进日志、跨进程关联与未知事件回退、退出码 1/2 指针合并。"""

    def run_logs(self) -> list[Path]:
        return sorted(self.work_root.glob("run-*[0-9]Z.log"))

    def warning_lines(self, text: str) -> list[str]:
        return [m[2] for line in text.splitlines() if (m := LOG_LINE.match(line)) and m[1] == "WARNING"]

    def test_uncaught_startup_and_lock_release_errors_reach_run_log(self) -> None:
        # 启动初始化（record_input）在取工作锁后失败：异常进 run-*.log 且释放工作根锁
        with mock.patch("kototoki.job.artifacts.record_input", side_effect=OSError("disk full")), \
                self.assertRaisesRegex(OSError, "disk full"):
            self.run_job()
        self.assertFalse((self.work_root / artifacts.LOCK).exists())
        (first_log,) = self.run_logs()
        first_text = first_log.read_text(encoding="utf-8")
        self.assertIn("ERROR    [run] ABORTED: OSError", first_text)
        self.assertIn("OSError: disk full", first_text)
        self.assertIn("[summary]", first_text)
        first_log.unlink()

        # 收尾释放锁（GPU 锁与工作根锁）抛错：均记入 run-*.log，且 GPU 锁释放失败时工作根锁仍继续释放
        self.make_inputs("a.mkv")
        real_release = ProcessLock.release

        def flaky_release(lock: ProcessLock) -> None:
            real_release(lock)
            if lock.kind == "GPU lock":
                raise OSError("gpu lock unlink boom")
            if lock.kind == "work directory lock":
                raise OSError("work lock unlink boom")

        with mock.patch("kototoki.job._gpu_stages", side_effect=RuntimeError("gpu boom")), \
                mock.patch.object(ProcessLock, "release", flaky_release), \
                self.assertRaisesRegex(OSError, "work lock unlink boom"):
            self.run_job()
        self.assertFalse((self.work_root / artifacts.LOCK).exists())
        (second_log,) = self.run_logs()
        second_text = second_log.read_text(encoding="utf-8")
        self.assertIn("ERROR    [run] ABORTED: RuntimeError", second_text)
        self.assertIn("ERROR    [run] ABORTED: OSError", second_text)
        self.assertIn("gpu lock unlink boom", second_text)
        self.assertIn("work lock unlink boom", second_text)

    def test_cross_process_correlation_and_unknown_event_id_fallback(self) -> None:
        # 未知进度事件 id 回退保留原 id；worker 启动 pid 与文件数、重启分隔行及 work_id 双向可关联
        self.make_inputs("a.mkv", "b.mkv")
        self.plan({"asr": {"a.mkv": "crash"}})
        # 在 vad 阶段注入一条未知 id 进度事件，其余阶段走 fake_worker（asr 含一次重启）
        inject = (
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import fake_worker\n"
            "if sys.argv[2] == 'vad':\n"
            "    sys.stdout.buffer.write(json.dumps({'event': 'done', 'id': 'ghost-id', 'windows': 7}).encode() + b'\\n')\n"
            "    sys.stdout.buffer.flush()\n"
            "sys.exit(fake_worker.main(['fake_worker.py', sys.argv[2], '--jobs', sys.argv[3]]))\n"
        )
        summary = job.run(
            self.config,
            worker_command=lambda stage, jobs: [sys.executable, "-c", inject, str(FAKE_WORKER.parent), stage, str(jobs)],
            sleep=lambda _: None,
            console=io.StringIO(),
        )
        self.assertEqual(summary.failed, {"a.mkv": "asr"})
        self.assertEqual(summary.published, ["b.mkv"])
        (run_log,) = self.run_logs()
        run_text = run_log.read_text(encoding="utf-8")
        a_id, b_id = self.ids("a.mkv", "b.mkv")
        # 未知 id 保留原样、不被丢弃
        self.assertRegex(run_text, r"\[vad\] done .*ghost-id.*windows=7")
        # 进度与失败行带 work_id
        self.assertRegex(run_text, rf"\[vad\] done a\.mkv: .*work_id={a_id}")
        self.assertRegex(run_text, rf"ERROR\s+\[asr\] FAILED a\.mkv \(work_id={a_id}\): WorkerCrashed")
        # 两次 asr 启动的 pid 均同时出现在 run-*.log 与 run-*-asr.stderr.log 的分隔行中
        asr_launches = self.launches("asr")
        self.assertEqual(len(asr_launches), 2)
        (asr_stderr,) = self.work_root.glob("run-*-asr.stderr.log")
        asr_err_text = asr_stderr.read_text(encoding="utf-8")
        for launch in asr_launches:
            pid = launch["pid"]
            self.assertRegex(run_text, rf"\[asr\] worker launched: pid={pid}, {len(launch['ids'])} file\(s\)")
            self.assertTrue(
                any(re.match(rf"^--- \[asr\] launch pid={pid} utc=\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}Z files={len(launch['ids'])} ---$", ln)
                    for ln in asr_err_text.splitlines()),
                f"missing launch separator for pid={pid} in {asr_err_text!r}",
            )

    def test_exit_code_1_and_2_emit_at_most_one_stderr_pointer(self) -> None:
        # vad：退出码 1 且 stderr 无结构化告警（裸崩溃）→ 仍给 1 条 see stderr 指针；
        # asr：退出码 2 且 stderr 有 1 条结构化 ERROR → 合并为唯一 1 条 see stderr 指针，不重复两条。
        self.make_inputs("a.mkv")
        bare_exit_1 = (
            "import json, sys\n"
            "sys.stdout.buffer.write(json.dumps({'event': 'started'}).encode() + b'\\n')\n"
            "sys.stdout.buffer.flush()\n"
            "sys.stderr.write('Traceback (most recent call last):\\nRuntimeError: bare crash\\n')\n"
            "sys.exit(1)\n"
        )
        console1 = io.StringIO()
        summary1 = job.run(
            self.config,
            worker_command=lambda stage, jobs: [sys.executable, "-c", bare_exit_1],
            sleep=lambda _: None,
            console=console1,
        )
        self.assertEqual(summary1.failed, {"a.mkv": "vad"})
        vad_warnings = [w for w in self.warning_lines(console1.getvalue()) if w.startswith("[vad] ")]
        self.assertEqual(len(vad_warnings), 1)
        self.assertRegex(vad_warnings[0], r"worker exited with code 1.*see run-.*-vad\.stderr\.log")

        # 第二次：加入 b.mkv，vad 正常完成，asr 以退出码 2 退出且 stderr 带一条标准格式 ERROR
        self.make_inputs("b.mkv")
        self.plan({})
        exit_2_with_problem = (
            "import json, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import fake_worker\n"
            "if sys.argv[2] == 'asr':\n"
            "    sys.stderr.write('2026-11-27 00:00:00Z [     0.1s] ERROR    [asr] startup failed: RuntimeError\\n')\n"
            "    sys.stderr.flush()\n"
            "    sys.stdout.buffer.write(json.dumps({'event': 'startup_failed', 'error_type': 'RuntimeError'}).encode() + b'\\n')\n"
            "    sys.stdout.buffer.flush()\n"
            "    sys.exit(2)\n"
            "sys.exit(fake_worker.main(['fake_worker.py', sys.argv[2], '--jobs', sys.argv[3]]))\n"
        )
        console2 = io.StringIO()
        summary2 = job.run(
            self.config,
            worker_command=lambda stage, jobs: [sys.executable, "-c", exit_2_with_problem,
                                                str(FAKE_WORKER.parent), stage, str(jobs)],
            sleep=lambda _: None,
            console=console2,
        )
        self.assertEqual(summary2.failed, {"a.mkv": "asr", "b.mkv": "asr"})
        asr_warnings = [w for w in self.warning_lines(console2.getvalue()) if w.startswith("[asr] ")]
        self.assertEqual(len(asr_warnings), 1)
        self.assertRegex(asr_warnings[0], r"code 2.*1 warning/error line\(s\).*see run-.*-asr\.stderr\.log")


if __name__ == "__main__":
    unittest.main()
