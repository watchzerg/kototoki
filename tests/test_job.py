"""批次编排器离线测试：媒体、cue 构建、翻译与合并均为假实现，GPU 阶段由 `fake_worker.py` 子进程顶替。"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
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
from tests.fake_worker import FAKE_MODELS

REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_WORKER = Path(__file__).resolve().parent / "fake_worker.py"
SRT_JA = "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n"
SRT_ZH = "1\n00:00:01,000 --> 00:00:02,000\n你好\n"
DEAD_PID = 999999999
FAKE_SERVER_PID = 12345


def fake_worker_command(stage: str, jobs_path: Path) -> list[str]:
    return [sys.executable, str(FAKE_WORKER), stage, "--jobs", str(jobs_path)]


class JobCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.input, self.output = self.root / "in", self.root / "out"
        self.input.mkdir()
        self.toml = self.root / "kototoki.toml"
        self.toml.write_text('[paths]\ninput_dir = "in"\noutput_dir = "out"\n'
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
        self.enterContext(mock.patch("kototoki.job.media.probe", side_effect=self._probe))
        self.enterContext(mock.patch("kototoki.job.media.extract", side_effect=self._extract))
        self.enterContext(mock.patch("kototoki.job.cues.build_cues", return_value=({"cues": []}, SRT_JA)))
        self.enterContext(mock.patch("kototoki.job.gpu.verify_models", return_value=FAKE_MODELS))
        self.enterContext(mock.patch("kototoki.job.contain_children"))  # 不把测试进程放进 Job Object

        # 假翻译与合并模块：orchestrator 通过 importlib 取用。
        self.calls: list[str] = []
        self.translate_snapshots: list[dict] = []
        self.translate_errors: set[str] = set()  # work id
        self.fallback = 0
        case = self

        class Session:
            def __init__(self, config, on_server_pid):
                self.on_server_pid = on_server_pid

            def __enter__(self):
                case.calls.append("session_enter")
                self.on_server_pid(FAKE_SERVER_PID)
                return self

            def __exit__(self, *exc):
                case.calls.append("session_exit")
                return False

        translate = types.ModuleType("kototoki.translate")
        translate.RECIPE_HASH = "a" * 64
        translate.Session = Session
        translate.translate_document = self._translate_document
        merge = types.ModuleType("kototoki.merge")
        merge.merge = self._merge
        self.enterContext(mock.patch.dict(sys.modules, {"kototoki.translate": translate, "kototoki.merge": merge}))

    # --- 假实现 -------------------------------------------------------------------------------

    def _rel(self, path: Path) -> str:
        return Path(path).relative_to(self.input).as_posix()

    def _probe(self, path: Path, config) -> media.Probe:
        self.probed.append(self._rel(path))
        track = media.AudioTrack(index=0, codec_name="aac", channels=2, channel_layout="stereo", sample_rate=48000,
                                 language="jpn", default=True, comment=False, start_time=0.0, duration=10.0)
        return media.Probe(
            ffprobe={"streams": [{"index": 0, "codec_name": "aac"}], "format": {"duration": "10"}},
            audio=track, audio_tracks=(track,), video_duration_s=10.0, video_duration_source="stream.duration",
            container_start_time=0.0, subtitles=(), warnings=())

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
            audio_copy=Path(work_dir) / "audio.m4a", wav=wav, log=Path(work_dir) / artifacts.EXTRACT_LOG,
            sample_rate=16000, samples=len(pcm) // 2, pcm_sha256=hashlib.sha256(pcm).hexdigest(),
            decoded_duration_s=10.0, video_duration_s=10.0, offset_s=0.0, pan="", compensation={}, warnings=())

    def _translate_document(self, document, run_dir, session, config):
        identifier = Path(run_dir).parent.parent.name
        self.calls.append(f"translate:{identifier}")
        gpu_lock = self.config.gpu_lock
        self.translate_snapshots.append({
            "processed": [(e["stage"], e["id"]) for e in self.entries("file")],
            "lock": json.loads(gpu_lock.read_text(encoding="utf-8")) if gpu_lock.is_file() else None,
            "finals": [p for p in self.output.rglob("*.srt") if ".work" not in p.relative_to(self.output).parts]})
        if identifier in self.translate_errors:
            raise RuntimeError("fake translate failure")
        return types.SimpleNamespace(translations={cue.id: "你好" for cue in document.cues},
                                     fallback_count=self.fallback)

    def _merge(self, document, translations) -> str:
        self.calls.append("merge")
        return "\n\n".join(f"{cue.index_text}\n{cue.time_line}\n{translations[cue.id]}\n{cue.text}"
                           for cue in document.cues) + "\n"

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
        return self.output / artifacts.WORK_DIR / artifacts.work_id(rel)

    def final(self, rel: str, kind: str) -> Path:
        return artifacts.final_srt_paths(self.output, rel)[kind]

    @staticmethod
    def ids(*relatives: str) -> list[str]:
        return [artifacts.work_id(rel) for rel in relatives]

    def failure(self, rel: str) -> dict:
        return artifacts.read_json(self.work_dir(rel) / artifacts.FAILURE)


FOUR = ("f1.mkv", "f2.mkv", "f3.mkv", "f4.mkv")


class ScanTests(JobCase):
    def test_scan_filters_sorts_and_mirrors(self) -> None:
        rels = ["b.mkv", "A.MP4", "S1/ep01.mkv"]
        self.make_inputs(*rels, "notes.txt", "S1/readme.md")
        summary = self.run_job()
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.published, ["A.MP4", "S1/ep01.mkv", "b.mkv"])
        self.assertEqual(summary.exit_code, 0)
        self.assertEqual(self.launches("vad")[0]["ids"], self.ids("A.MP4", "S1/ep01.mkv", "b.mkv"))
        for suffix in (".ja.srt", ".zh.srt", ".ja-zh.srt"):
            self.assertTrue((self.output / "S1" / f"ep01{suffix}").is_file(), suffix)
        self.assertTrue((self.output / "A.ja.srt").is_file())
        self.assertEqual(self.final("S1/ep01.mkv", "ja").read_text(encoding="utf-8"), SRT_JA)
        self.assertEqual(self.final("S1/ep01.mkv", "zh").read_text(encoding="utf-8"), SRT_ZH)
        self.assertEqual(self.final("S1/ep01.mkv", "ja-zh").read_text(encoding="utf-8"), "1\n00:00:01,000 --> 00:00:02,000\n你好\nこんにちは\n")
        index = artifacts.read_json(self.output / artifacts.WORK_DIR / artifacts.INDEX)
        self.assertEqual(index, {artifacts.work_id(r): r for r in rels})
        for rel in rels:
            self.assertTrue(self.work_dir(rel).is_dir())

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
        self.assertNotIn(self.ids("b.mkv")[0], artifacts.read_json(self.output / ".work" / "index.json"))

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


class PublishPreconditionTests(JobCase):
    def test_modified_final_is_blocked_before_any_work(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        edited = self.final("a.mkv", "zh")
        edited.write_text("edited by user\n", encoding="utf-8")
        self.probed.clear()
        launches, calls = len(self.launches()), len(self.calls)

        summary = self.run_job()
        self.assertEqual(summary.blocked, ["a.mkv"])
        self.assertEqual(summary.up_to_date, ["b.mkv"])
        self.assertEqual(summary.published, [])
        self.assertEqual(self.probed, ["b.mkv"])
        self.assertEqual((len(self.launches()), len(self.calls)), (launches, calls))
        self.assertEqual(edited.read_text(encoding="utf-8"), "edited by user\n")
        self.assertEqual(summary.exit_code, 0)

    def test_force_republishes_modified_final(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        edited = self.final("a.mkv", "zh")
        edited.write_text("edited by user\n", encoding="utf-8")
        launches = len(self.launches())

        config = replace(self.config, run=replace(self.config.run, force=True))
        summary = self.run_job(config)
        self.assertEqual((summary.published, summary.up_to_date, summary.blocked), (["a.mkv"], ["b.mkv"], []))
        self.assertEqual(edited.read_text(encoding="utf-8"), SRT_ZH)
        self.assertEqual(len(self.launches()), launches)  # 只重做翻译与发布，GPU 阶段产物仍当前

    def test_unchanged_rerun_is_up_to_date(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.run_job()
        self.probed.clear()
        extracted, launches, calls = len(self.extracted), len(self.launches()), len(self.calls)
        self.config.gpu_lock.unlink(missing_ok=True)

        summary = self.run_job()
        self.assertEqual((summary.up_to_date, summary.published, summary.blocked), (["a.mkv", "b.mkv"], [], []))
        self.assertEqual(sorted(self.probed), ["a.mkv", "b.mkv"])  # ffprobe 每次都跑，取视频身份
        self.assertEqual((len(self.extracted), len(self.launches()), len(self.calls)), (extracted, launches, calls))
        self.assertFalse(self.config.gpu_lock.exists())  # 无需 GPU 就不取锁


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
        self.assertEqual(self.calls, ["session_enter", *[f"translate:{i}" for i in ids], "session_exit"] + ["merge"] * 3)
        for snapshot in self.translate_snapshots:  # 翻译开始时 9 个 GPU 步骤已完成、尚无最终文件
            self.assertEqual(len(snapshot["processed"]), 9)
            self.assertEqual(snapshot["finals"], [])

    def test_child_environment(self) -> None:
        self.make_inputs("a.mkv")
        self.run_job()
        cache = str(self.config.paths.output_dir / ".work" / "cache")
        self.assertEqual(len(self.launches()), 3)
        for launch in self.launches():
            self.assertEqual(launch["env"], {"PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "HF_HOME": cache,
                                             "TORCH_HOME": cache})


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
        self.assertFalse(self.final("f2.mkv", "ja").exists())

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

    def test_translate_failure_isolated_to_that_file(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.translate_errors = set(self.ids("a.mkv"))
        summary = self.run_job()
        self.assertEqual(summary.failed, {"a.mkv": "translate"})
        self.assertEqual(summary.published, ["b.mkv"])
        self.assertFalse(self.final("a.mkv", "zh").exists())

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
        self.assertEqual((second.failed, second.published, second.up_to_date), ({}, ["a.mkv"], ["b.mkv"]))
        later = self.launches()[seen:]
        self.assertEqual([(e["stage"], e["ids"]) for e in later], [("align", self.ids("a.mkv"))])
        self.assertFalse((self.work_dir("a.mkv") / artifacts.FAILURE).exists())
        self.assertTrue(self.final("a.mkv", "ja-zh").is_file())


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

    def test_output_dir_lock_conflict(self) -> None:
        self.make_inputs("a.mkv")
        lock = self.output / ".work" / "lock"
        text = self.write_lock(lock, os.getpid())
        with self.assertRaises(job.OutputLocked):
            self.run_job()
        code, err = self.run_main()
        self.assertEqual(code, job.EXIT_OUTPUT_LOCKED)
        self.assertIn("output directory locked", err)
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
        self.assertFalse((self.output / ".work" / "lock").exists())  # 输出目录锁已释放

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

    def test_stale_output_lock_refused_unless_break_requested(self) -> None:
        self.make_inputs("a.mkv")
        self.write_lock(self.output / ".work" / "lock", DEAD_PID)
        with self.assertRaises(job.OutputLocked):
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
            self.assertEqual(lock["output_dir"], str(self.output))
        (snapshot,) = self.translate_snapshots
        self.assertEqual(snapshot["lock"]["server_pid"], FAKE_SERVER_PID)
        self.assertIsNone(snapshot["lock"]["worker_pid"])
        self.assertFalse(self.config.gpu_lock.exists())
        self.assertFalse((self.output / ".work" / "lock").exists())

    def test_main_usage_and_config_errors_exit_2(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cli.main(["a.toml", "b.toml"]), job.EXIT_CONFIG)
            self.assertEqual(cli.main([str(self.root / "missing.toml")]), job.EXIT_CONFIG)


class PublishTests(JobCase):
    def test_three_finals_published_together_with_record(self) -> None:
        self.make_inputs("a.mkv", "b.mkv")
        self.fallback = 1
        console = io.StringIO()
        summary = self.run_job(console=console)
        self.assertEqual((summary.published, summary.fallback_cues), (["a.mkv", "b.mkv"], 2))
        for rel in ("a.mkv", "b.mkv"):
            record = artifacts.read_published(self.work_dir(rel))
            self.assertEqual(set(record["sha256"]), {"ja", "zh", "ja-zh"})
            for kind, path in artifacts.final_srt_paths(self.output, rel).items():
                self.assertEqual(artifacts.sha256_file(path), record["sha256"][kind])
            self.assertEqual(record["sources"]["translate_fallback_cues"], 1)
            self.assertTrue(record["translate_dir"].startswith("translate/srt-"))
            self.assertEqual(list((self.work_dir(rel) / job.PUBLISH_DIR).iterdir()), [])
        self.assertIn("[summary] 2 video(s): 2 published", console.getvalue())

    def test_no_speech_publishes_empty_finals_and_skips_later_stages(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.plan({"vad": {"b.mkv": "empty"}})
        summary = self.run_job()
        self.assertEqual(summary.no_speech, ["b.mkv"])
        self.assertEqual(summary.published, ["a.mkv", "b.mkv", "c.mkv"])
        for stage in ("asr", "align"):
            self.assertEqual(self.launches(stage)[0]["ids"], self.ids("a.mkv", "c.mkv"))
        self.assertNotIn(f"translate:{self.ids('b.mkv')[0]}", self.calls)
        self.assertEqual(len([c for c in self.calls if c.startswith("translate:")]), 2)
        for kind in artifacts.FINAL_SUFFIXES:
            self.assertEqual(self.final("b.mkv", kind).stat().st_size, 0)
        record = artifacts.read_published(self.work_dir("b.mkv"))
        self.assertEqual(set(record["sha256"].values()), {hashlib.sha256(b"").hexdigest()})

        launches = len(self.launches())  # 重跑：无语音文件同样视为已发布
        again = self.run_job()
        self.assertEqual((again.up_to_date, again.published), (["a.mkv", "b.mkv", "c.mkv"], []))
        self.assertEqual(len(self.launches()), launches)


class PlanCallTests(JobCase):
    def test_next_stage_once_per_file_and_advance_once_per_stage_run(self) -> None:
        self.make_inputs("a.mkv", "b.mkv", "c.mkv")
        self.plan({"vad": {"b.mkv": "empty"}})
        with mock.patch.object(job.plan, "next_stage", wraps=job.plan.next_stage) as next_stage,                 mock.patch.object(job.plan, "advance", wraps=job.plan.advance) as advance:
            summary = self.run_job()
            self.assertEqual(len(summary.published), 3)
            self.assertEqual(next_stage.call_count, 3)
            # a、c 各推进 vad／asr／align／cues 四次，b 只推进 vad 一次。
            self.assertEqual(advance.call_count, 4 + 4 + 1)
            self.assertEqual(sorted(call.args[0].stage for call in advance.call_args_list),
                             ["align"] * 2 + ["asr"] * 2 + ["cues"] * 2 + ["vad"] * 3)

            next_stage.reset_mock()
            advance.reset_mock()
            self.config.gpu_lock.unlink(missing_ok=True)
            again = self.run_job()
            self.assertEqual(again.up_to_date, ["a.mkv", "b.mkv", "c.mkv"])
            self.assertEqual((next_stage.call_count, advance.call_count), (3, 0))


class ImportAndOutputDirTests(JobCase):
    def test_job_and_main_import_no_inference_stack(self) -> None:
        code = (
            "import sys, kototoki.job, kototoki.__main__\n"
            "banned = {'torch', 'ctranslate2', 'faster_whisper', 'transformers', 'pyannote', 'torchaudio',\n"
            "          'torchcodec', 'experiments'}\n"
            "bad = sorted(m for m in sys.modules if m.split('.')[0] in banned)\n"
            "print(bad)\n"
            "sys.exit(1 if bad else 0)\n")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def with_output(self, output: Path, input_dir: Path | None = None):
        paths = replace(self.config.paths, output_dir=output, input_dir=input_dir or self.config.paths.input_dir)
        return replace(self.config, paths=paths)

    def test_check_output_dir(self) -> None:
        cli.check_output_dir(self.config)
        cli.check_output_dir(self.with_output(REPO_ROOT / ".local" / "out"))
        for bad in (REPO_ROOT / "out", REPO_ROOT, self.input / "out", self.input):
            with self.subTest(output=bad), self.assertRaises(ConfigError):
                cli.check_output_dir(self.with_output(bad))


if __name__ == "__main__":
    unittest.main()
