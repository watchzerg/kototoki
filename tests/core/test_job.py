"""批次编排器离线测试：媒体、cue 构建、专名建表、翻译与 Strata session 为假实现（属性 patch），合并用真的，
GPU 阶段由 `fake_worker.py` 子进程顶替。

`JobCase` 也是 full 层端到端测试（`tests/full/test_job_ffmpeg.py`）的接缝：`FAKE_MEDIA = False` 时媒体阶段用真实 ffmpeg。
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
import warnings
import wave

from kototoki import __main__ as cli
from kototoki import artifacts, job, media, recipes
from kototoki.config import ConfigError, load
from kototoki.merge import merge as real_merge
from kototoki.names import NamesError
from kototoki.strata import StrataRefused
from tests.fake_worker import FAKE_MODELS

REPO_ROOT = Path(__file__).resolve().parents[2]
FAKE_WORKER = Path(__file__).resolve().parents[1] / "fake_worker.py"
SRT_JA = "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n"
MERGED = "1\n00:00:01,000 --> 00:00:02,000\n你好\nこんにちは\n"  # 伪翻译经真实合并给出的双语字幕
DEAD_PID = 999999999
FAKE_SERVER_PID = 12345   # 伪 Strata 的 pid（names 与翻译共用同一个 session）


def fake_cue_payload(cues: int, *, interpolated: int = 0, fallback: int = 0, fallback_windows: int = 0,
                     unrendered: int = 0) -> dict:
    """伪 `cues.build_cues` 的 payload：编排只读条数与回填、回退计数。"""
    return {"cues": [{"index": k + 1} for k in range(cues)],
            "time_sources": {"native": 5, "interpolated": interpolated, "fallback": fallback},
            "backfilled_units": [], "fallback_windows": list(range(fallback_windows)), "unrendered_chars": unrendered}


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
            "KOTOTOKI_FAKE_PLAN": str(self.plan_path), "KOTOTOKI_FAKE_LOG": str(self.log_path),
            "KOTOTOKI_FAKE_GPU_LOCK": str(self.config.gpu_lock)}))

        # 媒体、cue 构建：假实现，并记录调用。
        self.probed: list[str] = []
        self.extracted: list[str] = []
        self.extract_errors: set[str] = set()
        self.media_warnings: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}  # rel → (probe, extract) 告警
        self.compensation: dict[str, dict] = {}  # rel → 伪 extract 记进 probe.json 的补偿统计
        self.probe_delay_s = 0.0                 # 伪 probe 的耗时，供线程池取消测试
        self.subtitles: dict[str, tuple[dict, ...]] = {}   # rel → 伪 probe 给出的字幕流清单
        self.subtitle_text: dict[str, object] = {}         # rel → 伪抽轨给出的 SRT 文本，或要抛的异常
        self.subtitle_extracted: list[str] = []
        if self.FAKE_MEDIA:
            self.enterContext(mock.patch("kototoki.job.media.probe", side_effect=self._probe))
            self.enterContext(mock.patch("kototoki.job.media.extract", side_effect=self._extract))
            self.enterContext(mock.patch("kototoki.job.media.extract_subtitle", side_effect=self._extract_subtitle))
        self.empty_cues: set[str] = set()  # 相对路径：伪 cue 构建给出零条目 `ja.srt`
        self.enterContext(mock.patch("kototoki.job.cues.build_cues", side_effect=self._build_cues))
        self.enterContext(mock.patch("kototoki.job.gpu.verify_models", return_value=FAKE_MODELS))
        self.enterContext(mock.patch("kototoki.job.contain_children"))  # 不把测试进程放进 Job Object

        # 假 Strata 共享 session（属性 patch `kototoki.strata.Session`）：构造不启动，第一次
        # `ensure_started` 才"启动"（记 session_enter、回调 pid），`stop`／退出上下文记 session_exit。
        self.calls: list[str] = []
        self.session_error: Exception | None = None   # 设置后 ensure_started 抛（Strata 起不来，不置 unavailable）
        self.session_refused: str | None = None       # 设置后 ensure_started 抛 StrataRefused 并置 unavailable
        self.strata_sessions: list = []               # 本次运行构造的共享 session（应恰一个）
        self.interrupt_translate: set[str] = set()    # work id：伪翻译在记下调用后抛 KeyboardInterrupt
        case = self

        class StrataSession:
            def __init__(self, config, on_server_pid):
                case.strata_sessions.append(self)
                self.on_server_pid = on_server_pid
                self.server = None
                self.unavailable: str | None = None
                self.ordinal = 0

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.stop()
                return False

            def ensure_started(self):
                if self.unavailable is not None:
                    raise StrataRefused(f"Strata is unavailable for the rest of this batch: {self.unavailable}")
                if self.server is None:
                    if case.session_refused is not None:
                        self.unavailable = case.session_refused
                        raise StrataRefused(case.session_refused)
                    if case.session_error is not None:
                        raise case.session_error
                    self.ordinal += 1
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
        self.translate_errors: set[str] = set()  # work id
        # (work id, 表 SHA)：伪 run 已完成，再计划即 needs_model=False；表一变即另起 run
        self.translate_done: set[tuple[str, str]] = set()
        self.untranslated = 0
        self.enterContext(mock.patch("kototoki.translate.plan", self._translate_plan))
        self.enterContext(mock.patch("kototoki.translate.translate_document", self._translate_document))
        self.enterContext(mock.patch("kototoki.merge.merge", self._merge))

        # 伪建表：属性 patch `names.build_document`，按 `name_entries` 给表，在共享 session 上"请求模型"；没有发布期替换
        # （ADR-0019）。建表配方 hash 钉成固定值，names 身份的断言不随真实配方变化。
        self.name_entries: list[dict] = []          # 伪建表给出的条目；默认空表
        self.names_status: dict[str, str] = {}      # work id → 伪建表终态（failed／too_long）
        self.names_errors: set[str] = set()         # work id：伪 build_document 抛 NamesError
        self.names_snapshots: list[dict] = []
        self.names_attempts = 1                     # 伪建表成功前的请求次数
        self.planned_tables: list[dict] = []        # 伪 translate.plan 收到的专名表
        self.enterContext(mock.patch("kototoki.names.build_document", self._build_document))
        self.enterContext(mock.patch("kototoki.names.recipes.BUILD_RECIPE_HASH", "d" * 64))

    # --- 假实现 -------------------------------------------------------------------------------

    def _rel(self, path: Path) -> str:
        return Path(path).relative_to(self.input).as_posix()

    def _probe(self, path: Path, config) -> media.Probe:
        self.probed.append(self._rel(path))
        if self.probe_delay_s:
            time.sleep(self.probe_delay_s)
        track = media.AudioTrack(index=0, codec_name="aac", channels=2, channel_layout="stereo", sample_rate=48000,
                                 language="jpn", default=True, comment=False, start_time=0.0, duration=10.0)
        return media.Probe(
            ffprobe={"streams": [{"index": 0, "codec_name": "aac"}], "format": {"duration": "10"}},
            audio=track, audio_tracks=(track,), has_video=True, duration_s=10.0, duration_source="stream.duration",
            container_start_time=0.0, subtitles=self.subtitles.get(self._rel(path), ()),
            warnings=self.media_warnings.get(self._rel(path), ((), ()))[0])

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
        if rel in self.extract_errors:
            raise media.MediaError(f"fake extract failure: {rel}")
        wav = Path(work_dir) / artifacts.AUDIO_16K
        pcm = hashlib.sha256(rel.encode()).digest()  # 每个文件不同的 16 个样本；伪 worker 从 WAV 重算同一 SHA
        with wave.open(str(wav), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(pcm)
        return media.Extract(
            wav=wav, log=Path(work_dir) / artifacts.EXTRACT_LOG, sample_rate=16000, samples=len(pcm) // 2, pcm_sha256=hashlib.sha256(pcm).hexdigest(),
            decoded_duration_s=10.0, duration_s=10.0, offset_s=0.0, pan="",
            compensation=self.compensation.get(rel, {}), warnings=self.media_warnings.get(rel, ((), ()))[1])

    def _build_cues(self, align, options):
        """`empty_cues` 里的文件给零条目 SRT；按 align 身份里的 PCM SHA 认出文件（伪 extract 每个文件不同）。"""
        pcm = align["identity"]["upstream"][artifacts.AUDIO_16K]
        empty = {hashlib.sha256(hashlib.sha256(rel.encode()).digest()).hexdigest() for rel in self.empty_cues}
        return fake_cue_payload(0 if pcm in empty else 1), "" if pcm in empty else SRT_JA

    def _build_document(self, work_dir, document, session, seed):
        identifier = Path(work_dir).name
        if document.cues:  # 同真实模块：有 cue 才向共享 session 要模型（可能就在这里启动 Strata）
            if session is None:
                raise AssertionError("a document with cues was built without a session")
            session.ensure_started()
        self.calls.append(f"names:{identifier}")
        gpu_lock = self.config.gpu_lock
        self.names_snapshots.append({
            "lock": json.loads(gpu_lock.read_text(encoding="utf-8")) if gpu_lock.is_file() else None,
            "session": session is not None, "seed": seed,
            "ja_srt": (Path(work_dir) / "ja.srt").is_file()})
        if identifier in self.names_errors:
            raise NamesError("fake names transport failure")
        status = self.names_status.get(identifier, "ok")
        entries = [dict(entry) for entry in self.name_entries] if status == "ok" and document.cues else []
        payload = {"schema": "name-table-v2", "prompt_version": "fake", "work_guess": None, "entries": entries,
                   "meta": {"seed": seed, "attempt": 1, "dropped_shape": [], "dropped_honorific": [{"ja": "x"}],
                            "dropped_ja_shape": [], "prompt_tokens": 100, "completion_tokens": 20, "seconds": 1.5},
                   "build": {"status": status, "reason": None if status == "ok" else f"fake {status}"}}
        attempts = self.names_attempts if document.cues else 0
        return types.SimpleNamespace(payload=payload, attempts=attempts, seconds=1.5, status=status)

    @staticmethod
    def table_sha256(table: dict) -> str:
        """伪表身份：整张 `name-table.json` 内容的不透明 hash。哪些条目进翻译身份（只取 `confidence: high`）是翻译子系统的
        规则，由 `tests/core/test_translate.py` 对真实的 `translate.plan` 断言，这里不重写。"""
        return hashlib.sha256(json.dumps(table, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _translate_plan(self, work_dir, document, name_table, config):
        """伪计划：目录键与真实子系统同形；同一张表已翻译过（`translate_done`）或零条目即不需要模型。"""
        self.planned_tables.append(name_table)
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
        if identifier in self.interrupt_translate:
            raise KeyboardInterrupt
        if identifier in self.translate_errors:
            raise RuntimeError("fake translate failure")
        self.translate_done.add((identifier, plan.names_sha256))
        return types.SimpleNamespace(translations={cue.id: "你好" for cue in plan.document.cues},
                                     untranslated_count=self.untranslated)

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

    def test_work_dir_registration_failure_fails_that_file_only(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        original = artifacts.register_work_dir

        def register(root, rel):
            if rel == "b.mkv":
                raise ValueError("Work id collides")
            return original(root, rel)

        with mock.patch("kototoki.job.artifacts.register_work_dir", side_effect=register):
            summary = self.run_job()
        self.assertEqual(summary.failed, {"b.mkv": "scan"})
        self.assertEqual((summary.published, summary.exit_code), (["a.mkv", "c.mkv"], 1))
        self.assertNotIn("b.mkv", self.probed)
        self.assertFalse(self.work_dir("b.mkv").exists())
        self.assertFalse((self.work_root / artifacts.LOCK).exists())

    def test_job_object_failure_releases_the_work_lock(self) -> None:
        self.make_inputs("a.mkv")
        with mock.patch("kototoki.job.contain_children", side_effect=OSError(5, "CreateJobObjectW failed")), \
                self.assertRaises(OSError):
            self.run_job()
        self.assertFalse((self.work_root / artifacts.LOCK).exists())
        self.assertEqual(self.probed, [])

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

    def test_stable_files_unit(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        files = [(rel, self.input / rel) for rel in ("a.mkv", "b.mkv")]
        slept: list[float] = []
        self.assertEqual(job.stable_files(files, 0, slept.append), (files, []))
        self.assertEqual(job.stable_files([], 3, slept.append), ([], []))
        self.assertEqual(slept, [])

        def vanish(seconds: float) -> None:
            slept.append(seconds)
            (self.input / "b.mkv").unlink()

        self.assertEqual(job.stable_files(files, 2, vanish), (files[:1], ["b.mkv"]))
        self.assertEqual(slept, [2])


class ExistingSubtitleTests(JobCase):
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

    def test_rerun_after_publish_skips_everything(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        self.probed.clear()
        extracted, launches, calls = len(self.extracted), len(self.launches()), len(self.calls)
        self.config.gpu_lock.unlink(missing_ok=True)

        summary = self.run_job()
        self.assertEqual((summary.existing, summary.published, summary.exit_code), (["a.mkv", "b.mkv"], [], 0))
        self.assertEqual(self.probed, [])  # 已有字幕即不 probe
        self.assertEqual((len(self.extracted), len(self.launches()), len(self.calls)), (extracted, launches, calls))
        self.assertFalse(self.config.gpu_lock.exists())  # 无需 GPU 就不取锁

    def test_subtitle_appearing_during_the_run_is_not_overwritten(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        for rel in ("a.mkv", "b.mkv"):
            self.final(rel).unlink()
        artifacts.write_failure(self.work_dir("a.mkv"), "asr", RuntimeError("stale"))
        inner = self._translate_document

        def write_then_translate(plan, session, *, relative):  # 翻译期间用户（或别的工具）写了 a 的字幕
            self.final("a.mkv").write_text("written meanwhile\n", encoding="utf-8")
            return inner(plan, session, relative=relative)

        self.enterContext(mock.patch("kototoki.translate.translate_document", write_then_translate))
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.existing, summary.published, summary.exit_code), (["a.mkv"], ["b.mkv"], 0))
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"), "written meanwhile\n")
        self.assertEqual(self.final("b.mkv").read_text(encoding="utf-8"), MERGED)
        self.assertFalse((self.work_dir("a.mkv") / artifacts.FAILURE).exists())
        warnings = [m[2] for m in map(LOG_LINE.match, console.getvalue().splitlines()) if m and m[1] == "WARNING"]
        self.assertEqual(warnings, ["[publish] a.mkv: a.ja-zh.srt appeared during the run, not overwritten"])


class WorkRootTests(JobCase):
    def test_work_root_is_keyed_by_input_dir_name_and_path_hash(self) -> None:
        self.make_inputs("a.mkv")
        seen: list[dict] = []
        inner = self._translate_document

        def look_then_translate(plan, session, *, relative):  # 运行中工作根里有锁
            seen.append({"lock": (self.work_root / artifacts.LOCK).is_file(), "work_dir": plan.work_dir})
            return inner(plan, session, relative=relative)

        self.enterContext(mock.patch("kototoki.translate.translate_document", look_then_translate))
        self.run_job()
        digest = hashlib.sha256(os.path.normcase(str(self.input)).encode("utf-8")).hexdigest()[:12]
        self.assertEqual(self.work_root, self.work / f"in-{digest}")
        self.assertEqual(seen, [{"lock": True, "work_dir": self.work_root / self.ids("a.mkv")[0]}])
        self.assertFalse((self.work_root / artifacts.LOCK).exists())  # 结束即释放
        self.assertEqual(artifacts.read_json(self.work_root / artifacts.INPUT_RECORD), {"input_dir": str(self.input)})
        self.assertEqual(artifacts.read_json(self.work_root / artifacts.INDEX), {self.ids("a.mkv")[0]: "a.mkv"})
        self.assertEqual([p.name for p in self.work.iterdir() if p.name != artifacts.CACHE_DIR], [self.work_root.name])

    def test_two_input_dirs_with_the_same_relative_file_get_separate_work_roots(self) -> None:
        first_input, first_root = self.input, self.work_root
        self.make_inputs("a.mkv")
        first = self.run_job()
        self.input = self.root / "elsewhere" / "in"  # 末段名相同、绝对路径不同；伪媒体按 self.input 取相对路径
        self.make_inputs("a.mkv")
        second = self.run_job(replace(self.config, paths=replace(self.config.paths, input_dir=self.input)))
        self.assertEqual((first.published, second.published), (["a.mkv"], ["a.mkv"]))
        second_root = artifacts.work_root(self.work, self.input)
        self.assertNotEqual(second_root, first_root)
        self.assertRegex(second_root.name, r"^in-[0-9a-f]{12}$")
        for root, input_dir in ((first_root, first_input), (second_root, self.input)):
            self.assertTrue((root / self.ids("a.mkv")[0] / artifacts.PUBLISHED).is_file())
            self.assertEqual(artifacts.read_json(root / artifacts.INPUT_RECORD), {"input_dir": str(input_dir)})
            self.assertTrue((input_dir / "a.ja-zh.srt").is_file())
        self.assertEqual(len(self.launches("vad")), 2)  # 另一个目标目录从头跑，不复用前者的产物


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

    def test_child_environment(self) -> None:
        self.make_inputs("a.mkv")
        self.run_job()
        cache = str(self.work / "cache")  # 各目标目录共用
        self.assertEqual(len(self.launches()), 3)
        for launch in self.launches():
            self.assertEqual(launch["env"], {"PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "HF_HOME": cache,
                                             "TORCH_HOME": cache})

    def test_child_environment_silences_progress_bars(self) -> None:
        env = job.child_env(self.config)
        for key, value in {"TQDM_DISABLE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1",
                           "TRANSFORMERS_VERBOSITY": "warning"}.items():
            self.assertEqual(env[key], value)


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

    def test_crash_on_first_file_restarts_for_the_rest(self) -> None:
        self.make_inputs(*FOUR)
        self.plan({"asr": {"f1.mkv": "crash"}})
        summary = self.run_job()
        self.assertEqual(summary.failed, {"f1.mkv": "asr"})
        self.assertEqual([e["ids"] for e in self.launches("asr")], [self.ids(*FOUR), self.ids(*FOUR[1:])])
        self.assertEqual(summary.published, list(FOUR[1:]))

    def test_fatal_error_fails_that_file_and_restarts_after_it(self) -> None:
        self.make_inputs(*FOUR)
        self.plan({"asr": {"f2.mkv": "fatal"}})
        summary = self.run_job()
        self.assertEqual(summary.failed, {"f2.mkv": "asr"})
        self.assertEqual(summary.published, ["f1.mkv", "f3.mkv", "f4.mkv"])
        self.assertEqual([e["ids"] for e in self.launches("asr")],
                         [self.ids(*FOUR), self.ids("f3.mkv", "f4.mkv")])
        self.assertEqual(self.failure("f2.mkv")["error_type"], "FatalWorkerError")

    def test_startup_failure_fails_whole_stage_without_restart_loop(self) -> None:
        self.make_inputs("f1.mkv", "f2.mkv")
        self.plan({"asr": {"f1.mkv": "startup"}})
        summary = self.run_job()
        self.assertEqual(summary.failed, {"f1.mkv": "asr", "f2.mkv": "asr"})
        self.assertEqual(len(self.launches("asr")), 1)
        self.assertEqual(self.launches("align"), [])
        self.assertEqual((summary.published, summary.exit_code), ([], 1))
        self.assertIn("startup failed", self.failure("f2.mkv")["message"])
        self.assertEqual(self.calls, [])

    def test_exit_one_with_a_file_unreported_restarts_for_the_rest(self) -> None:
        # worker 在 run_jobs 之外崩溃（未捕获异常，退出码 1）：缺事件的文件是崩溃文件，其后的文件重启 worker。
        self.make_inputs(*FOUR)
        real_launch = job._launch

        def launch(ctx, stage, batch):
            code, events = real_launch(ctx, stage, batch)
            if stage == "asr" and len(batch) == len(FOUR):  # 第一次 asr：只留 f1 的事件，假装 worker 以 1 退出
                return 1, events[:1]
            return code, events

        with mock.patch("kototoki.job._launch", side_effect=launch):
            summary = self.run_job()
        self.assertEqual(summary.failed, {"f2.mkv": "asr"})
        self.assertEqual(self.failure("f2.mkv")["error_type"], "WorkerCrashed")
        self.assertEqual([e["ids"] for e in self.launches("asr")], [self.ids(*FOUR), self.ids("f3.mkv", "f4.mkv")])

    def test_interrupt_while_reading_worker_output_reaps_the_worker(self) -> None:
        self.make_inputs("a.mkv")
        started: list[subprocess.Popen] = []
        real_popen = subprocess.Popen

        def popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            started.append(process)
            return process

        sleeper = lambda stage, jobs_path: [sys.executable, "-c", "import time; time.sleep(60)"]  # noqa: E731
        with mock.patch("kototoki.job.subprocess.Popen", side_effect=popen), \
                mock.patch("kototoki.job._read_events", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            job.run(self.config, worker_command=sleeper, sleep=lambda seconds: None, console=io.StringIO())
        (process,) = started
        self.assertIsNotNone(process.returncode)  # 已 kill 并 wait，不留孤儿 worker
        self.assertFalse(self.config.gpu_lock.exists())
        self.assertFalse((self.work_root / artifacts.LOCK).exists())

    def test_file_left_unhandled_by_every_executor_fails_at_publish(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        with mock.patch("kototoki.job.translate_batch", return_value={}):  # 翻译执行器漏掉全部文件
            summary = self.run_job()
        self.assertEqual((summary.published, summary.exit_code), ([], 1))
        self.assertEqual(summary.failed, {"a.mkv": "publish", "b.mkv": "publish"})
        failure = self.failure("a.mkv")
        self.assertEqual((failure["stage"], failure["error_type"]), ("publish", "NotPublished"))

    def test_model_check_failure_is_cached_per_stage(self) -> None:
        verify = self.enterContext(mock.patch("kototoki.job.gpu.verify_models",
                                              side_effect=FileNotFoundError("model missing")))
        lookup = job.model_sha_lookup(self.config)
        for _ in range(3):
            with self.assertRaises(FileNotFoundError):
                lookup("vad")
        self.assertEqual(verify.call_count, 1)

    def test_ordinary_failure_excludes_file_from_later_stages(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.plan({"vad": {"b.mkv": "fail"}})
        summary = self.run_job()
        self.assertEqual(summary.failed, {"b.mkv": "vad"})
        self.assertEqual(summary.exit_code, 1)
        self.assertEqual(summary.published, ["a.mkv", "c.mkv"])
        for stage in ("asr", "align"):
            self.assertEqual(self.launches(stage)[0]["ids"], self.ids("a.mkv", "c.mkv"))
        self.assertEqual(len(self.launches("vad")), 1)
        failure = self.failure("b.mkv")
        self.assertEqual((failure["stage"], failure["error_type"]), ("vad", "RuntimeError"))

    def test_extract_media_error_fails_at_extract(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.extract_errors = {"c.mkv"}
        summary = self.run_job()
        self.assertEqual(summary.failed, {"c.mkv": "extract"})
        self.assertEqual(summary.published, ["a.mkv", "b.mkv"])
        self.assertEqual(self.launches("vad")[0]["ids"], self.ids("a.mkv", "b.mkv"))
        failure = self.failure("c.mkv")
        self.assertEqual((failure["stage"], failure["error_type"]), ("extract", "MediaError"))

    def test_interrupt_during_extract_cancels_queued_files(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.probe_delay_s = 0.3  # a 在唯一的线程里跑着，b、c 还在队列里
        config = replace(self.config, run=replace(self.config.run, extract_workers=1))
        with mock.patch("kototoki.job.concurrent.futures.as_completed", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            self.run_job(config)
        self.assertEqual(self.probed, ["a.mkv"])
        self.assertFalse((self.work_root / artifacts.LOCK).exists())
        self.assertEqual(list(self.work.rglob(artifacts.FAILURE)), [])

    def test_leftover_temporary_files_removed_before_extract(self) -> None:
        self.make_inputs("a.mkv")
        work = self.work_dir("a.mkv")
        work.mkdir(parents=True)
        leftovers = [work / ".audio-16k.4242.partial.wav", work / ".audio.4242.partial.mka", work / ".probe.json.4242.1.tmp"]
        for path in leftovers + [work / artifacts.EXTRACT_LOG]:
            path.write_bytes(b"x")
        self.run_job()
        self.assertEqual([p.exists() for p in leftovers], [False] * 3)
        self.assertTrue((work / artifacts.EXTRACT_LOG).is_file())

    def test_translate_failure_isolated_to_that_file(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.translate_errors = set(self.ids("a.mkv"))
        summary = self.run_job()
        self.assertEqual(summary.failed, {"a.mkv": "translate"})
        self.assertEqual(summary.published, ["b.mkv"])
        self.assertFalse(self.final("a.mkv").exists())

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


class LockTests(JobCase):
    def write_lock(self, path: Path, pid: int) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"pid": pid, "pid_created": None})
        path.write_text(text, encoding="utf-8")
        return text

    def run_main(self) -> tuple[int, str]:
        err = io.StringIO()
        with mock.patch("kototoki.__main__.load", return_value=self.config), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            return cli.main([str(self.toml)]), err.getvalue()

    def test_work_lock_conflict(self) -> None:
        self.make_inputs("a.mkv")
        lock = self.work_root / artifacts.LOCK
        text = self.write_lock(lock, os.getpid())
        with self.assertRaises(job.WorkLocked):
            self.run_job()
        code, err = self.run_main()
        self.assertEqual(code, job.EXIT_WORK_LOCKED)
        self.assertIn("work directory locked", err)
        self.assertEqual(lock.read_text(encoding="utf-8"), text)  # 他人的锁不动
        self.assertEqual(self.probed, [])

    def test_gpu_lock_conflict_keeps_cpu_artifacts(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        text = self.write_lock(self.config.gpu_lock, os.getpid())
        with self.assertRaises(job.GpuLocked):
            self.run_job()
        code, err = self.run_main()
        self.assertEqual(code, job.EXIT_GPU_LOCKED)
        self.assertIn("GPU locked", err)
        for rel in ("a.mkv", "b.mkv"):
            self.assertTrue((self.work_dir(rel) / artifacts.PROBE).is_file())
            self.assertTrue((self.work_dir(rel) / artifacts.AUDIO_16K).is_file())
        self.assertEqual(self.launches(), [])
        self.assertEqual(self.config.gpu_lock.read_text(encoding="utf-8"), text)
        self.assertFalse((self.work_root / artifacts.LOCK).exists())  # 工作根锁已释放

    def test_gpu_lock_conflict_at_names_is_process_level(self) -> None:
        # ADR-0025：首个需要 GPU 的阶段是 names（整批都是内嵌字幕文件）时撞锁同样退出码 4，不写逐文件 failure.json。
        self.make_inputs("a.mkv", "b.mkv")
        for rel in ("a.mkv", "b.mkv"):
            self.subtitles[rel] = JPN_SRT_TRACK
            self.subtitle_text[rel] = SRT_EMBEDDED
        text = self.write_lock(self.config.gpu_lock, os.getpid())
        with self.assertRaises(job.GpuLocked):
            self.run_job()
        code, err = self.run_main()
        self.assertEqual(code, job.EXIT_GPU_LOCKED)
        self.assertIn("GPU locked", err)
        self.assertEqual(list(self.work.rglob(artifacts.FAILURE)), [])
        self.assertEqual((self.calls, self.launches()), ([], []))
        for rel in ("a.mkv", "b.mkv"):  # CPU 产物保留，可续跑
            self.assertTrue((self.work_dir(rel) / "ja.srt").is_file())
            self.assertTrue((self.work_dir(rel) / artifacts.JA_EMBEDDED).is_file())
            self.assertFalse(self.final(rel).exists())
        self.assertEqual(self.config.gpu_lock.read_text(encoding="utf-8"), text)
        self.assertFalse((self.work_root / artifacts.LOCK).exists())

    def test_gpu_lock_conflict_at_translate_is_process_level(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.empty_cues = {"b.mkv"}
        self.run_job()
        self.final("a.mkv").unlink()
        self.final("b.mkv").unlink()  # b 零条目：不需要模型，但同批撞锁后也等下一次运行再发布
        self.translate_done.clear()   # a 只有翻译需要模型
        self.calls.clear()
        self.write_lock(self.config.gpu_lock, os.getpid())
        with self.assertRaises(job.GpuLocked):
            self.run_job()
        self.assertEqual(list(self.work.rglob(artifacts.FAILURE)), [])
        self.assertEqual(self.calls, [])
        self.assertFalse(self.final("a.mkv").exists())
        self.assertFalse(self.final("b.mkv").exists())

    def test_stale_gpu_lock_refused_unless_break_requested(self) -> None:
        self.make_inputs("a.mkv")
        text = self.write_lock(self.config.gpu_lock, DEAD_PID)
        with self.assertRaises(job.GpuLocked) as context:
            self.run_job()
        self.assertIn("Stale", str(context.exception))
        self.assertEqual(self.config.gpu_lock.read_text(encoding="utf-8"), text)

        summary = self.run_job(replace(self.config, break_stale_lock=True))
        self.assertEqual(summary.published, ["a.mkv"])
        self.assertEqual(self.launches()[0]["lock"]["replaced_stale_lock"]["pid"], DEAD_PID)
        self.assertFalse(self.config.gpu_lock.exists())

    def test_empty_or_unparseable_lock_is_stale_and_breakable(self) -> None:
        for content, rel in ((b"", "a.mkv"), (b"not json", "b.mkv")):
            with self.subTest(content=content):
                self.make_inputs(rel)  # 新文件要跑 GPU 阶段，取锁失败即 GpuLocked
                self.config.gpu_lock.parent.mkdir(parents=True, exist_ok=True)
                self.config.gpu_lock.write_bytes(content)
                with self.assertRaises(job.GpuLocked) as context:
                    self.run_job()
                self.assertIn("Stale", str(context.exception))
                self.assertIn("KOTOTOKI_BREAK_STALE_LOCK=1", str(context.exception))
                self.assertEqual(self.config.gpu_lock.read_bytes(), content)
                summary = self.run_job(replace(self.config, break_stale_lock=True))
                self.assertEqual(summary.published, [rel])
                self.assertFalse(self.config.gpu_lock.exists())

        (self.work_root / artifacts.LOCK).write_bytes(b"")
        with self.assertRaises(job.WorkLocked):
            self.run_job()
        self.assertEqual(self.run_job(replace(self.config, break_stale_lock=True)).existing, ["a.mkv", "b.mkv"])

    def test_stale_work_lock_refused_unless_break_requested(self) -> None:
        self.make_inputs("a.mkv")
        self.write_lock(self.work_root / artifacts.LOCK, DEAD_PID)
        with self.assertRaises(job.WorkLocked):
            self.run_job()
        self.assertEqual(self.run_job(replace(self.config, break_stale_lock=True)).published, ["a.mkv"])

    def test_gpu_lock_records_pids_and_is_released(self) -> None:
        self.make_inputs("a.mkv")
        self.run_job()
        for launch in self.launches():
            lock = launch["lock"]
            self.assertEqual(lock["pid"], os.getpid())
            self.assertIn(lock["worker_pid"], (launch["pid"], launch["ppid"]))  # venv 启动器时 Popen.pid 是父进程
            self.assertEqual(lock["worker_stage"], launch["stage"])
            self.assertEqual(lock["input_dir"], str(self.input))
        (snapshot,) = self.translate_snapshots
        self.assertEqual(snapshot["lock"]["server_pid"], FAKE_SERVER_PID)
        self.assertIsNone(snapshot["lock"]["worker_pid"])
        self.assertFalse(self.config.gpu_lock.exists())
        self.assertFalse((self.work_root / artifacts.LOCK).exists())

    def test_main_usage_and_config_errors_exit_2(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["a.toml", "b.toml"]), job.EXIT_CONFIG)
            self.assertEqual(cli.main([str(self.root / "missing.toml")]), job.EXIT_CONFIG)


class PublishTests(JobCase):
    def test_bilingual_subtitle_published_with_audit_record(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.untranslated = 1
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.untranslated_cues), (["a.mkv", "b.mkv"], 2))
        for rel in ("a.mkv", "b.mkv"):
            record = self.published(rel)
            self.assertEqual(record["final"], str(self.final(rel)))
            self.assertEqual(record["sha256"], artifacts.sha256_file(self.final(rel)))
            self.assertEqual(record["sources"]["translate_untranslated_cues"], 1)
            self.assertTrue(record["translate_dir"].startswith("translate/srt-"))
            self.assertRegex(record["translate_dir"], rf"/fake__s{self.config.translate.seed}__n[0-9a-f]{{12}}$")
            copy = self.work_dir(rel) / job.PUBLISH_DIR / self.final(rel).name  # 工作目录副本保留
            self.assertEqual(artifacts.sha256_file(copy), record["sha256"])
        self.assertIn("[summary] 2 file(s): 2 published", console.getvalue())

    def test_publish_never_moves_across_directories(self) -> None:
        """回归：工作目录与输入不在同一卷时 `os.replace` 跨卷失败（WinError 17）。
        打桩成"跨目录替换即抛 EXDEV"，发布仍须成功：临时文件建在目标目录内。"""
        self.make_inputs("a.mkv")
        real = artifacts.replace_with_retry

        def same_volume_only(source, target, **kwargs):
            if Path(source).parent != Path(target).parent:
                raise OSError(18, "The system cannot move the file to a different disk drive")
            return real(source, target, **kwargs)

        with mock.patch.object(artifacts, "replace_with_retry", side_effect=same_volume_only):
            summary = self.run_job()
        self.assertEqual((summary.published, summary.failed), (["a.mkv"], {}))
        self.assertEqual(self.published("a.mkv")["sha256"], artifacts.sha256_file(self.final("a.mkv")))
        self.assertEqual([p.name for p in self.input.iterdir() if p.name.endswith(".tmp")], [])

    def test_failed_publish_writes_no_audit_record(self) -> None:
        self.make_inputs("a.mkv")
        self.untranslated = 2  # 汇总的未翻译数在翻译完成时计，发布失败也不漏（batch-run-fixes 06.1）
        real = artifacts.replace_with_retry
        final = self.final("a.mkv")

        def locked_final(source, target, **kwargs):
            if Path(target) == final.resolve():
                raise PermissionError("locked")
            return real(source, target, **kwargs)

        with mock.patch.object(artifacts, "replace_with_retry", side_effect=locked_final):
            summary = self.run_job()
        self.assertEqual((summary.failed, summary.untranslated_cues), ({"a.mkv": "publish"}, 2))
        self.assertFalse(final.exists())
        self.assertFalse((self.work_dir("a.mkv") / artifacts.PUBLISHED).exists())
        self.assertTrue((self.work_dir("a.mkv") / job.PUBLISH_DIR / final.name).is_file())  # 副本可人工恢复

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


    def test_nearly_silent_vad_result_fails_before_asr(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.plan({"vad": {"b.mkv": "quiet"}})
        summary = self.run_job()
        self.assertEqual(summary.failed, {"b.mkv": "vad"})
        self.assertEqual(summary.published, ["a.mkv"])
        for stage in ("asr", "align"):
            self.assertEqual(self.launches(stage)[0]["ids"], self.ids("a.mkv"))
        self.assertEqual(self.failure("b.mkv")["error_type"], "TooLittleSpeech")
        self.assertTrue((self.work_dir("b.mkv") / artifacts.VAD).is_file())

        again = self.run_job()  # 重跑：vad.json 当前，不再跑 vad，仍在 asr 前判失败
        self.assertEqual(again.failed, {"b.mkv": "vad"})
        self.assertEqual([launch["ids"] for launch in self.launches("vad")], [self.ids("a.mkv", "b.mkv")])


class PlanCallTests(JobCase):
    def test_next_stage_once_per_file_and_advance_once_per_stage_run(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.plan({"vad": {"b.mkv": "empty"}})
        with mock.patch.object(job.plan, "next_stage", wraps=job.plan.next_stage) as next_stage,                 mock.patch.object(job.plan, "advance", wraps=job.plan.advance) as advance:
            summary = self.run_job()
            self.assertEqual(len(summary.published), 3)
            self.assertEqual(next_stage.call_count, 3)
            # a、c 各推进 vad／asr／align／cues／names 五次，b 只推进 vad 一次。
            self.assertEqual(advance.call_count, 5 + 5 + 1)
            self.assertEqual(sorted(call.args[0].stage for call in advance.call_args_list),
                             ["align"] * 2 + ["asr"] * 2 + ["cues"] * 2 + ["names"] * 2 + ["vad"] * 3)

            # 删掉 a 的字幕再跑：只有 a 再计划；产物全当前，计划直达 translate，不再推进
            self.final("a.mkv").unlink()
            next_stage.reset_mock()
            advance.reset_mock()
            self.config.gpu_lock.unlink(missing_ok=True)
            again = self.run_job()
            self.assertEqual((again.published, again.existing), (["a.mkv"], ["b.mkv", "c.mkv"]))
            self.assertEqual((next_stage.call_count, advance.call_count), (1, 0))


class TranslatePlanTests(JobCase):
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

    def test_session_failure_only_fails_files_that_need_the_model(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        self.final("a.mkv").unlink()      # a：run 已完成，只需重新发布
        self.final("b.mkv").unlink()
        b = self.ids("b.mkv")[0]
        self.translate_done = {done for done in self.translate_done if done[0] != b}  # b：伪 run 视为未完成，需要模型
        self.session_error = RuntimeError("strata unavailable")
        self.calls.clear()
        summary = self.run_job()
        self.assertEqual(summary.published, ["a.mkv"])
        self.assertEqual(list(summary.failed), ["b.mkv"])
        self.assertEqual(summary.failed["b.mkv"], "translate")
        self.assertEqual(self.calls, [f"translate:{self.ids('a.mkv')[0]}", "merge"])

    def test_zero_cue_documents_never_take_the_gpu_lock_for_translation(self) -> None:
        self.make_inputs("a.mkv")
        self.enterContext(mock.patch("kototoki.job.cues.build_cues", return_value=(fake_cue_payload(0), "")))
        self.run_job()
        self.final("a.mkv").unlink()
        self.calls.clear()
        self.config.gpu_lock.unlink(missing_ok=True)
        summary = self.run_job()
        self.assertEqual(summary.published, ["a.mkv"])
        self.assertEqual(self.calls, [f"translate:{self.ids('a.mkv')[0]}"])  # 零条目：无 session、无 merge
        self.assertIsNone(self.translate_snapshots[-1]["lock"])
        self.assertEqual(self.final("a.mkv").stat().st_size, 0)


GREETING ={"entity_ja": "こんにちは", "kind": "other", "confidence": "high", "zh": "您好",
            "forms": [{"ja": "こんにちは", "zh": "您好"}], "zh_variants": ["你好"], "evidence": [1]}
TOKYO = {"entity_ja": "東京", "kind": "place", "confidence": "medium", "zh": "东京",
         "forms": [{"ja": "東京", "zh": "东京"}], "zh_variants": [], "evidence": [1]}


class NamesTests(JobCase):
    def table(self, rel: str) -> dict:
        return artifacts.read_json(self.work_dir(rel) / artifacts.NAME_TABLE)

    def test_table_built_after_cues_before_translate_on_the_shared_session(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        summary = self.run_job()
        self.assertEqual(summary.published, ["a.mkv", "b.mkv"])
        ids = self.ids("a.mkv", "b.mkv")
        self.assertEqual(self.calls[:3], ["session_enter", *[f"names:{i}" for i in ids]])
        for snapshot in self.names_snapshots:  # 建表时 Strata 已在跑，GPU 锁记着它的 pid
            self.assertTrue(snapshot["ja_srt"])
            self.assertEqual((snapshot["lock"]["server_pid"], snapshot["seed"]),
                             (FAKE_SERVER_PID, self.config.names.seed))
        self.assertEqual(self.translate_snapshots[0]["lock"]["server_pid"], FAKE_SERVER_PID)
        for rel in ("a.mkv", "b.mkv"):
            table = self.table(rel)
            self.assertEqual(table["identity"], {
                "ja_srt_sha256": artifacts.sha256_file(self.work_dir(rel) / "ja.srt"), "recipe_hash": "d" * 64,
                "seed": self.config.names.seed})
            self.assertEqual(table["build"]["status"], "ok")
            sources = self.published(rel)["sources"]
            self.assertEqual(sources["names"], table["identity"])
            self.assertEqual(sources["translate"]["names_sha256"], self.table_sha256(table))

    def test_strata_starts_once_in_names_and_stops_after_translate(self) -> None:
        # ADR-0022：整批一个 Strata session，names 第一部启动，两阶段之间不停，翻译结束才 --stop，之后才放 GPU 锁。
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        self.assertEqual(len(self.strata_sessions), 1)
        self.assertEqual((self.calls.count("session_enter"), self.calls.count("session_exit")), (1, 1))
        self.assertLess(self.calls.index("session_enter"), self.calls.index(f"names:{self.ids('a.mkv')[0]}"))
        self.assertGreater(self.calls.index("session_exit"), self.calls.index(f"translate:{self.ids('b.mkv')[0]}"))
        self.assertFalse(self.config.gpu_lock.exists())

    def test_refused_strata_fails_both_stages_without_starting(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        self.final("b.mkv").unlink()
        b = self.ids("b.mkv")[0]
        self.translate_done = {done for done in self.translate_done if done[0] != b}  # b：表当前，只有翻译要模型
        self.make_inputs("c.mkv")  # c：从头跑，names 就要模型
        self.session_refused = "another Strata launch is serving"
        self.calls.clear()
        summary = self.run_job()
        self.assertEqual(summary.failed, {"c.mkv": "names", "b.mkv": "translate"})
        self.assertEqual(summary.published, [])
        self.assertNotIn("session_enter", self.calls)
        self.assertEqual(len(self.strata_sessions), 2)
        self.assertEqual(self.strata_sessions[-1].unavailable, "another Strata launch is serving")
        self.assertIn("unavailable for the rest of this batch", self.failure("b.mkv")["message"])

    def test_interrupt_during_translate_stops_strata_and_releases_the_locks(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.interrupt_translate = set(self.ids("a.mkv"))
        with self.assertRaises(KeyboardInterrupt):
            self.run_job()
        self.assertEqual(self.calls[-1], "session_exit")
        self.assertEqual(self.calls.count("session_enter"), 1)
        self.assertNotIn(f"translate:{self.ids('b.mkv')[0]}", self.calls)
        self.assertFalse(self.config.gpu_lock.exists())
        self.assertFalse((self.work_root / artifacts.LOCK).exists())

    def test_table_reaches_the_translate_plan_without_replacing_output(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.name_entries = [GREETING, TOKYO]
        summary = self.run_job()
        self.assertEqual(summary.published, ["a.mkv", "b.mkv"])
        self.assertEqual([table["entries"] for table in self.planned_tables[-2:]], [[GREETING, TOKYO]] * 2)
        for rel in ("a.mkv", "b.mkv"):
            sources = self.published(rel)["sources"]
            self.assertEqual(sources["translate"]["names_sha256"], self.table_sha256(self.table(rel)))
            self.assertEqual(set(sources), {"probe", "vad", "asr", "align", "ja_cues", "names", "translate",
                                            "no_speech", "translate_untranslated_cues"})
            # 表只经翻译注入：发布的译文就是翻译结果，不再做发布期替换、不写替换审计。
            self.assertEqual(self.final(rel).read_text(encoding="utf-8"), MERGED)
            self.assertFalse((self.work_dir(rel) / "names-apply.json").exists())

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
        self.final("a.mkv").unlink()  # 要重做就删掉字幕（ADR-0020）
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

    def test_session_failure_only_fails_files_with_cues(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.empty_cues = {"b.mkv"}
        self.session_error = RuntimeError("Strata did not become ready")
        summary = self.run_job()
        self.assertEqual(summary.failed, {"a.mkv": "names", "c.mkv": "names"})
        self.assertEqual(summary.published, ["b.mkv"])
        self.assertEqual(self.calls, [f"names:{self.ids('b.mkv')[0]}", f"translate:{self.ids('b.mkv')[0]}"])
        self.assertFalse(self.names_snapshots[0]["session"])
        self.assertEqual(self.failure("a.mkv")["stage"], "names")
        self.assertEqual(self.table("b.mkv")["entries"], [])
        self.assertFalse((self.work_dir("a.mkv") / artifacts.NAME_TABLE).exists())

    def test_build_error_fails_that_file_only(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.names_errors = set(self.ids("a.mkv"))
        summary = self.run_job()
        self.assertEqual((summary.failed, summary.published), ({"a.mkv": "names"}, ["b.mkv"]))
        self.assertEqual(self.failure("a.mkv")["error_type"], "NamesError")
        self.assertNotIn(f"translate:{self.ids('a.mkv')[0]}", self.calls)

        self.names_errors.clear()  # 重跑同一命令：只对失败的影片再建表
        self.calls.clear()
        again = self.run_job()
        self.assertEqual((again.published, again.existing), (["a.mkv"], ["b.mkv"]))
        a = self.ids("a.mkv")[0]
        self.assertEqual(self.calls, ["session_enter", f"names:{a}", f"translate:{a}", "session_exit", "merge"])

    def test_terminal_build_failure_publishes_with_empty_table(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.name_entries = [GREETING]
        self.names_status = {self.ids("a.mkv")[0]: "failed"}
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.failed), (["a.mkv", "b.mkv"], {}))
        self.assertEqual((self.table("a.mkv")["build"]["status"], self.table("a.mkv")["entries"]), ("failed", []))
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"), MERGED)
        names_sha = {rel: self.published(rel)["sources"]["translate"]["names_sha256"] for rel in ("a.mkv", "b.mkv")}
        self.assertEqual(names_sha, {rel: self.table_sha256(self.table(rel)) for rel in ("a.mkv", "b.mkv")})
        warnings = [m[2] for m in map(LOG_LINE.match, console.getvalue().splitlines()) if m and m[1] == "WARNING"]
        self.assertEqual(warnings, ["[names] done a.mkv: build failed (fake failed), empty table"])

    def test_broken_table_fails_translate(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        path = self.work_dir("a.mkv") / artifacts.NAME_TABLE
        table = artifacts.read_json(path)
        del table["entries"]  # 用户改坏了表：表身份仍当前，翻译计划取不到 entries 即抛
        artifacts.atomic_write_json(path, table)
        for rel in ("a.mkv", "b.mkv"):
            self.final(rel).unlink()
        summary = self.run_job()
        self.assertEqual((summary.failed, summary.published), ({"a.mkv": "translate"}, ["b.mkv"]))
        self.assertEqual(self.failure("a.mkv")["stage"], "translate")

    def test_zero_cue_document_needs_no_lock_or_session(self) -> None:
        self.make_inputs("a.mkv")
        self.empty_cues = {"a.mkv"}
        self.run_job()
        (self.work_dir("a.mkv") / artifacts.NAME_TABLE).unlink()  # 只剩 names 起要重做：GPU 阶段不再取锁
        self.final("a.mkv").unlink()
        self.calls.clear()
        self.config.gpu_lock.unlink(missing_ok=True)
        summary = self.run_job()  # 零条目：仍走 names（写空表）与翻译，但不起 server、不取锁
        self.assertEqual(summary.published, ["a.mkv"])
        self.assertEqual(self.calls, [f"names:{self.ids('a.mkv')[0]}", f"translate:{self.ids('a.mkv')[0]}"])
        self.assertEqual((self.names_snapshots[-1]["lock"], self.names_snapshots[-1]["session"]), (None, False))
        self.assertIsNone(self.translate_snapshots[-1]["lock"])
        self.assertEqual(self.table("a.mkv")["entries"], [])


JPN_SRT_TRACK = ({"index": 2, "codec_name": "subrip", "language": "jpn", "default": True, "forced": False},)
SRT_EMBEDDED = ("1\n00:00:03,000 --> 00:00:04,000\n<i>字幕の</i>\n台詞\n\n"
                "2\n00:00:05,000 --> 00:00:06,000\n次の台詞\n")
SRT_EMBEDDED_CLEAN = ("1\n00:00:03,000 --> 00:00:04,000\n字幕の 台詞\n\n"
                      "2\n00:00:05,000 --> 00:00:06,000\n次の台詞\n")


class EmbeddedSubtitleTests(JobCase):
    """有可用的内嵌日文文本字幕轨的文件跳过 STT：不提取音频、不起 worker，`ja.srt` 取自字幕轨（ADR-0024）。"""

    def with_track(self, rel: str, text: object = SRT_EMBEDDED) -> None:
        self.subtitles[rel] = JPN_SRT_TRACK
        self.subtitle_text[rel] = text

    def test_embedded_track_skips_extract_and_gpu_stages(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.with_track("a.mkv")
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.embedded, summary.exit_code), (["a.mkv", "b.mkv"], ["a.mkv"], 0))
        self.assertEqual((self.extracted, self.subtitle_extracted), (["b.mkv"], ["a.mkv"]))
        for stage in ("vad", "asr", "align"):  # 只有 b 进 GPU 阶段
            self.assertEqual([launch["ids"] for launch in self.launches(stage)], [self.ids("b.mkv")])
        work = self.work_dir("a.mkv")
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), SRT_EMBEDDED_CLEAN)
        for name in (artifacts.AUDIO_16K, artifacts.VAD, artifacts.ASR, artifacts.ALIGN, artifacts.JA_CUES):
            self.assertFalse((work / name).exists(), name)
        record = artifacts.read_json(work / artifacts.JA_EMBEDDED)
        self.assertEqual((record["stream"], record["source_cues"], record["cues"]), (JPN_SRT_TRACK[0], 2, 2))
        self.assertEqual(record["ja_srt_sha256"], artifacts.sha256_file(work / "ja.srt"))
        self.assertIsNone(artifacts.read_json(work / artifacts.PROBE)["extract"])
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"),
                         "1\n00:00:03,000 --> 00:00:04,000\n你好\n字幕の 台詞\n\n"
                         "2\n00:00:05,000 --> 00:00:06,000\n你好\n次の台詞\n")
        sources = self.published("a.mkv")["sources"]
        self.assertEqual(set(sources), {"probe", "ja_embedded", "names", "translate", "no_speech",
                                        "translate_untranslated_cues"})
        self.assertEqual(sources["ja_embedded"], record["identity"])
        self.assertIn("vad", self.published("b.mkv")["sources"])
        log = console.getvalue()
        self.assertIn("[extract] done a.mkv: embedded subtitle stream 2 (subrip), 2 cue(s), skipping speech recognition",
                      log)
        self.assertIn("[publish] done a.mkv (embedded subtitles)", log)
        self.assertIn("2 published (0 no speech, 1 from embedded subtitles)", log)
        self.assertNotIn("字幕の", log)  # 字幕文字不进日志

    def test_batch_of_embedded_files_takes_the_gpu_lock_only_for_strata(self) -> None:
        self.make_inputs("a.mkv")
        self.with_track("a.mkv")
        self.run_job()
        self.assertEqual(self.launches(), [])
        identifier = self.ids("a.mkv")[0]
        self.assertEqual(self.calls, ["session_enter", f"names:{identifier}", f"translate:{identifier}",
                                      "session_exit", "merge"])
        self.assertEqual(self.names_snapshots[0]["lock"]["pid"], os.getpid())  # 建表需要模型：此时才取 GPU 锁

    def test_switch_off_goes_through_speech_recognition(self) -> None:
        self.make_inputs("a.mkv")
        self.with_track("a.mkv")
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

    def test_rerun_reuses_the_extracted_subtitle(self) -> None:
        self.make_inputs("a.mkv")
        self.with_track("a.mkv")
        self.translate_errors.add(self.ids("a.mkv")[0])
        self.assertEqual(self.run_job().failed, {"a.mkv": "translate"})
        self.translate_errors.clear()
        summary = self.run_job()
        self.assertEqual((summary.published, summary.embedded), (["a.mkv"], ["a.mkv"]))
        self.assertEqual(self.subtitle_extracted, ["a.mkv"])  # 第二次运行按身份跳过抽轨
        (self.work_dir("a.mkv") / "ja.srt").write_text(SRT_JA, encoding="utf-8")  # ja.srt 被别的路径改写：重新抽轨
        self.final("a.mkv").unlink()
        self.run_job()
        self.assertEqual(self.subtitle_extracted, ["a.mkv", "a.mkv"])
        self.assertEqual((self.work_dir("a.mkv") / "ja.srt").read_text(encoding="utf-8"), SRT_EMBEDDED_CLEAN)

    def test_switching_paths_never_reuses_the_other_path_s_ja_srt(self) -> None:
        self.make_inputs("a.mkv")
        stt = replace(self.config, input=replace(self.config.input, use_embedded_subtitles=False))
        self.with_track("a.mkv")
        work = self.work_dir("a.mkv")

        self.run_job(stt)                                   # 先走 STT：ja.srt 来自 cue 阶段
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), SRT_JA)
        self.final("a.mkv").unlink()
        self.run_job()                                      # 改走内嵌字幕：ja.srt 换成字幕轨，ja-cues.json 不再当前
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), SRT_EMBEDDED_CLEAN)
        self.assertNotEqual(artifacts.read_json(work / artifacts.JA_CUES)["ja_srt_sha256"],
                            artifacts.sha256_file(work / "ja.srt"))
        self.assertIn("ja_embedded", self.published("a.mkv")["sources"])
        self.final("a.mkv").unlink()
        launches = len(self.launches())
        self.run_job(stt)                                   # 再回 STT：GPU 产物仍当前，只重做 cue 阶段
        self.assertEqual(len(self.launches()), launches)
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), SRT_JA)
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"), MERGED)
        self.assertIn("ja_cues", self.published("a.mkv")["sources"])


class IdentityTests(JobCase):
    def test_media_hash_change_with_same_pcm_keeps_vad_and_later_stages_current(self) -> None:
        # 票据 03：LAYOUT_BY_CHANNELS 与音轨选择规则进 MEDIA，MEDIA hash 变一次。旧工作目录的 probe.json 不再当前、
        # 重抽一次音频；派生 PCM 不变，vad、asr、align、cues 与专名表仍当前，不起 worker、不重建 cue。
        # batch-run-fixes 02 又出 v2（加 sample_rate_correction）：一并去掉、id 还原，仍得到票据 03 之前的 MEDIA。
        legacy = {key: value for key, value in recipes.MEDIA.items()
                  if key not in ("layout_by_channels", "audio_selection", "sample_rate_correction")}
        legacy["id"] = "media-pcm16k-v1"
        self.assertEqual(recipes.recipe_hash(legacy),  # 改之前的 MEDIA（test_recipes.py 记着同一个值）
                         "58892e0a96afe3a876ba90959ce19ef649d5cd1052910c132bcd92055f971e1e")
        self.make_inputs("a.mkv")
        with mock.patch("kototoki.recipes.MEDIA", legacy):
            self.run_job()
        work = self.work_dir("a.mkv")
        kept = {name: (work / name).read_bytes() for name in (artifacts.VAD, artifacts.ASR, artifacts.ALIGN,
                                                              artifacts.JA_CUES, "ja.srt", artifacts.NAME_TABLE)}
        probe = artifacts.read_json(work / artifacts.PROBE)["identity"]
        launches, names = len(self.launches()), len(self.names_snapshots)
        self.final("a.mkv").unlink()

        summary = self.run_job()
        self.assertEqual(summary.published, ["a.mkv"])
        self.assertEqual(self.extracted, ["a.mkv", "a.mkv"])  # probe.json 不当前：重抽一次
        self.assertNotEqual(artifacts.read_json(work / artifacts.PROBE)["identity"], probe)
        self.assertEqual((len(self.launches()), len(self.names_snapshots)), (launches, names))
        self.assertEqual({name: (work / name).read_bytes() for name in kept}, kept)

    def test_hand_edited_ja_srt_rebuilds_cues(self) -> None:
        self.make_inputs("a.mkv")
        self.run_job()
        work = self.work_dir("a.mkv")
        record = artifacts.read_json(work / artifacts.JA_CUES)
        self.assertEqual(record["ja_srt_sha256"], artifacts.sha256_file(work / "ja.srt"))
        (work / "ja.srt").write_text(SRT_JA.replace("こんにちは", "さようなら"), encoding="utf-8")
        self.final("a.mkv").unlink()
        launches = len(self.launches())
        with mock.patch("kototoki.job.cues.build_cues", side_effect=self._build_cues) as build:
            summary = self.run_job()
        self.assertEqual(summary.published, ["a.mkv"])
        self.assertEqual((build.call_count, len(self.launches())), (1, launches))
        self.assertEqual((work / "ja.srt").read_text(encoding="utf-8"), SRT_JA)
        self.assertEqual(artifacts.read_json(work / artifacts.JA_CUES), record)


class ImportAndDirTests(JobCase):
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

    def test_missing_input_dir_is_a_config_error(self) -> None:
        config = self.with_paths(input_dir=self.root / "missing")
        with self.assertRaisesRegex(ConfigError, "input_dir is not a directory"):
            cli.check_input_dir(config)
        cli.check_input_dir(self.config)
        err = io.StringIO()
        with mock.patch("kototoki.__main__.load", return_value=config), contextlib.redirect_stderr(err):
            self.assertEqual(cli.main([str(self.toml)]), job.EXIT_CONFIG)
        self.assertIn("config error", err.getvalue())
        self.assertFalse(self.work.exists())

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


# 运行日志一行：UTC 墙钟、相对秒、级别、消息。traceback 的续行不匹配。
LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}Z \[ *\d+\.\ds\] (\w+) +(.*)$")
# 伪 worker 前置：先往 stderr 写一行本格式的告警、一行 INFO 和两行非本格式的噪声，再照常跑 fake_worker。
NOISY_WORKER = (
    "import runpy, sys\n"
    "sys.stderr.write('2026-10-18 12:00:00Z [     1.0s] WARNING  [pyannote] fake warning\\n'\n"
    "                 '2026-10-18 12:00:00Z [     1.0s] INFO     [kototoki] fake info\\n'\n"
    "                 'Loading weights: 100%|##########| WARNING ERROR\\n'\n"
    "                 'ERROR: bare line\\n')\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n")


class RunLogTests(JobCase):
    def run_logged(self, config=None, *, raises: type[BaseException] | None = None,
                   **kwargs) -> tuple[list[str], list[str]]:
        """跑一次，返回 (控制台行, 本次运行日志文件行)；`raises` 给出时断言运行以该异常结束。"""
        before = set(self.work_root.glob("run-*.log"))
        # 日志文件名精确到秒：同一用例内第二次运行若落在同一秒会复用文件名，先等到下一秒。
        stamp = lambda: time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        if any(path.name.startswith(f"run-{stamp()}") for path in before):
            current = stamp()
            while stamp() == current:
                time.sleep(0.05)
        console = io.StringIO()
        with self.assertRaises(raises) if raises else contextlib.nullcontext():
            job.run(config or self.config, worker_command=kwargs.pop("worker_command", fake_worker_command),
                    sleep=kwargs.pop("sleep", lambda seconds: None), console=console)
        (path,) = set(self.work_root.glob("run-*[0-9]Z.log")) - before
        data = path.read_bytes()
        self.assertNotIn(b"\r", data)
        return console.getvalue().splitlines(), data.decode("utf-8").splitlines()

    def entries_at(self, lines: list[str], level: str) -> list[str]:
        return [m[2] for m in map(LOG_LINE.match, lines) if m and m[1] == level]

    def test_console_and_file_are_identical_and_formatted(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        console, file = self.run_logged()
        self.assertEqual(console, file)
        self.assertTrue(file)
        for line in file:
            self.assertRegex(line, LOG_LINE)
        self.assertIn("[summary] 2 file(s): 2 published (0 no speech, 0 from embedded subtitles), 0 with subtitles, 0 failed, "
                      "0 unstable, 0 untranslated cue(s)", self.entries_at(file, "INFO"))

    def test_warnings_use_level_not_wording(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")

        def sleep(seconds: float) -> None:
            with (self.input / "b.mkv").open("ab") as stream:
                stream.write(b"more")

        config = replace(self.config, run=replace(self.config.run, stable_check_s=1.0))
        console, file = self.run_logged(config, sleep=sleep)
        self.assertEqual(console, file)
        self.assertEqual(self.entries_at(file, "WARNING"), ["[scan] b.mkv: size still changing, skipped this run"])
        for line in file:
            self.assertNotIn("WARNING", LOG_LINE.match(line)[2])

    def test_extract_logs_start_done_end(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.extract_errors.add("b.mkv")
        _, file = self.run_logged()
        extract = [entry for entry in self.entries_at(file, "INFO") if entry.startswith("[extract]")]
        self.assertEqual(extract[0], "[extract] start: 3 file(s)")
        self.assertEqual(sorted(extract[1:-1]), ["[extract] done a.mkv", "[extract] done c.mkv"])
        self.assertRegex(extract[-1], r"^\[extract\] end: 2 done, 1 failed, \d+\.\ds$")

    def test_media_warnings_are_logged_per_file(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        probe_warning = "No non-commentary audio stream tagged 'jpn'; using the first audio stream (index 1)"
        extract_warning = "Decoded audio is 0.300 s longer than the video"
        self.media_warnings["b.mkv"] = ((probe_warning,), (extract_warning,))
        console, file = self.run_logged()
        self.assertEqual(console, file)
        expected = [f"[extract] b.mkv: {probe_warning}", f"[extract] b.mkv: {extract_warning}"]
        self.assertEqual(self.entries_at(file, "WARNING"), expected)
        record = artifacts.read_json(self.work_dir("b.mkv") / artifacts.PROBE)
        self.assertEqual((record["warnings"], record["extract"]["warnings"]), ([probe_warning], [extract_warning]))

        # 续跑跳过 extract 时告警照样出现：probe 的来自本次 ffprobe，extract 的取自 `probe.json`
        self.media_warnings["b.mkv"] = ((probe_warning,), ())
        for rel in ("a.mkv", "b.mkv"):
            self.final(rel).unlink()
        _, file = self.run_logged()
        self.assertEqual(self.extracted.count("b.mkv"), 1)
        self.assertEqual(self.entries_at(file, "WARNING"), expected)

    def test_compensation_warnings_unit(self) -> None:
        self.assertEqual(job.compensation_warnings({"net_padding_s": 0.05, "swr_reported_discarded_samples": 4000}, 48000), [])
        self.assertEqual(job.compensation_warnings({"net_padding_s": None, "swr_reported_discarded_samples": 4801}, None), [])
        self.assertEqual(job.compensation_warnings({"net_padding_s": 0.25}, 48000),
                         ["Resampler padded 0.250 s net to keep the timeline"])
        self.assertEqual(job.compensation_warnings({"net_padding_s": -2.0, "swr_reported_discarded_samples": 9600}, 48000),
                         ["Resampler dropped 2.000 s net to keep the timeline",
                          "Resampler discarded 9600 input samples (0.200 s)"])

    def test_compensation_over_threshold_is_logged_also_when_extract_is_skipped(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.compensation["b.mkv"] = {"swr_reported_silence_samples": 0, "swr_reported_discarded_samples": 0,
                                      "input_samples": 480000, "net_padding_s": 0.25}
        self.compensation["a.mkv"] = {"net_padding_s": 0.0}
        expected = ["[extract] b.mkv: Resampler padded 0.250 s net to keep the timeline"]
        _, file = self.run_logged()
        self.assertEqual(self.entries_at(file, "WARNING"), expected)
        for rel in ("a.mkv", "b.mkv"):
            self.final(rel).unlink()
        _, file = self.run_logged()  # 续跑跳过 extract：补偿取自 probe.json，告警照样出现
        self.assertEqual(self.extracted.count("b.mkv"), 1)
        self.assertEqual(self.entries_at(file, "WARNING"), expected)

    def test_failure_is_error_with_traceback_in_file(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.extract_errors.add("b.mkv")
        console, file = self.run_logged()
        self.assertEqual(console, file)
        self.assertEqual(self.entries_at(file, "ERROR"), ["[extract] FAILED b.mkv: MediaError"])
        text = "\n".join(file)
        self.assertIn("Traceback (most recent call last):", text)
        self.assertIn("kototoki.media.MediaError: fake extract failure: b.mkv", text)

    def test_handlers_removed_after_each_run(self) -> None:
        root, ours = logging.getLogger(), logging.getLogger("kototoki")
        before = (list(root.handlers), list(ours.handlers), ours.level)
        self.make_inputs("a.mkv")
        self.run_job()
        self.final("a.mkv").unlink()
        self.extract_errors.add("a.mkv")
        self.run_job()
        self.assertEqual((list(root.handlers), list(ours.handlers), ours.level), before)

    def test_third_party_records_are_prefixed(self) -> None:
        self.make_inputs("a.mkv")

        def build_cues(align, options):
            logging.getLogger("transformers.modeling_utils").warning("third-party note")
            logging.getLogger("transformers.modeling_utils").info("below root level, dropped")
            logging.getLogger("kototoki.translate").info("own note")
            return fake_cue_payload(1), SRT_JA

        with mock.patch("kototoki.job.cues.build_cues", side_effect=build_cues):
            _, file = self.run_logged()
        self.assertIn("[transformers] third-party note", self.entries_at(file, "WARNING"))
        self.assertIn("own note", self.entries_at(file, "INFO"))
        self.assertNotIn("below root level", "\n".join(file))

    def test_first_line_is_the_run_header(self) -> None:
        self.make_inputs("a.mkv")
        _, file = self.run_logged()
        self.assertEqual(LOG_LINE.match(file[0])[2],
                         f"[run] start: config={self.config.source} input={self.input} engine={self.config.engine}")
        self.assertIn(f"[lock] GPU acquired: {self.config.gpu_lock}", self.entries_at(file, "INFO"))

    def test_unexpected_exception_is_logged_as_aborted_with_summary(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.extract_errors.add("b.mkv")
        with mock.patch("kototoki.job.run_gpu_stage", side_effect=OSError("disk gone")):
            console, file = self.run_logged(raises=OSError)
        self.assertEqual(console, file)
        self.assertIn("[run] ABORTED: OSError", self.entries_at(file, "ERROR"))
        text = "\n".join(file)
        self.assertIn("OSError: disk gone", text.split("[run] ABORTED: OSError", 1)[1])
        info = self.entries_at(file, "INFO")
        self.assertIn("[summary] 2 file(s): 0 published (0 no speech, 0 from embedded subtitles), 0 with subtitles, "
                      "1 failed, 0 unstable, 0 untranslated cue(s)", info)
        self.assertEqual(info[-1], "[summary] failed at extract: b.mkv")
        self.assertFalse(self.config.gpu_lock.exists())

    def test_keyboard_interrupt_is_aborted_without_traceback(self) -> None:
        self.make_inputs("a.mkv")
        with mock.patch("kototoki.job.run_gpu_stage", side_effect=KeyboardInterrupt):
            _, file = self.run_logged(raises=KeyboardInterrupt)
        self.assertEqual(self.entries_at(file, "ERROR"), ["[run] ABORTED: KeyboardInterrupt"])
        self.assertNotIn("Traceback", "\n".join(file))
        self.assertTrue(LOG_LINE.match(file[-1])[2].startswith("[summary] 1 file(s): 0 published"))

    def test_gpu_lock_conflict_after_extract_closes_the_log(self) -> None:
        self.make_inputs("a.mkv")
        self.config.gpu_lock.write_text(json.dumps({"pid": os.getpid(), "pid_created": None}), encoding="utf-8")
        _, file = self.run_logged(raises=job.GpuLocked)
        messages = [LOG_LINE.match(line)[2] for line in file if LOG_LINE.match(line)]
        self.assertLess(messages.index("[extract] done a.mkv"), messages.index("[run] ABORTED: GpuLocked"))
        self.assertTrue(messages[-1].startswith("[summary] 1 file(s): 0 published"))

    def test_breaking_stale_locks_is_a_warning(self) -> None:
        self.make_inputs("a.mkv")
        for path, record in ((self.work_root / artifacts.LOCK, {"pid": DEAD_PID}),
                             (self.config.gpu_lock, {"pid": DEAD_PID, "worker_stage": "asr", "server_pid": 4242})):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(record), encoding="utf-8")
        _, file = self.run_logged(replace(self.config, break_stale_lock=True))
        self.assertEqual(self.entries_at(file, "WARNING"), [
            f"[lock] replaced stale work directory lock (pid {DEAD_PID})",
            f"[lock] replaced stale GPU lock (pid {DEAD_PID}, worker_stage asr, server_pid 4242)"])

        self.config.gpu_lock.write_bytes(b"")
        self.final("a.mkv").unlink()
        self.translate_done.clear()
        _, file = self.run_logged(replace(self.config, break_stale_lock=True))
        self.assertEqual(self.entries_at(file, "WARNING"), ["[lock] replaced stale GPU lock (no owner pid)"])

    def test_python_warnings_are_captured_during_the_run_only(self) -> None:
        self.make_inputs("a.mkv")
        before = warnings.showwarning

        def build_cues(align, options):
            warnings.warn("third-party deprecation", UserWarning)
            return fake_cue_payload(1), SRT_JA

        with mock.patch("kototoki.job.cues.build_cues", side_effect=build_cues), warnings.catch_warnings():
            warnings.simplefilter("always")
            _, file = self.run_logged()
            self.assertIs(warnings.showwarning, before)
        self.assertTrue(any(entry.startswith("[py] ") and "UserWarning: third-party deprecation" in entry
                            for entry in self.entries_at(file, "WARNING")))

    def test_worker_done_lines_carry_numeric_event_fields(self) -> None:
        self.make_inputs("a.mkv")
        _, file = self.run_logged()
        info = self.entries_at(file, "INFO")
        for stage in ("vad", "asr", "align"):
            self.assertIn(f"[{stage}] done a.mkv: windows=1", info)  # 字符串字段 `stage` 不抄

    def test_worker_reported_failure_is_one_error_line_with_its_type(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.plan({"asr": {"b.mkv": "fail", "c.mkv": "fatal"}})
        _, file = self.run_logged()
        self.assertEqual(self.entries_at(file, "ERROR"),
                         ["[asr] FAILED b.mkv: RuntimeError", "[asr] FAILED c.mkv: FatalWorkerError"])
        self.assertNotIn("Traceback", "\n".join(file))
        self.assertFalse([entry for entry in self.entries_at(file, "INFO")
                          if entry.startswith(("[asr] failed", "[asr] fatal"))])
        warnings = self.entries_at(file, "WARNING")
        self.assertTrue(any(re.fullmatch(r"\[asr\] worker exited with code 2, see run-\d{8}T\d{6}Z-asr\.stderr\.log", w)
                            for w in warnings), warnings)

    def test_crash_exit_code_points_to_the_stderr_file(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.plan({"vad": {"a.mkv": "crash"}})
        _, file = self.run_logged()
        self.assertTrue(any(re.fullmatch(r"\[vad\] worker exited with code 3, see run-\d{8}T\d{6}Z-vad\.stderr\.log", w)
                            for w in self.entries_at(file, "WARNING")))
        self.assertEqual(self.entries_at(file, "ERROR"), ["[vad] FAILED a.mkv: WorkerCrashed: vad worker exited with code 3"])

    def test_startup_failure_is_logged_once(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.plan({"asr": {"a.mkv": "startup"}})
        _, file = self.run_logged()
        self.assertEqual(self.entries_at(file, "ERROR"), ["[asr] worker startup failed: RuntimeError",
                                                          "[asr] FAILED a.mkv: WorkerCrashed: asr worker startup failed: RuntimeError",
                                                          "[asr] FAILED b.mkv: WorkerCrashed: asr worker startup failed: RuntimeError"])
        self.assertNotIn("Traceback", "\n".join(file))

    def test_one_cached_cause_gets_one_traceback(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.enterContext(mock.patch("kototoki.job.gpu.verify_models", side_effect=FileNotFoundError("model missing")))
        _, file = self.run_logged()
        self.assertEqual(self.entries_at(file, "ERROR"), ["[vad] FAILED a.mkv: PlanError",
                                                          "[vad] FAILED b.mkv: PlanError: FileNotFoundError: model missing"])
        self.assertEqual("\n".join(file).count("kototoki.plan.PlanError: FileNotFoundError: model missing"), 1)  # 链式 traceback 只出现一份

    def test_same_kind_of_failure_gets_one_traceback(self) -> None:
        """回归（batch-run-fixes 06.3）：每个文件各抛一个新异常、但阶段、类型与抛出位置相同，只第一次带 traceback，
        其后一行带消息。"""
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.extract_errors.update({"a.mkv", "b.mkv"})
        _, file = self.run_logged()
        self.assertEqual(self.entries_at(file, "ERROR"), ["[extract] FAILED a.mkv: MediaError",
                                                          "[extract] FAILED b.mkv: MediaError: fake extract failure: b.mkv"])
        self.assertEqual("\n".join(file).count("Traceback (most recent call last):"), 1)

    def test_cues_log_start_done_end_with_counts(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")

        def build_cues(align, options):
            pcm = align["identity"]["upstream"][artifacts.AUDIO_16K]
            rel = next(r for r in ("a.mkv", "b.mkv", "c.mkv")
                       if hashlib.sha256(hashlib.sha256(r.encode()).digest()).hexdigest() == pcm)
            if rel == "b.mkv":
                return fake_cue_payload(0, unrendered=7), ""
            if rel == "c.mkv":
                raise ValueError("broken align")
            return fake_cue_payload(3, interpolated=4, fallback=2, fallback_windows=1), SRT_JA

        with mock.patch("kototoki.job.cues.build_cues", side_effect=build_cues):
            _, file = self.run_logged()
        cue_lines = [LOG_LINE.match(line).group(1, 2) for line in file
                     if LOG_LINE.match(line) and LOG_LINE.match(line)[2].startswith("[cues]")]
        self.assertEqual(cue_lines[:4], [
            ("INFO", "[cues] start: 3 file(s)"),
            ("INFO", "[cues] done a.mkv: 3 cue(s), 4 interpolated unit(s), 2 fallback unit(s), 1 fallback window(s), "
                     "0 unrendered char(s)"),
            ("WARNING", "[cues] done b.mkv: 0 cue(s), 0 interpolated unit(s), 0 fallback unit(s), 0 fallback window(s), "
                        "7 unrendered char(s)"),
            ("ERROR", "[cues] FAILED c.mkv: ValueError")])
        self.assertEqual(cue_lines[-1][0], "INFO")
        self.assertRegex(cue_lines[-1][1], r"^\[cues\] end: 2 done, 1 failed, \d+\.\ds$")

    def test_translate_done_line_carries_time_resume_and_untranslated_level(self) -> None:
        self.make_inputs("a.mkv")
        self.untranslated = 2
        _, file = self.run_logged()
        (done,) = [m.group(1, 2) for m in map(LOG_LINE.match, file) if m and m[2].startswith("[translate] done")]
        self.assertEqual(done[0], "WARNING")
        self.assertRegex(done[1], r"^\[translate\] done a\.mkv: 1 cue\(s\), 2 untranslated, \d+\.\ds$")

        self.untranslated = 0
        self.final("a.mkv").unlink()  # run 已完成：只读回译文，不需要模型
        _, file = self.run_logged()
        (done,) = [m.group(1, 2) for m in map(LOG_LINE.match, file) if m and m[2].startswith("[translate] done")]
        self.assertEqual(done[0], "INFO")
        self.assertRegex(done[1], r"^\[translate\] done a\.mkv \(resumed\): 1 cue\(s\), 0 untranslated, \d+\.\ds$")

    def test_names_done_line_shows_the_attempt_only_after_retries(self) -> None:
        self.make_inputs("a.mkv")
        _, file = self.run_logged()
        self.assertIn("[names] done a.mkv: 0 entries (1 dropped), 100 prompt tok, 20 completion tok, 1.5s",
                      self.entries_at(file, "INFO"))
        self.final("a.mkv").unlink()
        self.names_attempts = 3
        (self.work_dir("a.mkv") / artifacts.NAME_TABLE).unlink()
        _, file = self.run_logged()
        self.assertIn("[names] done a.mkv: 0 entries (1 dropped), 100 prompt tok, 20 completion tok, 1.5s, "
                      "attempt 3/5", self.entries_at(file, "INFO"))

    def test_failures_after_strata_became_unavailable_carry_no_traceback(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.session_refused = "another Strata launch is serving"
        _, file = self.run_logged()
        errors = self.entries_at(file, "ERROR")
        self.assertEqual([e for e in errors if "FAILED" in e],
                         ["[names] FAILED a.mkv: StrataRefused"]
                         + [f"[names] FAILED {rel}: StrataRefused: Strata is unavailable for the rest of this batch: "
                            "another Strata launch is serving" for rel in ("b.mkv", "c.mkv")])
        self.assertEqual("\n".join(file).count("Traceback (most recent call last):"), 1)  # 只有触发拒绝的第一部

    def test_plan_line_counts_where_each_file_resumes(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv", "d.mkv")
        self.plan({"asr": {"b.mkv": "crash"}, "vad": {"c.mkv": "empty"}})
        _, file = self.run_logged()
        self.assertIn("[plan] 4 file(s) resume at: vad 4", self.entries_at(file, "INFO"))

        # 续跑：b 从 asr 起；a、d 已发布，扫描即跳过；c 无语音已发布。删掉 a 的字幕与翻译 run 让它从 translate 起
        self.plan({})
        self.final("a.mkv").unlink()
        self.translate_done.clear()
        _, file = self.run_logged()
        self.assertIn("[plan] 2 file(s) resume at: asr 1, translate 1", self.entries_at(file, "INFO"))
        extract = [e for e in self.entries_at(file, "INFO") if e.startswith("[extract] done")]
        self.assertEqual(sorted(extract), ["[extract] done a.mkv (reused)", "[extract] done b.mkv (reused)"])

    def test_plan_line_with_nothing_to_plan(self) -> None:
        _, file = self.run_logged()
        self.assertIn("[plan] 0 file(s) resume at: none", self.entries_at(file, "INFO"))

    def test_non_ascii_percent_file_name_fails_cleanly(self) -> None:
        rel = "日本語 100%.mkv"
        self.make_inputs(rel, "b.mkv")
        self.plan({"asr": {rel: "fail"}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):  # logging 的格式化异常会写到 stderr（"--- Logging error ---"）
            _, file = self.run_logged()
        self.assertEqual(err.getvalue(), "")
        self.assertIn(f"[asr] FAILED {rel}: RuntimeError", self.entries_at(file, "ERROR"))
        self.assertTrue(self.final("b.mkv").is_file())

    def test_transcript_translation_and_name_text_never_reach_logs(self) -> None:
        self.make_inputs("a.mkv")
        self.name_entries = [GREETING, TOKYO]
        _, file = self.run_logged()
        self.assertEqual(self.final("a.mkv").read_text(encoding="utf-8"), MERGED)  # 文本确实走完了整条流水线
        stderr_logs = sorted(self.work_root.glob("run-*-*.stderr.log"))
        self.assertEqual({path.name.rsplit("-", 1)[1] for path in stderr_logs},
                         {"vad.stderr.log", "asr.stderr.log", "align.stderr.log"})
        texts = ["\n".join(file)] + [path.read_text(encoding="utf-8") for path in stderr_logs]
        for secret in ("こんにちは", "你好", "您好", "東京", "东京"):
            for text in texts:
                self.assertNotIn(secret, text)

    def test_scan_counts_add_up_and_stage_end_lines_share_one_shape(self) -> None:
        self.make_inputs("S1/ep.mkv", "S1/ep.mp4", "b.mkv")  # ep.mp4 与 ep.mkv 争用同一份字幕：scan 失败
        self.translate_errors = set(self.ids("b.mkv"))
        _, file = self.run_logged()
        info = self.entries_at(file, "INFO")
        self.assertIn("[scan] 3 file(s): 2 to process, 0 with subtitles, 0 unstable, 1 failed", info)
        ends = {entry.split("]")[0][1:]: entry for entry in info if re.match(r"^\[\w+\] end: ", entry)}
        self.assertEqual(set(ends), {"extract", "vad", "asr", "align", "cues", "names", "translate"})
        for stage, entry in ends.items():
            self.assertRegex(entry, rf"^\[{stage}\] end: \d+ done, \d+ failed, \d+\.\ds$")
        self.assertTrue(ends["translate"].startswith("[translate] end: 1 done, 1 failed, "))
        self.assertIn("[publish] done S1/ep.mkv", info)

    def test_worker_stderr_warnings_are_counted(self) -> None:
        self.make_inputs("a.mkv")

        def command(stage: str, jobs_path: Path) -> list[str]:
            prefix = [sys.executable, "-c", NOISY_WORKER] if stage == "asr" else [sys.executable]
            return prefix + [str(FAKE_WORKER), stage, "--jobs", str(jobs_path)]

        _, file = self.run_logged(worker_command=command)
        warnings = self.entries_at(file, "WARNING")
        self.assertEqual(len(warnings), 1, warnings)
        self.assertRegex(warnings[0], r"^\[asr\] 1 warning/error line\(s\), see run-\d{8}T\d{6}Z-asr\.stderr\.log$")


if __name__ == "__main__":
    unittest.main()
