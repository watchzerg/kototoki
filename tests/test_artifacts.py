from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from kototoki import artifacts as a

SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
PROBE = {
    "streams": [{"index": 0, "codec_name": "h264", "duration": "10.0", "tags": {"title": "x"}},
                {"index": 1, "codec_name": "aac", "channels": 2, "channel_layout": "stereo",
                 "sample_rate": "48000", "start_time": "0.021", "duration": "10.0", "tags": {"language": "jpn"}}],
    "format": {"filename": "D:/movies/ep01.mkv", "duration": "10.05", "tags": {"encoder": "x"}},
}


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class WorkDirTests(TempCase):
    def test_work_id_is_sha12_of_posix_relative_path_with_extension(self) -> None:
        self.assertEqual(a.work_id("S1/ep01.mkv"), a.sha256_bytes(b"S1/ep01.mkv")[:12])
        self.assertEqual(a.work_id("S1\\ep01.mkv"), a.work_id("S1/ep01.mkv"))
        self.assertNotEqual(a.work_id("S1/ep01.mkv"), a.work_id("S1/ep01.mp4"))

    def test_rejects_paths_outside_input_dir(self) -> None:
        for bad in ("/abs/ep.mkv", "../ep.mkv", "C:/ep.mkv", "C:ep.mkv", "S1/ep.mkv:stream", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                a.work_id(bad)

    def test_register_writes_index_and_is_idempotent(self) -> None:
        first = a.register_work_dir(self.root, "S1/ep01.mkv")
        again = a.register_work_dir(self.root, "S1/ep01.mkv")
        self.assertEqual(first, again)
        self.assertEqual(first, self.root / ".work" / a.work_id("S1/ep01.mkv"))
        self.assertTrue(first.is_dir())
        a.register_work_dir(self.root, "ep02.mkv")
        index = a.read_json(self.root / ".work/index.json")
        self.assertEqual(index, {a.work_id("S1/ep01.mkv"): "S1/ep01.mkv", a.work_id("ep02.mkv"): "ep02.mkv"})

    def test_short_id_collision_is_refused(self) -> None:
        identifier = a.work_id("S1/ep01.mkv")
        a.atomic_write_json(self.root / ".work/index.json", {identifier: "other/file.mkv"})
        with self.assertRaisesRegex(ValueError, "collides"):
            a.register_work_dir(self.root, "S1/ep01.mkv")
        self.assertFalse((self.root / ".work" / identifier).exists())

    def test_final_paths_mirror_input_tree(self) -> None:
        paths = a.final_srt_paths(self.root, "S1/ep01.mkv")
        self.assertEqual(paths, {"ja": self.root / "S1/ep01.ja.srt", "zh": self.root / "S1/ep01.zh.srt",
                                 "ja-zh": self.root / "S1/ep01.ja-zh.srt"})


class IdentityTests(TempCase):
    def video(self) -> Path:
        path = self.root / "in/S1/ep01.mkv"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"video")
        return path

    def test_probe_fingerprint_drops_filename_and_tags(self) -> None:
        fingerprint = a.probe_fingerprint(PROBE)
        self.assertEqual(fingerprint["format_duration"], "10.05")
        self.assertEqual(fingerprint["streams"][1], {
            "index": 1, "codec_name": "aac", "channels": 2, "channel_layout": "stereo",
            "sample_rate": "48000", "start_time": "0.021", "duration": "10.0"})
        self.assertNotIn("D:/movies", json.dumps(fingerprint))
        self.assertNotIn("tags", json.dumps(fingerprint))

    def test_video_identity_ignores_location_and_tracks_size_mtime_probe(self) -> None:
        video = self.video()
        identity = a.video_identity(self.root / "in", "S1/ep01.mkv", PROBE)
        self.assertEqual(identity["relative_path"], "S1/ep01.mkv")
        self.assertNotIn(str(self.root), json.dumps(identity))
        retagged = json.loads(json.dumps(PROBE))
        retagged["format"]["filename"] = "E:/elsewhere.mkv"
        retagged["streams"][1]["tags"] = {}
        self.assertEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", retagged), identity)
        changed = json.loads(json.dumps(PROBE))
        changed["streams"][1]["channels"] = 6
        self.assertNotEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", changed), identity)
        stat = video.stat()
        os.utime(video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        self.assertNotEqual(a.video_identity(self.root / "in", "S1/ep01.mkv", PROBE), identity)

    def test_derived_identity_requires_digests(self) -> None:
        identity = a.derived_identity(upstream={"pcm": SHA_A}, recipe_hash=SHA_B, models={"seg": SHA_C},
                                      config={"seed": 7})
        self.assertEqual(identity, {"upstream": {"pcm": SHA_A}, "recipe_hash": SHA_B,
                                    "models": {"seg": SHA_C}, "config": {"seed": 7}})
        for kwargs in ({"upstream": {}, "recipe_hash": SHA_B},
                       {"upstream": {"pcm": "D:/x/audio-16k.wav"}, "recipe_hash": SHA_B},
                       {"upstream": {"pcm": SHA_A}, "recipe_hash": "v1"},
                       {"upstream": {"pcm": SHA_A}, "recipe_hash": SHA_B, "models": {"seg": "/models/seg.bin"}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                a.derived_identity(**kwargs)


class ArtifactTests(TempCase):
    def identity(self, **changes: object) -> dict:
        base = {"upstream": {"pcm": SHA_A}, "recipe_hash": SHA_B, "models": {}, "config": {}}
        return {**base, **changes}

    def test_is_current_matches_and_invalidates(self) -> None:
        path = self.root / a.VAD
        self.assertFalse(a.is_current(path, self.identity()))
        a.write_artifact(path, self.identity(), {"offset_s": 0, "windows": []})
        self.assertTrue(a.is_current(path, self.identity()))
        for changed in (self.identity(recipe_hash=SHA_C), self.identity(upstream={"pcm": SHA_C}),
                        self.identity(models={"seg": SHA_C}), self.identity(config={"seed": 1})):
            with self.subTest(changed=changed):
                self.assertFalse(a.is_current(path, changed))

    def test_mismatch_is_replaced_in_place(self) -> None:
        path = self.root / a.ASR
        a.write_artifact(path, self.identity(), {"offset_s": 0, "text": "旧"})
        a.write_artifact(path, self.identity(recipe_hash=SHA_C), {"offset_s": 0, "text": "新"})
        self.assertEqual(a.read_json(path)["text"], "新")
        self.assertTrue(a.is_current(path, self.identity(recipe_hash=SHA_C)))
        self.assertEqual([p.name for p in self.root.iterdir()], [a.ASR])

    def test_corrupt_or_foreign_artifact_is_not_current(self) -> None:
        path = self.root / a.ALIGN
        path.write_text("{truncated", encoding="utf-8")
        self.assertFalse(a.is_current(path, self.identity()))
        path.write_text("[]", encoding="utf-8")
        self.assertFalse(a.is_current(path, self.identity()))

    def test_local_time_artifacts_require_offset(self) -> None:
        for name in (a.VAD, a.ASR, a.ALIGN):
            for payload in ({}, {"offset_s": None}, {"offset_s": True}, {"offset_s": float("nan")}):
                with self.subTest(name=name, payload=payload), self.assertRaises(ValueError):
                    a.write_artifact(self.root / name, self.identity(), payload)
        a.write_artifact(self.root / a.JA_CUES, self.identity(), {"cues": []})
        with self.assertRaises(ValueError):
            a.write_artifact(self.root / a.JA_CUES, self.identity(), {"identity": {}})

    def test_failure_lists_existing_stage_artifacts(self) -> None:
        a.write_artifact(self.root / a.VAD, self.identity(), {"offset_s": 0})
        (self.root / a.PROBE).write_text("{}", encoding="utf-8")
        a.write_failure(self.root, "asr", RuntimeError("boom"))
        failure = a.read_json(self.root / a.FAILURE)
        self.assertEqual((failure["stage"], failure["error_type"], failure["message"]), ("asr", "RuntimeError", "boom"))
        self.assertEqual(failure["completed"], [a.PROBE, a.VAD])


class ModelVerificationTests(TempCase):
    def setUp(self) -> None:
        super().setUp()
        self.model = self.root / "model.bin"
        self.model.write_bytes(b"weights")
        self.expected = a.sha256_bytes(b"weights")
        self.cache = self.root / ".work/cache/model-verification.json"
        self.calls = 0

    def hasher(self, path: Path) -> str:
        self.calls += 1
        return a.sha256_file(path)

    def test_cache_hit_skips_hashing(self) -> None:
        first = a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        second = a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        self.assertEqual((first["method"], second["method"]), ("computed", "cached-size-mtime"))
        self.assertEqual(self.calls, 1)
        self.assertEqual(second["sha256"], self.expected)

    def test_size_or_mtime_change_rehashes(self) -> None:
        a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        stat = self.model.stat()
        os.utime(self.model, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        self.assertEqual(a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)["method"], "computed")
        stat = self.model.stat()
        self.model.write_bytes(b"weightz")  # 同大小、改内容，mtime 恢复原值：缓存仍命中（size+mtime 语义）
        os.utime(self.model, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)["method"],
                         "cached-size-mtime")
        self.model.write_bytes(b"weights!")
        os.utime(self.model, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # 只改大小
        with self.assertRaisesRegex(ValueError, "mismatch"):
            a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        self.assertEqual(self.calls, 3)

    def test_cached_digest_must_equal_expected(self) -> None:
        a.verify_model(self.model, self.expected, self.cache, hasher=self.hasher)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            a.verify_model(self.model, SHA_A, self.cache, hasher=self.hasher)
        self.assertEqual(self.calls, 2)

    def test_mismatch_is_not_cached(self) -> None:
        with self.assertRaises(ValueError):
            a.verify_model(self.model, SHA_A, self.cache, hasher=self.hasher)
        self.assertFalse(self.cache.exists())


class PublishTests(TempCase):
    def setUp(self) -> None:
        super().setUp()
        self.work = self.root / ".work/abc"
        self.work.mkdir(parents=True)
        self.finals = a.final_srt_paths(self.root, "ep01.mkv")

    def publish(self, texts: dict[str, str]) -> None:
        self.record(texts, {"ja_cues": SHA_A}, "translate/srt-aaaaaaaaaaaa")
        for kind, text in texts.items():
            a.atomic_write_text(self.finals[kind], text)

    def record(self, texts: dict[str, str], sources: dict | None = None, translate_dir: str = "translate/x") -> None:
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=False), [])
        a.record_published(self.work, self.finals, {k: a.sha256_bytes(v.encode()) for k, v in texts.items()},
                           sources or {}, translate_dir)

    def texts(self, tag: str) -> dict[str, str]:
        return {kind: f"{tag}-{kind}" for kind in a.FINAL_SUFFIXES}

    def test_absent_files_may_be_published(self) -> None:
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=False), [])

    def test_unchanged_files_may_be_replaced(self) -> None:
        self.publish(self.texts("v1"))
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=False), [])
        record = a.read_published(self.work)
        self.assertEqual(record["translate_dir"], "translate/srt-aaaaaaaaaaaa")
        self.assertEqual(record["sources"], {"ja_cues": SHA_A})

    def test_user_modified_file_blocks_without_force(self) -> None:
        self.publish(self.texts("v1"))
        self.finals["zh"].write_text("用户手改", encoding="utf-8")
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=False), ["zh"])

    def test_force_overrides_modified_file(self) -> None:
        self.publish(self.texts("v1"))
        self.finals["ja"].write_text("用户手改", encoding="utf-8")
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=True), [])

    def test_existing_files_without_record_are_treated_as_user_files(self) -> None:
        self.finals["ja-zh"].write_text("外来文件", encoding="utf-8")
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=False), ["ja-zh"])

    def test_crash_between_record_and_move_keeps_old_files_replaceable(self) -> None:
        self.publish(self.texts("v1"))
        self.record(self.texts("v2"))  # 写完记录、尚未移动就崩溃
        self.record(self.texts("v3"))  # 重跑后内容变化，又在移动中途崩溃
        a.atomic_write_text(self.finals["ja"], self.texts("v3")["ja"])
        self.record(self.texts("v4"))
        self.publish(self.texts("v5"))
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=False), [])

    def test_mixed_absent_unchanged_and_modified(self) -> None:
        self.publish(self.texts("v1"))
        self.finals["ja"].unlink()
        self.finals["ja-zh"].write_text("用户手改", encoding="utf-8")
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=False), ["ja-zh"])
        self.assertEqual(a.publish_blockers(self.finals, self.work, force=True), [])

    def test_record_requires_all_three_digests(self) -> None:
        with self.assertRaises(ValueError):
            a.record_published(self.work, self.finals, {"ja": SHA_A, "zh": SHA_A}, {}, "translate/x")


class AtomicWriteTests(TempCase):
    def test_replace_retries_permission_error_then_succeeds(self) -> None:
        calls, sleeps = [], []

        def flaky(source: Path, target: Path) -> None:
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("in use")
            os.replace(source, target)

        source, target = self.root / "s", self.root / "t"
        source.write_text("x", encoding="utf-8")
        a.replace_with_retry(source, target, replace=flaky, sleep=sleeps.append)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [0.1, 0.2])
        self.assertEqual(target.read_text(encoding="utf-8"), "x")

    def test_replace_gives_up_after_limit(self) -> None:
        def locked(source: Path, target: Path) -> None:
            raise PermissionError("in use")

        sleeps: list[float] = []
        with self.assertRaises(PermissionError):
            a.replace_with_retry(self.root / "s", self.root / "t", replace=locked, sleep=sleeps.append)
        self.assertEqual(len(sleeps), a.REPLACE_ATTEMPTS - 1)
        self.assertLessEqual(max(sleeps), 0.5)

    def test_failed_write_leaves_target_and_no_temp_file(self) -> None:
        target = self.root / "out.json"
        a.atomic_write_json(target, {"v": 1})
        with mock.patch.object(a, "replace_with_retry", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                a.atomic_write_json(target, {"v": 2})
        self.assertEqual(a.read_json(target), {"v": 1})
        self.assertEqual([p.name for p in self.root.iterdir()], ["out.json"])

    def test_text_is_utf8_without_bom_and_lf(self) -> None:
        target = self.root / "x.txt"
        a.atomic_write_text(target, "日本語\n中文\n")
        self.assertEqual(target.read_bytes(), "日本語\n中文\n".encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
